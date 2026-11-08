#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T-301 / S-783 —— ① 库内内核与参考实现逐事件对账 ② squeeze 30 天超额盲复算。

预注册:S-783 原文(照抄在 docs/research/T-301_squeeze_recompute.md 开头),S-726 / S-777 的口径段。

① 事件:自己的 t289_squeeze.py 家族(本 lane 的 S-777 交付 docs/research/t297_clean.py)的
   detect(guards=True) = S-777 干净口径(f7 为空 / ATR14 ≤ 0 / qv20 ≤ 0 不是事件)。
   与 crowding_watch(cohort='backfill')逐 (kind, symbol, d) 对账。
② 前向:S-726 口径 —— d+1 开盘 → d+30 收盘(期间停更取窗口内最后一个收盘;进场那天没有开盘价
   ⇒ 不算、报个数),超额 = 代币 − 同一进出窗口的时点等权永续篮(宇宙 = 内核的 uni)。
   零分布:同币同年随机日,1,000 次,种子 783,零分布只用 src/data/evaluation/apparatus.py。

数据:今天重拉(perp_bv_daily / v_funding_daily / perp_bv_pairs),缓存
  /Volumes/CometCloudAI/cometcloud-local/research/t301/cache/
只读:不写库、不入库、不读 .env、不打印 key。
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import time

import numpy as np
import pandas as pd

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HERE = os.path.dirname(os.path.abspath(__file__))
# 缓存目录:参数优先,其次环境变量 COMETCLOUD_LOCAL_ROOT,最后是 Mac 数据根的默认值。
# (T-307 改:原来写死绝对路径,换个 checkout / 换个机器就跑不动了。)
DEFAULT_CACHE = os.path.join(
    os.environ.get("COMETCLOUD_LOCAL_ROOT", "/Volumes/CometCloudAI/cometcloud-local"),
    "research", "t301", "cache")
OUT_JSON = os.path.join(HERE, "t301_results.json")
OUT_CSV = os.path.join(HERE, "t301_events.csv")
OUT_SUM = os.path.join(HERE, "t301_summary.txt")

# 参考实现(自己的 S-777 交付:build_panels / detect(guards=True) / forward / null_stats)
_spec = importlib.util.spec_from_file_location("t297_clean", os.path.join(HERE, "t297_clean.py"))
t297 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(t297)

# apparatus(唯一允许的零分布 / 分位来源)
_spec2 = importlib.util.spec_from_file_location(
    "apparatus", os.path.join(REPO, "src", "data", "evaluation", "apparatus.py"))
apparatus = importlib.util.module_from_spec(_spec2)
_spec2.loader.exec_module(apparatus)
null_distribution = apparatus.null_distribution
percentile_of = apparatus.percentile_of
long_return = apparatus.long_return

# ── 预注册常数(照抄卡上 acceptance / S-783 / S-726 / S-777,一个不改)─────────
D_TO = "2026-11-04"          # 事件检测面板的截止(S-781 的事件窗口)
H_EVENT = 30                # 30 天超额
N_NULL = 1000
NULL_SEED = 783
HALVES = {"H1": ("-inf", "2022-12-31"), "H2": ("2023-01-01", "+inf")}


LOG_LINES = []


def log(*a):
    print(*a, flush=True)
    LOG_LINES.append(" ".join(str(x) for x in a))


def load_cache(name, cache=None):
    p = os.path.join(cache or CACHE, name)
    with open(p) as f:
        return json.load(f)


def build_pbv_df(rows):
    df = pd.DataFrame(rows)
    df["d"] = pd.to_datetime(df["d"])
    for c in ["o", "h", "l", "c", "qv", "tbqv"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.sort_values(["symbol", "d"]).reset_index(drop=True)


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=DEFAULT_CACHE,
                    help="缓存目录(默认 $COMETCLOUD_LOCAL_ROOT/research/t301/cache)")
    args = ap.parse_args()
    CACHE = args.cache
    t0 = time.time()
    log("=== T-301 recompute ===")
    log("cache: %s" % CACHE)
    pbv_rows = load_cache("perp_bv_daily.json", CACHE)["rows"]
    fund_rows = load_cache("v_funding_daily.json", CACHE)["rows"]
    pair_rows = load_cache("perp_bv_pairs.json", CACHE)["rows"]
    cw_rows = load_cache("crowding_watch_backfill.json", CACHE)["rows"]
    log("loaded: pbv=%d fund=%d pairs=%d cw=%d" % (len(pbv_rows), len(fund_rows), len(pair_rows), len(cw_rows)))

    pbv = build_pbv_df(pbv_rows)
    pairs = pd.DataFrame(pair_rows)
    pairs["first_d"] = pd.to_datetime(pairs["first_d"])
    funding = pd.DataFrame(fund_rows)
    funding["d"] = pd.to_datetime(funding["d"])
    funding["funding_rate"] = pd.to_numeric(funding["funding_rate"], errors="coerce")
    log("panels: pbv %d rows / %d symbols / %s .. %s" %
        (len(pbv), pbv["symbol"].nunique(), pbv["d"].min().date(), pbv["d"].max().date()))

    pan = t297.build_panels(pbv, pairs, funding, None)
    log("panels built %.0fs" % (time.time() - t0))
    syms = pan["syms"]

    # 宇宙(照 SQL 内核 S1 / 参考实现 main):kind='coin' 或 (kind 为空且 dead_from 非空)
    kind = dict(zip(pairs["symbol"], pairs["kind"]))
    dead = {s: (None if pd.isna(dd) else dd) for s, dd in zip(pairs["symbol"], pairs["dead_from"])}
    coin_mask = np.array([(kind.get(s) == "coin") for s in syms])
    uni_mask = np.array([(kind.get(s) == "coin") or (kind.get(s) is None and dead.get(s) is not None)
                         for s in syms])
    log("universe(uni)=%d  coin=%d" % (int(uni_mask.sum()), int(coin_mask.sum())))

    # 篮子成分的「已上市 ≥ 30 天」(参考实现 forward() 的口径,副口径用)
    first_ord_pairs = np.full(len(syms), np.nan)
    for s, fd in zip(pairs["symbol"], pairs["first_d"]):
        if s in pan["sidx"]:
            first_ord_pairs[pan["sidx"][s]] = fd.value / 86400e9 if pd.notna(fd) else np.nan
    first_ord = np.where(np.isfinite(first_ord_pairs), first_ord_pairs, pan["first_ord"])

    # ── ① 事件检测(参考实现 detect, guards=True) ───────────────────────────
    ev = t297.detect(pan, uni_mask, off=0, guards=True)
    ev_legacy = t297.detect(pan, uni_mask, off=0, guards=False)
    log("events(guards=True): squeeze=%d flush=%d | (guards=False) squeeze=%d flush=%d" %
        (len(ev["squeeze"]), len(ev["flush"]), len(ev_legacy["squeeze"]), len(ev_legacy["flush"])))

    # 逐事件的检测输入(只报不改口径):fund_pct = 7 日资金费分位、ret = 当日收益、
    # atr_thr = ATR_K×ATR14/前收盘、qv_mult = qv 门槛倍数(常量)。
    def ev_detail(e):
        i, j = e["sym_i"], e["bar"]
        c = pan["C"][i]
        atr = pan["atr"][i]
        thr = t297.ATR_K * atr / np.roll(c, 1)
        ret = pan["ret"][i][j]
        return {"fund_pct": float(pan["pct"][i][j]),
                "ret": float(ret) if ret is not None else float("nan"),
                "atr_thr": float(thr[j]), "qv_mult": float(t297.QV_MULT),
                "qv": float(pan["QV"][i][j]), "qv20": float(pan["qv20"][i][j]),
                "atr14": float(atr[j]), "f7": float(pan["f7"][i][j]),
                "pctl_hi": float(t297.PCTL_HI), "pctl_lo": float(t297.PCTL_LO),
                "dedupe_days": float(t297.DEDUPE_DAYS)}

    mine = {}
    for kindname in ("squeeze", "flush"):
        for e in ev[kindname]:
            mine[(kindname, syms[e["sym_i"]], e["d"])] = e
    mine_backfill = {k: v for k, v in mine.items() if k[2] <= D_TO}
    mine_fwd = {k: v for k, v in mine.items() if k[2] > D_TO}

    db = {}
    for r in cw_rows:
        db[(r["kind"], r["symbol"], str(r["d"])[:10])] = r
    log("reconcile: mine(backfill)=%d  db(backfill)=%d  mine(forward-cohort)=%d" %
        (len(mine_backfill), len(db), len(mine_fwd)))

    only_mine = sorted(set(mine_backfill) - set(db))
    only_db = sorted(set(db) - set(mine_backfill))
    common = sorted(set(mine_backfill) & set(db))

    # 事件清单落盘(先落,后算)
    with open(OUT_CSV, "w") as f:
        f.write("source,kind,symbol,d,note\n")
        for k in sorted(mine):
            f.write("mine,%s,%s,%s,guards=True\n" % (k[0], k[1], k[2]))
        for k in sorted(db):
            f.write("db,%s,%s,%s,crowding_watch backfill\n" % (k[0], k[1], k[2]))
    log("events csv written: %s" % OUT_CSV)

    # ── ② 前向:S-726 口径(d+1 开盘 → d+30 收盘,日历口径)──────────────────
    # 全部向量化:ex_ret[k, sym] = 轴上第 k 天(= 事件日 d)的成员收益
    Omat, Cmat = pan["Omat"], pan["Cmat"]
    alld = np.array(sorted({pd.Timestamp(x) for x in pan["dates"].values.ravel() if not pd.isna(x)}))
    n_dates, n_sym = Cmat.shape
    assert n_dates == len(alld)
    # 反向填充:最后一个 ≤ t 的收盘(窗口内最后一个收盘)
    Cdf = pd.DataFrame(Cmat).bfill(axis=0).to_numpy()
    ex_ret = np.full((n_dates, n_sym), np.nan)
    entry_ok = np.zeros(n_dates, dtype=bool)
    max_d = alld[-1]
    for k in range(n_dates):
        d0 = alld[k]
        d1 = d0 + np.timedelta64(1, "D")
        if d1 > max_d:
            continue
        j1 = np.searchsorted(alld, d1)
        if j1 >= n_dates or alld[j1] != d1:
            continue                      # 进场那天没有开盘价 ⇒ 不算
        d30 = d0 + np.timedelta64(H_EVENT, "D")
        if d30 > max_d:
            continue                      # 未到期
        j30 = np.searchsorted(alld, d30, side="right") - 1
        entry = Omat[j1, :]
        exit_ = Cdf[j30, :]
        ok = np.isfinite(entry) & (entry > 0) & np.isfinite(exit_) & (exit_ > 0)
        ex_ret[k, :] = np.where(ok, exit_ / np.where(entry > 0, entry, np.nan) - 1.0, np.nan)
        entry_ok[k] = True
    log("forward matrix built: %d/%d dates mature+entry-capable" % (int(entry_ok.sum()), n_dates))

    # 篮子:同一进出窗口的时点等权永续篮(宇宙 = 内核的 uni)
    with np.errstate(all="ignore"):
        basket = np.nanmean(np.where(uni_mask[None, :], ex_ret, np.nan), axis=1)
        basket_n = np.sum(np.isfinite(ex_ret) & uni_mask[None, :], axis=1)
    # 副口径:只用 kind='coin' 且已上市 ≥ 30 天(参考实现 forward() 的篮子口径)
    with np.errstate(all="ignore"):
        basket_coin = np.nanmean(np.where(coin_mask[None, :], ex_ret, np.nan), axis=1)

    axis_pos = {pd.Timestamp(d).value: k for k, d in enumerate(alld)}

    def event_excess(kindname, sym, dstr):
        """返回 (超额, 代币收益, 篮子收益, 篮子 n, 是否到期)。"""
        d = pd.Timestamp(dstr)
        k = axis_pos.get(d.value)
        if k is None:
            return (np.nan,) * 5
        i = pan["sidx"].get(sym)
        if i is None:
            return (np.nan,) * 5
        ev_ret = ex_ret[k, i]
        bk = basket[k]
        if not np.isfinite(ev_ret) or not np.isfinite(bk):
            return (np.nan,) * 5
        return (ev_ret - bk, ev_ret, bk, int(basket_n[k]), True)

    def event_excess_coin(sym, dstr):
        d = pd.Timestamp(dstr)
        k = axis_pos.get(d.value)
        if k is None:
            return (np.nan,) * 4
        i = pan["sidx"].get(sym)
        if i is None:
            return (np.nan,) * 4
        ev_ret = ex_ret[k, i]
        bk = basket_coin[k]
        if not np.isfinite(ev_ret) or not np.isfinite(bk):
            return (np.nan,) * 4
        return (ev_ret - bk, ev_ret, bk, int(basket_n[k]))

    # 逐事件算,并与库内已存的 x30 逐条对(那是 SQL 内核写下的数)
    rows = []
    for kindname in ("squeeze", "flush"):
        for e in sorted(ev[kindname], key=lambda x: x["d"]):
            sym = syms[e["sym_i"]]
            exc, evr, bk, bn, _ = event_excess(kindname, sym, e["d"])
            exc_c, _, bk_c, _ = event_excess_coin(sym, e["d"])
            r = db.get((kindname, sym, e["d"]))
            rows.append({"kind": kindname, "symbol": sym, "d": e["d"], "exc": exc, "ev_ret": evr,
                         "basket": bk, "basket_n": bn, "exc_coin": exc_c,
                         "db_x30": (r or {}).get("x30"), "db_basket_n": (r or {}).get("basket_n"),
                         "in_db": r is not None, **ev_detail(e)})
    import csv as _csv
    with open(os.path.join(HERE, "t301_event_forward.csv"), "w", newline="") as f:
        w = _csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        for r in rows:
            w.writerow(r)
    log("event forward csv written")

    df = pd.DataFrame(rows)
    sq = df[(df["kind"] == "squeeze")].copy()
    sq_mat = sq[np.isfinite(sq["exc"])].copy()
    log("squeeze events=%d  matured(with excess)=%d" % (len(sq), len(sq_mat)))

    # 与库内 x30 的逐条比对(前向口径自检)
    cmp_rows = df[df["in_db"] & df["db_x30"].notna() & np.isfinite(df["exc"])]
    if len(cmp_rows):
        diff = (cmp_rows["exc"] - cmp_rows["db_x30"]).abs()
        log("x30 vs db: n=%d  max|diff|=%.3e  median|diff|=%.3e  exact(<=1e-9)=%d" %
            (len(cmp_rows), diff.max(), diff.median(), int((diff <= 1e-9).sum())))
    else:
        diff = None
        log("x30 vs db: no comparable rows")

    # ── 统计(主口径)────────────────────────────────────────────────────────
    def stats(x):
        x = np.asarray([v for v in x if np.isfinite(v)], dtype=float)
        if x.size == 0:
            return {"n": 0}
        return {"n": int(x.size), "median": float(np.median(x)), "mean": float(x.mean()),
                "p10": float(np.percentile(x, 10)), "p90": float(np.percentile(x, 90)),
                "neg_frac": float((x < 0).mean()), "min": float(x.min()), "max": float(x.max())}

    def halves(x, darr):
        out = {}
        for hk, (a, b) in HALVES.items():
            # "-inf" / "+inf" 是哨兵(照抄 HALVES 常数),不是字面字符串比较——
            # 否则 "+inf" < "2026-07-13"(ASCII '+' < '2')会把 H2 全部判成空。
            m = np.ones(len(darr), dtype=bool)
            if a != "-inf":
                m &= (darr >= a)
            if b != "+inf":
                m &= (darr <= b)
            out[hk] = stats(np.asarray(x)[m])
        return out

    exc = sq_mat["exc"].to_numpy()
    darr = sq_mat["d"].to_numpy()
    res = {"meta": {"task": "T-301", "pre_registered": "S-783 (2026-11-08)",
                    "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "pbv_rows": int(len(pbv)), "pbv_d_min": str(pbv["d"].min().date()),
                    "pbv_d_max": str(pbv["d"].max().date()), "pbv_symbols": int(pbv["symbol"].nunique()),
                    "fund_rows": int(len(funding)), "pairs_rows": int(len(pairs)),
                    "cw_backfill_rows": int(len(db)),
                    "n_uni": int(uni_mask.sum()), "n_coin": int(coin_mask.sum()),
                    "constants": {"horizon": H_EVENT, "n_null": N_NULL, "seed": NULL_SEED,
                                  "d_to": D_TO, "guards": True,
                                  "basket": "uni(内核宇宙),同一进出窗口的时点等权永续篮",
                                  "forward": "d+1 开盘 → d+30 收盘(窗口内最后一个收盘)"}}}

    res["reconcile"] = {
        "mine_backfill": len(mine_backfill), "db_backfill": len(db), "mine_forward_cohort": len(mine_fwd),
        "common": len(common), "only_mine": len(only_mine), "only_db": len(only_db),
        "only_mine_first20": [list(k) for k in only_mine[:20]],
        "only_db_first20": [list(k) for k in only_db[:20]],
        "only_mine_all": [list(k) for k in only_mine],
        "only_db_all": [list(k) for k in only_db],
        "mine_forward_first20": [list(k) for k in sorted(mine_fwd)[:20]],
        "events_guards_true": {"squeeze": len(ev["squeeze"]), "flush": len(ev["flush"])},
        "events_guards_false": {"squeeze": len(ev_legacy["squeeze"]), "flush": len(ev_legacy["flush"])},
    }
    log("reconcile: common=%d only_mine=%d only_db=%d" % (len(common), len(only_mine), len(only_db)))

    # 主口径统计
    res["squeeze"] = {"full": stats(exc), "halves": halves(exc, darr)}
    # 副口径:coin-only 篮子(参考实现 forward() 的篮子口径)
    sq_c = sq[np.isfinite(sq["exc_coin"])]
    res["squeeze_coin_basket"] = {"full": stats(sq_c["exc_coin"].to_numpy()),
                                   "halves": halves(sq_c["exc_coin"].to_numpy(), sq_c["d"].to_numpy())}
    # 参考实现自带的 bar 口径(bar j+1 开盘 → bar j+30 收盘,coin 篮子)
    sq_sorted = sorted(ev["squeeze"], key=lambda x: x["d"])
    ev_ret, bk_ret, exc_ref, meta_ref = t297.forward(pan, sq_sorted, coin_mask, first_ord, H_EVENT)
    res["squeeze_reference_bar"] = {"full": t297.describe(exc_ref)}
    log("reference bar-basis median %.4f (n=%d)" %
        (res["squeeze_reference_bar"]["full"].get("median", float("nan")),
         res["squeeze_reference_bar"]["full"].get("n", 0)))

    # 逐事件 x30 自检
    if diff is not None:
        res["x30_vs_db"] = {"n": len(cmp_rows), "max_abs_diff": float(diff.max()),
                            "median_abs_diff": float(diff.median()),
                            "n_exact_1e-9": int((diff <= 1e-9).sum())}

    # ── 零分布:同币同年随机日,1,000 次,种子 783(只用 apparatus)──────────
    # 候选:同合约、同一年、已到期、且该合约在 d'+1 有开盘价
    # 掩码对齐:零分布与实际值必须用同一批事件(已到期 / x30 有值)——
    # 否则零分布按 351 个事件抽、实际值只有 341 个,分位不可比。
    matured_keys = set(zip(sq_mat["symbol"], sq_mat["d"]))
    sq_matured = [e for e in sq_sorted if (syms[e["sym_i"]], e["d"]) in matured_keys]
    cands = []
    for e in sq_matured:
        sym = syms[e["sym_i"]]
        i = pan["sidx"][sym]
        y = int(e["d"][:4])
        cs = []
        for k, d0 in enumerate(alld):
            if d0.year != y:
                continue
            if not np.isfinite(ex_ret[k, i]):
                continue
            cs.append(k)
        cands.append(np.array(cs, dtype=np.int64))
    log("null candidates per event: min=%d max=%d" %
        (min(len(c) for c in cands), max(len(c) for c in cands)))

    def draw(rng):
        vals = np.empty(len(cands), dtype=float)
        for t, c in enumerate(cands):
            if len(c) == 0:
                return np.nan
            k = c[int(rng.integers(0, len(c)))]
            vals[t] = ex_ret[k, pan["sidx"][syms[sq_matured[t]["sym_i"]]]] - basket[k]
        return vals

    n_median = null_distribution(lambda rng: float(np.median(draw(rng))), N_NULL, NULL_SEED)
    n_mean = null_distribution(lambda rng: float(np.mean(draw(rng))), N_NULL, NULL_SEED)
    act_med = float(np.median(exc))
    act_mean = float(np.mean(exc))
    res["null"] = {
        "median": {"actual": act_med, "pctl": percentile_of(act_med, n_median),
                   "null_median": float(np.median(n_median)), "n": int(len(n_median))},
        "mean": {"actual": act_mean, "pctl": percentile_of(act_mean, n_mean),
                 "null_median": float(np.median(n_mean)), "n": int(len(n_mean))},
        "seed": NULL_SEED, "n_null": N_NULL,
        "note": "同币同年随机日;每抽每个事件独立取一个随机日;零分布/分位只用 apparatus.py",
    }
    log("null: median pct=%s (null med %.4f) | mean pct=%s (null med %.4f)" %
        (res["null"]["median"]["pctl"], res["null"]["median"]["null_median"],
         res["null"]["mean"]["pctl"], res["null"]["mean"]["null_median"]))

    with open(OUT_JSON, "w") as f:
        json.dump(res, f, indent=2, ensure_ascii=False, default=str)
    log("results written: %s (%.0fs)" % (OUT_JSON, time.time() - t0))

    # 摘要落盘到**被跟踪**的路径(T-307 改:原来只有 *.log,被 .gitignore 吃掉,
    # 报告 §4 指的日志在仓库里根本不存在)。*.log 在 .gitignore 里,所以用 .txt。
    with open(OUT_SUM, "w") as f:
        f.write("T-301 复算运行摘要(机器读数见 t301_results.json)\n")
        f.write("cache: %s\n" % CACHE)
        f.write("\n".join(LOG_LINES) + "\n")
    log("summary written: %s" % OUT_SUM)


if __name__ == "__main__":
    sys.exit(main())
