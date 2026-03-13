"""
CIS Backtest Framework
=====================
Backtest CIS rating strategy:
- Buy: CIS grade A+ / A
- Sell: CIS grade C or below

Compare performance vs BTC buy-and-hold.

Author: Seth
"""

import asyncio
import json
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yfinance as yf


# Backtest configuration
BACKTEST_START = "2025-09-01"
BACKTEST_END = "2026-03-01"
REBALANCE_FREQ = "monthly"  # monthly, weekly


def get_historical_prices(symbols: List[str], start: str, end: str) -> Dict[str, List[dict]]:
    """Fetch historical prices for all symbols."""
    print(f"Fetching historical prices from {start} to {end}...")

    prices = {}
    for symbol in symbols:
        try:
            ticker = yf.Ticker(symbol)
            hist = ticker.history(start=start, end=end)
            if len(hist) > 0:
                prices[symbol] = [
                    {
                        "date": str(row.name.date()),
                        "close": row["Close"],
                        "volume": row["Volume"],
                    }
                    for _, row in hist.iterrows()
                ]
                print(f"  {symbol}: {len(prices[symbol])} days")
        except Exception as e:
            print(f"  {symbol}: error - {e}")

    return prices


def calculate_cis_scores_historical(prices: Dict[str, List[dict]], date: str) -> Dict[str, float]:
    """
    Calculate CIS scores for all assets at a given date.
    Uses simplified scoring based on available data.
    """
    scores = {}

    for symbol, price_data in prices.items():
        # Find price at or before the given date
        past_prices = [p for p in price_data if p["date"] <= date]
        if not past_prices:
            continue

        current_price = past_prices[-1]["close"]

        # Get 30d change
        if len(past_prices) > 30:
            price_30d_ago = past_prices[-31]["close"]
            change_30d = ((current_price - price_30d_ago) / price_30d_ago) * 100
        else:
            change_30d = 0

        # Simplified CIS scoring (based on momentum + volatility)
        # This is a simplified version - real backtest would use actual CIS calculation
        base_score = 50

        # Momentum factor (30d change)
        if change_30d > 20:
            base_score += 20
        elif change_30d > 10:
            base_score += 15
        elif change_30d > 0:
            base_score += 10
        elif change_30d > -10:
            base_score -= 5
        else:
            base_score -= 15

        # Volume factor
        recent_volumes = [p["volume"] for p in past_prices[-7:]]
        avg_volume = sum(recent_volumes) / len(recent_volumes) if recent_volumes else 0
        if avg_volume > 10_000_000:  # $10M+ daily volume
            base_score += 15
        elif avg_volume > 1_000_000:
            base_score += 10
        elif avg_volume > 100_000:
            base_score += 5

        # Market cap proxy (price * volume as proxy)
        market_cap_proxy = current_price * avg_volume * 365
        if market_cap_proxy > 10e9:
            base_score += 15
        elif market_cap_proxy > 1e9:
            base_score += 10
        elif market_cap_proxy > 100e6:
            base_score += 5

        scores[symbol] = min(100, max(0, base_score))

    return scores


def get_grade(score: float) -> str:
    """Get letter grade from score."""
    if score >= 85:
        return "A+"
    elif score >= 80:
        return "A"
    elif score >= 70:
        return "B+"
    elif score >= 60:
        return "B"
    elif score >= 50:
        return "C+"
    elif score >= 40:
        return "C"
    else:
        return "D"


def run_backtest():
    """Run the CIS backtest."""
    print("=" * 60)
    print("CIS Backtest Framework")
    print("=" * 60)
    print(f"Period: {BACKTEST_START} to {BACKTEST_END}")
    print(f"Strategy: Buy A+/A grades, Sell C or below")
    print(f"Rebalance: {REBALANCE_FREQ}")
    print()

    # Assets to test
    crypto_assets = ["BTC-USD", "ETH-USD", "SOL-USD", "BNB-USD", "AVAX-USD"]
    equity_assets = ["SPY", "QQQ", "AAPL", "MSFT", "NVDA"]
    bond_assets = ["TLT", "IEF", "HYG"]
    commodity_assets = ["GLD", "SLV", "USO"]

    all_assets = crypto_assets + equity_assets + bond_assets + commodity_assets

    # Fetch historical prices
    prices = get_historical_prices(all_assets, BACKTEST_START, BACKTEST_END)

    if not prices:
        print("No price data fetched. Exiting.")
        return

    print(f"\nFetched data for {len(prices)} assets")
    print()

    # Generate rebalance dates
    start_date = datetime.strptime(BACKTEST_START, "%Y-%m-%d")
    end_date = datetime.strptime(BACKTEST_END, "%Y-%m-%d")

    rebalance_dates = []
    current = start_date
    while current <= end_date:
        rebalance_dates.append(current.strftime("%Y-%m-%d"))
        if REBALANCE_FREQ == "monthly":
            # Next month
            if current.month == 12:
                current = current.replace(year=current.year + 1, month=1)
            else:
                current = current.replace(month=current.month + 1)
        else:  # weekly
            current += timedelta(days=7)

    print(f"Rebalance dates: {len(rebalance_dates)}")
    print()

    # Track portfolio value over time
    portfolio_value = 10000  # Start with $10k
    btc_value = 10000  # BTC benchmark
    btc_price_start = None
    btc_price_end = None

    portfolio_history = []
    btc_history = []

    for i, date in enumerate(rebalance_dates[:-1]):  # Skip last date (no rebalance needed)
        # Calculate CIS scores at this date
        scores = calculate_cis_scores_historical(prices, date)

        # Determine buy/sell signals
        buy_signals = []
        sell_signals = []

        for symbol, score in scores.items():
            grade = get_grade(score)
            if grade in ["A+", "A"]:
                buy_signals.append((symbol, score, grade))
            elif grade in ["C", "D", "F"]:
                sell_signals.append((symbol, score, grade))

        # Get next rebalance date for price lookup
        next_date = rebalance_dates[i + 1]

        # Calculate portfolio performance to next date
        if buy_signals:
            # Simple equal-weight portfolio
            allocation_per_asset = portfolio_value / len(buy_signals)

            for symbol, score, grade in buy_signals:
                if symbol in prices:
                    symbol_prices = prices[symbol]
                    current_price_data = next((p for p in symbol_prices if p["date"] >= date), None)
                    next_price_data = next((p for p in symbol_prices if p["date"] >= next_date), None)

                    if current_price_data and next_price_data:
                        price_change = (next_price_data["close"] - current_price_data["close"]) / current_price_data["close"]
                        allocation_per_asset *= (1 + price_change)

            portfolio_value = allocation_per_asset * len(buy_signals)

        # Track BTC performance
        if "BTC-USD" in prices:
            btc_prices = prices["BTC-USD"]
            btc_current = next((p for p in btc_prices if p["date"] >= date), None)
            btc_next = next((p for p in btc_prices if p["date"] >= next_date), None)

            if btc_current and btc_next:
                btc_change = (btc_next["close"] - btc_current["close"]) / btc_current["close"]
                btc_value *= (1 + btc_change)

                if not btc_price_start:
                    btc_price_start = btc_current["close"]
                btc_price_end = btc_next["close"]

        portfolio_history.append({"date": date, "value": portfolio_value})
        btc_history.append({"date": date, "value": btc_value})

        if i % 2 == 0:
            print(f"{date}:")
            print(f"  CIS Portfolio: ${portfolio_value:,.2f}")
            print(f"  BTC Hold: ${btc_value:,.2f}")
            print(f"  Buy signals: {len(buy_signals)}")
            print()

    # Final results
    print("=" * 60)
    print("BACKTEST RESULTS")
    print("=" * 60)

    total_return = (portfolio_value - 10000) / 10000 * 100
    btc_return = (btc_value - 10000) / 10000 * 100

    print(f"\nInitial Investment: $10,000")
    print(f"\nCIS Strategy:")
    print(f"  Final Value: ${portfolio_value:,.2f}")
    print(f"  Total Return: {total_return:+.2f}%")

    print(f"\nBTC Buy-and-Hold:")
    print(f"  Final Value: ${btc_value:,.2f}")
    print(f"  Total Return: {btc_return:+.2f}%")

    print(f"\nAlpha vs BTC: {total_return - btc_return:+.2f}%")

    # Save results
    results = {
        "config": {
            "start": BACKTEST_START,
            "end": BACKTEST_END,
            "rebalance": REBALANCE_FREQ,
        },
        "cis_strategy": {
            "final_value": portfolio_value,
            "total_return": total_return,
        },
        "btc_hold": {
            "final_value": btc_value,
            "total_return": btc_return,
        },
        "alpha": total_return - btc_return,
        "portfolio_history": portfolio_history,
        "btc_history": btc_history,
    }

    output_path = os.path.join(os.path.dirname(__file__), "backtest_results.json")
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)

    print(f"\nResults saved to: {output_path}")

    return results


if __name__ == "__main__":
    run_backtest()
