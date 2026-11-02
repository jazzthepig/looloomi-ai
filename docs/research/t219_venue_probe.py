"""T-219 step 4: public-venue probe (read-only public GETs). No trading, no keys."""
import json, urllib.request, urllib.error

URLS = [
    ("HL spot meta (GET)", "https://api.hyperliquid.xyz/info/spotMeta"),
    ("HL perp meta (GET)", "https://api.hyperliquid.xyz/info/meta"),
    ("HL spot clearinghouse (GET)", "https://api.hyperliquid.xyz/info/spotClearinghouseState"),
    ("Jupiter xstocks search", "https://tokens.jup.ag/search?query=xstock"),
    ("DexScreener xstocks search", "https://api.dexscreener.com/latest/dex/search?q=xstocks"),
    ("Jupiter tokens v2 toptraded", "https://api.jup.ag/tokens/v2/toptraded/24h?limit=20"),
    ("Backed xStocks page", "https://xstocks.fi/"),
]

for name, url in URLS:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (research; cometcloud-lane-b)"})
        with urllib.request.urlopen(req, timeout=45) as r:
            body = r.read().decode("utf-8", "replace")
            print("=== %-32s HTTP %s  len=%d" % (name, r.status, len(body)))
            print(body[:700].replace("\n", " "))
            print()
    except urllib.error.HTTPError as e:
        print("=== %-32s HTTP %s" % (name, e.code))
        try:
            print(e.read().decode("utf-8", "replace")[:300])
        except Exception:
            pass
    except Exception as e:
        print("=== %-32s ERR %s" % (name, str(e)[:160]))
