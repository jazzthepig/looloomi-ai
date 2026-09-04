"""VC Deal Flow Tracker —— 融资轮次 / VC 组合 / 代币解锁。

## ⚠️ 2026-09-04 (S-288):删除了全部编造数据

本文件原有三个 `_get_mock_*()`,在 **10 个返回点**上把失败替换成假数据。
CLAUDE.md 规则 #9 点名过这条(「audit standing: DeFiLlama-402 fallbacks」)。

最坏的一个不是 402 那条,是:

    return rounds if rounds else self._get_mock_funding_rounds()

**一个成功但为空的响应(今天真的没有融资)会被替换成虚构的融资。**
真实的「没有」变成虚构的「有」—— 而调用方无从分辨。

而这些假数据**署了真实机构的名**:
"Pump.fun $45M Series A / Paradigm, a16z"、"Soneium $80M / Sony"。
一般的假数据是噪声;**署名的假数据是关于真实公司的虚构事实**。
本模块当时无人 import(死代码),所以没有流到用户面前 ——
但一旦有人接上去,我们就在发布那种东西。

现在:**取不到就返回空。** 空是一个诚实的答案,编造不是。

## ⚠️ 上游状态未验证

`api.llama.fi/raises` 的免费可用性**尚未实测**(代码里那句
"paywalled as of ~May 2026" 是注释,不是观测)。在实测之前,
本模块的产出应视为 `unknown`,不是 `empty`。
"""
import logging
import requests
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import time

_logger = logging.getLogger(__name__)


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
    
    def get_recent_funding_rounds(self, limit: int = 50) -> List[Dict]:
        """
        Get recent crypto funding rounds from DeFiLlama Raises API
        Returns: List of funding rounds with project, amount_usd, round, investors
        API: https://api.llama.fi/raises
        """
        try:
            response = requests.get(
                "https://api.llama.fi/raises",
                timeout=30
            )
            # 402 = paid plan — return mock instead of raising
            if response.status_code == 402:
                _logger.warning("DeFiLlama /raises requires paid plan — using fallback")
                return []            # S-288:宁可空,不可编造
            if response.status_code != 200:
                _logger.warning(f"DeFiLlama /raises status {response.status_code}")
                return []            # S-288:宁可空,不可编造
            data = response.json()
            raises = data.get("raises", [])

            filtered = [r for r in raises if r.get("amount") and r.get("amount", 0) >= 0.1]

            sorted_raises = sorted(filtered, key=lambda x: x.get("date", 0), reverse=True)

            rounds = []
            for item in sorted_raises[:limit]:
                timestamp = item.get("date", 0)
                date_str = ""
                if timestamp:
                    try:
                        date_str = datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d")
                    except:
                        date_str = str(timestamp)

                all_investors = list(item.get("leadInvestors", [])) + list(item.get("otherInvestors", []))

                rounds.append({
                    "project":     item.get("name", "Unknown"),
                    "amount_usd":  int((item.get("amount", 0) or 0) * 1_000_000),
                    "round":       item.get("round", "Unknown"),
                    "date":        timestamp,
                    "dateStr":     date_str,
                    "investors":   all_investors[:10],
                    "category":    item.get("category", "Unknown"),
                    "chains":      item.get("chains", []),
                })

            return rounds        # 空就是空 —— 见模块顶部 S-288

        except requests.RequestException as e:
            _logger.warning(f"DeFiLlama /raises network error: {e}")
            return []            # S-288:宁可空,不可编造
        except Exception as e:
            _logger.warning(f"DeFiLlama /raises error: {e}")
            return []            # S-288:宁可空,不可编造
    
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
                return []            # S-288:宁可空,不可编造
                
        except Exception as e:
            _logger.warning(f"Error fetching VCs: {e}")
            return []            # S-288:宁可空,不可编造
    
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
                return []            # S-288:宁可空,不可编造
                
        except Exception as e:
            _logger.warning(f"Error fetching unlocks: {e}")
            return []            # S-288:宁可空,不可编造
    
    def get_vc_portfolio_overlap(self, vc_names: List[str]) -> Dict:
        """
        Find projects that multiple top VCs have co-invested in.
        Derived from recent funding rounds in the dataset — no hardcoded data.
        """
        rounds = self.get_recent_funding_rounds(200)
        # Build project → investor set map
        project_investors: Dict[str, set] = {}
        for r in rounds:
            proj = r.get("project", "")
            investors = r.get("investors", [])
            if not proj or not investors:
                continue
            if proj not in project_investors:
                project_investors[proj] = set()
            project_investors[proj].update(investors)

        # Filter vc_names if provided
        target_vcs = set(vc_names) if vc_names else None

        overlaps = []
        for proj, investors in project_investors.items():
            matched = list(investors & target_vcs) if target_vcs else list(investors)
            count = len(matched)
            if count >= 2:
                overlaps.append({"project": proj, "vcs": sorted(matched), "count": count})

        overlaps.sort(key=lambda x: x["count"], reverse=True)
        high = [o for o in overlaps if o["count"] >= 3]
        recent = [o for o in overlaps if o["count"] == 2]

        return {
            "high_overlap": high[:10],
            "recent_overlap": recent[:10],
            "data_source": "funding_rounds",
            "available": len(overlaps) > 0,
        }
    
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
