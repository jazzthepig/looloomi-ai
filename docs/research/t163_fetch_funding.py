"""T-163 fetch step 2: funding_history(binance_perp) for the members that have it. Retries, 4 workers."""
import json, os, sys, time, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor

URL = os.environ["SUPABASE_URL"]
KEY = os.environ["SUPABASE_KEY"]
ENV = "/Volumes/CometCloudAI/cometcloud-local/research/t163/"
HDR = {"apikey": KEY, "Authorization": "Bearer " + KEY}
FUND_FROM, TO = "2019-08-01", "2026-09-30"


def rest(q, lo, hi, tries=5):
    last = None
    for k in range(tries):
        try:
            r = urllib.request.Request(URL + "/rest/v1/" + q, headers=dict(HDR, Range=f"{lo}-{hi}"))
            return json.loads(urllib.request.urlopen(r, timeout=300).read())
        except Exception as e:                                    # noqa: BLE001
            last = e
            time.sleep(1.5 * (k + 1))
    raise last


def page_all(q, cap, tries=5):
    out, off = [], 0
    while True:
        rows = rest(q, off, off + 999, tries)
        if not rows:
            break
        out += rows
        off += 1000
        if len(rows) < 1000 or off >= cap * 1000:
            break
    return out


def fund_for(sym):
    q = (f"funding_history?select=funding_time,funding_rate&venue=eq.binance_perp&symbol=eq.{sym}"
         f"&funding_time=gte.{FUND_FROM}&funding_time=lte.{TO}&order=funding_time.asc")
    try:
        rows = page_all(q, 20)
    except Exception as e:                                         # noqa: BLE001
        print("FAIL", sym, repr(e)[:80], file=sys.stderr)
        return sym, []
    return sym, [[r["funding_time"][:10], r["funding_rate"]] for r in rows]


syms = []
for line in open(ENV + "bars.jsonl"):
    syms.append(json.loads(line)["symbol"])
print("members:", len(syms), file=sys.stderr)
with ThreadPoolExecutor(max_workers=4) as ex:
    got = list(ex.map(fund_for, syms))
with open(ENV + "funding.jsonl", "w") as f:
    n = 0
    for sym, rows in got:
        if rows:
            f.write(json.dumps({"symbol": sym, "funding": rows}) + "\n")
            n += len(rows)
print("funding rows:", n, "symbols:", sum(1 for s, r in got if r), file=sys.stderr)