#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T-383 探针:查 perp 日线 / 资金费表在库里的覆盖范围(只读)。"""
import json
import os
import urllib.parse
import urllib.request

URL = os.environ.get("SUPABASE_URL")
KEY = os.environ.get("SUPABASE_KEY")
if not URL or not KEY:
    raise SystemExit("缺 SUPABASE_URL / SUPABASE_KEY")


def get(path, params, count=False):
    q = dict(params)
    q.setdefault("limit", "1000")
    full = f"{URL}/rest/v1/{path}?" + urllib.parse.urlencode(q)
    req = urllib.request.Request(full, headers={
        "apikey": KEY, "Authorization": f"Bearer {KEY}", "Prefer": "count=exact"})
    with urllib.request.urlopen(req, timeout=60) as r:
        body = r.read().decode()
        cr = r.headers.get("Content-Range")
        return r.status, body, cr


def head(path, params):
    q = dict(params)
    q["limit"] = "1"
    full = f"{URL}/rest/v1/{path}?" + urllib.parse.urlencode(q)
    req = urllib.request.Request(full, headers={"apikey": KEY, "Authorization": f"Bearer {KEY}",
                                               "Range": "0-0", "Prefer": "count=exact"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.status, r.read().decode(), r.headers.get("Content-Range")


for tbl, order in (("perp_bv_daily", "d.desc"), ("v_funding_daily", "d.desc")):
    try:
        st, body, cr = head(tbl, {"select": "d", "order": order})
        print(tbl, "max row:", body[:200], "| content-range:", cr)
    except Exception as ex:
        print(tbl, "ERR", type(ex).__name__, str(ex)[:200])

# 列名探一下
for tbl in ("perp_bv_daily", "v_funding_daily"):
    try:
        st, body, cr = get(tbl, {"select": "*", "order": "d.desc"})
        rows = json.loads(body)
        print(f"--- {tbl}: n_rows_page={len(rows)}")
        if rows:
            print("   cols:", sorted(rows[0].keys()))
            print("   latest:", json.dumps(rows[0], ensure_ascii=False)[:400])
    except Exception as ex:
        print(tbl, "ERR", type(ex).__name__, str(ex)[:200])
