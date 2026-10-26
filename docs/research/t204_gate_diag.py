#!/usr/bin/env python3
"""T-204 闸门诊断:perp_cg_map 逐行 + cg_coin_mcap_daily 进度。

用途:判断补数循环(Railway,每 10 分钟 ≤3 次 CoinGecko 请求)是否真在推进,
以及闸门(无 pending 行)大概什么时候开。纯只读。
"""
import json
import os
import urllib.request
from collections import Counter
from datetime import datetime, timezone

URL = os.environ["SUPABASE_URL"].rstrip("/")
KEY = os.environ["SUPABASE_KEY"]


def q(path):
    req = urllib.request.Request(
        URL + "/rest/v1/" + path,
        headers={"apikey": KEY, "Authorization": "Bearer " + KEY},
    )
    return json.loads(urllib.request.urlopen(req, timeout=90).read())


def main():
    now = datetime.now(timezone.utc)
    print("now_utc:", now.isoformat())

    rows = q("perp_cg_map?select=*&order=symbol.asc")
    print("perp_cg_map rows:", len(rows))
    print("columns:", sorted(rows[0].keys()) if rows else [])
    print()
    for r in rows:
        print(
            "{symbol:10s} verdict={verdict:10s} coin_id={coin_id} "
            "checked_at={checked_at} note={note}".format(
                symbol=r.get("symbol"),
                verdict=r.get("verdict"),
                coin_id=r.get("coin_id"),
                checked_at=r.get("checked_at"),
                note=(r.get("note") or "")[:110],
            )
        )
        cands = r.get("candidates")
        if cands:
            print("           candidates:", str(cands)[:200])
    print()
    print("verdict counts:", dict(Counter(r.get("verdict") for r in rows)))
    pend = [r for r in rows if r.get("verdict") == "pending"]
    noc = [r.get("symbol") for r in pend if not (r.get("candidates") or [])]
    print("pending:", len(pend), "无候选(空/None):", noc)
    print("候选数分布:", sorted(len(r.get("candidates") or []) for r in pend))
    checked = sorted(r["checked_at"] for r in rows if r.get("checked_at"))
    print("checked_at range:", checked[0] if checked else None, "->", checked[-1] if checked else None)

    cm = q("cg_coin_mcap_daily?select=coin_id&limit=100000")
    print("cg_coin_mcap_daily rows(sample):", len(cm))
    print("distinct coins in sample:", len(set(r["coin_id"] for r in cm)))


if __name__ == "__main__":
    main()
