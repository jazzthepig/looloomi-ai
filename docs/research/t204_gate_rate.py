#!/usr/bin/env python3
"""T-204 闸门测速:resolved 行的完成时间线 + cg_coin_mcap_daily 真实行数。

用 Range 头绕过 PostgREST 默认 max-rows=1000,拿 cg_coin_mcap_daily 的准确计数。
"""
import json
import os
import urllib.request
from datetime import datetime, timezone

URL = os.environ["SUPABASE_URL"].rstrip("/")
KEY = os.environ["SUPABASE_KEY"]


def q(path, count=False):
    headers = {"apikey": KEY, "Authorization": "Bearer " + KEY}
    if count:
        headers["Prefer"] = "count=exact"
        headers["Range"] = "0-0"
    req = urllib.request.Request(URL + "/rest/v1/" + path, headers=headers)
    r = urllib.request.urlopen(req, timeout=120)
    body = r.read()
    if count:
        cr = r.headers.get("Content-Range")
        return int(cr.split("/")[-1]), json.loads(body)
    return json.loads(body)


def main():
    now = datetime.now(timezone.utc)
    print("now_utc:", now.isoformat())

    rows = q("perp_cg_map?select=symbol,verdict,coin_id,checked_at,note,candidates&order=symbol.asc")
    print("=== resolved / 非 pending 行 ===")
    for r in rows:
        if r.get("verdict") != "pending":
            print(" ", r["symbol"], r["verdict"], r.get("coin_id"), r.get("checked_at"), (r.get("note") or "")[:80])

    print()
    n, _ = q("cg_coin_mcap_daily?select=coin_id", count=True)
    print("cg_coin_mcap_daily total rows:", n)

    # 逐个统计 pending 名字的候选 coin 在 cg_coin_mcap_daily 里已有多少行
    import collections

    pend = [r for r in rows if r.get("verdict") == "pending"]
    print("pending_n:", len(pend))
    hits = collections.Counter()
    for r in pend:
        cands = r.get("candidates") or []
        for c in cands:
            cn, _ = q("cg_coin_mcap_daily?coin_id=eq." + c + "&select=coin_id", count=True)
            if cn:
                hits[r["symbol"]] += cn
    print("候选里已有 cg_coin_mcap_daily 数据的 pending 名字:", dict(hits) or "无")


if __name__ == "__main__":
    main()
