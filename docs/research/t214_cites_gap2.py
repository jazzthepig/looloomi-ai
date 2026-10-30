#!/usr/bin/env python3
"""T-214 — 引用补抓(第三轮):名单覆盖 / 场所挂牌 / 条款 / 手续费。

只读 GET/POST 公开页面与公开 API。不注册、不下单、不碰私钥、不连钱包、不写库。
输出:docs/research/t214_cites_gap2.json
"""
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from t214_cites_gap import fetch, grab  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "t214_cites_gap2.json")

PAGES = [
    # ---- CoinGecko 全量挂牌场所(谁在卖 XAUT / SPYX)----
    ("cg_tickers_xaut_venues",
     "https://api.coingecko.com/api/v3/coins/tether-gold/tickers", "GET", None,
     ["hyperliquid", "hashkey", "bullish", "kraken", "okx", "bybit", "uniswap", "bitfinex",
      "coinbase", "gate", "mexc"]),
    ("cg_tickers_spyx_venues",
     "https://api.coingecko.com/api/v3/coins/sp500-xstock/tickers", "GET", None,
     ["hyperliquid", "hashkey", "bullish", "kraken", "okx", "bybit", "uniswap", "gate", "mexc",
      "SPYX/USDC", "SPYX/USDT"]),
    ("cg_tickers_wspyx_venues",
     "https://api.coingecko.com/api/v3/coins/wrapped-sp500-xstock/tickers", "GET", None,
     ["hyperliquid", "uniswap", "arbitrum", "solana", "kraken", "binance"]),
    # ---- Hyperliquid 盘口(验证 XAUT0/USDC、SPYX/USDC 的真实价格与深度)----
    ("hl_l2_btcusdc",
     "https://api.hyperliquid.xyz/info", "POST", {"type": "l2book", "coin": "BTC/USDC"}, ["px"]),
    ("hl_l2_xaut0usdc2",
     "https://api.hyperliquid.xyz/info", "POST", {"type": "l2book", "coin": "XAUT0/USDC"}, ["px"]),
    ("hl_spot_candle_xaut",
     "https://api.hyperliquid.xyz/info", "POST",
     {"type": "candleSnapshot", "req": {"coin": "XAUT0/USDC", "interval": "1d",
                                        "startTime": 1790000000000, "endTime": 1793000000000}},
     ["c", "T", "v"]),
    ("hl_allmids_spot",
     "https://api.hyperliquid.xyz/info", "POST", {"type": "allMids"}, ["XAUT0", "SPYX"]),
    # ---- Binance:SPYB 是什么、bStocks 是什么 ----
    ("binance_cms_detail_25stocks",
     "https://www.binance.com/bapi/composite/v1/public/cms/article/detail/query"
     "?catalogId=48&articleCode=a0adb246c4a24f108fd0d1f51dfd3d1d", "GET", None,
     ["SPY", "bStock", "Backed", "xStock", "SPYX", "token"]),
    ("binance_cms_detail_bstocks",
     "https://www.binance.com/bapi/composite/v1/public/cms/article/detail/query"
     "?catalogId=48&articleCode=3f180bddad424ea5b7a00148433721dc", "GET", None,
     ["bStocks", "collateral", "SPY", "token"]),
    ("binance_24h_xaut",
     "https://api.binance.com/api/v3/ticker/24hr?symbol=XAUTUSDT", "GET", None,
     ["lastPrice", "priceChangePercent", "quoteVolume"]),
    ("binance_24h_spyb",
     "https://api.binance.com/api/v3/ticker/24hr?symbol=SPYBUSDT", "GET", None,
     ["lastPrice", "priceChangePercent", "quoteVolume"]),
    ("binance_exchangeinfo_spyb_full",
     "https://api.binance.com/api/v3/exchangeInfo?symbols=%5B%22SPYBUSDT%22%5D", "GET", None,
     ["baseAsset", "isSpotTradingAllowed", "minQty", "quoteOrderQtyMarketAllowed"]),
    # ---- Kraken:全量 pair 里到底有没有 SPYX / xStocks ----
    ("kraken_assetpairs_full",
     "https://api.kraken.com/0/public/AssetPairs", "GET", None,
     ["SPYX", "SPY", "TSLA", "AAPL", "XAUT"]),
    ("kraken_ticker_spyx",
     "https://api.kraken.com/0/public/Ticker?pair=SPYXUSD", "GET", None, ["error", "SPYX"]),
    # ---- SFC 持牌平台:官方平台是否挂 XAUT / SPYX(HashKey / Bullish / OSL)----
    ("hashkey_instruments",
     "https://api.hashkey.com/spot/v1/instruments", "GET", None, ["XAUT", "SPYX", "symbol"]),
    ("hashkey_ticker_xaut",
     "https://api.hashkey.com/spot/v1/ticker?symbol=XAUTUSDT", "GET", None, ["XAUT"]),
    ("bullish_markets",
     "https://api.bullish.com/api/v1/markets", "GET", None, ["symbol", "XAUT", "SPYX"]),
    # ---- Tether 官方链与合约清单 ----
    ("tether_supported_protocols",
     "https://tether.to/en/supported-protocols/", "GET", None,
     ["XAUt", "XAUt0", "0x68749665ff8d2d112fa859aa293f07a622782f38",
      "0xf4d9235269a96aadafc9adae454a0618ebe37949", "Arbitrum", "Solana"]),
    # ---- xStocks 官方文档目录(找资格/赎回页)----
    ("xstocks_sitemap",
     "https://docs.xstocks.fi/sitemap.xml", "GET", None, ["loc", "eligib", "redeem", "fee"]),
    # ---- 各所条款备选入口 ----
    ("binance_terms_alt1",
     "https://www.binance.com/en/terms", "GET", None, ["Hong Kong", "Restricted Jurisdiction"]),
    ("binance_terms_alt2",
     "https://www.binance.com/en/legal/global_terms", "GET", None, ["Hong Kong", "Restricted Jurisdiction"]),
    ("okx_terms_alt1",
     "https://www.okx.com/legal", "GET", None, ["Hong Kong", "Restricted Jurisdiction"]),
    ("okx_terms_alt2",
     "https://www.okx.com/help/where-can-i-use-okx", "GET", None,
     ["Hong Kong", "not available", "restricted"]),
    ("kraken_countries_alt",
     "https://support.kraken.com/hc/en-us/articles/360000426166-Kraken-available-in-your-country",
     "GET", None, ["Hong Kong"]),
    ("hl_terms_alt",
     "https://hyperliquid.gitbook.io/hyperliquid-docs/hypercore/terms-of-service.md", "GET", None,
     ["Hong Kong", "Restricted"]),
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
            print("%-28s ERR %s" % (key, rec["error"][:70]))
            continue
        if key.startswith("hl_"):
            rec["quotes"] = []
            try:
                d = json.loads(txt)
                rec["quotes"].append({"kw": key, "text": json.dumps(d, ensure_ascii=False)[:900]})
            except Exception as e:  # noqa: BLE001
                rec["quotes"] = [{"kw": "parse_error", "text": "%s: %s" % (type(e).__name__, e)},
                                 {"kw": "raw", "text": txt[:600]}]
        else:
            rec["quotes"] = grab(txt, kws, limit=3)
        out["pages"][key] = rec
        print("%-28s ok chars=%-9d quotes=%d" % (key, rec["chars"], len(rec["quotes"])))
    with open(OUT, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
