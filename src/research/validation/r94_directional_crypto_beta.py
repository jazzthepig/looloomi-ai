"""
R94 — §TRADER_TOM Two-Layer Book: Directional Crypto Beta Sleeve (L2 — Regime-Scaled LONG-Only BTC/ETH/SOL) (Seth, 2026-07-26).

Per user's pivot (Option D — "Try directional Strategy 2 on crypto beta sleeve"): R77 = market-neutral
factor book (LOCKED, Layer 1). R94 = directional crypto beta sleeve (Layer 2). The two books are
ORTHOGONAL: R77 = factor alpha; R94 = directional beta. Combined book = durable fundamental core
(R77) + tactical trend-riding overlay (R94).

§TRADER_TOM_DOCTRINE two-layer book:
  Layer 1 — Durable fundamental core (R77 fusion cell, market-neutral, always-on)
  Layer 2 — Tactical trend-riding overlay (R94 = THIS, directional LONG-only beta, gross scales
            with regime per "press in risk-ON, defend in risk-OFF")

KEY FIXES vs R87/R92 (both REFUTED on 731-day panel):

  R87 filter: macro_regime (RISK_ON/EASING/STAGFLATION/TIGHTENING/RISK_OFF) — BROAD macro
  R87 state:  LONG top-K quality, weekly rebal only
  R87 limit:  71% reduced/zero gross; alpha FLAT across regimes; gross_t=+0.08

  R92 filter: BTC 3-factor trend confirmation (close vs 100d MA + slope + 30d return)
  R92 state:  signed directional L/S (LONG in BULL, SHORT in BEAR), weekly rebal only
  R92 limit:  gross_t=+1.03 < 1.96; maxDD=−48.69%; W3/W6 catastrophic

  R94 filter: macro_regime per day (same as R87) — but DAILY state evaluation
  R94 state:  LONG-only BTC/ETH/SOL equal-weight, daily gross scalar, weekly allocation
  R94 target: must beat static_beta benchmark (regime scaling adds value, not just beta capture)

Structural fixes baked in:
  1. DAILY risk-state evaluation — gross scalar updates every day from lagged regime[t-1]
     (R87/R92 only updated on weekly rebal, causing "state only acted on rebal day" anti-pattern)
  2. ONE-DAY LAG on all decision inputs — gross[t] = f(regime[t-1]), PIT-safe
  3. SMOOTH SCALAR in [0, 1.5] — not binary BULL/BEAR/CHOP
  4. TIGHTER maxDD budget ≤20% (vs R92's 30%) — pre-registered gate
  5. MANDATORY BENCHMARKS — must beat static BTC/ETH/SOL, BTC-only, regime-flat
  6. MANDATORY COMBINED-BOOK CHECK — does adding R94 actually help frozen R77?

Construction:
  - Universe: BTC + ETH + SOL (3-asset crypto beta sleeve)
  - Direction: LONG-only (no shorts, no pair trades, per user explicit choice)
  - Base weights: equal-weight (1/3 BTC, 1/3 ETH, 1/3 SOL) on every rebal
  - Regime scalar: R94_REGIME_GROSS (frozen map)
  - Daily gross scalar: applied daily with cost on weight change
  - Cadence: weekly rebal on 7d schedule (base weights are fixed; "rebal" = reset to base)
  - Cost: 5/10/20/30bps sweep (R32/R89/R90 lesson #58 MANDATORY)

3-check gauntlet:
  - gross_t > 1.96
  - 5bps_t > 1.96
  - OOS_t > 1.96 (last 30% of panel)
  AND survives_realistic_10bps (cost-tier sweep)
  AND maxDD > −20% (tighter than R92's 30%)
  AND W5 sign-positive (late-cycle fragility)
  AND ≥5/6 windows positive
  AND R94 OOS Sharpe ≥ static_beta OOS Sharpe (regime scaler adds value)
  AND combined-book Sharpe > R77 Sharpe alone (L1+L2 actual benefit)

Anti-imposter:
  - Directional beta sleeve can pass t-stats purely from long crypto in favorable sample.
    Mandatory benchmark comparison (R94 vs static_beta, R94 vs BTC-only, R94 vs regime-flat).
  - Combined-book check: does R94 ADD to frozen R77, or just dilute it?
  - Daily state evaluation with one-day lag (no same-day state leakage).
  - Cost on actual weight change (not only on rebal days).
  - Frozen R77 cell at w_R46=0.25/w_R62=0.75/w_R76=0.30 unchanged (R94 does NOT touch it).

Verdict grammar:
  ✅ SURVIVES = 3-check at 5bps AND survives 10bps AND maxDD > −20% AND W5 +ve AND
                ≥5/6 windows +ve AND R94 OOS Sharpe ≥ static_beta OOS Sharpe AND
                combined-book Sharpe > R77 Sharpe alone
  🟡 PARTIAL  = clears 5bps 3-check but fails 10bps OR scaling adds value but
                combined-book dilutes R77
  🔴 REFUTED  = fails 3-check at any cost tier OR scaling does NOT beat static_beta OR
                combined-book Sharpe ≤ R77 Sharpe alone
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from src.research.validation.factor_absorption import absorption_test
from src.research.validation.cis_quality_absorption import load_daily_returns
from src.research.data_align.cis_history_loader import load_cis_history

ALIGNED_CSV = ROOT / "_data" / "cis_historical" / "cis_historical_11yr_aligned.csv"

# ── Frozen config ────────────────────────────────────────────────────────────
R94_UNIVERSE = ("BTC", "ETH", "SOL")           # crypto beta sleeve (3-asset, equal-weight)
R94_BASE_WEIGHT = 1.0 / 3                       # equal-weight base
R94_REBAL_DAYS = 7                              # weekly allocation rebal
R94_COST_BPS = 5.0                              # 5bps per rebal (R77 cleared at 5bps)
R94_COST_GRID = (0.0, 5.0, 10.0, 20.0, 30.0)    # R32/R89/R90 lesson #58 MANDATORY
R94_REALISTIC_COST_BPS = 10.0                   # lesson #58 gate
R94_MAXDD_BUDGET = -0.20                        # tighter than R77's −8.91% + buffer

# ── Regime → gross scalar map (frozen per R87; expanded to all 7 canonical regimes) ──
R94_REGIME_GROSS = {
    "GOLDILOCKS":  1.00,    # bull-friendly
    "RISK_ON":     1.00,    # bull-friendly
    "EASING":      1.00,    # bull-friendly
    "NEUTRAL":     0.50,    # half gross
    "STAGFLATION": 0.50,    # half gross (uncertain)
    "TIGHTENING":  0.25,    # quarter gross (defend)
    "RISK_OFF":    0.00,    # flat (cash)
    None:          0.00,    # unknown → defensive
}

# ── Frozen R77 reference values (for combined-book test) ──────────────────────
R77_SHARPE_FROZEN = 2.06      # R77 Sharpe at frozen weights (w_R46=0.25/w_R62=0.75/w_R76=0.30)
R77_MAXDD_FROZEN = -0.0891    # R77 maxDD at frozen weights (≈ −8.91%)

NW_LAGS = 6
PERIODS_PER_YEAR = 365
OOS_FRAC = 0.30
MIN_TRADEABLE = 3              # BTC/ETH/SOL minimum (3)
MAX_GROSS_CAP = 1.5            # safety cap on the scaler


# ── Regime helpers ───────────────────────────────────────────────────────────
def load_regime_per_day(panel_dates: pd.DatetimeIndex) -> pd.Series:
    """Load per-day modal macro regime from aligned CIS history, ffill PIT-safe.

    Mirrors R87's pattern: pivot macro_regime wide (date × symbol), take modal regime
    per day, reindex to panel dates, ffill. UNKNOWN/None → NEUTRAL fallback (defensive).
    """
    cis = load_cis_history(ALIGNED_CSV, force_schema=True)
    if "macro_regime" not in cis.columns or "_date" not in cis.columns or "symbol" not in cis.columns:
        # Defensive: return all-RISK_OFF if no regime data
        return pd.Series("RISK_OFF", index=panel_dates, dtype=object)

    regime_wide = cis.pivot_table(
        index="_date", columns="symbol", values="macro_regime", aggfunc="first"
    ).sort_index()

    # Modal per day (most-common regime across symbols); ties → first mode
    mode_per_day = regime_wide.mode(axis=1).iloc[:, 0]
    # Normalize to UPPER_SNAKE for canonical map lookup
    mode_per_day = mode_per_day.astype(str).str.upper().str.replace("-", "_")
    # Reindex + ffill
    aligned = mode_per_day.reindex(panel_dates).ffill()
    # Fill any remaining NaN with RISK_OFF (defensive)
    aligned = aligned.fillna("RISK_OFF")
    return aligned


def gross_scalar_from_regime(
    regime_per_day: pd.Series,
    *,
    map_: dict[str, float] | None = None,
    cap: float = MAX_GROSS_CAP,
) -> pd.Series:
    """Map per-day regime → gross scalar in [0, cap]. ONE-DAY LAG enforced.

    Args:
        regime_per_day: per-day regime Series (aligned to panel dates)
        map_: regime → scalar dict (default R94_REGIME_GROSS)
        cap: safety cap on the scalar

    Returns:
        gross_scalar[t] = map[regime[t-1]] for t >= first_valid_index
        Lagged one day (no same-day state use).
    """
    if map_ is None:
        map_ = R94_REGIME_GROSS

    # Map regime → scalar; unknown regimes → 0.0 (defensive)
    raw = regime_per_day.map(map_).fillna(0.0)
    # Cap at safety limit
    raw = raw.clip(upper=cap)
    # ONE-DAY LAG: gross[t] = f(regime[t-1])
    lagged = raw.shift(1).fillna(0.0)
    return lagged


# ── Sleeve engines ───────────────────────────────────────────────────────────
def directional_beta_ls(
    rets: pd.DataFrame,
    gross_scalar: pd.Series,
    *,
    universe: tuple[str, ...] = R94_UNIVERSE,
    base_weight: float = R94_BASE_WEIGHT,
    rebal_days: int = R94_REBAL_DAYS,
    cost_bps: float = R94_COST_BPS,
) -> pd.Series:
    """R94 — directional crypto beta sleeve with DAILY gross scaling.

    - Universe: BTC/ETH/SOL equal-weight
    - Daily gross scalar from lagged regime (KEY FIX vs R87/R92)
    - Cost applied on actual weight change every day
    - Returns daily PnL series aligned to rets.index

    Args:
        rets: daily-return matrix (date × asset); must contain BTC, ETH, SOL
        gross_scalar: per-day gross scalar (already 1-day lagged), index aligned to rets
        universe: 3-tuple of asset symbols
        base_weight: per-asset base weight (1/3 default)
        rebal_days: weekly rebal cadence (only used for the "reset to base" check;
                    since base is fixed and equal-weight, this is a no-op marker)
        cost_bps: cost per round-trip on weight change
    """
    # Reindex scalar to rets.index, ffill to handle any missing dates
    scalar = gross_scalar.reindex(rets.index).ffill().fillna(0.0)

    common = list(universe)
    missing = [c for c in common if c not in rets.columns]
    if missing:
        raise ValueError(f"Required assets missing from rets: {missing}")

    r = rets[common].copy()
    fac = pd.Series(0.0, index=rets.index)
    prev_w = pd.Series(0.0, index=common)
    cost_per_unit = cost_bps / 1e4

    for i, date in enumerate(rets.index):
        rr = r.loc[date].reindex(common).fillna(0.0)
        # Target weight for end-of-day = scalar[t] * base_weight each
        scalar_t = float(scalar.loc[date])
        w_target = pd.Series(scalar_t * base_weight, index=common)
        # On rebal days, snap back to base if the scalar happens to have drifted
        # (defensive — ensures no accumulation error)
        if i % rebal_days == 0 and i > 0:
            w_target = pd.Series(scalar_t * base_weight, index=common)
        # Cost on weight change (round-trip on the delta)
        turnover = float((w_target - prev_w).abs().sum())
        cost = turnover * cost_per_unit
        # Daily PnL = prev_w @ r_t (we held yesterday's weights during today)
        pnl = float((prev_w * rr).sum())
        fac.loc[date] = pnl - cost
        prev_w = w_target

    return fac


def static_beta_ls(rets: pd.DataFrame, *, universe: tuple[str, ...] = R94_UNIVERSE,
                   base_weight: float = R94_BASE_WEIGHT) -> pd.Series:
    """Benchmark: equal-weight BTC/ETH/SOL, NO regime scaling, no cost.

    Daily PnL = sum(prev_w * r_t) where w_t = base_weight for each asset (no drift,
    no regime scaling, no cost). This is the "pure beta" baseline.
    """
    common = list(universe)
    fac = pd.Series(0.0, index=rets.index)
    w = pd.Series(base_weight, index=common)
    for date in rets.index:
        rr = rets.loc[date, common].reindex(common).fillna(0.0)
        fac.loc[date] = float((w * rr).sum())
    return fac


def btc_only_ls(rets: pd.DataFrame, gross_scalar: pd.Series,
                *, cost_bps: float = R94_COST_BPS) -> pd.Series:
    """Benchmark: BTC-only with the same gross scaling (no ETH/SOL diversification).

    Daily PnL = prev_w_btc * r_btc - cost. w_btc = gross_scalar[t] (BTC only, full weight).
    """
    scalar = gross_scalar.reindex(rets.index).ffill().fillna(0.0)
    fac = pd.Series(0.0, index=rets.index)
    prev_w = 0.0
    cost_per_unit = cost_bps / 1e4
    for date in rets.index:
        rr = float(rets.loc[date, "BTC"]) if "BTC" in rets.columns else 0.0
        if pd.isna(rr):
            rr = 0.0
        scalar_t = float(scalar.loc[date])
        w_target = scalar_t  # BTC = 100% of (scaled) book
        turnover = abs(w_target - prev_w)
        cost = turnover * cost_per_unit
        pnl = prev_w * rr
        fac.loc[date] = pnl - cost
        prev_w = w_target
    return fac


def regime_flat_ls(rets: pd.DataFrame, *, universe: tuple[str, ...] = R94_UNIVERSE,
                   base_weight: float = R94_BASE_WEIGHT,
                   rebal_days: int = R94_REBAL_DAYS,
                   cost_bps: float = R94_COST_BPS) -> pd.Series:
    """Benchmark: gross=1.0 always (no scaling), same weekly rebal + cost structure.

    Tests whether regime scaling adds value over constant-full exposure.
    """
    common = list(universe)
    flat_scalar = pd.Series(1.0, index=rets.index)
    return directional_beta_ls(rets, flat_scalar, universe=universe,
                               base_weight=base_weight, rebal_days=rebal_days,
                               cost_bps=cost_bps)


# ── 3-check gauntlet utilities ───────────────────────────────────────────────
def build_known_factors(rets: pd.DataFrame, lookback: int = 30) -> dict:
    """Standard 2-factor absorption (BTC-weighted market + TSMOM)."""
    if "BTC" in rets.columns:
        f_market = rets["BTC"].fillna(0.0)
    else:
        f_market = rets.mean(axis=1).fillna(0.0)
    cum = (1 + f_market).rolling(lookback, min_periods=lookback).apply(np.prod, raw=True) - 1
    f_momentum = (np.sign(cum) * f_market).fillna(0.0)
    return {"market": f_market.values, "momentum": f_momentum.values}


def run_one(fac: pd.Series, known: dict, oos_frac: float = OOS_FRAC) -> dict:
    """Compute full-sample and OOS t-stats + annualized return via absorption_test."""
    fac = fac.fillna(0.0).values
    cut = int(len(fac) * (1 - oos_frac))
    if cut < 30 or len(fac) - cut < 30:
        return {
            "full_t": 0.0, "full_ann_pct": 0.0,
            "oos_t": 0.0, "oos_ann_pct": 0.0,
            "oos_n": int(len(fac) - cut),
        }
    r_full = absorption_test(fac, known, nw_lags=NW_LAGS, periods_per_year=PERIODS_PER_YEAR)
    r_oos = absorption_test(fac[cut:], {k: v[cut:] for k, v in known.items()},
                            nw_lags=NW_LAGS, periods_per_year=PERIODS_PER_YEAR)
    return {
        "full_t": r_full["alpha_t"],
        "full_ann_pct": r_full["alpha_ann_pct"],
        "oos_t": r_oos["alpha_t"],
        "oos_ann_pct": r_oos["alpha_ann_pct"],
        "oos_n": int(len(fac) - cut),
    }


def max_drawdown(pnl: pd.Series) -> float:
    cum = (1 + pnl.fillna(0.0)).cumprod()
    peak = cum.cummax()
    dd = (cum - peak) / peak
    return float(dd.min())


def sharpe(pnl: pd.Series) -> float:
    """Annualized Sharpe (mean / std * sqrt(365))."""
    p = pnl.fillna(0.0)
    if p.std() == 0:
        return 0.0
    return float(p.mean() / p.std() * np.sqrt(PERIODS_PER_YEAR))


def per_window_pnl(pnl: pd.Series, n_windows: int = 6) -> dict:
    """Per-window attribution. W1 = oldest, W6 = most recent."""
    n = len(pnl)
    if n < n_windows:
        return {}
    windows = np.array_split(np.arange(n), n_windows)
    out = {}
    for i, idx in enumerate(windows, 1):
        w_pnl = pnl.iloc[idx]
        ann_ret = (1 + w_pnl.fillna(0.0)).prod() ** (PERIODS_PER_YEAR / len(idx)) - 1
        out[f"W{i}"] = {
            "n_days": int(len(idx)),
            "ann_pct": float(ann_ret * 100),
            "max_dd": float(max_drawdown(w_pnl)),
        }
    return out


# ── Combined-book check (R77 + R94) ──────────────────────────────────────────
def load_r77_pnl(rets_index: pd.DatetimeIndex) -> pd.Series | None:
    """Try to load frozen R77 daily PnL from persisted reports.

    R77 is at w_R46=0.25/w_R62=0.75/w_R76=0.30 frozen. We don't reconstruct R77 from
    scratch here (out of scope); if no cached R77 PnL is available, return None and the
    combined-book check degrades gracefully.
    """
    # Search gitignored reports dir for R77 verdict artifacts
    candidates = list(ROOT.glob("reports/r77_r76_as_fusion_contribution/*/verdict.json"))
    candidates += list(ROOT.glob("reports/r69_*/**/verdict.json"))
    if not candidates:
        return None
    # Use the most recent
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    try:
        with candidates[0].open() as f:
            v = json.load(f)
        # Look for any persisted PnL array; if not present, return None
        pnl_data = v.get("frozen_r77_daily_pnl") or v.get("daily_pnl") or v.get("pnl_series")
        if pnl_data is None:
            return None
        pnl = pd.Series(pnl_data)
        pnl.index = rets_index[:len(pnl)]
        return pnl
    except Exception:
        return None


def combined_book_stats(r94_pnl: pd.Series, r77_pnl: pd.Series | None,
                        *, w_r94: float = 0.5) -> dict:
    """Combined book = (1-w_r94) * R77 + w_r94 * R94 (L1+L2 weighted).

    Returns dict with: corr, combined_sharpe, combined_maxdd, combined_oos_t, delta metrics.
    """
    if r77_pnl is None:
        return {"available": False, "note": "R77 PnL not persisted; combined-book check skipped"}

    common = sorted(set(r94_pnl.index) & set(r77_pnl.index))
    if len(common) < 30:
        return {"available": False, "note": f"only {len(common)} common dates"}

    r94 = r94_pnl.reindex(common).fillna(0.0)
    r77 = r77_pnl.reindex(common).fillna(0.0)
    combined = (1 - w_r94) * r77 + w_r94 * r94

    corr = float(r94.corr(r77))
    known = build_known_factors(pd.DataFrame({"R77": r77, "R94": r94}))
    combined_metrics = run_one(combined, known, OOS_FRAC)
    r77_metrics = run_one(r77, known, OOS_FRAC)
    r94_metrics = run_one(r94, known, OOS_FRAC)

    return {
        "available": True,
        "w_r94": w_r94,
        "corr_r94_r77": corr,
        "combined_sharpe": sharpe(combined),
        "combined_max_dd": max_drawdown(combined),
        "combined_full_t": combined_metrics["full_t"],
        "combined_oos_t": combined_metrics["oos_t"],
        "r77_sharpe": sharpe(r77),
        "r77_max_dd": max_drawdown(r77),
        "r94_sharpe": sharpe(r94),
        "r94_max_dd": max_drawdown(r94),
        "oos_t_lift": combined_metrics["oos_t"] - r77_metrics["oos_t"],
        "sharpe_lift": sharpe(combined) - sharpe(r77),
        "max_dd_increase": max_drawdown(combined) - max_drawdown(r77),
    }


# ── Orchestrator ─────────────────────────────────────────────────────────────
def run(out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    print("=== R94 — §TRADER_TOM Two-Layer Book: Directional Crypto Beta Sleeve (L2) ===\n")
    print(f"Frozen config: universe={R94_UNIVERSE}, base_weight={R94_BASE_WEIGHT:.4f}, "
          f"rebal={R94_REBAL_DAYS}d, cost_grid={R94_COST_GRID}bps, maxDD_budget={R94_MAXDD_BUDGET:.0%}")

    # Load daily returns (BTC/ETH/SOL covered)
    rets_all = load_daily_returns()
    common = sorted(set(R94_UNIVERSE) & set(rets_all.columns))
    if len(common) < 3:
        raise RuntimeError(f"Missing assets: have {common}, need all of {R94_UNIVERSE}")
    rets = rets_all[common].copy()
    print(f"\nPanel: {len(rets)} days, universe={common}")

    # Load regime per day, compute lagged gross scalar
    regime = load_regime_per_day(rets.index)
    regime_dist = regime.value_counts()
    print(f"\nRegime distribution on panel:")
    for s, n in regime_dist.items():
        pct = 100.0 * n / len(regime)
        scalar = R94_REGIME_GROSS.get(s, 0.0)
        print(f"  {s:12s}: {n:4d} days ({pct:5.1f}%) → gross={scalar:.2f}")

    bull_days = sum(n for s, n in regime_dist.items()
                    if R94_REGIME_GROSS.get(s, 0.0) >= 1.0)
    bull_pct = 100.0 * bull_days / len(regime)
    print(f"\nBull-active (gross ≥ 1.0): {bull_days} days ({bull_pct:.1f}%) — R87 lesson: require ≥15%")

    gross_scalar = gross_scalar_from_regime(regime)
    gs_dist = gross_scalar.value_counts().sort_index()
    print(f"\nGross scalar distribution (after 1-day lag):")
    for v, n in gs_dist.items():
        print(f"  {v:.2f}: {n:4d} days ({100.0 * n / len(gross_scalar):.1f}%)")
    pct_active = 100.0 * (gross_scalar > 0).sum() / len(gross_scalar)
    print(f"  pct active (gross > 0): {pct_active:.1f}%")

    known = build_known_factors(rets)
    cut = int(len(rets) * (1 - OOS_FRAC))

    # ── Default cell: 7d rebal × 5bps (R77 cleared at 5bps) ───────────────────
    print(f"\n══ Default cell: 7d rebal × 5bps ══\n")
    r94_default = directional_beta_ls(rets, gross_scalar, cost_bps=5.0)
    r94_default = r94_default.reindex(rets.index).fillna(0.0)
    default_metrics = run_one(r94_default, known, OOS_FRAC)
    print(f"  full_t = {default_metrics['full_t']:+.3f}, OOS_t = {default_metrics['oos_t']:+.3f}, "
          f"full_ann = {default_metrics['full_ann_pct']:+.1f}%, OOS_ann = {default_metrics['oos_ann_pct']:+.1f}%")

    # ── Cost-tier sweep (R32/R89/R90 lesson #58 MANDATORY) ──────────────────────
    print(f"\n══ Cost-tier sweep at default cadence (7d rebal) — R32/R89/R90 gate ══\n")
    cost_tier = {}
    for cost_bps in R94_COST_GRID:
        leg = directional_beta_ls(rets, gross_scalar, cost_bps=cost_bps)
        leg = leg.reindex(rets.index).fillna(0.0)
        g = run_one(leg, known, OOS_FRAC)
        cost_tier[cost_bps] = {
            "cost_bps": cost_bps,
            "full_t": g["full_t"],
            "full_ann_pct": g["full_ann_pct"],
            "oos_t": g["oos_t"],
            "oos_ann_pct": g["oos_ann_pct"],
            "passes_full": g["full_t"] > 1.96,
            "passes_oos": g["oos_t"] > 1.96,
            "passes_all": g["full_t"] > 1.96 and g["oos_t"] > 1.96,
        }

    survives_realistic_10bps = cost_tier[R94_REALISTIC_COST_BPS]["passes_all"]
    print(f"  cost_bps | full_t | OOS_t | full_ann% | OOS_ann% | passes_all")
    for cost_bps, v in cost_tier.items():
        marker = " ← GATE" if cost_bps == R94_REALISTIC_COST_BPS else ""
        print(f"  {cost_bps:8.1f} | {v['full_t']:+.3f} | {v['oos_t']:+.3f} | "
              f"{v['full_ann_pct']:+.1f}% | {v['oos_ann_pct']:+.1f}% | "
              f"{'YES' if v['passes_all'] else 'NO':<10} | {marker}")
    print(f"\n  Survives at 10bps? {survives_realistic_10bps}")

    # ── Benchmark comparisons (anti-imposter, NEW) ─────────────────────────────
    print(f"\n══ Benchmark comparisons (regime scaler vs static beta) ══\n")
    static_leg = static_beta_ls(rets).reindex(rets.index).fillna(0.0)
    btc_leg = btc_only_ls(rets, gross_scalar, cost_bps=5.0).reindex(rets.index).fillna(0.0)
    flat_leg = regime_flat_ls(rets, cost_bps=5.0).reindex(rets.index).fillna(0.0)

    static_metrics = run_one(static_leg, known, OOS_FRAC)
    btc_metrics = run_one(btc_leg, known, OOS_FRAC)
    flat_metrics = run_one(flat_leg, known, OOS_FRAC)

    r94_sharpe = sharpe(r94_default)
    static_sharpe = sharpe(static_leg)
    btc_sharpe = sharpe(btc_leg)
    flat_sharpe = sharpe(flat_leg)

    print(f"  Sleeve | full_t | OOS_t | Sharpe | maxDD")
    print(f"  -------+--------+-------+--------+-------")
    for label, m, sh, mdd in [
        ("R94 (default 5bps)", default_metrics, r94_sharpe, max_drawdown(r94_default)),
        ("static_beta (1/3, no scaling)", static_metrics, static_sharpe, max_drawdown(static_leg)),
        ("BTC-only (with scaling)", btc_metrics, btc_sharpe, max_drawdown(btc_leg)),
        ("regime-flat (gross=1.0)", flat_metrics, flat_sharpe, max_drawdown(flat_leg)),
    ]:
        print(f"  {label:30s} | {m['full_t']:+.3f} | {m['oos_t']:+.3f} | "
              f"{sh:+.3f} | {mdd:+.2%}")

    scaling_beats_static = default_metrics["oos_t"] > static_metrics["oos_t"]
    scaling_beats_flat = default_metrics["oos_t"] > flat_metrics["oos_t"]
    print(f"\n  R94 OOS_t > static_beta OOS_t? {scaling_beats_static}")
    print(f"  R94 OOS_t > regime_flat OOS_t? {scaling_beats_flat}")

    # ── Per-window W1–W6 at default cell (5bps) ───────────────────────────────
    print(f"\n══ Per-window W1–W6 at default cell (7d/5bps) ══\n")
    pw = per_window_pnl(r94_default)
    mdd_5bps = max_drawdown(r94_default)
    n_pos_windows = sum(1 for w in pw.values() if w["ann_pct"] > 0)
    w5_ann = pw.get("W5", {}).get("ann_pct", 0.0)
    print(f"  maxDD = {mdd_5bps:+.2%}")
    print(f"  Window | n_days | ann_pct | maxDD")
    for label in ("W1", "W2", "W3", "W4", "W5", "W6"):
        if label in pw:
            print(f"  {label} | {pw[label]['n_days']:6d} | "
                  f"{pw[label]['ann_pct']:+.1f}% | {pw[label]['max_dd']:+.2%}")

    # ── Combined-book check (R77 + R94, L1 + L2) ───────────────────────────────
    print(f"\n══ Combined-book check (R77 + R94, L1 + L2) ══\n")
    r77_pnl = load_r77_pnl(rets.index)
    combined = combined_book_stats(r94_default, r77_pnl, w_r94=0.5)
    if combined.get("available"):
        print(f"  corr(R94, R77) = {combined['corr_r94_r77']:+.3f}")
        print(f"  R77 Sharpe = {combined['r77_sharpe']:+.3f}, maxDD = {combined['r77_max_dd']:+.2%}")
        print(f"  R94 Sharpe = {combined['r94_sharpe']:+.3f}, maxDD = {combined['r94_max_dd']:+.2%}")
        print(f"  Combined (50/50) Sharpe = {combined['combined_sharpe']:+.3f}, maxDD = {combined['combined_max_dd']:+.2%}")
        print(f"  Combined OOS_t lift = {combined['oos_t_lift']:+.3f}")
        print(f"  Sharpe lift = {combined['sharpe_lift']:+.3f}")
        print(f"  maxDD increase = {combined['max_dd_increase']:+.2%}")
    else:
        print(f"  R77 PnL not persisted; combined-book check skipped (note: {combined.get('note')})")

    # ── Verdict grammar ────────────────────────────────────────────────────────
    passes_3check_5bps = cost_tier[5.0]["passes_all"]
    maxdd_ok = mdd_5bps > R94_MAXDD_BUDGET
    w5_ok = w5_ann > 0
    n_pos_ok = n_pos_windows >= 5
    bull_pct_ok = bull_pct >= 15.0
    scaling_adds_value = scaling_beats_static and scaling_beats_flat
    combined_sharpe_lifts_r77 = combined.get("available", False) and combined["sharpe_lift"] > 0

    if (passes_3check_5bps and survives_realistic_10bps and maxdd_ok and w5_ok and
            n_pos_ok and bull_pct_ok and scaling_adds_value and combined_sharpe_lifts_r77):
        verdict = ("✅ SURVIVES — TRADEABLE — eligible for Strategy 2 slot (Layer 2 of "
                   "§TRADER_TOM two-layer book).")
        verdict_band = "TRADEABLE"
    elif passes_3check_5bps and survives_realistic_10bps and maxdd_ok and w5_ok and n_pos_ok:
        if scaling_adds_value and not combined_sharpe_lifts_r77:
            verdict = ("🟡 PARTIAL — 3-check passes, scaling adds value, but combined-book "
                       "dilutes frozen R77 (Sharpe lift ≤ 0). R94 is real but does not LIFT "
                       "the combined book — Layer 2 needs further work.")
            verdict_band = "PARTIAL"
        elif not scaling_adds_value:
            verdict = ("🟡 PARTIAL — 3-check passes but regime scaling does NOT beat static "
                       "beta. R94 is captured beta, not regime-alpha. The directional signal "
                       "is real but the scaler is noise.")
            verdict_band = "PARTIAL"
        else:
            verdict = ("🟡 PARTIAL — partial clearance (some gate failed). Review per-window "
                       "and combined-book stats for the binding constraint.")
            verdict_band = "PARTIAL"
    elif passes_3check_5bps and not survives_realistic_10bps:
        verdict = ("🟡 PARTIAL — 3-check at 5bps passes but edge dies at 10bps (R32/R89/R90 "
                   "taker-fee illusion). Directional beta sleeve cannot survive realistic cost.")
        verdict_band = "PARTIAL"
    else:
        verdict = ("🔴 REFUTED — directional crypto beta sleeve lacks standalone edge. "
                   "Daily risk-state updates + tight maxDD budget did not rescue the "
                   "731-day panel's bear-domination. Strategy 2 remains STRUCTURALLY "
                   "DEFERRED pending §OHLCV-EXTENSION.")
        verdict_band = "REFUTED"

    print(f"\nVerdict: {verdict}\n")

    out = {
        "panel": {"n_days": int(len(rets)), "n_assets": len(common)},
        "construction": {
            "universe": list(R94_UNIVERSE),
            "base_weight": R94_BASE_WEIGHT,
            "rebal_days": R94_REBAL_DAYS,
            "cost_grid": list(R94_COST_GRID),
            "realistic_cost_bps": R94_REALISTIC_COST_BPS,
            "maxdd_budget": R94_MAXDD_BUDGET,
            "regime_map": R94_REGIME_GROSS,
            "two_layer_intent": "R77 (Layer 1) + R94 (Layer 2)",
        },
        "regime_distribution": {str(s): int(n) for s, n in regime_dist.items()},
        "gross_scalar_distribution": {f"{v:.2f}": int(n) for v, n in gs_dist.items()},
        "bull_active_pct": bull_pct,
        "default_cell_5bps": default_metrics,
        "cost_tier_sweep": {f"{int(k)}bps": v for k, v in cost_tier.items()},
        "survives_realistic_10bps": survives_realistic_10bps,
        "benchmarks": {
            "r94": {"sharpe": r94_sharpe, "max_dd": max_drawdown(r94_default)},
            "static_beta": {"sharpe": static_sharpe, "max_dd": max_drawdown(static_leg),
                            "full_t": static_metrics["full_t"], "oos_t": static_metrics["oos_t"]},
            "btc_only": {"sharpe": btc_sharpe, "max_dd": max_drawdown(btc_leg),
                         "full_t": btc_metrics["full_t"], "oos_t": btc_metrics["oos_t"]},
            "regime_flat": {"sharpe": flat_sharpe, "max_dd": max_drawdown(flat_leg),
                            "full_t": flat_metrics["full_t"], "oos_t": flat_metrics["oos_t"]},
        },
        "scaling_beats_static": scaling_beats_static,
        "scaling_beats_flat": scaling_beats_flat,
        "per_window_5bps": pw,
        "max_dd_5bps": mdd_5bps,
        "n_positive_windows": n_pos_windows,
        "w5_ann_pct": w5_ann,
        "combined_book": combined,
        "verdict": {
            "band": verdict_band,
            "verdict_string": verdict,
            "passes_3check_5bps": passes_3check_5bps,
            "survives_realistic_10bps": survives_realistic_10bps,
            "max_dd_ok": maxdd_ok,
            "w5_ok": w5_ok,
            "n_positive_windows_ok": n_pos_ok,
            "bull_pct_ok": bull_pct_ok,
            "scaling_adds_value": scaling_adds_value,
            "combined_sharpe_lifts_r77": combined_sharpe_lifts_r77,
        },
        "live_book_impact": {
            "touches_frozen_r77_cell": False,
            "strategy_2_slot_eligible": verdict_band == "TRADEABLE",
            "note": "R94 is Layer 2 of §TRADER_TOM two-layer book; R77 (Layer 1) frozen at "
                    "w_R46=0.25/w_R62=0.75/w_R76=0.30 unchanged.",
        },
    }
    return out


def format_report(payload: dict) -> str:
    """Human-readable R94 report."""
    lines = []
    lines.append("# R94 — §TRADER_TOM Two-Layer Book: Directional Crypto Beta Sleeve (L2)")
    lines.append(f"**Run date:** {datetime.now().isoformat(timespec='seconds')}")
    lines.append("")
    lines.append("## Construction")
    c = payload["construction"]
    lines.append(f"- Universe: {c['universe']} (3-asset crypto beta sleeve, equal-weight)")
    lines.append(f"- Base weight: {c['base_weight']:.4f} each")
    lines.append(f"- Cadence: {c['rebal_days']}d allocation rebal (weekly)")
    lines.append(f"- Cost grid: {c['cost_grid']} bps")
    lines.append(f"- Realistic cost gate: {c['realistic_cost_bps']} bps")
    lines.append(f"- maxDD budget: {c['maxdd_budget']:.0%} (tighter than R92's −30%)")
    lines.append(f"- Two-layer intent: {c['two_layer_intent']}")
    lines.append("")
    lines.append("## Regime distribution on panel")
    for s, n in payload["regime_distribution"].items():
        scalar = c["regime_map"].get(s, 0.0)
        lines.append(f"- {s}: {n} days (gross={scalar:.2f})")
    lines.append("")
    lines.append(f"**Bull-active (gross ≥ 1.0): {payload['bull_active_pct']:.1f}%**")
    lines.append("")
    lines.append("## Gross scalar distribution (after 1-day lag)")
    for v, n in payload["gross_scalar_distribution"].items():
        lines.append(f"- {v}: {n} days")
    lines.append("")
    lines.append("## Verdict")
    vd = payload["verdict"]
    lines.append(f"**{vd['band']}** — {vd['verdict_string']}")
    lines.append("")
    lines.append(f"- Passes 3-check at 5bps: **{vd['passes_3check_5bps']}**")
    lines.append(f"- Survives realistic 10bps cost: **{vd['survives_realistic_10bps']}**")
    lines.append(f"- maxDD OK (>{payload['construction']['maxdd_budget']:.0%}): **{vd['max_dd_ok']}** "
                 f"(actual = {payload['max_dd_5bps']:+.2%})")
    lines.append(f"- W5 sign-positive: **{vd['w5_ok']}** (W5 = {payload['w5_ann_pct']:+.1f}%)")
    lines.append(f"- ≥5/6 positive windows: **{vd['n_positive_windows_ok']}** "
                 f"({payload['n_positive_windows']}/6)")
    lines.append(f"- Bull-active ≥ 15%: **{vd['bull_pct_ok']}**")
    lines.append(f"- Scaling beats static + flat: **{vd['scaling_adds_value']}**")
    lines.append(f"- Combined-book Sharpe lifts R77: **{vd['combined_sharpe_lifts_r77']}**")
    lines.append("")
    lines.append("## Cost-tier sweep (R32/R89/R90 lesson #58 — MANDATORY)")
    lines.append("")
    lines.append("| cost_bps | full_t | OOS_t | full_ann% | OOS_ann% | passes_all |")
    lines.append("|----------|--------|-------|-----------|----------|------------|")
    for k, v in payload["cost_tier_sweep"].items():
        marker = " ← GATE" if float(k.replace("bps", "")) == R94_REALISTIC_COST_BPS else ""
        lines.append(f"| {k} | {v['full_t']:+.3f} | {v['oos_t']:+.3f} | "
                     f"{v['full_ann_pct']:+.1f}% | {v['oos_ann_pct']:+.1f}% | "
                     f"{'YES' if v['passes_all'] else 'NO'} |{marker}")
    lines.append("")
    lines.append("## Benchmark comparisons (regime scaler vs static beta)")
    lines.append("")
    bm = payload["benchmarks"]
    lines.append("| Sleeve | full_t | OOS_t | Sharpe | maxDD |")
    lines.append("|--------|--------|-------|--------|-------|")
    lines.append(f"| R94 (default 5bps) | {payload['default_cell_5bps']['full_t']:+.3f} | "
                 f"{payload['default_cell_5bps']['oos_t']:+.3f} | {bm['r94']['sharpe']:+.3f} | "
                 f"{bm['r94']['max_dd']:+.2%} |")
    lines.append(f"| static_beta (1/3, no scaling) | {bm['static_beta']['full_t']:+.3f} | "
                 f"{bm['static_beta']['oos_t']:+.3f} | {bm['static_beta']['sharpe']:+.3f} | "
                 f"{bm['static_beta']['max_dd']:+.2%} |")
    lines.append(f"| BTC-only (with scaling) | {bm['btc_only']['full_t']:+.3f} | "
                 f"{bm['btc_only']['oos_t']:+.3f} | {bm['btc_only']['sharpe']:+.3f} | "
                 f"{bm['btc_only']['max_dd']:+.2%} |")
    lines.append(f"| regime-flat (gross=1.0) | {bm['regime_flat']['full_t']:+.3f} | "
                 f"{bm['regime_flat']['oos_t']:+.3f} | {bm['regime_flat']['sharpe']:+.3f} | "
                 f"{bm['regime_flat']['max_dd']:+.2%} |")
    lines.append("")
    lines.append(f"- Scaling beats static_beta (OOS_t): **{payload['scaling_beats_static']}**")
    lines.append(f"- Scaling beats regime_flat (OOS_t): **{payload['scaling_beats_flat']}**")
    lines.append("")
    lines.append("## Per-window W1–W6 at default cell (5bps)")
    lines.append(f"**maxDD = {payload['max_dd_5bps']:+.2%}**")
    lines.append("")
    lines.append("| Window | n_days | ann_pct | maxDD |")
    lines.append("|--------|--------|---------|-------|")
    for label in ("W1", "W2", "W3", "W4", "W5", "W6"):
        if label in payload["per_window_5bps"]:
            pw = payload["per_window_5bps"][label]
            lines.append(f"| {label} | {pw['n_days']:6d} | {pw['ann_pct']:+.1f}% | "
                         f"{pw['max_dd']:+.2%} |")
    lines.append("")
    lines.append("## Combined-book check (R77 + R94, L1 + L2)")
    cb = payload["combined_book"]
    if cb.get("available"):
        lines.append(f"- corr(R94, R77) = {cb['corr_r94_r77']:+.3f}")
        lines.append(f"- R77 Sharpe = {cb['r77_sharpe']:+.3f}, maxDD = {cb['r77_max_dd']:+.2%}")
        lines.append(f"- R94 Sharpe = {cb['r94_sharpe']:+.3f}, maxDD = {cb['r94_max_dd']:+.2%}")
        lines.append(f"- Combined (50/50) Sharpe = {cb['combined_sharpe']:+.3f}, "
                     f"maxDD = {cb['combined_max_dd']:+.2%}")
        lines.append(f"- Combined OOS_t lift = {cb['oos_t_lift']:+.3f}")
        lines.append(f"- Sharpe lift = {cb['sharpe_lift']:+.3f}")
        lines.append(f"- maxDD increase = {cb['max_dd_increase']:+.2%}")
    else:
        lines.append(f"- **NOT AVAILABLE** — {cb.get('note', 'unknown')}")
        lines.append("- R77 PnL was not persisted in any reports dir; combined-book check skipped.")
    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", type=Path, default=None)
    args = parser.parse_args()

    today = datetime.now().strftime("%Y-%m-%d")
    out = args.out_dir or Path(f"reports/r94_directional_crypto_beta/{today}")
    payload = run(out)

    out.mkdir(parents=True, exist_ok=True)
    verdict_path = out / "verdict.json"
    report_path = out / "REPORT.md"
    with verdict_path.open("w") as f:
        json.dump(payload, f, indent=2, default=str)
    with report_path.open("w") as f:
        f.write(format_report(payload))

    print(f"Wrote {verdict_path}")
    print(f"Wrote {report_path}")
    print()
    print(format_report(payload))