#!/usr/bin/env python3
"""T-217: 把 t217_ledger.json 汇总成报告要用的表 + 用 write_health 区分「0 行」与「读不到」。"""
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
BASE = "https://web-production-0cdf76.up.railway.app"

KEY_TABLES = ["core_cap_daily", "cis_tilt_daily", "hl_book_daily", "r_money_daily",
              "short_paper_money", "core_variants_daily", "multiplier_daily",
              "beta_core_nav", "risk_meter_history", "cis_official_daily", "signal_journal"]


def sb(path, params):
    qq = urllib.parse.urlencode(params, safe="().,:*$")
    req = urllib.request.Request(SB + "/rest/v1/" + path + "?" + qq, headers=H)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, json.loads(r.read().decode() or "[]")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:200]
    except Exception as e:  # noqa: BLE001
        return None, type(e).__name__ + ": " + str(e)[:120]


def main() -> None:
    led = json.loads((HERE / "t217_ledger.json").read_text())
    wh = {r["table_name"]: r for r in (sb("rpc/write_health", {})[1] or [])}
    out = {"key_tables": {}, "zero_row_check": {}, "series": {}}

    print("=" * 100)
    print("KEY TABLES — per arm")
    for t in KEY_TABLES:
        rec = led["tables"].get(t) or {}
        if not rec.get("readable"):
            continue
        print(f"\n### {t}  rows={rec['n_rows']}  cols: date={rec['date_col']} arm={rec['arm_col']} ts={rec['ts_col']}")
        for a, e in sorted(rec["arms"].items(), key=lambda kv: -(kv[1].get("n_rows") or 0)):
            lg = e.get("longest_gap")
            gaptxt = "-" if not lg else f"{lg['after']}→{lg['before']} ({lg['len']}d)"
            print(f"  arm={a[:26]:26s} n={e['n_rows']:6d} {e.get('first')}..{e.get('last')} "
                  f"days={e['n_days']:5d} exp={e['expected']:5d} miss={e['missing']:4d} "
                  f"gap={gaptxt:24s} ts_distinct={e.get('n_distinct_ts')} "
                  f"max_rows_per_ts={e.get('max_rows_per_ts')} "
                  f"lag[min..max]={e.get('lag_min')}..{e.get('lag_max')} "
                  f"late>2d={e.get('n_late_gt_2')} corr={e.get('n_correction_nonempty')}")
        out["key_tables"][t] = rec

    print("\n" + "=" * 100)
    print("ZERO-ROW TABLES — 0 行是「表空」还是「读不到」?  用 write_health 的写入计数判")
    for t, rec in led["tables"].items():
        if not rec.get("readable"):
            continue
        if rec["n_rows"] != 0:
            continue
        w = wh.get(t)
        if w:
            verdict = ("表非空(24h 有成功写入)⇒ 读到 0 行是 RLS 过滤,不是表空"
                       if (w.get("n_ok_24h") or 0) > 0 else
                       "write_health 里 24h 无成功写入 ⇒ 与「表空」一致")
            print(f"  {t:30s} write_ok24h={w.get('n_ok_24h')} last_ok={w.get('last_ok')} ⇒ {verdict}")
            out["zero_row_check"][t] = {"write_health": w, "verdict": verdict}
        else:
            print(f"  {t:30s} write_health 里没有这张表 ⇒ 无法用写入计数判")
            out["zero_row_check"][t] = {"write_health": None, "verdict": "write_health 无此表"}

    # 公开 series 端点(服务端 service_role):给 401 表的臂级/日级计数
    print("\n" + "=" * 100)
    print("PUBLIC /api/v1/portfolio/series (service_role 白名单)")
    for t in ["core_cap_daily", "cis_tilt_daily", "core_variants_daily", "multiplier_daily",
              "portfolio_layer_daily", "feature_arms_daily", "meta_allocator_daily"]:
        u = BASE + "/api/v1/portfolio/series?table=" + t
        try:
            with urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "t217"}), timeout=90) as r:
                body = json.loads(r.read().decode())
            arms = body.get("arms") if isinstance(body, dict) else None
            if isinstance(arms, list) and arms:
                a0 = arms[0]
                print(f"  {t:24s} status=200 keys={list(body)[:6]} n_arms={len(arms)} arm0={json.dumps(a0, ensure_ascii=False)[:150]}")
            else:
                print(f"  {t:24s} status=200 shape={list(body)[:8] if isinstance(body, dict) else type(body)}")
            out["series"][t] = body
        except urllib.error.HTTPError as e:
            print(f"  {t:24s} HTTP {e.code} {e.read().decode()[:80]}")
            out["series"][t] = {"http_error": e.code}
        except Exception as e:  # noqa: BLE001
            print(f"  {t:24s} {type(e).__name__}: {str(e)[:80]}")
            out["series"][t] = {"error": type(e).__name__}

    (HERE / "t217_rollup.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print("\nwrote t217_rollup.json")


if __name__ == "__main__":
    main()
