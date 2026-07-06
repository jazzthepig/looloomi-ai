"""
Parity diff: Nautilus LS v1 vs freqtrade LS V4 (Minimax-B, 2026-07-04)
======================================================================

Reads the structured JSON output from `runner.run_parity()` and a freqtrade
LS V4 baseline (JSON or CSV), produces a side-by-side diff.

Per the handoff "4 open items" status, this is open item 3: the actual
comparison framework.  Matplotlib equity-curve plot is a separate script
(`scripts/plot_ls_v1_parity.py`, not in this skeleton).

Public surface:
    diff_runs(nautilus_dir, freqtrade_path, out_dir=None) -> dict
        Top-level: produce a parity report dict + write to out_dir.

    ParityReport — typed dataclass with the comparison fields.

Expected gap (per Shadow's earlier note):
    Nautilus LS v1 with all gates ON should produce FEWER trades than
    freqtrade LS V4 (CIS gate + ADX gate filter more aggressively).  With
    gates OFF, Nautilus produces MORE trades.  The diff surfaces both
    the magnitude and the direction so reviewers can sanity-check.

The freqtrade baseline format is intentionally permissive — accept JSON
keys like `n_trades`, `total_trades`, `trades_count` (the freqtrade
strategy output reports trades under several names depending on version).
"""

from __future__ import annotations

import csv
import json
import logging
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from typing import Optional


logger = logging.getLogger(__name__)


# ── Freqtrade baseline discovery ─────────────────────────────────────────────

# Default locations for the freqtrade LS V4 baseline
DEFAULT_FREQTRADE_PATHS = [
    Path("/Volumes/CometCloudAI/cometcloud-local/_reports/backtest/ls_v4_latest.json"),
    Path("/Volumes/CometCloudAI/cometcloud-local/_reports/backtest/CometCloudLongShortV4_latest.json"),
    Path("/Volumes/CometCloudAI/cometcloud-local/_reports/backtest/ls_v4_latest.csv"),
    Path("/Volumes/CometCloudAI/cometcloud-local/_reports/backtest/CometCloudLongShortV4_latest.csv"),
]


def _load_freqtrade_baseline(path: Optional[Path]) -> dict:
    """Load freqtrade LS V4 baseline.  Tries defaults if path is None.

    Returns a dict shaped like:
        {instrument_str: {n_trades, n_long, n_short, pnl_usd, ...}, ...}
    """
    if path is None:
        for candidate in DEFAULT_FREQTRADE_PATHS:
            if candidate.exists():
                path = candidate
                break
    if path is None or not path.exists():
        logger.warning(
            "No freqtrade LS V4 baseline found in defaults; "
            "pass freqtrade_path explicitly.  Expected keys: "
            f"{[str(p) for p in DEFAULT_FREQTRADE_PATHS]}"
        )
        return {}

    if path.suffix == ".json":
        return json.loads(path.read_text())
    if path.suffix == ".csv":
        with path.open() as fp:
            reader = csv.DictReader(fp)
            return {row.pop("instrument", row.get("pair", "")): row for row in reader}
    raise ValueError(f"unsupported freqtrade baseline format: {path.suffix}")


def _extract_freqtrade_metric(row: dict, *keys: str):
    """Try multiple key names (freqtrade versions vary)."""
    for k in keys:
        if k in row and row[k] not in (None, "", "nan"):
            try:
                return float(row[k])
            except (TypeError, ValueError):
                return row[k]
    return None


def _normalise_instrument_key(key: str) -> str:
    """Normalize instrument key for cross-engine matching.

    Nautilus:    "BTCUSDT-PERP.BINANCE"  (canonical from InstrumentId)
    Freqtrade:   "BTC/USDT:USDT"  (freqtrade futures pair format) OR
                 "BTCUSDT"  (sometimes) OR
                 "BTC/USDT"  (spot)

    → collapse all to the underlying symbol stem so we can match across
      engine conventions.  Strip trailing quote currency (USDT/USDC/USD/BUSD)
      and any "-PERP" / ".VENUE" / "_PERP" suffix.
    """
    if not key:
        return ""
    s = str(key).strip().upper()
    # Take stem before any pair separator (freqtrade uses / or :)
    for sep in ("/", ":"):
        if sep in s:
            s = s.split(sep, 1)[0]
            break
    # Strip venue suffix (Nautilus: ".BINANCE")
    if "." in s:
        s = s.split(".", 1)[0]
    # Strip perpetual suffix
    for suf in ("-PERP", "_PERP"):
        if s.endswith(suf):
            s = s[: -len(suf)]
    # Strip trailing quote currency (USDT/USDC/USD/BUSD) so Nautilus
    # "BTCUSDT" and freqtrade "BTC/USDT" both collapse to "BTC".
    for qc in ("USDT", "USDC", "BUSD", "USD"):
        if s.endswith(qc) and len(s) > len(qc):
            s = s[: -len(qc)]
            break  # only strip one (e.g. "BTCUSDCUSDT" doesn't happen)
    return s


def _find_freqtrade_row(freqtrade: dict, nautilus_key: str) -> dict:
    """Find the freqtrade row matching a Nautilus instrument id.

    freqtrade baseline keys may be `BTC/USDT:USDT`, `BTCUSDT`, `BTC/USDT`,
    or anything else — we normalise both sides and match on the stem.
    """
    if not isinstance(freqtrade, dict):
        return {}
    target = _normalise_instrument_key(nautilus_key)
    if not target:
        return {}
    # Exact match first
    if nautilus_key in freqtrade:
        return freqtrade[nautilus_key]
    # Normalised match
    for k, v in freqtrade.items():
        if _normalise_instrument_key(k) == target:
            return v
    return {}


# ── Parity report ────────────────────────────────────────────────────────────

@dataclass
class ParityRow:
    instrument: str
    nautilus_n_orders: int = 0
    nautilus_n_positions: int = 0
    nautilus_n_long: int = 0
    nautilus_n_short: int = 0
    nautilus_pnl_usd: float = 0.0
    freqtrade_n_trades: Optional[int] = None
    freqtrade_n_long: Optional[int] = None
    freqtrade_n_short: Optional[int] = None
    freqtrade_pnl_usd: Optional[float] = None
    n_trades_diff: Optional[int] = None
    pnl_diff_usd: Optional[float] = None
    direction_bias: str = ""  # "nautilus_more" | "freqtrade_more" | "tie"


@dataclass
class ParityReport:
    nautilus_run_dir: str
    freqtrade_baseline_path: str
    n_instruments: int = 0
    nautilus_total_orders: int = 0
    nautilus_total_positions: int = 0
    nautilus_total_pnl_usd: float = 0.0
    freqtrade_total_trades: Optional[int] = None
    freqtrade_total_pnl_usd: Optional[float] = None
    by_instrument: list[ParityRow] = field(default_factory=list)
    skip_summaries: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


# ── diff_runs ────────────────────────────────────────────────────────────────

def diff_runs(
    nautilus_dir: Path,
    freqtrade_path: Optional[Path] = None,
    out_dir: Optional[Path] = None,
) -> dict:
    """Produce a parity report comparing Nautilus LS v1 (in `nautilus_dir`)
    to a freqtrade LS V4 baseline (at `freqtrade_path` or auto-discovered).
    """
    nautilus_dir = Path(nautilus_dir)
    out_dir = Path(out_dir) if out_dir else nautilus_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    # Read Nautilus per_instrument.json
    per_inst_path = nautilus_dir / "per_instrument.json"
    if not per_inst_path.exists():
        raise FileNotFoundError(
            f"Nautilus per_instrument.json not found in {nautilus_dir}. "
            f"Run `python -m src.research.nautilus.ls_v1.runner` first."
        )
    nautilus_rows = json.loads(per_inst_path.read_text())

    # Read Nautilus summary.json (totals)
    summary_path = nautilus_dir / "summary.json"
    nautilus_summary = (
        json.loads(summary_path.read_text()) if summary_path.exists() else {}
    )

    # Read Nautilus skip_summary.json (strategy-level diagnostics)
    skip_path = nautilus_dir / "skip_summary.json"
    skip_summaries = (
        json.loads(skip_path.read_text()) if skip_path.exists() else {}
    )

    # Read freqtrade baseline
    freqtrade = _load_freqtrade_baseline(freqtrade_path)
    freqtrade_path_str = str(freqtrade_path) if freqtrade_path else "auto-discover"

    # Build ParityReport
    report = ParityReport(
        nautilus_run_dir=str(nautilus_dir),
        freqtrade_baseline_path=freqtrade_path_str,
        n_instruments=len(nautilus_rows),
        nautilus_total_orders=nautilus_summary.get("n_orders_total", 0),
        nautilus_total_positions=nautilus_summary.get("n_positions_total", 0),
        nautilus_total_pnl_usd=nautilus_summary.get("pnl_usd_total", 0.0),
        skip_summaries=skip_summaries,
    )

    if not freqtrade:
        report.notes.append(
            "freqtrade LS V4 baseline not found — diff is one-sided "
            "(Nautilus only).  Re-run with freqtrade_path=<.json|.csv> "
            "once the baseline is exported from freqtrade."
        )

    freqtrade_total = 0
    freqtrade_total_pnl = 0.0
    for nrow in nautilus_rows:
        iid = nrow.get("instrument", "")
        freq_row = _find_freqtrade_row(freqtrade, iid)

        n_long = int(nrow.get("n_long_entries", 0) or 0)
        n_short = int(nrow.get("n_short_entries", 0) or 0)
        n_orders = int(nrow.get("n_orders", 0) or 0)

        # Nautilus PnL — only "PnL (total)" is dollars; the dict also
        # contains Sharpe / Sortino / Win Rate etc. which are NOT dollars.
        pnl_dict = nrow.get("stats_pnls_USD", {}) or {}
        naut_pnl = 0.0
        pnl_total = pnl_dict.get("PnL (total)")
        if pnl_total is not None:
            try:
                naut_pnl = float(pnl_total)
            except (TypeError, ValueError):
                naut_pnl = 0.0

        # Freqtrade PnL
        ftrade_n = _extract_freqtrade_metric(freq_row, "n_trades", "total_trades", "trades_count")
        ftrade_long = _extract_freqtrade_metric(freq_row, "n_long", "long_trades")
        ftrade_short = _extract_freqtrade_metric(freq_row, "n_short", "short_trades")
        ftrade_pnl = _extract_freqtrade_metric(
            freq_row, "pnl_usd", "profit_total", "total_profit_usd", "profit_abs"
        )
        if ftrade_n is not None:
            freqtrade_total += int(ftrade_n)
        if ftrade_pnl is not None:
            try:
                freqtrade_total_pnl += float(ftrade_pnl)
            except (TypeError, ValueError):
                pass

        # Direction bias
        n_diff = None
        if ftrade_n is not None:
            n_diff = n_orders - int(ftrade_n)
        direction = ""
        if n_diff is not None:
            if n_diff > 0:
                direction = "nautilus_more"
            elif n_diff < 0:
                direction = "freqtrade_more"
            else:
                direction = "tie"
        elif n_orders > 0 and not freq_row:
            direction = "nautilus_only"

        pnl_diff = None
        if ftrade_pnl is not None:
            pnl_diff = round(naut_pnl - float(ftrade_pnl), 2)

        report.by_instrument.append(ParityRow(
            instrument=iid,
            nautilus_n_orders=n_orders,
            nautilus_n_positions=int(nrow.get("n_positions", 0) or 0),
            nautilus_n_long=n_long,
            nautilus_n_short=n_short,
            nautilus_pnl_usd=round(naut_pnl, 2),
            freqtrade_n_trades=int(ftrade_n) if ftrade_n is not None else None,
            freqtrade_n_long=int(ftrade_long) if ftrade_long is not None else None,
            freqtrade_n_short=int(ftrade_short) if ftrade_short is not None else None,
            freqtrade_pnl_usd=float(ftrade_pnl) if ftrade_pnl is not None else None,
            n_trades_diff=n_diff,
            pnl_diff_usd=pnl_diff,
            direction_bias=direction,
        ))

    if freqtrade:
        report.freqtrade_total_trades = freqtrade_total
        report.freqtrade_total_pnl_usd = round(freqtrade_total_pnl, 2)

    # ── Notes (auto-generated) ───────────────────────────────────────────
    feature_flags = _try_read_feature_flags(nautilus_dir)
    if feature_flags:
        adx_on = feature_flags.get("ENABLE_ADX_GATE", "?") == "1"
        cis_on = feature_flags.get("ENABLE_CIS_GATE", "?") == "1"
        fund_off = feature_flags.get("ENABLE_FUNDING_FILTER", "?") == "0"
        report.notes.append(
            f"feature flags: ADX={adx_on}, CIS={cis_on}, FUNDING={not fund_off}"
        )
        if adx_on and cis_on:
            report.notes.append(
                "expected: Nautilus should produce FEWER trades than freqtrade "
                "(both gates filter aggressively).  Inverse direction → check gates."
            )
        elif not adx_on and not cis_on:
            report.notes.append(
                "expected: Nautilus should produce MORE trades than freqtrade "
                "(alpha-only run, mirrors Shadow's earlier ls_v4.py stub)."
            )

    # ── Write outputs ────────────────────────────────────────────────────
    report_dict = report.to_dict()
    (out_dir / "parity_report.json").write_text(
        json.dumps(report_dict, indent=2, default=str)
    )

    # CSV
    csv_path = out_dir / "parity_report.csv"
    if report.by_instrument:
        keys = list(asdict(report.by_instrument[0]).keys())
        with csv_path.open("w", newline="") as fp:
            w = csv.DictWriter(fp, fieldnames=keys)
            w.writeheader()
            for r in report.by_instrument:
                w.writerow(asdict(r))

    # Human-readable markdown
    md_path = out_dir / "parity_report.md"
    md_path.write_text(_render_markdown(report))

    logger.info(f"parity report → {out_dir}/parity_report.{{json,csv,md}}")
    return report_dict


def _try_read_feature_flags(nautilus_dir: Path) -> dict:
    meta_path = nautilus_dir / "run_metadata.json"
    if not meta_path.exists():
        return {}
    meta = json.loads(meta_path.read_text())
    return meta.get("feature_flags", {})


def _render_markdown(report: ParityReport) -> str:
    lines = [
        f"# LS v1 parity report",
        f"",
        f"- Nautilus run: `{report.nautilus_run_dir}`",
        f"- Freqtrade baseline: `{report.freqtrade_baseline_path}`",
        f"- Instruments: {report.n_instruments}",
        f"",
        f"## Totals",
        f"",
        f"| Metric | Nautilus | Freqtrade |",
        f"|---|---|---|",
        f"| Orders / trades | {report.nautilus_total_orders} | "
        f"{report.freqtrade_total_trades or 'n/a'} |",
        f"| Positions | {report.nautilus_total_positions} | n/a |",
        f"| PnL (USD) | {report.nautilus_total_pnl_usd:.2f} | "
        f"{report.freqtrade_total_pnl_usd if report.freqtrade_total_pnl_usd is not None else 'n/a'} |",
        f"",
        f"## Per instrument",
        f"",
        f"| Instrument | Naut. orders | N long | N short | Fq trades | Diff | PnL diff (USD) | Bias |",
        f"|---|---|---|---|---|---|---|---|",
    ]
    for r in report.by_instrument:
        diff_str = f"{r.n_trades_diff:+d}" if r.n_trades_diff is not None else "n/a"
        pnl_str = f"{r.pnl_diff_usd:+.2f}" if r.pnl_diff_usd is not None else "n/a"
        lines.append(
            f"| {r.instrument} | {r.nautilus_n_orders} | {r.nautilus_n_long} | "
            f"{r.nautilus_n_short} | {r.freqtrade_n_trades or 'n/a'} | "
            f"{diff_str} | {pnl_str} | {r.direction_bias or 'n/a'} |"
        )
    if report.skip_summaries:
        lines += ["", "## Strategy skip summary", ""]
        for inst, summary in report.skip_summaries.items():
            lines.append(f"### {inst}")
            lines.append("")
            lines.append("| Key | Value |")
            lines.append("|---|---|")
            for k, v in summary.items():
                lines.append(f"| {k} | {v} |")
            lines.append("")
    if report.notes:
        lines += ["", "## Notes", ""]
        for n in report.notes:
            lines.append(f"- {n}")
    return "\n".join(lines) + "\n"


# ── Smoke (CLI) ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if len(sys.argv) < 2:
        print("usage: python parity_check.py <nautilus_run_dir> [freqtrade_baseline.json]")
        sys.exit(1)
    naut_dir = Path(sys.argv[1])
    ftrade_path = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    report = diff_runs(naut_dir, ftrade_path)
    print(json.dumps(report, indent=2, default=str))
