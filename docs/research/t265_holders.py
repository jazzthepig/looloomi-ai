#!/usr/bin/env python3
"""
T-265 / S-743 — 持有人数增长(采用面)对之后 4 周相对 BTC 的超额,横截面周频。

预注册来源:REFUTATION_LEDGER.md §S-743(Seth, 2026-11-06 08:36 UTC),(a)–(d) 一字不改。
本脚本只算、不改代码、不入库。零分布 / 打乱 / 分位用 src/data/evaluation/apparatus.py,
不另起炉灶(CLAUDE.md 硬规则:零分布与盈亏只许用 apparatus)。

用法:
    python3 docs/research/t265_holders.py cover      # 前提检查(token_holders_coverage n_weekly>=52 的币数)
    python3 docs/research/t265_holders.py fetch      # 抓价格 / 基准 / 持有人到 Mac 研究缓存
    python3 docs/research/t265_holders.py selftest   # 合成数据的机器自检(不是证据)
    python3 docs/research/t265_holders.py run        # 完整检验(前提不过 ⇒ 停,不跑)→ t265_results.json

缓存目录:MAC_ROOT/research/t265/(不落 /tmp;搬运用 mv)
"""
from __future__ import annotations

import json
import math
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict

import numpy as np

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)
from src.data.evaluation.apparatus import (  # noqa: E402
    NoOpNull,
    null_distribution,
    percentile_of,
    price_on_or_after,
    shuffle_within,
)

SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SUPABASE_KEY = os.environ["SUPABASE_KEY"]
HDRS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
}

OUT_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS_PATH = os.path.join(OUT_DIR, "t265_results.json")
MAC_ROOT = "/Volumes/CometCloudAI/cometcloud-local"
CACHE_DIR = os.path.join(MAC_ROOT, "research", "t265")
CACHE_PRICES = os.path.join(CACHE_DIR, "cg_mcap.json")
CACHE_BENCH = os.path.join(CACHE_DIR, "bench_ohlcv.json")
CACHE_HOLDERS = os.path.join(CACHE_DIR, "holders.json")
CACHE_FAST = os.path.join(CACHE_DIR, "cg_mcap_fast.json")

# S-743 写死的参数
N_TOP_MCAP = 200          # 当周市值前 200
MIN_LISTING_WEEKS = 26    # 上市满 26 周
HOLD_LOOKBACK_D = 28      # H_{t-28}
MAX_STALE_D = 7           # 取 <= t 最近的点,相差 <= 7 天
JUMP_ABS_G = 1.0          # |g| > 1 视为数据跳变丢掉
FWD_D = 28                # 结果窗口 t -> t+28(副项 8 周 = 56)
VOL_WIN_D = 90            # 90 天波动
VOL_EXCL = 0.01           # 波动 < 1% ⇒ 稳定币 / 包装 / 质押衍生,去掉
NW_LAG = 4                # Newey-West 4 阶
N_PERM = 1000             # 零分布 1000 次
PERM_SEED = 743           # 种子 743
COVER_MIN_COINS = 80      # 前提:n_weekly >= 52 的币数 >= 80
COVER_MIN_WEEKS = 52
FETCH_WINDOW = "2023-06-01"


# ───────────────────────────────────────────────────────────── HTTP
def rest(path: str, params: dict | None = None, count: bool = False):
    params = dict(params or {})
    url = f"{SUPABASE_URL}/rest/v1/{path}?" + urllib.parse.urlencode(params, doseq=True)
    headers = dict(HDRS)
    if count:
        headers["Prefer"] = "count=exact"
    last = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=180) as r:
                body = r.read().decode("utf-8")
                cr = r.headers.get("Content-Range")
            rows = json.loads(body) if body else []
            total = None
            if cr and "/" in cr:
                tail = cr.split("/")[-1].strip()
                if tail.isdigit():
                    total = int(tail)
            return rows, total
        except urllib.error.HTTPError as e:
            last = e
            time.sleep(1.5 * (attempt + 1))
        except Exception as e:  # 网络抖动
            last = e
            time.sleep(1.5 * (attempt + 1))
    raise last


def fetch_all(path: str, params: dict, order: str, page: int = 1000) -> list[dict]:
    """分页拉取。必须带 order=;每页 <=1000 行(offset 超过 ~50k 后 PostgREST 会慢,但正确)。"""
    out, off = [], 0
    while True:
        p = dict(params)
        p["order"] = order
        p["limit"] = page
        p["offset"] = off
        rows, total = rest(path, p, count=True)
        out.extend(rows)
        if total is not None:
            if len(out) >= total or not rows:
                break
        elif len(rows) < page:
            break
        off += page
        if off % 20000 == 0:
            print(f"  ...{path} {off}/{total}", flush=True)
    return out


# ───────────────────────────────────────────────────────────── 阶段:前提
def stage_cover() -> dict:
    """前提检查:token_holders_coverage 里 n_weekly >= 52 的币数。< 80 ⇒ 停。"""
    rows = fetch_all("token_holders_coverage", {}, "coin_id.asc")
    res = {
        "checked_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "coverage_rows": len(rows),
        "n_weekly_ge_52": 0,
        "threshold_coins": COVER_MIN_COINS,
        "threshold_weeks": COVER_MIN_WEEKS,
        "pass_precondition": False,
    }
    if rows:
        counts = [int(r.get("n_weekly") or 0) for r in rows]
        res["n_weekly_ge_52"] = sum(1 for c in counts if c >= COVER_MIN_WEEKS)
        res["max_n_weekly"] = max(counts)
        res["median_n_weekly"] = sorted(counts)[len(counts) // 2]
    res["pass_precondition"] = res["n_weekly_ge_52"] >= COVER_MIN_COINS
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return res


def stage_raw_holders_count() -> dict:
    rows, total = rest("token_holders_daily", {"limit": 1}, count=True)
    return {"token_holders_daily_rows": total, "token_holders_coverage_rows": stage_cover()["coverage_rows"]}


# ───────────────────────────────────────────────────────────── 阶段:抓数
def stage_fetch(window: str = FETCH_WINDOW) -> None:
    os.makedirs(CACHE_DIR, exist_ok=True)
    print("fetch cg_coin_mcap_daily ...", flush=True)
    px = fetch_all(
        "cg_coin_mcap_daily",
        {"d": f"gte.{window}", "select": "coin_id,d,price,mcap,source"},
        "coin_id.asc,d.asc",
    )
    with open(CACHE_PRICES, "w") as f:
        json.dump(px, f)
    print(f"  prices rows={len(px)} -> {CACHE_PRICES}", flush=True)

    print("fetch ohlcv_daily (BTC/ETH benchmark) ...", flush=True)
    bench = fetch_all(
        "ohlcv_daily",
        {"symbol": "in.(BTC,ETH)", "trade_date": f"gte.{window}",
         "select": "symbol,trade_date,close,source,recorded_at"},
        "symbol.asc,trade_date.asc,recorded_at.desc",
    )
    with open(CACHE_BENCH, "w") as f:
        json.dump(bench, f)
    print(f"  bench rows={len(bench)} -> {CACHE_BENCH}", flush=True)

    print("fetch token_holders_daily ...", flush=True)
    h = fetch_all("token_holders_daily", {}, "coin_id.asc,d.asc")
    with open(CACHE_HOLDERS, "w") as f:
        json.dump(h, f)
    print(f"  holders rows={len(h)} -> {CACHE_HOLDERS}", flush=True)


# ───────────────────────────────────────────────────────────── 价格侧工具
def _series(rows, key="d", val="price"):
    """{(coin): (dates[], values[])}"""
    out = defaultdict(lambda: ([], []))
    for r in rows:
        d, v = r.get(key), r.get(val)
        if d is None or v is None:
            continue
        ds, vs = out[r["coin_id"] if "coin_id" in r else r["symbol"]]
        ds.append(d)
        vs.append(v)
    return out


def _price_at(dates, closes, d, max_gap=3):
    return price_on_or_after(dates, closes, d, max_gap_days=max_gap)


def _std_daily(logrets):
    if len(logrets) < 20:
        return float("nan")
    return float(np.std(logrets, ddof=1))


# ───────────────────────────────────────────────────────────── 检验核心
def spearman(x, y):
    rx = np.argsort(np.argsort(x)).astype(float)
    ry = np.argsort(np.argsort(y)).astype(float)
    if rx.std() == 0 or ry.std() == 0:
        return float("nan")
    return float(np.corrcoef(rx, ry)[0, 1])


def newey_west_t(x, lag=NW_LAG):
    """Newey-West(HAC,Bartlett) 对均值的 t 统计。"""
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    n = len(x)
    if n < 5:
        return float("nan"), float("nan"), n
    e = x - x.mean()
    lrv = float(np.dot(e, e)) / n
    for j in range(1, min(lag, n - 1) + 1):
        w = 1.0 - j / (lag + 1.0)
        lrv += 2.0 * w * float(np.dot(e[j:], e[:-j])) / n
    if lrv <= 0:
        return float("nan"), float("nan"), n
    se = math.sqrt(lrv / n)
    return float(x.mean() / se), float(x.mean()), n


def rank_regression_resid(y, xs):
    """横截面秩回归残差:y 对 xs 的秩(百分位)回归。"""
    y = np.asarray(y, dtype=float)
    X = np.column_stack([_pct(xs[0]), _pct(xs[1])])
    Y = _pct(y)
    A = np.column_stack([np.ones(len(Y)), X])
    beta, *_ = np.linalg.lstsq(A, Y, rcond=None)
    return Y - A @ beta


def _pct(v):
    v = np.asarray(v, dtype=float)
    if len(v) == 0:
        return v
    order = np.argsort(np.argsort(v)).astype(float)
    return order / max(len(v) - 1, 1)


def build_panel(prices, bench, holders, horizon=FWD_D, with_feature=True):
    """按 S-743 写死的口径造每周横截面样本。返回 (weeks, diagnostics)。"""
    px = _series(prices, "d", "price")
    mc = _series(prices, "d", "mcap")
    first_d = {}
    for r in prices:
        cid = r["coin_id"]
        if cid not in first_d or r["d"] < first_d[cid]:
            first_d[cid] = r["d"]
    bt = defaultdict(lambda: ([], []))
    for r in bench:
        ds, vs = bt[r["symbol"]]
        ds.append(r["trade_date"])
        vs.append(r["close"])
    hd = defaultdict(list)
    for r in holders:
        hd[r["coin_id"]].append((r["d"], float(r["holders"])))
    for k in hd:
        hd[k].sort()

    # 每周一
    all_days = sorted({r["d"] for r in prices})
    mondays = []
    for d in all_days:
        y, m, dd = (int(x) for x in d.split("-"))
        if dd == 1:
            mondays.append(d)
    if not mondays:
        return [], {"error": "no mondays"}

    weeks, diag = [], defaultdict(int)
    for t in mondays:
        t_ts = time.mktime(time.strptime(t, "%Y-%m-%d"))
        rows = []
        for cid, (ds, vs) in px.items():
            p_t = _price_at(ds, vs, t, 3)
            if p_t is None or p_t <= 0:
                continue
            m_t = _price_at(mc[cid][0], mc[cid][1], t, 3) if cid in mc else None
            if m_t is None or m_t <= 0:
                continue
            # 上市满 26 周
            if cid in first_d:
                age_d = (t_ts - time.mktime(time.strptime(first_d[cid], "%Y-%m-%d"))) / 86400.0
                if age_d < MIN_LISTING_WEEKS * 7:
                    continue
            rows.append({"coin": cid, "p_t": p_t, "mcap": m_t})
        if not rows:
            continue
        # 当周市值前 200
        rows.sort(key=lambda r: -r["mcap"])
        rows = rows[:N_TOP_MCAP]
        # 90 天波动锚:相对 BTC / ETH / 1 美元,任一 < 1% ⇒ 去掉
        keep = []
        for r in rows:
            cid = r["coin"]
            ds, vs = px[cid]
            win = [(d, v) for d, v in zip(ds, vs) if t_ts - 90 * 86400 <= time.mktime(time.strptime(d, "%Y-%m-%d")) <= t_ts]
            if len(win) < 30:
                continue
            wdates = [d for d, _ in win]
            wvals = [v for _, v in win]
            bdates, bvals = bt["BTC"]
            edates, evals = bt["ETH"]
            rel_b, rel_e, rel_u = [], [], []
            for d, v in win:
                pb = _price_at(bdates, bvals, d, 3)
                pe = _price_at(edates, evals, d, 3)
                if pb and pb > 0:
                    rel_b.append(math.log(v / pb))
                if pe and pe > 0:
                    rel_e.append(math.log(v / pe))
                rel_u.append(math.log(v))
            vols = [_std_daily(np.diff(rel_b)) if len(rel_b) > 21 else float("nan"),
                    _std_daily(np.diff(rel_e)) if len(rel_e) > 21 else float("nan"),
                    _std_daily(np.diff(rel_u))]
            if any((not math.isnan(v)) and v < VOL_EXCL for v in vols):
                diag["excluded_vol_anchor"] += 1
                continue
            r["vol_anchor_min"] = float(np.nanmin(vols))
            keep.append(r)
        rows = keep
        if len(rows) < 20:
            diag["weeks_dropped_small_universe"] += 1
            continue
        # 特征
        for r in rows:
            cid = r["coin"]
            # 过去 4 周对数收益
            ds, vs = px[cid]
            p_prev = _price_at(ds, vs, (time.strftime("%Y-%m-%d", time.localtime(t_ts - 28 * 86400))), 7)
            r["ret4w"] = math.log(r["p_t"] / p_prev) if p_prev else float("nan")
            r["ln_mcap"] = math.log(r["mcap"])
            if with_feature:
                seq = hd.get(cid) or []
                h_t = h_t28 = None
                for d, h in seq:
                    if d <= t:
                        h_t = (d, h)
                    if d <= (time.strftime("%Y-%m-%d", time.localtime(t_ts - HOLD_LOOKBACK_D * 86400))):
                        h_t28 = (d, h)
                if not h_t or not h_t28:
                    continue
                if (t_ts - time.mktime(time.strptime(h_t[0], "%Y-%m-%d"))) / 86400.0 > MAX_STALE_D:
                    continue
                if ((t_ts - HOLD_LOOKBACK_D * 86400) - time.mktime(time.strptime(h_t28[0], "%Y-%m-%d"))) / 86400.0 > MAX_STALE_D:
                    continue
                r["g"] = math.log(h_t[1] / h_t28[1])
                r["h_t"] = h_t[0]
                r["h_t28"] = h_t28[0]
        if with_feature:
            feat = [r for r in rows if "g" in r and abs(r["g"]) <= JUMP_ABS_G]
            diag["weeks_jump_dropped"] += len(rows) - len(feat)
            rows = feat
            if len(rows) < 20:
                diag["weeks_dropped_small_after_feature"] += 1
                continue
        # 结果:t -> t+28 相对 BTC 的对数超额
        bdates, bvals = bt["BTC"]
        b_t = _price_at(bdates, bvals, t, 3)
        b_t28 = _price_at(bdates, bvals, (time.strftime("%Y-%m-%d", time.localtime(t_ts + horizon * 86400))), 7)
        if b_t is None or b_t28 is None:
            continue
        for r in rows:
            ds, vs = px[r["coin"]]
            p_end = _price_at(ds, vs, (time.strftime("%Y-%m-%d", time.localtime(t_ts + horizon * 86400))), 7)
            if p_end is None or p_end <= 0:
                r["fwd"] = None
                continue
            r["fwd_log"] = math.log(p_end / r["p_t"]) - math.log(b_t28 / b_t)
            r["fwd_pct"] = (p_end / r["p_t"]) / (b_t28 / b_t) - 1.0
        rows = [r for r in rows if r.get("fwd_log") is not None]
        if len(rows) < 20:
            diag["weeks_dropped_small_after_fwd"] += 1
            continue
        # 主特征 g_res
        if with_feature:
            res = rank_regression_resid([r["g"] for r in rows],
                                        ([r["ret4w"] for r in rows], [r["ln_mcap"] for r in rows]))
            for r, v in zip(rows, res):
                r["g_res"] = float(v)
        weeks.append({"t": t, "rows": rows, "n": len(rows)})
        diag["weeks_kept"] += 1
    return weeks, dict(diag)


def evaluate_panel(weeks, feature="g_res", horizon_label="4w"):
    """S-743 的 (a)–(d)。"""
    ics, spreads_log, spreads_pct = [], [], []
    for w in weeks:
        rows = w["rows"]
        x = np.array([r[feature] for r in rows], dtype=float)
        y = np.array([r["fwd_log"] for r in rows], dtype=float)
        ic = spearman(x, y)
        if not math.isnan(ic):
            ics.append(ic)
        k = max(1, len(rows) // 5)
        order = np.argsort(x)
        lo = [rows[i] for i in order[:k]]
        hi = [rows[i] for i in order[-k:]]
        spreads_log.append(np.mean([r["fwd_log"] for r in hi]) - np.mean([r["fwd_log"] for r in lo]))
        spreads_pct.append((np.mean([r["fwd_pct"] for r in hi]) - np.mean([r["fwd_pct"] for r in lo])) * 100.0)
    if not ics:
        return {"error": "no weeks with IC"}
    t_stat, mean_ic, n = newey_west_t(ics)
    # (c) 每周内打乱 g_res,1000 次,种子 743
    groups = np.array([w["t"] for w in weeks for _ in w["rows"]], dtype=object)
    feats = np.array([r[feature] for w in weeks for r in w["rows"]], dtype=object)
    outs = np.array([r["fwd_log"] for w in weeks for r in w["rows"]], dtype=float)
    wk_idx = np.array([i for i, w in enumerate(weeks) for _ in w["rows"]], dtype=int)

    def one_draw(rng):
        sh = shuffle_within(feats, groups, rng)
        vals = []
        for i in range(len(weeks)):
            m = wk_idx == i
            ic = spearman(np.asarray(sh[m], dtype=float), outs[m])
            if not math.isnan(ic):
                vals.append(ic)
        return float(np.mean(vals)) if vals else float("nan")

    perm = None
    pct = None
    try:
        perm = null_distribution(one_draw, N_PERM, PERM_SEED, actual=mean_ic)
        pct = percentile_of(mean_ic, perm)
    except NoOpNull as e:
        pct = None
        perm_err = str(e)
    # (d) 两段同号
    half = len(ics) // 2
    ic1 = float(np.mean(ics[:half]))
    ic2 = float(np.mean(ics[half:])) if len(ics) > half else float("nan")
    verdict = {
        "a": bool(mean_ic > 0 and (math.isnan(t_stat) is False) and t_stat >= 2.0),
        "b_log": bool(np.mean(spreads_log) >= 0.015),
        "b_pct": bool(np.mean(spreads_pct) >= 1.5),
        "c": bool(pct is not None and pct >= 0.95),
        "d": bool((ic1 > 0 and ic2 > 0) or (ic1 < 0 and ic2 < 0)),
    }
    return {
        "feature": feature,
        "horizon": horizon_label,
        "n_weeks": len(weeks),
        "n_obs": int(sum(w["n"] for w in weeks)),
        "mean_ic": mean_ic,
        "ic_t_newey_west": t_stat,
        "ic_median": float(np.median(ics)),
        "ic_std": float(np.std(ics, ddof=1)) if len(ics) > 1 else float("nan"),
        "ic_pct_positive": float(np.mean(np.array(ics) > 0)),
        "quintile_spread_log": float(np.mean(spreads_log)),
        "quintile_spread_pct": float(np.mean(spreads_pct)),
        "perm_percentile": pct,
        "perm_null_mean": float(np.mean(perm)) if perm is not None else None,
        "perm_null_sd": float(np.std(perm, ddof=1)) if perm is not None else None,
        "halves": {"ic_first": ic1, "ic_second": ic2},
        "verdict": verdict,
        "all_pass": bool(all(verdict.values())),
    }


# ───────────────────────────────────────────────────────────── 阶段:自检
def _synth_panel(n_weeks=40, n_assets=120, seed=11, mode="planted"):
    """合成面板(仅用于机器自检,不是证据)。mode: planted / null / ret_only。"""
    rng = np.random.default_rng(seed)
    weeks = []
    for w in range(n_weeks):
        t = f"2025-{1 + (w // 4):02d}-{1 + 4 * (w % 4):02d}"
        rows = []
        for a in range(n_assets):
            g = rng.normal()
            ret = rng.normal()
            lnm = rng.normal()
            if mode == "planted":
                fwd = 0.05 * g + rng.normal(0, 0.03)
            elif mode == "ret_only":
                fwd = 0.30 * ret + rng.normal(0, 0.03)
            else:
                fwd = rng.normal(0, 0.03)
            rows.append({"coin": f"c{a}", "g": g, "g_res": 0.0, "ret4w": ret,
                         "ln_mcap": lnm, "fwd_log": fwd, "fwd_pct": math.exp(fwd) - 1.0})
        res = rank_regression_resid([r["g"] for r in rows], ([r["ret4w"] for r in rows], [r["ln_mcap"] for r in rows]))
        for r, v in zip(rows, res):
            r["g_res"] = float(v)
        weeks.append({"t": t, "rows": rows, "n": len(rows)})
    return weeks


def stage_selftest() -> dict:
    out = {}
    planted = evaluate_panel(_synth_panel(mode="planted"), "g_res", "synthetic-4w")
    null = evaluate_panel(_synth_panel(mode="null"), "g_res", "synthetic-4w")
    ret_only = evaluate_panel(_synth_panel(mode="ret_only"), "g_res", "synthetic-4w")
    keys = ("mean_ic", "ic_t_newey_west", "quintile_spread_pct", "perm_percentile", "verdict")
    out["planted"] = {k: planted[k] for k in keys}
    out["null"] = {k: null[k] for k in keys}
    out["ret_only"] = {k: ret_only[k] for k in keys}
    checks = {
        "planted_ic_positive": planted["mean_ic"] > 0.1,
        "planted_t_ge_2": (planted["ic_t_newey_west"] or -9) >= 2.0,
        "planted_perm_ge_095": (planted["perm_percentile"] or 0) >= 0.95,
        "planted_split_half_same_sign": planted["verdict"]["d"],
        "null_ic_near_zero": abs(null["mean_ic"]) < 0.05,
        "null_perm_not_significant": (null["perm_percentile"] or 0.5) < 0.95,
        "ret_only_resid_drops_signal": abs(ret_only["mean_ic"]) < 0.05,
    }
    out["checks"] = checks
    out["all_checks_pass"] = all(checks.values())
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return out


# ───────────────────────────────────────────────────────────── 阶段:跑
def stage_run() -> dict:
    gate = stage_raw_holders_count()
    out = {"task": "T-265", "ledger": "S-743", "gate": gate,
           "ran_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    if not gate["pass_precondition"]:
        out["status"] = "STOPPED_PRECONDITION"
        out["reason"] = (
            f"token_holders_daily 空 / n_weekly>=52 的币数 {gate['n_weekly_ge_52']} < {COVER_MIN_COINS}:"
            "回填还没完,按卡 acceptance ① 不跑 (a)–(d)。"
        )
        out["criteria"] = {k: None for k in ("a", "b", "c", "d")}
        with open(RESULTS_PATH, "w") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return out
    prices = json.load(open(CACHE_PRICES))
    bench = json.load(open(CACHE_BENCH))
    holders = json.load(open(CACHE_HOLDERS))
    weeks, diag = build_panel(prices, bench, holders, horizon=FWD_D, with_feature=True)
    out["panel"] = {"n_weeks": len(weeks), "diag": diag}
    out["main"] = evaluate_panel(weeks, "g_res", "4w")
    out["side_raw_g"] = evaluate_panel(weeks, "g", "4w")
    weeks8, _ = build_panel(prices, bench, holders, horizon=56, with_feature=True)
    out["side_8w"] = evaluate_panel(weeks8, "g_res", "8w")
    with open(RESULTS_PATH, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return out


def stage_universe_diag() -> dict:
    """价格侧诊断(不需要持有人):每周的宇宙规模、mcap 覆盖、基准可得性。"""
    src = CACHE_PRICES if os.path.exists(CACHE_PRICES) else CACHE_FAST
    prices = json.load(open(src))
    bench = json.load(open(CACHE_BENCH))
    weeks, diag = build_panel(prices, bench, [], horizon=FWD_D, with_feature=False)
    sizes = [w["n"] for w in weeks]
    out = {
        "price_cache": src,
        "n_weeks": len(weeks),
        "week_range": [weeks[0]["t"], weeks[-1]["t"]] if weeks else None,
        "universe_n": {"min": min(sizes) if sizes else None, "median": int(np.median(sizes)) if sizes else None,
                       "max": max(sizes) if sizes else None},
        "diag": diag,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return out


def stage_fetch_fast(window: str = "2024-08-01", n_candidates: int = 300) -> None:
    """快速抓价格:按 coin 逐个抓(每个 coin 一页),候选集 = cg_coin_mcap_coins 里 last_mcap 前 N。
    offset 分页在 40 万行上会退化(O(n²)),逐 coin 抓是 O(n) 次请求。
    候选集用**期末**市值挑 ⇒ 有前视偏差,只用于价格侧诊断(不用于 (a)–(d) 的宇宙)。"""
    os.makedirs(CACHE_DIR, exist_ok=True)
    cands, _ = rest("cg_coin_mcap_coins", {"select": "coin_id,last_mcap", "limit": n_candidates,
                                           "order": "last_mcap.desc"})
    coins = [c["coin_id"] for c in cands]
    print(f"candidates: {len(coins)}", flush=True)
    rows = []
    for i, cid in enumerate(coins):
        got = fetch_all("cg_coin_mcap_daily", {"coin_id": f"eq.{cid}", "d": f"gte.{window}",
                                                "select": "coin_id,d,price,mcap,source"},
                        "d.asc")
        rows.extend(got)
        if (i + 1) % 50 == 0:
            print(f"  ...{i+1}/{len(coins)} coins, {len(rows)} rows", flush=True)
    with open(CACHE_FAST, "w") as f:
        json.dump(rows, f)
    print(f"fast prices rows={len(rows)} -> {CACHE_FAST}", flush=True)

    bench = fetch_all("ohlcv_daily", {"symbol": "in.(BTC,ETH)", "trade_date": f"gte.{window}",
                                      "select": "symbol,trade_date,close,source,recorded_at"},
                      "symbol.asc,trade_date.asc,recorded_at.desc")
    with open(CACHE_BENCH, "w") as f:
        json.dump(bench, f)
    print(f"bench rows={len(bench)} -> {CACHE_BENCH}", flush=True)

    h = fetch_all("token_holders_daily", {}, "coin_id.asc,d.asc")
    with open(CACHE_HOLDERS, "w") as f:
        json.dump(h, f)
    print(f"holders rows={len(h)} -> {CACHE_HOLDERS}", flush=True)


def stage_scen() -> None:
    """情景文件需要的量:macro_daily 的 series 名单 + BTC 最近收盘(ohlcv_daily)。"""
    v, series = None, []
    while len(series) < 40:
        p = {"select": "series", "limit": 1, "order": "series.asc"}
        if v is not None:
            p["series"] = f"gt.{v}"
        rows, _ = rest("macro_daily", p)
        if not rows:
            break
        v = rows[0]["series"]
        if v in series:
            break
        series.append(v)
    print("macro series:", series)
    rows, _ = rest("ohlcv_daily", {"symbol": "eq.BTC", "select": "trade_date,close,source,recorded_at",
                                   "limit": 5, "order": "trade_date.desc,recorded_at.desc"})
    print("BTC last:", json.dumps(rows, ensure_ascii=False))
    rows, _ = rest("ohlcv_daily", {"symbol": "eq.ETH", "select": "trade_date,close", "limit": 1,
                                   "order": "trade_date.desc"})
    print("ETH last:", json.dumps(rows, ensure_ascii=False))
    feats, _ = rest("state_daily", {"select": "feature", "limit": 200, "order": "feature.asc"})
    seen = sorted({f["feature"] for f in feats})
    print(f"state features ({len(seen)}):", json.dumps(seen[:40], ensure_ascii=False))
    for s in ("vix", "fng"):
        rows, _ = rest("macro_daily", {"series": f"eq.{s}", "select": "d,value", "limit": 3, "order": "d.desc"})
        print(f"macro {s}:", json.dumps(rows, ensure_ascii=False))
    rows, _ = rest("state_daily", {"entity": "eq.panel", "feature": "eq.breadth_above_ma50",
                                   "select": "d,value", "limit": 3, "order": "d.desc"})
    print("state breadth_above_ma50:", json.dumps(rows, ensure_ascii=False))


def stage_report() -> dict:
    """组装交付用的 t265_results.json:前提 + 自检 + 价格侧诊断 + (a)-(d) 槽位。"""
    gate = stage_raw_holders_count()
    out = {
        "task": "T-265",
        "ledger": "S-743",
        "ran_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "gate": gate,
        "criteria": {k: None for k in ("a", "b", "c", "d")},
        "criteria_reason": "前提未满足(token_holders_daily 空):按卡 acceptance ① 不跑",
        "selftest": stage_selftest(),
    }
    if os.path.exists(CACHE_FAST) or os.path.exists(CACHE_PRICES):
        try:
            out["price_side"] = stage_universe_diag()
        except Exception as e:  # 诊断失败不影响交付主体
            out["price_side"] = {"error": repr(e)}
    with open(RESULTS_PATH, "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("wrote", RESULTS_PATH)
    return out


if __name__ == "__main__":
    stage = sys.argv[1] if len(sys.argv) > 1 else "cover"
    if stage == "fetchfast":
        stage_fetch_fast()
    elif stage == "report":
        stage_report()
    elif stage == "scen":
        stage_scen()
    elif stage == "cover":
        stage_cover()
    elif stage == "fetch":
        stage_fetch()
    elif stage == "selftest":
        stage_selftest()
    elif stage == "run":
        stage_run()
    elif stage == "universe":
        stage_universe_diag()
    else:
        print(f"unknown stage {stage}")
        sys.exit(2)
