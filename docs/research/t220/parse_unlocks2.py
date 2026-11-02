#!/usr/bin/env python3
"""T-220 ①:解公开 unlocks 页对 CIS 25 名的覆盖 + 解锁事件是否含历史(PIT 可行性)。"""
import datetime as dt
import json
import re

HERE = "/Volumes/CometCloudAI/cometcloud-local/research/t220/"
html = open(HERE + "_dl_unlocks_page.html", encoding="utf-8", errors="replace").read()
d = json.loads(re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.S).group(1))
pp = d["props"]["pageProps"]
data = pp["data"]
print("unlockTypes:", json.dumps(pp.get("unlockTypes"), ensure_ascii=False)[:400], flush=True)
print("generatedAtSec:", pp.get("generatedAtSec"), "pageClockSec:", pp.get("pageClockSec"), flush=True)
print("nextWeekUnlocksSentence:", str(pp.get("nextWeekUnlocksSentence"))[:200], flush=True)
print("upcomingUnlockStatistics:", json.dumps(pp.get("upcomingUnlockStatistics"), ensure_ascii=False)[:400], flush=True)
print("topUnlocks24d len:", len(pp.get("topUnlocks24h") or []), " topUnlocks30d len:", len(pp.get("topUnlocks30d") or []), flush=True)

CIS_GID = {"AAVE": "aave", "ADA": "cardano", "APT": "aptos", "ARB": "arbitrum", "AVAX": "avalanche-2",
           "BNB": "binancecoin", "BTC": "bitcoin", "DOT": "polkadot", "ETH": "ethereum",
           "HYPE": "hyperliquid", "INJ": "injective-protocol", "LDO": "lido-dao", "LINK": "chainlink",
           "NEAR": "near", "ONDO": "ondo-finance", "OP": "optimism", "PENDLE": "pendle",
           "POL": "polygon-ecosystem-token", "SKY": "sky", "SOL": "solana", "STRK": "starknet",
           "SUI": "sui", "TIA": "celestia", "UNI": "uniswap", "XRP": "ripple"}
by_gid = {}
for e in data:
    g = e.get("gecko_id")
    if g:
        by_gid.setdefault(g, []).append(e)

print("\n=== CIS 25 名在公开 unlocks 页的覆盖 ===", flush=True)
cover = {}
for sym, gid in CIS_GID.items():
    ents = by_gid.get(gid, [])
    if not ents:
        cover[sym] = {"covered": False}
        print(f"{sym:6s} gecko_id={gid:26s} 未命中", flush=True)
        continue
    e = ents[0]
    ue = e.get("upcomingEvent") or []
    cats = sorted({u.get("category") for u in ue if u.get("category")})
    ue_dates = [dt.datetime.utcfromtimestamp(u["timestamp"]).date().isoformat()
                for u in ue if u.get("timestamp")]
    ux = e.get("unlockEvents")
    ux_dates = []
    if ux:
        for u in ux:
            t = u.get("timestamp") or u.get("date")
            if t:
                ux_dates.append(dt.datetime.utcfromtimestamp(int(t)).date().isoformat())
    ne = e.get("nextEvent") or {}
    ne_d = dt.datetime.utcfromtimestamp(ne["date"]).date().isoformat() if ne.get("date") else None
    cover[sym] = {"covered": True, "name": e.get("name"), "protocolSlug": e.get("protocolSlug"),
                  "token": e.get("token"), "maxSupply": e.get("maxSupply"),
                  "circSupply": e.get("circSupply"), "totalLocked": e.get("totalLocked"),
                  "nextEvent_date": ne_d, "nextEvent_type": (e.get("nextEventV2") or {}).get("unlockType"),
                  "n_upcomingEvent": len(ue), "upcoming_categories": cats,
                  "upcoming_dates": ue_dates[:6],
                  "unlockEvents_null": ux is None,
                  "unlockEvents_n": (len(ux) if ux else 0),
                  "unlockEvents_date_min": min(ux_dates) if ux_dates else None,
                  "unlockEvents_date_max": max(ux_dates) if ux_dates else None,
                  "has_historical_events": bool(ux_dates and min(ux_dates) < dt.date.today().isoformat())}
    print(f"{sym:6s} {e.get('name'):22s} slug={str(e.get('protocolSlug')):22s} "
          f"next={ne_d} type={cover[sym]['nextEvent_type']} n_upcoming={len(ue)} cats={cats} "
          f"unlockEvents_null={ux is None} ux_dates={cover[sym]['unlockEvents_date_min']}..{cover[sym]['unlockEvents_date_max']}", flush=True)

n_cov = sum(1 for v in cover.values() if v.get("covered"))
print(f"\n覆盖 {n_cov}/25", flush=True)

# 全页:有多少条目带非空 unlockEvents(历史事件)?其中最早日期?
hist = []
for e in data:
    ux = e.get("unlockEvents")
    if not ux:
        continue
    for u in ux:
        t = u.get("timestamp") or u.get("date")
        if t:
            hist.append((dt.datetime.utcfromtimestamp(int(t)).date().isoformat(), e.get("name"), u.get("category")))
hist.sort()
print("带历史事件(非空 unlockEvents)的条目数:", sum(1 for e in data if e.get("unlockEvents")),
      "| 历史事件条数:", len(hist), flush=True)
if hist:
    print("最早 5 条:", hist[:5], flush=True)
    print("最晚 5 条:", hist[-5:], flush=True)
    cats = {}
    for _, _, c in hist:
        cats[c] = cats.get(c, 0) + 1
    print("历史事件类别分布:", cats, flush=True)

# 全页类别
allcats = {}
for e in data:
    for u in (e.get("upcomingEvent") or []):
        c = u.get("category")
        allcats[c] = allcats.get(c, 0) + 1
print("upcomingEvent 类别分布:", allcats, flush=True)

json.dump({"cover": cover, "n_covered": n_cov,
           "n_entries_with_unlockEvents": sum(1 for e in data if e.get("unlockEvents")),
           "n_historical_events": len(hist),
           "historical_sample": hist[:10] + hist[-10:],
           "upcoming_categories": allcats},
          open(HERE + "_dl_unlocks_cover.json", "w"), ensure_ascii=False, indent=1)
print("saved _dl_unlocks_cover.json")
