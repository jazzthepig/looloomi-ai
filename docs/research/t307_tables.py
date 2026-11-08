#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T-307 —— T-301 补三张表(剂量-反应 × 两臂并列 × x1/x7/x30 时间形状)。

背景:lane-a 11-08 交叉复核 T-301,指出报告只报了 squeeze 臂的 30 天超额,漏了
  ① squeeze 臂内资金费分位的剂量-反应;② flush 臂从未与 squeeze 并列;
  ③ 只报 30 天(库内 x1/x7 已存);④ 内核 ≡ 参考实现只在 squeeze 臂成立。

口径:全部沿用 T-301(S-783 预注册 / S-726 前向 / S-777 干净检测),预注册常量一个没改。
新增的只有:三个分组(剂量-反应四档 / 两臂 / 时间形状)与一个置换检验(种子 301,卡上点名)。
零分布 / 分位 / 置换 / 随机日:只用 src/data/evaluation/apparatus.py。

数据:读 T-301 的缓存(默认 Mac 数据根 research/t301/cache/,可用 --cache 改)。
只读:不写库、不入库、不读 .env、不打印 key。
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import os
import sys
import time

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
DEFAULT_CACHE = os.path.join(
    os.environ.get("COMETCLOUD_LOCAL_ROOT", "/Volumes/CometCloudAI/cometcloud-local"),
    "research", "t301", "cache")
OUT_JSON = os.path.join(HERE, "t307_results.json")
OUT_SUM = os.path.join(HERE, "t307_summary.txt")
OUT_CSV = os.path.join(HERE, "t307_event_forward.csv")

# ── 预注册常量(照抄 T-301 / S-783,一个不改)────────────────────────────────
D_TO = "2026-11-04"
HORIZONS = (1, 7, 30)
# ── T-307 新增的量(卡上点名;与 T-301 的 783 分开,原数不动)─────────────────
NEW_SEED = 301
NEW_N_NULL = 1000
# 剂量-反应四档(squeeze 臂的资金费分位 ∈ [0, 0.10];档界照 lane-a 复核里写的
# 「≤0.02 … 0.08-0.10」取整档,中间两档补齐)
DOSE_BUCKETS = [("≤0.02", 0.00, 0.02), ("0.02-0.05", 0.02, 0.05),
                ("0.05-0.08", 0.05, 0.08), ("0.08-0.10", 0.08, 0.10)]

_spec = importlib.util.spec_from_file_location("t297_clean", os.path.join(HERE, "t297_clean.py"))
t297 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(t297)

_spec2 = importlib.util.spec_from_file_location(
    "apparatus", os.path.join(REPO, "src", "data", "evaluation", "apparatus.py"))
apparatus = importlib.util.module_from_spec(_spec2)
_spec2.loader.exec_module(apparatus)
null_distribution = apparatus.null_distribution
percentile_of = apparatus.percentile_of
random_dates_like = apparatus.random_dates_like
shuffle_within = apparatus.shuffle_within

LOG = []


def log(*a):
    msg = " ".join(str(x) for x in a)
    LOG.append(msg)
    print(msg, flush=True)


def load_cache(name, cache):
    with open(os.path.join(cache, name)) as f:
        return json.load(f)


def build_pbv_df(rows):
    df = pd.DataFrame(rows)
    df["d"] = pd.to_datetime(df["d"])
    for c in ["o", "h", "l", "c", "qv", "tbqv"]:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.sort_values(["symbol", "d"]).reset_index(drop=True)


def stats(x):
    x = np.asarray([v for v in x if np.isfinite(v)], dtype=float)
    if x.size == 0:
        return {"n": 0}
    return {"n": int(x.size), "median": float(np.median(x)), "mean": float(x.mean()),
            "p10": float(np.percentile(x, 10)), "p90": float(np.percentile(x, 90)),
            "neg_frac": float((x < 0).mean()), "min": float(x.min()), "max": float(x.max())}


def pct(x):
    """百分比字符串(保留两位),给 markdown 用。"""
    return "—" if x is None else ("%.2f%%" % (100.0 * x))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=DEFAULT_CACHE, help="T-301 缓存目录")
    args = ap.parse_args()
    cache = args.cache
    t0 = time.time()
    log("=== T-307 三张表 ===")
    log("cache: %s" % cache)

    pbv_rows = load_cache("perp_bv_daily.json", cache)["rows"]
    fund_rows = load_cache("v_funding_daily.json", cache)["rows"]
    pair_rows = load_cache("perp_bv_pairs.json", cache)["rows"]
    cw_rows = load_cache("crowding_watch_backfill.json", cache)["rows"]
    log("loaded: pbv=%d fund=%d pairs=%d cw=%d" %
        (len(pbv_rows), len(fund_rows), len(pair_rows), len(cw_rows)))

    pbv = build_pbv_df(pbv_rows)
    pairs = pd.DataFrame(pair_rows)
    pairs["first_d"] = pd.to_datetime(pairs["first_d"])
    funding = pd.DataFrame(fund_rows)
    funding["d"] = pd.to_datetime(funding["d"])
    funding["funding_rate"] = pd.to_numeric(funding["funding_rate"], errors="coerce")

    pan = t297.build_panels(pbv, pairs, funding, None)
    syms = pan["syms"]
    log("panels built %.0fs" % (time.time() - t0))

    kind = dict(zip(pairs["symbol"], pairs["kind"]))
    dead = {s: (None if pd.isna(dd) else dd) for s, dd in zip(pairs["symbol"], pairs["dead_from"])}
    uni_mask = np.array([(kind.get(s) == "coin") or (kind.get(s) is None and dead.get(s) is not None)
                         for s in syms])
    log("universe(uni)=%d" % int(uni_mask.sum()))

    ev = t297.detect(pan, uni_mask, off=0, guards=True)
    log("events(guards=True): squeeze=%d flush=%d" % (len(ev["squeeze"]), len(ev["flush"])))

    db = {(r["kind"], r["symbol"], str(r["d"])[:10]): r for r in cw_rows}

    # ── 前向矩阵:H = 1 / 7 / 30(日历口径 d+1 开盘 → d+H 收盘,窗口内最后一个收盘)──
    Omat, Cmat = pan["Omat"], pan["Cmat"]
    alld = np.array(sorted({pd.Timestamp(x) for x in pan["dates"].values.ravel() if not pd.isna(x)}))
    n_dates, n_sym = Cmat.shape
    Cdf = pd.DataFrame(Cmat).bfill(axis=0).to_numpy()
    max_d = alld[-1]
    axis_pos = {pd.Timestamp(d).value: k for k, d in enumerate(alld)}

    fwd = {}
    for H in HORIZONS:
        ex_ret = np.full((n_dates, n_sym), np.nan)
        for k in range(n_dates):
            d0 = alld[k]
            d1 = d0 + np.timedelta64(1, "D")
            if d1 > max_d:
                continue
            j1 = np.searchsorted(alld, d1)
            if j1 >= n_dates or alld[j1] != d1:
                continue                      # 进场那天没有开盘价 ⇒ 不算
            dH = d0 + np.timedelta64(H, "D")
            if dH > max_d:
                continue                      # 未到期
            jH = np.searchsorted(alld, dH, side="right") - 1
            entry = Omat[j1, :]
            exit_ = Cdf[jH, :]
            ok = np.isfinite(entry) & (entry > 0) & np.isfinite(exit_) & (exit_ > 0)
            ex_ret[k, :] = np.where(ok, exit_ / np.where(entry > 0, entry, np.nan) - 1.0, np.nan)
        with np.errstate(all="ignore"):
            basket = np.nanmean(np.where(uni_mask[None, :], ex_ret, np.nan), axis=1)
            basket_n = np.sum(np.isfinite(ex_ret) & uni_mask[None, :], axis=1)
        fwd[H] = {"ex_ret": ex_ret, "basket": basket, "basket_n": basket_n}
        log("forward matrix H=%d built" % H)

    # ── 逐事件(参考实现口径 mine vs 库内内核已存 db)──────────────────────────
    rows = []
    for kindname in ("squeeze", "flush"):
        for e in sorted(ev[kindname], key=lambda x: x["d"]):
            if e["d"] > D_TO:
                continue                      # 只用 backfill cohort
            sym = syms[e["sym_i"]]
            i = pan["sidx"].get(sym)
            r = db.get((kindname, sym, e["d"]))
            rec = {"kind": kindname, "symbol": sym, "d": e["d"],
                   "fund_pct": float(pan["pct"][i][e["bar"]]),
                   "in_db": r is not None}
            for H in HORIZONS:
                k = axis_pos.get(pd.Timestamp(e["d"]).value)
                F = fwd[H]
                v = np.nan
                if k is not None and i is not None and np.isfinite(F["ex_ret"][k, i]) \
                        and np.isfinite(F["basket"][k]):
                    v = float(F["ex_ret"][k, i] - F["basket"][k])
                rec["mine_x%d" % H] = v
                rec["db_x%d" % H] = (r or {}).get("x%d" % H)
                rec["db_basket_n"] = (r or {}).get("basket_n")
            rows.append(rec)
    df = pd.DataFrame(rows)
    log("events(backfill): squeeze=%d flush=%d  (in_db: %d)" %
        (int((df["kind"] == "squeeze").sum()), int((df["kind"] == "flush").sum()),
         int(df["in_db"].sum())))
    with open(OUT_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        for r in rows:
            w.writerow(r)
    log("event csv written: %s" % OUT_CSV)

    sq = df[df["kind"] == "squeeze"].copy()
    fl = df[df["kind"] == "flush"].copy()

    res = {"meta": {"task": "T-307", "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "cache": cache, "d_to": D_TO, "guards": True,
                    "constants_inherited": {"horizons": list(HORIZONS), "detection": "t297_clean.detect(guards=True)",
                                            "forward": "d+1 开盘 → d+H 收盘(窗口内最后一个收盘)",
                                            "basket": "uni(内核宇宙),同一进出窗口的时点等权永续篮"},
                    "constants_new": {"seed": NEW_SEED, "n_null": NEW_N_NULL,
                                      "dose_buckets": [b[0] for b in DOSE_BUCKETS],
                                      "note": "T-301 的 seed=783 / n=1000 原样保留,本卡新增计算用 301"}},
           "tables": {}}

    # ── 表 1:剂量-反应(squeeze 臂,按资金费分位四档)────────────────────────
    # 随机日零分布:同币、同年、已到期(有可用前向超额)的随机日 —— 用 apparatus.random_dates_like
    elig = {}
    for s in syms:
        i = pan["sidx"].get(s)
        if i is None:
            continue
        ds = []
        for k, d0 in enumerate(alld):
            if np.isfinite(fwd[30]["ex_ret"][k, i]):
                ds.append(str(d0.date()))
        if ds:
            elig[s] = ds

    def bucket_random_day_median(bucket_events, rng):
        """每个事件换成同币同年随机日,取这些日子上的超额中位数(随机日对照)。"""
        evs = [(r["symbol"], r["d"]) for r in bucket_events]
        picked = random_dates_like(evs, elig, rng)
        vals = []
        for (sym, d0), (_, dnew) in zip(evs, picked):
            if dnew is None:
                continue                        # None = 缺失,不能当 0
            i = pan["sidx"].get(sym)
            k = axis_pos.get(pd.Timestamp(dnew).value)
            if i is None or k is None:
                continue
            ev_ret = fwd[30]["ex_ret"][k, i]
            bk = fwd[30]["basket"][k]
            if not np.isfinite(ev_ret) or not np.isfinite(bk):
                continue
            vals.append(float(ev_ret - bk))
        if not vals:
            return float("nan")
        return float(np.median(vals))

    dose = []
    for label, lo, hi in DOSE_BUCKETS:
        if label.startswith("≤"):
            m = (sq["fund_pct"] <= hi)
        elif label.endswith("-0.10"):
            m = (sq["fund_pct"] > lo) & (sq["fund_pct"] <= hi)
        else:
            m = (sq["fund_pct"] > lo) & (sq["fund_pct"] <= hi)
        b = sq[m].copy()
        b_mine = b[np.isfinite(b["mine_x30"])]
        b_db = b[b["db_x30"].notna() & np.isfinite(b["db_x30"])]
        entry = {"bucket": label, "lo": lo, "hi": hi,
                 "n_all_events": int(len(b)),
                 "n_mine": int(len(b_mine)), "n_db": int(len(b_db)),
                 "mine": stats(b_mine["mine_x30"].to_numpy()),
                 "db": stats(b_db["db_x30"].to_numpy())}
        # 随机日对照分位(种子 301)
        if len(b_mine) >= 5:
            actual = float(np.median(b_mine["mine_x30"].to_numpy()))
            try:
                null = null_distribution(
                    lambda rng: bucket_random_day_median(b_mine.to_dict("records"), rng),
                    NEW_N_NULL, NEW_SEED)
                entry["random_day_null"] = {
                    "actual_median": actual, "pctl": percentile_of(actual, null),
                    "null_median": float(np.median(null)), "n_null": int(len(null)),
                    "seed": NEW_SEED}
            except Exception as e:            # NoOpNull 等:记下来,不猜
                entry["random_day_null"] = {"error": "%s: %s" % (type(e).__name__, e)}
        dose.append(entry)
        log("dose %s: n_mine=%d median=%s | db median=%s | null pctl=%s" %
            (label, entry["n_mine"], pct(entry["mine"].get("median")),
             pct(entry["db"].get("median")),
             (entry.get("random_day_null") or {}).get("pctl")))
    res["tables"]["dose_response"] = {"arm": "squeeze", "horizon": 30, "buckets": dose}

    # ── 表 2:两臂并列(squeeze vs flush;x1/x7/x30)──────────────────────────
    def perm_diff_pctl(vals, is_sq, actual, seed=NEW_SEED, n=NEW_N_NULL):
        """置换检验:打乱两臂标签,零分布 = 置换后的中位差;分位 = 实际差在零分布里的位次。
        打乱用 apparatus.shuffle_within(单组 = 全体打乱),零分布用 apparatus.null_distribution。"""
        vals = np.asarray(vals, dtype=float)
        is_sq = np.asarray(is_sq, dtype=bool)

        def draw(rng):
            sh = np.asarray(shuffle_within(vals, np.zeros(len(vals), dtype=object), rng), dtype=float)
            m0 = float(np.median(sh[is_sq]))
            m1 = float(np.median(sh[~is_sq]))
            return m0 - m1
        null = null_distribution(draw, n, seed)
        return {"actual_diff": actual, "pctl": percentile_of(actual, null),
                "null_median": float(np.median(null)), "n_null": int(len(null)), "seed": seed}

    arms = []
    for src in ("db", "mine"):
        for H in HORIZONS:
            col = "%s_x%d" % (src, H)
            a = sq[np.isfinite(sq[col])]
            b = fl[np.isfinite(fl[col])]
            if len(a) == 0 or len(b) == 0:
                continue
            ma = float(np.median(a[col].to_numpy()))
            mb = float(np.median(b[col].to_numpy()))
            vals = np.concatenate([a[col].to_numpy(), b[col].to_numpy()])
            is_sq = np.concatenate([np.ones(len(a), dtype=bool), np.zeros(len(b), dtype=bool)])
            try:
                pt = perm_diff_pctl(vals, is_sq, ma - mb)
            except Exception as e:
                pt = {"error": "%s: %s" % (type(e).__name__, e)}
            arms.append({"source": src, "horizon": H,
                         "squeeze": stats(a[col].to_numpy()), "flush": stats(b[col].to_numpy()),
                         "median_diff_pp": (ma - mb) * 100.0, "permutation": pt})
            log("arms[%s] H=%d: sq n=%d med=%s | fl n=%d med=%s | diff=%.2fpp | perm pctl=%s" %
                (src, H, len(a), pct(ma), len(b), pct(mb), (ma - mb) * 100.0, pt.get("pctl")))
    res["tables"]["two_arms"] = arms

    # ── 表 3:时间形状(x1/x7/x30)───────────────────────────────────────────
    shape = {}
    for src in ("db", "mine"):
        per_arm = {}
        for kindname, sub in (("squeeze", sq), ("flush", fl)):
            row = {}
            for H in HORIZONS:
                col = "%s_x%d" % (src, H)
                s = stats(sub[np.isfinite(sub[col])][col].to_numpy())
                row["x%d" % H] = s
            # 到第 7 天实现的超额占 30 天的比例(只算 x7/x30 同号的)
            c7, c30 = sub["%s_x7" % src], sub["%s_x30" % src]
            m = np.isfinite(c7) & np.isfinite(c30) & (np.sign(c7) == np.sign(c30)) & (c30 != 0)
            ratio = (c7[m] / c30[m]).to_numpy()
            row["x7_over_x30_same_sign"] = {"n": int(ratio.size),
                                            "median": float(np.median(ratio)) if ratio.size else None}
            # 30 天为负的事件里,7 天时已经为负的比例
            m2 = np.isfinite(c30) & (c30 < 0) & np.isfinite(c7)
            row["neg30_also_neg7_frac"] = (float((c7[m2] < 0).mean()) if m2.sum() else None)
            row["neg30_n"] = int(m2.sum())
            per_arm[kindname] = row
        shape[src] = per_arm
    res["tables"]["time_shape"] = shape

    # ── 表 4:库内内核 vs 参考实现(逐臂、逐期限)──────────────────────────────
    kern = []
    for kindname, sub in (("squeeze", sq), ("flush", fl)):
        for H in HORIZONS:
            a, b = sub["db_x%d" % H], sub["mine_x%d" % H]
            m = a.notna() & np.isfinite(b)
            if not m.any():
                continue
            diff = (a[m] - b[m]).abs()
            med_db = float(np.median(a[m].to_numpy()))
            med_mine = float(np.median(b[m].to_numpy()))
            kern.append({"kind": kindname, "horizon": H, "n": int(m.sum()),
                         "median_db": med_db, "median_mine": med_mine,
                         "median_diff_pp": (med_db - med_mine) * 100.0,
                         "n_bit_identical": int((diff <= 1e-12).sum()),
                         "n_exact_1e-9": int((diff <= 1e-9).sum()),
                         "median_abs_diff": float(diff.median()),
                         "p90_abs_diff": float(np.percentile(diff, 90)),
                         "max_abs_diff": float(diff.max())})
            log("kernel-vs-ref %s H=%d: n=%d med_db=%s med_mine=%s diff=%.2fpp | bit-identical %d | max|diff|=%.4f" %
                (kindname, H, int(m.sum()), pct(med_db), pct(med_mine),
                 (med_db - med_mine) * 100.0, int((diff <= 1e-12).sum()), float(diff.max())))
    res["tables"]["kernel_vs_reference"] = kern

    # ── 表 4b:参考实现「自带的」forward(bar 口径 + coin 篮子)vs 库内内核 ──────
    # T-301 §4.2 报过 squeeze 的 bar 口径中位 −16.32%(vs 日历口径 −16.35%);
    # 这里按臂分开比,看 flush 臂的差是不是更大(lane-a 复核说 flush 差 0.65–1.31pp)。
    kind_map = dict(zip(pairs["symbol"], pairs["kind"]))
    coin_mask = np.array([(kind_map.get(s) == "coin") for s in syms])
    first_ord_pairs = np.full(len(syms), np.nan)
    for s, fd in zip(pairs["symbol"], pairs["first_d"]):
        if s in pan["sidx"]:
            first_ord_pairs[pan["sidx"][s]] = fd.value / 86400e9 if pd.notna(fd) else np.nan
    first_ord = np.where(np.isfinite(first_ord_pairs), first_ord_pairs, pan["first_ord"])

    bar_ref = []
    for kindname in ("squeeze", "flush"):
        evs = sorted([e for e in ev[kindname] if e["d"] <= D_TO], key=lambda x: x["d"])
        keys = [(syms[e["sym_i"]], e["d"]) for e in evs]
        for H in HORIZONS:
            _, _, exc_ref, _ = t297.forward(pan, evs, coin_mask, first_ord, H)
            exc_ref = np.asarray(exc_ref, dtype=float)
            a = np.array([np.nan if db.get((kindname, s, d)) is None
                          else db[(kindname, s, d)].get("x%d" % H) for s, d in keys], dtype=float)
            b = exc_ref[:len(keys)]
            m = np.isfinite(a) & np.isfinite(b)
            if not m.any():
                continue
            diff = np.abs(a[m] - b[m])
            bar_ref.append({"kind": kindname, "horizon": H, "n": int(m.sum()),
                            "median_db": float(np.median(a[m])), "median_ref_bar": float(np.median(b[m])),
                            "median_diff_pp": (float(np.median(a[m])) - float(np.median(b[m]))) * 100.0,
                            "median_abs_diff": float(np.median(diff)),
                            "p90_abs_diff": float(np.percentile(diff, 90)),
                            "max_abs_diff": float(diff.max()),
                            "n_bit_identical": int((diff <= 1e-12).sum())})
            log("bar-ref vs db %s H=%d: n=%d med_db=%s med_ref=%s diff=%.2fpp | med|diff|=%.4f max|diff|=%.4f"
                % (kindname, H, int(m.sum()), pct(float(np.median(a[m]))), pct(float(np.median(b[m]))),
                   (float(np.median(a[m])) - float(np.median(b[m]))) * 100.0,
                   float(np.median(diff)), float(diff.max())))
    res["tables"]["kernel_vs_reference_bar_basis"] = bar_ref

    with open(OUT_JSON, "w") as f:
        json.dump(res, f, indent=2, ensure_ascii=False, default=str)
    log("results written: %s (%.0fs)" % (OUT_JSON, time.time() - t0))

    # ── 摘要(被跟踪的路径;*.log 在 .gitignore 里,所以用 .txt)────────────────
    L = []
    L.append("T-307 三张表 —— 摘要(机器读数见 t307_results.json,逐事件见 t307_event_forward.csv)")
    L.append("生成: %s   缓存: %s" % (res["meta"]["generated_at"], cache))
    L.append("口径: 检测 t297_clean.detect(guards=True);前向 d+1 开盘 → d+H 收盘;篮子 = 内核 uni 同一进出窗口时点等权")
    L.append("新增量: 种子 %d / %d 次;剂量四档 %s;T-301 原 seed=783 的数未动"
             % (NEW_SEED, NEW_N_NULL, "/".join(b[0] for b in DOSE_BUCKETS)))
    L.append("")
    L.append("[表1] 剂量-反应(squeeze 臂,x30 超额;随机日对照分位,种子 %d)" % NEW_SEED)
    for e in dose:
        L.append("  %-9s n=%-4d 参考中位=%-9s 库内中位=%-9s 随机日分位=%s"
                 % (e["bucket"], e["n_mine"], pct(e["mine"].get("median")), pct(e["db"].get("median")),
                    (e.get("random_day_null") or {}).get("pctl")))
    L.append("")
    L.append("[表2] 两臂并列")
    for a in arms:
        L.append("  [%s] H=%d  squeeze n=%-4d 中位=%-9s | flush n=%-4d 中位=%-9s | 中位差=%+.2fpp | 置换分位=%s"
                 % (a["source"], a["horizon"], a["squeeze"]["n"], pct(a["squeeze"].get("median")),
                    a["flush"]["n"], pct(a["flush"].get("median")), a["median_diff_pp"],
                    a["permutation"].get("pctl")))
    L.append("")
    L.append("[表3] 时间形状(x1/x7/x30 中位)")
    for src in ("db", "mine"):
        for arm in ("squeeze", "flush"):
            r = shape[src][arm]
            L.append("  [%s] %-7s x1=%-9s x7=%-9s x30=%-9s | x7/x30(同号)中位=%s | 30天为负且7天也为负=%.1f%%(n=%d)"
                     % (src, arm, pct(r["x1"].get("median")), pct(r["x7"].get("median")),
                        pct(r["x30"].get("median")),
                        ("%.2f" % r["x7_over_x30_same_sign"]["median"])
                        if r["x7_over_x30_same_sign"]["median"] is not None else "—",
                        100 * (r["neg30_also_neg7_frac"] or 0), r["neg30_n"]))
    L.append("")
    L.append("[表4] 库内内核 vs 参考实现")
    for k in kern:
        L.append("  %-7s H=%-2d n=%-4d 库内中位=%-9s 参考中位=%-9s 中位差=%+.3fpp | 逐位相同=%d/%d | max|diff|=%.4f"
                 % (k["kind"], k["horizon"], k["n"], pct(k["median_db"]), pct(k["median_mine"]),
                    k["median_diff_pp"], k["n_bit_identical"], k["n"], k["max_abs_diff"]))
    L.append("")
    L.append("[表4b] 参考实现自带的 forward(bar 口径 + coin 篮子)vs 库内内核")
    for k in bar_ref:
        L.append("  %-7s H=%-2d n=%-4d 库内中位=%-9s 参考中位=%-9s 中位差=%+.3fpp | 逐位相同=%d/%d | 中位|diff|=%.4f max|diff|=%.4f"
                 % (k["kind"], k["horizon"], k["n"], pct(k["median_db"]), pct(k["median_ref_bar"]),
                    k["median_diff_pp"], k["n_bit_identical"], k["n"],
                    k["median_abs_diff"], k["max_abs_diff"]))
    L.append("")
    L.append("log:")
    L.extend("  " + x for x in LOG)
    with open(OUT_SUM, "w") as f:
        f.write("\n".join(L) + "\n")
    log("summary written: %s" % OUT_SUM)


if __name__ == "__main__":
    sys.exit(main())
