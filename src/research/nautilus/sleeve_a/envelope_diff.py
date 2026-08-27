"""
B-S1 envelope diff tool (Minimax-B, 2026-07-21)
==============================================================================
Diff a Nautilus-side envelope CSV (3 variants × 7 folds = 21 cells) against
the freqtrade-side envelope CSV that Minimax-C already computed. Applies the
(a)+(b)+(c) parity gates per cell with the relative-tolerance thresholds from
`c_s5_b_s1_parity_metrics_envelope_summary.json`:

    gate (a): |n_FT − n_N| == 0                    [exact match]
    gate (b): |exp_FT − exp_N| / |exp_FT| ≤ 0.10    [10% relative]
    gate (c): |loss_FT − loss_N| / |loss_FT| ≤ 0.20 [20% relative]

Pipeline:
    1. Read freqtrade envelope CSV (input, fixed path on Mac side).
    2. Read Nautilus envelope CSV (input, Mac-side runner emits at the path
       given on CLI; same 21-row shape).
    3. Apply gates per (variant, fold) cell.
    4. Emit per-cell verdict + 21-cell aggregate + JSON + CSV + Markdown.
    5. Apply implicit-PASS mapping (A2≡A5, A3 lev, A7/A8 notional-only) —
       surface in the report so a reader can see the envelope trick holds
       once the load-bearing axes are verified.

A pure-Python module — does NOT import nautilus_trader. Runs in any sandbox
(or even the Mac side). Once Mac-side Nautilus runs land and emit the
Nautilus-side CSV at a known path, this tool flips the 21 cells from
MISSING_NAUTILUS → PASS/FAIL.

Public surface:
    diff_envelope(nautilus_csv, out_dir=None, freqtrade_csv=None) -> dict
        Top-level entrypoint. Returns a serialisable verdict dict.

    EnvelopeCell — dataclass per (variant, fold).
    EnvelopeReport — dataclass aggregate (21 cells + verdict).

Schemas:
    Freqtrade CSV (input, read-only): ../../_data/research/c_s5_b_s1_parity_metrics_envelope.csv
    Nautilus CSV (input, Mac-emit):    {variant, fold, label, oos_window,
                                         n_trades, expectancy, max_loss}
                                       (subset of freqtrade cols suffices)
"""

from __future__ import annotations

import csv
import json
import logging
import sys
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from typing import Optional


logger = logging.getLogger(__name__)


# ── Defaults ─────────────────────────────────────────────────────────────────

# Freqtrade envelope CSV (Minimax-C emitted 2026-07-20 14:36 UTC).
# Path root from src.research.paths.MAC_DATA (env-overridable via COMETCLOUD_MAC_DATA).
from src.research.paths import MAC_DATA
FREQTRADE_ENVELOPE_CSV = (
    MAC_DATA / "research" / "c_s5_b_s1_parity_metrics_envelope.csv"
)

# Gate tolerances (sourced from the envelope summary JSON at the same path).
N_TRADES_TOL = 0                 # exact match
EXPECTANCY_REL_TOL = 0.10        # 10 %
MAX_LOSS_REL_TOL = 0.20          # 20 %

# Implicit-PASS layer (B-S1 envelope algebraic shortcut, per MINIMAX_SYNC §B-S1
# envelope handoff):
#   PASS(A1+A4+A6) ⇒ PASS(A2≡A5) ∧ PASS(A3 2× interp) ∧ PASS(A7/A8 notional)
IMPLICIT_PASS_MAP = {
    "A2_NO_LEVERAGE_1X":         "A5_CAUSE_BREAK_MVRV_1_05",   # A5 = A2 + cause_break exit (eclipsed by signal exit per C-S3 :5508-5557)
    "A3_2X_LEVERAGE":            "A1_A4_INTERPOLATION",       # 2× is mechanical interp between A2 1× and A1 3×
    "A7_POSITION_CAP_5PCT":      "A7_A8_NOTIONAL_ONLY",       # position caps scale notional; pct-based metrics unchanged
    "A8_DOCTRINE_COMBO":         "A7_A8_NOTIONAL_ONLY",
}


# ── Dataclasses ──────────────────────────────────────────────────────────────

@dataclass
class EnvelopeCell:
    """One (variant, fold) cell with both engines' metrics + per-gate verdicts."""
    variant: str
    fold: int
    label: str
    oos_window: str
    fq_n_trades: int
    fq_expectancy: float
    fq_max_loss: float
    # Nautilus columns are Optional because the Mac-side runner may not have
    # emitted a CSV yet — cells default to MISSING_NAUTILUS in that case.
    naut_n_trades: Optional[int] = None
    naut_expectancy: Optional[float] = None
    naut_max_loss: Optional[float] = None
    # Gate verdicts (None = not computed because Nautilus side missing)
    gate_a_pass: Optional[bool] = None      # exact n_trades match
    gate_b_pass: Optional[bool] = None      # expectancy within 10 % relative
    gate_c_pass: Optional[bool] = None      # max_loss within 20 % relative
    # Aggregate verdict for the cell:
    #   PASS      — all 3 gates PASS
    #   WARN      — any gate in 2× tolerance band (not applied in this tool, see note)
    #   FAIL      — at least one gate FAIL
    #   MISSING   — Nautilus side has no row for this cell
    cell_verdict: str = ""

    @property
    def cell_pass(self) -> bool:
        return self.cell_verdict == "PASS"

    @property
    def cell_fail(self) -> bool:
        return self.cell_verdict == "FAIL"

    @property
    def cell_missing(self) -> bool:
        return self.cell_verdict == "MISSING_NAUTILUS"


@dataclass
class EnvelopeReport:
    freqtrade_csv: str
    nautilus_csv: str
    n_cells_total: int = 0
    n_cells_pass: int = 0
    n_cells_fail: int = 0
    n_cells_missing: int = 0
    n_implicit_pass: int = 0           # cells covered by the A2≡A5/A3/A7/A8 trick
    overall_verdict: str = ""
    by_cell: list[EnvelopeCell] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


# ── Gate math ────────────────────────────────────────────────────────────────

def _gate_exact(a: Optional[float], b: Optional[float]) -> Optional[bool]:
    """Gate (a) — exact match on n_trades.  None if either side missing."""
    if a is None or b is None:
        return None
    return abs(int(a) - int(b)) <= N_TRADES_TOL


def _gate_relative(a: Optional[float], b: Optional[float], rel: float) -> Optional[bool]:
    """Relative-tolerance gate.  None if either side missing.  Special cases:
       - If freqtrade (a) is 0: only PASS if Nautilus (b) is also 0; if b != 0
         the relative diff is undefined → FAIL (consistent with "100% off").
       - If a != 0 but b == 0: relative diff is 100% → FAIL.
    """
    if a is None or b is None:
        return None
    a, b = float(a), float(b)
    if abs(a) < 1e-9:                            # a == 0
        return abs(b) < 1e-9
    return abs(a - b) / abs(a) <= rel


# ── CSV loaders ──────────────────────────────────────────────────────────────

def _load_freqtrade_envelope(csv_path: Path) -> dict[tuple[str, int], dict]:
    """Returns {(variant, fold): row} from the freqtrade envelope CSV."""
    rows: dict[tuple[str, int], dict] = {}
    with csv_path.open() as fp:
        reader = csv.DictReader(fp)
        for row in reader:
            key = (row["variant"].strip(), int(row["fold"]))
            rows[key] = {
                "variant": row["variant"].strip(),
                "fold": int(row["fold"]),
                "label": row.get("label", "").strip(),
                "oos_window": row.get("oos_window", "").strip(),
                "n_trades": int(float(row["n_trades_oos"])),
                "expectancy": float(row["expectancy_oos"]),
                "max_loss": float(row["max_single_loss_oos"]),
            }
    return rows


def _load_nautilus_envelope(csv_path: Path) -> dict[tuple[str, int], dict]:
    """Returns {(variant, fold): row} from the Nautilus-side envelope CSV.

    The Nautilus runner is expected to emit a CSV with the same
    `(variant, fold, n_trades, expectancy, max_loss)` schema (subset of the
    freqtrade CSV columns).  `label` and `oos_window` are optional — they're
    copied through from freqtrade side regardless.
    """
    rows: dict[tuple[str, int], dict] = {}
    if not csv_path.exists():
        return rows
    with csv_path.open() as fp:
        reader = csv.DictReader(fp)
        for row in reader:
            variant = row.get("variant", "").strip()
            if not variant:
                continue
            fold = int(row["fold"])
            # Tolerate either `n_trades` (Nautilus runner convention) or
            # `n_trades_oos` (freqtrade convention) for robustness.
            n_trades_raw = row.get("n_trades") or row.get("n_trades_oos") or "0"
            exp_raw = row.get("expectancy") or row.get("expectancy_oos") or "nan"
            loss_raw = row.get("max_loss") or row.get("max_single_loss_oos") or "nan"
            try:
                rows[(variant, fold)] = {
                    "variant": variant,
                    "fold": fold,
                    "n_trades": int(float(n_trades_raw)),
                    "expectancy": float(exp_raw),
                    "max_loss": float(loss_raw),
                }
            except (ValueError, TypeError) as exc:
                logger.debug(f"  skipping bad Nautilus row {variant} fold={fold}: {exc}")
                continue
    return rows


# ── Verdict assembly ─────────────────────────────────────────────────────────

def _classify_cell(cell: EnvelopeCell) -> str:
    """Reduce 3 gate booleans to a single cell verdict."""
    if cell.gate_a_pass is None:                       # Nautilus missing
        return "MISSING_NAUTILUS"
    if cell.gate_a_pass and cell.gate_b_pass and cell.gate_c_pass:
        return "PASS"
    return "FAIL"


def _apply_implicit_pass_layer(by_variant_fold: dict[str, dict[int, EnvelopeCell]]) -> dict[str, int]:
    """Returns count of cells covered by the implicit-PASS layer (A2/A3/A5/A7/A8).

    These are NOT computed here because B-S1 envelope only runs A1+A4+A6.  The
    layer is documented in MINIMAX_SYNC.md §B-S1 envelope handoff; we just
    surface the count so the report notes which cells *would* be implicitly
    PASS if the envelope holds.  Always returns 0 unless the envelope has
    extended to the full-8 matrix in a future iteration.
    """
    # Currently no cells are implicit; reserved for the full-8 extension.
    return {}


def diff_envelope(
    nautilus_csv: Path,
    out_dir: Optional[Path] = None,
    freqtrade_csv: Optional[Path] = None,
) -> dict:
    """Top-level diff.  Reads both CSVs, applies the 3 gates per cell, emits
    a report dict (also writes JSON + CSV + Markdown if out_dir is given)."""
    freqtrade_csv = Path(freqtrade_csv) if freqtrade_csv else FREQTRADE_ENVELOPE_CSV
    nautilus_csv = Path(nautilus_csv)
    out_dir = Path(out_dir) if out_dir else Path("reports/sleeve_a_envelope_diff")
    out_dir.mkdir(parents=True, exist_ok=True)

    if not freqtrade_csv.exists():
        raise FileNotFoundError(f"freqtrade envelope CSV not found: {freqtrade_csv}")
    fq = _load_freqtrade_envelope(freqtrade_csv)
    naut = _load_nautilus_envelope(nautilus_csv) if nautilus_csv.exists() else {}

    report = EnvelopeReport(
        freqtrade_csv=str(freqtrade_csv),
        nautilus_csv=str(nautilus_csv) if nautilus_csv.exists() else f"<not yet: {nautilus_csv}>",
    )

    # ── Iterate over the 21 freqtrade cells (3 variants × 7 folds) ─────
    by_variant_fold: dict[str, dict[int, EnvelopeCell]] = {}
    for (variant, fold), fq_row in sorted(fq.items()):
        naut_row = naut.get((variant, fold), {})
        cell = EnvelopeCell(
            variant=variant,
            fold=fold,
            label=fq_row.get("label", ""),
            oos_window=fq_row.get("oos_window", ""),
            fq_n_trades=fq_row["n_trades"],
            fq_expectancy=fq_row["expectancy"],
            fq_max_loss=fq_row["max_loss"],
            naut_n_trades=naut_row.get("n_trades"),
            naut_expectancy=naut_row.get("expectancy"),
            naut_max_loss=naut_row.get("max_loss"),
        )
        cell.gate_a_pass = _gate_exact(cell.fq_n_trades, cell.naut_n_trades)
        cell.gate_b_pass = _gate_relative(cell.fq_expectancy, cell.naut_expectancy,
                                          EXPECTANCY_REL_TOL)
        cell.gate_c_pass = _gate_relative(cell.fq_max_loss, cell.naut_max_loss,
                                          MAX_LOSS_REL_TOL)
        cell.cell_verdict = _classify_cell(cell)
        report.by_cell.append(cell)
        by_variant_fold.setdefault(variant, {})[fold] = cell

    # ── Aggregate counts ────────────────────────────────────────────────
    report.n_cells_total = len(report.by_cell)
    report.n_cells_pass = sum(1 for c in report.by_cell if c.cell_pass)
    report.n_cells_fail = sum(1 for c in report.by_cell if c.cell_fail)
    report.n_cells_missing = sum(1 for c in report.by_cell if c.cell_missing)
    implicit = _apply_implicit_pass_layer(by_variant_fold)
    report.n_implicit_pass = sum(implicit.values()) if implicit else 0

    if report.n_cells_missing == report.n_cells_total:
        overall = "🔴 BLOCKED — Nautilus side has 0 cells (Mac run pending)"
    elif report.n_cells_fail == 0 and report.n_cells_missing == 0:
        overall = (f"✅ PARITY PASS — all {report.n_cells_pass}/{report.n_cells_total} cells clear "
                   f"(a)+(b)+(c); A2≡A5, A3, A7/A8 implicit-PASS")
    else:
        overall = (f"🔴 PARITY FAIL — {report.n_cells_fail}/{report.n_cells_total} cells fail "
                   f"(a)+(b)+(c); see per-cell verdict table")
    report.overall_verdict = overall
    report.notes = [
        f"Gates: (a) |n_FT − n_N| == 0 ;  (b) |exp_FT − exp_N|/|exp_FT| ≤ {EXPECTANCY_REL_TOL:.0%} ;  "
        f"(c) |loss_FT − loss_N|/|loss_FT| ≤ {MAX_LOSS_REL_TOL:.0%}",
        f"Implicit-PASS coverage: A1+A4+A6 envelopes 3/8 variants directly; "
        f"A2≡A5 (same trade list per C-S3 cause-break-eclipse) + A3 (2× lev interp) "
        f"+ A7/A8 (notional-only caps) are implied PASS — full-8 is the algebra.",
        f"freqtrade CSV: {freqtrade_csv}",
        f"Nautilus CSV:  {nautilus_csv}",
    ]

    # ── Write outputs ───────────────────────────────────────────────────
    report_dict = report.to_dict()
    (out_dir / "envelope_diff.json").write_text(json.dumps(report_dict, indent=2, default=str))

    # CSV (one row per cell)
    csv_path = out_dir / "envelope_diff.csv"
    if report.by_cell:
        keys = list(asdict(report.by_cell[0]).keys())
        with csv_path.open("w", newline="") as fp:
            w = csv.DictWriter(fp, fieldnames=keys)
            w.writeheader()
            for c in report.by_cell:
                w.writerow(asdict(c))

    (out_dir / "envelope_diff.md").write_text(_render_markdown(report))
    logger.info(f"envelope diff → {out_dir}/")
    logger.info(f"  overall: {overall}")
    return report_dict


# ── Markdown ─────────────────────────────────────────────────────────────────

def _render_markdown(report: EnvelopeReport) -> str:
    L = [
        "# B-S1 envelope parity verdict",
        "",
        f"- Freqtrade CSV: `{report.freqtrade_csv}`",
        f"- Nautilus CSV:  `{report.nautilus_csv}`",
        "",
        f"## Overall verdict",
        "",
        f"**{report.overall_verdict}**",
        "",
        f"- cells total: {report.n_cells_total}",
        f"- PASS: {report.n_cells_pass}",
        f"- FAIL: {report.n_cells_fail}",
        f"- MISSING_NAUTILUS: {report.n_cells_missing}",
        f"- implicit-PASS (A2/A3/A5/A7/A8): {report.n_implicit_pass}",
        "",
        "## Per-cell verdict",
        "",
        "| variant | fold | label | fq n | naut n | (a) | fq exp | naut exp | (b) | fq loss | naut loss | (c) | verdict |",
        "|---|---|---|--:|--:|:-:|--:|--:|:-:|--:|--:|:-:|:-:|",
    ]
    for c in report.by_cell:
        a = "✓" if c.gate_a_pass else ("✗" if c.gate_a_pass is False else "—")
        b = "✓" if c.gate_b_pass else ("✗" if c.gate_b_pass is False else "—")
        d = "✓" if c.gate_c_pass else ("✗" if c.gate_c_pass is False else "—")
        vn = c.naut_n_trades if c.naut_n_trades is not None else "—"
        ve = f"{c.naut_expectancy:+.2f}" if c.naut_expectancy is not None else "—"
        vl = f"{c.naut_max_loss:+.2f}" if c.naut_max_loss is not None else "—"
        L.append(
            f"| {c.variant} | {c.fold} | {c.label[:30]} | "
            f"{c.fq_n_trades} | {vn} | {a} | "
            f"{c.fq_expectancy:+.2f} | {ve} | {b} | "
            f"{c.fq_max_loss:+.2f} | {vl} | {d} | "
            f"**{c.cell_verdict}** |"
        )
    L.append("")
    L.append("## Notes")
    L.append("")
    for n in report.notes:
        L.append(f"- {n}")
    return "\n".join(L) + "\n"


# ── CLI smoke ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    if len(sys.argv) < 2:
        print("usage: python envelope_diff.py <nautilus_envelope_csv> "
              "[freqtrade_envelope_csv] [out_dir]")
        sys.exit(1)
    naut_csv = Path(sys.argv[1])
    fq_csv = Path(sys.argv[2]) if len(sys.argv) > 2 else FREQTRADE_ENVELOPE_CSV
    out_dir = Path(sys.argv[3]) if len(sys.argv) > 3 else Path(
        f"reports/sleeve_a_envelope_diff/{naut_csv.stem}"
    )
    rep = diff_envelope(naut_csv, out_dir=out_dir, freqtrade_csv=fq_csv)
    print(json.dumps(rep["overall_verdict"], indent=2))
    print(f"\nPer-cell: {rep['n_cells_pass']} PASS, "
          f"{rep['n_cells_fail']} FAIL, "
          f"{rep['n_cells_missing']} MISSING_NAUTILUS")
    print(f"Report → {out_dir}/envelope_diff.{{json,csv,md}}")
