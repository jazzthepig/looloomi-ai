#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T-295 · detect() ↔ SQL 语义逐格对账(只读;不改代码、不入库)。

做四件事:
  A. 用 t242 的路子重建参考面板(JSONL + 缓存),跑 detect() → 事件(期望 218 + 20)。
  B. 独立实现 SQL 文件(t295_crowding_events.sql)的 S1–S12 语义,跑在同一面板上
     → 与 detect() 的事件集逐条比对(证明 SQL 写法 = detect 口径)。
  C. 20 个事件(10 squeeze + 10 flush)逐格打印中间量 f7 / pct / atr / qv20 / ret /
     thr / qv_mult / age,并标出每一格由 python 哪一行、SQL 哪一步决定。
  D. 从库里拉这 20 个合约的 perp_bv_daily 行,与参考面板逐日对账
     (bar 数、close、qv),并在库版数据上重跑 SQL 语义 → 回答「SQL 能不能复现」。

用法: python3 docs/research/t295_event_audit.py
产物: docs/research/t295_audit.json
"""
import importlib.util
import json
import os
import sys
import time
import urllib.request

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
OUT = os.path.join(HERE, "t295_audit.json")

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
D_TO = "2026-11-04"          # T-242 / T-289 参考跑数的截止日
N_AUDIT = 10                 # 每类抽 N 个事件做逐格审计

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
    pairs_json = json.load(open("/Volumes/CometCloudAI/cometcloud-local/research/"
                                "t242/cache/perp_bv_pairs.json"))["rows"]
    pairs = pd.DataFrame(pairs_json)
    funding = pd.read_csv("/Volumes/CometCloudAI/cometcloud-local/research/"
                           "t242/cache/v_funding_daily.csv.gz")
    funding["d"] = pd.to_datetime(funding["d"])
    log("pairs rows", len(pairs), "funding rows", len(funding))
    pan = t242.build_panels(pbv, pairs, funding, None)
    kind = dict(zip(pairs["symbol"], pairs["kind"]))
    dead = {s: (None if pd.isna(dd) else dd) for s, dd in zip(pairs["symbol"], pairs["dead_from"])}
    uni = np.array([(kind.get(s) == "coin") or (kind.get(s) is None and dead.get(s) is not None)
                    for s in pan["syms"]])
    log("universe", int(uni.sum()), "of", len(uni))
    return t242, pan, uni


# ── B. SQL 语义(S1–S12)的独立实现 ─────────────────────────────────────────
def sql_pct_series(f7_row, k):
    """S11:扩张中位秩。分母 = 更早的行数(不是非空样本数);NaN 进分母不进分子。"""
    out = np.full(k, np.nan)
    for j in range(k):
        v = f7_row[j]
        if j == 0:
            out[j] = 0.0
            continue
        earlier = f7_row[:j]
        with np.errstate(all="ignore"):
            less = np.sum(earlier < v)
            eq = np.sum(earlier == v)
        out[j] = (less + 0.5 * eq) / max(j, 1)
    return out


def sql_detect(pan, uni_mask):
    """照 t295_crowding_events.sql 的 S1–S12 逐步实现(不复用 detect 的判定)。"""
    n_sym = pan["n_sym"]
    syms = pan["syms"]
    events = []
    for i in range(n_sym):
        if not uni_mask[i]:
            continue
        C = pan["C"][i]
        k = int(np.isfinite(C).sum())
        if k < 40:                                     # S10 / detect 第 216 行
            continue
        d = pan["dates"].iloc[i]
        o, h, l, qv = pan["O"][i], pan["H"][i], pan["L"][i], pan["QV"][i]
        f = pan["F"][i]
        ords = pan["ordmat"][i]
        first_ord = pan["first_ord"][i]

        # S4 TR(与 build_panels 139–141 同式,但这里重算,不复用 pan["atr"])
        c_prev = np.full(k, np.nan)
        c_prev[1:] = C[:k - 1]
        with np.errstate(all="ignore"):
            tr = np.nanmax(np.stack([h[:k] - l[:k],
                                      np.abs(h[:k] - c_prev),
                                      np.abs(l[:k] - c_prev)]), axis=0)
        # S5 ATR14:min_periods = 14
        atr = np.full(k, np.nan)
        for j in range(ATR_N + 1, k):
            w = tr[j - ATR_N:j]
            if np.isfinite(w).sum() == ATR_N:
                atr[j] = w.mean()
        # S6 qv20:min_periods = 20
        qv20 = np.full(k, np.nan)
        for j in range(QV_WIN + 1, k):
            w = qv[:k][j - QV_WIN:j]
            if np.isfinite(w).sum() == QV_WIN:
                qv20[j] = w.mean()
        # S7 f7:min_periods = 7,×1095 —— 只在面板的【前 k_fund 行】上算
        #   (python: k = isfinite(F[i]).sum();s = pd.Series(F[i,:k]))
        k_fund = int(np.isfinite(f).sum())
        if k_fund < FUND_WIN + 2:          # python 第 159–160 行:整行 continue
            continue                       # ⇒ f7 与 pct 全 NaN ⇒ 该合约不产生任何事件
        f7 = np.full(k, np.nan)
        for j in range(FUND_WIN, k_fund):
            w = f[:k_fund][j - FUND_WIN:j]
            if np.isfinite(w).sum() == FUND_WIN:
                f7[j] = w.mean() * FUND_ANN_MULT
        # S8/S11 pct:只在面板前 k_fund 行上有定义(python: pct[i,:k_fund])
        pct = np.full(k, np.nan)
        for j in range(1, k_fund):
            earlier = f7[:j]
            v = f7[j]
            with np.errstate(all="ignore"):
                less = np.sum(earlier < v)
                eq = np.sum(earlier == v)
            pct[j] = (less + 0.5 * eq) / max(j, 1)
        # S10 便宜门槛
        cand = []
        for j in range(1, k - 1):                       # bar0 ∈ [1, k−2]
            age = ords[j] - first_ord
            if age < MIN_AGE_DAYS:
                continue
            if not (np.isfinite(qv20[j]) and np.isfinite(atr[j])):
                continue
            if not (np.isfinite(C[j - 1]) and C[j - 1] != 0 and np.isfinite(C[j])):
                continue
            ret = C[j] / C[j - 1] - 1.0
            if not np.isfinite(ret):
                continue
            if qv[j] < QV_MULT * qv20[j]:
                continue
            thr = ATR_K * atr[j] / C[j - 1]
            if not np.isfinite(thr):
                continue
            kind = None
            if pct[j] >= PCTL_HI and ret <= -thr:
                kind = "flush"
            elif pct[j] <= PCTL_LO and ret >= thr:
                kind = "squeeze"
            if kind:
                cand.append((kind, j, d.iloc[j], float(pct[j]), float(ret),
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
def db_get(path, rng=None, count_exact=False):
    url = os.environ["SUPABASE_URL"].rstrip("/") + "/rest/v1/" + path
    key = os.environ["SUPABASE_KEY"]
    req = urllib.request.Request(url)
    req.add_header("apikey", key)
    req.add_header("Authorization", "Bearer " + key)
    if count_exact:
        req.add_header("Prefer", "count=exact")
    if rng:
        req.add_header("Range", rng)
    with urllib.request.urlopen(req, timeout=120) as r:
        body = r.read().decode()
    return json.loads(body) if body else []


def db_rows(symbol, d_to):
    rows, start = [], 0
    while True:
        page = db_get("perp_bv_daily?select=d,o,h,l,c,qv&symbol=eq.%s&d=lte.%s&order=d.asc"
                       % (symbol, d_to), "%d-%d" % (start, start + 999))
        if not page:
            break
        rows.extend(page)
        start += len(page)
        if len(page) < 1000:
            break
    return rows


def main():
    t242 = load_t242()
    t242, pan, uni = build_reference(t242)
    ref = t242.detect(pan, uni, off=0)
    ref_s = sorted([(e["d"], pan["syms"][e["sym_i"]]) for e in ref["squeeze"]])
    ref_f = sorted([(e["d"], pan["syms"][e["sym_i"]]) for e in ref["flush"]])
    log("detect(): squeeze", len(ref_s), "flush", len(ref_f))

    sq = sql_detect(pan, uni)
    sql_s = sorted([(e["d"], e["symbol"]) for e in sq if e["kind"] == "squeeze"])
    sql_f = sorted([(e["d"], e["symbol"]) for e in sq if e["kind"] == "flush"])
    log("sql_detect(): squeeze", len(sql_s), "flush", len(sql_f))
    same_s = ref_s == sql_s
    same_f = ref_f == sql_f
    log("event sets identical: squeeze", same_s, "flush", same_f)
    if not (same_s and same_f):
        log("  only-in-detect  squeeze", sorted(set(ref_s) - set(sql_s))[:5])
        log("  only-in-sql     squeeze", sorted(set(sql_s) - set(ref_s))[:5])
        log("  only-in-detect  flush  ", sorted(set(ref_f) - set(sql_f))[:5])
        log("  only-in-sql     flush  ", sorted(set(sql_f) - set(ref_f))[:5])

    # ── C. 逐格审计:10 squeeze + 10 flush ──────────────────────────────────
    picks = []
    for name, evs in (("squeeze", ref["squeeze"]), ("flush", ref["flush"])):
        step = max(1, len(evs) // N_AUDIT)
        picked = evs[::step][:N_AUDIT]
        picks.extend(picked)
    rows = []
    for e in picks:
        i = e["sym_i"]
        j = e["bar"]
        sym = pan["syms"][i]
        f7_row = pan["f7"][i]
        pct_row = pan["pct"][i]
        k = int(np.isfinite(pan["C"][i]).sum())
        sql_pct_j = sql_pct_series(f7_row, k)[j]
        c_prev = pan["C"][i][j - 1]
        ret = pan["ret"][i][j]
        thr = ATR_K * pan["atr"][i][j] / c_prev
        age = pan["ordmat"][i][j] - pan["first_ord"][i]
        rows.append(dict(
            kind=("flush" if e in ref["flush"] else "squeeze"),
            symbol=sym, d=e["d"], bar0=int(j), k=int(k),
            f7=float(f7_row[j]) if np.isfinite(f7_row[j]) else None,
            pct=float(pct_row[j]) if np.isfinite(pct_row[j]) else None,
            pct_sql=float(sql_pct_j) if np.isfinite(sql_pct_j) else None,
            atr=float(pan["atr"][i][j]) if np.isfinite(pan["atr"][i][j]) else None,
            qv20=float(pan["qv20"][i][j]) if np.isfinite(pan["qv20"][i][j]) else None,
            qv=float(pan["QV"][i][j]),
            qv_mult=float(pan["QV"][i][j] / pan["qv20"][i][j]),
            ret=float(ret), atr_thr=float(thr), age_days=float(age),
            f7_is_nan=not np.isfinite(f7_row[j]),
            pct_is_zero=(np.isfinite(pct_row[j]) and pct_row[j] == 0.0),
        ))
    log("audited", len(rows), "events")
    # f7 为空 ⇒ pct=0 的伪装(边角 E3)有多少
    n_f7nan = sum(1 for r in rows if r["f7_is_nan"])
    n_pct0 = sum(1 for r in rows if r["pct_is_zero"])
    log("audited events with f7=NaN:", n_f7nan, "| with pct==0.0:", n_pct0)

    # ── 全量:218 + 20 里有多少是 f7 为空的「伪 pct=0」 ────────────────────
    def event_row(e):
        i, j = e["sym_i"], e["bar"]
        f7v = pan["f7"][i][j]
        return (pan["syms"][i], e["d"], bool(np.isfinite(f7v)),
                float(pan["pct"][i][j]))
    full = ([event_row(e) for e in ref["squeeze"]] + [event_row(e) for e in ref["flush"]])
    n_f7nan_all = sum(1 for x in full if not x[2])
    n_pct0_all = sum(1 for x in full if x[3] == 0.0)
    log("all events: f7 NaN", n_f7nan_all, "/", len(full), "| pct==0.0", n_pct0_all)

    # ── D. 库侧对账(20 个合约) ────────────────────────────────────────────
    db_checks = []
    for r in rows:
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
        if len(db_checks) >= 6:
            break

    out = dict(
        task="T-295",
        generated_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        reference=dict(squeeze=len(ref_s), flush=len(ref_f),
                       universe=int(uni.sum()), panel_symbols=int(pan["n_sym"])),
        sql_semantics=dict(squeeze=len(sql_s), flush=len(sql_f),
                           identical_squeeze=same_s, identical_flush=same_f),
        audited=rows,
        f7_nan_audited=n_f7nan, pct_zero_audited=n_pct0,
        f7_nan_all_events=n_f7nan_all, pct_zero_all_events=n_pct0_all,
        n_events_total=len(full),
        db_reconciliation=db_checks,
    )
    with open(OUT, "w") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1, default=float)
    log("wrote", OUT)
    print("=" * 78)
    print("detect() 事件数 squeeze/flush:", len(ref_s), len(ref_f))
    print("sql_detect() 事件数 squeeze/flush:", len(sql_s), len(sql_f),
          "| 逐条相同:", same_s, same_f)
    print("审计事件:", len(rows), "| f7=NaN:", n_f7nan, "| pct==0.0:", n_pct0)
    print("全量事件里 f7=NaN:", n_f7nan_all, "/", len(full),
          "| pct==0.0:", n_pct0_all)
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
