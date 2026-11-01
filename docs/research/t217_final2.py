#!/usr/bin/env python3
"""T-217 v2 —— 前向记录连续性账(只读)。修 v1 的两个缺陷:
  (1) PostgREST 单页上限 1000 行,v1 用 limit=2000 ⇒ 每表只拿到第一页(被截断)
  (2) arm 列选取把 JSON 列(hl_book_daily.book)当成臂名 ⇒ 每行自成一组

输出 t217_final2.json。
"""
from __future__ import annotations

import datetime as dt
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

DIRECT_TABLES = ["core_cap_daily", "cis_tilt_daily", "hl_book_daily", "core_variants_daily",
                 "multiplier_daily", "r_money_daily", "short_paper_money"]
SERIES_TABLES = ["portfolio_layer_daily", "feature_arms_daily", "meta_allocator_daily",
                 "core_cap_daily", "cis_tilt_daily", "core_variants_daily", "multiplier_daily"]
SETH_ONLY = ["beta_plus_daily", "tokenization_tilt_daily", "allocation_daily",
             "allocation_nav_daily", "live_account_daily", "rr_matrix_daily"]
DATE_COLS = ("d", "date", "trade_date", "nav_date", "as_of", "day")
ARM_COLS = ("arm", "arm_id", "book_id", "name")
PAGE = 1000
TIMEOUT_WORDS = ("timeout", "timed out", "time out", "超时", "deadline exceeded")


def http(url, hdr=None, timeout=120):
    req = urllib.request.Request(url, headers=hdr or {"User-Agent": "t217-readonly"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:300]
    except Exception as e:  # noqa: BLE001
        return None, type(e).__name__ + ": " + str(e)[:150]


def sb(path, params=None):
    q = urllib.parse.urlencode(params or {}, safe="().,:*$")
    st, body = http(SB + "/rest/v1/" + path + (("?" + q) if q else ""), H)
    if st != 200:
        return st, body
    try:
        return st, json.loads(body or "[]")
    except Exception:  # noqa: BLE001
        return st, body


def api(path):
    st, body = http(BASE + path)
    try:
        return st, json.loads(body or "null")
    except Exception:  # noqa: BLE001
        return st, body


def dparse(v):
    try:
        return dt.date.fromisoformat(str(v)[:10])
    except Exception:  # noqa: BLE001
        return None


def tsparse(v):
    if not v:
        return None
    try:
        return dt.datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None


def gap_runs(dates, lo, hi, weekdays_only=False):
    if not dates or hi < lo:
        return 0, []
    runs, cur, n = [], None, 0
    day = lo
    while day <= hi:
        if weekdays_only and day.weekday() >= 5:
            day += dt.timedelta(days=1)
            continue
        if day in dates:
            if cur:
                runs.append((cur[0], cur[1], cur[1].day - cur[0].day + 1))
                cur = None
        else:
            n += 1
            cur = [day, day] if cur is None else [cur[0], day]
        day += dt.timedelta(days=1)
    if cur:
        runs.append((cur[0], cur[1], cur[1].day - cur[0].day + 1))
    runs.sort(key=lambda r: -r[2])
    return n, runs


def pull(table):
    """直读整表(带 order= 翻页,单页 1000)。返回 (status, cols, rows, err)。"""
    st, one = sb(table, {"limit": "1"})
    if st != 200:
        return st, None, [], str(one)[:200]
    if not isinstance(one, list) or not one:
        return st, [], [], "200 但样本为空(表空或被 RLS 全过滤)"
    cols = list(one[0].keys())
    dcol = next((c for c in DATE_COLS if c in cols), None)
    acol = None
    for c in ARM_COLS:
        if c in cols:
            v = one[0].get(c)
            if isinstance(v, (dict, list)) or (isinstance(v, str) and (v.startswith("{") or len(v) > 60)):
                continue
            acol = c
            break
    if not dcol:
        return st, cols, [], "无日期列"
    want = [dcol] + ([acol] if acol else [])
    for c in ("computed_at", "recorded_at", "inception", "correction", "code_ref", "source"):
        if c in cols and c not in want:
            want.append(c)
    order = dcol + ".asc" + ("," + acol + ".asc" if acol else "")
    rows, offset, err = [], 0, None
    while True:
        st2, chunk = sb(table, {"select": ",".join(want), "order": order,
                                "limit": str(PAGE), "offset": str(offset)})
        if st2 != 200:
            err = "page(offset=%d) status=%s %s" % (offset, st2, str(chunk)[:120])
            break
        if not isinstance(chunk, list) or not chunk:
            break
        rows.extend(chunk)
        if len(chunk) < PAGE:
            break
        offset += PAGE
        if offset > 500000:
            break
    return st, cols, rows, err


def write_mode(rec):
    for c in ("computed_at", "recorded_at"):
        k = c + "_distinct"
        if k not in rec:
            continue
        if rec[k] == 1:
            return "整段重算(%s 全表同一时刻,最晚 d+%s 天)⇒ 无逐行时间戳证据" % (c, rec[c + "_max_lag_days"])
        if rec.get(c + "_n_lag_gt2", 0) > 0:
            return "逐行 upsert,另有 %d 行写于 d+2 之后 ⇒ 有晚写/回填迹象" % rec[c + "_n_lag_gt2"]
        return "逐行 upsert,无 d+2 之后的晚写行(%s distinct=%d)" % (c, rec[k])
    return "表内无逐行时间戳列 ⇒ 无逐行时间戳证据"


def analyse(table, cols, rows, series_inception):
    dcol = next((c for c in DATE_COLS if c in cols), None)
    acol = next((c for c in ARM_COLS if c in cols), None)
    has = {c: (c in cols) for c in ("computed_at", "recorded_at", "inception", "correction")}
    groups = {}
    for r in rows:
        key = str(r.get(acol)) if acol else "(all)"
        groups.setdefault(key, []).append(r)
    out = {"table": table, "cols": cols, "n_rows": len(rows), "date_col": dcol, "arm_col": acol,
           "ts_cols": sorted([k for k, v in has.items() if v]), "arms": []}
    for arm, rs in sorted(groups.items()):
        ds = sorted({dparse(r.get(dcol)) for r in rs if dparse(r.get(dcol))})
        if not ds:
            continue
        dset = set(ds)
        miss, runs = gap_runs(dset, ds[0], ds[-1])
        missw, runsw = gap_runs(dset, ds[0], ds[-1], weekdays_only=True)
        rec = {"arm": arm, "first": ds[0].isoformat(), "last": ds[-1].isoformat(),
               "n_days": len(ds), "expected_cal": (ds[-1] - ds[0]).days + 1, "missing_cal": miss,
               "longest_gap_cal": ([runs[0][0].isoformat(), runs[0][1].isoformat(), runs[0][2]] if runs else None),
               "missing_weekdays": missw,
               "longest_gap_weekdays": ([runsw[0][0].isoformat(), runsw[0][1].isoformat(), runsw[0][2]] if runsw else None),
               "n_gaps_cal": len(runs)}
        inc = series_inception.get(arm) or (dparse(rs[0].get("inception")) if has["inception"] else None)
        if inc:
            fds = [x for x in ds if x >= inc]
            if fds:
                fm, fr = gap_runs(set(fds), fds[0], fds[-1])
                rec["inception"] = inc.isoformat()
                rec["inception_src"] = "series_endpoint" if series_inception.get(arm) else "row_column"
                rec["fwd_first"] = fds[0].isoformat()
                rec["fwd_last"] = fds[-1].isoformat()
                rec["fwd_n"] = len(fds)
                rec["fwd_expected"] = (fds[-1] - fds[0]).days + 1
                rec["fwd_missing"] = fm
                rec["fwd_longest_gap"] = ([fr[0][0].isoformat(), fr[0][1].isoformat(), fr[0][2]] if fr else None)
                rec["pre_inception_days"] = len([x for x in ds if x < inc])
        for c in ("computed_at", "recorded_at"):
            if not has[c]:
                continue
            pairs = []
            for r in rs:
                t, d = tsparse(r.get(c)), dparse(r.get(dcol))
                if t and d:
                    pairs.append(((t.date() - d).days, t))
            if not pairs:
                continue
            lags = [p[0] for p in pairs]
            rec[c + "_distinct"] = len({p[1].isoformat() for p in pairs})
            rec[c + "_max_lag_days"] = max(lags)
            rec[c + "_min_lag_days"] = min(lags)
            rec[c + "_n_lag_gt2"] = sum(1 for x in lags if x > 2)
            rec[c + "_n_lag_lt0"] = sum(1 for x in lags if x < 0)
        if has["correction"]:
            rec["correction_nonempty"] = sum(1 for r in rs if r.get("correction") not in (None, "", [], {}))
        rec["write_mode"] = write_mode(rec)
        out["arms"].append(rec)
    return out


def main():
    out = {"read_at": dt.datetime.now(dt.timezone.utc).isoformat(), "base": BASE}

    out["series"] = {}
    for t in SERIES_TABLES:
        st, body = api("/api/v1/portfolio/series?table=" + t)
        arms = body.get("arms") if isinstance(body, dict) else None
        out["series"][t] = {"status": st, "note": body.get("note") if isinstance(body, dict) else str(body)[:200],
                            "arms": arms}
        print("series", t, st, len(arms) if arms else "-")

    out["direct"] = {}
    for t in DIRECT_TABLES:
        st, cols, rows, err = pull(t)
        print("pull", t, st, "rows", len(rows), err or "")
        if st != 200:
            out["direct"][t] = {"status": st, "note": err or "读不到"}
            continue
        inc = {}
        for a in (out["series"].get(t, {}).get("arms") or []):
            if isinstance(a, dict) and a.get("arm") and a.get("inception"):
                inc[str(a["arm"])] = dparse(a["inception"])
        out["direct"][t] = analyse(t, cols, rows, inc)
        out["direct"][t]["status"] = st
        out["direct"][t]["pull_err"] = err

    out["proof"] = {}
    for p in ("/api/v1/proof/anchors", "/api/v1/proof/books"):
        st, body = api(p)
        out["proof"][p] = {"status": st, "head": json.dumps(body, ensure_ascii=False)[:2500]}
        print("proof", p, st)

    st_d, direct = sb("loop_attempt", {"select": "at,loop_name,outcome,reason,elapsed_ms",
                                       "order": "at.asc", "limit": "50"})
    out["loop_attempt_direct"] = {"status": st_d,
                                  "n_rows": len(direct) if isinstance(direct, list) else None,
                                  "sample": (direct[:2] if isinstance(direct, list) else str(direct)[:200])}
    st_rpc, loops = sb("rpc/loop_attempt_health", {})
    out["loop_rpc"] = {"status": st_rpc}
    if isinstance(loops, list):
        rows = []
        for r in loops:
            reason = (r.get("last_reason") or "")
            rows.append({"loop": r.get("loop_name"), "last_ok": r.get("last_ok"),
                         "last_fail": r.get("last_fail"), "last_reason": reason[:220],
                         "n_ok_24h": r.get("n_ok_24h"), "n_fail_24h": r.get("n_fail_24h"),
                         "timeout_class": any(w in reason.lower() for w in TIMEOUT_WORDS)})
        rows.sort(key=lambda x: (x["last_fail"] or ""))
        to = [r for r in rows if r["timeout_class"]]
        out["loop_rpc"].update({
            "n_loops": len(rows),
            "sum_fail_24h": sum(int(r.get("n_fail_24h") or 0) for r in rows),
            "sum_ok_24h": sum(int(r.get("n_ok_24h") or 0) for r in rows),
            "n_loops_fail24h": sum(1 for r in rows if int(r.get("n_fail_24h") or 0) > 0),
            "n_loops_timeout_reason": len(to),
            "sum_fail_24h_timeout_loops": sum(int(r.get("n_fail_24h") or 0) for r in to),
            "timeout_loops": to,
            "loops_with_fail": [r for r in rows if int(r.get("n_fail_24h") or 0) > 0],
            "loops": rows})
        print("loop rpc loops", len(rows), "fail24h", out["loop_rpc"]["sum_fail_24h"],
              "timeout_loops", len(to), "timeout_fails", out["loop_rpc"]["sum_fail_24h_timeout_loops"])
    st_w, tables = sb("rpc/write_health", {})
    if isinstance(tables, list):
        tf = []
        for t in tables:
            body = str(t.get("last_body") or "")
            tf.append({"table": t.get("table"), "last_fail": t.get("last_fail"),
                       "last_outcome": t.get("last_outcome"), "n_fail_24h": t.get("n_fail_24h"),
                       "timeout_class": any(w in body.lower() for w in TIMEOUT_WORDS),
                       "last_body": body[:200]})
        tf.sort(key=lambda x: x["last_fail"] or "")
        out["write_health"] = {"status": st_w, "n_tables": len(tables),
                               "n_with_fail": sum(1 for x in tf if x["last_fail"]),
                               "sum_fail_24h": sum(int(x.get("n_fail_24h") or 0) for x in tf),
                               "rows": tf}
        print("write_health tables", len(tables), "with_fail", out["write_health"]["n_with_fail"],
              "sum_fail_24h", out["write_health"]["sum_fail_24h"])

    st_e, eh = sb("executor_host", {"limit": "1"})
    out["executor_host_table"] = {"status": st_e, "note": str(eh)[:200]}
    out["seth_only"] = {}
    for t in SETH_ONLY:
        st, body = sb(t, {"limit": "1"})
        out["seth_only"][t] = {"status": st, "note": (body if isinstance(body, str) else "readable")[:160]}
    print("executor_host", st_e, "| seth_only", {k: v["status"] for k, v in out["seth_only"].items()})

    (HERE / "t217_final2.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print("wrote t217_final2.json")


if __name__ == "__main__":
    main()
