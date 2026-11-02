"""T-219: Nasdaq public API historical endpoint probe (public GET, no key).
Can we get rail-ticker daily closes while our EODHD channel has not landed them?
Prints shape only.
"""
import json, urllib.request

HDR = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Origin": "https://www.nasdaq.com",
    "Referer": "https://www.nasdaq.com/",
}


def hist(sym, frm="2023-01-01", to="2026-11-02", limit=1200):
    url = ("https://api.nasdaq.com/api/quote/" + sym + "/historical?assetclass=stocks"
           "&fromdate=" + frm + "&todate=" + to + "&limit=" + str(limit))
    req = urllib.request.Request(url, headers=HDR)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


if __name__ == "__main__":
    for s in ["CRCL", "COIN", "V", "QQQ"]:
        try:
            d = hist(s)
            data = (d.get("data") or {})
            rows = (data.get("tradesTable") or {}).get("rows") or []
            print(s, "status=", d.get("status", {}).get("rCode"), "rows=", len(rows))
            for r in rows[:3]:
                print("    ", json.dumps(r, ensure_ascii=False)[:200])
        except Exception as e:
            print(s, "ERR", str(e)[:160])
