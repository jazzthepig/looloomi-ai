"""
OOS Isolation — Per-window isolated OOS PnL from cached multi-window sweep data.

The multi_window_baseline.py driver runs Nautilus once per window over [is_start, oos_end].
The aggregated pnl_usd in each window's raw JSON is the TOTAL PnL over that combined
range, not the isolated OOS portion. Worse, most of that PnL comes from positions that
opened during IS (warmup) but happened to close during OOS.

This script computes the TRUE isolated OOS PnL per window by filtering positions
where ts_opened falls within [oos_start, oos_end) — only positions the strategy ENTERED
during the OOS period count.

Output: reports/multi_window_baseline_<src>_<cis>/<date>/oos_isolation.json with per-window
OOS PnL + IS/OOS monthly series.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import pandas as pd


CIS_PIPELINE_START = datetime.fromisoformat("2024-06-07T00:00:00+00:00")


def isolate_window(raw_path: Path) -> dict:
    """Read a single raw window JSON, return isolated OOS PnL + supporting stats.

    A trade is OOS-isolated iff ts_opened ∈ [oos_start, oos_end).
    """
    d = json.loads(raw_path.read_text())
    if "error" in d:
        return {"label": raw_path.stem, "error": d["error"]}

    w = d["window_dates"]
    oos_s = int(datetime.fromisoformat(w["oos_start"]).timestamp() * 1_000_000_000)
    oos_e = int(datetime.fromisoformat(w["oos_end"]).timestamp() * 1_000_000_000)
    is_s = int(datetime.fromisoformat(w["is_start"]).timestamp() * 1_000_000_000)

    reported_pnl = d.get("pnl_usd", 0)
    oos_pnl = 0.0
    is_pnl = 0.0
    n_oos = 0
    n_is = 0
    oos_events = []  # (bar_end_ts, pnl) for those opened in OOS

    for r in d.get("per_instrument", []):
        for pos in r.get("positions", []):
            pnl = float(pos.get("realized_pnl") or 0)
            ts_o = int(pos.get("ts_opened") or 0)
            ts_c = int(pos.get("ts_closed") or 0)
            if ts_o == 0 or ts_c == 0:
                continue
            if oos_s <= ts_o < oos_e:
                oos_pnl += pnl
                n_oos += 1
                bar_end = ts_c - (ts_c % (4 * 3_600_000_000_000))
                oos_events.append({"bar_end_ns": bar_end, "pnl": pnl})
            elif is_s <= ts_o < oos_s:
                is_pnl += pnl
                n_is += 1

    return {
        "label": raw_path.stem,
        "window_dates": w,
        "reported_pnl_usd": reported_pnl,
        "is_pnl_usd": round(is_pnl, 2),
        "oos_pnl_usd": round(oos_pnl, 2),
        "n_is_trades": n_is,
        "n_oos_trades": n_oos,
        "oos_events": oos_events,
    }


def aggregate(windows: list[dict]) -> dict:
    """Aggregate per-window OOS into monthly returns + summary stats."""
    rows = []
    for w in windows:
        if "error" in w:
            continue
        rows.append({
            "label": w["label"],
            "oos_start": w["window_dates"]["oos_start"],
            "oos_end": w["window_dates"]["oos_end"],
            "reported_pnl": w["reported_pnl_usd"],
            "is_pnl": w["is_pnl_usd"],
            "oos_pnl": w["oos_pnl_usd"],
            "n_is": w["n_is_trades"],
            "n_oos": w["n_oos_trades"],
        })
    if not rows:
        return {"error": "no valid windows"}

    df = pd.DataFrame(rows)
    df["oos_start_dt"] = pd.to_datetime(df["oos_start"])
    df = df.sort_values("oos_start_dt").reset_index(drop=True)
    df["month"] = df["oos_start_dt"].dt.to_period("M")

    monthly = df.groupby("month").agg(
        oos_pnl=("oos_pnl", "sum"),
        is_pnl=("is_pnl", "sum"),
        reported_pnl=("reported_pnl", "sum"),
        n_windows=("label", "count"),
        n_oos_trades=("n_oos", "sum"),
        n_is_trades=("n_is", "sum"),
    )

    # Stats on monthly OOS PnL
    mean = monthly["oos_pnl"].mean()
    std = monthly["oos_pnl"].std(ddof=1) if len(monthly) > 1 else 0
    ann_sharpe = float(mean / std * (12 ** 0.5)) if std > 0 else 0.0
    total = monthly["oos_pnl"].sum()
    n_pos = int((monthly["oos_pnl"] > 0).sum())
    n_neg = int((monthly["oos_pnl"] < 0).sum())

    # NAV path: starting NAV + cumulative OOS PnL
    nav = 10_000 + monthly["oos_pnl"].cumsum()
    peak = nav.cummax()
    dd_pct = ((nav - peak) / peak * 100)
    max_dd_pct = float(dd_pct.min())
    final_nav = float(nav.iloc[-1])

    # Pre/post CIS split — by WINDOW's oos_start, not month aggregation
    df["cis_era"] = df["oos_start_dt"].apply(
        lambda x: "post_cis" if x >= CIS_PIPELINE_START else "pre_cis"
    )
    pre_df = df[df["cis_era"] == "pre_cis"]
    post_df = df[df["cis_era"] == "post_cis"]

    return {
        "n_windows": len(rows),
        "n_months": len(monthly),
        "summary": {
            "total_oos_pnl": round(float(total), 2),
            "total_is_pnl": round(float(monthly["is_pnl"].sum()), 2),
            "total_reported_pnl": round(float(monthly["reported_pnl"].sum()), 2),
            "win_rate_oos": round(n_pos / len(monthly), 4),
            "win_rate_reported": round(float((df["reported_pnl"] > 0).mean()), 4),
            "annualized_sharpe_oos_monthly": round(ann_sharpe, 4),
            "max_dd_oos_pct": round(max_dd_pct, 4),
            "final_nav": round(final_nav, 2),
        },
        "pre_cis": {
            "n_windows": len(pre_df),
            "total_oos_pnl": round(float(pre_df["oos_pnl"].sum()), 2),
            "win_rate": round(float((pre_df["oos_pnl"] > 0).mean()), 4) if len(pre_df) else None,
        },
        "post_cis": {
            "n_windows": len(post_df),
            "total_oos_pnl": round(float(post_df["oos_pnl"].sum()), 2),
            "win_rate": round(float((post_df["oos_pnl"] > 0).mean()), 4) if len(post_df) else None,
        },
        "per_window": rows,
        "monthly": [
            {
                "month": str(m),
                "oos_pnl": round(float(monthly.loc[m, "oos_pnl"]), 2),
                "is_pnl": round(float(monthly.loc[m, "is_pnl"]), 2),
                "reported_pnl": round(float(monthly.loc[m, "reported_pnl"]), 2),
                "n_oos_trades": int(monthly.loc[m, "n_oos_trades"]),
                "n_is_trades": int(monthly.loc[m, "n_is_trades"]),
            }
            for m in monthly.index
        ],
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw-dir", type=Path, required=True,
                    help="Directory of raw w*.json window files")
    ap.add_argument("--out-dir", type=Path, required=True,
                    help="Output directory (writes oos_isolation.json)")
    args = ap.parse_args(argv)

    if not args.raw_dir.exists():
        print(f"ERROR: {args.raw_dir} not found")
        return 1

    windows = []
    for p in sorted(args.raw_dir.glob("w*.json")):
        windows.append(isolate_window(p))

    result = aggregate(windows)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    out_path = args.out_dir / "oos_isolation.json"
    out_path.write_text(json.dumps(result, indent=2, default=str))

    s = result.get("summary", {})
    print(f"=== OOS Isolation: {result.get('n_windows', 0)} windows, {result.get('n_months', 0)} months ===")
    print(f"Total OOS PnL:    ${s.get('total_oos_pnl', 0):+.2f}  (vs reported ${s.get('total_reported_pnl', 0):+.2f})")
    print(f"Win rate (OOS):   {s.get('win_rate_oos', 0):.1%}")
    print(f"Sharpe (monthly): {s.get('annualized_sharpe_oos_monthly', 0):+.3f}")
    print(f"Max DD:           {s.get('max_dd_oos_pct', 0):.2f}%")
    print(f"Final NAV:        ${s.get('final_nav', 0):.2f}")
    pre = result.get("pre_cis", {})
    post = result.get("post_cis", {})
    print(f"Pre-CIS  ({pre.get('n_windows', 0)}w):  ${pre.get('total_oos_pnl', 0):+.2f}  win={pre.get('win_rate', 0):.1%}")
    print(f"Post-CIS ({post.get('n_windows', 0)}w):  ${post.get('total_oos_pnl', 0):+.2f}  win={post.get('win_rate', 0):.1%}")
    print(f"\nWrote: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())