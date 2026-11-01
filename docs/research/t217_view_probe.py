#!/usr/bin/env python3
"""T-217:探测是否存在可读的视图/别名,能打开受限表(live_account_daily 等)。只读。"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request

U = os.environ["SUPABASE_URL"].rstrip("/")
K = os.environ["SUPABASE_KEY"]
H = {"apikey": K, "Authorization": "Bearer " + K, "Accept": "application/json"}
NAMES = [
    "live_account_daily", "live_account", "live_accounts", "live_balances",
    "v_live_account", "v_live_account_daily", "live_account_nav", "live_fills",
    "live_trades", "hyperliquid_account", "account_daily", "executor_fills",
    "v_allocation_daily", "v_allocation_nav_daily", "allocation_nav",
    "v_beta_plus_daily", "beta_plus_nav", "v_rr_matrix_daily", "rr_matrix",
    "v_tokenization_tilt_daily", "tokenization_tilt_nav", "v_depth_divergence_log",
    "depth_divergence", "v_loop_attempt", "loop_attempts", "attempts",
    "public.loop_attempt", "live_positions", "position_daily", "book_of_truth_daily",
]


def head(t):
    q = urllib.parse.urlencode({"select": "*", "limit": "2"}, safe="(),:*$")
    try:
        with urllib.request.urlopen(urllib.request.Request(U + "/rest/v1/" + t + "?" + q, headers=H), timeout=45) as r:
            return r.status, r.read().decode()[:400]
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:120]
    except Exception as e:  # noqa: BLE001
        return None, type(e).__name__


for n in NAMES:
    st, body = head(n)
    flag = "READABLE" if st == 200 else ("404" if st == 404 else str(st))
    print(n.ljust(30), flag, body[:150].replace("\n", " "))
