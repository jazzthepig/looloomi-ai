#!/usr/bin/env python3
"""T-188 补测：上一轮只测了 PAXG/XAUT 的 CEX 盘口，GLDX/SPYX/QQQX/AAPLX 缺实测深度。

复用 t188_venues.py 的同一套 book_* / depth_from_levels，保证口径一致。
结果合并回 t188_venues.json 的 cex_books（键名 "Venue:PAIR"），并新增 cex_books_extra。
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
VJ = os.path.join(HERE, "t188_venues.json")

import t188_venues as T  # noqa: E402

# 代币 → 候选交易对（从 CoinGecko tickers_top 实际出现的场所反查）
CANDIDATES = {
    "GLDX": [
        ("Kraken", "GLDXUSD"), ("Kraken", "GLDXUSDT"),
        ("Binance", "GLDXUSDT"), ("OKX", "GLDX-USDT"),
        ("Gate", "GLDX_USDT"), ("Bybit", "GLDXUSDT"),
    ],
    "SPYX": [
        ("Kraken", "SPYXUSD"), ("Kraken", "SPYXUSDT"),
        ("Binance", "SPYXUSDT"), ("OKX", "SPYX-USDT"),
        ("Gate", "SPYX_USDT"), ("Bybit", "SPYXUSDT"),
    ],
    "QQQX": [
        ("Kraken", "QQQXUSD"), ("Kraken", "QQQXUSDT"),
        ("Binance", "QQQXUSDT"), ("OKX", "QQQX-USDT"),
        ("Gate", "QQQX_USDT"), ("Bybit", "QQQXUSDT"),
    ],
    "AAPLX": [
        ("Kraken", "AAPLXUSD"), ("Kraken", "AAPLXUSDT"),
        ("Binance", "AAPLXUSDT"), ("OKX", "AAPLX-USDT"),
        ("Gate", "AAPLX_USDT"), ("Bybit", "AAPLXUSDT"),
    ],
}

FUNCS = {
    ("Kraken", None): T.book_kraken,
    ("Binance", None): T.book_binance,
    ("OKX", None): T.book_okx,
    ("Coinbase", None): T.book_coinbase,
}
# Bybit / Gate 用各自的公开 depth 接口
BYBIT = "https://api.bybit.com/v5/market/orderbook?category=spot&symbol={}&limit=200"
GATE = "https://api.gateio.ws/api/v4/spot/order_book?currency_pair={}&limit=100"


def bybit_book(symbol):
    d = T._try(T._get, BYBIT.format(symbol))
    if not isinstance(d, dict) or d.get("retCode") != 0:
        return {"error": str(d)[:150]}
    r = d.get("result") or {}
    bids = [{"px": float(p), "sz": float(q)} for p, q in r.get("b", [])]
    asks = [{"px": float(p), "sz": float(q)} for p, q in r.get("a", [])]
    m = T.depth_from_levels(bids, asks)
    if m:
        m["venue"] = "Bybit"
        m["pair"] = symbol
    return m or {"error": "empty"}


def gate_book(pair):
    d = T._try(T._get, GATE.format(pair))
    if not isinstance(d, dict) or "bids" not in d:
        return {"error": str(d)[:150]}
    bids = [{"px": float(p), "sz": float(q)} for p, q in d.get("bids", [])]
    asks = [{"px": float(p), "sz": float(q)} for p, q in d.get("asks", [])]
    m = T.depth_from_levels(bids, asks)
    if m:
        m["venue"] = "Gate"
        m["pair"] = pair
    return m or {"error": "empty"}


def main():
    d = json.load(open(VJ))
    books = d.setdefault("cex_books", {})
    extra = {}
    for sym, cands in CANDIDATES.items():
        got = {}
        for venue, sym2 in cands:
            try:
                if venue == "Kraken":
                    m = T.book_kraken(sym2)
                elif venue == "Binance":
                    m = T.book_binance(sym2)
                elif venue == "OKX":
                    m = T.book_okx(sym2)
                elif venue == "Bybit":
                    m = bybit_book(sym2)
                elif venue == "Gate":
                    m = gate_book(sym2)
                else:
                    continue
            except Exception as e:  # noqa: BLE001
                m = {"error": str(e)[:120]}
            if m and "error" not in m:
                key = f"{venue}:{sym2}"
                books[key] = m
                got[key] = m
                print(f"[{sym}] HIT {key} mid={m.get('mid')} spr={m.get('spread_bps', 0):.2f}bp "
                      f"d10={m.get('depth_usd_10bp', 0):,.0f}")
            else:
                print(f"[{sym}] miss {venue}:{sym2} {str(m)[:70]}")
        extra[sym] = sorted(got.keys())
    d["cex_books_extra"] = extra
    d["cex_books_extra_asof"] = T.ASOF
    with open(VJ, "w") as f:
        json.dump(d, f, indent=1, ensure_ascii=False)
    print("merged into", VJ, "total books:", len(books))


if __name__ == "__main__":
    main()
