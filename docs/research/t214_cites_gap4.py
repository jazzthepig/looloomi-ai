#!/usr/bin/env python3
"""T-214 — 引用补抓(第五轮):HL 条款原文 / 费率表原文 / Tether 多链合约 / SFC 名单全文计数。

只读 GET/POST 公开页面与公开 API。不注册、不下单、不碰私钥、不连钱包、不写库。
输出:docs/research/t214_cites_gap4.json
"""
import datetime
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from t214_cites_gap import fetch, grab  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "t214_cites_gap4.json")

SFC = ("https://www.sfc.hk/en/Welcome-to-the-Fintech-Contact-Point/Virtual-assets/"
       "Virtual-asset-trading-platforms-operators/Lists-of-virtual-asset-trading-platforms")

PAGES = [
    ("hl_llms_txt", "https://hyperliquid.gitbook.io/hyperliquid-docs/llms.txt", "GET", None,
     ["terms", "legal", "bridg", "deposit", "fee"]),
    ("hl_legal_terms", "https://hyperliquid.gitbook.io/hyperliquid-docs/legal/terms.md", "GET", None,
     ["Hong Kong", "Restricted", "jurisdiction", "Prohibited"]),
    ("hl_legal_index", "https://hyperliquid.gitbook.io/hyperliquid-docs/legal/index.md", "GET", None,
     ["Hong Kong", "Restricted", "terms"]),
    ("hl_legal_tos", "https://hyperliquid.gitbook.io/hyperliquid-docs/legal/hyperliquid-terms-of-service.md",
     "GET", None, ["Hong Kong", "Restricted", "jurisdiction"]),
    ("hl_fees_raw", "https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees.md", "GET", None,
     ["Spot fee tiers", "Maker", "Taker", "Base rate"]),
    ("tether_gold_raw", "https://tether.to/en/gold/", "GET", None,
     ["0x", "Avalanche", "Solana", "Arbitrum", "Polygon", "contract address", "minimum purchase",
      "Tether Gold"]),
    ("sfc_count", SFC, "GET", None,
     ["Kraken", "Binance", "OKX", "Bybit", "Bullish", "HashKey", "CoinW", "Bitfinex", "MEXC",
      "BingX", "Nado", "VALR", "Coinbase", "Withdrawn", "applicant"]),
    ("kraken_assets_xaut", "https://api.kraken.com/0/public/Assets?asset=XAUT", "GET", None,
     ["XAUT", "aclass", "decimals"]),
    ("kraken_assets_spyx", "https://api.kraken.com/0/public/Assets?asset=SPYX", "GET", None,
     ["SPYX", "error"]),
    ("binance_bookticker_xautusdc2",
     "https://api.binance.com/api/v3/ticker/bookTicker?symbol=XAUTUSDC", "GET", None, ["XAUTUSDC"]),
    ("binance_exchangeinfo_xautusdc",
     "https://api.binance.com/api/v3/exchangeInfo?symbol=XAUTUSDC", "GET", None,
     ["XAUTUSDC", "minQty", "stepSize", "tickSize"]),
    ("bybit_ticker_xautusdc",
     "https://api.bybit.com/v5/market/tickers?category=spot&symbol=XAUTUSDC", "GET", None,
     ["XAUTUSDC", "bid1Price", "ask1Price"]),
    ("okx_ticker_xaut_usdc",
     "https://www.okx.com/api/v5/market/ticker?instId=XAUT-USDC", "GET", None,
     ["XAUT-USDC", "bidPx", "askPx"]),
    ("gate_ticker_spyx",
     "https://api.gateio.ws/api/v4/spot/tickers?currency_pair=SPYX_USDT", "GET", None,
     ["SPYX_USDT", "highest_bid", "lowest_ask"]),
    ("mexc_ticker_spyx",
     "https://api.mexc.com/api/v3/ticker/24hr?symbol=SPYXUSDT", "GET", None,
     ["SPYXUSDT", "lastPrice", "bidPrice", "askPrice"]),
]


def main():
    out = {"generated_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(), "pages": {}}
    for key, url, method, body, kws in PAGES:
        ts, txt = fetch(url, body)
        rec = {"url": url, "method": method, "fetched_at_utc": ts, "chars": len(txt)}
        if txt.startswith("FETCH_ERROR"):
            rec["error"] = txt[:200]
            rec["quotes"] = []
            out["pages"][key] = rec
            print("%-26s ERR %s" % (key, rec["error"][:70]))
            continue
        if key == "sfc_count":
            rec["counts"] = {}
            for nm in kws:
                rec["counts"][nm] = len(re.findall(re.escape(nm), txt, re.I))
            rec["quotes"] = grab(txt, ["Withdrawn", "applicant"], limit=2)
        elif key in ("hl_fees_raw", "tether_gold_raw", "hl_llms_txt"):
            rec["raw_head"] = txt[:3000]
            rec["quotes"] = grab(txt, kws, limit=4, width=600)
        else:
            rec["quotes"] = grab(txt, kws, limit=3)
        out["pages"][key] = rec
        print("%-26s ok chars=%-9d quotes=%d" % (key, rec["chars"], len(rec["quotes"])))
    with open(OUT, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
