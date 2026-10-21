"""T-163 fetch: style_index_pit_daily + ohlcv_daily(binance_hist) closes + funding_history(binance_perp).

Read-only, publishable key. Caches into /Volumes/CometCloudAI/cometcloud-local/research/t163/.
PostgREST here caps every response at 1000 rows, so everything is paged via the Range header.
"""
import json, os, string, sys, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor

URL = os.environ["SUPABASE_URL"]
KEY = os.environ["SUPABASE_KEY"]
ENV = "/Volumes/CometCloudAI/cometcloud-local/research/t163/"
HDR = {"apikey": KEY, "Authorization": "Bearer " + KEY}
BAR_FROM = "2019-08-01"          # ≥ 50d MA + 30d return for the first style day (2020-01-01)
FUND_FROM = "2019-08-01"
TO = "2026-09-30"                # last t (2026-08-31) + 30d outcome


def rest(q, lo=0, hi=999):
    r = urllib.request.Request(URL + "/rest/v1/" + q, headers=dict(HDR, Range=f"{lo}-{hi}"))
    try:
        return json.loads(urllib.request.urlopen(r, timeout=300).read())
    except urllib.error.HTTPError as e:
        if e.code == 416:
            return []
        raise


def page_all(q, cap):
    out, off = [], 0
    while True:
        rows = rest(q, off, off + 999)
        if not rows:
            break
        out += rows
        off += 1000
        if len(rows) < 1000 or off >= cap * 1000:
            break
    return out


def member_universe():
    rows = json.load(open(ENV + "styles.json"))
    syms = set()
    for r in rows:
        for m in (r.get("members") or []):
            if re_sym(m):
                syms.add(m)
    return sorted(syms)


def re_sym(s):
    return s.isascii() and s.isupper() and 1 <= len(s) <= 15


def bars_for(sym):
    q = (f"ohlcv_daily?select=trade_date,close&source=eq.binance_hist&symbol=eq.{sym}"
         f"&trade_date=gte.{BAR_FROM}&trade_date=lte.{TO}&order=trade_date.asc")
    rows = page_all(q, 12)
    return [sym, [[r["trade_date"], r["close"]] for r in rows]]


def fund_probe(sym):
    q = (f"funding_history?select=funding_time&venue=eq.binance_perp&symbol=eq.{sym}"
         f"&funding_time=gte.{FUND_FROM}&funding_time=lte.{TO}&order=funding_time.asc")
    r = rest(q, 0, 0)
    return sym, len(r) > 0


def fund_for(sym):
    q = (f"funding_history?select=funding_time,funding_rate&venue=eq.binance_perp&symbol=eq.{sym}"
         f"&funding_time=gte.{FUND_FROM}&funding_time=lte.{TO}&order=funding_time.asc")
    rows = page_all(q, 20)
    out = []
    for r in rows:
        t = r["funding_time"][:10]
        out.append([t, r["funding_rate"]])
    return sym, out


def main():
    os.makedirs(ENV, exist_ok=True)
    syms = member_universe()
    print("members:", len(syms), file=sys.stderr)
    with ThreadPoolExecutor(max_workers=8) as ex:
        got = list(ex.map(bars_for, syms))
    with open(ENV + "bars.jsonl", "w") as f:
        n = 0
        for sym, rows in got:
            if rows:
                f.write(json.dumps({"symbol": sym, "bars": rows}) + "\n")
                n += len(rows)
    print("bars rows:", n, "symbols with bars:", sum(1 for s, r in got if r), file=sys.stderr)

    with ThreadPoolExecutor(max_workers=8) as ex:
        has = list(ex.map(fund_probe, syms))
    fsy = sorted(s for s, ok in has if ok)
    print("members with binance_perp funding:", len(fsy), file=sys.stderr)
    with ThreadPoolExecutor(max_workers=8) as ex:
        frows = list(ex.map(fund_for, fsy))
    with open(ENV + "funding.jsonl", "w") as f:
        m = 0
        for sym, rows in frows:
            if rows:
                f.write(json.dumps({"symbol": sym, "funding": rows}) + "\n")
                m += len(rows)
    print("funding rows:", m, file=sys.stderr)


if __name__ == "__main__":
    main()