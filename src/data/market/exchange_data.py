"""
Market Data Layer - CCXT Integration
Unified interface for CEX data
"""
import ccxt
import pandas as pd
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import time

class ExchangeDataFetcher:
    """
    Fetches market data from multiple exchanges via CCXT
    Supports: Binance, OKX, Coinbase, Kraken
    """
    
    def __init__(self, exchange_id: str = "binance"):
        self.exchange = getattr(ccxt, exchange_id)({
            'enableRateLimit': True,
            'options': {'defaultType': 'spot'}
        })
        self.exchange_id = exchange_id
        
    def get_ohlcv(self, symbol: str, timeframe: str = "1d", 
                  limit: int = 100) -> pd.DataFrame:
        """
        Fetch OHLCV data for a symbol
        
        Args:
            symbol: Trading pair (e.g., "BTC/USDT")
            timeframe: Candle period ("1m", "1h", "1d", etc.)
            limit: Number of candles to fetch
            
        Returns:
            DataFrame with columns: timestamp, open, high, low, close, volume
        """
        try:
            ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
            df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df['symbol'] = symbol
            return df
        except Exception as e:
            print(f"Error fetching {symbol}: {e}")
            return pd.DataFrame()
    
    def get_ticker(self, symbol: str) -> Dict:
        """Get current ticker data"""
        try:
            return self.exchange.fetch_ticker(symbol)
        except Exception as e:
            print(f"Error fetching ticker {symbol}: {e}")
            return {}
    
    def get_multiple_tickers(self, symbols: List[str]) -> pd.DataFrame:
        """
        Fetch tickers for multiple symbols
        Returns DataFrame with current prices and 24h changes
        """
        tickers = []
        for symbol in symbols:
            ticker = self.get_ticker(symbol)
            if ticker:
                tickers.append({
                    'symbol': symbol,
                    'price': ticker.get('last', 0),
                    'change_24h': ticker.get('percentage', 0),
                    'volume_24h': ticker.get('quoteVolume', 0),
                    'high_24h': ticker.get('high', 0),
                    'low_24h': ticker.get('low', 0),
                    'timestamp': datetime.now()
                })
            time.sleep(0.1)  # Rate limiting
        
        return pd.DataFrame(tickers)
    
    def get_orderbook(self, symbol: str, limit: int = 20) -> Dict:
        """Get current orderbook"""
        try:
            return self.exchange.fetch_order_book(symbol, limit)
        except Exception as e:
            print(f"Error fetching orderbook {symbol}: {e}")
            return {}


class MultiExchangeAggregator:
    """
    Aggregates data from multiple exchanges
    Handles arbitrage detection and best execution routing
    """
    
    def __init__(self, exchanges: List[str] = ["binance", "okx"]):
        self.fetchers = {ex: ExchangeDataFetcher(ex) for ex in exchanges}
    
    def get_best_price(self, symbol: str) -> Dict:
        """Find best bid/ask across exchanges"""
        results = {}
        for ex_name, fetcher in self.fetchers.items():
            ticker = fetcher.get_ticker(symbol)
            if ticker:
                results[ex_name] = {
                    'bid': ticker.get('bid', 0),
                    'ask': ticker.get('ask', 0),
                    'spread': ticker.get('ask', 0) - ticker.get('bid', 0)
                }
        
        if not results:
            return {}
        
        best_bid = max(results.items(), key=lambda x: x[1]['bid'])
        best_ask = min(results.items(), key=lambda x: x[1]['ask'])
        
        return {
            'symbol': symbol,
            'best_bid': {'exchange': best_bid[0], 'price': best_bid[1]['bid']},
            'best_ask': {'exchange': best_ask[0], 'price': best_ask[1]['ask']},
            'all_exchanges': results
        }


# Test
if __name__ == "__main__":
    print("\n" + "="*60)
    print("  LOOLOOMI DATA LAYER TEST")
    print("="*60)
    
    # Single exchange test
    fetcher = ExchangeDataFetcher("binance")
    
    print("\n📊 Fetching BTC/USDT OHLCV (last 7 days)...")
    df = fetcher.get_ohlcv("BTC/USDT", "1d", limit=7)
    print(df.to_string(index=False))
    
    print("\n📈 Fetching multiple tickers...")
    symbols = ["BTC/USDT", "ETH/USDT", "SOL/USDT"]
    tickers = fetcher.get_multiple_tickers(symbols)
    print(tickers[['symbol', 'price', 'change_24h', 'volume_24h']].to_string(index=False))
    
    # Multi-exchange test
    print("\n🔄 Multi-exchange price comparison...")
    aggregator = MultiExchangeAggregator(["binance", "okx"])
    best = aggregator.get_best_price("BTC/USDT")
    if best:
        print(f"  Best Bid: {best['best_bid']['exchange']} @ ${best['best_bid']['price']:,.2f}")
        print(f"  Best Ask: {best['best_ask']['exchange']} @ ${best['best_ask']['price']:,.2f}")
    
    print("\n" + "="*60)
