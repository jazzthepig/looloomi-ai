"""T-188 — 灵活组合非加密腿(金 20% / 股 30%)在链上的持有场所:公开数据测量。

只读脚本。不注册、不连钱包、不下单、不填表。
数据源(全部公开接口):
  - Hyperliquid info API  https://api.hyperliquid.xyz/info   (HIP-3 dex / 现货 / l2Book / candle / funding)
  - CoinGecko Pro          https://pro-api.coingecko.com/api/v3 (代币行情、逐日成交、场所档口)
  - DexScreener            https://api.dexscreener.com          (AMM 池子流动性与成交)
  - 交易所公开订单簿       Binance / OKX / Kraken / Coinbase 公共 REST
  - Supabase REST          ohlcv_daily (库内 GLD / SPY / QQQ / AAPL 日线,作跟踪误差基准)

输出: docs/research/t188_venues.json
用法: python3 docs/research/t188_venues.py
"""
from __future__ import annotations

import json
import math
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "t188_venues.json")
# 取数日 = 抓取时刻的 UTC 日期。Mac 侧时钟是 JST,直接用本地日期会写成次日。
ASOF = datetime.now(timezone.utc).strftime("%Y-%m-%d")

UA = {"User-Agent": "cometcloud-research/1.0 (T-188)"}
HL = "https://api.hyperliquid.xyz/info"
CG = "https://pro-api.coingecko.com/api/v3"
CG_KEY = os.environ.get("COINGECKO_API_KEY", "")


# ---------------------------------------------------------------- http helpers
def _get(url, headers=None, timeout=60):
    req = urllib.request.Request(url, headers={**UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _post(url, payload, timeout=60):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={**UA, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _try(fn, *a, **kw):
    """网络调用容错:失败不中断整轮,错误记进结果。"""
    try:
        return fn(*a, **kw)
    except urllib.error.HTTPError as e:
        return {"__error__": f"HTTP {e.code}"}
    except Exception as e:  # noqa: BLE001
        return {"__error__": f"{type(e).__name__}: {e}"}


def cg(path, params=None):
    url = CG + path
    if params:
        url += "?" + urllib.parse.urlencode({k: str(v) for k, v in params.items()})
    return _get(url, {"x-cg-pro-api-key": CG_KEY})


# ---------------------------------------------------------------- HL: 永续
HL_GOLD = [("xyz", "xyz:GOLD"), ("flx", "flx:GOLD"), ("hyna", "hyna:GOLD"),
           ("km", "km:GOLD"), ("mkts", "mkts:GOLD"), ("cash", "cash:GOLD"),
           ("vntl", "vntl:GOLDJM"), ("para", "para:GDX")]
HL_EQ = [("xyz", "xyz:SP500"), ("xyz", "xyz:XYZ100"), ("km", "km:US500"),
         ("mkts", "mkts:US500"), ("km", "km:USTECH"), ("km", "km:SMALL2000"),
         ("para", "para:IGV"), ("flx", "flx:USA500"), ("flx", "flx:USA100"),
         ("xyz", "xyz:SOXL"), ("xyz", "xyz:MAGS"), ("xyz", "xyz:XBI"),
         ("xyz", "xyz:XLE"), ("para", "para:GDX"), ("para", "para:SMH")]
HL_STOCK = [("xyz", "xyz:AAPL"), ("xyz", "xyz:NVDA"), ("xyz", "xyz:TSLA"),
            ("km", "km:AAPL"), ("cash", "cash:AAPL")]


def depth_from_levels(bids, asks):
    """订单簿 → 中间价、点差(bp)、±0.5%/±1% 深度(双边合计, USD)。"""
    if not bids or not asks:
        return None
    bb, ba = float(bids[0]["px"]), float(asks[0]["px"])
    if bb <= 0 or ba <= 0:
        return None
    mid = (bb + ba) / 2.0
    out = {"mid": mid, "bid1": bb, "ask1": ba,
           "spread_bps": (ba - bb) / mid * 1e4,
           "n_levels_bid": len(bids), "n_levels_ask": len(asks)}
    for band in (0.005, 0.01):
        lo, hi = mid * (1 - band), mid * (1 + band)
        b = sum(float(l["px"]) * float(l["sz"]) for l in bids if float(l["px"]) >= lo)
        a = sum(float(l["px"]) * float(l["sz"]) for l in asks if float(l["px"]) <= hi)
        k = int(band * 1000)
        out[f"bid_usd_{k}bp"] = b
        out[f"ask_usd_{k}bp"] = a
        out[f"depth_usd_{k}bp"] = b + a
        out[f"bid_levels_{k}bp"] = sum(1 for l in bids if float(l["px"]) >= lo)
        out[f"ask_levels_{k}bp"] = sum(1 for l in asks if float(l["px"]) <= hi)
    # 盘口最深档距中价的百分比(超出即 ±0.5% 覆盖全部可见深度)
    out["deepest_bid_pct"] = (mid - float(bids[-1]["px"])) / mid * 100
    out["deepest_ask_pct"] = (float(asks[-1]["px"]) - mid) / mid * 100
    return out


def hl_l2(dex, coin):
    b = _try(_post, HL, {"type": "l2Book", "coin": coin, "dex": dex})
    if not isinstance(b, dict) or "levels" not in b:
        return {"error": str(b)[:200]}
    lv = b["levels"]
    m = depth_from_levels(lv[0], lv[1])
    if m is None:
        m = {"empty_book": True, "note": "该合约当时没有可见挂单"}
    m["book_time_ms"] = b.get("time")
    return m


def hl_daily_candles(dex, coin, days=45):
    """日线 → 近 30 天日均成交额(USD)、日均成交笔数/张数、末日收盘。"""
    now = int(time.time() * 1000)
    req = {"coin": coin, "interval": "1d",
           "startTime": now - days * 86400000, "endTime": now}
    if dex:
        req["dex"] = dex
    c = _try(_post, HL, {"type": "candleSnapshot", "req": req})
    if not isinstance(c, list) or not c:
        return {"error": str(c)[:200]}
    rows = []
    for x in c:
        rows.append({"t": x.get("t"), "close": float(x.get("c")),
                     "vlm": float(x.get("v", 0) or 0), "n_trades": x.get("n")})
    rows.sort(key=lambda r: r["t"])
    last30 = rows[-30:]
    vlm_usd = [r["vlm"] * r["close"] for r in last30]
    return {
        "n_days": len(rows),
        "avg_daily_volume_usd_30d": (sum(vlm_usd) / len(vlm_usd)) if vlm_usd else None,
        "last_close": rows[-1]["close"] if rows else None,
        "last_day_utc": datetime.fromtimestamp(rows[-1]["t"] / 1000, timezone.utc).date().isoformat() if rows else None,
        "daily_volume_usd_last10": vlm_usd[-10:],
    }


def hl_funding(dex, coin, days=30):
    """资金费历史 → 多头持有成本(年化)。HIP-3 每小时结算,按 8h 折算再年化。"""
    now = int(time.time() * 1000)
    start = now - days * 86400000
    recs, cursor = [], start
    for _ in range(6):                      # 每次最多 500 条,翻页
        p = {"type": "fundingHistory", "coin": coin, "startTime": cursor, "endTime": now}
        if dex:
            p["dex"] = dex
        c = _try(_post, HL, p)
        if not isinstance(c, list) or not c:
            break
        recs.extend(c)
        oldest = min(int(x["time"]) for x in c)
        if oldest >= cursor:
            break
        cursor = oldest - 1
        if len(c) < 500:
            break
        time.sleep(0.2)
    if not recs:
        return {"error": str(recs)[:200] if not isinstance(recs, list) else "no rows"}
    uniq = {int(x["time"]): float(x["fundingRate"]) for x in recs}
    times = sorted(uniq)
    rates = [uniq[t] for t in times]
    # 频率:相邻记录间隔
    gaps = [times[i + 1] - times[i] for i in range(len(times) - 1)]
    step_ms = min(gaps) if gaps else 3600000
    per_year = 365 * 24 * 3600 * 1000 / step_ms
    ann = sum(rates) / len(rates) * per_year * 100
    return {
        "n_records": len(rates),
        "funding_interval_hours": step_ms / 3600000.0,
        "mean_funding_per_interval": sum(rates) / len(rates),
        "annualised_pct_long_side": ann,
        "sum_last_30d": sum(rates),
        "first_utc": datetime.fromtimestamp(times[0] / 1000, timezone.utc).date().isoformat(),
        "last_utc": datetime.fromtimestamp(times[-1] / 1000, timezone.utc).date().isoformat(),
    }


def hl_perp_leg(coins):
    out = {}
    for dex, coin in coins:
        key = coin
        rec = {}
        rec["dex"] = dex
        rec["dex_full_name"] = None
        rec["l2book"] = hl_l2(dex, coin)
        rec["candles"] = hl_daily_candles(dex, coin)
        rec["funding"] = hl_funding(dex, coin)
        out[key] = rec
        time.sleep(0.15)
    return out


def hl_perp_dexes():
    d = _try(_post, HL, {"type": "perpDexs"})
    out = []
    if isinstance(d, list):
        for x in d:
            if not isinstance(x, dict):
                continue
            out.append({"name": x.get("name"), "fullName": x.get("fullName"),
                        "deployer": x.get("deployer"), "oracleUpdater": x.get("oracleUpdater")})
    return out


def hl_spot_pairs():
    """HL 现货:有没有黄金 / 股票现货对。"""
    smc = _try(_post, HL, {"type": "spotMetaAndAssetCtxs"})
    if not (isinstance(smc, list) and len(smc) >= 2):
        return {"error": str(smc)[:200]}
    uni = smc[0].get("universe", [])
    ctxs = smc[1]
    rows = []
    for u, c in zip(uni, ctxs):
        rows.append({"name": u.get("name"), "index": u.get("index"),
                     "tokens": u.get("tokens"),
                     "dayNtlVlm": (c or {}).get("dayNtlVlm") if isinstance(c, dict) else None,
                     "prevDayPx": (c or {}).get("prevDayPx") if isinstance(c, dict) else None,
                     "markPx": (c or {}).get("markPx") if isinstance(c, dict) else None})
    gold = [r for r in rows if any(k in (r["name"] or "").upper() for k in ("PAXG", "XAUT", "GOLD", "XAU"))]
    return {"n_pairs": len(rows),
            "gold_or_equity_spot_pairs": gold,
            "sample_pair_names": [r["name"] for r in rows if not (r["name"] or "").startswith("@")][:60]}


# ---------------------------------------------------------------- 代币现货
TOKENS = [
    # (cg_id, symbol, 腿, 基准(symbol in ohlcv_daily), 合约地址或 None)
    ("pax-gold", "PAXG", "gold", "GLD", "0x45804880De22913dafe09f4980848ece6F6B885C"),
    ("tether-gold", "XAUT", "gold", "GLD", "0x68749665FF8D2d112fa859Aa293f07A622782f38"),
    ("gold-xstock", "GLDX", "gold", "GLD", "0x2380F2673C640fB67E2d6B55B44C62F0E0e69DA9"),
    ("sp500-xstock", "SPYX", "equity", "SPY", None),
    ("nasdaq-xstock", "QQQX", "equity", "QQQ", None),
    ("apple-xstock", "AAPLX", "equity", "AAPL", None),
]


def cg_coin(cg_id):
    d = cg("/coins/" + cg_id, {"localization": "false", "tickers": "true", "market_data": "true",
                                "community_data": "false", "developer_data": "false", "sparkline": "false"})
    if not isinstance(d, dict) or "id" not in d:
        return {"error": str(d)[:200]}
    md = d.get("market_data", {}) or {}
    plats = d.get("platforms", {}) or {}
    contracts = {k: v for k, v in plats.items() if isinstance(v, str) and v.startswith("0x")}
    tickers = []
    for t in d.get("tickers", []) or []:
        tickers.append({
            "market": (t.get("market") or {}).get("name"),
            "base": t.get("base"), "target": t.get("target"),
            "vol24_usd": (t.get("converted_volume") or {}).get("usd"),
            "last": t.get("last"),
            "spread_pct": t.get("bid_ask_spread_percentage"),
            "bid": t.get("bid"), "ask": t.get("ask"),
            "stale": t.get("is_stale"), "anomaly": t.get("is_anomaly"),
            "trade_url": t.get("trade_url"),
        })
    tickers.sort(key=lambda x: (x["vol24_usd"] or 0), reverse=True)
    return {
        "cg_id": cg_id, "symbol": d.get("symbol"), "name": d.get("name"),
        "price_usd": (md.get("current_price") or {}).get("usd"),
        "market_cap_usd": (md.get("market_cap") or {}).get("usd"),
        "total_volume_24h_usd": md.get("total_volume", {}).get("usd") if isinstance(md.get("total_volume"), dict) else md.get("total_volume"),
        "contracts": contracts,
        "tickers_top": tickers[:14],
        "n_tickers": len(tickers),
    }


def cg_series(cg_id, days=120):
    """逐日价格 + 逐日总成交额(全场所合计)。"""
    mc = cg("/coins/" + cg_id + "/market_chart", {"vs_currency": "usd", "days": days,
                                                   "precision": "full"})
    if not isinstance(mc, dict) or "prices" not in mc:
        return {"error": str(mc)[:200]}
    def to_map(lst):
        return {datetime.fromtimestamp(p[0] / 1000, timezone.utc).date().isoformat(): p[1] for p in lst}
    px = to_map(mc.get("prices", []))
    vol = to_map(mc.get("total_volumes", []))
    return {"prices": px, "total_volumes": vol}


def dexscreener_pools(address):
    """AMM 池子:流动性、24h 成交、币价。"""
    if not address:
        return []
    d = _try(_get, f"https://api.dexscreener.com/latest/dex/tokens/{address}")
    pairs = (d or {}).get("pairs") or []
    rows = []
    for p in pairs[:14]:
        liq = (p.get("liquidity") or {}).get("usd")
        base = (p.get("liquidity") or {}).get("base")
        quote = (p.get("liquidity") or {}).get("quote")
        row = {"dex": p.get("dexId"), "pair": (p.get("baseToken") or {}).get("symbol", "") + "/" + (p.get("quoteToken") or {}).get("symbol", ""),
               "price_usd": p.get("priceUsd"), "liquidity_usd": liq,
               "vol24h_usd": (p.get("volume") or {}).get("h24"),
               "fdv": p.get("fdv"), "url": p.get("url"),
               "created": p.get("pairCreatedAt")}
        row["amm_depth_estimate"] = amm_depth_estimate(base, quote, p.get("priceUsd"))
        rows.append(row)
    rows.sort(key=lambda x: (x["liquidity_usd"] or 0), reverse=True)
    return rows


def amm_depth_estimate(base, quote, price_usd):
    """AMM(恒定乘积)深度估算方法:
    对 Uniswap v2 型池,价格 p = y/x;用 quote 买入 base 后新价格 p' = (y+q)^2/(x*y),
    故使价格移动 f 所需的 quote 流入 q = y*(sqrt(1+f)-1)。bid 侧对称。
    v3 集中流动性的储备随 tick 变化,同一公式只是近似(会高估远离当前价的部分),
    因此结果标注为「估算」并写明方法。返回 None 表示缺储备数据。"""
    try:
        y = float(quote)
        if y <= 0 or not price_usd:
            return None
        out = {"method": "constant-product q = y*(sqrt(1+f)-1), 双边合计", "quote_reserve": y}
        for band in (0.005, 0.01):
            q_up = y * (math.sqrt(1 + band) - 1.0)
            q_dn = y * (1.0 - 1.0 / math.sqrt(1 + band))
            out[f"depth_usd_{int(band*1000)}bp"] = (q_up + q_dn) * float(price_usd)
        return out
    except Exception:
        return None


# ---------------------------------------------------------------- 交易所订单簿(实测)
def book_binance(symbol):
    d = _try(_get, f"https://api.binance.com/api/v3/depth?symbol={symbol}&limit=1000")
    if not isinstance(d, dict) or "bids" not in d:
        return {"error": str(d)[:200]}
    bids = [{"px": p, "sz": q} for p, q in d["bids"]]
    asks = [{"px": p, "sz": q} for p, q in d["asks"]]
    m = depth_from_levels(bids, asks)
    if m:
        m["venue"] = "Binance"
        m["pair"] = symbol
    return m or {"error": "empty"}


def book_okx(inst_id):
    d = _try(_get, f"https://www.okx.com/api/v5/market/books?instId={inst_id}&sz=100")
    if not isinstance(d, dict) or d.get("code") != "0":
        return {"error": str(d)[:200]}
    bk = (d.get("data") or [{}])[0]
    bids = [{"px": x[0], "sz": x[1]} for x in bk.get("bids", [])]
    asks = [{"px": x[0], "sz": x[1]} for x in bk.get("asks", [])]
    m = depth_from_levels(bids, asks)
    if m:
        m["venue"] = "OKX"
        m["pair"] = inst_id
    return m or {"error": "empty"}


def book_kraken(pair):
    d = _try(_get, f"https://api.kraken.com/0/public/Depth?pair={pair}&count=500")
    if not isinstance(d, dict) or d.get("error"):
        return {"error": str(d)[:200]}
    res = d.get("result") or {}
    key = [k for k in res if k != "last"]
    if not key:
        return {"error": "no pair"}
    bk = res[key[0]]
    bids = [{"px": r[0], "sz": r[1]} for r in bk.get("bids", [])]
    asks = [{"px": r[0], "sz": r[1]} for r in bk.get("asks", [])]
    m = depth_from_levels(bids, asks)
    if m:
        m["venue"] = "Kraken"
        m["pair"] = key[0]
    return m or {"error": "empty"}


def book_coinbase(product):
    d = _try(_get, f"https://api.exchange.coinbase.com/products/{product}/book?level=2")
    if not isinstance(d, dict) or "bids" not in d:
        return {"error": str(d)[:200]}
    bids = [{"px": x[0], "sz": x[1]} for x in d["bids"]]
    asks = [{"px": x[0], "sz": x[1]} for x in d["asks"]]
    m = depth_from_levels(bids, asks)
    if m:
        m["venue"] = "Coinbase"
        m["pair"] = product
    return m or {"error": "empty"}


# ---------------------------------------------------------------- 库内基准
SB_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SB_KEY = os.environ.get("SUPABASE_KEY", "")
SB_HDR = {"apikey": SB_KEY, "Authorization": "Bearer " + SB_KEY, **UA}


def sb_closes(symbol, source="eodhd", limit=400):
    """库内日线收盘(单一来源,倒序取最近 limit 条)。
    注意:同一 symbol 在库里可能有多个来源(eodhd / yfinance),日期会重复 ⇒ 必须按来源过滤。"""
    if not SB_URL:
        return {"error": "SUPABASE_URL 未设置"}
    q = urllib.parse.urlencode({"symbol": f"eq.{symbol}", "select": "trade_date,close,source",
                                "source": f"eq.{source}", "order": "trade_date.desc", "limit": limit})
    url = f"{SB_URL}/rest/v1/ohlcv_daily?{q}"
    rows = _try(_get, url, SB_HDR)
    if not isinstance(rows, list):
        return {"error": str(rows)[:200]}
    d = {}
    for r in rows:
        if r.get("close") is not None:
            d[r["trade_date"]] = float(r["close"])
    return {"closes": d, "source": source, "n": len(d),
            "first": min(d) if d else None, "last": max(d) if d else None}


# ---------------------------------------------------------------- 跟踪误差
def daily_returns(px):
    ds = sorted(px)
    out = {}
    for i in range(1, len(ds)):
        a, b = px[ds[i - 1]], px[ds[i]]
        if a and b and a > 0 and b > 0:
            out[ds[i]] = b / a - 1.0
    return out


def tracking(token_px, bench_px):
    """近 90 天(按基准交易日)日收益相关 + 年化跟踪误差。

    对齐口径(必须写清):CoinGecko 的逐日价是「该日历日 00:00 UTC 的快照」,
    落在美股当日收盘(约 21:00 UTC)之后 3 小时 ⇒ 基准日 d 的 ETF 收盘
    对应代币的 t(d+1)。因此把代币价平移:A[d] = t(d+1),再在基准的交易日序列上算收益。
    代币 7×24 交易、ETF 5 日 ⇒ 周末的代币漂移会落在下一个交易日的收益里,
    这是真实的跟踪噪声,不是口径错误。
    """
    bd = sorted(bench_px)

    def _align(shift):
        al = {}
        for d in bd:
            nxt = (datetime.fromisoformat(d) + timedelta(days=shift)).date().isoformat()
            if nxt in token_px:
                al[d] = token_px[nxt]
        return al

    def _stats(shift):
        al = _align(shift)
        ds = [d for d in bd if d in al]
        if len(ds) < 30:
            return None
        cutoff = (datetime.fromisoformat(ds[-1]) - timedelta(days=90)).date().isoformat()
        ds = [d for d in ds if d >= cutoff]
        x, y = [], []
        for i in range(1, len(ds)):
            if al[ds[i - 1]] > 0 and bench_px[ds[i - 1]] > 0:
                x.append(al[ds[i]] / al[ds[i - 1]] - 1.0)
                y.append(bench_px[ds[i]] / bench_px[ds[i - 1]] - 1.0)
        n = len(x)
        if n < 30:
            return None
        mx, my = sum(x) / n, sum(y) / n
        vx = sum((v - mx) ** 2 for v in x) / (n - 1)
        vy = sum((v - my) ** 2 for v in y) / (n - 1)
        cov = sum((x[i] - mx) * (y[i] - my) for i in range(n)) / (n - 1)
        corr = cov / math.sqrt(vx * vy) if vx > 0 and vy > 0 else None
        diff = [x[i] - y[i] for i in range(n)]
        md = sum(diff) / n
        sd = math.sqrt(sum((v - md) ** 2 for v in diff) / (n - 1))
        return {"n": n, "ds": ds, "x": x, "y": y, "corr": corr, "sd": sd, "md": md}

    s1 = _stats(1)
    s0 = _stats(0)
    if s1 is None:
        return {"error": "可对齐的基准交易日不足 30 天"}
    x, y, n = s1["x"], s1["y"], s1["n"]
    ds = s1["ds"]
    return {
        "n_common_days": n, "window_start": ds[0], "window_end": ds[-1],
        "alignment": "token t(d+1) vs benchmark close(d); CoinGecko 逐日快照 = 该日 00:00 UTC(在美股前一日收盘后约 3 小时)",
        "corr_daily_returns": s1["corr"],
        "tracking_error_annualised_pct": s1["sd"] * math.sqrt(365) * 100,
        "tracking_error_daily_bp": s1["sd"] * 1e4,
        "token_ann_return_pct": (math.prod(1 + v for v in x) ** (365 / n) - 1) * 100,
        "bench_ann_return_pct": (math.prod(1 + v for v in y) ** (365 / n) - 1) * 100,
        "mean_daily_diff_bp": s1["md"] * 1e4,
        "token_cum_pct": (math.prod(1 + v for v in x) - 1) * 100,
        "bench_cum_pct": (math.prod(1 + v for v in y) - 1) * 100,
        "corr_alt_alignment_shift0": (s0 or {}).get("corr"),
        "_note_alt": "shift0 = token t(d) vs benchmark close(d),仅作时间戳口径的敏感性对照,不是另一个候选口径",
    }


def discover_binance_pairs(want):
    """在 Binance 现货里找我们关心的代币对(只读 exchangeInfo)。"""
    d = _try(_get, "https://api.binance.com/api/v3/exchangeInfo?permissions=SPOT")
    if not isinstance(d, dict) or "symbols" not in d:
        return {"error": str(d)[:200]}
    out = []
    for s in d["symbols"]:
        if s.get("status") != "TRADING":
            continue
        b = s.get("baseAsset", "")
        if b.upper() in want:
            out.append({"symbol": s["symbol"], "base": b, "quote": s.get("quoteAsset")})
    return out


def discover_kraken_pairs(want):
    d = _try(_get, "https://api.kraken.com/0/public/AssetPairs")
    if not isinstance(d, dict) or d.get("error"):
        return {"error": str(d)[:200]}
    out = []
    for k, v in (d.get("result") or {}).items():
        ws = v.get("wsname") or ""
        base = (v.get("base") or "")
        if base.upper() in want or any(w in ws.upper() for w in want):
            out.append({"pair": k, "wsname": ws, "base": base, "quote": v.get("quote")})
    return out


def discover_okx_pairs(want):
    d = _try(_get, "https://www.okx.com/api/v5/public/instruments?instType=SPOT")
    if not isinstance(d, dict) or d.get("code") != "0":
        return {"error": str(d)[:200]}
    out = []
    for it in d.get("data", []):
        if it.get("state") != "live":
            continue
        if it.get("baseCcy", "").upper() in want:
            out.append({"instId": it.get("instId"), "base": it.get("baseCcy"), "quote": it.get("quoteCcy")})
    return out


# ---------------------------------------------------------------- 主流程
def main():
    out = {"asof": ASOF, "generated_utc": datetime.now(timezone.utc).isoformat(),
           "note": "全部为公开接口只读测量;未注册、未连钱包、未下单。"}

    print("[1/6] HL HIP-3 dex 列表")
    out["hl_perp_dexes"] = hl_perp_dexes()

    print("[2/6] HL 黄金永续")
    out["hl_perp_gold"] = hl_perp_leg(HL_GOLD)
    print("[3/6] HL 股指/商品永续")
    out["hl_perp_index"] = hl_perp_leg(HL_EQ)
    print("[4/6] HL 个股永续")
    out["hl_perp_stock"] = hl_perp_leg(HL_STOCK)
    print("      HL 现货对")
    out["hl_spot"] = hl_spot_pairs()

    print("[5/6] 代币现货 + AMM 池")
    tokens, series = {}, {}
    for cg_id, sym, leg, bench, addr in TOKENS:
        print(f"      {cg_id}")
        rec = cg_coin(cg_id)
        rec["leg"] = leg
        rec["benchmark"] = bench
        rec["amm_pools"] = dexscreener_pools(addr or rec.get("contracts", {}).get("ethereum"))
        tokens[sym] = rec
        s = cg_series(cg_id)
        series[sym] = s
        time.sleep(1.2)
    out["tokens"] = tokens

    print("[6/6] 交易所订单簿实测")
    WANT = {"PAXG", "XAUT", "SPYX", "QQQX", "GLDX", "AAPLX", "SPY", "QQQ"}
    books, discovery = {}, {}
    bn = discover_binance_pairs(WANT)
    discovery["binance_pairs"] = bn
    ok = discover_okx_pairs(WANT)
    discovery["okx_pairs"] = ok
    kr = discover_kraken_pairs(WANT)
    discovery["kraken_pairs"] = kr
    for venue, fn, args in [
        ("Binance", book_binance, [p["symbol"] for p in bn] if isinstance(bn, list) else []),
        ("OKX", book_okx, [p["instId"] for p in ok] if isinstance(ok, list) else []),
        ("Kraken", book_kraken, [p["pair"] for p in kr] if isinstance(kr, list) else []),
        ("Coinbase", book_coinbase, ["PAXG-USD", "XAUT-USD"]),
    ]:
        for a in args:
            m = fn(a)
            books[f"{venue}:{a}"] = m
            print("     ", venue, a, "->",
                  (f"spread {m.get('spread_bps', float('nan')):.2f}bp  d0.5% ${m.get('depth_usd_5bp', 0):,.0f}"
                   if m.get("spread_bps") is not None else m.get("error", "?")[:60]))
            time.sleep(0.35)
    out["cex_book_discovery"] = discovery
    out["cex_books"] = books

    print("[7/6] 库内基准 + 跟踪误差")
    bench = {}
    for b in sorted({t[3] for t in TOKENS}):
        bench[b] = sb_closes(b)
        print("      bench", b, bench[b].get("n"), bench[b].get("sources"))
    out["benchmarks"] = bench

    te = {}
    for cg_id, sym, leg, bench_sym, _addr in TOKENS:
        bpx = (bench.get(bench_sym) or {}).get("closes") or {}
        tpx = (series.get(sym) or {}).get("prices") or {}
        if not tpx:
            te[sym] = {"error": "no token price series"}
            continue
        # 只用最近 120 天的 token 价格(对齐与窗口在 tracking() 里做)
        ds = sorted(tpx)[-121:]
        tpx90 = {d: tpx[d] for d in ds}
        te[sym] = tracking(tpx90, bpx)
        te[sym]["benchmark_symbol"] = bench_sym
        te[sym]["token_price_first"] = tpx90.get(sorted(tpx90)[0])
        te[sym]["token_price_last"] = tpx90.get(sorted(tpx90)[-1])
    out["tracking_error_90d"] = te

    # 30 天日均成交额(全场所合计,CoinGecko 逐日 total_volumes)
    vol30 = {}
    for sym, s in series.items():
        vols = (s or {}).get("total_volumes") or {}
        ds = sorted(vols)[-31:]
        vals = [vols[d] for d in ds if vols[d]]
        vol30[sym] = {"n_days": len(vals),
                      "avg_daily_volume_usd_30d": (sum(vals) / len(vals)) if vals else None,
                      "median_daily_volume_usd_30d": (sorted(vals)[len(vals) // 2]) if vals else None,
                      "window_start": ds[0] if ds else None, "window_end": ds[-1] if ds else None}
    out["token_volume_30d"] = vol30

    with open(OUT, "w") as f:
        json.dump(out, f, indent=1, default=str, ensure_ascii=False)
    print("\nwrote", OUT)
    return out


if __name__ == "__main__":
    main()
