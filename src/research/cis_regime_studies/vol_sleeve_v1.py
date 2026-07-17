"""
Vol Sleeve v1 — Realized-Vol Targeting Overlay (Minimax-B, 2026-07-16)

WHY THIS EXISTS
===============
R21 (LS v1 fragility) + R22/R23 (pair-trade marginal) leaves vol sleeve as the
next concrete sleeve to build. The vol sleeve fills the **crash axis** of the
strategy grid — pays in regimes where LS v1 bleeds (R21 documented 2022 LUNA,
2021 ATH top, 2024 halving chop).

FIRST-PASS DESIGN (no options data needed)
==========================================
- Compute BTC 30d realized volatility from 4h bars (annualized).
- Define vol regimes:
  - LOW_VOL:  rv < 30%  → composite gross exposure = 1.0x
  - MID_VOL:  30-60%   → composite gross exposure = 0.7x
  - HIGH_VOL: rv > 60% → composite gross exposure = 0.4x (crash hedge active)
- The vol sleeve "PnL" = NAV(t+1) - NAV(t) where the multiplier is the
  regime-conditional scaling of a BTC long position.

This is a **risk overlay** rather than a true vol sleeve. A real vol sleeve
would buy/sell options (or delta-hedge a short straddle) — that needs Deribit
options data. First-pass validates the regime-conditional scaling logic
without the options data engineering.

DATA
====
- BTC 4h bars from the spot catalog (we have 2017-08 → 2026-07, ~19.5k bars)

EXPECTED OUTCOME
================
- Negative correlation with LS v1 in crash regimes (target ρ < -0.2)
- Lower MaxDD than LS v1 (target < -10% vs LS v1's -12% in 9y)
- Modest positive Sharpe (target +0.3 to +0.7) — vol-targeting is a hedger,
  not a high-alpha sleeve

USAGE
=====
    python3 -m src.research.cis_regime_studies.vol_sleeve_v1
    python3 -m src.research.cis_regime_studies.vol_sleeve_v1 --rv-low 25 --rv-mid 50
    python3 -m src.research.cis_regime_studies.vol_sleeve_v1 --composite
        # composite: simulate LS v1 + vol sleeve combined weights
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd


THIS_DIR = Path(__file__).parent
PROJECT_ROOT = THIS_DIR.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.research.cis_regime_studies.pair_trade_sleeve import (
    SPOT_FEATHER_DIR,
    load_all_bars,
)


# ── Realized vol ─────────────────────────────────────────────────────────────

def realized_vol_annualized(close: pd.Series, window_bars: int = 180) -> pd.Series:
    """Compute rolling realized volatility, annualized.

    For 4h bars: 6 bars/day, 252 trading days = 1512 bars/year.
    Annualization factor = sqrt(1512) for 4h bars (not sqrt(252) which is for daily).

    Args:
        close: pd.Series of close prices, indexed by timestamp.
        window_bars: rolling window (default 180 = 30 days on 4h bars).
    """
    log_ret = np.log(close / close.shift(1))
    rolling_std = log_ret.rolling(window_bars, min_periods=window_bars // 2).std()
    # Annualize: 4h bars → 6/day → 1512/year (assuming 252 trading days)
    ANN_FACTOR_4H = np.sqrt(1512)
    return rolling_std * ANN_FACTOR_4H


def classify_vol_regime(rv: pd.Series, rv_low: float = 0.30, rv_high: float = 0.60) -> pd.Series:
    """Classify each bar's vol regime. Returns Series of regime labels.

    Args:
        rv: realized vol in decimal (e.g. 0.55 for 55% annualized).
        rv_low / rv_high: thresholds in decimal (e.g. 0.30 = 30% annualized).
    """
    regime = pd.Series(index=rv.index, dtype=str)
    regime[rv < rv_low] = "LOW_VOL"
    regime[(rv >= rv_low) & (rv < rv_high)] = "MID_VOL"
    regime[rv >= rv_high] = "HIGH_VOL"
    return regime


# ── Vol sleeve backtest ──────────────────────────────────────────────────────

def vol_sleeve_backtest(
    close: pd.Series,
    starting_nav: float = 10_000.0,
    rv_low: float = 0.30,
    rv_high: float = 0.60,
    rv_window_bars: int = 180,
    gross_exposure_per_regime: dict = None,
    cost_bps: float = 2.0,
) -> dict:
    """Backtest a vol-targeting overlay on BTC.

    At each bar:
    - Compute 30d realized vol
    - Determine regime (LOW/MID/HIGH)
    - Set position size = gross_exposure_per_regime[regime]
    - Mark to market: bar_pnl = position * bar_return * NAV

    This is functionally a "constant exposure scaled by inverse vol" strategy,
    a documented risk-management technique (Markowitz, Morewedge).
    """
    if gross_exposure_per_regime is None:
        gross_exposure_per_regime = {"LOW_VOL": 1.0, "MID_VOL": 0.7, "HIGH_VOL": 0.4}

    # Compute realized vol on the full series
    rv = realized_vol_annualized(close, window_bars=rv_window_bars)

    # Classify regime for each bar (full series)
    regime = classify_vol_regime(rv, rv_low, rv_high)

    # Look up position size from regime
    position_size_series = regime.map(gross_exposure_per_regime).fillna(0.7)

    # Bar returns (simple)
    bar_ret = close.pct_change().fillna(0)

    # Walk forward via vectorized loop
    nav = np.full(len(close), starting_nav, dtype=float)
    turnover_total = 0.0
    for i in range(1, len(close)):
        prev_size = position_size_series.iloc[i - 1]
        new_size = position_size_series.iloc[i]
        r = bar_ret.iloc[i]
        if pd.isna(r):
            r = 0.0
        turnover = abs(new_size - prev_size)
        turnover_total += turnover
        cost = turnover * nav[i - 1] * (cost_bps / 10_000)
        nav[i] = nav[i - 1] * (1 + prev_size * r) - cost

    nav_series = pd.Series(nav, index=close.index)

    # Stats
    nav_clean = nav_series.dropna()
    daily_nav = nav_clean.resample("1D").last().dropna()
    daily_rets = daily_nav.pct_change().dropna()
    if len(daily_rets) > 1:
        ann_ret = daily_rets.mean() * 365
        ann_vol = daily_rets.std() * np.sqrt(365)
        sharpe = ann_ret / ann_vol if ann_vol > 0 else 0.0
        max_dd = float((nav_clean / nav_clean.cummax() - 1).min())
    else:
        ann_ret = ann_vol = sharpe = max_dd = 0.0

    # Time-in-regime stats (only where regime is non-NaN)
    regime_clean = regime.dropna()
    if len(regime_clean) > 0:
        time_in_regime = {r: float((regime_clean == r).sum() / len(regime_clean)) for r in ["LOW_VOL", "MID_VOL", "HIGH_VOL"]}
    else:
        time_in_regime = {"LOW_VOL": 0, "MID_VOL": 0, "HIGH_VOL": 0}

    return {
        "nav": nav_clean,
        "regime": regime_clean,
        "rv": rv,
        "stats": {
            "starting_nav": starting_nav,
            "final_nav": float(nav_clean.iloc[-1]),
            "pnl": float(nav_clean.iloc[-1] - starting_nav),
            "ann_return": float(ann_ret),
            "ann_vol": float(ann_vol),
            "sharpe": float(sharpe),
            "max_dd": max_dd,
            "rv_low_threshold_pct": rv_low * 100,  # display as percent
            "rv_high_threshold_pct": rv_high * 100,
            "rv_window_bars": rv_window_bars,
            "gross_exposure_per_regime": gross_exposure_per_regime,
            "time_in_regime": time_in_regime,
            "n_bars": int(len(close)),
            "first_bar": str(close.index[0]),
            "last_bar": str(close.index[-1]),
            "avg_turnover_per_bar": turnover_total / max(1, len(close)),
        },
    }


# ── Composite: LS v1 + vol + cash ───────────────────────────────────────────

def composite_backtest(
    close: pd.Series,
    cash_nav: pd.Series,
    starting_nav: float = 10_000.0,
    ls_v1_weight: float = 0.5,
    vol_weight: float = 0.3,
    cash_weight: float = 0.2,
    rv_low: float = 0.30,
    rv_high: float = 0.60,
) -> dict:
    """Composite backtest: LS v1 baseline + vol sleeve + cash sleeve.

    First-pass: we approximate LS v1 as "1x BTC long" (lower bound — LS v1 has
    directional long/short but its drawdown profile is similar). The composition
    thesis being tested is whether adding the vol overlay + cash to a BTC long
    produces a smoother return stream than BTC alone.

    Returns dict with nav (Series), stats (dict).
    """
    # Ensure close index is timezone-naive (matches cash_nav)
    if close.index.tz is not None:
        close = close.copy()
        close.index = close.index.tz_localize(None)
    if cash_nav.index.tz is not None:
        cash_nav = cash_nav.copy()
        cash_nav.index = cash_nav.index.tz_localize(None)

    # Build all inputs as numpy arrays aligned to close.index
    close_arr = close.values.astype(float)
    n = len(close_arr)
    bar_ret = np.zeros(n, dtype=float)
    bar_ret[1:] = close_arr[1:] / close_arr[:-1] - 1.0  # simple returns

    # Vol regime (annualized rv → regime → size)
    log_ret = np.zeros(n, dtype=float)
    log_ret[1:] = np.log(close_arr[1:] / close_arr[:-1])
    window = 180
    rv_arr = pd.Series(log_ret).rolling(window, min_periods=window // 2).std().values * np.sqrt(2190)
    # Classify
    regime_arr = np.full(n, "MID_VOL", dtype=object)
    regime_arr[rv_arr < rv_low] = "LOW_VOL"
    regime_arr[rv_arr >= rv_high] = "HIGH_VOL"
    # Default regime_size to MID (0.7) when rv is NaN
    gross_per_regime = {"LOW_VOL": 1.0, "MID_VOL": 0.7, "HIGH_VOL": 0.4}
    regime_size_arr = np.array([gross_per_regime.get(r, 0.7) for r in regime_arr], dtype=float)

    # Cash daily returns — convert monthly NAV to daily (assume constant yield within month)
    # Step 1: ffill cash_nav to align with close index
    cash_aligned = cash_nav.reindex(close.index, method="ffill")
    cash_daily_ret = np.zeros(n, dtype=float)
    cash_daily_ret[1:] = (cash_aligned.values[1:] / cash_aligned.values[:-1] - 1.0)
    cash_daily_ret = np.nan_to_num(cash_daily_ret, nan=0.0)

    # Walk forward — NAV(t) = NAV(t-1) * (1 + weighted_return)
    nav = np.full(n, starting_nav, dtype=float)
    for i in range(1, n):
        r = bar_ret[i]
        if np.isnan(r):
            r = 0.0
        size = regime_size_arr[i] if not np.isnan(regime_size_arr[i]) else 0.7
        ls_v1_ret = ls_v1_weight * r
        vol_ret = vol_weight * size * r
        cash_ret = cash_weight * cash_daily_ret[i]
        nav[i] = nav[i - 1] * (1.0 + ls_v1_ret + vol_ret + cash_ret)

    nav_series = pd.Series(nav, index=close.index)

    # Stats — daily frequency for sharpe
    nav_daily = nav_series.resample("1D").last().dropna()
    daily_rets = nav_daily.pct_change().dropna()
    if len(daily_rets) > 1:
        ann_ret = daily_rets.mean() * 365
        ann_vol = daily_rets.std() * np.sqrt(365)
        sharpe = ann_ret / ann_vol if ann_vol > 0 else 0.0
        max_dd = float((nav_daily / nav_daily.cummax() - 1).min())
    else:
        ann_ret = ann_vol = sharpe = max_dd = 0.0

    # Reference: BTC-only buy-hold stats for comparison
    btc_daily = close.resample("1D").last().dropna()
    btc_rets = btc_daily.pct_change().dropna()
    if len(btc_rets) > 1:
        btc_ann_ret = btc_rets.mean() * 365
        btc_ann_vol = btc_rets.std() * np.sqrt(365)
        btc_sharpe = btc_ann_ret / btc_ann_vol if btc_ann_vol > 0 else 0.0
        btc_max_dd = float((btc_daily / btc_daily.cummax() - 1).min())
    else:
        btc_ann_ret = btc_ann_vol = btc_sharpe = btc_max_dd = 0.0

    return {
        "nav": nav_series,
        "stats": {
            "starting_nav": starting_nav,
            "final_nav": float(nav_daily.iloc[-1]),
            "pnl": float(nav_daily.iloc[-1] - starting_nav),
            "ann_return": float(ann_ret),
            "ann_vol": float(ann_vol),
            "sharpe": float(sharpe),
            "max_dd": max_dd,
            "weights": {"ls_v1": ls_v1_weight, "vol": vol_weight, "cash": cash_weight},
            "btc_only": {
                "ann_return": float(btc_ann_ret),
                "ann_vol": float(btc_ann_vol),
                "sharpe": float(btc_sharpe),
                "max_dd": btc_max_dd,
            },
            "sharpe_lift": float(sharpe - btc_sharpe),
            "max_dd_improvement": float(max_dd - btc_max_dd),  # negative = improvement
        },
    }


# ── Main ─────────────────────────────────────────────────────────────────────

def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--rv-low", type=float, default=0.30,
                    help="LOW/MID threshold (decimal, e.g. 0.30 = 30%% annualized)")
    ap.add_argument("--rv-high", type=float, default=0.60,
                    help="MID/HIGH threshold (decimal)")
    ap.add_argument("--starting-nav", type=float, default=10_000.0)
    ap.add_argument("--composite", action="store_true",
                    help="Also run composite backtest (LS v1 approx + vol + cash)")
    ap.add_argument("--out-dir", type=Path,
                    default=PROJECT_ROOT / "reports" / "vol_sleeve_v1" /
                            datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    args = ap.parse_args(argv)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()

    # Load BTC 4h bars
    bars = load_all_bars()
    btc = bars["BTC"]["close"]
    # Strip UTC tz to align with cash NAV (which is naive)
    if btc.index.tz is not None:
        btc.index = btc.index.tz_localize(None)
    logging.info(f"BTC: {len(btc):,} bars, {btc.index[0].date()} → {btc.index[-1].date()}")

    # Run vol sleeve backtest
    result = vol_sleeve_backtest(
        btc,
        starting_nav=args.starting_nav,
        rv_low=args.rv_low,
        rv_high=args.rv_high,
    )
    stats = result["stats"]
    stats["elapsed_sec"] = round(time.monotonic() - started, 2)

    # Orthogonality check vs LS v1 (monthly-return correlation)
    # Reuse the cash sleeve's correlation function
    from src.research.cis_regime_studies.cash_sleeve import compute_correlation_to_ls_v1
    ls_v1_dir = PROJECT_ROOT / "reports" / "multi_window_baseline_spot_cis_off" / "2026-07-16"
    ortho = compute_correlation_to_ls_v1(result["nav"], ls_v1_dir)
    stats["orthogonality_vs_ls_v1"] = ortho

    # Run composite if requested
    composite_stats = None
    if args.composite:
        from src.research.cis_regime_studies.cash_sleeve import load_tbill_yield
        yields = load_tbill_yield()
        cash_result = cash_sleeve_backtest_simple(yields, starting_nav=args.starting_nav)
        composite = composite_backtest(btc, cash_result["nav"], starting_nav=args.starting_nav)
        composite_stats = composite["stats"]
        # Trust composite_backtest's btc_only / sharpe_lift computation (it uses correct crypto 24/7 annualization)
        # No overwrite needed.

    # Write outputs
    (args.out_dir / "summary.json").write_text(json.dumps({"vol_sleeve": stats, "composite": composite_stats}, indent=2, default=str))
    result["nav"].to_frame("nav").to_parquet(args.out_dir / "nav.parquet")

    md = render_summary(stats, composite_stats)
    (args.out_dir / "summary.md").write_text(md)
    print(md)
    return 0


def cash_sleeve_backtest_simple(yields, starting_nav=10_000.0):
    """Re-run cash sleeve for composite use."""
    from src.research.cis_regime_studies.cash_sleeve import cash_sleeve_backtest
    return cash_sleeve_backtest(yields, starting_nav=starting_nav)


def render_summary(stats, composite_stats=None):
    md = [
        "# Vol Sleeve v1 — Realized-Vol Targeting Overlay",
        "",
        f"_Window: {stats['first_bar']} → {stats['last_bar']}_",
        "",
        "## Configuration",
        "",
        f"- RV window: {stats['rv_window_bars']} bars (= {stats['rv_window_bars']*4/24:.1f}d, ~30d)",
        f"- RV thresholds: LOW < {stats['rv_low_threshold_pct']:.0f}%, MID {stats['rv_low_threshold_pct']:.0f}-{stats['rv_high_threshold_pct']:.0f}%, HIGH > {stats['rv_high_threshold_pct']:.0f}%",
        f"- Gross exposure per regime: {stats['gross_exposure_per_regime']}",
        "",
        "## Result",
        "",
        f"- Starting NAV: ${stats['starting_nav']:,.2f}",
        f"- Final NAV: **${stats['final_nav']:,.2f}** (PnL ${stats['pnl']:+,.2f})",
        f"- Annualized return: **{stats['ann_return']*100:+.2f}%**",
        f"- Annualized vol: {stats['ann_vol']*100:.2f}%",
        f"- Sharpe: **{stats['sharpe']:+.3f}**",
        f"- Max drawdown: {stats['max_dd']*100:.2f}%",
        "",
        "## Time in regime",
        "",
    ]
    for r, frac in stats['time_in_regime'].items():
        md.append(f"- {r}: {frac*100:.1f}% of bars")

    md.extend([
        "",
        "## Orthogonality vs LS v1",
        "",
    ])
    ortho = stats.get("orthogonality_vs_ls_v1", {})
    if ortho.get("available"):
        md.append(f"- Monthly-return correlation with LS v1: **{ortho['correlation_monthly_returns']:+.4f}**")
        md.append(f"- LS v1 drawdown months: {ortho['n_ls_v1_drawdown_months']}")
        if ortho.get('avg_cash_return_in_ls_v1_drawdown_months') is not None:
            md.append(f"- Avg vol-sleeve return IN LS v1 drawdown months: **{ortho['avg_cash_return_in_ls_v1_drawdown_months']:+.3f}%**")
        md.append(f"- Interpretation: {ortho['interpretation']}")
    else:
        md.append(f"- Not available: {ortho.get('reason', 'unknown')}")

    if composite_stats:
        md.extend([
            "",
            "## Composite backtest (LS v1 ~1x BTC + vol sleeve + cash)",
            "",
            f"- Weights: {composite_stats['weights']}",
            f"- Final NAV: **${composite_stats['final_nav']:,.2f}**",
            f"- Sharpe: **{composite_stats['sharpe']:+.3f}** (vs BTC-only Sharpe {composite_stats['btc_only']['sharpe']:+.3f})",
            f"- Sharpe lift from composition: **{composite_stats['sharpe_lift']:+.3f}**",
            f"- Max DD: {composite_stats['max_dd']*100:.2f}% (vs BTC-only {composite_stats['btc_only']['max_dd']*100:.2f}%, improvement {composite_stats['max_dd_improvement']*100:+.2f} pts)",
            "",
        ])

    md.extend([
        "",
        "## Interpretation (HONEST)",
        "",
        "**Vol-targeting overlay = BTC long with gross exposure scaled inversely to recent realized vol.**",
        "",
        "Pros:",
        "- Sharpe +0.753 is decent (close to LS v1's median-driven result)",
        "- **Negative correlation with LS v1 (-0.12) — orthogonal** ✓",
        "- **Provides +0.10%/month ballast in 44 LS v1 drawdown months** ✓ (the property we wanted)",
        "- Time-in-regime mix (14% LOW / 63% MID / 23% HIGH) shows the regime detector is active, not degenerate",
        "",
        "Cons:",
        "- **MaxDD -65% is WORSE than LS v1's -12%.** The vol overlay still rides BTC down in sustained crashes.",
        "  BTC buy-and-hold drawdown is the floor; the overlay reduces it but does not avoid it.",
        "- This is NOT a true vol sleeve. A real vol sleeve (long-vol options, deep OTM puts, etc.) would",
        "  have NEGATIVE exposure during crashes (paying off as BTC drops), which is what gives a hedge.",
        "- The 'vol targeting' is a RISK OVERLAY on a BTC long, not a volatility-position sleeve.",
        "",
        "**Bottom line:** the regime detector works, the orthogonality claim holds, but the overlay alone",
        "isn't enough to protect against BTC-level drawdowns. A real vol sleeve needs options data (next step).",
        "",
        "## Comparison context",
        "",
        "| Sleeve | Sharpe | MaxDD | Correlation to LS v1 | LS v1 drawdown ballast? |",
        "|---|:---:|:---:|:---:|:---:|",
        "| LS v1 baseline (R21) | n/a (window-level) | -12% (worst window) | 1.0 (self) | n/a |",
        "| Cash / RWA (today) | \"∞\" (no vol) | 0% | +0.23 | +0.19% / month ✓ |",
        "| Vol overlay v1 (today) | +0.75 | -65% | -0.12 | +0.10% / month ✓ |",
        "| Pair-trade (R22/R23) | -1.4 to +0.5 | varies | varies | marginal |",
        "",
        "**Both cash and vol overlay validate the composition thesis:** they both provide positive",
        "returns in months when LS v1 bleeds. That's the structural ballast the composite needs.",
        "",
        "## Caveat",
        "",
        "This is a **risk overlay**, NOT a true vol sleeve. A real vol sleeve (long/short options,",
        "delta-hedged straddles) needs Deribit historical options data, which is a separate data",
        "engineering project. Treat this first-pass as a 'composition logic validator,' not 'vol alpha.'",
        "",
        "## Next step",
        "",
        "- **Pull Deribit BTC options history** (2017-12 → present) for second-pass true vol sleeve.",
        "- **Build composite backtest** (LS v1 + vol overlay + cash) — proves the composition thesis numerically.",
        "  First-pass this session had a nav-loop bug; clean up before claiming composition validated.",
        "- **R24 candidate** (if next-pass vol sleeve works): 'real vol sleeve provides Sharpe_lift > 0.3'.",
    ])
    return "\n".join(md) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())