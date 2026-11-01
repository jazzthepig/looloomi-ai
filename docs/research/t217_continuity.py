#!/usr/bin/env python3
"""T-217 ①: 前向记录连续性账 (read-only).

对每条按日写入的前向表，逐臂算:
  首日 / 末日 / 应有天数 / 缺失天数 / 最长连续缺口(日期+长度)
  computed_at 晚于 d+2 天的行数(事后改写/补写) / 早于当天的行数
  correction 列非空的行数
并判断它能否被外部第三方当作「自首日起连续、未回填」的证据。

两条读取通道:
  A) 直读 PostgREST (publishable key) —— 只对 RLS 放行的表有效
  B) /api/v1/portfolio/series (Railway 服务端 service_role) —— 白名单内的表,
     但只给 (d, ret, nav) 与 arm 列表,没有 computed_at ⇒ 只能算日期连续性

翻页一律带 order= (T-170/T-173 实测:不带 order 翻页边界会漂)。
输出: /tmp/t217_scratch/continuity.json
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
os.makedirs(SCRATCH, exist_ok=True)

# 直读表: (select_cols, order, date_col, arm_col, ts_col)
DIRECT = {
    "core_cap_daily": ("d,arm,inception,computed_at,code_ref,source,nav,ret", "d.asc,arm.asc", "d", "arm", "computed_at"),
    "cis_tilt_daily": ("d,arm,inception,computed_at,code_ref,source,nav,ret", "d.asc,arm.asc", "d", "arm", "computed_at"),
    "hl_book_daily": ("d,book,computed_at,correction,code_ref,is_decision,nav,ret", "d.asc,book.asc", "d", "book", "computed_at"),
    "core_variants_daily": ("d,arm,inception,computed_at,code_ref,nav,ret", "d.asc,arm.asc", "d", "arm", "computed_at"),
    "multiplier_daily": ("d,arm,inception,computed_at,cost,code_ref,nav,ret", "d.asc,arm.asc", "d", "arm", "computed_at"),
    "r_money_daily": ("d,computed_at,inception,rule_version,nav,ret", "d.asc", "d", None, "computed_at"),
    "short_paper_money": ("d,arm,recorded_at,inception,rule_version,nav,ret", "d.asc,arm.asc", "d", "arm", "recorded_at"),
    "beta_core_nav": ("mark_date,marked_at,inception_id,nav,rebalanced,note,mark_source", "mark_date.asc", "mark_date", None, "marked_at"),
    "risk_meter_history": ("d,computed_at,band,regime", "d.asc", "d", None, "computed_at"),
    "cis_official_daily": ("d,symbol,published_at,code_ref,grade,signal", "d.asc,symbol.asc", "d", "symbol", "published_at"),
    "signal_journal": ("signal_date,symbol,recorded_at,outcome_at,signal,grade", "signal_date.asc,symbol.asc", "signal_date", "symbol", "recorded_at"),
}

# series 端点白名单(服务端 service_role)
SERIES = ["core_variants_daily", "multiplier_daily", "portfolio_layer_daily",
          "cis_tilt_daily", "core_cap_daily", "feature_arms_daily", "meta_allocator_daily"]

# 卡片点名但 publishable key 读不到的表 —— 用 42501 记录为 blocked
CARD_TABLES = ["core_cap_daily", "cis_tilt_daily", "beta_plus_daily", "tokenization_tilt_daily",
               "hl_book_daily", "allocation_daily", "allocation_nav_daily", "live_account_daily",
               "depth_divergence_log", "rr_matrix_daily"]


def get(path: str, params: dict, timeout: int = 90) -> tuple:
    q = urllib.parse.urlencode(params, safe="(),:*$")
    req = urllib.request.Request(f"{SB}/rest/v1/{path}?{q}", headers=H)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:300]
    except Exception as e:  # noqa: BLE001
        return None, type(e).__name__ + ": " + str(e)[:200]


def fetch_all(table: str, cols: str, order: str) -> tuple:
    rows, off = [], 0
    while True:
        st, body = get(table, {"select": cols, "order": order, "limit": str(PAGE), "offset": str(off)})
        if st != 200:
            return rows, st, body
        try:
            batch = json.loads(body)
        except Exception:  # noqa: BLE001
            return rows, st, body[:200]
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < PAGE:
            break
        off += PAGE
        if off > 400000:
            break
    return rows, 200, ""


def http(url: str, timeout: int = 90) -> tuple:
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "t217"}),
                                    timeout=timeout) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:200]
    except Exception as e:  # noqa: BLE001
        return None, type(e).__name__ + ": " + str(e)[:150]


def day(v) -> dt.date | None:
    if not v:
        return None
    try:
        return dt.date.fromisoformat(str(v)[:10])
    except Exception:  # noqa: BLE001
        return None


def ts(v) -> dt.datetime | None:
    if not v:
        return None
    try:
        t = dt.datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except Exception:  # noqa: BLE001
        return None
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


def gap_stats(days: list) -> tuple:
    """(缺失天数, 最长连续缺口长度, 缺口起止)"""
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


def analyse(rows: list, dcol: str, acol: str | None, tscol: str | None, table: str) -> dict:
    groups = collections.defaultdict(list)
    for r in rows:
        key = r.get(acol) if acol else "_all"
        if not isinstance(key, (str, int, float, type(None))):
            key = json.dumps(key, ensure_ascii=False, sort_keys=True)
        groups[key].append(r)
    arms = {}
    for arm, rs in groups.items():
        incs = sorted({r.get("inception") for r in rs if r.get("inception")})
        # 前向段 = d >= inception;回放段(之前)是模拟,不算「每天记录」
        fwd = [r for r in rs if not incs or (day(r.get(dcol)) and day(r.get(dcol)) >= day(incs[0]))]
        fd = sorted({day(r.get(dcol)) for r in fwd if day(r.get(dcol))})
        miss, longest, rng = gap_stats(fd)
        lags = collections.Counter()
        for r in fwd:
            a, b = day(r.get(dcol)), ts(r.get(tscol)) if tscol else None
            if a and b:
                lags[(b.date() - a).days] += 1
        corr = [r for r in fwd if r.get("correction")]
        arms[str(arm)] = {
            "n_rows": len(rs), "n_forward_rows": len(fwd),
            "inception": incs[0] if incs else None,
            "first": fd[0].isoformat() if fd else None,
            "last": fd[-1].isoformat() if fd else None,
            "days_present": len(fd),
            "days_expected": ((fd[-1] - fd[0]).days + 1) if fd else 0,
            "missing_days": miss,
            "longest_gap_days": longest, "longest_gap_range": rng,
            "missing_dates": [m.isoformat() for m in
                              sorted({d for d in (fd[0] + dt.timedelta(days=i)
                                                  for i in range(((fd[-1] - fd[0]).days + 1)))
                                      if d not in set(fd)})][:30] if fd else [],
            "lag_hist": {str(k): v for k, v in sorted(lags.items())},
            "late_gt_2d": sum(v for k, v in lags.items() if k > 2),
            "early_before_day": sum(v for k, v in lags.items() if k < 0),
            "max_lag_days": max(lags) if lags else None,
            "corrections_nonempty": len(corr),
            "correction_samples": [str(c.get("correction"))[:120] for c in corr[:3]],
            "code_refs": sorted({str(r.get("code_ref")) for r in fwd if r.get("code_ref")})[:3],
        }
    return {"n_rows": len(rows), "n_arms": len(arms), "arms": arms}


def main() -> None:
    out = {"direct": {}, "series": {}, "blocked": {}, "card_tables": {}}

    for t, (cols, order, dcol, acol, tscol) in DIRECT.items():
        rows, st, note = fetch_all(t, cols, order)
        if st != 200:
            out["direct"][t] = {"status": st, "note": note[:200]}
            print("BLOCKED", t, st, note[:90])
            continue
        out["direct"][t] = {"status": 200, **analyse(rows, dcol, acol, tscol, t)}
        print("OK    ", t, "rows", len(rows), "arms", out["direct"][t]["n_arms"])

    for t in SERIES:
        st, body = http(f"{BASE}/api/v1/portfolio/series?table={t}")
        try:
            j = json.loads(body)
        except Exception:  # noqa: BLE001
            out["series"][t] = {"status": st, "note": body[:150]}
            continue
        arms = {}
        for a in j.get("arms", []):
            fd = [a.get("first"), a.get("last")]
            dd = [day(x) for x in fd if x]
            miss, longest, rng = gap_stats([d for d in dd if d]) if len(dd) == 2 else (None, None, None)
            arms[a.get("arm")] = {
                "inception": a.get("inception"), "first": a.get("first"), "last": a.get("last"),
                "n": a.get("n"), "note": "series 端点只给臂级计数,无逐日明细 ⇒ 缺失/缺口不可算",
            }
        out["series"][t] = {"status": st, "arms": arms}
        print("SERIES", t, "arms", len(arms))

    # 卡片点名的表:逐个探测可读性
    for t in CARD_TABLES:
        st, body = get(t, {"limit": "1"})
        if st == 200:
            try:
                b = json.loads(body)
                out["card_tables"][t] = {"readable": True, "cols": list(b[0].keys()) if b else []}
            except Exception:  # noqa: BLE001
                out["card_tables"][t] = {"readable": True, "cols": []}
        else:
            out["card_tables"][t] = {"readable": False, "status": st, "note": body[:160]}
        print("CARD", t, out["card_tables"][t].get("readable"), out["card_tables"][t].get("note", "")[:80])

    with open(f"{SCRATCH}/continuity.json", "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("saved", f"{SCRATCH}/continuity.json")


if __name__ == "__main__":
    main()
