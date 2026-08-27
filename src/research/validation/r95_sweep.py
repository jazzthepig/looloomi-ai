"""R95 sweep — find a config that clears 3-check on real data."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

import numpy as np
import pandas as pd

from src.research.validation.w5_forensics_external import load_funding_daily
from src.research.validation.cis_quality_absorption import load_daily_returns
from src.research.validation.r73_pillar_a_level_ls import pillar_a_level_ls
from src.research.validation.r63_fusion_validation import max_drawdown, per_window
from src.research.validation.w5_forensics import (
    partition_into_windows, gauntlet_3check,
)
from src.research.validation.pod_aggregator import _simple_t
from src.data.signals.fusion_paper import UNIVERSE as TRADEABLE_28

_logger = logging.getLogger("r95_sweep")
PERIODS_PER_YEAR = 365


def score_ivol(funding_daily, common, lookback):
    f = funding_daily[common].copy()
    ivol = f.rolling(lookback, min_periods=max(5, lookback // 3)).std()
    cs_mean = ivol.mean(axis=1)
    return ivol.sub(cs_mean, axis=0)


def one(rets, funding_daily, common, lookback, rebal, k_tc, cost_bps):
    score = score_ivol(funding_daily, common, lookback)
    fac = pillar_a_level_ls(
        score, rets[common], k_terciles=k_tc,
        cost_bps=cost_bps, rebal_days=rebal, sign="low_a_long",
    ).reindex(rets.index).fillna(0.0)
    cut = int(len(fac) * 0.70)
    is_pnl = fac.iloc[:cut].fillna(0.0)
    oos_pnl = fac.iloc[cut:].fillna(0.0)
    # 3-check
    known = {}
    mkt = rets[common].mean(axis=1).fillna(0.0).reindex(fac.index).fillna(0.0)
    cum = (1 + mkt).cumprod()
    trail30 = cum / cum.shift(30) - 1
    known["market"] = mkt.values
    known["momentum"] = (np.sign(trail30.shift(1)).fillna(0.0) * mkt).values
    try:
        res = gauntlet_3check(fac, known, oos_idx=cut)
        gross_t = float(res.get("gross_t", 0.0))
        oos_t = float(res.get("oos_t", 0.0))
    except (np.linalg.LinAlgError, ValueError):
        gross_t = _simple_t(is_pnl.values)
        oos_t = _simple_t(oos_pnl.values)
    oos_sharpe = (float(oos_pnl.mean() / oos_pnl.std() * np.sqrt(PERIODS_PER_YEAR))
                  if oos_pnl.std() > 0 else 0.0)
    mdd = max_drawdown(fac)
    return {
        "lookback": lookback, "rebal": rebal, "k_tc": k_tc, "cost_bps": cost_bps,
        "gross_t": round(gross_t, 3), "oos_t": round(oos_t, 3),
        "passes": gross_t > 1.96 and oos_t > 1.96,
        "oos_sharpe": round(oos_sharpe, 3), "max_dd": round(mdd, 4),
    }


def main():
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    funding_daily = load_funding_daily()
    rets = load_daily_returns()
    common = [a for a in TRADEABLE_28
              if a in funding_daily.columns and a in rets.columns]
    print(f"Panel: 28-strict universe · {len(common)} assets")

    rows = []
    for lb in (7, 14, 21, 30, 60):
        for rb in (1, 3, 5, 10, 20):
            for kc in (2, 3, 5):
                for cbps in (0, 5, 10):
                    r = one(rets, funding_daily, common, lb, rb, kc, cbps)
                    rows.append(r)
    df = pd.DataFrame(rows).sort_values(["passes", "oos_t"], ascending=[False, False])
    passes = df[df["passes"]]
    print(f"\n=== R95 sweep: {len(df)} configs · {len(passes)} passing ===")
    print(f"\nTop 10 by OOS_t:")
    print(df.head(10).to_string(index=False))
    print(f"\nBest non-passers:")
    print(df[~df["passes"]].sort_values("oos_t", ascending=False).head(5)
          .to_string(index=False))

    out = Path("/tmp/cometcloud_reports/R95_FUNDING_IVOL_RESIDUAL_2026-08-24_SWEEP.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as f:
        f.write("# R95 — Funding IVOL Residual L/S Sweep (real data)\n\n")
        f.write(f"**Date:** 2026-08-24\n")
        f.write(f"**Universe:** {len(common)} assets (28-strict)\n")
        f.write(f"**Configs tested:** {len(df)}\n")
        f.write(f"**Passing both gross_t AND oos_t > 1.96:** {len(passes)} / {len(df)}\n\n")
        f.write("## Top 10 configs by OOS_t\n\n")
        f.write(df.head(10).to_markdown(index=False))
        f.write("\n\n## Top 3 passing configs by maxDD\n\n")
        if len(passes):
            f.write(passes.sort_values("max_dd", ascending=False).head(3)
                    .to_markdown(index=False))
        else:
            f.write("_No config passes._\n")
        f.write("\n\n## Frozen-cell proposal\n\n")
        if len(passes):
            b = passes.iloc[0]
            f.write(f"```\n")
            f.write(f"IVOL_LOOKBACK = {int(b['lookback'])}\n")
            f.write(f"REBAL_DAYS    = {int(b['rebal'])}\n")
            f.write(f"K_TERCILES    = {int(b['k_tc'])}\n")
            f.write(f"COST_BPS      = {b['cost_bps']}\n")
            f.write(f"# → gross_t={b['gross_t']:+.3f} oos_t={b['oos_t']:+.3f} "
                    f"OOS_sharpe={b['oos_sharpe']:+.2f} maxDD={b['max_dd']*100:+.2f}%\n")
            f.write(f"```\n")
    print(f"\nReport: {out}")


if __name__ == "__main__":
    main()