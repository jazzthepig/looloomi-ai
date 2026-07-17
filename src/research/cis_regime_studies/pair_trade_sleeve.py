"""
Pair-Trade Sleeve — Cross-Sectional Reversal (Minimax-B, 2026-07-16)

WHY THIS EXISTS
===============
R21 (LS v1 baseline fragility) reframed the strategy roadmap: LS v1 trend-following
is structurally vulnerable to BTC top/reversal regimes. The fix is NOT a smarter
gate within LS v1 — it's regime-orthogonal multi-strategy composition. The first
new sleeve to build is the pair-trade sleeve.

DESIGN (from reports/STRATEGY_GRID_2026-07-16.md §7)
====================================================
- Signal: cross-sectional 30d return reversal.
  - Each rebalance day (weekly): rank universe by 30d return.
  - LONG bottom decile (lowest 30d return = losers, mean-reversion candidate).
  - SHORT top decile (highest 30d return = winners, reversal candidate).
- Why reversal (not cointegration pairs)? Two reasons:
  1. Doesn't require pair-selection tuning (Hurst / cointegration tests are noisy
     and overfit prone — R1, R12 lessons).
  2. Scales linearly with universe size. 21 names × 2 long / 2 short (decile
     of 20) = 4 positions per side = 8 total. Easy to reason about.
- Rebalance: weekly (5 trading days = 30 bars × 4h).
- Position sizing: equal-weight within each leg.
- Holding period: 1 week (forced rebalance). Spreads may revert sooner, but
  weekly rebalance matches the signal frequency (30d lookback → ~weekly turnover).

REGIME ORTHOGONALITY EXPECTATION
================================
- LS v1 trend-following: wins in trending regimes (RISK_ON / EASING uptrend).
- Pair-trade reversal:   wins in chop / reversal regimes (CHOP / TIGHTENING).
- Correlation target:    monthly returns < 0.3 in either direction.

DATA
====
21 instruments, 4h Binance spot, 2017-08 (BTC/ETH/LTC/BNB) through 2026-07-16.
Per-instrument date ranges vary (see reports/STRATEGY_GRID §2).

USAGE
=====
    python3 -m src.research.cis_regime_studies.pair_trade_sleeve
    python3 -m src.research.cis_regime_studies.pair_trade_sleeve --lookback 20
    python3 -m src.research.cis_regime_studies.pair_trade_sleeve --rebalance-days 7
"""
from __future__ import annotations

import argparse
import json
import logging
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd


# ── Paths ────────────────────────────────────────────────────────────────────

THIS_DIR = Path(__file__).parent
PROJECT_ROOT = THIS_DIR.parent.parent.parent
SPOT_FEATHER_DIR = Path(
    "/Volumes/CometCloudAI/looloomi-research/data/ohlcv/4h-spot/"
)

# (feather_stem, display_symbol)
INSTRUMENTS = [
    ("BTC_USDT-4h-spot", "BTC"),
    ("ETH_USDT-4h-spot", "ETH"),
    ("SOL_USDT-4h-spot", "SOL"),
    ("LTC_USDT-4h-spot", "LTC"),
    ("BNB_USDT-4h-spot", "BNB"),
    ("XRP_USDT-4h-spot", "XRP"),
    ("ADA_USDT-4h-spot", "ADA"),
    ("DOGE_USDT-4h-spot", "DOGE"),
    ("DOT_USDT-4h-spot", "DOT"),
    ("LINK_USDT-4h-spot", "LINK"),
    ("AVAX_USDT-4h-spot", "AVAX"),
    ("ATOM_USDT-4h-spot", "ATOM"),
    ("NEAR_USDT-4h-spot", "NEAR"),
    ("MATIC_USDT-4h-spot", "MATIC"),
    ("UNI_USDT-4h-spot", "UNI"),
    ("AAVE_USDT-4h-spot", "AAVE"),
    ("MKR_USDT-4h-spot", "MKR"),
    ("APT_USDT-4h-spot", "APT"),
    ("ARB_USDT-4h-spot", "ARB"),
    ("OP_USDT-4h-spot", "OP"),
    ("SUI_USDT-4h-spot", "SUI"),
]


# ── Helpers ──────────────────────────────────────────────────────────────────

def load_all_bars(feather_dir: Path = SPOT_FEATHER_DIR) -> dict[str, pd.DataFrame]:
    """Load all available 4h spot bars into a {symbol: DataFrame} dict.

    Each DataFrame has columns [date, open, high, low, close, volume] indexed by date.
    Returns only instruments that have a feather file present.
    """
    bars: dict[str, pd.DataFrame] = {}
    for stem, symbol in INSTRUMENTS:
        path = feather_dir / f"{stem}.feather"
        if not path.exists():
            logging.warning(f"missing feather: {path}")
            continue
        df = pd.read_feather(path)
        df["date"] = pd.to_datetime(df["date"], utc=True)
        df = df.set_index("date").sort_index()
        bars[symbol] = df
    logging.info(f"loaded {len(bars)}/{len(INSTRUMENTS)} instruments")
    return bars


def build_returns_matrix(bars: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Build a wide DataFrame of close prices, indexed by common timestamp.

    For each timestamp present in ≥MIN_UNIVERSE instruments, take the close.
    Returns a (T × N) DataFrame of close prices.
    """
    closes = {}
    for symbol, df in bars.items():
        closes[symbol] = df["close"].rename(symbol)
    wide = pd.concat(closes.values(), axis=1)
    wide = wide.sort_index()
    return wide


# ── Pair-trade signal + backtest ─────────────────────────────────────────────

def pair_trade_backtest(
    prices: pd.DataFrame,
    lookback_bars: int = 30,       # 30 × 4h = 120h = 5 trading days
    rebalance_bars: int = 30,       # weekly rebalance (30 × 4h = 5 days)
    decile: float = 0.1,            # long bottom decile / short top decile
    min_universe: int = 10,         # require at least 10 names for decile = 1 each side
    starting_nav: float = 10_000.0,
    cost_bps: float = 5.0,          # round-trip cost per rebalance (5 bps conservative)
    max_gross_lev: float = 1.5,     # 75% long + 75% short = 1.5x gross, 0% net
) -> dict:
    """Run a vectorized cross-sectional reversal backtest.

    Args:
        prices: wide DataFrame (T × N) of close prices, indexed by timestamp.
        lookback_bars: how many bars of history to use for the reversal signal.
        rebalance_bars: how often to rebalance (in bars).
        decile: fraction of universe to long / short on each side.
        min_universe: minimum number of valid (non-NaN) names to form the trade.
        starting_nav: starting sleeve NAV in dollars.
        cost_bps: round-trip transaction cost in basis points per rebalance.
        max_gross_lev: cap on total gross exposure (long + short).

    Returns:
        dict with keys: nav (pd.Series), trades (list), stats (dict).
    """
    # Compute bar-by-bar returns (simple, not log, to match Nautilus convention)
    rets = prices.pct_change()
    # Lookback return (signal): trailing `lookback_bars` cumulative return
    signal = prices.pct_change(periods=lookback_bars)

    n_bars = len(prices)
    rebalance_idx = list(range(lookback_bars, n_bars, rebalance_bars))
    logging.info(f"rebalance events: {len(rebalance_idx)} over {n_bars} bars")

    nav = pd.Series(index=prices.index, dtype=float)
    nav.iloc[:lookback_bars] = starting_nav  # flat during warmup

    # State: per-instrument current weight (fraction of NAV per side)
    positions: dict[str, float] = {}  # symbol -> signed weight (positive=long, negative=short)
    per_trade_log = []
    turnover_total = 0.0

    for bar_idx in range(lookback_bars, n_bars):
        ts = prices.index[bar_idx]
        prev_ts = prices.index[bar_idx - 1]
        nav_prev = nav.iloc[bar_idx - 1] if bar_idx > 0 else starting_nav

        # Mark to market: apply each held position's bar return to NAV
        bar_pnl = 0.0
        for sym, w in positions.items():
            if sym in rets.columns:
                r = rets.at[prev_ts, sym] if prev_ts in rets.index else 0.0
                if pd.isna(r):
                    r = 0.0
                bar_pnl += w * nav_prev * r
        nav.iloc[bar_idx] = nav_prev + bar_pnl

        # Rebalance?
        if bar_idx in rebalance_idx:
            # Get signal snapshot at this rebalance
            sig = signal.iloc[bar_idx].dropna()
            # Filter to names with valid prices at this bar
            valid_prices = prices.iloc[bar_idx].dropna()
            valid = sig.index.intersection(valid_prices.index).tolist()
            if len(valid) < min_universe:
                continue  # not enough universe, hold current positions

            sig_valid = sig.loc[valid].sort_values()
            n = len(sig_valid)
            k = max(1, int(n * decile))  # # of names per side

            longs = sig_valid.index[:k].tolist()    # lowest 30d return → long
            shorts = sig_valid.index[-k:].tolist()  # highest 30d return → short

            # Compute new positions: equal-weight within each leg, gross scaled to max_gross_lev
            new_positions = {}
            long_w = (max_gross_lev / 2) / k   # 0.75 / k per long name
            short_w = -(max_gross_lev / 2) / k  # -0.75 / k per short name
            for sym in longs:
                new_positions[sym] = long_w
            for sym in shorts:
                new_positions[sym] = short_w

            # Compute turnover (sum of |new - old| / 2 = one-way turnover)
            all_syms = set(new_positions.keys()) | set(positions.keys())
            turnover = sum(abs(new_positions.get(s, 0) - positions.get(s, 0))
                           for s in all_syms) / 2.0
            turnover_total += turnover

            # Apply transaction cost (charged on one-way turnover × NAV × cost_bps)
            cost_dollars = turnover * nav.iloc[bar_idx] * (cost_bps / 10_000)
            nav.iloc[bar_idx] -= cost_dollars

            per_trade_log.append({
                "ts": str(ts),
                "n_universe": n,
                "k_per_side": k,
                "longs": longs,
                "shorts": shorts,
                "turnover_oneway": round(turnover, 4),
                "cost_dollars": round(cost_dollars, 4),
                "nav_before_cost": round(nav.iloc[bar_idx] + cost_dollars, 4),
            })
            positions = new_positions

    # Close any remaining positions at final bar (no extra cost — assume intra-bar exit)
    final_nav = nav.iloc[-1] if len(nav) else starting_nav
    pnl = final_nav - starting_nav

    # Stats
    nav_clean = nav.dropna()
    daily_rets = nav_clean.resample("1D").last().pct_change().dropna()
    if len(daily_rets) > 1:
        ann_ret = daily_rets.mean() * 365
        ann_vol = daily_rets.std() * np.sqrt(365)
        sharpe = ann_ret / ann_vol if ann_vol > 0 else 0.0
        max_dd = (nav_clean / nav_clean.cummax() - 1).min()
    else:
        ann_ret = ann_vol = sharpe = max_dd = 0.0

    stats = {
        "starting_nav": starting_nav,
        "final_nav": round(final_nav, 2),
        "pnl": round(pnl, 2),
        "n_bars": n_bars,
        "n_rebalances": len(rebalance_idx),
        "avg_turnover_oneway": round(turnover_total / max(1, len(rebalance_idx)), 4),
        "ann_return_pct": round(ann_ret * 100, 3),
        "ann_vol_pct": round(ann_vol * 100, 3),
        "sharpe": round(sharpe, 3),
        "max_drawdown_pct": round(max_dd * 100, 3),
        "lookback_bars": lookback_bars,
        "rebalance_bars": rebalance_bars,
        "decile": decile,
        "min_universe": min_universe,
        "cost_bps": cost_bps,
        "max_gross_lev": max_gross_lev,
        "first_bar": str(prices.index[0]),
        "last_bar": str(prices.index[-1]),
    }
    return {
        "nav": nav_clean,
        "trades": per_trade_log,
        "stats": stats,
    }


# ── Main ─────────────────────────────────────────────────────────────────────

def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--lookback", type=int, default=30,
                    help="Lookback bars for reversal signal (default 30 = 5 days on 4h)")
    ap.add_argument("--rebalance-bars", type=int, default=30,
                    help="Rebalance frequency in bars (default 30 = weekly)")
    ap.add_argument("--decile", type=float, default=0.1,
                    help="Fraction of universe per side (default 0.1 = bottom/top decile)")
    ap.add_argument("--cost-bps", type=float, default=5.0,
                    help="Round-trip cost per rebalance in bps (default 5)")
    ap.add_argument("--starting-nav", type=float, default=10_000.0)
    ap.add_argument("--out-dir", type=Path,
                    default=PROJECT_ROOT / "reports" / "pair_trade_sleeve" /
                            datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    args = ap.parse_args(argv)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    logging.info(f"output → {args.out_dir}")

    started = time.monotonic()
    bars = load_all_bars()
    prices = build_returns_matrix(bars)
    logging.info(f"price matrix: {prices.shape[0]} bars × {prices.shape[1]} names")

    result = pair_trade_backtest(
        prices,
        lookback_bars=args.lookback,
        rebalance_bars=args.rebalance_bars,
        decile=args.decile,
        starting_nav=args.starting_nav,
        cost_bps=args.cost_bps,
    )
    elapsed = round(time.monotonic() - started, 2)

    # Write outputs
    stats = result["stats"]
    stats["elapsed_sec"] = elapsed
    (args.out_dir / "summary.json").write_text(json.dumps(stats, indent=2, default=str))

    # Write per-rebalance trade log (compact)
    trades_path = args.out_dir / "trades.json"
    trades_path.write_text(json.dumps(result["trades"], indent=2, default=str))

    # Write NAV series for downstream correlation analysis
    nav_path = args.out_dir / "nav.parquet"
    result["nav"].to_frame("nav").to_parquet(nav_path)

    # Render summary markdown
    md = render_summary(stats, elapsed, n_instruments=len(bars))
    (args.out_dir / "summary.md").write_text(md)
    print(md)
    return 0


def render_summary(stats: dict, elapsed: float, n_instruments: int) -> str:
    md = [
        "# Pair-Trade Sleeve — Cross-Sectional Reversal Backtest",
        "",
        f"_Elapsed: {elapsed}s, instruments: {n_instruments}_",
        "",
        "## Configuration",
        "",
        f"- Lookback bars: `{stats['lookback_bars']}` (= {stats['lookback_bars']*4}h = {stats['lookback_bars']*4/24:.1f}d)",
        f"- Rebalance frequency: `{stats['rebalance_bars']}` bars (= {stats['rebalance_bars']*4/24:.1f}d, weekly)",
        f"- Decile per side: `{stats['decile']}`",
        f"- Min universe size: `{stats['min_universe']}`",
        f"- Round-trip cost: `{stats['cost_bps']}` bps",
        f"- Max gross leverage: `{stats['max_gross_lev']}`",
        "",
        "## Result",
        "",
        f"- Starting NAV: ${stats['starting_nav']:,.2f}",
        f"- Final NAV: **${stats['final_nav']:,.2f}** (PnL ${stats['pnl']:+,.2f})",
        f"- Annualized return: **{stats['ann_return_pct']:+.2f}%**",
        f"- Annualized vol: {stats['ann_vol_pct']:.2f}%",
        f"- Sharpe (daily→annual): **{stats['sharpe']:.3f}**",
        f"- Max drawdown: {stats['max_drawdown_pct']:.2f}%",
        f"- Rebalances: {stats['n_rebalances']}",
        f"- Avg one-way turnover / rebalance: {stats['avg_turnover_oneway']:.2%}",
        "",
        f"- Window: {stats['first_bar']} → {stats['last_bar']}",
        "",
        "## Interpretation",
        "",
        "- **Sharp > 0.5** with low max DD = sleeve viable; **Sharpe 1.0+** = great.",
        "- **Sharpe near 0** = signal has no edge after costs — try different lookback / decile.",
        "- **Negative Sharpe** = refutation candidate — add to REFUTATION_LEDGER.md.",
        "",
        "## Next step",
        "",
        "Compute monthly-return correlation with LS v1 baseline (target < 0.3 for orthogonality).",
        "Driver: `src/research/cis_regime_studies/sleeve_orthogonality_check.py` (TODO).",
    ]
    return "\n".join(md) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())