import os
import requests
import time
from datetime import datetime
from typing import Dict

# S-895 阶段 0:闸门外调用的记账(不是闸门)。这个文件用**同步** `requests`
# ⇒ 记账同步落 Redis。见 `src/data/market/cg_guard.py`。
from src.data.market.cg_guard import note_unbudgeted_call, endpoint_label

#: CoinGecko。11-16:有 key 时走 Pro 端点(每分钟 500 次);公开端点每分钟十几次,
#: 而 Pro key 在公开 host 上会被忽略 —— 拿 Analyst 的额度去打公开端点是最亏的用法。
CG_API_KEY = os.getenv("COINGECKO_API_KEY", "")
CG_PRO_BASE = "https://pro-api.coingecko.com/api/v3"
CG_PUBLIC_BASE = "https://api.coingecko.com/api/v3"


def _cg_base() -> str:
    return CG_PRO_BASE if CG_API_KEY else CG_PUBLIC_BASE


def _cg_headers() -> dict:
    return {"x-cg-pro-api-key": CG_API_KEY} if CG_API_KEY else {}


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
        #: 11-16:historical 与 onchain 两个分项要的是**同一份** `/market_chart`。
        #: 原来两个方法各取一次(同一个 URL、同一个参数)—— 一次 calculate() = 两次调用 + 3 秒空等。
        #: 现在取一次、两个分项共用。
        self._mc_cache: dict | None = None

    def _api_call(self, url: str, params: dict = None) -> dict:
        """Make API call with delay and error handling"""
        time.sleep(self.api_delay)
        try:
            # ⚠️ S-895 阶段 0:闸门外记账。这里是**同步** `requests`(批处理脚本),
            # 没有事件循环 ⇒ 记账同步落 Redis。这两个同步 `requests` 点是登记
            # 在册的例外(阶段 2 的形状守卫白名单),不是「忘了收口」。
            note_unbudgeted_call("coingecko", endpoint_label(url))
            response = requests.get(url, params=params, headers=_cg_headers(), timeout=15)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"    API Error: {e}")
            return None

    def _market_chart(self) -> dict:
        """30 天的 `/market_chart` —— 一轮里只取一次,historical 与 onchain 共用。"""
        if self._mc_cache is not None:
            return self._mc_cache
        url = f"{_cg_base()}/coins/{self.token_id}/market_chart"
        self._mc_cache = self._api_call(url, {'vs_currency': 'usd', 'days': '30'}) or {}
        return self._mc_cache

    def get_historical_score(self) -> Dict:
        """Historical Score: price & mcap changes"""
        print(f"    Fetching historical data...")

        # 30-day data(与 onchain 共用同一份 —— 见 _market_chart)
        data_30d = self._market_chart()
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

        data = self._market_chart()

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
        """Social Score: X/Twitter API not configured — returns neutral with available: False"""
        return {
            'score': 50,        # Neutral — does not influence composite until real data
            'available': False,
            'note': 'Social data unavailable — X API not configured',
            'twitter': None,
            'telegram': None,
        }
    
    def calculate(self) -> float:
        """Calculate composite MMI"""

        # 每轮重新取一次 market_chart(两个分项共用这一份)—— 不要把上一轮的数据带进来。
        self._mc_cache = None
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
        """Trading signal interpretation (positioning language only per compliance)"""
        if score >= 75:
            return "🔴 MARKET OVERHEATED - Consider risk reduction positioning"
        elif score >= 60:
            return "🟡 GREED BUILDING - Caution advised for new entries"
        elif score >= 40:
            return "⚪ NEUTRAL REGIME - No clear directional bias"
        elif score >= 25:
            return "🟢 FEAR PRESENT - Market positioned favorably"
        else:
            return "🟢🟢 EXTREME FEAR - Exceptional opportunity positioning"
    
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
