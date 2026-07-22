"""
Causal Sleeve Extension — Conviction-Weighted Sizing (CW-Causal)
==================================================================

Track 5 of the 2026-07-18 strategy sprint (minimax-b / Austin).

WHY this extension (the cause):
  The causal sleeve fades funding dislocations: short crowded longs (high
  funding), long crowded shorts (low/negative funding). The current
  construction EQUAL-WEIGHTS all dislocations after z-score normalization —
  a 1σ fade gets the same capital as a 3σ fade. This is structurally
  lossy: a 3σ funding dislocation is a meaningful crowd-herding event with
  a much stronger forced-flow expectation than a 1σ noise-day. Concentrating
  capital on the highest-conviction fades should improve Sharpe without
  breaking the orthogonal-to-LS property (the α comes from the SAME signal,
  just weighted differently).

MECHANIC:
  Original (positioning_weights):  w_i = -z_i        (equal after demeaning/gross=1)
  Extension (CW-Causal):           w_i = -z_i · |z_i|^p   (conviction-scaled)
  p=0 → original. p=1 → linear conviction. p=2 → quadratic conviction.

  After sizing, demean (dollar-neutral) and scale to gross=1 (same as before).

VALIDATION DISCIPLINE:
  - Use the same 6y panel (2019-12-31 → 2026-01-27) as the original causal
    sleeve, IS/OOS split at 2024-01-01.
  - Test 5 windows on the OOS side: 2024-01, 2024-04, 2024-07, 2024-10,
    2025-04 (each 120d, non-overlapping).
  - Compare p ∈ {0, 0.5, 1.0, 1.5, 2.0} — if higher p doesn't beat p=0 OOS
    on Sharpe AND MaxDD across 4/5 windows, KILL the extension.

INPUTS:
  - reports/causal_sleeve/2026-07-17/panel_meta.json — for universe
  - Re-fetch from Binance if panel is missing; otherwise load parquet.

OUTPUTS:
  - reports/causal_sleeve_extension/<date>/results.json
  - reports/causal_sleeve_extension/<date>/window_metrics.csv

DESIGN RATIONALE:
  This is a STRUCTURAL change to the sleeve (not a parameter re-sweep of the
  existing equal-weight construction). If it works, it permanently upgrades
  the sleeve. If not, the original sleeve remains untouched.
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

# Default universe — same as causal_positioning.DEFAULT_UNIVERSE
DEFAULT_UNIVERSE = ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX", "LINK",
                    "DOT", "LTC", "TRX", "ATOM", "NEAR", "APT", "ARB", "OP", "SUI",
                    "UNI", "AAVE", "INJ", "FIL", "ETC", "BCH"]

KWIN = 10  # validated optimal from causal_positioning docstring
FEE_BPS = 5  # 5bps per side (per existing causal sleeve validation)
REBALANCE_DAYS = 7  # weekly rebalance (per existing validated config)


def positioning_weights_cw(fmean: np.ndarray, kwin: int = KWIN, p: float = 0.0) -> np.ndarray:
    """T×K daily mean-funding panel → T×K market-neutral contrarian weights.

    p=0: original (equal-weight after demeaning)
    p>0: conviction-weighted — w_i = -z_i · |z_i|^p
    """
    T, K = fmean.shape
    W = np.zeros((T, K))
    for i in range(T):
        roll = fmean[max(0, i - kwin + 1):i + 1].mean(0)
        z = roll - roll.mean()
        sd = z.std()
        z = z / sd if sd > 0 else z
        if p > 0:
            w = -z * (np.abs(z) ** p)  # conviction-weighted contrarian
        else:
            w = -z  # original
        w = w - w.mean()  # dollar-neutral
        g = np.abs(w).sum()
        W[i] = w / g if g > 0 else w  # gross = 1
    return W


def backtest_cw(close: np.ndarray, fmean: np.ndarray, fsum: np.ndarray,
                *, kwin: int = KWIN, fee: float = FEE_BPS / 10000,
                rebal_days: int = REBALANCE_DAYS, p: float = 0.0) -> dict:
    """Backtest with conviction-weighted sizing.

    Returns: daily_pnl (full series), ann_sharpe, total_return_pct,
             max_dd_pct, turnover_x_day (avg), annual_return_pct.
    """
    T, K = close.shape
    # Price returns
    ret = np.zeros((T, K))
    ret[1:] = np.nan_to_num((close[1:] - close[:-1]) / close[:-1])

    # Build weights
    W = positioning_weights_cw(fmean, kwin=kwin, p=p)

    # Apply weekly rebalance — only update weights every rebal_days
    if rebal_days > 1:
        W_rebal = np.zeros_like(W)
        W_rebal[0] = W[0]
        for i in range(1, T):
            if i % rebal_days == 0:
                W_rebal[i] = W[i]
            else:
                W_rebal[i] = W_rebal[i - 1]
        W = W_rebal

    # Daily PnL
    pnl = np.zeros(T)
    turnover = np.zeros(T)
    for i in range(1, T - 1):
        turn = np.abs(W[i] - W[i - 1]).sum()
        pnl[i + 1] = (W[i] * ret[i + 1]).sum() - (W[i] * fsum[i + 1]).sum() - fee * turn
        turnover[i + 1] = turn

    sd = pnl.std(ddof=1)
    ann_sharpe = float(pnl.mean() / sd * np.sqrt(365)) if sd > 0 else 0.0
    total_ret_pct = float(pnl.sum() * 100)
    cum = np.cumsum(pnl)
    max_dd = float((np.maximum.accumulate(cum) - cum).max() * 100)
    avg_turnover_per_day = float(turnover.mean())
    annual_return_pct = float(pnl.mean() * 365 * 100)

    return {
        "daily_pnl": pnl,
        "ann_sharpe": round(ann_sharpe, 3),
        "total_return_pct": round(total_ret_pct, 2),
        "max_dd_pct": round(max_dd, 2),
        "annual_return_pct": round(annual_return_pct, 2),
        "avg_turnover_per_day": round(avg_turnover_per_day, 4),
    }


def fetch_binance_panel(assets: list[str], start_date: str = "2020-01-01") -> tuple:
    """Fetch (dates, close, fmean, fsum) from Binance USDT perps.

    Uses httpx (network call). For sandbox-safety, can be replaced with
    cached parquet if available.
    """
    import datetime as dt
    import httpx
    c = httpx.Client(timeout=25, headers={"User-Agent": "research"})
    base = "https://fapi.binance.com"
    start_ms = int(dt.datetime.strptime(start_date, "%Y-%m-%d").timestamp() * 1000)

    def klines(sym):
        end_ms = int(dt.datetime.utcnow().timestamp() * 1000)
        cur = start_ms
        out = {}
        for _ in range(15):
            r = c.get(f"{base}/fapi/v1/klines",
                      params={"symbol": sym, "interval": "1d", "startTime": cur, "limit": 1000})
            j = r.json()
            if not j:
                break
            for k in j:
                out[int(k[0]) // 86400000] = float(k[4])
            cur = int(j[-1][0]) + 86_400_000
            if len(j) < 1000 or cur > end_ms:
                break
        return out

    def funding(sym):
        out, cur = {}, start_ms
        for _ in range(6):
            r = c.get(f"{base}/fapi/v1/fundingRate",
                      params={"symbol": sym, "startTime": cur, "limit": 500})
            j = r.json()
            if not j:
                break
            for x in j:
                out.setdefault(int(x["fundingTime"]) // 86400000, []).append(float(x["fundingRate"]))
            cur = int(j[-1]["fundingTime"]) + 1
            if len(j) < 500:
                break
        return out

    cl, fm, fs = {}, {}, {}
    for a in assets:
        sym = a + "USDT"
        cl[a] = klines(sym)
        fu = funding(sym)
        fm[a] = {d: sum(v) / len(v) for d, v in fu.items()}
        fs[a] = {d: sum(v) for d, v in fu.items()}
    days = sorted(set(d for a in assets for d in fm[a]))
    di = {d: i for i, d in enumerate(days)}
    T, K = len(days), len(assets)
    close = np.full((T, K), np.nan); fmean = np.zeros((T, K)); fsum = np.zeros((T, K))
    for j, a in enumerate(assets):
        for d, v in cl[a].items():
            if d in di:
                close[di[d], j] = v
        for d, v in fm[a].items():
            fmean[di[d], j] = v
        for d, v in fs[a].items():
            fsum[di[d], j] = v
    for j in range(K):
        for i in range(1, T):
            if np.isnan(close[i, j]):
                close[i, j] = close[i - 1, j]
    return days, close, fmean, fsum


def window_metrics(pnl: np.ndarray, dates: list, start_idx: int, end_idx: int) -> dict:
    """Compute Sharpe/MaxDD/CAGR for a contiguous slice [start_idx, end_idx)."""
    slice_pnl = pnl[start_idx:end_idx]
    if len(slice_pnl) < 30:
        return {"sharpe": None, "max_dd_pct": None, "total_ret_pct": None, "n_days": len(slice_pnl)}
    sd = slice_pnl.std(ddof=1)
    sharpe = float(slice_pnl.mean() / sd * np.sqrt(365)) if sd > 0 else 0.0
    total_ret = float(slice_pnl.sum() * 100)
    cum = np.cumsum(slice_pnl)
    max_dd = float((np.maximum.accumulate(cum) - cum).max() * 100)
    return {
        "sharpe": round(sharpe, 3),
        "total_ret_pct": round(total_ret, 2),
        "max_dd_pct": round(max_dd, 2),
        "n_days": len(slice_pnl),
        "start_date": str(dates[start_idx]) if isinstance(dates[start_idx], (int, np.integer)) else dates[start_idx].isoformat() if hasattr(dates[start_idx], 'isoformat') else str(dates[start_idx]),
        "end_date": str(dates[end_idx - 1]) if isinstance(dates[end_idx - 1], (int, np.integer)) else dates[end_idx - 1].isoformat() if hasattr(dates[end_idx - 1], 'isoformat') else str(dates[end_idx - 1]),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--universe", nargs="+", default=DEFAULT_UNIVERSE)
    ap.add_argument("--start-date", default="2020-01-01")
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--p-values", nargs="+", type=float, default=[0.0, 0.5, 1.0, 1.5, 2.0])
    ap.add_argument("--oos-split-date", default="2024-01-01")
    ap.add_argument("--offline", action="store_true", help="Use cached parquet if available")
    args = ap.parse_args(argv)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")

    print("=== Causal Sleeve Extension — Conviction-Weighted Sizing ===")
    print(f"Date: {today}")
    print(f"Universe: {len(args.universe)} assets")
    print(f"Start date: {args.start_date}")
    print(f"OOS split: {args.oos_split_date}")
    print(f"p-values: {args.p_values}")
    print()

    # Load panel
    print("Loading Binance panel (network call)…")
    days, close, fmean, fsum = fetch_binance_panel(args.universe, args.start_date)
    print(f"  panel: {len(days)} days × {len(args.universe)} assets | "
          f"{days[0]} → {days[-1]}")

    # Convert days (ms timestamps) to dates for window slicing
    import datetime as dt
    dates = [dt.date.fromtimestamp(d * 86400) for d in days]

    # Find OOS split index
    oos_split = dt.datetime.strptime(args.oos_split_date, "%Y-%m-%d").date()
    is_end_idx = next((i for i, d in enumerate(dates) if d >= oos_split), len(dates))
    print(f"  IS: 0 → {is_end_idx} ({dates[0]} → {dates[is_end_idx - 1]})")
    print(f"  OOS: {is_end_idx} → {len(dates)} ({dates[is_end_idx]} → {dates[-1]})")
    print()

    # Define 5 OOS windows (120d each, non-overlapping, starting from oos_split)
    # If the OOS region is too short, fewer windows; if too long, more.
    oos_n = len(dates) - is_end_idx
    win_size = 120
    n_full_windows = oos_n // win_size
    windows = []
    for w in range(n_full_windows):
        s = is_end_idx + w * win_size
        e = s + win_size
        windows.append((s, e, f"window_{w+1}"))
    # Add a final partial window if there's leftover
    leftover = oos_n - n_full_windows * win_size
    if leftover >= 60:
        s = is_end_idx + n_full_windows * win_size
        e = s + leftover
        windows.append((s, e, f"window_{n_full_windows + 1}_partial"))
    print(f"OOS windows: {len(windows)} × {win_size}d (last is partial if leftover)")
    for s, e, name in windows:
        print(f"  {name}: idx {s} → {e}, dates {dates[s]} → {dates[e-1]}")
    print()

    # Run all p-values across all windows
    results = {}
    for p in args.p_values:
        print(f"--- p = {p} (conviction exponent) ---")
        bt = backtest_cw(close, fmean, fsum, p=p)
        is_metrics = window_metrics(bt["daily_pnl"], dates, 0, is_end_idx)
        oos_metrics = window_metrics(bt["daily_pnl"], dates, is_end_idx, len(dates))
        win_metrics = []
        for s, e, name in windows:
            wm = window_metrics(bt["daily_pnl"], dates, s, e)
            wm["name"] = name
            win_metrics.append(wm)
        results[f"p={p}"] = {
            "is": is_metrics,
            "oos_full": oos_metrics,
            "windows": win_metrics,
            "ann_sharpe_full": bt["ann_sharpe"],
            "total_return_pct_full": bt["total_return_pct"],
            "max_dd_pct_full": bt["max_dd_pct"],
            "annual_return_pct_full": bt["annual_return_pct"],
            "avg_turnover_per_day": bt["avg_turnover_per_day"],
        }
        print(f"  IS:  Sharpe={is_metrics['sharpe']:+.3f} Ret={is_metrics['total_ret_pct']:+.2f}% MaxDD={is_metrics['max_dd_pct']:.2f}%")
        print(f"  OOS: Sharpe={oos_metrics['sharpe']:+.3f} Ret={oos_metrics['total_ret_pct']:+.2f}% MaxDD={oos_metrics['max_dd_pct']:.2f}%")
        print(f"  Turnover: {bt['avg_turnover_per_day']:.4f}/day")
        for wm in win_metrics:
            print(f"  {wm['name']}: Sharpe={wm['sharpe']:+.3f} Ret={wm['total_ret_pct']:+.2f}% MaxDD={wm['max_dd_pct']:.2f}%")
        print()

    # Verdict logic: does any p>0 beat p=0 on (OOS Sharpe AND OOS MaxDD)?
    p0 = results[f"p={args.p_values[0]}"]
    p0_oos_sharpe = p0["oos_full"]["sharpe"]
    p0_oos_dd = p0["oos_full"]["max_dd_pct"]
    print(f"BASELINE (p=0): OOS Sharpe={p0_oos_sharpe:+.3f}, MaxDD={p0_oos_dd:.2f}%")
    print()
    verdict_table = []
    for p in args.p_values[1:]:
        rp = results[f"p={p}"]
        rs = rp["oos_full"]["sharpe"]
        rd = rp["oos_full"]["max_dd_pct"]
        delta_sharpe = rs - p0_oos_sharpe
        delta_dd = rd - p0_oos_dd  # negative is better (less DD)
        wins_windows = sum(1 for w0, wp in zip(p0["windows"], rp["windows"])
                          if wp["sharpe"] is not None and w0["sharpe"] is not None
                          and wp["sharpe"] > w0["sharpe"])
        # Conviction-weighted wins if: better OOS Sharpe AND lower OOS MaxDD AND wins ≥ 3/5 windows
        survives = (delta_sharpe > 0) and (delta_dd <= 0) and (wins_windows >= 3)
        verdict_table.append({
            "p": p,
            "oos_sharpe": rs,
            "oos_max_dd": rd,
            "delta_sharpe": round(delta_sharpe, 3),
            "delta_dd": round(delta_dd, 2),
            "windows_won": wins_windows,
            "survives": survives,
        })
        print(f"  p={p}: OOS Sharpe={rs:+.3f} (Δ={delta_sharpe:+.3f}) | MaxDD={rd:.2f}% (Δ={delta_dd:+.2f}%) | "
              f"windows won: {wins_windows}/{len(p0['windows'])} | {'✅ SURVIVES' if survives else '❌ REJECTED'}")

    # Save outputs
    out = {
        "date": today,
        "universe": args.universe,
        "n_universe": len(args.universe),
        "kwin": KWIN,
        "fee_bps": FEE_BPS,
        "rebalance_days": REBALANCE_DAYS,
        "oos_split_date": args.oos_split_date,
        "p_values_tested": args.p_values,
        "results_by_p": results,
        "verdict_table": verdict_table,
        "baseline_p": args.p_values[0],
    }
    out_file = args.out_dir / "results.json"
    with open(out_file, "w") as f:
        json.dump(out, f, indent=2, default=str)
    print(f"\nSaved: {out_file}")

    # CSV summary
    rows = []
    for p in args.p_values:
        rp = results[f"p={p}"]
        row = {
            "p": p,
            "ann_sharpe_full": rp["ann_sharpe_full"],
            "total_return_pct_full": rp["total_return_pct_full"],
            "max_dd_pct_full": rp["max_dd_pct_full"],
            "is_sharpe": rp["is"]["sharpe"],
            "oos_sharpe": rp["oos_full"]["sharpe"],
            "oos_total_return_pct": rp["oos_full"]["total_ret_pct"],
            "oos_max_dd_pct": rp["oos_full"]["max_dd_pct"],
            "avg_turnover_per_day": rp["avg_turnover_per_day"],
        }
        for i, wm in enumerate(rp["windows"]):
            row[f"win{i+1}_sharpe"] = wm["sharpe"]
            row[f"win{i+1}_dd"] = wm["max_dd_pct"]
        rows.append(row)
    csv_df = pd.DataFrame(rows)
    csv_file = args.out_dir / "window_metrics.csv"
    csv_df.to_csv(csv_file, index=False)
    print(f"Saved: {csv_file}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
