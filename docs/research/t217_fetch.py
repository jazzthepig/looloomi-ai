#!/usr/bin/env python3
"""T-217 — 抓公开只读端点(无 key) + 可读表的明细。只读。"""
from __future__ import annotations

import json
from pathlib import Path
import os
import sys
import urllib.parse
import urllib.request

BASE = "https://web-production-0cdf76.up.railway.app"
SB = os.environ["SUPABASE_URL"].rstrip("/")
KEY = os.environ["SUPABASE_KEY"]
SBH = {"apikey": KEY, "Authorization": f"Bearer {KEY}", "Accept": "application/json"}
SCRATCH = str(Path(__file__).resolve().parent)
os.makedirs(SCRATCH, exist_ok=True)


def http(url: str, hdr=None, timeout=90):
    req = urllib.request.Request(url, headers=hdr or {"User-Agent": "t217-readonly"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return {"status": r.status, "body": r.read().decode()}
    except Exception as e:                                     # noqa: BLE001
        return {"status": None, "body": f"{type(e).__name__}: {str(e)[:200]}"}


def sb(table: str, params: dict):
    q = urllib.parse.urlencode(params, safe="().,*:$")
    return http(f"{SB}/rest/v1/{table}?{q}", SBH)


def dump(name: str, obj):
    p = os.path.join(SCRATCH, name)
    with open(p, "w") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    return p


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    if what in ("all", "public"):
        for ep, fn in (("/internal/data-freshness", "data_freshness.json"),
                       ("/internal/loop-health", "loop_health.json"),
                       ("/internal/health-summary", "health_summary.json")):
            r = http(BASE + ep)
            try:
                body = json.loads(r["body"])
            except Exception:
                body = r["body"]
            dump(fn, body)
            print(ep, "->", fn, r["status"])
    if what in ("all", "series"):
        for t in ("core_cap_daily", "cis_tilt_daily", "core_variants_daily",
                  "multiplier_daily", "portfolio_layer_daily", "feature_arms_daily",
                  "meta_allocator_daily"):
            r = http(f"{BASE}/api/v1/portfolio/series?table={t}")
            try:
                body = json.loads(r["body"])
            except Exception:
                body = r["body"]
            dump(f"series_{t}.json", body)
            n = len(body.get("arms", [])) if isinstance(body, dict) else -1
            print(f"series {t}: status={r['status']} arms={n} keys={list(body)[:6] if isinstance(body, dict) else body}")
    if what in ("all", "sb"):
        for t in ("core_cap_daily", "cis_tilt_daily", "hl_book_daily"):
            r = sb(t, {"select": "d,arm,inception,computed_at,correction",
                       "order": "d.asc,arm.asc", "limit": "5000"})
            try:
                body = json.loads(r["body"])
            except Exception:
                body = r["body"]
            dump(f"sb_{t}.json", body)
            print(f"sb {t}: n={len(body) if isinstance(body, list) else body}")
