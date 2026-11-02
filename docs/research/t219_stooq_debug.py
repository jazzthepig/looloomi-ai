"""T-219 4j: stooq raw format debug (one shot)."""
import urllib.request

UA = {"User-Agent": "Mozilla/5.0 (research; cometcloud-lane-b)"}


def get(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=40) as r:
        return r.read().decode("utf-8", "replace")


for u in ["https://stooq.com/q/d/l/?s=crcl.us&i=d",
          "https://stooq.com/q/l/?s=crcl.us&f=sd2t2ohlcv&h&e=csv",
          "https://stooq.com/q/d/l/?s=gemi.us&i=d"]:
    try:
        t = get(u)
        lines = t.strip().split("\n")
        print("URL", u, "-> lines", len(lines))
        for l in lines[:4]:
            print("   ", l[:160])
    except Exception as e:
        print("URL", u, "ERR", str(e)[:100])
