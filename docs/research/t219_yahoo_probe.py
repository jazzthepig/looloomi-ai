"""T-219: public-source (Yahoo chart API) probe for the 10 rail tickers + 5 old rails + QQQ.

Read-only public GET. No credentials. Prints row counts and first/last dates only.
"""
import json, urllib.request, time

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120 Safari/537.36"}
SYMS = ["CRCL", "COIN", "HOOD", "GLXY", "MSTR", "PYPL", "XYZ", "BLSH", "FIGR", "GEMI",
        "V", "MA", "BLK", "IBKR", "SCHW", "QQQ", "SPY"]


def chart(sym, rng="5y"):
    url = ("https://query1.finance.yahoo.com/v8/finance/chart/" + sym +
           "?range=" + rng + "&interval=1d&events=div%2Csplit")
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=40) as r:
        d = json.loads(r.read().decode())
    res = d["chart"]["result"]
    if not res:
        return None
    r0 = res[0]
    ts = r0.get("timestamp") or []
    q = (r0.get("indicators", {}).get("quote") or [{}])[0]
    closes = q.get("close") or []
    return {"n": len(ts), "t0": ts[0] if ts else None, "t1": ts[-1] if ts else None,
            "close0": closes[0] if closes else None, "closeN": closes[-1] if closes else None,
            "currency": r0.get("meta", {}).get("currency"),
            "exchange": r0.get("meta", {}).get("exchangeName"),
            "symbol": r0.get("meta", {}).get("symbol"),
            "longName": r0.get("meta", {}).get("longName") or r0.get("meta", {}).get("shortName")}


if __name__ == "__main__":
    for s in SYMS:
        try:
            r = chart(s)
            if r is None:
                print(s, "NO RESULT")
            else:
                import datetime as dt
                f = dt.datetime.utcfromtimestamp(r["t0"]).date().isoformat() if r["t0"] else None
                l = dt.datetime.utcfromtimestamp(r["t1"]).date().isoformat() if r["t1"] else None
                print("%-6s n=%-6s %s..%s  close %s -> %s  %s %s  %s" % (
                    s, r["n"], f, l, r["close0"], r["closeN"], r["exchange"], r["currency"], r["longName"]))
        except Exception as e:
            print(s, "ERR", str(e)[:120])
        time.sleep(0.7)
