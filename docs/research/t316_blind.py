#!/usr/bin/env python3
"""T-316 — S-795 盲复算(B 道 / lane-b,2026-11-10)。

只读 `REFUTATION_LEDGER.md` 的 **S-795 原文**(2026-11-09 15:16 UTC,Seth 预注册)独立实现两臂与 (a)–(d)。
**不读** lane-a 的 `docs/research/t315_*` / `T-315_*` / `lane-a/T-315` 分支的任何内容。

口径全部来自 S-795 原文;原文没写清的地方,本脚本里的每一个决定都记在 `AMBIGUITIES` 里,
并在 `docs/research/T-316_blind_replication.md` 的「口径歧义」一节逐条展开(本卡最重要的产出)。

产物:
  docs/research/t316_results.json      —— 全部数字 + 指纹
  docs/research/t316_event_match.csv   —— 事件匹配表(先落,再算)
  docs/research/t316_blind.py           —— 本文件
"""
from __future__ import annotations

import csv
import datetime as dt
import gzip
import hashlib
import json
import math
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Optional

import numpy as np

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "docs" / "research"
CACHE = Path("/Volumes/CometCloudAI/cometcloud-local/research/t316_cache")
EVENTS_CSV = REPO / "docs" / "research" / "t309_events.csv"

sys.path.insert(0, str(REPO))
from src.data.evaluation import apparatus  # noqa: E402
from src.data.state.window_vectors import window_vector  # noqa: E402

# ── S-795 原文写死的量(改这里就是改预注册) ────────────────────────────────
K = 50                    # kNN 近邻数
LABEL_H = 60              # 标签窗口 (t, t+60 天]
JUDGE_START = os.environ.get("T316_JUDGE_START", "2024-01-01")
JUDGE_END = os.environ.get("T316_JUDGE_END", "2026-08-31")
SEED = 795                # 打乱 / 自助的种子
N_PERM = int(os.environ.get("T316_N_PERM", "1000"))   # (a) 周内打乱次数
N_BOOT = int(os.environ.get("T316_N_BOOT", "1000"))   # (b) 整周块自助次数
C_BAND = 1.0              # LogisticRegression(C=1.0)
MIN_HIST = 90             # dd90 需要 90 个有价日 ⇒ 两臂的最小历史
VEC_LEN = 61              # 形状向量窗口 = 61 个收盘(含 t)
TOP_PCT = 0.10            # (d) 取前 10%
TOP_MIN = 5               # (d) 至少 5 个币
HOLD_DAYS = 30            # (d) t+1 → t+31

# 原文没写清、本脚本自己定的地方(报告里逐条展开)
AMBIGUITIES: list[dict[str, Any]] = []


def amb(key: str, question: str, choice: str, alt: str, flips: str) -> None:
    AMBIGUITIES.append({"id": key, "question": question, "choice": choice, "alternative": alt,
                        "conclusion_flip": flips})


def log(msg: str) -> None:
    print(f"[t316 {dt.datetime.now(dt.timezone.utc).strftime('%H:%M:%S')}] {msg}", flush=True)


def sha(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


def sha_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ── 只读取数 ──────────────────────────────────────────────────────────────
URL = os.environ.get("SUPABASE_URL")
KEY = os.environ.get("SUPABASE_KEY")
if not URL or not KEY:
    sys.exit("缺 SUPABASE_URL / SUPABASE_KEY")


def rest(path: str, params: str = "", rng: Optional[str] = None, timeout: int = 120):
    import urllib.request
    url = f"{URL}/rest/v1/{path}"
    if params:
        url += "?" + params
    headers = {"apikey": KEY, "Authorization": f"Bearer {KEY}", "Prefer": "count=exact"}
    if rng:
        headers["Range"] = rng
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode()), r.headers.get("Content-Range")


def rest_all(path: str, params: str = "", page: int = 1000) -> list[dict]:
    """翻页读,每页带 order=;核总行数。"""
    out: list[dict] = []
    start = 0
    total = None
    while True:
        rows, cr = rest(path, params, f"{start}-{start + page - 1}")
        if total is None and cr and "/" in cr:
            total = int(cr.split("/")[-1])
        out.extend(rows)
        start += page
        if not rows or (total is not None and start >= total):
            break
    if total is not None and len(out) != total:
        raise RuntimeError(f"{path}: 抓到 {len(out)} 行,表里 {total} 行")
    return out


# ── 1. 事件:监控标签(t309_events.csv)+ 整币下架(delisting_watch) ─────────
def load_events() -> tuple[dict[str, dict], list[dict]]:
    """→ {perp 代号: 事件日 + 来源},匹配表。"""
    tag: dict[str, str] = {}
    with open(EVENTS_CSV) as f:
        for r in csv.DictReader(f):
            s = r["symbol"].strip()
            d = r["d0"][:10]
            if s not in tag or d < tag[s]:
                tag[s] = d
    dw = rest_all("delisting_watch?select=symbol,d0,kind&order=symbol.asc,d0.asc")
    dlv: dict[str, str] = {}
    for r in dw:
        s = str(r["symbol"]).strip()
        d = str(r["d0"])[:10]
        if s not in dlv or d < dlv[s]:
            dlv[s] = d
    return {"_tag": tag, "_dlv": dlv}, dw


PREFIXES = ("1000000", "1000")


def strip_prefix(sym: str) -> str:
    for p in PREFIXES:
        if sym.startswith(p) and len(sym) > len(p):
            return sym[len(p):]
    return sym


def match_events(tag: dict[str, str], dlv: dict[str, str], perp_syms: set[str],
                 first_d: dict[str, str]) -> tuple[dict[str, dict], list[dict]]:
    """事件代号 → 永续代号。精确匹配优先;否则用「去掉 1000/1000000 前缀后的代号」对齐。
    一个事件代号对到多个永续代号 ⇒ 取 first_d 最早的那个(并在匹配表里标出来)。"""
    first_d = {s: first_d.get(s, "9999-12-31") for s in perp_syms}
    rows: list[dict] = []
    out: dict[str, dict] = {}
    for src, ev in (("monitoring_tag", tag), ("delisting", dlv)):
        for esym in sorted(ev):
            d0 = ev[esym]
            cands = []
            if esym in perp_syms:
                cands.append(esym)
            # 方向 A:永续代号去掉前缀 == 事件代号
            cands += [s for s in perp_syms if s not in cands and strip_prefix(s) == esym]
            # 方向 B:事件代号去掉前缀 == 永续代号
            cands += [s for s in perp_syms if s not in cands and strip_prefix(esym) == s]
            hit = sorted(cands, key=lambda s: (first_d.get(s, "9999-12-31"), s))
            row = {"source": src, "event_symbol": esym, "event_d0": d0, "perp_symbol": hit[0] if hit else "",
                   "n_candidates": len(hit), "candidates": "|".join(hit[:6])}
            rows.append(row)
            if hit:
                ps = hit[0]
                cur = out.get(ps)
                if cur is None or d0 < cur["event_d0"]:
                    out[ps] = {"event_d0": d0, "source": src, "event_symbol": esym}
    return out, rows


# ── 2. 取价(perp_bv_daily,kind='coin') ───────────────────────────────────
def load_prices(coin_syms: list[str]) -> tuple[dict[str, dict[str, tuple[float, float]]], dict]:
    CACHE.mkdir(parents=True, exist_ok=True)
    cpath = CACHE / "perp_bv_daily_coin.json.gz"
    meta_path = CACHE / "perp_bv_daily_coin.meta.json"
    want = sorted(coin_syms)
    if cpath.exists() and meta_path.exists():
        meta = json.loads(meta_path.read_text())
        if meta.get("symbols") == want:
            log(f"用缓存 {cpath} ({meta.get('rows')} 行)")
            with gzip.open(cpath, "rt") as f:
                rows = json.load(f)
            return _rows_to_price(rows), meta

    shards = [want[i:i + 40] for i in range(0, len(want), 40)]
    rows_all: list[list] = []

    def one(shard: list[str]) -> list[list]:
        got: list[list] = []
        start = 0
        total = None
        while True:
            q = ("select=pair,symbol,d,c,qv&symbol=in.(" + ",".join(shard) +
                 ")&order=symbol.asc,d.asc")
            rws, cr = rest("perp_bv_daily", q, f"{start}-{start + 999}")
            if total is None and cr and "/" in cr:
                total = int(cr.split("/")[-1])
            for r in rws:
                got.append([r["symbol"], str(r["d"])[:10], r.get("c"), r.get("qv")])
            start += 1000
            if not rws or (total is not None and start >= total):
                break
        if total is not None and len(got) != total:
            raise RuntimeError(f"shard {shard[0]} 抓到 {len(got)} / {total}")
        return got

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=6) as ex:
        for part in ex.map(one, shards):
            rows_all.extend(part)
    log(f"取价 {len(rows_all)} 行, {time.time() - t0:.0f}s")
    with gzip.open(cpath, "wt") as f:
        json.dump(rows_all, f)
    meta = {"symbols": want, "rows": len(rows_all), "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat()}
    meta_path.write_text(json.dumps(meta))
    return _rows_to_price(rows_all), meta


def _rows_to_price(rows: list[list]) -> dict[str, dict[str, tuple[float, float]]]:
    out: dict[str, dict[str, tuple[float, float]]] = {}
    for sym, d, c, qv in rows:
        if c is None:
            continue
        try:
            c = float(c)
        except (TypeError, ValueError):
            continue
        if not (c > 0):
            continue
        out.setdefault(sym, {})[d] = (c, float(qv) if qv is not None else float("nan"))
    return out


# ── 3. 样本:形状 + 基线特征 ──────────────────────────────────────────────
def build_samples(price: dict[str, dict[str, tuple[float, float]]],
                  ev: dict[str, dict]) -> list[dict]:
    """每个 (币, 周一) 一个样本。条件:该币在 t 有收盘、t 之前(含)至少 61 个有价日、事件日 > t。
    基线 5 个特征任一缺 ⇒ 该样本两臂都不进(S-795 原文)。"""
    samples: list[dict] = []
    for sym in sorted(price):
        days = sorted(price[sym])
        cs = [price[sym][d][0] for d in days]
        qvs = [price[sym][d][1] for d in days]
        e = ev.get(sym)
        ed0 = e["event_d0"] if e else None
        for i, d in enumerate(days):
            dtv = dt.date.fromisoformat(d)
            if dtv.weekday() != 0:          # 只取周一
                continue
            if i < MIN_HIST - 1:             # dd90 要 90 个有价日
                continue
            if ed0 is not None and not (d < ed0):   # 事件日 > t;出过事件的币从事件日起退出
                continue
            # 形状:最近 61 个收盘(含 t)
            vec = window_vector(cs[i - 60:i + 1])
            if vec is None:
                continue
            # 基线 5 特征
            mom30 = math.log(cs[i] / cs[i - 30])
            mom60 = math.log(cs[i] / cs[i - 60])
            hi90 = max(cs[i - 89:i + 1])
            dd90 = cs[i] / hi90 - 1.0
            lr = [math.log(cs[j + 1] / cs[j]) for j in range(i - 30, i)]
            mu = sum(lr) / 30.0
            vol30 = math.sqrt(sum((x - mu) ** 2 for x in lr) / 29.0)
            q30 = [q for q in qvs[i - 29:i + 1] if not (isinstance(q, float) and math.isnan(q))]
            if len(q30) < 30 or any(q <= 0 for q in q30):
                continue
            lnqv = math.log(sum(q30) / 30.0)
            y = 1 if (ed0 is not None and d < ed0 <= (dtv + dt.timedelta(days=LABEL_H)).isoformat()) else 0
            iso = dtv.isocalendar()
            samples.append({"sym": sym, "d": d, "ord": dtv.toordinal(), "vec": vec,
                            "feat": [mom30, mom60, dd90, vol30, lnqv], "y": y,
                            "week": f"{iso[0]}-W{iso[1]:02d}"})
    samples.sort(key=lambda s: (s["ord"], s["sym"]))
    return samples


# ── 4. AUC 工具 ──────────────────────────────────────────────────────────
def auc(y: np.ndarray, s: np.ndarray) -> Optional[float]:
    if len(y) == 0 or len(set(y.tolist())) < 2:
        return None
    from sklearn.metrics import roc_auc_score
    return float(roc_auc_score(y, s))


def fast_shuffle_within(values: list[int], group_ids: list[int], rng) -> np.ndarray:
    """与 `apparatus.shuffle_within` 同语义、同 rng 消耗顺序的快版(整数分组)。

    apparatus 的实现把分组转成 object 数组再逐组 `grp == g` 比较:24 万行 × ~340 周 × 1000 次打乱
    ⇒ 单次 ~4 秒、总共 1 小时,不可用。本版只把分组比较换成整数比较,`rng.permutation(idx)` 的调用
    顺序与 apparatus 完全一致(组按首次出现顺序),所以输出逐位相同 —— 脚本里有一处 assert 钉住。
    """
    vals = np.asarray(values)
    gid = np.asarray(group_ids)
    out = vals.copy()
    for g in dict.fromkeys(gid.tolist()):
        idx = np.flatnonzero(gid == g)
        out[idx] = vals[rng.permutation(idx)]
    return out


def main() -> None:
    t_start = time.time()
    print(json.dumps({"event": "S-795 blind replication (T-316, lane-b)"}, ensure_ascii=False))

    # ── 取配对表 ──
    pairs = rest_all("perp_bv_pairs?select=pair,symbol,kind,first_d,active,dead_from&order=symbol.asc")
    coin_pairs = [p for p in pairs if p.get("kind") == "coin"]
    coin_syms = sorted({str(p["symbol"]) for p in coin_pairs})
    log(f"perp_bv_pairs {len(pairs)} 行 / kind='coin' {len(coin_pairs)} 行 / {len(coin_syms)} 个代号")

    ev_raw, dw_rows = load_events()
    first_d = {str(p["symbol"]): str(p.get("first_d") or "9999-12-31") for p in coin_pairs}
    ev, mrows = match_events(ev_raw["_tag"], ev_raw["_dlv"], set(coin_syms), first_d)
    matched = {r["perp_symbol"] for r in mrows if r["perp_symbol"]}
    unmatched = [r for r in mrows if not r["perp_symbol"]]
    log(f"事件代号:监控标签 {len(ev_raw['_tag'])} / 下架 {len(ev_raw['_dlv'])};"
        f"对上永续 {len(matched)} 个代号;对不上 {len(unmatched)} 个")

    price, pmeta = load_prices(coin_syms)
    log(f"永续代号有价的 {len(price)} 个")

    samples = build_samples(price, ev)
    log(f"样本 {len(samples)} 条(两臂共有)")

    # 匹配表先落
    mp = OUT / "t316_event_match.csv"
    with open(mp, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["source", "event_symbol", "event_d0", "perp_symbol", "n_candidates", "candidates"])
        for r in mrows:
            w.writerow([r["source"], r["event_symbol"], r["event_d0"], r["perp_symbol"],
                        r["n_candidates"], r["candidates"]])

    # ── 数组化 ──
    n = len(samples)
    V = np.asarray([s["vec"] for s in samples], dtype=np.float32)
    F = np.asarray([s["feat"] for s in samples], dtype=np.float64)
    Y = np.asarray([s["y"] for s in samples], dtype=np.int8)
    ORD = np.asarray([s["ord"] for s in samples], dtype=np.int64)
    WEEK = [s["week"] for s in samples]
    SYM = [s["sym"] for s in samples]
    SYM_A = np.asarray(SYM)
    SDATE = [s["d"] for s in samples]
    js = dt.date.fromisoformat(JUDGE_START)
    je = dt.date.fromisoformat(JUDGE_END)
    mondays = []
    d = js
    while d <= je:
        if d.weekday() == 0:
            mondays.append(d.isoformat())
        d += dt.timedelta(days=1)
    log(f"判定区间的周一 {len(mondays)} 个 ({mondays[0]} → {mondays[-1]})")

    # ── 每周一:参照集 / 查询集 / kNN / 基线 ──
    from sklearn.linear_model import LogisticRegression
    per_t: dict[str, dict] = {}
    nb_all: list[np.ndarray] = []
    q_all: list[np.ndarray] = []
    base_all: list[np.ndarray] = []
    score_all: list[np.ndarray] = []
    base_by_t: dict[str, np.ndarray] = {}
    knn_by_t: dict[str, np.ndarray] = {}
    for t in mondays:
        tord = dt.date.fromisoformat(t).toordinal()
        qrows = np.flatnonzero(ORD == tord)
        rrows = np.flatnonzero(ORD <= tord - LABEL_H)
        if len(qrows) == 0 or len(rrows) < K:
            per_t[t] = {"n_q": int(len(qrows)), "n_ref": int(len(rrows)), "skipped": True}
            continue
        R = V[rrows]
        Q = V[qrows]
        r2 = (R.astype(np.float64) ** 2).sum(1)
        nb = np.empty((len(qrows), K), dtype=np.int64)
        qb = 200
        for s0 in range(0, len(qrows), qb):
            blk = Q[s0:s0 + qb].astype(np.float64)
            d2 = r2[None, :] + (blk ** 2).sum(1)[:, None] - 2.0 * (blk @ R.T)
            part = np.argpartition(d2, K - 1, axis=1)[:, :K]
            dd = np.take_along_axis(d2, part, axis=1)
            order = np.argsort(dd, axis=1, kind="stable")
            part = np.take_along_axis(part, order, axis=1)
            nb[s0:s0 + qb] = rrows[part]
        score_knn = Y[nb].mean(axis=1)

        # 基线:参照集标准化 → LogisticRegression
        mu = F[rrows].mean(axis=0)
        sd = F[rrows].std(axis=0)
        sd = np.where(sd < 1e-12, 1.0, sd)
        Xr = (F[rrows] - mu) / sd
        Xq = (F[qrows] - mu) / sd
        try:
            lr = LogisticRegression(C=C_BAND, max_iter=1000)
            lr.fit(Xr, Y[rrows])
            score_base = lr.predict_proba(Xq)[:, 1]
        except Exception as e:  # noqa: BLE001
            log(f"  {t} 基线拟合失败 {e}")
            score_base = np.full(len(qrows), np.nan)
        per_t[t] = {"n_q": int(len(qrows)), "n_ref": int(len(rrows)),
                    "n_pos": int(Y[qrows].sum()), "mean_score": float(score_knn.mean()),
                    "mean_base": float(np.nanmean(score_base))}
        nb_all.append(nb)
        q_all.append(qrows)
        base_all.append(score_base)
        score_all.append(score_knn)
        base_by_t[t] = score_base
        knn_by_t[t] = score_knn
        if len(nb_all) % 20 == 0:
            log(f"  {t} 已算 {len(nb_all)}/{len(mondays)}")

    nb_cat = np.vstack(nb_all)
    q_cat = np.concatenate(q_all)
    score_base_cat = np.concatenate(base_all)
    score_knn = np.concatenate(score_all)
    log(f"kNN 完成:查询样本 {len(q_cat)},平均参照集 {np.mean([per_t[t]['n_ref'] for t in mondays if not per_t[t].get('skipped')]):.0f}")

    y_q = Y[q_cat]
    auc_knn = auc(y_q, score_knn)
    auc_base = auc(y_q, score_base_cat)
    log(f"AUC kNN {auc_knn:.4f} / 基线 {auc_base:.4f} / 差 {auc_knn - auc_base:+.4f}")

    # ── (a) 周内打乱标签 ──
    wmap: dict[str, int] = {}
    week_ids: list[int] = []
    for w in WEEK:
        if w not in wmap:
            wmap[w] = len(wmap)
        week_ids.append(wmap[w])

    _r1 = np.random.default_rng(SEED)
    _r2 = np.random.default_rng(SEED)
    _fast = fast_shuffle_within(Y.tolist(), week_ids, _r1)
    _ref = np.asarray(apparatus.shuffle_within(Y.tolist(), WEEK, _r2), dtype=np.int8)
    assert np.array_equal(_fast.astype(np.int8), _ref), "快版打乱与 apparatus.shuffle_within 不一致"
    log(f"打乱实现核对通过(与 apparatus.shuffle_within 逐位相同;{len(wmap)} 个周组)")

    def perm_scores(rng) -> float:
        yp = fast_shuffle_within(Y.tolist(), week_ids, rng).astype(np.int8)
        sc = yp[nb_cat].mean(axis=1)
        v = auc(yp[q_cat], sc)
        return float(v) if v is not None else float("nan")

    try:
        null_a = apparatus.null_distribution(perm_scores, N_PERM, SEED, actual=auc_knn)
        p_a = (1 + int((null_a >= auc_knn).sum())) / (1 + len(null_a))
        a_null_note = "ok"
    except Exception as e:  # noqa: BLE001
        null_a = np.asarray([])
        p_a = None
        a_null_note = f"{type(e).__name__}: {e}"

    # 弱版对照:只打乱查询标签、不重算 kNN 得分
    def perm_scores_weak(rng) -> float:
        yp = fast_shuffle_within(Y.tolist(), week_ids, rng).astype(np.int8)
        v = auc(yp[q_cat], score_knn)
        return float(v) if v is not None else float("nan")

    null_a_weak = apparatus.null_distribution(perm_scores_weak, N_PERM, SEED + 1, actual=auc_knn)
    p_a_weak = (1 + int((null_a_weak >= auc_knn).sum())) / (1 + len(null_a_weak))

    # ── (b) 整周块自助(按周重抽) ──
    weeks = sorted({WEEK[i] for i in q_cat.tolist()})
    w_of_row = np.asarray([weeks.index(WEEK[i]) for i in q_cat.tolist()])
    rows_by_week = [np.flatnonzero(w_of_row == j) for j in range(len(weeks))]
    rng_b = np.random.default_rng(SEED)
    widx = apparatus.stationary_bootstrap_index(len(weeks), 1.0, N_BOOT, rng_b)
    diffs = np.empty(N_BOOT)
    for b in range(N_BOOT):
        sel = np.concatenate([rows_by_week[j] for j in widx[b]])
        a1 = auc(y_q[sel], score_knn[sel])
        a2 = auc(y_q[sel], score_base_cat[sel])
        diffs[b] = (a1 - a2) if (a1 is not None and a2 is not None) else np.nan
    diffs = diffs[np.isfinite(diffs)]
    ci_lo, ci_hi = (float(np.percentile(diffs, 2.5)), float(np.percentile(diffs, 97.5))) if len(diffs) else (None, None)

    # 敏感性:4 周移动块
    rng_b2 = np.random.default_rng(SEED)
    widx2 = apparatus.stationary_bootstrap_index(len(weeks), 4.0, N_BOOT, rng_b2)
    diffs2 = []
    for b in range(N_BOOT):
        sel = np.concatenate([rows_by_week[j] for j in widx2[b]])
        a1 = auc(y_q[sel], score_knn[sel])
        a2 = auc(y_q[sel], score_base_cat[sel])
        if a1 is not None and a2 is not None:
            diffs2.append(a1 - a2)
    ci2 = (float(np.percentile(diffs2, 2.5)), float(np.percentile(diffs2, 97.5))) if diffs2 else (None, None)

    # ── (c) 两半 ──
    half = len(mondays) // 2
    w1, w2 = set(mondays[:half]), set(mondays[half:])
    m1 = np.asarray([WEEK[i] in w1 for i in q_cat.tolist()])
    m2 = ~m1
    auc_h1 = auc(y_q[m1], score_knn[m1])
    auc_h2 = auc(y_q[m2], score_knn[m2])
    auc_b_h1 = auc(y_q[m1], score_base_cat[m1])
    auc_b_h2 = auc(y_q[m2], score_base_cat[m2])

    # ── (d) 金额 ──
    import bisect
    PX: dict[str, tuple[list[str], list[float]]] = {}
    for sym, dd in price.items():
        ks = sorted(dd.keys())
        PX[sym] = (ks, [dd[k][0] for k in ks])

    def px_on_or_after(sym: str, day: dt.date) -> Optional[float]:
        ks, cs = PX.get(sym, ([], []))
        if not ks:
            return None
        i = bisect.bisect_left(ks, day.isoformat())
        if i >= len(ks):
            return None
        return apparatus.price_on_or_after(ks[i:], cs[i:], day.isoformat(), max_gap_days=3)

    def px_exact(sym: str, day: dt.date) -> Optional[float]:
        v = price.get(sym, {}).get(day.isoformat())
        return v[0] if v else None

    def ret_of(sym: str, d1: dt.date, d31: dt.date, mode: str) -> Optional[float]:
        if mode == "on_after":
            p1, p31 = px_on_or_after(sym, d1), px_on_or_after(sym, d31)
        else:
            p1, p31 = px_exact(sym, d1), px_exact(sym, d31)
        if p1 and p31 and p1 > 0:
            return p31 / p1 - 1.0
        return None

    def leg(score_map: dict[str, np.ndarray], mode: str, universe: str, missing: str) -> dict:
        per_week = []
        for t in mondays:
            if t not in score_map:
                continue
            tord = dt.date.fromisoformat(t).toordinal()
            idx_in_cat = np.flatnonzero(ORD[q_cat] == tord)
            s = score_map[t]
            sy = SYM_A[q_cat[idx_in_cat]]
            n = len(s)
            k = min(max(int(math.ceil(TOP_PCT * n)), TOP_MIN), n)
            order = sorted(range(n), key=lambda i: (-s[i], sy[i]))
            sel = [sy[i] for i in order[:k]]
            qrows = np.flatnonzero(ORD == tord)
            umem = sorted(price.keys()) if universe == "full" else sorted({SYM[i] for i in qrows.tolist()})
            d1 = dt.date.fromisoformat(t) + dt.timedelta(days=1)
            d31 = dt.date.fromisoformat(t) + dt.timedelta(days=1 + HOLD_DAYS)
            uni = [r for r in (ret_of(sy2, d1, d31, mode) for sy2 in umem) if r is not None]
            if not uni:
                continue
            bench = float(np.mean(uni))
            sel_rets: list[float] = []
            nm = 0
            for sy2 in sel:
                r = ret_of(sy2, d1, d31, mode)
                if r is None:
                    nm += 1
                    if missing == "minus100":
                        sel_rets.append(-1.0)
                else:
                    sel_rets.append(r)
            if not sel_rets:
                continue
            per_week.append({"t": t, "n_sel": len(sel), "n_missing": nm, "bench": bench,
                             "excess": float(np.mean(sel_rets) - bench)})
        ex = np.asarray([w["excess"] for w in per_week]) if per_week else np.asarray([])
        if len(ex) == 0:
            return {"n_weeks": 0, "per_week": []}
        return {"n_weeks": int(len(ex)), "mean": float(ex.mean()), "median": float(np.median(ex)),
                "p10": float(np.percentile(ex, 10)), "p90": float(np.percentile(ex, 90)),
                "n_missing_total": int(sum(w["n_missing"] for w in per_week)),
                "per_week": per_week}

    def safe_leg(*a, **kw) -> dict:
        try:
            return leg(*a, **kw)
        except Exception as e:  # noqa: BLE001
            log(f"  leg 失败:{type(e).__name__}: {e}")
            return {"n_weeks": 0, "error": f"{type(e).__name__}: {e}", "per_week": []}

    d_main = safe_leg(knn_by_t, "on_after", "full", "exclude")
    d_full_exact = safe_leg(knn_by_t, "exact", "full", "exclude")
    d_sample_uni = safe_leg(knn_by_t, "on_after", "sample", "exclude")
    d_m100 = safe_leg(knn_by_t, "on_after", "full", "minus100")
    d_base = safe_leg(base_by_t, "on_after", "full", "exclude")

    # ── 判定 ──
    res_a = {"auc_knn": auc_knn, "auc_base": auc_base, "diff": auc_knn - auc_base,
             "p_upper": p_a, "n_null": int(len(null_a)), "null_note": a_null_note,
             "p_upper_weak": p_a_weak, "null_mean": float(np.mean(null_a)) if len(null_a) else None,
             "null_sd": float(np.std(null_a)) if len(null_a) else None}
    res_b = {"diff": auc_knn - auc_base, "ci95_lo": ci_lo, "ci95_hi": ci_hi,
             "ci95_lo_mb4": ci2[0], "ci95_hi_mb4": ci2[1], "n_boot": int(len(diffs))}
    res_c = {"auc_h1": auc_h1, "auc_h2": auc_h2, "auc_base_h1": auc_b_h1, "auc_base_h2": auc_b_h2,
             "diff_h1_h2": (auc_h1 - auc_h2) if (auc_h1 is not None and auc_h2 is not None) else None,
             "knn_minus_base_h1": (auc_h1 - auc_b_h1) if (auc_h1 is not None and auc_b_h1 is not None) else None,
             "knn_minus_base_h2": (auc_h2 - auc_b_h2) if (auc_h2 is not None and auc_b_h2 is not None) else None,
             "n_weeks_h1": half, "n_weeks_h2": len(mondays) - half}
    res_d = {"knn_top10": {k: v for k, v in d_main.items() if k != "per_week"},
             "knn_top10_exact_date": {k: v for k, v in d_full_exact.items() if k != "per_week"},
             "knn_top10_universe_sample": {k: v for k, v in d_sample_uni.items() if k != "per_week"},
             "knn_top10_missing_minus100": {k: v for k, v in d_m100.items() if k != "per_week"},
             "baseline_top10": {k: v for k, v in d_base.items() if k != "per_week"},
             "per_week_knn": d_main.get("per_week", [])}

    verdict = {
        "a": bool(auc_knn is not None and auc_knn >= 0.70 and p_a is not None and p_a <= 0.01),
        "b": bool((auc_knn - auc_base) >= 0.02 and ci_lo is not None and ci_lo > 0),
        "c_abs": bool(auc_h1 is not None and auc_h2 is not None and auc_h1 >= 0.65 and auc_h2 >= 0.65),
        "c_gap_nonzero": bool(res_c["diff_h1_h2"] is not None and abs(res_c["diff_h1_h2"]) > 0),
        "c_knn_beats_base_both_halves": bool(res_c["knn_minus_base_h1"] is not None and
                                             res_c["knn_minus_base_h2"] is not None and
                                             res_c["knn_minus_base_h1"] > 0 and res_c["knn_minus_base_h2"] > 0),
        "d_mean_le_m3pp": bool(d_main.get("mean") is not None and d_main["mean"] <= -0.03),
        "d_beats_base_1pp": bool(d_main.get("mean") is not None and d_base.get("mean") is not None and
                                 d_main["mean"] <= d_base["mean"] - 0.01),
    }

    fp = {
        "script_sha256": sha_file(Path(__file__)),
        "events_csv_sha256": sha_file(EVENTS_CSV),
        "events_csv_rows": sum(1 for _ in open(EVENTS_CSV)) - 1,
        "delisting_watch_rows": len(dw_rows),
        "delisting_watch_sha256": sha(dw_rows),
        "perp_bv_pairs_sha256": sha(pairs),
        "perp_bv_daily_coin_sha256": sha(pmeta.get("symbols")),
        "perp_bv_daily_rows": pmeta.get("rows"),
        "samples_sha256": sha([[s["sym"], s["d"], s["y"]] for s in samples]),
        "results_sha256": None,
    }

    out = {
        "task": "T-316", "lane": "lane-b", "kind": "blind replication of S-795",
        "prereg": "REFUTATION_LEDGER.md S-795 (2026-11-09 15:16 UTC, Seth)",
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "constants": {"K": K, "LABEL_H": LABEL_H, "judge_start": JUDGE_START, "judge_end": JUDGE_END,
                      "seed": SEED, "n_perm": N_PERM, "n_boot": N_BOOT, "C": C_BAND,
                      "min_history_priced_days": MIN_HIST, "vector_window_closes": VEC_LEN,
                      "top_pct": TOP_PCT, "top_min": TOP_MIN, "hold_days": HOLD_DAYS},
        "universe": {"perp_bv_pairs_rows": len(pairs), "coin_pairs": len(coin_pairs),
                     "coin_symbols": len(coin_syms), "symbols_with_prices": len(price),
                     "price_rows": pmeta.get("rows"),
                     "monitoring_tag_symbols": len(ev_raw["_tag"]),
                     "delisting_symbols": len(ev_raw["_dlv"]),
                     "event_symbols_matched": len(matched),
                     "event_symbols_unmatched": len(unmatched),
                     "unmatched_list": [f"{r['source']}:{r['event_symbol']}" for r in unmatched][:40],
                     "multi_candidate": [f"{r['source']}:{r['event_symbol']}->{r['candidates']}"
                                         for r in mrows if r["n_candidates"] > 1][:40]},
        "samples": {"n": n, "n_pos": int(Y.sum()),
                    "n_weeks_judgement": len(mondays), "first_monday": mondays[0], "last_monday": mondays[-1],
                    "n_query": int(len(q_cat)), "n_query_pos": int(y_q.sum()),
                    "mean_ref_samples": float(np.mean([per_t[t]["n_ref"] for t in mondays if not per_t[t].get("skipped")])),
                    "per_week_n_query": {t: per_t[t].get("n_q", 0) for t in mondays}},
        "criteria": {"a": res_a, "b": res_b, "c": res_c, "d": res_d},
        "verdict": verdict,
        "all_pass": bool(all([verdict["a"], verdict["b"], verdict["c_abs"], verdict["d_mean_le_m3pp"],
                              verdict["d_beats_base_1pp"]])),
        "ambiguities": AMBIGUITIES,
        "fingerprints": fp,
        "elapsed_s": round(time.time() - t_start, 1),
    }
    (OUT / "t316_results.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
    log(f"落 {OUT / 't316_results.json'}")
    print(json.dumps({"verdict": verdict, "auc_knn": auc_knn, "auc_base": auc_base,
                      "p_a": p_a, "ci": [ci_lo, ci_hi], "d_mean": d_main.get("mean"),
                      "d_base_mean": d_base.get("mean"), "elapsed_s": out["elapsed_s"]},
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    amb("A1", "监控标签的事件日取 CSV 的 d0(逐句解析出来的「第一次被打上」日期),"
              "还是公告的 kind_db(有些行是 monitoring_tag_removed)?",
        "用 d0。t309_monitoring.py 的 `first[s]` 取的是「代号第一次出现在某条公告的打上句里」,"
        "kind_db 只是那条公告在库里的分类(同一条公告既含打上句又含移除句时,库里会记成 removed)。",
        "若改用 kind_db=='monitoring_tag' 的行当事件(会少 55 个代号),事件集从 137 变成 82。",
        "会变:样本的正例来源变少,(a)–(d) 的分子全变。")
    amb("A2", "监控标签事件集漏了 2023-07-26 那条「种子公告」的 5 个代号(逐句解析没抽到 add 句)。",
        "照 CSV 原样用(137 个代号)。这 5 个代号因此被当成「没出过事」的币,标签有噪声。",
        "把 5 个代号按 2023-07-26 补进事件集。",
        "会变(轻微):多 5 个正例事件,受影响的是它们事件前 60 天的样本。")
    amb("A3", "事件代号 ↔ 永续代号:去掉 1000 / 1000000 前缀时,剥哪一边?",
        "两边都试:永续代号剥前缀 == 事件代号(主),或事件代号剥前缀 == 永续代号(次)。",
        "只按原文字面「事件代号去前缀」单向匹配。",
        "先看匹配表里的 n_candidates>0 行;差集见匹配表。")
    amb("A4", "下架事件的 d0 是「公告日」,不是「实际下架日」(公告与执行通常差 7 天)。",
        "用 d0(公告日),照原文。", "用执行日(公告日 + 标题里的日期)。",
        "会变(轻微):事件日前移一周,标签窗口 (t, t+60] 的边界移动 ⇒ 每周的正例数变。")
    amb("A5", "两臂共用的最小历史:原文说「至少 61 个有价日」,但基线的 dd90 要 90 个。",
        "取 90(原文说「任一特征缺 ⇒ 该样本两臂都不进」⇒ 两臂取交集)。",
        "kNN 臂用 61、基线臂用 90(两臂样本集不同 ⇒ AUC 不可比)。",
        "会变:kNN 臂多出 ~1/3 的早期样本 ⇒ AUC 变。")
    amb("A6", "参照集截止:「s ≤ t − 60 天」按日历日还是按周数?",
        "按日历日:s + 60 天 ≤ t(周一减 60 天是周四 ⇒ 实际上参照集最后是 t 之前第 9 个周一)。",
        "按周数:最近 8 个周一的样本都排除。", "会变(很小):多/少一个周一的参照样本。")
    amb("A7", "(a) 的零分布:打乱标签后要不要重算 kNN 得分?",
        "重算(标签同时打乱参照集与查询集,近邻下标不变 —— 近邻下标与标签无关,只依赖形状向量)。",
        "只打乱查询标签、不重算得分(更弱、也更便宜)。",
        "会变:两个 p 值都报在结果里(见 t316_results.json 的 p_upper / p_upper_weak)。")
    amb("A8", "(b) 「整周块自助(按周重抽)」= 按周整群重抽,还是移动块?",
        "主口径:按周整群重抽(apparatus.stationary_bootstrap_index, mean_block=1, 1000 次, 种子 795)。",
        "敏感性:mean_block=4 的移动块(结果也报)。", "会变(区间宽度),不动点估计。")
    amb("A9", "(c) 「两半的 AUC 差都 > 0」怎么读?",
        "报四种读法:① 两半各 ≥ 0.65;② |AUC1 − AUC2| > 0;③ 每半 kNN − 基线 > 0;④ AUC1 − AUC2 > 0(带号)。",
        "只取其中一种。", "见结果里的 c_abs / c_gap_nonzero / c_knn_beats_base_both_halves 三个布尔。")
    amb("A10", "(d) 「t+1 收盘 → t+31 收盘」用哪天的价?",
        "主口径:「不早于该日的第一个有价日」,容差 3 天(apparatus.price_on_or_after);"
        "敏感性:严格日历日当天。",
        "严格日历日(加密永续每天都有线,差异只在死币上)。", "两者都报。")
    amb("A11", "(d) 选中的币在 t+31 没有价(已下架)怎么办?",
        "主口径:剔除该币(并报剔除数);敏感性:当 −100%。",
        "一律当 −100%(下架归零)。", "会变(大):这是 (d) 最重的一条。")
    amb("A12", "(d) 「同期全宇宙等权」的全宇宙 = ?",
        "主口径:全部 kind='coin' 的永续代号(在该周有 t+1 与 t+31 两个价的)。",
        "敏感性:该周有样本的代号(已出过事的币已退出)。", "两条都报。")
    amb("A13", "(d) 前 10% 的并列怎么处理?",
        "按 (−得分, 代号) 排序取前 k,保证可复现。", "随机打破并列。", "不会变(并列极少)。")
    amb("A14", "基线的标准化与 LogisticRegression 默认参数。",
        "参照集均值/标准差标准化;C=1.0,lbfgs,max_iter=1000(原文只写 C=1.0)。",
        "max_iter=100(sklearn 默认)。", "会变(极小,除非不收敛)。")
    main()
