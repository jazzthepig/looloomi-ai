#!/usr/bin/env python3
"""T-214 — 把 5 轮补抓合并成一份引用档案 t214_cites.json(每条:url + 抓取时间 + 原文片段),
并把 Kraken 的 XAUT 费率数组与 SPYX 交易对存在与否一并核进去。

只读 GET 公开 API。不注册、不下单、不碰私钥、不连钱包、不写库。
"""
import datetime
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from t214_cites_gap import fetch  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
CITES = os.path.join(HERE, "t214_cites.json")
GAPS = ["t214_cites_gap.json", "t214_cites_gap2.json", "t214_cites_gap3.json", "t214_cites_gap4.json"]


def merge():
    base = json.load(open(CITES))
    pages = base.setdefault("pages", {})
    for gf in GAPS:
        p = os.path.join(HERE, gf)
        if not os.path.exists(p):
            continue
        g = json.load(open(p))
        for k, v in g.get("pages", {}).items():
            # 后抓的同名 key 覆盖先抓的(更新的抓取时刻更晚)
            pages[k] = v
    base["merged_at_utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    base["note"] = ("pages 里每条 = {url, method, fetched_at_utc, chars, quotes:[{kw,text}]};"
                    "quotes 是原文片段(抓取时的页面/JSON 原文)。"
                    "另外 t214_venues.json 是同一批公开 API 的结构化汇总(挂牌/价差/池子)。")
    return base


def kraken_facts():
    """Kraken XAUT 两个交易对的费率数组 + 名单里有没有 SPYX/SPYx。"""
    out = {"fetched_at_utc": None, "url": "https://api.kraken.com/0/public/AssetPairs", "pairs": {}}
    ts, txt = fetch("https://api.kraken.com/0/public/AssetPairs")
    out["fetched_at_utc"] = ts
    for sym in ("XAUTUSD", "XAUTUSDT"):
        i = txt.find('"%s":{"altname"' % sym)
        if i < 0:
            continue
        seg = txt[i:i + 1200]

        def g(field):
            m = re.search(r'"%s":(\[\[.*?\]\])' % field, seg)
            return m.group(1) if m else None
        out["pairs"][sym] = {
            "ordermin": (re.search(r'"ordermin":"([^"]+)"', seg) or [None, None])[1],
            "costmin": (re.search(r'"costmin":"([^"]+)"', seg) or [None, None])[1],
            "tick_size": (re.search(r'"tick_size":"([^"]+)"', seg) or [None, None])[1],
            "lot_decimals": (re.search(r'"lot_decimals":(\d+)', seg) or [None, None])[1],
            "fees": g("fees"), "fees_maker": g("fees_maker"),
            "fee_volume_currency": (re.search(r'"fee_volume_currency":"([^"]+)"', seg) or [None, None])[1],
            "quote": (re.search(r'"quote":"([^"]+)"', seg) or [None, None])[1],
            "status": (re.search(r'"status":"([^"]+)"', seg) or [None, None])[1],
        }
    out["counts"] = {nm: len(re.findall(nm, txt)) for nm in ("SPYX", "SPYx", "SPY", "TSLAx", "XAUTUSD", "XAUTUSDT")}
    return out


def main():
    base = merge()
    base["pages"]["kraken_xaut_pairs_fees"] = kraken_facts()
    with open(CITES, "w") as f:
        json.dump(base, f, ensure_ascii=False, indent=1)
    print("pages:", len(base["pages"]))
    print("kraken xaut pairs:", json.dumps(base["pages"]["kraken_xaut_pairs_fees"]["pairs"], ensure_ascii=False))
    print("kraken counts:", json.dumps(base["pages"]["kraken_xaut_pairs_fees"]["counts"], ensure_ascii=False))
    print("wrote", CITES)


if __name__ == "__main__":
    main()
