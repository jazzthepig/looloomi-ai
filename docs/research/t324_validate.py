#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T-324 校验 —— 两件独立于主结果的事:

(1) **① 面板校验**:用我拉的 cap_pit24 成员 + asset_mcap_daily 的价格/市值,按 core_pit_daily 的权重公式
    (市值加权、单币 ≤ 40%、日再平衡)重算日收益,和库里 `core_variants_daily` 的 arm='cap_pit24' 逐日对。
    对得上 ⇒ 我的成员、出处、日历对齐都是对的(主结果的地基)。

(2) **宇宙 vs 窗口分解**:S-428 发表的是「幸存者 24 名 × 2020-01→2026-09」的 +17.3%/年。
    这里把 M52 搬到**我的窗口**(2023-01→2026-10)分别跑两块面板:
      A. 按时点 cap_pit24(主结果用的面板)、B. S-428 的幸存者 24 名。
    A vs B = 宇宙效应(死币拖累);B 在我窗口里的数 vs S-428 的 +17.3% = 窗口效应。

只读;结果写 t324_validation.json。
"""
import importlib.util
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
OUT = HERE / "t324_validation.json"

spec = importlib.util.spec_from_file_location("t324_p_tilt", HERE / "t324_p_tilt.py")
t324 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(t324)
t312 = t324.t312

URL = os.environ.get("SUPABASE_URL")
KEY = os.environ.get("SUPABASE_KEY")
BASE = URL.rstrip("/") + "/rest/v1/"

# S-428 的幸存者 24 名(s428_beta_plus_factor_tilt.py 的 PANEL,逐字照抄)
SURVIVOR = ["BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX", "LINK", "DOT", "LTC", "TRX",
            "ATOM", "NEAR", "APT", "ARB", "OP", "SUI", "UNI", "AAVE", "INJ", "FIL", "ETC", "BCH"]

SIGNAL_START, SIGNAL_END = t324.SIGNAL_START, t324.SIGNAL_END


def _get(path, extra=None):
    return t312._get(BASE + path, t312._hdr(extra))


def fetch_mcap(syms):
    """asset_mcap_daily 的 price + mcap(校验 ① 的权重公式要用市值)。"""
    rows, off = [], 0
    while True:
        q = ("asset_mcap_daily?select=symbol,d,price,mcap&symbol=in.(%s)"
             "&and=(d.gte.%s,d.lte.%s)&order=symbol.asc,d.asc&limit=1000&offset=%d"
             % (",".join(syms), t324.PRICE_FROM, t324.PRICE_TO, off))
        body, _h = _get(q)
        r = json.loads(body)
        rows.extend(r)
        if len(r) < 1000:
            break
        off += len(r)
    return rows


def fetch_arm():
    rows, off = [], 0
    while True:
        q = ("core_variants_daily?select=d,ret,nav&arm=eq.cap_pit24"
             "&order=d.asc&limit=1000&offset=%d" % off)
        body, _h = _get(q)
        r = json.loads(body)
        rows.extend(r)
        if len(r) < 1000:
            break
        off += len(r)
    return rows


def main():
    mem = json.loads(t324.MEMBERS_JSON.read_text())
    mem_by_month = {}
    for r in mem:
        mem_by_month.setdefault(r["m"], []).append(r["symbol"])
    syms = sorted({r["symbol"] for r in mem} | set(SURVIVOR))
    raw_cache = HERE / "_t324_mcap_raw.json"
    if raw_cache.exists():
        raw = json.loads(raw_cache.read_text())
    else:
        raw = fetch_mcap(syms)
        raw_cache.write_text(json.dumps(raw, ensure_ascii=False))
    df = pd.DataFrame(raw, columns=["symbol", "d", "price", "mcap"])
    df["d"] = pd.to_datetime(df["d"])
    cal = pd.date_range(df["d"].min(), df["d"].max(), freq="D")
    P = df.pivot(index="d", columns="symbol", values="price").reindex(cal)
    MC = df.pivot(index="d", columns="symbol", values="mcap").reindex(cal)
    R = pd.DataFrame({s: P[s].dropna().pipe(lambda x: x / x.shift(1) - 1.0) for s in P.columns}).reindex(cal)

    # ── (1) ① 面板校验:重算 cap_pit24 的市值加权日收益 ──────────────────────
    out = []
    for d in cal:
        m = d.strftime("%Y-%m-01")
        mems = mem_by_month.get(m, [])
        if not mems:
            continue
        prev = d - pd.Timedelta(days=1)
        if prev not in cal:
            continue
        rr, pm = {}, {}
        for s in mems:
            if s not in P.columns:
                continue
            p0, p1 = P.at[prev, s], P.at[d, s]
            mc1 = MC.at[prev, s]
            if not (np.isfinite(p0) and np.isfinite(p1) and p0 > 0 and np.isfinite(mc1) and mc1 > 0):
                continue
            r = p1 / p0 - 1.0
            if not (-0.95 < r < 5):
                continue
            rr[s] = r
            pm[s] = mc1
        if len(rr) < 2:
            continue
        tot = sum(pm.values())
        w0 = {s: v / tot for s, v in pm.items()}
        excess = sum(max(w - 0.40, 0.0) for w in w0.values())
        rest = sum(w for w in w0.values() if w < 0.40)
        w1 = {s: (0.40 if w0[s] >= 0.40 else w0[s] * (1 + excess / rest if rest > 0 else 1.0)) for s in w0}
        out.append((d.date().isoformat(), sum(w1[s] * rr[s] for s in w1), len(w1)))
    mine = pd.Series({d: r for d, r, _ in out}).sort_index()

    arm = fetch_arm()
    db = pd.Series({r["d"]: float(r["ret"]) for r in arm if r.get("ret") is not None}).sort_index()
    db_nav = pd.Series({r["d"]: float(r["nav"]) for r in arm if r.get("nav") is not None}).sort_index()
    mine_n = pd.Series({d: n for d, _r, n in out}).sort_index()
    idx = db.index.intersection(mine.index)
    diff = (mine.loc[idx] - db.loc[idx])
    adiff = diff.abs()

    # ── 差异归因:差在哪些天、占多少、是不是前向冻结行 ─────────────────────────
    def _bucket(lo, hi):
        m = (adiff >= lo) & (adiff < hi)
        return {"lo": lo, "hi": hi, "n": int(m.sum()),
                "dates": [str(x) for x in adiff.index[m]] if m.sum() <= 12 else None}

    worst = adiff.sort_values(ascending=False).head(8)
    nav_chk = None
    try:
        # 库自己的 nav 与 ret 是否自洽(ret_t == nav_t/nav_{t-1} − 1)
        navser = db_nav.reindex(db_nav.index).dropna()
        navret = (navser / navser.shift(1) - 1.0).dropna()
        j = navret.index.intersection(db.index)
        if len(j) > 2:
            dv = (navret.loc[j] - db.loc[j]).abs()
            nav_chk = {"n": int(len(j)), "max_abs_diff": float(dv.max()),
                       "n_exact_1e-8": int((dv < 1e-8).sum())}
    except Exception:
        pass
    cum_mine = float((1 + mine.loc[idx]).prod() - 1)
    cum_db = float((1 + db.loc[idx]).prod() - 1)
    att = {
        "inception_forward_lock": "2026-10-30",
        "n_days_diff_lt_1e-9": int((adiff < 1e-9).sum()),
        "n_days_diff_lt_1e-6": int((adiff < 1e-6).sum()),
        "n_days_diff_ge_1e-6": int((adiff >= 1e-6).sum()),
        "n_days_diff_ge_1e-4": int((adiff >= 1e-4).sum()),
        "buckets": [_bucket(0.0, 1e-9), _bucket(1e-9, 1e-6), _bucket(1e-6, 1e-4), _bucket(1e-4, 1.0)],
        "worst8": [{"d": str(i), "abs_diff": float(v), "mine": float(mine.loc[i]),
                    "db": float(db.loc[i]), "n_members": int(mine_n.get(i, -1))} for i, v in worst.items()],
        "cum_mine_over_overlap": cum_mine, "cum_db_over_overlap": cum_db,
        "cum_gap_pp": (cum_mine - cum_db) * 100,
        "sum_abs_diff": float(adiff.sum()),
        "lib_nav_selfcheck": nav_chk,
        "read": ("库里存的是 8 位小数(ret 列),故 <1e-9 的天就是逐位相同;"
                 "≥1e-4 的天要看是不是前向冻结行(d ≥ inception = 2026-10-30,库冻结、我用今天的市值重算)"),
    }
    out_json = {
        "panel_check": {
            "n_days_mine": int(len(mine)), "n_days_db": int(len(db)),
            "overlap_days": int(len(idx)),
            "overlap_from": str(idx[0]) if len(idx) else None,
            "overlap_to": str(idx[-1]) if len(idx) else None,
            "max_abs_diff": float(diff.abs().max()) if len(diff) else None,
            "mean_abs_diff": float(diff.abs().mean()) if len(diff) else None,
            "corr": float(np.corrcoef(mine.loc[idx], db.loc[idx])[0, 1]) if len(idx) > 2 else None,
            "n_days_exact_1e-9": int((diff.abs() < 1e-9).sum()),
            "note": "我的重算 vs 库里的 cap_pit24 臂;差 0 = 成员/出处/日历全对",
        },
        "panel_check_attribution": att,
    }

    # ── (2) 宇宙 vs 窗口:M52 在两块面板上、同一个窗口 ──────────────────────
    days = pd.date_range(pd.Timestamp(SIGNAL_START), pd.Timestamp(SIGNAL_END) + pd.Timedelta(days=1), freq="D")
    mondays = [pd.Timestamp(x) for x in t312._mondays(SIGNAL_START, SIGNAL_END)]
    all_syms = sorted(set(syms))

    def m52_scores(panel_of):
        sc = {}
        for t in mondays:
            panel = panel_of.get(t, [])
            if not panel:
                continue
            sub = P[panel]
            rk = lambda X: X.rank(axis=1, pct=True)
            mom = {n: sub / sub.shift(n) - 1.0 for n in (14, 28, 90)}
            mc = (rk(mom[14]) + rk(mom[28]) + rk(mom[90])) / 3.0
            h52 = sub / sub.rolling(365, min_periods=180).max()
            combo = (rk(mc) + rk(h52)) / 2.0
            row = combo.loc[t] if t in combo.index else pd.Series(dtype=float)
            sc[t] = {s: (float(row[s]) if np.isfinite(row.get(s, np.nan)) else None) for s in panel}
        return sc

    def build(panel_of, tag):
        def hold_target(t):
            p = panel_of.get(t, [])
            return pd.Series(1.0 / len(p), index=p) if p else None

        def tilt_target(scores):
            def f(t):
                p = panel_of.get(t, [])
                if not p:
                    return None
                z = t324._zmap({s: scores.get(t, {}).get(s) for s in p})
                w = pd.Series({s: (1.0 / len(p)) * (1.0 + t324.K * z[s]) for s in p}).clip(lower=0.0)
                return (w / w.sum()) if w.sum() > 0 else None
            return f

        sc = m52_scores(panel_of)
        rh, toh = t324._run_arm(days, R, all_syms, P, hold_target)
        rm, tom = t324._run_arm(days, R, all_syms, P, tilt_target(sc))
        s_h = t324._stats(rh, rh, toh, "HOLD")
        s_m = t324._stats(rm, rh, tom, "M52")
        return {"HOLD": s_h, "M52": s_m}

    # A. 按时点 cap_pit24(主结果的面板)
    pit_panel = {}
    for t in mondays:
        members = mem_by_month.get(t.strftime("%Y-%m-01"), [])
        px = P.loc[t] if t in P.index else pd.Series(dtype=float)
        pit_panel[t] = [s for s in members if s in px.index and np.isfinite(px[s])]
    a = build(pit_panel, "pit")

    # B. S-428 的幸存者 24 名(固定名单)
    surv_panel = {}
    for t in mondays:
        px = P.loc[t] if t in P.index else pd.Series(dtype=float)
        surv_panel[t] = [s for s in SURVIVOR if s in px.index and np.isfinite(px[s])]
    b = build(surv_panel, "survivor")

    out_json["universe_vs_window"] = {
        "window": [SIGNAL_START, SIGNAL_END],
        "A_pit_cap_pit24": {"HOLD": a["HOLD"], "M52": a["M52"]},
        "B_survivor24_S428_universe": {"HOLD": b["HOLD"], "M52": b["M52"]},
        "S428_published_2020_2026_survivor": t324.S428_PUB,
        "reading": {
            "universe_effect_ann_ex_pp": (b["M52"]["ann_ex_vs_hold"] - a["M52"]["ann_ex_vs_hold"]) * 100,
            "window_effect_ann_ex_pp": (b["M52"]["ann_ex_vs_hold"] * 100 - t324.S428_PUB["ann_ex_pct"]),
            "note": "宇宙效应 = B.M52 − A.M52(同窗口,换面板);窗口效应 = B.M52 − S-428 发表值",
        },
    }
    OUT.write_text(json.dumps(out_json, ensure_ascii=False, indent=2, default=float))
    pc = out_json["panel_check"]
    print("① 校验: 重算 %d 天 vs 库 %d 天,重叠 %d 天(%s→%s)最大差 %.3g 相关 %.6f" %
          (pc["n_days_mine"], pc["n_days_db"], pc["overlap_days"], pc["overlap_from"], pc["overlap_to"],
           pc["max_abs_diff"] or float("nan"), pc["corr"] or float("nan")), flush=True)
    at = out_json["panel_check_attribution"]
    print("   归因: <1e-9 %d 天 / <1e-6 %d 天 / ≥1e-6 %d 天 / ≥1e-4 %d 天;累计 我 %.4f vs 库 %.4f (差 %.4f pp)" %
          (at["n_days_diff_lt_1e-9"], at["n_days_diff_lt_1e-6"], at["n_days_diff_ge_1e-6"],
           at["n_days_diff_ge_1e-4"], at["cum_mine_over_overlap"], at["cum_db_over_overlap"],
           at["cum_gap_pp"]), flush=True)
    for w in at["worst8"][:4]:
        print("   差最大: %s |Δ|=%.3g 我 %.8f 库 %.8f 成员 %d" %
              (w["d"], w["abs_diff"], w["mine"], w["db"], w["n_members"]), flush=True)
    u = out_json["universe_vs_window"]
    print("A 按时点面板: HOLD cum %.4f / M52 cum %.4f ann_ex %+.4f" %
          (a["HOLD"]["cum"], a["M52"]["cum"], a["M52"]["ann_ex_vs_hold"]), flush=True)
    print("B 幸存者面板: HOLD cum %.4f / M52 cum %.4f ann_ex %+.4f" %
          (b["HOLD"]["cum"], b["M52"]["cum"], b["M52"]["ann_ex_vs_hold"]), flush=True)
    print("→", OUT.name, flush=True)


if __name__ == "__main__":
    main()
