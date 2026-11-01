#!/usr/bin/env python3
"""T-217 只读: 从 public_columns / catalog_inventory 取表结构与清单。"""
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

WANT = ["core_cap_daily", "cis_tilt_daily", "beta_plus_daily", "tokenization_tilt_daily",
        "hl_book_daily", "allocation_daily", "allocation_nav_daily", "live_account_daily",
        "depth_divergence_log", "rr_matrix_daily", "core_variants_daily", "multiplier_daily",
        "r_money_daily", "short_paper_money", "portfolio_layer_daily", "feature_arms_daily",
        "meta_allocator_daily", "beta_core_nav", "risk_meter_history", "cis_official_daily",
        "signal_journal", "loop_attempt"]


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
    st, cols = sb("rpc/public_columns", {})
    print("public_columns status", st, "n_tables", len(cols) if isinstance(cols, dict) else "n/a")
    out = {}
    if isinstance(cols, dict):
        for t in WANT:
            if t in cols:
                out[t] = cols[t]
                print(f"\n== {t}")
                print("   ", ", ".join(cols[t]))
        (HERE / "t217_public_columns.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))

    st2, inv = sb("rpc/catalog_inventory", {})
    kinds = {}
    if isinstance(inv, list):
        for r in inv:
            kinds[r.get("kind")] = kinds.get(r.get("kind"), 0) + 1
        print("\ncatalog_inventory kinds:", kinds)
        tables = [r for r in inv if r.get("kind") == "table"]
        print("tables listed:", len(tables))
        for r in tables:
            if any(w in str(r.get("name")) for w in WANT):
                print("   ", json.dumps(r, ensure_ascii=False)[:300])
        (HERE / "t217_catalog.json").write_text(json.dumps(inv, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
