#!/usr/bin/env python3
"""T-217 ①: 前向记录连续性账 —— 逐表逐臂,全部从原始行算(不继承任何中间产物)。

指标:
  first_d / last_d / n_rows / n_days / expected_days / missing_days
  longest_gap (起日 + 长度)
  computed_at: n_distinct / lag_days 分布 / late_gt_0 / late_gt_2 / early(当天之前)
  correction 列非空行数
  判定: 能否被外部第三方当作「自首日起连续、未回填」的证据

读通道: PostgREST 直读(anon/publishable)。不可读的表记 42501/404。
翻页一律带 order=(T-170/T-173 实测:不带 order 边界会漂)。
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

# (表, 日期列, 臂列, 时间戳列, correction 列, 需要的其它列)
SPEC = [
    ("core_cap_daily",         "d", "arm", "computed_at", None, ["nav", "ret", "code_ref", "inception"]),
    ("cis_tilt_daily",         "d", "arm", "computed_at", None, ["nav", "ret", "code_ref", "inception"]),
    ("beta_plus_daily",        "d", "arm", "computed_at", None, ["nav", "ret", "code_ref", "inception"]),
    ("tokenization_tilt_daily", "d", "arm", "computed_at", None, ["nav", "ret", "code_ref", "inception"]),
    ("hl_book_daily",          "d", "book", "computed_at", "correction", ["nav", "ret", "is_decision", "code_ref"]),
    ("allocation_daily",       "d", "book", "updated_at", None, ["weight", "exposure", "code_ref"]),
    ("allocation_nav_daily",   "d", None, "updated_at", None, ["nav", "ret", "exposure", "code_ref"]),
    ("live_account_daily",     "d", None, "written_at", None, ["equity_usd", "spot_usd", "flows_usd", "perp_upnl",
                                                              "nav", "ret", "heartbeat_at", "n_heartbeats", "note", "account_mode"]),
    ("depth_divergence_log",   "d", "symbol", "recorded_at", None, ["signal", "is_measured", "problems", "rule_version"]),
    ("rr_matrix_daily",        "d", "cell", "computed_at", None, ["p_pos", "n_days", "code_ref", "strategy_id"]),
    ("core_variants_daily",    "d", "arm", "computed_at", None, ["nav", "ret", "code_ref"]),
    ("multiplier_daily",       "d", "arm", "computed_at", None, ["nav", "ret", "code_ref", "cost"]),
    ("r_money_daily",          "d", None, "computed_at", None, ["nav", "ret", "code_ref", "rule_version"]),
    ("short_paper_money",      "d", "arm", "recorded_at", None, ["nav", "ret", "inception", "rule_version"]),
    ("portfolio_layer_daily",  "d", "arm", "computed_at", None, ["nav", "ret", "code_ref"]),
    ("feature_arms_daily",     "d", "arm", "computed_at", None, ["nav", "ret", "code_ref"]),
    ("meta_allocator_daily",   "d", "arm", "computed_at", None, ["nav", "ret", "code_ref"]),
    ("beta_core_nav",          "mark_date", None, "marked_at", None, ["nav", "daily_return", "excess_return", "note"]),
    ("risk_meter_history",     "d", None, "computed_at", None, ["regime", "band", "score"]),
    ("cis_official_daily",     "d", "symbol", "published_at", None, ["grade", "signal", "code_ref"]),
    ("signal_journal",         "signal_date", "symbol", "recorded_at", None, ["signal", "grade", "outcome_at"]),
    ("causal_paper_nav",       "d", None, None, None, ["nav", "ret"]),
    ("combined_book_nav",      "d", None, None, None, ["nav", "ret"]),
    ("dingge_paper_nav",       "d", None, None, None, ["nav", "ret"]),
    ("factor_tilt_nav",        "d", None, None, None, ["nav", "ret"]),
    ("fusion_paper_nav",       "d", None, None, None, ["nav", "ret"]),
    ("pod_aggregator_nav",     "d", None, None, None, ["nav", "ret"]),
    ("scalable_book_nav",      "d", None, None, None, ["nav", "ret"]),
    ("two_layer_paper_nav",    "d", None, None, None, ["nav", "ret"]),
    ("world50_book_nav",       "d", None, None, None, ["nav", "ret"]),
    ("forward_book_nav",       "d", "arm", "recorded_at", None, ["nav", "ret", "rule"]),
    ("forward_anchor_daily",   "d", None, None, None, []),
    ("execution_quality_daily", "d", None, None, None, []),
    ("portfolio_targets_daily", "d", None, None, None, []),
    ("state_daily",            "d", None, None, None, []),
    ("social_daily",           "d", None, None, None, []),
    ("style_index_daily",      "d", None, None, None, []),
    ("regime_band_log",        "d", None, None, None, []),
    ("oi_lev_snapshot_daily",  "d", None, None, None, []),
    ("perp_bv_daily",          "d", None, None, None, []),
    ("trending_log",           "d", None, None, None, []),
    ("macro_daily",            "d", None, None, None, []),
    ("market_interpretation_daily", "d", None, None, None, []),
    ("price_source_agreement_daily", "d", None, None, None, []),
    ("interpretation_validation_runs", "d", None, None, None, []),
    ("crowd_clock_log",        "d", None, None, None, []),
    ("r77_forward_episodes",   "d", None, None, None, []),
    ("panel_ew_forward_returns", "d", None, None, None, []),
    ("nav_exceptions",         "d", None, None, None, []),
    ("j_tickets",              "d", None, None, None, []),
    ("r_tickets_paper",        "signal_d", "symbol", None, None, []),
    ("execution_unresolved",   "d", None, None, None, []),
    ("vault_nav_tick",         "d", None, None, None, []),
    ("decisions",              "d", None, None, None, []),
    ("trade_results",          "d", None, None, None, []),
    ("execution_intents",      "ts_decision", "symbol", None, None, []),
    ("execution_outcomes",     "ts_resolved", "symbol", None, None, []),
]


def q(table: str, params: dict):
    qq = urllib.parse.urlencode(params, safe="().,:*$")
    req = urllib.request.Request(SB + "/rest/v1/" + table + "?" + qq, headers=H)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, json.loads(r.read().decode() or "[]")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:200]
    except Exception as e:  # noqa: BLE001
        return None, type(e).__name__ + ": " + str(e)[:120]


def fetch_all(table: str, cols: list[str], dcol: str, armcol: str | None):
    """翻页取全表,order 带主键。"""
    order = dcol + ".asc" + ("," + armcol + ".asc" if armcol else "")
    rows, offset = [], 0
    while True:
        st, page = q(table, {"select": ",".join(cols), "order": order,
                              "limit": str(PAGE), "offset": str(offset)})
        if st != 200 or not isinstance(page, list) or not page:
            if st != 200:
                return st, str(page)[:200], rows
            break
        rows.extend(page)
        if len(page) < PAGE:
            break
        offset += PAGE
        if offset > 60000:
            break
    return 200, "", rows


def as_date(v) -> dt.date | None:
    if v is None:
        return None
    s = str(v)[:10]
    try:
        return dt.date.fromisoformat(s)
    except ValueError:
        return None


def continuity(dates: list[dt.date]) -> dict:
    ds = sorted(set(dates))
    if not ds:
        return {"n_days": 0, "first": None, "last": None, "expected": 0, "missing": 0,
                "longest_gap": None, "gaps": []}
    first, last = ds[0], ds[-1]
    expected = (last - first).days + 1
    have = set(ds)
    gaps, cur_start, prev = [], None, None
    for d in ds:
        if prev is not None and (d - prev).days > 1:
            gaps.append({"after": prev.isoformat(), "before": d.isoformat(), "len": (d - prev).days - 1})
        prev = d
    longest = max(gaps, key=lambda g: g["len"]) if gaps else None
    missing = expected - len(ds)
    return {"n_days": len(ds), "first": first.isoformat(), "last": last.isoformat(),
            "expected": expected, "missing": missing,
            "longest_gap": longest, "n_gaps": len(gaps),
            "gaps": gaps[:12]}


def main() -> None:
    out = {"tables": {}, "read_at": dt.datetime.now(dt.timezone.utc).isoformat()}
    for table, dcol, armcol, tscol, corrcol, extra in SPEC:
        cols = [dcol]
        if armcol:
            cols.append(armcol)
        if tscol:
            cols.append(tscol)
        if corrcol:
            cols.append(corrcol)
        for c in extra:
            if c not in cols:
                cols.append(c)
        st, err, rows = fetch_all(table, cols, dcol, armcol)
        if st != 200:
            out["tables"][table] = {"readable": False, "status": st, "err": err}
            print(f"{table:30s} NOT READABLE {st} {err[:80]}")
            continue
        # 真实列名以服务返回为准
        have = set()
        for r in rows:
            have.update(r.keys())
        rec = {"readable": True, "n_rows": len(rows), "cols": sorted(have)}
        # 时间戳列可能不存在(列名猜错)→ 从返回列里找
        ts_actual = tscol if tscol in have else None
        arms = sorted({str(r.get(armcol)) for r in rows}) if armcol and armcol in have else [None]
        per_arm = {}
        for a in arms:
            sub = [r for r in rows if (armcol is None or str(r.get(armcol)) == a)]
            ds = [as_date(r.get(dcol)) for r in sub]
            ds = [x for x in ds if x]
            cont = continuity(ds)
            entry = dict(cont)
            entry["n_rows"] = len(sub)
            if ts_actual:
                tss = [str(r.get(ts_actual)) for r in sub if r.get(ts_actual)]
                entry["n_distinct_ts"] = len(set(tss))
                entry["max_ts"] = max(tss) if tss else None
                entry["min_ts"] = min(tss) if tss else None
                lags = []
                for r in sub:
                    d = as_date(r.get(dcol))
                    t = as_date(r.get(ts_actual))
                    if d and t:
                        lags.append((t - d).days)
                if lags:
                    entry["lag_days_min"] = min(lags)
                    entry["lag_days_max"] = max(lags)
                    entry["lag_days_median"] = sorted(lags)[len(lags) // 2]
                    entry["n_late_gt_0"] = sum(1 for x in lags if x > 0)
                    entry["n_late_gt_2"] = sum(1 for x in lags if x > 2)
                    entry["n_early"] = sum(1 for x in lags if x < 0)
                    entry["n_same_day"] = sum(1 for x in lags if x == 0)
                    entry["lag_hist"] = dict(collections.Counter(lags).most_common(12))
            if corrcol and corrcol in have:
                entry["n_correction_nonempty"] = sum(
                    1 for r in sub if r.get(corrcol) not in (None, "", [], {}))
            per_arm[str(a)] = entry
        rec["arms"] = per_arm
        rec["n_arms"] = len(per_arm)
        rec["total_distinct_days"] = max((e["n_days"] for e in per_arm.values()), default=0)
        out["tables"][table] = rec
        tot = sum(e["n_rows"] for e in per_arm.values())
        miss = max((e["missing"] for e in per_arm.values()), default=0)
        lg = max((e["longest_gap"]["len"] for e in per_arm.values()
                  if e.get("longest_gap")), default=0)
        dts = max((e.get("n_distinct_ts", 0) for e in per_arm.values()), default=0)
        late = sum(e.get("n_late_gt_2", 0) for e in per_arm.values())
        print(f"{table:30s} OK rows={tot:6d} arms={len(per_arm):3d} "
              f"max_missing={miss:4d} max_gap={lg:3d} max_distinct_ts={dts:4d} late>2d={late}")
    (HERE / "t217_ledger.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print("\nwrote t217_ledger.json")


if __name__ == "__main__":
    main()
