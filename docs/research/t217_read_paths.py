#!/usr/bin/env python3
"""T-217 只读探针: 找出每张卡面表能走通的读通道。

三种通道:
  A) PostgREST 直读表(anon/publishable) —— 需要 grant + RLS policy
  B) PostgREST RPC(SECURITY DEFINER) —— 可绕过 RLS
  C) Railway 公开端点(服务端 service_role)

只读: 只有 SELECT / GET。
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
BASE = "https://web-production-0cdf76.up.railway.app"
H = {"apikey": KEY, "Authorization": "Bearer " + KEY, "Accept": "application/json"}
HERE = Path(__file__).resolve().parent

CARD_TABLES = ["core_cap_daily", "cis_tilt_daily", "beta_plus_daily", "tokenization_tilt_daily",
               "hl_book_daily", "allocation_daily", "allocation_nav_daily", "live_account_daily",
               "depth_divergence_log", "rr_matrix_daily"]
EXTRA_TABLES = ["core_variants_daily", "multiplier_daily", "r_money_daily", "short_paper_money",
                "portfolio_layer_daily", "feature_arms_daily", "meta_allocator_daily",
                "beta_core_nav", "risk_meter_history", "cis_official_daily", "signal_journal",
                "write_log", "loop_attempt", "execution_intents", "execution_outcomes",
                "decisions", "vault_nav_tick", "trade_results", "ohlcv_daily",
                "portfolio_targets_daily", "execution_quality_daily", "core_pit",
                "short_paper_state", "j_tickets_state", "r_tickets_state"]


def sb(path: str, params: dict):
    qq = urllib.parse.urlencode(params, safe="().,:*$")
    req = urllib.request.Request(SB + "/rest/v1/" + path + "?" + qq, headers=H)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read().decode() or "[]")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:160]
    except Exception as e:  # noqa: BLE001
        return None, type(e).__name__ + ": " + str(e)[:100]


def http(url: str, hdr=None):
    req = urllib.request.Request(url, headers=hdr or {"User-Agent": "t217-readonly"})
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            return r.status, json.loads(r.read().decode() or "null")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:160]
    except Exception as e:  # noqa: BLE001
        return None, type(e).__name__ + ": " + str(e)[:100]


def main() -> None:
    report = {"tables": {}, "rpc": {}, "endpoints": {}}

    # A) 表直读
    for t in CARD_TABLES + EXTRA_TABLES:
        st, body = sb(t, {"select": "*", "limit": "2"})
        if st == 200 and isinstance(body, list):
            cols = list(body[0].keys()) if body else []
            report["tables"][t] = {"status": 200, "n_sample": len(body), "cols": cols}
            print(f"{t:26s} DIRECT  rows={len(body)} cols={cols[:6]}")
        elif st == 200:
            report["tables"][t] = {"status": 200, "n_sample": 0, "cols": [], "note": "200 but empty (RLS filters or empty table)"}
            print(f"{t:26s} DIRECT  0 rows (RLS-filtered or empty)")
        else:
            report["tables"][t] = {"status": st, "err": str(body)[:120]}
            print(f"{t:26s} DIRECT  {st} {str(body)[:90]}")

    # B) RPC
    for rpc in ("loop_attempt_health", "write_health"):
        st, body = sb("rpc/" + rpc, {"p_loop_name": None} if rpc == "loop_attempt_health" else {})
        report["rpc"][rpc] = {"status": st, "body": body if not isinstance(body, list) else body[:5],
                              "n": len(body) if isinstance(body, list) else None}
        print("RPC", rpc, st, (len(body) if isinstance(body, list) else str(body)[:120]))

    # C) 端点
    for ep in ("/api/v1/portfolio/series?table=allocation_daily",
               "/api/v1/portfolio/series?table=live_account_daily",
               "/api/v1/portfolio/series?table=beta_plus_daily",
               "/api/v1/portfolio/series?table=rr_matrix_daily",
               "/api/v1/portfolio/series?table=tokenization_tilt_daily",
               "/internal/allocation/latest",
               "/api/v1/trading/portfolio",
               "/internal/research/book-navs"):
        st, body = http(BASE + ep)
        n = len(body) if isinstance(body, (list, dict)) else 0
        report["endpoints"][ep] = {"status": st, "n": n}
        print("EP ", ep, st, n)

    (HERE / "t217_read_paths.json").write_text(json.dumps(report, ensure_ascii=False, indent=1))
    print("wrote t217_read_paths.json")


if __name__ == "__main__":
    main()
