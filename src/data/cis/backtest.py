"""
CIS Backtest Framework v3.1
==========================
Backtest with CoinGecko historical data:
- Fetch 4 assets at a time to avoid rate limits
- Save results to history database

Author: Seth
"""

import json
import asyncio
import httpx
import time
from datetime import datetime, timedelta
from typing import Dict, List


API_BASE = "https://web-production-0cdf76.up.railway.app"
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
    "ARB": "arbitrum",
    "MANTLE": "mantle",
    "TON": "the-open-network",
    "UNI": "uniswap",
    "AAVE": "aave",
    "LINK": "chainlink",
    "ONDO": "ondo-finance",
    "PEPE": "pepe",
}


async def fetch_price_history(cg_id: str, days: int = 60) -> List[dict]:
    """Fetch historical prices from CoinGecko."""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            url = f"https://api.coingecko.com/api/v3/coins/{cg_id}/market_chart"
            params = {"vs_currency": "usd", "days": days}
            r = await client.get(url, params=params)

            if r.status_code == 200:
                data = r.json()
                prices = data.get("prices", [])
                return [
                    {"date": datetime.fromtimestamp(p[0] / 1000).strftime("%Y-%m-%d"), "price": p[1]}
                    for p in prices
                ]
            elif r.status_code == 429:
                print(f"  Rate limited, waiting...")
                await asyncio.sleep(60)
                return []
    except Exception as e:
        print(f"  Error: {e}")
    return []


def calculate_return(prices: List[dict], days: int = 30) -> float:
    """Calculate return for last N days."""
    if not prices or len(prices) < days:
        return 0.0
    start = prices[-days]["price"]
    end = prices[-1]["price"]
    if start > 0:
        return (end - start) / start * 100
    return 0.0


async def run_backtest():
    """Run backtest with batch fetching."""
    print("=" * 60)
    print("CIS Backtest v3.1 - Batch Fetch")
    print("=" * 60)

    # Get CIS scores
    print("\nFetching CIS scores...")
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.get(f"{API_BASE}/api/v1/cis/universe")
        cis_data = r.json()
        universe = cis_data.get("universe", [])

    if not universe:
        print("No CIS data!")
        return

    print(f"Loaded {len(universe)} assets")
    print(f"Grade distribution: ", end="")
    grades = {}
    for a in universe:
        g = a["grade"]
        grades[g] = grades.get(g, 0) + 1
    print(", ".join(f"{k}:{v}" for k, v in sorted(grades.items())))

    # Fetch prices in batches of 4
    print("\nFetching historical prices (4 assets at a time)...")
    price_data = {}
    symbols = [a["symbol"] for a in universe]

    # Process in batches
    batch_size = 4
    for i in range(0, len(symbols), batch_size):
        batch = symbols[i:i + batch_size]
        print(f"\n  Batch {i // batch_size + 1}: {batch}")

        tasks = []
        for symbol in batch:
            cg_id = COINGECKO_IDS.get(symbol, symbol.lower())
            tasks.append(fetch_price_history(cg_id, 60))

        results = await asyncio.gather(*tasks)

        for symbol, prices in zip(batch, results):
            if prices:
                price_data[symbol] = prices
                print(f"    {symbol}: {len(prices)} days")
            else:
                print(f"    {symbol}: FAILED")

        # Rate limit delay between batches
        if i + batch_size < len(symbols):
            print("  Waiting 10s for rate limit...")
            await asyncio.sleep(10)

    # Calculate returns
    print("\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)

    # Group by grade
    grade_a = [a for a in universe if a["grade"] in ["A+", "A"]]
    grade_b = [a for a in universe if a["grade"] in ["B+", "B"]]
    grade_c = [a for a in universe if a["grade"] in ["C+", "C", "D"]]

    # Calculate 30d returns
    returns = {s: calculate_return(price_data.get(s, []), 30) for s in symbols}

    # Average by grade
    a_returns = [returns[s["symbol"]] for s in grade_a if s["symbol"] in returns]
    b_returns = [returns[s["symbol"]] for s in grade_b if s["symbol"] in returns]
    c_returns = [returns[s["symbol"]] for s in grade_c if s["symbol"] in returns]

    avg_a = sum(a_returns) / len(a_returns) if a_returns else 0
    avg_b = sum(b_returns) / len(b_returns) if b_returns else 0
    avg_c = sum(c_returns) / len(c_returns) if c_returns else 0

    btc_return = returns.get("BTC", 0)

    print(f"\n30-Day Returns by Grade:")
    print(f"  A/A+ ({len(a_returns)} assets): {avg_a:+.2f}%")
    print(f"  B/B+ ({len(b_returns)} assets): {avg_b:+.2f}%")
    print(f"  C/D  ({len(c_returns)} assets): {avg_c:+.2f}%")
    print(f"  BTC: {btc_return:+.2f}%")

    print(f"\nAlpha:")
    print(f"  A vs B: {avg_a - avg_b:+.2f}%")
    print(f"  A vs C: {avg_a - avg_c:+.2f}%")
    print(f"  A vs BTC: {avg_a - btc_return:+.2f}%")

    # Individual assets
    print(f"\nIndividual Performance:")
    print(f"{'Symbol':<8} {'Grade':<6} {'Return':>10}")
    print("-" * 30)
    sorted_assets = sorted(universe, key=lambda x: returns.get(x["symbol"], 0), reverse=True)
    for a in sorted_assets:
        ret = returns.get(a["symbol"], 0)
        print(f"{a['symbol']:<8} {a['grade']:<6} {ret:>+9.2f}%")

    # Save to database
    print("\nSaving to database...")
    try:
        from src.data.cis.history_db import init_db
        from src.data.cis.cis_provider import calculate_cis_universe

        # This would save the backtest result
        # For now just print
        print("  (Database save not implemented yet)")
    except Exception as e:
        print(f"  Error: {e}")

    # Save to JSON
    result = {
        "timestamp": datetime.now().isoformat(),
        "assets": len(universe),
        "grades": grades,
        "returns_by_grade": {
            "A": round(avg_a, 2),
            "B": round(avg_b, 2),
            "C": round(avg_c, 2),
        },
        "alpha": {
            "A_vs_B": round(avg_a - avg_b, 2),
            "A_vs_C": round(avg_a - avg_c, 2),
            "A_vs_BTC": round(avg_a - btc_return, 2),
        },
        "individual": {s: round(returns.get(s, 0), 2) for s in symbols},
    }

    output_path = "/Users/sbb/Projects/looloomi-ai/src/data/cis/backtest_results.json"
    with open(output_path, "w") as f:
        json.dump(result, f, indent=2)
    print(f"Results saved to: {output_path}")


if __name__ == "__main__":
    asyncio.run(run_backtest())
