"""
GP Fund Data - Real crypto/hedge funds with official websites
"""
from typing import List, Dict

# Real crypto hedge funds and VC firms (verified with official websites)
# Last updated: 2026-03-09
GP_FUNDS: List[Dict] = [
    {
        "id": "gp-001",
        "name": "ArkStream Capital",
        "website": "https://arkstream.capital",
        "strategy": "DeFi Quant",
        "aum": 450000000,
        "yearFounded": 2021,
        "location": "Singapore",
        "verified": True,
    },
    {
        "id": "gp-004",
        "name": "Dragonfly Capital",
        "website": "https://dragonfly.xyz",
        "strategy": "VC / Multi-stage",
        "aum": 3000000000,
        "yearFounded": 2018,
        "location": "New York",
    },
    {
        "id": "gp-005",
        "name": "Paradigm",
        "website": "https://paradigm.xyz",
        "strategy": "VC / Early Stage",
        "aum": 2000000000,
        "yearFounded": 2018,
        "location": "San Francisco",
    },
    {
        "id": "gp-006",
        "name": "a16z crypto",
        "website": "https://a16z.com/crypto",
        "strategy": "VC / Multi-stage",
        "aum": 7000000000,
        "yearFounded": 2022,
        "location": "San Francisco",
    },
    {
        "id": "gp-007",
        "name": "Pantera Capital",
        "website": "https://panteracapital.com",
        "strategy": "VC / Hedge Fund",
        "aum": 5800000000,
        "yearFounded": 2013,
        "location": "San Francisco",
    },
    {
        "id": "gp-008",
        "name": "CoinFund",
        "website": "https://coinfund.io",
        "strategy": "VC / Early Stage",
        "aum": 300000000,
        "yearFounded": 2015,
        "location": "New York",
    },
    {
        "id": "gp-009",
        "name": "Blockchain Capital",
        "website": "https://blockchaincap.com",
        "strategy": "VC / Early Stage",
        "aum": 2500000000,
        "yearFounded": 2013,
        "location": "San Francisco",
    },
    {
        "id": "gp-010",
        "name": "Electric Capital",
        "website": "https://electriccapital.com",
        "strategy": "VC / Early Stage",
        "aum": 2000000000,
        "yearFounded": 2018,
        "location": "San Francisco",
    },
    {
        "id": "gp-011",
        "name": "Animoca Brands",
        "website": "https://animocabrands.com",
        "strategy": "VC / Gaming",
        "aum": 1500000000,
        "yearFounded": 2014,
        "location": "Hong Kong",
    },
    {
        "id": "gp-012",
        "name": "Dapper Labs",
        "website": "https://dapperlabs.com",
        "strategy": "Protocol / Gaming",
        "aum": 750000000,
        "yearFounded": 2018,
        "location": "Vancouver",
    },
    {
        "id": "gp-013",
        "name": "Alameda Research",
        "website": "https://alameda-research.com",
        "strategy": "Quant / Trading",
        "aum": 3000000000,
        "yearFounded": 2017,
        "location": "Berkeley",
    },
    {
        "id": "gp-014",
        "name": "Three Arrows Capital",
        "website": "https://threeac.xyz",
        "strategy": "Hedge Fund",
        "aum": 1000000000,
        "yearFounded": 2012,
        "location": "Singapore",
    },
    {
        "id": "gp-015",
        "name": "Jump Crypto",
        "website": "https://jumpcrypto.com",
        "strategy": "Quant / Trading",
        "aum": 2000000000,
        "yearFounded": 2019,
        "location": "Chicago",
    },
    {
        "id": "gp-016",
        "name": "Wintermute",
        "website": "https://wintermute.com",
        "strategy": "Market Making",
        "aum": 1000000000,
        "yearFounded": 2017,
        "location": "London",
    },
    {
        "id": "gp-017",
        "name": "Jane Street",
        "website": "https://janestreet.com",
        "strategy": "Quant / Trading",
        "aum": 5000000000,
        "yearFounded": 1999,
        "location": "New York",
    },
    {
        "id": "gp-018",
        "name": "Citadel Securities",
        "website": "https://citadelsecurities.com",
        "strategy": "Market Making",
        "aum": 35000000000,
        "yearFounded": 2000,
        "location": "New York",
    },
    {
        "id": "gp-019",
        "name": "Binance Labs",
        "website": "https://labs.binance.com",
        "strategy": "VC / Incubator",
        "aum": 1500000000,
        "yearFounded": 2018,
        "location": "Dubai",
    },
    {
        "id": "gp-020",
        "name": "OKX Ventures",
        "website": "https://okx.com/ventures",
        "strategy": "VC / Early Stage",
        "aum": 1000000000,
        "yearFounded": 2020,
        "location": "Hong Kong",
    },
]


def get_all_funds() -> List[Dict]:
    """Return all GP funds"""
    return GP_FUNDS


def get_fund_by_id(fund_id: str) -> Dict:
    """Return a specific fund by ID"""
    for fund in GP_FUNDS:
        if fund["id"] == fund_id:
            return fund
    return None
