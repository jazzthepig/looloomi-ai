#!/usr/bin/env python3
"""T-210 侦察 2:DexScreener 找合约地址 + 各 DEX 上的池子/流动性;CoinGecko 补 id。

只读公开 API。输出 t210_recon2.json。
"""
import json
import os
import time
import urllib.parse
import urllib.request

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120 Safari/537.36"}
QUERIES = ["PAXG", "XAUT", "GLDX", "SPYX", "QQQX", "OUSG", "USDY", "TBILL", "bILL"]


def get(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=45) as r:
        return json.loads(r.read())


out = {"dexscreener": {}, "coingecko": {}}

for q in QUERIES:
    try:
        d = get("https://api.dexscreener.com/latest/dex/search?q=" + urllib.parse.quote(q))
        pairs = []
        for p in d.get("pairs", [])[:12]:
            pairs.append({
                "chain": p.get("chainId"), "dex": p.get("dexId"),
                "pair": p.get("pairAddress"), "base": (p.get("baseToken") or {}).get("symbol"),
                "base_addr": (p.get("baseToken") or {}).get("address"),
                "quote": (p.get("quoteToken") or {}).get("symbol"),
                "price_usd": p.get("priceUsd"), "liq_usd": (p.get("liquidity") or {}).get("usd"),
                "vol24_usd": (p.get("volume") or {}).get("h24"),
                "fdv": p.get("fdv"), "mcap": p.get("marketCap"),
            })
        out["dexscreener"][q] = pairs
        print(q, "->", [(p["chain"], p["dex"], p["pair"], p["liq_usd"]) for p in pairs[:5]])
    except Exception as exc:  # noqa: BLE001
        print(q, "ERR", exc)
    time.sleep(1.2)

for q in ["ondo gold", "xstock sp500", "ondo short term treasuries", "open eden tbill"]:
    try:
        d = get("https://api.coingecko.com/api/v3/search?query=" + urllib.parse.quote(q))
        coins = [{"id": c["id"], "sym": c["symbol"], "rank": c.get("market_cap_rank"),
                  "mcap": c.get("market_cap")} for c in d.get("coins", [])[:6]]
        out["coingecko"][q] = coins
        print("CG", q, "->", [(c["id"], c["sym"]) for c in coins])
    except Exception as exc:  # noqa: BLE001
        print("CG", q, "ERR", exc)
    time.sleep(6)

path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "t210_recon2.json")
with open(path, "w") as fh:
    json.dump(out, fh, indent=1, ensure_ascii=False)
print("WROTE", path)
