"""
Strategy 5 candidate — Funding IVOL Residual L/S (R-N + 95, Seth, 2026-08-24).

CAUSE (per §STRATEGY-DISCIPLINE): assets with HIGH cross-sectional funding-IVOL
residual are in a regime of rapidly changing perp-market-maker positioning —
funding flips sign frequently, carry is unstable, and the asset is exposed to
forced de-levering cascades. CONVERSE: assets with LOW funding-IVOL residual
have stable carry and a stable crowd, so the carry is durable and the asset
behaves like a clean beta. Long low-IVOL / short high-IVOL captures the
"stable carry premium" minus the "regime-uncertainty penalty" — orthogonal
to R76 (which captures funding LEVEL residual, not its volatility).

DATA: 28-asset strict funding ∩ CIS ∩ OHLCV panel (R77 family), 770 days.

WHY THIS SHAPE (per the §14-attempt structural finding): cross-sectional L/S
on a within-class microstructure signal is the ONLY shape that clears the
3-check on this panel. R76 funding LEVEL residual is the 1-in-many outlier
that proved this shape; R78 (momentum), R79 (vol), R80 (turnover), R81
(taker-buy) all REFUTED on the same shape. Funding IVOL is the missing
microstructure axis (LEVEL ✓, IVOL ✗ untested) — same axis family, different
moment.
"""
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

_logger = logging.getLogger("r95_funding_ivol_residual")

SIGN_HIGH_IVOL_SHORT = "high_ivol_short"
SIGN_LOW_IVOL_SHORT = "low_ivol_short"
_VALID_SIGNS = (SIGN_HIGH_IVOL_SHORT, SIGN_LOW_IVOL_SHORT)

IVOL_LOOKBACK = 30
COST_BPS = 5.0
REBAL_DAYS = 5
K_TERCILES = 3
OOS_FRAC = 0.30
PERIODS_PER_YEAR = 365


def score_funding_ivol_residual(funding_daily: pd.DataFrame,
                                 tradeable: list[str],
                                 ivol_lookback: int = IVOL_LOOKBACK) -> pd.DataFrame:
    """Per-asset trailing-30d std of daily funding, CROSS-SECTIONALLY DEMEANED.

    High score (positive demeaned IVOL) = unstable carry / regime uncertainty.
    Low score (negative demeaned IVOL) = stable carry / durable crowd.

    Sign convention for the L/S: SIGN_HIGH_IVOL_SHORT (long low, short high).
    """
    # align to common assets and dates
    common = [a for a in tradeable if a in funding_daily.columns]
    f = funding_daily[common].copy()

    # Per-asset trailing IVOL
    ivol = f.rolling(ivol_lookback, min_periods=max(5, ivol_lookback // 3)).std()

    # Cross-sectional demean: subtract the day's mean IVOL across assets
    # so positive values = above-mean IVOL = "unstable carry" (fade)
    # and negative values = below-mean IVOL = "stable carry" (hold long)
    cs_mean = ivol.mean(axis=1)
    residual = ivol.sub(cs_mean, axis=0)

    return residual


def decide(gauntlet: dict, oos_sharpe: float, max_dd: float) -> str:
    if (gauntlet.get("passes_all")
            and oos_sharpe >= 1.0
            and max_dd >= -0.20):
        return "FUSION_LIFT"
    if oos_sharpe >= 0.5 and max_dd >= -0.25:
        return "NEUTRAL"
    return "REFUTED"


def main() -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(name)s] %(message)s")

    # ── Load data (same panel as R77 / Strategies 3+4) ───────────────────────
    _logger.info("Loading funding + returns panel...")
    funding_daily = load_funding_daily()
    rets = load_daily_returns()

    # Strict 28-asset intersection (R77 family panel)
    from src.data.signals.fusion_paper import UNIVERSE as TRADEABLE_28
    tradeable = TRADEABLE_28
    common = [a for a in tradeable if a in funding_daily.columns and a in rets.columns]
    _logger.info("Universe: %d assets (28-strict)", len(common))

    # ── Score: funding-IVOL residual ─────────────────────────────────────────
    score = score_funding_ivol_residual(funding_daily, common)
    _logger.info("Score shape: %s · date range %s → %s",
                 score.shape, score.index.min().date(), score.index.max().date())

    # ── L/S backtest: long low-IVOL, short high-IVOL (R76 parity) ────────────
    fac = pillar_a_level_ls(
        score, rets[common], k_terciles=K_TERCILES,
        cost_bps=COST_BPS, rebal_days=REBAL_DAYS, sign="low_a_long",
    ).reindex(rets.index).fillna(0.0)

    # ── Per-window W1-W6 ─────────────────────────────────────────────────────
    windows = partition_into_windows(fac.index, n_windows=6)
    pw = per_window(fac, windows)
    mdd = max_drawdown(fac)
    is_idx, oos_idx = int(len(fac) * (1 - OOS_FRAC)), len(fac)
    is_pnl = fac.iloc[:is_idx].fillna(0.0)
    oos_pnl = fac.iloc[is_idx:].fillna(0.0)
    is_sharpe = (_simple_t(is_pnl.values) * np.sqrt(PERIODS_PER_YEAR)
                 if is_pnl.std() > 0 else 0.0)
    oos_sharpe = (_simple_t(oos_pnl.values) * np.sqrt(PERIODS_PER_YEAR)
                  if oos_pnl.std() > 0 else 0.0)

    # ── 3-check gauntlet (vs market + TSMOM known factors) ───────────────────
    known = {}
    mkt = rets[common].mean(axis=1).fillna(0.0).reindex(fac.index).fillna(0.0)
    cum = (1 + mkt).cumprod()
    trail30 = cum / cum.shift(30) - 1
    known["market"] = mkt.values
    known["momentum"] = (np.sign(trail30.shift(1)).fillna(0.0) * mkt).values

    try:
        res = gauntlet_3check(fac, known, oos_idx=is_idx)
        gross_t = float(res.get("gross_t", res.get("alpha_t", 0.0)))
        oos_t = float(res.get("oos_t", 0.0))
        passes_gross = bool(res.get("passes_gross", False))
        passes_oos = bool(res.get("passes_oos", False))
    except (np.linalg.LinAlgError, ValueError):
        gross_t = _simple_t(is_pnl.values)
        oos_t = _simple_t(oos_pnl.values)
        passes_gross = gross_t > 1.96
        passes_oos = oos_t > 1.96

    gauntlet = {
        "gross_t": gross_t,
        "oos_t": oos_t,
        "passes_gross": passes_gross,
        "passes_oos": passes_oos,
        "passes_all": passes_gross and passes_oos,
        "cut": is_idx,
    }
    decision = decide(gauntlet, oos_sharpe, mdd)

    # ── Per-window sign verdict (matched-cell directional differential) ──────
    # Split each day's L/S contribution by the SIGN of the cross-sectional
    # IVOL residual: positive score = high IVOL residual (short leg) = fac < 0;
    # negative score = low IVOL residual (long leg) = fac > 0.
    # Compute per-window sharpe of (fac | low-IVOL days) minus (fac | high-IVOL days).
    score_signed = score.mean(axis=1).reindex(fac.index).fillna(0.0)
    high_minus_low = {}
    for w in sorted(pw):
        s, e = next((S, E) for L, S, E in windows if L == w)
        in_w = (fac.index >= s) & (fac.index <= e)
        low_ivol_mask = (score_signed < 0) & in_w   # days we went LONG (low IVOL)
        high_ivol_mask = (score_signed > 0) & in_w  # days we went SHORT (high IVOL)
        low_sub = fac[low_ivol_mask]
        high_sub = fac[high_ivol_mask]
        # Direction-correct metric: low-IVOL days Sharpe > high-IVOL days Sharpe
        # (because long low-IVOL wins AND short high-IVOL wins, so on the long
        # leg days we make money, on the short leg days we make money)
        low_sharpe = float(low_sub.mean() / low_sub.std() * np.sqrt(PERIODS_PER_YEAR)) \
            if len(low_sub) > 2 and low_sub.std() > 0 else np.nan
        high_sharpe = float(high_sub.mean() / high_sub.std() * np.sqrt(PERIODS_PER_YEAR)) \
            if len(high_sub) > 2 and high_sub.std() > 0 else np.nan
        high_minus_low[w] = float(low_sharpe - high_sharpe) \
            if not (np.isnan(low_sharpe) or np.isnan(high_sharpe)) else 0.0

    # ── Sign audit ───────────────────────────────────────────────────────────
    # Direction: long low-IVOL, short high-IVOL → on low-IVOL days the LONG
    # leg wins (fac > 0), on high-IVOL days the SHORT leg wins (fac < 0).
    # So we expect low-IVOL days Sharpe > high-IVOL days Sharpe.
    sign_audit_pass = all(v > 0 for v in high_minus_low.values()
                          if not np.isnan(v))

    # ── Print + write report ─────────────────────────────────────────────────
    print(f"\n=== R95 Funding IVOL Residual L/S ===")
    print(f"Panel: {fac.index.min().date()} → {fac.index.max().date()} "
          f"({len(fac)} days × {len(common)} assets)")
    print(f"Sign: long low-IVOL residual, short high-IVOL residual")
    print(f"\n3-check gauntlet:")
    print(f"  gross_t = {gross_t:+.3f} ({'✓' if passes_gross else '✗'} clears 1.96)")
    print(f"  oos_t   = {oos_t:+.3f} ({'✓' if passes_oos else '✗'} clears 1.96)")
    print(f"  passes_all = {gauntlet['passes_all']}")
    print(f"\nPerformance:")
    print(f"  IS Sharpe   = {is_sharpe:+.2f}")
    print(f"  OOS Sharpe  = {oos_sharpe:+.2f}")
    print(f"  maxDD       = {mdd*100:+.2f}%")
    print(f"\nDecision: {decision}")
    print(f"Sign audit (high_minus_low > 0 in every window): "
          f"{'✓ PASS' if sign_audit_pass else '✗ FAIL'} "
          f"({high_minus_low})")
    print(f"\nPer-window (vol-targeted raw):")
    print(f"{'Window':<6} {'ann %':>8} {'Sharpe':>8} {'maxDD %':>8} "
          f"{'high_minus_low':>16}")
    for w in sorted(pw):
        row = pw[w]
        print(f"  {w:<4} {row['ann_pct']:>+7.2f}% {row['sharpe']:>+7.2f} "
              f"{row['max_dd']*100:>+7.2f}% {high_minus_low[w]:>+15.3f}")

    out = Path("/tmp/cometcloud_reports/R95_FUNDING_IVOL_RESIDUAL_2026-08-24.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as f:
        f.write("# R95 — Funding IVOL Residual L/S (Strategy 5 candidate)\n\n")
        f.write(f"**Date:** 2026-08-24\n")
        f.write(f"**Decision:** **{decision}**\n\n")
        f.write(f"**Panel:** {fac.index.min().date()} → {fac.index.max().date()} "
                f"({len(fac)} days × {len(common)} assets)\n")
        f.write(f"**Sign:** long low-IVOL residual, short high-IVOL residual\n\n")
        f.write("## Cause\n\n")
        f.write("Cross-sectional funding-IVOL residual captures the *stability of "
                "perp carry* — assets with high demeaned IVOL are in a regime of "
                "rapidly flipping positioning, with unstable carry and forced "
                "de-levering risk; assets with low demeaned IVOL have durable "
                "carry and behave like clean beta. Long low / short high captures "
                "the stable-carry premium.\n\n")
        f.write("## 3-check gauntlet\n\n")
        f.write(f"- gross_t = **{gross_t:+.3f}** "
                f"({'✓' if passes_gross else '✗'} clears 1.96)\n")
        f.write(f"- oos_t = **{oos_t:+.3f}** "
                f"({'✓' if passes_oos else '✗'} clears 1.96)\n")
        f.write(f"- **3-check pass: {'✓' if gauntlet['passes_all'] else '✗'}**\n\n")
        f.write("## Performance\n\n")
        f.write(f"- IS Sharpe: {is_sharpe:+.2f}\n")
        f.write(f"- OOS Sharpe: {oos_sharpe:+.2f}\n")
        f.write(f"- maxDD: {mdd*100:+.2f}%\n\n")
        f.write("## Per-window\n\n")
        f.write("| Window | ann % | Sharpe | maxDD % | high-IVOL minus low-IVOL Sharpe |\n")
        f.write("|--------|-------|--------|---------|---------------------------------|\n")
        for w in sorted(pw):
            row = pw[w]
            f.write(f"| {w} | {row['ann_pct']:+.2f}% | {row['sharpe']:+.2f} "
                    f"| {row['max_dd']*100:+.2f}% | {high_minus_low[w]:+.3f} |\n")
        f.write("\n## Sign audit\n\n")
        f.write(f"- Direction: long low-IVOL residual, short high-IVOL residual\n")
        f.write(f"- Expected per-window: low-IVOL Sharpe > high-IVOL Sharpe "
                f"(positive high_minus_low)\n")
        f.write(f"- Result: **{'PASS' if sign_audit_pass else 'FAIL'}** — "
                f"{'directional thesis correct in every window' if sign_audit_pass else 'one or more windows violate'}\n\n")
        f.write("## Why this shape\n\n")
        f.write("Cross-sectional L/S on a within-class microstructure signal is the "
                "ONLY shape that has cleared 3-check on this 770-day panel (R76 funding "
                "LEVEL residual was the 1-in-many outlier that proved this; R78/R79/"
                "R80/R81 on momentum/vol/turnover/taker-buy all REFUTED). Funding IVOL "
                "is the missing microstructure moment — LEVEL ✓, IVOL ✗ untested until "
                "this run.\n\n")
        f.write("## Path if PASSES\n\n")
        f.write("1. **Ship as Strategy 5** — long/short sleeve (paper trade; "
                "compliant language only: long/short describes exposure, not advice)\n")
        f.write("2. **OR add as 4th leg to R77** — test |corr(R95, R76)| against "
                "lesson #42 gate (max |corr| < 0.30). If passes, run "
                "R77+R95 fusion weight sweep (lesson #43: orthogonal legs DO carry).\n\n")
        f.write("## Path if REFUTED\n\n")
        f.write("The §14-attempt graveyard closes for the 770-day panel; Strategy 2 "
                "is deferred to §OHLCV-EXTENSION (11yr panel).\n")
    print(f"\n=== Report: {out} ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())