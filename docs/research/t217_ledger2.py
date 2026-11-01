#!/usr/bin/env python3
"""T-217 ①(第 2 版): 前向记录连续性账 —— 列名从 rpc/public_columns 自动选,不猜。

修掉第 1 版的两个问题:
  1) 猜列名 ⇒ 20 张表 42703(column does not exist) ⇒ 那些表其实可读。
  2) 分页上限 60000 ⇒ state_daily/social_daily/perp_bv_daily 截断 ⇒ 连续性数字失真。

指标(每臂):
  first/last/n_days/expected/missing/longest_gap(起日+长度)/n_gaps
  ts: n_distinct / lag_days 分布 / late_gt_0 / late_gt_2 / early
  correction 非空行数
  ts_seq: 每个 ts 有几行(判定「整段重算」vs「逐行 upsert」)

输出: t217_ledger.json
"""
from __future__ import annotations

import collections
import datetime as dt
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
PAGE = 1000
MAXROWS = 200000

DATE_PRI = ["d", "mark_date", "signal_date", "trade_date", "date", "as_of", "entry_d",
            "ts_decision", "tick_ts", "end_date", "occurred_at", "ts", "day"]
ARM_PRI = ["arm", "book", "cell", "symbol", "strategy_id", "sleeve", "coin", "token",
           "inception_id", "entity", "feature", "metric", "pair", "slug"]
TS_PRI = ["computed_at", "written_at", "updated_at", "recorded_at", "published_at", "marked_at",
          "heartbeat_at", "at", "fetched_at", "run_at", "occurred_at", "created_at", "ts", "tick_ts"]
KEEP_EXTRA = ["nav", "ret", "code_ref", "inception", "correction", "is_decision", "rule_version",
              "equity_usd", "spot_usd", "flows_usd", "perp_upnl", "weight", "exposure", "signal",
              "grade", "outcome_at", "p_pos", "n_days", "strategy_id", "nav_per_share", "nav_usd",
              "gross", "value", "state", "purpose", "note"]

TABLES = [
    "core_cap_daily", "cis_tilt_daily", "beta_plus_daily", "tokenization_tilt_daily",
    "hl_book_daily", "allocation_daily", "allocation_nav_daily", "live_account_daily",
    "depth_divergence_log", "rr_matrix_daily",
    "core_variants_daily", "multiplier_daily", "r_money_daily", "short_paper_money",
    "portfolio_layer_daily", "feature_arms_daily", "meta_allocator_daily",
    "beta_core_nav", "beta_core_nav_q", "risk_meter_history", "cis_official_daily",
    "signal_journal", "short_paper_state", "r_tickets_state",
    "causal_paper_nav", "combined_book_nav", "dingge_paper_nav", "factor_tilt_nav",
    "fusion_paper_nav", "pod_aggregator_nav", "scalable_book_nav", "two_layer_paper_nav",
    "world50_book_nav", "forward_book_nav", "forward_anchor_daily",
    "execution_quality_daily", "portfolio_targets_daily",
    "state_daily", "social_daily", "style_index_daily", "regime_band_log",
    "oi_lev_snapshot_daily", "perp_bv_daily", "trending_log", "macro_daily",
    "market_interpretation_daily", "price_source_agreement_daily",
    "interpretation_validation_runs", "crowd_clock_log", "r77_forward_episodes",
    "panel_ew_forward_returns", "nav_exceptions", "j_tickets", "r_tickets_paper",
    "execution_unresolved", "vault_nav_tick", "decisions", "trade_results",
    "execution_intents", "execution_outcomes", "short_paper_tickets", "j_tickets_state",
]


def q(table: str, params: dict):
    qq = urllib.parse.urlencode(params, safe="().,:*$")
    req = urllib.request.Request(SB + "/rest/v1/" + table + "?" + qq, headers=H)
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return r.status, json.loads(r.read().decode() or "[]")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:200]
    except Exception as e:  # noqa: BLE001
        return None, type(e).__name__ + ": " + str(e)[:120]


def as_date(v):
    if v is None:
        return None
    s = str(v)[:10]
    try:
        return dt.date.fromisoformat(s)
    except ValueError:
        return None


def pick(cols: set[str], prio: list[str]) -> str | None:
    for c in prio:
        if c in cols:
            return c
    return None


def continuity(dates):
    ds = sorted({d for d in dates if d})
    if not ds:
        return {"n_days": 0, "first": None, "last": None, "expected": 0, "missing": 0,
                "longest_gap": None, "n_gaps": 0, "gaps": []}
    first, last = ds[0], ds[-1]
    gaps = []
    for a, b in zip(ds, ds[1:]):
        if (b - a).days > 1:
            gaps.append({"after": a.isoformat(), "before": b.isoformat(), "len": (b - a).days - 1})
    return {"n_days": len(ds), "first": first.isoformat(), "last": last.isoformat(),
            "expected": (last - first).days + 1, "missing": (last - first).days + 1 - len(ds),
            "longest_gap": max(gaps, key=lambda g: g["len"]) if gaps else None,
            "n_gaps": len(gaps), "gaps": gaps[:12]}


def main() -> None:
    allcols = json.loads((HERE / "t217_all_columns.json").read_text())
    out = {"read_at": dt.datetime.now(dt.timezone.utc).isoformat(), "tables": {}}
    for table in TABLES:
        cols_avail = set(allcols.get(table) or [])
        if not cols_avail:
            out["tables"][table] = {"readable": False, "status": "no_columns",
                                    "err": "public_columns 里没有这张表"}
            print(f"{table:30s} NO SUCH TABLE (public_columns)")
            continue
        dcol = pick(cols_avail, DATE_PRI)
        armcol = pick(cols_avail - {dcol}, ARM_PRI) if dcol else None
        tscol = pick(cols_avail, TS_PRI)
        corrcol = "correction" if "correction" in cols_avail else None
        if dcol is None:
            out["tables"][table] = {"readable": False, "status": "no_date_col", "cols": sorted(cols_avail)}
            print(f"{table:30s} NO DATE COL {sorted(cols_avail)[:8]}")
            continue
        want = [dcol]
        if armcol:
            want.append(armcol)
        if tscol and tscol not in want:
            want.append(tscol)
        if corrcol and corrcol not in want:
            want.append(corrcol)
        for c in KEEP_EXTRA:
            if c in cols_avail and c not in want:
                want.append(c)
        order = dcol + ".asc" + ("," + armcol + ".asc" if armcol else "")
        rows, offset, truncated = [], 0, False
        while True:
            st, page = q(table, {"select": ",".join(want), "order": order,
                                  "limit": str(PAGE), "offset": str(offset)})
            if st != 200:
                out["tables"][table] = {"readable": False, "status": st, "err": str(page)[:160],
                                        "date_col_guess": dcol}
                print(f"{table:30s} NOT READABLE {st} {str(page)[:70]}")
                break
            rows.extend(page)
            if len(page) < PAGE:
                break
            offset += PAGE
            if offset >= MAXROWS:
                truncated = True
                break
        else:
            pass
        if out["tables"].get(table, {}).get("readable") is False:
            continue
        rec = {"readable": True, "n_rows": len(rows), "truncated": truncated,
               "date_col": dcol, "arm_col": armcol, "ts_col": tscol,
               "correction_col": corrcol}
        arms = sorted({str(r.get(armcol)) for r in rows}) if armcol else [None]
        per_arm = {}
        for a in arms:
            sub = rows if armcol is None else [r for r in rows if str(r.get(armcol)) == a]
            e = continuity([as_date(r.get(dcol)) for r in sub])
            e["n_rows"] = len(sub)
            if tscol:
                tss = [str(r.get(tscol)) for r in sub if r.get(tscol)]
                e["n_distinct_ts"] = len(set(tss))
                cnt = collections.Counter(tss)
                e["max_rows_per_ts"] = max(cnt.values()) if cnt else 0
                e["ts_min"] = min(tss) if tss else None
                e["ts_max"] = max(tss) if tss else None
                lags = []
                for r in sub:
                    d = as_date(r.get(dcol))
                    t = as_date(r.get(tscol))
                    if d and t:
                        lags.append((t - d).days)
                if lags:
                    e["lag_min"] = min(lags)
                    e["lag_max"] = max(lags)
                    e["lag_median"] = sorted(lags)[len(lags) // 2]
                    e["n_late_gt_0"] = sum(1 for x in lags if x > 0)
                    e["n_late_gt_2"] = sum(1 for x in lags if x > 2)
                    e["n_early"] = sum(1 for x in lags if x < 0)
                    e["lag_hist"] = {str(k): v for k, v in sorted(collections.Counter(lags).items())}
            if corrcol:
                e["n_correction_nonempty"] = sum(1 for r in sub if r.get(corrcol) not in (None, "", [], {}))
            per_arm[str(a)] = e
        rec["arms"] = per_arm
        rec["n_arms"] = len(per_arm)
        rec["max_missing"] = max((e["missing"] for e in per_arm.values()), default=0)
        rec["max_gap"] = max((e["longest_gap"]["len"] for e in per_arm.values()
                              if e.get("longest_gap")), default=0)
        rec["max_distinct_ts"] = max((e.get("n_distinct_ts", 0) for e in per_arm.values()), default=0)
        rec["min_distinct_ts"] = min((e.get("n_distinct_ts", 0) for e in per_arm.values()), default=0)
        rec["sum_late_gt_2"] = sum(e.get("n_late_gt_2", 0) for e in per_arm.values())
        rec["sum_correction_nonempty"] = sum(e.get("n_correction_nonempty", 0)
                                             for e in per_arm.values())
        out["tables"][table] = rec
        print(f"{table:30s} OK rows={len(rows):7d} arms={rec['n_arms']:4d} "
              f"miss={rec['max_missing']:4d} gap={rec['max_gap']:3d} "
              f"ts[min..max]={rec['min_distinct_ts']}..{rec['max_distinct_ts']} "
              f"late>2d={rec['sum_late_gt_2']} corr={rec['sum_correction_nonempty']}"
              + (" TRUNC" if truncated else ""))
        (HERE / "t217_ledger.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    (HERE / "t217_ledger.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print("\nwrote t217_ledger.json")


if __name__ == "__main__":
    main()
