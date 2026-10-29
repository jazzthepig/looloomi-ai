#!/usr/bin/env python3
"""T-210 侦察:各候选代币的链上合约地址 + 各场所上真的存在的交易对。

只读:GET 公开 API。不注册、不下单、不写库。
输出:t210_recon.json(同目录)
"""
import json
import os
import urllib.parse
import urllib.request

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120 Safari/537.36"}


def get(url, hdr=None):
    h = dict(UA)
    if hdr:
        h.update(hdr)
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=45) as r:
        return json.loads(r.read())


def try_get(url, hdr=None):
    try:
        return get(url, hdr)
    except Exception as exc:  # noqa: BLE001
        return {"__err__": f"{type(exc).__name__}: {exc}"}


CANDS = [
    ("PAXG", "pax-gold"),
    ("XAUT", "tether-gold"),
    ("GLDX", "ondo-gold"),
    ("SPYX", "xstock-sp500"),
    ("QQQX", "xstock-qqq"),
    ("OUSG", "ondo-short-term-us-treasuries-fund"),
    ("USDC", "usd-coin"),
]

out = {"cg": {}, "cex": {}}

for sym, cid in CANDS:
    d = try_get(
        "https://api.coingecko.com/api/v3/coins/" + cid
        + "?localization=false&tickers=true&market_data=false&community_data=false&developer_data=false"
    )
    if "__err__" in d:
        out["cg"][sym] = {"id_guess": cid, "error": d["__err__"]}
        continue
    plats = {k: v for k, v in (d.get("platforms") or {}).items() if v}
    tickers = []
    for t in (d.get("tickers") or [])[:40]:
        tickers.append({
            "m": (t.get("market") or {}).get("name"),
            "p": (t.get("market") or {}).get("identifier"),
            "base": t.get("base"), "quote": t.get("target"),
            "vol_usd": (t.get("volume") or 0),
            "trust": t.get("trust_score"),
        })
    out["cg"][sym] = {
        "id": d.get("id"), "symbol": (d.get("symbol") or "").upper(),
        "name": d.get("name"), "platforms": plats,
        "last_updated": d.get("last_updated"),
        "tickers": tickers,
    }

# 场所上真的存在的交易对
pairs = {}
try:
    d = get("https://api.binance.com/api/v3/exchangeInfo")
    for s in d["symbols"]:
        pairs.setdefault("binance", []).append(s["symbol"])
except Exception as exc:  # noqa: BLE001
    pairs["binance"] = ["__err__ " + str(exc)]

try:
    d = get("https://api.kraken.com/0/public/AssetPairs")
    pairs["kraken"] = list(d.get("result", {}).keys())
except Exception as exc:  # noqa: BLE001
    pairs["kraken"] = ["__err__ " + str(exc)]

try:
    d = get("https://api.coinbase.com/api/v3/brokerage/market/products")
    pairs["coinbase"] = [p["product_id"] for p in d.get("products", [])]
except Exception as exc:  # noqa: BLE001
    pairs["coinbase"] = ["__err__ " + str(exc)]

try:
    d = get("https://www.okx.com/api/v5/public/instruments?instType=SPOT")
    pairs["okx"] = [i["instId"] for i in d.get("data", [])]
except Exception as exc:  # noqa: BLE001
    pairs["okx"] = ["__err__ " + str(exc)]

try:
    d = get("https://api.bybit.com/v5/market/instruments-info?category=spot")
    pairs["bybit"] = [i["symbol"] for i in d.get("result", {}).get("list", [])]
except Exception as exc:  # noqa: BLE001
    pairs["bybit"] = ["__err__ " + str(exc)]

out["cex"] = {v: [p for p in lst if any(k in p.upper() for k in
              ["PAXG", "XAUT", "GLDX", "SPYX", "QQQX", "OUSG", "TBILL", "USDC", "BILL", "USDY", "USTB"])]
              for v, lst in pairs.items()}

path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "t210_recon.json")
with open(path, "w") as fh:
    json.dump(out, fh, indent=1, ensure_ascii=False)
print("WROTE", path)
for sym, v in out["cg"].items():
    if "error" in v:
        print(sym, "ERR", v["error"][:80])
    else:
        plats = {k: x[:10] + "…" + x[-6:] for k, x in v["platforms"].items()}
        print(sym, v["id"], plats)
print("CEX:", json.dumps(out["cex"], ensure_ascii=False)[:1500])
