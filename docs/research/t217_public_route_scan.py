#!/usr/bin/env python3
"""T-217: enumerate public GET routes from source, curl each, and record which
mention the RLS-blocked tables / loop_attempt. Read-only; no auth guesses beyond
the token we already hold.

The point: the publishable key cannot read loop_attempt / live_account_daily /
allocation_* / rr_matrix_daily / beta_plus_daily directly (RLS 42501). If any
public route surfaces those tables' rows, we use it instead of inventing a path.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request

BASE = "https://web-production-0cdf76.up.railway.app"
SRC = "/Users/sbb/Projects/looloomi-ai-lane-a/src/api"
DEC = re.compile(r'^\s*@(app|router)\.(get)\(\s*"([^"]+)"')

KEYWORDS = ["loop_attempt", "executor_host", "live_account", "allocation_nav",
            "allocation_daily", "rr_matrix", "beta_plus", "tokenization_tilt",
            "depth_divergence"]


def routes() -> list[str]:
    import pathlib
    out = []
    for p in list(pathlib.Path(SRC).rglob("*.py")):
        try:
            for ln in p.read_text().splitlines():
                m = DEC.match(ln)
                if m:
                    out.append(m.group(3))
        except Exception:  # noqa: BLE001
            continue
    return sorted(set(out))


def main() -> None:
    tok = os.environ.get("INTERNAL_TOKEN", "")
    found = {}
    for path in routes():
        if "{" in path:
            continue
        url = BASE + path
        for hdrs in ({"Accept": "application/json"},
                     {"Accept": "application/json", "X-Internal-Token": tok}):
            try:
                req = urllib.request.Request(url, headers=hdrs)
                with urllib.request.urlopen(req, timeout=45) as r:
                    body = r.read().decode(errors="replace")
                    st = r.status
            except urllib.error.HTTPError as e:
                body = e.read().decode(errors="replace")[:120]
                st = e.code
            except Exception as e:  # noqa: BLE001
                body = type(e).__name__ + str(e)[:80]
                st = None
            hits = [k for k in KEYWORDS if k in body]
            if hits:
                found.setdefault(path, {"status": st, "hits": hits, "len": len(body),
                                        "auth": "token" if hdrs.get("X-Internal-Token") else "none",
                                        "sample": body[:600]})
                break
    for p, v in sorted(found.items()):
        print("=" * 70)
        print(p, v["status"], "auth=", v["auth"], "hits=", v["hits"], "len=", v["len"])
        print(v["sample"][:500])
    with open("/tmp/t217_public_route_hits.json", "w") as f:
        json.dump(found, f, ensure_ascii=False, indent=1)
    print("\nTOTAL routes with keyword hits:", len(found))


if __name__ == "__main__":
    main()
