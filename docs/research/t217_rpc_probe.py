#!/usr/bin/env python3
"""T-217 只读探针: 试所有可能有用的 SECURITY DEFINER RPC。

候选函数来自仓库里的 create-or-replace function 清单(全是 SELECT 型)。
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

CALLS = [
    ("catalog_inventory", {}),
    ("public_columns", {}),
    ("forward_return_coverage", {}),
    ("core_alpha_daily", {}),
    ("core_pit_daily", {}),
    ("core_pit_members", {}),
]


def sb(path: str, params: dict):
    qq = urllib.parse.urlencode(params, safe="().,:*$")
    req = urllib.request.Request(SB + "/rest/v1/" + path + "?" + qq, headers=H)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, json.loads(r.read().decode() or "[]")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:200]
    except Exception as e:  # noqa: BLE001
        return None, type(e).__name__ + ": " + str(e)[:160]


def main() -> None:
    out = {}
    for name, params in CALLS:
        st, body = sb("rpc/" + name, params)
        n = len(body) if isinstance(body, list) else None
        out[name] = {"status": st, "n": n, "body": body}
        print("=" * 70)
        print("RPC", name, "status", st, "n", n)
        if isinstance(body, list) and body:
            print("  cols:", list(body[0].keys()))
            for r in body[:3]:
                print("  ", json.dumps(r, ensure_ascii=False)[:400])
        else:
            print("  ", str(body)[:200])
    (HERE / "t217_rpc_probe.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print("\nwrote t217_rpc_probe.json")


if __name__ == "__main__":
    main()
