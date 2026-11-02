#!/usr/bin/env python3
"""T-220 ①:DeFiLlama 免费 /protocol 端点对 CIS 25 名的 treasury / raises(基金会·投资方)覆盖。"""
import json
import ssl
import urllib.request
import urllib.error

HERE = "/Volumes/CometCloudAI/cometcloud-local/research/t220/"
CTX = ssl.create_default_context()
UA = {"User-Agent": "Mozilla/5.0 (cometcloud research feasibility probe)"}

# 用 unlocks 公开页里实测到的 llama slug
SLUGS = {"AAVE": "aave", "ADA": "cardano", "APT": "aptos", "ARB": "arbitrum-foundation",
         "AVAX": "avalanche", "BNB": "binance-smart-chain", "BTC": "bitcoin", "DOT": "polkadot-treasury",
         "ETH": "ethereum", "HYPE": "hyperliquid", "INJ": "injective", "LDO": "lido",
         "LINK": "chainlink", "NEAR": "near-protocol", "ONDO": "ondo-finance",
         "OP": "optimism-foundation", "PENDLE": "pendle", "POL": "polygon-bridge",
         "SKY": "sky", "SOL": "solana", "STRK": "starknet-bridge", "SUI": "sui-foundation",
         "TIA": "celestia", "UNI": "uniswap", "XRP": "ripple"}


def get(u, timeout=60):
    try:
        req = urllib.request.Request(u, headers=UA)
        with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()[:300]
    except Exception as e:  # noqa: BLE001
        return -1, repr(e).encode()[:200]


out = {}
n_treas = 0
n_raise = 0
for sym, slug in SLUGS.items():
    st, b = get("https://api.llama.fi/protocol/" + slug)
    if st != 200:
        out[sym] = {"status": st}
        print(f"{sym:6s} {slug:24s} -> {st}", flush=True)
        continue
    d = json.loads(b)
    tr = (d.get("treasury") or "").strip()
    rs = d.get("raises") or []
    keys = sorted(rs[0].keys()) if rs else []
    out[sym] = {"status": st, "name": d.get("name"), "gecko_id": d.get("gecko_id"),
                "treasury": tr, "n_raises": len(rs), "raise_keys": keys,
                "raise_rounds": [{"round": r.get("round"), "date": r.get("date"),
                                  "amount": r.get("amount"), "category": r.get("category")}
                                 for r in rs][:4]}
    n_treas += 1 if tr else 0
    n_raise += 1 if rs else 0
    print(f"{sym:6s} {str(d.get('name'))[:20]:20s} treasury={tr[:40]:40s} n_raises={len(rs)} "
          f"keys={keys}", flush=True)

print(f"\n有 treasury 地址: {n_treas}/25;有 raises(融资轮)记录: {n_raise}/25", flush=True)
out["_summary"] = {"n_treasury": n_treas, "n_raises": n_raise}
json.dump(out, open(HERE + "_sources4.json", "w"), ensure_ascii=False, indent=1)
print("saved _sources4.json")
