#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T-324 / S-802 —— ② 面板内倾斜:高维 P(价格相位 5 维)能不能胜过现任的 M52(S-428 动量 + 52 周高点)。

预注册原文(REFUTATION_LEDGER.md S-802)照抄在报告 `T-324_p_tilt.md` 开头。纪律:只读、不入库、不改代码。

框架(照 S-802「写死」段):
  ① = 按时点 `cap_pit24` 的 24 名(RPC `core_pit_members`,与 src/data/signals/core_pit.py 同一个出处)。
  基础权重等权 1/N;倾斜 w = (1/N)·(1 + k·z),k = 1;z = 该周 24 名里打分的居中秩(映射到 [-1,1]);
  没有分数的币 z = 0。每周一收盘出信号、次日收盘成交;成本 10bp × 换手。三条臂同日程同成本:
  HOLD(等权持有)、M52(S-428 原文)、P(t312_rebaseline.py 的 P 臂 Ridge 预测,只在 24 名里取秩)。
  区间:2023-01-02 → 2026-10-05;两半按周数对半。

用法:
  python3 t324_p_tilt.py fetch   # 拉 ① 成员 + 价格(只读)→ _t324_members.json / _t324_prices.json
  python3 t324_p_tilt.py run     # P 走步(自检) + 三臂回测 → t324_results.json
"""
import argparse
import datetime as dt
import importlib.util
import json
import os
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent

MEMBERS_JSON = HERE / "_t324_members.json"
PRICES_JSON = HERE / "_t324_prices.json"
RESULTS = HERE / "t324_results.json"

URL = os.environ.get("SUPABASE_URL")
KEY = os.environ.get("SUPABASE_KEY")

PANEL_N = 24
SIGNAL_START = "2023-01-02"
SIGNAL_END = "2026-10-05"
PRICE_FROM = "2021-12-01"
PRICE_TO = "2026-10-31"
COST = 10e-4
K = 1.0
AB_SEED = 802
AB_BLOCK = 20.0
AB_BOOT = 2000

# S-428 已发表的数(动量+52w · 周 · k=1):窗口 2020-01-01→2026-09-25,宇宙 = 今天的幸存者 24 名。
S428_PUB = {"ann_ex_pct": 17.3, "t": 3.23, "oos_ann_ex_pct": 10.2, "oos_t": 1.62, "beta": 0.98,
            "rel_mdd_pct": -14.1, "worst_12m_pct": 0.8, "turnover_yr": 12.8}


def _t312():
    p = HERE / "t312_rebaseline.py"
    spec = importlib.util.spec_from_file_location("t312_rebaseline", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


t312 = _t312()


def _load_apparatus():
    return t312._load_apparatus()


# ── 取数(只读)────────────────────────────────────────────────────────────────
def cmd_fetch():
    if not URL or not KEY:
        raise SystemExit("缺 SUPABASE_URL / SUPABASE_KEY")
    base = URL.rstrip("/") + "/rest/v1/"

    # ① 成员:按时点 cap_pit24(每月一个名单)
    mem, off = [], 0
    while True:
        q = ("rpc/core_pit_members?p_start=2023-01-01&p_end=2026-10-01&p_n=24"
             "&order=m.asc,rnk.asc&limit=1000&offset=%d" % off)
        body, _h = t312._get(base + q, t312._hdr())
        rows = json.loads(body)
        mem.extend(rows)
        if len(rows) < 1000:
            break
        off += len(rows)
    MEMBERS_JSON.write_text(json.dumps(mem, ensure_ascii=False))
    months = sorted({r["m"] for r in mem})
    syms = sorted({r["symbol"] for r in mem})
    print("① 成员: %d 行, %d 个月(%s → %s), %d 个币" % (len(mem), len(months), months[0], months[-1], len(syms)),
          flush=True)

    def shard(sl):
        out, off = [], 0
        while True:
            q = ("asset_mcap_daily?select=symbol,d,price&symbol=in.(%s)"
                 "&and=(d.gte.%s,d.lte.%s)&order=symbol.asc,d.asc&limit=1000&offset=%d"
                 % (",".join(sl), PRICE_FROM, PRICE_TO, off))
            body, _h = t312._get(base + q, t312._hdr())
            rows = json.loads(body)
            out.extend(rows)
            if len(rows) < 1000:
                break
            off += len(rows)
        return out

    shards = [syms[i:i + 8] for i in range(0, len(syms), 8)]
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=8) as ex:
        parts = list(ex.map(shard, shards))
    rows = [r for p in parts for r in p]
    seen, uniq = set(), []
    for r in rows:
        k = (r["symbol"], r["d"])
        if k in seen:
            continue
        seen.add(k)
        uniq.append([r["symbol"], r["d"], r["price"]])
    uniq.sort(key=lambda r: (r[0], r[1]))
    meta = {"fetched_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            "price_from": PRICE_FROM, "price_to": PRICE_TO,
            "n_rows": len(uniq), "n_symbols": len({r[0] for r in uniq}),
            "seconds": round(time.time() - t0, 1)}
    PRICES_JSON.write_text(json.dumps({"meta": meta, "rows": uniq}, ensure_ascii=False))
    ds = sorted({r[1] for r in uniq})
    print("价格: %d 行, %d 币, %s → %s (%.0fs)" % (len(uniq), meta["n_symbols"], ds[0], ds[-1], meta["seconds"]),
          flush=True)
    print("→ %s / %s" % (MEMBERS_JSON.name, PRICES_JSON.name), flush=True)


# ── 面板 / 价格 ──────────────────────────────────────────────────────────────
def _load_panel():
    mem = json.loads(MEMBERS_JSON.read_text())
    pr = json.loads(PRICES_JSON.read_text())
    mem_by_month = {}
    for r in mem:
        mem_by_month.setdefault(r["m"], []).append(r["symbol"])
    df = pd.DataFrame(pr["rows"], columns=["symbol", "d", "price"])
    df["d"] = pd.to_datetime(df["d"])
    P = df.pivot(index="d", columns="symbol", values="price").sort_index()
    cal = pd.date_range(P.index.min(), P.index.max(), freq="D")
    Pcal = P.reindex(cal)
    # 日收益:每个币在自己的稀疏序列上算(缺天的那段涨幅记在价格回来的那天)——
    # 与 S-428 的 pct_change(fill_method=None) 在无缺口时逐字相同。
    rets = {}
    for s in P.columns:
        ser = P[s].dropna()
        rets[s] = ser / ser.shift(1) - 1.0
    R = pd.DataFrame(rets).reindex(cal)
    return mem, mem_by_month, Pcal, R, pr["meta"]


def _zmap(scores: dict) -> dict:
    """居中秩 → [-1, 1](与 S-428 `tilt_targets` 的 z 逐字同构:z=(2r-n-1)/(n-1));没有分数 → 0。"""
    out = {s: 0.0 for s in scores}
    sc = [s for s, v in scores.items() if v is not None and np.isfinite(v)]
    n = len(sc)
    if n < 2:
        return out
    vals = np.asarray([scores[s] for s in sc], dtype=float)
    r = pd.Series(vals).rank(method="average").to_numpy()
    for s, ri in zip(sc, r):
        out[s] = float((2.0 * ri - n - 1.0) / (n - 1.0))
    return out


# ── P 臂走步(t312 的框架,一字不改;只多铺几周以便首周有分)───────────────────
def _p_predictions():
    from scipy.stats import spearmanr
    from sklearn.linear_model import Ridge
    D = t312.load_cache(t312.CACHE)
    sym, dat, X, y = D["sym"], D["dat"], D["X"], D["y"]
    o = np.lexsort((sym, dat))
    sym, dat, X, y = sym[o], dat[o], X[o], y[o]
    weeks = t312._mondays("2022-06-06", t312.LAST_WEEK)     # 提前铺;对 2023-01-02 之后的周无影响
    starts = np.searchsorted(dat, np.array(weeks), side="left")
    ends = np.searchsorted(dat, np.array(weeks), side="right")
    ps, pd_, pv, ics, icw = [], [], [], [], []
    for wi, t in enumerate(weeks):
        lo, hi = int(starts[wi]), int(ends[wi])
        if hi <= lo:
            continue
        idx = np.arange(lo, hi)
        us = idx[np.isfinite(y[idx])]
        if us.size < t312.MIN_COINS:
            continue
        cut = int(np.searchsorted(dat, t312._minus30(t), side="left"))
        tr = np.flatnonzero(np.isfinite(y[:cut]))
        if tr.size < 100:
            continue
        ridge = Ridge(alpha=t312.ALPHA).fit(X[tr][:, t312.IDX_P], y[tr])
        p = ridge.predict(X[idx][:, t312.IDX_P])
        if t >= SIGNAL_START:                                  # 自检段 = t312 的同一批周
            ics.append(float(spearmanr(p[us - lo], y[us]).statistic))
            icw.append(t)
        ps.append(sym[idx]); pd_.append(dat[idx]); pv.append(p)
    psym = np.concatenate(ps); pdat = np.concatenate(pd_); pval = np.concatenate(pv)
    o2 = np.lexsort((pdat, psym))
    psym, pdat, pval = psym[o2], pdat[o2], pval[o2]
    u, st = np.unique(psym, return_index=True)
    en = np.append(st[1:], len(psym))
    per_sym = {str(s): (pdat[a:b], pval[a:b]) for s, a, b in zip(u, st, en)}
    return per_sym, {"ic_mean": float(np.mean(ics)) if ics else None,
                     "n_weeks": len(ics), "first": icw[0] if icw else None,
                     "last": icw[-1] if icw else None,
                     "published": 0.09628629002352945,
                     "delta": (float(np.mean(ics)) - 0.09628629002352945) if ics else None,
                     "prop_positive": float(np.mean(np.asarray(ics) > 0)) if ics else None}


# ── 三臂回测 ─────────────────────────────────────────────────────────────────
def _run_arm(days, R, all_syms, Pcal, target_fn):
    w = pd.Series(0.0, index=all_syms)
    pend, out, to = None, [], 0.0
    for d in days:
        r = R.loc[d].reindex(all_syms).fillna(0.0) if d in R.index else pd.Series(0.0, index=all_syms)
        rt = float((w * r).sum())
        if w.sum() > 0:
            w = w * (1 + r) / (1 + rt)
        if pend is not None:
            tt = pend[pend.index.isin(Pcal.columns)]
            keep = [s for s in tt.index if np.isfinite(Pcal.at[d, s])]
            tt = tt[keep]
            if tt.sum() > 0:
                tt = tt / tt.sum()
            c = float((tt - w.reindex(tt.index).fillna(0.0)).abs().sum())
            rt = (1 + rt) * (1 - c * COST) - 1
            to += c
            w = tt.reindex(all_syms).fillna(0.0)
            pend = None
        out.append(rt)
        if d.dayofweek == 0:
            tgt = target_fn(d)
            if tgt is not None and len(tgt) and tgt.sum() > 0:
                pend = tgt
    return pd.Series(out, index=days), to


def _stats(r_arm, r_hold, turnover, label):
    ex = r_arm - r_hold
    nav = (1 + r_arm).cumprod()
    navh = (1 + r_hold).cumprod()
    yrs = len(r_arm) / 365.0
    mdd = float((nav / nav.cummax() - 1).min())
    mddh = float((navh / navh.cummax() - 1).min())
    var_h = float(np.var(r_hold, ddof=1))
    beta = float(np.cov(r_arm, r_hold, ddof=1)[0, 1] / var_h) if var_h > 0 else None
    wk = ex.groupby(ex.index.to_period("W")).sum()
    mo = r_arm.groupby(r_arm.index.to_period("M")).apply(lambda x: float((1 + x).prod() - 1))
    mo_ex = ex.groupby(ex.index.to_period("M")).sum()
    return {
        "label": label,
        "cum": float((1 + r_arm).prod() - 1),
        "ann": float((1 + r_arm).prod() ** (365.0 / len(r_arm)) - 1),
        "mdd": mdd,
        "ann_ex_vs_hold": float(ex.mean() * 365),
        "te_ann_vs_hold": float(ex.std(ddof=1) * np.sqrt(365)) if len(ex) > 1 else None,
        "beta_vs_hold": beta,
        "ir_vs_hold": float(ex.mean() / ex.std(ddof=1) * np.sqrt(365)) if ex.std(ddof=1) > 0 else None,
        "t_weekly_ex": float(wk.mean() / wk.std(ddof=1) * np.sqrt(len(wk))) if wk.std(ddof=1) > 0 else None,
        "turnover_yr": float(turnover / yrs),
        "worst_month": float(mo.min()) if len(mo) else None,
        "worst_month_str": str(mo.idxmin()) if len(mo) else None,
        "worst_month_ex": float(mo_ex.min()) if len(mo_ex) else None,
        "hit_month_ex": float((mo_ex > 0).mean()) if len(mo_ex) else None,
        "n_days": int(len(r_arm)),
    }


def cmd_run():
    ap = _load_apparatus()
    mem, mem_by_month, Pcal, R, pmeta = _load_panel()
    all_syms = sorted({r["symbol"] for r in mem})
    print("① 面板: %d 行成员, %d 个月, %d 个币;价格 %s → %s" %
          (len(mem), len(mem_by_month), len(all_syms), Pcal.index.min().date(), Pcal.index.max().date()), flush=True)

    per_sym, sc = _p_predictions()
    print("自检: P 臂周 IC 均值 = %.6f(S-791 发表 %.6f,差 %.2e;%d 周 %s → %s)" %
          (sc["ic_mean"], sc["published"], sc["delta"], sc["n_weeks"], sc["first"], sc["last"]), flush=True)

    mondays = [pd.Timestamp(x) for x in t312._mondays(SIGNAL_START, SIGNAL_END)]
    days = pd.date_range(pd.Timestamp(SIGNAL_START), pd.Timestamp(SIGNAL_END) + pd.Timedelta(days=1), freq="D")

    # ── 每个周一的面板与两个信号 ────────────────────────────────────────────
    panel_of, m52_of, p_of = {}, {}, {}
    n_noscore_p, n_noscore_m = 0, 0
    for t in mondays:
        month = t.strftime("%Y-%m-01")
        members = [s for s in mem_by_month.get(month, []) if s in Pcal.columns]
        px = Pcal.loc[t] if t in Pcal.index else pd.Series(dtype=float)
        panel = [s for s in members if s in px.index and np.isfinite(px[s])]
        panel_of[t] = panel
        # M52:动量(14/28/90)+ 52 周高点,截面排名只在当周面板内做
        sc52 = {}
        if panel:
            sub = Pcal[panel]
            rk = lambda X: X.rank(axis=1, pct=True)
            mom = {n: sub / sub.shift(n) - 1.0 for n in (14, 28, 90)}
            mc = (rk(mom[14]) + rk(mom[28]) + rk(mom[90])) / 3.0
            h52 = sub / sub.rolling(365, min_periods=180).max()
            combo = (rk(mc) + rk(h52)) / 2.0
            row = combo.loc[t] if t in combo.index else pd.Series(dtype=float)
            for s in panel:
                v = row.get(s, np.nan)
                sc52[s] = float(v) if np.isfinite(v) else None
        m52_of[t] = sc52
        n_noscore_m += sum(1 for s in panel if sc52.get(s) is None)
        # P:该周之前(含当日)最后一次预测
        scp = {}
        for s in panel:
            ds, vals = per_sym.get(s, (None, None))
            if ds is None or len(ds) == 0:
                continue
            j = int(np.searchsorted(ds, t.strftime("%Y-%m-%d"), side="right")) - 1
            if j < 0:
                continue
            v = float(vals[j])
            if np.isfinite(v):
                scp[s] = v
        p_of[t] = scp
        n_noscore_p += len(panel) - len(scp)

    npanel = np.array([len(panel_of[t]) for t in mondays])
    print("面板规模: 平均 %.1f 个(最小 %d / 最大 %d);P 无分 %d 次(成员-周),M52 无分 %d 次" %
          (npanel.mean(), npanel.min(), npanel.max(), n_noscore_p, n_noscore_m), flush=True)

    def hold_target(t):
        p = panel_of.get(t, [])
        if not p:
            return None
        return pd.Series(1.0 / len(p), index=p)

    def tilt_target(scores):
        def f(t):
            p = panel_of.get(t, [])
            if not p:
                return None
            z = _zmap({s: scores.get(t, {}).get(s) for s in p})
            w = pd.Series({s: (1.0 / len(p)) * (1.0 + K * z[s]) for s in p})
            w = w.clip(lower=0.0)
            if w.sum() <= 0:
                return None
            return w / w.sum()
        return f

    r_hold, to_h = _run_arm(days, R, all_syms, Pcal, hold_target)
    r_m52, to_m = _run_arm(days, R, all_syms, Pcal, tilt_target(m52_of))
    r_p, to_p = _run_arm(days, R, all_syms, Pcal, tilt_target(p_of))

    st_h = _stats(r_hold, r_hold, to_h, "HOLD")
    st_m = _stats(r_m52, r_hold, to_m, "M52")
    st_p = _stats(r_p, r_hold, to_p, "P")

    # ── 两半(按周数对半)─────────────────────────────────────────────────────
    mid = len(mondays) // 2
    cut = mondays[mid]
    halves = {"h1": [d for d in days if d < cut], "h2": [d for d in days if d >= cut]}
    hs = {}
    for hk, dd in halves.items():
        hs[hk] = {"label": hk, "n_weeks": (mid if hk == "h1" else len(mondays) - mid),
                  "start": str(dd[0].date()) if dd else None, "end": str(dd[-1].date()) if dd else None,
                  "M52_ann_ex": float((r_m52[dd] - r_hold[dd]).mean() * 365),
                  "P_ann_ex": float((r_p[dd] - r_hold[dd]).mean() * 365),
                  "M52_cum": float((1 + r_m52[dd]).prod() - 1), "P_cum": float((1 + r_p[dd]).prod() - 1),
                  "HOLD_cum": float((1 + r_hold[dd]).prod() - 1)}

    # ── 判据 ────────────────────────────────────────────────────────────────
    ab = ap.ab_test(r_m52.to_numpy(), r_p.to_numpy(), mean_block=AB_BLOCK, n_boot=AB_BOOT, seed=AB_SEED)
    j_i = bool(st_p["cum"] >= st_m["cum"])
    j_ii = bool(ab.get("p_b_le_a") is not None and ab["p_b_le_a"] <= 0.10)
    j_iii = bool(hs["h1"]["P_ann_ex"] >= hs["h1"]["M52_ann_ex"] and hs["h2"]["P_ann_ex"] >= hs["h2"]["M52_ann_ex"])
    j_iv = bool(st_p["mdd"] >= st_m["mdd"] - 0.02)

    rows = ([{"d": str(d.date()), "arm": "HOLD", "ret": float(r_hold[d])} for d in days] +
            [{"d": str(d.date()), "arm": "M52", "ret": float(r_m52[d])} for d in days] +
            [{"d": str(d.date()), "arm": "P", "ret": float(r_p[d])} for d in days])
    fp_arms = ap.content_fingerprint(rows, ["d", "arm", "ret"])
    fp_mem = ap.content_fingerprint([{"m": r["m"], "symbol": r["symbol"], "rnk": r["rnk"]} for r in mem],
                                    ["m", "symbol", "rnk"])
    fp_px = ap.content_fingerprint([{"symbol": s, "d": d, "price": p} for s, d, p in
                                    json.loads(PRICES_JSON.read_text())["rows"]], ["symbol", "d", "price"])

    res = {
        "task": "T-324", "ledger": "S-802",
        "framework": {
            "panel": "core_pit_members(p_n=24) —— 按时点 cap_pit24,每月一个名单",
            "weight": "w = (1/N)·(1 + k·z),k = 1;z = 居中秩映射到 [-1,1];无分 z = 0",
            "schedule": "周一收盘出信号、次日收盘成交;成本 10bp × 换手;三臂同日程同成本",
            "window": [SIGNAL_START, SIGNAL_END], "cost_bp": 10,
            "P_arm": "t312_rebaseline.py 的 P 臂(Ridge alpha=10,只用 d' < t-30 的行训练,训练集全宇宙)",
            "M52_arm": "S-428 原文:动量组合(14/28/90 的秩均值)与 52 周高点的秩均值",
            "ab_test": {"mean_block": AB_BLOCK, "n_boot": AB_BOOT, "seed": AB_SEED},
        },
        "self_check": sc,
        "panel_stats": {"n_members_rows": len(mem), "n_months": len(mem_by_month),
                        "n_symbols": len(all_syms), "avg_panel_size": float(npanel.mean()),
                        "min_panel_size": int(npanel.min()), "max_panel_size": int(npanel.max()),
                        "member_weeks_without_P_score": int(n_noscore_p),
                        "member_weeks_without_M52_score": int(n_noscore_m),
                        "price_meta": pmeta},
        "arms": {"HOLD": st_h, "M52": st_m, "P": st_p},
        "halves": hs,
        "ab_test_P_vs_M52": ab,
        "judgments": {
            "i_P_cum_ge_M52_cum": {"pass": j_i, "P_cum": st_p["cum"], "M52_cum": st_m["cum"],
                                   "diff": st_p["cum"] - st_m["cum"]},
            "ii_ab_p_le_010": {"pass": j_ii, "p_b_le_a": ab.get("p_b_le_a"),
                               "ci95_log_diff": ab.get("ci95_log_diff"),
                               "cum_a_M52": ab.get("cum_a"), "cum_b_P": ab.get("cum_b")},
            "iii_both_halves_excess": {"pass": j_iii, "h1": hs["h1"], "h2": hs["h2"]},
            "iv_mdd_not_2pp_deeper": {"pass": j_iv, "P_mdd": st_p["mdd"], "M52_mdd": st_m["mdd"],
                                      "diff_pp": (st_p["mdd"] - st_m["mdd"]) * 100},
            "verdict_all_pass": bool(j_i and j_ii and j_iii and j_iv),
        },
        "compare_S428_published": {
            "published": S428_PUB,
            "recomputed_M52_here": {"ann_ex_pct": st_m["ann_ex_vs_hold"] * 100,
                                    "t_weekly": st_m["t_weekly_ex"], "beta": st_m["beta_vs_hold"],
                                    "mdd_pct": st_m["mdd"] * 100, "turnover_yr": st_m["turnover_yr"],
                                    "worst_month_pct": st_m["worst_month"] * 100},
            "why_differ": ["宇宙:S-428 用今天的幸存者 24 名;这里用按时点 cap_pit24(含死币的时点名单)",
                           "窗口:S-428 是 2020-01-01→2026-09-25;这里是 2023-01-02→2026-10-05",
                           "基准:S-428 的基准 = 合格币等权(≥180 天历史);这里是当周面板全体等权",
                           "S-428 的 mom_combo 用 14/28/90 的秩均值再取秩,52 周高点 = 365 自然日滚动最高(min 180)",
                           "本卡的价格源是 asset_mcap_daily(① 的同一出处),不是 Binance 公共日线"],
        },
        "fingerprints": {"arms_daily": fp_arms, "members": fp_mem, "prices": fp_px},
    }
    RESULTS.write_text(json.dumps(res, ensure_ascii=False, indent=2, default=float))
    for k in ("HOLD", "M52", "P"):
        s = res["arms"][k]
        print("%-5s cum=%+.4f ann_ex=%+.4f beta=%.4f te=%.4f turn=%.2f mdd=%.4f worst_mo=%+.4f" %
              (k, s["cum"], s["ann_ex_vs_hold"], s["beta_vs_hold"] or float("nan"),
               s["te_ann_vs_hold"] or float("nan"), s["turnover_yr"], s["mdd"], s["worst_month"]), flush=True)
    print("判据:", json.dumps(res["judgments"], ensure_ascii=False)[:600], flush=True)
    print("→", RESULTS.name, flush=True)


if __name__ == "__main__":
    _a = argparse.ArgumentParser()
    _a.add_argument("cmd", choices=["fetch", "run"])
    _args = _a.parse_args()
    if _args.cmd == "fetch":
        cmd_fetch()
    else:
        cmd_run()
