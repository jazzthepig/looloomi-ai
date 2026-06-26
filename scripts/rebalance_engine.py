#!/usr/bin/env python3
"""
CometCloud — Meter-Driven Portfolio Rebalance Engine (v1)
==========================================================

Implements the user's pivot from mechanical 4h long-short to a meter-driven
mid-to-long-term portfolio rebalance model (per 2026-06-26 direction):

  - **Universe is dynamic**: any asset passing CIS criteria can be added (we
    score all symbols with a CIS history file on the rebalance day).
  - **Tiered versions**: Senior (1×, unleveraged) + Junior (2×, leveraged).
  - **Shorts allowed**: institutional LPs DO short, especially in
    single-direction down markets.
  - **Low rebalance frequency**: trigger-based (monthly 1st, regime change,
    grade cross, weight delta > 10%) — not daily.
  - **Cash yield 2-3%** on uninvested NAV.

Inputs:
  - /Volumes/CometCloudAI/freqtrade/user_data/data/binance/*.feather (prices)
  - /Volumes/CometCloudAI/cometcloud-local/_data/cis_history/cis_*.json (CIS)

Output:
  - /Volumes/CometCloudAI/cometcloud-local/_reports/backtest/rebalance_<tag>.md
  - Same dir: rebalance_<tag>_senior_nav.csv, _junior_nav.csv, _trades.csv

This is NOT a frozen-factor systematic — weights are computed from CURRENT
CIS state (grade + regime) on each rebalance, then compared against current
weights; rebalance fires only when the DELTA is meaningful. The 2026-06-26
rebalance is a SPECIFIC niche edge (CIS-grade-driven portfolio, regime-aware
exposure scaling, mid-term rebalance), not a universal backtestable factor.

Usage:
  python3 scripts/rebalance_engine.py --timerange 20250503-20260312 \
      --report rebalance_v1_20260626
"""
import argparse
import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Configuration (user-set per 2026-06-26 direction)
# ---------------------------------------------------------------------------

# Grade → target weight factor (long side); D/F → 0 (excluded)
GRADE_FACTOR = {
    "A+": 1.5, "A": 1.2, "B+": 1.0, "B": 0.7, "C+": 0.4,
    "C": 0.2, "D": 0.0, "F": 0.0,
}

# Grade ordinal for "≥N level jump" trigger
GRADE_ORDINAL = {"A+": 7, "A": 6, "B+": 5, "B": 4, "C+": 3, "C": 2, "D": 1, "F": 0}

# Grade → short-side factor (smaller because shorts are riskier / less
# conviction by design). D/F = best shorts (worst assets).
SHORT_GRADE_FACTOR = {
    "A+": 0.0, "A": 0.0, "B+": 0.0, "B": 0.0, "C+": 0.2,
    "C": 0.4, "D": 0.6, "F": 0.6,
}

# Regime → total exposure scale (1.0 = full deployment)
REGIME_FACTOR = {
    "Risk-On": 1.00, "Goldilocks": 1.00, "Easing": 1.00,
    "Neutral": 0.80,
    "Risk-Off": 0.50, "Tightening": 0.50, "Stagflation": 0.50,
}

# Tier leverage (Junior carries 2× gross exposure)
TIER_LEVERAGE = {"senior": 1.0, "junior": 2.0}

# Max single-name short weight (avoid tail-risk shorts)
MAX_SHORT_PCT = 0.30

# Rebalance trigger thresholds (tuned v2 — less noise)
REBAL_WEIGHT_DELTA = 0.15      # |Δw| ≥ 15% absolute (was 10%)
REBAL_GRADE_CROSS = True       # grade change → rebalance
REBAL_GRADE_MIN_JUMP = 2       # ≥2 grade levels (B+→C is noise; A→D is signal)
REBAL_REGIME_CHANGE = True     # regime change → rebalance
MIN_HOLD_DAYS = 14             # churn guard (was 7)
MONTHLY_REBAL = True           # always rebalance on day-1 of month

# Costs / cash
FEE_PER_SIDE = 0.0005          # 5bps per side (Binance futures taker)
CASH_APR_DAILY = 0.025 / 365   # 2.5% APR → daily

# Universe
PRICE_DIR = Path("/Volumes/CometCloudAI/freqtrade/user_data/data/binance")
CIS_HISTORY_DIR = Path("/Volumes/CometCloudAI/cometcloud-local/_data/cis_history")
REPORT_DIR = Path("/Volumes/CometCloudAI/cometcloud-local/_reports/backtest")
REPORT_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _normalise_regime(r: str) -> str:
    """Translate CIS regime strings to canonical Title-case-hyphen."""
    if not r:
        return "Neutral"
    s = r.strip().upper().replace("_", "-").replace(" ", "-")
    table = {
        "RISK-ON": "Risk-On", "GOLDILOCKS": "Goldilocks", "EASING": "Easing",
        "NEUTRAL": "Neutral",
        "RISK-OFF": "Risk-Off", "TIGHTENING": "Tightening", "STAGFLATION": "Stagflation",
    }
    return table.get(s, "Neutral")


def load_prices(symbols: list[str], start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    """Load prices: 4h feather first, fallback to Supabase ohlcv_daily."""
    frames = {}
    missing = []
    for sym in symbols:
        f = PRICE_DIR / f"{sym}_USDT-4h.feather"
        if f.exists():
            df = pd.read_feather(f)
            if "date" in df.columns:
                df = df.rename(columns={"date": "timestamp"})
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True).dt.tz_localize(None)
            df = df.set_index("timestamp").sort_index()
            daily = df["close"].resample("D").last().ffill()
            frames[sym] = daily
        else:
            missing.append(sym)
    # Fallback: Supabase ohlcv_daily for missing symbols
    if missing:
        try:
            import os
            import httpx
            KEY = os.environ.get("SUPABASE_KEY") or os.environ.get("SUPABASE_SERVICE_KEY")
            if KEY:
                URL = "https://soupjamxlfsmgmmtoeok.supabase.co/rest/v1"
                H = {"apikey": KEY, "Authorization": f"Bearer {KEY}"}
                # Build filter for needed symbols
                filt = ",".join(f'"{s}"' for s in missing)
                rows, off = [], 0
                while True:
                    r = httpx.get(
                        f"{URL}/ohlcv_daily",
                        params={"select": "symbol,trade_date,close",
                                "symbol": f"in.({filt})",
                                "limit": 1000, "offset": off},
                        headers=H, timeout=60,
                    )
                    if r.status_code != 200:
                        print(f"  [WARN] Supabase ohlcv_daily fetch failed: {r.status_code}")
                        break
                    batch = r.json()
                    if not batch:
                        break
                    rows += batch
                    if len(batch) < 1000:
                        break
                    off += 1000
                if rows:
                    sb = pd.DataFrame(rows)
                    sb["trade_date"] = pd.to_datetime(sb["trade_date"])
                    for sym in missing:
                        sub = sb[sb["symbol"] == sym].set_index("trade_date")["close"].astype(float)
                        if len(sub) > 0:
                            sub = sub.sort_index()
                            daily = sub.resample("D").last().ffill()
                            frames[sym] = daily
                            print(f"  [PRICE] {sym}: {len(daily)} days from Supabase")
        except Exception as e:
            print(f"  [WARN] Supabase fallback failed: {e}")
    if not frames:
        return pd.DataFrame()
    px = pd.concat(frames, axis=1).sort_index()
    px = px.loc[(px.index >= start) & (px.index <= end)]
    return px


def load_cis_history(start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    """Load per-day CIS history. Returns df indexed by date with columns:
       [sym: cis_score, cis_grade, signal, macro_regime].
    """
    rows = []
    files = sorted(CIS_HISTORY_DIR.glob("cis_*.json"))
    for f in files:
        try:
            date_str = f.stem.replace("cis_", "")
            d = pd.Timestamp(date_str)
        except Exception:
            continue
        if d < start or d > end:
            continue
        try:
            data = json.loads(f.read_text())
        except Exception:
            continue
        regime = _normalise_regime(data.get("macro_regime", ""))
        for s in data.get("scores", []):
            sym = s.get("symbol") or s.get("asset")
            if not sym:
                continue
            rows.append({
                "date": d, "symbol": sym,
                "cis_score": s.get("cis_score"),
                "cis_grade": s.get("cis_grade") or s.get("grade") or "F",
                "signal": s.get("signal", ""),
                "macro_regime": regime,
            })
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    # Regime: per-date single value (all symbols share same regime)
    reg_s = df.drop_duplicates("date").set_index("date")["macro_regime"]
    # Build flat df with single column names: cis_<SYM>_score / _grade
    wide = pd.DataFrame(index=sorted(df["date"].unique()))
    wide.index.name = "date"
    wide["regime"] = reg_s.reindex(wide.index).ffill().bfill()
    for sym in df["symbol"].unique():
        sub = df[df["symbol"] == sym].set_index("date")
        wide[f"cis_{sym}_score"] = sub["cis_score"].reindex(wide.index).ffill()
        wide[f"cis_{sym}_grade"] = sub["cis_grade"].reindex(wide.index).ffill()
    return wide.sort_index()


# ---------------------------------------------------------------------------
# Target weight computation
# ---------------------------------------------------------------------------

def compute_target_weights(cis_row: pd.Series, regime: str, universe: list[str]) -> dict[str, float]:
    """Compute signed target weights for the universe given current CIS row.

    Returns {sym: signed_weight} where signed_weight is positive (long) or
    negative (short). Long-side sum + |short-side sum| ≤ REGIME_FACTOR[regime].
    """
    scale = REGIME_FACTOR.get(regime, 0.8)
    longs, shorts = [], []
    for sym in universe:
        grade = cis_row.get(f"cis_{sym}_grade")
        if grade is None or (isinstance(grade, float) and math.isnan(grade)):
            continue
        g = str(grade).strip()
        # LONG side
        lf = GRADE_FACTOR.get(g, 0.0)
        if lf > 0:
            longs.append((sym, lf))
        # SHORT side
        sf = SHORT_GRADE_FACTOR.get(g, 0.0)
        if sf > 0 and MAX_SHORT_PCT > 0:
            shorts.append((sym, -sf))  # negative weight
    # Normalise so gross long + gross short ≤ scale
    raw_long_sum = sum(w for _, w in longs)
    raw_short_sum = sum(abs(w) for _, w in shorts)
    gross_raw = raw_long_sum + raw_short_sum
    if gross_raw <= 0:
        return {sym: 0.0 for sym in universe}
    norm = scale / gross_raw
    weights = {}
    for sym, w in longs:
        weights[sym] = w * norm
    for sym, w in shorts:
        weights[sym] = max(w * norm, -MAX_SHORT_PCT * scale)
    # Fill zeros for symbols not in either side
    for sym in universe:
        weights.setdefault(sym, 0.0)
    return weights


# ---------------------------------------------------------------------------
# Rebalance engine
# ---------------------------------------------------------------------------

@dataclass
class RebalanceEvent:
    date: pd.Timestamp
    reason: str
    weights_before: dict[str, float]
    weights_after: dict[str, float]
    turnover: float
    regime: str


@dataclass
class BacktestResult:
    tag: str
    tier: str
    leverage: float
    nav: pd.Series                  # daily NAV
    regime: pd.Series               # daily regime
    gross_exposure: pd.Series       # daily sum(|w|)
    rebalances: list[RebalanceEvent] = field(default_factory=list)
    final_weights: dict[str, float] = field(default_factory=dict)
    start: pd.Timestamp = None
    end: pd.Timestamp = None

    def summary_metrics(self, btc_nav: pd.Series, eq_nav: pd.Series) -> dict:
        nav = self.nav
        n = len(nav)
        yrs = n / 365 if n > 0 else np.nan
        tot = nav.iloc[-1] / nav.iloc[0] - 1 if n > 1 else 0.0
        cagr = (nav.iloc[-1] / nav.iloc[0]) ** (1 / yrs) - 1 if yrs > 0 else np.nan
        rets = nav.pct_change().dropna()
        sharpe = (rets.mean() * 365) / (rets.std() * np.sqrt(365)) if rets.std() > 0 else np.nan
        down = rets[rets < 0]
        sortino = (rets.mean() * 365) / (down.std() * np.sqrt(365)) if len(down) > 0 and down.std() > 0 else np.nan
        dd = (nav / nav.cummax() - 1).min()
        calmar = cagr / abs(dd) if dd < 0 else np.nan
        btc_rets = btc_nav.pct_change().dropna().reindex(rets.index).fillna(0)
        alpha_cagr = cagr - ((btc_nav.iloc[-1] / btc_nav.iloc[0]) ** (1 / yrs) - 1) if yrs > 0 else np.nan
        winrate = (rets > 0).sum() / len(rets) if len(rets) > 0 else np.nan
        return {
            "CAGR": cagr, "TotalReturn": tot, "Sharpe": sharpe, "Sortino": sortino,
            "Calmar": calmar, "MaxDD": dd, "WinRate": winrate,
            "BTC_Alpha": alpha_cagr, "n_rebalances": len(self.rebalances),
            "avg_turnover": np.mean([e.turnover for e in self.rebalances]) if self.rebalances else 0.0,
        }

    def to_report(self, btc_nav: pd.Series, eq_nav: pd.Series, prices: pd.DataFrame) -> str:
        m = self.summary_metrics(btc_nav, eq_nav)
        yrs = (self.end - self.start).days / 365 if self.start and self.end else 0
        btc_cagr = (btc_nav.iloc[-1] / btc_nav.iloc[0]) ** (1 / yrs) - 1 if yrs > 0 else 0
        eq_cagr = (eq_nav.iloc[-1] / eq_nav.iloc[0]) ** (1 / yrs) - 1 if yrs > 0 else 0
        lines = [
            f"# Rebalance Report — {self.tag} — {self.tier} tier ({self.leverage}× leverage)",
            f"**Window:** {self.start.date()} → {self.end.date()} ({yrs:.2f}y)",
            f"**Universe:** {len(prices.columns)} assets (CIS-driven selection)",
            "",
            "## Aggregate metrics",
            "| metric | strategy | BTC-hold | equal-weight |",
            "|---|---|---|---|",
            f"| CAGR | {m['CAGR']*100:.2f}% | {btc_cagr*100:.2f}% | {eq_cagr*100:.2f}% |",
            f"| Sharpe | {m['Sharpe']:.2f} | n/a | n/a |",
            f"| Sortino | {m['Sortino']:.2f} | n/a | n/a |",
            f"| Calmar | {m['Calmar']:.2f} | n/a | n/a |",
            f"| MaxDD (rel) | {m['MaxDD']*100:.2f}% | n/a | n/a |",
            f"| WinRate | {m['WinRate']*100:.1f}% | n/a | n/a |",
            f"| vs BTC-hold (CAGR Δ) | {m['BTC_Alpha']*100:+.2f}pp | — | — |",
            f"| n_rebalances | {m['n_rebalances']} | — | — |",
            f"| avg turnover per rebal | {m['avg_turnover']*100:.2f}% | — | — |",
            f"| avg gross exposure | {self.gross_exposure.mean()*100:.2f}% | — | — |",
            "",
            "## Trigger distribution",
            "",
        ]
        # Count triggers
        from collections import Counter
        triggers = Counter(e.reason.split("+")[0].strip() for e in self.rebalances)
        for k, v in triggers.most_common():
            lines.append(f"- {k}: {v}")
        lines.append("")
        lines.append("## Top 20 final weights")
        lines.append("")
        lines.append("| symbol | weight | grade |")
        lines.append("|---|---|---|")
        # Get latest grade
        sorted_w = sorted(self.final_weights.items(), key=lambda x: -abs(x[1]))
        for sym, w in sorted_w[:20]:
            if abs(w) < 0.001:
                continue
            lines.append(f"| {sym} | {w*100:+.2f}% | — |")
        lines.append("")
        # Regime timeline
        lines.append("## Regime timeline (first occurrence of each)")
        lines.append("")
        lines.append("| date | regime |")
        lines.append("|---|---|")
        seen = set()
        for d, r in self.regime.items():
            if r not in seen:
                lines.append(f"| {d.date()} | {r} |")
                seen.add(r)
        return "\n".join(lines) + "\n"


def run_backtest(prices: pd.DataFrame, cis: pd.DataFrame, tier: str, leverage: float, tag: str) -> BacktestResult:
    """Walk-forward daily rebalance backtest. Returns BacktestResult with NAV."""
    universe = [c for c in prices.columns]
    days = prices.index
    start, end = days[0], days[-1]
    # State
    weights = {sym: 0.0 for sym in universe}
    cash = 1.0  # start with $1 NAV
    nav = pd.Series(index=days, dtype=float)
    regime_series = pd.Series(index=days, dtype=object)
    gross_series = pd.Series(index=days, dtype=float)
    events: list[RebalanceEvent] = []
    last_rebal: Optional[pd.Timestamp] = None
    last_regime: Optional[str] = None
    last_grades: dict[str, str] = {}
    prev_close = None
    for d in days:
        if prev_close is None or d not in prices.index:
            prev_close = prices.loc[d].to_dict() if d in prices.index else prev_close
            nav.loc[d] = cash
            regime_series.loc[d] = last_regime or "Neutral"
            gross_series.loc[d] = 0.0
            continue
        # Mark to market: NAV_t = sum(w_i * P_t/P_{t-1}) + cash * (1+r_cash)
        ret = 0.0
        for sym, w in weights.items():
            p_t = prices.at[d, sym] if (d in prices.index and sym in prices.columns) else None
            p_y = prices.at[prev_close["_date"], sym] if isinstance(prev_close, dict) and "_date" in prev_close else None
            # Simpler: track via prev_close dict
            p_y = prev_close.get(sym)
            if p_t is not None and p_y is not None and p_y > 0 and not np.isnan(p_y) and not np.isnan(p_t):
                ret += w * (p_t / p_y - 1)
        # Cash earns yield
        cash_part = 1.0 - sum(abs(w) for w in weights.values())
        cash_yield = max(cash_part, 0.0) * CASH_APR_DAILY
        nav.loc[d] = (1 + ret + cash_yield)
        regime_series.loc[d] = last_regime or "Neutral"
        gross_series.loc[d] = sum(abs(w) for w in weights.values())
        # Decide rebalance (do AFTER mark-to-market so trigger is at-close)
        if d in cis.index:
            cis_row = cis.loc[d]
            regime = str(cis_row["regime"]).strip() if "regime" in cis_row else "Neutral"
            regime = _normalise_regime(regime)
            last_regime = regime
            # Build target weights
            target = compute_target_weights(cis_row, regime, universe)
            # Check triggers
            triggers = []
            if last_rebal is None:
                triggers.append("init")
            elif MONTHLY_REBAL and d.month != last_rebal.month:
                triggers.append("monthly")
            if REBAL_REGIME_CHANGE and last_rebal is not None and regime != _normalise_regime(str(cis.loc[last_rebal]["regime"]) if "regime" in cis.loc[last_rebal] else ""):
                triggers.append("regime_change")
            if REBAL_GRADE_CROSS and last_rebal is not None:
                for sym in universe:
                    new_g = cis_row.get(f"cis_{sym}_grade")
                    old_g = last_grades.get(sym)
                    if new_g is None or old_g is None:
                        continue
                    new_o = GRADE_ORDINAL.get(str(new_g).strip(), 0)
                    old_o = GRADE_ORDINAL.get(str(old_g).strip(), 0)
                    if abs(new_o - old_o) >= REBAL_GRADE_MIN_JUMP:
                        triggers.append("grade_cross")
                        break
            if last_rebal is not None:
                max_delta = max(abs(target.get(s, 0) - weights.get(s, 0)) for s in universe)
                if max_delta >= REBAL_WEIGHT_DELTA:
                    triggers.append("weight_delta")
            # Apply leverage
            target_lev = {k: v * leverage for k, v in target.items()}
            # Re-normalise gross to ≤ leverage
            gross_target = sum(abs(w) for w in target_lev.values())
            if gross_target > leverage:
                scale = leverage / gross_target
                target_lev = {k: v * scale for k, v in target_lev.items()}
            # Churn guard
            min_hold_ok = last_rebal is None or (d - last_rebal).days >= MIN_HOLD_DAYS
            if triggers and (min_hold_ok or "init" in triggers or "regime_change" in triggers or "monthly" in triggers):
                # Compute turnover
                turnover = 0.5 * sum(abs(target_lev.get(s, 0) - weights.get(s, 0)) for s in universe)
                events.append(RebalanceEvent(
                    date=d, reason="+".join(triggers) if triggers else "?",
                    weights_before=dict(weights),
                    weights_after=dict(target_lev),
                    turnover=turnover, regime=regime,
                ))
                weights = target_lev
                last_rebal = d
                # Update grade cache
                last_grades = {}
                for sym in universe:
                    g = cis_row.get(f"cis_{sym}_grade")
                    if g is not None:
                        last_grades[sym] = str(g)
                # Apply transaction cost on NAV (deducted from cash side)
                cost = turnover * FEE_PER_SIDE * 2  # round-trip
                nav.loc[d] = nav.loc[d] * (1 - cost)
        prev_close = prices.loc[d].to_dict()
        prev_close["_date"] = d
    return BacktestResult(
        tag=tag, tier=tier, leverage=leverage,
        nav=nav, regime=regime_series, gross_exposure=gross_series,
        rebalances=events, final_weights=weights,
        start=start, end=end,
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_timerange(s: str) -> tuple[pd.Timestamp, pd.Timestamp]:
    a, b = s.split("-")
    return pd.Timestamp(a), pd.Timestamp(b)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--timerange", default="20250503-20260312")
    ap.add_argument("--report", default="rebalance_v1")
    ap.add_argument("--universe", default="BTC,ETH,SOL,BNB,XRP,LINK,AVAX,DOT,LTC,ADA",
                    help="comma list of symbols (USDT pairs)")
    args = ap.parse_args()

    start, end = parse_timerange(args.timerange)
    print(f"[rebalance] window {start.date()} → {end.date()}")
    universe = [s.strip().upper() for s in args.universe.split(",") if s.strip()]
    print(f"[rebalance] universe: {universe}")

    # Load prices
    prices = load_prices(universe, start, end)
    if prices.empty:
        print("ERROR: no prices loaded")
        return 2
    # Drop symbols with no data in window
    prices = prices.dropna(axis=1, thresh=int(len(prices) * 0.5))
    print(f"[rebalance] prices: {prices.shape}, cols={list(prices.columns)}")

    # Load CIS
    cis = load_cis_history(start, end)
    print(f"[rebalance] CIS history: {cis.shape if not cis.empty else 'empty'}")
    if cis.empty:
        print("ERROR: no CIS history in window")
        return 3

    # Run both tiers
    for tier, lev in [("senior", 1.0), ("junior", 2.0)]:
        print(f"\n[rebalance] running {tier} tier ({lev}×)...")
        result = run_backtest(prices, cis, tier=tier, leverage=lev, tag=args.report)
        print(f"[rebalance] {tier}: CAGR={result.summary_metrics(prices['BTC'], prices.mean(axis=1))['CAGR']*100:.2f}%, "
              f"rebalances={len(result.rebalances)}")
        # Benchmarks (BTC-only & equal-weight of available universe)
        btc_nav = prices["BTC"] / prices["BTC"].iloc[0]
        eq_nav = prices.mean(axis=1) / prices.mean(axis=1).iloc[0]
        # Save CSVs
        nav_path = REPORT_DIR / f"{args.report}_{tier}_nav.csv"
        nav_df = pd.DataFrame({
            "nav": result.nav,
            "regime": result.regime,
            "gross_exposure": result.gross_exposure,
            "btc_nav": btc_nav,
            "eq_nav": eq_nav,
        })
        nav_df.to_csv(nav_path)
        print(f"[rebalance] wrote {nav_path}")
        # Save trades log
        if result.rebalances:
            trades_df = pd.DataFrame([{
                "date": e.date, "reason": e.reason, "regime": e.regime,
                "turnover": e.turnover,
                **{f"w_{k}": v for k, v in e.weights_after.items()},
            } for e in result.rebalances])
            trades_path = REPORT_DIR / f"{args.report}_{tier}_trades.csv"
            trades_df.to_csv(trades_path, index=False)
            print(f"[rebalance] wrote {trades_path}")
        # Markdown report
        md = result.to_report(btc_nav, eq_nav, prices)
        md_path = REPORT_DIR / f"{args.report}_{tier}.md"
        md_path.write_text(md)
        print(f"[rebalance] wrote {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
