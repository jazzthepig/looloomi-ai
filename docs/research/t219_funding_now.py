"""T-219 step 4n: funding for the last 24h (proper startTime) + current snapshot for xyz equity perps."""
import json, urllib.request, time

UA = {"User-Agent": "Mozilla/5.0 (research; cometcloud-lane-b)", "Content-Type": "application/json"}


def post_info(payload):
    req = urllib.request.Request("https://api.hyperliquid.xyz/info", data=json.dumps(payload).encode(),
                                 headers=UA, method="POST")
    with urllib.request.urlopen(req, timeout=45) as r:
        return json.loads(r.read().decode())


now = int(time.time() * 1000)
print("now_ms", now, "utc", time.strftime("%Y-%m-%d %H:%M", time.gmtime(now / 1000)))
print("\ncoin      | last24h mean hourly | ann% | pos/24 | min | max | current ctx funding | ann%")
for coin in ["xyz:CRCL", "xyz:COIN", "xyz:MSTR", "xyz:HOOD"]:
    try:
        fh = post_info({"type": "fundingHistory", "coin": coin, "startTime": now - 26 * 3600 * 1000})
        pts = sorted(fh, key=lambda x: x["time"])
        recent = [p for p in pts if p["time"] >= now - 25 * 3600 * 1000]
        rates = [float(p["fundingRate"]) for p in recent] or [float(p["fundingRate"]) for p in pts[-24:]]
        avg = sum(rates) / len(rates)
        pos = sum(1 for r in rates if r > 0)
        # current context
        pm = post_info({"type": "metaAndAssetCtxs", "dex": "xyz"})
        uni = pm[0].get("universe", [])
        ctxs = pm[1]
        cur = None
        for j, a in enumerate(uni):
            if (a.get("name") or "").upper() == coin.upper():
                cur = float((ctxs[j] or {}).get("funding") or 0)
        print("  %-9s | %+.8f | %+6.1f%% | %2d/24 | %+.8f | %+.8f | %+.8f | %+6.1f%%  (n=%d, hours covered %.1f)"
              % (coin, avg, avg * 24 * 365 * 100, pos, min(rates), max(rates), cur, cur * 24 * 365 * 100,
                 len(rates), (pts[-1]["time"] - pts[0]["time"]) / 3600000.0))
    except Exception as e:
        print("  %-9s ERR %s" % (coin, str(e)[:120]))
