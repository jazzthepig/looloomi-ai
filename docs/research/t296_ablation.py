#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T-296 / S-776 —— S-774 的力量从哪来:6 个「因」维 / 5 个价格相位维 / 全部 11 维。

三个 Ridge 走步(与 S-774 同一份数据、同一个走步、同一套超参):
  F(因)  = fund7 / doi7 / crowd / smart / taker7 / turn   (6 维)
  P(相位)= mom7 / mom30 / vol30 / vratio / dd90            (5 维)
  A(全部)= 11 维(= S-774 的 R 臂;自检须复算到 1e-6)

判只判 F(IC 均值 > 0 且 NW t ≥ 2;两半都 > 0;周内打乱 1,000 次种子 776 分位 ≥ 0.95;
且 IC(A) − IC(P) > 0、配对 NW t ≥ 1.5)。只报:各子集最低五分位、市值三档、两半、
F 里逐一去掉一维的 IC。

用法:
  python3 t296_ablation.py run      # 走步 + 指标 + 零分布 → docs/research/t296_results.json
  python3 t296_ablation.py fetch    # 缓存缺失时拉一份(只读);优先复用 t293 的缓存

纪律(S-776):只读库、只算、不改代码、不入库;零分布只走 src/data/evaluation/apparatus.py;
NW t 留在本脚本内(挪进 apparatus 由 Seth 做)。
"""
import argparse
import json
import math
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
CACHE_REUSE = HERE / "_t293_asset_flow.jsonl"
CACHE = HERE / "_t296_asset_flow.jsonl"
MCAP_REUSE = HERE / "_t293_mcap.jsonl"
MCAP = HERE / "_t296_mcap.jsonl"
META = HERE / "_t296_fetch_meta.json"
RESULTS = HERE / "t296_results.json"

URL = os.environ.get("SUPABASE_URL")
KEY = os.environ.get("SUPABASE_KEY")

# vec 的维序 = migrations/2026-11-07_asset_flow_daily.sql 里 array[...] 的顺序
DIMS = ["fund7", "doi7", "crowd", "smart", "taker7", "mom7", "mom30",
        "vol30", "vratio", "turn", "dd90"]
F_DIMS = ["fund7", "doi7", "crowd", "smart", "taker7", "turn"]
P_DIMS = ["mom7", "mom30", "vol30", "vratio", "dd90"]
IDX_F = [DIMS.index(d) for d in F_DIMS]
IDX_P = [DIMS.index(d) for d in P_DIMS]
IDX_A = list(range(len(DIMS)))
QCOLS = ["q_" + d for d in DIMS]
SEL = ",".join(["symbol", "d", "vec", "x30", "n_cs"] + QCOLS)

# S-774 的 R 臂(t293_results.json;台账 S-774 结果段)—— A 必须复算到 1e-6
S774_R = {
    "ic_mean": 0.10063970161006076,
    "nw_t_lag5": 4.992452094168978,
    "n_weeks": 197,
    "q5_minus_q1_x30": 0.04273600705368608,
    "bottom_quintile_x30": -0.02074471883444584,
    "halves": [0.028834929106088803, 0.16355435942306473],
}

MIN_COINS = 20
ALPHA = 10.0
LAST_WEEK = "2026-11-06"
HALVES_AT = ["2023-01-01", "2024-10-01"]


# ── HTTP(只读) ────────────────────────────────────────────────────────────────
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
            with urllib.request.urlopen(req, timeout=timeout) as f:
                return f.read().decode(), dict(f.headers)
        except urllib.error.HTTPError as e:
            last = "HTTP %s: %s" % (e.code, e.read().decode()[:200])
            time.sleep(2 * (i + 1))
        except Exception as e:  # noqa: BLE001
            last = repr(e)
            time.sleep(2 * (i + 1))
    raise SystemExit("取数失败 %s :: %s" % (url[:200], last))


def _mondays(d0, d1):
    import datetime as dt
    a = dt.date.fromisoformat(d0)
    b = dt.date.fromisoformat(d1)
    while a.weekday() != 0:
        a += dt.timedelta(days=1)
    out = []
    while a <= b:
        out.append(a.isoformat())
        a += dt.timedelta(days=7)
    return out


def _minus30(t):
    import datetime as dt
    return (dt.date.fromisoformat(t) - dt.timedelta(days=30)).isoformat()


def cmd_fetch():
    if not URL or not KEY:
        raise SystemExit("缺 SUPABASE_URL / SUPABASE_KEY")
    base = URL.rstrip("/") + "/rest/v1/"
    body, _ = _get(base + "asset_flow_daily?select=d&order=d.desc&limit=1", _hdr())
    max_d = json.loads(body)[0]["d"]
    q = ("asset_flow_daily?select=%s&d=lte.%s&order=symbol.asc,d.asc" % (SEL, max_d))
    body, hd = _get(base + q + "&limit=1", _hdr({"Prefer": "count=exact", "Range": "0-0"}))
    total = int(hd.get("Content-Range", "").split("/")[-1]) if "/" in hd.get("Content-Range", "") else -1
    page, off, n, seen = 1000, 0, 0, set()
    t0 = time.time()
    with open(CACHE, "w") as f:
        while off < total:
            b, _h = _get(base + q, _hdr({"Prefer": "count=exact",
                                         "Range": "%d-%d" % (off, off + page - 1)}))
            rows = json.loads(b)
            if not rows:
                break
            for r in rows:
                seen.add((r["symbol"], r["d"]))
                f.write(json.dumps(r, separators=(",", ":")) + "\n")
                n += 1
            off += len(rows)
            if off % 20000 == 0 or off >= total:
                print("  %d/%d 行  %.0fs" % (off, total, time.time() - t0), flush=True)
            if len(rows) < page:
                break
    META.write_text(json.dumps({"max_d": max_d, "total_expected": total, "n_pulled": n,
                                "n_unique": len(seen),
                                "fetched_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                "seconds": round(time.time() - t0, 1)}, indent=2))
    print("拉取完成:", n, "行 →", CACHE, flush=True)
    if total >= 0 and n != total:
        print("!! 行数不符(视图可能已刷新),需重跑 fetch", flush=True)


def cmd_fetch_mcap():
    """只报项:asset_mcap_daily 的 (symbol, d, mcap) —— 只拉周一。"""
    if not URL or not KEY:
        raise SystemExit("缺 SUPABASE_URL / SUPABASE_KEY")
    base = URL.rstrip("/") + "/rest/v1/"
    body, hd = _get(base + "asset_mcap_daily?select=d&order=d.desc&limit=1",
                    _hdr({"Prefer": "count=exact"}))
    body2, _hd2 = _get(base + "asset_mcap_daily?select=d&order=d.asc&limit=1",
                       _hdr({"Prefer": "count=exact"}))
    d_last = json.loads(body)[0]["d"]
    d_first = json.loads(body2)[0]["d"]
    print("asset_mcap_daily: %s → %s" % (d_first, d_last), flush=True)
    weeks = _mondays("2023-01-02", d_last)
    n, t0 = 0, time.time()
    with open(MCAP, "w") as f:
        for i in range(0, len(weeks), 30):
            chunk = weeks[i:i + 30]
            q = ("asset_mcap_daily?select=symbol,d,mcap&d=in.(%s)&order=symbol.asc,d.asc"
                 % ",".join(chunk))
            off = 0
            while True:
                b, _h = _get(base + q, _hdr({"Range": "%d-%d" % (off, off + 999)}))
                rows = json.loads(b)
                if not rows:
                    break
                for r in rows:
                    f.write(json.dumps(r, separators=(",", ":")) + "\n")
                    n += 1
                off += len(rows)
                if len(rows) < 1000:
                    break
    print("mcap 拉取 %d 行 %.0fs" % (n, time.time() - t0), flush=True)


# ── 本地数据装载 ─────────────────────────────────────────────────────────────
def load_cache():
    path = CACHE_REUSE if CACHE_REUSE.exists() else CACHE
    if not path.exists():
        raise SystemExit("缓存不存在(%s / %s);先跑 fetch" % (CACHE_REUSE.name, CACHE.name))
    sym, dat, vec, x30, ncs, qs = [], [], [], [], [], []
    with open(path) as f:
        for line in f:
            r = json.loads(line)
            v = r.get("vec")
            if v is None:
                continue
            arr = np.fromstring(v.strip().strip("[]"), sep=",", dtype=np.float64)
            if arr.size != 11 or not np.isfinite(arr).all():
                continue
            sym.append(r["symbol"])
            dat.append(r["d"])
            vec.append(arr)
            x30.append(r.get("x30"))
            ncs.append(r.get("n_cs") or 0)
            qs.append([r.get(c) for c in QCOLS])
    X = np.asarray(vec, dtype=np.float64)
    return {"path": path.name,
            "sym": np.asarray(sym), "dat": np.asarray(dat), "X": X,
            "y": np.asarray([np.nan if v is None else float(v) for v in x30]),
            "ncs": np.asarray(ncs, dtype=np.float64),
            "Q": np.asarray([[np.nan if q is None else float(q) for q in row] for row in qs],
                            dtype=np.float64)}


def _load_apparatus():
    import importlib.util
    p = os.path.abspath(os.path.join(str(HERE), "..", "..", "src", "data", "evaluation", "apparatus.py"))
    spec = importlib.util.spec_from_file_location("apparatus", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _nw_t(x, lags=5):
    """Newey-West t(Bartlett)—— 与 S-774 写的「NW t(滞后 5)」一致。留在本脚本内。"""
    x = np.asarray(x, dtype=float)
    n = len(x)
    d = x - x.mean()
    var = float((d @ d) / n)
    for l in range(1, lags + 1):
        gl = float((d[l:] @ d[:-l]) / n)
        var += 2.0 * (1.0 - l / (lags + 1.0)) * gl
    se = math.sqrt(max(var, 1e-24) / n)
    return float(x.mean() / se), float(x.mean()), float(se)


def _summ(ic, spread, bot, halves):
    ic = np.asarray(ic, dtype=float)
    out = {"n_weeks": int(len(ic)), "ic_mean": float(ic.mean()) if len(ic) else None}
    if len(ic):
        t, m, se = _nw_t(ic, lags=5)
        out.update({"nw_t_lag5": t, "nw_se": se, "prop_positive": float((ic > 0).mean())})
    if spread:
        out["q5_minus_q1_x30"] = float(np.mean(spread))
        out["bottom_quintile_x30"] = float(np.mean(bot))
    h = []
    for label, idx in halves:
        sub = ic[idx] if len(idx) else np.asarray([])
        h.append({"half": label, "n_weeks": int(len(sub)),
                  "ic_mean": float(sub.mean()) if len(sub) else None})
    out["halves"] = h
    out["halves_both_positive"] = bool(len(h) == 2 and all(
        (x["ic_mean"] is not None and x["ic_mean"] > 0) for x in h))
    return out


def _mcap_map():
    path = MCAP_REUSE if MCAP_REUSE.exists() else MCAP
    mcap = {}
    if not path.exists():
        return None
    with open(path) as f:
        for line in f:
            r = json.loads(line)
            m = r.get("mcap")
            if m is None:
                continue
            k = (r["symbol"], r["d"])
            if k not in mcap or m > mcap[k]:
                mcap[k] = m
    return mcap


def _mcap_buckets(weeks, sym_store, pred_store, y_store, rows, mcap):
    """只报项:每周按当日市值切三档后的 IC。"""
    from scipy.stats import spearmanr
    if mcap is None:
        return {"error": "无市值缓存"}
    out = {"note": "asset_mcap_daily 按 (symbol,d) 取当日最大市值;周内三分档"}
    for key in ("F", "P", "A"):
        buckets = {"low_mcap": [], "mid_mcap": [], "high_mcap": []}
        for wi, t in enumerate(weeks):
            sy = sym_store[wi]
            mc = np.array([mcap.get((s, t), np.nan) for s in sy], dtype=float)
            ok = np.isfinite(mc)
            if ok.sum() < 30:
                continue
            q1, q2 = np.percentile(mc[ok], [33.3, 66.7])
            yu = y_store[wi]
            pu = pred_store[key][wi]
            for name, m in (("low_mcap", ok & (mc <= q1)),
                            ("mid_mcap", ok & (mc > q1) & (mc <= q2)),
                            ("high_mcap", ok & (mc > q2))):
                if int(m.sum()) >= 10:
                    buckets[name].append(float(spearmanr(pu[m], yu[m]).statistic))
        out[key] = {b: {"n_weeks": len(v), "ic_mean": float(np.mean(v)) if v else None}
                    for b, v in buckets.items()}
    return out


def _shuffle_pct(preds, w_all, y_all, weeks_used, actual, ap, seed=776, n=1000):
    """周内打乱预测的零分布(分位)。只走 apparatus。"""
    from scipy.stats import rankdata
    preds = np.concatenate(preds)
    masks = [np.flatnonzero(w_all == w) for w in weeks_used]
    ry = [rankdata(y_all[m]) for m in masks]

    def null_stat(rng):
        sh = ap.shuffle_within(preds, w_all, rng)
        rs = []
        for m, r in zip(masks, ry):
            a = rankdata(sh[m])
            a0 = a - a.mean()
            r0 = r - r.mean()
            den = math.sqrt(float(a0 @ a0) * float(r0 @ r0))
            if den == 0:
                continue
            rs.append(float((a0 @ r0) / den))
        return float(np.mean(rs)) if rs else float("nan")

    try:
        null = ap.null_distribution(null_stat, n, seed, actual=actual)
        return {"n": n, "seed": seed, "percentile": ap.percentile_of(actual, null),
                "null_mean": float(np.mean(null)), "null_sd": float(np.std(null)),
                "null_max": float(np.max(null))}
    except Exception as e:  # noqa: BLE001
        return {"n": n, "seed": seed, "error": str(e)}


def cmd_run():
    from scipy.stats import spearmanr
    from sklearn.linear_model import Ridge
    ap = _load_apparatus()
    D = load_cache()
    sym, dat, X, y, ncs = D["sym"], D["dat"], D["X"], D["y"], D["ncs"]
    o = np.lexsort((sym, dat))
    sym, dat, X, y, ncs = sym[o], dat[o], X[o], y[o], ncs[o]
    Q = D["Q"][o]
    vec_chk = float(np.abs(X - (2.0 * Q - 1.0).astype(np.float32).astype(np.float64)).max())
    print("缓存 %s  行数(vec 非空)=%d  vec vs 2q-1 最大差=%.3g"
          % (D["path"], len(dat), vec_chk), flush=True)

    weeks_all = _mondays("2023-01-02", LAST_WEEK)
    starts = np.searchsorted(dat, np.array(weeks_all), side="left")
    ends = np.searchsorted(dat, np.array(weeks_all), side="right")

    VAR = {"F": IDX_F, "P": IDX_P, "A": IDX_A}
    rows = {k: [] for k in VAR}
    spread = {k: [] for k in VAR}
    bot = {k: [] for k in VAR}
    pred_store = {k: [] for k in VAR}
    loo = {d: [] for d in F_DIMS}
    weeks_used, y_store, w_store, sym_store = [], [], [], []

    for wi, t in enumerate(weeks_all):
        lo, hi = int(starts[wi]), int(ends[wi])
        if hi <= lo:
            continue
        idx = np.arange(lo, hi)
        us = idx[np.isfinite(y[idx])]
        if us.size < MIN_COINS:
            continue
        cut = int(np.searchsorted(dat, _minus30(t), side="left"))
        tr = np.flatnonzero(np.isfinite(y[:cut]))
        if tr.size < 100:
            continue
        yu = y[us]
        for key, cols in VAR.items():
            ridge = Ridge(alpha=ALPHA).fit(X[tr][:, cols], y[tr])
            p = ridge.predict(X[idx][:, cols])
            pu = p[us - idx[0]]
            rows[key].append(float(spearmanr(pu, yu).statistic))
            pred_store[key].append(pu)
            srt = np.argsort(pu, kind="stable")
            k5 = max(1, len(srt) // 5)
            spread[key].append(float(yu[srt[-k5:]].mean() - yu[srt[:k5]].mean()))
            bot[key].append(float(yu[srt[:k5]].mean()))
        # 只报项:F 里逐一去掉一维
        for d in F_DIMS:
            cols = [c for c in IDX_F if c != IDX_F[F_DIMS.index(d)]]
            r2 = Ridge(alpha=ALPHA).fit(X[tr][:, cols], y[tr])
            p2 = r2.predict(X[idx][:, cols])
            loo[d].append(float(spearmanr(p2[us - idx[0]], yu).statistic))
        weeks_used.append(t)
        y_store.append(yu)
        sym_store.append(sym[us])
        w_store.append(np.full(len(yu), t, dtype=object))
        if len(weeks_used) % 40 == 0:
            print("  %s  周数 %d" % (t, len(weeks_used)), flush=True)

    weeks_used = np.asarray(weeks_used)
    y_all = np.concatenate(y_store)
    w_all = np.concatenate(w_store)
    print("样本周 %d  起 %s  末 %s" % (len(weeks_used), weeks_used[0], weeks_used[-1]), flush=True)

    halves = ap.windows(list(weeks_used), HALVES_AT)
    res = {"task": "T-296", "ledger": "S-776",
           "sample": {"n_weeks": int(len(weeks_used)), "first": str(weeks_used[0]),
                      "last": str(weeks_used[-1]), "min_coins_per_week": MIN_COINS,
                      "alpha": ALPHA, "dims": {"F": F_DIMS, "P": P_DIMS, "A": DIMS}},
           "self_check": {"vec_vs_2q_minus_1_max_abs_diff": vec_chk,
                          "n_rows_with_vec": int(len(dat))},
           "arms": {}}
    for key in ("F", "P", "A"):
        res["arms"][key] = _summ(rows[key], spread[key], bot[key], halves)

    # ── 自检:A(= S-774 的 R)必须复算到 1e-6 ─────────────────────────────────
    a = res["arms"]["A"]
    sc = {"reference": S774_R, "recomputed": {
        "ic_mean": a["ic_mean"], "nw_t_lag5": a.get("nw_t_lag5"),
        "n_weeks": a["n_weeks"], "q5_minus_q1_x30": a.get("q5_minus_q1_x30"),
        "bottom_quintile_x30": a.get("bottom_quintile_x30"),
        "halves": [h["ic_mean"] for h in a["halves"]]}}
    sc["abs_diff_ic_mean"] = abs(a["ic_mean"] - S774_R["ic_mean"])
    sc["abs_diff_nw_t"] = abs(a.get("nw_t_lag5", float("nan")) - S774_R["nw_t_lag5"])
    sc["abs_diff_bottom_quintile"] = abs(a.get("bottom_quintile_x30", float("nan"))
                                          - S774_R["bottom_quintile_x30"])
    sc["within_1e-6"] = bool(sc["abs_diff_ic_mean"] <= 1e-6)
    res["self_check"]["A_vs_S774_R"] = sc
    print("自检 A vs S-774 R: |ΔIC|=%.3g (≤1e-6 ⇒ %s)  |Δt|=%.3g  |Δbot|=%.3g"
          % (sc["abs_diff_ic_mean"], sc["within_1e-6"], sc["abs_diff_nw_t"],
             sc["abs_diff_bottom_quintile"]), flush=True)

    # ── 配对 IC 差(A − P 是判据;F − P / F − A 只报) ───────────────────────────
    res["paired_ic_diff"] = {}
    for x, y in (("A", "P"), ("F", "P"), ("F", "A")):
        diff = np.asarray(rows[x], dtype=float) - np.asarray(rows[y], dtype=float)
        t, m, se = _nw_t(diff, lags=5)
        res["paired_ic_diff"]["%s_minus_%s" % (x, y)] = {
            "mean": m, "nw_t_lag5": t, "nw_se": se, "n_weeks": int(len(diff)),
            "prop_positive": float((diff > 0).mean())}

    # ── 零分布:周内打乱 1,000 次(种子 776) ─────────────────────────────────
    for key in ("F", "P", "A"):
        res["arms"][key]["shuffle_null"] = _shuffle_pct(
            pred_store[key], w_all, y_all, weeks_used,
            float(res["arms"][key]["ic_mean"]), ap, seed=776, n=1000)
        s = res["arms"][key]["shuffle_null"]
        print("%s: IC=%.4f t=%.2f 两半=%s bot=%s 零分位=%s"
              % (key, res["arms"][key]["ic_mean"], res["arms"][key].get("nw_t_lag5", float("nan")),
                 [round(h["ic_mean"], 4) for h in res["arms"][key]["halves"]],
                 round(res["arms"][key].get("bottom_quintile_x30", float("nan")), 4),
                 s.get("percentile")), flush=True)

    # ── 只报项:F 里逐一去掉一维 ──────────────────────────────────────────────
    res["loo_f"] = {}
    for d in F_DIMS:
        t, m, se = _nw_t(loo[d], lags=5)
        res["loo_f"][d] = {"ic_mean": m, "nw_t_lag5": t, "nw_se": se,
                           "n_weeks": len(loo[d]),
                           "delta_vs_full_F": m - res["arms"]["F"]["ic_mean"]}
    # ── 只报项:市值三档 ──────────────────────────────────────────────────────
    res["mcap_tercile_ic"] = _mcap_buckets(weeks_used, sym_store, pred_store, y_store,
                                           rows, _mcap_map())
    # ── 只报项:单维 IC(与 S-774 一致,便于对照) ──────────────────────────────
    res["per_dim_ic_mean"] = {}

    # ── 判定(只判 F) ────────────────────────────────────────────────────────
    f = res["arms"]["F"]
    ap_diff = res["paired_ic_diff"]["A_minus_P"]
    v = {"ic_gt0_and_nw_ge2": bool(f["ic_mean"] > 0 and f.get("nw_t_lag5", -99) >= 2.0),
         "halves_both_positive": f["halves_both_positive"],
         "shuffle_pct_ge_0.95": bool((f["shuffle_null"].get("percentile") or 0) >= 0.95),
         "ic_A_minus_P_gt0_and_nw_ge1.5": bool(ap_diff["mean"] > 0
                                                and ap_diff["nw_t_lag5"] >= 1.5)}
    v["PASS"] = bool(all(v.values()))
    res["verdict"] = {"F": v}
    RESULTS.write_text(json.dumps(res, indent=2, ensure_ascii=False))
    print("判定 F:", json.dumps(v, ensure_ascii=False), flush=True)
    print("结果写入", RESULTS, flush=True)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["fetch", "fetch_mcap", "run"])
    a = ap.parse_args()
    if a.cmd == "fetch":
        cmd_fetch()
    elif a.cmd == "fetch_mcap":
        cmd_fetch_mcap()
    else:
        cmd_run()
