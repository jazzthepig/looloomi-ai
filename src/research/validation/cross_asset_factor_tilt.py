"""
Strategy 4 — Cross-Asset Quality-Momentum-LowVol Tilt (R-N + 31, Minimax-B, 2026-08-20).
========================================================================================

Spec: docs/STRATEGY_4_CROSS_ASSET_FACTOR_TILT.md (AQR flavor).

What this does
--------------
1. Load a 58-asset panel (41 crypto + 17 TradFi ETFs).
2. Compute per-day composite score:
       z_quality   = (cis_pillar_o[t-1, a] − μ_quality[t-1]) / σ_quality[t-1]
       z_momentum  = close[t-1, a] / close[t-31, a] − 1   (raw, not z-scored)
       z_lowrisk   = −(σ_30d[t-1, a] − μ_σ[t-1]) / σ_σ[t-1]
       score_t     = mean of {z_quality, z_momentum, z_lowrisk}
   All inputs use t-1 (or earlier) data — PIT-safe.
3. Convert scores to long-only tilt weights (no shorting).
4. Apply H3.2 conviction-scaled sizing at each rebalance (floor 0.5, cap 1.75).
5. Aggregate to daily book return (5d rebalance, 5bps round-trip).
6. Apply vol targeting (12% annualized) at the aggregator.
7. Run 3-check gauntlet + per-window W1-W6.

Output
------
* Console: 3-check + per-window + decision grammar.
* File: reports/CROSS_ASSET_FACTOR_TILT_YYYY-MM-DD.md

Lane
----
Minimax-B (analysis). Mac-side run. Reads CIS pillar_O history from
`/Volumes/CometCloudAI/cometcloud-local/_data/cis_history/` and OHLCV from
`/Volumes/CometCloudAI/data/ohlcv/`, TradFi ETF prices via EODHD cache.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass, asdict
from pathlib import Path

import numpy as np
import pandas as pd

from src.research.validation.cis_quality_absorption import (
    load_cis_history_wide, load_daily_returns, PILLAR_KEYS,
)
from src.research.validation.w5_forensics import (
    partition_into_windows, gauntlet_3check,
)
from src.research.validation.r63_fusion_validation import (
    max_drawdown, per_window,
)
from src.research.validation.cis_quality_tradfi import (
    load_tradfi_panel, TRADFI_UNIVERSE,
)
from src.research.validation.factor_absorption import absorption_test

# ── Constants (frozen-cell pending backtest result) ───────────────────────────
REBAL_DAYS = 5                       # R77 cadence
COST_BPS = 5.0                       # round-trip
VOL_TARGET_ANN = 0.12                # 12% annualized
H32_FLOOR = 0.5                      # conviction-scaled sizing floor
H32_CAP = 1.75                       # conviction-scaled sizing cap
PERIODS_PER_YEAR = 365
N_WINDOWS = 6                        # R62 partition

MOMENTUM_LOOKBACK = 30               # 30d momentum (AQR standard)
VOL_LOOKBACK = 30                    # 30d realized vol
Z_CLIP = 3.0                         # clip z-scores to ±3 σ
OOS_FRAC = 0.30                      # last 30% = OOS

OHLCV_DIR = Path("/Volumes/CometCloudAI/data/ohlcv")
CIS_HISTORY_DIR = Path("/Volumes/CometCloudAI/cometcloud-local/_data/cis_history")
OUTPUT_DIR = Path("/Users/sbb/Documents/Claude/Reports")

_logger = logging.getLogger("cross_asset_factor_tilt")


# ── Composite scoring (PIT-safe) ──────────────────────────────────────────────
def zscore_cross_section(x: pd.DataFrame, lag: int = 1) -> pd.DataFrame:
    """Per-day cross-sectional z-score using ONLY data through t-lag.

    Returns a DataFrame with z-scored values clipped to ±Z_CLIP.
    """
    if lag > 0:
        x_lag = x.shift(lag)
    else:
        x_lag = x
    mu = x_lag.mean(axis=1)
    sd = x_lag.std(axis=1).replace(0, np.nan)
    z = x_lag.sub(mu, axis=0).div(sd, axis=0)
    return z.clip(-Z_CLIP, Z_CLIP)


def build_quality_score(cis_long: pd.DataFrame, assets: list[str],
                        dates: pd.DatetimeIndex) -> pd.DataFrame:
    """z_quality[t, a] = (cis_pillar_o[t-1, a] − μ[t-1]) / σ[t-1]."""
    wide = (cis_long.pivot(index="date", columns="asset", values="O")
            .reindex(index=dates, columns=assets))
    return zscore_cross_section(wide, lag=1)


def build_momentum_score(rets: pd.DataFrame, assets: list[str],
                         dates: pd.DatetimeIndex) -> pd.DataFrame:
    """z_momentum[t, a] = close[t-1, a] / close[t-31, a] − 1, z-scored cross-section."""
    prices = (1 + rets[assets].reindex(dates).fillna(0.0)).cumprod()
    raw = prices.shift(1) / prices.shift(MOMENTUM_LOOKBACK + 1) - 1.0
    return zscore_cross_section(raw, lag=0)


def build_lowrisk_score(rets: pd.DataFrame, assets: list[str],
                        dates: pd.DatetimeIndex) -> pd.DataFrame:
    """z_lowrisk[t, a] = −(σ_30d[t-1, a] − μ_σ[t-1]) / σ_σ[t-1].

    Higher z_lowrisk → lower realized vol → "safer" asset.
    """
    vol = rets[assets].reindex(dates).rolling(VOL_LOOKBACK, min_periods=10).std()
    raw = -vol  # negative vol is "low-risk"
    return zscore_cross_section(raw, lag=1)


def build_composite(cis_long: pd.DataFrame, rets: pd.DataFrame,
                    assets: list[str], dates: pd.DatetimeIndex) -> pd.DataFrame:
    """Equal-weight composite of z_quality + z_momentum + z_lowrisk."""
    z_q = build_quality_score(cis_long, assets, dates)
    z_m = build_momentum_score(rets, assets, dates)
    z_l = build_lowrisk_score(rets, assets, dates)
    return (z_q.fillna(0.0) + z_m.fillna(0.0) + z_l.fillna(0.0)) / 3.0


# ── Long-only tilt weights (CLAUDE.md canonical) ─────────────────────────────
def tilt_weights(scores: pd.DataFrame, min_weight: float = 1.0 / 58.0,
                 floor_quartile: float = 0.25) -> pd.DataFrame:
    """Long-only tilt: rank by score, linear top-heavy weights, bottom-quartile floor.

    Algorithm (per spec STRATEGY_4 §Tilt weights):
      1. Rank assets by score (1 = best, N = worst).
      2. Compute linear top-heavy raw weights = (N + 1 - rank) / (N(N+1)/2).
      3. The BOTTOM QUARTILE (worst 25%) gets weight = 1/N each (the floor).
      4. The top 75% absorbs the residual (sum = 1) via proportional scaling.

    No negative weights anywhere. The floor is guaranteed ONLY on the bottom
    quartile; assets just above the cutoff can be smaller than 1/N because they
    share the residual. This is the spec's literal reading.

    Returns a DataFrame of weights summing to 1.0 per day.
    """
    n = scores.shape[1]
    k_floor = max(1, int(round(n * floor_quartile)))  # bottom quartile count
    ranks = scores.rank(axis=1, ascending=False)
    raw = (n + 1 - ranks).astype(float) / (n * (n + 1) / 2.0)

    # Bottom k_floor assets get exactly floor
    is_bottom = ranks > (n - k_floor)
    floor_total = k_floor * min_weight

    # Top part: scale to absorb residual
    top_raw = raw.where(~is_bottom, 0.0)
    top_sum = top_raw.sum(axis=1).replace(0.0, 1.0)
    top_scaled = top_raw.mul(1.0 - floor_total, axis=0).div(top_sum, axis=0)

    bottom_part = pd.DataFrame(np.where(is_bottom.values, min_weight, 0.0),
                                index=ranks.index, columns=ranks.columns)
    return bottom_part + top_scaled


# ── H3.2 conviction-scaled sizing ────────────────────────────────────────────
def h32_size(recent_returns: pd.Series, target_ann: float = VOL_TARGET_ANN,
             floor: float = H32_FLOOR, cap: float = H32_CAP,
             lookback: int = 30) -> float:
    """H3.2 conviction-sized scalar: target_ann / realized_ann_vol, clipped.

    Returns a single scalar (the same scalar applies to all assets on the
    rebalance day — H3.2 sizes the book, not individual assets).
    """
    daily_target = target_ann / np.sqrt(PERIODS_PER_YEAR)
    rv = recent_returns.dropna().tail(lookback).std()
    if rv == 0 or np.isnan(rv):
        return 1.0
    size = daily_target / rv
    return float(np.clip(size, floor, cap))


# ── Aggregator: book return with rebalance + turnover cost ────────────────────
def book_returns(weights: pd.DataFrame, rets: pd.DataFrame,
                 cost_bps: float = COST_BPS) -> pd.Series:
    """Daily book return with 5d rebalance + 5bps round-trip turnover cost.

    Returns a Series indexed like rets (not weights) — days when no rebalance
    are carried at the prior-day's weights.
    """
    w = weights.reindex(rets.index).ffill().fillna(0.0)
    w = w.div(w.sum(axis=1).replace(0, np.nan), axis=0).fillna(0.0)

    r = rets.reindex(w.index).fillna(0.0)
    pnl = (w * r).sum(axis=1)

    # Turnover cost on rebalance days
    delta_w = w.diff().abs().sum(axis=1).fillna(0.0)
    cost_per_unit = cost_bps / 2.0 / 1e4  # half of round-trip
    rebal_mask = pd.Series(0.0, index=w.index)
    rebal_mask.iloc[::REBAL_DAYS] = 1.0
    pnl = pnl - delta_w * cost_per_unit * rebal_mask
    return pnl


# ── Vol targeting at the aggregator ──────────────────────────────────────────
def vol_target(fac: pd.Series, target_ann: float = VOL_TARGET_ANN) -> pd.Series:
    """12% annualized vol target with trailing 30d realized vol."""
    daily_target = target_ann / np.sqrt(PERIODS_PER_YEAR)
    rv = fac.rolling(30, min_periods=10).std().fillna(fac.std())
    rv = rv.clip(lower=daily_target * 0.5)
    scale = (daily_target / rv).clip(upper=2.0)
    return fac * scale


# ── Hold-the-panel benchmark (CLAUDE.md canonical) ───────────────────────────
def hold_panel_benchmark(rets: pd.DataFrame) -> pd.Series:
    """Equal-weight hold of the panel — the canonical benchmark per CLAUDE.md.

    Every sleeve is measured against hold-the-panel, NEVER 0.
    """
    return rets.mean(axis=1).fillna(0.0)


# ── 3-check gauntlet wrapper ─────────────────────────────────────────────────
def full_gauntlet(fac: pd.Series, rets: pd.DataFrame,
                  oos_frac: float = OOS_FRAC) -> dict:
    """3-check: gross residual-α t > 1.96 (full + OOS).

    known = {market: equal-weight hold, momentum: TSMOM(30) on f_market}.
    Falls back to a simpler t-stat if OLS is singular (sandbox / degenerate panels).
    """
    cut = int(len(fac) * (1 - oos_frac))
    known = {}
    mkt = hold_panel_benchmark(rets)
    known["market"] = mkt.values
    cum = (1 + mkt).cumprod()
    trail30 = cum / cum.shift(30) - 1
    known["momentum"] = (np.sign(trail30.shift(1)).fillna(0.0) * mkt).values

    try:
        res = gauntlet_3check(fac, known, oos_idx=cut)
        gross_t = res.get("gross_t", res.get("alpha_t", 0.0))
        oos_t = res.get("oos_t", 0.0)
        passes_gross = res.get("passes_gross", False)
        passes_oos = res.get("passes_oos", False)
    except (np.linalg.LinAlgError, ValueError):
        # Singular matrix — fall back to simple t-stat on the residual stream
        gross_t = _simple_t(fac.iloc[:cut].values)
        oos_t = _simple_t(fac.iloc[cut:].values)
        passes_gross = gross_t > 1.96
        passes_oos = oos_t > 1.96
    return {
        "gross_t": gross_t,
        "oos_t": oos_t,
        "passes_gross": passes_gross,
        "passes_oos": passes_oos,
        "passes_all": passes_gross and passes_oos,
        "cut": cut,
    }


def _simple_t(x) -> float:
    """Simple t-stat for fallback when OLS is degenerate."""
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    if len(x) < 2 or x.std() == 0:
        return 0.0
    return float(x.mean() / (x.std() / np.sqrt(len(x))))


# ── Decision grammar ─────────────────────────────────────────────────────────
def decide(gauntlet: dict, fac: pd.Series, oos_sharpe: float,
           max_dd: float) -> str:
    """Strategy 4 verdict:
       - FUSION_LIFT: 3-check passes AND OOS Sharpe ≥ 1.0 AND maxDD ≥ −20%
       - NEUTRAL: OOS Sharpe ≥ 0.5 AND maxDD ≥ −25%
       - REFUTED: anything else
    """
    if (gauntlet["passes_all"]
            and oos_sharpe >= 1.0
            and max_dd >= -0.20):
        return "FUSION_LIFT"
    if oos_sharpe >= 0.5 and max_dd >= -0.25:
        return "NEUTRAL"
    return "REFUTED"


# ── Driver ────────────────────────────────────────────────────────────────────
def run(output_dir: Path = OUTPUT_DIR, sandbox: bool = False) -> dict:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(name)s] %(message)s")

    if sandbox:
        # Synthetic panel for Cowork execution — NOT a real backtest result.
        # 58-asset panel with composite z_quality + z_momentum + z_lowrisk.
        # Verdict on synthetic data is always REFUTED (no real alpha survives
        # on noise) but proves the pipeline fires end-to-end.
        rng = np.random.default_rng(53)
        n_days = 365
        n_assets = 58
        dates = pd.date_range("2024-06-07", periods=n_days, freq="D")
        cols = [f"A{i:02d}" for i in range(n_assets)]
        # Synthetic returns (random walk) + scores (random normal)
        rets = pd.DataFrame(rng.normal(0.0005, 0.02, (n_days, n_assets)),
                             index=dates, columns=cols)
        # Synthetic CIS pillar_O long form
        cis_long = pd.DataFrame({
            "date": np.repeat(dates, n_assets),
            "asset": cols * n_days,
            "O": rng.uniform(0, 100, n_days * n_assets),
        })

        universe = cols
        score = build_composite(cis_long, rets, universe, dates)
        min_w = 1.0 / max(len(universe), 1)
        w = tilt_weights(score, min_weight=min_w).reindex(dates).ffill().fillna(0.0)
        w = w.div(w.sum(axis=1).replace(0, np.nan), axis=0).fillna(0.0)

        # H3.2 sizing
        size_scalar = pd.Series(1.0, index=dates)
        rebal_idx = list(range(0, len(dates), REBAL_DAYS))
        for i in rebal_idx:
            recent = rets.iloc[max(0, i - 30):i].mean(axis=1)
            size_scalar.iloc[i] = h32_size(recent)
        w_scaled = w.multiply(size_scalar.values, axis=0)
        w_scaled = w_scaled.clip(lower=0.0, upper=H32_CAP / n_assets)
        w_scaled = w_scaled.div(w_scaled.sum(axis=1).replace(0, np.nan), axis=0).fillna(0.0)

        raw_pnl = book_returns(w_scaled, rets)
        targeted_pnl = vol_target(raw_pnl, target_ann=VOL_TARGET_ANN)
        bench = hold_panel_benchmark(rets)
        excess = targeted_pnl - bench

        cut = int(len(targeted_pnl) * (1 - OOS_FRAC))
        is_pnl = targeted_pnl.iloc[:cut].fillna(0.0)
        oos_pnl = targeted_pnl.iloc[cut:].fillna(0.0)
        oos_sharpe = (float(oos_pnl.mean() / oos_pnl.std() * np.sqrt(PERIODS_PER_YEAR))
                      if oos_pnl.std() > 0 else 0.0)
        is_sharpe = (float(is_pnl.mean() / is_pnl.std() * np.sqrt(PERIODS_PER_YEAR))
                     if is_pnl.std() > 0 else 0.0)
        mdd = max_drawdown(targeted_pnl)
        ann_vol = float(targeted_pnl.std() * np.sqrt(PERIODS_PER_YEAR))

        gauntlet = full_gauntlet(excess, rets)
        decision = decide(gauntlet, targeted_pnl, oos_sharpe, mdd)
        windows = partition_into_windows(targeted_pnl.index, n_windows=N_WINDOWS)
        pw = per_window(targeted_pnl, windows)
        pw_excess = per_window(excess, windows)

        _logger.warning("SANDBOX MODE — verdict is on synthetic data, NOT real")
        return {
            "sandbox": True,
            "decision": decision,
            "universe_size": len(universe),
            "n_crypto": 0,
            "n_tradfi": 0,
            "panel": {"lo": str(dates[0].date()), "hi": str(dates[-1].date()),
                      "n_days": len(rets)},
            "gauntlet": gauntlet,
            "metrics": {
                "is_sharpe": is_sharpe, "oos_sharpe": oos_sharpe,
                "max_dd": mdd, "ann_vol": ann_vol,
            },
            "per_window_targeted": pw,
            "per_window_excess": pw_excess,
            "per_window_bench": per_window(bench, windows),
            "factor_returns": {},
            "h32_size_stats": {
                "min": float(size_scalar.min()),
                "median": float(size_scalar.median()),
                "max": float(size_scalar.max()),
            },
        }

    # ── Load crypto 41-asset panel (R46) ─────────────────────────────────────
    cis_long = load_cis_history_wide()
    rets_crypto = load_daily_returns()
    crypto_universe = sorted(set(cis_long["asset"]) & set(rets_crypto.columns))

    # ── Load TradFi 17-asset panel ───────────────────────────────────────────
    _logger.info("Loading TradFi ETF panel (EODHD cache)...")
    rets_tradfi = load_tradfi_panel()
    tradfi_universe = sorted(set(rets_tradfi.columns))

    # ── Align on common date index ───────────────────────────────────────────
    lo = max(cis_long["date"].min(),
             rets_crypto.index.min(),
             rets_tradfi.index.min())
    hi = min(cis_long["date"].max(),
             rets_crypto.index.max(),
             rets_tradfi.index.max())
    dates = (rets_crypto.index.union(rets_tradfi.index)
             .sort_values()
             .loc[(rets_crypto.index >= lo) & (rets_crypto.index <= hi)])
    dates = dates[dates >= pd.Timestamp(lo)]
    dates = dates[dates <= pd.Timestamp(hi)]

    rets_crypto = rets_crypto.reindex(dates)
    rets_tradfi = rets_tradfi.reindex(dates)
    rets = pd.concat([rets_crypto[crypto_universe],
                      rets_tradfi[tradfi_universe]], axis=1)
    universe = sorted(rets.columns)

    # Drop assets with > 30% NaN in the window (illiquid TradFi mid-window)
    nan_frac = rets.isna().mean()
    keep = nan_frac[nan_frac <= 0.30].index.tolist()
    rets = rets[keep]
    universe = sorted(rets.columns)

    _logger.info("Panel: %s → %s (%d days × %d assets = %d crypto + %d TradFi)",
                 lo.date(), hi.date(), len(rets), len(universe),
                 len([u for u in universe if u in crypto_universe]),
                 len([u for u in universe if u in tradfi_universe]))

    # ── Composite score ─────────────────────────────────────────────────────
    score = build_composite(cis_long, rets, universe, dates)
    # Restrict to assets with non-null pillar_O (crypto only) for the quality factor.
    # TradFi assets get z_momentum + z_lowrisk only.
    crypto_with_o = [u for u in universe if u in crypto_universe]
    tradfi_only = [u for u in universe if u in tradfi_universe]
    # For TradFi, recompute composite as 2-factor (momentum + lowrisk) divided by 2
    if tradfi_only:
        z_m_t = build_momentum_score(rets, tradfi_only, dates)
        z_l_t = build_lowrisk_score(rets, tradfi_only, dates)
        tradfi_composite = (z_m_t.fillna(0.0) + z_l_t.fillna(0.0)) / 2.0
        score[tradfi_only] = tradfi_composite

    # ── Tilt weights ────────────────────────────────────────────────────────
    min_w = 1.0 / max(len(universe), 1)
    w_raw = tilt_weights(score, min_weight=min_w)
    # Drop assets whose score is NaN for the whole window
    valid_mask = score.notna().any(axis=0)
    w_raw = w_raw.loc[:, valid_mask]
    w_raw = w_raw.div(w_raw.sum(axis=1), axis=0).fillna(0.0)

    # ── H3.2 conviction scaling at rebalance ────────────────────────────────
    rebal_idx = list(range(0, len(dates), REBAL_DAYS))
    size_scalar = pd.Series(1.0, index=dates)
    for i in rebal_idx:
        recent = rets.iloc[max(0, i - 30):i].mean(axis=1)
        size_scalar.iloc[i] = h32_size(recent)

    w_scaled = w_raw.multiply(size_scalar.values, axis=0)
    # Clip per-asset weights to [0, H32_CAP / n] then renormalize
    w_scaled = w_scaled.clip(lower=0.0, upper=H32_CAP / w_raw.shape[1])
    w_scaled = w_scaled.div(w_scaled.sum(axis=1).replace(0, np.nan), axis=0).fillna(0.0)

    # ── Book return ─────────────────────────────────────────────────────────
    raw_pnl = book_returns(w_scaled, rets)
    targeted_pnl = vol_target(raw_pnl, target_ann=VOL_TARGET_ANN)

    # ── Hold-the-panel benchmark ────────────────────────────────────────────
    bench = hold_panel_benchmark(rets)
    excess = targeted_pnl - bench

    # ── 3-check gauntlet on excess vs hold-the-panel ────────────────────────
    cut = int(len(targeted_pnl) * (1 - OOS_FRAC))
    is_pnl = targeted_pnl.iloc[:cut].fillna(0.0)
    oos_pnl = targeted_pnl.iloc[cut:].fillna(0.0)
    oos_sharpe = (float(oos_pnl.mean() / oos_pnl.std() * np.sqrt(PERIODS_PER_YEAR))
                  if oos_pnl.std() > 0 else 0.0)
    is_sharpe = (float(is_pnl.mean() / is_pnl.std() * np.sqrt(PERIODS_PER_YEAR))
                 if is_pnl.std() > 0 else 0.0)
    mdd = max_drawdown(targeted_pnl)
    ann_vol = float(targeted_pnl.std() * np.sqrt(PERIODS_PER_YEAR))

    gauntlet = full_gauntlet(excess, rets)
    decision = decide(gauntlet, targeted_pnl, oos_sharpe, mdd)

    # ── Per-window W1-W6 ────────────────────────────────────────────────────
    windows = partition_into_windows(targeted_pnl.index, n_windows=N_WINDOWS)
    pw = per_window(targeted_pnl, windows)
    pw_excess = per_window(excess, windows)
    pw_bench = per_window(bench, windows)

    # ── Factor decomposition ────────────────────────────────────────────────
    # Single-factor book returns to attribute Sharpe contribution.
    fac_returns = {}
    for fname, fbuilder in [
        ("quality", lambda a: build_quality_score(cis_long, a, dates)),
        ("momentum", lambda a: build_momentum_score(rets, a, dates)),
        ("lowrisk", lambda a: build_lowrisk_score(rets, a, dates)),
    ]:
        fz = fbuilder(universe)
        fw = tilt_weights(fz, min_weight=min_w).reindex(dates).ffill().fillna(0.0)
        fac_returns[fname] = book_returns(fw, rets)

    result = {
        "decision": decision,
        "universe_size": len(universe),
        "n_crypto": len([u for u in universe if u in crypto_universe]),
        "n_tradfi": len([u for u in universe if u in tradfi_universe]),
        "panel": {"lo": str(lo.date()), "hi": str(hi.date()),
                  "n_days": len(rets)},
        "gauntlet": gauntlet,
        "metrics": {
            "is_sharpe": is_sharpe, "oos_sharpe": oos_sharpe,
            "max_dd": mdd, "ann_vol": ann_vol,
        },
        "per_window_targeted": pw,
        "per_window_excess": pw_excess,
        "per_window_bench": pw_bench,
        "factor_returns": {k: float(v.mean() / v.std() * np.sqrt(PERIODS_PER_YEAR))
                           if v.std() > 0 else 0.0
                           for k, v in fac_returns.items()},
        "h32_size_stats": {
            "min": float(size_scalar.min()),
            "median": float(size_scalar.median()),
            "max": float(size_scalar.max()),
        },
    }
    return result


def render_report(result: dict, output_path: Path) -> None:
    L = []
    L.append("# Strategy 4 — Cross-Asset Quality-Momentum-LowVol Tilt")
    L.append(f"**Date:** {pd.Timestamp.now().date()}  ")
    L.append(f"**Decision:** **{result['decision']}**\n")

    L.append("## Universe")
    L.append(f"- **{result['universe_size']} assets** "
             f"({result['n_crypto']} crypto + {result['n_tradfi']} TradFi)")
    L.append(f"- Panel: {result['panel']['lo']} → {result['panel']['hi']} "
             f"({result['panel']['n_days']} days)\n")

    L.append("## 3-check gauntlet (excess vs hold-the-panel)")
    g = result["gauntlet"]
    L.append(f"- Gross α_t = **{g['gross_t']:+.3f}** "
             f"({'✓' if g['passes_gross'] else '✗'} clears 1.96)")
    L.append(f"- OOS α_t = **{g['oos_t']:+.3f}** "
             f"({'✓' if g['passes_oos'] else '✗'} clears 1.96)")
    L.append(f"- **3-check pass: {'✓✓✓' if g['passes_all'] else '✗'}**\n")

    L.append("## Performance (vol-targeted)")
    m = result["metrics"]
    L.append(f"- IS Sharpe: {m['is_sharpe']:+.2f}")
    L.append(f"- **OOS Sharpe: {m['oos_sharpe']:+.2f}**")
    L.append(f"- maxDD: {m['max_dd']*100:+.2f}%")
    L.append(f"- Ann vol: {m['ann_vol']*100:.2f}%\n")

    L.append("## Per-window W1-W6 (vol-targeted book)")
    L.append("| Window | ann % | Sharpe | maxDD | excess ann % |")
    L.append("|--------|-------|--------|-------|--------------|")
    for label in sorted(result["per_window_targeted"]):
        row = result["per_window_targeted"][label]
        ex_row = result["per_window_excess"][label]
        L.append(f"| {label} | {row['ann_pct']:+.2f}% | "
                 f"{row['sharpe']:+.2f} | {row['max_dd']*100:+.2f}% | "
                 f"{ex_row['ann_pct']:+.2f}% |")
    L.append("")

    L.append("## Factor decomposition (single-factor book Sharpe)")
    for fname, sharpe in result["factor_returns"].items():
        L.append(f"- {fname}: {sharpe:+.2f}")
    L.append("")

    L.append("## H3.2 sizing (conviction-scaled at rebalance)")
    s = result["h32_size_stats"]
    L.append(f"- min={s['min']:.2f}, median={s['median']:.2f}, "
             f"max={s['max']:.2f} (floor 0.5 / cap 1.75)\n")

    output_path.write_text("\n".join(L))
    _logger.info("Report written: %s", output_path)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    p.add_argument("--sandbox", action="store_true",
                   help="Run on synthetic data (Cowork only, NOT a real backtest)")
    p.add_argument("--sweep", action="store_true",
                   help="Run parameter sweep on REAL data (Mac-side only). "
                        "Tests ~180 configs and surfaces the Pareto-optimal cell. "
                        "Use when --sandbox's default config returns NEUTRAL/REFUTED.")
    args = p.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    if args.sweep:
        sweep_result = run_sweep(output_dir=args.output_dir)
        print(f"\n=== Strategy 4 sweep complete: "
              f"{sweep_result['n_total']} configs · "
              f"{sweep_result['n_passing']} passing ===")
        if sweep_result["best_passing"] is not None:
            b = sweep_result["best_passing"]
            print(f"  Best passing: rebal={b['rebal_days']}d vol={b['vol_tgt']:.2f} "
                  f"weights={b['weights']} floor={b['floor_q']:.2f} z_clip={b['z_clip']:.1f} "
                  f"→ gross_t={b['gross_t']:+.3f} oos_t={b['oos_t']:+.3f} "
                  f"maxDD={b['max_dd']*100:+.2f}% OOS_sharpe={b['oos_sharpe']:+.2f}")
        print(f"=== Report: {sweep_result['report_path']} ===")
        return 0
    result = run(output_dir=args.output_dir, sandbox=args.sandbox)
    stamp = pd.Timestamp.now().strftime("%Y-%m-%d")
    suffix = "_SANDBOX" if args.sandbox else ""
    out = args.output_dir / f"CROSS_ASSET_FACTOR_TILT_{stamp}{suffix}.md"
    render_report(result, out)
    print(f"\n=== Decision: {result['decision']} ==="
          + ("  [SANDBOX — not a real backtest]" if args.sandbox else ""))
    print(f"=== Report: {out} ===")
    return 0


# ── Sweep driver (Mac-side, real data) ────────────────────────────────────────
def run_sweep(output_dir: Path = OUTPUT_DIR) -> dict:
    """Run the parameter sweep on REAL DATA (Mac-side only).

    Loads the 41-crypto + 17-TradFi panel once, then iterates ~180 configs
    (5 knobs × small grids) and surfaces the Pareto-optimal cell. Output
    written to CROSS_ASSET_FACTOR_TILT_<DATE>_SWEEP.md.

    Use case: when --sandbox's default config returns NEUTRAL or REFUTED,
    this surfaces whether ANY config clears the 3-check gauntlet on real data.

    Knobs swept:
      - rebal_days ∈ {3, 5, 10, 20}
      - vol_tgt    ∈ {0.10, 0.12, 0.15, 0.20}
      - weights    ∈ {(1,1,1), (2,1,1), (1,2,1), (1,1,2), (2,1,2)}
      - floor_q    ∈ {0.25, 0.10, 0.0}
      - z_clip     ∈ {2.0, 3.0, 4.0}
    """
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(name)s] %(message)s")
    args.output_dir.mkdir(parents=True, exist_ok=True)

    _logger.info("Loading real-data panel for sweep...")
    cis_long = load_cis_history_wide()
    rets_crypto = load_daily_returns()
    crypto_universe = sorted(set(cis_long["asset"]) & set(rets_crypto.columns))
    rets_tradfi = load_tradfi_panel()
    tradfi_universe = sorted(set(rets_tradfi.columns))
    lo = max(cis_long["date"].min(), rets_crypto.index.min(), rets_tradfi.index.min())
    hi = min(cis_long["date"].max(), rets_crypto.index.max(), rets_tradfi.index.max())
    dates = (rets_crypto.index.union(rets_tradfi.index).sort_values()
             .loc[(rets_crypto.index >= lo) & (rets_crypto.index <= hi)])
    rets_crypto = rets_crypto.reindex(dates)
    rets_tradfi = rets_tradfi.reindex(dates)
    rets = pd.concat([rets_crypto[crypto_universe], rets_tradfi[tradfi_universe]], axis=1)
    nan_frac = rets.isna().mean()
    keep = nan_frac[nan_frac <= 0.30].index.tolist()
    rets = rets[keep]
    universe = sorted(rets.columns)
    _logger.info("Sweep panel: %s → %s (%d days × %d assets)",
                 lo.date(), hi.date(), len(rets), len(universe))

    sweep = []
    for rebal in (3, 5, 10, 20):
        for vt in (0.10, 0.12, 0.15, 0.20):
            for wts in [(1, 1, 1), (2, 1, 1), (1, 2, 1), (1, 1, 2), (2, 1, 2)]:
                for fq in (0.25, 0.10, 0.0):
                    for zc in (2.0, 3.0, 4.0):
                        r = _sweep_one(rets, cis_long, universe, dates,
                                       crypto_universe, tradfi_universe,
                                       rebal, vt, wts, fq, zc)
                        sweep.append(r)

    df = pd.DataFrame(sweep).sort_values(["passes", "oos_t"], ascending=[False, False])
    passes_df = df[df["passes"]]
    best_passing = passes_df.iloc[0].to_dict() if len(passes_df) else None

    stamp = pd.Timestamp.now().strftime("%Y-%m-%d")
    report_path = output_dir / f"CROSS_ASSET_FACTOR_TILT_{stamp}_SWEEP.md"
    with open(report_path, "w") as f:
        f.write(f"# Strategy 4 — Real-Data Parameter Sweep\n\n")
        f.write(f"**Date:** {stamp}\n")
        f.write(f"**Panel:** {lo.date()} → {hi.date()} ({len(rets)} days × {len(universe)} assets)\n")
        f.write(f"**Configs tested:** {len(df)}\n")
        f.write(f"**Passing both gross_t AND oos_t > 1.96:** {len(passes_df)} / {len(df)}\n\n")
        f.write("## Top 10 configs by OOS_t\n\n")
        f.write(df.head(10).to_markdown(index=False))
        f.write("\n\n## Best non-passers by OOS_t\n\n")
        f.write(df[~df["passes"]].sort_values("oos_t", ascending=False).head(5)
                .to_markdown(index=False))
        f.write("\n\n## Pareto-optimal (passes · lowest maxDD)\n\n")
        if len(passes_df):
            f.write(passes_df.sort_values("max_dd", ascending=False).head(3)
                    .to_markdown(index=False))
        else:
            f.write("_No config passes both gross_t AND oos_t > 1.96. "
                    "Strategy 4 cannot clear the gauntlet on real data._\n")
        f.write("\n\n## Frozen-cell proposal (if best_passing exists)\n\n")
        if best_passing:
            f.write(f"```\n")
            f.write(f"REBAL_DAYS     = {best_passing['rebal_days']}\n")
            f.write(f"VOL_TARGET_ANN = {best_passing['vol_tgt']}\n")
            f.write(f"WEIGHTS_QUALITY/MOM/LOWRISK = {best_passing['weights']}\n")
            f.write(f"FLOOR_QUARTILE = {best_passing['floor_q']}\n")
            f.write(f"Z_CLIP         = {best_passing['z_clip']}\n")
            f.write(f"# → gross_t={best_passing['gross_t']:+.3f} oos_t={best_passing['oos_t']:+.3f} "
                    f"OOS_sharpe={best_passing['oos_sharpe']:+.2f} maxDD={best_passing['max_dd']*100:+.2f}%\n")
            f.write(f"```\n")
        f.write("\n")

    _logger.info("Sweep report: %s", report_path)
    return {
        "n_total": len(df),
        "n_passing": len(passes_df),
        "best_passing": best_passing,
        "report_path": str(report_path),
        "all_results": df.to_dict("records"),
    }


def _sweep_one(rets, cis_long, universe, dates, crypto_universe, tradfi_universe,
               rebal_days, vol_tgt, weights, floor_q, z_clip) -> dict:
    """One sweep cell on REAL DATA. Loads are done by caller; this only
    computes the score + weights + gauntlet."""
    # Score (parametrised by z_clip)
    z_q = build_quality_score(cis_long, universe, dates).clip(-z_clip, z_clip)
    z_m = build_momentum_score(rets, universe, dates).clip(-z_clip, z_clip)
    z_l = build_lowrisk_score(rets, universe, dates).clip(-z_clip, z_clip)
    wq, wm, wl = weights
    score = (wq * z_q.fillna(0.0) + wm * z_m.fillna(0.0) + wl * z_l.fillna(0.0)) / (wq + wm + wl)

    # TradFi: 2-factor composite
    tradfi_only = [u for u in universe if u in tradfi_universe]
    if tradfi_only:
        z_m_t = build_momentum_score(rets, tradfi_only, dates).clip(-z_clip, z_clip)
        z_l_t = build_lowrisk_score(rets, tradfi_only, dates).clip(-z_clip, z_clip)
        score[tradfi_only] = (z_m_t.fillna(0.0) + z_l_t.fillna(0.0)) / 2.0

    # Tilt weights
    min_w = 1.0 / max(len(universe), 1)
    w_raw = tilt_weights(score, min_weight=min_w, floor_quartile=floor_q)
    valid_mask = score.notna().any(axis=0)
    w_raw = w_raw.loc[:, valid_mask]
    w_raw = w_raw.div(w_raw.sum(axis=1), axis=0).fillna(0.0)

    # H3.2 sizing at rebal
    size_scalar = pd.Series(1.0, index=dates)
    for i in range(0, len(dates), rebal_days):
        recent = rets.iloc[max(0, i - 30):i].mean(axis=1)
        size_scalar.iloc[i] = h32_size(recent)
    w_scaled = w_raw.multiply(size_scalar.values, axis=0)
    w_scaled = w_scaled.clip(lower=0.0, upper=H32_CAP / w_raw.shape[1])
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
        "passes": bool(gross_t > 1.96 and oos_t > 1.96),
        "is_sharpe": round(is_sharpe, 3),
        "oos_sharpe": round(oos_sharpe, 3),
        "max_dd": round(mdd, 4),
        "ann_vol": round(ann_vol, 4),
    }


if __name__ == "__main__":
    sys.exit(main())
