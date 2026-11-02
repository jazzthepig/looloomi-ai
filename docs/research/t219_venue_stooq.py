"""T-219 step 4i: independent issuer cross-check + fallback-source coverage for the 10 rail tickers
via stooq public CSV (https://stooq.com/q/d/l/?s=<t>.us&i=d). Read-only GET, no trading.
NOTE: this script MEASURES availability only. Per T-219's gate, no rail risk profile is computed
from it this round (the card says: no warehouse rows => write "waiting for data" and stop).
"""
import urllib.request, urllib.error

UA = {"User-Agent": "Mozilla/5.0 (research; cometcloud-lane-b)"}
RAIL = ["CRCL", "COIN", "HOOD", "GLXY", "MSTR", "PYPL", "XYZ", "BLSH", "FIGR", "GEMI"]


def get(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=40) as r:
        return r.read().decode("utf-8", "replace")


print("ticker | stooq daily rows | first -> last | last close | identity check (stooq quote api)")
for tk in RAIL:
    try:
        csv = get("https://stooq.com/q/d/l/?s=%s.us&i=d" % tk.lower())
        lines = [x for x in csv.strip().split("\n") if x]
        if len(lines) < 2 or lines[0].lower().startswith("no data") or "," not in lines[0]:
            print("  %-6s -> %s" % (tk, lines[0][:60] if lines else "empty"))
            continue
        hdr = lines[0].split(",")
        di, ci = hdr.index("Date"), hdr.index("Close")
        rows = [l.split(",") for l in lines[1:]]
        print("  %-6s rows=%5d  %s -> %s  last_close=%s" %
              (tk, len(rows), rows[0][di], rows[-1][di], rows[-1][ci]))
    except urllib.error.HTTPError as e:
        print("  %-6s HTTP %s" % (tk, e.code))
    except Exception as e:
        print("  %-6s ERR %s" % (tk, str(e)[:70]))

print("\nissuer names via stooq quote api:")
for tk in RAIL:
    try:
        q = get("https://stooq.com/q/l/?s=%s.us&f=sd2t2ohlcvn&h&e=csv" % tk.lower())
        print("  %-6s %s" % (tk, q.strip().replace("\n", " | ")[:170]))
    except urllib.error.HTTPError as e:
        print("  %-6s HTTP %s" % (tk, e.code))
    except Exception as e:
        print("  %-6s ERR %s" % (tk, str(e)[:70]))
