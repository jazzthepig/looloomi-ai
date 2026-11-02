#!/usr/bin/env python3
"""T-217 —— 前向记录连续性账:按日前向表到底连续不连续、能不能当第三方证据。

Seth 11-01 §6:时间戳是唯一复制不了的,但「连续」今天没有机械证明。本脚本只读 SELECT,
给每张按日前向表一张连续性总表(首日/末日/应有天数/缺失天数/最长连续缺口),
并判写入口径 —— 这决定它能不能被外部第三方当作「自首日起连续、未回填」的证据。

读不到的表(401 / 0 行)一律写「读不到」,不推测来源、不用别的表顶替。

用法:
    python3 docs/research/t217_record_continuity.py run     # → t217_continuity.json
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

SB = os.environ["SUPABASE_URL"].rstrip("/")
KEY = os.environ["SUPABASE_KEY"]
H = {"apikey": KEY, "Authorization": "Bearer " + KEY, "Accept": "application/json"}
HERE = Path(__file__).resolve().parent
PAGE = 1000

# 日期列候选(按优先级);都不存在就报「无日期列」
DATE_COLS = ("d", "trade_date", "date", "as_of", "computed_date", "d_utc", "day")
TS_COLS = ("computed_at", "created_at", "recorded_at", "published_at", "updated_at")

# 卡上点名的三张 + 其它「决策/前瞻」性质的按日表(市场数据表不在此列 —— 它们是行情,不是记录)
FORWARD_TABLES = [
    "core_cap_daily", "cis_tilt_daily", "hl_book_daily",
    "forward_anchor_daily", "portfolio_targets_daily", "portfolio_layer_daily",
    "book_style_exposure_daily", "multiplier_daily", "meta_allocator_daily",
    "execution_quality_daily", "feature_arms_daily", "market_interpretation_daily",
    "style_index_pit_daily", "style_pit_coverage_daily", "core_variants_daily",
]
# 卡上点名「401、本卡不查」的表 —— 逐个实测状态码,作为「需 Seth 代查」清单的证据
LOCKED_EXPECTED = [
    "beta_plus_daily", "tokenization_tilt_daily", "allocation_daily",
    "allocation_nav_daily", "live_account_daily", "rr_matrix_daily",
]
LOOP_TABLES = ["loop_attempt"]


def sb(path, params):
    """读一页。params 传 list[tuple] 时同名 key 会重复出现(PostgREST 里是 AND)。
    返回 (rows, http_status);401/403/404 不抛异常 —— 「读不到」是要如实报出来的结果。"""
    if isinstance(params, dict):
        params = list(params.items())
    q = urllib.parse.urlencode(params, safe="().,:*$-", doseq=True)
    req = urllib.request.Request(SB + "/rest/v1/" + path + "?" + q, headers=H)
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            return json.load(r), r.status
    except urllib.error.HTTPError as e:
        try:
            body = json.load(e)
        except Exception:
            body = {"message": str(e)}
        return [], e.code
    except Exception as e:  # 网络/超时
        return [], f"error:{type(e).__name__}"


def sb_all(path, params, page_size=PAGE):
    """顺序翻页取全量(每页都带 order= —— 不带时边界会漂)。"""
    if isinstance(params, dict):
        params = list(params.items())
    rows, offset = [], 0
    while True:
        p = list(params) + [("limit", page_size), ("offset", offset)]
        chunk, st = sb(path, p)
        if not isinstance(st, int):
            return rows, st
        if st != 200:
            return rows, st
        rows.extend(chunk)
        if len(chunk) < page_size:
            break
        offset += page_size
    return rows, 200


def pick_date_col(sample):
    for c in DATE_COLS:
        if c in sample:
            return c
    return None


def ts_col(sample):
    for c in TS_COLS:
        if c in sample:
            return c
    return None


def _d(x):
    return str(x)[:10]


def analyse(table):
    """→ 一行连续性结论。读不到就如实说读不到。"""
    out = {"table": table, "readable": False}
    sample, st = sb(table, {"select": "*", "limit": 1})
    if st != 200:
        out.update(status=st, reason="http_%s" % st, n_rows=None)
        return out
    if not sample:
        out.update(status=st, reason="empty_table", n_rows=0)
        return out

    cols = set(sample[0].keys())
    dc = pick_date_col(cols)
    out["columns"] = sorted(cols)
    out["date_col"] = dc
    if dc is None:
        out.update(readable=True, status=st, reason="no_date_column")
        return out

    rows, st2 = sb_all(table, [("select", "*"), ("order", dc + ".asc")])
    if st2 != 200:
        out.update(status=st2, reason="http_%s" % st2)
        return out
    out["n_rows"] = len(rows)

    by_day = defaultdict(list)
    for r in rows:
        if r.get(dc) is not None:
            by_day[_d(r[dc])].append(r)
    days = sorted(by_day)
    if not days:
        out.update(readable=True, status=200, reason="all_null_dates", n_rows=len(rows))
        return out

    first, last = days[0], days[-1]
    d0 = dt.date.fromisoformat(first)
    d1 = dt.date.fromisoformat(last)
    expected = (d1 - d0).days + 1
    dset = set(days)

    # 最长连续缺口
    gaps, cur_start, cur_len = [], None, 0
    cur = None
    for s in days:
        sd = dt.date.fromisoformat(s)
        if cur is None:
            cur, cur_start, cur_len = sd, sd, 1
            continue
        if (sd - cur).days == 1:
            cur_len += 1
        else:
            gaps.append((cur_start, cur_len))
            cur, cur_start, cur_len = sd, sd, 1
        cur = sd
    gaps.append((cur_start, cur_len))
    gap_ivs = []
    for g_start, g_len in gaps:
        g_end = g_start + dt.timedelta(days=g_len - 1)
        if g_start > d0:  # 只算首日之后的内部缺口
            gap_ivs.append({"from": g_start.isoformat(), "to": g_end.isoformat(),
                            "len": g_len, "missing": g_len - 1})
    longest = max(gap_ivs, key=lambda g: g["missing"]) if gap_ivs else None

    out.update(readable=True, status=200, first=first, last=last, n_days=len(days),
               expected_days=expected, missing_days=expected - len(days),
               coverage_pct=round(100.0 * len(days) / expected, 2),
               longest_gap=longest, n_gaps=len(gap_ivs),
               rows_per_day_max=max(len(v) for v in by_day.values()),
               rows_per_day_min=min(len(v) for v in by_day.values()))

    # ---- 写入口径:逐行 upsert 还是整段重算 ----
    tc = ts_col(cols)
    out["ts_col"] = tc
    out["correction_col"] = "correction" if "correction" in cols else None
    if tc:
        ts_vals = []
        late_rows = 0
        late_examples = []
        for r in rows:
            ts = r.get(tc)
            if ts is None:
                continue
            ts_vals.append(str(ts))
            rd = r.get(dc)
            if rd is None:
                continue
            try:
                rdate = dt.date.fromisoformat(_d(rd))
            except Exception:
                continue
            tdate = str(ts)[:10]
            try:
                td = dt.date.fromisoformat(tdate)
            except Exception:
                continue
            if (td - rdate).days > 2:
                late_rows += 1
                if len(late_examples) < 5:
                    late_examples.append({"d": _d(rd), "ts": str(ts)[:19]})
        uniq_ts = sorted(set(ts_vals))
        out["n_ts_rows"] = len(ts_vals)
        out["n_unique_ts"] = len(uniq_ts)
        out["ts_first"] = uniq_ts[0][:19] if uniq_ts else None
        out["ts_last"] = uniq_ts[-1][:19] if uniq_ts else None
        out["late_rows_gt_d_plus_2"] = late_rows
        out["late_examples"] = late_examples
        # 整段重算判据:所有行的 computed_at 落在同一个 UTC 日 ⇒ 是一次性重算
        if uniq_ts:
            ts_days = {t[:10] for t in uniq_ts}
            out["n_unique_ts_days"] = len(ts_days)
            out["whole_recompute"] = (len(ts_days) == 1) or (late_rows >= 0.5 * len(rows))
        else:
            out["whole_recompute"] = None
    if "correction" in cols:
        nn = sum(1 for r in rows if r.get("correction") not in (None, ""))
        out["correction_non_null"] = nn
    return out


def run():
    res = {"tables": [], "loop_tables": [], "locked_expected": []}
    print("== 按日前向表 ==")
    for t in FORWARD_TABLES:
        a = analyse(t)
        res["tables"].append(a)
        if a.get("readable"):
            print("  %-30s 首 %s 末 %s 期望 %d 实有 %d 缺 %d 最长缺口 %s"
                  % (t, a.get("first"), a.get("last"), a.get("expected_days", 0),
                     a.get("n_days", 0), a.get("missing_days", 0),
                     ("%s→%s(%d)" % (a["longest_gap"]["from"], a["longest_gap"]["to"],
                                     a["longest_gap"]["missing"])) if a.get("longest_gap") else "无"))
        else:
            print("  %-30s 读不到 (status=%s, %s)" % (t, a.get("status"), a.get("reason")))
    print("== loop_attempt ==")
    for t in LOOP_TABLES:
        a = analyse(t)
        res["loop_tables"].append(a)
        print("  %-30s %s" % (t, "可读" if a.get("readable") else "读不到"))
    print("== 卡上点名 401 的表(实测状态码) ==")
    for t in LOCKED_EXPECTED:
        rows, st = sb(t, {"select": "*", "limit": 1})
        res["locked_expected"].append({"table": t, "status": st, "readable": st == 200})
        print("  %-30s status=%s" % (t, st))

    out = HERE / "t217_continuity.json"
    with open(out, "w") as f:
        json.dump(res, f, indent=2, default=str)
    print("\n[out] %s" % out)
    return res


if __name__ == "__main__":
    stage = sys.argv[1] if len(sys.argv) > 1 else "run"
    if stage == "run":
        run()
    else:
        print(__doc__)
