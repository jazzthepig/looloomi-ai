#!/usr/bin/env python3
"""T-210 第二轮深度测量:把所有候选(黄金 / 股票 / 现金)放在**同一个取数时刻**。

为什么有第二轮:第一轮(t210_depth.py / t210_depth.json)只测了 PAXG / XAUT / USDC 三条
CEX 腿,没有美元腿(USDY / OUSG)与代币化股票的 CEX/DEX 对照,不同腿的取数时刻也不一致。
本轮把「每条腿每个候选」的 CEX 盘口 + DEX 池深度放在一次运行里,便于报告横向比较。

只读公开接口;不下单、不注册、不写库。
输出:t210_depth2.json(同目录)。
"""
import importlib.util
import json
import os
import time

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("t210_depth", os.path.join(HERE, "t210_depth.py"))
D = importlib.util.module_from_spec(spec)
spec.loader.exec_module(D)

OUT = os.path.join(HERE, "t210_depth2.json")
NOTIONALS = D.NOTIONALS

# 本轮新增的 DEX 代币(第一轮已测的 PAXG/XAUT/SPYX/SPY_ondo/GLD_ondo/BIL_ondo 在第一轮 json 里)。
# 地址不手写:全部取自 CoinGecko /coins/list?include_platform=true,并在运行开始时**逐条核对**
# (见 verify_addresses);核对不过的条目直接标 skip,不进入测量。
TOKEN_ADDR2 = {
    # label: (coin_gecko_id, {network: address})
    "USDY": ("ondo-us-dollar-yield", {
        "eth": "0x96f6ef951840721adbf46ac996b59e0235cb985c",
        "solana": "A1KLoBrKBde8Ty9qtNQUtq3C2ortoC3u7twggz7sEto6",
        "arbitrum-one": "0x35e050d3c0ec2d29d269a8ecea763a183bdf9a9d",
    }),
    "OUSG": ("ousg", {
        "eth": "0x1b19c19393e2d034d8ff31ff34c81252fcbbee92",
        "solana": "i7u4r16TcsJTgq1kAG8opmVZyVnAKBwLKu6ZPMwzxNc",
    }),
    "GLDx": ("gold-xstock", {
        "eth": "0x2380f2673c640fb67e2d6b55b44c62f0e0e69da9",
        "solana": "Xsv9hRk1z5ystj9MhnA7Lq4vjSsLwzL2nxrwmwtD3re",
    }),
    "PAXG_solana": ("pax-gold", {
        "solana": "5GgRAEmv8ZxF2PR5hY72Qs5x1bnQ6UK2RbTPoqJ3wSwW",
    }),
    "SPYX_solana": ("sp500-xstock", {
        "solana": "XsoCS1TfEyfFhfvj8EtZ528L3CaKBDBRqRapnBbDF2W",
    }),
}

# GeckoTerminal 的网络名 / CoinGecko 的 platform 键名
GT_NET = {"eth": "eth", "solana": "solana", "arbitrum-one": "arbitrum"}
CG_PLAT = {"eth": "ethereum", "solana": "solana", "arbitrum-one": "arbitrum-one"}


def verify_addresses():
    """用 CoinGecko coins/list 核对每个地址确实属于该代币(不匹配就跳过)。"""
    try:
        lst = D.get("https://api.coingecko.com/api/v3/coins/list?include_platform=true")
    except Exception as exc:  # noqa: BLE001
        print("  !! CoinGecko 核对失败,全部跳过:", exc)
        return {}
    by_id = {c.get("id"): c for c in lst}
    ok = {}
    for label, (cg_id, nets) in TOKEN_ADDR2.items():
        c = by_id.get(cg_id)
        if not c:
            print(f"  !! {label}: CoinGecko 无 id={cg_id},跳过")
            continue
        plats = {k: (v or "").lower() for k, v in (c.get("platforms") or {}).items()}
        for net, addr in nets.items():
            want = plats.get(CG_PLAT.get(net, net))
            if want and want == addr.lower():
                ok[(label, net)] = addr
            else:
                print(f"  !! {label}:{net} 地址与 CoinGecko({cg_id}) 不符 —— 跳过")
    return ok


def slim(rec):
    """只保留报告要用的字段,免得 json 太大。"""
    if not isinstance(rec, dict) or rec.get("error"):
        return rec
    out = {k: rec.get(k) for k in ("source", "ts_utc", "venue", "pair", "mid", "best_bid",
                                   "best_ask", "spread_bps", "depth_0.5pct_bid_usd",
                                   "depth_0.5pct_ask_usd", "levels", "error")}
    out["slippage"] = rec.get("slippage")
    return out


def main():
    out = {
        "measured_at_utc": D.now(),
        "notionals_usd": NOTIONALS,
        "method": D.__dict__.get("METHOD", "slippage_bps = (VWAP 走完盘口 - mid)/mid*1e4;价格冲击,不含交易所手续费"),
        "note": ("第二轮:一次运行内测完所有候选,横向可比。第一轮 t210_depth.json 保留为对照。"
                 "DEX 侧用 GeckoTerminal 池子 reserve_in_usd 作深度代理(不是真盘口),"
                 "share_of_pool_pct = 名义额 / 池内美元总量。"),
        "cex": {}, "dex": {},
    }

    print("== CEX ==\n")
    jobs = [
        ("binance", "PAXGUSDT"), ("binance", "XAUTUSDT"), ("binance", "USDCUSDT"),
        ("binance", "USDYUSDT"), ("binance", "PAXGUSDC"), ("binance", "XAUTUSDC"),
        ("kraken", "PAXGUSD"), ("kraken", "XAUTUSD"), ("kraken", "USDCUSD"),
        ("okx", "PAXG-USDT"), ("okx", "XAUT-USDT"),
        ("bybit", "PAXGUSDT"), ("bybit", "XAUTUSDT"), ("bybit", "USDCUSDT"),
        ("bybit", "USDYUSDT"),
        ("coinbase", "PAXG-USD"), ("coinbase", "XAUT-USD"),
    ]
    fn = {"binance": D.binance, "kraken": D.kraken, "okx": D.okx,
          "bybit": D.bybit, "coinbase": D.coinbase}
    for venue, sym in jobs:
        try:
            rec = fn[venue](sym)
        except Exception as exc:  # noqa: BLE001
            rec = {"error": str(exc)[:200]}
        out["cex"][venue + "|" + sym] = slim(rec)
        sp = rec.get("spread_bps")
        b50 = ((rec.get("slippage") or {}).get("50000") or {}).get("buy", {}).get("slippage_bps")
        print(f"  {venue:9s} {sym:12s} " + (f"spread={sp}bp buy50k={b50}bp"
              if sp is not None else "ERR " + str(rec.get("error"))[:70]))
        time.sleep(0.4)

    print("\n== DEX(地址先跟 CoinGecko 核对)==\n")
    ok = verify_addresses()
    print("  核对通过:", len(ok), "条")
    for (label, net), addr in ok.items():
        key = f"{label}:{net}"
        rec = None
        for attempt in range(3):
            rec = D.dex_summary(label, addr, GT_NET.get(net, net))
            if rec.get("top_pools"):
                break
            time.sleep(8 + attempt * 8)   # GeckoTerminal 免费层限流,退避重试
        rec["coin_gecko_id"] = TOKEN_ADDR2[label][0]
        rec["retries"] = attempt
        out["dex"][key] = rec
        pools = rec.get("top_pools") or []
        print(f"  {key:20s} " + (f"liq=${pools[0]['reserve_usd']:,.0f} vol24=${pools[0]['vol24_usd']:,.0f} px={pools[0]['price_usd']}"
                                 if pools else "ERR " + str(rec.get("error"))[:70]))
        time.sleep(2.0)

    with open(OUT, "w") as f:
        json.dump(out, f, indent=1)
    print("WROTE", OUT)


if __name__ == "__main__":
    main()
