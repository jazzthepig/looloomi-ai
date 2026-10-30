#!/usr/bin/env python3
"""T-214 — 汇总成可核对的数字表:各场所挂牌(价/价差/量)+ 各链 DEX 池(储备/量/费 tier)。

只读 GET 公开 API。不注册、不下单、不碰私钥、不连钱包、不写库。
输出:docs/research/t214_venues.json
"""
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from t214_cites_gap import fetch  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "t214_venues.json")

CG_TICKERS = {
    "tether-gold": "https://api.coingecko.com/api/v3/coins/tether-gold/tickers",
    "sp500-xstock": "https://api.coingecko.com/api/v3/coins/sp500-xstock/tickers",
    "wrapped-sp500-xstock": "https://api.coingecko.com/api/v3/coins/wrapped-sp500-xstock/tickers",
    "tether-gold-tokens": "https://api.coingecko.com/api/v3/coins/tether-gold-tokens/tickers",
}

GT_POOLS = {
    "eth_xaut_0x68749665": "https://api.geckoterminal.com/api/v2/networks/eth/tokens/"
                           "0x68749665ff8d2d112fa859aa293f07a622782f38/pools",
    "eth_spyx_0x90a2a4c7": "https://api.geckoterminal.com/api/v2/networks/eth/tokens/"
                           "0x90a2a4c76b5d8c0bc892a69ea28aa775a8f2dd48/pools",
    "arb_xaut0_0x40461291": "https://api.geckoterminal.com/api/v2/networks/arbitrum/tokens/"
                            "0x40461291347e1ecbb09499f3371d3f17f10d7159/pools",
    "arb_spyx_0x90a2a4c7": "https://api.geckoterminal.com/api/v2/networks/arbitrum/tokens/"
                          "0x90a2a4c76b5d8c0bc892a69ea28aa775a8f2dd48/pools",
    "sol_spyx_XsoCS1Tf": "https://api.geckoterminal.com/api/v2/networks/solana/tokens/"
                         "XsoCS1TfEyfFhfvj8EtZ528L3CaKBDBRqRapnBbDF2W/pools",
    "sol_xaut0_AymATz4T": "https://api.geckoterminal.com/api/v2/networks/solana/tokens/"
                          "AymATz4TCL9sWNEEV9Kvyz45CHVhDZ6kUgjTJPzLpU9P/pools",
    "hyper_xaut0_0xf4d9235": "https://api.geckoterminal.com/api/v2/networks/hyperevm/tokens/"
                             "0xf4d9235269a96aadafc9adae454a0618ebe37949/pools",
    "hyper_wspyx_0xe7e553cd": "https://api.geckoterminal.com/api/v2/networks/hyperevm/tokens/"
                              "0xe7e553cd128f0011777323a0b44a7b96ea1cb540/pools",
    "xlayer_wspyx_0xe7e553cd": "https://api.geckoterminal.com/api/v2/networks/x-layer/tokens/"
                               "0xe7e553cd128f0011777323a0b44a7b96ea1cb540/pools",
}


def fnum(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def main():
    out = {"generated_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
           "venues": {}, "pools": {}}
    for coin, url in CG_TICKERS.items():
        ts, txt = fetch(url)
        rec = {"url": url, "fetched_at_utc": ts}
        try:
            d = json.loads(txt)
            rows = []
            for t in d.get("tickers", []):
                m = t.get("market") or {}
                rows.append({
                    "venue": m.get("name"), "identifier": m.get("identifier"),
                    "base": t.get("base"), "target": t.get("target"),
                    "last": t.get("last"), "volume": t.get("volume"),
                    "spread_pct": t.get("bid_ask_spread_percentage"),
                    "converted_volume_usd": (t.get("converted_volume") or {}).get("usd"),
                    "trade_url": t.get("trade_url"),
                    "last_traded_at": t.get("last_traded_at"),
                    "is_stale": t.get("is_stale"),
                })
            rows.sort(key=lambda r: -fnum(r["converted_volume_usd"]))
            rec["rows"] = rows
            print("%-22s venues=%d" % (coin, len(rows)))
        except Exception as e:  # noqa: BLE001
            rec["error"] = "%s: %s" % (type(e).__name__, e)
            rec["raw"] = txt[:200]
            print("%-22s ERR %s" % (coin, rec["error"][:60]))
        out["venues"][coin] = rec

    for key, url in GT_POOLS.items():
        ts, txt = fetch(url)
        rec = {"url": url, "fetched_at_utc": ts}
        try:
            d = json.loads(txt)
            rows = []
            for p in d.get("data", []):
                a = p.get("attributes", {})
                rows.append({
                    "name": a.get("name"), "address": a.get("address"),
                    "reserve_usd": a.get("reserve_in_usd"), "volume_usd": a.get("volume_usd"),
                    "fee_pct": a.get("fee_percentage"), "price_usd": a.get("base_token_price_usd"),
                    "created": a.get("pool_created_at"),
                })
            rows.sort(key=lambda r: -fnum(r["reserve_usd"]))
            rec["rows"] = rows
            print("%-24s pools=%d" % (key, len(rows)))
        except Exception as e:  # noqa: BLE001
            rec["error"] = "%s: %s" % (type(e).__name__, e)
            rec["raw"] = txt[:200]
            print("%-24s ERR %s" % (key, rec["error"][:60]))
        out["pools"][key] = rec

    with open(OUT, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
