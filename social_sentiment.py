import requests
import time
from datetime import datetime, timedelta
from pytrends.request import TrendReq

class SocialSentiment:
    """
    Social Sentiment Data Collector
    Sources: CryptoPanic, Google Trends, Reddit
    """
    
    def __init__(self):
        self.api_delay = 1.0
    
    # ========== CRYPTOPANIC (News Sentiment) ==========
    def get_cryptopanic_sentiment(self, currency: str = "BTC") -> dict:
        """
        CryptoPanic free API - news sentiment
        Returns: bullish/bearish ratio from news
        """
        print(f"    Fetching CryptoPanic news...")
        
        try:
            # Free public endpoint (no auth needed for basic)
            url = f"https://cryptopanic.com/api/free/v1/posts/"
            params = {
                'auth_token': 'free',  # Use 'free' for public access
                'currencies': currency,
                'filter': 'hot',
                'public': 'true'
            }
            
            response = requests.get(url, params=params, timeout=10)
            
            if response.status_code != 200:
                # Fallback: just count we tried
                return {
                    'score': 50,
                    'source': 'cryptopanic',
                    'note': 'API requires registration for full access'
                }
            
            data = response.json()
            results = data.get('results', [])
            
            # Count sentiment from votes
            bullish = sum(1 for r in results if r.get('votes', {}).get('positive', 0) > r.get('votes', {}).get('negative', 0))
            bearish = sum(1 for r in results if r.get('votes', {}).get('negative', 0) > r.get('votes', {}).get('positive', 0))
            total = len(results)
            
            if total > 0:
                score = (bullish / total) * 100
            else:
                score = 50
            
            return {
                'score': round(score, 1),
                'bullish_posts': bullish,
                'bearish_posts': bearish,
                'total_posts': total,
                'source': 'cryptopanic'
            }
            
        except Exception as e:
            print(f"    CryptoPanic error: {e}")
            return {'score': 50, 'error': str(e)}
    
    # ========== GOOGLE TRENDS (Search Interest) ==========
    def get_google_trends(self, keyword: str = "bitcoin") -> dict:
        """
        Google Trends - search interest as sentiment proxy
        High search = high interest (can be fear or greed)
        """
        print(f"    Fetching Google Trends for '{keyword}'...")
        
        try:
            pytrends = TrendReq(hl='en-US', tz=360, timeout=(10, 25))
            
            # Get interest over last 7 days 
            pytrends.build_payload([keyword], cat=0, timeframe='now 7-d')
            interest_df = pytrends.interest_over_time()
            
            if interest_df.empty:
                return {'score': 50, 'error': 'No data'}
            
            # Get values
            values = interest_df[keyword].tolist()
            current = values[-1]
            avg_7d = sum(values) / len(values)
            peak = max(values)
            
            # Normalize: 0-100 based on relative interest
            # High interest during fear = buying opportunity
            # We'll combine this with F&G later
            score = current  # Already 0-100 scale
            
            # Trend direction
            if len(values) >= 2:
                trend = "📈 Rising" if values[-1] > values[-2] else "📉 Falling"
            else:
                trend = "➡️ Stable"
            
            return {
                'score': round(score, 1),
                'current': current,
                'avg_7d': round(avg_7d, 1),
                'peak_7d': peak,
                'trend': trend,
                'source': 'google_trends'
            }
            
        except Exception as e:
            print(f"    Google Trends error: {e}")
            return {'score': 50, 'error': str(e)}
    
    # ========== REDDIT (Community Activity) ==========
    def get_reddit_activity(self, subreddit: str = "bitcoin") -> dict:
        """
        Reddit public JSON API - no auth needed
        Measures: post volume, upvotes, comment activity
        """
        print(f"    Fetching Reddit r/{subreddit}...")
        
        try:
            # Reddit public JSON endpoint
            url = f"https://www.reddit.com/r/{subreddit}/hot.json"
            headers = {'User-Agent': 'LooloomiMMI/1.0'}
            
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            
            data = response.json()
            posts = data['data']['children']
            
            # Analyze top 25 posts
            total_upvotes = 0
            total_comments = 0
            post_count = len(posts)
            
            for post in posts:
                p = post['data']
                total_upvotes += p.get('ups', 0)
                total_comments += p.get('num_comments', 0)
            
            avg_upvotes = total_upvotes / post_count if post_count > 0 else 0
            avg_comments = total_comments / post_count if post_count > 0 else 0
            
            # Engagement score (normalized)
            # High engagement can signal both fear and greed
            engagement = (avg_upvotes / 1000) + (avg_comments / 100)
            score = min(100, engagement * 10)
            
            return {
                'score': round(score, 1),
                'avg_upvotes': round(avg_upvotes, 0),
                'avg_comments': round(avg_comments, 0),
                'post_count': post_count,
                'source': 'reddit',
                'subreddit': subreddit
            }
            
        except Exception as e:
            print(f"    Reddit error: {e}")
            return {'score': 50, 'error': str(e)}
    
    # ========== COMBINED SOCIAL SCORE ==========
    def get_combined_score(self, token: str = "bitcoin") -> dict:
        """
        Combine all social sources into one score
        Weights: Google Trends 40%, Reddit 40%, News 20%
        """
        print(f"\n  📱 SOCIAL SENTIMENT ANALYSIS")
        print(f"  {'─'*40}")
        
        # Collect all sources
        trends = self.get_google_trends(token)
        time.sleep(1)
        
        reddit = self.get_reddit_activity(token)
        time.sleep(1)
        
        # Weighted combination
        weights = {
            'trends': 0.40,
            'reddit': 0.40,
            'news': 0.20
        }
        
        # Use neutral for news if API not available
        news_score = 50
        
        combined = (
            trends['score'] * weights['trends'] +
            reddit['score'] * weights['reddit'] +
            news_score * weights['news']
        )
        
        return {
            'score': round(combined, 1),
            'google_trends': trends,
            'reddit': reddit,
            'weights': weights
        }


# Test
if __name__ == "__main__":
    social = SocialSentiment()
    
    print("\n" + "="*60)
    print("  SOCIAL SENTIMENT TEST")
    print("="*60)
    
    result = social.get_combined_score("bitcoin")
    
    print(f"\n  {'─'*40}")
    print(f"  COMBINED SOCIAL SCORE: {result['score']}/100")
    print(f"  {'─'*40}")
    
    gt = result['google_trends']
    print(f"\n  Google Trends: {gt['score']}/100")
    print(f"    Current interest: {gt.get('current', 'N/A')}")
    print(f"    7-day average: {gt.get('avg_7d', 'N/A')}")
    print(f"    Trend: {gt.get('trend', 'N/A')}")
    
    rd = result['reddit']
    print(f"\n  Reddit r/bitcoin: {rd['score']}/100")
    print(f"    Avg upvotes: {rd.get('avg_upvotes', 'N/A')}")
    print(f"    Avg comments: {rd.get('avg_comments', 'N/A')}")
    
    print("\n" + "="*60)
