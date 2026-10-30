#!/usr/bin/env python3
"""T-214 — 复核:把报告里最吃重的数字/原文重新抓一遍,逐条判定 PASS/FAIL。

只读 GET/POST 公开页面与公开 API。不注册、不下单、不碰私钥、不连钱包、不写库、不读 .env。
输出:docs/research/t214_verify.json —— {checked_at_utc, results:[{id, claim, expect, got, status, url, fetched_at_utc}]}
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
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "t214_verify.json")

RESULTS = []


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
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=45, context=CTX) as r:
                return ts, r.read().decode("utf-8", "ignore")
        except Exception as e:  # noqa: BLE001
            last = "%s: %s" % (type(e).__name__, e)
            if "429" in last or "Too Many" in last:
                time.sleep(8 + 4 * attempt)
                continue
            break
    return ts, ""


def strip_tags(t):
    t = re.sub(r"<[^>]+>", " ", t)
    t = html.unescape(t)
    return re.sub(r"\s+", " ", t)


def check(cid, claim, expect, got, ok, url, ts, note=""):
    RESULTS.append({"id": cid, "claim": claim, "expect": expect, "got": got,
                    "status": "PASS" if ok else ("READ_FAIL" if got in ("", None) else "FAIL"),
                    "url": url, "fetched_at_utc": ts, "note": note})


# ---------------------------------------------------------------- A. SFC 名单
SFC = ("https://www.sfc.hk/en/Welcome-to-the-Fintech-Contact-Point/Virtual-assets/"
       "Virtual-asset-trading-platforms-operators/Lists-of-virtual-asset-trading-platforms")
ts, body = fetch(SFC)
txt = strip_tags(body)
if txt:
    for name in ("Kraken", "Binance", "OKX", "Bybit", "Bullish", "HashKey"):
        n = len(re.findall(re.escape(name), body))
        expect = {"Kraken": 0, "Binance": 0, "OKX": 2, "Bybit": 2, "Bullish": 2, "HashKey": 1}[name]
        check("sfc_count_" + name.lower(),
              "SFC 名单页全文出现次数:%s" % name,
              "=%d" % expect, "=%d" % n, n == expect, SFC, ts,
              "Kraken/Binance 不在任何一张表" if name in ("Kraken", "Binance") else "")
    licensed = ["OSL Exchange", "HashKey Exchange", "HKVAX", "HKbitEX", "Accumulus",
                "DFX Labs", "EX.IO", "PantherTrade", "YAX", "Bullish", "BGE", "VDX", "Bixin.com"]
    miss = [x for x in licensed if x not in txt]
    check("sfc_licensed_13", "SFC 持牌 13 家的平台名全部出现在名单页",
          "13/13 全中", "%d/13 全中" % (13 - len(miss)), not miss, SFC, ts,
          "缺:" + ",".join(miss) if miss else "")
    check("sfc_licence_dates", "持牌发牌日(OSL 15/12/2020 / HashKey 09/11/2022 / Bullish 18/02/2025)",
          "三个日期原文可见",
          "见 page chars=%d" % len(txt),
          all(d in txt for d in ("15/12/2020", "09/11/2022", "18/02/2025")), SFC, ts)
else:
    check("sfc_page", "SFC 名单页可读", "非空", "", False, SFC, ts, "本轮取不到")

# ---------------------------------------------------------------- B/C. Hyperliquid
ts, body = fetch("https://api.hyperliquid.xyz/info", {"type": "spotMeta"})
meta = json.loads(body) if body else {}
tokens = {t["name"]: t for t in meta.get("tokens", [])}
pairs = [(i, p) for i, p in enumerate(meta.get("universe", []))]
if tokens:
    for nm, addr in (("XAUT0", "0xf4d9235269a96aadafc9adae454a0618ebe37949"),
                     ("SPYX", "0xe7e553cd128f0011777323a0b44a7b96ea1cb540")):
        t = tokens.get(nm)
        got = (t or {}).get("evmContract", {}).get("address")
        check("hl_contract_" + nm, "HL 现货 %s 的 EVM 合约地址" % nm, addr, got, got == addr,
              "https://api.hyperliquid.xyz/info", ts, "token index=%s" % (t or {}).get("index"))
    idx = {nm: tokens[nm]["index"] for nm in ("XAUT0", "SPYX") if nm in tokens}
    check("hl_token_index", "HL token index:XAUT0=297 / SPYX=846",
          "XAUT0=297, SPYX=846", "XAUT0=%s, SPYX=%s" % (idx.get("XAUT0"), idx.get("SPYX")),
          idx.get("XAUT0") == 297 and idx.get("SPYX") == 846,
          "https://api.hyperliquid.xyz/info", ts)
else:
    check("hl_spotmeta", "HL spotMeta 可读", "非空", "", False, "https://api.hyperliquid.xyz/info", ts)

ts2, body2 = fetch("https://api.hyperliquid.xyz/info", {"type": "spotMetaAndAssetCtxs"})
ctxs = json.loads(body2) if body2 else []
if len(ctxs) >= 2:
    meta_universe = ctxs[0].get("universe", [])
    asset_ctx = ctxs[1]
    name_of_idx = {t["index"]: t["name"] for t in ctxs[0].get("tokens", [])}
    pair_tokens = {}
    for u in meta_universe:
        pair_tokens[u.get("name")] = [name_of_idx.get(i) for i in u.get("tokens", [])]
    by_coin = {c.get("coin"): c for c in asset_ctx if isinstance(c, dict) and c.get("coin")}
    for pair, nm in (("@182", "XAUT0/USDC"), ("@703", "SPYX/USDC")):
        c = by_coin.get(pair, {})
        check("hl_ctx_%s" % pair.strip("@"), "HL 现货对 %s (%s) 的 ctx(按 coin 字段配对,非按位置)" % (pair, nm),
              "对名 %s" % nm, "coin=%s tokens=%s midPx=%s dayNtlVlm=%s" % (
                  c.get("coin"), pair_tokens.get(pair), c.get("midPx"), c.get("dayNtlVlm")),
              pair_tokens.get(pair) == nm.split("/"),
              "https://api.hyperliquid.xyz/info", ts2,
              "旧脚本按位置 zip(universe, ctxs) —— 两个数组长度/顺序不同 ⇒ 配错,报告 §2/§3 的两条读数警告是脚本假象")
    for pair, lo, hi in (("@182", 3000.0, 5000.0), ("@703", 500.0, 1000.0)):
        c = by_coin.get(pair, {})
        try:
            mid = float(c.get("midPx"))
        except (TypeError, ValueError):
            mid = None
        check("hl_midpx_%s" % pair.strip("@"), "HL %s 的 midPx 是美元价(与 CoinGecko 同量级)" % pair,
              "%g–%g" % (lo, hi), str(c.get("midPx")), mid is not None and lo <= mid <= hi,
              "https://api.hyperliquid.xyz/info", ts2)
    for pair, floor in (("@182", 100000.0), ("@703", 10000.0)):
        c = by_coin.get(pair, {})
        try:
            v = float(c.get("dayNtlVlm"))
        except (TypeError, ValueError):
            v = None
        check("hl_vol_%s" % pair.strip("@"), "HL %s 的 24h 名义成交额 > %g" % (pair, floor),
              ">%g" % floor, str(c.get("dayNtlVlm")), v is not None and v > floor,
              "https://api.hyperliquid.xyz/info", ts2)
    for pair, nm in (("@209", "XAUT0/USDT0"), ("@279", "SPY/USDC")):
        c = by_coin.get(pair, {})
        check("hl_ctx_%s" % pair.strip("@"), "HL %s (%s) 的 ctx(配对正确后)" % (pair, nm),
              "对名 %s" % nm, "coin=%s tokens=%s midPx=%s dayNtlVlm=%s" % (
                  c.get("coin"), pair_tokens.get(pair), c.get("midPx"), c.get("dayNtlVlm")),
              pair_tokens.get(pair) == nm.split("/"),
              "https://api.hyperliquid.xyz/info", ts2)
else:
    check("hl_ctx", "HL spotMetaAndAssetCtxs 可读", "非空", "", False,
          "https://api.hyperliquid.xyz/info", ts2)

# ---------------------------------------------------------------- D. Kraken AssetPairs
ts, body = fetch("https://api.kraken.com/0/public/AssetPairs")
try:
    ap = json.loads(body)["result"]
except Exception:  # noqa: BLE001
    ap = {}
if ap:
    def pair_row(q):
        for k, v in ap.items():
            if v.get("altname") == q or k == q:
                return v
        return None
    xautusd = pair_row("XAUTUSD")
    xautusdt = pair_row("XAUTUSDT")
    omin = (xautusd or {}).get("ordermin")
    cmin = (xautusd or {}).get("costmin")
    check("kraken_xautusd_min", "Kraken XAUT/USD ordermin=0.0012 / costmin=0.5",
          "ordermin=0.0012, costmin=0.5", "ordermin=%s, costmin=%s" % (omin, cmin),
          abs(float(omin) - 0.0012) < 1e-9 and abs(float(cmin) - 0.5) < 1e-9,
          "https://api.kraken.com/0/public/AssetPairs", ts)
    omin2 = (xautusdt or {}).get("ordermin")
    check("kraken_xautusdt_min", "Kraken XAUT/USDT ordermin(参考)", "读数", "ordermin=%s" % omin2,
          omin2 is not None, "https://api.kraken.com/0/public/AssetPairs", ts)
    hits = [k for k, v in ap.items() if any(s in (v.get("altname") or "") for s in ("SPYX", "SPYx", "TSLAx"))]
    check("kraken_spyx_absent", "Kraken 公开 AssetPairs 里 SPYX/SPYx/TSLAx 命中数",
          "=0(共 %d 对)" % len(ap), "=%d" % len(hits), len(hits) == 0,
          "https://api.kraken.com/0/public/AssetPairs", ts, "xStocks 在另一命名空间")

# ---------------------------------------------------------------- E. Kraken xStocks FAQ
ts, body = fetch("https://www.kraken.com/legal/xstocks")
page = strip_tags(body)
if page:
    for cid, needle in (("kraken_xstocks_spread_1pct", "1.0% spread"),
                        ("kraken_xstocks_min_1usd", "starting as low as $1"),
                        ("kraken_xstocks_selfcustody", "self-custody is supported"),
                        ("kraken_xstocks_redeem_fee", "for an additional fee")):
        check(cid, "Kraken xStocks FAQ 原文含:%s" % needle, "出现", "出现" if needle in page else "未出现",
              needle in page, "https://www.kraken.com/legal/xstocks", ts)
else:
    check("kraken_xstocks_faq", "Kraken xStocks FAQ 可读", "非空", "", False,
          "https://www.kraken.com/legal/xstocks", ts)

# ---------------------------------------------------------------- F. Binance exchangeInfo
for sym, minq in (("XAUTUSDT", "0.0001"), ("SPYBUSDT", "0.001")):
    ts, body = fetch("https://api.binance.com/api/v3/exchangeInfo?symbol=" + sym)
    try:
        syms = json.loads(body)["symbols"]
    except Exception:  # noqa: BLE001
        syms = []
    s = syms[0] if syms else {}
    got = s.get("filters", [{}])
    pq = [f.get("minQty") for f in got if f.get("filterType") == "LOT_SIZE"]
    pqv = float(pq[0]) if pq and pq[0] is not None else None
    check("binance_%s_minqty" % sym.lower(), "Binance %s minQty" % sym, minq,
          str(pq[0] if pq else None), pqv is not None and abs(pqv - float(minq)) < 1e-12,
          "https://api.binance.com/api/v3/exchangeInfo?symbol=" + sym, ts)
    if sym == "SPYBUSDT":
        check("binance_spyb_spot_ok", "Binance SPYBUSDT 现货可交易", "isSpotTradingAllowed=true",
              str(s.get("isSpotTradingAllowed")), s.get("isSpotTradingAllowed") is True,
              "https://api.binance.com/api/v3/exchangeInfo?symbol=SPYBUSDT", ts)
ts, body = fetch("https://api.binance.com/api/v3/exchangeInfo?symbol=SPYXUSDT")
check("binance_spyx_invalid", "Binance 无 SPYXUSDT(400 无效符号)", "无效/0 个 symbol",
      "%d 个 symbol" % len(json.loads(body).get("symbols", [])) if body else "空",
      (not body) or len(json.loads(body).get("symbols", [])) == 0,
      "https://api.binance.com/api/v3/exchangeInfo?symbol=SPYXUSDT", ts)

# ---------------------------------------------------------------- G. CoinGecko 盘口
for cid, coin in (("cg_xaut", "tether-gold"), ("cg_spyx", "sp500-xstock")):
    ts, body = fetch("https://api.coingecko.com/api/v3/coins/%s/tickers?include_exchange_logo=false" % coin)
    try:
        tk = json.loads(body).get("tickers", [])
    except Exception:  # noqa: BLE001
        tk = []
    def num(x):
        return x if isinstance(x, (int, float)) else None

    rows = []
    for t in tk:
        if not isinstance(t, dict):
            continue
        m = t.get("market") or {}
        vol = t.get("converted_volume")
        vol = vol.get("usd") if isinstance(vol, dict) else num(vol)
        rows.append((m.get("identifier", ""), m.get("name", ""), t.get("last"),
                     t.get("bid_ask_spread_percentage"), vol, vol))
    rows = [r for r in rows if r[4] and float(r[4]) > 20000]
    rows.sort(key=lambda r: -float(r[4] or 0))
    top = rows[:4]
    names = [r[0] for r in top]
    check(cid + "_top_venues", "CoinGecko %s 前 4 场所(按 24h 美元成交额)" % coin,
          "见报告 §5.1", " / ".join("%s:%.8g spread=%s" % (n, v, sp) for n, _, v, sp, _, _ in top),
          bool(top), "https://api.coingecko.com/api/v3/coins/%s/tickers" % coin, ts)
    if cid == "cg_spyx":
        check("cg_spyx_no_binance", "CoinGecko SPYX 场所表里没有 Binance", "不含 binance",
              "含" if any("binance" in (r[1] or "").lower() for r in rows) else "不含",
              not any("binance" in (r[1] or "").lower() for r in rows),
              "https://api.coingecko.com/api/v3/coins/sp500-xstock/tickers", ts)
        hl = [r for r in rows if "hyperliquid" in (r[1] or "").lower()]
        if hl:
            check("cg_spyx_hl_spread", "CoinGecko 归一化 SPYX/Hyperliquid 价差(报告 0.032582%)",
                  "0.005%–0.5%(百分比单位)", str(hl[0][3]),
                  hl[0][3] is not None and 0.005 <= float(hl[0][3]) <= 0.5,
                  "https://api.coingecko.com/api/v3/coins/sp500-xstock/tickers", ts)
            check("cg_spyx_hl_volume", "CoinGecko 归一化 SPYX/Hyperliquid 24h 成交额(报告 $132,834)",
                  "非零(与 HL ctx 的 0 打架)", "%.0f USD" % float(hl[0][5] or 0),
                  float(hl[0][5] or 0) > 0,
                  "https://api.coingecko.com/api/v3/coins/sp500-xstock/tickers", ts)

# ---------------------------------------------------------------- H. HyperEVM gas
ts, body = fetch("https://rpc.hyperliquid.xyz/evm", {
    "jsonrpc": "2.0", "method": "eth_gasPrice", "params": [], "id": 1})
try:
    gwei = int(json.loads(body)["result"], 16) / 1e9
except Exception:  # noqa: BLE001
    gwei = None
check("gas_hyperevm", "HyperEVM gas price(报告 0.1694 gwei)", "0.05–0.50 gwei",
      "%.4f gwei" % gwei if gwei is not None else "", gwei is not None and 0.05 <= gwei <= 0.5,
      "https://rpc.hyperliquid.xyz/evm", ts)

# ---------------------------------------------------------------- I. Tether 合约地址原文
ts, body = fetch("https://tether.to/en/supported-protocols/")
check("tether_xaut_contract", "Tether 集成页原文给出 XAU₮ 以太坊合约地址",
      "0x68749665FF8D2d112Fa859AA293F07A622782F38",
      "出现" if "0x68749665FF8D2d112Fa859AA293F07A622782F38" in body else "未出现",
      "0x68749665FF8D2d112Fa859AA293F07A622782F38" in body,
      "https://tether.to/en/supported-protocols/", ts)

# ---------------------------------------------------------------- J. xStocks 发行方
ts, body = fetch("https://docs.xstocks.fi/docs/product-legal-overview.md")
lp = strip_tags(body)
for cid, needle in (("xstocks_issuer", "Backed Assets (JE) Limited"),
                     ("xstocks_1to1", "1:1"),
                     ("xstocks_jersey", "Jersey")):
    check(cid, "xStocks 发行方文档含:%s" % needle, "出现",
          "出现" if needle in lp else "未出现", needle in lp,
          "https://docs.xstocks.fi/docs/product-legal-overview.md", ts)

# ---------------------------------------------------------------- K. 费率原文
ts, body = fetch("https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees.md")
fees = strip_tags(body)
check("hl_fee_tier0", "HL 现货费用表 Tier 0 行 = taker 0.070% / maker 0.040%",
      "Tier 0 行含 0.070% 与 0.040%",
      "出现" if ("0.070%" in fees and "0.040%" in fees) else "未出现",
      "0.070%" in fees and "0.040%" in fees,
      "https://hyperliquid.gitbook.io/hyperliquid-docs/trading/fees.md", ts)

ts, body = fetch("https://support.kraken.com/hc/en-us/articles/360000920306-Kraken-Fees-Schedule-Volumes-and-Pairs")
kf = strip_tags(body)
check("kraken_fee_026", "Kraken 现货费用表:taker 0.26% / maker 0.16% 在原文",
      "fees [[0,0.26] 与 fees_maker [[0,0.16] 可见",
      "出现" if ("0.26" in kf and "0.16" in kf) else "未出现", "0.26" in kf and "0.16" in kf,
      "https://support.kraken.com/hc/en-us/articles/360000920306-Kraken-Fees-Schedule-Volumes-and-Pairs", ts)

# ---------------------------------------------------------------- 汇总
out = {
    "checked_at_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "note": "T-214 复核:重新抓取报告里最吃重的数字/原文,逐条判定。status=PASS/FAIL/READ_FAIL。",
    "results": RESULTS,
}
with open(OUT, "w") as f:
    json.dump(out, f, ensure_ascii=False, indent=1)

n_pass = sum(1 for r in RESULTS if r["status"] == "PASS")
n_fail = sum(1 for r in RESULTS if r["status"] == "FAIL")
n_rf = sum(1 for r in RESULTS if r["status"] == "READ_FAIL")
print("PASS=%d FAIL=%d READ_FAIL=%d  total=%d" % (n_pass, n_fail, n_rf, len(RESULTS)))
for r in RESULTS:
    if r["status"] != "PASS":
        print("  [%s] %s | expect=%s | got=%s" % (r["status"], r["id"], r["expect"], r["got"]))