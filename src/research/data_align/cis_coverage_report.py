"""
CIS historical coverage report — per-asset × per-year × per-pillar.

Reports coverage of the 11yr CIS historical CSV (or any subset thereof) on
three axes that matter for §DATA-ALIGN and downstream S-77/78/79:

  1. Coverage (n rows with pillar ≠ null per asset × year)
  2. 2024 bull window: pillar_a + 4 other pillars per asset (the gate)
  3. Per-asset × per-pillar finite rate over the full 11yr

Output: prints a markdown-style table + writes JSON to reports/.

Why this exists:
  - The 2024 bull window is the natural regime where pillar_A / vol / momentum
    WERE real (if they ever were). S-77/78/79 cannot settle the
    "A/vol: real or bear-window illusion" question without TRUE pillar_a
    coverage on that window.
  - Per-asset × per-year coverage surfaces holes in the historical reconstruction
    (e.g., an asset that joins mid-2023 has fewer rows).

CLI:
    python3 src/research/data_align/cis_coverage_report.py
    python3 src/research/data_align/cis_coverage_report.py --csv <path> --out <dir>
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from src.research.data_align.cis_history_loader import load_cis_history
from src.research.data_align.cis_history_schema import (
    CSV_COLUMNS, NUMERIC_COLUMNS,
)

PILLARS: tuple[str, ...] = ("f", "m", "o", "s", "a")


def per_asset_year_coverage(df: pd.DataFrame) -> pd.DataFrame:
    """Pivot table: rows = (symbol, year), columns = pillar, values = n finite."""
    df = df.copy()
    df["year"] = df["_date"].dt.year
    rows = []
    for (sym, yr), g in df.groupby(["symbol", "year"]):
        rec = {"symbol": sym, "year": int(yr), "n_obs": int(len(g))}
        for p in PILLARS:
            col = f"pillar_{p}"
            rec[f"n_{p}"] = int(g[col].notna().sum())
        rec["has_all_5_pillars"] = all(rec[f"n_{p}"] == rec["n_obs"] for p in PILLARS)
        rows.append(rec)
    return pd.DataFrame(rows).sort_values(["symbol", "year"])


def bull_window_coverage(df: pd.DataFrame,
                         lo: str = "2024-01-01",
                         hi: str = "2024-12-31") -> pd.DataFrame:
    """Per-asset coverage of the 2024 bull window — the §DATA-ALIGN gate.

    Returns a table of (symbol, n_obs, n_with_all_5, pct_with_all_5, ...).
    """
    sub = df[(df["_date"] >= pd.Timestamp(lo)) & (df["_date"] <= pd.Timestamp(hi))]
    rows = []
    for sym, g in sub.groupby("symbol"):
        n_total = int(len(g))
        all5 = int(g[[f"pillar_{p}" for p in PILLARS]].notna().all(axis=1).sum())
        rows.append({
            "symbol": sym,
            "n_obs_2024": n_total,
            "n_with_all_5_pillars": all5,
            "pct_with_all_5": round(100.0 * all5 / max(1, n_total), 2),
            "first_2024_date": str(g["_date"].min()),
            "last_2024_date": str(g["_date"].max()),
            "bull_window_pass": all5 >= 0.95 * n_total,  # ≥95% rows have all 5 pillars
        })
    return pd.DataFrame(rows).sort_values("symbol")


def overall_finite_rate(df: pd.DataFrame) -> dict:
    """Per-pillar finite rate over the full df."""
    out = {"n_rows": int(len(df)), "n_assets": int(df["symbol"].nunique()),
           "n_dates": int(df["_date"].nunique())}
    for p in PILLARS:
        col = f"pillar_{p}"
        n = int(df[col].notna().sum())
        out[col] = {"n_finite": n, "pct_finite": round(100.0 * n / max(1, len(df)), 2)}
    return out


def write_markdown(report: dict, out_path: Path) -> None:
    """Pretty-print the coverage report as markdown."""
    lines: list[str] = []
    lines.append("# CIS Historical Coverage Report\n")
    lines.append(f"Generated: 2026-07-24 (Seth — §DATA-ALIGN directive)\n")
    lines.append(f"CSV: `{report['csv_path']}` ({report['n_rows']:,} rows × "
                 f"{report['n_assets']} symbols × {report['n_dates']:,} dates)\n")
    lines.append("\n## Overall per-pillar finite rate\n")
    lines.append("| Pillar | n_finite | pct_finite |")
    lines.append("|---|---:|---:|")
    for p in PILLARS:
        col = f"pillar_{p}"
        lines.append(f"| pillar_{p} | {report['overall'][col]['n_finite']:,} | "
                     f"{report['overall'][col]['pct_finite']}% |")
    lines.append("\n## 2024 bull window — per-asset pillar coverage\n")
    lines.append("Gate: ≥95% of 2024 rows must have all 5 pillars populated.\n")
    lines.append("| Symbol | n_obs | n_with_all_5 | pct_with_all_5 | pass |")
    lines.append("|---|---:|---:|---:|:---:|")
    for _, r in report["bull_2024"].iterrows():
        flag = "✅" if r["bull_window_pass"] else "❌"
        lines.append(f"| {r['symbol']} | {r['n_obs_2024']:,} | "
                     f"{r['n_with_all_5_pillars']:,} | {r['pct_with_all_5']}% | {flag} |")
    pass_n = int(report["bull_2024"]["bull_window_pass"].sum())
    total_n = len(report["bull_2024"])
    lines.append(f"\n**Summary: {pass_n}/{total_n} assets pass the 2024 bull gate "
                 f"(all 5 pillars populated on ≥95% of rows).**\n")
    out_path.write_text("\n".join(lines))


def main():
    ap = argparse.ArgumentParser(description="CIS historical coverage report")
    ap.add_argument("--csv", default=str(ROOT / "_data" / "cis_historical" / "cis_historical_11yr_aligned.csv"))
    ap.add_argument("--out", default=str(ROOT / "reports" / "data_align"))
    ap.add_argument("--lo", default="2024-01-01")
    ap.add_argument("--hi", default="2024-12-31")
    args = ap.parse_args()

    csv_path = Path(args.csv)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Loading {csv_path.name}…")
    df = load_cis_history(csv_path, force_schema=True)

    overall = overall_finite_rate(df)
    bull_2024 = bull_window_coverage(df, args.lo, args.hi)
    per_asset_year = per_asset_year_coverage(df)

    print(f"\nOverall: {overall['n_rows']:,} rows × {overall['n_assets']} symbols × "
          f"{overall['n_dates']:,} dates")
    print("Per-pillar finite rate:")
    for p in PILLARS:
        col = f"pillar_{p}"
        print(f"  pillar_{p}: {overall[col]['n_finite']:,} ({overall[col]['pct_finite']}%)")
    pass_n = int(bull_2024["bull_window_pass"].sum())
    total_n = len(bull_2024)
    print(f"\n2024 bull window: {pass_n}/{total_n} assets pass the gate "
          f"(≥95% rows have all 5 pillars)")
    print("Per-asset 2024 coverage:")
    for _, r in bull_2024.iterrows():
        flag = "✅" if r["bull_window_pass"] else "❌"
        print(f"  {flag} {r['symbol']:6s}  n={r['n_obs_2024']:4d}  "
              f"all5={r['n_with_all_5_pillars']:4d} ({r['pct_with_all_5']:5.1f}%)")

    report = {
        "csv_path": str(csv_path),
        "n_rows": overall["n_rows"],
        "n_assets": overall["n_assets"],
        "n_dates": overall["n_dates"],
        "overall": overall,
        "bull_2024": bull_2024,
        "per_asset_year_sample": per_asset_year.head(50).to_dict(orient="records"),
    }
    json_path = out_dir / "cis_coverage_report.json"
    md_path = out_dir / "cis_coverage_report.md"
    json_path.write_text(json.dumps(report, indent=2, default=str))
    write_markdown(report, md_path)
    print(f"\nWrote {json_path}")
    print(f"Wrote {md_path}")


if __name__ == "__main__":
    main()