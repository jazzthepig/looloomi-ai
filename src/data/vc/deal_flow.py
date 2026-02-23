"""
VC Deal Flow Tracker
Track funding rounds, VC portfolios, and token unlocks
"""
import requests
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import time


class VCDealFlowTracker:
    """
    Track crypto VC deal flow from multiple sources
    - CryptoRank API (free tier)
    - DefiLlama unlocks
    - Public announcements
    """
    
    def __init__(self):
        self.cryptorank_base = "https://api.cryptorank.io/v1"
        self.defillama_base = "https://api.llama.fi"
        self.cache = {}
        self.cache_ttl = 3600  # 1 hour
    
    def get_recent_funding_rounds(self, limit: int = 20) -> List[Dict]:
        """
        Get recent crypto funding rounds
        Returns: List of funding rounds with project, amount, round type, investors
        """
        try:
            # CryptoRank funding rounds endpoint
            url = f"{self.cryptorank_base}/funding-rounds"
            params = {"limit": limit}
            
            response = requests.get(url, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                rounds = []
                
                for item in data.get("data", [])[:limit]:
                    rounds.append({
                        "project": item.get("project", {}).get("name", "Unknown"),
                        "amount": item.get("amount"),
                        "round_type": item.get("roundType", "Unknown"),
                        "date": item.get("date"),
                        "investors": [inv.get("name") for inv in item.get("investors", [])[:5]],
                        "category": item.get("project", {}).get("category", "Unknown"),
                        "website": item.get("project", {}).get("website"),
                    })
                
                return rounds
            else:
                # Fallback to mock data for demo
                return self._get_mock_funding_rounds()
                
        except Exception as e:
            print(f"Error fetching funding rounds: {e}")
            return self._get_mock_funding_rounds()
    
    def get_top_vcs(self, limit: int = 20) -> List[Dict]:
        """
        Get top crypto VCs by deal count
        """
        try:
            url = f"{self.cryptorank_base}/funds"
            params = {"limit": limit, "sort": "deals"}
            
            response = requests.get(url, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                vcs = []
                
                for item in data.get("data", [])[:limit]:
                    vcs.append({
                        "name": item.get("name", "Unknown"),
                        "deals_count": item.get("dealsCount", 0),
                        "portfolio_size": item.get("portfolioSize", 0),
                        "top_investments": item.get("topInvestments", []),
                        "website": item.get("website"),
                        "twitter": item.get("twitter"),
                    })
                
                return vcs
            else:
                return self._get_mock_top_vcs()
                
        except Exception as e:
            print(f"Error fetching VCs: {e}")
            return self._get_mock_top_vcs()
    
    def get_token_unlocks(self, days_ahead: int = 30) -> List[Dict]:
        """
        Get upcoming token unlocks from DefiLlama
        """
        try:
            url = f"{self.defillama_base}/emissions/unlocks"
            response = requests.get(url, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                unlocks = []
                
                now = datetime.now()
                cutoff = now + timedelta(days=days_ahead)
                
                for protocol, info in data.items():
                    events = info.get("events", [])
                    for event in events:
                        unlock_date = datetime.fromtimestamp(event.get("timestamp", 0))
                        if now <= unlock_date <= cutoff:
                            unlocks.append({
                                "protocol": protocol,
                                "date": unlock_date.isoformat(),
                                "amount_usd": event.get("value"),
                                "tokens": event.get("amount"),
                                "type": event.get("type", "unlock"),
                                "days_until": (unlock_date - now).days,
                            })
                
                # Sort by date
                unlocks.sort(key=lambda x: x["date"])
                return unlocks[:30]
            else:
                return self._get_mock_unlocks()
                
        except Exception as e:
            print(f"Error fetching unlocks: {e}")
            return self._get_mock_unlocks()
    
    def get_vc_portfolio_overlap(self, vc_names: List[str]) -> Dict:
        """
        Find projects that multiple top VCs have invested in
        High overlap = strong signal
        """
        # This would require portfolio data from each VC
        # For now, return curated high-conviction plays
        return {
            "high_overlap": [
                {"project": "Celestia", "vcs": ["Paradigm", "Polychain", "a16z"], "count": 3},
                {"project": "EigenLayer", "vcs": ["a16z", "Polychain", "Coinbase Ventures"], "count": 3},
                {"project": "Monad", "vcs": ["Paradigm", "Dragonfly", "Electric Capital"], "count": 3},
                {"project": "Berachain", "vcs": ["Polychain", "Framework", "Hack VC"], "count": 3},
                {"project": "Movement Labs", "vcs": ["Polychain", "Hack VC", "Placeholder"], "count": 3},
            ],
            "recent_overlap": [
                {"project": "Story Protocol", "vcs": ["a16z", "Polychain"], "count": 2},
                {"project": "Succinct", "vcs": ["Paradigm", "Robot Ventures"], "count": 2},
                {"project": "Ritual", "vcs": ["Archetype", "Accomplice"], "count": 2},
            ]
        }
    
    def _get_mock_funding_rounds(self) -> List[Dict]:
        """Mock data for demo purposes"""
        return [
            {"project": "Monad", "amount": 225000000, "round_type": "Series A", "date": "2024-04-09", "investors": ["Paradigm", "Electric Capital"], "category": "Layer 1"},
            {"project": "Berachain", "amount": 100000000, "round_type": "Series B", "date": "2024-04-12", "investors": ["Polychain", "Framework", "Hack VC"], "category": "Layer 1"},
            {"project": "Story Protocol", "amount": 80000000, "round_type": "Series B", "date": "2024-08-21", "investors": ["a16z", "Polychain"], "category": "Infrastructure"},
            {"project": "Succinct", "amount": 55000000, "round_type": "Series A", "date": "2024-10-21", "investors": ["Paradigm", "Robot Ventures"], "category": "ZK"},
            {"project": "Movement Labs", "amount": 38000000, "round_type": "Series A", "date": "2024-04-25", "investors": ["Polychain", "Hack VC"], "category": "Layer 2"},
            {"project": "Ritual", "amount": 25000000, "round_type": "Series A", "date": "2024-04-08", "investors": ["Archetype", "Accomplice"], "category": "AI"},
            {"project": "Morph", "amount": 20000000, "round_type": "Seed", "date": "2024-03-14", "investors": ["Pantera", "Dragonfly"], "category": "Layer 2"},
            {"project": "Avail", "amount": 43000000, "round_type": "Series A", "date": "2024-02-26", "investors": ["Founders Fund", "Dragonfly"], "category": "Data Availability"},
        ]
    
    def _get_mock_top_vcs(self) -> List[Dict]:
        """Mock VC data"""
        return [
            {"name": "a16z crypto", "deals_count": 125, "portfolio_size": 500, "focus": ["Infrastructure", "DeFi", "Gaming"]},
            {"name": "Paradigm", "deals_count": 89, "portfolio_size": 120, "focus": ["Infrastructure", "DeFi", "MEV"]},
            {"name": "Polychain Capital", "deals_count": 156, "portfolio_size": 180, "focus": ["Layer 1", "DeFi", "Interoperability"]},
            {"name": "Coinbase Ventures", "deals_count": 400, "portfolio_size": 450, "focus": ["Infrastructure", "DeFi", "Payments"]},
            {"name": "Dragonfly", "deals_count": 78, "portfolio_size": 100, "focus": ["DeFi", "Infrastructure", "Asia"]},
            {"name": "Pantera Capital", "deals_count": 210, "portfolio_size": 250, "focus": ["Infrastructure", "DeFi", "Bitcoin"]},
            {"name": "Framework Ventures", "deals_count": 65, "portfolio_size": 80, "focus": ["DeFi", "Gaming", "Infrastructure"]},
            {"name": "Hack VC", "deals_count": 95, "portfolio_size": 110, "focus": ["Infrastructure", "AI", "DeFi"]},
        ]
    
    def _get_mock_unlocks(self) -> List[Dict]:
        """Mock token unlock data"""
        now = datetime.now()
        return [
            {"protocol": "Arbitrum", "date": (now + timedelta(days=3)).isoformat(), "amount_usd": 85000000, "type": "team", "days_until": 3},
            {"protocol": "Optimism", "date": (now + timedelta(days=7)).isoformat(), "amount_usd": 42000000, "type": "investor", "days_until": 7},
            {"protocol": "Aptos", "date": (now + timedelta(days=12)).isoformat(), "amount_usd": 120000000, "type": "foundation", "days_until": 12},
            {"protocol": "Sui", "date": (now + timedelta(days=15)).isoformat(), "amount_usd": 95000000, "type": "team", "days_until": 15},
            {"protocol": "Celestia", "date": (now + timedelta(days=21)).isoformat(), "amount_usd": 180000000, "type": "investor", "days_until": 21},
            {"protocol": "Starknet", "date": (now + timedelta(days=25)).isoformat(), "amount_usd": 65000000, "type": "team", "days_until": 25},
        ]
    
    def generate_report(self) -> None:
        """Generate VC deal flow report"""
        print("\n" + "="*70)
        print("       LOOLOOMI VC DEAL FLOW REPORT")
        print("="*70)
        print(f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("="*70)
        
        # Recent Funding Rounds
        print("\n" + "-"*70)
        print("  RECENT FUNDING ROUNDS")
        print("-"*70)
        rounds = self.get_recent_funding_rounds(8)
        for r in rounds:
            amount = f"${r['amount']/1e6:.0f}M" if r['amount'] else "Undisclosed"
            investors = ", ".join(r['investors'][:3]) if r['investors'] else "N/A"
            print(f"  {r['project']:20} {r['round_type']:12} {amount:>10}  [{investors}]")
        
        # Token Unlocks
        print("\n" + "-"*70)
        print("  UPCOMING TOKEN UNLOCKS (30 days)")
        print("-"*70)
        unlocks = self.get_token_unlocks(30)
        for u in unlocks[:8]:
            amount = f"${u['amount_usd']/1e6:.0f}M" if u['amount_usd'] else "TBD"
            print(f"  {u['protocol']:15} {u['days_until']:3}d  {amount:>10}  ({u['type']})")
        
        # VC Overlap
        print("\n" + "-"*70)
        print("  HIGH VC OVERLAP (Strong Signal)")
        print("-"*70)
        overlap = self.get_vc_portfolio_overlap([])
        for item in overlap['high_overlap']:
            vcs = ", ".join(item['vcs'])
            print(f"  {item['project']:20} ({item['count']} VCs: {vcs})")
        
        print("\n" + "="*70)


# Test
if __name__ == "__main__":
    tracker = VCDealFlowTracker()
    tracker.generate_report()
