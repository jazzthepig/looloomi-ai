#!/usr/bin/env python3
"""T-214 — 引用补抓(第二轮):补第一轮 cites.json 没覆盖到的口子。

只读 GET/POST 公开页面与公开 API。不注册、不下单、不碰私钥、不连钱包、不写库。
输出:docs/research/t214_cites_gap.json —— 每个 key 一条:url + 抓取时间 + 命中原文片段。
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
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "t214_cites_gap.json")


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


def grab(text, kws, limit=4, width=420, minlen=10):
    """整页搜索关键词,取命中点上下文(单行大 JSON 也适用)。"""
    out, seen = [], set()
    flat = strip_tags(text)
    for kw in kws:
        n = 0
        for m in re.finditer(re.escape(kw), flat, re.I):
            s = flat[max(0, m.start() - 220):m.start() + 320].strip()
            if len(s) > minlen and s not in seen:
                seen.add(s)
                out.append({"kw": kw, "text": s[:width]})
                n += 1
            if n >= limit:
                break
    return out


PAGES = [
    # ---- Hyperliquid:条款(受限司法辖区)+ 两条腿的现货盘口 ----
    ("hl_terms_gitbook",
     "https://hyperliquid.gitbook.io/hyperliquid-docs/legal/terms-of-service.md", "GET", None,
     ["Hong Kong", "Restricted", "jurisdiction", "eligible", "Prohibited"]),
    ("hl_terms_app",
     "https://app.hyperliquid.xyz/terms-of-service", "GET", None,
     ["Hong Kong", "Restricted Jurisdiction", "United States", "person eligible"]),
    ("hl_spot_ctx_px",
     "https://api.hyperliquid.xyz/info", "POST", {"type": "spotMetaAndAssetCtxs"},
     ["SPYX", "XAUT0"]),
    ("hl_l2_xaut0usdc",
     "https://api.hyperliquid.xyz/info", "POST",
     {"type": "l2book", "coin": "XAUT0/USDC"}, ["px", "sz"]),
    ("hl_l2_spyxusdc",
     "https://api.hyperliquid.xyz/info", "POST",
     {"type": "l2book", "coin": "SPYX/USDC"}, ["px", "sz"]),
    # ---- 各所「香港居民能不能开户」条款原文 ----
    ("kraken_countries",
     "https://support.kraken.com/hc/en-us/articles/360000426166-Kraken-available-in-your-country",
     "GET", None, ["Hong Kong", "restricted", "not available"]),
    ("kraken_terms_hk",
     "https://www.kraken.com/legal/global-terms", "GET", None,
     ["Hong Kong", "Restricted Jurisdiction", "Restricted Person"]),
    ("binance_terms_hk",
     "https://www.binance.com/en/legal/terms", "GET", None,
     ["Hong Kong", "Restricted Jurisdiction", "restricted"]),
    ("okx_terms_hk",
     "https://www.okx.com/legal/terms", "GET", None,
     ["Hong Kong", "Restricted Jurisdiction", "restricted"]),
    ("bybit_terms_hk",
     "https://www.bybit.com/en/legal/terms", "GET", None,
     ["Hong Kong", "Restricted Jurisdiction", "restricted"]),
    # ---- Binance:SPYX / SPYB 到底是不是同一个东西 ----
    ("binance_exchangeinfo_spyx",
     "https://api.binance.com/api/v3/exchangeInfo?symbol=SPYXUSDT", "GET", None, ["SPYXUSDT"]),
    ("binance_bookticker_spyx",
     "https://api.binance.com/api/v3/ticker/bookTicker?symbol=SPYXUSDT", "GET", None, ["SPYXUSDT"]),
    ("binance_cms_stockdetail",
     "https://www.binance.com/bapi/composite/v1/public/cms/article/catalog/list/query"
     "?catalogId=48&pageNo=1&pageSize=50", "GET", None,
     ["Binance Adds 25 Stocks", "SPY", "xStock", "Backed", "tokenized"]),
    # ---- DEX 流动性(GeckoTerminal pools)----
    ("gt_pools_xaut_eth",
     "https://api.geckoterminal.com/api/v2/networks/eth/tokens/"
     "0x68749665ff8d2d112fa859aa293f07a622782f38/pools", "GET", None,
     ["reserve_in_usd", "volume_usd", "fee_percentage", "pool_created_at"]),
    ("gt_pools_xaut_arb",
     "https://api.geckoterminal.com/api/v2/networks/arbitrum/tokens/"
     "0xf4d9235269a96aadafc9adae454a0618ebe37949/pools", "GET", None,
     ["reserve_in_usd", "volume_usd", "fee_percentage"]),
    ("gt_pools_spyx_arb",
     "https://api.geckoterminal.com/api/v2/networks/arbitrum/tokens/"
     "0x90a2a4c76b5d8c0bc892a69ea28aa775a8f2dd48/pools", "GET", None,
     ["reserve_in_usd", "volume_usd", "fee_percentage"]),
    ("gt_pools_spyx_sol",
     "https://api.geckoterminal.com/api/v2/networks/solana/tokens/"
     "XsoCS1TfEyfFhfvj8EtZ528L3CaKBDBRqRapnBbDF2W/pools", "GET", None,
     ["reserve_in_usd", "volume_usd", "fee_percentage"]),
    ("gt_pools_spyx_xlayer",
     "https://api.geckoterminal.com/api/v2/networks/x-layer/tokens/"
     "0xe7e553cd128f0011777323a0b44a7b96ea1cb540/pools", "GET", None,
     ["reserve_in_usd", "volume_usd", "fee_percentage"]),
    ("gt_pools_xaut_sol",
     "https://api.geckoterminal.com/api/v2/networks/solana/tokens/"
     "XAUTso11111111111111111111111111111111111111/pools", "GET", None,
     ["reserve_in_usd", "Tether Gold"]),
    # ---- gas ----
    ("gas_eth_rpc",
     "https://ethereum-rpc.publicnode.com", "POST",
     {"jsonrpc": "2.0", "id": 1, "method": "eth_gasPrice", "params": []}, ["result"]),
    ("gas_arb_rpc",
     "https://arb1.arbitrum.io/rpc", "POST",
     {"jsonrpc": "2.0", "id": 1, "method": "eth_gasPrice", "params": []}, ["result"]),
    ("gas_hyperevm_rpc",
     "https://rpc.hyperliquid.xyz/evm", "POST",
     {"jsonrpc": "2.0", "id": 1, "method": "eth_gasPrice", "params": []}, ["result"]),
    # ---- 出入金 / 费用条款 ----
    ("binance_fee_spot",
     "https://www.binance.com/en/fee/schedule", "GET", None,
     ["Spot", "maker", "taker", "0.1"]),
    ("okx_fee_spot",
     "https://www.okx.com/help/spot-trading-fees", "GET", None,
     ["maker", "taker", "0.1"]),
    ("bybit_fee_spot",
     "https://www.bybit.com/en/help-center/article/Standard-Spot-Trading-Fee-Structure", "GET", None,
     ["maker", "taker", "0.1"]),
    ("xstocks_eligibility",
     "https://docs.xstocks.fi/docs/eligibility.md", "GET", None,
     ["Hong Kong", "KYC", "eligible", "jurisdiction", "institutional"]),
    ("tether_gold_chains",
     "https://tether.to/en/gold/", "GET", None,
     ["Arbitrum", "Solana", "Ethereum", "contract", "0x68749665ff8d2d112fa859aa293f07a622782f38",
      "0xf4d9235269a96aadafc9adae454a0618ebe37949", "minimum", "fee"]),
    # ---- SFC 端:未持牌 / 疑似平台清单(若有)----
    ("sfc_warnings",
     "https://www.sfc.hk/en/Regulatory-functions/Intermediaries/Virtual-assets/"
     "Virtual-asset-trading-platforms-operators", "GET", None,
     ["unlicensed", "warning", "list", "Hong Kong"]),
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
        if key in ("hl_spot_ctx_px", "hl_l2_xaut0usdc", "hl_l2_spyxusdc"):
            rec["quotes"] = []
            try:
                d = json.loads(txt)
                if key == "hl_spot_ctx_px":
                    meta, ctxs = d[0], d[1]
                    names = {t["index"]: t["name"] for t in meta.get("tokens", [])}
                    # ctxs 的长度与顺序都不同于 universe —— 必须按 ctx 自己的 "coin"(= 交易对名)
                    # 去查 universe,不能按位置 zip(2026-10-30 初稿的 14,000 倍误读就是这么来的)
                    by_coin = {c.get("coin"): c for c in ctxs if isinstance(c, dict) and c.get("coin")}
                    for u in meta.get("universe", []):
                        nm = [names.get(i) for i in u.get("tokens", [])]
                        if not any(n in ("SPYX", "XAUT0", "SPY") for n in nm):
                            continue
                        c = by_coin.get(u.get("name"), {})
                        rec["quotes"].append({"kw": "ctx", "text": json.dumps(
                            {"pair": u.get("name"), "tokens": nm,
                             "midPx": c.get("midPx"), "bidPx": c.get("bidPx"), "askPx": c.get("askPx"),
                             "markPx": c.get("markPx"), "prevDayPx": c.get("prevDayPx"),
                             "dayNtlVlm": c.get("dayNtlVlm")}, ensure_ascii=False)[:400]})
                else:
                    rec["quotes"].append({"kw": "book", "text": json.dumps(
                        {"coin": d.get("coin"), "levels": (d.get("levels") or [])[:6],
                         "n": len(d.get("levels") or [])}, ensure_ascii=False)[:700]})
            except Exception as e:  # noqa: BLE001
                rec["quotes"] = [{"kw": "parse_error", "text": "%s: %s" % (type(e).__name__, e)}]
        else:
            rec["quotes"] = grab(txt, kws)
        out["pages"][key] = rec
        print("%-28s ok chars=%-9d quotes=%d" % (key, rec["chars"], len(rec["quotes"])))
    with open(OUT, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
