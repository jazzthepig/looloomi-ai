#!/usr/bin/env python3
"""T-214 — 引用抓取:把报告要引的每一句原文抓下来,连 URL 与取数时刻一起存档。

只读 GET/POST 公开页面与公开 API。不注册、不下单、不碰私钥、不连钱包、不写库。
输出:docs/research/t214_cites.json —— 报告里每条引文都能在这里核到 url + 抓取时间 + 原文片段。
"""
import datetime
import html
import json
import os
import re
import ssl
import time
import urllib.request

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
CTX = ssl.create_default_context()
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "t214_cites.json")


def fetch(url, body=None):
    data = None
    headers = {"User-Agent": UA, "Accept": "*/*"}
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers,
                                 method="POST" if body is not None else "GET")
    ts = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    last = ""
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=45, context=CTX) as r:
                return ts, r.read().decode("utf-8", "ignore")
        except Exception as e:  # noqa: BLE001
            last = "%s: %s" % (type(e).__name__, e)
            if "429" in last or "Too Many" in last:
                time.sleep(9 + 5 * attempt)
                continue
            break
    return ts, "FETCH_ERROR %s" % last


def strip_tags(t):
    t = re.sub(r"<[^>]+>", " ", t)
    t = html.unescape(t)
    t = t.replace("\\u003c", "<").replace("\\u003e", ">").replace("\\u0026", "&").replace('\\"', '"')
    return re.sub(r"\s+", " ", t)


def grab(text, kws, limit=6, width=420, minlen=12):
    """按关键词抓原文(已 strip 标签)。整页是单行 JSON/HTML 时走正则窗口。返回 [{kw,text}]。"""
    out, seen = [], set()
    lines = [strip_tags(x) for x in text.split("\n")]
    flat = strip_tags(text)
    for kw in kws:
        n = 0
        for ln in lines:
            if kw.lower() in ln.lower() and minlen < len(ln) < 4000:
                s = ln.strip()
                if s not in seen:
                    seen.add(s)
                    out.append({"kw": kw, "text": s[:width]})
                    n += 1
                if n >= limit:
                    break
        if n < limit:  # 单行页面:正则窗口
            for m in re.finditer(re.escape(kw), flat, re.I):
                s = flat[max(0, m.start() - 200):m.start() + 260].strip()
                if len(s) > minlen and s not in seen:
                    seen.add(s)
                    out.append({"kw": kw, "text": s[:width]})
                    n += 1
                if n >= limit:
                    break
    return out


PAGES = [
    # (key, url, method, body, keywords)
    ("sfc_vatp_list",
     "https://www.sfc.hk/en/Welcome-to-the-Fintech-Contact-Point/Virtual-assets/"
     "Virtual-asset-trading-platforms-operators/Lists-of-virtual-asset-trading-platforms",
     "GET", None, ["OSL Exchange", "HashKey", "HKVAX", "HKbitEX", "Accumulus", "DFX Labs", "EX.IO",
                   "PantherTrade", "YAX", "Bullish", "BGE", "VDX", "Bixin",
                   "Crypto.com", "Bybit", "OKX Hong Kong", "Gate.HK", "bitV", "Nebulas",
                   "Withdrawn", "Matrixport"]),
    ("kraken_xstocks", "https://www.kraken.com/legal/xstocks", "GET", None,
     ["minimum investment", "24/5", "redemption", "additional fee", "self-custody",
      "withdraw your xStocks", "Not available in the US", "Geo restrictions", "fractional"]),
    ("kraken_global_terms", "https://www.kraken.com/legal/global-terms", "GET", None,
     ["Restricted Jurisdiction", "North Korea", "Prohibited Person", "identity verification"]),
    ("kraken_assetpairs", "https://api.kraken.com/0/public/AssetPairs", "GET", None,
     ["XAUTUSD", "XAUTUSDT", "PAXGUSD"]),
    ("kraken_ticker_xaut", "https://api.kraken.com/0/public/Ticker?pair=XAUTUSD", "GET", None,
     ["XAUTUSD", "a", "b"]),
    ("binance_exchangeinfo_xaut", "https://api.binance.com/api/v3/exchangeInfo?symbol=XAUTUSDT",
     "GET", None, ["XAUTUSDT"]),
    ("binance_exchangeinfo_spyb", "https://api.binance.com/api/v3/exchangeInfo?symbol=SPYBUSDT",
     "GET", None, ["SPYBUSDT", "isSpotTradingAllowed", "minQty", "tickSize"]),
    ("binance_bookticker_xaut", "https://api.binance.com/api/v3/ticker/bookTicker?symbol=XAUTUSDT",
     "GET", None, ["XAUTUSDT"]),
    ("binance_bookticker_xautusdc", "https://api.binance.com/api/v3/ticker/bookTicker?symbol=XAUTUSDC",
     "GET", None, ["XAUTUSDC"]),
    ("binance_bookticker_spyb", "https://api.binance.com/api/v3/ticker/bookTicker?symbol=SPYBUSDT",
     "GET", None, ["SPYBUSDT"]),
    ("binance_cms_announcements",
     "https://www.binance.com/bapi/composite/v1/public/cms/article/catalog/list/query"
     "?catalogId=48&pageNo=1&pageSize=50", "GET", None,
     ["Binance Adds 25 Stocks on Binance Stock Trading", "Binance Adds 5 Stocks on Binance Stock Trading",
      "bStocks", "Invesco QQQ Trust"]),
    ("coingecko_tether_gold", "https://api.coingecko.com/api/v3/coins/tether-gold", "GET", None,
     ["platforms", "ethereum", "0x68749665ff8d2d112fa859aa293f07a622782f38", "contract_address"]),
    ("coingecko_spyx", "https://api.coingecko.com/api/v3/coins/sp500-xstock", "GET", None,
     ["platforms", "solana", "arbitrum-one", "hyperliquid", "0x90a2a4c76b5d8c0bc892a69ea28aa775a8f2dd48",
      "XsoCS1TfEyfFhfvj8EtZ528L3CaKBDBRqRapnBbDF2W", "0x29067197b3125c8b82ad0f338e4a31b2"]),
    ("coingecko_wspyx", "https://api.coingecko.com/api/v3/coins/wrapped-sp500-xstock", "GET", None,
     ["platforms", "0xe7e553cd128f0011777323a0b44a7b96ea1cb540", "hyperevm"]),
    ("coingecko_tickers_spyx", "https://api.coingecko.com/api/v3/coins/sp500-xstock/tickers", "GET", None,
     ["SPYX", "Kraken", "Hyperliquid", "LBank", "Gate", "MEXC"]),
    ("coingecko_tickers_xaut", "https://api.coingecko.com/api/v3/coins/tether-gold/tickers", "GET", None,
     ["XAUT", "Binance", "Bybit", "OKX", "Uniswap V3"]),
    ("geckoterminal_xaut_eth",
     "https://api.geckoterminal.com/api/v2/networks/eth/tokens/0x68749665ff8d2d112fa859aa293f07a622782f38",
     "GET", None, ["Tether Gold", "price_usd"]),
    ("geckoterminal_spyx_eth",
     "https://api.geckoterminal.com/api/v2/networks/eth/tokens/0x90a2a4c76b5d8c0bc892a69ea28aa775a8f2dd48",
     "GET", None, ["SP500 xStock", "price_usd"]),
    ("geckoterminal_spyx_sol",
     "https://api.geckoterminal.com/api/v2/networks/solana/tokens/XsoCS1TfEyfFhfvj8EtZ528L3CaKBDBRqRapnBbDF2W",
     "GET", None, ["SP500 xStock", "price_usd"]),
    ("geckoterminal_xaut0_hyperevm",
     "https://api.geckoterminal.com/api/v2/networks/hyperevm/tokens/0xf4d9235269a96aadafc9adae454a0618ebe37949",
     "GET", None, ["XAUt0", "price_usd"]),
    ("geckoterminal_wspyx_hyperevm",
     "https://api.geckoterminal.com/api/v2/networks/hyperevm/tokens/0xe7e553cd128f0011777323a0b44a7b96ea1cb540",
     "GET", None, ["Wrapped SP500 xStock", "price_usd"]),
    ("hyperliquid_spotmeta", "https://api.hyperliquid.xyz/info", "POST", {"type": "spotMeta"},
     ["SPYX", "XAUT0", "SPY", "evmContract", "0x29067197b3125c8b82ad0f338e4a31b2"]),
    ("hyperliquid_spotctx", "https://api.hyperliquid.xyz/info", "POST",
     {"type": "spotMetaAndAssetCtxs"}, ["SPYX", "XAUT0", "dayNtlVlm", "mid"]),
    ("hyperliquid_fees", "https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees.md", "GET", None,
     ["Spot fee tiers", "Base rate", "0.070%", "0.040%", "separate fee schedules"]),
    ("hyperliquid_usdc", "https://hyperliquid.gitbook.io/hyperliquid-docs/hypercore/usdc.md", "GET", None,
     ["natively minted", "Arbitrum", "CCTP", "legacy Arbitrum bridge"]),
    ("xstocks_legal", "https://docs.xstocks.fi/docs/product-legal-overview.md", "GET", None,
     ["Jersey", "tracker certificate", "KYC and AML", "Liechtenstein FMA", "segregated"]),
    ("xstocks_products", "https://xstocks.com/products", "GET", None,
     ["not available", "U.S. persons", "Hong Kong", "minimum", "fee"]),
    ("tether_gold", "https://tether.to/en/gold/", "GET", None,
     ["redeem", "fee", "Ethereum", "Tether Gold", "vault", "minimum"]),
    ("tether_terms", "https://tether.to/en/legal/", "GET", None,
     ["Prohibited Jurisdiction", "Prohibited Person", "freeze", "Issuances and Redemptions"]),
    ("okx_ticker_xaut", "https://www.okx.com/api/v5/market/ticker?instId=XAUT-USDT", "GET", None,
     ["XAUT-USDT", "bidPx", "askPx", "volCcy24h"]),
    ("okx_instruments", "https://www.okx.com/api/v5/public/instruments?instType=SPOT", "GET", None,
     ["XAUT-USDT", "XAUT-TRY"]),
    ("bybit_ticker_xaut", "https://api.bybit.com/v5/market/tickers?category=spot&symbol=XAUTUSDT",
     "GET", None, ["XAUTUSDT", "bid1Price", "ask1Price"]),
    ("eth_gas_blockchair", "https://api.blockchair.com/ethereum/stats", "GET", None,
     ["mempool_median_gas_price", "blocks_24h"]),
    ("sol_priority_fee", "https://api.mainnet-beta.solana.com", "POST",
     {"jsonrpc": "2.0", "id": 1, "method": "getRecentPrioritizationFees", "params": []},
     ["prioritizationFee"]),
]


def main():
    out = {"generated_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(), "pages": {}}
    for key, url, method, body, kws in PAGES:
        ts, txt = fetch(url, body)
        rec = {"url": url, "method": method, "fetched_at_utc": ts, "chars": len(txt)}
        if txt.startswith("FETCH_ERROR"):
            rec["error"] = txt[:200]
            out["pages"][key] = rec
            print("%-32s ERR %s" % (key, rec["error"][:70]))
            continue
        if key in ("hyperliquid_spotmeta", "hyperliquid_spotctx"):
            rec["quotes"] = []
            try:
                d = json.loads(txt)
                if key == "hyperliquid_spotmeta":
                    for t in d.get("tokens", []):
                        if t.get("name") in ("SPYX", "XAUT0", "SPY"):
                            rec["quotes"].append({"kw": "token", "text": json.dumps(t, ensure_ascii=False)[:400]})
                    for u in d.get("universe", []):
                        if u.get("name") in ("@182", "@703", "@279", "@209"):
                            rec["quotes"].append({"kw": "pair", "text": json.dumps(u, ensure_ascii=False)[:300]})
                else:
                    meta, ctxs = d[0], d[1]
                    names = {t["index"]: t["name"] for t in meta.get("tokens", [])}
                    for u, c in zip(meta.get("universe", []), ctxs):
                        nm = [names.get(i) for i in u.get("tokens", [])]
                        if any(n in ("SPYX", "XAUT0", "SPY") for n in nm):
                            rec["quotes"].append({"kw": "ctx", "text": json.dumps(
                                {"pair": u.get("name"), "tokens": nm, "mid": c.get("mid"),
                                 "bid": c.get("bid"), "ask": c.get("ask"),
                                 "dayNtlVlm": c.get("dayNtlVlm")}, ensure_ascii=False)[:300]})
            except Exception as e:  # noqa: BLE001
                rec["parse_error"] = str(e)[:120]
        elif key.startswith("binance_exchangeinfo"):
            rec["quotes"] = []
            try:
                s = json.loads(txt)["symbols"][0]
                keep = {k: s.get(k) for k in ("symbol", "status", "baseAsset", "quoteAsset",
                                              "isSpotTradingAllowed", "baseAssetPrecision")}
                keep["filters"] = [f for f in s.get("filters", [])
                                   if f.get("filterType") in ("LOT_SIZE", "PRICE_FILTER")]
                rec["quotes"].append({"kw": "exchangeInfo", "text": json.dumps(keep, ensure_ascii=False)[:700]})
            except Exception as e:  # noqa: BLE001
                rec["parse_error"] = str(e)[:120]
        else:
            rec["quotes"] = grab(txt, kws)
        out["pages"][key] = rec
        print("%-32s %s chars=%-8d quotes=%d" % (key, ts[11:19], len(txt), len(rec.get("quotes", []))))

    with open(OUT, "w") as fh:
        json.dump(out, fh, indent=1, ensure_ascii=False)
    print("WROTE", OUT)


if __name__ == "__main__":
    main()
