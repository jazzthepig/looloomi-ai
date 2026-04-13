"""
CIS Backtest Framework v4.0
===========================
Backtest with Binance/OKX historical klines:
- Fetch real market data from Binance API
- Save results to history database

Author: Seth
"""

import json
import asyncio
import httpx
import time
import sys
import os
from datetime import datetime, timedelta
from typing import Dict, List

# Add project root to path (backtest.py is at src/data/cis/backtest.py)
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, project_root)


API_BASE = os.getenv("RAILWAY_URL", "http://localhost:8000").rstrip("/")

# Map CIS symbols to Binance trading pairs
BINANCE_SYMBOLS = {
    "BTC": "BTCUSDT",
    "ETH": "ETHUSDT",
    "SOL": "SOLUSDT",
    "BNB": "BNBUSDT",
    "XRP": "XRPUSDT",
    "ADA": "ADAUSDT",
    "DOGE": "DOGEUSDT",
    "AVAX": "AVAXUSDT",
    "DOT": "DOTUSDT",
    "ARB": "ARBUSDT",
    "MANTLE": "MANTLEUSDT",
    "TON": "TONUSDT",
    "UNI": "UNIUSDT",
    "AAVE": "AAVEUSDT",
    "LINK": "LINKUSDT",
    "ONDO": "ONDOUSDT",
    "PEPE": "PEPEUSDT",
}


async def fetch_price_history(symbol: str, months: int = 6) -> List[dict]:
    """Fetch historical klines from Binance API."""
    from src.data.market.data_layer import get_klines

    binance_pair = BINANCE_SYMBOLS.get(symbol, f"{symbol}USDT")
    klines = await get_klines(binance_pair, source="auto", months=months)

    if klines:
        return [
            {
                "date": k["timestamp"][:10],  # YYYY-MM-DD
                "price": k["close"],
                "open": k["open"],
                "high": k["high"],
                "low": k["low"],
                "volume": k["volume"],
            }
            for k in klines
        ]
    return []


def calculate_return(prices: List[dict], days: int = 30) -> float:
    """Calculate return for last N days from klines."""
    if not prices or len(prices) < days:
        return 0.0
    start = prices[-days]["price"]
    end = prices[-1]["price"]
    if start > 0:
        return (end - start) / start * 100
    return 0.0


async def run_backtest():
    """Run backtest with Binance/OKX klines."""
    print("=" * 60)
    print("CIS Backtest v4.0 - Binance/OKX Data")
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

    # Fetch klines - no rate limits with Binance
    print("\nFetching historical klines from Binance/OKX...")
    price_data = {}
    symbols = [a["symbol"] for a in universe]

    # Process in batches of 10 (Binance is fast)
    batch_size = 10
    for i in range(0, len(symbols), batch_size):
        batch = symbols[i:i + batch_size]
        print(f"\n  Batch {i // batch_size + 1}: {batch}")

        tasks = [fetch_price_history(symbol, 6) for symbol in batch]
        results = await asyncio.gather(*tasks)

        for symbol, prices in zip(batch, results):
            if prices:
                price_data[symbol] = prices
                print(f"    {symbol}: {len(prices)} days")
            else:
                print(f"    {symbol}: FAILED")

        # Small delay between batches
        if i + batch_size < len(symbols):
            await asyncio.sleep(1)

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
        from src.data.cis.history_db import init_db, save_backtest_result

        init_db()

        # Calculate entry/exit dates (30 days ago to today)
        exit_date = datetime.now().strftime("%Y-%m-%d")
        entry_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")

        saved_count = 0
        for asset in universe:
            symbol = asset["symbol"]
            if symbol not in returns:
                continue

            ret = returns[symbol]
            grade_entry = asset["grade"]
            score_entry = asset.get("cis_score", 0)

            # Save each asset's backtest result
            success = save_backtest_result(
                asset=symbol,
                entry_date=entry_date,
                exit_date=exit_date,
                holding_days=30,
                grade_entry=grade_entry,
                grade_exit=grade_entry,  # Assume same grade for now
                score_entry=score_entry,
                score_exit=score_entry,
                return_pct=round(ret, 2),
                btc_return_pct=round(btc_return, 2),
                alpha_vs_btc=round(ret - btc_return, 2),
                data_source="binance"
            )
            if success:
                saved_count += 1

        print(f"  Saved {saved_count} backtest results")
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
