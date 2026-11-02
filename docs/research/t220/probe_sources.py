#!/usr/bin/env python3
"""T-220 ①:免费数据源可行性实测(只 GET;不注册、不付费、不写任何 key)。"""
import json
import re
import ssl
import urllib.request
import urllib.error

HERE = "/Volumes/CometCloudAI/cometcloud-local/research/t220/"
CTX = ssl.create_default_context()
UA = {"User-Agent": "Mozilla/5.0 (cometcloud research feasibility probe)"}

# CIS 加密 25 名单 → DeFiLlama protocol slug 猜测 + gecko id
SLUGS = {
    "AAVE": "aave", "ADA": "cardano", "APT": "aptos", "ARB": "arbitrum", "AVAX": "avalanche",
    "BNB": "binance-smart-chain", "BTC": "bitcoin", "DOT": "polkadot", "ETH": "ethereum",
    "HYPE": "hyperliquid", "INJ": "injective-protocol", "LDO": "lido-dao", "LINK": "chainlink",
    "NEAR": "near", "ONDO": "ondo-finance", "OP": "optimism", "PENDLE": "pendle",
    "POL": "polygon", "SKY": "sky-lend", "SOL": "solana", "STRK": "starknet",
    "SUI": "sui", "TIA": "celestia", "UNI": "uniswap", "XRP": "ripple",
}


def get(u, timeout=45, hdrs=None):
    h = dict(UA)
    if hdrs:
        h.update(hdrs)
    try:
        req = urllib.request.Request(u, headers=h)
        with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
            b = r.read()
            return r.status, len(b), b
    except urllib.error.HTTPError as e:
        return e.code, 0, e.read()[:400]
    except Exception as e:  # noqa: BLE001
        return -1, 0, repr(e).encode()[:300]


def head(b, n=220):
    return b[:n].decode("utf-8", "replace").replace("\n", " ")


out = {}

print("=== A1. DeFiLlama 免费域 ===", flush=True)
for path in ["/emissions", "/emission/aave", "/raises", "/protocols", "/unlocks",
             "/tokenUnlocks", "/emissionProtocols"]:
    st, ln, b = get("https://api.llama.fi" + path)
    print(f"{path:24s} {st} len={ln} :: {head(b,120)}", flush=True)
    out["llama" + path] = {"status": st, "len": ln, "head": head(b, 300)}

# AAVE protocol 详情里有没有 unlock / emissions 字段
st, ln, b = get("https://api.llama.fi/protocol/aave")
if st == 200:
    d = json.loads(b)
    keys = sorted(d.keys())
    print("protocol/aave keys:", keys, flush=True)
    out["llama_protocol_aave_keys"] = keys
    for k in ("emissions", "unlocks", "token", "raises", "treasury", "mcap", "raises"):
        if k in d:
            v = json.dumps(d[k], ensure_ascii=False)
            print(f"  {k}: {v[:300]}", flush=True)
            out[f"llama_protocol_aave_{k}"] = v[:1500]

# 25 个币的 protocol 端点:gecko_id / treasury / emissions 是否存在
hit = {}
for sym, slug in SLUGS.items():
    st, ln, b = get("https://api.llama.fi/protocol/" + slug, timeout=60)
    if st != 200:
        hit[sym] = {"status": st}
        continue
    try:
        d = json.loads(b)
    except Exception:  # noqa: BLE001
        hit[sym] = {"status": st, "parse": "fail"}
        continue
    hit[sym] = {"status": st, "name": d.get("name"), "gecko_id": d.get("gecko_id"),
                "has_emissions": "emissions" in d, "has_unlocks": "unlocks" in d,
                "treasury": (d.get("treasury") or "")[:80],
                "raises": bool(d.get("raises")),
                "mcap": d.get("mcap")}
    print(sym, json.dumps(hit[sym], ensure_ascii=False)[:260], flush=True)
out["llama_protocol_25"] = hit

print("\n=== A2. DeFiLlama Pro 价格(公开页) ===", flush=True)
st, ln, b = get("https://docs.llama.fi/pro-api")
if st == 200:
    txt = b.decode("utf-8", "replace")
    prices = re.findall(r"\$\s?\d[\d,]*(?:\.\d+)?\s*(?:/|per\s)\s*(?:mo|month|yr|year)?", txt, re.I)
    print("status", st, "price-like tokens:", sorted(set(prices))[:40], flush=True)
    out["llama_pro_prices"] = sorted(set(prices))[:60]
    out["llama_pro_page_head"] = head(b, 1500)
else:
    print("status", st, head(b, 200), flush=True)
    out["llama_pro_prices"] = {"status": st, "head": head(b, 300)}

print("\n=== B. 钱包标签 / 团队钱包源 ===", flush=True)
probes = [
    ("etherscan_v2_nokey", "https://api.etherscan.io/v2/api?chainid=1&module=account&action=balance&address=0x0000000000000000000000000000000000000000"),
    ("arkham_intel_root", "https://intel.arkm.com/"),
    ("arkham_api_root", "https://api.arkhamintelligence.com/"),
    ("nansen_api_root", "https://api.nansen.ai/"),
    ("tokenomist_api", "https://api.tokenomist.ai/"),
    ("cryptorank_api", "https://api.cryptorank.io/"),
    ("openchain_labels", "https://api.openchain.xyz/v1/gas_price"),
    ("labels_eth_org", "https://labels.ethereum.org/"),
    ("blockchair", "https://api.blockchair.com/ethereum/stats"),
    ("ethplorer", "https://api.ethplorer.io/api?module=stats&action=ethPrice"),
    ("dune_api_nokey", "https://api.dune.com/api/v1/query/1/results"),
    ("coingecko_free", "https://api.coingecko.com/api/v3/ping"),
    ("llama_unlocks_page", "https://defillama.com/unlocks"),
    ("tokenunlocks_site", "https://tokenunlocks.app/"),
]
for name, u in probes:
    st, ln, b = get(u, timeout=40)
    print(f"{name:22s} {st} len={ln} :: {head(b,150)}", flush=True)
    out[name] = {"status": st, "len": ln, "head": head(b, 400)}

json.dump(out, open(HERE + "_sources.json", "w"), ensure_ascii=False, indent=1)
print("\nsaved _sources.json")
