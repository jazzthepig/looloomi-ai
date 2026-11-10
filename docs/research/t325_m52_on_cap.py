#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T-325 / S-803 —— 现任 ② 规则(M52:S-428 动量 + 52 周高点)叠在 ① **真实的持有方式**
(`cap_pit24` 市值加权)上,对 ① 臂本身还挣不挣。

预注册(REFUTATION_LEDGER.md S-803)原文照抄在报告 `T-325_m52_on_cap.md` 开头。
纪律:只读、不入库、不改代码。

框架(照 S-803「写死」段):
  ① 面板 = 按时点 `cap_pit24`(RPC `core_pit_members`,p_n=24,每月一个名单,含死币)。
  CAP 臂  = `core_pit_daily` 的权重公式(前一日市值加权、单币 ≤ 40%、每日再平衡、不扣成本)
            —— 先与库里 `core_variants_daily` 的 arm='cap_pit24' **逐日对**(报最大差),对不上先停。
  CAP×M52 = w_i ∝ cap_i ·(1 + k·z_i),k = 1,z = 当周面板内 M52 打分的居中秩 → [-1,1];
            z 每周一收盘算、周二生效;归一;**不设额外上限**(与现行 `cap_a1_u` 一致)。
  成本 10bp × 换手,两臂同扣;窗口 2023-01-02 → 2026-10-05;两半按周数对半。

用法:
  python3 t325_m52_on_cap.py fetch   # 拉 ① 成员 + 价格/市值 + 库里的 cap_pit24 臂(只读)
  python3 t325_m52_on_cap.py run     # 自检 + 两臂回测 + 判据 → t325_results.json
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
ROOT = HERE.parents[1]

MEMBERS_JSON = HERE / "_t325_members.json"
PRICES_JSON = HERE / "_t325_prices.json"
ARM_JSON = HERE / "_t325_arm.json"
RESULTS = HERE / "t325_results.json"

URL = os.environ.get("SUPABASE_URL")
KEY = os.environ.get("SUPABASE_KEY")

SIGNAL_START = "2023-01-02"
SIGNAL_END = "2026-10-05"
MEMBER_START = "2022-06-01"
MEMBER_END = "2026-10-01"
PRICE_FROM = "2021-11-01"
PRICE_TO = "2026-10-31"
COST = 10e-4
K = 1.0
CAP_LIMIT = 0.40
AB_SEED = 803
AB_BLOCK = 20.0
AB_BOOT = 2000

# S-802 已发表的数(lane-a T-324,等权 HOLD 基准):M52 对**等权**持有的年化超额。
S802_PUB = {"M52_cum": 1.148, "M52_ann_ex_vs_equalweight_hold": 3.61, "M52_beta": 0.946,
            "M52_te": 0.097, "M52_mdd": -0.661, "M52_turnover_yr": 13.6,
            "HOLD_cum": 0.771, "HOLD_mdd": -0.716, "HOLD_turnover_yr": 3.7}


# ── REST(只读)───────────────────────────────────────────────────────────────
def _hdr(extra=None):
    h = {"apikey": KEY, "Authorization": "Bearer " + KEY}
    if extra:
        h.update(extra)
    return h


def _get(url, headers, tries=5, timeout=180):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8"), dict(r.headers)
        except urllib.error.HTTPError as e:
            last = "HTTP %s: %s" % (e.code, e.read().decode("utf-8", "replace")[:300])
            if e.code in (400, 404):
                raise SystemExit("REST 错误 %s" % last)
            time.sleep(1.5 * (i + 1))
        except Exception as e:  # noqa: BLE001
            last = repr(e)
            time.sleep(1.5 * (i + 1))
    raise SystemExit("REST 取数失败:%s(%s)" % (url[:160], last))


def _load_apparatus():
    p = ROOT / "src" / "data" / "evaluation" / "apparatus.py"
    spec = importlib.util.spec_from_file_location("apparatus", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── 取数(只读)───────────────────────────────────────────────────────────────
def cmd_fetch():
    if not URL or not KEY:
        raise SystemExit("缺 SUPABASE_URL / SUPABASE_KEY")
    base = URL.rstrip("/") + "/rest/v1/"

    # ① 成员:按时点 cap_pit24(每月一个名单)
    mem, off = [], 0
    while True:
        q = ("rpc/core_pit_members?p_start=%s&p_end=%s&p_n=24"
             "&order=m.asc,rnk.asc&limit=1000&offset=%d" % (MEMBER_START, MEMBER_END, off))
        body, _h = _get(base + q, _hdr())
        rows = json.loads(body)
        mem.extend(rows)
        if len(rows) < 1000:
            break
        off += len(rows)
    MEMBERS_JSON.write_text(json.dumps(mem, ensure_ascii=False))
    months = sorted({r["m"] for r in mem})
    syms = sorted({r["symbol"] for r in mem})
    print("① 成员: %d 行, %d 个月(%s → %s), %d 个币" %
          (len(mem), len(months), months[0], months[-1], len(syms)), flush=True)

    # 价格 + 市值(asset_mcap_daily = ① 的同一出处)
    def shard(sl):
        out, off = [], 0
        while True:
            q = ("asset_mcap_daily?select=symbol,d,price,mcap&symbol=in.(%s)"
                 "&and=(d.gte.%s,d.lte.%s)&order=symbol.asc,d.asc&limit=1000&offset=%d"
                 % (",".join(sl), PRICE_FROM, PRICE_TO, off))
            body, _h = _get(base + q, _hdr())
            rows = json.loads(body)
            out.extend(rows)
            if len(rows) < 1000:
                break
            off += len(rows)
        return out

    shards = [syms[i:i + 6] for i in range(0, len(syms), 6)]
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=8) as ex:
        parts = list(ex.map(shard, shards))
    seen, uniq = set(), []
    for r in parts:
        for x in r:
            k = (x["symbol"], x["d"])
            if k in seen:
                continue
            seen.add(k)
            uniq.append([x["symbol"], x["d"], x["price"], x["mcap"]])
    uniq.sort(key=lambda r: (r[0], r[1]))
    meta = {"fetched_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            "price_from": PRICE_FROM, "price_to": PRICE_TO,
            "n_rows": len(uniq), "n_symbols": len({r[0] for r in uniq}),
            "seconds": round(time.time() - t0, 1)}
    PRICES_JSON.write_text(json.dumps({"meta": meta, "rows": uniq}, ensure_ascii=False))
    print("价格+市值: %d 行, %d 币, %s → %s (%.0fs)" %
          (len(uniq), meta["n_symbols"], PRICE_FROM, PRICE_TO, meta["seconds"]), flush=True)

    # 库里的 ① 臂(core_variants_daily,arm='cap_pit24')—— 自检的对照物
    arm, off = [], 0
    while True:
        q = ("core_variants_daily?select=d,ret,nav&arm=eq.cap_pit24"
             "&order=d.asc&limit=1000&offset=%d" % off)
        body, _h = _get(base + q, _hdr())
        rows = json.loads(body)
        arm.extend(rows)
        if len(rows) < 1000:
            break
        off += len(rows)
    ARM_JSON.write_text(json.dumps(arm, ensure_ascii=False))
    print("库里 cap_pit24 臂: %d 行 %s → %s" %
          (len(arm), arm[0]["d"] if arm else "-", arm[-1]["d"] if arm else "-"), flush=True)
    print("→ %s / %s / %s" % (MEMBERS_JSON.name, PRICES_JSON.name, ARM_JSON.name), flush=True)


# ── 面板 / 权重 ──────────────────────────────────────────────────────────────
def _load_panel():
    mem = json.loads(MEMBERS_JSON.read_text())
    pr = json.loads(PRICES_JSON.read_text())
    mem_by_month = {}
    for r in mem:
        mem_by_month.setdefault(r["m"], []).append(r["symbol"])
    df = pd.DataFrame(pr["rows"], columns=["symbol", "d", "price", "mcap"])
    df["d"] = pd.to_datetime(df["d"])
    cal = pd.date_range(df["d"].min(), df["d"].max(), freq="D")
    P = df.pivot(index="d", columns="symbol", values="price").reindex(cal)
    MC = df.pivot(index="d", columns="symbol", values="mcap").reindex(cal)
    return mem, mem_by_month, P, MC, pr["meta"]


def _cap_weights(dates, mem_by_month, P, MC):
    """照 `core_pit_daily` 的 SQL 逐日算:前一日市值加权、单币 ≤ 40%(超出按比例分给上限以下的币)、
    当日没有连续两日价格的成员不计入、其余重归一。返回 {d: (w1 dict, r dict)}。"""
    out = {}
    for d in dates:
        mems = mem_by_month.get(d.strftime("%Y-%m-01"), [])
        if not mems:
            continue
        prev = d - pd.Timedelta(days=1)
        rr, pm = {}, {}
        for s in mems:
            if s not in P.columns:
                continue
            p0 = P.at[prev, s] if prev in P.index else np.nan
            p1 = P.at[d, s]
            mc1 = MC.at[prev, s] if prev in MC.index else np.nan
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
        excess = sum(max(w - CAP_LIMIT, 0.0) for w in w0.values())
        rest = sum(w for w in w0.values() if w < CAP_LIMIT)
        w1 = {s: (CAP_LIMIT if w0[s] >= CAP_LIMIT else w0[s] * (1 + excess / rest if rest > 0 else 1.0))
              for s in w0}
        out[d] = (w1, rr)
    return out


def _zmap(scores):
    """居中秩 → [-1, 1](与 S-428 / T-324 的 `tilt_targets` 的 z 逐字同构);没有分数 → 0。"""
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


def _m52_scores(mondays, panel_of, P):
    """S-428 原文:动量组合(14/28/90 的截面秩均值)与 52 周高点的截面秩均值,再取居中秩 → [-1,1]。"""
    sc = {}
    for t in mondays:
        panel = panel_of.get(t, [])
        if not panel:
            continue
        sub = P[panel]
        rk = lambda X: X.rank(axis=1, pct=True)  # noqa: E731
        mom = {n: sub / sub.shift(n) - 1.0 for n in (14, 28, 90)}
        mc = (rk(mom[14]) + rk(mom[28]) + rk(mom[90])) / 3.0
        h52 = sub / sub.rolling(365, min_periods=180).max()
        combo = (rk(mc) + rk(h52)) / 2.0
        row = combo.loc[t] if t in combo.index else pd.Series(dtype=float)
        sc[t] = {s: (float(row[s]) if np.isfinite(row.get(s, np.nan)) else None) for s in panel}
    return sc


def _stats(r_arm, r_bench, turnover, label, weight_path=None):
    ex = r_arm - r_bench
    nav = (1 + r_arm).cumprod()
    navh = (1 + r_bench).cumprod()
    yrs = len(r_arm) / 365.0
    mdd = float((nav / nav.cummax() - 1).min())
    var_h = float(np.var(r_bench, ddof=1))
    beta = float(np.cov(r_arm, r_bench, ddof=1)[0, 1] / var_h) if var_h > 0 else None
    mo = r_arm.groupby(r_arm.index.to_period("M")).apply(lambda x: float((1 + x).prod() - 1))
    mo_ex = ex.groupby(ex.index.to_period("M")).sum()
    return {
        "label": label,
        "cum": float((1 + r_arm).prod() - 1),
        "ann": float((1 + r_arm).prod() ** (365.0 / len(r_arm)) - 1),
        "mdd": mdd,
        "ann_ex_vs_bench": float(ex.mean() * 365),
        "te_ann_vs_bench": float(ex.std(ddof=1) * np.sqrt(365)) if len(ex) > 1 else None,
        "beta_vs_bench": beta,
        "ir_vs_bench": float(ex.mean() / ex.std(ddof=1) * np.sqrt(365)) if ex.std(ddof=1) > 0 else None,
        "turnover_yr": float(turnover / yrs),
        "worst_month": float(mo.min()) if len(mo) else None,
        "worst_month_str": str(mo.idxmin()) if len(mo) else None,
        "hit_month_ex": float((mo_ex > 0).mean()) if len(mo_ex) else None,
        "n_days": int(len(r_arm)),
    }


# ── 日频回测(日程 A:① 真实 = 每日再平衡)────────────────────────────────────
def _cap_limit(w0):
    """照 `core_pit_daily` 的单币上限规则:超出 p_cap 的部分按比例分给上限以下的币。"""
    excess = sum(max(w - CAP_LIMIT, 0.0) for w in w0.values())
    rest = sum(w for w in w0.values() if w < CAP_LIMIT)
    return {s: (CAP_LIMIT if w0[s] >= CAP_LIMIT else w0[s] * (1 + excess / rest if rest > 0 else 1.0))
            for s in w0}


def _run_daily(dates, capw, z_by_week, bench_key):
    """两臂同日频:`capw` 给每日的 (cap 权重, 当日收益);`z_by_week` 给每周一 → 居中秩。
    bench_key='cap' ⇒ CAP 臂;`tilt` ⇒ CAP×M52(w ∝ cap·(1+z),不设额外上限);
    `tilt_cap` ⇒ 同上但**再套单币 40% 上限**(分离「解除上限」这一效应)。
    返回 (日收益 Series, 换手总额, 每日权重 dict)。"""
    all_syms = sorted({s for d in dates for s in capw.get(d, ({}, {}))[0]})
    w_prev = {s: 0.0 for s in all_syms}
    out, turn = [], 0.0
    wpath = {}
    z_active = {s: 0.0 for s in all_syms}
    for d in dates:
        if d not in capw:
            out.append(0.0)
            wpath[d] = dict(w_prev)
            continue
        w_cap, rr = capw[d]
        if bench_key in ("tilt", "tilt_cap"):
            raw = {s: w_cap.get(s, 0.0) * (1.0 + z_active.get(s, 0.0)) for s in w_cap}
            tot = sum(raw.values())
            w = {s: v / tot for s, v in raw.items()} if tot > 0 else {}
            if bench_key == "tilt_cap" and w:
                w = _cap_limit(w)
        else:
            w = dict(w_cap)
        rt = float(sum(w.get(s, 0.0) * rr[s] for s in rr))
        c = float(sum(abs(w.get(s, 0.0) - w_prev.get(s, 0.0)) for s in set(w) | set(w_prev)))
        turn += c
        rt = (1 + rt) * (1 - c * COST) - 1
        out.append(rt)
        wpath[d] = dict(w)
        w_prev = dict(w)
        if d.dayofweek == 0:                       # 周一收盘出信号 → 周二生效
            z_next = z_by_week.get(d)
            if z_next is not None:
                z_active = dict(z_next)
    return pd.Series(out, index=dates), turn, wpath


# ── 周频回测(日程 B:照 S-802 字面,敏感性)────────────────────────────────────
def _run_weekly(days, target_of, all_syms, P):
    """照 T-324 的 `_run_arm`:周一收盘出目标、次日收盘成交,持有期内权重随收益漂移。"""
    R = pd.DataFrame({s: P[s].dropna().pipe(lambda x: x / x.shift(1) - 1.0) for s in P.columns}).reindex(P.index)
    w = pd.Series(0.0, index=all_syms)
    pend, out, to = None, [], 0.0
    for d in days:
        r = R.loc[d].reindex(all_syms).fillna(0.0) if d in R.index else pd.Series(0.0, index=all_syms)
        rt = float((w * r).sum())
        if w.sum() > 0:
            w = w * (1 + r) / (1 + rt)
        if pend is not None:
            tt = pend[pend.index.isin(P.columns)]
            keep = [s for s in tt.index if np.isfinite(P.at[d, s])]
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
            tgt = target_of(d)
            if tgt is not None and len(tgt) and tgt.sum() > 0:
                pend = tgt
    return pd.Series(out, index=days), to


# ── 主流程 ──────────────────────────────────────────────────────────────────
def cmd_run():
    ap = _load_apparatus()
    mem, mem_by_month, P, MC, pmeta = _load_panel()
    arm_db = json.loads(ARM_JSON.read_text())
    all_syms = sorted({r["symbol"] for r in mem})
    print("① 面板: %d 行成员, %d 个月, %d 个币;价格 %s → %s" %
          (len(mem), len(mem_by_month), len(all_syms), P.index.min().date(), P.index.max().date()), flush=True)

    days = pd.date_range(pd.Timestamp(SIGNAL_START), pd.Timestamp(SIGNAL_END) + pd.Timedelta(days=1), freq="D")
    # 权重路径要往前多铺一段(换手要用前一天的权重)
    warm = pd.date_range(pd.Timestamp(SIGNAL_START) - pd.Timedelta(days=45),
                          pd.Timestamp(SIGNAL_END) + pd.Timedelta(days=1), freq="D")
    capw = _cap_weights(warm, mem_by_month, P, MC)
    print("权重: %d 天算出(cap_pit24 公式)" % len(capw), flush=True)

    # ── 自检:CAP 臂(毛)vs 库里的 core_variants_daily cap_pit24 ──────────────
    mine = pd.Series({d: float(sum(w.get(s, 0.0) * rr[s] for s in rr))
                       for d, (w, rr) in capw.items() if d in set(days)}).sort_index()
    db = pd.Series({r["d"]: float(r["ret"]) for r in arm_db if r.get("ret") is not None}).sort_index()
    db.index = pd.to_datetime(db.index)
    idx = db.index.intersection(mine.index)
    diff = (mine.loc[idx] - db.loc[idx]) if len(idx) else pd.Series(dtype=float)
    panel_check = {
        "n_days_mine": int(len(mine)), "n_days_db": int(len(db)),
        "overlap_days": int(len(idx)),
        "overlap_from": str(idx[0].date()) if len(idx) else None,
        "overlap_to": str(idx[-1].date()) if len(idx) else None,
        "max_abs_diff": float(diff.abs().max()) if len(diff) else None,
        "mean_abs_diff": float(diff.abs().mean()) if len(diff) else None,
        "n_days_exact_1e-9": int((diff.abs() < 1e-9).sum()) if len(diff) else 0,
        "corr": float(np.corrcoef(mine.loc[idx], db.loc[idx])[0, 1]) if len(idx) > 2 else None,
        "note": "我的重算(前一日市值加权 + 单币 ≤40% + 日再平衡)vs 库里 core_variants_daily 的 "
                "cap_pit24 臂(毛);差 0 = 成员/市值源/日历全对",
    }
    print("自检: 重算 %d 天 vs 库 %d 天,重叠 %d 天(%s→%s)最大差 %.3g" %
          (panel_check["n_days_mine"], panel_check["n_days_db"], panel_check["overlap_days"],
           panel_check["overlap_from"], panel_check["overlap_to"],
           panel_check["max_abs_diff"] or float("nan")), flush=True)
    if not panel_check["max_abs_diff"] is not None or panel_check["max_abs_diff"] > 1e-6:
        res = {"task": "T-325", "ledger": "S-803", "status": "STOPPED_AT_SELF_CHECK",
               "panel_check": panel_check}
        RESULTS.write_text(json.dumps(res, ensure_ascii=False, indent=2, default=float))
        raise SystemExit("自检不过(最大差 %.3g > 1e-6)—— 停,不往下算" % (panel_check["max_abs_diff"] or -1))

    # ── 每周面板与 M52 打分 ──────────────────────────────────────────────────
    mondays = [d for d in pd.date_range(pd.Timestamp(SIGNAL_START) - pd.Timedelta(days=7),
                                        pd.Timestamp(SIGNAL_END), freq="W-MON")]
    panel_of = {}
    for t in mondays:
        members = mem_by_month.get(t.strftime("%Y-%m-01"), [])
        px = P.loc[t] if t in P.index else pd.Series(dtype=float)
        panel_of[t] = [s for s in members if s in px.index and np.isfinite(px[s])]
    m52_of = _m52_scores(mondays, panel_of, P)
    z_by_week = {}
    for t in mondays:
        p = panel_of.get(t, [])
        if not p:
            continue
        z_by_week[t] = _zmap({s: m52_of.get(t, {}).get(s) for s in p})
    npanel = np.array([len(panel_of[t]) for t in mondays if t in panel_of])
    n_noscore = sum(1 for t in mondays for s in panel_of.get(t, []) if m52_of.get(t, {}).get(s) is None)
    print("面板: 平均 %.1f 个(最小 %d / 最大 %d);M52 无分 %d 个成员-周" %
          (npanel.mean(), npanel.min(), npanel.max(), n_noscore), flush=True)

    # ── 日频两臂 ────────────────────────────────────────────────────────────
    r_cap, to_cap, w_cap_path = _run_daily(days, capw, z_by_week, "cap")
    r_tilt, to_tilt, w_tilt_path = _run_daily(days, capw, z_by_week, "tilt")
    r_tiltcap, to_tiltcap, w_tiltcap_path = _run_daily(days, capw, z_by_week, "tilt_cap")
    st_cap = _stats(r_cap, r_cap, to_cap, "CAP(cap_pit24 市值加权)")
    st_tilt = _stats(r_tilt, r_cap, to_tilt, "CAP×M52")
    st_tiltcap = _stats(r_tiltcap, r_cap, to_tiltcap, "CAP×M52(仍套 40% 上限)")

    # ── 前向基率(给 scenarios 用)—— ① 篮子(CAP 臂的 nav)相对 200 日线的位置 ──
    nav_cap = (1 + r_cap).cumprod()
    ma200 = nav_cap.rolling(200, min_periods=100).mean()
    dist200 = (nav_cap / ma200 - 1.0).dropna()
    last_day = P.index.max()
    btc_last_mcap = (float(P.at[last_day, "BTC"])
                     if "BTC" in P.columns and np.isfinite(P.at[last_day, "BTC"]) else None)
    try:
        body, _h = _get(URL.rstrip("/") + "/rest/v1/ohlcv_daily?select=d,close&symbol=eq.BTC"
                                     "&order=d.desc&limit=5", _hdr())
        ohl = json.loads(body)
        btc_ohlcv_last = ohl[0] if ohl else None
    except SystemExit:
        btc_ohlcv_last = None
    base_rates = {
        "dist_200_gt_0_share": float((dist200 > 0).mean()) if len(dist200) else None,
        "n_days": int(len(dist200)),
        "dist_200_median": float(dist200.median()) if len(dist200) else None,
        "btc_last_mcap_price": btc_last_mcap,
        "btc_last_date": str(last_day.date()),
        "btc_ohlcv_last": btc_ohlcv_last,
        "note": "dist_200 = CAP 臂 nav / 其 200 日均线 − 1(自算,给 scenarios 的概率定基率用;"
                "情景文件里的 state:dist_200 由库里的 state_daily 结算,口径可能略有差别",
    }

    # 逐年超额(对 CAP)—— 读法用
    yr = {}
    for y in sorted({d.year for d in days}):
        dd = [d for d in days if d.year == y]
        yr[str(y)] = {
            "CAP_cum": float((1 + r_cap[dd]).prod() - 1),
            "tilt_cum": float((1 + r_tilt[dd]).prod() - 1),
            "tilt_cap_cum": float((1 + r_tiltcap[dd]).prod() - 1),
            "tilt_ex_ann": float((r_tilt[dd] - r_cap[dd]).mean() * 365),
            "tilt_cap_ex_ann": float((r_tiltcap[dd] - r_cap[dd]).mean() * 365),
            "n_days": len(dd),
        }

    btc_cap = np.array([w_cap_path.get(d, {}).get("BTC", 0.0) for d in days])
    btc_tilt = np.array([w_tilt_path.get(d, {}).get("BTC", 0.0) for d in days])
    btc_tiltcap = np.array([w_tiltcap_path.get(d, {}).get("BTC", 0.0) for d in days])
    btc_shift = {"mean_pp": float((btc_tilt - btc_cap).mean() * 100),
                 "mean_cap_pct": float(btc_cap.mean() * 100),
                 "mean_tilt_pct": float(btc_tilt.mean() * 100),
                 "tilt_cap_mean_pp": float((btc_tiltcap - btc_cap).mean() * 100),
                 "tilt_cap_mean_pct": float(btc_tiltcap.mean() * 100),
                 "n_days_btc_in_cap": int((btc_cap > 0).sum()),
                 "n_days_btc_in_tilt": int((btc_tilt > 0).sum())}

    # ── 周频敏感性(日程 B:照 S-802 字面)──────────────────────────────────
    def _cap_weekly_target(t):
        d = t - pd.Timedelta(days=1)          # 用周一之前最后一个有数的日子(≈周末)的市值
        w, _rr = capw.get(d, ({}, {}))
        return pd.Series(w) if w else None

    def _tilt_weekly_target(t):
        p = panel_of.get(t, [])
        if not p:
            return None
        d = t - pd.Timedelta(days=1)
        wc, _rr = capw.get(d, ({}, {}))
        if not wc:
            return None
        z = z_by_week.get(t, {})
        raw = {s: wc.get(s, 0.0) * (1.0 + K * z.get(s, 0.0)) for s in wc}
        tot = sum(raw.values())
        return pd.Series({s: v / tot for s, v in raw.items()}) if tot > 0 else None

    wdays = pd.date_range(pd.Timestamp(SIGNAL_START), pd.Timestamp(SIGNAL_END) + pd.Timedelta(days=1), freq="D")
    r_wcap, to_wcap = _run_weekly(wdays, _cap_weekly_target, all_syms, P)
    r_wtilt, to_wtilt = _run_weekly(wdays, _tilt_weekly_target, all_syms, P)
    st_wcap = _stats(r_wcap, r_wcap, to_wcap, "CAP(周频)")
    st_wtilt = _stats(r_wtilt, r_wcap, to_wtilt, "CAP×M52(周频)")

    # ── 两半(按周数对半)─────────────────────────────────────────────────────
    wk_mondays = [d for d in mondays if pd.Timestamp(SIGNAL_START) <= d <= pd.Timestamp(SIGNAL_END)]
    mid = len(wk_mondays) // 2
    cut = wk_mondays[mid]
    halves = {}
    for hk, dd in (("h1", [d for d in days if d < cut]), ("h2", [d for d in days if d >= cut])):
        halves[hk] = {"start": str(dd[0].date()), "end": str(dd[-1].date()),
                      "CAP_ann_ex": 0.0,
                      "tilt_ann_ex": float((r_tilt[dd] - r_cap[dd]).mean() * 365),
                      "CAP_cum": float((1 + r_cap[dd]).prod() - 1),
                      "tilt_cum": float((1 + r_tilt[dd]).prod() - 1),
                      "w_CAP_ann_ex": 0.0,
                      "w_tilt_ann_ex": float((r_wtilt[dd] - r_wcap[dd]).mean() * 365),
                      "w_CAP_cum": float((1 + r_wcap[dd]).prod() - 1),
                      "w_tilt_cum": float((1 + r_wtilt[dd]).prod() - 1)}

    # ── 判据(S-803 原文)─────────────────────────────────────────────────────
    def _judge(rc, rt, prefix):
        """prefix='tilt'(日程 A)或 'w_tilt'(日程 B)。"""
        ab = ap.ab_test(rc.to_numpy(), rt.to_numpy(), mean_block=AB_BLOCK, n_boot=AB_BOOT, seed=AB_SEED)
        sc, st = _stats(rc, rc, 0.0, "CAP"), _stats(rt, rc, 0.0, "tilt")
        j_i = bool(st["cum"] >= sc["cum"])
        j_ii = bool(ab.get("p_b_le_a") is not None and ab["p_b_le_a"] <= 0.10)
        h1, h2 = halves["h1"], halves["h2"]
        j_iii = bool(h1[prefix + "_ann_ex"] > 0 and h2[prefix + "_ann_ex"] > 0)
        j_iv = bool(st["mdd"] >= sc["mdd"] - 0.02)
        return ab, {"i_cum_ge": {"pass": j_i, "CAP_cum": sc["cum"], "tilt_cum": st["cum"],
                                 "diff": st["cum"] - sc["cum"]},
                    "ii_ab_p_le_010": {"pass": j_ii, "p_b_le_a": ab.get("p_b_le_a"),
                                       "ci95_log_diff": ab.get("ci95_log_diff"),
                                       "cum_a_CAP": ab.get("cum_a"), "cum_b_tilt": ab.get("cum_b")},
                    "iii_both_halves_ex_pos": {"pass": j_iii, "h1": h1, "h2": h2},
                    "iv_mdd_not_2pp_deeper": {"pass": j_iv, "tilt_mdd": st["mdd"], "CAP_mdd": sc["mdd"],
                                             "diff_pp": (st["mdd"] - sc["mdd"]) * 100},
                    "verdict_all_pass": bool(j_i and j_ii and j_iii and j_iv)}

    ab_daily, j_daily = _judge(r_cap, r_tilt, "tilt")
    ab_weekly, j_weekly = _judge(r_wcap, r_wtilt, "w_tilt")
    # 探索性:同一倾斜但**仍套 40% 单币上限** —— 把「解除上限」这一效应从「M52 选股」里剥出来
    ab_tc = ap.ab_test(r_cap.to_numpy(), r_tiltcap.to_numpy(), mean_block=AB_BLOCK, n_boot=AB_BOOT,
                        seed=AB_SEED)
    ex_tc = {
        "note": "探索性分解(非预注册判据):CAP×M52 但倾斜后仍套单币 40% 上限",
        "arms": {"CAPxM52_with_cap": st_tiltcap},
        "ab_test_vs_CAP": {"p_b_le_a": ab_tc.get("p_b_le_a"), "ci95_log_diff": ab_tc.get("ci95_log_diff"),
                           "cum_a_CAP": ab_tc.get("cum_a"), "cum_b_tiltcap": ab_tc.get("cum_b")},
        "btc_weight": {"mean_pct": float(btc_tiltcap.mean() * 100)},
    }

    res = {
        "task": "T-325", "ledger": "S-803",
        "framework": {
            "panel": "core_pit_members(p_n=24) —— 按时点 cap_pit24,每月一个名单(含死币)",
            "CAP_arm": "core_pit_daily 的权重公式:前一日市值加权、单币 ≤ 40%、每日再平衡(毛收益)",
            "tilt_arm": "w ∝ cap_i·(1 + k·z_i),k=1,z = M52 居中秩([-1,1]),周一收盘算、周二生效;归一;不设额外上限",
            "schedule_primary": "日程 A(日频):两臂都用每日再平衡的市值权重;z 每周更新",
            "schedule_sensitivity": "日程 B(周频):照 S-802 字面,两臂每周一重算、周二成交、持有期内漂移",
            "window": [SIGNAL_START, SIGNAL_END], "cost_bp": 10,
            "ab_test": {"mean_block": AB_BLOCK, "n_boot": AB_BOOT, "seed": AB_SEED},
        },
        "panel_check": panel_check,
        "panel_stats": {"n_members_rows": len(mem), "n_months": len(mem_by_month),
                        "n_symbols": len(all_syms), "avg_panel_size": float(npanel.mean()),
                        "min_panel_size": int(npanel.min()), "max_panel_size": int(npanel.max()),
                        "member_weeks_without_M52_score": int(n_noscore), "price_meta": pmeta},
        "daily": {"arms": {"CAP": st_cap, "CAPxM52": st_tilt, "CAPxM52_with_cap": st_tiltcap},
                  "halves": halves, "yearly": yr,
                  "ab_test": ab_daily, "judgments": j_daily, "btc_weight_shift": btc_shift},
        "weekly_sensitivity": {"arms": {"CAP": st_wcap, "CAPxM52": st_wtilt},
                               "ab_test": ab_weekly, "judgments": j_weekly},
        "exploratory_cap_limit_split": ex_tc,
        "forward_base_rates": base_rates,
        "compare_S802_published": {
            "published": S802_PUB,
            "note": "S-802 是对**等权** HOLD 的超额(2023-01-02→2026-10-05);这里是市值加权的 CAP 基准",
        },
        "fingerprints": {
            "arms_daily": ap.content_fingerprint(
                [{"d": str(d.date()), "arm": a, "ret": float(r)} for a, r in
                 (("CAP", r_cap), ("CAPxM52", r_tilt)) for d, r in r.items()], ["d", "arm", "ret"]),
            "members": ap.content_fingerprint(
                [{"m": r["m"], "symbol": r["symbol"], "rnk": r["rnk"]} for r in mem], ["m", "symbol", "rnk"]),
        },
    }
    RESULTS.write_text(json.dumps(res, ensure_ascii=False, indent=2, default=float))
    for tag, a in (("日频", res["daily"]["arms"]), ("周频", res["weekly_sensitivity"]["arms"])):
        for k, s in a.items():
            print("%-4s %-22s cum=%+.4f ann_ex=%+.4f beta=%.4f te=%.4f turn=%.2f mdd=%.4f worst_mo=%+.4f" %
                  (tag, k, s["cum"], s["ann_ex_vs_bench"], s["beta_vs_bench"] or float("nan"),
                   s["te_ann_vs_bench"] or float("nan"), s["turnover_yr"], s["mdd"], s["worst_month"]),
                  flush=True)
    print("逐年超额(对 CAP):", json.dumps(yr, ensure_ascii=False), flush=True)
    print("前向基率:", json.dumps(base_rates, ensure_ascii=False), flush=True)
    print("日频判据:", json.dumps(j_daily, ensure_ascii=False)[:700], flush=True)
    print("周频判据:", json.dumps(j_weekly, ensure_ascii=False)[:700], flush=True)
    print("BTC 权重:", json.dumps(btc_shift, ensure_ascii=False), flush=True)
    print("→", RESULTS.name, flush=True)


if __name__ == "__main__":
    _a = argparse.ArgumentParser()
    _a.add_argument("cmd", choices=["fetch", "run"])
    _args = _a.parse_args()
    if _args.cmd == "fetch":
        cmd_fetch()
    else:
        cmd_run()
