#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T-295 — squeeze/flush 的 SQL 内核对账(S-777 干净口径)

三层:
  A 参考 legacy : t242.detect 原样(S-768 ① 原口径)
  B 参考 clean  : t242.detect + S-777 两条【日级】守卫
  C SQL 复算     : 照 t295_crowding_events.sql 的语义独立实现(不复用 detect 的判定)+ 同两条守卫

对账目标:C 与 B 逐条(日期, 合约)相同;不一致时逐条说清差在哪一格。
不改 t242(那是别人的参考实现);参考自己重写一遍 detect_clean,只加两条守卫。

用法:python3 t295_event_audit.py
"""
import os
import json
import time
import importlib.util
import urllib.request

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "t295_audit.json")
CACHE = "/Volumes/CometCloudAI/cometcloud-local/research/t242/cache"

# ── 常数(照抄 S-726 / t242_crowding_setups.py 37–53 行,一个都不扫)──────────
FUND_WIN = 7
FUND_ANN_MULT = 3 * 365
PCTL_HI = 0.90
PCTL_LO = 0.10
ATR_N = 14
ATR_K = 2.0
QV_WIN = 20
QV_MULT = 3.0
MIN_AGE_DAYS = 180
DEDUPE_DAYS = 10
EPS = 1e-12                  # f7「相等」判定容差(pandas rolling 与 SQL avg 的末位差)
# 前向表钉死的平局规则(见报告 §4):参考实现 strict / SQL 端 quant 时两者逐条一致
PINNED_MODE = "strict"
D_TO = "2026-11-04"          # T-242 / T-289 参考跑数的截止日
N_AUDIT = 10                 # 每类抽 N 个事件做逐格审计
MIN_BARS = 40                # detect 第 216 行

log_t0 = time.time()


def log(*a):
    print("[%6.1fs]" % (time.time() - log_t0), *a, flush=True)


# ── A. 参考面板(直接复用 t242 的实现,保证是「参考」而不是重写)─────────────
def load_t242():
    spec = importlib.util.spec_from_file_location(
        "t242", os.path.join(HERE, "t242_crowding_setups.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def build_reference(t242):
    pbv, meta = t242.load_pbv()
    log("pbv rows", len(pbv), "meta", json.dumps(meta)[:160])
    # ⚠ 陷阱 E1:load_cached() 优先读 .csv.gz → perp_bv_pairs 的空 kind 变 NaN
    #   (NaN is not None)→ 宇宙从 653 掉到 649。这里【故意】读 .json 原件,
    #   复现参考跑数用的就是 .json(2026-11-05 16:03 生成的 .csv.gz 当时还不存在)。
    pairs_json = json.load(open(os.path.join(CACHE, "perp_bv_pairs.json")))["rows"]
    pairs = pd.DataFrame(pairs_json)
    funding = pd.read_csv(os.path.join(CACHE, "v_funding_daily.csv.gz"))
    funding["d"] = pd.to_datetime(funding["d"])
    funding["funding_rate"] = pd.to_numeric(funding["funding_rate"], errors="coerce")
    log("pairs rows", len(pairs), "funding rows", len(funding))
    pan = t242.build_panels(pbv, pairs, funding, None)
    kind = dict(zip(pairs["symbol"], pairs["kind"]))
    dead = {s: (None if pd.isna(dd) else dd)
            for s, dd in zip(pairs["symbol"], pairs["dead_from"])}
    uni = np.array([(kind.get(s) == "coin") or (kind.get(s) is None and dead.get(s) is not None)
                    for s in pan["syms"]])
    log("universe", int(uni.sum()), "of", len(uni))
    return t242, pan, uni


# ── B. 参考:detect + S-777 两条日级守卫 ───────────────────────────────────
def detect_clean(pan, universe_mask, off=0, guards=True):
    """t242.detect 的逐字副本,只在【事件日】上加两条守卫:
      ① d 日 f7 为空 ⇒ 不是事件(缺失 ≠ 「最低分位」);
      ② ATR14 ≤ 0 或 20 日均 qv ≤ 0 ⇒ 不是事件(门槛恒为 0 ⇒ 恒真命中)。
    守卫位置照 T-297 的 t297_clean.py:在 pct/q20/thr 的有限性检查之后、年龄/收益/成交量之前。
    """
    ev = {"flush": [], "squeeze": []}
    n_sym = pan["n_sym"]
    age_ok = pan["ordmat"] - pan["first_ord"][:, None] >= MIN_AGE_DAYS
    for i in range(n_sym):
        if not universe_mask[i]:
            continue
        k = int(np.isfinite(pan["C"][i]).sum())
        if k < MIN_BARS:
            continue
        d = pan["dates"].iloc[i]
        c = pan["C"][i]
        qv = pan["QV"][i]
        ret = pan["ret"][i]
        atr = pan["atr"][i]
        q20 = pan["qv20"][i]
        pct = pan["pct"][i]
        f7 = pan["f7"][i]
        ords = pan["ordmat"][i]
        thr = ATR_K * atr / np.roll(c, 1)
        cand_f, cand_s = [], []
        for j in range(1, k):
            jj = j + off
            if jj < 0 or jj >= k - 1:
                continue
            if not np.isfinite(pct[jj]) or not np.isfinite(q20[jj]) or not np.isfinite(thr[jj]):
                continue
            if guards:
                if not np.isfinite(f7[jj]):
                    continue
                if not (atr[jj] > 0) or not (q20[jj] > 0):
                    continue
            if not np.isfinite(ords[jj]) or not (age_ok[i, jj]):
                continue
            if ret[jj] is None or not np.isfinite(ret[jj]):
                continue
            if qv[jj] < QV_MULT * q20[jj]:
                continue
            if pct[jj] >= PCTL_HI and ret[jj] <= -thr[jj]:
                cand_f.append(jj)
            elif pct[jj] <= PCTL_LO and ret[jj] >= thr[jj]:
                cand_s.append(jj)
        for name, cand in (("flush", cand_f), ("squeeze", cand_s)):
            last = None
            for jj in cand:
                if last is not None and (ords[jj] - ords[last]) < DEDUPE_DAYS:
                    continue
                ev[name].append({"sym_i": i, "bar": jj, "d": str(d.iloc[jj])[:10],
                                 "ord": float(ords[jj]), "kind": name})
                last = jj
    return ev


# ── C. SQL 语义(照 t295_crowding_events.sql 的 S1–S12 独立实现)────────────
def pct_from_f7(f7, k_fund, mode="eps"):
    """S5:扩张中位秩。分母 = 更早的行数(不是非空样本数);NaN 进分母不进分子。

    三种「平局」规则 —— 之所以要分三种,是因为 f7 的末位取决于求和结合顺序:
    参考实现用 pandas rolling(7).mean()(增量 + 补偿),SQL/本脚本用 7 行显式求和
    (顺序累加),两者在个别行上差 1 ULP。而 pct 的阈值是 0.10,一条事件的取舍
    完全由这个末位决定(实测 HYPE 2026-01-27:strict 0.10124 vs eps 0.09917)。

      strict —— 照 t242 detect() 的严格 `<` 与 `==`(定义之口的规则)
      eps    —— 平局用容差 1e-12(把 1 ULP 的差吸收成「并列」)
      quant  —— 先把 f7 四舍五入到 12 位小数再比(网格化 ⇒ 与结合顺序无关)
    """
    pct = np.full(len(f7), np.nan)
    vals = np.round(f7, 12) if mode == "quant" else f7
    for j in range(1, k_fund):
        v = vals[j]
        earlier = vals[:j]
        with np.errstate(all="ignore"):
            if mode == "eps":
                less = np.sum(earlier < v - EPS)
                eq = np.sum(np.abs(earlier - v) <= EPS)
            else:
                less = np.sum(earlier < v)
                eq = np.sum(earlier == v)
        pct[j] = (less + 0.5 * eq) / max(j, 1)
    return pct


def ref_panel_pct(pan, mode):
    """参考面板的 pct 换成另一种平局规则(其余中间量一字不动)。
    参考面板的 f7 来自 t242 的 pandas rolling;这里只重算 pct。
    尾部(资金费数据起点之后)照参考实现填 0.0 —— 参考用矩阵法,av 为 NaN 时
    less_eq = 0 ⇒ pct = 0(S-777 点名的「缺失被当成最低分位」的机制来源)。"""
    out = np.full_like(pan["pct"], np.nan)
    for i in range(pan["n_sym"]):
        k_fund = int(np.isfinite(pan["F"][i]).sum())
        if k_fund < 9:                       # 参考实现:k < FUND_WIN+2 整行 continue
            continue
        row = pct_from_f7(pan["f7"][i], k_fund, mode)
        out[i, :k_fund] = row[:k_fund]
        out[i, 0] = 0.0
    return out


def sql_panel(i, pan, pct_mode=None):
    """按 SQL 语义算出单个合约的全部中间量(行号 j = 0..k−1)。
    与 t295_crowding_events.sql 的 S1–S8 一一对应。"""
    C = pan["C"][i]
    k = int(np.isfinite(C).sum())
    h, l, qv, f = pan["H"][i], pan["L"][i], pan["QV"][i], pan["F"][i]
    # S6 TR
    c_prev = np.full(k, np.nan)
    c_prev[1:] = C[:k - 1]
    with np.errstate(all="ignore"):
        tr = np.nanmax(np.stack([h[:k] - l[:k],
                                  np.abs(h[:k] - c_prev),
                                  np.abs(l[:k] - c_prev)]), axis=0)
    # S7 ATR14:pandas rolling(14).mean().shift(1) ⇒ 行 j−14..j−1
    atr = np.full(k, np.nan)
    for j in range(ATR_N, k):
        w = tr[j - ATR_N:j]
        if np.isfinite(w).sum() == ATR_N:
            atr[j] = w.mean()
    # S8 qv20:行 j−20..j−1
    qv20 = np.full(k, np.nan)
    for j in range(QV_WIN, k):
        w = qv[:k][j - QV_WIN:j]
        if np.isfinite(w).sum() == QV_WIN:
            qv20[j] = w.mean()
    # S2/S3/S4 f7:只在前 k_fund 行上有定义;窗口缺一天 ⇒ NULL
    k_fund = int(np.isfinite(f).sum())
    f7 = np.full(k, np.nan)
    if k_fund >= FUND_WIN + 2:
        for j in range(FUND_WIN, k_fund):
            w = f[:k_fund][j - FUND_WIN:j]
            if np.isfinite(w).sum() == FUND_WIN:
                f7[j] = w.mean() * FUND_ANN_MULT
    # S5 pct:只在面板前 k_fund 行上有定义
    pct = pct_from_f7(f7, k_fund, pct_mode or PINNED_MODE)
    ret = np.full(k, np.nan)
    cc = C[:k]
    with np.errstate(all="ignore"):
        ret[1:] = cc[1:] / cc[:-1] - 1.0
    return dict(k=k, k_fund=k_fund, tr=tr, atr=atr, qv20=qv20, f7=f7, pct=pct, ret=ret)


def sql_detect(pan, uni_mask, guards=True, pct_mode="eps"):
    """照 t295_crowding_events.sql 的 S1–S12 逐步实现(不复用 detect 的判定)。
    语义(与 .sql 文件逐条对应):
      S1  面板 = perp_bv_daily 的日线行,按 d 排序,行号 j = 0..k−1
      S2  k_fund = 面板行里【有资金费观测】的行数(grid 对齐,不是原始行数)
      S3  截断:只有前 k_fund 行携带资金费(第 k_fund 行之后一律 NULL)—— 与 python 的 F[i,:k] 同义
      S4  f7 = 1095 × mean(funding, 行 j−7..j−1),7 行都要有数(缺一 ⇒ NULL)
      S5  pct = (#更早行 f7 更小 + 0.5×#相等) / greatest(j, 1);只在 j < k_fund 上有定义
      S6  tr = max(h−l, |h−c_{j−1}|, |l−c_{j−1}|)
      S7  atr14 = mean(tr, 行 j−14..j−1)(止于 d−1)
      S8  qv20 = mean(qv, 行 j−20..j−1)
      S9  便宜门槛 qv ≥ 3 × qv20
      S10 年龄 ≥ 180 天;面板行数 k ≥ 40
      S11 【S-777 守卫】f7 为空 ⇒ 不是事件;atr ≤ 0 或 qv20 ≤ 0 ⇒ 不是事件
      S12 去重:同合约同类 10 天内只计第一次
    """
    n_sym = pan["n_sym"]
    syms = pan["syms"]
    events = []
    for i in range(n_sym):
        if not uni_mask[i]:
            continue
        C = pan["C"][i]
        k = int(np.isfinite(C).sum())
        if k < MIN_BARS:                                 # S10
            continue
        d = pan["dates"].iloc[i]
        qv = pan["QV"][i]
        ords = pan["ordmat"][i]
        first_ord = pan["first_ord"][i]
        sp = sql_panel(i, pan, pct_mode)
        if sp["k_fund"] < FUND_WIN + 2:      # python 第 159–160 行:整行 continue
            continue
        atr, qv20, f7, pct, ret = sp["atr"], sp["qv20"], sp["f7"], sp["pct"], sp["ret"]
        # S9/S10/S11 候选
        cand = []
        for j in range(1, k - 1):                       # 行 0 与最后一行不判
            age = ords[j] - first_ord
            if age < MIN_AGE_DAYS:
                continue
            if not (np.isfinite(qv20[j]) and np.isfinite(atr[j])):
                continue
            if not (np.isfinite(C[j - 1]) and C[j - 1] != 0 and np.isfinite(C[j])):
                continue
            r = ret[j]
            if not np.isfinite(r):
                continue
            if qv[j] < QV_MULT * qv20[j]:
                continue
            thr = ATR_K * atr[j] / C[j - 1]
            if not np.isfinite(thr):
                continue
            if guards:
                # S-777 守卫 ①:d 日 f7 为空 ⇒ 不是事件
                if not np.isfinite(f7[j]):
                    continue
                # S-777 守卫 ②:ATR14 ≤ 0 或 20 日均 qv ≤ 0 ⇒ 不是事件
                if not (atr[j] > 0) or not (qv20[j] > 0):
                    continue
            kind = None
            if pct[j] >= PCTL_HI and r <= -thr:
                kind = "flush"
            elif pct[j] <= PCTL_LO and r >= thr:
                kind = "squeeze"
            if kind:
                cand.append((kind, j, d.iloc[j], float(pct[j]), float(r),
                             float(thr), float(qv[j] / qv20[j]), float(ords[j])))
        # S12 去重:距上一个【已计入】≥ 10 个日历日
        for kind in ("flush", "squeeze"):
            sub = [c for c in cand if c[0] == kind]
            sub.sort(key=lambda c: c[2])
            last_kept = None
            for c in sub:
                if last_kept is not None and (c[7] - last_kept) < DEDUPE_DAYS:
                    continue
                events.append(dict(kind=kind, symbol=syms[i], d=str(c[2])[:10],
                                   bar=c[1], fund_pct=c[3], ret=c[4],
                                   atr_thr=c[5], qv_mult=c[6]))
                last_kept = c[7]
    return events


# ── D. 库侧取数(只读) ─────────────────────────────────────────────────────
def db_get(path, rng=None):
    url = os.environ["SUPABASE_URL"].rstrip("/") + "/rest/v1/" + path
    key = os.environ["SUPABASE_KEY"]
    req = urllib.request.Request(url)
    req.add_header("apikey", key)
    req.add_header("Authorization", "Bearer " + key)
    if rng:
        req.add_header("Range", rng)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def db_rows(symbol, d_to):
    out = []
    rng = 0
    while True:
        r = db_get("perp_bv_daily?symbol=eq.%s&d=lte.%s&order=d.asc"
                   % (symbol, d_to), rng="0-999")
        if not r:
            break
        out.extend([{"d": x["d"], "c": float(x["c"]), "qv": float(x["qv"])} for x in r])
        if len(r) < 1000:
            break
        rng += 1000
    return out


# ── E. 主流程 ──────────────────────────────────────────────────────────────
def evset(evs, pan):
    out = []
    for e in evs:
        sym = e.get("symbol") or pan["syms"][e["sym_i"]]
        out.append((e["d"], sym))
    return sorted(out)


def main():
    t242 = load_t242()
    t242, pan, uni = build_reference(t242)

    ref_l = t242.detect(pan, uni, off=0)
    ref_c = detect_clean(pan, uni, off=0, guards=True)
    sql_l = sql_detect(pan, uni, guards=False)
    sql_c = sql_detect(pan, uni, guards=True)

    L = {k: evset(ref_l[k], pan) for k in ("squeeze", "flush")}
    C = {k: evset(ref_c[k], pan) for k in ("squeeze", "flush")}
    SL = {k: evset([e for e in sql_l if e["kind"] == k], pan) for k in ("squeeze", "flush")}
    SC = {k: evset([e for e in sql_c if e["kind"] == k], pan) for k in ("squeeze", "flush")}
    for nm, dd in (("legacy", L), ("clean", C), ("sql_legacy", SL), ("sql_clean", SC)):
        log(nm, "squeeze", len(dd["squeeze"]), "flush", len(dd["flush"]))
    same_l = (L["squeeze"] == SL["squeeze"] and L["flush"] == SL["flush"])
    same_c = (C["squeeze"] == SC["squeeze"] and C["flush"] == SC["flush"])
    log("legacy identical:", same_l, "| clean identical:", same_c)

    # ── 变体扫描:三种平局规则(strict/eps/quant)× 参考/sql × 守卫 ──────
    variants = {}
    for mode in ("strict", "eps", "quant"):
        pmode = dict(pan)
        pmode["pct"] = ref_panel_pct(pan, mode)
        rl = t242.detect(pmode, uni, off=0)
        rc = detect_clean(pmode, uni, off=0, guards=True)
        sl = sql_detect(pan, uni, guards=False, pct_mode=mode)
        sc = sql_detect(pan, uni, guards=True, pct_mode=mode)
        Rl = {k: evset(rl[k], pan) for k in ("squeeze", "flush")}
        Rc = {k: evset(rc[k], pan) for k in ("squeeze", "flush")}
        Sl = {k: evset([e for e in sl if e["kind"] == k], pan) for k in ("squeeze", "flush")}
        Sc = {k: evset([e for e in sc if e["kind"] == k], pan) for k in ("squeeze", "flush")}
        variants[mode] = dict(
            ref_legacy=dict(squeeze=len(Rl["squeeze"]), flush=len(Rl["flush"])),
            ref_clean=dict(squeeze=len(Rc["squeeze"]), flush=len(Rc["flush"])),
            sql_legacy=dict(squeeze=len(Sl["squeeze"]), flush=len(Sl["flush"])),
            sql_clean=dict(squeeze=len(Sc["squeeze"]), flush=len(Sc["flush"])),
            identical_clean=(Rc["squeeze"] == Sc["squeeze"] and Rc["flush"] == Sc["flush"]),
            identical_legacy=(Rl["squeeze"] == Sl["squeeze"] and Rl["flush"] == Sl["flush"]),
            only_in_ref_clean=[list(x) for x in sorted(set(Rc["squeeze"]) - set(Sc["squeeze"]))[:5]],
            only_in_sql_clean=[list(x) for x in sorted(set(Sc["squeeze"]) - set(Rc["squeeze"]))[:5]],
        )
        log("mode", mode, json.dumps(variants[mode], ensure_ascii=False, default=str)[:420])

    diffs = {}
    for tag, a, b in (("legacy_squeeze", L["squeeze"], SL["squeeze"]),
                      ("legacy_flush", L["flush"], SL["flush"]),
                      ("clean_squeeze", C["squeeze"], SC["squeeze"]),
                      ("clean_flush", C["flush"], SC["flush"])):
        only_a = sorted(set(a) - set(b))
        only_b = sorted(set(b) - set(a))
        diffs[tag] = dict(only_in_ref=only_a[:20], only_in_sql=only_b[:20],
                          n_only_in_ref=len(only_a), n_only_in_sql=len(only_b))
        log(tag, "only_ref", len(only_a), only_a[:4], "| only_sql", len(only_b), only_b[:4])

    # ── C1. 语义差定位:对「多出来的那些事件」逐条打印参考面板上的对应格 ────
    def cell(sym, dstr):
        i = pan["syms"].index(sym)
        k = int(np.isfinite(pan["C"][i]).sum())
        dts = [str(x)[:10] for x in pan["dates"].iloc[i][:k]]
        if dstr not in dts:
            return None
        j = dts.index(dstr)
        sp = sql_panel(i, pan)
        f7v = pan["f7"][i][j]
        pv = pan["pct"][i][j]
        return dict(symbol=sym, d=dstr, bar=j, k=k, k_fund=sp["k_fund"],
                    ref_f7=(float(f7v) if np.isfinite(f7v) else None),
                    sql_f7=(float(sp["f7"][j]) if np.isfinite(sp["f7"][j]) else None),
                    ref_pct=(float(pv) if np.isfinite(pv) else None),
                    sql_pct=(float(sp["pct"][j]) if np.isfinite(sp["pct"][j]) else None),
                    atr=float(pan["atr"][i][j]) if np.isfinite(pan["atr"][i][j]) else None,
                    qv20=float(pan["qv20"][i][j]) if np.isfinite(pan["qv20"][i][j]) else None,
                    ret=float(pan["ret"][i][j]) if np.isfinite(pan["ret"][i][j]) else None)
    diag = dict(only_in_sql_samples=[cell(sym, dstr) for dstr, sym in
                                     sorted(set(SL["squeeze"]) - set(L["squeeze"]))[:8]],
                only_in_ref_samples=[cell(sym, dstr) for dstr, sym in
                                     sorted(set(L["squeeze"]) - set(SL["squeeze"]))[:8]])
    for k2, v2 in diag.items():
        log(k2, json.dumps(v2[:3], ensure_ascii=False, default=float))

    # ── C2. 逐格审计:10 squeeze + 10 flush(干净口径)────────────────────
    picks = []
    for name in ("squeeze", "flush"):
        evs = ref_c[name]
        step = max(1, len(evs) // N_AUDIT)
        picks.extend(evs[::step][:N_AUDIT])
    rows = []
    for e in picks:
        i, j = e["sym_i"], e["bar"]
        sym = pan["syms"][i]
        f7_row = pan["f7"][i]
        pct_row = pan["pct"][i]
        k = int(np.isfinite(pan["C"][i]).sum())
        sp = sql_panel(i, pan)
        c_prev = pan["C"][i][j - 1]
        ret = pan["ret"][i][j]
        thr = ATR_K * pan["atr"][i][j] / c_prev
        age = pan["ordmat"][i][j] - pan["first_ord"][i]
        rows.append(dict(
            kind=e["kind"],
            symbol=sym, d=e["d"], bar0=int(j), k=int(k),
            f7=float(f7_row[j]) if np.isfinite(f7_row[j]) else None,
            pct=float(pct_row[j]) if np.isfinite(pct_row[j]) else None,
            pct_sql=(float(sp["pct"][j]) if np.isfinite(sp["pct"][j]) else None),
            f7_sql=(float(sp["f7"][j]) if np.isfinite(sp["f7"][j]) else None),
            atr=float(pan["atr"][i][j]) if np.isfinite(pan["atr"][i][j]) else None,
            qv20=float(pan["qv20"][i][j]) if np.isfinite(pan["qv20"][i][j]) else None,
            qv=float(pan["QV"][i][j]),
            qv_mult=float(pan["QV"][i][j] / pan["qv20"][i][j]),
            ret=float(ret), atr_thr=float(thr), age_days=float(age),
            f7_is_nan=not np.isfinite(f7_row[j]),
            pct_is_zero=(np.isfinite(pct_row[j]) and pct_row[j] == 0.0),
        ))
    n_f7nan = sum(1 for r in rows if r["f7_is_nan"])
    n_pct0 = sum(1 for r in rows if r["pct_is_zero"])
    n_pctdiff = sum(1 for r in rows if r["pct"] is not None and r["pct_sql"] is not None
                     and abs(r["pct"] - r["pct_sql"]) > 1e-12)
    log("audited", len(rows), "events | f7=NaN:", n_f7nan, "| pct==0.0:", n_pct0,
        "| pct ref≠sql:", n_pctdiff)

    # ── C3. 守卫剔掉了哪些 ──────────────────────────────────────────────
    def ev_row(e):
        i, j = e["sym_i"], e["bar"]
        return dict(sym=pan["syms"][i], d=e["d"],
                    f7_nan=not np.isfinite(pan["f7"][i][j]),
                    atr_le_0=not (pan["atr"][i][j] > 0),
                    qv20_le_0=not (pan["qv20"][i][j] > 0))
    full_c = [ev_row(e) for e in ref_c["squeeze"]] + [ev_row(e) for e in ref_c["flush"]]
    full_l = [ev_row(e) for e in ref_l["squeeze"]] + [ev_row(e) for e in ref_l["flush"]]
    log("legacy events", len(full_l), "| f7 NaN", sum(1 for x in full_l if x["f7_nan"]),
        "| atr<=0", sum(1 for x in full_l if x["atr_le_0"]),
        "| qv20<=0", sum(1 for x in full_l if x["qv20_le_0"]))
    log("clean events", len(full_c), "| f7 NaN", sum(1 for x in full_c if x["f7_nan"]),
        "| atr<=0", sum(1 for x in full_c if x["atr_le_0"]),
        "| qv20<=0", sum(1 for x in full_c if x["qv20_le_0"]))
    dropped = sorted(set((x["sym"], x["d"]) for x in full_l) -
                     set((x["sym"], x["d"]) for x in full_c))
    log("dropped by guards:", len(dropped), dropped[:6])

    # ── D. 库侧对账(前 6 个事件合约)────────────────────────────────────
    db_checks = []
    for r in rows[:6]:
        sym = r["symbol"]
        dbr = db_rows(sym, D_TO)
        i = pan["syms"].index(sym)
        panel_rows = []
        for j in range(int(np.isfinite(pan["C"][i]).sum())):
            panel_rows.append((str(pan["dates"].iloc[i][j])[:10],
                               float(pan["C"][i][j]), float(pan["QV"][i][j])))
        db_map = {str(x["d"])[:10]: (x["c"], x["qv"]) for x in dbr}
        only_panel = [x for x in panel_rows if x[0] not in db_map]
        only_db = [x for x in db_map if x not in {p[0] for p in panel_rows}]
        diff_c = diff_qv = 0
        for dd, c, q in panel_rows:
            if dd in db_map:
                if abs(db_map[dd][0] - c) > 1e-12:
                    diff_c += 1
                if abs(db_map[dd][1] - q) > 1e-6:
                    diff_qv += 1
        db_checks.append(dict(symbol=sym, d=r["d"], panel_bars=len(panel_rows),
                              db_bars=len(dbr), only_in_panel=len(only_panel),
                              only_in_db=len(only_db), close_mismatch=diff_c,
                              qv_mismatch=diff_qv))
        log("db check", sym, "panel", len(panel_rows), "db", len(dbr),
            "only_panel", len(only_panel), "only_db", len(only_db),
            "c≠", diff_c, "qv≠", diff_qv)

    out = dict(
        task="T-295",
        generated_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        reference=dict(legacy_squeeze=len(L["squeeze"]), legacy_flush=len(L["flush"]),
                       clean_squeeze=len(C["squeeze"]), clean_flush=len(C["flush"]),
                       universe=int(uni.sum()), panel_symbols=int(pan["n_sym"])),
        sql_semantics=dict(legacy_squeeze=len(SL["squeeze"]), legacy_flush=len(SL["flush"]),
                           clean_squeeze=len(SC["squeeze"]), clean_flush=len(SC["flush"]),
                           identical_legacy=same_l, identical_clean=same_c),
        diffs=diffs,
        diagnosis=diag,
        audited=rows,
        audited_pct_mismatch=n_pctdiff,
        dropped_by_guards=dropped,
        guards_legacy=dict(f7_nan=sum(1 for x in full_l if x["f7_nan"]),
                           atr_le_0=sum(1 for x in full_l if x["atr_le_0"]),
                           qv20_le_0=sum(1 for x in full_l if x["qv20_le_0"])),
        guards_clean=dict(f7_nan=sum(1 for x in full_c if x["f7_nan"]),
                          atr_le_0=sum(1 for x in full_c if x["atr_le_0"]),
                          qv20_le_0=sum(1 for x in full_c if x["qv20_le_0"])),
        db_reconciliation=db_checks,
        tie_rule_variants=variants,
        pinned_mode=PINNED_MODE,
    )
    with open(OUT, "w") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1, default=float)
    log("wrote", OUT)
    print("=" * 78)
    print("legacy  参考 squeeze/flush:", len(L["squeeze"]), len(L["flush"]),
          "| SQL:", len(SL["squeeze"]), len(SL["flush"]), "| 逐条相同:", same_l)
    print("clean   参考 squeeze/flush:", len(C["squeeze"]), len(C["flush"]),
          "| SQL:", len(SC["squeeze"]), len(SC["flush"]), "| 逐条相同:", same_c)
    print("守卫剔掉:", len(dropped), dropped[:6])
    for mode, v in variants.items():
        print("平局规则 %-7s 参考(legacy/clean) squeeze %s/%s flush %s/%s | SQL %s/%s %s/%s | clean 逐条相同 %s"
              % (mode, v["ref_legacy"]["squeeze"], v["ref_clean"]["squeeze"],
                 v["ref_legacy"]["flush"], v["ref_clean"]["flush"],
                 v["sql_legacy"]["squeeze"], v["sql_clean"]["squeeze"],
                 v["sql_legacy"]["flush"], v["sql_clean"]["flush"], v["identical_clean"]))
    for r in rows:
        print("  %-7s %-14s %s bar=%4d f7=%s pct=%s atr=%s qv20=%s qv_mult=%.2f ret=%.4f thr=%.4f age=%d"
              % (r["kind"], r["symbol"], r["d"], r["bar0"],
                 ("%9.4f" % r["f7"]) if r["f7"] is not None else "     None",
                 ("%7.4f" % r["pct"]) if r["pct"] is not None else "   None",
                 ("%8.5f" % r["atr"]) if r["atr"] is not None else "    None",
                 ("%12.1f" % r["qv20"]) if r["qv20"] is not None else "       None",
                 r["qv_mult"], r["ret"], r["atr_thr"], int(r["age_days"])))


if __name__ == "__main__":
    main()
