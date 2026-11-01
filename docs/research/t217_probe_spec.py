#!/usr/bin/env python3
"""T-217 只读探针: 拉 PostgREST OpenAPI spec (只读, 不打印 key)。

用法: python3 t217_probe_spec.py [out_path]
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
    "Authorization": "Bearer " + KEY,
    "Accept": "application/json",
}


def fetch(url: str):
    req = urllib.request.Request(url, headers=HDRS)
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:300]
    except Exception as e:  # noqa: BLE001
        return None, type(e).__name__ + ": " + str(e)[:160]


def main() -> None:
    out = sys.argv[1] if len(sys.argv) > 1 else "t217_spec.json"
    base = URL.rstrip("/") + "/rest/v1/"
    st, body = fetch(base)
    print("root status:", st, "len:", len(body))
    if st == 200:
        with open(out, "w") as f:
            f.write(body)
        spec = json.loads(body)
        defs = sorted(spec.get("definitions", {}).keys())
        print("tables in spec:", len(defs))
        with open("t217_spec_tables.json", "w") as f:
            json.dump(defs, f, indent=1)
        print("wrote", out)
        return
    # fallback: try the newer /api/ root
    st2, body2 = fetch(URL.rstrip("/") + "/api/")
    print("api root status:", st2, "len:", len(body2))


if __name__ == "__main__":
    main()
