#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T-319 / S-798 —— 固定宇宙(每周市值前 150)重算 S-791 的 P:后半段更强是市场态还是宇宙扩张。

框架逐字照 `docs/research/t312_rebaseline.py`(= t296 / t293 / S-774 / S-776 / S-791 同一套走步与超参):
  P(相位,5 维)= mom7/mom30/vol30/vratio/dd90
  每周一 t;训练只用 d' < t − 30 的行;Ridge alpha 10 带截距;输入=居中百分位;目标 x30;IC=Spearman。
**一个字都不改**,只加一道过滤:
  每个周一 t 只保留当周 `asset_mcap_daily` 市值(取 t 当天,没有则往前 ≤ 3 天)前 150 的币;
  没有市值的不进;不足 150 就用全部并报出;训练集同样过滤(按训练行自己的日期 d 过滤)。

先跑**不过滤**自检:必须复现 S-791 的 P IC 0.096286,对不上先停(不产出结论)。
结果 JSON 的内容指纹用 `apparatus.content_fingerprint` 记 (symbol, d, vec, x30)。

用法:
  python3 t319_fixed_universe.py fetch           # 拉 asset_mcap_daily(只读)→ _t319_mcap.jsonl
  python3 t319_fixed_universe.py run             # 自检 + 固定宇宙走步 → t319_results.json

纪律(S-798):只读库、只算、不改代码、不入库;只报不判;不计试验数。
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
CACHE = HERE / "_t312_asset_flow.jsonl"          # t312 的快照(只读复用,自检要复现 S-791)
META = HERE / "_t312_fetch_meta.json"            # t312 的拉取元数据(随快照一起复用)
MCAP_CACHE = HERE / "_t319_mcap.jsonl"
MCAP_META = HERE / "_t319_mcap_meta.json"
RESULTS = HERE / "t319_results.json"

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

# ── 框架超参:与 t293 / t296 / t312 逐字相同 ─────────────────────────────────
MIN_COINS = 20
ALPHA = 10.0
LAST_WEEK = "2026-11-06"
HALVES_AT = ["2023-01-01", "2024-10-01"]

# ── S-798 新增的唯一一个参数(过滤) ───────────────────────────────────────────
TOP_N = 150
MCAP_LOOKBACK_DAYS = 3

# ── S-791 自检基准(不过滤的 P IC;对不上就停) ───────────────────────────────
S791_P_IC = 0.09628629002352945
S791_P_IC_TOL = 1e-12

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


# ── 拉 asset_mcap_daily(只读;翻页带 order=symbol.asc,d.asc) ─────────────────
def cmd_fetch():
    if not URL or not KEY:
        raise SystemExit("缺 SUPABASE_URL / SUPABASE_KEY")
    base = URL.rstrip("/") + "/rest/v1/"
    body, _ = _get(base + "asset_mcap_daily?select=d&order=d.asc&limit=1", _hdr())
    min_d = json.loads(body)[0]["d"]
    body, _ = _get(base + "asset_mcap_daily?select=d&order=d.desc&limit=1", _hdr())
    max_d = json.loads(body)[0]["d"]
    q = "asset_mcap_daily?select=symbol,d,mcap&order=symbol.asc,d.asc"
    body, hd = _get(base + q + "&limit=1", _hdr({"Prefer": "count=exact", "Range": "0-0"}))
    total = int(hd.get("Content-Range", "").split("/")[-1]) if "/" in hd.get("Content-Range", "") else -1
    page, off, n, seen = 1000, 0, 0, set()
    t0 = time.time()
    fetch_started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with open(MCAP_CACHE, "w") as f:
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
    meta = {"min_d": min_d, "max_d": max_d, "total_expected": total, "n_pulled": n,
            "n_unique": len(seen),
            "fetch_started_utc": fetch_started, "fetched_at_utc": fetch_done,
            "seconds": round(time.time() - t0, 1),
            "cache_file": MCAP_CACHE.name}
    MCAP_META.write_text(json.dumps(meta, indent=2))
    print("拉取完成:", n, "行 →", MCAP_CACHE, flush=True)
    if total >= 0 and n != total:
        print("!! 行数不符,需重跑 fetch", flush=True)


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


def load_mcap(path):
    """asset_mcap_daily → {date: {symbol: mcap}};(symbol,d) 重复取 mcap 最大的一条。"""
    if not path.exists():
        raise SystemExit("市值缓存不存在(%s);先跑 fetch" % path.name)
    by_date = {}
    n, dup, nullmcap = 0, 0, 0
    with open(path) as f:
        for line in f:
            r = json.loads(line)
            m = r.get("mcap")
            if m is None:
                nullmcap += 1
                continue
            m = float(m)
            if not math.isfinite(m):
                nullmcap += 1
                continue
            dct = by_date.setdefault(r["d"], {})
            s = r["symbol"]
            if s in dct:
                dup += 1
                if m > dct[s]:
                    dct[s] = m
            else:
                dct[s] = m
            n += 1
    return by_date, {"rows_used": n, "dup_symbol_date": dup, "null_or_bad_mcap": nullmcap,
                     "n_dates": len(by_date)}


def _load_apparatus():
    import importlib.util
    p = os.path.abspath(os.path.join(str(HERE), "..", "..", "src", "data",
                                     "evaluation", "apparatus.py"))
    spec = importlib.util.spec_from_file_location("apparatus", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── 内容指纹:apparatus.content_fingerprint;origin/main 尚无该函数时的等价镜像 ──
def _canon(v):
    if v is None:
        return None
    if isinstance(v, (bool, np.bool_)):
        return bool(v)
    if isinstance(v, (int, np.integer)):
        return int(v)
    if isinstance(v, (float, np.floating)):
        x = float(v)
        return None if not math.isfinite(x) else format(x, ".12g")
    if isinstance(v, (list, tuple, np.ndarray)):
        return [_canon(x) for x in list(v)]
    return str(v)


def _fp_fallback(rows, fields):
    """镜像主目录本地 apparatus.py 的 content_fingerprint(逐字同 _canon 规则)。"""
    keys = list(fields)
    lines = sorted(json.dumps([_canon(r.get(k)) for k in keys], ensure_ascii=False,
                              separators=(",", ":")) for r in rows)
    h = hashlib.sha256()
    h.update(json.dumps(keys, ensure_ascii=False).encode("utf-8"))
    for ln in lines:
        h.update(b"\n")
        h.update(ln.encode("utf-8"))
    return {"n": len(lines), "fields": keys, "sha256": h.hexdigest()}


def _content_fingerprint(rows, fields):
    try:
        from src.data.evaluation.apparatus import content_fingerprint as _cf
        fp = _cf(rows, fields)
        fp["method"] = "apparatus.content_fingerprint"
        return fp
    except Exception:  # noqa: BLE001 —— origin/main 的 apparatus.py 还没这个函数
        fp = _fp_fallback(rows, fields)
        fp["method"] = "fallback:mirror_of_main_apparatus.content_fingerprint"
        return fp


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


def _fp_rows_flow(path):
    """(symbol, d, vec, x30) 原始行;过滤条件与 load_cache 一致。"""
    rows = []
    with open(path) as f:
        for line in f:
            r = json.loads(line)
            v = r.get("vec")
            if v is None:
                continue
            arr = np.fromstring(v.strip().strip("[]"), sep=",", dtype=np.float64)
            if arr.size != 11 or not np.isfinite(arr).all():
                continue
            rows.append({"symbol": r["symbol"], "d": r["d"], "vec": v, "x30": r.get("x30")})
    return rows


def _build_universe(dat, sym, mcap_by_date):
    """每个周一 d 的固定宇宙:市值前 150(取 d 当天,没有则往前 ≤ 3 天)。"""
    allowed, stats = {}, {}
    for ds in sorted(set(dat.tolist())):
        base = dt.date.fromisoformat(ds)
        best = {}
        for k in range(0, MCAP_LOOKBACK_DAYS + 1):
            dk = (base - dt.timedelta(days=k)).isoformat()
            for s, m in (mcap_by_date.get(dk) or {}).items():
                if s not in best:          # k 从 0 起 ⇒ 先到先得 = 日期最近的那条
                    best[s] = m
        ordered = sorted(best.items(), key=lambda kv: (-kv[1], kv[0]))
        keep = [s for s, _ in ordered[:TOP_N]]
        allowed[ds] = set(keep)
        stats[ds] = {"n_mcap_avail": len(best), "n_universe": len(keep),
                     "short_of_top_n": len(best) < TOP_N}
    return allowed, stats


def cmd_run(flow_cache=None, mcap_cache=None):
    from scipy.stats import spearmanr
    from sklearn.linear_model import Ridge
    ap = _load_apparatus()
    path = Path(flow_cache) if flow_cache else CACHE
    mpath = Path(mcap_cache) if mcap_cache else MCAP_CACHE
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

    mcap_by_date, mcap_stat = load_mcap(mpath)
    print("市值缓存 %s  用掉 %d 行 / %d 天(重复 %d,mcap 缺失 %d)"
          % (mpath.name, mcap_stat["rows_used"], mcap_stat["n_dates"],
             mcap_stat["dup_symbol_date"], mcap_stat["null_or_bad_mcap"]), flush=True)

    allowed, ustats = _build_universe(dat, sym, mcap_by_date)
    keep = np.zeros(len(dat), dtype=bool)
    for ds, st in allowed.items():
        if not st:
            continue
        m = dat == ds
        keep[m] = np.isin(sym[m], np.asarray(sorted(st), dtype=sym.dtype))
    n_keep = int(keep.sum())
    print("固定宇宙:保留行 %d/%d (%.1f%%)  周数 %d"
          % (n_keep, len(dat), 100.0 * n_keep / max(1, len(dat)), len(allowed)), flush=True)

    weeks_all = _mondays("2023-01-02", LAST_WEEK)
    starts = np.searchsorted(dat, np.array(weeks_all), side="left")
    ends = np.searchsorted(dat, np.array(weeks_all), side="right")

    VAR = {"R": IDX_A, "P": IDX_P}
    weeks_all_used = _mondays("2023-01-02", LAST_WEEK)

    def _walk(use_filter):
        rows = {k: [] for k in VAR}
        spread = {k: [] for k in VAR}
        bot = {k: [] for k in VAR}
        weeks_used, y_store, sym_store = [], [], []
        n_coins, n_coins_raw, n_univ = [], [], []
        dropped = {"no_rows": 0, "thin": 0, "thin_train": 0}
        # ── 走步(逐字照 t296 cmd_run 的循环) ────────────────────────────────
        for wi, t in enumerate(weeks_all):
            lo, hi = int(starts[wi]), int(ends[wi])
            if hi <= lo:
                dropped["no_rows"] += 1
                continue
            idx = np.arange(lo, hi)
            if use_filter:
                idx = idx[keep[idx]]
                if idx.size == 0:
                    dropped["thin"] += 1
                    continue
            us = idx[np.isfinite(y[idx])]
            if us.size < MIN_COINS:
                dropped["thin"] += 1
                continue
            cut = int(np.searchsorted(dat, _minus30(t), side="left"))
            tr = np.flatnonzero(np.isfinite(y[:cut]))
            if use_filter:
                tr = tr[keep[tr]]
            if tr.size < 100:
                dropped["thin_train"] += 1
                continue
            yu = y[us]
            for key, cols in VAR.items():
                ridge = Ridge(alpha=ALPHA).fit(X[tr][:, cols], y[tr])
                p = ridge.predict(X[idx][:, cols])
                # 不过滤时 idx 连续 ⇒ us − idx[0] 就是下标;过滤后 idx 不连续,
                # 改用「us 在 idx 里的位置」(idx 已升序)。两条路径同一行代码。
                pu = p[np.searchsorted(idx, us)]
                rows[key].append(float(spearmanr(pu, yu).statistic))
                srt = np.argsort(pu, kind="stable")
                k5 = max(1, len(srt) // 5)
                spread[key].append(float(yu[srt[-k5:]].mean() - yu[srt[:k5]].mean()))
                bot[key].append(float(yu[srt[:k5]].mean()))
            weeks_used.append(t)
            y_store.append(yu)
            sym_store.append(sym[us])
            n_coins.append(int(us.size))
            n_coins_raw.append(int(us.size))
            n_univ.append(int(len(allowed.get(t, ())) if use_filter else -1))
            if len(weeks_used) % 40 == 0:
                print("  [%s] %s  周数 %d" % ("fixed" if use_filter else "raw", t,
                                             len(weeks_used)), flush=True)
        return {"rows": rows, "spread": spread, "bot": bot,
                "weeks": np.asarray(weeks_used), "n_coins": np.asarray(n_coins),
                "n_univ": np.asarray(n_univ), "dropped": dropped}

    # ── 自检:不过滤必须复现 S-791 的 P IC 0.096286 ──────────────────────────
    raw = _walk(False)
    halves_raw = ap.windows(list(raw["weeks"]), HALVES_AT)
    raw_p = _summ(raw["rows"]["P"], raw["spread"]["P"], raw["bot"]["P"], halves_raw)
    print("自检(不过滤)P IC=%.12f  基准=%.12f  Δ=%.3g"
          % (raw_p["ic_mean"], S791_P_IC, raw_p["ic_mean"] - S791_P_IC), flush=True)
    self_check_ok = abs(raw_p["ic_mean"] - S791_P_IC) <= S791_P_IC_TOL
    if not self_check_ok:
        raise SystemExit("自检失败:不过滤 P IC %.12f ≠ S-791 基准 %.12f;停止。"
                         % (raw_p["ic_mean"], S791_P_IC))
    print("自检通过(Δ ≤ %.0e)。" % S791_P_IC_TOL, flush=True)

    # ── 固定宇宙跑 ──────────────────────────────────────────────────────────
    fx = _walk(True)
    halves = ap.windows(list(fx["weeks"]), HALVES_AT)

    res = {"task": "T-319", "ledger": "S-798",
           "framework": {"source": "docs/research/t312_rebaseline.py (= t296 / t293 / S-774 / S-776 / S-791)",
                         "params_unchanged": True, "alpha": ALPHA,
                         "min_coins_per_week": MIN_COINS, "last_week": LAST_WEEK,
                         "halves_at": HALVES_AT,
                         "dims": {"R": DIMS, "P": P_DIMS},
                         "added_filter": {"top_n_by_mcap": TOP_N,
                                          "mcap_source": "asset_mcap_daily",
                                          "asof": "当天,没有则往前 ≤ %d 天" % MCAP_LOOKBACK_DAYS,
                                          "no_mcap": "不进",
                                          "fewer_than_top_n": "用全部并报出",
                                          "train_rows_filtered": True,
                                          "train_filter_key": "训练行自己的日期 d"}},
           "sample": {"n_weeks": int(len(fx["weeks"])), "first": str(fx["weeks"][0]),
                      "last": str(fx["weeks"][-1]),
                      "n_weeks_unfiltered": int(len(raw["weeks"])),
                      "weeks_dropped_by_filter": fx["dropped"]},
           "self_check": {"vec_vs_2q_minus_1_max_abs_diff": vec_chk,
                          "n_rows_with_vec": int(len(dat)),
                          "unfiltered_P_ic_mean": raw_p["ic_mean"],
                          "unfiltered_P_ic_expected": S791_P_IC,
                          "unfiltered_P_ic_delta": raw_p["ic_mean"] - S791_P_IC,
                          "passed": bool(self_check_ok)},
           "arms": {}, "paired_ic_diff": {}}

    for key in ("R", "P"):
        res["arms"][key] = _summ(fx["rows"][key], fx["spread"][key], fx["bot"][key], halves)
        hlist = res["arms"][key]["halves"]
        for hh, (_label, mask) in zip(hlist, halves):
            idx = np.flatnonzero(np.asarray(mask))
            if len(idx):
                hh["bottom_quintile_x30"] = float(np.mean([fx["bot"][key][i] for i in idx]))
                hh["bottom_quintile_x30_median"] = float(np.median([fx["bot"][key][i] for i in idx]))
                hh["q5_minus_q1_x30"] = float(np.mean([fx["spread"][key][i] for i in idx]))
        res["arms"][key]["unfiltered"] = _summ(raw["rows"][key], raw["spread"][key],
                                                raw["bot"][key], halves_raw)

    # ── 两半差距(S-798 的读法量;只报) ─────────────────────────────────────
    p = res["arms"]["P"]
    h1, h2 = p["halves"][0]["ic_mean"], p["halves"][1]["ic_mean"]
    gap = (h2 - h1) if (h1 is not None and h2 is not None) else None
    pu = p["unfiltered"]["halves"]
    gap_unf = (pu[1]["ic_mean"] - pu[0]["ic_mean"]) if (pu[0]["ic_mean"] is not None
                                                       and pu[1]["ic_mean"] is not None) else None
    res["halves_gap"] = {
        "P_fixed_universe": gap,
        "P_unfiltered": gap_unf,
        "R_fixed_universe": (res["arms"]["R"]["halves"][1]["ic_mean"]
                             - res["arms"]["R"]["halves"][0]["ic_mean"]),
        "R_unfiltered": (res["arms"]["R"]["unfiltered"]["halves"][1]["ic_mean"]
                         - res["arms"]["R"]["unfiltered"]["halves"][0]["ic_mean"]),
        "read_rule_preregistered": ("后半−前半 ≥ 0.05 ⇒ 更像市场态;收到 0.03 以内 ⇒ 主要是宇宙扩张。"
                                    "只报不判:这里只给数与落在哪一档,不下判定。"),
        "lands_in_preregistered_band": ("market_state(≥0.05)" if (gap is not None and gap >= 0.05)
                                        else ("universe_expansion(≤0.03)" if (gap is not None and gap <= 0.03)
                                              else "in_between(0.03,0.05)"))}

    # ── 每周币数 ────────────────────────────────────────────────────────────
    nc = np.asarray(fx["n_coins"], dtype=float)
    nu = np.asarray(fx["n_univ"], dtype=float)
    res["weekly_coins"] = {
        "fixed_universe_n_coins_with_x30": {
            "mean": float(nc.mean()) if nc.size else None,
            "median": float(np.median(nc)) if nc.size else None,
            "min": float(nc.min()) if nc.size else None,
            "max": float(nc.max()) if nc.size else None,
            "p25": float(np.percentile(nc, 25)) if nc.size else None,
            "p75": float(np.percentile(nc, 75)) if nc.size else None},
        "fixed_universe_n_symbols_in_top150": {
            "mean": float(nu.mean()) if nu.size else None,
            "median": float(np.median(nu)) if nu.size else None,
            "min": float(nu.min()) if nu.size else None,
            "max": float(nu.max()) if nu.size else None},
        "unfiltered_n_coins_with_x30": {
            "mean": float(np.mean(raw["n_coins"])) if raw["n_coins"].size else None,
            "median": float(np.median(raw["n_coins"])) if raw["n_coins"].size else None,
            "min": float(np.min(raw["n_coins"])) if raw["n_coins"].size else None,
            "max": float(np.max(raw["n_coins"])) if raw["n_coins"].size else None},
        "weeks_where_mcap_universe_below_top_n": int(sum(1 for v in ustats.values()
                                                         if v["short_of_top_n"])),
        "dates_with_mcap_coverage": len(ustats),
        "mcap_coverage_per_flow_date": {
            "n_mcap_avail_mean": float(np.mean([v["n_mcap_avail"] for v in ustats.values()])),
            "n_mcap_avail_min": int(min(v["n_mcap_avail"] for v in ustats.values())),
            "n_mcap_avail_max": int(max(v["n_mcap_avail"] for v in ustats.values())),
            "flow_dates_with_zero_mcap": int(sum(1 for v in ustats.values()
                                                 if v["n_mcap_avail"] == 0)),
            "flow_dates_with_mcap_below_top_n": int(sum(1 for v in ustats.values()
                                                        if v["short_of_top_n"]))},
        "per_week": [{"week": str(w), "n_coins": int(a), "n_universe": int(b)}
                     for w, a, b in zip(fx["weeks"], fx["n_coins"], fx["n_univ"])],
        "per_week_unfiltered": [{"week": str(w), "n_coins": int(a)}
                                for w, a in zip(raw["weeks"], raw["n_coins"])],
        "per_half_mean_coins": {
            "fixed_h1": float(np.mean([a for w, a in zip(fx["weeks"], fx["n_coins"])
                                       if w < HALVES_AT[1]])),
            "fixed_h2": float(np.mean([a for w, a in zip(fx["weeks"], fx["n_coins"])
                                       if w >= HALVES_AT[1]])),
            "unfiltered_h1": float(np.mean([a for w, a in zip(raw["weeks"], raw["n_coins"])
                                            if w < HALVES_AT[1]])),
            "unfiltered_h2": float(np.mean([a for w, a in zip(raw["weeks"], raw["n_coins"])
                                            if w >= HALVES_AT[1]]))}}

    # ── 配对 IC 差(R − P;只报,不判) + 逐周 IC 序列(供审计) ───────────────────
    diff = np.asarray(fx["rows"]["R"], dtype=float) - np.asarray(fx["rows"]["P"], dtype=float)
    t, m, se = _nw_t(diff, lags=5)
    res["paired_ic_diff"]["R_minus_P"] = {
        "mean": m, "nw_t_lag5": t, "nw_se": se, "n_weeks": int(len(diff)),
        "prop_positive": float((diff > 0).mean())}
    res["weekly_ic"] = {"weeks": [str(x) for x in fx["weeks"]],
                        "R": [float(x) for x in fx["rows"]["R"]],
                        "P": [float(x) for x in fx["rows"]["P"]],
                        "R_bottom_quintile_x30": [float(x) for x in fx["bot"]["R"]],
                        "P_bottom_quintile_x30": [float(x) for x in fx["bot"]["P"]],
                        "P_unfiltered": [float(x) for x in raw["rows"]["P"]]}

    # ── 内容指纹 ────────────────────────────────────────────────────────────
    fp_rows = _fp_rows_flow(path)
    fp_fields = ["symbol", "d", "vec", "x30"]
    res["content_fingerprint"] = {
        "flow_unfiltered": _content_fingerprint(fp_rows, fp_fields),
        "flow_fixed_universe": _content_fingerprint(
            [{"symbol": r["symbol"], "d": r["d"], "vec": r["vec"], "x30": r["x30"]}
             for r in fp_rows
             if (r["d"] in allowed and r["symbol"] in allowed[r["d"]])], fp_fields),
        "mcap": _content_fingerprint(
            [{"symbol": s, "d": ds, "mcap": m}
             for ds, dct in sorted(mcap_by_date.items()) for s, m in sorted(dct.items())],
            ["symbol", "d", "mcap"]),
        "fields": fp_fields}

    meta = json.loads(META.read_text()) if (META.exists() and path == CACHE) else None
    res["snapshot_fingerprint"] = _fingerprint(path, D, meta)
    mmeta = json.loads(MCAP_META.read_text()) if MCAP_META.exists() else None
    res["mcap_snapshot"] = {"cache_file": mpath.name,
                            "rows_used": mcap_stat["rows_used"],
                            "dup_symbol_date": mcap_stat["dup_symbol_date"],
                            "null_or_bad_mcap": mcap_stat["null_or_bad_mcap"],
                            "n_dates": mcap_stat["n_dates"],
                            "fetched_at_utc": (mmeta or {}).get("fetched_at_utc"),
                            "fetch_seconds": (mmeta or {}).get("seconds"),
                            "min_d": (mmeta or {}).get("min_d"),
                            "max_d": (mmeta or {}).get("max_d")}
    print("内容指纹:", json.dumps(res["content_fingerprint"]["flow_fixed_universe"],
                                  ensure_ascii=False), flush=True)
    for key in ("R", "P"):
        a = res["arms"][key]
        print("%s: IC=%.6f t=%.3f 两半=%s bot=%.6f bot中位=%.6f Q5-Q1=%.6f"
              % (key, a["ic_mean"], a.get("nw_t_lag5", float("nan")),
                 [round(h["ic_mean"], 4) for h in a["halves"]],
                 a.get("bottom_quintile_x30", float("nan")),
                 a.get("bottom_quintile_x30_median", float("nan")),
                 a.get("q5_minus_q1_x30", float("nan"))), flush=True)
    print("两半差距 P: 固定宇宙 %.6f / 不过滤 %.6f"
          % (gap, res["halves_gap"]["P_unfiltered"]), flush=True)

    RESULTS.write_text(json.dumps(res, ensure_ascii=False, indent=2))
    print("结果写入", RESULTS.name, flush=True)


if __name__ == "__main__":
    _ap = argparse.ArgumentParser()
    _ap.add_argument("cmd", choices=["fetch", "run"])
    _ap.add_argument("--cache", default=None)
    _ap.add_argument("--mcap", default=None)
    _a = _ap.parse_args()
    if _a.cmd == "fetch":
        cmd_fetch()
    else:
        cmd_run(_a.cache, _a.mcap)
