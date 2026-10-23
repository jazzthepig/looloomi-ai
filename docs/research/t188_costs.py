#!/usr/bin/env python3
"""T-188 三档买入成本：从 t188_venues.json 的实测盘口推算 $10k/$100k/$1M 一次买入的成本。

只用实测到的数据：spread_bps + 每档深度（bid/ask USD @ ±5bp / ±10bp）。
推算方法（写在报告里）：
  - 买价 = mid + (半spread) + 冲击成本
  - 冲击成本 = 订单量超出该档深度时，按下一档价格线性外推；
    深度不足以覆盖时，标注「超出实测档位，按最后实测深度线性外推（低置信）」
  - 手续费：JSON 未实测各场所费率 → 手续费一栏为 0 且标「查不到」
  - 永续另加：近 30 天资金费年化 × 持有期（按 1 年、30 天两种口径列出年化成本）
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
VJ = os.path.join(HERE, "t188_venues.json")
OUT = os.path.join(HERE, "t188_costs.json")
SIZES = [10_000, 100_000, 1_000_000]


def book_cost(book, usd):
    """买入只能吃 ask 侧 → 用单侧 ask 深度判定覆盖。

    返回 (买价USD, 冲击成本bps, 覆盖档位标签)。仅用实测字段。
    冲击成本口径：落在某档内 → 取该档边界价差（保守上限）；
    超出全部实测档 → 以最后实测档线性外推，标「外推（低置信）」。
    """
    mid = book.get("mid")
    if mid is None or mid <= 0:
        return None, None, None
    spread_bps = book.get("spread_bps", 0.0)
    half = spread_bps / 2.0 / 1e4          # 半价差占价格比
    for tag, dk, edge in (("±0.5%", "5bp", 5.0), ("±1%", "10bp", 10.0)):
        ask = book.get(f"ask_usd_{dk}")
        if ask is None:
            continue
        if ask >= usd:
            return mid * (1 + half + edge / 1e4), edge, tag
    # 超出全部实测档：以 10bp 档线性外推（低置信）
    ask10 = book.get("ask_usd_10bp") or 0
    if ask10 <= 0:
        return mid * (1 + half), None, "无实测深度"
    excess = usd - ask10
    slip_bps = 10.0 + excess * (10.0 / ask10)
    return mid * (1 + half + slip_bps / 1e4), slip_bps, "外推(低置信)"


def main():
    d = json.load(open(VJ))
    out = {"sizes_usd": SIZES, "venues": {}}

    # --- 代币现货：每个 token 挑实测盘口 ---
    for sym, tok in d["tokens"].items():
        base = tok["symbol"].upper()
        rows = []
        for key, b in d["cex_books"].items():
            # 键形如 "Binance:PAXGUSDT"；用 base 是否出现在 pair 部分判断
            pair = key.split(":", 1)[1] if ":" in key else key
            if base not in pair.upper():
                continue
            if not b.get("mid"):
                continue
            rows.append((key, b))
        rows.sort(key=lambda r: -(r[1].get("depth_usd_10bp") or 0))
        # 美元稳定币对优先（TRY/BTC/EUR 对有额外汇率或基差敞口，单独列）
        def usd_first(r):
            pair = r[0].split(":", 1)[1].upper()
            stable = any(q in pair for q in ("USDT", "USDC", "USD1", "USD", "FDUSD"))
            return (0 if stable else 1, -(r[1].get("depth_usd_10bp") or 0))
        rows.sort(key=usd_first)
        rows = rows[:6]
        per = []
        for key, b in rows:
            entry = {"venue": key, "mid": b.get("mid"),
                     "spread_bps": b.get("spread_bps"),
                     "depth_5bp_usd": b.get("depth_usd_5bp"),
                     "depth_10bp_usd": b.get("depth_usd_10bp"), "sizes": {}}
            for s in SIZES:
                px, slip, tag = book_cost(b, s)
                entry["sizes"][str(s)] = {
                    "est_buy_px": px,
                    "slippage_bps": slip,
                    "band": tag,
                    "notional_cost_usd": (px - b["mid"]) * s / b["mid"] if b.get("mid") else None,
                }
            per.append(entry)
        amms = []
        for a in (tok.get("amm_pools") or [])[:4]:
            amms.append({"dex": a.get("dex"), "pair": a.get("pair"),
                         "liquidity_usd": a.get("liquidity_usd"),
                         "note": "AMM：仅池子规模，未实测盘口深度/费率 → 深度查不到"})
        out["venues"][sym] = {
            "kind": "token_spot",
            "price_usd": tok.get("price_usd"),
            "market_cap_usd": tok.get("market_cap_usd"),
            "vol30d_avg_usd": d["token_volume_30d"].get(sym, {}).get("avg_daily_volume_usd_30d"),
            "leg": tok.get("leg"),
            "benchmark": tok.get("benchmark"),
            "tracking_error_90d": d["tracking_error_90d"].get(sym),
            "amm_pools": amms,
            "books": per,
        }

    # --- HL 永续：l2book ---
    for group in ("hl_perp_gold", "hl_perp_index", "hl_perp_stock"):
        for coin, v in d[group].items():
            b = v.get("l2book") or {}
            if not b.get("mid"):
                continue
            entry = {"venue": f"HL:{coin}", "mid": b.get("mid"),
                     "spread_bps": b.get("spread_bps"),
                     "depth_5bp_usd": b.get("depth_usd_5bp"),
                     "depth_10bp_usd": b.get("depth_usd_10bp"), "sizes": {}}
            for s in SIZES:
                px, slip, tag = book_cost(b, s)
                entry["sizes"][str(s)] = {
                    "est_buy_px": px, "slippage_bps": slip, "band": tag,
                    "notional_cost_usd": (px - b["mid"]) * s / b["mid"] if b.get("mid") else None,
                }
            out["venues"][f"{group}:{coin}"] = {
                "kind": "hl_perp",
                "dex": v.get("dex"),
                "vol30d_avg_usd": (v.get("candles") or {}).get("avg_daily_volume_usd_30d"),
                "funding_ann_pct_long": (v.get("funding") or {}).get("annualised_pct_long_side"),
                "books": [entry],
            }

    with open(OUT, "w") as f:
        json.dump(out, f, indent=1, ensure_ascii=False)
    print("wrote", OUT)

    # 控制台摘要（<60 行）
    print("\n### 三档买入成本摘要（冲击成本 bps / 名义 USD 成本）")
    for k, v in out["venues"].items():
        if v["kind"] != "token_spot":
            continue
        if not v["books"]:
            print(f"{k:6s} 无实测 CEX 盘口")
            continue
        best = v["books"][0]
        line = f"{k:6s} {best['venue']:20s} spr={best['spread_bps']:7.2f}bp d10={best['depth_10bp_usd']:>12,.0f}"
        for s in SIZES:
            sz = best["sizes"][str(s)]
            line += (f" | ${s//1000}k: {sz['slippage_bps']:.1f}bp"
                     f" (${sz['notional_cost_usd']:,.0f},{sz['band']})")
        print(line)


if __name__ == "__main__":
    main()
