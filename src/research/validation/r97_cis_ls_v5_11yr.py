"""R97 dual-horizon trend L/S — 11yr daily-bar version.

Per user direction 2026-07-27: re-run the dual-horizon shape on the 11yr
multi-cycle panel to test whether R97's REFUTED-on-731-day-panel verdict is
a real no-edge signal OR a 731-day-bear-window artifact.

This is a fresh test, NOT a re-run of the 4h R97. The signal lookbacks
are different (4h EMA54/126 ≈ 9d/21d → daily EMA200/500 ≈ 9mo/22mo) because
the test window itself changed. Verdict is independent.

Signal (DAILY, frozen):
  Major trend:   EMA200/EMA500 daily
  Fast signal:   EMA50/EMA100 daily
  Direction rule: major is ceiling/floor; fast cannot REVERSE major
  Entry:         ADX14 ≥ 25 + DMI consistency
  Gates NOT applied on 11yr:
    - CIS gate (CIS history only spans 2024+, no 11yr coverage)
    - Funding z-veto (no 11yr funding coverage)
  ATR14 inverse-vol sizing, 5%/name cap, 100% gross cap
  5d rebal; PIT lag ≥ 1 bar

Output: daily aggregated return series + per-cycle breakdown.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

_VALIDATION_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _VALIDATION_DIR.parents[2]
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_VALIDATION_DIR))
from r97_panel_11yr import (
    Panel11yr,
    DAILY_R97_PARAMS,
    freeze_universe,
    to_wide,
    CYCLE_WINDOWS,
)
from m_wo1_r77_episode_count_audit import (
    EPISODE_COUNT_FLOOR,
    EPISODE_T_FLOOR,
    aggregate_episodes,
    segment_episodes,
)


# ── Indicators (vectorized, no leakage — uses .shift(1) before scoring) ────
def _ema(series: pd.Series, span: int) -> pd.Series:
    """Standard EMA (adjust=False so it matches exchange convention)."""
    return series.ewm(span=span, adjust=False).mean()


def _adx(high: pd.DataFrame, low: pd.DataFrame, close: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """ADX (Average Directional Index) per Wilder. Vectorized per symbol column.

    Returns (adx, plus_di, minus_di) — three DataFrames, all aligned to (date, symbol).
    """
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = ((up_move > down_move) & (up_move > 0)) * up_move.clip(lower=0)
    minus_dm = ((down_move > up_move) & (down_move > 0)) * down_move.clip(lower=0)
    # True range: element-wise max of 3 DataFrames (avoids pd.concat MultiIndex trap)
    tr = np.maximum(np.maximum(high - low, (high - close.shift(1)).abs()),
                    (low - close.shift(1)).abs())
    atr = tr.ewm(alpha=1/period, adjust=False).mean()
    plus_di = 100 * plus_dm.ewm(alpha=1/period, adjust=False).mean() / atr.replace(0, np.nan)
    minus_di = 100 * minus_dm.ewm(alpha=1/period, adjust=False).mean() / atr.replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx = dx.ewm(alpha=1/period, adjust=False).mean()
    return adx, plus_di, minus_di


def _atr(high: pd.DataFrame, low: pd.DataFrame, close: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """ATR (Average True Range) per Wilder. Same vectorized pattern as _adx."""
    tr = np.maximum(np.maximum(high - low, (high - close.shift(1)).abs()),
                    (low - close.shift(1)).abs())
    return tr.ewm(alpha=1/period, adjust=False).mean()


# ── Signal construction ────────────────────────────────────────────────────
def build_dual_horizon_score_wide(panel: Panel11yr) -> pd.DataFrame:
    """Daily dual-horizon score: +1 long, -1 short, 0 flat.

    Direction rule (same as 4h R97 §2): major trend is the ceiling/floor.
    Fast signal CANNOT reverse major direction — if they disagree, side = 0.

    Output: wide DataFrame indexed by trade_date, columns=symbol, values ∈ {-1, 0, +1}.
    PIT-safe: all inputs shifted by 1 bar before scoring.
    """
    p = DAILY_R97_PARAMS
    open_w = to_wide(panel, "open")
    high_w = to_wide(panel, "high")
    low_w = to_wide(panel, "low")
    close_w = to_wide(panel, "close")

    # Major trend
    ema_major_fast = _ema(close_w, p["MAJOR_FAST"])
    ema_major_slow = _ema(close_w, p["MAJOR_SLOW"])
    major_dir = (ema_major_fast > ema_major_slow).astype(int) - (ema_major_fast < ema_major_slow).astype(int)

    # Fast signal
    ema_fast = _ema(close_w, p["FAST"])
    ema_slow = _ema(close_w, p["SLOW"])
    fast_dir = (ema_fast > ema_slow).astype(int) - (ema_fast < ema_slow).astype(int)

    # ADX + DMI (PIT-safe via .shift(1) below)
    adx, plus_di, minus_di = _adx(high_w, low_w, close_w, p["ADX_PERIOD"])

    # PIT lag ≥ 1 bar
    major_dir_lag = major_dir.shift(p["PIT_LAG_BARS"])
    fast_dir_lag = fast_dir.shift(p["PIT_LAG_BARS"])
    adx_lag = adx.shift(p["PIT_LAG_BARS"])
    plus_di_lag = plus_di.shift(p["PIT_LAG_BARS"])
    minus_di_lag = minus_di.shift(p["PIT_LAG_BARS"])

    # Direction rule: agreement = major × fast (+1 agree, -1 disagree, 0 flat)
    agreement = major_dir_lag * fast_dir_lag
    adx_ok = (adx_lag >= p["ADX_THRESHOLD"]).fillna(False)
    dmi_long = (plus_di_lag > minus_di_lag).fillna(False)
    dmi_short = (plus_di_lag < minus_di_lag).fillna(False)
    dmi_ok = ((major_dir_lag > 0) & dmi_long) | ((major_dir_lag < 0) & dmi_short)

    # Side: ±1 when agreement > 0 AND ADX AND DMI all pass; else 0.
    side = major_dir_lag.where((agreement > 0) & adx_ok & dmi_ok, 0.0)
    return side


# ── Risk / sizing ──────────────────────────────────────────────────────────
def atr_weights(side: pd.DataFrame, panel: Panel11yr) -> pd.DataFrame:
    """Build PIT-safe percentage-ATR target weights under hard risk caps."""
    p = DAILY_R97_PARAMS
    high_w = to_wide(panel, "high")
    low_w = to_wide(panel, "low")
    close_w = to_wide(panel, "close")
    atr_w = _atr(high_w, low_w, close_w, p["ATR_PERIOD"])
    lag = p["PIT_LAG_BARS"]
    pct_atr = atr_w.shift(lag) / close_w.shift(lag).replace(0, np.nan)

    raw_w = side / pct_atr.replace(0, np.nan)
    raw_w = raw_w.where(side.abs() > 0, 0.0).replace([np.inf, -np.inf], np.nan).fillna(0.0)

    # Balance long and short sleeves independently when both sides exist.
    long_raw = raw_w.clip(lower=0)
    short_raw = (-raw_w.clip(upper=0))
    long_sum = long_raw.sum(axis=1).replace(0, np.nan)
    short_sum = short_raw.sum(axis=1).replace(0, np.nan)
    has_both = long_sum.notna() & short_sum.notna()

    balanced = raw_w.copy()
    balanced.loc[has_both] = (
        long_raw.loc[has_both].div(long_sum.loc[has_both], axis=0) * 0.5
        - short_raw.loc[has_both].div(short_sum.loc[has_both], axis=0) * 0.5
    )

    # One-sided days remain directional, but never exceed the same book budget.
    one_sided = ~has_both
    one_gross = balanced.loc[one_sided].abs().sum(axis=1).replace(0, np.nan)
    balanced.loc[one_sided] = balanced.loc[one_sided].div(one_gross, axis=0)
    balanced = balanced.fillna(0.0)

    # Final caps are applied after every normalization step.
    capped = balanced.clip(-p["MAX_NAME_WEIGHT"], p["MAX_NAME_WEIGHT"])
    gross = capped.abs().sum(axis=1)
    scale = (p["MAX_BOOK_GROSS"] / gross.replace(0, np.nan)).clip(upper=1.0).fillna(0.0)
    capped = capped.mul(scale, axis=0)

    if (capped.abs().max(axis=1) > p["MAX_NAME_WEIGHT"] + 1e-12).any():
        raise AssertionError("per-name weight cap breached")
    if (capped.abs().sum(axis=1) > p["MAX_BOOK_GROSS"] + 1e-12).any():
        raise AssertionError("book gross cap breached")
    return capped


def hold_to_rebalance(target_w: pd.DataFrame, rebal_days: int) -> pd.DataFrame:
    """Refresh target weights every ``rebal_days`` rows and hold between dates."""
    if rebal_days < 1:
        raise ValueError("rebal_days must be >= 1")
    held = target_w.copy()
    mask = np.zeros(len(held), dtype=bool)
    mask[::rebal_days] = True
    held.loc[~mask] = np.nan
    return held.ffill().fillna(0.0)


def cycle_active_universe(panel: Panel11yr, cycle: tuple, min_obs: int = 200) -> tuple:
    """Return (effective_universe, n_active_min, n_active_median) for a cycle."""
    cn, cs, ce = cycle
    close_w = to_wide(panel, "close").loc[pd.Timestamp(cs):pd.Timestamp(ce)]
    coverage = close_w.notna().sum()
    eff = coverage[coverage >= min_obs].index.tolist()
    n_active = close_w.notna().sum(axis=1)
    return eff, int(n_active.min()) if len(n_active) else 0, float(n_active.median()) if len(n_active) else 0.0


def backtest(panel: Panel11yr, cost_bps: float = 5.0) -> dict:
    """Run R97 daily L/S on the panel with 5d rebalance, M-WO-1 episodes and signed gates."""
    p = DAILY_R97_PARAMS
    side = build_dual_horizon_score_wide(panel)
    target = atr_weights(side, panel)
    w = hold_to_rebalance(target, p["REBAL_DAYS"])

    close_w = to_wide(panel, "close")
    fwd_ret = close_w.pct_change().shift(-1)

    # PIT alignment check: target weights and forward returns only depend on
    # information that was public at the close of bar t.
    gross_daily = (w * fwd_ret).sum(axis=1, min_count=1)
    turnover = w.diff().abs().sum(axis=1) / 2.0
    turnover.iloc[0] = w.abs().sum(axis=1).iloc[0] / 2.0

    cost = turnover * (cost_bps / 1e4)
    net_daily = gross_daily - cost
    net_daily.name = "r97_11yr_net"

    # Per-cycle breakdown with effective universe disclosure
    cycle_pnl = {}
    cycle_summary = {}
    for cn, cs, ce in CYCLE_WINDOWS:
        cycle = (cn, cs, ce)
        eff, n_min, n_med = cycle_active_universe(panel, cycle)
        if len(eff) < 12:
            cycle_summary[cn] = {
                "n_days": 0,
                "status": "INSUFFICIENT",
                "effective_universe": eff,
                "active_min": n_min,
                "active_median": n_med,
            }
            cycle_pnl[cn] = pd.Series(dtype=float)
            continue

        cs_ts, ce_ts = pd.Timestamp(cs), pd.Timestamp(ce)
        c_pnl = net_daily.loc[cs_ts:ce_ts].dropna()
        if len(c_pnl) < 30:
            cycle_summary[cn] = {
                "n_days": int(len(c_pnl)),
                "status": "INSUFFICIENT",
                "effective_universe": eff,
                "active_min": n_min,
                "active_median": n_med,
            }
            cycle_pnl[cn] = c_pnl
            continue

        ann_ret = c_pnl.mean() * 365
        ann_vol = c_pnl.std() * np.sqrt(365)
        sharpe = ann_ret / ann_vol if ann_vol > 0 else 0
        cum = (1 + c_pnl).prod() - 1
        t_stat = c_pnl.mean() / (c_pnl.std() / np.sqrt(len(c_pnl))) if c_pnl.std() > 0 else 0.0
        cycle_pnl[cn] = c_pnl
        cycle_summary[cn] = {
            "n_days": int(len(c_pnl)),
            "ann_ret": float(ann_ret),
            "ann_vol": float(ann_vol),
            "sharpe": float(sharpe),
            "cum_ret": float(cum),
            "t_stat": float(t_stat),
            "sign": int(np.sign(c_pnl.mean())),
            "status": "OK",
            "effective_universe": eff,
            "active_min": n_min,
            "active_median": n_med,
        }

    nd = net_daily.dropna()
    gross_ann = nd.mean() * 365
    gross_vol = nd.std() * np.sqrt(365)
    sharpe = gross_ann / gross_vol if gross_vol > 0 else 0
    cum = (1 + nd).prod() - 1
    t_stat = nd.mean() / (nd.std() / np.sqrt(len(nd))) if nd.std() > 0 else 0
    cum_equity = (1 + nd).cumprod()
    peak = cum_equity.cummax()
    dd = (cum_equity - peak) / peak
    max_dd = float(dd.min()) if len(dd) else 0.0

    # M-WO-1 episode audit (gap>7d on |pnl| > zero_tol)
    episodes = segment_episodes(nd, gap_days=7, min_days=3, zero_tol=1e-9)
    agg = aggregate_episodes(episodes)
    m_wo1_pass = (
        agg["n_episodes"] >= EPISODE_COUNT_FLOOR
        and agg["sign_majority_positive"]
        and (not np.isnan(agg["pooled_positive_t"]))
        and agg["pooled_positive_t"] >= EPISODE_T_FLOOR
    )

    # The last-30% slice is no longer treated as a forward holdout. It is
    # reported only as a development-window diagnostic.
    oos_start = net_daily.index[int(len(net_daily) * 0.7)]
    oos = net_daily.loc[oos_start:].dropna()
    oos_t = oos.mean() / (oos.std() / np.sqrt(len(oos))) if oos.std() > 0 else 0.0
    oos_ann = oos.mean() * 365 if len(oos) else 0.0

    overall = {
        "n_days": int(len(nd)),
        "ann_ret": float(gross_ann),
        "ann_vol": float(gross_vol),
        "sharpe": float(sharpe),
        "cum_ret": float(cum),
        "t_stat": float(t_stat),
        "max_dd": max_dd,
        "late_window_30pct": {
            "is_holdout": False,
            "note": "development-only comparison; already consumed by prior R97 runs",
            "oos_ann": float(oos_ann),
            "oos_t": float(oos_t),
        },
        "m_wo1": {
            "n_episodes": int(agg["n_episodes"]),
            "n_positive": int(agg["n_positive"]),
            "n_negative": int(agg["n_negative"]),
            "sign_majority_positive": bool(agg["sign_majority_positive"]),
            "pooled_positive_t": float(agg["pooled_positive_t"])
            if not np.isnan(agg["pooled_positive_t"]) else None,
            "passes_m_wo1": bool(m_wo1_pass),
        },
    }

    return {
        "daily_pnl": net_daily,
        "weights": w,
        "target_weights": target,
        "cycle_pnl": cycle_pnl,
        "cycle_summary": cycle_summary,
        "overall": overall,
    }


def main() -> int:
    print("=" * 72)
    print("R97-11yr daily-bar backtest")
    print("=" * 72)
    panel = freeze_universe()
    print()
    print("Running backtest @ 5bps cost...")
    res = backtest(panel, cost_bps=5.0)

    print()
    print("=" * 72)
    print("OVERALL (full panel, 5bps cost, 5d rebalance)")
    print("=" * 72)
    o = res["overall"]
    print(f"  n_days:        {o['n_days']}")
    print(f"  ann_ret:       {o['ann_ret']:+.2%}")
    print(f"  ann_vol:       {o['ann_vol']:+.2%}")
    print(f"  Sharpe:        {o['sharpe']:+.3f}")
    print(f"  cum_ret:       {o['cum_ret']:+.2%}")
    print(f"  t_stat:        {o['t_stat']:+.3f}  (signed; need > 1.96)")
    print(f"  max_dd:        {o['max_dd']:+.2%}  (need > -20%)")
    late = o["late_window_30pct"]
    print(f"  late_window:   ann={late['oos_ann']:+.2%}  t={late['oos_t']:+.3f}  is_holdout={late['is_holdout']}")
    print(f"  M-WO-1:        episodes={o['m_wo1']['n_episodes']}  pos={o['m_wo1']['n_positive']}  "
          f"majority_pos={o['m_wo1']['sign_majority_positive']}  passes={o['m_wo1']['passes_m_wo1']}")

    print()
    print("=" * 72)
    print("PER-CYCLE (5bps cost)")
    print("=" * 72)
    n_pos_cycles = 0
    for cn, cs, ce in CYCLE_WINDOWS:
        s = res["cycle_summary"][cn]
        if s.get("status") != "OK":
            eff = len(s.get("effective_universe", []))
            print(f"  {cn:24s}  n_days={s['n_days']:>4d}  eff_universe={eff}  INSUFFICIENT")
            continue
        sign_mark = "🟢" if s["sign"] > 0 else "🔴"
        print(f"  {cn:24s}  n={s['n_days']:>4d}  ann={s['ann_ret']:+.2%}  "
              f"Sharpe={s['sharpe']:+.2f}  t={s['t_stat']:+.2f}  "
              f"eff={len(s['effective_universe'])}  {sign_mark}")
        if s["sign"] > 0:
            n_pos_cycles += 1

    print()
    print(f"Positive cycles: {n_pos_cycles}/{len(CYCLE_WINDOWS)}  (need ≥6/7 per M-WO-2)")

    print()
    print("=" * 72)
    print("M-WO-1 EPISODE AUDIT (gap>7d on |pnl|>zero_tol)")
    print("=" * 72)
    mwo1 = o["m_wo1"]
    print(f"  n_episodes:           {mwo1['n_episodes']}  (need ≥{EPISODE_COUNT_FLOOR})")
    print(f"  n_positive:           {mwo1['n_positive']}")
    print(f"  n_negative:           {mwo1['n_negative']}")
    print(f"  sign_majority_pos:    {mwo1['sign_majority_positive']}")
    pooled = mwo1["pooled_positive_t"]
    pooled_str = f"{pooled:+.3f}" if pooled is not None else "n/a"
    print(f"  pooled_positive_t:    {pooled_str}  (need ≥{EPISODE_T_FLOOR})")
    print(f"  passes_m_wo1:         {mwo1['passes_m_wo1']}")

    print()
    print("=" * 72)
    print("3-CHECK GAUNTLET (signed, after correction)")
    print("=" * 72)
    check_t = o["t_stat"] > 1.96
    check_dd = o["max_dd"] > -0.20
    check_cycles = n_pos_cycles >= 6
    check_mwo1 = mwo1["passes_m_wo1"]
    for nm, ok in [("gross_t > 1.96 (signed)", check_t),
                   ("maxDD > -20%", check_dd),
                   (f"≥6/7 pos cycles", check_cycles),
                   ("M-WO-1 episode gate", check_mwo1)]:
        print(f"  {'✅' if ok else '❌'}  {nm}")
    n_pass = sum([check_t, check_dd, check_cycles, check_mwo1])
    if check_t and check_dd and check_cycles and check_mwo1:
        verdict = "CORRECTED_BASELINE_SURVIVES"
    elif check_t and n_pos_cycles >= 5:
        verdict = "CORRECTED_BASELINE_PARTIAL"
    elif check_t:
        verdict = "CORRECTED_BASELINE_PARTIAL"
    else:
        verdict = "CORRECTED_BASELINE_REFUTED"
    print()
    late = o["late_window_30pct"]
    print(f"  late-window t (informational only): {late['oos_t']:+.3f}  is_holdout={late['is_holdout']}")
    print(f"  {n_pass}/4 passed → {verdict}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
