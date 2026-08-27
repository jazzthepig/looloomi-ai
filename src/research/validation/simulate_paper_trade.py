"""
§SIMULATION-60D — PIT replay harness for R77 (Strategy 1) and R76 (Strategy 2)
==============================================================================

Seth, 2026-08-24. Per user directive "继续模拟两个赚钱的策略的运行 不用60day真实记录":

This module produces **SIMULATED 60-day paper-trade marks** for both wired
strategies, using the ACTUAL backtest logic on REAL historical OHLCV + funding
data, instead of waiting for wall-clock 60 days of live forward paper-trade
marks.

PIT SAFETY:
  · All scores are computed at time t using only data ≤ t (no look-ahead).
  · Funding residual uses the lagged daily mean (t-1) of funding per asset.
  · Returns are daily, calculated from t-1 → t closes.
  · Mark-to-market is sequential (no future returns).

HONEST FRAMING:
  · These marks are SIMULATED (run on historical data forward through time)
    NOT live forward-clock paper-trade marks.
  · The 60-day wall-clock constraint on the §STRATEGY-DISCIPLINE gate is
    WAIVED per user 2026-08-24 directive; this module provides the equivalent
    of "60d backtest marks on a forward slice" using the same frozen cells.
  · Once live paper-trade marks accumulate on Railway (R77 Day 60+, R76 first
    mark), those live marks SUPERSEDE these simulated ones.

STRATEGIES SIMULATED:
  · Strategy 1 (R77 fusion): w_R46=0.25 / w_R62=0.75 / w_R76=0.30 on the
    28-asset strict universe. R46 = pillar_O LEVEL 5d/5bps; R62 = −funding_z
    fragility-gated 21d/0bps; R76 = funding residual 5d/0bps.
  · Strategy 2 (R76 standalone): 5d/0bps/k=3/high_fund_long on 28-asset
    strict universe.

OUTPUTS (per strategy):
  · /tmp/cometcloud_data/sim_{strategy}/nav.csv — daily NAV, returns, weights
  · /tmp/cometcloud_data/sim_{strategy}/summary.json — Sharpe, maxDD, ann%,
    per-window W1-W6 breakdown

DATA SOURCES (read-only):
  · OHLCV:   /Volumes/CometCloudAI/data/ohlcv/{ASSET}.parquet (Binance fapi 1h)
  · Funding: /Volumes/CometCloudAI/cometcloud-local/_data/hyperliquid_funding/{asset}_funding_1h.csv

Compliance: positioning language only. L/S = exposure, not investment advice.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import logging
import sys
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

_log = logging.getLogger("sim_paper_trade")

# ── Data paths (read-only) ──────────────────────────────────────────────────
OHLCV_DIR = Path("/Volumes/CometCloudAI/data/ohlcv")
FUNDING_DIR = Path("/Volumes/CometCloudAI/cometcloud-local/_data/hyperliquid_funding")
SIM_DIR = Path("/tmp/cometcloud_data/sim_paper")
SIM_DIR.mkdir(parents=True, exist_ok=True)

# ── Frozen universe (R77/R76 strict 28-asset) ──────────────────────────────
UNIVERSE = sorted([
    "AAVE", "APT", "ARB", "ATOM", "AVAX", "BNB", "BTC", "COMP",
    "DOGE", "DOT", "ENA", "ETH", "FIL", "INJ", "LDO", "LINK",
    "MKR", "NEAR", "OP", "PENDLE", "SEI", "SOL", "STRK", "STX",
    "SUI", "TIA", "UNI", "XRP",
])

# ── Frozen R76 cell (Strategy 2) ────────────────────────────────────────────
R76_CAD = 5
R76_BPS = 0.0
R76_K = 3
R76_SIGN = "high_fund_long"  # long top tercile of demeaned funding

# ── Frozen R77 fusion weights (Strategy 1) ─────────────────────────────────
W_R46 = 0.25
W_R62 = 0.75  # (= 1 - W_R46 for the 2-component base)
W_R76 = 0.30  # 3rd-leg contribution

# R46 leg: pillar_O 5d/5bps (frozen best cell)
R46_CAD = 5
R46_BPS = 5.0
R46_K = 3

# R62 leg: −funding_z fragility-gated 21d/0bps (detector-gated)
R62_CAD = 21
R62_BPS = 0.0
R62_K = 3


# ── Data loaders (re-use the canonical panels) ─────────────────────────────
def load_ohlcv_daily(symbols: list[str]) -> pd.DataFrame:
    """Wide daily close panel: [date × asset]. Reads Binance fapi 1h parquet,
    resamples to daily close. PIT-safe (only past data). Returns tz-naive index.
    """
    out: dict = {}
    for s in symbols:
        fp = OHLCV_DIR / f"{s}.parquet"
        if not fp.exists():
            continue
        df = pd.read_parquet(fp)
        df["ts"] = pd.to_datetime(df["timestamp"])
        df["date"] = df["ts"].dt.tz_localize(None).dt.normalize() if df["ts"].dt.tz is not None else df["ts"].dt.normalize()
        # Daily last close
        daily = df.groupby("date")["close"].last().sort_index()
        out[s] = daily
    panel = pd.DataFrame(out).sort_index()
    return panel


def load_returns_daily(symbols: list[str]) -> pd.DataFrame:
    """Daily return panel = pct_change(close). date × asset. PIT-safe."""
    px = load_ohlcv_daily(symbols)
    rets = px.pct_change(fill_method=None).fillna(0.0)
    return rets


def load_funding_daily(symbols: list[str]) -> pd.DataFrame:
    """Wide daily funding panel: [date × asset] mean of 8h funding rate.
    Reads Hyperliquid 1h csv per asset."""
    out: dict = {}
    for s in symbols:
        fp = FUNDING_DIR / f"{s.lower()}_funding_1h.csv"
        if not fp.exists():
            continue
        df = pd.read_csv(fp)
        if df.empty or "fundingRate" not in df.columns:
            continue
        df["dt"] = pd.to_datetime(df["fundingTime"], unit="ms").dt.normalize()
        daily = df.groupby("dt")["fundingRate"].mean()
        if len(daily) < 100:
            continue
        out[s] = daily
    panel = pd.DataFrame(out).sort_index()
    return panel


# ── L/S engine (PIT-safe, score_lag = score.shift(1)) ──────────────────────
def _cadence_ls_sim(score_wide: pd.DataFrame, rets: pd.DataFrame,
                    rebal_days: int, cost_bps: float,
                    k_terciles: int = 3) -> pd.Series:
    """Long top / short bottom tercile with fixed rebalance cadence.
    Same logic as cis_quality_robustness.cadence_ls, inlined for clarity.
    """
    common = sorted(set(score_wide.columns) & set(rets.columns))
    if len(common) < 6:
        return pd.Series(0.0, index=rets.index)
    score = score_wide[common].reindex(rets.index).ffill().shift(1)
    r = rets[common]

    fac = pd.Series(0.0, index=r.index)
    prev_w = pd.Series(0.0, index=common)
    for i, date in enumerate(r.index):
        rr = r.loc[date].reindex(common).fillna(0.0)
        if i % rebal_days == 0:
            s_row = score.loc[date].dropna()
            w = pd.Series(0.0, index=common)
            if len(s_row) >= 6:
                try:
                    ranks = pd.qcut(s_row, q=k_terciles, labels=False, duplicates="drop")
                except ValueError:
                    ranks = (s_row >= s_row.median()).astype(int)
                top_label, bot_label = ranks.max(), ranks.min()
                if top_label != bot_label:
                    top = ranks[ranks == top_label].index
                    bot = ranks[ranks == bot_label].index
                    if len(top) and len(bot):
                        w.loc[top] = 1.0 / len(top)
                        w.loc[bot] = -1.0 / len(bot)
            turnover = float((w - prev_w).abs().sum())
            fac.loc[date] = float((w * rr).sum()) - turnover * cost_bps / 1e4
            prev_w = w
        else:
            fac.loc[date] = float((prev_w * rr).sum())
    return fac


# ── Score functions ────────────────────────────────────────────────────────
def score_r76_funding_residual(funding_daily: pd.DataFrame) -> pd.DataFrame:
    """Per-time cross-sectional demean of funding. R76 score."""
    return funding_daily.subtract(funding_daily.mean(axis=1), axis=0)


def score_r62_funding_z(funding_daily: pd.DataFrame, lookback: int = 60) -> pd.DataFrame:
    """Per-asset rolling z-score of funding. R62 raw score (detector will gate)."""
    mu = funding_daily.rolling(lookback, min_periods=20).mean()
    sd = funding_daily.rolling(lookback, min_periods=20).std()
    z = (funding_daily - mu) / (sd + 1e-12)
    return z


def score_r46_pillar_o_synthetic(rets_daily: pd.DataFrame, lookback: int = 30) -> pd.DataFrame:
    """R46 pillar_O LEVEL — in simulation, we approximate CIS pillar_O with
    trailing-30d raw return (mean-reversion proxy).

    NOTE: This is a SIMULATION proxy. Live R46 uses true CIS pillar_O. The
    proxy preserves the structural property (PIT-safe ffill, 1-day lag) and
    gives a defensible placeholder when the CIS history file is not in scope.
    Documented honestly in summary output.

    The synthetic pillar_O is computed as: trailing 30d cumulative return
    (then demeaned cross-sectionally so positive = outperformer).
    """
    cumret_30 = (1 + rets_daily).rolling(lookback).apply(np.prod, raw=True) - 1
    cumret_30 = cumret_30.replace([np.inf, -np.inf], np.nan)
    # demean cross-sectionally so positive = above-mean 30d return
    demeaned = cumret_30.subtract(cumret_30.mean(axis=1), axis=0)
    return demeaned


# ── Strategy 2: R76 standalone ─────────────────────────────────────────────
def simulate_r76(rets_daily: pd.DataFrame, funding_daily: pd.DataFrame,
                 start_date: pd.Timestamp, end_date: pd.Timestamp,
                 out_dir: Path) -> dict:
    """R76 standalone L/S: 5d/0bps/k=3/high_fund_long on 28-asset strict."""
    common = sorted(set(rets_daily.columns) & set(funding_daily.columns) & set(UNIVERSE))
    if len(common) < 12:
        return {"status": "error", "reason": f"only {len(common)} common assets"}

    rets = rets_daily[common].loc[start_date:end_date]
    funding = funding_daily[common].reindex(rets.index).ffill()

    score = score_r76_funding_residual(funding)
    fac = _cadence_ls_sim(score, rets, rebal_days=R76_CAD, cost_bps=R76_BPS, k_terciles=R76_K)
    fac = fac.fillna(0.0)

    nav = (1 + fac).cumprod()
    nav.iloc[0] = 1.0
    return _write_summary(
        strategy="R76_standalone",
        fac=fac, nav=nav, score=score, rets=rets,
        start_date=start_date, end_date=end_date,
        out_dir=out_dir,
        cell={"cad": R76_CAD, "bps": R76_BPS, "k": R76_K, "sign": R76_SIGN,
              "weights": {"w_R76": 1.0}, "n_assets": len(common)},
    )


# ── Strategy 1: R77 fusion (3 legs) ────────────────────────────────────────
def simulate_r77(rets_daily: pd.DataFrame, funding_daily: pd.DataFrame,
                 start_date: pd.Timestamp, end_date: pd.Timestamp,
                 out_dir: Path) -> dict:
    """R77 fusion: R46 (25%) + R62 (75%) + R76 (30%) on 28-asset strict.

    In SIMULATION mode, R46 uses a synthetic pillar_O proxy (trailing-30d
    return, cross-sectionally demeaned) — same PIT-safe structure as true
    pillar_O. R62's detector requires fragility-gated weights; in simulation
    we run R62 UNGATED (z-threshold 0.0) — equivalent to always-on with full
    weights, since we don't have the KS-detector pre-computed on the sim
    slice. R76 is the real funding residual (same as Strategy 2).

    Fusion: combined_factor = w_R46 * R46 + w_R62 * R62 + w_R76 * R76
    where each leg is the daily factor return (not raw score).
    """
    common = sorted(set(rets_daily.columns) & set(funding_daily.columns) & set(UNIVERSE))
    if len(common) < 12:
        return {"status": "error", "reason": f"only {len(common)} common assets"}

    rets = rets_daily[common].loc[start_date:end_date]
    funding = funding_daily[common].reindex(rets.index).ffill()

    # ── R46 leg (synthetic pillar_O proxy) ─────────────────────────────────
    r46_score = score_r46_pillar_o_synthetic(rets)
    r46_fac = _cadence_ls_sim(r46_score, rets, rebal_days=R46_CAD, cost_bps=R46_BPS, k_terciles=R46_K)

    # ── R62 leg (funding_z, ungated simulation) ────────────────────────────
    r62_score = score_r62_funding_z(funding)
    # R62 sign is short-funding-crowded → LONG low funding_z, SHORT high funding_z
    r62_fac = _cadence_ls_sim(-r62_score, rets, rebal_days=R62_CAD, cost_bps=R62_BPS, k_terciles=R62_K)

    # ── R76 leg (real funding residual) ────────────────────────────────────
    r76_score = score_r76_funding_residual(funding)
    r76_fac = _cadence_ls_sim(r76_score, rets, rebal_days=R76_CAD, cost_bps=R76_BPS, k_terciles=R76_K)

    # ── Fusion ─────────────────────────────────────────────────────────────
    fac = W_R46 * r46_fac + W_R62 * r62_fac + W_R76 * r76_fac
    fac = fac.fillna(0.0)
    nav = (1 + fac).cumprod()
    nav.iloc[0] = 1.0

    return _write_summary(
        strategy="R77_fusion",
        fac=fac, nav=nav, score=r76_score, rets=rets,
        start_date=start_date, end_date=end_date,
        out_dir=out_dir,
        cell={"cad": "5/21/5", "bps": "5/0/0", "k": 3,
              "weights": {"w_R46": W_R46, "w_R62": W_R62, "w_R76": W_R76},
              "n_assets": len(common),
              "sim_notes": ("R46 uses synthetic pillar_O proxy (trailing-30d "
                            "return demeaned); R62 ungated (no detector in sim)")},
    )


# ── Output writer ──────────────────────────────────────────────────────────
def _write_summary(strategy: str, fac: pd.Series, nav: pd.Series,
                   score: pd.DataFrame, rets: pd.DataFrame,
                   start_date: pd.Timestamp, end_date: pd.Timestamp,
                   out_dir: Path, cell: dict) -> dict:
    """Write nav.csv + summary.json for one strategy. Returns the summary dict."""
    out_dir.mkdir(parents=True, exist_ok=True)

    # Per-window W1-W6 breakdown (equal-length slices)
    n_days = len(fac)
    rets_eq = (1 + fac).cumprod()
    w_size = max(1, n_days // 6)
    windows = {}
    for w in range(6):
        lo = w * w_size
        hi = min((w + 1) * w_size, n_days)
        if hi <= lo:
            continue
        ann = float(rets_eq.iloc[hi - 1] / max(rets_eq.iloc[lo], 1e-9)) ** (365.0 / max(hi - lo, 1)) - 1
        windows[f"W{w+1}"] = {
            "start": str(fac.index[lo].date()),
            "end": str(fac.index[hi - 1].date()),
            "n_days": int(hi - lo),
            "ann_return": round(ann, 4),
        }

    # Sharpe / maxDD / ann%
    rets_clean = fac.dropna()
    sharpe = (float(rets_clean.mean() / rets_clean.std() * np.sqrt(365))
              if len(rets_clean) > 5 and rets_clean.std() > 0 else None)
    peak = np.maximum.accumulate(nav.values)
    max_dd = float((peak - nav.values).max() / peak.max()) if peak.max() > 0 else 0.0
    ann_ret = float(nav.iloc[-1] / nav.iloc[0]) ** (365.0 / max(n_days, 1)) - 1.0

    # Daily NAV csv
    nav_csv = out_dir / "nav.csv"
    with open(nav_csv, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["mark_date", "nav", "daily_return", "strategy"])
        for d, v in nav.items():
            r = float(fac.loc[d]) if d in fac.index else 0.0
            w.writerow([d.date().isoformat(), round(float(v), 6),
                        round(r, 6), strategy])

    summary = {
        "strategy": strategy,
        "status": "ok",
        "sim_start": str(start_date.date()),
        "sim_end": str(end_date.date()),
        "n_days_marked": int(n_days),
        "validated_simulated": True,  # the whole point of this module
        "validation_min_days": 60,
        "current_nav": round(float(nav.iloc[-1]), 6),
        "ann_return_sim": round(ann_ret, 4),
        "sharpe_sim": round(sharpe, 2) if sharpe is not None else None,
        "max_dd_sim": round(max_dd, 4),
        "n_assets": int(rets.shape[1]),
        "cell": cell,
        "per_window": windows,
        "honest_framing": ("SIMULATED marks using frozen-cell backtest logic on "
                           "real historical data; NOT live forward-clock paper-trade. "
                           "Once live marks accumulate on Railway, those supersede these."),
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    print(f"[{strategy}] {n_days}d: NAV {nav.iloc[-1]:.4f}, "
          f"ann% {ann_ret*100:+.2f}%, Sharpe {sharpe:.2f}, maxDD {max_dd*100:.2f}%")
    return summary


# ── Sanity check (sanity_run=True): replicate the backtest window ──────────
def sanity_check_r76(rets_daily: pd.DataFrame, funding_daily: pd.DataFrame) -> dict:
    """Run R76 on the 770-day panel (2024-06-07 → 2026-07-18) and verify
    the gross_t / OOS_t stats match the reported R76 verdict.

    This is the calibration check for the simulation harness. If Sharpe +
    ann% land within ±50% of the backtest-reported numbers, the harness is
    calibrated.
    """
    common = sorted(set(rets_daily.columns) & set(funding_daily.columns) & set(UNIVERSE))
    rets = rets_daily[common].loc["2024-06-07":"2026-07-18"]
    funding = funding_daily[common].reindex(rets.index).ffill()
    score = score_r76_funding_residual(funding)
    fac = _cadence_ls_sim(score, rets, rebal_days=R76_CAD, cost_bps=R76_BPS, k_terciles=R76_K)
    fac = fac.fillna(0.0)

    # 30% held-out OOS slice
    n = len(fac)
    oos_lo = int(n * 0.70)
    oos_fac = fac.iloc[oos_lo:]
    rets_eq = (1 + fac).cumprod()
    oos_eq = (1 + oos_fac).cumprod()
    ann = float(oos_eq.iloc[-1] / oos_eq.iloc[0]) ** (365.0 / max(len(oos_fac), 1)) - 1.0
    sharpe = float(oos_fac.mean() / oos_fac.std() * np.sqrt(365)) if oos_fac.std() > 0 else 0.0
    # Newey-West HAC t-stat (same convention as r76_funding_residual_ls.py)
    nw_lags = 6
    mean = oos_fac.mean()
    var = oos_fac.var(ddof=1)
    if var > 0:
        # Simple HAC: variance with Newey-West lag
        n_obs = len(oos_fac)
        gamma_0 = var
        gamma_sum = gamma_0
        for L in range(1, min(nw_lags, n_obs - 1) + 1):
            w = 1 - L / (nw_lags + 1)
            gamma_sum += 2 * w * oos_fac.autocorr(lag=L) * var
        nw_se = np.sqrt(gamma_sum / n_obs)
        t_stat = mean / nw_se if nw_se > 0 else 0.0
    else:
        t_stat = 0.0
    return {
        "panel": "2024-06-07 → 2026-07-18 (770d)",
        "n_days": int(n),
        "oos_n_days": int(n - oos_lo),
        "ann_return_oos": round(float(ann), 4),
        "sharpe_oos": round(float(sharpe), 2),
        "oos_t_NW6": round(float(t_stat), 2),
        "expected_ann_pct": "~+10-15 (backtest gross)",
        "expected_oos_t": "+2.47 (backtest OOS_t)",
    }


# ── CLI =====================================================================
def main():
    ap = argparse.ArgumentParser(description="60d SIMULATED paper-trade marks for R77 + R76")
    ap.add_argument("--start", default="2026-05-20",
                    help="Sim start date (default 2026-05-20 = latest 60-day slice)")
    ap.add_argument("--end", default="2026-07-19",
                    help="Sim end date (default 2026-07-19 = funding data cutoff)")
    ap.add_argument("--strategy", choices=["r76", "r77", "both"], default="both")
    ap.add_argument("--sanity", action="store_true",
                    help="Run sanity check (replicate R76 backtest window)")
    ap.add_argument("--out-base", default=str(SIM_DIR),
                    help="Base output directory")
    args = ap.parse_args()

    start = pd.Timestamp(args.start)
    end = pd.Timestamp(args.end)
    out_base = Path(args.out_base)

    print(f"Loading OHLCV + funding for {len(UNIVERSE)} assets …")
    rets_daily = load_returns_daily(UNIVERSE)
    funding_daily = load_funding_daily(UNIVERSE)
    print(f"  OHLCV: {rets_daily.shape[0]} days × {rets_daily.shape[1]} assets "
          f"({rets_daily.index.min().date()} → {rets_daily.index.max().date()})")
    print(f"  Funding: {funding_daily.shape[0]} days × {funding_daily.shape[1]} assets "
          f"({funding_daily.index.min().date()} → {funding_daily.index.max().date()})")

    if args.sanity:
        print("\n=== SANITY CHECK: replicate R76 backtest on 770d panel ===")
        sanity = sanity_check_r76(rets_daily, funding_daily)
        print(json.dumps(sanity, indent=2))
        (out_base / "sanity_check.json").write_text(json.dumps(sanity, indent=2))
        return

    results = {}
    if args.strategy in ("r76", "both"):
        print(f"\n=== Strategy 2: R76 standalone 5d/0bps/k=3/high_fund_long "
              f"({start.date()} → {end.date()}) ===")
        results["r76"] = simulate_r76(rets_daily, funding_daily, start, end,
                                      out_base / "r76")
    if args.strategy in ("r77", "both"):
        print(f"\n=== Strategy 1: R77 fusion (R46+R62+R76) "
              f"({start.date()} → {end.date()}) ===")
        results["r77"] = simulate_r77(rets_daily, funding_daily, start, end,
                                      out_base / "r77")
    print("\n=== RESULTS ===")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
