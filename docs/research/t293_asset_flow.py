#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T-293 / S-774 —— 按币资金面空间(asset_flow_daily,11 维)的横截面排序力。

K 臂(近邻)/ R 臂(Ridge 11 维)/ B 基线(Ridge 只用 mom30),走步样本外。

用法(脚本改同一个文件再跑):
  python3 t293_asset_flow.py fetch   # 一次拉全表 → docs/research/_t293_asset_flow.jsonl
  python3 t293_asset_flow.py check   # 本地 numpy 近邻 vs RPC asset_flow_knn,20 个 (币, 周一)
  python3 t293_asset_flow.py run     # 三臂走步 + 指标 + 零分布 → docs/research/t293_results.json

纪律(S-774):只读库、只算、不改代码、不做 DDL、不入库;零分布只走 src/data/evaluation/apparatus.py。
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
CACHE = HERE / "_t293_asset_flow.jsonl"
META = HERE / "_t293_fetch_meta.json"
RESULTS = HERE / "t293_results.json"

URL = os.environ.get("SUPABASE_URL")
KEY = os.environ.get("SUPABASE_KEY")

# vec 的维序 = migrations/2026-11-07_asset_flow_daily.sql 里 array[...] 的顺序
DIMS = ["fund7", "doi7", "crowd", "smart", "taker7", "mom7", "mom30",
        "vol30", "vratio", "turn", "dd90"]
QCOLS = ["q_" + d for d in DIMS]
SEL = ",".join(["symbol", "d", "vec", "x30", "n_cs"] + QCOLS)


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


def _rpc(fn, payload):
    url = URL.rstrip("/") + "/rest/v1/rpc/" + fn
    body, _ = _get(url, _hdr({"Content-Type": "application/json"}))
    return json.loads(body)


def _post_rpc(fn, payload, tries=4, timeout=180):
    url = URL.rstrip("/") + "/rest/v1/rpc/" + fn
    data = json.dumps(payload).encode()
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, data=data, method="POST",
                                         headers=_hdr({"Content-Type": "application/json"}))
            with urllib.request.urlopen(req, timeout=timeout) as f:
                return json.loads(f.read().decode())
        except urllib.error.HTTPError as e:
            last = "HTTP %s: %s" % (e.code, e.read().decode()[:200])
            time.sleep(2 * (i + 1))
        except Exception as e:  # noqa: BLE001
            last = repr(e)
            time.sleep(2 * (i + 1))
    raise SystemExit("RPC 失败 %s :: %s" % (fn, last))


# ── fetch:一次拉全表 ─────────────────────────────────────────────────────────
def cmd_fetch():
    if not URL or not KEY:
        raise SystemExit("缺 SUPABASE_URL / SUPABASE_KEY")
    base = URL.rstrip("/") + "/rest/v1/"
    body, _ = _get(base + "asset_flow_daily?select=d&order=d.desc&limit=1", _hdr())
    max_d = json.loads(body)[0]["d"]
    print("快照最大日 max_d =", max_d, flush=True)

    q = ("asset_flow_daily?select=%s&d=lte.%s&order=symbol.asc,d.asc"
         % (SEL, max_d))
    body, hd = _get(base + q + "&limit=1", _hdr({"Prefer": "count=exact", "Range": "0-0"}))
    cr = hd.get("Content-Range", "")
    total = int(cr.split("/")[-1]) if "/" in cr else -1
    print("总行数 total =", total, flush=True)

    page = 1000
    off = 0
    n = 0
    seen = set()
    dup = 0
    t0 = time.time()
    with open(CACHE, "w") as f:
        while off < total:
            b, h = _get(base + q, _hdr({"Prefer": "count=exact",
                                        "Range": "%d-%d" % (off, off + page - 1)}))
            rows = json.loads(b)
            if not rows:
                break
            for r in rows:
                k = (r["symbol"], r["d"])
                if k in seen:
                    dup += 1
                seen.add(k)
                f.write(json.dumps(r, separators=(",", ":")) + "\n")
                n += 1
            off += len(rows)
            if off % 20000 == 0 or off >= total:
                print("  %d/%d 行  %.0fs" % (off, total, time.time() - t0), flush=True)
            if len(rows) < page:
                break
    meta = {"max_d": max_d, "total_expected": total, "n_pulled": n,
            "n_unique": len(seen), "n_dup": dup,
            "fetched_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "seconds": round(time.time() - t0, 1)}
    META.write_text(json.dumps(meta, indent=2))
    print("拉取完成:", json.dumps(meta, ensure_ascii=False), flush=True)
    if total >= 0 and n != total:
        print("!! 行数不符(可能期间视图被刷新),需重跑 fetch", flush=True)


# ── 本地数据装载 ─────────────────────────────────────────────────────────────
def load_cache():
    import numpy as np
    sym, dat, vec, x30, ncs, qs = [], [], [], [], [], []
    with open(CACHE) as f:
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
    import numpy as np  # noqa: F811
    X = np.asarray(vec, dtype=np.float64)
    return {
        "sym": np.asarray(sym),
        "dat": np.asarray(dat),
        "X": X,
        "y": np.asarray([np.nan if v is None else float(v) for v in x30]),
        "ncs": np.asarray(ncs, dtype=np.float64),
        "Q": np.asarray([[np.nan if q is None else float(q) for q in row] for row in qs],
                        dtype=np.float64),
    }


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


def cmd_check():
    """本地 numpy 近邻 vs RPC asset_flow_knn:20 个 (币, 周一)。"""
    import numpy as np
    D = load_cache()
    dat = D["dat"]
    order = np.argsort(dat, kind="stable")
    dat_s = dat[order]
    X = D["X"][order]
    y = D["y"][order]
    sym_s = D["sym"][order]
    ncs = D["ncs"][order]

    max_t = max(ds for ds, yy in zip(dat_s, y) if yy == yy)
    weeks = _mondays("2023-01-02", max_t)
    # 20 个 (币, 周一):每 9 周取一周,该周宇宙里第 5 个币(确定性)
    picks = []
    for i in range(0, len(weeks), max(1, len(weeks) // 20)):
        t = weeks[i]
        m = np.flatnonzero(dat_s == t)
        if m.size < 5:
            continue
        picks.append((sym_s[m[(i * 7 + 4) % m.size]], t))
        if len(picks) >= 20:
            break
    print("对照对:", picks, flush=True)

    res = []
    for s, t in picks:
        qm = np.flatnonzero((dat_s == t) & (sym_s == s))
        if qm.size != 1:
            print("  跳过", s, t, "查询行不唯一", flush=True)
            continue
        q = X[qm[0]]
        cut = t  # d' < t - 30
        elig = np.flatnonzero((dat_s < cut) & np.isfinite(y))
        # d' < t-30 的切点(dat_s 已排序 ⇒ 前 pos 行即 d' < t-30)
        pos = int(np.searchsorted(dat_s[elig], _minus30(t)))
        elig = elig[:pos]
        d2 = ((X[elig] - q) ** 2).sum(axis=1)
        order_e = np.argsort(d2, kind="stable")[:100]
        local = {(sym_s[elig[j]], dat_s[elig[j]]) for j in order_e}
        rpc = _post_rpc("asset_flow_knn", {"p_symbol": s, "p_d": t, "p_k": 100, "p_h": 30})
        rs = {(r["symbol"], r["d"]) for r in rpc}
        ov = len(local & rs)
        res.append({"symbol": s, "d": t, "n_local": len(local), "n_rpc": len(rs),
                    "overlap": ov, "overlap_pct": round(ov / max(1, len(rs)), 4)})
        print("  %-10s %s  重合 %d/%d  (%.1f%%)" % (s, t, ov, len(rs),
                                                    100 * ov / max(1, len(rs))), flush=True)
    pct = [r["overlap_pct"] for r in res]
    summary = {"n_pairs": len(res), "mean_overlap_pct": round(float(np.mean(pct)), 4) if pct else None,
               "min_overlap_pct": round(float(np.min(pct)), 4) if pct else None,
               "all_ge_95pct": bool(pct and min(pct) >= 0.95),
               "pairs": res}
    (HERE / "_t293_knn_check.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps({k: v for k, v in summary.items() if k != "pairs"}, ensure_ascii=False),
          flush=True)


def cmd_mcap():
    """只报项用:asset_mcap_daily 的 (symbol, d, mcap) —— 只拉周一(市值分档)。"""
    if not URL or not KEY:
        raise SystemExit("缺 SUPABASE_URL / SUPABASE_KEY")
    base = URL.rstrip("/") + "/rest/v1/"
    body, hd = _get(base + "asset_mcap_daily?select=d&order=d.desc&limit=1",
                    _hdr({"Prefer": "count=exact"}))
    body2, hd2 = _get(base + "asset_mcap_daily?select=d&order=d.asc&limit=1",
                      _hdr({"Prefer": "count=exact"}))
    d_last = json.loads(body)[0]["d"]
    d_first = json.loads(body2)[0]["d"]
    total = int(hd.get("Content-Range", "0/0").split("/")[-1])
    print("asset_mcap_daily: %s → %s  总行数 %d" % (d_first, d_last, total), flush=True)
    if d_first > "2023-01-02":
        print("覆盖不足(起点晚于样本),市值分档做不了", flush=True)
        return
    weeks = _mondays("2023-01-02", d_last)
    out = HERE / "_t293_mcap.jsonl"
    n = 0
    t0 = time.time()
    with open(out, "w") as f:
        for i in range(0, len(weeks), 30):
            chunk = weeks[i:i + 30]
            q = ("asset_mcap_daily?select=symbol,d,mcap&d=in.(%s)&order=symbol.asc,d.asc"
                 % ",".join(chunk))
            off = 0
            while True:
                b, h = _get(base + q, _hdr({"Range": "%d-%d" % (off, off + 999)}))
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


def _minus30(t):
    import datetime as dt
    return (dt.date.fromisoformat(t) - dt.timedelta(days=30)).isoformat()


def _load_apparatus():
    import importlib.util
    p = os.path.abspath(os.path.join(str(HERE), "..", "..", "src", "data", "evaluation", "apparatus.py"))
    spec = importlib.util.spec_from_file_location("apparatus", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _nw_t(x, lags=5):
    """Newey-West t( Bartlett 权重)—— 与 S-774 写的「NW t(滞后 5)」一致。"""
    import math
    import numpy as np
    x = np.asarray(x, dtype=float)
    n = len(x)
    d = x - x.mean()
    var = float((d @ d) / n)
    for l in range(1, lags + 1):
        gl = float((d[l:] @ d[:-l]) / n)
        var += 2.0 * (1.0 - l / (lags + 1.0)) * gl
    se = math.sqrt(max(var, 1e-24) / n)
    return float(x.mean() / se), float(x.mean()), float(se)


def _summ(ic, spread, bot, weeks, halves, ap):
    import numpy as np  # noqa: F811
    ic = np.asarray(ic, dtype=float)
    out = {"n_weeks": int(len(ic)), "ic_mean": float(ic.mean()) if len(ic) else None}
    if len(ic):
        t, m, se = _nw_t(ic, lags=5)
        out.update({"nw_t_lag5": t, "nw_se": se, "prop_positive": float((ic > 0).mean())})
    if len(spread):
        out["q5_minus_q1_x30"] = float(np.mean(spread))
        out["bottom_quintile_x30"] = float(np.mean(bot))
    # 两半(2023-01 → 2024-09 / 2024-10 → 末)
    h = []
    for label, idx in halves:
        sub = ic[idx] if len(idx) else np.asarray([])
        h.append({"half": label, "n_weeks": int(len(sub)),
                  "ic_mean": float(sub.mean()) if len(sub) else None})
    out["halves"] = h
    out["halves_both_positive"] = bool(len(h) == 2 and all(
        (x["ic_mean"] is not None and x["ic_mean"] > 0) for x in h))
    return out


def cmd_run():
    import math
    import numpy as np
    from scipy.stats import spearmanr, rankdata
    from scipy.spatial import cKDTree
    from sklearn.linear_model import Ridge
    ap = _load_apparatus()
    D = load_cache()
    sym, dat, X, y, ncs = D["sym"], D["dat"], D["X"], D["y"], D["ncs"]
    o = np.lexsort((sym, dat))
    sym, dat, X, y, ncs = sym[o], dat[o], X[o], y[o], ncs[o]
    Q = D["Q"][o]
    vec_chk = float(np.abs(X - (2.0 * Q - 1.0).astype(np.float32).astype(np.float64)).max())
    print("行数(vec 非空)=%d  vec vs 2q-1 最大差=%.3g" % (len(dat), vec_chk), flush=True)

    weeks_all = _mondays("2023-01-02", "2026-11-06")
    starts = np.searchsorted(dat, np.array(weeks_all), side="left")
    ends = np.searchsorted(dat, np.array(weeks_all), side="right")

    MIN_COINS = 20
    rows = {"K": [], "R": [], "B": [], "K30": [], "K300": []}
    dims_ic = {d: [] for d in DIMS}
    weeks_used, spread = [], {"K": [], "R": [], "B": []}
    bot = {"K": [], "R": [], "B": []}
    ncs_at = []
    cluster_counts = []
    pred_store = {"K": [], "R": [], "B": []}
    y_store, w_store, sym_store = [], [], []

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
        tree = cKDTree(X[tr])
        K = 100
        kk = min(K, tr.size)
        _, nb = tree.query(X[idx], k=kk)
        nb = np.atleast_2d(nb)
        predK = y[tr][nb].mean(axis=1)
        # 只报项:近邻的独立簇数(币 × 月)
        if kk >= K:
            nb_s = sym[tr][nb]
            nb_m = dat[tr][nb]
            for a in range(nb.shape[0]):
                cluster_counts.append(len(set(zip(nb_s[a].tolist(),
                                                 [m[:7] for m in nb_m[a].tolist()]))))
        # 只报项:k = 30 / 300
        for kk2, key in ((30, "K30"), (300, "K300")):
            if tr.size >= kk2:
                _, nb2 = tree.query(X[idx], k=kk2)
                rows[key].append(float(spearmanr(
                    y[tr][np.atleast_2d(nb2)].mean(axis=1)[us - idx[0]], y[us]).statistic))
        # R 臂 / B 基线
        ridge = Ridge(alpha=10.0).fit(X[tr], y[tr])
        predR = ridge.predict(X[idx])
        ridgeB = Ridge(alpha=10.0).fit(X[tr][:, [6]], y[tr])
        predB = ridgeB.predict(X[idx][:, [6]]).ravel()
        predK_u = predK[us - idx[0]]
        predR_u = predR[us - idx[0]]
        predB_u = predB[us - idx[0]]
        yu = y[us]
        icK = float(spearmanr(predK_u, yu).statistic)
        icR = float(spearmanr(predR_u, yu).statistic)
        icB = float(spearmanr(predB_u, yu).statistic)
        rows["K"].append(icK)
        rows["R"].append(icR)
        rows["B"].append(icB)
        for d, j in zip(DIMS, range(11)):
            dims_ic[d].append(float(spearmanr(X[us][:, j], yu).statistic))
        for key, p in (("K", predK_u), ("R", predR_u), ("B", predB_u)):
            srt = np.argsort(p, kind="stable")
            k5 = max(1, len(srt) // 5)
            b = yu[srt[:k5]]
            tp = yu[srt[-k5:]]
            spread[key].append(float(tp.mean() - b.mean()))
            bot[key].append(float(b.mean()))
        weeks_used.append(t)
        ncs_at.append(float(np.median(ncs[idx])))
        pred_store["K"].append(predK_u)
        pred_store["R"].append(predR_u)
        pred_store["B"].append(predB_u)
        y_store.append(yu)
        sym_store.append(sym[us])
        w_store.append(np.full(len(yu), t, dtype=object))
        if len(weeks_used) % 20 == 0:
            print("  %s  周数 %d" % (t, len(weeks_used)), flush=True)

    weeks_used = np.asarray(weeks_used)
    y_all = np.concatenate(y_store)
    w_all = np.concatenate(w_store)
    print("样本周 %d  起 %s  末 %s" % (len(weeks_used), weeks_used[0], weeks_used[-1]), flush=True)

    halves = ap.windows(list(weeks_used), ["2023-01-01", "2024-10-01"])
    res = {"task": "T-293", "ledger": "S-774",
           "sample": {"n_weeks": int(len(weeks_used)), "first": str(weeks_used[0]),
                      "last": str(weeks_used[-1]), "min_coins_per_week": MIN_COINS},
           "self_check": {"vec_vs_2q_minus_1_max_abs_diff": vec_chk,
                          "n_rows_with_vec": int(len(dat)),
                          "vec_dim_order": DIMS},
           "arms": {}}
    for key in ("K", "R", "B"):
        res["arms"][key] = _summ(rows[key], spread[key], bot[key], weeks_used, halves, ap)
    # IC − B 的 IC(配对)
    for key in ("K", "R"):
        diff = np.asarray(rows[key], dtype=float) - np.asarray(rows["B"], dtype=float)
        t, m, se = _nw_t(diff, lags=5)
        res["arms"][key]["ic_minus_b"] = {"mean": m, "nw_t_lag5": t, "nw_se": se,
                                         "n_weeks": int(len(diff))}
    # 零分布:周内打乱预测 1,000 次(种子 774)
    for key in ("K", "R", "B"):
        preds = np.concatenate(pred_store[key])
        actual = float(np.mean(rows[key]))
        masks = [(np.flatnonzero(w_all == w)) for w in weeks_used]
        ry = [rankdata(y_all[m]) for m in masks]

        def null_stat(rng, preds=preds, masks=masks, ry=ry):
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
            null = ap.null_distribution(null_stat, 1000, 774, actual=actual)
            pct = ap.percentile_of(actual, null)
            res["arms"][key]["shuffle_null"] = {"n": 1000, "seed": 774,
                                                "percentile": pct,
                                                "null_mean": float(np.mean(null)),
                                                "null_sd": float(np.std(null))}
        except Exception as e:  # noqa: BLE001
            res["arms"][key]["shuffle_null"] = {"n": 1000, "seed": 774, "error": str(e)}
        print("%s: IC=%.4f t=%.2f 零分位=%s" % (key, res["arms"][key]["ic_mean"],
                                                 res["arms"][key].get("nw_t_lag5", float("nan")),
                                                 res["arms"][key]["shuffle_null"].get("percentile")),
              flush=True)
    # 只报不判
    res["report_only"] = {
        "per_dim_ic_mean": {d: float(np.mean(v)) for d, v in dims_ic.items()},
        "knn_k30_ic_mean": float(np.mean(rows["K30"])) if rows["K30"] else None,
        "knn_k300_ic_mean": float(np.mean(rows["K300"])) if rows["K300"] else None,
        "neighbor_cluster_median": float(np.median(cluster_counts)) if cluster_counts else None,
        "n_cs_tercile_ic": _ncs_buckets(weeks_used, ncs_at, rows["K"]),
        "mcap_tercile_ic": _mcap_buckets(weeks_used, sym_store, pred_store, y_store, rows),
    }
    # 判定
    res["verdict"] = {}
    for key in ("K", "R"):
        a = res["arms"][key]
        v = {"ic_gt0_and_nw_ge2": bool(a["ic_mean"] > 0 and a.get("nw_t_lag5", -99) >= 2.0),
             "ic_minus_b_gt0_and_nw_ge1.5": bool(a["ic_minus_b"]["mean"] > 0
                                                 and a["ic_minus_b"]["nw_t_lag5"] >= 1.5),
             "halves_both_positive": a["halves_both_positive"],
             "shuffle_pct_ge_0.95": bool((a["shuffle_null"].get("percentile") or 0) >= 0.95)}
        v["PASS"] = bool(all(v.values()))
        res["verdict"][key] = v
    RESULTS.write_text(json.dumps(res, indent=2, ensure_ascii=False))
    print("结果写入", RESULTS, flush=True)


def _mcap_buckets(weeks, sym_store, pred_store, y_store, rows):
    """只报项:按市值三分档的每周 IC(每个周内按当日市值切三档)。"""
    import numpy as np
    from scipy.stats import spearmanr
    p = HERE / "_t293_mcap.jsonl"
    if not p.exists():
        return {"error": "无 _t293_mcap.jsonl"}
    mcap = {}
    with open(p) as f:
        for line in f:
            r = json.loads(line)
            m = r.get("mcap")
            if m is None:
                continue
            k = (r["symbol"], r["d"])
            if k not in mcap or m > mcap[k]:
                mcap[k] = m
    out = {"note": "asset_mcap_daily 按 (symbol,d) 取当日最大市值;周内三分档"}
    for key in ("K", "R"):
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


def _ncs_buckets(weeks, ncs_at, ic):
    import numpy as np
    ncs_at = np.asarray(ncs_at, dtype=float)
    ic = np.asarray(ic, dtype=float)
    if len(ncs_at) == 0:
        return {}
    q1, q2 = np.percentile(ncs_at, [33.3, 66.7])
    out = {}
    for name, m in (("low_n_cs", ncs_at <= q1), ("mid_n_cs", (ncs_at > q1) & (ncs_at <= q2)),
                    ("high_n_cs", ncs_at > q2)):
        out[name] = {"n_weeks": int(m.sum()), "ic_mean": float(ic[m].mean()) if m.any() else None,
                     "n_cs_range": [float(ncs_at[m].min()), float(ncs_at[m].max())] if m.any() else None}
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["fetch", "check", "run", "mcap"])
    a = ap.parse_args()
    if a.cmd == "fetch":
        cmd_fetch()
    elif a.cmd == "check":
        cmd_check()
    elif a.cmd == "mcap":
        cmd_mcap()
    else:
        cmd_run()
