"""
CIS Backtest Framework v3
=========================
Backtest CIS rating strategy:
- Uses current CIS scores from API
- Simulates trading based on grades
- Shows Alpha (A grade vs C grade) performance

Author: Seth
"""

import json
import asyncio
import httpx
from datetime import datetime, timedelta
from typing import Dict, List, Any


# Test configuration
API_BASE = "https://web-production-0cdf76.up.railway.app"
DAYS_LOOKBACK = 60


async def fetch_price_series(coin_id: str, days: int = 60) -> List[dict]:
    """Fetch price history from CoinGecko."""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            url = f"https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart"
            params = {"vs_currency": "usd", "days": days}
            r = await client.get(url, params=params)

            if r.status_code == 200:
                data = r.json()
                prices = data.get("prices", [])
                return [
                    {
                        "date": datetime.fromtimestamp(p[0] / 1000).strftime("%Y-%m-%d"),
                        "price": p[1]
                    }
                    for p in prices
                ]
    except Exception as e:
        pass
    return []


async def run_backtest():
    """Run the CIS backtest."""
    print("=" * 70)
    print("CIS Backtest Framework v3")
    print("=" * 70)
    print(f"Period: Last {DAYS_LOOKBACK} days")
    print(f"Strategy: Buy A/A+ (STRONG OVERWEIGHT), Sell C or below (UNDERWEIGHT)")
    print(f"API: {API_BASE}")
    print()

    # Get CIS data from API
    print("Fetching CIS scores from API...")
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(f"{API_BASE}/api/v1/cis/universe")
            cis_data = r.json()
            universe = cis_data.get("universe", [])
    except Exception as e:
        print(f"Error fetching CIS: {e}")
        return

    if not universe:
        print("No CIS data. Exiting.")
        return

    print(f"Loaded {len(universe)} assets")
    print()

    # Map symbols to CoinGecko IDs
    COINGECKO_IDS = {
        "BTC": "bitcoin",
        "ETH": "ethereum",
        "SOL": "solana",
        "BNB": "binancecoin",
        "XRP": "ripple",
        "ADA": "cardano",
        "DOGE": "dogecoin",
        "AVAX": "avalanche-2",
        "DOT": "polkadot",
        "TON": "the-open-network",
        "ARB": "arbitrum",
        "MANTLE": "mantle",
        "UNI": "uniswap",
        "AAVE": "aave",
        "LINK": "chainlink",
        "ONDO": "ondo-finance",
        "PEPE": "pepe",
    }

    # Fetch prices for all assets
    print("Fetching historical prices...")
    price_data = {}
    for asset in universe:
        symbol = asset["symbol"]
        cg_id = COINGECKO_IDS.get(symbol, symbol.lower())
        prices = await fetch_price_series(cg_id, DAYS_LOOKBACK)
        if prices:
            price_data[symbol] = prices
            print(f"  {symbol}: {len(prices)} days")
        await asyncio.sleep(1.2)  # Rate limit

    print()

    if not price_data:
        print("No price data. Exiting.")
        return

    # Calculate returns for each grade
    grade_a = [a for a in universe if a["grade"] in ["A+", "A"]]
    grade_b = [a for a in universe if a["grade"] in ["B+", "B"]]
    grade_c = [a for a in universe if a["grade"] in ["C+", "C", "D"]]

    print(f"Grade Distribution:")
    print(f"  A/A+: {len(grade_a)} assets")
    print(f"  B/B+: {len(grade_b)} assets")
    print(f"  C/D: {len(grade_c)} assets")
    print()

    # Calculate period returns
    def calc_period_return(prices: list, days: int = 30) -> float:
        if not prices or len(prices) < days:
            return 0
        start_price = prices[-days]["price"]
        end_price = prices[-1]["price"]
        if start_price > 0:
            return (end_price - start_price) / start_price * 100
        return 0

    # 30-day returns
    returns_30d = {}
    for symbol, prices in price_data.items():
        returns_30d[symbol] = calc_period_return(prices, 30)

    # 7-day returns
    returns_7d = {}
    for symbol, prices in price_data.items():
        returns_7d[symbol] = calc_period_return(prices, 7)

    # Calculate average returns by grade
    a_returns = [returns_30d[s["symbol"]] for s in grade_a if s["symbol"] in returns_30d]
    b_returns = [returns_30d[s["symbol"]] for s in grade_b if s["symbol"] in returns_30d]
    c_returns = [returns_30d[s["symbol"]] for s in grade_c if s["symbol"] in returns_30d]

    avg_a = sum(a_returns) / len(a_returns) if a_returns else 0
    avg_b = sum(b_returns) / len(b_returns) if b_returns else 0
    avg_c = sum(c_returns) / len(c_returns) if c_returns else 0

    btc_return = returns_30d.get("BTC", 0)

    # Results
    print("=" * 70)
    print("BACKTEST RESULTS")
    print("=" * 70)
    print()
    print("30-Day Average Returns by Grade:")
    print(f"  A/A+ ({len(a_returns)} assets): {avg_a:+.2f}%")
    print(f"  B/B+ ({len(b_returns)} assets): {avg_b:+.2f}%")
    print(f"  C/D ({len(c_returns)} assets): {avg_c:+.2f}%")
    print(f"  BTC benchmark:              {btc_return:+.2f}%")
    print()
    print("Alpha (Outperformance):")
    print(f"  A vs B:   {avg_a - avg_b:+.2f}%")
    print(f"  A vs C:   {avg_a - avg_c:+.2f}%")
    print(f"  A vs BTC: {avg_a - btc_return:+.2f}%")
    print()

    # Individual asset performance
    print("=" * 70)
    print("ASSET PERFORMANCE")
    print("=" * 70)
    print()
    print(f"{'Symbol':<8} {'Grade':<6} {'CIS':>5} {'30d':>8} {'7d':>8}  {'Signal'}")
    print("-" * 55)

    # Sort by CIS score
    sorted_assets = sorted(universe, key=lambda x: x.get("cis_score", 0), reverse=True)

    for a in sorted_assets:
        symbol = a["symbol"]
        grade = a["grade"]
        cis = a.get("cis_score", 0)
        ret_30d = returns_30d.get(symbol, 0)
        ret_7d = returns_7d.get(symbol, 0)
        signal = a.get("signal", "N/A")
        print(f"{symbol:<8} {grade:<6} {cis:>5.1f} {ret_30d:>+7.1f}% {ret_7d:>+7.1f}%  {signal}")

    # Save results
    results = {
        "config": {
            "period_days": DAYS_LOOKBACK,
            "lookback_30d": "30 days",
            "lookback_7d": "7 days",
            "strategy": "Buy A/A+ (STRONG OVERWEIGHT), Sell C or below (UNDERWEIGHT)",
            "assets": len(universe),
            "api": API_BASE,
        },
        "grade_distribution": {
            "A": len(grade_a),
            "B": len(grade_b),
            "C": len(grade_c),
        },
        "returns_30d_by_grade": {
            "A": round(avg_a, 2),
            "B": round(avg_b, 2),
            "C": round(avg_c, 2),
        },
        "alpha": {
            "A_vs_B": round(avg_a - avg_b, 2),
            "A_vs_C": round(avg_a - avg_c, 2),
            "A_vs_BTC": round(avg_a - btc_return, 2),
        },
        "individual": {
            s["symbol"]: {
                "grade": s["grade"],
                "cis_score": s.get("cis_score", 0),
                "signal": s.get("signal", "N/A"),
                "return_30d": round(returns_30d.get(s["symbol"], 0), 2),
                "return_7d": round(returns_7d.get(s["symbol"], 0), 2),
            }
            for s in sorted_assets
        },
    }

    output_path = "/Users/sbb/Projects/looloomi-ai/src/data/cis/backtest_results.json"
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)

    print()
    print(f"Results saved to: {output_path}")


if __name__ == "__main__":
    asyncio.run(run_backtest())
