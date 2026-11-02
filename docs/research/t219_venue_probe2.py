"""T-219 step 4b: venue facts. HL spot (read-only POST to the public /info endpoint),
Jupiter/DexScreener for Solana xStocks. No trading, no keys, no orders."""
import json, urllib.request, urllib.error, re

UA = {"User-Agent": "Mozilla/5.0 (research; cometcloud-lane-b)", "Content-Type": "application/json"}


def post_info(payload):
    req = urllib.request.Request("https://api.hyperliquid.xyz/info", data=json.dumps(payload).encode(),
                                 headers=UA, method="POST")
    with urllib.request.urlopen(req, timeout=45) as r:
        return json.loads(r.read().decode())


def get_json(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=45) as r:
        return json.loads(r.read().decode())


def get_text(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=45) as r:
        return r.read().decode("utf-8", "replace")


RAIL = ["CRCL", "COIN", "HOOD", "GLXY", "MSTR", "PYPL", "XYZ", "BLSH", "FIGR", "GEMI"]

print("########## HYPERLIQUID spotMeta")
try:
    sm = post_info({"type": "spotMeta"})
    tokens = sm.get("tokens", [])
    universe = sm.get("universe", [])
    print("tokens:", len(tokens), "pairs:", len(universe))
    names = [(t.get("name"), t.get("tokenId"), t.get("szDecimals"), t.get("index")) for t in tokens]
    hits = [n for n in names if any(re.search(r"\b" + r + r"\b", n[0] or "", re.I) for r in RAIL)]
    print("RAIL-named spot tokens:", hits)
    print("spot pair names (first 60):", [u.get("name") for u in universe[:60]])
    print("tokens sample:", names[:12])
except Exception as e:
    print("ERR", str(e)[:200])

print("\n########## HYPERLIQUID perpDexs (HIP-3)")
try:
    dx = post_info({"type": "perpDexs"})
    print("perp dexs:", json.dumps(dx)[:1200])
except Exception as e:
    print("ERR", str(e)[:200])

print("\n########## HYPERLIQUID perpMeta (asset names)")
try:
    pm = post_info({"type": "meta"})
    uni = pm.get("universe", [])
    print("perp count:", len(uni))
    print("names:", [a.get("name") for a in uni][:80])
except Exception as e:
    print("ERR", str(e)[:200])

print("\n########## JUPITER token search 'xstock'")
for url in ["https://api.jup.ag/tokens/v2/search?query=xstock",
            "https://api.jup.ag/tokens/v2/tag?query=xstocks"]:
    try:
        d = get_json(url)
        if isinstance(d, list):
            print(url, "->", len(d), "tokens")
            for t in d[:40]:
                print("   ", t.get("symbol"), "|", t.get("name"), "| id", t.get("id"), "| liq$",
                      round(t.get("liquidity") or 0), "| usd", t.get("usdPrice"))
        else:
            print(url, "->", json.dumps(d)[:300])
    except Exception as e:
        print(url, "ERR", str(e)[:120])
