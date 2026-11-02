"""T-219 step 4h: (a) which Nasdaq ticker belongs to the Gemini crypto exchange,
(b) Jupiter token details for the 5 Solana xStocks mints, (c) HL HIP-3 'xyz' perp state for rail names."""
import json, urllib.request, urllib.error

UA = {"User-Agent": "Mozilla/5.0 (research; cometcloud-lane-b)", "Content-Type": "application/json"}
RAIL = ["CRCL", "COIN", "HOOD", "GLXY", "MSTR", "PYPL", "XYZ", "BLSH", "FIGR", "GEMI"]
SOL_MINT = {"CRCL": "XsueG8BtpquVJX9LVLLEGuViXUungE6WmK5YZ3p3bd1",
            "COIN": "Xs7ZdzSHLU9ftNJsii5fCeJhoRWSC32SQGzGQtePxNu",
            "HOOD": "XsvNBAYkrDRNhA7wPHQfX3ZUXZyZLdnCQDfHZ56bzpg",
            "MSTR": "XsP7xzNPvEHS1m6qfanPUGjNmdnmsLKEoNAnHjdxxyZ",
            "GLXY": "Fi12y231dBD24XS2VoqvytMNcyC7gkZQ8gnMxNeEi8FE"}


def get(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=40) as r:
        return r.read().decode("utf-8", "replace")


def post_info(payload):
    req = urllib.request.Request("https://api.hyperliquid.xyz/info", data=json.dumps(payload).encode(),
                                 headers=UA, method="POST")
    with urllib.request.urlopen(req, timeout=45) as r:
        return json.loads(r.read().decode())


print("########## (a) Nasdaq issuer registry: candidates for the Gemini crypto exchange")
for tk in ["GEMI", "GEM", "GSIS", "GEMI", "GLXY", "BLSH", "FIGR", "XYZ", "MSTR", "HOOD", "COIN", "CRCL", "PYPL"]:
    try:
        d = json.loads(get("https://api.nasdaq.com/api/quote/%s/info?assetclass=stocks" % tk))
        dat = d.get("data") or {}
        if not dat:
            print("  %-6s -> (no data)" % tk)
        else:
            print("  %-6s -> %-40s %s" % (tk, (dat.get("companyName") or "")[:40], dat.get("exchange")))
    except urllib.error.HTTPError as e:
        print("  %-6s -> HTTP %s" % (tk, e.code))
    except Exception as e:
        print("  %-6s -> ERR %s" % (tk, str(e)[:50]))

print("\n########## (b) Jupiter token details for the 5 Solana xStocks mints")
for tk, mint in SOL_MINT.items():
    try:
        d = json.loads(get("https://tokens.jup.ag/token/" + mint))
        info = d.get("info") or {}
        print("  %-5s sym=%-9s name=%-26s org=%-24s website=%s" %
              (tk, d.get("symbol"), (d.get("name") or "")[:26], (info.get("organization") or "")[:24],
               info.get("website")))
        print("        liquidity=$%s  usdPrice=%s  holderCount=%s  created=%s  tags=%s" %
              (round(d.get("liquidity") or 0), d.get("usdPrice"), d.get("holderCount"),
               (info.get("createdAt") or "")[:10], d.get("tags")))
    except urllib.error.HTTPError as e:
        print("  %-5s HTTP %s" % (tk, e.code))
    except Exception as e:
        print("  %-5s ERR %s" % (tk, str(e)[:90]))

print("\n########## (c) HL HIP-3 xyz dex: perp state for rail names")
try:
    pm = post_info({"type": "meta", "dex": "xyz"})
    uni = pm.get("universe", [])
    print("  xyz universe sample names:", [a.get("name") for a in uni[:15]])
    mact = post_info({"type": "metaAndAssetCtxs", "dex": "xyz"})
    ctxs = mact[1] if isinstance(mact, list) and len(mact) > 1 else mact
    for j, a in enumerate(uni):
        nm = (a.get("name") or "").upper()
        if nm in RAIL:
            c = ctxs[j] if j < len(ctxs) else {}
            print("   %-6s mark=%-10s oi=%-12s vol24=%-14s funding=%s" %
                  (nm, c.get("markPx"), c.get("openInterest"), c.get("dayNtlVlm"), c.get("funding")))
except Exception as e:
    print("  ERR", str(e)[:200])
