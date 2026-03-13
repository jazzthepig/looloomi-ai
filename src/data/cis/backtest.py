"""
CIS Backtest Framework v2
=========================
Backtest CIS rating strategy over 6 months:
- Calculate CIS scores at month-start
- Buy: CIS grade A+ / A
- Sell: CIS grade C or below
- Compare performance vs BTC buy-and-hold

This validates whether CIS ratings can predict future performance.

Author: Seth
"""

import json
import time
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
import sys
import os

# Use local yfinance
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import yfinance as yf


# Backtest configuration
BACKTEST_START = "2025-09-01"
BACKTEST_END = "2026-03-01"
REBALANCE_FREQ = "monthly"

# Test assets
CRYPTO_SYMBOLS = {
    "BTC-USD": "Bitcoin",
    "ETH-USD": "Ethereum",
    "SOL-USD": "Solana",
    "BNB-USD": "BNB",
    "AVAX-USD": "Avalanche",
    "ADA-USD": "Cardano",
    "XRP-USD": "XRP",
    "DOGE-USD": "Dogecoin",
    "DOT-USD": "Polkadot",
    "LINK-USD": "Chainlink",
    "UNI-USD": "Uniswap",
    "AAVE-USD": "Aave",
    "MKR-USD": "Maker",
    "MATIC-USD": "Polygon",
    "ARB-USD": "Arbitrum",
}

# Traditional assets
TRADITIONAL_SYMBOLS = {
    "SPY": "S&P 500",
    "QQQ": "Nasdaq 100",
    "GLD": "Gold",
    "TLT": "Treasury Bond",
}


def calculate_historical_cis(
    prices: List[dict],
    volume: List[dict],
    date: str,
    asset_class: str = "Crypto"
) -> Dict[str, Any]:
    """
    Calculate CIS score at a specific historical date using only data available up to that date.
    """
    # Get prices up to the date
    past_prices = [p for p in prices if p["date"] <= date]
    past_volumes = [v for v in volume if v["date"] <= date] if volume else []

    if len(past_prices) < 30:
        return None

    # Get current price and 30d price
    current_price = past_prices[-1]["close"]
    price_30d_ago = past_prices[-31]["close"] if len(past_prices) > 30 else past_prices[0]["close"]
    change_30d = ((current_price - price_30d_ago) / price_30d_ago) * 100

    # Volume
    avg_volume = sum(p["volume"] for p in past_volumes[-30:]) / 30 if past_volumes else 0

    # Market cap proxy (simplified)
    market_cap_proxy = current_price * avg_volume * 365

    # === Simplified CIS Scoring ===
    # F: Fundamental (based on market cap as proxy)
    f_score = 30  # base
    if market_cap_proxy > 10e9:
        f_score += 40
    elif market_cap_proxy > 1e9:
        f_score += 30
    elif market_cap_proxy > 100e6:
        f_score += 20
    f_score = min(100, f_score)

    # M: Momentum (based on 30d return)
    m_score = 50
    if change_30d > 20:
        m_score += 30
    elif change_30d > 10:
        m_score += 20
    elif change_30d > 0:
        m_score += 10
    elif change_30d > -10:
        m_score -= 10
    else:
        m_score -= 20
    m_score = min(100, max(0, m_score))

    # O: On-chain / Risk-adjusted (volume health)
    o_score = 40
    if avg_volume > 10_000_000:
        o_score += 30
    elif avg_volume > 1_000_000:
        o_score += 20
    elif avg_volume > 100_000:
        o_score += 10
    o_score = min(100, o_score)

    # S: Sentiment (simplified - use momentum as proxy)
    s_score = 50 + (change_30d / 2)  # Simplified
    s_score = min(100, max(0, s_score))

    # A: Alpha (smaller assets have more alpha potential)
    a_score = 50
    if market_cap_proxy < 1e9:
        a_score += 20
    elif market_cap_proxy < 10e9:
        a_score += 10
    elif market_cap_proxy > 50e9:
        a_score -= 10
    a_score = min(100, max(0, a_score))

    # Weighted total (Crypto weights)
    total = (
        0.25 * f_score +
        0.25 * m_score +
        0.20 * o_score +
        0.15 * s_score +
        0.15 * a_score
    )

    # Grade
    if total >= 85:
        grade = "A+"
    elif total >= 80:
        grade = "A"
    elif total >= 70:
        grade = "B+"
    elif total >= 60:
        grade = "B"
    elif total >= 50:
        grade = "C+"
    elif total >= 40:
        grade = "C"
    else:
        grade = "D"

    return {
        "f": round(f_score, 1),
        "m": round(m_score, 1),
        "o": round(o_score, 1),
        "s": round(s_score, 1),
        "a": round(a_score, 1),
        "total": round(total, 1),
        "grade": grade,
        "change_30d": round(change_30d, 2),
    }


def get_monthly_dates(start: str, end: str) -> List[str]:
    """Generate monthly dates for rebalancing."""
    dates = []
    current = datetime.strptime(start, "%Y-%m-%d")
    end_date = datetime.strptime(end, "%Y-%m-%d")

    while current <= end_date:
        dates.append(current.strftime("%Y-%m-%d"))
        # Next month
        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1)
        else:
            current = current.replace(month=current.month + 1)

    return dates


def run_backtest():
    """Run the CIS backtest."""
    print("=" * 70)
    print("CIS Backtest Framework v2")
    print("=" * 70)
    print(f"Period: {BACKTEST_START} to {BACKTEST_END}")
    print(f"Strategy: Buy A/A+, Sell C or below")
    print(f"Rebalance: {REBALANCE_FREQ}")
    print()

    all_symbols = {**CRYPTO_SYMBOLS, **TRADITIONAL_SYMBOLS}

    # Fetch historical data
    print("Fetching historical data...")

    price_data = {}
    volume_data = {}

    for symbol in all_symbols.keys():
        try:
            ticker = yf.Ticker(symbol)
            # Download more history for 30d lookback
            hist = ticker.history(start="2025-08-01", end=BACKTEST_END, auto_adjust=True)
            time.sleep(0.3)  # Rate limiting

            if len(hist) > 0:
                price_data[symbol] = [
                    {"date": str(row.name.date()), "close": row["Close"]}
                    for _, row in hist.iterrows()
                ]
                volume_data[symbol] = [
                    {"date": str(row.name.date()), "volume": row["Volume"]}
                    for _, row in hist.iterrows()
                ]
                print(f"  {symbol}: {len(price_data[symbol])} days loaded")
        except Exception as e:
            print(f"  {symbol}: ERROR - {e}")

    print(f"\nLoaded {len(price_data)} assets")
    print()

    if not price_data:
        print("No data loaded. Exiting.")
        return

    # Get rebalancing dates
    rebalance_dates = get_monthly_dates(BACKTEST_START, BACKTEST_END)
    print(f"Rebalancing dates: {len(rebalance_dates)} months")
    print()

    # Run backtest
    # Track portfolio returns
    portfolio_returns = []
    btc_returns = []
    grades_a_performance = []
    grades_c_performance = []

    for i, date in enumerate(rebalance_dates[:-1]):
        next_date = rebalance_dates[i + 1]

        # Calculate CIS scores at this date
        scores = {}
        for symbol in all_symbols.keys():
            if symbol in price_data and symbol in volume_data:
                score = calculate_historical_cis(
                    price_data[symbol],
                    volume_data[symbol],
                    date,
                    "Crypto" if symbol in CRYPTO_SYMBOLS else "Traditional"
                )
                if score:
                    scores[symbol] = score

        # Separate by grade
        grade_a = [s for s in scores.values() if s["grade"] in ["A+", "A"]]
        grade_b = [s for s in scores.values() if s["grade"] in ["B+", "B"]]
        grade_c = [s for s in scores.values() if s["grade"] in ["C+", "C", "D"]]

        # Calculate next month performance for each group
        def get_next_month_return(symbol):
            if symbol not in price_data:
                return None
            prices = price_data[symbol]
            current_price = next((p["close"] for p in prices if p["date"] >= date), None)
            next_price = next((p["close"] for p in prices if p["date"] >= next_date), None)
            if current_price and next_price:
                return (next_price - current_price) / current_price * 100
            return None

        a_returns = [r for r in [get_next_month_return(s) for s in scores.keys() if scores[s]["grade"] in ["A+", "A"]] if r is not None]
        c_returns = [r for r in [get_next_month_return(s) for s in scores.keys() if scores[s]["grade"] in ["C+", "C", "D"]] if r is not None]

        avg_a = sum(a_returns) / len(a_returns) if a_returns else 0
        avg_c = sum(c_returns) / len(c_returns) if c_returns else 0

        # BTC benchmark
        btc_return = get_next_month_return("BTC-USD") or 0

        print(f"{date}:")
        print(f"  Grade A/A+: {len(grade_a)} assets, avg next month return: {avg_a:+.2f}%")
        print(f"  Grade C/D:   {len(grade_c)} assets, avg next month return: {avg_c:+.2f}%")
        print(f"  BTC:         {btc_return:+.2f}%")
        print(f"  Alpha (A vs C): {avg_a - avg_c:+.2f}%")
        print()

        grades_a_performance.append(avg_a)
        grades_c_performance.append(avg_c)
        btc_returns.append(btc_return)

    # Summary
    print("=" * 70)
    print("BACKTEST RESULTS")
    print("=" * 70)

    avg_a_perf = sum(grades_a_performance) / len(grades_a_performance) if grades_a_performance else 0
    avg_c_perf = sum(grades_c_performance) / len(grades_c_performance) if grades_c_performance else 0
    avg_btc = sum(btc_returns) / len(btc_returns) if btc_returns else 0

    print(f"\nAverage Monthly Returns:")
    print(f"  Grade A/A+ assets: {avg_a_perf:+.2f}%")
    print(f"  Grade C/D assets: {avg_c_perf:+.2f}%")
    print(f"  BTC:              {avg_btc:+.2f}%")
    print(f"\n  Alpha (A vs C):   {avg_a_perf - avg_c_perf:+.2f}%")
    print(f"  Alpha (A vs BTC): {avg_a_perf - avg_btc:+.2f}%")

    # Win rate
    wins = sum(1 for a, c in zip(grades_a_performance, grades_c_performance) if a > c)
    win_rate = wins / len(grades_a_performance) * 100 if grades_a_performance else 0

    print(f"\n  Win rate (A beats C): {win_rate:.1f}%")

    # Save results
    results = {
        "config": {
            "start": BACKTEST_START,
            "end": BACKTEST_END,
            "rebalance": REBALANCE_FREQ,
            "assets": len(all_symbols),
        },
        "summary": {
            "avg_return_grade_a": round(avg_a_perf, 2),
            "avg_return_grade_c": round(avg_c_perf, 2),
            "avg_return_btc": round(avg_btc, 2),
            "alpha_a_vs_c": round(avg_a_perf - avg_c_perf, 2),
            "alpha_a_vs_btc": round(avg_a_perf - avg_btc, 2),
            "win_rate": round(win_rate, 1),
        },
        "monthly_data": [
            {
                "date": rebalance_dates[i],
                "grade_a_return": round(grades_a_performance[i], 2) if i < len(grades_a_performance) else None,
                "grade_c_return": round(grades_c_performance[i], 2) if i < len(grades_c_performance) else None,
                "btc_return": round(btc_returns[i], 2) if i < len(btc_returns) else None,
            }
            for i in range(len(rebalance_dates) - 1)
        ],
    }

    output_path = os.path.join(os.path.dirname(__file__), "backtest_results.json")
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)

    print(f"\nResults saved to: {output_path}")

    return results


if __name__ == "__main__":
    run_backtest()
