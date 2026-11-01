#!/usr/bin/env python3
"""T-217 —— 前向记录连续性账(只读)。

通道(全部只读,不改代码 / 不动密钥 / 不做 DDL):
  A) 直读表      PostgREST /rest/v1/<table>  —— publishable key,带 order= 翻页
  B) 公开接口    https://web-production-0cdf76.up.railway.app/api/v1/...  (无 key)
  C) 只读函数    /rest/v1/rpc/<fn>  —— SECURITY DEFINER 聚合视图

输出:
  t217_final.json      —— 全部原始 + 派生数字
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

# 卡面点名的三张表 + 可直读的其它按日前向表
DIRECT_TABLES = [
    "core_cap_daily", "cis_tilt_daily", "hl_book_daily",
    "core_variants_daily", "multiplier_daily", "r_money_daily", "short_paper_money",
]
# 卡面列明「本卡不查 / 需 Seth 代查」的表(只探读权限状态,不看内容)
SETH_ONLY = [
    "beta_plus_daily", "tokenization_tilt_daily", "allocation_daily",
    "allocation_nav_daily", "live_account_daily", "rr_matrix_daily",
]
# 公开接口可见但直读 401 的按日表
SERIES_TABLES = ["portfolio_layer_daily", "feature_arms_daily", "meta_allocator_daily"]

DATE_COLS = ("d", "date", "trade_date", "nav_date", "as_of", "day")
ARM_COLS = ("arm", "book", "arm_id", "book_id", "name")


def http(url: str, hdr=None, timeout=90):
    req = urllib.request.Request(url, headers=hdr or {"User-Agent": "t217-readonly"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:300]
    except Exception as e:  # noqa: BLE001
        return None, type(e).__name__ + ": " + str(e)[:150]


def sb(path: str, params: dict | None = None):
    q = urllib.parse.urlencode(params or {}, safe="().,:*$")
    st, body = http(SB + "/rest/v1/" + path + (("?" + q) if q else ""), H)
    if st != 200:
        return st, body
    try:
        return st, json.loads(body or "[]")
    except Exception:  # noqa: BLE001
        return st, body


def api(path: str):
    st, body = http(BASE + path)
    try:
        return st, json.loads(body or "null")
    except Exception:  # noqa: BLE001
        return st, body


def dparse(v):
    if not v:
        return None
    try:
        return dt.date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def tsparse(v):
    if not v:
        return None
    s = str(v).replace("Z", "+00:00")
    try:
        return dt.datetime.fromisoformat(s)
    except ValueError:
        return None


def gap_runs(dates: set, lo: dt.date, hi: dt.date, weekdays_only=False):
    """返回 (缺失天数, [(缺口起, 缺口止, 长度)])。"""
    if not dates or hi < lo:
        return 0, []
    runs, cur = [], None
    n = 0
    day = lo
    while day <= hi:
        present = day in dates
        if weekdays_only and day.weekday() >= 5:
            day += dt.timedelta(days=1)
            continue
        if present:
            if cur:
                runs.append((cur[0], cur[1], cur[1].day - cur[0].day + 1))
                cur = None
        else:
            n += 1
            if cur is None:
                cur = [day, day]
            else:
                cur[1] = day
        day += dt.timedelta(days=1)
    if cur:
        runs.append((cur[0], cur[1], cur[1].day - cur[0].day + 1))
    runs.sort(key=lambda r: -r[2])
    return n, runs


def pull_table(table: str):
    """直读一张按日表:返回 (status, cols, rows)。带 order= 翻页。"""
    st, one = sb(table, {"limit": "1"})
    if st != 200:
        return st, None, []
    if not isinstance(one, list) or not one:
        return st, [], []
    cols = list(one[0].keys())
    dcol = next((c for c in DATE_COLS if c in cols), None)
    acol = next((c for c in ARM_COLS if c in cols), None)
    if not dcol:
        return st, cols, []
    want = [dcol] + ([acol] if acol else [])
    for c in ("computed_at", "recorded_at", "inception", "correction", "code_ref"):
        if c in cols and c not in want:
            want.append(c)
    order = dcol + ".asc" + ("," + acol + ".asc" if acol else "")
    rows, offset, limit = [], 0, 2000
    while True:
        st2, chunk = sb(table, {"select": ",".join(want), "order": order,
                                "limit": str(limit), "offset": str(offset)})
        if st2 != 200 or not isinstance(chunk, list) or not chunk:
            break
        rows.extend(chunk)
        if len(chunk) < limit:
            break
        offset += limit
        if offset > 400000:
            break
    return st, cols, rows


def analyse_table(table: str, cols: list, rows: list) -> dict:
    """逐臂连续性 + 写入口径判定。"""
    dcol = next((c for c in DATE_COLS if c in cols), None)
    acol = next((c for c in ARM_COLS if c in cols), None)
    has = {c: (c in cols) for c in ("computed_at", "recorded_at", "inception", "correction")}
    arms: dict = {}
    for r in rows:
        key = str(r.get(acol)) if acol else "(all)"
        arms.setdefault(key, []).append(r)
    out = {"table": table, "cols": cols, "n_rows": len(rows), "date_col": dcol,
           "arm_col": acol, "ts_cols": {k: v for k, v in has.items() if v}, "arms": []}
    for arm, rs in sorted(arms.items()):
        ds = sorted({dparse(r.get(dcol)) for r in rs if dparse(r.get(dcol))})
        if not ds:
            continue
        lo, hi = ds[0], ds[-1]
        dset = set(ds)
        miss_cal, runs_cal = gap_runs(dset, lo, hi)
        miss_wd, runs_wd = gap_runs(dset, lo, hi, weekdays_only=True)
        rec = {"arm": arm, "first": lo.isoformat(), "last": hi.isoformat(), "n_days": len(ds),
               "expected_cal": (hi - lo).days + 1, "missing_cal": miss_cal,
               "longest_gap_cal": ([runs_cal[0][0].isoformat(), runs_cal[0][1].isoformat(), runs_cal[0][2]]
                                   if runs_cal else None),
               "missing_weekdays": miss_wd,
               "longest_gap_weekdays": ([runs_wd[0][0].isoformat(), runs_wd[0][1].isoformat(), runs_wd[0][2]]
                                        if runs_wd else None),
               "n_gaps_cal": len(runs_cal)}
        inc = dparse(rs[0].get("inception")) if has["inception"] else None
        if inc:
            fds = [x for x in ds if x >= inc]
            if fds:
                fset = set(fds)
                fm, fr = gap_runs(fset, fds[0], fds[-1])
                rec["inception"] = inc.isoformat()
                rec["fwd_first"] = fds[0].isoformat()
                rec["fwd_last"] = fds[-1].isoformat()
                rec["fwd_n"] = len(fds)
                rec["fwd_expected"] = (fds[-1] - fds[0]).days + 1
                rec["fwd_missing"] = fm
                rec["fwd_longest_gap"] = ([fr[0][0].isoformat(), fr[0][1].isoformat(), fr[0][2]]
                                          if fr else None)
                rec["pre_inception_days"] = len([x for x in ds if x < inc])
        for c in ("computed_at", "recorded_at"):
            if not has[c]:
                continue
            pairs = []
            for r in rs:
                t = tsparse(r.get(c))
                d = dparse(r.get(dcol))
                if t and d:
                    pairs.append(((t.date() - d).days, t))
            if not pairs:
                continue
            lags = [p[0] for p in pairs]
            rec[c + "_distinct"] = len({p[1].isoformat() for p in pairs})
            rec[c + "_max_lag_days"] = max(lags)
            rec[c + "_n_lag_gt2"] = sum(1 for x in lags if x > 2)
            rec[c + "_n_lag_lt0"] = sum(1 for x in lags if x < 0)
            rec[c + "_min_lag_days"] = min(lags)
        if has["correction"]:
            rec["correction_nonempty"] = sum(
                1 for r in rs if r.get("correction") not in (None, "", [], {}))
        out["arms"].append(rec)
    return out


def write_mode(rec: dict) -> str:
    """写入口径判定(卡面口径)。"""
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


def main() -> None:
    out: dict = {"read_at": dt.datetime.now(dt.timezone.utc).isoformat(), "base": BASE}

    # ---- ① A) 直读按日前向表 ----
    out["direct"] = {}
    for t in DIRECT_TABLES:
        st, cols, rows = pull_table(t)
        print("pull", t, st, "rows", len(rows))
        if st != 200:
            out["direct"][t] = {"status": st, "note": "读不到"}
            continue
        a = analyse_table(t, cols, rows)
        for rec in a["arms"]:
            rec["write_mode"] = write_mode(rec)
        out["direct"][t] = a

    # ---- ① B) 公开接口可见的按日表 ----
    out["series"] = {}
    for t in SERIES_TABLES + ["core_cap_daily", "cis_tilt_daily", "hl_book_daily"]:
        st, body = api("/api/v1/portfolio/series?table=" + t)
        arms = body.get("arms") if isinstance(body, dict) else None
        print("series", t, st, "arms", len(arms) if arms is not None else "-")
        out["series"][t] = {"status": st, "arms": arms,
                            "note": body.get("note") if isinstance(body, dict) else str(body)[:200]}

    # ---- ① C) proof 端点:第三方能不能自己验 ----
    out["proof"] = {}
    for p in ("/api/v1/proof/anchors", "/api/v1/proof/books"):
        st, body = api(p)
        n = None
        if isinstance(body, dict):
            n = len(body.get("books") or body.get("anchors") or [])
        print("proof", p, st, "n", n)
        out["proof"][p] = {"status": st, "head": json.dumps(body, ensure_ascii=False)[:1200]}

    # ---- ② loop_attempt ----
    st_d, direct = sb("loop_attempt", {"select": "at,loop_name,outcome,reason,elapsed_ms,writer,build",
                                       "order": "at.asc", "limit": "50"})
    n_direct = len(direct) if isinstance(direct, list) else None
    print("loop_attempt direct:", st_d, "n", n_direct)
    out["loop_attempt_direct"] = {"status": st_d, "n_rows": n_direct,
                                  "sample": (direct[:3] if isinstance(direct, list) else str(direct)[:200])}
    st_rpc, loops = sb("rpc/loop_attempt_health", {})
    out["loop_rpc"] = {"status": st_rpc}
    if isinstance(loops, list):
        fails = []
        for r in loops:
            fails.append({"loop": r.get("loop_name"), "last_fail": r.get("last_fail"),
                          "last_reason": (r.get("last_reason") or "")[:200],
                          "n_ok_24h": r.get("n_ok_24h"), "n_fail_24h": r.get("n_fail_24h"),
                          "last_ok": r.get("last_ok")})
        fails.sort(key=lambda x: x["last_fail"] or "")
        out["loop_rpc"].update({
            "n_loops": len(loops),
            "sum_fail_24h": sum(int(x.get("n_fail_24h") or 0) for x in fails),
            "sum_ok_24h": sum(int(x.get("n_ok_24h") or 0) for x in fails),
            "n_loops_fail24h": sum(1 for x in fails if int(x.get("n_fail_24h") or 0) > 0),
            "loops": fails})
        print("loop rpc loops", len(loops), "sum_fail_24h", out["loop_rpc"]["sum_fail_24h"])
    st_w, tables = sb("rpc/write_health", {})
    if isinstance(tables, list):
        tf = [{"table": t.get("table"), "last_fail": t.get("last_fail"),
               "last_outcome": t.get("last_outcome"), "n_fail_24h": t.get("n_fail_24h"),
               "last_body": (str(t.get("last_body"))[:160] if t.get("last_body") else "")}
              for t in tables if t.get("last_fail")]
        tf.sort(key=lambda x: x["last_fail"] or "")
        out["write_health"] = {"status": st_w, "n_tables": len(tables), "with_fail": len(tf), "rows": tf}
        print("write_health tables", len(tables), "with_fail", len(tf))

    # ---- ③ executor_host 心跳 / live 余额 ----
    st_e, eh = sb("executor_host", {"limit": "1"})
    out["executor_host_table"] = {"status": st_e, "note": str(eh)[:200]}
    print("executor_host table:", st_e)
    for alt in ("agent_call_log", "write_log"):
        st_a, rows_a = sb(alt, {"limit": "1"})
        out.setdefault("alt_heartbeat_tables", {})[alt] = {
            "status": st_a, "cols": list(rows_a[0].keys()) if isinstance(rows_a, list) and rows_a else []}
        print("alt", alt, st_a, out["alt_heartbeat_tables"][alt]["cols"][:8])

    # ---- 卡面 401 表:只探读权限状态 ----
    out["seth_only"] = {}
    for t in SETH_ONLY:
        st, body = sb(t, {"limit": "1"})
        out["seth_only"][t] = {"status": st, "note": (body if isinstance(body, str) else "readable")[:160]}
        print("seth_only", t, st)

    (HERE / "t217_final.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print("wrote t217_final.json")


if __name__ == "__main__":
    main()
