#!/usr/bin/env python3
"""T-217 ②: loop_attempt_health RPC (SECURITY DEFINER, anon 可执行) —— 逐循环判活。

上一轮 urlencode 把 None 编成字符串 "None" ⇒ 0 行;这里不传该参数。
输出: t217_loop_health.json
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request

SB = os.environ["SUPABASE_URL"].rstrip("/")
KEY = os.environ["SUPABASE_KEY"]
H = {"apikey": KEY, "Authorization": "Bearer " + KEY, "Accept": "application/json"}
HERE = Path(__file__).resolve().parent


def sb(path: str, params: dict):
    qq = urllib.parse.urlencode(params, safe="().,:*$")
    req = urllib.request.Request(SB + "/rest/v1/" + path + "?" + qq, headers=H)
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return r.status, json.loads(r.read().decode() or "[]")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:300]
    except Exception as e:  # noqa: BLE001
        return None, type(e).__name__ + ": " + str(e)[:160]


def main() -> None:
    out = {}
    st, body = sb("rpc/loop_attempt_health", {})
    out["all_status"] = st
    out["all"] = body
    print("loop_attempt_health (all loops): status", st, "n =", len(body) if isinstance(body, list) else "n/a")
    if isinstance(body, list):
        for r in body:
            print("  ", json.dumps(r, ensure_ascii=False))
    (HERE / "t217_loop_health.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
