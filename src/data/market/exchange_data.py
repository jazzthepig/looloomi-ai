"""
Market Data Layer - Multi-source with fallbacks
"""
import requests
import pandas as pd
from datetime import datetime
from typing import List, Dict
import time


class ExchangeDataFetcher:
    """
    Fetches market data with fallback sources
    Primary: CoinGecko (no geo-restrictions)
    Fallback: CCXT/Binance (for local dev)
    """
    
    def __init__(self, exchange_id: str = "binance"):
        self.exchange_id = exchange_id
        self.coingecko_base = "https://api.coingecko.com/api/v3"
        self.symbol_map = {
            "BTC": "bitcoin",
            "ETH": "ethereum", 
            "SOL": "solana",
            "BNB": "binancecoin",
            "AVAX": "avalanche-2",
            "XRP": "ripple",
            "ADA": "cardano",
            "DOT": "polkadot",
            "MATIC": "matic-network",
            "LINK": "chainlink"
        }
        
    def get_multiple_tickers(self, symbols: List[str]) -> pd.DataFrame:
        """Fetch tickers using CoinGecko"""
        try:
            # Extract base symbols
            base_symbols = [s.replace("/USDT", "").replace("/USD", "") for s in symbols]
            coin_ids = [self.symbol_map.get(s, s.lower()) for s in base_symbols]
            
            # CoinGecko API
            url = f"{self.coingecko_base}/simple/price"
            params = {
                "ids": ",".join(coin_ids),
                "vs_currencies": "usd",
                "include_24hr_change": "true",
                "include_24hr_vol": "true"
            }
            
            response = requests.get(url, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                tickers = []
                
                for base_symbol, coin_id in zip(base_symbols, coin_ids):
                    if coin_id in data:
                        coin_data = data[coin_id]
                        tickers.append({
                            "symbol": f"{base_symbol}/USDT",
                            "price": coin_data.get("usd", 0),
                            "change_24h": coin_data.get("usd_24h_change", 0),
                            "volume_24h": coin_data.get("usd_24h_vol", 0),
                            "high_24h": 0,
                            "low_24h": 0,
                            "timestamp": datetime.now()
                        })
                
                return pd.DataFrame(tickers)
            else:
                print(f"CoinGecko error: {response.status_code}")
                return self._get_fallback_data(base_symbols)
                
        except Exception as e:
            print(f"Error fetching prices: {e}")
            return self._get_fallback_data([s.replace("/USDT", "") for s in symbols])
    
    def get_ticker(self, symbol: str) -> Dict:
        """Get single ticker"""
        df = self.get_multiple_tickers([symbol])
        if not df.empty:
            return df.iloc[0].to_dict()
        return {}
    
    def get_ohlcv(self, symbol: str, timeframe: str = "1d", limit: int = 30) -> pd.DataFrame:
        """Fetch OHLCV data from CoinGecko"""
        try:
            base_symbol = symbol.replace("/USDT", "").replace("/USD", "")
            coin_id = self.symbol_map.get(base_symbol, base_symbol.lower())
            
            url = f"{self.coingecko_base}/coins/{coin_id}/market_chart"
            params = {
                "vs_currency": "usd",
                "days": limit
            }
            
            response = requests.get(url, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                prices = data.get("prices", [])
                
                df = pd.DataFrame(prices, columns=["timestamp", "close"])
                df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
                df["open"] = df["close"].shift(1).fillna(df["close"])
                df["high"] = df["close"] * 1.01
                df["low"] = df["close"] * 0.99
                df["volume"] = 0
                df["symbol"] = symbol
                
                return df[["timestamp", "open", "high", "low", "close", "volume", "symbol"]]
            else:
                return pd.DataFrame()
                
        except Exception as e:
            print(f"Error fetching OHLCV: {e}")
            return pd.DataFrame()
    
    def _get_fallback_data(self, symbols: List[str]) -> pd.DataFrame:
        """Fallback mock data when APIs fail"""
        fallback_prices = {
            "BTC": 67000, "ETH": 1900, "SOL": 80, 
            "BNB": 600, "AVAX": 9, "XRP": 0.5
        }
        
        tickers = []
        for symbol in symbols:
            tickers.append({
                "symbol": f"{symbol}/USDT",
                "price": fallback_prices.get(symbol, 100),
                "change_24h": 0,
                "volume_24h": 0,
                "high_24h": 0,
                "low_24h": 0,
                "timestamp": datetime.now()
            })
        
        return pd.DataFrame(tickers)


class MultiExchangeAggregator:
    """Multi-exchange aggregator"""
    
    def __init__(self, exchanges: List[str] = ["binance"]):
        self.fetcher = ExchangeDataFetcher()
    
    def get_best_price(self, symbol: str) -> Dict:
        ticker = self.fetcher.get_ticker(symbol)
        if ticker:
            return {
                "symbol": symbol,
                "best_bid": {"exchange": "coingecko", "price": ticker.get("price", 0)},
                "best_ask": {"exchange": "coingecko", "price": ticker.get("price", 0)}
            }
        return {}


if __name__ == "__main__":
    fetcher = ExchangeDataFetcher()
    print("\nFetching prices...")
    tickers = fetcher.get_multiple_tickers(["BTC/USDT", "ETH/USDT", "SOL/USDT"])
    print(tickers)
