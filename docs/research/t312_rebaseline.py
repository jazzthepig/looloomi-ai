#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T-312 / S-791 —— 在今天的 `asset_flow_daily` 快照上重算 S-774 的 R(11 维)与 S-776 的 P(价格相位)。

框架逐字照 `docs/research/t296_ablation.py`(= t293 / S-774 / S-776 同一套走步与超参):
  R(=A,11 维)= fund7/doi7/crowd/smart/taker7/mom7/mom30/vol30/vratio/turn/dd90
  P(相位,5 维)= mom7/mom30/vol30/vratio/dd90
  每周一 t;训练只用 d' < t − 30 的行;Ridge alpha 10 带截距;输入=居中百分位;目标 x30;IC=Spearman。
只换快照(今天的),不改任何参数;结果 JSON 带快照指纹(行数、币数、首末日期、拉取时间)。

用法:
  python3 t312_rebaseline.py fetch                # 拉今天的快照(只读)→ _t312_asset_flow.jsonl
  python3 t312_rebaseline.py run                  # 走步 → t312_results.json
  python3 t312_rebaseline.py run --cache <path>   # 指定缓存跑(用于同框架换缓存对照)

纪律(S-791):只读库、只算、不改代码、不入库;只报不判;不改 S-774 / S-776 的判定。
"""
import argparse
import datetime as dt
import hashlib
import json
import math
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
CACHE = HERE / "_t312_asset_flow.jsonl"
META = HERE / "_t312_fetch_meta.json"
RESULTS = HERE / "t312_results.json"

URL = os.environ.get("SUPABASE_URL")
KEY = os.environ.get("SUPABASE_KEY")

# vec 的维序 = migrations/2026-11-07_asset_flow_daily.sql 里 array[...] 的顺序
DIMS = ["fund7", "doi7", "crowd", "smart", "taker7", "mom7", "mom30",
        "vol30", "vratio", "turn", "dd90"]
P_DIMS = ["mom7", "mom30", "vol30", "vratio", "dd90"]
IDX_P = [DIMS.index(d) for d in P_DIMS]
IDX_A = list(range(len(DIMS)))
QCOLS = ["q_" + d for d in DIMS]
SEL = ",".join(["symbol", "d", "vec", "x30", "n_cs"] + QCOLS)

# ── 框架超参:与 t293 / t296 逐字相同 ────────────────────────────────────────
MIN_COINS = 20
ALPHA = 10.0
LAST_WEEK = "2026-11-06"
HALVES_AT = ["2023-01-01", "2024-10-01"]

# ── 已发表的旧快照基线(供对照,不改) ─────────────────────────────────────────
S774_R_PUB = {
    "ic_mean": 0.10063970161006076,
    "nw_t_lag5": 4.992452094168978,
    "n_weeks": 197,
    "q5_minus_q1_x30": 0.04273600705368608,
    "bottom_quintile_x30": -0.02074471883444584,
    "halves": [0.028834929106088803, 0.16355435942306473],
}


# ── HTTP(只读;逐字照 t296) ──────────────────────────────────────────────────
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


# ── 拉今天的快照(逐字照 t296 的 cmd_fetch;只换路径 + 加快照指纹) ─────────────
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
    fetch_started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
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
            if off % 50000 == 0 or off >= total:
                print("  %d/%d 行  %.0fs" % (off, total, time.time() - t0), flush=True)
            if len(rows) < page:
                break
    fetch_done = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    meta = {"max_d": max_d, "total_expected": total, "n_pulled": n,
            "n_unique": len(seen),
            "fetch_started_utc": fetch_started, "fetched_at_utc": fetch_done,
            "seconds": round(time.time() - t0, 1),
            "cache_file": CACHE.name}
    META.write_text(json.dumps(meta, indent=2))
    print("拉取完成:", n, "行 →", CACHE, flush=True)
    if total >= 0 and n != total:
        print("!! 行数不符(视图可能已刷新),需重跑 fetch", flush=True)


# ── 本地装载(逐字照 t296 的 load_cache;只换路径) ────────────────────────────
def load_cache(path):
    if not path.exists():
        raise SystemExit("缓存不存在(%s);先跑 fetch" % path.name)
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
    p = os.path.abspath(os.path.join(str(HERE), "..", "..", "src", "data",
                                     "evaluation", "apparatus.py"))
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
    """逐字照 t296 的 _summ;另加 bot 的中位与分位(只报项,不改任何判定量)。"""
    ic = np.asarray(ic, dtype=float)
    out = {"n_weeks": int(len(ic)), "ic_mean": float(ic.mean()) if len(ic) else None}
    if len(ic):
        t, m, se = _nw_t(ic, lags=5)
        out.update({"nw_t_lag5": t, "nw_se": se, "prop_positive": float((ic > 0).mean())})
    if spread:
        out["q5_minus_q1_x30"] = float(np.mean(spread))
        out["bottom_quintile_x30"] = float(np.mean(bot))
        b = np.asarray(bot, dtype=float)
        out["bottom_quintile_x30_median"] = float(np.median(b))
        out["bottom_quintile_x30_p25"] = float(np.percentile(b, 25))
        out["bottom_quintile_x30_p75"] = float(np.percentile(b, 75))
        s = np.asarray(spread, dtype=float)
        out["q5_minus_q1_x30_median"] = float(np.median(s))
    h = []
    for label, idx in halves:
        sub = ic[idx] if len(idx) else np.asarray([])
        h.append({"half": label, "n_weeks": int(len(sub)),
                  "ic_mean": float(sub.mean()) if len(sub) else None})
    out["halves"] = h
    out["halves_both_positive"] = bool(len(h) == 2 and all(
        (x["ic_mean"] is not None and x["ic_mean"] > 0) for x in h))
    return out


def _mondays(d0, d1):
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
    return (dt.date.fromisoformat(t) - dt.timedelta(days=30)).isoformat()


def _fingerprint(path, D, meta):
    coins = sorted(set(D["sym"].tolist()))
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return {"cache_file": path.name,
            "rows_total_in_db": (meta or {}).get("total_expected"),
            "rows_with_vec": int(len(D["dat"])),
            "n_coins": len(coins),
            "first_date": min(D["dat"].tolist()) if len(D["dat"]) else None,
            "last_date": max(D["dat"].tolist()) if len(D["dat"]) else None,
            "fetched_at_utc": (meta or {}).get("fetched_at_utc"),
            "fetch_started_utc": (meta or {}).get("fetch_started_utc"),
            "fetch_seconds": (meta or {}).get("seconds"),
            "max_d_in_db": (meta or {}).get("max_d"),
            "cache_sha256": h.hexdigest()}


def cmd_run(cache_path=None):
    from scipy.stats import spearmanr
    from sklearn.linear_model import Ridge
    ap = _load_apparatus()
    path = Path(cache_path) if cache_path else CACHE
    D = load_cache(path)
    sym, dat, X, y, ncs = D["sym"], D["dat"], D["X"], D["y"], D["ncs"]
    o = np.lexsort((sym, dat))
    sym, dat, X, y, ncs = sym[o], dat[o], X[o], y[o], ncs[o]
    Q = D["Q"][o]
    vec_chk = float(np.abs(X - (2.0 * Q - 1.0).astype(np.float32).astype(np.float64)).max())
    print("缓存 %s  行数(vec 非空)=%d  币 %d  日期 %s → %s  vec vs 2q-1 最大差=%.3g"
          % (D["path"], len(dat), len(set(sym.tolist())),
             min(dat.tolist()), max(dat.tolist()), vec_chk),
          flush=True)

    weeks_all = _mondays("2023-01-02", LAST_WEEK)
    starts = np.searchsorted(dat, np.array(weeks_all), side="left")
    ends = np.searchsorted(dat, np.array(weeks_all), side="right")

    VAR = {"R": IDX_A, "P": IDX_P}
    rows = {k: [] for k in VAR}
    spread = {k: [] for k in VAR}
    bot = {k: [] for k in VAR}
    weeks_used, y_store, sym_store = [], [], []

    # ── 走步(逐字照 t296 cmd_run 的循环) ────────────────────────────────────
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
            srt = np.argsort(pu, kind="stable")
            k5 = max(1, len(srt) // 5)
            spread[key].append(float(yu[srt[-k5:]].mean() - yu[srt[:k5]].mean()))
            bot[key].append(float(yu[srt[:k5]].mean()))
        weeks_used.append(t)
        y_store.append(yu)
        sym_store.append(sym[us])
        if len(weeks_used) % 40 == 0:
            print("  %s  周数 %d" % (t, len(weeks_used)), flush=True)

    weeks_used = np.asarray(weeks_used)
    print("样本周 %d  起 %s  末 %s" % (len(weeks_used), weeks_used[0], weeks_used[-1]), flush=True)

    halves = ap.windows(list(weeks_used), HALVES_AT)
    res = {"task": "T-312", "ledger": "S-791",
           "framework": {"source": "docs/research/t296_ablation.py (= t293 / S-774 / S-776)",
                         "params_unchanged": True, "alpha": ALPHA,
                         "min_coins_per_week": MIN_COINS, "last_week": LAST_WEEK,
                         "halves_at": HALVES_AT,
                         "dims": {"R": DIMS, "P": P_DIMS}},
           "sample": {"n_weeks": int(len(weeks_used)), "first": str(weeks_used[0]),
                      "last": str(weeks_used[-1])},
           "self_check": {"vec_vs_2q_minus_1_max_abs_diff": vec_chk,
                          "n_rows_with_vec": int(len(dat))},
           "arms": {}, "paired_ic_diff": {}}
    for key in ("R", "P"):
        res["arms"][key] = _summ(rows[key], spread[key], bot[key], halves)
        hlist = res["arms"][key]["halves"]
        for hh, (_label, mask) in zip(hlist, halves):
            idx = np.flatnonzero(np.asarray(mask))
            if len(idx):
                hh["bottom_quintile_x30"] = float(np.mean([bot[key][i] for i in idx]))
                hh["bottom_quintile_x30_median"] = float(np.median([bot[key][i] for i in idx]))
                hh["q5_minus_q1_x30"] = float(np.mean([spread[key][i] for i in idx]))

    # ── 对照:旧快照已发表的数 ────────────────────────────────────────────────
    r = res["arms"]["R"]
    res["compare_published_S774_R_old_snapshot"] = {
        "reference": S774_R_PUB,
        "recomputed_now": {"ic_mean": r["ic_mean"], "nw_t_lag5": r.get("nw_t_lag5"),
                           "n_weeks": r["n_weeks"],
                           "q5_minus_q1_x30": r.get("q5_minus_q1_x30"),
                           "bottom_quintile_x30": r.get("bottom_quintile_x30"),
                           "halves": [h["ic_mean"] for h in r["halves"]]},
        "delta_ic_mean": r["ic_mean"] - S774_R_PUB["ic_mean"],
        "delta_nw_t": r.get("nw_t_lag5", float("nan")) - S774_R_PUB["nw_t_lag5"],
        "delta_bottom_quintile": r.get("bottom_quintile_x30", float("nan")) - S774_R_PUB["bottom_quintile_x30"]}
    p_arm = res["arms"]["P"]
    res["compare_published_S776_P_old_snapshot"] = {
        "reference_ic_mean": 0.111847, "recomputed_ic_mean": p_arm["ic_mean"],
        "delta_ic_mean": p_arm["ic_mean"] - 0.111847}

    # ── 配对 IC 差(R − P;只报,不判) + 逐周 IC 序列(供审计) ───────────────────
    diff = np.asarray(rows["R"], dtype=float) - np.asarray(rows["P"], dtype=float)
    t, m, se = _nw_t(diff, lags=5)
    res["paired_ic_diff"]["R_minus_P"] = {
        "mean": m, "nw_t_lag5": t, "nw_se": se, "n_weeks": int(len(diff)),
        "prop_positive": float((diff > 0).mean())}
    res["weekly_ic"] = {"weeks": [str(x) for x in weeks_used],
                        "R": [float(x) for x in rows["R"]],
                        "P": [float(x) for x in rows["P"]],
                        "R_bottom_quintile_x30": [float(x) for x in bot["R"]],
                        "P_bottom_quintile_x30": [float(x) for x in bot["P"]]}
    meta = json.loads(META.read_text()) if (META.exists() and path == CACHE) else None
    res["snapshot_fingerprint"] = _fingerprint(path, D, meta)
    print("快照指纹:", json.dumps(res["snapshot_fingerprint"], ensure_ascii=False), flush=True)
    for key in ("R", "P"):
        a = res["arms"][key]
        print("%s: IC=%.6f t=%.3f 两半=%s bot=%.6f bot中位=%.6f Q5-Q1=%.6f"
              % (key, a["ic_mean"], a.get("nw_t_lag5", float("nan")),
                 [round(h["ic_mean"], 4) for h in a["halves"]],
                 a.get("bottom_quintile_x30", float("nan")),
                 a.get("bottom_quintile_x30_median", float("nan")),
                 a.get("q5_minus_q1_x30", float("nan"))), flush=True)

    if path == CACHE:
        RESULTS.write_text(json.dumps(res, ensure_ascii=False, indent=2))
        print("结果写入", RESULTS.name, flush=True)
    else:
        alt = HERE / (path.stem + "_run.json")
        alt.write_text(json.dumps(res, ensure_ascii=False, indent=2))
        print("结果写入", alt.name, flush=True)


if __name__ == "__main__":
    _ap = argparse.ArgumentParser()
    _ap.add_argument("cmd", choices=["fetch", "run"])
    _ap.add_argument("--cache", default=None)
    _a = _ap.parse_args()
    if _a.cmd == "fetch":
        cmd_fetch()
    else:
        cmd_run(_a.cache)
