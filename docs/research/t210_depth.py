#!/usr/bin/env python3
"""T-210 执行成本:候选代币在 CEX / DEX 上的盘口深度与三档滑点。

只读公开行情 API(Binance / Kraken / OKX / Bybit / Coinbase / GeckoTerminal /
Paraswap / CoinGecko);不下单、不注册、不碰任何 .env。

口径:
  · mid = (best_bid + best_ask) / 2
  · spread_bps = (ask - bid) / mid * 1e4
  · buy_slippage_bps = 走完 ask 侧逐档吃单得到的 VWAP 相对 mid 的偏离(正数=比 mid 贵)
  · sell_slippage_bps = 走完 bid 侧逐档吃单得到的 VWAP 相对 mid 的偏离(负数=比 mid 便宜)
  · round_trip_cost_bps = 同一名义额一买一卖的价格冲击成本(不含交易所手续费)
  · 名义额按 USD 计(USDC ≈ 1 USD)
  · DEX 侧没有连续盘口,用「名义额 ÷ 最深池储备」给出量级,并另取 Paraswap 报价(能取到时)

输出:docs/research/t210_depth.json(与本脚本同目录)
"""
import datetime
import json
import os
import time
import urllib.error
import urllib.request

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120 Safari/537.36"}
NOTIONALS = [500, 5000, 50000]
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "t210_depth.json")

# 合约地址来自 CoinGecko /coins/list?include_platform=true(脚本内再核一次)
TOKEN_ADDR = {
    "PAXG": {"cg": "pax-gold", "eth": "0x45804880De22913dafe09b4984769B7C5562aC7"},
    "XAUT": {"cg": "tether-gold", "eth": "0x68749665Ff8D2d112fa859Aa293f07A622782f38"},
    "SPYX_xstocks": {"cg": "sp500-xstock",
                     "eth": "0x90a2a4c76b5d8c0bc892a69ea28aa775a8f2dd48",
                     "solana": "XsoCS1TfEyfFhfvj8EtZ528L3CaKBDBRqRapnBbDF2W"},
    "SPY_ondo": {"cg": "spdr-s-p-500-etf-ondo-tokenized-etf",
                 "eth": "0xfedc5f4a6c38211c1338aa411018dfaf26612c08",
                 "solana": "k18WJUULWheRkSpSquYGdNNmtuE2Vbw1hpuUi92ondo"},
    "GLD_ondo": {"cg": "spdr-gold-shares-ondo-tokenized",
                 "eth": "0x423d42e505e64f99b6e277eb7ed324cc5606f139"},
    "BIL_ondo": {"cg": "spdr-bloomberg-1-3-month-t-bill-etf-ondo-tokenized",
                 "eth": "0x2710e30d84b376c34a3b3036aa196b26a83a321b"},
}


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def get(url, hdr=None):
    h = dict(UA)
    if hdr:
        h.update(hdr)
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=45) as r:
        return json.loads(r.read())


def safe(url, hdr=None):
    try:
        return get(url, hdr)
    except urllib.error.HTTPError as e:
        return {"_error": f"HTTP {e.code}"}
    except Exception as e:  # noqa: BLE001
        return {"_error": f"{type(e).__name__}: {str(e)[:120]}"}


def walk_book(bids, asks, notional_usd, side):
    """按 USD 名义额吃单,返回 (VWAP, 吃掉的档位数, 未成交额)。"""
    levels = asks if side == "buy" else bids
    total_qty = 0.0
    total_usd = 0.0
    touched = 0
    for px, qty in levels:
        px = float(px)
        qty = float(qty)
        if px <= 0 or qty <= 0:
            continue
        level_usd = px * qty
        take_usd = min(level_usd, notional_usd - total_usd)
        if take_usd <= 0:
            break
        total_qty += take_usd / px
        total_usd += take_usd
        touched += 1
        if total_usd >= notional_usd - 1e-9:
            break
    if total_usd <= 0:
        return None, 0, notional_usd
    return total_usd / total_qty, touched, max(0.0, notional_usd - total_usd)


def book_metrics(bids, asks, ts, source, extra=None):
    # 各所盘口档位可能带第三个字段(Kraken: timestamp;Coinbase: order id)——只取价与量
    def norm(raw):
        out = []
        for lvl in raw or []:
            try:
                p, q = float(lvl[0]), float(lvl[1])
            except (TypeError, ValueError, IndexError):
                continue
            if p > 0 and q > 0:
                out.append((p, q))
        return out

    bids = norm(bids)
    asks = norm(asks)
    if not bids or not asks:
        return {"source": source, "ts_utc": ts, "error": "empty book"}
    best_bid = max(float(p) for p, _ in bids)
    best_ask = min(float(p) for p, _ in asks)
    mid = (best_bid + best_ask) / 2.0
    bids_s = sorted(bids, key=lambda x: -float(x[0]))
    asks_s = sorted(asks, key=lambda x: float(x[0]))
    depth_b = sum(float(p) * float(q) for p, q in bids_s if float(p) >= mid * 0.995)
    depth_a = sum(float(p) * float(q) for p, q in asks_s if float(p) <= mid * 1.005)
    rec = {
        "source": source, "ts_utc": ts,
        "mid": mid, "best_bid": best_bid, "best_ask": best_ask,
        "spread_bps": round((best_ask - best_bid) / mid * 1e4, 4),
        "depth_0.5pct_bid_usd": round(depth_b, 2),
        "depth_0.5pct_ask_usd": round(depth_a, 2),
        "levels": {"bids": len(bids), "asks": len(asks)},
        "slippage": {},
    }
    for n in NOTIONALS:
        vwap_b, tb, short_b = walk_book(bids_s, asks_s, n, "buy")
        vwap_s, ts_, short_s = walk_book(bids_s, asks_s, n, "sell")
        entry = {}
        if vwap_b:
            entry["buy"] = {"vwap": round(vwap_b, 8),
                            "slippage_bps": round((vwap_b - mid) / mid * 1e4, 3),
                            "levels_consumed": tb, "unfilled_usd": round(short_b, 2)}
        if vwap_s:
            entry["sell"] = {"vwap": round(vwap_s, 8),
                             "slippage_bps": round((vwap_s - mid) / mid * 1e4, 3),
                             "levels_consumed": ts_, "unfilled_usd": round(short_s, 2)}
        if vwap_b and vwap_s:
            entry["round_trip_cost_bps"] = round((vwap_b - vwap_s) / mid * 1e4, 3)
        rec["slippage"][str(n)] = entry
    if extra:
        rec.update(extra)
    return rec


# ------------------------------------------------------------------ CEX
def binance(sym):
    ts = now()
    d = safe(f"https://api.binance.com/api/v3/depth?symbol={sym}&limit=1000")
    if "_error" in d:
        return {"source": "binance_public_depth", "ts_utc": ts, "error": d["_error"]}
    return book_metrics(d.get("bids", []), d.get("asks", []), ts, "binance_public_depth",
                        {"venue": "Binance spot", "pair": sym})


def kraken(sym):
    ts = now()
    d = safe(f"https://api.kraken.com/0/public/Depth?pair={sym}&count=500")
    if "_error" in d:
        return {"source": "kraken_public_depth", "ts_utc": ts, "error": d["_error"]}
    res = d.get("result", {})
    key = next((k for k in res if k != "last"), None)
    if not key:
        return {"source": "kraken_public_depth", "ts_utc": ts, "error": "no pair key"}
    lvl = res.get(key, {})
    return book_metrics(lvl.get("bids", []), lvl.get("asks", []), ts, "kraken_public_depth",
                        {"venue": "Kraken spot", "pair": key})


def okx(inst):
    ts = now()
    d = safe(f"https://www.okx.com/api/v5/market/books?instId={inst}&sz=400")
    if "_error" in d:
        return {"source": "okx_public_books", "ts_utc": ts, "error": d["_error"]}
    data = d.get("data") or []
    if not data:
        return {"source": "okx_public_books", "ts_utc": ts, "error": "no data"}
    bids = [[x[0], x[1]] for x in data[0].get("bids", [])]
    asks = [[x[0], x[1]] for x in data[0].get("asks", [])]
    return book_metrics(bids, asks, ts, "okx_public_books", {"venue": "OKX spot", "pair": inst})


def bybit(sym):
    ts = now()
    d = safe(f"https://api.bybit.com/v5/market/orderbook?category=spot&symbol={sym}&limit=200")
    if "_error" in d:
        return {"source": "bybit_public_orderbook", "ts_utc": ts, "error": d["_error"]}
    res = d.get("result") or {}
    return book_metrics(res.get("b") or [], res.get("a") or [], ts, "bybit_public_orderbook",
                        {"venue": "Bybit spot", "pair": sym})


def coinbase(sym):
    ts = now()
    d = safe(f"https://api.exchange.coinbase.com/products/{sym}/book?level=2")
    if "_error" in d:
        return {"source": "coinbase_public_book", "ts_utc": ts, "error": d["_error"]}
    return book_metrics(d.get("bids", []), d.get("asks", []), ts, "coinbase_public_book",
                        {"venue": "Coinbase Exchange", "pair": sym})


# ------------------------------------------------------------------ DEX
def gecko_pools(token_addr, network):
    d = safe(f"https://api.geckoterminal.com/api/v2/networks/{network}/tokens/{token_addr}/pools")
    if "_error" in d:
        return []
    out = []
    for p in d.get("data", []):
        a = p.get("attributes") or {}
        out.append({
            "pool": p.get("id", "").split("_", 1)[-1],
            "name": a.get("name"),
            "reserve_usd": float(a.get("reserve_in_usd") or 0),
            "vol24_usd": float((a.get("volume_usd") or {}).get("h24") or 0),
            "price_usd": float(a.get("base_token_price_usd") or 0),
        })
    out.sort(key=lambda x: -x["reserve_usd"])
    return out


def dex_summary(label, addr, network):
    ts = now()
    pools = gecko_pools(addr, network)
    if not pools:
        return {"source": "geckoterminal_token_pools", "ts_utc": ts, "network": network,
                "token": label, "token_address": addr, "error": "no pools / no platform"}
    top = pools[0]
    rec = {
        "source": "geckoterminal_token_pools", "ts_utc": ts, "network": network,
        "token": label, "token_address": addr, "top_pools": pools[:5],
        "note": "reserve_usd = 池内两边资产的美元总量;share_of_pool = 名义额 / reserve_usd(量级估计,未建模价格曲线)",
    }
    for n in NOTIONALS:
        rec.setdefault("notional_vs_pool", {})[str(n)] = {
            "share_of_pool_pct": round(n / top["reserve_usd"] * 100, 4) if top["reserve_usd"] else None,
            "pool_reserve_usd": top["reserve_usd"],
        }
    return rec


def paraswap_quote(src, dst, amount_wei, side="BUY", network=1):
    """Paraswap 公开报价(能取到就用真实曲线,取不到只记错误)。"""
    ts = now()
    url = (f"https://apiv5.paraswap.io/prices?srcToken={src}&destToken={dst}"
           f"&amount={amount_wei}&side={side}&network={network}")
    d = safe(url)
    if "_error" in d:
        return {"source": "paraswap_public_prices", "ts_utc": ts, "url": url, "error": d["_error"]}
    p = ((d.get("priceRoute") or {}).get("destAmount") or 0)
    try:
        amt = int(p)
    except Exception:  # noqa: BLE001
        amt = 0
    return {"source": "paraswap_public_prices", "ts_utc": ts, "url": url,
            "dest_amount": str(amt), "raw": json.dumps(d)[:600]}


def coingecko_ref(cg_id):
    ts = now()
    d = safe(f"https://api.coingecko.com/api/v3/simple/price?ids={cg_id}"
             f"&vs_currencies=usd&include_24hr_vol=true&include_market_cap=true")
    return {"source": "coingecko_simple_price", "ts_utc": ts, "data": d}


def main():
    out = {
        "measured_at_utc": now(), "notionals_usd": NOTIONALS,
        "method": "slippage_bps = (VWAP_走完盘口 - mid) / mid * 1e4;价格冲击,不含交易所手续费",
        "binance": {}, "kraken": {}, "coinbase": {}, "okx": {}, "bybit": {},
        "dex": {}, "dex_paraswap": {}, "coingecko_reference": {},
    }

    print("== CEX ==\n")
    for sym in ("PAXGUSDT", "XAUTUSDT", "USDCUSDT"):
        out["binance"][sym] = binance(sym)
        r = out["binance"][sym]
        print(" binance", sym, r.get("error") or
              f'spread={r["spread_bps"]}bps buy500={r["slippage"]["500"]["buy"]["slippage_bps"]}bps '
              f'buy50k={r["slippage"]["50000"]["buy"]["slippage_bps"]}bps')
        time.sleep(0.3)
    for sym in ("PAXGUSD", "XAUTUSD", "USDCUSD"):
        out["kraken"][sym] = kraken(sym)
        r = out["kraken"][sym]
        print(" kraken", sym, r.get("error") or f'spread={r["spread_bps"]}bps')
        time.sleep(0.5)
    for sym in ("PAXG-USDT", "XAUT-USDT"):
        out["okx"][sym] = okx(sym)
        r = out["okx"][sym]
        print(" okx", sym, r.get("error") or f'spread={r["spread_bps"]}bps')
        time.sleep(0.3)
    for sym in ("PAXGUSDT", "XAUTUSDT", "USDCUSDT"):
        out["bybit"][sym] = bybit(sym)
        r = out["bybit"][sym]
        print(" bybit", sym, r.get("error") or f'spread={r["spread_bps"]}bps')
        time.sleep(0.3)
    for sym in ("PAXG-USD", "XAUT-USD"):
        out["coinbase"][sym] = coinbase(sym)
        r = out["coinbase"][sym]
        print(" coinbase", sym, r.get("error") or f'spread={r["spread_bps"]}bps')
        time.sleep(0.5)

    print("== DEX ==\n")
    for label, spec in TOKEN_ADDR.items():
        for net, addr in spec.items():
            if net == "cg":
                continue
            key = f"{label}:{net}"
            out["dex"][key] = dex_summary(label, addr, net)
            r = out["dex"][key]
            print(" dex", key, r.get("error") or
                  f'liq=${r["top_pools"][0]["reserve_usd"]:,.0f} vol24=${r["top_pools"][0]["vol24_usd"]:,.0f}')
            time.sleep(1.0)

    print("== Paraswap(PAXG/XAUT, ETH, $500 等值)==\n")
    usdc = "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"
    for label in ("PAXG", "XAUT"):
        spec = TOKEN_ADDR[label]
        q = paraswap_quote(usdc, spec["eth"], 500 * 10**6)
        out["dex_paraswap"][f"{label}_500usd_buy"] = q
        print(" paraswap", label, q.get("error") or q.get("dest_amount"))
        time.sleep(2.0)

    print("== CoinGecko 参考 ==\n")
    for label, spec in TOKEN_ADDR.items():
        out["coingecko_reference"][label] = coingecko_ref(spec["cg"])
        print(" cg", label, json.dumps(out["coingecko_reference"][label]["data"], ensure_ascii=False)[:160])
        time.sleep(3.0)

    with open(OUT, "w") as fh:
        json.dump(out, fh, indent=1, ensure_ascii=False)
    print("WROTE", OUT)


if __name__ == "__main__":
    main()
