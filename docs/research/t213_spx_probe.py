#!/usr/bin/env python3
"""T-213:找「S&P 500 指数」口径的日线,用来算 SPY(ETF 本身) vs 指数 的跟踪成本。

只读:读 Supabase ohlcv_daily(带 order=),不写库、不下单。
候选 symbol 名 + 表里实际存在的以 SPX/SP500/GSPC 开头或含 INDEX 的 symbol,全探一遍。
"""
import json
import os
import urllib.request

URL = os.environ["SUPABASE_URL"].rstrip("/") + "/rest/v1/ohlcv_daily"
KEY = os.environ["SUPABASE_KEY"]
HDR = dict()
HDR["apikey"] = KEY
HDR["Authorization"] = "Bearer " + KEY

CANDS = ["SPX", "^GSPC", "GSPC", "SP500", "SPXTR", "SPX.IND", "IDX:SPX",
         "SPX.INDEX", "SP500.INDEX", "SP500TR", "SPXTR.IND", "INDEX:SPX"]


def get(url):
    req = urllib.request.Request(url, headers=HDR)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def probe(sym):
    q = (URL + "?symbol=eq." + sym +
         "&select=symbol,trade_date,close,source&order=trade_date.desc&limit=5")
    try:
        rows = get(q)
        return {"symbol": sym, "ok": bool(rows), "n_returned": len(rows),
                "first": rows[0] if rows else None}
    except Exception as exc:  # noqa: BLE001
        return {"symbol": sym, "ok": False, "error": type(exc).__name__ + ": " + str(exc)[:120]}


def probe_http(url, note=""):
    """外部指数日线来源探测(stooq / Yahoo chart),留证用。"""
    try:
        req = urllib.request.Request(url)
        req.add_header("User-Agent", "Mozilla/5.0")
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read(400)
        head = raw.decode("utf-8", "replace")[:120].replace("\n", " ")
        is_html = head.lstrip().startswith("<")
        return {"url": url, "ok": not is_html, "bytes_head": len(raw),
                "head": head, "note": note or ("HTML/JS challenge,不是 CSV" if is_html else "")}
    except Exception as exc:  # noqa: BLE001
        return {"url": url, "ok": False, "error": type(exc).__name__ + ": " + str(exc)[:120],
                "note": note}


def main():
    out = {"candidates": [probe(s) for s in CANDS], "symbol_scan": []}

    # 表里实际有哪些像指数的 symbol。整表扫描会被 PostgREST max-rows(1000) 截断,
    # 配合 order=symbol.asc 只会看到字典序第一个 symbol ⇒ 改用 like 过滤逐个查。
    q = (URL + "?select=symbol&order=symbol.asc&limit=4000")
    scan = {"method": "like 过滤(整表扫描会被 max-rows=1000 + order=symbol.asc 截断)",
            "patterns": {}}
    for pat in ("SPX*", "*SPX", "*GSPC*", "*SP500*", "*SP5*", "*INDEX*", "I:*"):
        qq = (URL + "?symbol=like." + pat +
              "&select=symbol,trade_date,close,source&order=symbol.asc,trade_date.asc&limit=30")
        try:
            rows = get(qq)
            scan["patterns"][pat] = sorted({r["symbol"] for r in rows})[:30]
        except Exception as exc:  # noqa: BLE001
            scan["patterns"][pat] = "ERR " + type(exc).__name__
    out["symbol_scan"] = scan

    out["http_attempts"] = [
        probe_http("https://stooq.com/q/d/l/?s=%5Espx&i=d", "S&P500 指数日线 CSV"),
        probe_http("https://query1.finance.yahoo.com/v8/finance/chart/%5EGSPC?range=2y&interval=1d",
                   "Yahoo chart API ^GSPC"),
    ]

    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "t213_spx_probe.json")
    with open(path, "w") as fh:
        json.dump(out, fh, indent=1, ensure_ascii=False)
    print(json.dumps(out, indent=1, ensure_ascii=False)[:3000])
    print("WROTE", path)


if __name__ == "__main__":
    main()
