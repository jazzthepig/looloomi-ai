import requests
from datetime import datetime
from typing import Dict, Optional

class LooloomiMMI:
    """
    Looloomi Memecoin Momentum Index (MMI)
    
    Formula: MMI = 0.3×Social + 0.3×OnChain + 0.2×Sentiment + 0.2×Historical
    
    v1 Implementation: Uses free data sources
    - Social: Placeholder (needs X API)
    - On-Chain: DeFiLlama + CoinGecko volume
    - Sentiment: Fear & Greed Index as proxy
    - Historical: CoinGecko price/mcap data
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
    
    # ========== HISTORICAL SCORE (20%) ==========
    def get_historical_score(self) -> Dict:
        """
        Historical Score components:
        - 30-day price change (normalized)
        - 90-day market cap growth
        """
        try:
            # Get market data
            url = f"https://api.coingecko.com/api/v3/coins/{self.token_id}/market_chart"
            
            # 30-day price data
            params_30d = {'vs_currency': 'usd', 'days': '30'}
            response = requests.get(url, params=params_30d, timeout=15)
            data_30d = response.json()
            
            prices_30d = [p[1] for p in data_30d['prices']]
            price_now = prices_30d[-1]
            price_30d_ago = prices_30d[0]
            price_change_30d = ((price_now - price_30d_ago) / price_30d_ago) * 100
            
            mcaps_30d = [m[1] for m in data_30d['market_caps']]
            mcap_now = mcaps_30d[-1]
            mcap_30d_ago = mcaps_30d[0]
            mcap_change_30d = ((mcap_now - mcap_30d_ago) / mcap_30d_ago) * 100
            
            # 90-day market cap growth
            params_90d = {'vs_currency': 'usd', 'days': '90'}
            response = requests.get(url, params=params_90d, timeout=15)
            data_90d = response.json()
            
            mcaps_90d = [m[1] for m in data_90d['market_caps']]
            mcap_90d_ago = mcaps_90d[0]
            mcap_change_90d = ((mcap_now - mcap_90d_ago) / mcap_90d_ago) * 100
            
            # Normalize to 0-100 (assuming ±50% range maps to 0-100)
            price_score = max(0, min(100, 50 + price_change_30d))
            mcap_30d_score = max(0, min(100, 50 + mcap_change_30d))
            mcap_90d_score = max(0, min(100, 50 + (mcap_change_90d / 2)))
            
            # Weighted historical score
            historical_score = (price_score * 0.4 + mcap_30d_score * 0.3 + mcap_90d_score * 0.3)
            
            return {
                'score': round(historical_score, 1),
                'price_change_30d': round(price_change_30d, 2),
                'mcap_change_30d': round(mcap_change_30d, 2),
                'mcap_change_90d': round(mcap_change_90d, 2),
                'current_price': round(price_now, 2),
                'current_mcap': mcap_now
            }
            
        except Exception as e:
            print(f"Error in historical score: {e}")
            return {'score': 50, 'price_change_30d': 0, 'mcap_change_30d': 0, 'mcap_change_90d': 0}
    
    # ========== ON-CHAIN SCORE (30%) ==========
    def get_onchain_score(self) -> Dict:
        """
        On-Chain Score components:
        - Trading volume vs average
        - Volume trend (recent vs monthly)
        """
        try:
            url = f"https://api.coingecko.com/api/v3/coins/{self.token_id}/market_chart"
            params = {'vs_currency': 'usd', 'days': '30'}
            response = requests.get(url, params=params, timeout=15)
            data = response.json()
            
            volumes = [v[1] for v in data['total_volumes']]
            
            # Recent 7-day average vs 30-day average
            vol_7d_avg = sum(volumes[-7:]) / 7
            vol_30d_avg = sum(volumes) / len(volumes)
            vol_ratio = vol_7d_avg / vol_30d_avg if vol_30d_avg > 0 else 1
            
            # Today's volume vs 7-day average
            vol_today = volumes[-1]
            vol_today_ratio = vol_today / vol_7d_avg if vol_7d_avg > 0 else 1
            
            # Normalize: ratio of 1 = 50, ratio of 2 = 100, ratio of 0.5 = 25
            volume_score = max(0, min(100, vol_ratio * 50))
            spike_score = max(0, min(100, vol_today_ratio * 50))
            
            onchain_score = volume_score * 0.6 + spike_score * 0.4
            
            return {
                'score': round(onchain_score, 1),
                'vol_7d_avg': vol_7d_avg,
                'vol_30d_avg': vol_30d_avg,
                'vol_ratio': round(vol_ratio, 2),
                'vol_today': vol_today,
                'vol_today_ratio': round(vol_today_ratio, 2)
            }
            
        except Exception as e:
            print(f"Error in on-chain score: {e}")
            return {'score': 50, 'vol_ratio': 1, 'vol_today_ratio': 1}
    
    # ========== SENTIMENT SCORE (20%) ==========
    def get_sentiment_score(self) -> Dict:
        """
        Sentiment Score:
        - Fear & Greed Index (proxy for market sentiment)
        - TODO: Add NLP sentiment from social media
        """
        try:
            url = "https://api.alternative.me/fng/?limit=7"
            response = requests.get(url, timeout=10)
            data = response.json()
            
            # Current value
            current_fg = int(data['data'][0]['value'])
            classification = data['data'][0]['value_classification']
            
            # 7-day average
            fg_values = [int(d['value']) for d in data['data']]
            fg_7d_avg = sum(fg_values) / len(fg_values)
            
            # Trend: is sentiment improving?
            fg_trend = current_fg - fg_7d_avg
            
            # Score is the Fear & Greed value itself (already 0-100)
            sentiment_score = current_fg
            
            return {
                'score': round(sentiment_score, 1),
                'fear_greed': current_fg,
                'classification': classification,
                'fg_7d_avg': round(fg_7d_avg, 1),
                'fg_trend': round(fg_trend, 1)
            }
            
        except Exception as e:
            print(f"Error in sentiment score: {e}")
            return {'score': 50, 'fear_greed': 50, 'classification': 'Neutral'}
    
    # ========== SOCIAL SCORE (30%) ==========
    def get_social_score(self) -> Dict:
        """
        Social Media Score:
        - TODO: Requires X API or web scraping
        - For now: placeholder using CoinGecko community data
        """
        try:
            url = f"https://api.coingecko.com/api/v3/coins/{self.token_id}"
            response = requests.get(url, timeout=15)
            data = response.json()
            
            # Get available social metrics from CoinGecko
            community = data.get('community_data', {})
            twitter_followers = community.get('twitter_followers', 0) or 0
            reddit_subscribers = community.get('reddit_subscribers', 0) or 0
            
            # Normalize (BTC has ~6M twitter followers as reference)
            twitter_score = min(100, (twitter_followers / 6000000) * 100)
            reddit_score = min(100, (reddit_subscribers / 5000000) * 100)
            
            # Placeholder score
            social_score = (twitter_score * 0.6 + reddit_score * 0.4)
            
            return {
                'score': round(social_score, 1),
                'twitter_followers': twitter_followers,
                'reddit_subscribers': reddit_subscribers,
                'note': 'Limited data - needs X API for full implementation'
            }
            
        except Exception as e:
            print(f"Error in social score: {e}")
            return {'score': 50, 'note': 'Error fetching social data'}
    
    # ========== CALCULATE MMI ==========
    def calculate(self) -> float:
        """Calculate the composite MMI score"""
        
        # Fetch all components
        self.components['historical'] = self.get_historical_score()
        self.components['onchain'] = self.get_onchain_score()
        self.components['sentiment'] = self.get_sentiment_score()
        self.components['social'] = self.get_social_score()
        
        # Weighted sum
        mmi = (
            self.components['social']['score'] * self.weights['social'] +
            self.components['onchain']['score'] * self.weights['onchain'] +
            self.components['sentiment']['score'] * self.weights['sentiment'] +
            self.components['historical']['score'] * self.weights['historical']
        )
        
        return round(mmi, 1)
    
    def get_classification(self, score: float) -> str:
        """MMI classification bands"""
        if score >= 80:
            return "Extreme Greed 🚀"
        elif score >= 65:
            return "Greed 📈"
        elif score >= 50:
            return "Neutral-Bullish 😊"
        elif score >= 35:
            return "Neutral-Bearish 😐"
        elif score >= 20:
            return "Fear 📉"
        else:
            return "Extreme Fear 😱"
    
    def report(self) -> Dict:
        """Generate comprehensive MMI report"""
        score = self.calculate()
        classification = self.get_classification(score)
        
        print("\n" + "="*60)
        print("         LOOLOOMI MEMECOIN MOMENTUM INDEX (MMI)")
        print("="*60)
        print(f"  Token: {self.token_id.upper()}")
        print(f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("="*60)
        
        print(f"\n  >>> MMI SCORE: {score}/100 — {classification} <<<\n")
        
        print("-"*60)
        print("  COMPONENT BREAKDOWN:")
        print("-"*60)
        
        # Social (30%)
        soc = self.components['social']
        print(f"\n  📱 SOCIAL MEDIA (30% weight): {soc['score']}/100")
        print(f"     Twitter Followers: {soc.get('twitter_followers', 'N/A'):,}")
        print(f"     Reddit Subscribers: {soc.get('reddit_subscribers', 'N/A'):,}")
        print(f"     ⚠️  {soc.get('note', '')}")
        
        # On-Chain (30%)
        oc = self.components['onchain']
        print(f"\n  ⛓️  ON-CHAIN (30% weight): {oc['score']}/100")
        print(f"     7d/30d Volume Ratio: {oc.get('vol_ratio', 'N/A')}x")
        print(f"     Today vs 7d Avg: {oc.get('vol_today_ratio', 'N/A')}x")
        
        # Sentiment (20%)
        sent = self.components['sentiment']
        print(f"\n  🧠 SENTIMENT (20% weight): {sent['score']}/100")
        print(f"     Fear & Greed Index: {sent.get('fear_greed', 'N/A')} ({sent.get('classification', 'N/A')})")
        print(f"     7-day Trend: {sent.get('fg_trend', 0):+.1f}")
        
        # Historical (20%)
        hist = self.components['historical']
        print(f"\n  📊 HISTORICAL (20% weight): {hist['score']}/100")
        print(f"     30d Price Change: {hist.get('price_change_30d', 0):+.2f}%")
        print(f"     30d MCap Change: {hist.get('mcap_change_30d', 0):+.2f}%")
        print(f"     90d MCap Change: {hist.get('mcap_change_90d', 0):+.2f}%")
        print(f"     Current Price: ${hist.get('current_price', 0):,.2f}")
        
        print("\n" + "="*60)
        print("  Formula: MMI = 0.3×Social + 0.3×OnChain + 0.2×Sentiment + 0.2×Historical")
        print("="*60 + "\n")
        
        return {
            'score': score,
            'classification': classification,
            'components': self.components,
            'timestamp': datetime.now().isoformat()
        }


if __name__ == "__main__":
    # Test with Bitcoin
    print("\n🔍 Calculating MMI for Bitcoin...")
    mmi = LooloomiMMI("bitcoin")
    result = mmi.report()
    
    # Test with Ethereum
    print("\n🔍 Calculating MMI for Ethereum...")
    mmi_eth = LooloomiMMI("ethereum")
    result_eth = mmi_eth.report()
    
    # Test with a memecoin (Dogecoin)
    print("\n🔍 Calculating MMI for Dogecoin...")
    mmi_doge = LooloomiMMI("dogecoin")
    result_doge = mmi_doge.report()
