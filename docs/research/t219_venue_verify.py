"""T-219 step 4g: (a) xstocks.fi page: canonical contract addresses vs HL evmContract + Solana mints,
(b) issuer verification for GEMI (ticker may collide), (c) Nasdaq last sale for cross-check."""
import json, re, urllib.request, urllib.error

UA = {"User-Agent": "Mozilla/5.0 (research; cometcloud-lane-b)"}
RAIL = ["CRCL", "COIN", "HOOD", "GLXY", "MSTR", "PYPL", "XYZ", "BLSH", "FIGR", "GEMI"]
HL_EVM = {"CRCL": "0xe74aa6c4050a15790525eb11cc4562c664dc67c9",
          "HOOD": "0xc304a9d52cf9165024ebc7814250ef3a5013f924"}
SOL_MINT = {"CRCL": "XsueG8BtpquVJX9LVLLEGuViXUungE6WmK5YZ3p3bd1",
            "COIN": "Xs7ZdzSHLU9ftNJsii5fCeJhoRWSC32SQGzGQtePxNu",
            "HOOD": "XsvNBAYkrDRNhA7wPHQfX3ZUXZyZLdnCQDfHZ56bzpg",
            "MSTR": "XsP7xzNPvEHS1m6qfanPUGjNmdnmsLKEoNAnHjdxxyZ",
            "GLXY": "Fi12y231dBD24XS2VoqvytMNcyC7gkZQ8gnMxNeEi8FE"}


def get(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=40) as r:
        return r.read().decode("utf-8", "replace")


print("########## (a) xstocks.fi HTML: addresses + mints present?")
html = get("https://xstocks.fi/")
addrs = set(a.lower() for a in re.findall(r"0x[0-9a-fA-F]{40}", html))
mints = set(m for m in re.findall(r"\b[1-9A-HJ-NP-Za-km-z]{40,50}\b", html))
print("  0x addrs on page:", len(addrs), "| base58-ish strings:", len(mints))
for k, v in HL_EVM.items():
    print("  HL evmContract %-5s %s on page: %s" % (k, v, v.lower() in addrs))
for k, v in SOL_MINT.items():
    print("  Solana mint   %-5s %s on page: %s" % (k, v, v in mints))
for key in ("contractAddress", "mint", "chainId", "address", "ticker"):
    m = re.search(r'"' + key + r'"\s*:', html)
    print("  key %-16s present: %s" % (key, bool(m)))
for needle in ("Circle", "Coinbase", "Robinhood", "Galaxy", "Block", "PayPal", "Bullish", "Figure", "Gemini"):
    print("  name %-10s occurrences: %d" % (needle, len(re.findall(needle, html))))

print("\n########## (b) Nasdaq: resolve GEMI + last sale for all 10")
for tk in RAIL:
    try:
        d = json.loads(get("https://api.nasdaq.com/api/quote/%s/info?assetclass=stocks" % tk))
        dat = d.get("data") or {}
        try:
            s = json.loads(get("https://api.nasdaq.com/api/quote/%s/summary?assetclass=stocks" % tk))
            pd = ((s.get("data") or {}).get("primaryData") or {})
            last = pd.get("lastSalePrice") or "-"
        except Exception:
            last = "-"
        print("  %-6s %-34s %-12s last=%s" % (tk, (dat.get("companyName") or "")[:34], dat.get("exchange"), last))
    except urllib.error.HTTPError as e:
        print("  %-6s HTTP %s" % (tk, e.code))
    except Exception as e:
        print("  %-6s ERR %s" % (tk, str(e)[:60]))

print("\n########## (c) Nasdaq search 'Gemini'")
try:
    d = json.loads(get("https://api.nasdaq.com/api/search?q=Gemini"))
    rows = ((d.get("data") or {}).get("rows") or [])
    for r in rows[:8]:
        print("  ", json.dumps(r)[:220])
except Exception as e:
    print("  ERR", str(e)[:120])
