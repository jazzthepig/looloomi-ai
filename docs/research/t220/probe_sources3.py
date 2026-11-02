#!/usr/bin/env python3
"""T-220 ① 第三轮:公开页面里到底有没有解锁数据 / 标签页要不要 key / robots 与 ToS。"""
import json
import re
import ssl
import urllib.request
import urllib.error

HERE = "/Volumes/CometCloudAI/cometcloud-local/research/t220/"
CTX = ssl.create_default_context()
UA = {"User-Agent": "Mozilla/5.0 (cometcloud research feasibility probe)"}
ADDR = "0x28C6c06298d514Db089934071355E5743bf21d60"


def get(u, timeout=45):
    try:
        req = urllib.request.Request(u, headers=UA)
        with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()[:400]
    except Exception as e:  # noqa: BLE001
        return -1, repr(e).encode()[:300]


out = {}

# 1) defillama.com/unlocks 页面里有没有内嵌解锁数据
st, b = get("https://defillama.com/unlocks")
open(HERE + "_dl_unlocks_page.html", "wb").write(b)
txt = b.decode("utf-8", "replace")
hits = {}
for kw in ("nextUnlock", "unlockDate", "unlocks", "vesting", "team", "advisor", "investor", "treasury",
           "api.llama", "__NEXT_DATA__"):
    hits[kw] = txt.count(kw)
print("defillama.com/unlocks status", st, "len", len(b), "kw counts:", hits, flush=True)
out["dl_unlocks_page"] = {"status": st, "len": len(b), "kw": hits}
m = re.search(r'"__NEXT_DATA__"[^>]*>(.{0,400})', txt)
if m:
    print("NEXT_DATA head:", m.group(1)[:300], flush=True)

# 2) 公开页面里出现的 llama API 路径(前端取数走哪)
paths = sorted(set(re.findall(r"https://[a-z0-9.\-]*llama[a-z0-9.\-]*/[A-Za-z0-9/_\-]+", txt)))
print("llama endpoints referenced in page:", paths[:20], flush=True)
out["dl_unlocks_page_llama_endpoints"] = paths[:40]

# 3) Etherscan 地址页(无 key 的公开 GET)是否带标签
st, b = get(f"https://etherscan.io/address/{ADDR}")
t2 = b.decode("utf-8", "replace")
print("etherscan address page:", st, "len", len(b),
      "| has 'Binance' label:", ("Binance" in t2), "| 'Centralized Exchange' in tags:", ("Centralized Exchange" in t2), flush=True)
out["etherscan_addr_page"] = {"status": st, "len": len(b), "has_binance": "Binance" in t2}

# 4) robots.txt
for host in ["https://etherscan.io/robots.txt", "https://api.llama.fi/robots.txt",
             "https://defillama.com/robots.txt", "https://api.coingecko.com/robots.txt"]:
    st, b = get(host, timeout=30)
    body = b.decode("utf-8", "replace")
    lines = [l for l in body.splitlines() if l.strip()][:14]
    print(f"\n--- {host} [{st}] ---", flush=True)
    for l in lines:
        print("   ", l[:120], flush=True)
    out[host] = {"status": st, "head": "\n".join(lines)[:1200]}

# 5) openchain 标签 API 路径猜测
for u in ["https://api.openchain.xyz/", "https://api.openchain.xyz/v1/label/" + ADDR,
          "https://openchain.xyz/api/v1/address/" + ADDR]:
    st, b = get(u, timeout=30)
    print(f"openchain {u} -> {st} :: {b[:120].decode('utf-8','replace')}", flush=True)
    out[u] = {"status": st, "head": b[:200].decode("utf-8", "replace")}

# 6) santiment 无 key 的 GraphQL
q = json.dumps({"query": "{ getAllTimeseriesMetrics(metrics: [\"price_usd\"]) { slug } }"})
try:
    req = urllib.request.Request("https://api.santiment.net/graphql", data=q.encode(),
                                 headers={"Content-Type": "application/json", **UA})
    with urllib.request.urlopen(req, timeout=40) as r:
        body = r.read()
        print("santiment graphql:", r.status, body[:250].decode("utf-8", "replace"), flush=True)
        out["santiment_graphql"] = {"status": r.status, "head": body[:300].decode("utf-8", "replace")}
except urllib.error.HTTPError as e:
    b = e.read()
    print("santiment graphql:", e.code, b[:250].decode("utf-8", "replace"), flush=True)
    out["santiment_graphql"] = {"status": e.code, "head": b[:300].decode("utf-8", "replace")}
except Exception as e:  # noqa: BLE001
    print("santiment graphql err", repr(e)[:200], flush=True)

json.dump(out, open(HERE + "_sources3.json", "w"), ensure_ascii=False, indent=1)
print("\nsaved _sources3.json")
