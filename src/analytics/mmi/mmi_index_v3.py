import requests
import time
from datetime import datetime
from typing import Dict

class LooloomiMMI:
    """
    Looloomi Memecoin Momentum Index (MMI) v3
    With rate limiting and better error handling
    """
    
    def __init__(self, token_id: str = "bitcoin"):
        self.token_id = token_id
        self.components = {}
        self.weights = {
            'social': 0.30,
            'onchain': 0.30,
            'sentiment': 0.20,
            'historical': 0.20
        }
        self.api_delay = 1.5  # seconds between API calls
    
    def _api_call(self, url: str, params: dict = None) -> dict:
        """Make API call with delay and error handling"""
        time.sleep(self.api_delay)
        try:
            response = requests.get(url, params=params, timeout=15)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"    API Error: {e}")
            return None
    
    def get_historical_score(self) -> Dict:
        """Historical Score: price & mcap changes"""
        print(f"    Fetching historical data...")
        
        url = f"https://api.coingecko.com/api/v3/coins/{self.token_id}/market_chart"
        
        # 30-day data
        data_30d = self._api_call(url, {'vs_currency': 'usd', 'days': '30'})
        if not data_30d or 'prices' not in data_30d:
            return {'score': 50, 'error': 'No data'}
        
        prices = [p[1] for p in data_30d['prices']]
        mcaps = [m[1] for m in data_30d.get('market_caps', [])]
        
        price_now = prices[-1]
        price_30d_ago = prices[0]
        price_change = ((price_now - price_30d_ago) / price_30d_ago) * 100
        
        mcap_change = 0
        if mcaps:
            mcap_now = mcaps[-1]
            mcap_30d_ago = mcaps[0]
            mcap_change = ((mcap_now - mcap_30d_ago) / mcap_30d_ago) * 100
        
        # Normalize to 0-100
        score = max(0, min(100, 50 + price_change))
        
        return {
            'score': round(score, 1),
            'price_change_30d': round(price_change, 2),
            'mcap_change_30d': round(mcap_change, 2),
            'current_price': round(price_now, 2)
        }
    
    def get_onchain_score(self) -> Dict:
        """On-Chain Score: volume analysis"""
        print(f"    Fetching on-chain data...")
        
        url = f"https://api.coingecko.com/api/v3/coins/{self.token_id}/market_chart"
        data = self._api_call(url, {'vs_currency': 'usd', 'days': '30'})
        
        if not data or 'total_volumes' not in data:
            return {'score': 50, 'error': 'No data'}
        
        volumes = [v[1] for v in data['total_volumes']]
        
        vol_7d = sum(volumes[-7:]) / 7
        vol_30d = sum(volumes) / len(volumes)
        vol_ratio = vol_7d / vol_30d if vol_30d > 0 else 1
        
        score = max(0, min(100, vol_ratio * 50))
        
        return {
            'score': round(score, 1),
            'vol_ratio': round(vol_ratio, 2),
            'vol_7d_avg': round(vol_7d, 0),
            'vol_30d_avg': round(vol_30d, 0)
        }
    
    def get_sentiment_score(self) -> Dict:
        """Sentiment Score: Fear & Greed Index"""
        print(f"    Fetching sentiment data...")
        
        data = self._api_call("https://api.alternative.me/fng/?limit=7")
        
        if not data or 'data' not in data:
            return {'score': 50, 'error': 'No data'}
        
        current = int(data['data'][0]['value'])
        classification = data['data'][0]['value_classification']
        
        values = [int(d['value']) for d in data['data']]
        avg_7d = sum(values) / len(values)
        trend = current - avg_7d
        
        return {
            'score': current,
            'fear_greed': current,
            'classification': classification,
            'trend_7d': round(trend, 1)
        }
    
    def get_social_score(self) -> Dict:
        """Social Score: placeholder until X API available"""
        print(f"    Social data: using neutral placeholder...")
        
        # For now, return neutral score
        # TODO: Implement X API / web scraping
        return {
            'score': 50,
            'note': 'Placeholder - needs X API implementation',
            'twitter': 'N/A',
            'telegram': 'N/A'
        }
    
    def calculate(self) -> float:
        """Calculate composite MMI"""
        
        self.components['historical'] = self.get_historical_score()
        self.components['onchain'] = self.get_onchain_score()
        self.components['sentiment'] = self.get_sentiment_score()
        self.components['social'] = self.get_social_score()
        
        mmi = (
            self.components['social']['score'] * self.weights['social'] +
            self.components['onchain']['score'] * self.weights['onchain'] +
            self.components['sentiment']['score'] * self.weights['sentiment'] +
            self.components['historical']['score'] * self.weights['historical']
        )
        
        return round(mmi, 1)
    
    def get_signal(self, score: float) -> str:
        """Trading signal interpretation"""
        if score >= 75:
            return "🔴 SELL SIGNAL - Market overheated"
        elif score >= 60:
            return "🟡 CAUTION - Greed building"
        elif score >= 40:
            return "⚪ NEUTRAL - No clear signal"
        elif score >= 25:
            return "🟢 ACCUMULATE - Fear present"
        else:
            return "🟢🟢 STRONG BUY - Extreme fear = opportunity"
    
    def report(self) -> Dict:
        """Generate MMI report"""
        
        print(f"\n{'='*60}")
        print(f"  LOOLOOMI MMI — {self.token_id.upper()}")
        print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*60}")
        
        score = self.calculate()
        signal = self.get_signal(score)
        
        print(f"\n  {'━'*56}")
        print(f"  ┃  MMI SCORE: {score:>5}/100                              ┃")
        print(f"  ┃  {signal:<52} ┃")
        print(f"  {'━'*56}")
        
        # Components
        h = self.components['historical']
        o = self.components['onchain']
        s = self.components['sentiment']
        
        print(f"\n  COMPONENTS:")
        print(f"  ├─ Historical (20%): {h['score']:>5}  |  30d: {h.get('price_change_30d', 0):>+7.2f}%")
        print(f"  ├─ On-Chain  (30%): {o['score']:>5}  |  Vol Ratio: {o.get('vol_ratio', 1):>5.2f}x")
        print(f"  ├─ Sentiment (20%): {s['score']:>5}  |  F&G: {s.get('fear_greed', 50)} ({s.get('classification', 'N/A')})")
        print(f"  └─ Social    (30%): {self.components['social']['score']:>5}  |  (placeholder)")
        
        print(f"\n  Price: ${h.get('current_price', 0):,.2f}")
        print(f"{'='*60}\n")
        
        return {'score': score, 'signal': signal, 'components': self.components}


if __name__ == "__main__":
    # Only test Bitcoin to avoid rate limits
    mmi = LooloomiMMI("bitcoin")
    result = mmi.report()
