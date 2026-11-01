#!/usr/bin/env python3
"""T-217 ② 探针: loop_attempt 表可读性 / 最新行 / 计数。只读。"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request

SB = os.environ["SUPABASE_URL"].rstrip("/")
KEY = os.environ["SUPABASE_KEY"]
H = {"apikey": KEY, "Authorization": "Bearer " + KEY, "Accept": "application/json"}


def q(params: dict):
    qq = urllib.parse.urlencode(params, safe="().,:*$")
    req = urllib.request.Request(SB + "/rest/v1/loop_attempt?" + qq, headers=H)
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return r.status, json.loads(r.read().decode() or "[]")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:300]
    except Exception as e:  # noqa: BLE001
        return None, type(e).__name__ + ": " + str(e)[:160]


def show(label: str, params: dict, n: int = 12) -> None:
    st, body = q(params)
    print("---", label, "status:", st)
    if isinstance(body, list):
        print("   n:", len(body))
        for r in body[:n]:
            print("   ", json.dumps(r, ensure_ascii=False)[:230])
    else:
        print("   ", str(body)[:300])


if __name__ == "__main__":
    show("latest by at.desc", {"select": "at,loop_name,outcome,reason", "order": "at.desc", "limit": "10"})
    show("oldest by at.asc", {"select": "at,loop_name,outcome", "order": "at.asc", "limit": "5"})
    show("executor_host desc", {"select": "at,loop_name,outcome,detail",
                                 "loop_name": "eq.executor_host", "order": "at.desc", "limit": "8"})
    show("errors 7d", {"select": "at,loop_name,outcome,reason", "outcome": "eq.error",
                       "at": "gte.2026-10-25T00:00:00Z", "order": "at.asc", "limit": "20"})
