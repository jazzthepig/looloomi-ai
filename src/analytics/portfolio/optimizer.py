"""
Portfolio Optimization Layer
Using skfolio for institutional-grade allocation
"""
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, List, Optional

# CCXT for data
import ccxt

# Portfolio optimization
from skfolio.optimization import MeanRisk, HierarchicalRiskParity
from skfolio.measures import RiskMeasure
from skfolio.optimization.convex import ObjectiveFunction

import warnings
warnings.filterwarnings('ignore')


class CryptoPortfolioOptimizer:
    """
    Institutional-grade portfolio optimization for crypto assets
    """
    
    def __init__(self, assets: List[str] = None):
        self.assets = assets or ["BTC", "ETH", "SOL", "BNB", "AVAX"]
        self.exchange = ccxt.binance({'enableRateLimit': True})
        self.returns_data = None
        
    def fetch_historical_data(self, days: int = 90) -> pd.DataFrame:
        """Fetch historical price data for all assets"""
        print(f"  Fetching {days} days of data for {len(self.assets)} assets...")
        
        all_data = {}
        for asset in self.assets:
            symbol = f"{asset}/USDT"
            try:
                ohlcv = self.exchange.fetch_ohlcv(symbol, '1d', limit=days)
                df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
                df.set_index('timestamp', inplace=True)
                all_data[asset] = df['close']
            except Exception as e:
                print(f"    Warning: Could not fetch {symbol}: {e}")
        
        prices = pd.DataFrame(all_data)
        self.returns_data = prices.pct_change().dropna()
        return prices
    
    def _calc_metrics(self, weights_arr: np.ndarray) -> Dict:
        """Calculate portfolio metrics from weights"""
        portfolio_return = np.sum(self.returns_data.mean() * weights_arr) * 365
        portfolio_vol = np.sqrt(np.dot(weights_arr.T, np.dot(self.returns_data.cov() * 365, weights_arr)))
        sharpe = portfolio_return / portfolio_vol if portfolio_vol > 0 else 0
        return {
            "expected_annual_return": round(portfolio_return * 100, 2),
            "annual_volatility": round(portfolio_vol * 100, 2),
            "sharpe_ratio": round(sharpe, 2)
        }
    
    def optimize_mean_variance(self) -> Dict:
        """Mean-Variance Optimization - Maximize Sharpe Ratio"""
        if self.returns_data is None:
            self.fetch_historical_data()
        
        print("  Running Mean-Variance optimization...")
        
        try:
            model = MeanRisk(
                risk_measure=RiskMeasure.VARIANCE,
                objective_function=ObjectiveFunction.MAXIMIZE_RATIO,
            )
            model.fit(self.returns_data)
            weights = dict(zip(self.assets, model.weights_))
            metrics = self._calc_metrics(model.weights_)
        except Exception as e:
            print(f"    MeanRisk failed: {e}, using minimum variance fallback")
            # Fallback to minimum variance
            model = MeanRisk(
                risk_measure=RiskMeasure.VARIANCE,
                objective_function=ObjectiveFunction.MINIMIZE_RISK,
            )
            model.fit(self.returns_data)
            weights = dict(zip(self.assets, model.weights_))
            metrics = self._calc_metrics(model.weights_)
        
        return {
            "method": "Mean-Variance",
            "weights": weights,
            **metrics
        }
    
    def optimize_hrp(self) -> Dict:
        """Hierarchical Risk Parity - robust to estimation error"""
        if self.returns_data is None:
            self.fetch_historical_data()
        
        print("  Running Hierarchical Risk Parity...")
        
        model = HierarchicalRiskParity(
            risk_measure=RiskMeasure.VARIANCE,
        )
        model.fit(self.returns_data)
        weights = dict(zip(self.assets, model.weights_))
        metrics = self._calc_metrics(model.weights_)
        
        return {
            "method": "Hierarchical Risk Parity",
            "weights": weights,
            **metrics
        }
    
    def optimize_min_variance(self) -> Dict:
        """Minimum Variance Portfolio"""
        if self.returns_data is None:
            self.fetch_historical_data()
        
        print("  Running Minimum Variance optimization...")
        
        model = MeanRisk(
            risk_measure=RiskMeasure.VARIANCE,
            objective_function=ObjectiveFunction.MINIMIZE_RISK,
        )
        model.fit(self.returns_data)
        weights = dict(zip(self.assets, model.weights_))
        metrics = self._calc_metrics(model.weights_)
        
        return {
            "method": "Minimum Variance",
            "weights": weights,
            **metrics
        }
    
    def optimize_equal_weight(self) -> Dict:
        """Simple equal-weight benchmark"""
        if self.returns_data is None:
            self.fetch_historical_data()
        
        n = len(self.assets)
        weights = {asset: 1/n for asset in self.assets}
        weights_arr = np.array([1/n] * n)
        metrics = self._calc_metrics(weights_arr)
        
        return {
            "method": "Equal Weight",
            "weights": weights,
            **metrics
        }
    
    def compare_strategies(self) -> pd.DataFrame:
        """Compare all optimization strategies"""
        strategies = [
            self.optimize_equal_weight(),
            self.optimize_hrp(),
            self.optimize_min_variance(),
        ]
        
        comparison = []
        for s in strategies:
            row = {
                "Strategy": s["method"],
                "Return (%)": s["expected_annual_return"],
                "Vol (%)": s["annual_volatility"],
                "Sharpe": s["sharpe_ratio"]
            }
            for asset, weight in s["weights"].items():
                row[asset] = f"{weight*100:.1f}%"
            comparison.append(row)
        
        return pd.DataFrame(comparison)
    
    def generate_report(self) -> None:
        """Generate a full portfolio optimization report"""
        print("\n" + "="*70)
        print("       LOOLOOMI PORTFOLIO OPTIMIZATION REPORT")
        print("="*70)
        print(f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"  Assets: {', '.join(self.assets)}")
        print("="*70)
        
        # Fetch data
        prices = self.fetch_historical_data(days=90)
        
        print(f"\n  Data period: {prices.index[0].date()} to {prices.index[-1].date()}")
        print(f"  Trading days: {len(prices)}")
        
        # Asset statistics
        print("\n" + "-"*70)
        print("  ASSET STATISTICS (90 days)")
        print("-"*70)
        
        stats = []
        for asset in self.assets:
            returns = self.returns_data[asset]
            stats.append({
                "Asset": asset,
                "Return": f"{returns.sum()*100:.1f}%",
                "Vol": f"{returns.std()*np.sqrt(365)*100:.1f}%",
                "Sharpe": f"{(returns.mean()*365)/(returns.std()*np.sqrt(365)):.2f}",
                "MaxDD": f"{(prices[asset]/prices[asset].cummax()-1).min()*100:.1f}%"
            })
        
        stats_df = pd.DataFrame(stats)
        print(stats_df.to_string(index=False))
        
        # Strategy comparison
        print("\n" + "-"*70)
        print("  STRATEGY COMPARISON")
        print("-"*70)
        
        comparison = self.compare_strategies()
        print(comparison.to_string(index=False))
        
        # Recommended allocation
        hrp = self.optimize_hrp()
        print("\n" + "-"*70)
        print("  RECOMMENDED ALLOCATION (HRP)")
        print("-"*70)
        print("  HRP is recommended for crypto due to robustness in regime changes.\n")
        
        for asset, weight in sorted(hrp["weights"].items(), key=lambda x: -x[1]):
            bar = "█" * int(weight * 50)
            print(f"  {asset:6} {weight*100:5.1f}% {bar}")
        
        print("\n" + "="*70)


if __name__ == "__main__":
    optimizer = CryptoPortfolioOptimizer(
        assets=["BTC", "ETH", "SOL", "BNB", "AVAX"]
    )
    optimizer.generate_report()
