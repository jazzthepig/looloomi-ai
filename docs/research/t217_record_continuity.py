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

# 11-02 §Seth-1102g:loop_attempt / regime_band_log / crowd_clock_log 已对 lane 开权限
# (write_log / execution_* / agent_call_log 仍不开)。心跳缺口与超时来源在 loop_attempt 里。
HEARTBEAT_LOOP = "executor_host"
# 卡上点名的心跳缺口区间(UTC)
HB_FROM = "2026-10-26T21:42:49Z"
HB_TO = "2026-10-29T14:24:06Z"
# 超时类 error:近 7 天
TIMEOUT_WINDOW_FROM = "2026-10-26T00:00:00Z"
TIMEOUT_MARKERS = ("timeout", "timed out", "no response from supabase")
# 严格超时类(ReadTimeout / ConnectTimeout / TimeoutError)—— 与「no response from Supabase」分开计
STRICT_TIMEOUT_MARKERS = ("readtimeout", "connecttimeout", "timeouterror", "timed out")

# 11-02 起对 lane 开权限的日志表(§Seth-1102g (b)):其余日志表仍 401/0 行
OPENED_LOG_TABLES = ["loop_attempt", "regime_band_log", "crowd_clock_log",
                     "agent_call_log", "write_log", "execution_intents", "execution_outcomes"]


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


def sb_count(path):
    """精确行数:Prefer: count=exact + Range: 0-0 —— 只回 Content-Range,不下数据。"""
    req = urllib.request.Request(SB + "/rest/v1/" + path + "?select=*",
                                 headers=dict(H, Prefer="count=exact", Range="0-0"))
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            total = (r.headers.get("Content-Range") or "").split("/")[-1].strip()
            return (int(total) if total.isdigit() else None), r.status
    except urllib.error.HTTPError as e:
        return None, e.code
    except Exception as e:
        return None, "error:%s" % type(e).__name__


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


def _s(x):
    """reason/detail 可能是 str,也可能是 JSON dict —— 一律拍平成可搜的文本。"""
    if x is None:
        return ""
    if isinstance(x, str):
        return x
    try:
        return json.dumps(x, ensure_ascii=False, default=str)
    except Exception:
        return str(x)


def _ts(x):
    """ISO 时间戳 → aware datetime(UTC)。PostgREST 混着 '...Z' 和 '...+00:00' 两种格式,
    字符串比较会把 '2026-10-26T21:42:49.129096+00:00' 排到 '2026-10-26T21:42:49Z' 之后 ——
    所以一律解析成 datetime 再比。"""
    if x is None:
        return None
    s = str(x).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        d = dt.datetime.fromisoformat(s)
    except Exception:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=dt.timezone.utc)
    return d.astimezone(dt.timezone.utc)


def analyse(table):
    """→ 一行连续性结论。读不到就如实说读不到。"""
    out = {"table": table, "readable": False}
    # 样本探针(limit 1、无 offset)不是翻页读 —— 不加 order 是有意的:
    # PostgREST 先校验列名再鉴权(实测:给 401 表一个不存在的 order 列 → 400 而不是 401),
    # 给看不见 schema 的表加 order 会把「401」变成「400」,正好毁掉本卡要报的东西。
    # 真正的翻页走 sb_all,一律带 order=(见下)。
    sample, st = sb(table, [("select", "*"), ("limit", "1")])
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


def heartbeat_gap():
    """executor_host 心跳在 [HB_FROM, HB_TO] 区间内是否真的无行。
    自核(不采信任何人的转述):区间内计数 + 区间前后各一行,证明「确实断了」而不是「查不到」。
    """
    out = {"loop_name": HEARTBEAT_LOOP, "window_from": HB_FROM, "window_to": HB_TO,
           "rows_in_window": None, "prev_before": None, "next_after": None,
           "gap_hours": None, "verdict": None}
    lo = "2026-10-25T00:00:00Z"
    hi = "2026-10-31T00:00:00Z"
    rows, st = sb_all("loop_attempt", [
        ("select", "at,outcome,reason"), ("loop_name", "eq." + HEARTBEAT_LOOP),
        ("at", "gte." + lo), ("at", "lte." + hi), ("order", "at.asc")])
    out["status"] = st
    if not isinstance(rows, list):
        out["verdict"] = "read_error_%s" % st
        return out
    out["rows_in_window"] = len(rows)
    # 全序列按时间排序,找 **相邻两行之间** 的最大缺口 —— 这比「区间内有没有行」更硬:
    # 它直接给出「主机不在」的那一段,以及它两侧活着的心跳行。
    series = sorted([(_ts(r["at"]), r) for r in rows if _ts(r["at"])])
    out["n_series"] = len(series)
    gaps = []
    for i in range(1, len(series)):
        d_h = (series[i][0] - series[i - 1][0]).total_seconds() / 3600.0
        gaps.append((d_h, series[i - 1][1], series[i][1]))
    if gaps:
        gaps.sort(key=lambda g: -g[0])
        top = gaps[0]
        out["max_gap_hours"] = round(top[0], 2)
        out["max_gap_from"] = top[1]["at"]
        out["max_gap_to"] = top[2]["at"]
        out["max_gap_from_outcome"] = top[1].get("outcome")
        out["max_gap_to_outcome"] = top[2].get("outcome")
        out["n_gaps_over_6h"] = sum(1 for g in gaps if g[0] > 6.0)
        out["gaps_over_6h"] = [{"hours": round(g[0], 2), "from": g[1]["at"], "to": g[2]["at"]}
                               for g in sorted(gaps, key=lambda g: -g[0]) if g[0] > 6.0][:10]
    # 卡上给的区间:两端各放宽 1 秒(卡上写的是整秒,DB 里带小数)
    t_from, t_to = _ts(HB_FROM), _ts(HB_TO)
    tol = dt.timedelta(seconds=1)
    # 区间 **内部**(排除两端心跳行本身 —— 两端行是「活着」的证据,不是「断了」的证据)
    interior = [r for r in rows
                if (t_from + tol) < (_ts(r["at"]) or t_from) and ((_ts(r["at"]) or t_to) < (t_to - tol))]
    out["rows_in_window_interior"] = len(interior)
    out["interior_rows_sample"] = [{"at": r["at"], "outcome": r.get("outcome"),
                                     "reason": _s(r.get("reason"))[:120]} for r in interior[:5]]
    before = [r for r in rows if (_ts(r["at"]) or t_to) <= (t_from + tol)]
    after = [r for r in rows if (_ts(r["at"]) or t_from) >= (t_to - tol)]
    out["prev_before"] = {"at": before[-1]["at"], "outcome": before[-1].get("outcome")} if before else None
    out["next_after"] = {"at": after[0]["at"], "outcome": after[0].get("outcome")} if after else None
    out["rows_in_outer_window"] = len(rows)
    if before and after:
        t0, t1 = _ts(before[-1]["at"]), _ts(after[0]["at"])
        if t0 and t1:
            out["gap_hours"] = round((t1 - t0).total_seconds() / 3600.0, 2)
    # 判定用「相邻两行之间的最大缺口」—— 比「区间内有没有行」更硬:
    # 若 max_gap 的两端正好是 prev_before / next_after,则是同一次中断。
    mg_from, mg_to = out.get("max_gap_from"), out.get("max_gap_to")
    same = (mg_from == (out.get("prev_before") or {}).get("at")
            and mg_to == (out.get("next_after") or {}).get("at"))
    out["max_gap_is_the_claimed_window"] = same
    if same and len(interior) == 0:
        out["verdict"] = "confirmed_no_rows_in_window"
    elif len(interior) > 0:
        out["verdict"] = "has_rows_in_window"
    else:
        out["verdict"] = "insufficient_evidence"
    return out


def heartbeat_balance_ledger():
    """executor_host 心跳 detail 里带 balances.USDC —— 「live 余额 +17.4」的出处。
    断线区间两侧各取最后一个有心跳余额的行,算净值差。"""
    out = {"field": "detail.balances.USDC", "n_with_balance": None,
           "last_before_gap": None, "first_after_gap": None, "delta": None,
           "gap_hours": None, "series_tail": []}
    rows, st = sb_all("loop_attempt", [
        ("select", "at,outcome,detail"), ("loop_name", "eq." + HEARTBEAT_LOOP),
        ("order", "at.asc")])
    out["status"] = st
    if not isinstance(rows, list):
        out["verdict"] = "read_error_%s" % st
        return out
    t_from, t_to = _ts(HB_FROM), _ts(HB_TO)
    seq = []
    for r in rows:
        d = r.get("detail")
        if not isinstance(d, dict):
            continue
        b = d.get("balances")
        if not isinstance(b, dict) or b.get("USDC") is None:
            continue
        seq.append((_ts(r["at"]), float(b["USDC"]), r["at"], d.get("mode"), d.get("kind")))
    out["n_with_balance"] = len(seq)
    if not seq:
        out["verdict"] = "no_balance_field"
        return out
    before = [s for s in seq if s[0] <= t_from]
    after = [s for s in seq if s[0] >= t_to]
    if before:
        out["last_before_gap"] = {"at": before[-1][2], "usdc": before[-1][1],
                                  "mode": before[-1][3], "kind": before[-1][4]}
    if after:
        out["first_after_gap"] = {"at": after[0][2], "usdc": after[0][1],
                                  "mode": after[0][3], "kind": after[0][4]}
    if before and after:
        out["delta"] = round(after[0][1] - before[-1][1], 4)
        out["gap_hours"] = round((after[0][0] - before[-1][0]).total_seconds() / 3600.0, 2)
    out["series_tail"] = [{"at": s[2], "usdc": round(s[1], 4)} for s in seq[-25:]]
    out["verdict"] = "balance_ledger_measured"
    return out


def timeout_census():
    """近 7 天 loop_attempt 里的 error / 超时类记录 —— 「约 50 次超时」的来源核对。
    按 outcome 分类 + 按 loop_name 聚合,timeout 类按 marker 匹配 reason/detail。
    """
    out = {"window_from": TIMEOUT_WINDOW_FROM, "n_rows_total": None,
           "by_outcome": {}, "timeout_rows": [], "errors_by_loop": {},
           "all_errors_last7d": []}
    rows, st = sb_all("loop_attempt", [
        ("select", "at,loop_name,outcome,reason,detail,elapsed_ms"),
        ("at", "gte." + TIMEOUT_WINDOW_FROM), ("order", "at.asc")])
    out["status"] = st
    if not isinstance(rows, list):
        out["verdict"] = "read_error_%s" % st
        return out
    out["n_rows_total"] = len(rows)
    for r in rows:
        oc = (r.get("outcome") or "").lower()
        out["by_outcome"][oc] = out["by_outcome"].get(oc, 0) + 1
    errs = [r for r in rows if (r.get("outcome") or "").lower() not in ("ok", "")]
    for r in errs:
        ln = r.get("loop_name") or "?"
        out["errors_by_loop"][ln] = out["errors_by_loop"].get(ln, 0) + 1
    # timeout 判定:error 类里 reason/detail 含 timeout marker
    to_rows, strict_rows = [], []
    for r in errs:
        blob = (_s(r.get("reason")) + " " + _s(r.get("detail"))).lower()
        if any(m in blob for m in TIMEOUT_MARKERS):
            to_rows.append(r)
        if any(m in blob for m in STRICT_TIMEOUT_MARKERS):
            strict_rows.append(r)
    def _row(r):
        return {"at": r["at"], "loop_name": r.get("loop_name"),
                "outcome": r.get("outcome"),
                "reason": _s(r.get("reason"))[:200],
                "detail": _s(r.get("detail"))[:200],
                "elapsed_ms": r.get("elapsed_ms")}
    out["timeout_rows"] = [_row(r) for r in to_rows]
    out["strict_timeout_rows"] = [_row(r) for r in strict_rows]
    out["n_errors_total"] = len(errs)
    out["n_non_ok_total"] = len(errs)
    out["n_outcome_error"] = out["by_outcome"].get("error", 0)
    out["n_outcome_refused"] = out["by_outcome"].get("refused", 0)
    out["n_timeout_broad"] = len(to_rows)
    out["n_timeout_strict"] = len(strict_rows)
    # 严格超时按 loop_name / 按日聚合
    byloop, byday = {}, {}
    for r in strict_rows:
        byloop[r.get("loop_name") or "?"] = byloop.get(r.get("loop_name") or "?", 0) + 1
        d0 = str(r["at"])[:10]
        byday[d0] = byday.get(d0, 0) + 1
    out["strict_by_loop"] = byloop
    out["strict_by_day"] = byday
    out["strict_by_loop_all_errors"] = out["errors_by_loop"]
    # 区分「循环自身挂在网络上」(marker 出现在 reason)与「子请求超时」(marker 只在 detail 里)
    loop_level, sub_req = [], []
    for r in strict_rows:
        if any(m in _s(r.get("reason")).lower() for m in STRICT_TIMEOUT_MARKERS):
            loop_level.append(r)
        else:
            sub_req.append(r)
    out["n_timeout_loop_level"] = len(loop_level)
    out["n_timeout_sub_request"] = len(sub_req)
    ll_byloop, ll_byday = {}, {}
    for r in loop_level:
        ln = r.get("loop_name") or "?"
        ll_byloop[ln] = ll_byloop.get(ln, 0) + 1
        d0 = str(r["at"])[:10]
        ll_byday[d0] = ll_byday.get(d0, 0) + 1
    out["loop_level_by_loop"] = ll_byloop
    out["loop_level_by_day"] = ll_byday
    out["sub_request_rows"] = [{"at": r["at"], "loop_name": r.get("loop_name"),
                                "reason": _s(r.get("reason"))[:160]} for r in sub_req]
    out["window_to"] = dt.datetime.now(dt.timezone.utc).isoformat()
    # 「no response from Supabase」子类 —— 写端连不上库。与网络超时是两回事,单独计。
    noresp = [r for r in errs if "no response from supabase" in
              (_s(r.get("reason")) + " " + _s(r.get("detail"))).lower()]
    out["n_no_response_supabase"] = len(noresp)
    out["no_response_by_loop"] = {}
    for r in noresp:
        ln = r.get("loop_name") or "?"
        out["no_response_by_loop"][ln] = out["no_response_by_loop"].get(ln, 0) + 1
    out["no_response_by_day"] = {}
    for r in noresp:
        d0 = str(r["at"])[:10]
        out["no_response_by_day"][d0] = out["no_response_by_day"].get(d0, 0) + 1
    # 「写前向记录的那个循环」自身的成败 —— 与本卡(记录连续性)直接相关
    fr = [r for r in rows if (r.get("loop_name") or "") == "_forward_record_loop"]
    frd = {}
    for r in fr:
        d0 = str(r["at"])[:10]
        oc = (r.get("outcome") or "?").lower()
        frd.setdefault(d0, {}).setdefault(oc, 0)
        frd[d0][oc] += 1
    out["forward_record_loop_by_day"] = frd
    out["forward_record_loop_n"] = len(fr)
    out["verdict"] = "timeout_count_measured"
    return out


def live_balance_check():
    """live_account_daily:401 还是可读?可读则报首/末日与 equity 序列(核对 +17.4 那一跳)。"""
    out = {"table": "live_account_daily"}
    sample, st = sb("live_account_daily", [("select", "*"), ("limit", "1")])
    out["status"] = st
    if st != 200:
        out["readable"] = False
        out["reason"] = "http_%s" % st
        return out
    out["readable"] = True
    cols = set(sample[0].keys()) if sample else set()
    out["columns"] = sorted(cols)
    if not sample:
        out["n_rows"] = 0
        return out
    dc = pick_date_col(cols)
    out["date_col"] = dc
    if dc is None:
        return out
    rows, st2 = sb_all("live_account_daily", [("select", "*"), ("order", dc + ".asc")])
    out["status2"] = st2
    out["n_rows"] = len(rows)
    out["first"] = _d(rows[0].get(dc)) if rows else None
    out["last"] = _d(rows[-1].get(dc)) if rows else None
    eqcol = next((c for c in ("equity", "equity_usd", "total_equity", "nav_usd", "balance_usd")
                   if c in cols), None)
    out["equity_col"] = eqcol
    if eqcol:
        seq = [{"d": _d(r.get(dc)), "equity": r.get(eqcol)} for r in rows]
        out["equity_series"] = seq
        jumps = []
        for i in range(1, len(seq)):
            a, b = seq[i - 1].get("equity"), seq[i].get("equity")
            if isinstance(a, (int, float)) and isinstance(b, (int, float)):
                jumps.append({"d": seq[i]["d"], "delta": round(b - a, 4)})
        out["equity_jumps"] = jumps
        out["max_abs_jump"] = max((abs(j["delta"]) for j in jumps), default=None)
    return out


def log_table_counts():
    """§Seth-1102g (b):7 张「0 行」表逐个精确行数 —— 分清「RLS 把行过滤成 0」与「真的空表」。"""
    out = {}
    for t in OPENED_LOG_TABLES:
        n, st = sb_count(t)
        out[t] = {"status": st, "rows_exact": n}
    return out


def heartbeat_modes(n=12):
    """心跳余额行的 mode/kind —— 余额跳变是不是「live→别的模式」造成的假象。"""
    out = {"table": "loop_attempt", "loop_name": HEARTBEAT_LOOP, "tail": [], "status": None}
    rows, st = sb("loop_attempt", [("select", "at,outcome,detail"),
                                   ("loop_name", "eq." + HEARTBEAT_LOOP),
                                   ("order", "at.desc"), ("limit", str(n))])
    out["status"] = st
    if not isinstance(rows, list):
        return out
    for r in rows:
        d = r.get("detail") if isinstance(r.get("detail"), dict) else {}
        b = d.get("balances") if isinstance(d.get("balances"), dict) else {}
        out["tail"].append({"at": r.get("at"), "outcome": r.get("outcome"),
                            "mode": d.get("mode"), "kind": d.get("kind"),
                            "usdc": b.get("USDC")})
    return out


def run():
    res = {"tables": [], "loop_tables": [], "locked_expected": [],
           "opened_log_tables": []}
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
    print("== 11-02 §Seth-1102g:已开权限的日志表 ==")
    for t in OPENED_LOG_TABLES:
        sample, st = sb(t, [("select", "*"), ("limit", "1")])
        n = None
        if st == 200:
            row2, st2 = sb(t, {"select": "id", "order": "id.asc", "limit": 1})
            n = len(row2) if st2 == 200 else None
        res["opened_log_tables"].append({"table": t, "status": st, "has_rows": bool(sample),
                                         "n_min": n})
        print("  %-30s status=%s rows=%s" % (t, st, bool(sample)))
    print("== executor_host 心跳缺口(自核) ==")
    hb = heartbeat_gap()
    res["heartbeat_gap"] = hb
    print("  区间内行数=%s  前一行=%s  后一行=%s  缺口=%sh  判定=%s"
          % (hb.get("rows_in_window_interior"), (hb.get("prev_before") or {}).get("at"),
             (hb.get("next_after") or {}).get("at"), hb.get("gap_hours"), hb.get("verdict")))
    print("== 心跳里的 live 余额(核对 +17.4) ==")
    bl = heartbeat_balance_ledger()
    res["heartbeat_balance"] = bl
    print("  断线前=%s  断线后=%s  净值差=%s"
          % (bl.get("last_before_gap"), bl.get("first_after_gap"), bl.get("delta")))
    print("== 近 7 天超时类 error 计数(自核) ==")
    tc = timeout_census()
    res["timeout_census"] = tc
    print("  loop_attempt 近 7 天行数=%s  outcome 分布=%s"
          % (tc.get("n_rows_total"), tc.get("by_outcome")))
    print("  error 总数=%s (outcome=error %s)  timeout 宽口径=%s  严格=%s"
          % (tc.get("n_errors_total"), tc.get("n_outcome_error"),
             tc.get("n_timeout_broad"), tc.get("n_timeout_strict")))
    print("  严格超时按 loop=%s" % tc.get("strict_by_loop"))
    print("  严格超时按日=%s" % tc.get("strict_by_day"))
    print("  no-response-from-Supabase=%s by_loop=%s"
          % (tc.get("n_no_response_supabase"), tc.get("no_response_by_loop")))
    print("== live_account_daily(核对 +17.4) ==")
    lb = live_balance_check()
    res["live_balance"] = lb
    print("  status=%s readable=%s rows=%s equity_col=%s max|d jump|=%s"
          % (lb.get("status"), lb.get("readable"), lb.get("n_rows"),
             lb.get("equity_col"), lb.get("max_abs_jump")))
    print("== 卡上点名 401 的表(实测状态码) ==")
    for t in LOCKED_EXPECTED:
        rows, st = sb(t, [("select", "*"), ("limit", "1")])
        res["locked_expected"].append({"table": t, "status": st, "readable": st == 200})
        print("  %-30s status=%s" % (t, st))
    print("== 7 张日志表精确行数(RLS vs 真空) ==")
    ltc = log_table_counts()
    res["log_table_counts"] = ltc
    for t, v in ltc.items():
        print("  %-24s status=%s rows_exact=%s" % (t, v["status"], v["rows_exact"]))
    print("== 心跳余额行的 mode/kind(末尾) ==")
    hm = heartbeat_modes()
    res["heartbeat_modes"] = hm
    for r in hm.get("tail", [])[:6]:
        print("  %s mode=%s kind=%s usdc=%s" % (r["at"], r["mode"], r["kind"], r["usdc"]))

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
