#!/usr/bin/env python3
"""T-217:在可读表里找 live 账户余额痕迹(613.25 / 630.64)与 10-26..10-29 窗口的行。只读。"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request

U = os.environ["SUPABASE_URL"].rstrip("/")
K = os.environ["SUPABASE_KEY"]
H = {"apikey": K, "Authorization": "Bearer " + K, "Accept": "application/json"}
TABLES = ["core_cap_daily", "cis_tilt_daily", "hl_book_daily", "core_variants_daily",
          "multiplier_daily", "r_money_daily", "short_paper_money", "beta_core_nav",
          "risk_meter_history", "cis_official_daily", "signal_journal"]
PATTERNS = ["613.2", "630.6", "613.25", "630.64"]


def q(t, params):
    s = urllib.parse.urlencode(params, safe="(),:*$")
    try:
        with urllib.request.urlopen(urllib.request.Request(U + "/rest/v1/" + t + "?" + s, headers=H), timeout=120) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return {"__err__": e.code}
    except Exception as e:  # noqa: BLE001
        return {"__err__": type(e).__name__}


rows = q("beta_core_nav", {"select": "mark_date,marked_at,nav,rebalanced,note,mark_source,n_positions,gross,exposure_cap,realized_vol_30d",
                           "mark_date": "gte.2026-10-24", "order": "mark_date.asc", "limit": "40"})
print("=== beta_core_nav 2026-10-24.. ===")
if isinstance(rows, list):
    for r in rows:
        print(json.dumps(r, ensure_ascii=False)[:300])
else:
    print("ERR", rows)

print()
print("=== 余额数字搜索 ===")
for t in TABLES:
    rr = q(t, {"select": "*", "order": "d.asc", "limit": "20000"})
    if not isinstance(rr, list):
        print(t, "skip", rr.get("__err__"))
        continue
    s = json.dumps(rr, ensure_ascii=False)
    hits = [p for p in PATTERNS if p in s]
    print(t, "rows", len(rr), "hits", hits)
