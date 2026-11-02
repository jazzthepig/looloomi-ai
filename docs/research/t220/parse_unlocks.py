#!/usr/bin/env python3
"""T-220 ①:把 defillama.com/unlocks 公开页的 __NEXT_DATA__ 解析出来,看解锁日程字段是否齐全、覆盖哪些币。"""
import json
import re
from collections import Counter

HERE = "/Volumes/CometCloudAI/cometcloud-local/research/t220/"
html = open(HERE + "_dl_unlocks_page.html", encoding="utf-8", errors="replace").read()
m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.S)
if not m:
    print("no __NEXT_DATA__")
    raise SystemExit(1)
d = json.loads(m.group(1))
pp = d.get("props", {}).get("pageProps", {})
print("pageProps keys:", list(pp.keys()), flush=True)
data = pp.get("data", [])
print("entries:", len(data), flush=True)
if data:
    print("entry keys:", sorted(data[0].keys()), flush=True)
    # 字段统计
    keycnt = Counter()
    for e in data:
        keycnt.update(e.keys())
    print("key coverage over entries:", {k: v for k, v in keycnt.most_common()}, flush=True)
    # 日期类字段
    datekeys = set()
    for e in data:
        for k, v in e.items():
            if isinstance(v, str) and re.match(r"^\d{4}-\d{2}-\d{2}", v):
                datekeys.add(k)
    print("date-like fields:", sorted(datekeys), flush=True)
    # 找解锁相关字段的样本
    for e in data[:2]:
        print(json.dumps(e, ensure_ascii=False)[:1200], flush=True)
    # 类别字段
    for k in ("unlockSchedule", "unlocks", "categories", "vestings", "nextUnlock", "unlockDate"):
        vals = [e.get(k) for e in data if k in e]
        if vals:
            print(f"\nfield {k}: present in {len(vals)} entries; sample:", json.dumps(vals[0], ensure_ascii=False)[:900], flush=True)
    # 覆盖:里面出现哪些 CIS 25 名字 / gecko slug
    CIS = ["AAVE", "ADA", "APT", "ARB", "AVAX", "BNB", "BTC", "DOT", "ETH", "HYPE", "INJ", "LDO",
           "LINK", "NEAR", "ONDO", "OP", "PENDLE", "POL", "SKY", "SOL", "STRK", "SUI", "TIA", "UNI", "XRP"]
    names = {e.get("name"): e for e in data}
    hits = []
    for s in CIS:
        f = [n for n in names if n and n.upper() == s]
        hits.append((s, f))
    print("\nCIS25 by exact name:", hits, flush=True)
    slugs = sorted({e.get("protocolSlug") for e in data if e.get("protocolSlug")})
    print("n protocol slugs in page:", len(slugs), flush=True)
    print("slug sample:", slugs[:40], flush=True)
    for s in ("aave", "pendle", "celestia", "uniswap", "ondo-finance", "injective-protocol", "chainlink",
              "hyperliquid", "aptos", "arbitrum", "optimism", "polygon", "sui", "starknet", "lido-dao",
              "near", "cardano", "avalanche", "polkadot", "ripple", "solana", "binancecoin"):
        print("  slug present:", s, s in slugs, flush=True)
    json.dump({"n_entries": len(data), "entry_keys": sorted(data[0].keys()),
               "date_like_fields": sorted(datekeys),
               "slugs": slugs,
               "sample": data[:3]},
              open(HERE + "_dl_unlocks_parsed.json", "w"), ensure_ascii=False, indent=1)
