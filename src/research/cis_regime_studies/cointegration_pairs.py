"""
Cointegration-based Pair-Trade Sleeve (Minimax-B, 2026-07-16)

WHY THIS EXISTS
===============
R22 falsified cross-sectional reversal as a viable pair-trade signal on broad
crypto. The losers are structurally declining (deprecation, broken projects)
and reversal fights the trend. The RIGHT pair-trade for crypto is
**cointegration-based**: find two assets whose price spread is stationary,
trade z-score of the spread.

DESIGN
======
For each candidate pair (i, j):
1. Compute 90d rolling OLS hedge ratio β: log(price_i) = α + β · log(price_j) + ε
2. Spread s = log(price_i) - β · log(price_j)  (log-spread for stationarity)
3. z-score = (s - rolling_mean(s, 30d)) / rolling_std(s, 30d)
4. ENTRY: |z| > 2σ → trade the spread (short i / long j if z > 2, vice versa)
5. EXIT: |z| < 0.5σ → close position
6. STOP: |z| > 4σ → emergency close (model broken)

POTENTIAL COINTEGRATED PAIRS (hand-picked, then validated by EG test)
======================================================================
- ETH/BTC — classic, often discussed
- LTC/BTC — old pair, both slow L1s
- BNB/ETH — both smart-contract L1s
- AVAX/SOL — both high-perf L1s
- ARB/OP — both L2s, same narrative
- AAVE/UNI — both DeFi blue-chips
- LINK/ETH — oracle vs L1
- DOT/ATOM — both parachain/cosmoshub

EXPECTED OUTCOME
================
In a cointegrated pair:
- The spread has stable long-run mean (σ-bounded)
- It diverges occasionally due to liquidity / narrative / regime shifts
- The divergence converges (mean-reverts) — this is the trade

REGIME ORTHOGONALITY
====================
Cointegration pairs should win in CHOP and sideways regimes (when the spread
is oscillating around its mean, no strong trend). Should NOT win in strong
trends (one leg runs away, cointegration breaks).

USAGE
=====
    python3 -m src.research.cis_regime_studies.cointegration_pairs
    python3 -m src.research.cis_regime_studies.cointegration_pairs --pair ETH,BTC --lookback 90
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.tsa.stattools import coint, adfuller


THIS_DIR = Path(__file__).parent
PROJECT_ROOT = THIS_DIR.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.research.cis_regime_studies.pair_trade_sleeve import (
    INSTRUMENTS,
    load_all_bars,
    build_returns_matrix,
    SPOT_FEATHER_DIR,
)


# ── Candidate pairs ──────────────────────────────────────────────────────────

# Hand-picked pairs by structural similarity (same narrative / sector)
# These are the "educated guesses" — the EG test will tell us which are actually
# cointegrated on the 9-year data.
CANDIDATE_PAIRS = [
    ("ETH", "BTC"),    # Smart-contract L1 vs store-of-value L1
    ("LTC", "BTC"),    # Old L1 vs BTC (correlation 0.7+ historically)
    ("BNB", "ETH"),    # Exchange token vs smart-contract L1
    ("AVAX", "SOL"),   # High-perf L1 vs high-perf L1
    ("NEAR", "AVAX"),  # High-perf L1 pair
    ("ARB", "OP"),     # L2 narrative pair
    ("AAVE", "UNI"),   # DeFi blue-chip pair
    ("LINK", "ETH"),   # Oracle vs L1
    ("DOT", "ATOM"),   # Parachain vs Cosmos hub
    ("MATIC", "ETH"),  # L2 vs L1 (pre-rebrand MATIC)
    ("DOGE", "BTC"),   # Meme vs BTC
    ("XRP", "ETH"),    # Payments vs smart-contract
    ("AAVE", "ETH"),   # DeFi vs L1
    ("MKR", "ETH"),    # DeFi vs L1
    ("APT", "SUI"),    # New L1 vs new L1
]


# ── Cointegration test ───────────────────────────────────────────────────────

def test_cointegration_full(prices_a: pd.Series, prices_b: pd.Series,
                            p_threshold: float = 0.05) -> dict:
    """Engle-Granger cointegration test on full price series.

    Returns dict with: p_value, is_cointegrated, hedge_ratio, alpha, spread_mean, spread_std.
    """
    # Align on common timestamps
    common = prices_a.dropna().index.intersection(prices_b.dropna().index)
    a = np.log(prices_a.loc[common].values)
    b = np.log(prices_b.loc[common].values)
    if len(a) < 100:
        return {"p_value": 1.0, "is_cointegrated": False, "reason": "insufficient data"}

    # OLS: log(a) = alpha + beta * log(b) + epsilon
    beta, alpha, _, _, _ = stats.linregress(b, a)
    spread = a - (alpha + beta * b)

    # ADF test on spread
    try:
        adf_stat, p_value, _, _, crit_values, _ = adfuller(spread, maxlag=30, autolag="AIC")
    except Exception as exc:
        return {"p_value": 1.0, "is_cointegrated": False, "reason": f"ADF failed: {exc!r}"}

    return {
        "p_value": float(p_value),
        "is_cointegrated": bool(p_value < p_threshold),
        "adf_stat": float(adf_stat),
        "hedge_ratio_beta": float(beta),
        "alpha": float(alpha),
        "spread_mean": float(spread.mean()),
        "spread_std": float(spread.std()),
        "n_obs": int(len(a)),
        "first_date": str(common.min()),
        "last_date": str(common.max()),
    }


# ── Pair-trade backtest (single pair) ────────────────────────────────────────

def backtest_pair(
    prices_a: pd.Series,
    prices_b: pd.Series,
    hedge_ratio: float,
    alpha: float,
    entry_z: float = 2.0,
    exit_z: float = 0.5,
    stop_z: float = 4.0,
    cost_bps_per_leg: float = 5.0,
    starting_nav: float = 10_000.0,
) -> dict:
    """Backtest a cointegrated pair's spread.

    Spread = log(a) - alpha - beta * log(b)
    z-score = (spread - mean_30d) / std_30d

    Position state: 1 = long spread (long a, short b), -1 = short spread, 0 = flat.
    """
    common = prices_a.dropna().index.intersection(prices_b.dropna().index)
    a = np.log(prices_a.loc[common].values)
    b = np.log(prices_b.loc[common].values)
    spread = a - (alpha + hedge_ratio * b)

    # 30d rolling z-score (30 * 6 = 180 bars on 4h since 4h = 6 bars/day, but
    # we only have 6 bars/day for 4h? Wait — 24h / 4h = 6 bars/day. So 30d = 180 bars.)
    # Actually our data is 4h bars. 1 day = 6 bars. 30d = 180 bars. 90d = 540 bars.
    LOOKBACK_Z = 180
    spread_series = pd.Series(spread, index=common)
    z_mean = spread_series.rolling(LOOKBACK_Z, min_periods=LOOKBACK_Z // 2).mean()
    z_std = spread_series.rolling(LOOKBACK_Z, min_periods=LOOKBACK_Z // 2).std()
    z_score = (spread_series - z_mean) / z_std.replace(0, np.nan)

    # Walk forward: track position state, NAV
    n = len(common)
    nav = pd.Series(index=common, dtype=float)
    position = 0  # 1 = long spread, -1 = short spread, 0 = flat
    entry_idx = None
    trades = []
    nav.iloc[0] = starting_nav

    # Pre-compute simple returns on a and b
    rets_a = pd.Series(a, index=common).diff().fillna(0)
    rets_b = pd.Series(b, index=common).diff().fillna(0)

    for i in range(1, n):
        # Mark to market: if long spread (long a, short b), return = ret_a - beta * ret_b
        if position != 0:
            bar_return = rets_a.iloc[i] - hedge_ratio * rets_b.iloc[i]
            nav.iloc[i] = nav.iloc[i - 1] * (1 + bar_return)
        else:
            nav.iloc[i] = nav.iloc[i - 1]

        z = z_score.iloc[i] if not pd.isna(z_score.iloc[i]) else 0.0

        # Entry logic
        if position == 0:
            if z > entry_z:
                # Short spread (short a, long b)
                position = -1
                cost = 2 * cost_bps_per_leg / 10_000 * nav.iloc[i]
                nav.iloc[i] -= cost
                entry_idx = i
                trades.append({"ts": str(common[i]), "action": "SHORT_SPREAD", "z": round(float(z), 3)})
            elif z < -entry_z:
                # Long spread (long a, short b)
                position = 1
                cost = 2 * cost_bps_per_leg / 10_000 * nav.iloc[i]
                nav.iloc[i] -= cost
                entry_idx = i
                trades.append({"ts": str(common[i]), "action": "LONG_SPREAD", "z": round(float(z), 3)})

        # Exit logic
        elif position == 1:  # long spread
            if abs(z) < exit_z or z > stop_z:
                pnl_pct = (nav.iloc[i] / nav.iloc[entry_idx]) - 1
                trades.append({"ts": str(common[i]), "action": "CLOSE_LONG_SPREAD", "z": round(float(z), 3),
                               "holding_bars": i - entry_idx, "pnl_pct": round(pnl_pct * 100, 3)})
                cost = 2 * cost_bps_per_leg / 10_000 * nav.iloc[i]
                nav.iloc[i] -= cost
                position = 0
                entry_idx = None
        elif position == -1:  # short spread
            if abs(z) < exit_z or z < -stop_z:
                pnl_pct = (nav.iloc[i] / nav.iloc[entry_idx]) - 1
                trades.append({"ts": str(common[i]), "action": "CLOSE_SHORT_SPREAD", "z": round(float(z), 3),
                               "holding_bars": i - entry_idx, "pnl_pct": round(pnl_pct * 100, 3)})
                cost = 2 * cost_bps_per_leg / 10_000 * nav.iloc[i]
                nav.iloc[i] -= cost
                position = 0
                entry_idx = None

    # Stats
    nav_clean = nav.dropna()
    daily_nav = nav_clean.resample("1D").last().dropna()
    daily_rets = daily_nav.pct_change().dropna()
    if len(daily_rets) > 1:
        ann_ret = daily_rets.mean() * 365
        ann_vol = daily_rets.std() * np.sqrt(365)
        sharpe = ann_ret / ann_vol if ann_vol > 0 else 0.0
        max_dd = float((nav_clean / nav_clean.cummax() - 1).min())
    else:
        ann_ret = ann_vol = sharpe = max_dd = 0.0

    n_trades = sum(1 for t in trades if "CLOSE" in t["action"])
    win_trades = sum(1 for t in trades if "CLOSE" in t["action"] and t.get("pnl_pct", 0) > 0)
    win_rate = win_trades / n_trades if n_trades else 0

    return {
        "final_nav": float(nav_clean.iloc[-1]),
        "pnl": float(nav_clean.iloc[-1] - starting_nav),
        "sharpe": float(sharpe),
        "ann_ret": float(ann_ret),
        "ann_vol": float(ann_vol),
        "max_dd": max_dd,
        "n_trades": n_trades,
        "win_rate": float(win_rate),
        "first_bar": str(common.min()),
        "last_bar": str(common.max()),
        "nav": nav_clean,
        "trades": trades,
    }


# ── Main: test all candidate pairs ──────────────────────────────────────────

def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", nargs="+", default=None,
                    help="Pairs to test as 'SYM_A,SYM_B' (default: all CANDIDATE_PAIRS)")
    ap.add_argument("--entry-z", type=float, default=2.0)
    ap.add_argument("--exit-z", type=float, default=0.5)
    ap.add_argument("--stop-z", type=float, default=4.0)
    ap.add_argument("--cost-bps", type=float, default=5.0,
                    help="Round-trip cost per leg in bps")
    ap.add_argument("--out-dir", type=Path,
                    default=PROJECT_ROOT / "reports" / "cointegration_pairs" /
                            datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    args = ap.parse_args(argv)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()

    bars = load_all_bars()
    prices = build_returns_matrix(bars)
    logging.info(f"price matrix: {prices.shape[0]} bars × {prices.shape[1]} names")

    # Pick pairs to test
    if args.pairs:
        pairs_to_test = []
        for p in args.pairs:
            a, b = p.split(",")
            pairs_to_test.append((a.strip(), b.strip()))
    else:
        pairs_to_test = CANDIDATE_PAIRS

    # Test all candidate pairs for cointegration
    logging.info(f"Testing {len(pairs_to_test)} candidate pairs for cointegration...")
    coint_results = []
    for a, b in pairs_to_test:
        if a not in prices.columns or b not in prices.columns:
            logging.warning(f"missing data for {a} or {b}; skipping")
            continue
        res = test_cointegration_full(prices[a], prices[b])
        res["pair"] = f"{a}/{b}"
        coint_results.append(res)
        status = "✅ COINT" if res["is_cointegrated"] else "❌ NOT"
        logging.info(f"  {a:5s}/{b:5s}: p={res['p_value']:.4f} {status} (β={res.get('hedge_ratio_beta', 0):+.3f}, n={res.get('n_obs', 0)})")

    # Sort by cointegration strength (lowest p-value first)
    coint_results.sort(key=lambda r: r["p_value"])

    # Backtest the top cointegrated pairs (p < 0.10 = "borderline", p < 0.05 = "coint")
    n_coint = sum(1 for r in coint_results if r["is_cointegrated"])
    logging.info(f"\nFound {n_coint} cointegrated pairs. Backtesting all that pass p < 0.10...")

    backtest_results = []
    for res in coint_results:
        if res["p_value"] > 0.10:
            continue
        a, b = res["pair"].split("/")
        bt = backtest_pair(
            prices[a], prices[b],
            hedge_ratio=res["hedge_ratio_beta"],
            alpha=res["alpha"],
            entry_z=args.entry_z,
            exit_z=args.exit_z,
            stop_z=args.stop_z,
            cost_bps_per_leg=args.cost_bps,
        )
        bt_summary = {k: v for k, v in bt.items() if k not in ("nav", "trades")}
        bt_summary["pair"] = res["pair"]
        bt_summary["coint_p_value"] = res["p_value"]
        bt_summary["hedge_ratio_beta"] = res["hedge_ratio_beta"]
        backtest_results.append(bt_summary)
        logging.info(f"  Backtest {a:5s}/{b:5s}: Sharpe {bt['sharpe']:+.3f}, "
                     f"PnL ${bt['pnl']:+.2f}, MaxDD {bt['max_dd']*100:.2f}%, "
                     f"Trades {bt['n_trades']}, WinRate {bt['win_rate']*100:.1f}%")

    # Render summary
    elapsed = round(time.monotonic() - started, 2)
    md = render_summary(coint_results, backtest_results, args, elapsed)
    (args.out_dir / "summary.md").write_text(md)

    # Write JSON outputs
    (args.out_dir / "coint_results.json").write_text(json.dumps(coint_results, indent=2, default=str))
    (args.out_dir / "backtest_results.json").write_text(json.dumps(backtest_results, indent=2, default=str))

    print(md)
    return 0


def render_summary(coint_results, backtest_results, args, elapsed):
    md = [
        "# Cointegration Pair-Trade Sleeve — Spread z-Score Backtest",
        "",
        f"_Elapsed: {elapsed}s, pairs tested: {len(coint_results)}, pairs backtested: {len(backtest_results)}_",
        "",
        "## Configuration",
        "",
        f"- Entry z-score: ±{args.entry_z}σ (30d rolling window, ~180 bars on 4h)",
        f"- Exit z-score: ±{args.exit_z}σ",
        f"- Stop z-score: ±{args.stop_z}σ",
        f"- Round-trip cost per leg: {args.cost_bps} bps (×2 for both legs = {args.cost_bps*2} bps per round-trip)",
        "",
        "## Cointegration test (Engle-Granger, full 9y window)",
        "",
        "| pair | p-value | cointegrated? | hedge ratio β | n obs |",
        "|---|---:|:---:|---:|---:|",
    ]
    for r in coint_results:
        status = "✅" if r["is_cointegrated"] else "❌"
        md.append(f"| `{r['pair']}` | {r['p_value']:.4f} | {status} | "
                  f"{r.get('hedge_ratio_beta', 0):+.3f} | {r.get('n_obs', 0):,} |")

    md.extend([
        "",
        "## Backtest (top cointegrated pairs, p < 0.10)",
        "",
        "| pair | coint p | Sharpe | AnnRet | MaxDD | Trades | WinRate |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ])
    # Sort backtest results by Sharpe desc
    backtest_results.sort(key=lambda r: -r["sharpe"])
    for r in backtest_results:
        md.append(f"| `{r['pair']}` | {r['coint_p_value']:.4f} | "
                  f"{r['sharpe']:+.3f} | {r['ann_ret']*100:+.2f}% | "
                  f"{r['max_dd']*100:.2f}% | {r['n_trades']} | {r['win_rate']*100:.1f}% |")

    md.extend([
        "",
        "## Interpretation",
        "",
        "- **Cointegrated pair (p < 0.05):** spread is stationary → mean-reversion trade has theoretical edge.",
        "- **Sharpe > 0.5 with low MaxDD:** viable sleeve; **Sharpe > 1.0:** great.",
        "- **Sharpe ≤ 0 or huge MaxDD:** the spread drifted (cointegration broke); not a robust sleeve.",
        "- **Win rate < 50%:** model is right direction but stops are too tight or costs too high.",
        "",
        "## Next step",
        "",
        "If any pair shows Sharpe > 0.5:",
        "1. Add it to the strategy grid as the new pair-trade sleeve.",
        "2. Validate orthogonality vs LS v1 (target monthly-return correlation < 0.3).",
        "3. Compute composite Sharpe (LS v1 + pair-trade).",
        "",
        "If ALL pairs fail: pivot to vol sleeve (next item in strategy grid).",
    ])
    return "\n".join(md) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())