#!/usr/bin/env python3
"""T-210:把深度测量压成一张可读的滑点表(报告里直接用)。

用法:python3 t210_sum.py [t210_depth2.json t210_depth.json]
每行:场所|对|中间价|买卖价差bp|买入滑点bp(500/5k/50k)|卖出滑点bp(500/5k/50k)|来回成本bp(500/5k/50k)
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def g(d, *keys, default=None):
    cur = d
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k)
        if cur is None:
            return default
    return cur


def row_for(venue, sym, rec):
    if not isinstance(rec, dict):
        return None
    if rec.get("error"):
        return f"  {venue:9s} {sym:12s} ERR {str(rec.get('error'))[:60]}"
    sl = rec.get("slippage") or {}
    def s(n, side, field="slippage_bps"):
        return g(sl, str(n), side, field)
    def rt(n):
        return g(sl, str(n), "round_trip_cost_bps")
    d05b = rec.get("depth_0.5pct_bid_usd")
    d05a = rec.get("depth_0.5pct_ask_usd")
    return (f"  {venue:9s} {sym:12s} mid={g(rec,'mid',default=0):10.4f} spread={g(rec,'spread_bps',default=0):6.3f}bp "
            f"| buy {s(500,'buy')}/{s(5000,'buy')}/{s(50000,'buy')} "
            f"| sell {s(500,'sell')}/{s(5000,'sell')}/{s(50000,'sell')} "
            f"| rt {rt(500)}/{rt(5000)}/{rt(50000)} "
            f"| depth±0.5% {int(d05b or 0):,}/{int(d05a or 0):,}")


def main():
    files = sys.argv[1:] or ["t210_depth2.json"]
    for fn in files:
        path = os.path.join(HERE, fn)
        if not os.path.exists(path):
            continue
        d = json.load(open(path))
        print("===", fn, "| measured_at", d.get("measured_at_utc"))
        cex = d.get("cex")
        if cex:
            for key in sorted(cex):
                venue, _, sym = key.partition("|")
                line = row_for(venue, sym, cex[key])
                if line:
                    print(line)
        else:
            for venue in ("binance", "kraken", "okx", "bybit", "coinbase"):
                for sym in sorted(d.get(venue, {})):
                    line = row_for(venue, sym, d[venue][sym])
                    if line:
                        print(line)
        print("  --- DEX(池子深度代理,非真盘口)---")
        for key in sorted(d.get("dex", {})):
            rec = d["dex"][key]
            pools = rec.get("top_pools") or []
            if not pools:
                print(f"  {key:22s} ERR {str(rec.get('error'))[:60]}")
                continue
            nv = rec.get("notional_vs_pool") or {}
            sh = "/".join(str((nv.get(str(n)) or {}).get("share_of_pool_pct")) for n in (500, 5000, 50000))
            print(f"  {key:22s} liq=${pools[0]['reserve_usd']:>14,.0f} vol24=${pools[0]['vol24_usd']:>12,.0f} "
                  f"px={pools[0]['price_usd']:>12.6f} | 名义额占池% 500/5k/50k = {sh}")
        print()


if __name__ == "__main__":
    main()
