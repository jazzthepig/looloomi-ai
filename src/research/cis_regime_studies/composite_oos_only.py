"""
Composite with OOS-isolated LS v1 (Seth 2026-07-17 refactor → Minimax-B re-run 2026-07-17)

Replaces the LS v1 sleeve in `composite_6y.py` (which used the dedup-but-still-mixed NAV
from `extract_per_bar_nav.py`) with the proper OOS-isolated NAV from `per_day_nav_oos_only.parquet`.

OOS isolation: filter `ts_opened >= oos_start` per walk-forward window, then dedup by
(instrument, ts_closed) — same discipline as `oos_isolation.py`.

Inputs:
- LS v1 (OOS-isolated): reports/multi_window_baseline_spot_cis_off/2026-07-16/per_day_nav_oos_only.parquet
- Causal sleeve (6y, kwin=7, 5bps): reports/causal_sleeve/2026-07-17/nav_deploy_6y.parquet
- Cash (T-bill compounding): reports/cash_sleeve/2026-07-16/nav.parquet

Output:
- reports/composite_oos_only/<date>/{composite_oos_only.json, weights.md}
"""
from __future__ import annotations

import argparse
import itertools
import json
import math
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd


def compute_metrics(nav: pd.Series) -> dict:
    """Annualized Sharpe, MaxDD, CAGR from a NAV series."""
    if len(nav) < 30:
        return {"cagr": None, "sharpe": None, "max_dd": None, "final_nav": None}
    # Daily returns
    rets = nav.pct_change().dropna()
    if len(rets) < 10 or rets.std() == 0:
        return {"cagr": None, "sharpe": None, "max_dd": None, "final_nav": float(nav.iloc[-1])}
    # Annualized Sharpe (sqrt(252) for daily equity returns)
    sharpe = float(rets.mean() / rets.std() * np.sqrt(252))
    # CAGR from first/last NAV
    days = (nav.index[-1] - nav.index[0]).days
    cagr = float((nav.iloc[-1] / nav.iloc[0]) ** (365.0 / days) - 1) if days > 0 else None
    # Max DD
    peak = nav.cummax()
    dd = (peak - nav) / peak
    max_dd = float(dd.max() * 100)
    return {
        "cagr": round(cagr, 4) if cagr is not None else None,
        "sharpe": round(sharpe, 3),
        "max_dd": round(max_dd, 2),
        "final_nav": round(float(nav.iloc[-1]), 2),
    }


def build_composite(ls: pd.Series, cs: pd.Series, cash: pd.Series,
                    w_ls: float, w_cs: float, w_cash: float) -> pd.Series:
    """Build composite NAV at given weights.

    Each sleeve's NAV starts at $10k. Composite starts at $10k × Σw = $10k.
    On day t: composite_ret = w_ls × (ls[t]/ls[t-1] - 1) + w_cs × (cs[t]/cs[t-1] - 1) + w_cash × (cash[t]/cash[t-1] - 1)
    """
    if abs((w_ls + w_cs + w_cash) - 1.0) > 1e-6:
        raise ValueError(f"Weights must sum to 1.0, got {w_ls + w_cs + w_cash}")

    # All to 1.0 weights internally; we'll scale by starting NAV
    df = pd.DataFrame({'ls': ls, 'cs': cs, 'cash': cash}).sort_index().ffill().dropna()
    if len(df) < 30:
        return pd.Series(dtype=float)
    # Daily returns per sleeve
    rets = df.pct_change().fillna(0.0)
    # Weighted return
    composite_ret = w_ls * rets['ls'] + w_cs * rets['cs'] + w_cash * rets['cash']
    # NAV at $10k starting
    nav = 10_000 * (1 + composite_ret).cumprod()
    nav.iloc[0] = 10_000  # explicit
    return nav


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--ls-nav', type=Path,
                    default=Path('/Users/sbb/Projects/looloomi-ai/reports/multi_window_baseline_spot_cis_off/2026-07-16/per_day_nav_oos_only.parquet'))
    ap.add_argument('--cs-nav', type=Path,
                    default=Path('/Users/sbb/Projects/looloomi-ai/reports/causal_sleeve/2026-07-17/nav_deploy_6y.parquet'))
    ap.add_argument('--cash-nav', type=Path,
                    default=Path('/Users/sbb/Projects/looloomi-ai/reports/cash_sleeve/2026-07-16/nav.parquet'))
    ap.add_argument('--out-dir', type=Path, required=True)
    args = ap.parse_args(argv)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")

    # Load NAVs
    ls = pd.read_parquet(args.ls_nav)['nav']
    cs = pd.read_parquet(args.cs_nav)['nav']
    cash = pd.read_parquet(args.cash_nav)['nav']

    print('=== Loaded sleeves ===')
    print(f'  LS v1 (OOS-isolated): {ls.index[0].date()} → {ls.index[-1].date()}, n={len(ls)}, '
          f'final=${ls.iloc[-1]:.2f} ({((ls.iloc[-1]/ls.iloc[0])-1)*100:+.2f}%)')
    print(f'  Causal sleeve:        {cs.index[0].date()} → {cs.index[-1].date()}, n={len(cs)}, '
          f'final=${cs.iloc[-1]:.2f} ({((cs.iloc[-1]/cs.iloc[0])-1)*100:+.2f}%)')
    print(f'  Cash sleeve:          {cash.index[0].date()} → {cash.index[-1].date()}, n={len(cash)}, '
          f'final=${cash.iloc[-1]:.2f} ({((cash.iloc[-1]/cash.iloc[0])-1)*100:+.2f}%)')

    # Per-sleeve monthly correlations on intersection
    monthly = pd.DataFrame({
        'ls': ls.resample('M').last(),
        'cs': cs.resample('M').last(),
        'cash': cash.resample('M').last(),
    }).dropna()
    monthly_ret = monthly.pct_change().dropna()
    print(f'\n=== Monthly correlations (intersection) ===')
    print(monthly_ret.corr().round(4))
    print(f'  N months: {len(monthly_ret)}')

    # Per-sleeve metrics on intersection
    print('\n=== Per-sleeve metrics (master intersection) ===')
    master_start = max(ls.index[0], cs.index[0], cash.index[0])
    master_end = min(ls.index[-1], cs.index[-1], cash.index[-1])
    print(f'  Master index: {master_start.date()} → {master_end.date()}')

    # Reindex all to common daily index, forward fill
    idx = pd.date_range(master_start, master_end, freq='D')
    ls_i = ls.reindex(idx).ffill()
    cs_i = cs.reindex(idx).ffill()
    cash_i = cash.reindex(idx).ffill()

    print(f'\n  LS v1 (master intersection):   {compute_metrics(ls_i)}')
    print(f'  Causal (master intersection):  {compute_metrics(cs_i)}')
    print(f'  Cash (master intersection):    {compute_metrics(cash_i)}')

    # Weight sweep
    print('\n=== Weight sweep ===')
    grid = []
    for w_ls in [i/100 for i in range(0, 101, 5)]:
        for w_cs in [i/100 for i in range(0, 101, 5)]:
            w_cash = 1.0 - w_ls - w_cs
            if w_cash < 0 or w_cash > 1:
                continue
            nav = build_composite(ls_i, cs_i, cash_i, w_ls, w_cs, w_cash)
            m = compute_metrics(nav)
            grid.append({
                'w_ls': round(w_ls, 2),
                'w_cs': round(w_cs, 2),
                'w_cash': round(w_cash, 2),
                **m,
            })
    grid_df = pd.DataFrame(grid)

    # Top 10 by Sharpe
    top_sharpe = grid_df.dropna(subset=['sharpe']).nlargest(10, 'sharpe')
    # Top 10 by MaxDD (least negative)
    top_dd = grid_df.dropna(subset=['max_dd']).nsmallest(10, 'max_dd')
    # Top 10 by CAGR
    top_cagr = grid_df.dropna(subset=['cagr']).nlargest(10, 'cagr')

    print('\nTop 10 by Sharpe:')
    print(top_sharpe.to_string(index=False))
    print('\nTop 10 by MaxDD (least negative):')
    print(top_dd.to_string(index=False))
    print('\nTop 10 by CAGR:')
    print(top_cagr.to_string(index=False))

    # Recommended allocations — the old 45/15/40, 50/20/30, 40/30/30 from the previous report
    print('\n=== Specific allocations (from previous report) ===')
    for w in [(0.45, 0.15, 0.40), (0.40, 0.30, 0.30), (0.50, 0.20, 0.30), (0.60, 0.25, 0.15)]:
        nav = build_composite(ls_i, cs_i, cash_i, *w)
        m = compute_metrics(nav)
        print(f'  {w[0]:.0%}/{w[1]:.0%}/{w[2]:.0%}: {m}')

    # Save results
    result = {
        'date': today,
        'inputs': {
            'ls_nav_path': str(args.ls_nav),
            'cs_nav_path': str(args.cs_nav),
            'cash_nav_path': str(args.cash_nav),
        },
        'master_index': {
            'start': str(master_start.date()),
            'end': str(master_end.date()),
            'n_days': len(idx),
        },
        'per_sleeve_metrics': {
            'ls_v1_oos_only': compute_metrics(ls_i),
            'causal': compute_metrics(cs_i),
            'cash': compute_metrics(cash_i),
        },
        'monthly_correlations': monthly_ret.corr().round(4).to_dict(),
        'top_10_sharpe': top_sharpe.to_dict(orient='records'),
        'top_10_maxdd': top_dd.to_dict(orient='records'),
        'top_10_cagr': top_cagr.to_dict(orient='records'),
        'all_weights': grid,
    }
    out_json = args.out_dir / 'composite_oos_only.json'
    out_json.write_text(json.dumps(result, indent=2, default=str))
    print(f'\nWrote: {out_json}')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())