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

# v4 regime conviction smoother (per 2026-06-27 direction: "regime 不一定
# 强行持有" → soft signal instead of hard min-hold filter)
# regime_change trigger only fires when conviction >= threshold, where
# conviction = 1.0 - (transitions in last STABILITY_WINDOW days / window).
# See scripts/regime_smoother.py for full algorithm + sweep grid.
ENABLE_REGIME_SMOOTHING = True     # v4 default on; v3 behaviour when off
REGIME_CONVICTION_THRESHOLD = 0.85  # 12/37 regime transitions fire at default
REGIME_STABILITY_WINDOW = 14        # days of lookback for transition count

# Costs / cash
FEE_PER_SIDE = 0.0005          # 5bps per side (Binance futures taker)
CASH_APR_DAILY = 0.025 / 365   # 2.5% APR → daily

# Risk-Off overlay (v3) — see scripts/risk_off_overlay.py
# Set to False to run base-only (v2 behaviour) for A/B comparison
ENABLE_RISK_OFF_OVERLAY = True
try:
    from risk_off_overlay import (
        overlay_daily_pnl, apply_naked_short_overlay,
        RISK_OFF_REGIMES, RISK_OFF_OVERLAY_ALLOC, BASKET_OPTIONS_PARAMS,
        NAKED_SHORT_PARAMS, sensitivity_table,
    )
    _OVERLAY_AVAILABLE = True
except ImportError:
    _OVERLAY_AVAILABLE = False
    ENABLE_RISK_OFF_OVERLAY = False

# Regime smoother (v4) — see scripts/regime_smoother.py
# Computes a soft conviction score per day based on how many regime flips
# happened in the last REGIME_STABILITY_WINDOW days. Used to gate the
# regime_change rebalance trigger.
try:
    from regime_smoother import (
        regime_with_conviction, regime_confidence_v5, regime_change_triggers,
        DEFAULT_CONVICTION_THRESHOLD, DEFAULT_STABILITY_WINDOW,
    )
    _SMOOTHER_AVAILABLE = True
except ImportError:
    _SMOOTHER_AVAILABLE = False
    ENABLE_REGIME_SMOOTHING = False

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
       [sym: cis_score, cis_grade, signal, macro_regime, regime_confidence].

    `regime_confidence` is OPTIONAL — added to top-level JSON by
    scripts/load_cis_with_confidence.py once Minimax ships the Supabase
    column. When absent, the column is filled with NaN and
    regime_confidence_v5() falls back to the window-stability heuristic.
    """
    rows = []
    files = sorted(CIS_HISTORY_DIR.glob("cis_*.json"))
    # Track per-day regime_confidence (latest value wins if multiple)
    conf_by_date: dict[pd.Timestamp, float] = {}
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
        # v5: top-level regime_confidence field (preferred)
        top_conf = data.get("regime_confidence")
        if top_conf is not None:
            try:
                conf_val = float(top_conf)
                if conf_val == conf_val:  # not NaN
                    conf_by_date[d] = conf_val
            except (TypeError, ValueError):
                pass
        for s in data.get("scores", []):
            sym = s.get("symbol") or s.get("asset")
            if not sym:
                continue
            # Prefer per-asset regime_confidence if present (matches minimax's
            # CISResult.to_dict() shape); fall back to top-level; else NaN
            asset_conf = s.get("regime_confidence", top_conf)
            try:
                asset_conf_val = float(asset_conf) if asset_conf is not None else float("nan")
            except (TypeError, ValueError):
                asset_conf_val = float("nan")
            rows.append({
                "date": d, "symbol": sym,
                "cis_score": s.get("cis_score"),
                "cis_grade": s.get("cis_grade") or s.get("grade") or "F",
                "signal": s.get("signal", ""),
                "macro_regime": regime,
                "regime_confidence": asset_conf_val,
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
    # v5: regime_confidence column (top-level, ffill'd across rows)
    if conf_by_date:
        wide["regime_confidence"] = pd.Series(conf_by_date).reindex(wide.index).ffill()
    else:
        wide["regime_confidence"] = float("nan")
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
    # v4: regime conviction at time of rebalance (None if smoothing disabled)
    conviction: float | None = None


@dataclass
class BacktestResult:
    tag: str
    tier: str
    leverage: float
    nav: pd.Series                  # daily NAV (base + overlay combined)
    regime: pd.Series               # daily regime
    gross_exposure: pd.Series       # daily sum(|w|)
    rebalances: list[RebalanceEvent] = field(default_factory=list)
    final_weights: dict[str, float] = field(default_factory=dict)
    start: pd.Timestamp = None
    end: pd.Timestamp = None
    # v3 overlay fields
    base_nav: pd.Series = None              # daily NAV without overlay
    overlay_nav: pd.Series = None           # daily overlay P&L fraction
    overlay_enabled: bool = False

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

        # v4: regime smoothing section
        regime_convs = [e.conviction for e in self.rebalances if e.conviction is not None]
        if regime_convs:
            lines.extend([
                "## Regime conviction smoother (v4)",
                "",
                f"- Smoothing enabled: yes (window=14d, threshold=0.85 default)",
                f"- Rebalances with conviction recorded: {len(regime_convs)}",
                f"- Mean conviction at rebal: {np.mean(regime_convs):.3f}",
                f"- Min conviction at rebal: {np.min(regime_convs):.3f}",
                f"- Max conviction at rebal: {np.max(regime_convs):.3f}",
                "",
                "Conviction histogram:",
                "",
            ])
            # histogram bins
            bins = [0, 0.5, 0.7, 0.85, 0.9, 0.95, 1.01]
            labels = ["<0.5", "0.5-0.7", "0.7-0.85", "0.85-0.9", "0.9-0.95", "0.95-1.0"]
            counts = {l: 0 for l in labels}
            for c in regime_convs:
                for i in range(len(bins) - 1):
                    if bins[i] <= c < bins[i+1]:
                        counts[labels[i]] += 1
                        break
            for label, n in counts.items():
                bar = "█" * int(n / max(counts.values()) * 40) if max(counts.values()) > 0 else ""
                lines.append(f"  {label}: {n:>3} {bar}")
            lines.append("")
        else:
            lines.extend([
                "## Regime conviction smoother (v4)",
                "",
                "- Smoothing disabled or no conviction recorded",
            ])
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

        # v3 overlay section
        if self.overlay_enabled and self.overlay_nav is not None:
            overlay_total = (1 + self.overlay_nav.fillna(0)).cumprod().iloc[-1] - 1
            base_only_cagr = (self.base_nav.iloc[-1] / self.base_nav.iloc[0]) ** (1 / yrs) - 1 if yrs > 0 else 0
            overlay_yrs = (self.end - self.start).days / 365
            overlay_cagr = (1 + overlay_total) ** (1 / overlay_yrs) - 1 if overlay_yrs > 0 else 0
            overlay_during_riskoff = self.overlay_nav[self.regime.isin(["Risk-Off", "Tightening", "Stagflation"])].sum()
            lines.extend([
                "",
                "## Risk-Off strategy overlay (v3)",
                "",
                f"- Overlay enabled: yes (basket options + augmented short book)",
                f"- Base-only CAGR (no overlay): {base_only_cagr*100:.2f}%",
                f"- Combined CAGR (with overlay): {m['CAGR']*100:.2f}%",
                f"- Overlay total cumulative contribution: {overlay_total*100:+.2f}%",
                f"- Overlay contribution during Risk-Off months: {overlay_during_riskoff*100:+.2f}%",
                "",
                "### Per-month overlay contribution",
                "",
                "| month | base NAV cumret | overlay cumret | combined cumret |",
                "|---|---|---|---|",
            ])
            base_cumret = self.base_nav / self.base_nav.iloc[0] - 1
            overlay_cumret = (1 + self.overlay_nav.fillna(0)).cumprod() - 1
            combined_cumret = self.nav / self.nav.iloc[0] - 1
            for m_key, g in pd.DataFrame({
                "base": base_cumret, "overlay": overlay_cumret, "combined": combined_cumret,
            }).groupby([self.nav.index.year, self.nav.index.month]):
                last = g.iloc[-1]
                lines.append(
                    f"| {m_key[0]}-{m_key[1]:02d} | {last['base']*100:+.2f}% | "
                    f"{last['overlay']*100:+.2f}% | {last['combined']*100:+.2f}% |"
                )

            # Sensitivity table
            if _OVERLAY_AVAILABLE:
                lines.extend([
                    "",
                    "### Sensitivity grid (overlay monthly EV per unit of freed-up cash)",
                    "",
                    "Assumes default alloc (basket_options=100%, naked_short=0%).",
                    "To re-enable naked short EV, set RISK_OFF_SHORT_ALLOC>0.",
                    "",
                    "| premium yield ↓ / short mult → | 1.2× | 1.5× | 2.0× |",
                    "|---|---|---|---|",
                ])
                for row in sensitivity_table():
                    cells = [f"{r['monthly_ev']*100:+.2f}%" for r in row["results"]]
                    lines.append(f"| {row['premium_yield']*100:.1f}% | {cells[0]} | {cells[1]} | {cells[2]} |")
        else:
            lines.extend([
                "",
                "## Risk-Off strategy overlay (v3)",
                "",
                "- Overlay disabled — base-only backtest (use --overlay to enable)",
            ])

        return "\n".join(lines) + "\n"


def run_backtest(prices: pd.DataFrame, cis: pd.DataFrame, tier: str, leverage: float, tag: str,
                overlay_enabled: bool = True,
                regime_smoothing: bool | None = None,
                regime_threshold: float | None = None,
                regime_window: int | None = None) -> BacktestResult:
    """Walk-forward daily rebalance backtest. Returns BacktestResult with NAV.

    If overlay_enabled (default) AND risk_off_overlay module is available, the
    base portfolio's short book is augmented in Risk-Off/Tightening/Stagflation
    regimes and a basket-options premium-collecting overlay P&L is added daily.

    If regime_smoothing (v4 default on, when module available), the
    regime_change trigger is gated by a soft conviction score — see
    scripts/regime_smoother.py for algorithm.
    """
    universe = [c for c in prices.columns]
    days = prices.index
    start, end = days[0], days[-1]
    # State
    weights = {sym: 0.0 for sym in universe}
    cash = 1.0  # start with $1 NAV
    nav = pd.Series(index=days, dtype=float)
    base_nav = pd.Series(index=days, dtype=float)
    overlay_nav = pd.Series(index=days, dtype=float)
    regime_series = pd.Series(index=days, dtype=object)
    conviction_series = pd.Series(index=days, dtype=float)
    gross_series = pd.Series(index=days, dtype=float)
    events: list[RebalanceEvent] = []
    last_rebal: Optional[pd.Timestamp] = None
    last_regime: Optional[str] = None
    last_grades: dict[str, str] = {}
    prev_close = None
    use_overlay = overlay_enabled and ENABLE_RISK_OFF_OVERLAY and _OVERLAY_AVAILABLE
    use_smoothing = (regime_smoothing if regime_smoothing is not None
                     else ENABLE_REGIME_SMOOTHING) and _SMOOTHER_AVAILABLE
    threshold = regime_threshold if regime_threshold is not None else REGIME_CONVICTION_THRESHOLD
    window = regime_window if regime_window is not None else REGIME_STABILITY_WINDOW
    rng = np.random.default_rng(42)  # reproducible breach draws
    cycle_start = start  # 30-day options cycle for breach accounting

    # v5: pre-compute regime conviction via fallback chain
    # (regime_confidence field from cis_history preferred, window heuristic fallback)
    if use_smoothing:
        regime_for_conviction = cis["regime"].ffill().bfill() if "regime" in cis.columns else pd.Series("Neutral", index=days)
        # v5 fallback chain: regime_confidence_v5 prefers the field if present,
        # else falls back to regime_with_conviction (v4 heuristic)
        if "regime_confidence" in cis.columns and cis["regime_confidence"].notna().any():
            source_field = cis["regime_confidence"].copy()
        else:
            source_field = None
        v5_df = regime_confidence_v5(
            regime_for_conviction, source_field=source_field, window=window,
        )
        conviction_df = v5_df
        # Align index: conviction_df was built from cis.index, but our walk uses days.index
        # Map by date — both should cover the same range
        for d in days:
            if d in conviction_df.index:
                conviction_series.loc[d] = conviction_df.at[d, "conviction"]
    for d in days:
        if prev_close is None or d not in prices.index:
            prev_close = prices.loc[d].to_dict() if d in prices.index else prev_close
            nav.loc[d] = cash
            base_nav.loc[d] = cash
            overlay_nav.loc[d] = 0.0
            regime_series.loc[d] = "Neutral"  # default before first CIS update
            gross_series.loc[d] = 0.0
            continue
        # Mark to market: NAV_t = sum(w_i * P_t/P_{t-1}) + cash * (1+r_cash)
        ret = 0.0
        for sym, w in weights.items():
            p_t = prices.at[d, sym] if (d in prices.index and sym in prices.columns) else None
            p_y = prev_close.get(sym)
            if p_t is not None and p_y is not None and p_y > 0 and not np.isnan(p_y) and not np.isnan(p_t):
                ret += w * (p_t / p_y - 1)
        # Cash earns yield
        cash_part = 1.0 - sum(abs(w) for w in weights.values())
        cash_yield = max(cash_part, 0.0) * CASH_APR_DAILY
        base_today = (1 + ret + cash_yield)
        base_nav.loc[d] = base_today
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
            if REBAL_REGIME_CHANGE and last_rebal is not None:
                prev_regime_norm = _normalise_regime(
                    str(cis.loc[last_rebal]["regime"]) if "regime" in cis.loc[last_rebal] else ""
                )
                regime_differs = regime != prev_regime_norm
                if regime_differs:
                    # v4: gate regime_change trigger by regime conviction
                    if use_smoothing:
                        conv = conviction_series.loc[d] if d in conviction_series.index else 0.0
                        if conv >= threshold:
                            triggers.append("regime_change")
                        # else: regime flip detected but suppressed (low conviction)
                    else:
                        # v3 behaviour: fire on any regime change
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
            # v3: apply naked-short overlay BEFORE renormalising gross
            if use_overlay:
                target_lev = apply_naked_short_overlay(target_lev, regime, leverage)
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
                # v4: capture conviction at time of rebalance (None if smoothing off)
                conv_at_rebal = None
                if use_smoothing and d in conviction_series.index:
                    conv_at_rebal = float(conviction_series.loc[d])
                events.append(RebalanceEvent(
                    date=d, reason="+".join(triggers) if triggers else "?",
                    weights_before=dict(weights),
                    weights_after=dict(target_lev),
                    turnover=turnover, regime=regime,
                    conviction=conv_at_rebal,
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
                base_today = base_today * (1 - cost)
                base_nav.loc[d] = base_today
        regime_series.loc[d] = last_regime or "Neutral"
        # v3: overlay P&L — basket options premium collection in Risk-Off
        if use_overlay:
            freed_cash = 1.0 - REGIME_FACTOR.get(last_regime or "Neutral", 0.8)
            # Roll options cycle every 30 days
            if (d - cycle_start).days >= 30:
                cycle_start = d
            overlay_pnl, options_pnl = overlay_daily_pnl(
                last_regime or "Neutral", freed_cash,
                d.toordinal(), cycle_start.toordinal(), rng,
            )
            overlay_nav.loc[d] = overlay_pnl
            nav.loc[d] = base_today * (1.0 + overlay_pnl)
        else:
            overlay_nav.loc[d] = 0.0
            nav.loc[d] = base_today
        prev_close = prices.loc[d].to_dict()
        prev_close["_date"] = d
    return BacktestResult(
        tag=tag, tier=tier, leverage=leverage,
        nav=nav, regime=regime_series, gross_exposure=gross_series,
        rebalances=events, final_weights=weights,
        start=start, end=end,
        base_nav=base_nav, overlay_nav=overlay_nav, overlay_enabled=use_overlay,
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
    ap.add_argument("--overlay", choices=["on", "off"], default="on",
                    help="enable Risk-Off strategy overlay (basket options + augmented shorts)")
    ap.add_argument("--regime-smoothing", choices=["on", "off"], default="on",
                    help="enable v4 regime conviction smoother (gates regime_change trigger)")
    ap.add_argument("--regime-threshold", type=float, default=REGIME_CONVICTION_THRESHOLD,
                    help=f"conviction threshold for regime_change trigger fire (default {REGIME_CONVICTION_THRESHOLD})")
    ap.add_argument("--regime-window", type=int, default=REGIME_STABILITY_WINDOW,
                    help=f"stability lookback window in days (default {REGIME_STABILITY_WINDOW})")
    args = ap.parse_args()

    start, end = parse_timerange(args.timerange)
    print(f"[rebalance] window {start.date()} → {end.date()}")
    universe = [s.strip().upper() for s in args.universe.split(",") if s.strip()]
    print(f"[rebalance] universe: {universe}")
    print(f"[rebalance] overlay: {args.overlay} (module available={_OVERLAY_AVAILABLE})")
    print(f"[rebalance] regime_smoothing: {args.regime_smoothing} "
          f"(threshold={args.regime_threshold}, window={args.regime_window}d, "
          f"module available={_SMOOTHER_AVAILABLE})")

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

    overlay_enabled = (args.overlay == "on")
    regime_smoothing = (args.regime_smoothing == "on")

    # Run both tiers
    for tier, lev in [("senior", 1.0), ("junior", 2.0)]:
        print(f"\n[rebalance] running {tier} tier ({lev}×)...")
        result = run_backtest(prices, cis, tier=tier, leverage=lev, tag=args.report,
                              overlay_enabled=overlay_enabled,
                              regime_smoothing=regime_smoothing,
                              regime_threshold=args.regime_threshold,
                              regime_window=args.regime_window)
        m = result.summary_metrics(prices['BTC'], prices.mean(axis=1))
        print(f"[rebalance] {tier}: CAGR={m['CAGR']*100:.2f}%, "
              f"vs BTC={m['BTC_Alpha']*100:+.2f}pp, rebalances={len(result.rebalances)}")
        # Benchmarks (BTC-only & equal-weight of available universe)
        btc_nav = prices["BTC"] / prices["BTC"].iloc[0]
        eq_nav = prices.mean(axis=1) / prices.mean(axis=1).iloc[0]
        # Save CSVs
        nav_path = REPORT_DIR / f"{args.report}_{tier}_nav.csv"
        nav_data = {
            "nav": result.nav,
            "regime": result.regime,
            "gross_exposure": result.gross_exposure,
            "btc_nav": btc_nav,
            "eq_nav": eq_nav,
        }
        if result.overlay_enabled:
            nav_data["base_nav"] = result.base_nav
            nav_data["overlay_daily"] = result.overlay_nav
        # v4: include conviction (if smoothing was on)
        if _SMOOTHER_AVAILABLE and len(result.rebalances) > 0 \
                and any(e.conviction is not None for e in result.rebalances):
            # We don't store per-day conviction in result; only at rebal times.
            # Recompute from CIS regime series for the CSV column.
            if regime_smoothing:
                from regime_smoother import regime_with_conviction
                rs = cis["regime"].ffill().bfill() if "regime" in cis.columns else pd.Series("Neutral", index=result.nav.index)
                cs = regime_with_conviction(rs, window=args.regime_window)
                nav_data["conviction"] = cs["conviction"].reindex(result.nav.index)
        nav_df = pd.DataFrame(nav_data)
        nav_df.to_csv(nav_path)
        print(f"[rebalance] wrote {nav_path}")
        # Save trades log
        if result.rebalances:
            trades_df = pd.DataFrame([{
                "date": e.date, "reason": e.reason, "regime": e.regime,
                "turnover": e.turnover,
                "conviction": e.conviction,
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
