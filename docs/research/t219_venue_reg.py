"""T-219 step 4f: HL token raw records; candidate canonical xStocks registries; US listing venue."""
import json, urllib.request, urllib.error

UA = {"User-Agent": "Mozilla/5.0 (research; cometcloud-lane-b)", "Content-Type": "application/json"}
RAIL = ["CRCL", "COIN", "HOOD", "GLXY", "MSTR", "PYPL", "XYZ", "BLSH", "FIGR", "GEMI"]


def post_info(payload):
    req = urllib.request.Request("https://api.hyperliquid.xyz/info", data=json.dumps(payload).encode(),
                                 headers=UA, method="POST")
    with urllib.request.urlopen(req, timeout=45) as r:
        return json.loads(r.read().decode())


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA["User-Agent"]})
    with urllib.request.urlopen(req, timeout=40) as r:
        return r.status, r.read().decode("utf-8", "replace")


print("########## HL spot token raw records (rail-named)")
meta = post_info({"type": "spotMetaAndAssetCtxs"})
smeta = meta[0]
for t in smeta["tokens"]:
    if (t.get("name") or "").upper() in RAIL:
        print(" ", json.dumps(t))
print("  universe entries whose name is not a real pair (sample):")
for p in smeta["universe"]:
    if p.get("name", "").startswith("@"):
        idxs = p.get("tokens") or []
        names = [smeta["tokens"][i]["name"] for i in idxs if i < len(smeta["tokens"])]
        if any(n.upper() in RAIL for n in names):
            print("   ", p.get("name"), "tokens", idxs, names, "isCanonical", p.get("isCanonical"))

print("\n########## candidate canonical xStocks registries")
CANDS = [
    "https://api.backed.fi/api/xstocks",
    "https://api.backed.fi/xstocks",
    "https://api.backed.fi/api/v1/xstocks",
    "https://backed.exchange/api/tokens",
    "https://api.backed.exchange/tokens",
    "https://xstocks.fi/api/tokens",
    "https://www.backed.fi/api/tokens",
    "https://tokens.backed.fi/api",
]
for u in CANDS:
    try:
        st, body = get(u)
        print("  %-42s HTTP %s len=%d :: %s" % (u, st, len(body), body[:160].replace("\n", " ")))
    except urllib.error.HTTPError as e:
        print("  %-42s HTTP %s" % (u, e.code))
    except Exception as e:
        print("  %-42s ERR %s" % (u, str(e)[:80]))

print("\n########## US listing venue (nasdaq public quote api)")
for tk in RAIL:
    try:
        st, body = get("https://api.nasdaq.com/api/quote/%s/info?assetclass=stocks" % tk)
        d = json.loads(body)
        dat = (d.get("data") or {})
        if not dat:
            print("  %-6s -> no data" % tk)
            continue
        print("  %-6s -> %-28s exchange=%s symbol=%s" % (
            tk, (dat.get("companyName") or "")[:28], dat.get("exchange"), dat.get("symbol")))
    except urllib.error.HTTPError as e:
        print("  %-6s -> HTTP %s" % (tk, e.code))
    except Exception as e:
        print("  %-6s -> ERR %s" % (tk, str(e)[:60]))
