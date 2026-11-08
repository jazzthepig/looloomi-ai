#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""T-311 / S-790 —— 交易所的「决定」+ 被挤空头作为 Asset 空间的事件维,在 S-776 最强的价格相位模型(P)之上有没有排序力。

框架逐字照 S-774 / S-776(t293_asset_flow.py / t296_ablation.py):
  每周一 t(2023-01-02 → 最后一个 x30 已到期的周一);
  宇宙 = asset_flow_daily 有 vec 的币;目标 x30;
  走步 Ridge(alpha=10, 带截距),只用 d' < t − 30 的行训练,输入 = 居中百分位(±1)。
  基线 P = mom7 / mom30 / vol30 / vratio / dd90 五维(S-776 的 P 臂)。
  E = P + 6 个事件维(0/1 → 居中到 ±1):
    ① binance_spot_90   Binance 现货上币公告距 t ≤ 90 天
    ② binance_perp_90   Binance USDT 永续上线公告 ≤ 90 天
    ③ upbit_krw_90      Upbit 韩元上币 ≤ 90 天
    ④ tag_on            t 当天挂着 Binance 监控标签(逐句状态机)
    ⑤ squeeze_30        过去 30 天内有 squeeze 事件
    ⑥ delist_365        过去 365 天内被宣布整币下架

主判(排除的用法):每周 E 的最低五分位 x30 均值 − P 的最低五分位 x30 均值:
  全样本均值 < 0、NW t(滞后 5) ≤ −2、两半都 < 0 ⇒ ✅。
金额判据(S-779 附注):E 的 Q5 − Q1(扣 20 bps) ≥ P 的,且最低五分位均值更低。
副判:IC(E) − IC(P) 均值与配对 NW t。
只报:每维单独加进 P 的边际;每周被事件维标记的币数(稀疏度)。

用法:
  python3 t311_event_dims.py fetch   # 拉缓存(只读):asset_flow_daily + 四张事件表
  python3 t311_event_dims.py run     # 走步 + 指标 + 落 CSV/JSON

纪律:只读库、只算、不改生产代码、不入库;零分布与 NW t 只走 src/data/evaluation/apparatus.py。
"""
import argparse
import bisect
import csv
import datetime as dt
import json
import os
import re
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
CACHE_FLOW = HERE / "_t311_asset_flow.jsonl"
CACHE_BEW = HERE / "_t311_bew.jsonl"
CACHE_CROWD = HERE / "_t311_crowd.jsonl"
CACHE_DEL = HERE / "_t311_delist.jsonl"
CACHE_TAG = HERE / "_t311_tagann.jsonl"
DIMS_CSV = HERE / "t311_events_dims.csv"
RESULTS = HERE / "t311_results.json"

URL = os.environ.get("SUPABASE_URL")
KEY = os.environ.get("SUPABASE_KEY")

# vec 的维序 = migrations/2026-11-07_asset_flow_daily.sql 里 array[...] 的顺序
DIMS = ["fund7", "doi7", "crowd", "smart", "taker7", "mom7", "mom30",
        "vol30", "vratio", "turn", "dd90"]
P_DIMS = ["mom7", "mom30", "vol30", "vratio", "dd90"]
IDX_P = [DIMS.index(d) for d in P_DIMS]
EV_DIMS = ["binance_spot_90", "binance_perp_90", "upbit_krw_90",
           "tag_on", "squeeze_30", "delist_365"]
NEV = len(EV_DIMS)

MIN_COINS = 20
ALPHA = 10.0
LAST_WEEK = "2026-11-06"
HALVES_AT = ["2023-01-01", "2024-10-01"]          # 与 S-776 / t296 同一刀(自检用)
HALVES_AT_S790 = ["2023-01-01", "2025-01-01"]     # S-790 原文写的两半(主判用)
COST_BPS = 20.0

# S-776 的 P 臂(t296_results.json)—— 必须复现到 ±0.002
S776_P = {"ic_mean": 0.111847, "nw_t_lag5": 5.121, "bottom_quintile_x30": -0.024774,
          "q5_minus_q1_x30": 0.046092, "n_weeks": 197, "halves": [0.0266, 0.1865]}


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


def _fetch_all(table, select, order, path, where=None, workers=8):
    """整表拉取:Range 分页 + order= 固定排序 + count=exact 核总行数。"""
    base = URL.rstrip("/") + "/rest/v1/"
    q = "%s?select=%s&order=%s" % (table, select, order)
    if where:
        q += "&" + where
    _b, hd = _get(base + q, _hdr({"Prefer": "count=exact", "Range": "0-0"}))
    cr = hd.get("Content-Range", "")
    total = int(cr.split("/")[-1]) if "/" in cr else 0
    print("  %s 总行数 %d" % (table, total), flush=True)
    page = 1000
    ranges = [(o, min(o + page - 1, total - 1)) for o in range(0, total, page)]

    def one(rng):
        b, _h = _get(base + q, _hdr({"Range": "%d-%d" % rng}))
        return json.loads(b)

    out = []
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for i, rows in enumerate(ex.map(one, ranges)):
            out.extend(rows)
            if (i + 1) % 40 == 0:
                print("    %s %d/%d  %.0fs" % (table, (i + 1) * page, total,
                                              time.time() - t0), flush=True)
    with open(path, "w") as f:
        for r in out:
            f.write(json.dumps(r, separators=(",", ":")) + "\n")
    print("  %s 拉取 %d 行 → %s  %.0fs" % (table, len(out), path.name,
                                          time.time() - t0), flush=True)
    if len(out) != total:
        raise SystemExit("!! %s 行数不符: 拉到 %d / 期望 %d" % (table, len(out), total))
    return out


def cmd_fetch():
    if not URL or not KEY:
        raise SystemExit("缺 SUPABASE_URL / SUPABASE_KEY")
    _fetch_all("asset_flow_daily", "symbol,d,vec,x30", "symbol.asc,d.asc", CACHE_FLOW)
    _fetch_all("binance_event_watch", "symbol,kind,d0,announced_at,title",
               "d0.asc,symbol.asc", CACHE_BEW)
    _fetch_all("crowding_watch", "symbol,d,kind", "d.asc,symbol.asc", CACHE_CROWD)
    _fetch_all("delisting_watch", "symbol,d0,announced_at", "d0.asc,symbol.asc", CACHE_DEL)
    _fetch_all("events", "ts,title", "ts.asc", CACHE_TAG,
               where="source=eq.binance&kind=in.(monitoring_tag,monitoring_tag_removed)",
               workers=1)
    print("缓存齐了:", flush=True)


# ── 监控标签:生产的切句函数 ───────────────────────────────────────────────────
def _load_production_tag_changes():
    """优先用生产 src/data/market/events.py 的 monitoring_tag_changes(合进 main 后自动生效);
    找不到 ⇒ 用与 2026-11-08 待合并版本逐字一致的本地副本。"""
    try:
        import importlib.util
        p = os.path.abspath(os.path.join(str(HERE), "..", "..", "src", "data",
                                         "market", "events.py"))
        spec = importlib.util.spec_from_file_location("prod_events", p)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        fn = getattr(mod, "monitoring_tag_changes", None)
        if fn is not None:
            return fn, "production:src/data/market/events.py"
    except Exception as e:  # noqa: BLE001
        print("  (生产 monitoring_tag_changes 不可用:%s)" % repr(e)[:120], flush=True)
    return _tag_changes_local, "local-copy(与 2026-11-08 待合并的生产版本逐字一致)"


_TAG_REF = re.compile(r"\b(?:the\s+)?(?P<which>monitoring|seed)\s+tags?\b", re.IGNORECASE)
_TAG_VERB = re.compile(r"\b(?P<verb>extend|add|include|remove|update|change)\w*\b", re.IGNORECASE)
_TAG_STOP = {"USDT", "USDC", "BINANCE", "A", "I"}


def _tag_changes_local(title):
    """本地副本:与生产 src/data/market/events.py::monitoring_tag_changes 同逻辑(2026-11-08 版)。"""
    t = str(title or "")
    refs = list(_TAG_REF.finditer(t))
    out = {"add": [], "rem_mon": [], "rem_seed": []}
    last_verb = None
    for i, m in enumerate(refs):
        end = refs[i + 1].start() if i + 1 < len(refs) else len(t)
        start = refs[i - 1].end() if i > 0 else 0
        vs = list(_TAG_VERB.finditer(t, start, m.start()))
        verb = vs[-1].group("verb").lower() if vs else last_verb
        last_verb = verb or last_verb
        seg = re.sub(r"\(?\d{4}-\d{2}-\d{2}\)?", " ", t[m.end():end])
        toks = [x for x in re.findall(r"\b[A-Z0-9]{1,12}\b", seg)
                if not x.isdigit() and x not in _TAG_STOP]
        if m.group("which").lower() == "seed":
            out["rem_seed"] += toks if verb == "remove" else []
        elif verb in ("extend", "add", "include", "update"):
            out["add"] += toks
        elif verb == "remove":
            out["rem_mon"] += toks
    return {k: list(dict.fromkeys(v)) for k, v in out.items()}


# ── 事件源 ────────────────────────────────────────────────────────────────────
def _d(s):
    return str(s)[:10]


def load_events():
    bew = {}
    with open(CACHE_BEW) as f:
        for line in f:
            r = json.loads(line)
            bew.setdefault((r["kind"], r["symbol"]), []).append(_d(r["d0"]))
    for v in bew.values():
        v.sort()

    squeeze = {}
    with open(CACHE_CROWD) as f:
        for line in f:
            r = json.loads(line)
            if r.get("kind") != "squeeze":
                continue
            squeeze.setdefault(r["symbol"], []).append(_d(r["d"]))
    for v in squeeze.values():
        v.sort()

    dele = {}
    with open(CACHE_DEL) as f:
        for line in f:
            r = json.loads(line)
            dele.setdefault(r["symbol"], []).append(_d(r["d0"]))
    for v in dele.values():
        v.sort()

    tag_changes, tag_src = _load_production_tag_changes()
    anns = []
    with open(CACHE_TAG) as f:
        for line in f:
            r = json.loads(line)
            anns.append((_d(r["ts"]), r["title"]))
    anns.sort()
    timeline, n_add, n_rem = {}, 0, 0
    for d0, title in anns:
        ch = tag_changes(title)
        for s in ch.get("add", []):
            timeline.setdefault(s, []).append((d0, 1))
            n_add += 1
        for s in ch.get("rem_mon", []):
            timeline.setdefault(s, []).append((d0, 0))
            n_rem += 1
    for v in timeline.values():
        v.sort()
    tag_state = {s: ([x[0] for x in v], [x[1] for x in v]) for s, v in timeline.items()}
    print("  监控标签:公告 %d 条 / add 行 %d / rem_mon 行 %d / 代币 %d 个(切句源:%s)"
          % (len(anns), n_add, n_rem, len(tag_state), tag_src), flush=True)
    return {"bew": bew, "squeeze": squeeze, "delist": dele, "tag": tag_state,
            "tag_src": tag_src, "n_ann": len(anns)}


def _in_window(dates, lo, hi):
    if not dates:
        return False
    i = bisect.bisect_left(dates, lo)
    return i < len(dates) and dates[i] <= hi


def _tag_on(tag, sym, t):
    st = tag.get(sym)
    if not st:
        return 0
    ds, flags = st
    i = bisect.bisect_right(ds, t) - 1
    return 1 if (i >= 0 and flags[i] == 1) else 0


def build_event_matrix(EV, symbols, dates):
    """→ (n_dates, n_syms, 6) 的 0/1 事件矩阵。"""
    n_d, n_s = len(dates), len(symbols)
    M = np.zeros((n_d, n_s, NEV), dtype=np.int8)
    for di, d0 in enumerate(dates):
        t = dt.date.fromisoformat(d0)
        w90 = (t - dt.timedelta(days=90)).isoformat()
        w30 = (t - dt.timedelta(days=30)).isoformat()
        w365 = (t - dt.timedelta(days=365)).isoformat()
        row = M[di]
        for si, s in enumerate(symbols):
            if _in_window(EV["bew"].get(("listing", s)), w90, d0):
                row[si, 0] = 1
            if _in_window(EV["bew"].get(("perp_listing", s)), w90, d0):
                row[si, 1] = 1
            if _in_window(EV["bew"].get(("upbit_krw_listing", s)), w90, d0):
                row[si, 2] = 1
            if _tag_on(EV["tag"], s, d0):
                row[si, 3] = 1
            if _in_window(EV["squeeze"].get(s), w30, d0):
                row[si, 4] = 1
            if _in_window(EV["delist"].get(s), w365, d0):
                row[si, 5] = 1
    return M


# ── 本地数据装载 ─────────────────────────────────────────────────────────────
def load_flow():
    if not CACHE_FLOW.exists():
        raise SystemExit("缓存不存在(%s);先跑 fetch" % CACHE_FLOW.name)
    sym, dat, vec, x30 = [], [], [], []
    with open(CACHE_FLOW) as f:
        for line in f:
            r = json.loads(line)
            v = r.get("vec")
            if v is None:
                continue
            s = str(v).strip()
            s = s[1:-1] if (s.startswith("{") and s.endswith("}")) else s.strip("[]")
            arr = np.fromstring(s, sep=",", dtype=np.float64)
            if arr.size != len(DIMS) or not np.isfinite(arr).all():
                continue
            sym.append(r["symbol"])
            dat.append(r["d"])
            vec.append(arr)
            x30.append(r.get("x30"))
    X = np.asarray(vec, dtype=np.float64)
    return {"sym": np.asarray(sym), "dat": np.asarray(dat), "X": X,
            "y": np.asarray([np.nan if v is None else float(v) for v in x30])}


def _load_apparatus():
    import importlib.util
    p = os.path.abspath(os.path.join(str(HERE), "..", "..", "src", "data",
                                     "evaluation", "apparatus.py"))
    spec = importlib.util.spec_from_file_location("apparatus", p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _nw_t(x, ap, lags=5):
    return ap.newey_west_t(list(x), lags=lags)


def _halves(series, halves):
    out = []
    for label, mask in halves:
        sub = np.asarray(series)[mask]
        t, m, se = _nw_t(sub, ap_holder[0]) if len(sub) else (None, None, None)
        out.append({"half": label, "n_weeks": int(len(sub)), "mean": m, "nw_t_lag5": t})
    return out


ap_holder = [None]


def _summ(ic, spread, bot, halves, ap):
    ic = np.asarray(ic, dtype=float)
    out = {"n_weeks": int(len(ic)), "ic_mean": float(ic.mean()) if len(ic) else None}
    if len(ic):
        t, m, se = _nw_t(ic, ap)
        out.update({"nw_t_lag5": t, "nw_se": se, "prop_positive": float((ic > 0).mean())})
    if spread:
        out["q5_minus_q1_x30"] = float(np.mean(spread))
        out["q5_minus_q1_x30_after_20bps"] = float(np.mean(spread)) - COST_BPS / 1e4
        out["bottom_quintile_x30"] = float(np.mean(bot))
    h = []
    for label, mask in halves:
        sub = ic[mask] if len(idx_ok(mask, ic)) else np.asarray([])
        t, m, se = _nw_t(sub, ap) if len(sub) else (None, None, None)
        h.append({"half": label, "n_weeks": int(len(sub)), "ic_mean": m,
                  "nw_t_lag5": t,
                  "bottom_quintile_x30": (float(np.mean([bot[i] for i in np.flatnonzero(mask)]))
                                          if int(mask.sum()) else None)})
    out["halves"] = h
    out["halves_both_positive"] = bool(len(h) == 2 and all(
        (x["ic_mean"] is not None and x["ic_mean"] > 0) for x in h))
    return out


def idx_ok(mask, arr):
    return np.flatnonzero(mask) if np.asarray(mask).any() else []


def _load_old_per_dim():
    """S-774 旧快照的单维 IC(t293_results.json);文件不在 ⇒ None。"""
    p = HERE / "t293_results.json"
    if not p.exists():
        return {}
    try:
        d = json.loads(p.read_text())
        return {k: float(v) for k, v in d["report_only"]["per_dim_ic_mean"].items()}
    except Exception:  # noqa: BLE001
        return {}


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


def cmd_run():
    from scipy.stats import spearmanr
    from sklearn.linear_model import Ridge
    ap = _load_apparatus()
    ap_holder[0] = ap

    D = load_flow()
    sym, dat, X, y = D["sym"], D["dat"], D["X"], D["y"]
    o = np.lexsort((sym, dat))
    sym, dat, X, y = sym[o], dat[o], X[o], y[o]
    print("缓存 %s  行数(vec 非空)=%d  币 %d  日期 %s → %s"
          % (CACHE_FLOW.name, len(dat), len(set(sym.tolist())), dat[0], dat[-1]), flush=True)

    EV = load_events()
    symbols = sorted(set(sym.tolist()))
    dates = sorted(set(dat.tolist()))
    M = build_event_matrix(EV, symbols, dates)
    date_ix = {d: i for i, d in enumerate(dates)}
    sym_ix = {s: i for i, s in enumerate(symbols)}
    # 行对齐的事件特征(0/1 → ±1)
    E01 = M[np.array([date_ix[d] for d in dat]),
            np.array([sym_ix[s] for s in sym])]                     # (n_rows, 6)
    Epm = 2.0 * E01.astype(np.float64) - 1.0
    print("事件维矩阵:日期 %d × 币 %d  行对齐 %s" % (len(dates), len(symbols), E01.shape),
          flush=True)

    # 交付物:每周一每币的 6 个 0/1
    with open(DIMS_CSV, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["d", "symbol"] + EV_DIMS)
        for di, d0 in enumerate(dates):
            if dt.date.fromisoformat(d0).weekday() != 0:
                continue
            row = M[di]
            for si, s in enumerate(symbols):
                w.writerow([d0, s] + [int(v) for v in row[si]])
    print("落", DIMS_CSV.name, flush=True)

    weeks_all = _mondays("2023-01-02", LAST_WEEK)
    starts = np.searchsorted(dat, np.array(weeks_all), side="left")
    ends = np.searchsorted(dat, np.array(weeks_all), side="right")

    ARMS = {"P": (list(IDX_P), [])}
    for j, e in enumerate(EV_DIMS):
        ARMS["P+" + e] = (list(IDX_P), [j])
    ARMS["E"] = (list(IDX_P), list(range(NEV)))
    ARMS["A"] = (list(range(len(DIMS))), [])      # 全部 11 维(= S-774 的 R 臂,数据刷新对照)

    rows = {k: [] for k in ARMS}
    spread = {k: [] for k in ARMS}
    bot = {k: [] for k in ARMS}
    dims_ic = {d: [] for d in DIMS}
    weeks_used, y_store = [], []
    bot_diff_series = []
    marked_weeks = []
    coins_per_week = []

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
        for j, d in enumerate(DIMS):
            dims_ic[d].append(float(spearmanr(X[us][:, j], yu).statistic))
        for key in ARMS:
            cidx, ecols = ARMS[key]
            Xtr = X[tr][:, cidx]
            Xp = X[idx][:, cidx]
            if ecols:
                Xtr = np.hstack([Xtr, Epm[tr][:, ecols]])
                Xp = np.hstack([Xp, Epm[idx][:, ecols]])
            ridge = Ridge(alpha=ALPHA).fit(Xtr, y[tr])
            pu = ridge.predict(Xp)
            rows[key].append(float(spearmanr(pu, yu).statistic))
            srt = np.argsort(pu, kind="stable")
            k5 = max(1, len(srt) // 5)
            spread[key].append(float(yu[srt[-k5:]].mean() - yu[srt[:k5]].mean()))
            bot[key].append(float(yu[srt[:k5]].mean()))
        bot_diff_series.append(bot["E"][-1] - bot["P"][-1])
        marked_weeks.append(E01[idx].sum(axis=0))
        coins_per_week.append(int(us.size))
        weeks_used.append(t)
        y_store.append(yu)
        if len(weeks_used) % 40 == 0:
            print("  %s  周数 %d" % (t, len(weeks_used)), flush=True)

    weeks_used = np.asarray(weeks_used)
    print("样本周 %d  起 %s  末 %s" % (len(weeks_used), weeks_used[0], weeks_used[-1]), flush=True)

    halves = ap.windows(list(weeks_used), HALVES_AT)
    halves_s790 = ap.windows(list(weeks_used), HALVES_AT_S790)
    res = {"task": "T-311", "ledger": "S-790",
           "sample": {"n_weeks": int(len(weeks_used)), "first": str(weeks_used[0]),
                      "last": str(weeks_used[-1]), "min_coins_per_week": MIN_COINS,
                      "alpha": ALPHA, "baseline_dims": P_DIMS, "event_dims": EV_DIMS,
                      "halves_at": HALVES_AT_S790},
           "event_source": {"tag_parser": EV["tag_src"], "n_tag_announcements": EV["n_ann"]},
           "arms": {}}
    for key in ARMS:
        res["arms"][key] = _summ(rows[key], spread[key], bot[key], halves, ap)
        res["arms"][key]["halves_s790"] = _summ(rows[key], spread[key], bot[key],
                                                halves_s790, ap)["halves"]

    # ── 自检:复现 S-776 的 P(IC 0.112 ± 0.002) ───────────────────────────────
    p = res["arms"]["P"]
    sc = {"reference": S776_P, "recomputed": {
        "ic_mean": p["ic_mean"], "nw_t_lag5": p.get("nw_t_lag5"),
        "n_weeks": p["n_weeks"], "q5_minus_q1_x30": p.get("q5_minus_q1_x30"),
        "bottom_quintile_x30": p.get("bottom_quintile_x30"),
        "halves": [h["ic_mean"] for h in p["halves"]]}}
    sc["abs_diff_ic_mean"] = abs(p["ic_mean"] - S776_P["ic_mean"])
    sc["within_0.002"] = bool(sc["abs_diff_ic_mean"] <= 0.002)
    res["self_check"] = {"P_vs_S776": sc}
    print("自检 P vs S-776: IC=%.6f (参考 %.6f, |Δ|=%.4f ≤0.002 ⇒ %s) t=%.3f bot=%.6f"
          % (p["ic_mean"], S776_P["ic_mean"], sc["abs_diff_ic_mean"],
             sc["within_0.002"], p.get("nw_t_lag5", float("nan")),
             p.get("bottom_quintile_x30", float("nan"))), flush=True)

    # ── 诊断:基线漂移是数据刷新还是代码问题(单维 IC 对照,不用 Ridge) ────────
    old_per_dim = _load_old_per_dim()
    new_per_dim = {d: float(np.mean(v)) for d, v in dims_ic.items()}
    diag = {"old_snapshot": "t293_results.json(2026-11-08 03:51 抓取)",
            "new_snapshot": "本次抓取(%s)" % time.strftime("%Y-%m-%d %H:%M", time.localtime()),
            "per_dim_ic_old": old_per_dim, "per_dim_ic_new": new_per_dim,
            "per_dim_ic_delta": {d: (new_per_dim[d] - old_per_dim[d])
                                 for d in old_per_dim if d in new_per_dim}}
    if old_per_dim:
        same_sign = sum(1 for d in diag["per_dim_ic_delta"]
                        if (old_per_dim[d] > 0) == (new_per_dim[d] > 0))
        diag["n_dims"] = len(diag["per_dim_ic_delta"])
        diag["n_same_sign"] = same_sign
        diag["max_abs_delta"] = max(abs(v) for v in diag["per_dim_ic_delta"].values())
    a = res["arms"]["A"]
    diag["A_vs_S774_R"] = {"recomputed_ic_mean": a["ic_mean"],
                           "reference_ic_mean": 0.10063970161006076,
                           "abs_diff": abs(a["ic_mean"] - 0.10063970161006076)}
    res["data_refresh_diagnostic"] = diag
    print("诊断 单维 IC 变号 %d/%d;A 臂 IC=%.6f(参考 %.6f)"
          % (diag.get("n_same_sign", -1), diag.get("n_dims", -1),
             a["ic_mean"], 0.10063970161006076), flush=True)

    # ── 主判:最低五分位差(E − P) ───────────────────────────────────────────
    bd = np.asarray(bot_diff_series, dtype=float)
    t_bd, m_bd, se_bd = _nw_t(bd, ap)
    half_bd = _halves(bd, halves_s790)
    primary = {"stat": "bottom_quintile_x30_mean(E) − bottom_quintile_x30_mean(P)",
               "mean": m_bd, "nw_t_lag5": t_bd, "nw_se": se_bd,
               "n_weeks": int(len(bd)), "halves": half_bd,
               "mean_lt_0": bool(m_bd < 0),
               "nw_t_le_minus2": bool(t_bd is not None and t_bd <= -2.0),
               "halves_both_lt_0": bool(len(half_bd) == 2 and all(
                   (h["mean"] is not None and h["mean"] < 0) for h in half_bd))}
    primary["PASS"] = bool(primary["mean_lt_0"] and primary["nw_t_le_minus2"]
                           and primary["halves_both_lt_0"])
    res["primary_bottom_quintile"] = primary

    # ── 金额判据(S-779 附注) ───────────────────────────────────────────────
    q5q1_e = res["arms"]["E"]["q5_minus_q1_x30"]
    q5q1_p = res["arms"]["P"]["q5_minus_q1_x30"]
    money = {"q5_minus_q1_E": q5q1_e, "q5_minus_q1_P": q5q1_p,
             "q5_minus_q1_E_after_20bps": q5q1_e - COST_BPS / 1e4,
             "q5_minus_q1_P_after_20bps": q5q1_p - COST_BPS / 1e4,
             "spread_E_ge_P_after_cost": bool((q5q1_e - COST_BPS / 1e4)
                                             >= (q5q1_p - COST_BPS / 1e4)),
             "bottom_mean_E_lt_P": bool(res["arms"]["E"]["bottom_quintile_x30"]
                                        < res["arms"]["P"]["bottom_quintile_x30"])}
    money["PASS"] = bool(money["spread_E_ge_P_after_cost"] and money["bottom_mean_E_lt_P"])
    res["money_criterion"] = money

    # ── 副判:IC(E) − IC(P) ─────────────────────────────────────────────────
    diff = np.asarray(rows["E"], dtype=float) - np.asarray(rows["P"], dtype=float)
    t_d, m_d, se_d = _nw_t(diff, ap)
    res["secondary_ic_diff"] = {"mean": m_d, "nw_t_lag5": t_d, "nw_se": se_d,
                                "n_weeks": int(len(diff)),
                                "prop_positive": float((diff > 0).mean()),
                                "halves": _halves(diff, halves_s790)}

    # ── 只报项:每维单独加进 P 的边际 ───────────────────────────────────────
    res["per_dim_marginal"] = {}
    for e in EV_DIMS:
        k = "P+" + e
        res["per_dim_marginal"][e] = {
            "ic_mean": res["arms"][k]["ic_mean"],
            "nw_t_lag5": res["arms"][k].get("nw_t_lag5"),
            "delta_ic_vs_P": res["arms"][k]["ic_mean"] - res["arms"]["P"]["ic_mean"],
            "bottom_quintile_x30": res["arms"][k].get("bottom_quintile_x30"),
            "delta_bottom_vs_P": (res["arms"][k].get("bottom_quintile_x30", float("nan"))
                                  - res["arms"]["P"].get("bottom_quintile_x30", float("nan")))}

    # ── 只报项:稀疏度 ─────────────────────────────────────────────────────
    mw = np.asarray(marked_weeks, dtype=float)     # (n_weeks, 6)
    res["sparsity"] = {"per_dim_mean_marked_per_week": {
        e: float(mw[:, j].mean()) for j, e in enumerate(EV_DIMS)},
        "per_dim_max_marked_per_week": {e: int(mw[:, j].max()) for j, e in enumerate(EV_DIMS)},
        "total_marked_per_week_mean": float(mw.sum(axis=1).mean()),
        "total_marked_per_week_min": int(mw.sum(axis=1).min()),
        "total_marked_per_week_max": int(mw.sum(axis=1).max()),
        "weeks_with_zero_marked": int((mw.sum(axis=1) == 0).sum()),
        "coins_per_week_median": float(np.median(coins_per_week)),
        "coins_per_week_min": int(np.min(coins_per_week)),
        "coins_per_week_max": int(np.max(coins_per_week))}

    # ── 周度序列(审计用) ───────────────────────────────────────────────────
    res["weekly"] = {"weeks": [str(w) for w in weeks_used],
                     "ic_P": rows["P"], "ic_E": rows["E"],
                     "bot_P": bot["P"], "bot_E": bot["E"], "bot_diff": bot_diff_series}

    res["verdict"] = {"primary": primary["PASS"], "money": money["PASS"],
                      "note": "主判只看最低五分位差;副判与每维边际只报。"}
    RESULTS.write_text(json.dumps(res, indent=2, ensure_ascii=False))
    print("判定 主判=%s 金额=%s" % (primary["PASS"], money["PASS"]), flush=True)
    print("结果写入", RESULTS.name, flush=True)


if __name__ == "__main__":
    ap_ = argparse.ArgumentParser()
    ap_.add_argument("cmd", choices=["fetch", "run"])
    a = ap_.parse_args()
    if a.cmd == "fetch":
        cmd_fetch()
    else:
        cmd_run()
