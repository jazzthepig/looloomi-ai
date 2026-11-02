"""T-219 step 4m: 24h average funding for the xyz equity perps (hourly series verified) + issuer pages."""
import json, urllib.request, time, urllib.parse

UA = {"User-Agent": "Mozilla/5.0 (research; cometcloud-lane-b)", "Content-Type": "application/json"}


def post_info(payload):
    req = urllib.request.Request("https://api.hyperliquid.xyz/info", data=json.dumps(payload).encode(),
                                 headers=UA, method="POST")
    with urllib.request.urlopen(req, timeout=45) as r:
        return json.loads(r.read().decode())


def get_text(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=40) as r:
        return r.read().decode("utf-8", "replace")


print("########## 24h average hourly funding for xyz equity perps (annualised x24x365)")
for coin in ["xyz:CRCL", "xyz:COIN", "xyz:MSTR", "xyz:HOOD"]:
    try:
        fh = post_info({"type": "fundingHistory", "coin": coin, "startTime": 1767225600000})
        pts = sorted(fh, key=lambda x: x["time"])
        last24 = pts[-24:]
        rates = [float(p["fundingRate"]) for p in last24]
        avg = sum(rates) / len(rates)
        pos = sum(1 for r in rates if r > 0)
        print("  %-9s last24h mean=%+.8f  ann=%+.1f%%  positive %d/24  min=%+.8f max=%+.8f  span_hours=%.1f"
              % (coin, avg, avg * 24 * 365 * 100, pos, min(rates), max(rates),
                 (pts[-1]["time"] - pts[0]["time"]) / 3600000.0))
    except Exception as e:
        print("  %-9s ERR %s" % (coin, str(e)[:120]))

time.sleep(3)
print("\n########## wikipedia pages for the two Gemini issuers")
for title in ["Gemini_(cryptocurrency_exchange)", "Gemini_Space_Station"]:
    try:
        t = get_text("https://en.wikipedia.org/api/rest_v1/page/summary/" + title)
        d = json.loads(t)
        print("  %-34s %s" % (title, (d.get("extract") or "")[:300].replace("\n", " ")))
    except Exception as e:
        print("  %-34s ERR %s" % (title, str(e)[:80]))
        time.sleep(2)
