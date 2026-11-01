#!/usr/bin/env python3
"""T-217 只读 DB helper: 连续性账 + loop_attempt 错误对齐 + 心跳缺口查证。

只用 os.environ["SUPABASE_URL"] / ["SUPABASE_KEY"]; 不读 .env; 不打印 key。
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

URL = os.environ.get("SUPABASE_URL")
KEY = os.environ.get("SUPABASE_KEY")
if not URL or not KEY:
    print("MISSING ENV: SUPABASE_URL / SUPABASE_KEY", file=sys.stderr)
    sys.exit(2)

HDRS = {
    "apikey": KEY,
    "Authorization": f"Bearer {KEY}",
    "Accept": "application/json",
    "Content-Type": "application/json",
}


def get(path: str, params: dict | None = None, raw: bool = False):
    q = urllib.parse.urlencode(params or {}, safe="().,*:$")
    url = f"{URL}/rest/v1/{path}" + (f"?{q}" if q else "")
    req = urllib.request.Request(url, headers=HDRS)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            body = r.read().decode()
            if raw:
                return body
            return json.loads(body) if body else []
    except urllib.error.HTTPError as e:
        detail = e.read().decode()[:400]
        raise RuntimeError(f"HTTP {e.code} {url.split('/rest/v1/')[-1][:120]} :: {detail}") from e


def list_tables() -> list[str]:
    body = get("", raw=True)
    spec = json.loads(body)
    return sorted(spec.get("definitions", {}).keys())


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "tables"
    if cmd == "tables":
        t = list_tables()
        print(len(t))
        for x in t:
            print(x)
