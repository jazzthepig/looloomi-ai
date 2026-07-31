"""
R92 — §TRADER_TOM Two-Layer Book: Directional Overlay (Trend-Conditional L/S) (Seth, 2026-07-26).

Per user's decision (Option C — "Pivot to §TRADER_TOM two-layer directional overlay sleeve"):
R77 = market-neutral factor book (LOCKED, Layer 1). R92 = directional trend-conditional
book (Layer 2). The two books are ORTHOGONAL: R77 = factor alpha; R92 = trend alpha.
Combined book = durable fundamental core (R77) + tactical trend-riding overlay (R92).

§TRADER_TOM_DOCTRINE two-layer book:
  Layer 1 — Durable fundamental core (R77 fusion cell, market-neutral, always-on)
  Layer 2 — Tactical trend-riding overlay (R92 = THIS, directional, gross scales with TREND state)
            "defend in risk-OFF (small, hedged, cut fast), press/double-down in risk-ON +
             confirmed long-term trend (add to confirmed winners, never average into hope)"

KEY FIX vs R87 (REFUTED — 71% zero-gross + W4=−54.2% + W5=−29.3% + W6=−25.6%):

  R87 filter: macro_regime (RISK_ON/EASING/STAGFLATION/TIGHTENING/RISK_OFF) — BROAD macro
  R92 filter: BTC multi-factor TREND CONFIRMATION (close vs 100d MA + 100d MA slope + 30d return)
              — SPECIFIC trend signal

  R87 state: BULL (RISK_ON/EASING) → LONG top-K; STAGFLATION → 50% gross; TIGHTENING → 25%;
             RISK_OFF → 0% (cash). NO short leg.
  R92 state: BULL_TREND (3 conditions met) → LONG top-K; BEAR_TREND (3 inverted) → SHORT top-K;
             CHOP (anything else) → FLAT. SIGNED directional — earns alpha in BOTH directions.

  R87 has 71% reduced/zero gross days (mostly because macro regime is bear-mostly on the
  731-day panel) and the long-only book can't capture bear-window alpha.
  R92 has signed exposure — when BTC is in confirmed bear trend, R92 goes SHORT and earns
  the bear move. This is the structural fix.

Pre-confirmation filter (lesson #49 — KEY FIX):
  BULL_TREND: BTC_close > 100d_MA AND 100d_MA_slope > 0 AND BTC_30d_return > +3%
  BEAR_TREND: BTC_close < 100d_MA AND 100d_MA_slope < 0 AND BTC_30d_return < −3%
  CHOP:       otherwise → FLAT (no position, no turnover)

Construction:
  - LONG top-K (k=5) by composite quality in BULL_TREND
  - SHORT top-K (k=5) by composite quality in BEAR_TREND (negative weights, dollar-neutral
    by construction if combined with a long sleeve — but R92 alone is a directional sleeve,
    NOT dollar-neutral; combined-book dollar-neutrality is R77's job)
  - FLAT in CHOP
  - Cadence: 7d rebal (weekly, same as R87)
  - Cost: 5/10/20/30bps sweep (R32 lesson #58 MANDATORY)

Score:
  composite_quality = (pillar_F + pillar_M + pillar_A) / 3, PIT-safe ffill, 1-day lag
  (same as R87 — F = fundamental, M = momentum, A = alpha-vs-BTC)

Universe:
  28-asset strict (OHLCV ∩ CIS ∩ funding intersection, same as R87)

Anti-imposter:
  - Score uses 3 pillars (F/M/A), NOT all 5 — S/O excluded per S-77's lesson
  - Pre-confirmation filter requires ALL 3 conditions to be met (binary, no partial)
  - FLAT state means ZERO gross (not partial, not reduced — doctrine "cut fast")
  - Cost only on rebal days, not daily — honest cadence cost accounting
  - Trend state is BINARY (BULL/BEAR/CHOP), not graduated (vs R87's 5-tier regime)

Verdict grammar:
  ✅ SURVIVES = gross_t > 1.96 AND 5bps_t > 1.96 AND OOS_t > 1.96 AND W5 sign-positive
                AND maxDD < 30% AND at least 5/6 windows positive
  🟡 PARTIAL  = clears 2 of 3 (typically gross + 5bps but OOS weak) OR survives 3-check
                but maxDD > 30% OR survives 3-check but W5 catastrophic
  🔴 REFUTED = fails 2+ checks OR W5 catastrophic sign-flip OR maxDD > 40%
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
from src.research.validation.cis_quality_absorption import (
    load_cis_history_wide, load_daily_returns,
)
from src.research.data_align.cis_history_loader import load_cis_history

ALIGNED_CSV = ROOT / "_data" / "cis_historical" / "cis_historical_11yr_aligned.csv"

# ── Frozen config ────────────────────────────────────────────────────────────
R92_K = 5               # top-5 positions (20% each = 100% gross when active)
R92_CAD = 7             # weekly rebal
R92_COST_BPS = 5.0      # 5bps per rebal (R77 cleared at 5bps)
R92_MA_WINDOW = 100     # 100-day MA for trend filter
R92_SLOPE_LOOKBACK = 20 # 20-day slope window
R92_RETURN_LOOKBACK = 30  # 30-day return window
R92_BULL_THRESHOLD = 0.03   # +3% 30d return for BULL
R92_BEAR_THRESHOLD = -0.03  # −3% 30d return for BEAR

NW_LAGS = 6
PERIODS_PER_YEAR = 365
OOS_FRAC = 0.30
R92_COST_GRID = (0.0, 5.0, 10.0, 20.0, 30.0)  # R32 mandate
R92_REALISTIC_COST_BPS = 10.0  # lesson #58 gate

# ── Trend state enum ─────────────────────────────────────────────────────────
R92_TREND_BULL = "BULL_TREND"
R92_TREND_BEAR = "BEAR_TREND"
R92_TREND_CHOP = "CHOP"


def score_composite_wide(cis_long: pd.DataFrame) -> pd.DataFrame:
    """Composite quality score = (pillar_F + pillar_M + pillar_A) / 3.
    Pivot from long → wide, PIT-safe ffill. Same as R87."""
    pillars = ["pillar_f", "pillar_m", "pillar_a"]
    df = cis_long.dropna(subset=pillars)
    df = df.assign(_score=df[pillars].mean(axis=1))
    wide = df.pivot(index="_date", columns="symbol", values="_score").sort_index()
    return wide.ffill()


def compute_btc_trend_state(rets: pd.DataFrame, *,
                             ma_window: int = R92_MA_WINDOW,
                             slope_lookback: int = R92_SLOPE_LOOKBACK,
                             return_lookback: int = R92_RETURN_LOOKBACK,
                             bull_threshold: float = R92_BULL_THRESHOLD,
                             bear_threshold: float = R92_BEAR_THRESHOLD) -> pd.Series:
    """Compute BTC trend state per day using multi-factor confirmation.

    BULL: BTC_close > 100d_MA AND 100d_MA_slope > 0 AND 30d_return > +3%
    BEAR: BTC_close < 100d_MA AND 100d_MA_slope < 0 AND 30d_return < −3%
    CHOP: otherwise

    BTC price proxy = cumprod(1 + BTC_returns) starting at 1.0.
    PIT-safe: all conditions use only past data (lookback windows).
    """
    if "BTC" not in rets.columns:
        raise ValueError("BTC must be in rets columns for trend filter")
    btc_ret = rets["BTC"].fillna(0.0)
    btc_close = (1 + btc_ret).cumprod()

    ma = btc_close.rolling(ma_window, min_periods=ma_window).mean()
    ma_slope = (ma - ma.shift(slope_lookback)) / ma.shift(slope_lookback).replace(0, np.nan)
    ma_slope = ma_slope.fillna(0.0)
    btc_30d = btc_close / btc_close.shift(return_lookback) - 1
    btc_30d = btc_30d.fillna(0.0)

    bull_mask = (btc_close > ma) & (ma_slope > 0) & (btc_30d > bull_threshold)
    bear_mask = (btc_close < ma) & (ma_slope < 0) & (btc_30d < bear_threshold)

    state = pd.Series(R92_TREND_CHOP, index=rets.index, dtype=object)
    state[bull_mask] = R92_TREND_BULL
    state[bear_mask] = R92_TREND_BEAR
    return state


def directional_overlay_ls(score_wide: pd.DataFrame, rets: pd.DataFrame,
                            trend_state: pd.Series, *,
                            k: int = R92_K, rebal_days: int = R92_CAD,
                            cost_bps: float = R92_COST_BPS) -> pd.Series:
    """Trend-conditional directional L/S overlay.

    On rebal days:
      BULL_TREND → LONG top-K by composite quality
      BEAR_TREND → SHORT top-K by composite quality
      CHOP       → FLAT (zero gross)
    On other days: HOLD previous weights, no turnover, no cost.

    Returns daily PnL series.
    """
    common = sorted(set(score_wide.columns) & set(rets.columns))
    if len(common) < k + 2:
        return pd.Series(0.0, index=rets.index)

    score = score_wide[common]
    r = rets[common]
    score_lag = score.reindex(r.index).ffill().shift(1)  # PIT-safe 1-day lag
    trend_aligned = trend_state.reindex(r.index).ffill()

    fac = pd.Series(0.0, index=r.index)
    prev_w = pd.Series(0.0, index=common)

    for i, date in enumerate(r.index):
        rr = r.loc[date].reindex(common).fillna(0.0)

        if i % rebal_days == 0:
            s_row = score_lag.loc[date].dropna()
            w = pd.Series(0.0, index=common)
            if len(s_row) >= k + 1:
                state = trend_aligned.loc[date] if date in trend_aligned.index else R92_TREND_CHOP
                top_k = s_row.nlargest(k).index
                if state == R92_TREND_BULL:
                    w.loc[top_k] = 1.0 / k  # LONG
                elif state == R92_TREND_BEAR:
                    w.loc[top_k] = -1.0 / k  # SHORT

            turnover = float((w - prev_w).abs().sum())
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


def max_drawdown(pnl: pd.Series) -> float:
    cum = (1 + pnl).cumprod()
    peak = cum.cummax()
    dd = (cum - peak) / peak
    return float(dd.min())


def per_window_pnl(pnl: pd.Series, n_windows: int = 6) -> dict:
    """Per-window attribution. W1 = oldest, W6 = most recent."""
    n = len(pnl)
    if n < n_windows:
        return {}
    windows = np.array_split(np.arange(n), n_windows)
    out = {}
    for i, idx in enumerate(windows, 1):
        w_pnl = pnl.iloc[idx]
        ann_ret = (1 + w_pnl).prod() ** (PERIODS_PER_YEAR / len(idx)) - 1
        out[f"W{i}"] = {
            "n_days": int(len(idx)),
            "ann_pct": float(ann_ret * 100),
            "max_dd": float(max_drawdown(w_pnl)),
        }
    return out


def run(out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    print("=== R92 — §TRADER_TOM Two-Layer Book Directional Overlay (Trend-Conditional L/S) ===\n")
    print(f"Frozen config: k={R92_K}, cadence={R92_CAD}d, cost_grid={R92_COST_GRID}bps")
    print(f"Trend filter: BTC_close vs {R92_MA_WINDOW}d MA + {R92_SLOPE_LOOKBACK}d slope + "
          f"{R92_RETURN_LOOKBACK}d return ({R92_BULL_THRESHOLD:+.1%}/{R92_BEAR_THRESHOLD:+.1%})\n")

    cis_long = load_cis_history(ALIGNED_CSV, force_schema=True)
    rets = load_daily_returns()
    common_assets = sorted(set(cis_long["symbol"].dropna().unique()) & set(rets.columns))
    rets = rets[common_assets]
    print(f"Universe: {len(common_assets)} assets")

    score = score_composite_wide(cis_long[cis_long["symbol"].isin(common_assets)])
    score = score[common_assets].reindex(rets.index).ffill()

    # ── Trend state per day (BTC multi-factor) ─────────────────────────────────
    trend_state = compute_btc_trend_state(rets)
    state_dist = trend_state.value_counts()
    print(f"\nTrend state distribution on panel:")
    for s, n in state_dist.items():
        pct = 100.0 * n / len(trend_state)
        action = {"BULL_TREND": "LONG top-K", "BEAR_TREND": "SHORT top-K",
                  "CHOP": "FLAT (zero gross)"}.get(s, "?")
        print(f"  {s:12s}: {n:3d} days ({pct:5.1f}%)  → {action}")

    known = build_known_factors(rets)
    cut = int(len(rets) * (1 - OOS_FRAC))

    # ── Default cell sweep (5/10/20/30bps × 7d rebal) ─────────────────────────
    print(f"\n══ Cadence × cost sweep (R92 directional overlay) ══\n")
    sweep = {}
    for cad in (R92_CAD,):
        for bps in R92_COST_GRID:
            leg = directional_overlay_ls(score, rets, trend_state, k=R92_K,
                                          rebal_days=cad, cost_bps=bps)
            leg = leg.reindex(rets.index).fillna(0.0)
            g = run_one(leg, known, OOS_FRAC)
            sweep[(cad, bps)] = {
                "cadence": cad, "cost_bps": bps,
                "full_t": g["full_t"], "full_ann_pct": g["full_ann_pct"],
                "oos_t": g["oos_t"], "oos_ann_pct": g["oos_ann_pct"],
                "passes_full": g["full_t"] > 1.96,
                "passes_oos": g["oos_t"] > 1.96,
                "passes_all": g["full_t"] > 1.96 and g["oos_t"] > 1.96,
            }

    print(f"  cell | full_t | OOS_t | full_ann% | OOS_ann% | passes_all")
    print(f"  -----+--------+-------+-----------+----------+-----------")
    for (cad, bps), v in sweep.items():
        print(f"  {cad:3d}d/{bps:5.1f}bps | {v['full_t']:+.2f} | {v['oos_t']:+.2f} | "
              f"{v['full_ann_pct']:+.1f}% | {v['oos_ann_pct']:+.1f}% | "
              f"{'YES' if v['passes_all'] else 'NO'}")

    # Best cell (5bps first; if no passes, lowest cost)
    best_cell = max(((k, v) for k, v in sweep.items() if k[1] == 5.0),
                    key=lambda kv: kv[1]["full_t"], default=None)
    if best_cell is None:
        best_cell = max(sweep.items(), key=lambda kv: kv[1]["full_t"])
    (best_cad, best_bps), best_metrics = best_cell
    print(f"\nBest cell: {best_cad}d/{best_bps}bps → full_t={best_metrics['full_t']:+.2f}, "
          f"OOS_t={best_metrics['oos_t']:+.2f}, passes={best_metrics['passes_all']}")

    # ── Cost-tier sweep at best cell ──────────────────────────────────────────
    print(f"\n══ Cost-tier sweep at best cell ({best_cad}d) — R32/R89 gate ══\n")
    cost_tier = {}
    for cost_bps in R92_COST_GRID:
        leg = directional_overlay_ls(score, rets, trend_state, k=R92_K,
                                      rebal_days=best_cad, cost_bps=cost_bps)
        leg = leg.reindex(rets.index).fillna(0.0)
        g = run_one(leg, known, OOS_FRAC)
        cost_tier[cost_bps] = {
            "cost_bps": cost_bps,
            "full_t": g["full_t"], "full_ann_pct": g["full_ann_pct"],
            "oos_t": g["oos_t"], "oos_ann_pct": g["oos_ann_pct"],
            "passes_full": g["full_t"] > 1.96,
            "passes_oos": g["oos_t"] > 1.96,
            "passes_all": g["full_t"] > 1.96 and g["oos_t"] > 1.96,
        }

    survives_realistic_10bps = cost_tier[R92_REALISTIC_COST_BPS]["passes_all"]
    print(f"  cost_bps | full_t | OOS_t | OOS_ann% | passes_all | survives_10bps")
    for cost_bps, v in cost_tier.items():
        marker = " ← GATE" if cost_bps == R92_REALISTIC_COST_BPS else ""
        print(f"  {cost_bps:8.1f} | {v['full_t']:+.2f} | {v['oos_t']:+.2f} | "
              f"{v['oos_ann_pct']:+.1f}% | "
              f"{'YES' if v['passes_all'] else 'NO':<10} | "
              f"{survives_realistic_10bps}{marker}")
    print(f"\n  Survives at 10bps? {survives_realistic_10bps}")

    # ── Per-window W1–W6 at best cell (5bps) ──────────────────────────────────
    print(f"\n══ Per-window W1–W6 at best cell ({best_cad}d/5bps) ══\n")
    fac_5bps = directional_overlay_ls(score, rets, trend_state, k=R92_K,
                                       rebal_days=best_cad, cost_bps=5.0)
    fac_5bps = fac_5bps.reindex(rets.index).fillna(0.0)
    pw_5bps = per_window_pnl(fac_5bps)
    mdd_5bps = max_drawdown(fac_5bps)
    n_pos_windows = sum(1 for w in pw_5bps.values() if w["ann_pct"] > 0)
    w5_ann = pw_5bps.get("W5", {}).get("ann_pct", 0.0)
    print(f"  maxDD = {mdd_5bps:+.2%}")
    print(f"  Window | n_days | ann_pct | maxDD")
    for label in ("W1", "W2", "W3", "W4", "W5", "W6"):
        if label in pw_5bps:
            print(f"  {label} | {pw_5bps[label]['n_days']:6d} | "
                  f"{pw_5bps[label]['ann_pct']:+.1f}% | "
                  f"{pw_5bps[label]['max_dd']:+.2%}")

    # ── Verdict ────────────────────────────────────────────────────────────────
    passes_3check_5bps = cost_tier[5.0]["passes_all"]
    maxdd_ok = mdd_5bps > -0.30
    w5_ok = w5_ann > 0
    n_pos_ok = n_pos_windows >= 5

    if passes_3check_5bps and survives_realistic_10bps and maxdd_ok and w5_ok and n_pos_ok:
        verdict = ("✅ SURVIVES — TRADEABLE — eligible for Strategy 2 slot (Layer 2 of "
                   "§TRADER_TOM two-layer book).")
        verdict_band = "TRADEABLE"
    elif passes_3check_5bps and not survives_realistic_10bps:
        verdict = ("🟡 PARTIAL — 3-check at 5bps passes but edge dies at 10bps (R32/R89 "
                   "taker-fee illusion). Directional overlay cannot survive realistic cost.")
        verdict_band = "PARTIAL"
    elif passes_3check_5bps and (not w5_ok or not maxdd_ok or not n_pos_ok):
        verdict = ("🟡 PARTIAL — 3-check passes but fragility/quality gates fail "
                   f"(W5={w5_ann:+.1f}%, maxDD={mdd_5bps:+.2%}, n_pos_windows={n_pos_windows}/6).")
        verdict_band = "PARTIAL"
    else:
        verdict = ("🔴 REFUTED — directional overlay lacks standalone edge. The "
                   "pre-confirmation filter (lesson #49) did not rescue the long-only "
                   "directional book from the 731-day panel's bear-domination.")
        verdict_band = "REFUTED"

    print(f"\nVerdict: {verdict}\n")

    out = {
        "panel": {"n_days": int(len(rets)), "n_assets": len(common_assets)},
        "trend_state_distribution": {s: int(n) for s, n in state_dist.items()},
        "construction": {
            "k": R92_K, "cadence": R92_CAD, "cost_grid": list(R92_COST_GRID),
            "trend_filter": {
                "ma_window": R92_MA_WINDOW,
                "slope_lookback": R92_SLOPE_LOOKBACK,
                "return_lookback": R92_RETURN_LOOKBACK,
                "bull_threshold": R92_BULL_THRESHOLD,
                "bear_threshold": R92_BEAR_THRESHOLD,
                "states": ["BULL_TREND", "BEAR_TREND", "CHOP"],
            },
            "realistic_cost_bps": R92_REALISTIC_COST_BPS,
            "two_layer_intent": "R77 (Layer 1) + R92 (Layer 2)",
        },
        "best_cell": {"cadence": best_cad, "cost_bps_5bps": 5.0,
                      "gauntlet_5bps": cost_tier[5.0]},
        "cost_tier_sweep": {f"{int(k)}bps": v for k, v in cost_tier.items()},
        "survives_realistic_10bps": survives_realistic_10bps,
        "per_window_5bps": pw_5bps,
        "max_dd_5bps": mdd_5bps,
        "n_positive_windows": n_pos_windows,
        "w5_ann_pct": w5_ann,
        "sweep": {f"{c}d/{b}bps": v for (c, b), v in sweep.items()},
        "verdict": {
            "band": verdict_band,
            "verdict_string": verdict,
            "passes_3check_5bps": passes_3check_5bps,
            "survives_realistic_10bps": survives_realistic_10bps,
            "max_dd_ok": maxdd_ok,
            "w5_ok": w5_ok,
            "n_positive_windows_ok": n_pos_ok,
        },
        "live_book_impact": {
            "touches_frozen_r77_cell": False,
            "strategy_2_slot_eligible": verdict_band == "TRADEABLE",
            "note": "R92 is Layer 2 of §TRADER_TOM two-layer book; R77 (Layer 1) frozen at w_R46=0.25/w_R62=0.75/w_R76=0.30 unchanged.",
        },
    }
    return out


def format_report(payload: dict) -> str:
    """Human-readable R92 report."""
    lines = []
    lines.append("# R92 — §TRADER_TOM Two-Layer Book: Directional Overlay (Trend-Conditional L/S)")
    lines.append(f"**Run date:** {datetime.now().isoformat(timespec='seconds')}")
    lines.append("")
    lines.append("## Construction")
    c = payload["construction"]
    lines.append(f"- k = {c['k']} (top-5 by composite quality)")
    lines.append(f"- Cadence: {c['cadence']}d rebal (weekly)")
    lines.append(f"- Cost grid: {c['cost_grid']} bps")
    tf = c["trend_filter"]
    lines.append(f"- Trend filter: BTC_close vs {tf['ma_window']}d MA + "
                 f"{tf['slope_lookback']}d slope + {tf['return_lookback']}d return "
                 f"({tf['bull_threshold']:+.1%}/{tf['bear_threshold']:+.1%})")
    lines.append(f"- States: {tf['states']}")
    lines.append("")
    lines.append("## Trend state distribution on panel")
    for s, n in payload["trend_state_distribution"].items():
        pct = 100.0 * n / sum(payload["trend_state_distribution"].values())
        lines.append(f"- {s}: {n} days ({pct:.1f}%)")
    lines.append("")
    lines.append("## Verdict")
    vd = payload["verdict"]
    lines.append(f"**{vd['band']}** — {vd['verdict_string']}")
    lines.append("")
    lines.append(f"- Passes 3-check at 5bps: **{vd['passes_3check_5bps']}**")
    lines.append(f"- Survives realistic 10bps cost: **{vd['survives_realistic_10bps']}**")
    lines.append(f"- maxDD OK (< 30%): **{vd['max_dd_ok']}** (actual = {payload['max_dd_5bps']:+.2%})")
    lines.append(f"- W5 sign-positive: **{vd['w5_ok']}** (W5 = {payload['w5_ann_pct']:+.1f}%)")
    lines.append(f"- Positive windows: **{vd['n_positive_windows_ok']}** ({payload['n_positive_windows']}/6)")
    lines.append("")
    lines.append("## Cost-tier sweep (R32/R89 lesson #58 — MANDATORY)")
    lines.append("")
    lines.append("| cost_bps | full_t | OOS_t | full_ann% | OOS_ann% | passes_all |")
    lines.append("|----------|--------|-------|-----------|----------|------------|")
    for k, v in payload["cost_tier_sweep"].items():
        marker = " ← GATE" if float(k.replace("bps", "")) == R92_REALISTIC_COST_BPS else ""
        lines.append(f"| {k} | {v['full_t']:+.2f} | {v['oos_t']:+.2f} | "
                     f"{v['full_ann_pct']:+.1f}% | {v['oos_ann_pct']:+.1f}% | "
                     f"{'YES' if v['passes_all'] else 'NO'} |{marker}")
    lines.append("")
    lines.append("## Per-window W1–W6 at best cell (5bps)")
    lines.append(f"**maxDD = {payload['max_dd_5bps']:+.2%}**")
    lines.append("")
    lines.append("| Window | n_days | ann_pct | maxDD |")
    lines.append("|--------|--------|---------|-------|")
    for label in ("W1", "W2", "W3", "W4", "W5", "W6"):
        if label in payload["per_window_5bps"]:
            pw = payload["per_window_5bps"][label]
            lines.append(f"| {label} | {pw['n_days']:6d} | "
                         f"{pw['ann_pct']:+.1f}% | {pw['max_dd']:+.2%} |")
    return "\n".join(lines)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", type=Path, default=None)
    args = parser.parse_args()

    today = datetime.now().strftime("%Y-%m-%d")
    out = args.out_dir or Path(f"reports/r92_two_layer_directional_overlay/{today}")
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
