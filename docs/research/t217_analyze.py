#!/usr/bin/env python3
"""T-217 分析:前向段( d >= inception )连续性 + 写入滞后分布 + 公开 series 覆盖。

只读。重新拉原始行并算前向段(回放段与前向段分开 —— 两者混在一起会把
「历史回放一次算完」误读成「每天补写」)。
"""
from __future__ import annotations

import collections
import datetime as dt
import json
from pathlib import Path
import os
import urllib.error
import urllib.parse
import urllib.request

SB = os.environ["SUPABASE_URL"].rstrip("/")
KEY = os.environ["SUPABASE_KEY"]
H = {"apikey": KEY, "Authorization": "Bearer " + KEY, "Accept": "application/json"}
BASE = "https://web-production-0cdf76.up.railway.app"
SCRATCH = str(Path(__file__).resolve().parent)
PAGE = 1000

SPEC = {
    "core_cap_daily": ("d,arm,inception,computed_at,code_ref", "d.asc,arm.asc", "d", "arm", "computed_at"),
    "cis_tilt_daily": ("d,arm,inception,computed_at,code_ref", "d.asc,arm.asc", "d", "arm", "computed_at"),
    "hl_book_daily": ("d,computed_at,correction,code_ref,is_decision,nav,ret", "d.asc", "d", None, "computed_at"),
    "core_variants_daily": ("d,arm,inception,computed_at,code_ref", "d.asc,arm.asc", "d", "arm", "computed_at"),
    "multiplier_daily": ("d,arm,inception,computed_at,cost,code_ref", "d.asc,arm.asc", "d", "arm", "computed_at"),
    "r_money_daily": ("d,computed_at,inception,rule_version", "d.asc", "d", None, "computed_at"),
    "short_paper_money": ("d,arm,recorded_at,inception,rule_version", "d.asc,arm.asc", "d", "arm", "recorded_at"),
    "beta_core_nav": ("mark_date,marked_at,inception_id,nav,rebalanced,note", "mark_date.asc", "mark_date", None, "marked_at"),
    "risk_meter_history": ("d,computed_at,band,regime", "d.asc", "d", None, "computed_at"),
    "cis_official_daily": ("d,symbol,published_at,code_ref,grade,signal", "d.asc,symbol.asc", "d", "symbol", "published_at"),
    "signal_journal": ("signal_date,symbol,recorded_at,outcome_at,signal,grade", "signal_date.asc,symbol.asc", "signal_date", "symbol", "recorded_at"),
}
SERIES_TABLES = ["core_variants_daily", "multiplier_daily", "portfolio_layer_daily",
                 "cis_tilt_daily", "core_cap_daily", "feature_arms_daily", "meta_allocator_daily"]


def get(path, params, timeout=90):
    q = urllib.parse.urlencode(params, safe="(),:*$")
    req = urllib.request.Request(SB + "/rest/v1/" + path + "?" + q, headers=H)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:300]
    except Exception as e:  # noqa: BLE001
        return None, type(e).__name__ + ": " + str(e)[:200]


def http(url, timeout=90):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "t217"}), timeout=timeout) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:200]
    except Exception as e:  # noqa: BLE001
        return None, type(e).__name__ + ": " + str(e)[:150]


def fetch_all(table, cols, order):
    rows, off = [], 0
    while True:
        st, body = get(table, {"select": cols, "order": order, "limit": str(PAGE), "offset": str(off)})
        if st != 200:
            return rows, st, body
        batch = json.loads(body)
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < PAGE:
            break
        off += PAGE
        if off > 500000:
            break
    return rows, 200, ""


def day(v):
    try:
        return dt.date.fromisoformat(str(v)[:10])
    except Exception:
        return None


def ts(v):
    if not v:
        return None
    try:
        t = dt.datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except Exception:
        return None
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


def gap_stats(days):
    if not days:
        return 0, 0, None
    days = sorted(days)
    have = set(days)
    missing, cur = [], days[0]
    while cur <= days[-1]:
        if cur not in have:
            missing.append(cur)
        cur += dt.timedelta(days=1)
    longest, rng, run = 0, None, []
    for m in missing:
        if run and (m - run[-1]).days == 1:
            run.append(m)
        else:
            run = [m]
        if len(run) > longest:
            longest, rng = len(run), (run[0], run[-1])
    return len(missing), longest, ([rng[0].isoformat(), rng[1].isoformat()] if rng else None)


def main():
    out = {}
    for t, (cols, order, dcol, acol, tscol) in SPEC.items():
        rows, st, note = fetch_all(t, cols, order)
        if st != 200:
            out[t] = {"status": st, "note": note[:200]}
            print(t, "ERR", st, note[:80])
            continue
        groups = collections.defaultdict(list)
        for r in rows:
            key = r.get(acol) if acol else "_all"
            if not isinstance(key, (str, int, float, type(None))):
                key = json.dumps(key, ensure_ascii=False, sort_keys=True)
            groups[key].append(r)
        arms = {}
        for arm, rs in groups.items():
            incs = sorted({r.get("inception") for r in rs if r.get("inception")})
            fwd = [r for r in rs if not incs or (day(r.get(dcol)) and day(r.get(dcol)) >= day(incs[0]))]
            fd = sorted({day(r.get(dcol)) for r in fwd if day(r.get(dcol))})
            miss, longest, rng = gap_stats(fd)
            lags = collections.Counter()
            for r in fwd:
                a, b = day(r.get(dcol)), ts(r.get(tscol))
                if a and b:
                    lags[(b.date() - a).days] += 1
            corr = [r for r in fwd if r.get("correction")]
            arms[str(arm)] = {
                "n_rows": len(rs), "n_forward_rows": len(fwd),
                "inception": incs[0] if incs else None,
                "fwd_first": fd[0].isoformat() if fd else None,
                "fwd_last": fd[-1].isoformat() if fd else None,
                "fwd_days": len(fd),
                "fwd_expected": ((fd[-1] - fd[0]).days + 1) if fd else 0,
                "fwd_missing": miss, "fwd_longest_gap": longest, "fwd_gap_range": rng,
                "lag_hist": {str(k): v for k, v in sorted(lags.items())},
                "late_gt_2d": sum(v for k, v in lags.items() if k > 2),
                "corrections": len(corr),
                "correction_samples": [str(c.get("correction"))[:120] for c in corr[:3]],
            }
        out[t] = {"status": 200, "n_rows": len(rows), "arms": arms}
        print(t, "rows", len(rows), "arms", len(arms))

    series = {}
    for t in SERIES_TABLES:
        st, body = http(BASE + "/api/v1/portfolio/series?table=" + t)
        try:
            j = json.loads(body)
        except Exception:
            series[t] = {"status": st, "note": body[:120]}
            continue
        series[t] = {"status": st, "arms": {a["arm"]: {"inception": a.get("inception"),
                                                      "first": a.get("first"), "last": a.get("last"),
                                                      "n": a.get("n")} for a in j.get("arms", [])}}
    out["_series"] = series
    with open(SCRATCH + "/continuity_fwd.json", "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("saved continuity_fwd.json")


if __name__ == "__main__":
    main()
