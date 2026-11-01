#!/usr/bin/env python3
"""T-217 只读探针:哪些表用 publishable key 直读得到(200) / 401 / 400。"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

SB = os.environ["SUPABASE_URL"].rstrip("/")
KEY = os.environ["SUPABASE_KEY"]
H = {"apikey": KEY, "Authorization": "Bearer " + KEY, "Accept": "application/json"}

TABLES = [
    "core_cap_daily", "cis_tilt_daily", "hl_book_daily", "core_variants_daily",
    "multiplier_daily", "portfolio_layer_daily", "feature_arms_daily",
    "meta_allocator_daily", "loop_attempt", "executor_host", "r_money_daily",
    "short_paper_money", "cis_standard_outcomes", "cis_official_daily",
]


def probe(t: str):
    url = SB + "/rest/v1/" + t + "?select=*&limit=1"
    req = urllib.request.Request(url, headers=H)
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            b = r.read().decode()
            try:
                j = json.loads(b)
            except Exception:
                return r.status, b[:120], None
            if isinstance(j, list) and j:
                return r.status, "n=%d" % len(j), list(j[0].keys())
            return r.status, "empty" if isinstance(j, list) else str(j)[:120], None
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:150], None
    except Exception as e:  # noqa: BLE001
        return None, type(e).__name__ + ": " + str(e)[:100], None


if __name__ == "__main__":
    out = {}
    for t in TABLES:
        st, note, cols = probe(t)
        out[t] = {"status": st, "note": note, "cols": cols}
        print(t, st, note, (cols or [])[:12])
    with open(os.path.join(os.path.dirname(__file__), "t217_probe_read.json"), "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
