"""
B-S1 envelope runner (compose-only) — Minimax-B, 2026-07-21
==============================================================================
Produces a (variant × fold × pair) job grid for the 3-variant B-S1 envelope
(A1, A4, A6). For each cell, builds the SleeveAConfig (now supporting
`hard_stop_pct: Optional[float]` after the L3 refactor) and emits a manifest
JSON that a Mac-side runner can iterate over.

**This module is compose-only** — it does NOT call nautilus_trader, does NOT
submit to the engine, does NOT write results to a backtest directory. Mac-side
execution picks up the manifest and dispatches each cell to runner.py::run_one.

Why split compose from execute?

- Sandbox: `nautilus_trader` is NOT installable here, so we can't run.
- Mac: `nautilus_trader` is in the freqtrade venv at
  `/Volumes/CometCloudAI/freqtrade/.venv`, but the Cowork sandbox can't
  reach it (no shell).
- → composition happens in the sandbox; execution happens on Mac.

After Mac-side execution, the runner emits a CSV at the path:
    reports/sleeve_a_envelope/2026-07-21/per_cell.csv
with shape `{variant, fold, label, oos_window, n_trades, expectancy, max_loss}`
(same shape subset as the freqtrade envelope CSV — `envelope_diff.py` reads
both columns).

Public surface:
    build_envelope_manifest(out_dir, fold_dates_from_csv) -> Path
        Top-level: emit manifest.json + a small README explaining Mac-side
        execution steps.  Returns the manifest path.

    ENVELOPE_VARIANTS — the 3 (variant, hard_stop_pct, leverage) specs.

The 7-fold structure (6 OOS + 1 HOLD-OUT) is **mirrored** from
`/Volumes/.../_data/research/c_s3_walk_forward.py:65-74`.  If C-S3 grows more
folds, update both in lockstep.  Mac-side execution reads the same shape from
this module, so they should not drift.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from pathlib import Path
from typing import Optional


logger = logging.getLogger(__name__)


# ── Fold structure (mirror of C-S3) ──────────────────────────────────────────

@dataclass(frozen=True)
class Fold:
    fold_id: int
    train_start: str
    train_end: str
    oos_start: str
    oos_end: str
    label: str
    oos_window: str = ""

    def __post_init__(self) -> None:
        if not self.oos_window:
            object.__setattr__(self, "oos_window", f"{self.oos_start} → {self.oos_end}")


# Mirror of /Volumes/.../_data/research/c_s3_walk_forward.py:65-74
WINDOW_PLAN = [
    Fold(1,  "2024-04-01", "2024-09-30", "2024-10-08", "2025-03-31",
         "W1: recovery + bull-peak"),
    Fold(2,  "2024-07-01", "2024-12-31", "2025-01-08", "2025-06-30",
         "W2: bull-peak + chop"),
    Fold(3,  "2024-10-01", "2025-03-31", "2025-04-08", "2025-09-30",
         "W3: chop + late-summer"),
    Fold(4,  "2025-01-01", "2025-06-30", "2025-07-08", "2025-12-31",
         "W4: late-summer + autumn selloff"),
    Fold(5,  "2025-04-01", "2025-09-30", "2025-10-08", "2026-03-31",
         "W5: autumn selloff + recovery"),
    Fold(6,  "2025-07-01", "2025-12-31", "2026-01-08", "2026-06-30",
         "W6: recovery + Q2 2026"),
]
HOLDOUT = Fold(99, "2025-10-01", "2026-03-31", "2026-04-08", "2026-07-16",
               "HOLD-OUT: post all folds (embargoed)")

ALL_FOLDS: list[Fold] = WINDOW_PLAN + [HOLDOUT]


# ── Envelope variant spec (3 load-bearing axes only) ─────────────────────────

@dataclass(frozen=True)
class EnvelopeVariant:
    """B-S1 envelope axis.  NOT to be confused with C-S3 `Variant` class —
    this is the 3-variant subset that passes the implicit-PASS algebra:

        A1+A4+A6 PASS ⇒ A2(=A5), A3, A7/A8 implicit PASS.
    """
    name: str                                       # exact string for trades parser
    description: str
    hard_stop_pct: Optional[float]                  # 0.03 default preserved; None = NOSTOP
    leverage: int


# Mirror of /Volumes/.../_data/research/c_s3_walk_forward.py:91-99 (envelope
# subset).  hard_stop_pct is a float pct expressed as positive number (the
# strategy multiplies by entry_price to get sl_distance).  `None` ⇒ NOSTOP.
ENVELOPE_VARIANTS: list[EnvelopeVariant] = [
    EnvelopeVariant(
        name="A1_ORIGINAL_3X_NOSTOP",
        description="FAITHFUL marketing: AND entry, signal exit, 3× lev, no stop",
        hard_stop_pct=None,            # ← DISABLED (the L3 Optional[float] hook)
        leverage=3,
    ),
    EnvelopeVariant(
        name="A4_CATAS_STOP_15PCT",
        description="1× lev + wide −15% catas stop (Tom doctrine tail-bound)",
        hard_stop_pct=0.15,
        leverage=1,
    ),
    EnvelopeVariant(
        name="A6_TIGHT_STOP_5PCT",
        description="1× lev + tight −5% stop (over-tight contrast; whipsaw cost visible vs A4)",
        hard_stop_pct=0.05,
        leverage=1,
    ),
]


# ── Manifest assembly ────────────────────────────────────────────────────────

@dataclass
class EnvelopeCell:
    """One (variant, fold) cell, with the SleeveAConfig knobs for Mac-side
    execution.  `oos_start` / `oos_end` define the per-fold backtest window."""
    variant: str
    fold_id: int
    label: str
    oos_window: str
    train_start: str                 # for trainer-side pipeline build (if any)
    train_end: str
    hard_stop_pct: Optional[float]   # None ⇒ NOSTOP (A1 only)
    leverage: int
    out_basename: str                # per-cell output subdir name


@dataclass
class EnvelopeManifest:
    schema_version: int = 1
    generated_at: str = ""
    n_variants: int = 0
    n_folds: int = 0
    n_cells: int = 0
    pairs: list[str] = field(default_factory=lambda: [
        "BTCUSDT-PERP.BINANCE", "ETHUSDT-PERP.BINANCE", "SOLUSDT-PERP.BINANCE",
    ])
    cells: list[EnvelopeCell] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


def build_envelope_manifest(out_dir: Path) -> dict:
    """Construct the 3 × 7 = 21 envelope cells + the per-cell SleeveAConfig
    knobs.  Writes manifest.json + envelope_run_instructions.md.

    Returns the manifest dict (also serialised to out_dir/manifest.json).
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    manifest = EnvelopeManifest(
        generated_at=datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        n_variants=len(ENVELOPE_VARIANTS),
        n_folds=len(ALL_FOLDS),
    )

    for variant in ENVELOPE_VARIANTS:
        for fold in ALL_FOLDS:
            tag_stop = ("NOSTOP" if variant.hard_stop_pct is None
                        else f"{int(variant.hard_stop_pct * 100)}PCT")
            out_basename = f"{variant.name}__fold{fold.fold_id:02d}_{tag_stop}"
            cell = EnvelopeCell(
                variant=variant.name,
                fold_id=fold.fold_id,
                label=fold.label,
                oos_window=fold.oos_window,
                train_start=fold.train_start,
                train_end=fold.train_end,
                hard_stop_pct=variant.hard_stop_pct,
                leverage=variant.leverage,
                out_basename=out_basename,
            )
            manifest.cells.append(cell)
    manifest.n_cells = len(manifest.cells)
    manifest_dict = manifest.to_dict()

    manifest.notes = [
        "B-S1 envelope: 3 variants × 7 folds = 21 cells (6 OOS + 1 HOLD-OUT).",
        "Envelope run is compose-only here (no nautilus_trader in sandbox); "
        "Mac-side runner.py iterates manifest.cells and dispatches each cell.",
        "Hard-stop semantics: hard_stop_pct=None ⇒ NOSTOP (only signal exits; "
        "B-S1 variant A1).  Other cells pass hard_stop_pct=0.15 (A4) or 0.05 (A6).",
        "Pairs: BTC, ETH, SOL (3 pairs per cell; total Nautilus calls = 21 × 3 = 63).",
        "Implicit-PASS algebraic shortcut: A2≡A5 + A3 + A7/A8 PASS if A1+A4+A6 PASS.",
        "Per-cell output filename: <out_basename>_per_pair.json (3 of these per cell).",
        "Downstream: envelope_diff.py consumes this manifest + the freqtrade envelope "
        "CSV (already at /Volumes/.../c_s5_b_s1_parity_metrics_envelope.csv) + a "
        "Mac-side per_cell.csv emitted by the runner (same 21-row shape).",
    ]

    # ── Write outputs ───────────────────────────────────────────────────
    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest_dict, indent=2, default=str)
    )
    instructions_path = out_dir / "envelope_run_instructions.md"
    instructions_path.write_text(_render_instructions(manifest_dict))

    logger.info(f"envelope manifest → {manifest_path}  ({manifest.n_cells} cells)")
    return manifest_dict


# ── Markdown instructions (for Mac-side operator) ────────────────────────────

def _render_instructions(manifest: dict) -> str:
    L = [
        "# B-S1 envelope run instructions (Minimax-B → Mac operator)",
        "",
        f"Generated {manifest['generated_at']}.  Schema v{manifest['schema_version']}.",
        "",
        "## What this is",
        "",
        f"Compose-only manifest for the B-S1 envelope parity test.  "
        f"{manifest['n_variants']} variants × {manifest['n_folds']} folds = "
        f"**{manifest['n_cells']} cells** (3 pairs each = "
        f"{manifest['n_cells'] * len(manifest['pairs'])} Nautilus calls).",
        "",
        "## Mac-side execution",
        "",
        "```bash",
        "# Activate Mac venv that has nautilus_trader installed",
        "cd /Volumes/CometCloudAI/looloomi-research",
        "source /Volumes/CometCloudAI/freqtrade/.venv/bin/activate",
        "",
        "# Verify manifest + new strategy.py ship (L3 refactor: hard_stop_pct Optional[float])",
        "git log --oneline -5",
        "grep -n 'hard_stop_pct: Optional\\[float\\]' "
        "src/research/nautilus/sleeve_a/strategy.py",
        "",
        "# Iterate manifest; for each cell call runner.run_one() with the per-cell",
        "# SleeveAConfig + the per-fold oos_start/oos_end window.  Emits per_pair",
        "# JSON; an aggregator writes envelope_diff's input CSV.",
        "python -m src.research.nautilus.sleeve_a.envelope_runner_execute \\\n"
        "    --manifest reports/sleeve_a_envelope/2026-07-21/manifest.json \\\n"
        "    --out-root reports/sleeve_a_envelope/2026-07-21/run",
        "",
        "# Sanity: per_cell.csv should have 21 rows, same schema as freqtrade envelope CSV.",
        "# Run envelope_diff.py against per_cell.csv + the freqtrade envelope CSV.",
        "python -m src.research.nautilus.sleeve_a.envelope_diff \\\n"
        "    reports/sleeve_a_envelope/2026-07-21/run/per_cell.csv \\\n"
        "    /Volumes/CometCloudAI/cometcloud-local/_data/research/c_s5_b_s1_parity_metrics_envelope.csv \\\n"
        "    reports/sleeve_a_envelope/2026-07-21/diff",
        "```",
        "",
        "## Per-cell SleeveAConfig knobs (sample, not exhaustive)",
        "",
        "| variant | fold | hard_stop_pct | leverage | oos_window |",
        "|---|---|--:|--:|---|",
    ]
    sample = manifest["cells"][:7]  # 1st fold of each variant
    for c in sample:
        stop_str = "None (NOSTOP)" if c["hard_stop_pct"] is None else f"{c['hard_stop_pct']}"
        L.append(
            f"| {c['variant']} | {c['fold_id']} | {stop_str} | "
            f"{c['leverage']} | {c['oos_window']} |"
        )
    L.append("")
    L.append("(Full 21-row table in `manifest.json`.)")
    L.append("")
    L.append("## Notes")
    L.append("")
    for n in manifest["notes"]:
        L.append(f"- {n}")
    return "\n".join(L) + "\n"


# ── CLI ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", type=Path,
                    default=Path(f"reports/sleeve_a_envelope/"
                                 f"{datetime.utcnow():%Y-%m-%d}"))
    args = ap.parse_args()
    m = build_envelope_manifest(args.out_dir)
    print(f"\n{len(m['cells'])} cells × {len(m['pairs'])} pairs = "
          f"{len(m['cells']) * len(m['pairs'])} Nautilus calls planned")
    print(f"Manifest → {args.out_dir}/manifest.json + envelope_run_instructions.md")
