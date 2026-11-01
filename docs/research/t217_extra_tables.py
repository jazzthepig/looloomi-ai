#!/usr/bin/env python3
"""T-217 —— 复核 4 张 t217_continuity.json 里有、但主脚本没覆盖的按日表:
cis_official_daily / signal_journal / beta_core_nav / risk_meter_history。

逐表显式指定日期列 / 臂列 / 时间戳列(不猜),用本卡自己的翻页读法
(limit=1000 + 返回==limit 就续翻,order= 按主键),
逐臂算:首日/末日/应有天数/缺失天数/最长连续缺口/时间戳晚于 d+2 / correction 非空。

注:beta_core_nav 带 interval_hours 列 —— 若标称间隔不是 24h,「缺失天数」不是断档,
    脚本会把它单独报出来。
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

# 表 -> (日期列, 臂列, 时间戳列候选)
CONFIG = {
    "cis_official_daily": ("d", "symbol", ("published_at", "computed_at")),
    "signal_journal": ("signal_date", "symbol", ("recorded_at",)),
    "beta_core_nav": ("mark_date", None, ("marked_at",)),
    "risk_meter_history": ("d", None, ("computed_at",)),
}


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


def tsparse(v):
    if not v:
        return None
    try:
        return dt.datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None


def gaps(dates):
    """返回 (缺失天数, 最长缺口(起,止,长度))。"""
    if not dates:
        return 0, None
    s = set(dates)
    cand = []
    cur = None
    day = min(dates)
    while day <= max(dates):
        if day in s:
            if cur:
                cand.append((cur[0], cur[1], (cur[1] - cur[0]).days + 1))
                cur = None
        else:
            cur = [day, day] if cur is None else [cur[0], day]
        day += dt.timedelta(days=1)
    if cur:
        cand.append((cur[0], cur[1], (cur[1] - cur[0]).days + 1))
    if not cand:
        return 0, None
    best = max(cand, key=lambda g: g[2])
    return sum(g[2] for g in cand), best


def main():
    out = {}
    for t, (dcol, acol, tscands) in CONFIG.items():
        st1, one = sb_safe(t, {"limit": "1"})
        if st1 != 200 or not isinstance(one, list) or not one:
            out[t] = {"error": "probe status=%s %s" % (st1, str(one)[:160])}
            print("==", t, "probe failed:", st1, str(one)[:160])
            continue
        cols = list(one[0].keys())
        if dcol not in cols:
            print("==", t, "date col", dcol, "not in cols", cols)
            out[t] = {"cols": cols, "error": "date col %s missing" % dcol}
            continue
        tscol = next((c for c in tscands if c in cols), None)
        want = [c for c in (dcol, acol, tscol, "correction", "interval_hours") if c and c in cols]
        rows, off, err = [], 0, None
        while True:
            st2, chunk = sb_safe(t, {"select": ",".join(want), "order": dcol + ".asc",
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
        groups = {}
        for r in rows:
            groups.setdefault(str(r.get(acol)) if acol else "(all)", []).append(r)
        arms = []
        for arm, rs in sorted(groups.items()):
            ds = sorted({dparse(r.get(dcol)) for r in rs if dparse(r.get(dcol))})
            if not ds:
                continue
            miss, g = gaps(ds)
            rec = {"arm": arm, "first": ds[0].isoformat(), "last": ds[-1].isoformat(),
                   "n_days": len(ds), "expected": (ds[-1] - ds[0]).days + 1,
                   "missing": miss,
                   "longest_gap": ([g[0].isoformat(), g[1].isoformat(), g[2]] if g else None)}
            if "interval_hours" in cols:
                iv = sorted({str(r.get("interval_hours")) for r in rs})
                rec["interval_hours_values"] = iv
            if tscol:
                pairs = []
                for r in rs:
                    tt, dd = tsparse(r.get(tscol)), dparse(r.get(dcol))
                    if tt and dd:
                        pairs.append(((tt.date() - dd).days, tt))
                if pairs:
                    lags = [p[0] for p in pairs]
                    rec["ts_col"] = tscol
                    rec["ts_distinct"] = len({p[1].isoformat() for p in pairs})
                    rec["ts_max_lag"] = max(lags)
                    rec["ts_min_lag"] = min(lags)
                    rec["ts_n_lag_gt2"] = sum(1 for x in lags if x > 2)
                    rec["ts_n_lag_lt0"] = sum(1 for x in lags if x < 0)
            if "correction" in cols:
                rec["correction_nonempty"] = sum(1 for r in rs
                                                if r.get("correction") not in (None, "", [], {}))
            arms.append(rec)
        out[t] = {"cols": cols, "date_col": dcol, "arm_col": acol, "ts_col": tscol,
                   "pull_err": err, "n_rows": len(rows), "n_arms": len(arms), "arms": arms}
        print("==", t, "rows", len(rows), "arms", len(arms),
              "date_col", dcol, "arm_col", acol, "ts_col", tscol, err or "")
        for a in arms[:4]:
            print("   %-14s %s..%s n=%-5d exp=%-5d miss=%-5d gap=%-26s ts_late>2=%s dist=%s maxlag=%s" % (
                str(a["arm"])[:14], a["first"], a["last"], a["n_days"], a["expected"], a["missing"],
                str(a["longest_gap"]), a.get("ts_n_lag_gt2"), a.get("ts_distinct"),
                a.get("ts_max_lag")))
        if len(arms) > 4:
            print("   ... 其余 %d 臂见 json" % (len(arms) - 4))
    (HERE / "t217_extra_tables.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print("wrote t217_extra_tables.json")


if __name__ == "__main__":
    main()
