"""
Protocol Intelligence Engine v1.0
CIS-scored protocol universe with live DeFiLlama data.

Each protocol is scored across 5 CIS pillars:
  F (Fundamental): TVL scale + stability + audit + age
  M (Momentum):    TVL 7d/30d change + APY trend
  O (On-chain):    Concentration risk + depeg history + contract quality
  S (Sentiment):   Community + dev activity + trending
  A (Alpha):       Outperformance vs category peers

Output: CIS grade (A+ → F), signal (ACCUMULATE/HOLD/REDUCE/AVOID),
        recommended_weight, per-pillar breakdown, risk_tier.
"""

import time
import math
import httpx
import asyncio
from datetime import datetime, timezone

# ── TTL cache (shared with data_layer pattern) ─────────────────────────────
_pcache: dict = {}

def _cget(key: str, ttl: int = 300):
    if key in _pcache:
        val, ts = _pcache[key]
        if time.time() - ts < ttl:
            return val
    return None

def _cset(key: str, val):
    _pcache[key] = (val, time.time())
    return val


# ── Protocol Registry ───────────────────────────────────────────────────────
# slug = DeFiLlama protocol slug for live TVL lookup
PROTOCOL_REGISTRY = [
    # RWA — Treasuries
    {"id": "ondo",       "name": "Ondo Finance",       "slug": "ondo-finance",        "category": "RWA - Treasuries", "chain": "Multi-chain", "base_apy": 4.8, "audit_score": 9, "age_months": 24, "desc": "Tokenized US Treasuries (OUSG, OMMF)"},
    {"id": "blackrock",  "name": "BlackRock BUIDL",     "slug": "blackrock-buidl",     "category": "RWA - Treasuries", "chain": "Multi-chain", "base_apy": 4.3, "audit_score": 10, "age_months": 18, "desc": "Tokenized Money Market Fund"},
    {"id": "franklin",   "name": "Franklin Templeton",  "slug": "franklin-templeton",   "category": "RWA - Treasuries", "chain": "Polygon",     "base_apy": 4.5, "audit_score": 10, "age_months": 20, "desc": "BENJI — On-chain US Treasury Fund"},
    {"id": "superstate", "name": "Superstate",          "slug": "superstate",           "category": "RWA - Treasuries", "chain": "Ethereum",    "base_apy": 4.6, "audit_score": 8,  "age_months": 14, "desc": "USTB — US Treasury Short Fund"},
    {"id": "anemoy",     "name": "Anemoy Capital",      "slug": "anemoy",              "category": "RWA - Treasuries", "chain": "Multi-chain", "base_apy": 5.2, "audit_score": 7,  "age_months": 12, "desc": "Treasury Bill protocol"},

    # RWA — Private Credit
    {"id": "maple",      "name": "Maple Finance",       "slug": "maple",               "category": "RWA - Private Credit", "chain": "Multi-chain", "base_apy": 12.0, "audit_score": 8, "age_months": 36, "desc": "Institutional unsecured lending"},
    {"id": "centrifuge", "name": "Centrifuge",           "slug": "centrifuge",          "category": "RWA - Private Credit", "chain": "Multi-chain", "base_apy": 9.5,  "audit_score": 9, "age_months": 48, "desc": "Real-world asset financing"},
    {"id": "credix",     "name": "Credix",               "slug": "credix-finance",      "category": "RWA - Private Credit", "chain": "Solana",      "base_apy": 14.0, "audit_score": 7, "age_months": 24, "desc": "EM credit marketplace"},
    {"id": "goldfinch",  "name": "Goldfinch",            "slug": "goldfinch",           "category": "RWA - Private Credit", "chain": "Ethereum",    "base_apy": 8.0,  "audit_score": 9, "age_months": 36, "desc": "Decentralized credit protocol"},

    # DeFi — Lending
    {"id": "aave",       "name": "Aave",                "slug": "aave",                "category": "DeFi - Lending",  "chain": "Multi-chain", "base_apy": 3.5,  "audit_score": 10, "age_months": 60, "desc": "Largest DeFi lending protocol"},
    {"id": "compound",   "name": "Compound",            "slug": "compound",            "category": "DeFi - Lending",  "chain": "Multi-chain", "base_apy": 2.8,  "audit_score": 10, "age_months": 60, "desc": "Algorithmic money market"},
    {"id": "morpho",     "name": "Morpho",              "slug": "morpho",              "category": "DeFi - Lending",  "chain": "Ethereum",    "base_apy": 5.5,  "audit_score": 9,  "age_months": 24, "desc": "Peer-to-peer lending optimizer"},

    # DeFi — DEX / Liquidity
    {"id": "uniswap",    "name": "Uniswap",             "slug": "uniswap",             "category": "DeFi - DEX",      "chain": "Multi-chain", "base_apy": 0,    "audit_score": 10, "age_months": 72, "desc": "Leading DEX by volume"},
    {"id": "curve",      "name": "Curve Finance",       "slug": "curve-dex",           "category": "DeFi - DEX",      "chain": "Multi-chain", "base_apy": 2.0,  "audit_score": 9,  "age_months": 60, "desc": "Stablecoin DEX & yield"},
    {"id": "jupiter",    "name": "Jupiter",             "slug": "jupiter",             "category": "DeFi - DEX",      "chain": "Solana",      "base_apy": 0,    "audit_score": 8,  "age_months": 24, "desc": "Solana DEX aggregator"},

    # DeFi — Liquid Staking
    {"id": "lido",       "name": "Lido",                "slug": "lido",                "category": "DeFi - Staking",  "chain": "Multi-chain", "base_apy": 3.2,  "audit_score": 10, "age_months": 48, "desc": "Largest ETH liquid staking"},
    {"id": "rocketpool", "name": "Rocket Pool",         "slug": "rocket-pool",         "category": "DeFi - Staking",  "chain": "Ethereum",    "base_apy": 3.0,  "audit_score": 9,  "age_months": 36, "desc": "Decentralized ETH staking"},
    {"id": "jito",       "name": "Jito",                "slug": "jito",                "category": "DeFi - Staking",  "chain": "Solana",      "base_apy": 7.5,  "audit_score": 8,  "age_months": 18, "desc": "SOL liquid staking + MEV"},

    # Derivatives
    {"id": "hyperliquid","name": "Hyperliquid",         "slug": "hyperliquid",         "category": "Derivatives",     "chain": "Hyperliquid", "base_apy": 0,    "audit_score": 7,  "age_months": 18, "desc": "High-performance perps L1"},
    {"id": "gmx",        "name": "GMX",                 "slug": "gmx",                "category": "Derivatives",     "chain": "Arbitrum",    "base_apy": 0,    "audit_score": 9,  "age_months": 30, "desc": "Decentralized perpetual trading"},
    {"id": "dydx",       "name": "dYdX",                "slug": "dydx",               "category": "Derivatives",     "chain": "Cosmos",      "base_apy": 0,    "audit_score": 9,  "age_months": 48, "desc": "Decentralized perps exchange"},

    # Infrastructure
    {"id": "eigenlayer", "name": "EigenLayer",          "slug": "eigenlayer",          "category": "Infrastructure",  "chain": "Ethereum",    "base_apy": 3.8,  "audit_score": 8,  "age_months": 18, "desc": "Restaking infrastructure"},
    {"id": "ethena",     "name": "Ethena",              "slug": "ethena",              "category": "Infrastructure",  "chain": "Ethereum",    "base_apy": 15.0, "audit_score": 7,  "age_months": 12, "desc": "Synthetic dollar protocol"},
    {"id": "pendle",     "name": "Pendle",              "slug": "pendle",              "category": "DeFi - Yield",    "chain": "Multi-chain", "base_apy": 8.0,  "audit_score": 8,  "age_months": 30, "desc": "Yield tokenization & trading"},
    {"id": "maker",      "name": "Sky (MakerDAO)",      "slug": "makerdao",            "category": "DeFi - Stablecoin","chain": "Ethereum",   "base_apy": 5.0,  "audit_score": 10, "age_months": 84, "desc": "DAI stablecoin & RWA exposure"},
]


# ── DeFiLlama TVL Fetcher ───────────────────────────────────────────────────

async def _fetch_defillama_tvl(slug: str) -> dict | None:
    """Fetch TVL + TVL changes from DeFiLlama for a single protocol."""
    cache_key = f"proto_tvl:{slug}"
    cached = _cget(cache_key, ttl=600)  # 10min cache
    if cached is not None:
        return cached

    try:
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.get(f"https://api.llama.fi/protocol/{slug}")
            if r.status_code != 200:
                return _cset(cache_key, None)
            data = r.json()
            tvl_now = data.get("currentChainTvls", {})
            total_tvl = sum(v for k, v in tvl_now.items()
                           if not k.endswith("-borrowed") and not k.endswith("-staking")
                           and isinstance(v, (int, float)))
            if total_tvl == 0:
                total_tvl = data.get("tvl", [{}])[-1].get("totalLiquidityUSD", 0) if data.get("tvl") else 0

            # TVL history for 7d/30d change
            tvl_history = data.get("tvl", [])
            tvl_7d_ago = None
            tvl_30d_ago = None
            now_ts = time.time()
            for point in reversed(tvl_history):
                ts = point.get("date", 0)
                age_days = (now_ts - ts) / 86400
                if tvl_7d_ago is None and age_days >= 6.5:
                    tvl_7d_ago = point.get("totalLiquidityUSD", 0)
                if tvl_30d_ago is None and age_days >= 29:
                    tvl_30d_ago = point.get("totalLiquidityUSD", 0)
                if tvl_7d_ago and tvl_30d_ago:
                    break

            change_7d = ((total_tvl - tvl_7d_ago) / tvl_7d_ago * 100) if tvl_7d_ago and tvl_7d_ago > 0 else 0
            change_30d = ((total_tvl - tvl_30d_ago) / tvl_30d_ago * 100) if tvl_30d_ago and tvl_30d_ago > 0 else 0

            result = {
                "tvl": total_tvl,
                "tvl_7d_ago": tvl_7d_ago,
                "tvl_30d_ago": tvl_30d_ago,
                "change_7d": round(change_7d, 2),
                "change_30d": round(change_30d, 2),
                "chains": list(tvl_now.keys())[:5],
                "mcap": data.get("mcap", 0),
                "category": data.get("category", ""),
            }
            return _cset(cache_key, result)
    except Exception:
        return _cset(cache_key, None)


async def fetch_all_protocol_tvls() -> dict:
    """Batch fetch TVL for all protocols. Returns {id: tvl_data}."""
    cache_key = "proto_tvl_all"
    cached = _cget(cache_key, ttl=300)
    if cached is not None:
        return cached

    tasks = []
    for p in PROTOCOL_REGISTRY:
        tasks.append(_fetch_defillama_tvl(p["slug"]))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    tvl_map = {}
    for p, result in zip(PROTOCOL_REGISTRY, results):
        if isinstance(result, dict) and result:
            tvl_map[p["id"]] = result
        else:
            tvl_map[p["id"]] = None

    return _cset(cache_key, tvl_map)


# ── CIS Scoring Engine for Protocols ────────────────────────────────────────

def _score_protocol(proto: dict, tvl_data: dict | None, category_stats: dict) -> dict:
    """
    Score a single protocol across F/M/O/S/A pillars.
    Returns full scored protocol object.
    """
    pid = proto["id"]
    cat = proto["category"]

    tvl = tvl_data["tvl"] if tvl_data else 0
    chg_7d = tvl_data["change_7d"] if tvl_data else 0
    chg_30d = tvl_data["change_30d"] if tvl_data else 0
    live_tvl = tvl_data is not None

    # ── F pillar (Fundamental): TVL scale + audit + age ──────────────────
    # TVL score: log scale, max 30 at $10B+
    if tvl > 0:
        tvl_pts = min(30, max(0, int(math.log10(max(tvl, 1)) * 4 - 12)))
    else:
        tvl_pts = 0

    # Audit quality (0-10 input → 0-15 points)
    audit_pts = int(proto.get("audit_score", 5) * 1.5)

    # Protocol age maturity (months → points, max 15)
    age = proto.get("age_months", 0)
    age_pts = min(15, int(age / 4))

    # APY contribution (yield-bearing protocols get F boost)
    apy = proto.get("base_apy", 0)
    apy_pts = min(10, int(apy * 0.8)) if apy > 0 else 0

    f_score = min(40, tvl_pts + audit_pts + age_pts + apy_pts)

    # ── M pillar (Momentum): TVL change direction ────────────────────────
    m_7d = min(15, max(-15, int(chg_7d * 0.5)))
    m_30d = min(10, max(-10, int(chg_30d * 0.2)))
    m_base = 10 if tvl > 1e9 else 5 if tvl > 1e8 else 0
    m_score = max(0, min(30, m_base + m_7d + m_30d))

    # ── O pillar (On-chain / Risk): audit + age + TVL stability ──────────
    audit_risk = proto.get("audit_score", 5) * 2  # 0-20
    # TVL stability: penalize large drawdowns
    stability = 10
    if chg_7d < -15:
        stability -= 5
    if chg_30d < -30:
        stability -= 5
    # Age maturity for risk
    age_risk = min(10, int(age / 6))
    o_score = min(30, max(0, audit_risk + stability + age_risk))

    # ── S pillar (Sentiment): TVL growth = positive market perception ────
    s_growth = 5 if chg_7d > 5 else 0
    s_scale = min(10, int(math.log10(max(tvl, 1)) * 1.5 - 5)) if tvl > 0 else 0
    s_category = 5 if "RWA" in cat else 3  # RWA narrative premium 2026
    s_score = max(0, min(20, s_growth + s_scale + s_category))

    # ── A pillar (Alpha): outperformance vs category average ─────────────
    cat_avg_chg = category_stats.get(cat, {}).get("avg_change_7d", 0)
    alpha_vs_peers = chg_7d - cat_avg_chg
    a_outperform = min(10, max(-10, int(alpha_vs_peers * 0.5)))
    # Small protocols with high momentum = alpha opportunity
    a_size_bonus = 5 if tvl < 5e8 and chg_7d > 10 else 0
    a_score = max(0, min(20, 5 + a_outperform + a_size_bonus))

    # ── Composite ────────────────────────────────────────────────────────
    total = f_score + m_score + o_score + s_score + a_score
    # Normalize to 0-100
    max_possible = 40 + 30 + 30 + 20 + 20  # = 140
    normalized = round(total / max_possible * 100, 1)

    # Grade (protocol-specific thresholds)
    if normalized >= 75:
        grade = "A+"
    elif normalized >= 65:
        grade = "A"
    elif normalized >= 55:
        grade = "B+"
    elif normalized >= 45:
        grade = "B"
    elif normalized >= 35:
        grade = "C+"
    elif normalized >= 25:
        grade = "C"
    elif normalized >= 15:
        grade = "D"
    else:
        grade = "F"

    # Signal — compliance-safe positioning language (no buy/sell)
    if normalized >= 65 and chg_7d > 0:
        signal = "OUTPERFORM"
    elif normalized >= 50:
        signal = "NEUTRAL"
    elif normalized >= 35:
        signal = "UNDERPERFORM"
    else:
        signal = "UNDERWEIGHT"

    # Recommended weight (basis points of portfolio)
    if signal == "OUTPERFORM":
        rec_weight = min(800, max(200, int(normalized * 8)))
    elif signal == "NEUTRAL":
        rec_weight = min(500, max(100, int(normalized * 4)))
    elif signal == "UNDERPERFORM":
        rec_weight = max(0, int(normalized * 2))
    else:
        rec_weight = 0

    # Risk tier
    if o_score >= 25 and f_score >= 25:
        risk_tier = "LOW"
    elif o_score >= 15:
        risk_tier = "MEDIUM"
    else:
        risk_tier = "HIGH"

    # Direction arrow
    if chg_7d > 3:
        tvl_direction = "UP"
    elif chg_7d < -3:
        tvl_direction = "DOWN"
    else:
        tvl_direction = "FLAT"

    return {
        "id": pid,
        "name": proto["name"],
        "category": cat,
        "chain": proto["chain"],
        "description": proto["desc"],
        "live_data": live_tvl,
        "tvl": round(tvl, 0) if tvl else 0,
        "tvl_formatted": _fmt_usd(tvl),
        "tvl_change_7d": chg_7d,
        "tvl_change_30d": chg_30d,
        "tvl_direction": tvl_direction,
        "apy": apy,
        "cis_score": normalized,
        "grade": grade,
        "signal": signal,
        "risk_tier": risk_tier,
        "recommended_weight_bps": rec_weight,
        "pillars": {
            "F": round(f_score / 40 * 100),
            "M": round(m_score / 30 * 100),
            "O": round(o_score / 30 * 100),
            "S": round(s_score / 20 * 100),
            "A": round(a_score / 20 * 100),
        },
        "audit_score": proto.get("audit_score", 0),
        "age_months": proto.get("age_months", 0),
    }


def _fmt_usd(v: float) -> str:
    if not v:
        return "$0"
    if v >= 1e12:
        return f"${v/1e12:.1f}T"
    if v >= 1e9:
        return f"${v/1e9:.2f}B"
    if v >= 1e6:
        return f"${v/1e6:.1f}M"
    if v >= 1e3:
        return f"${v/1e3:.0f}K"
    return f"${v:.0f}"


def _compute_category_stats(protocols: list, tvl_map: dict) -> dict:
    """Compute category-level averages for alpha calculation."""
    cat_data: dict = {}
    for p in protocols:
        cat = p["category"]
        tvl_d = tvl_map.get(p["id"])
        if tvl_d:
            cat_data.setdefault(cat, []).append(tvl_d.get("change_7d", 0))
    return {
        cat: {"avg_change_7d": sum(vals) / len(vals) if vals else 0}
        for cat, vals in cat_data.items()
    }


# ── Main Entry Point ────────────────────────────────────────────────────────

async def get_protocol_universe(category: str | None = None,
                                 min_grade: str | None = None) -> dict:
    """
    Full protocol intelligence universe.
    Returns scored, ranked, categorized protocol list.
    """
    cache_key = f"proto_universe:{category or 'all'}:{min_grade or 'all'}"
    cached = _cget(cache_key, ttl=300)
    if cached is not None:
        return cached

    # 1. Fetch all TVLs
    tvl_map = await fetch_all_protocol_tvls()

    # 2. Category stats for alpha calculation
    cat_stats = _compute_category_stats(PROTOCOL_REGISTRY, tvl_map)

    # 3. Score each protocol
    scored = []
    for proto in PROTOCOL_REGISTRY:
        tvl_data = tvl_map.get(proto["id"])
        result = _score_protocol(proto, tvl_data, cat_stats)
        scored.append(result)

    # 4. Sort by CIS score descending
    scored.sort(key=lambda x: (-x["cis_score"],))

    # 5. Assign ranks
    for i, p in enumerate(scored):
        p["rank"] = i + 1

    # 6. Filter
    grade_order = ["A+", "A", "B+", "B", "C+", "C", "D", "F"]
    if min_grade and min_grade in grade_order:
        min_idx = grade_order.index(min_grade)
        scored = [p for p in scored if grade_order.index(p["grade"]) <= min_idx]

    if category:
        cat_lower = category.lower()
        scored = [p for p in scored
                  if cat_lower in p["category"].lower()]

    # 7. Category summary
    categories = {}
    for p in scored:
        cat = p["category"]
        if cat not in categories:
            categories[cat] = {"count": 0, "total_tvl": 0, "avg_score": 0, "scores": []}
        categories[cat]["count"] += 1
        categories[cat]["total_tvl"] += p["tvl"]
        categories[cat]["scores"].append(p["cis_score"])
    for cat, info in categories.items():
        info["avg_score"] = round(sum(info["scores"]) / len(info["scores"]), 1) if info["scores"] else 0
        info["total_tvl_formatted"] = _fmt_usd(info["total_tvl"])
        del info["scores"]

    # 8. Top picks (agent-recommended)
    top_picks = [p["id"] for p in scored if p["signal"] == "OUTPERFORM"][:5]

    result = {
        "status": "success",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": "1.0.0",
        "total_protocols": len(scored),
        "total_tvl": _fmt_usd(sum(p["tvl"] for p in scored)),
        "agent_picks": top_picks,
        "categories": categories,
        "protocols": scored,
    }
    return _cset(cache_key, result)
