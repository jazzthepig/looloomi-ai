"""T-219 step 4l: (a) issuer resolution for GEMI via Wikipedia public API,
(b) HL funding interval for the xyz equity perps (raw rate, no annualisation guess)."""
import json, urllib.request, urllib.parse

UA = {"User-Agent": "Mozilla/5.0 (research; cometcloud-lane-b)", "Content-Type": "application/json"}


def get_json(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.loads(r.read().decode())


def post_info(payload):
    req = urllib.request.Request("https://api.hyperliquid.xyz/info", data=json.dumps(payload).encode(),
                                 headers=UA, method="POST")
    with urllib.request.urlopen(req, timeout=45) as r:
        return json.loads(r.read().decode())


print("########## (a) Wikipedia search for the Gemini issuers")
for q in ["Gemini Global Group", "Gemini Space Station", "Figure Technology Solutions",
          "Bullish (company)", "Galaxy Digital"]:
    try:
        u = "https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode(
            {"action": "query", "list": "search", "srsearch": q, "format": "json", "srlimit": 3})
        d = get_json(u)
        hits = [(x["title"], x.get("snippet", "")[:110].replace("<span class=\"searchmatch\">", "")
                 .replace("</span>", "")) for x in d.get("query", {}).get("search", [])]
        print("  %-28s -> %s" % (q, hits[:2]))
    except Exception as e:
        print("  %-28s ERR %s" % (q, str(e)[:80]))

print("\n########## (a2) wikipedia summaries: ticker / exchange claims")
for title in ["Gemini Global Group", "Gemini Space Station", "Coinbase", "Robinhood Markets",
              "Bullish (company)", "Galaxy Digital Inc.", "Figure (company)", "Strategy (company)",
              "Block, Inc.", "Circle Internet Group", "PayPal"]:
    try:
        d = get_json("https://en.wikipedia.org/api/rest_v1/page/summary/" + urllib.parse.quote(title))
        ext = d.get("extract") or ""
        print("  %-24s %s" % (title, ext[:170].replace("\n", " ")))
    except Exception as e:
        print("  %-24s ERR %s" % (title, str(e)[:70]))

print("\n########## (b) HL funding interval check (xyz:COIN)")
try:
    fh = post_info({"type": "fundingHistory", "coin": "xyz:COIN", "startTime": 1767225600000})
    print("  points:", len(fh))
    for x in fh[:6]:
        print("   ", x)
except Exception as e:
    print("  ERR", str(e)[:150])
