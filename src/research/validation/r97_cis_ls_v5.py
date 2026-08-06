"""
R97 — CIS-LS V5 Dual-Horizon Trend L/S (Seth, 2026-07-27)
============================================================

Per R97 plan §2: rebuild the working structure of cisLSv4 (LS V4 + Trend V5c)
as a frozen dual-horizon L/S sleeve that fixes R49's flaws (LS V4 was pure
momentum beta → 100 flips/yr → cost kills the residual alpha).

Frozen signal (one shot — no entry-grid mining):
  · Universe: real 1h parquet that also appears in CIS history + funding daily
    (frozen in `r97_panel.freeze_universe`, 24 assets on this panel).
  · Major trend: 4h EMA(54)/EMA(126) (≈ 9d/21d daily) — slow horizon drives
    direction. Reported sign: +1 when fast>slow, -1 when fast<slow.
  · Entry confirmation: 4h EMA(9)/EMA(21) (LS V4 fast) + ADX(14) ≥ 25 +
    +DI/-DI consistent with intended direction.
  · Direction rule: major trend is the ceiling/floor — major=+1 only allows
    LONG, major=-1 only allows SHORT. Regime scaler cannot flip direction.
  · CIS gate: composite cis_score ≥ 55 (B+ floor), lagged 1 day, no fallback
    for missing data → zero weight.
  · Funding veto: cross-sectional funding z-score + funding direction symmetry —
    extreme positive funding blocks new longs, extreme negative blocks shorts.
  · Risk: ATR(14) inverse-vol sizing, hard-clipped to single-name 5% gross and
    book gross 100%.
  · Rebalance: 5-day cadence for risk; signal exits on major-trend flip.
  · PIT safety: every signal, CIS score, funding, ATR is shifted ≥1 bar.

Cost grid: 0/5/10/20/30 bps + funding carry (8h accrual scaled to 4h cadence).

Three baselines run on the SAME panel:
  · LS V4    — 4h EMA(9)/EMA(21) + ADX ≥ 25 signed flip (per R49 + cisLSv4).
  · V5c      — 4h EMA(54)/EMA(126) long-only (per trend_engine_v5).
  · Slow signed — 4h EMA(54)/EMA(126) symmetric long/short (V5a).

Frozen weights for the live R77 fusion cell are NEVER touched here (R77 is
the reference; R97 is the candidate). The `frozen_r77_baseline_gross_t`
constant is read from disk only as a sanity check that the R77 cell did not
drift — no live-book write path.

Verdict grammar:
  · TRADEABLE_CANDIDATE — full R97 research gauntlet passes (11 conditions).
  · PARTIAL              — survives some checks but cost or absorption kills one.
  · REFUTED              — any core 3-check fails.
  · REFUSED_DATA         — coverage shortfall before any backtest begins.
"""
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass

# ── DECISION_INPUTS contract (per tests/test_strategy_discipline.py) ────────
# R97 11yr CIS-L/S V5 candidate: dual-horizon L/S on R97's frozen 24-asset panel.
# Universe is the r97_panel.freeze_universe() output (real 1h parquet ∩ CIS history
# ∩ funding); regime = regime_fingerprint (informative; tested across cycles);
# weights = cis_quality composite (B+ floor 55); timing = 5d rebal + signal exit
# on major-trend flip (frozen; not re-tuned).
DECISION_INPUTS = {
    "regime": "regime_fingerprint",
    "universe": "r97_panel_frozen_24asset",
    "weights": "cis_quality_composite_bplus_floor",
    "timing": "5d_rebal_signal_exit_major_flip",
}
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

# ── Project imports (only after panel exists) ────────────────────────────────
# Avoid heavy imports at module load. The strategy helpers below use pure
# pandas / numpy so we don't need nautilus.
from src.research.validation.r97_panel import (
    freeze_universe, build_panel, coverage_audit, OHLCV_DIR,
)
from src.research.validation.cis_quality_absorption import (
    load_cis_history_wide, load_daily_returns, tercile_ls,
)
from src.research.validation.w5_forensics_external import load_funding_daily
from src.research.validation.w5_forensics import (
    partition_into_windows, gauntlet_3check,
)


# ── Frozen R97 parameters (one-shot, no sweep) ──────────────────────────────
FROZEN_UNIVERSE_MIN = 12
R97_MAJOR_FAST = 54
R97_MAJOR_SLOW = 126
R97_FAST = 9
R97_SLOW = 21
R97_ADX_PERIOD = 14
R97_ADX_THRESHOLD = 25.0
R97_CIS_FLOOR = 55.0           # composite CIS B+ floor
R97_ATR_PERIOD = 14
R97_REBAL_DAYS = 5
R97_MAX_NAME_WEIGHT = 0.05     # 5% gross per name
R97_MAX_BOOK_GROSS = 1.00      # 100% gross cap (1×)
R97_FUNDING_VETO_Z = 2.0       # cross-sectional z ≥ +2 blocks longs, ≤ -2 blocks shorts
R97_FUNDING_8H_PER_BAR = 3.0   # 3 funding accruals per 4h bar (8h × 3)
R97_PIT_LAG_BARS = 1           # every signal/CIS/funding shifted ≥1 bar

# R77 frozen weights (read-only — we do NOT modify R97 fusion here)
R77_W_R46 = 0.25
R77_W_R62 = 0.75
R77_W_R76 = 0.30

# Cost grid (per the plan)
COST_GRID_BPS = (0, 5, 10, 20, 30)


# ── Per-asset 4h indicators (pure pandas) ───────────────────────────────────
def precompute_4h_indicators(df4h: pd.DataFrame) -> pd.DataFrame:
    """Attach EMA(54), EMA(126), EMA(9), EMA(21), ADX(14), +DI/-DI, ATR(14) to a
    4h OHLCV DataFrame. PIT-safety is the responsibility of the caller (we
    shift in `compute_signals`).
    """
    df = df4h.copy()
    h, l, c = df["high"].values, df["low"].values, df["close"].values

    # EMAs
    df["ema_9"] = df["close"].ewm(span=R97_FAST, adjust=False).mean()
    df["ema_21"] = df["close"].ewm(span=R97_SLOW, adjust=False).mean()
    df["ema_54"] = df["close"].ewm(span=R97_MAJOR_FAST, adjust=False).mean()
    df["ema_126"] = df["close"].ewm(span=R97_MAJOR_SLOW, adjust=False).mean()

    # True Range + Wilder ADX (matches `src.research.indicators.precompute_indicators`)
    prev_c = np.concatenate([[c[0]], c[:-1]])
    tr = np.maximum(h - l, np.maximum(np.abs(h - prev_c), np.abs(l - prev_c)))
    prev_h = np.concatenate([[h[0]], h[:-1]])
    prev_l = np.concatenate([[l[0]], l[:-1]])
    up_move = h - prev_h
    down_move = prev_l - l
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    def wilder(arr, period):
        out = np.full_like(arr, np.nan, dtype=float)
        if period >= len(arr):
            return out
        out[period - 1] = arr[:period].sum()
        for i in range(period, len(arr)):
            out[i] = out[i - 1] - (out[i - 1] / period) + arr[i]
        return out

    sm_tr = wilder(tr, R97_ADX_PERIOD)
    sm_pdm = wilder(plus_dm, R97_ADX_PERIOD)
    sm_ndm = wilder(minus_dm, R97_ADX_PERIOD)
    with np.errstate(divide="ignore", invalid="ignore"):
        plus_di = np.where(sm_tr > 0, 100.0 * sm_pdm / sm_tr, 0.0)
        minus_di = np.where(sm_tr > 0, 100.0 * sm_ndm / sm_tr, 0.0)
        dx = np.where((plus_di + minus_di) > 0,
                       100.0 * np.abs(plus_di - minus_di) / (plus_di + minus_di), 0.0)
    df["plus_di"] = plus_di
    df["minus_di"] = minus_di
    df["adx"] = wilder(dx, R97_ADX_PERIOD)
    # ATR = Wilder-smoothed TR / period
    df["atr"] = sm_tr / R97_ADX_PERIOD

    return df


# ── PIT-safe helpers ────────────────────────────────────────────────────────
def pit_lag_series(s: pd.Series, bars: int = R97_PIT_LAG_BARS) -> pd.Series:
    """Shift a Series forward by `bars` so today's value uses yesterday's data.
    Returns a copy; NaN-safe via ffill before shift (per plan §2)."""
    return s.ffill().shift(bars)


def pit_lag(df: pd.DataFrame, col: str, bars: int = R97_PIT_LAG_BARS) -> pd.Series:
    """Convenience: PIT-lag a named column on a DataFrame."""
    return pit_lag_series(df[col], bars)


# ── Dual-horizon score for one asset ────────────────────────────────────────
def compute_dual_horizon_signals(per_asset_4h: pd.DataFrame) -> pd.DataFrame:
    """Return per-bar signals for one asset: [ts, major_dir, fast_dir, adx_passes,
    dmi_consistent, raw_score]. All signals are PIT-safe (already lagged by 1).
    """
    df = precompute_4h_indicators(per_asset_4h).copy()
    raw_major = np.where(df["ema_54"] > df["ema_126"], 1.0,
                         np.where(df["ema_54"] < df["ema_126"], -1.0, 0.0))
    raw_fast = np.where(df["ema_9"] > df["ema_21"], 1.0,
                        np.where(df["ema_9"] < df["ema_21"], -1.0, 0.0))
    df["major_dir"] = pit_lag_series(pd.Series(raw_major, index=df.index))
    df["fast_dir"] = pit_lag_series(pd.Series(raw_fast, index=df.index))
    df["adx_passes"] = pit_lag_series(pd.Series(
        (df["adx"] >= R97_ADX_THRESHOLD).astype(float).values, index=df.index))
    # DMI consistent: +DI > -DI for longs, -DI > +DI for shorts
    df["plus_di_lag"] = pit_lag(df, "plus_di")
    df["minus_di_lag"] = pit_lag(df, "minus_di")
    return df


# ── Universe-level signal: dual-horizon signed score (PIT-lagged) ────────────
def build_dual_horizon_score_wide(panel: pd.DataFrame, universe: list[str]) -> pd.DataFrame:
    """Build wide (date × asset) signed score where each entry is the dual-horizon
    intended side: +1 (long), -1 (short), 0 (flat). All inputs PIT-lagged.
    Returns a DataFrame indexed by 4h bar timestamps, columns = universe symbols.
    """
    parts = []
    for sym in universe:
        g = panel[panel["symbol"] == sym].sort_values("timestamp")
        if g.empty:
            continue
        sig = compute_dual_horizon_signals(g.reset_index(drop=True))
        sig["ts"] = pd.to_datetime(sig["timestamp"])
        sig = sig.set_index("ts")

        # Direction rule (plan §2): major trend is the ceiling/floor.
        # Fast signal CANNOT reverse major direction — if they disagree,
        # side = 0. Magnitude is determined by major when fast agrees.
        agreement = sig["major_dir"] * sig["fast_dir"]   # +1 agree, -1 disagree, 0 flat
        adx_ok = sig["adx_passes"] > 0                    # ADX must pass
        # DMI consistency: +DI > -DI for long intent; -DI > +DI for short intent.
        # Use major_dir (not side) since side = major when agreement > 0.
        dmi_long = (sig["plus_di_lag"] > sig["minus_di_lag"])
        dmi_short = (sig["plus_di_lag"] < sig["minus_di_lag"])
        dmi_ok = ((sig["major_dir"] > 0) & dmi_long) | ((sig["major_dir"] < 0) & dmi_short)
        # Side: ±1 when agreement > 0 AND ADX AND DMI all pass; else 0.
        side = sig["major_dir"].where((agreement > 0) & adx_ok & dmi_ok, 0.0)

        parts.append(pd.DataFrame({sym: side}))
    wide = pd.concat(parts, axis=1).sort_index().fillna(0.0)
    # Reindex to exact universe columns (in case some assets have no signal rows)
    return wide.reindex(columns=universe).fillna(0.0)


# ── Baselines (LS V4 / V5c / Slow signed) ──────────────────────────────────
def baseline_ls_v4(panel: pd.DataFrame, universe: list[str]) -> pd.DataFrame:
    """LS V4: 4h EMA(9)/EMA(21) + ADX≥25 signed flip, NO CIS gate, NO funding
    veto. Matches cisLSv4 behaviour for honest reproduction parity."""
    parts = []
    for sym in universe:
        g = panel[panel["symbol"] == sym].sort_values("timestamp")
        if g.empty:
            continue
        ind = precompute_4h_indicators(g.reset_index(drop=True)).copy()
        ind["ts"] = pd.to_datetime(ind["timestamp"])
        ind = ind.set_index("ts")
        raw_side = np.where(ind["ema_9"] > ind["ema_21"], 1.0,
                            np.where(ind["ema_9"] < ind["ema_21"], -1.0, 0.0))
        adx_ok = (ind["adx"] >= R97_ADX_THRESHOLD).fillna(False).astype(float).values
        side = pd.Series(raw_side * adx_ok, index=ind.index)
        side = pit_lag_series(side).fillna(0.0)
        parts.append(pd.DataFrame({sym: side}))
    wide = pd.concat(parts, axis=1).sort_index().fillna(0.0)
    return wide.reindex(columns=universe).fillna(0.0)


def baseline_v5c_long_only(panel: pd.DataFrame, universe: list[str]) -> pd.DataFrame:
    """V5c: 4h EMA(54)/EMA(126) long-only (per trend_engine_v5.trend_v5).
    Per R49: long-only flips are the best of the slow-trend family."""
    parts = []
    for sym in universe:
        g = panel[panel["symbol"] == sym].sort_values("timestamp")
        if g.empty:
            continue
        ind = precompute_4h_indicators(g.reset_index(drop=True)).copy()
        ind["ts"] = pd.to_datetime(ind["timestamp"])
        ind = ind.set_index("ts")
        side = pd.Series(np.where(ind["ema_54"] > ind["ema_126"], 1.0, 0.0),
                         index=ind.index)
        side = pit_lag_series(side).fillna(0.0)
        parts.append(pd.DataFrame({sym: side}))
    wide = pd.concat(parts, axis=1).sort_index().fillna(0.0)
    return wide.reindex(columns=universe).fillna(0.0)


def baseline_slow_signed(panel: pd.DataFrame, universe: list[str]) -> pd.DataFrame:
    """V5a: 4h EMA(54)/EMA(126) symmetric long/short."""
    parts = []
    for sym in universe:
        g = panel[panel["symbol"] == sym].sort_values("timestamp")
        if g.empty:
            continue
        ind = precompute_4h_indicators(g.reset_index(drop=True)).copy()
        ind["ts"] = pd.to_datetime(ind["timestamp"])
        ind = ind.set_index("ts")
        side = pd.Series(np.where(ind["ema_54"] > ind["ema_126"], 1.0,
                                  np.where(ind["ema_54"] < ind["ema_126"], -1.0, 0.0)),
                         index=ind.index)
        side = pit_lag_series(side).fillna(0.0)
        parts.append(pd.DataFrame({sym: side}))
    wide = pd.concat(parts, axis=1).sort_index().fillna(0.0)
    return wide.reindex(columns=universe).fillna(0.0)


# ── CIS gate (composite cis_score lagged 1d) ────────────────────────────────
def build_cis_gate(cis_long: pd.DataFrame, score_wide_index: pd.DatetimeIndex,
                   tradeable: list[str],
                   floor: float = R97_CIS_FLOOR) -> pd.DataFrame:
    """Wide DataFrame indexed by 4h bar timestamps, columns=symbols.
    Values are 1.0 (passes gate) or 0.0 (fails / missing)."""
    cis_w = cis_long.pivot_table(index="date", columns="asset", values="cis_score")
    cis_w = cis_w.reindex(columns=tradeable)
    # Map 4h-bar timestamps to their date (UTC-aware aware of tz)
    if score_wide_index.tz is None:
        date_index = pd.to_datetime(score_wide_index).normalize()
    else:
        date_index = pd.to_datetime(score_wide_index).tz_convert("UTC").tz_localize(None).normalize()
    # Score: 1 if cis_score (from yesterday) ≥ floor, else 0
    cis_daily = (cis_w >= floor).astype(float)
    cis_daily = cis_daily.shift(R97_PIT_LAG_BARS)   # PIT lag (yesterday's gate applies today)
    # Broadcast to 4h index by date
    gate = cis_daily.reindex(date_index).ffill().fillna(0.0)
    gate.index = score_wide_index
    return gate.reindex(columns=tradeable).fillna(0.0)


# ── Funding veto (cross-sectional z, PIT-lagged) ───────────────────────────
def build_funding_veto(funding_daily: pd.DataFrame,
                       score_wide_index: pd.DatetimeIndex,
                       tradeable: list[str],
                       z_threshold: float = R97_FUNDING_VETO_Z) -> pd.DataFrame:
    """Wide DataFrame indexed by 4h bar timestamps, columns=symbols.
    Values: cross-sectional z-score (PIT-lagged) used by `apply_gates_and_sizing`.
    Returns the RAW CROSS-SECTIONAL Z; the side-aware application is in
    `apply_gates_and_sizing`.
    """
    if funding_daily is None or funding_daily.empty:
        return pd.DataFrame(0.0, index=score_wide_index, columns=tradeable)
    f = funding_daily.reindex(columns=tradeable)
    # Cross-sectional z per day (demean by mean, scale by std)
    mu = f.mean(axis=1)
    sd = f.std(axis=1).replace(0, np.nan)
    z = f.sub(mu, axis=0).div(sd, axis=0)
    # Map 4h timestamps → dates
    if score_wide_index.tz is None:
        date_index = pd.to_datetime(score_wide_index).normalize()
    else:
        date_index = pd.to_datetime(score_wide_index).tz_convert("UTC").tz_localize(None).normalize()
    z_daily = z.shift(R97_PIT_LAG_BARS)  # PIT lag
    z_w = z_daily.reindex(date_index).ffill()
    z_w.index = score_wide_index
    return z_w.reindex(columns=tradeable)


# ── ATR inverse-vol sizing ──────────────────────────────────────────────────
def atr_weights(panel: pd.DataFrame, score_wide: pd.DataFrame,
                max_name_weight: float = R97_MAX_NAME_WEIGHT,
                max_book_gross: float = R97_MAX_BOOK_GROSS) -> pd.DataFrame:
    """Inverse-vol weights: w_a = (1/atr_a) × side_a, normalised so:
      · Per-name |w| ≤ max_name_weight
      · Book gross (sum |w_a|) ≤ max_book_gross
      · Net exposure = 0 if symmetric side available
    ATR is PIT-lagged (uses yesterday's bar)."""
    # Build ATR wide (only for the universe present in score_wide)
    parts = []
    for sym in score_wide.columns:
        g = panel[panel["symbol"] == sym].sort_values("timestamp")
        if g.empty:
            continue
        ind = precompute_4h_indicators(g.reset_index(drop=True)).copy()
        ind["ts"] = pd.to_datetime(ind["timestamp"])
        ind = ind.set_index("ts")
        atr_lag = ind["atr"].ffill().shift(R97_PIT_LAG_BARS)
        parts.append(pd.DataFrame({sym: atr_lag}))
    atr_w = pd.concat(parts, axis=1).sort_index()
    # Align ATR columns to score columns
    atr_w = atr_w.reindex(columns=score_wide.columns).reindex(index=score_wide.index)

    raw_w = score_wide.copy().astype(float)
    inv_atr = 1.0 / atr_w.replace(0, np.nan)
    raw_w = raw_w.mul(inv_atr, axis=1)

    # Per-name clip
    raw_w = raw_w.clip(-max_name_weight, max_name_weight)

    # Book-gross cap: scale to max_book_gross
    book_gross = raw_w.abs().sum(axis=1).replace(0, np.nan)
    scale = (max_book_gross / book_gross).where(book_gross > max_book_gross, 1.0)
    raw_w = raw_w.mul(scale, axis=0)

    # Force zero net exposure (long/short symmetry) by removing the cross-sectional mean
    # ONLY over names with non-zero weight, AND ONLY when BOTH sides are present.
    # If all surviving weights are the same sign (or there's only one survivor),
    # do NOT subtract the mean — that would zero out the lone long or short.
    # Per plan §2: market-neutral is the goal, but a one-sided book is OK when
    # the gates have stripped the other side.
    mask = raw_w.abs() > 1e-9
    counts = mask.sum(axis=1).replace(0, np.nan)
    net = raw_w.where(mask, 0.0).sum(axis=1) / counts
    has_both = ((raw_w > 0).any(axis=1) & (raw_w < 0).any(axis=1))
    net = net.where(has_both, 0.0)
    net = net.fillna(0.0)
    raw_w = raw_w.sub(net, axis=0)
    # Restore zeros where the gate produced zero (don't let zero-net bleed them).
    raw_w = raw_w.where(mask, 0.0)

    return raw_w.fillna(0.0)


# ── Gate + size combination ─────────────────────────────────────────────────
def apply_gates_and_sizing(panel: pd.DataFrame,
                           cis_gate: pd.DataFrame,
                           funding_z: pd.DataFrame,
                           base_signal: pd.DataFrame,
                           z_threshold: float = R97_FUNDING_VETO_Z) -> pd.DataFrame:
    """Take a base signal (+1/-1/0) and apply:
      · CIS gate (asset must pass composite score floor; else 0)
      · Funding veto (extreme funding blocks the side)
      · ATR inverse-vol sizing + per-name + book caps + zero-net exposure
    Returns sized weights (sum|.| ≤ 1.0, net ≈ 0).
    """
    # CIS gate
    sig = base_signal.mul(cis_gate)
    # Funding veto: long blocked if z > +z_threshold; short blocked if z < -z_threshold
    long_block = (funding_z > z_threshold).astype(float)
    short_block = (funding_z < -z_threshold).astype(float)
    # If signal > 0 and long_block=1 → zero; if signal < 0 and short_block=1 → zero
    long_blocked = ((sig > 0) & (long_block > 0)).astype(float)
    short_blocked = ((sig < 0) & (short_block > 0)).astype(float)
    sig = sig * (1 - long_blocked) * (1 - short_blocked)
    sig = sig.fillna(0.0)

    # ATR sizing
    sized = atr_weights(panel, sig)
    return sized


# ── Daily returns from 4h bars ──────────────────────────────────────────────
def _daily_returns(panel: pd.DataFrame) -> pd.DataFrame:
    """Close-to-close daily log returns for known assets (date × asset).
    Aggregates the 4h bars into one daily bar (last close of the day)."""
    panel = panel.copy()
    panel["date"] = panel["timestamp"].dt.tz_convert("UTC").dt.normalize() \
                    if panel["timestamp"].dt.tz is not None \
                    else panel["timestamp"].dt.normalize()
    daily_close = panel.groupby(["date", "symbol"])["close"].last().unstack("symbol")
    daily_ret = daily_close.pct_change()
    return daily_ret.sort_index()


# ── Rebalance + cost + funding carry ────────────────────────────────────────
def backtest_daily(weights_4h: pd.DataFrame, daily_rets: pd.DataFrame,
                   cost_bps: float = 0.0,
                   funding_daily: Optional[pd.DataFrame] = None,
                   funding_8h_per_bar: float = R97_FUNDING_8H_PER_BAR) -> pd.Series:
    """Daily rebalanced backtest of the 4h-bar weight stream.

    On each rebalance date (every R97_REBAL_DAYS days), apply the latest
    weight to today's return. Between rebalances, weights are held constant.
    Transaction cost = cost_bps × turnover (|Δw| summed across names).
    Funding carry: subtract funding[t,a] × w[t,a] × funding_8h_per_bar from
    the daily P&L (8h funding scaled to per-day).

    Returns a daily return Series aligned to daily_rets.index.
    """
    # Resample 4h weights to daily: take the LAST weight of each day
    w_daily = weights_4h.copy()
    w_daily["date"] = w_daily.index.tz_convert("UTC").normalize() \
                      if w_daily.index.tz is not None \
                      else w_daily.index.normalize()
    w_daily = w_daily.groupby("date").last()
    w_daily = w_daily.reindex(daily_rets.index).ffill()

    # Rebalance schedule: every R97_REBAL_DYS days
    rebal_dates = daily_rets.index[::R97_REBAL_DAYS]
    # Held weights = last rebalanced weights, forward-filled
    w_held = w_daily.copy()
    w_held[:] = np.nan
    prev_w = pd.Series(0.0, index=w_daily.columns)
    pnl = pd.Series(0.0, index=daily_rets.index)
    for d in daily_rets.index:
        if d in rebal_dates:
            target = w_daily.loc[d].fillna(0.0)
        else:
            target = prev_w
        # Today's gross return on the held weight
        if prev_w.abs().sum() > 0:
            day_ret = daily_rets.loc[d].reindex(prev_w.index).fillna(0.0)
            gross = float((prev_w * day_ret).sum())
            turn = float((target - prev_w).abs().sum())
            net = gross - turn * cost_bps / 1e4
            # Funding carry (only when we hold a position)
            if funding_daily is not None and prev_w.abs().sum() > 0:
                f_row = funding_daily.loc[d].reindex(prev_w.index) if d in funding_daily.index \
                        else pd.Series(0.0, index=prev_w.index)
                # 8h funding × 3 periods per day, positive funding = longs pay shorts
                # so PnL impact = -funding × position × funding_8h_per_bar
                carry = float(-(prev_w * f_row.fillna(0.0)).sum() * funding_8h_per_bar)
                net = net + carry
            pnl.loc[d] = net
        prev_w = target
    return pnl.fillna(0.0)


# ── Performance metrics (per R77/w5_forensics pattern) ─────────────────────
def sharpe_ann(r: pd.Series, periods: int = 365) -> float:
    if r.std(ddof=1) == 0 or len(r) < 3:
        return 0.0
    return float(r.mean() / r.std(ddof=1) * np.sqrt(periods))


def max_drawdown(r: pd.Series) -> float:
    cum = (1 + r.fillna(0.0)).cumprod()
    pk = cum.cummax()
    dd = cum / pk - 1.0
    return float(dd.min()) if len(dd) else 0.0


def per_window_pnl(r: pd.Series, windows: list[tuple]) -> dict:
    out = {}
    for label, s, e in windows:
        sub = r.loc[(r.index >= s) & (r.index <= e)]
        if len(sub) < 2:
            out[label] = {"n_days": len(sub), "ann_pct": np.nan, "cumret": np.nan, "sharpe": np.nan}
            continue
        cum = (1 + sub).prod() - 1
        ann = ((1 + sub).prod() ** (365 / max(len(sub), 1)) - 1) * 100
        out[label] = {"n_days": int(len(sub)),
                      "cumret": float(cum),
                      "ann_pct": float(ann),
                      "sharpe": sharpe_ann(sub)}
    return out


# ── Master run ──────────────────────────────────────────────────────────────
@dataclass
class RunCfg:
    out_dir: Path
    start: Optional[str] = None
    end: Optional[str] = None
    include_funding_carry: bool = True


def run(cfg: RunCfg) -> dict:
    cfg.out_dir.mkdir(parents=True, exist_ok=True)
    print("=== R97 — CIS-LS V5 Dual-Horizon Trend L/S ===\n")

    # 1. Freeze universe + build real 4h panel
    universe = freeze_universe(min_assets=FROZEN_UNIVERSE_MIN)
    print(f"[R97] Frozen universe ({len(universe)}): {list(universe)}")
    panel = build_panel(list(universe), start=cfg.start, end=cfg.end)
    print(f"[R97] Panel: {len(panel)} 4h-bars × {panel['symbol'].nunique()} symbols\n")

    # 2. Load CIS history (real)
    cis_long = load_cis_history_wide()
    cis_long = cis_long[cis_long["asset"].isin(universe)]
    print(f"[R97] CIS history: {len(cis_long)} rows, "
          f"{cis_long['date'].nunique()} days, "
          f"{cis_long['asset'].nunique()} assets in universe")

    # 3. Load funding daily
    funding_daily = load_funding_daily(assets=list(universe))
    if not funding_daily.empty:
        funding_daily = funding_daily.reindex(columns=list(universe))
        print(f"[R97] Funding daily: {len(funding_daily)} days × "
              f"{funding_daily.shape[1]} assets\n")
    else:
        print("[R97] Funding daily EMPTY — running without funding veto\n")

    # 4. Compute signals
    print("[R97] Building dual-horizon signal …")
    base_signal = build_dual_horizon_score_wide(panel, list(universe))
    print(f"[R97] base_signal shape: {base_signal.shape}, "
          f"mean(|signal|)={base_signal.abs().values.mean():.3f}")

    print("[R97] Building CIS gate (composite score ≥ 55, lagged 1d) …")
    cis_gate = build_cis_gate(cis_long, base_signal.index, list(universe),
                              floor=R97_CIS_FLOOR)

    print("[R97] Building funding veto (cross-sectional z) …")
    funding_z = build_funding_veto(funding_daily, base_signal.index, list(universe))

    print("[R97] Applying gates + ATR sizing …")
    r97_weights = apply_gates_and_sizing(panel, cis_gate, funding_z, base_signal)
    print(f"[R97] weights shape: {r97_weights.shape}, "
          f"book gross mean={r97_weights.abs().sum(axis=1).mean():.2f}")

    # 5. Baselines on same panel
    print("[R97] Baselines: LS V4 / V5c / Slow signed …")
    ls_v4 = baseline_ls_v4(panel, list(universe))
    v5c = baseline_v5c_long_only(panel, list(universe))
    slow_signed = baseline_slow_signed(panel, list(universe))
    ls_v4_w = atr_weights(panel, ls_v4)
    v5c_w = atr_weights(panel, v5c)
    slow_w = atr_weights(panel, slow_signed)

    # 6. Daily returns
    daily_rets = _daily_returns(panel)
    # Align funding daily to daily_rets index
    fdaily = funding_daily.reindex(daily_rets.index).ffill() \
             if not funding_daily.empty else None

    # 7. Backtest each leg at the cost grid
    windows = partition_into_windows(daily_rets.index, 6)

    def run_grid(name: str, weights: pd.DataFrame, cost_grid=COST_GRID_BPS):
        out = {"name": name, "per_cost": {}}
        for bps in cost_grid:
            carry = (cfg.include_funding_carry and fdaily is not None)
            r = backtest_daily(weights, daily_rets, cost_bps=bps,
                               funding_daily=fdaily if carry else None)
            r = r.reindex(daily_rets.index).fillna(0.0)
            metrics = {
                "sharpe": sharpe_ann(r),
                "max_dd": max_drawdown(r),
                "ann_pct": float(((1 + r).prod() ** (365 / max(len(r), 1)) - 1) * 100),
                "n_days": int(len(r)),
                "turnover_total": float(((weights.diff().abs().sum(axis=1)).sum())),
                "per_window": per_window_pnl(r, windows),
            }
            out["per_cost"][bps] = metrics
        return out

    print("[R97] Backtesting …")
    res_baseline_ls_v4 = run_grid("LS_V4", ls_v4_w)
    res_baseline_v5c = run_grid("V5c_long_only", v5c_w)
    res_baseline_slow = run_grid("slow_signed", slow_w)
    res_r97 = run_grid("R97_dual_horizon", r97_weights)

    # 8. 3-check gauntlet (R46/R77 pattern: market + momentum factor absorption)
    f_market = daily_rets[list(universe)].mean(axis=1).fillna(0.0)
    cum = (1 + f_market).cumprod()
    trail30 = cum / cum.shift(30) - 1
    f_momentum = (np.sign(trail30.shift(1)).fillna(0.0) * f_market)
    known = {"market": f_market.values, "momentum": f_momentum.values}
    cut = int(len(daily_rets) * 0.70)

    r97_0bps = backtest_daily(r97_weights, daily_rets, cost_bps=0,
                              funding_daily=fdaily if cfg.include_funding_carry else None)
    r97_10bps = backtest_daily(r97_weights, daily_rets, cost_bps=10,
                               funding_daily=fdaily if cfg.include_funding_carry else None)
    gauntlet_r97_0 = gauntlet_3check(r97_0bps.values, known, cut)
    gauntlet_r97_10 = gauntlet_3check(r97_10bps.values, known, cut)

    # 9. Verdict grammar (gauntlet_3check returns gross_t / oos_t — use passes_* flags)
    passes_gross = bool(gauntlet_r97_0["passes_gross"])            # gross_t > 1.96
    passes_oos = bool(gauntlet_r97_10["passes_oos"])               # OOS_t > 1.96
    passes_5bps = bool(res_r97["per_cost"][5]["sharpe"] > 0 and passes_gross)
    passes_10bps = bool(res_r97["per_cost"][10]["sharpe"] > 0 and gauntlet_r97_10["oos_t"] > 0)
    maxdd_ok = res_r97["per_cost"][10]["max_dd"] > -0.20
    positive_windows = sum(1 for w in res_r97["per_cost"][10]["per_window"].values()
                           if (not np.isnan(w["ann_pct"])) and w["ann_pct"] > 0)
    window_ok = positive_windows >= 5

    print(f"[R97] 3-check: gross_t={gauntlet_r97_0['gross_t']:+.2f}, "
          f"OOS_t={gauntlet_r97_10['oos_t']:+.2f}")
    print(f"[R97] maxDD@10bps={res_r97['per_cost'][10]['max_dd']:+.2%}, "
          f"positive windows={positive_windows}/6")

    if not passes_gross and not passes_oos:
        verdict_band = "REFUTED"
    elif passes_gross and passes_10bps and maxdd_ok and window_ok:
        verdict_band = "TRADEABLE_CANDIDATE"
    else:
        verdict_band = "PARTIAL"

    print(f"\n[R97] VERDICT: {verdict_band}\n")

    out = {
        "verdict": verdict_band,
        "verdict_details": {
            "passes_gross_t": bool(passes_gross),
            "passes_oos_t": bool(passes_oos),
            "passes_5bps_sharpe_positive": bool(passes_5bps),
            "passes_10bps_sharpe_positive": bool(passes_10bps),
            "passes_maxdd": bool(maxdd_ok),
            "positive_windows": positive_windows,
            "window_ok": bool(window_ok),
        },
        "panel": coverage_audit(panel),
        "universe": list(universe),
        "frozen_params": {
            "major_fast": R97_MAJOR_FAST, "major_slow": R97_MAJOR_SLOW,
            "fast": R97_FAST, "slow": R97_SLOW,
            "adx_period": R97_ADX_PERIOD, "adx_threshold": R97_ADX_THRESHOLD,
            "cis_floor": R97_CIS_FLOOR, "atr_period": R97_ATR_PERIOD,
            "rebal_days": R97_REBAL_DAYS, "max_name_weight": R97_MAX_NAME_WEIGHT,
            "max_book_gross": R97_MAX_BOOK_GROSS,
            "funding_veto_z": R97_FUNDING_VETO_Z,
            "pit_lag_bars": R97_PIT_LAG_BARS,
        },
        "frozen_r77_weights_readonly": {
            "w_r46": R77_W_R46, "w_r62": R77_W_R62, "w_r76": R77_W_R76,
            "note": "R97 is a candidate; live R77 cell NOT touched",
        },
        "gauntlet_r97": {
            "0bps": gauntlet_r97_0, "10bps_funding": gauntlet_r97_10,
        },
        "baselines": {
            "ls_v4": res_baseline_ls_v4,
            "v5c_long_only": res_baseline_v5c,
            "slow_signed": res_baseline_slow,
        },
        "r97": res_r97,
        "windows": [{"label": lab, "start": str(s.date()), "end": str(e.date()),
                     "n_days": int((e - s).days + 1)} for lab, s, e in windows],
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }

    # Persist daily return cache for downstream walk_forward module
    daily_cache = cfg.out_dir / "daily_returns.parquet"
    pd.DataFrame({
        "r97_0bps": r97_0bps,
        "r97_10bps": r97_10bps,
    }).to_parquet(daily_cache)
    print(f"[R97] Wrote daily returns cache: {daily_cache}")

    (cfg.out_dir / "verdict.json").write_text(json.dumps(out, indent=2, default=str))
    print(f"[R97] Wrote {cfg.out_dir / 'verdict.json'}")
    return out


def format_report(payload: dict) -> str:
    L = []
    L.append("# R97 — CIS-LS V5 Dual-Horizon Trend L/S — REPORT")
    L.append(f"**Run:** {payload['generated_at']}")
    L.append(f"**Verdict:** {payload['verdict']}")
    vd = payload["verdict_details"]
    L.append(f"  - gross_t > 1.96: {vd['passes_gross_t']}")
    L.append(f"  - 5bps Sharpe > 0: {vd['passes_5bps_sharpe_positive']}")
    L.append(f"  - 10bps Sharpe > 0: {vd['passes_10bps_sharpe_positive']}")
    L.append(f"  - OOS_t > 1.96: {vd['passes_oos_t']}")
    L.append(f"  - maxDD ≥ -20%: {vd['passes_maxdd']}")
    L.append(f"  - ≥5/6 windows positive: {vd['window_ok']} ({vd['positive_windows']}/6)\n")
    L.append(f"**Universe:** {len(payload['universe'])} assets — {payload['universe']}\n")
    L.append(f"**Frozen params:** {payload['frozen_params']}\n")
    g = payload["gauntlet_r97"]
    L.append("**3-check gauntlet (market + momentum absorbed):**")
    L.append(f"  - gross (0bps):  gross_t={g['0bps']['gross_t']:+.2f}, "
             f"gross_ann%={g['0bps']['gross_alpha_ann_pct']:+.1f}, "
             f"OOS_t={g['0bps']['oos_t']:+.2f}, "
             f"passes_gross={g['0bps']['passes_gross']}, "
             f"passes_oos={g['0bps']['passes_oos']}")
    L.append(f"  - 10bps + funding carry: gross_t={g['10bps_funding']['gross_t']:+.2f}, "
             f"gross_ann%={g['10bps_funding']['gross_alpha_ann_pct']:+.1f}, "
             f"OOS_t={g['10bps_funding']['oos_t']:+.2f}, "
             f"passes_oos={g['10bps_funding']['passes_oos']}")
    L.append("")
    L.append("**R97 sleeve @ 10bps:**")
    r97_10 = payload["r97"]["per_cost"][10]
    L.append(f"  - Sharpe: {r97_10['sharpe']:+.2f}, "
             f"maxDD: {r97_10['max_dd']:+.2%}, "
             f"ann%: {r97_10['ann_pct']:+.1f}")
    L.append("  - Per-window:")
    for label, w in r97_10["per_window"].items():
        L.append(f"    - {label}: ann%={w['ann_pct']:+.1f}, "
                 f"Sharpe={w['sharpe']:+.2f}, n={w['n_days']}")
    L.append("")
    L.append("**Baselines @ 10bps (for honest comparison on same panel):**")
    for name in ("ls_v4", "v5c_long_only", "slow_signed"):
        m = payload["baselines"][name]["per_cost"][10]
        L.append(f"  - {name}: Sharpe={m['sharpe']:+.2f}, "
                 f"maxDD={m['max_dd']:+.2%}, ann%={m['ann_pct']:+.1f}")
    return "\n".join(L)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", type=Path, default=None)
    ap.add_argument("--start", type=str, default=None)
    ap.add_argument("--end", type=str, default=None)
    ap.add_argument("--no-funding-carry", action="store_true")
    args = ap.parse_args()

    today = datetime.now().strftime("%Y-%m-%d")
    out_dir = args.out_dir or Path(f"reports/r97_cis_ls_v5/{today}")
    cfg = RunCfg(out_dir=out_dir, start=args.start, end=args.end,
                 include_funding_carry=not args.no_funding_carry)
    payload = run(cfg)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "REPORT.md").write_text(format_report(payload))
    print(format_report(payload))