#!/usr/bin/env python3
"""T-217 只读探针: 公共只读端点 + 表可读性矩阵。不打印 key。"""
from __future__ import annotations

import json
from pathlib import Path
import os
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://web-production-0cdf76.up.railway.app"
SB = os.environ["SUPABASE_URL"].rstrip("/")
KEY = os.environ["SUPABASE_KEY"]
SBH = {"apikey": KEY, "Authorization": "Bearer " + KEY, "Accept": "application/json"}
SCRATCH = str(Path(__file__).resolve().parent)
os.makedirs(SCRATCH, exist_ok=True)

ENDPOINTS = [
    "/internal/loop-health",
    "/internal/data-freshness",
    "/internal/health-summary",
    "/internal/executor-host",
    "/internal/loop-attempts",
]


def http(url, hdr=None, timeout=30):
    req = urllib.request.Request(url, headers=hdr or {"User-Agent": "t217-readonly"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:200]
    except Exception as e:  # noqa: BLE001
        return None, type(e).__name__ + ": " + str(e)[:120]


def sb_head(table, cols="*", limit=2):
    q = urllib.parse.urlencode({"select": cols, "limit": str(limit)}, safe="(),:*$")
    return http(SB + "/rest/v1/" + table + "?" + q, SBH)


def main():
    print("== public endpoints ==")
    for ep in ENDPOINTS:
        st, body = http(BASE + ep)
        fn = SCRATCH + "/ep_" + ep.strip("/").replace("/", "_") + ".json"
        with open(fn, "w") as f:
            f.write(body)
        print(ep, "->", st, len(body), body[:160].replace("\n", " "))

    print("== table read matrix ==")
    tables = [
        "core_cap_daily", "cis_tilt_daily", "beta_plus_daily", "tokenization_tilt_daily",
        "hl_book_daily", "allocation_daily", "allocation_nav_daily", "live_account_daily",
        "depth_divergence_log", "rr_matrix_daily", "loop_attempt", "executor_host",
        "core_variants_daily", "multiplier_daily", "portfolio_layer_daily",
        "feature_arms_daily", "meta_allocator_daily", "r_money_daily", "short_paper_money",
        "cis_official_daily", "execution_intents", "decisions",
    ]
    out = {}
    for t in tables:
        st, body = sb_head(t)
        out[t] = {"status": st, "body": body[:300]}
        print(t, st, body[:120].replace("\n", " "))
    with open(SCRATCH + "/table_matrix.json", "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
