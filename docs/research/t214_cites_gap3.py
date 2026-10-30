#!/usr/bin/env python3
"""T-214 — 引用补抓(第四轮):合约链清单 / xStocks 资格与费用 / 费率 / 出金路径 / Kraken 最小单。

只读 GET/POST 公开页面与公开 API。不注册、不下单、不碰私钥、不连钱包、不写库。
输出:docs/research/t214_cites_gap3.json
"""
import datetime
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from t214_cites_gap import fetch, grab  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "t214_cites_gap3.json")

PAGES = [
    # XAUt0(0xf4d92352…)在哪些链 —— 官方合约归属
    ("cg_tether_gold_tokens",
     "https://api.coingecko.com/api/v3/coins/tether-gold-tokens", "GET", None,
     ["platforms", "detail_platforms", "0xf4d9235269a96aadafc9adae454a0618ebe37949",
      "arbitrum-one", "hyperevm"]),
    # xStocks 文档站:把 sitemap 全量 URL 抽出来
    ("xstocks_sitemap_locs",
     "https://docs.xstocks.fi/sitemap.xml", "GET", None, ["loc"]),
    ("xstocks_fees_doc",
     "https://docs.xstocks.fi/apis/openapi/market-trades/list_trades_market_fees.md", "GET", None,
     ["fee", "redemption", "issuance", "broker", "eur", "usd"]),
    ("xstocks_eligibility_doc",
     "https://docs.xstocks.fi/docs/eligibility.md", "GET", None,
     ["Hong Kong", "KYC", "eligible", "jurisdiction", "blocked", "United States"]),
    # Kraken:xStocks 用什么交易对 / XAUT 其它计价币的最小单
    ("kraken_ticker_spyx_alt",
     "https://api.kraken.com/0/public/Ticker?pair=SPYxUSD", "GET", None, ["error", "SPYx"]),
    ("kraken_ticker_spyx_usdt",
     "https://api.kraken.com/0/public/Ticker?pair=SPYXUSDT", "GET", None, ["error", "SPYX"]),
    ("kraken_fees_schedule",
     "https://support.kraken.com/hc/en-us/articles/360000920306-Kraken-Fees-Schedule-Volumes-and-Pairs",
     "GET", None, ["maker", "taker", "0.26", "0.16", "XAUT"]),
    # OKX / Binance 费率页备选入口
    ("okx_fees_page",
     "https://www.okx.com/trade-spot/fees", "GET", None, ["maker", "taker", "0.1"]),
    ("okx_fee_api",
     "https://www.okx.com/api/v5/account/trade-fee?instType=SPOT", "GET", None,
     ["maker", "taker", "error", "code"]),
    ("binance_fee_api",
     "https://api.binance.com/sapi/v1/asset/tradeFee", "GET", None, ["code", "msg", "maker"]),
    ("binance_withdraw_fee_api",
     "https://api.binance.com/sapi/v1/capital/config/getall", "GET", None, ["code", "msg"]),
    ("bybit_coin_info",
     "https://api.bybit.com/v5/asset/coin/query-info?coin=USDC", "GET", None,
     ["code", "retMsg", "chainType", "withdrawFee"]),
    # Hyperliquid 出金 / 桥 / 存款
    ("hl_bridging",
     "https://hyperliquid.gitbook.io/hyperliquid-docs/hypercore/bridging.md", "GET", None,
     ["CCTP", "fee", "Arbitrum", "deposit", "USDC", "withdraw"]),
    ("hl_withdraw_fee",
     "https://hyperliquid.gitbook.io/hyperliquid-docs/hypercore/withdraw.md", "GET", None,
     ["fee", "1 USDC", "withdraw", "minimum"]),
    ("hl_deposit_docs",
     "https://hyperliquid.gitbook.io/hyperliquid-docs/hypercore/deposits.md", "GET", None,
     ["deposit", "fee", "Arbitrum", "HyperEVM", "USDC"]),
    # SFC 名单页里有没有 Gate / MEXC / Bitfinex / CoinW / BingX
    ("sfc_list_again",
     "https://www.sfc.hk/en/Welcome-to-the-Fintech-Contact-Point/Virtual-assets/"
     "Virtual-asset-trading-platforms-operators/Lists-of-virtual-asset-trading-platforms",
     "GET", None, ["Gate", "MEXC", "Bitfinex", "CoinW", "BingX", "Nado", "VALR", "HashKey Exchange"]),
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
        if key == "xstocks_sitemap_locs":
            locs = re.findall(r"<loc>([^<]+)</loc>", txt)
            rec["quotes"] = [{"kw": "loc", "text": l} for l in locs]
        else:
            rec["quotes"] = grab(txt, kws, limit=3)
        out["pages"][key] = rec
        print("%-28s ok chars=%-9d quotes=%d" % (key, rec["chars"], len(rec["quotes"])))
    with open(OUT, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
