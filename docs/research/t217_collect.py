#!/usr/bin/env python3
"""T-217 只读采集 + 连续性账:按日表逐臂算 首日/末日/应有天数/缺失/最长缺口/事后补写/更正。

- 只读:os.environ["SUPABASE_URL"] / ["SUPABASE_KEY"] (publishable)
- 不读 .env、不打印 key、不写库
- 翻页一律带 order=
"""
from __future__ import annotations

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
os.makedirs(SCRATCH, exist_ok=True)
PAGE = 1000

# table -> (cols, order, date_col, arm_col)
TABLES = {
    "core_cap_daily": ("d,arm,inception,computed_at,code_ref,source,nav,ret", "d.asc,arm.asc", "d", "arm"),
    "cis_tilt_daily": ("d,arm,inception,computed_at,code_ref,source,nav,ret", "d.asc,arm.asc", "d", "arm"),
    "hl_book_daily": ("d,book,computed_at,correction,code_ref,is_decision,nav,ret", "d.asc,book.asc", "d", "book"),
    "core_variants_daily": ("d,arm,inception,computed_at,code_ref,nav,ret", "d.asc,arm.asc", "d", "arm"),
    "multiplier_daily": ("d,arm,inception,computed_at,cost,code_ref,nav,ret", "d.asc,arm.asc", "d", "arm"),
    "r_money_daily": ("d,computed_at,inception,rule_version,nav,ret", "d.asc", "d", None),
    "short_paper_money": ("d,arm,recorded_at,inception,rule_version,nav,ret", "d.asc,arm.asc", "d", "arm"),
    "beta_core_nav": ("mark_date,marked_at,inception_id,nav,rebalanced,note,mark_source", "mark_date.asc", "mark_date", None),
    "risk_meter_history": ("d,computed_at,band,regime", "d.asc", "d", None),
    "cis_official_daily": ("d,symbol,published_at,code_ref,grade,signal", "d.asc,symbol.asc", "d", "symbol"),
    "signal_journal": ("signal_date,symbol,recorded_at,outcome_at,signal,grade", "signal_date.asc,symbol.asc", "signal_date", "symbol"),
    "depth_divergence_log": ("*", "id.asc", None, None),
}


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


def fetch_all(table, cols, order):
    rows, off = [], 0
    while True:
        st, body = get(table, {"select": cols, "order": order,
                               "limit": str(PAGE), "offset": str(off)})
        if st != 200:
            return rows, st, body
        try:
            batch = json.loads(body)
        except Exception:
            return rows, st, body[:200]
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < PAGE:
            break
        off += PAGE
        if off > 500000:
            break
    return rows, 200, ""


def parse_ts(v):
    if not v:
        return None
    s = str(v).replace("Z", "+00:00")
    try:
        t = dt.datetime.fromisoformat(s)
    except Exception:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=dt.timezone.utc)
    return t


def parse_day(v):
    if not v:
        return None
    try:
        return dt.date.fromisoformat(str(v)[:10])
    except Exception:
        return None


def continuity(dates, ts_pairs, corrections):
    """dates: sorted unique date list; ts_pairs: [(day, ts)]; corrections: list of truthy correction flags"""
    out = {}
    if not dates:
        return {"n_days": 0}
    first, last = dates[0], dates[-1]
    expected = (last - first).days + 1
    have = set(dates)
    missing = []
    cur = first
    while cur <= last:
        if cur not in have:
            missing.append(cur)
        cur += dt.timedelta(days=1)
    longest, best = 0, None
    for m in missing:
        if best and (m - best[-1]).days == 1:
            best.append(m)
        else:
            best = [m]
        if len(best) > longest:
            longest, longest_range = len(best), (best[0], best[-1])
    out.update({
        "first": first.isoformat(), "last": last.isoformat(),
        "n_days": len(dates), "expected_days": expected,
        "missing_days": len(missing),
        "missing_dates": [m.isoformat() for m in missing][:40],
        "longest_gap_days": longest,
        "longest_gap_range": [longest_range[0].isoformat(), longest_range[1].isoformat()] if longest else None,
        "late_writes_gt_2d": sum(1 for _, t in ts_pairs if t and (t.date() - _).days > 2),
        "early_writes_before_day": sum(1 for _, t in ts_pairs if t and t.date() < _),
        "max_write_lag_days": max([(t.date() - day).days for day, t in ts_pairs if t] or [None]),
        "corrections_nonempty": sum(1 for c in corrections if c),
        "n_rows": len(ts_pairs),
    })
    return out


def main():
    result = {"tables": {}, "series": {}, "errors": {}}
    for t, (cols, order, dcol, acol) in TABLES.items():
        rows, st, note = fetch_all(t, cols, order)
        if st != 200:
            result["errors"][t] = {"status": st, "note": note[:200]}
            print(t, "BLOCKED/ERR", st, note[:80])
            continue
        by = {}
        for r in rows:
            key = r.get(acol) if acol else "_all"
            if not isinstance(key, (str, int, float, type(None))):
                key = json.dumps(key, ensure_ascii=False, sort_keys=True)
            by.setdefault(key, []).append(r)
        arms = {}
        for arm, rs in by.items():
            days = sorted({parse_day(r.get(dcol)) for r in rs if parse_day(r.get(dcol))})
            tscol = "computed_at" if "computed_at" in rs[0] else ("recorded_at" if "recorded_at" in rs[0] else ("marked_at" if "marked_at" in rs[0] else ("published_at" if "published_at" in rs[0] else ("recorded_at" if "recorded_at" in rs[0] else None))))
            ts_pairs = [(parse_day(r.get(dcol)), parse_ts(r.get(tscol))) for r in rs] if tscol else []
            corr = [r.get("correction") for r in rs if "correction" in r]
            c = continuity(days, ts_pairs, corr)
            c["ts_col"] = tscol
            inc = {r.get("inception") for r in rs if r.get("inception")}
            c["inception"] = sorted(inc)[:3] if inc else None
            arms[str(arm)] = c
        result["tables"][t] = {"n_rows": len(rows), "arms": arms}
        print(t, "rows", len(rows), "arms", len(arms))
    with open(SCRATCH + "/continuity_raw.json", "w") as f:
        json.dump(result, f, ensure_ascii=False, indent=1)
    print("saved", SCRATCH + "/continuity_raw.json")


if __name__ == "__main__":
    main()
