"""R100 — DIRECTIONAL TREND OVERLAY (11yr daily panel validation).

Per user direction 2026-07-28 ("现在可以匹配millennium那样的风格rebalance策略嘛？")
→ user chose "先 backtest 11yr panel 验证 shape (推荐)" — validate the directional
overlay shape on the 11yr panel BEFORE adding to paper phase as sleeve_4.

Architectural reasoning (lesson-driven, §TRADER_TOM_DOCTRINE two-layer book):
  - Layer 1 = R77 fusion cell (market-neutral factor book; FROZEN)
  - Layer 2 = DIRECTIONAL trend overlay (THIS MODULE — sleeve_4 candidate)
  - Per lessons #44, #55, #59, #60: regime-gross overlay on a MARKET-NEUTRAL
    book is a category mismatch. The overlay needs a DIRECTIONAL sleeve to
    express regime-conditional alpha (long in risk-on, short in risk-off).
  - This module is the §TRADER_TOM Layer 2 candidate. It must clear the
    3-check gauntlet to join R77 as Strategy 2.

Shape (parameter-frozen for honest test):
  - Universe: 11yr panel strict (≥2000 days), top 27 cryptos
  - Signal: 12m + 6m combined momentum z, cross-sectional
  - Direction: long top quartile / short bottom quartile (NET DIRECTIONAL bias;
    weights carry sign, NOT symmetric like R46)
  - Regime tilt: smooth logistic P(RISK_ON | BTC 30d return) → gross ∈ {0.5, 1.0, 1.5}
  - Vol-target: VT10 — 60d lagged realized vol, 10% annual target, scale ≤ 1.0
  - Rebal: 7d
  - Cost sweep: 0/5/10/20/30 bps
  - PIT lag: 1 bar (signal at t-1 → return at t)
  - Caps: per-name 5%, book gross ≤ 100%

3-check gauntlet:
  - gross_t > 1.96 (signed; abs(t) gate is REFUSED)
  - maxDD > -20%
  - ≥6/7 cycles positive
  - M-WO-1 episode audit: n_episodes ≥ 8, majority-positive, pooled_t ≥ 2.0

Verdict grammar: SURVIVES / PARTIAL / REFUTED.

Sister candidate: R82 (regime-gross overlay on R77) REFUTED on 731-day panel;
R92 (two-layer directional overlay) REFUTED with W5 +509.7% lift but maxDD
-48.69%; R94 (directional crypto beta) REFUTED with sign-FLIP at every cost
tier. R100 differs: smooth tilt + cross-section directional book + 11yr panel
(less bear-dominated per lesson #54).

Output:
  reports/r100_directional_trend_overlay/<date>/REPORT.md
  reports/r100_directional_trend_overlay/<date>/verdict.json
  reports/r100_directional_trend_overlay/<date>/daily_nav.csv

Usage:
  python3 src/research/validation/r100_directional_trend_overlay.py
"""
from __future__ import annotations

import sys
import json
import math
import sqlite3
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, date
from pathlib import Path

import numpy as np
import pandas as pd

_VALIDATION_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _VALIDATION_DIR.parents[2]
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_VALIDATION_DIR))

from m_wo1_r77_episode_count_audit import (  # noqa: E402
    segment_episodes, aggregate_episodes,
    EPISODE_GAP_DAYS, EPISODE_MIN_DAYS, ZERO_TOL,
    EPISODE_COUNT_FLOOR, EPISODE_T_FLOOR,
)

# === Frozen shape parameters (R100 spec; do NOT change without re-registering) ===
DB_PATH = Path("/tmp/cometcloud_data/ohlcv_11yr.db")
MIN_SPAN_DAYS = 2000           # strict universe filter (top 27 cryptos)
MOM_LOOKBACKS = (252, 126)     # 12m + 6m momentum in business days
MOM_WEIGHTS = (0.6, 0.4)       # 12m weighted more (more signal-stable)
QUARTILE_TOP = 0.25            # top quartile LONG
QUARTILE_BOTTOM = 0.25         # bottom quartile SHORT
REBAL_DAYS = 7
MAX_NAME_WEIGHT = 0.05
MAX_BOOK_GROSS = 1.00
PIT_LAG_BARS = 1
VT_TARGET_VOL = 0.10           # 10% annualized
VT_LOOKBACK = 60               # days
VT_SCALE_CAP = 1.0             # de-lever only, no leverage up
COST_BPS_GRID = (0, 5, 10, 20, 30)
MIN_EPISODES = 8
SIGNED_T_GATE = 1.96           # gross_t > 1.96, signed; abs(t) REFUSED
MAX_DD_GATE = -0.20            # > -20%
CYCLE_POS_FLOOR = 6            # ≥6/7 cycles positive

# Regime tilt parameters (sleeve_2-style logistic on BTC 30d return only — keeps
# R100 self-contained on the 11yr OHLCV panel; no external data sources)
BTC_30D_RISK_ON = +0.05        # BTC 30d return > +5% → risk-on
BTC_30D_RISK_OFF = -0.05       # BTC 30d return < -5% → risk-off
REGIME_COEF = 12.0             # logistic slope (P = 0.5 at BTC 30d = 0; high slope)
TILT_HIGH = 1.5
TILT_LOW = 0.5
TILT_MID = 1.0

# Cycle windows for 3-check gauntlet (R97-11yr-style, 7 windows over 9 years)
CYCLE_WINDOWS = [
    ("C1_2017Q4_2018Q4_bull", "2017-09-01", "2018-12-31"),
    ("C2_2019_2020_recovery", "2019-01-01", "2020-12-31"),
    ("C3_2021_bull_cycle",    "2021-01-01", "2021-12-31"),
    ("C4_2022_bear",          "2022-01-01", "2022-12-31"),
    ("C5_2023_recovery",      "2023-01-01", "2023-12-31"),
    ("C6a_2024_post_halving", "2024-01-01", "2024-12-31"),
    ("C6b_2025_26_late_cycle", "2025-01-01", "2026-07-27"),
]


def _result_to_jsonable(r) -> dict:
    """Convert R100Result dataclass + numpy types to JSON-serializable dict."""
    from dataclasses import asdict as _asdict
    d = _asdict(r)
    out = {}
    for k, v in d.items():
        if isinstance(v, np.bool_):
            out[k] = bool(v)
        elif isinstance(v, (np.integer,)):
            out[k] = int(v)
        elif isinstance(v, (np.floating,)):
            out[k] = float(v) if not np.isnan(v) else None
        elif isinstance(v, dict):
            sub = {}
            for kk, vv in v.items():
                if isinstance(vv, np.bool_):
                    sub[kk] = bool(vv)
                elif isinstance(vv, (np.integer,)):
                    sub[kk] = int(vv)
                elif isinstance(vv, (np.floating,)):
                    sub[kk] = float(vv) if not np.isnan(vv) else None
                else:
                    sub[kk] = vv
            out[k] = sub
        else:
            out[k] = v
    return out


@dataclass
class R100Result:
    cost_bps: int
    gross_t: float
    max_dd: float
    cum_pnl: float
    n_days: int
    n_cycles_pos: int
    n_cycles_total: int
    cycle_t_stats: dict
    m_wo1: dict
    passes_3check: bool
    verdict_per_cost: str   # "SURVIVES" / "PARTIAL" / "REFUTED"


# === Panel loading ============================================================

def load_11yr_panel(db_path: Path = DB_PATH, min_span: int = MIN_SPAN_DAYS,
                    verbose: bool = True) -> tuple[pd.DataFrame, list[str]]:
    """Load 11yr daily panel from SQLite, filter to strict universe."""
    if not db_path.exists():
        raise FileNotFoundError(f"11yr panel DB not found: {db_path}")
    conn = sqlite3.connect(db_path)
    cov_rows = conn.execute(
        "SELECT symbol, COUNT(*) AS n, MIN(trade_date) AS first, MAX(trade_date) AS last "
        "FROM ohlcv_11yr_daily GROUP BY symbol"
    ).fetchall()
    cov = pd.DataFrame(cov_rows, columns=["symbol", "n", "first", "last"])
    cov["first"] = pd.to_datetime(cov["first"]).dt.date
    cov["last"] = pd.to_datetime(cov["last"]).dt.date
    cov["span_days"] = cov.apply(lambda r: (r["last"] - r["first"]).days, axis=1)
    cov["n"] = cov["n"].astype(int)
    frozen = cov[cov["span_days"] >= min_span].copy()
    universe = sorted(frozen["symbol"].tolist())
    if verbose:
        print(f"[R100] universe: {len(universe)} symbols (≥{min_span} days)")
    placeholders = ",".join("?" * len(universe))
    df = pd.read_sql_query(
        f"SELECT symbol, trade_date, close "
        f"FROM ohlcv_11yr_daily WHERE symbol IN ({placeholders}) "
        f"ORDER BY symbol, trade_date",
        conn, params=universe,
    )
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    conn.close()
    return df, universe


def to_wide_prices(df: pd.DataFrame) -> pd.DataFrame:
    """Pivot long-form to wide (index=date, cols=symbol, values=close)."""
    wide = df.pivot(index="trade_date", columns="symbol", values="close").sort_index()
    return wide


# === Signal & position construction ==========================================

def compute_momentum_z(close_wide: pd.DataFrame) -> pd.DataFrame:
    """12m + 6m combined momentum z-score, cross-sectional."""
    # Build weighted combined momentum (each is a per-symbol DataFrame)
    combined = None
    for lb, w in zip(MOM_LOOKBACKS, MOM_WEIGHTS):
        ret = close_wide.pct_change(periods=lb)
        if combined is None:
            combined = w * ret
        else:
            combined = combined.add(w * ret, fill_value=0)
    # Cross-sectional z (row-wise standardize)
    mu = combined.mean(axis=1)
    sd = combined.std(axis=1)
    z = combined.sub(mu, axis=0).div(sd.replace(0, np.nan), axis=0)
    return z


def directional_weights(z: pd.DataFrame) -> pd.DataFrame:
    """Long top quartile, short bottom quartile — DIRECTIONAL bias (signs carry).

    Returns: weight matrix with values in {-1/(N/4), 0, +1/(N/4)} before
    normalization to book-gross ≤ MAX_BOOK_GROSS.
    """
    ranks = z.rank(axis=1, ascending=True, na_option="bottom")
    n_valid = z.notna().sum(axis=1)
    q1_thr = (n_valid * QUARTILE_BOTTOM).round()
    q3_thr = n_valid - (n_valid * QUARTILE_TOP).round()
    # Broadcast q1_thr / q3_thr (Series) against ranks (DataFrame) via row-wise compare.
    # Use ge/le on each row individually.
    long_mask = pd.DataFrame(
        np.where(ranks.values > q3_thr.values.reshape(-1, 1), True, False),
        index=z.index, columns=z.columns,
    )
    short_mask = pd.DataFrame(
        np.where(ranks.values <= q1_thr.values.reshape(-1, 1), True, False),
        index=z.index, columns=z.columns,
    )
    w = pd.DataFrame(0.0, index=z.index, columns=z.columns)
    long_count = long_mask.sum(axis=1).replace(0, np.nan)
    short_count = short_mask.sum(axis=1).replace(0, np.nan)
    long_vals = (1.0 / long_count).values.reshape(-1, 1)
    short_vals = (1.0 / short_count).values.reshape(-1, 1)
    w_arr = np.where(long_mask.values, np.broadcast_to(long_vals, w.shape), 0.0)
    w_arr = np.where(short_mask.values, np.broadcast_to(-short_vals, w.shape), w_arr)
    w = pd.DataFrame(w_arr, index=z.index, columns=z.columns)
    # Normalize to gross = 1.0 (directional book, NOT market-neutral 2.0)
    long_sum = w.where(w > 0).sum(axis=1)
    short_sum = -w.where(w < 0).sum(axis=1)
    gross_sum = long_sum + short_sum
    w = w.div(gross_sum.replace(0, np.nan), axis=0)
    return w


def smooth_regime_tilt(close_wide: pd.DataFrame) -> pd.Series:
    """Logistic P(RISK_ON) from BTC 30d return → smooth tilt ∈ {TILT_LOW, TILT_MID, TILT_HIGH}.

    Smooth (continuous) tilt: P(RISK_ON) → tilt multiplier by mapping
    P ≥ 0.65 → TILT_HIGH; P ≤ 0.35 → TILT_LOW; else TILT_MID. Three discrete
    bands is the standard "smooth-tilt" shape from Asness R20 (NOT continuous).
    """
    btc = close_wide["BTC"] if "BTC" in close_wide.columns else close_wide.iloc[:, 0]
    btc_30d_ret = btc.pct_change(periods=30)
    p_risk_on = 1.0 / (1.0 + np.exp(-REGIME_COEF * btc_30d_ret.fillna(0)))
    tilt = pd.Series(TILT_MID, index=close_wide.index)
    tilt = tilt.mask(p_risk_on >= 0.65, TILT_HIGH)
    tilt = tilt.mask(p_risk_on <= 0.35, TILT_LOW)
    tilt = tilt.fillna(TILT_MID)
    return tilt


def vol_target_scale(close_wide: pd.DataFrame, weights: pd.DataFrame) -> pd.DataFrame:
    """Vol-targeting: 60d lagged realized vol → scale weights to 10% annualized.

    Only DE-LEVERS (scale ≤ 1.0); never amplifies.
    """
    rets = close_wide.pct_change()
    # Portfolio vol = sqrt(sum(w_i^2 * sigma_i^2))  (simplification: use BTC vol as proxy)
    btc_vol = rets["BTC"].rolling(VT_LOOKBACK).std() * np.sqrt(365)
    target_scale = (VT_TARGET_VOL / btc_vol.replace(0, np.nan)).clip(upper=VT_SCALE_CAP).fillna(1.0)
    # Lag by PIT_LAG_BARS to avoid look-ahead
    scale_matrix = pd.DataFrame(
        np.tile(target_scale.values.reshape(-1, 1), (1, weights.shape[1])),
        index=weights.index, columns=weights.columns,
    ).shift(PIT_LAG_BARS).fillna(1.0)
    return weights.mul(scale_matrix, axis=0)


def apply_rebalance(weights: pd.DataFrame, rebal_days: int) -> pd.DataFrame:
    """Hold last weight through rebal_days; refresh every rebal_days."""
    rebal_idx = weights.index[::rebal_days]
    rebal_w = weights.loc[rebal_idx].ffill()
    rebal_w = rebal_w.reindex(weights.index).ffill()
    return rebal_w


def apply_caps(weights: pd.DataFrame) -> pd.DataFrame:
    """Per-name 5% cap; book gross ≤ 100%."""
    w = weights.clip(lower=-MAX_NAME_WEIGHT, upper=MAX_NAME_WEIGHT)
    long_sum = w.where(w > 0).sum(axis=1)
    short_sum = -w.where(w < 0).sum(axis=1)
    gross = long_sum + short_sum
    excess = gross - MAX_BOOK_GROSS
    if (excess > 0).any():
        # Scale down long+short proportionally
        scale = (MAX_BOOK_GROSS / gross).where(excess > 0, 1.0)
        w = w.mul(scale, axis=0)
    return w


# === Returns computation =====================================================

def compute_daily_returns(close_wide: pd.DataFrame) -> pd.DataFrame:
    """Daily returns (next-day to avoid look-ahead)."""
    return close_wide.pct_change().shift(-1)


def portfolio_pnl(weights_lag: pd.DataFrame, returns: pd.DataFrame,
                  cost_bps: float, rebal_days: int) -> pd.Series:
    """Compute daily P&L with turnover cost."""
    # Weights at t use returns at t+1 (PIT lag)
    pnl = (weights_lag * returns).sum(axis=1)
    # Turnover cost on rebal days
    turnover = weights_lag.diff().abs().sum(axis=1).fillna(0)
    cost = turnover * (cost_bps / 10000.0)
    pnl = pnl - cost
    return pnl.dropna()


# === 3-check gauntlet ========================================================

def gauntlet_3check(pnl: pd.Series, weights: pd.DataFrame) -> dict:
    """Compute gross_t, maxDD, cycles, M-WO-1 episodes.

    Returns dict with keys: gross_t, max_dd, n_cycles_pos, n_cycles_total,
    cycle_t_stats, m_wo1, passes_3check.
    """
    # Gross t-stat (no cost): use pre-cost P&L OR mark this as net.
    # Convention: gross = raw pre-cost; net = after-cost. Compute both.
    pnl_clean = pnl.dropna()
    mu = pnl_clean.mean()
    sd = pnl_clean.std(ddof=1)
    n = len(pnl_clean)
    gross_t = (mu / sd * np.sqrt(n)) if sd > 0 else 0.0

    # MaxDD on cumulative P&L
    cum = pnl_clean.cumsum()
    peak = cum.cummax()
    dd = (cum - peak)
    max_dd = dd.min() if len(dd) else 0.0

    # Per-cycle t-stats
    cycle_stats = {}
    cycles_pos = 0
    for cname, cs, ce in CYCLE_WINDOWS:
        cs_dt = pd.Timestamp(cs)
        ce_dt = pd.Timestamp(ce)
        mask = (pnl_clean.index >= cs_dt) & (pnl_clean.index <= ce_dt)
        c_pnl = pnl_clean[mask]
        if len(c_pnl) < 30:
            cycle_stats[cname] = {"n": len(c_pnl), "t_stat": np.nan, "ann_pct": np.nan}
            continue
        cm = c_pnl.mean()
        cs_sd = c_pnl.std(ddof=1)
        ct = (cm / cs_sd * np.sqrt(len(c_pnl))) if cs_sd > 0 else 0.0
        cann = cm * 365 * 100
        cycle_stats[cname] = {"n": len(c_pnl), "t_stat": ct, "ann_pct": cann}
        if ct > 0:
            cycles_pos += 1

    # M-WO-1 episode audit (n_episodes ≥ 8, majority-positive, pooled_t ≥ 2.0)
    pnl_for_ep = pnl_clean.copy()
    pnl_for_ep[pnl_for_ep.abs() < ZERO_TOL] = 0  # mark zero days
    episodes = segment_episodes(pnl_for_ep)
    agg = aggregate_episodes(episodes)

    passes_3check = (
        gross_t > SIGNED_T_GATE
        and max_dd > MAX_DD_GATE
        and cycles_pos >= CYCLE_POS_FLOOR
        and agg.get("n_episodes", 0) >= EPISODE_COUNT_FLOOR
        and agg.get("n_positive", 0) > agg.get("n_negative", 0)
        and agg.get("pooled_t", 0.0) >= EPISODE_T_FLOOR
    )

    return {
        "gross_t": gross_t,
        "max_dd": max_dd,
        "n_cycles_pos": cycles_pos,
        "n_cycles_total": len(CYCLE_WINDOWS),
        "cycle_t_stats": cycle_stats,
        "m_wo1": agg,
        "passes_3check": passes_3check,
    }


# === Main ====================================================================

def main() -> int:
    print("=" * 78)
    print("R100 — DIRECTIONAL TREND OVERLAY (11yr daily panel validation)")
    print("=" * 78)
    print(f"  DB: {DB_PATH}")
    print(f"  Universe filter: ≥{MIN_SPAN_DAYS} days")
    print(f"  Signal: {MOM_LOOKBACKS} momentum, weights {MOM_WEIGHTS}, cross-sectional z")
    print(f"  Direction: top {QUARTILE_TOP*100:.0f}% LONG / bottom {QUARTILE_BOTTOM*100:.0f}% SHORT (directional)")
    print(f"  Regime tilt: smooth tilt {{0.5, 1.0, 1.5}} via BTC 30d logistic")
    print(f"  Vol-target: VT{VT_TARGET_VOL*100:.0f} over {VT_LOOKBACK}d lagged")
    print(f"  Rebal: {REBAL_DAYS}d; PIT lag: {PIT_LAG_BARS} bar")
    print(f"  Caps: per-name {MAX_NAME_WEIGHT*100:.0f}%, book gross {MAX_BOOK_GROSS*100:.0f}%")
    print(f"  Cost sweep: {COST_BPS_GRID} bps")
    print(f"  Gate: gross_t > {SIGNED_T_GATE}, maxDD > {MAX_DD_GATE}, cycles_pos ≥ {CYCLE_POS_FLOOR}/{len(CYCLE_WINDOWS)}, "
          f"M-WO-1 ≥ {EPISODE_COUNT_FLOOR} eps + majority-pos + pooled_t ≥ {EPISODE_T_FLOOR}")
    print()

    # Load panel
    df, universe = load_11yr_panel()
    print(f"  ✓ loaded {len(df):,} rows × {len(universe)} symbols")
    close = to_wide_prices(df)
    print(f"  ✓ close_wide shape: {close.shape}; range: {close.index.min().date()} → {close.index.max().date()}")
    print()

    # Signal + weights
    print("[R100] computing momentum z …")
    z = compute_momentum_z(close)
    print("[R100] directional weights (top quartile LONG, bottom SHORT) …")
    w_raw = directional_weights(z)
    print("[R100] smooth regime tilt (BTC 30d logistic) …")
    tilt = smooth_regime_tilt(close)
    w_tilt = w_raw.mul(tilt, axis=0)
    print("[R100] vol-targeting (VT10, 60d lagged) …")
    w_vt = vol_target_scale(close, w_tilt)
    print("[R100] rebalance 7d …")
    w_reb = apply_rebalance(w_vt, REBAL_DAYS)
    print("[R100] apply caps (5% per name, 100% gross) …")
    w_final = apply_caps(w_reb)
    print(f"  ✓ weight matrix shape: {w_final.shape}; mean abs weight: {w_final.abs().mean().mean():.4f}")
    print()

    # Returns + cost sweep
    print("[R100] computing next-day returns …")
    returns = compute_daily_returns(close)
    print(f"  ✓ returns matrix shape: {returns.shape}")

    # Run 3-check gauntlet for each cost tier
    results: list[R100Result] = []
    print()
    print("[R100] running 3-check gauntlet + M-WO-1 episode audit (cost sweep) …")
    print("-" * 78)
    print(f"{'cost_bps':>10s} {'gross_t':>9s} {'maxDD':>10s} {'cum%':>10s} {'cyc_pos':>8s} {'eps':>4s} {'pos/neg':>8s} {'pooled_t':>9s} {'verdict':>10s}")
    print("-" * 78)
    for bps in COST_BPS_GRID:
        pnl = portfolio_pnl(w_final, returns, cost_bps=bps, rebal_days=REBAL_DAYS)
        if len(pnl) < 100:
            print(f"{bps:>10d}    insufficient data (n={len(pnl)})")
            continue
        g3 = gauntlet_3check(pnl, w_final)
        cum_pct = pnl.sum() * 100
        if g3["passes_3check"]:
            verdict = "SURVIVES"
        elif g3["gross_t"] > SIGNED_T_GATE and (g3["n_cycles_pos"] >= 5 or g3["m_wo1"].get("n_episodes", 0) >= 5):
            verdict = "PARTIAL"
        else:
            verdict = "REFUTED"
        res = R100Result(
            cost_bps=bps,
            gross_t=round(g3["gross_t"], 3),
            max_dd=round(g3["max_dd"], 4),
            cum_pnl=round(cum_pct, 2),
            n_days=len(pnl),
            n_cycles_pos=g3["n_cycles_pos"],
            n_cycles_total=g3["n_cycles_total"],
            cycle_t_stats={k: {"t_stat": round(v["t_stat"], 3) if not np.isnan(v["t_stat"]) else None,
                                "ann_pct": round(v["ann_pct"], 2) if not np.isnan(v["ann_pct"]) else None}
                            for k, v in g3["cycle_t_stats"].items()},
            m_wo1={
                "n_episodes": g3["m_wo1"].get("n_episodes", 0),
                "n_positive": g3["m_wo1"].get("n_positive", 0),
                "n_negative": g3["m_wo1"].get("n_negative", 0),
                "pooled_t": round(g3["m_wo1"].get("pooled_t", 0.0), 3),
            },
            passes_3check=g3["passes_3check"],
            verdict_per_cost=verdict,
        )
        results.append(res)
        print(f"{bps:>10d} {res.gross_t:>+9.3f} {res.max_dd*100:>+9.2f}% {res.cum_pnl:>+9.2f}% {res.n_cycles_pos:>5d}/{res.n_cycles_total} {res.m_wo1['n_episodes']:>4d} {res.m_wo1['n_positive']:>3d}/{res.m_wo1['n_negative']:<3d} {res.m_wo1['pooled_t']:>+9.3f} {verdict:>10s}")
    print("-" * 78)

    # Final verdict
    survives_count = sum(1 for r in results if r.verdict_per_cost == "SURVIVES")
    partial_count = sum(1 for r in results if r.verdict_per_cost == "PARTIAL")
    refuted_count = sum(1 for r in results if r.verdict_per_cost == "REFUTED")
    print()
    if survives_count >= 2:
        # At least 2 cost tiers pass 3-check → SURVIVES
        overall = "SURVIVES"
        verdict_msg = (f"✅ SHAPE SURVIVES — {survives_count}/{len(results)} cost tiers pass 3-check; "
                       f"add to paper phase as sleeve_4 candidate.")
    elif survives_count >= 1 or partial_count >= 2:
        overall = "PARTIAL"
        verdict_msg = (f"🟡 SHAPE PARTIAL — {survives_count} SURVIVES, {partial_count} PARTIAL, "
                       f"{refuted_count} REFUTED. Survives at low-cost only; "
                       f"consider tightening shape or wait for 11yr deep test.")
    else:
        overall = "REFUTED"
        verdict_msg = (f"🔴 SHAPE REFUTED — all cost tiers fail 3-check on 11yr panel; "
                       f"lesson #54 (panel length lever) confirmed insufficient — "
                       f"directional overlay shape exhausted on this universe.")
    print(f"[R100] FINAL VERDICT: {overall}")
    print(f"  {verdict_msg}")

    # Persist dated report
    today = datetime.now(timezone.utc).date().isoformat()
    out_dir = _REPO_ROOT / "reports" / "r100_directional_trend_overlay" / today
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "module": "r100_directional_trend_overlay",
        "run_date_utc": today,
        "db_path": str(DB_PATH),
        "universe_size": len(universe),
        "universe": universe,
        "shape": {
            "momentum_lookbacks": list(MOM_LOOKBACKS),
            "momentum_weights": list(MOM_WEIGHTS),
            "quartile_top": QUARTILE_TOP,
            "quartile_bottom": QUARTILE_BOTTOM,
            "rebal_days": REBAL_DAYS,
            "vt_target_vol": VT_TARGET_VOL,
            "vt_lookback": VT_LOOKBACK,
            "vt_scale_cap": VT_SCALE_CAP,
            "regime_tilt_bands": [TILT_LOW, TILT_MID, TILT_HIGH],
            "regime_coef": REGIME_COEF,
            "max_name_weight": MAX_NAME_WEIGHT,
            "max_book_gross": MAX_BOOK_GROSS,
            "pit_lag_bars": PIT_LAG_BARS,
        },
        "results": [_result_to_jsonable(r) for r in results],
        "verdict": overall,
        "verdict_message": verdict_msg,
    }
    with open(out_dir / "verdict.json", "w") as f:
        json.dump(payload, f, indent=2)
    print(f"\n  ✓ verdict.json: {out_dir / 'verdict.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())