#!/usr/bin/env python3
"""
CIS Historical Align — §DATA-ALIGN directive (Jazz, 2026-07-24).

End-to-end orchestrator:
  1. Prepend the canonical header to `cis_historical_11yr.csv` (idempotent —
     skips if the file already starts with `symbol,...`).
  2. Run the enricher (β-adj returns + regime-normalized pillar z-scores).
  3. Write the aligned output to `cis_historical_11yr_aligned.csv` (same
     schema + extra columns: `beta_adj_return`, `regime_zscore_{f,m,o,s,a,score}`,
     `asset_zscore_{f,m,o,s,a,score}`, `_date`).

CLI:
    python3 scripts/cis_historical_align.py
    python3 scripts/cis_historical_align.py --no-beta-adj
    python3 scripts/cis_historical_align.py --in <path> --out <path>

Lane discipline (Seth → Minimax, per CLAUDE.md §5):
  - This script WRITES to `_data/cis_historical/cis_historical_11yr_aligned.csv`
    (Seth-owned path) and modifies the canonical CSV only by prepending a
    header line. Mac-side CIS push logic stays Minimax's lane.

The Supabase ingest target (`scripts/cis_historical_ingest.py --target supabase`)
reads from `cis_historical_11yr.csv` directly. After this script runs, the
canonical CSV has a header line; the ingest script's `read_csv_rows` is
header-tolerant and continues to work.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.research.data_align.cis_history_loader import prepend_header_if_missing, load_cis_history
from src.research.data_align.cis_history_enrich import enrich_cis_history
from src.research.data_align.cis_history_schema import CSV_COLUMNS, header_line


DEFAULT_IN = ROOT / "_data" / "cis_historical" / "cis_historical_11yr.csv"
DEFAULT_OUT = ROOT / "_data" / "cis_historical" / "cis_historical_11yr_aligned.csv"


def main():
    ap = argparse.ArgumentParser(description="§DATA-ALIGN: align 11yr CIS CSV headers + enrich")
    ap.add_argument("--in", dest="in_csv", default=str(DEFAULT_IN))
    ap.add_argument("--out", dest="out_csv", default=str(DEFAULT_OUT))
    ap.add_argument("--no-beta-adj", dest="no_beta_adj", action="store_true",
                    help="Skip β-adjusted return computation (faster; requires OHLCV)")
    ap.add_argument("--no-zscores", dest="no_zscores", action="store_true",
                    help="Skip regime/asset z-score computation")
    ap.add_argument("--skip-header-prepend", dest="skip_header", action="store_true",
                    help="Don't prepend the canonical header to the input CSV")
    args = ap.parse_args()

    in_path = Path(args.in_csv)
    out_path = Path(args.out_csv)

    # ── Step 1: prepend header (idempotent) ─────────────────────────────────
    if not args.skip_header:
        added = prepend_header_if_missing(in_path)
        if added:
            print(f"[1/3] Prepended canonical header to {in_path.name} "
                  f"({len(CSV_COLUMNS)} cols: {header_line()[:60]}…)")
        else:
            print(f"[1/3] {in_path.name} already has header — skipped")

    # ── Step 2: load + enrich ──────────────────────────────────────────────
    print(f"[2/3] Loading {in_path.name}…")
    df = load_cis_history(in_path, force_schema=True)
    print(f"       Loaded {len(df):,} rows × {len(df.columns)} cols "
          f"({df['symbol'].nunique()} symbols × {df['_date'].nunique()} dates)")

    print(f"[2/3] Enriching (β_adj={not args.no_beta_adj}, zscores={not args.no_zscores})…")
    enriched, report = enrich_cis_history(
        df,
        compute_beta_adj=not args.no_beta_adj,
        compute_zscores=not args.no_zscores,
    )

    # ── Step 3: write aligned output ───────────────────────────────────────
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # Make sure the canonical 20 cols come first, then extras, then _date
    extra_cols = [c for c in enriched.columns if c not in CSV_COLUMNS and c != "_date"]
    final_cols = CSV_COLUMNS + extra_cols + ["_date"]
    enriched = enriched[final_cols]

    enriched.to_csv(out_path, index=False)
    print(f"[3/3] Wrote {len(enriched):,} rows × {len(enriched.columns)} cols → {out_path}")

    # ── Coverage report ────────────────────────────────────────────────────
    if report.get("beta_adj"):
        b = report["beta_adj"]
        print(f"\n  β-adj coverage:")
        print(f"    {b['n_assets_with_ohlcv']}/{b['n_assets_total']} assets "
              f"({b['coverage_pct']:.1f}%) have ≥{20} OHLCV obs")
        if b.get("min_first_date"):
            print(f"    OHLCV window: {b['min_first_date']} → {b['max_last_date']}")

    if report.get("regime_zscores"):
        print(f"\n  Regime z-score coverage:")
        for p, r in report["regime_zscores"].items():
            print(f"    pillar_{p}: {r['n_finite']:,} finite ({r['pct_finite']}%)")

    print(f"\nDone. Next step: run `scripts/cis_historical_ingest.py --target supabase` "
          f"to push the aligned data (requires SUPABASE_SERVICE_KEY).")


if __name__ == "__main__":
    main()