#!/usr/bin/env python3
"""T-217 —— 同一次 `git stash -u` 的第二个受害者:asset_embeddings_history。

2026-10-13 09:13 JST,Mac 根的一次 `git stash -u` 把两个**从未被跟踪**的脚本
(risk_meter_history_push.py / vector_push.py)扫进 stash@{0}^3,从未 pop 回来。
T-211 的修复 commit e9e91b0 记:「恢复 risk_meter_history_push.py / vector_push.py」。

risk_meter_history 的 15 天空洞已定位(见报告 §2.5.2)。本脚本测**同一原因**是否
也打在 vector_push.py 的落表 asset_embeddings_history 上 —— 如果是,这是「一个原因、
两张表」而不是「一张表的偶发」。

只读 SELECT,显式 order= 翻页(limit=1000,返回==limit 就续翻)。
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
H = {"apikey": KEY, "Authorization": "Bearer " + KEY, "Accept": "application/json"}
HERE = Path(__file__).resolve().parent
PAGE = 1000

TABLE = "asset_embeddings_history"
DATE_CANDS = ("d", "date", "as_of", "created_at", "trade_date", "computed_date")
ARM_CANDS = ("symbol", "arm", "model", "asset")
TS_CANDS = ("computed_at", "created_at", "recorded_at", "published_at")


def sb_safe(path, params):
    q = urllib.parse.urlencode(params, safe="().,:*$")
    req = urllib.request.Request(SB + "/rest/v1/" + path + "?" + q, headers=H)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, json.loads(r.read().decode() or "[]")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:200]
    except Exception as e:  # noqa: BLE001
        return None, type(e).__name__ + ": " + str(e)[:150]


def dparse(v):
    try:
        return dt.date.fromisoformat(str(v)[:10])
    except Exception:  # noqa: BLE001
        return None


def gap_runs(dates, lo, hi):
    """补齐自然日,返回 (缺失天数, 最长缺口(起, 止, 长度))。"""
    runs, cur, n = [], None, 0
    day = lo
    while day <= hi:
        if day in dates:
            if cur:
                runs.append((cur[0], cur[1], (cur[1] - cur[0]).days + 1))
                cur = None
        else:
            n += 1
            cur = [day, day] if cur is None else [cur[0], day]
        day += dt.timedelta(days=1)
    if cur:
        runs.append((cur[0], cur[1], (cur[1] - cur[0]).days + 1))
    runs.sort(key=lambda g: -g[2])
    return n, (runs[0] if runs else None)


def main():
    out = {"table": TABLE, "checked_at": dt.datetime.now(dt.timezone.utc).isoformat()}
    st, one = sb_safe(TABLE, {"limit": "1"})
    if st != 200 or not isinstance(one, list) or not one:
        out["error"] = "probe status=%s %s" % (st, str(one)[:200])
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return
    cols = list(one[0].keys())
    dcol = next((c for c in DATE_CANDS if c in cols), None)
    acol = next((c for c in ARM_CANDS if c in cols), None)
    tsc = next((c for c in TS_CANDS if c in cols), None)
    out["cols"] = cols
    out["date_col"], out["arm_col"], out["ts_col"] = dcol, acol, tsc
    if not dcol:
        out["error"] = "no date col among %s" % (DATE_CANDS,)
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return
    want = [c for c in (dcol, acol, tsc) if c]
    rows, off, err = [], 0, None
    while True:
        st2, chunk = sb_safe(TABLE, {"select": ",".join(want), "order": dcol + ".asc",
                                     "limit": str(PAGE), "offset": str(off)})
        if st2 != 200:
            err = "page(offset=%d) status=%s %s" % (off, st2, str(chunk)[:140])
            break
        if not isinstance(chunk, list) or not chunk:
            break
        rows.extend(chunk)
        if len(chunk) < PAGE:
            break
        off += PAGE
        if off > 500000:
            break
    out["n_rows"] = len(rows)
    out["err"] = err
    groups = {}
    for r in rows:
        groups.setdefault(str(r.get(acol)) if acol else "(all)", []).append(r)
    arms = []
    for arm, rs in sorted(groups.items()):
        dates = sorted({dparse(r.get(dcol)) for r in rs} - {None})
        if not dates:
            continue
        lo, hi = dates[0], dates[-1]
        miss, best = gap_runs(set(dates), lo, hi)
        arms.append({"arm": arm, "first": lo.isoformat(), "last": hi.isoformat(),
                     "n_rows": len(rs), "n_days": len(dates),
                     "expected": (hi - lo).days + 1, "missing_days": miss,
                     "longest_gap": None if not best else
                     {"from": best[0].isoformat(), "to": best[1].isoformat(), "days": best[2]}})
    out["arms"] = arms
    out["n_arms"] = len(arms)
    out["total_missing"] = sum(a["missing_days"] for a in arms)
    print("==", TABLE, "rows", len(rows), "arms", len(arms),
          "total_missing", out["total_missing"])
    for a in arms[:20]:
        print("  ", a["arm"], a["first"], "->", a["last"], "n=%d/%d" % (a["n_days"], a["expected"]),
              "miss=%d" % a["missing_days"], "gap=", a["longest_gap"])
    (HERE / "t217_sibling_gap.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print("wrote t217_sibling_gap.json")


if __name__ == "__main__":
    main()
