"""T-219 step 4k: HL HIP-3 'xyz' equity-perp dex: full asset list + rail names' perp state;
Nasdaq GEMI detail (sector / market cap) for issuer cross-check."""
import json, urllib.request, urllib.error

UA = {"User-Agent": "Mozilla/5.0 (research; cometcloud-lane-b)", "Content-Type": "application/json"}
RAIL = ["CRCL", "COIN", "HOOD", "GLXY", "MSTR", "PYPL", "XYZ", "BLSH", "FIGR", "GEMI"]


def post_info(payload):
    req = urllib.request.Request("https://api.hyperliquid.xyz/info", data=json.dumps(payload).encode(),
                                 headers=UA, method="POST")
    with urllib.request.urlopen(req, timeout=45) as r:
        return json.loads(r.read().decode())


def get(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=40) as r:
        return r.read().decode("utf-8", "replace")


print("########## HL HIP-3 xyz dex: all 141 asset names")
pm = post_info({"type": "meta", "dex": "xyz"})
uni = pm.get("universe", [])
names = [(a.get("name") or "") for a in uni]
print("  ", ", ".join(names))
print("\n########## rail names present in xyz dex (prefixed names)")
mact = post_info({"type": "metaAndAssetCtxs", "dex": "xyz"})
ctxs = mact[1] if isinstance(mact, list) and len(mact) > 1 else mact
for j, a in enumerate(uni):
    nm = (a.get("name") or "").upper()
    short = nm.split(":")[-1]
    if short in RAIL:
        c = ctxs[j] if j < len(ctxs) else {}
        print("   %-12s mark=%-10s oi=%-14s vol24=%-16s funding=%s" %
              (nm, c.get("markPx"), c.get("openInterest"), c.get("dayNtlVlm"), c.get("funding")))

print("\n########## Nasdaq GEMI detail")
for u in ["https://api.nasdaq.com/api/quote/GEMI/summary?assetclass=stocks",
          "https://api.nasdaq.com/api/quote/GEMI/info?assetclass=stocks"]:
    try:
        d = json.loads(get(u))
        print(" ", u.split("/")[-1], json.dumps(d.get("data"))[:600])
    except urllib.error.HTTPError as e:
        print(" ", u, "HTTP", e.code)
    except Exception as e:
        print(" ", u, "ERR", str(e)[:80])
