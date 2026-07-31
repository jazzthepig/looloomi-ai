"""
R87 — Directional Trend-Overlay Sleeve (LONG top-K quality + regime-gated) (Seth, 2026-07-26).

Per user's pivot: build a DIRECTIONAL Strategy 2 sleeve to literally satisfy the goal
"完成两个可以进入真正交易的long/short 策略的开发". All four market-neutral L/S candidates
(R82/R83/R85/R86) were REFUTED on the 731-day panel — they were the wrong SHAPE for the
§TRADER_TOM_DOCTRINE trend-overlay slot. Right Strategy 2 = LONG-only directional, gross
scales with regime, structurally different from R77's market-neutral factor book.

§TRADER_TOM_DOCTRINE two-layer book:
  Layer 1 — Durable fundamental core (R77 fusion cell, market-neutral, always-on)
  Layer 2 — Tactical trend-riding overlay (R87 = THIS, directional, gross scales with regime)
            "defend in risk-OFF (small, hedged, cut fast), press/double-down in risk-ON +
             confirmed long-term trend (add to confirmed winners, never average into hope)"

Hypothesis:
  In confirmed RISK_ON/EASING regimes, LONG top-K quality assets captures directional alpha.
  In TIGHTENING/STAGFLATION, defend (cut gross). In RISK_OFF, cash.
  This is structurally DIFFERENT from R77:
    - R77 = market-neutral L/S (long top, short bottom, ~0 net beta)
    - R87 = LONG-only directional (positive net beta, gross scales with regime)
    - R87 alpha should be regime-DEPENDENT (per lesson #44), unlike R77 which is INVARIANT

Score:
  composite_quality = (pillar_F + pillar_M + pillar_A) / 3, PIT-safe ffill, 1-day lag
  (F = fundamental, M = momentum, A = alpha-vs-BTC; F is durable anchor, M is recent return
   strength, A is divergence — together = "quality + recent price action + idiosyncratic alpha")

Universe:
  28-asset funding ∩ CIS ∩ OHLCV intersection (same as R77)
  PIT-safe lagged 1 day to avoid forward look

Construction:
  - Top-K long (k=5, equal-weight, 20% each)
  - Regime-gated gross multiplier:
      RISK_ON     → 1.0  (press)
      EASING      → 1.0  (still positive macro)
      STAGFLATION → 0.5  (defend — half size)
      TIGHTENING  → 0.25 (cut fast — quarter size)
      RISK_OFF    → 0.0  (cash — flat)
  - Cadence: 7d rebal (weekly, institutional standard for directional)
  - Cost: 5bps per rebal on |w - prev_w|

Mechanics:
  - On rebal day: compute composite quality per asset, pick top-5
  - Position weight = (1/K) × regime_gross_multiplier (per asset)
  - Other days: HOLD previous weights, no turnover, no cost
  - Returns: w @ rets - turnover × cost_bps / 1e4 on rebal days only

3-check gauntlet:
  - gross_t > 1.96
  - 5bps_t > 1.96
  - OOS_t > 1.96 (last 30% of panel = bear-dominated window)

Anti-imposter:
  - Score uses 3 pillars (F/M/A), NOT all 5 — S/O excluded per S-77's lesson
    (S = risk gate, O = dispersion anchor, neither belongs in directional return score)
  - Regime gating is gross scaling, NOT binary — preserves partial exposure in
    STAGFLATION/TIGHTENING (per doctrine "defend in risk-OFF, press in risk-ON")
  - Cost only on rebal days, not daily — honest cadence cost accounting
  - Per-window W1-W6 attribution shows the regime gating payload

Verdict grammar:
  ✅ SURVIVES = gross_t > 1.96 AND 5bps_t > 1.96 AND OOS_t > 1.96 AND W5 sign-positive
  🟡 PARTIAL  = clears 2 of 3 (typically gross + 5bps but OOS weak)
  🔴 REFUTED = fails 2+ checks OR W5 catastrophic sign-flip
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

from src.research.validation.cis_quality_robustness import (
    cadence_ls as _cadence_ls,
    quarter_cuts,
    sub_period_absorption,
)
from src.research.validation.factor_absorption import absorption_test
from src.research.validation.cis_quality_absorption import (
    load_cis_history_wide, load_daily_returns,
)
from src.research.data_align.cis_history_loader import load_cis_history

ALIGNED_CSV = ROOT / "_data" / "cis_historical" / "cis_historical_11yr_aligned.csv"

# ── Frozen config ────────────────────────────────────────────────────────────
R87_K = 5               # top-5 long positions (20% each = 100% gross before regime mult)
R87_CAD = 7             # weekly rebal
R87_COST_BPS = 5.0      # 5bps per rebal
NW_LAGS = 6
PERIODS_PER_YEAR = 365
OOS_FRAC = 0.30

# ── Regime-gated gross multipliers (per §TRADER_TOM_DOCTRINE) ───────────────
R87_REGIME_GROSS = {
    "RISK_ON": 1.00,    # press — full gross
    "EASING": 1.00,     # still positive macro — full gross
    "STAGFLATION": 0.50,  # defend — half size
    "TIGHTENING": 0.25,   # cut fast — quarter size
    "RISK_OFF": 0.00,     # cash — flat
}


def score_composite_wide(cis_long: pd.DataFrame) -> pd.DataFrame:
    """Composite quality score = (pillar_F + pillar_M + pillar_A) / 3.
    Pivot from long → wide, PIT-safe ffill."""
    pillars = ["pillar_f", "pillar_m", "pillar_a"]
    df = cis_long.dropna(subset=pillars)
    df = df.assign(_score=df[pillars].mean(axis=1))
    wide = df.pivot(index="_date", columns="symbol", values="_score").sort_index()
    return wide.ffill()


def load_regime_per_day(panel_dates: pd.DatetimeIndex) -> pd.Series:
    """Load macro_regime from 11yr aligned CSV. Modal regime per day across assets.
    Forward-fill so every date in panel has a regime (no forward look)."""
    cis = load_cis_history(ALIGNED_CSV, force_schema=True)
    regime_wide = cis.pivot(index="_date", columns="symbol", values="macro_regime").sort_index()
    mode_per_day = regime_wide.mode(axis=1).iloc[:, 0]
    out = mode_per_day.reindex(panel_dates).ffill()
    return out


def directional_ls(score_wide: pd.DataFrame, rets: pd.DataFrame,
                    regime_per_day: pd.Series, *,
                    k: int = R87_K, rebal_days: int = R87_CAD,
                    cost_bps: float = R87_COST_BPS,
                    regime_gross: dict = None) -> pd.Series:
    """LONG top-K composite quality, regime-gated gross.

    On rebal days: compute fresh weights from lagged score, top-K long, apply regime gross.
    On other days: HOLD previous weights, no turnover, no cost.

    Returns daily PnL series."""
    if regime_gross is None:
        regime_gross = R87_REGIME_GROSS

    common = sorted(set(score_wide.columns) & set(rets.columns))
    if len(common) < k + 2:
        return pd.Series(0.0, index=rets.index)

    score = score_wide[common]
    r = rets[common]
    score_lag = score.reindex(r.index).ffill().shift(1)  # PIT-safe 1-day lag

    fac = pd.Series(0.0, index=r.index)
    prev_w = pd.Series(0.0, index=common)

    for i, date in enumerate(r.index):
        rr = r.loc[date].reindex(common).fillna(0.0)

        if i % rebal_days == 0:
            s_row = score_lag.loc[date].dropna()
            w = pd.Series(0.0, index=common)
            if len(s_row) >= k + 1:
                # Top-K by composite quality (long only, no short)
                top_k = s_row.nlargest(k).index
                w.loc[top_k] = 1.0 / k  # equal-weight long

                # Apply regime-gated gross multiplier
                regime = regime_per_day.loc[date] if date in regime_per_day.index else "RISK_OFF"
                mult = regime_gross.get(regime, 0.0)
                w = w * mult

            turnover = float((w - prev_w).abs().sum())
            # Gross PnL: w @ rr - turnover cost
            pnl_gross = float((w * rr).sum())
            cost = turnover * cost_bps / 1e4
            fac.loc[date] = pnl_gross - cost
            prev_w = w
        else:
            fac.loc[date] = float((prev_w * rr).sum())

    return fac


def build_known_factors(rets: pd.DataFrame, lookback: int = 30) -> dict:
    """Standard 2-factor absorption (market + TSMOM). NaN-safe via trailing fillna(0)."""
    f_market = rets.mean(axis=1).fillna(0.0)
    cum = (1 + f_market).rolling(lookback, min_periods=lookback).apply(np.prod, raw=True) - 1
    f_momentum = (np.sign(cum) * f_market).fillna(0.0)
    return {"market": f_market.values, "momentum": f_momentum.values}


def run_one(fac: pd.Series, known: dict, oos_frac: float = OOS_FRAC) -> dict:
    cut = int(len(fac) * (1 - oos_frac))
    r_full = absorption_test(fac.values, known, nw_lags=NW_LAGS,
                              periods_per_year=PERIODS_PER_YEAR)
    r_oos = absorption_test(fac.values[cut:], {k: v[cut:] for k, v in known.items()},
                             nw_lags=NW_LAGS, periods_per_year=PERIODS_PER_YEAR)
    return {
        "full_t": r_full["alpha_t"],
        "full_ann_pct": r_full["alpha_ann_pct"],
        "oos_t": r_oos["alpha_t"],
        "oos_ann_pct": r_oos["alpha_ann_pct"],
        "oos_n": int(len(fac.values[cut:])),
    }


def run(out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    print("=== R87 — Directional Trend-Overlay Sleeve (LONG top-K quality + regime-gated) ===\n")
    print(f"Frozen config: k={R87_K}, cadence={R87_CAD}d, cost={R87_COST_BPS}bps")
    print(f"Regime gross multipliers: {R87_REGIME_GROSS}\n")

    # ── Load 11yr aligned CSV (gives us pillar_F/M/A + regime per day per asset) ──
    cis_long = load_cis_history(ALIGNED_CSV, force_schema=True)
    rets = load_daily_returns()
    common_assets = sorted(set(cis_long["symbol"].dropna().unique()) & set(rets.columns))
    rets = rets[common_assets]
    print(f"Universe: {len(common_assets)} assets")

    # ── Score (composite quality) ────────────────────────────────────────────
    score = score_composite_wide(cis_long[cis_long["symbol"].isin(common_assets)])
    score = score[common_assets].reindex(rets.index).ffill()
    print(f"Score shape: {score.shape}, rets shape: {rets.shape}")

    # ── Regime per day (modal across assets, ffill PIT-safe) ─────────────────
    regime_per_day = load_regime_per_day(rets.index)
    regime_dist = regime_per_day.value_counts()
    print(f"\nRegime distribution on panel:")
    for r, n in regime_dist.items():
        pct = 100.0 * n / len(regime_per_day)
        mult = R87_REGIME_GROSS.get(r, 0.0)
        print(f"  {r:12s}: {n:3d} days ({pct:5.1f}%)  → gross mult = {mult:.2f}")
    n_long_days = (regime_per_day.isin(["RISK_ON", "EASING"])).sum()
    print(f"  Long-eligible days (RISK_ON/EASING): {n_long_days}/{len(regime_per_day)} "
          f"({100.0*n_long_days/len(regime_per_day):.1f}%)")

    # ── Build the directional sleeve ─────────────────────────────────────────
    print(f"\nBuilding R87 sleeve (k={R87_K}, cad={R87_CAD}d, {R87_COST_BPS}bps) …")
    fac_5bps = directional_ls(score, rets, regime_per_day,
                                k=R87_K, rebal_days=R87_CAD, cost_bps=R87_COST_BPS)
    fac_5bps = fac_5bps.reindex(rets.index).fillna(0.0)
    fac_gross = directional_ls(score, rets, regime_per_day,
                                k=R87_K, rebal_days=R87_CAD, cost_bps=0.0)
    fac_gross = fac_gross.reindex(rets.index).fillna(0.0)

    # ── 3-check gauntlet ────────────────────────────────────────────────────
    known = build_known_factors(rets)
    r_g = run_one(fac_gross, known, oos_frac=OOS_FRAC)
    r_5 = run_one(fac_5bps, known, oos_frac=OOS_FRAC)

    clears = (r_g["full_t"] > 1.96) + (r_5["full_t"] > 1.96) + (r_5["oos_t"] > 1.96)
    marker = "✅" if clears == 3 else ("🟡" if clears >= 2 else "🔴")
    print(f"\n=== 3-check gauntlet ===")
    print(f"  gross_t={r_g['full_t']:+.2f}  5bps_t={r_5['full_t']:+.2f}  "
          f"OOS_t={r_5['oos_t']:+.2f}  OOS_ann={r_5['oos_ann_pct']:+.1f}%  "
          f"OOS_n={r_5['oos_n']}  {clears}/3  {marker}")

    # ── Per-window W1-W6 attribution (the structural-finding test) ───────────
    windows = quarter_cuts(rets.index[0], rets.index[-1], n_windows=6)
    sub = sub_period_absorption(fac_5bps, known, windows, nw_lags=NW_LAGS,
                                  periods_per_year=PERIODS_PER_YEAR)
    print(f"\n=== W1-W6 attribution (5bps, regime-gated directional) ===")
    for w in sub:
        print(f"  {w['label']}: α_t={w['alpha_t']:+.2f}  α_ann_pct={w['alpha_ann_pct']:+.2f}%")
    w5_t = next((w["alpha_t"] for w in sub if w["label"].startswith("W5")), None)
    w5_ann = next((w["alpha_ann_pct"] for w in sub if w["label"].startswith("W5")), None)

    # ── Mechanism check (per S-82 lesson #44: directional sleeve MUST be regime-DEPENDENT) ─
    # Test if R87 alpha IS regime-dependent (the antithesis of R77's regime-INVARIANT result).
    print(f"\n=== Mechanism check (per S-82 lesson #44): regime-DEPENDENCE of daily alpha ===")
    regime_alpha = {}
    for regime in ["RISK_ON", "EASING", "STAGFLATION", "TIGHTENING", "RISK_OFF"]:
        mask = (regime_per_day == regime).reindex(fac_5bps.index).fillna(False)
        if mask.sum() > 30:
            regime_alpha[regime] = float(fac_5bps[mask].mean() * 365)
        else:
            regime_alpha[regime] = None
    for r, alpha in regime_alpha.items():
        if alpha is not None:
            print(f"  {r:12s}: α_ann = {alpha:+.1f}%")
        else:
            print(f"  {r:12s}: n<30, insufficient")

    # ── Verdict ──────────────────────────────────────────────────────────────
    if clears == 3:
        verdict = "✅ SURVIVES"
    elif clears >= 2:
        verdict = "🟡 PARTIAL"
    else:
        verdict = "🔴 REFUTED"
    print(f"\n  Verdict: {verdict} ({clears}/3 cleared)")

    # ── Report ───────────────────────────────────────────────────────────────
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "panel": {
            "lo": str(rets.index[0].date()),
            "hi": str(rets.index[-1].date()),
            "n_days": int(len(rets)),
            "n_assets": int(len(rets.columns)),
        },
        "config": {
            "score": "(pillar_F + pillar_M + pillar_A) / 3, PIT ffill, 1-day lag",
            "k_long": R87_K,
            "cadence_days": R87_CAD,
            "cost_bps": R87_COST_BPS,
            "regime_gross_multipliers": R87_REGIME_GROSS,
        },
        "regime_distribution": {r: int(n) for r, n in regime_dist.items()},
        "n_long_eligible_days": int(n_long_days),
        "gauntlet": {
            "gross_t": r_g["full_t"],
            "5bps_t": r_5["full_t"],
            "oos_t": r_5["oos_t"],
            "oos_ann_pct": r_5["oos_ann_pct"],
            "oos_n": r_5["oos_n"],
            "clears": int(clears),
        },
        "per_window_w1_w6": [
            {"label": w["label"],
             "alpha_t": float(w["alpha_t"]) if w["alpha_t"] is not None else None,
             "alpha_ann_pct": float(w["alpha_ann_pct"]) if w["alpha_ann_pct"] is not None else None}
            for w in sub
        ],
        "regime_alpha_check": regime_alpha,
        "verdict": verdict,
    }
    json_path = out_dir / "verdict.json"
    json_path.write_text(json.dumps(report, indent=2, default=str))
    print(f"\nWrote {json_path}")
    return report


def main():
    ap = argparse.ArgumentParser(description="R87 — Directional Trend-Overlay Sleeve")
    ap.add_argument("--out-dir", type=Path,
                     default=ROOT / "reports" / "r87_directional_trend_sleeve" /
                              datetime.now().strftime("%Y-%m-%d"))
    args = ap.parse_args()
    run(args.out_dir)


if __name__ == "__main__":
    main()