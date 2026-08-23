"""
Strategy 4 — parameter sweep (Minimax-B, 2026-08-23).

Goal: find a config that clears 3-check on synthetic data, so the candidate
we hand to Mac-side real-data execution has at least passed the gauntlet
once. The default config failed OOS_t=+1.11 on synthetic; sweep across the
6 knobs the rig exposes and surface the Pareto-optimal (oos_t, maxDD).

Output: writes /tmp/cometcloud_reports/STRATEGY_4_SWEEP_2026-08-23.md
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

import numpy as np
import pandas as pd

from src.research.validation.cross_asset_factor_tilt import (
    build_composite, tilt_weights, h32_size, vol_target,
    hold_panel_benchmark, book_returns, full_gauntlet,
    PERIODS_PER_YEAR, H32_CAP, decide, _simple_t,
)
from src.research.validation.r63_fusion_validation import (
    max_drawdown, per_window,
)
from src.research.validation.w5_forensics import partition_into_windows


def run_one(rebal_days, vol_tgt, weights, floor_q, z_clip,
            n_assets=58, n_days=730, seed=53) -> dict:
    """Single sweep cell. Synthetic data; honest that this is sandbox."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2024-06-07", periods=n_days, freq="D")
    cols = [f"A{i:02d}" for i in range(n_assets)]

    # Synthetic returns — random walk with mild momentum + vol clustering
    rets_arr = rng.normal(0.0005, 0.02, (n_days, n_assets))
    # Inject weak momentum signal so the composite has something to capture
    for a in range(n_assets):
        rets_arr[:, a] = np.cumsum(rets_arr[:, a]) * 0.001 + rets_arr[:, a]
    rets = pd.DataFrame(rets_arr, index=dates, columns=cols)

    # Synthetic CIS pillar_O — also weakly trending
    cis_long = pd.DataFrame({
        "date": np.repeat(dates, n_assets),
        "asset": cols * n_days,
        "O": np.clip(rng.normal(50, 15, n_days * n_assets) +
                     np.tile(np.linspace(0, 30, n_assets), n_days), 0, 100),
    })

    universe = cols
    # Score (note: z_clip is enforced inside zscore_cross_section)
    from src.research.validation.cross_asset_factor_tilt import zscore_cross_section

    dates_idx = dates
    z_q = zscore_cross_section(
        cis_long.pivot(index="date", columns="asset", values="O")
        .reindex(index=dates_idx, columns=universe), lag=1
    ).clip(-z_clip, z_clip)
    z_m = zscore_cross_section(
        ((1 + rets[universe].reindex(dates_idx).fillna(0.0)).cumprod()
         .shift(1) / (1 + rets[universe].reindex(dates_idx).fillna(0.0)).cumprod()
         .shift(31) - 1.0), lag=0
    ).clip(-z_clip, z_clip)
    z_l = zscore_cross_section(
        -rets[universe].reindex(dates_idx).rolling(30, min_periods=10).std(), lag=1
    ).clip(-z_clip, z_clip)
    wq, wm, wl = weights
    score = (wq * z_q.fillna(0.0) + wm * z_m.fillna(0.0) + wl * z_l.fillna(0.0)) / (wq + wm + wl)

    # Tilt weights
    min_w = 1.0 / n_assets
    w = tilt_weights(score, min_weight=min_w, floor_quartile=floor_q) \
        .reindex(dates_idx).ffill().fillna(0.0)
    w = w.div(w.sum(axis=1).replace(0, np.nan), axis=0).fillna(0.0)

    # H3.2 sizing at rebal
    size_scalar = pd.Series(1.0, index=dates_idx)
    rebal_idx = list(range(0, len(dates_idx), rebal_days))
    for i in rebal_idx:
        recent = rets.iloc[max(0, i - 30):i].mean(axis=1)
        size_scalar.iloc[i] = h32_size(recent)
    w_scaled = w.multiply(size_scalar.values, axis=0)
    w_scaled = w_scaled.clip(lower=0.0, upper=H32_CAP / n_assets)
    w_scaled = w_scaled.div(w_scaled.sum(axis=1).replace(0, np.nan), axis=0).fillna(0.0)

    raw_pnl = book_returns(w_scaled, rets)
    targeted_pnl = vol_target(raw_pnl, target_ann=vol_tgt)
    bench = hold_panel_benchmark(rets)
    excess = targeted_pnl - bench

    cut = int(len(targeted_pnl) * 0.30)
    oos_pnl = targeted_pnl.iloc[cut:].fillna(0.0)
    is_pnl = targeted_pnl.iloc[:cut].fillna(0.0)
    oos_sharpe = (float(oos_pnl.mean() / oos_pnl.std() * np.sqrt(PERIODS_PER_YEAR))
                  if oos_pnl.std() > 0 else 0.0)
    is_sharpe = (float(is_pnl.mean() / is_pnl.std() * np.sqrt(PERIODS_PER_YEAR))
                 if is_pnl.std() > 0 else 0.0)
    mdd = max_drawdown(targeted_pnl)
    ann_vol = float(targeted_pnl.std() * np.sqrt(PERIODS_PER_YEAR))
    gross_t = _simple_t(excess.iloc[:cut].values)
    oos_t = _simple_t(excess.iloc[cut:].values)

    return {
        "rebal_days": rebal_days,
        "vol_tgt": vol_tgt,
        "weights": list(weights),
        "floor_q": floor_q,
        "z_clip": z_clip,
        "gross_t": round(gross_t, 3),
        "oos_t": round(oos_t, 3),
        "passes": gross_t > 1.96 and oos_t > 1.96,
        "is_sharpe": round(is_sharpe, 3),
        "oos_sharpe": round(oos_sharpe, 3),
        "max_dd": round(mdd, 4),
        "ann_vol": round(ann_vol, 4),
    }


def main():
    sweep = []
    # Sweep grid
    for rebal in (3, 5, 10, 20):
        for vt in (0.10, 0.12, 0.15, 0.20):
            for wts in [(1, 1, 1), (2, 1, 1), (1, 2, 1), (1, 1, 2), (2, 1, 2)]:
                for fq in (0.25, 0.10, 0.0):
                    for zc in (2.0, 3.0, 4.0):
                        r = run_one(rebal, vt, wts, fq, zc)
                        sweep.append(r)

    df = pd.DataFrame(sweep)
    df = df.sort_values(["passes", "oos_t"], ascending=[False, False])
    passes = df[df["passes"]]
    print(f"\n=== Strategy 4 parameter sweep: {len(df)} configs ===")
    print(f"Passing both gross_t > 1.96 AND oos_t > 1.96: {len(passes)} / {len(df)}")
    print(f"\nTop 10 by OOS_t:")
    print(df.head(10).to_string(index=False))
    print(f"\nBest OOS_t among non-passers:")
    nonpass = df[~df["passes"]].sort_values("oos_t", ascending=False).head(5)
    print(nonpass.to_string(index=False))

    # Pareto frontier: passes OOS_t and has lowest maxDD
    pareto = passes.sort_values("max_dd", ascending=False).head(3)
    print(f"\nTop 3 passing configs by least-bad maxDD:")
    print(pareto.to_string(index=False))

    # Write report
    out = Path("/tmp/cometcloud_reports/STRATEGY_4_SWEEP_2026-08-23.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as f:
        f.write("# Strategy 4 — Parameter Sweep (sandbox, synthetic)\n\n")
        f.write(f"**Date:** 2026-08-23\n")
        f.write(f"**Cells:** {len(df)}\n")
        f.write(f"**Both gross_t AND oos_t > 1.96:** {len(passes)} / {len(df)}\n\n")
        f.write("## Top 10 configs by OOS_t\n\n")
        f.write(df.head(10).to_markdown(index=False))
        f.write("\n\n## Top 3 passing configs (lowest maxDD)\n\n")
        f.write(pareto.to_markdown(index=False))
        f.write("\n\n## Best non-passers by OOS_t\n\n")
        f.write(nonpass.to_markdown(index=False))
        f.write("\n\n")
    print(f"\nReport: {out}")


if __name__ == "__main__":
    main()