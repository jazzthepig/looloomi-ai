#!/usr/bin/env python3
"""T-232 —— 标记线的前向基率(条件 C 之后 28 天,BTC 碰 200 日线的概率)。

## 预注册口径(先写后算,只算一次,不扫参数)

**样本与最早可得日**
- state_daily(entity=panel) 自 2019-01-01 起(四个特征都从这天开始);条件 C 需要三个特征同时非空,
  而 vol_pct_3y 在 2021-07-12 及以前全是 NULL ⇒ **C 的最早可得日 = 2021-07-13**。
- universe = 2021-07-13 起、且 BTC 侧还剩满 28 根日线的每个日历日(收盘)。

**条件 C**(三个同时成立)
- breadth_above_ma50 ≤ 0.10
- dist_200 ∈ [0, 0.10](0 = 贴线,0.10 = 在线之上 10%)
- vol_pct_3y < 0.20

**事件簇**
- 满足 C 的日子按时间排序;相邻两个满足日之间间隔 ≤ 10 天 ⇒ 归为同一簇;**取簇首日**;簇数 = 独立事件数。

**观测窗(t = 簇首日,入场 = t 日收盘)**
- 窗口 = t+1 … t+28 共 28 根 BTC 日线(ohlcv_daily, symbol=BTC, source=binance_hist)。
- (1) 碰线:窗口内**任一天** BTC 收盘 < **当日** 200 日均线(用 binance_hist 收盘的 200 日简单均线)⇒ touch=1。
- (2) 28 日收益 = close[t+28] / close[t] − 1。
- (3) 28 日最大回撤 = 窗口内(含 t 的收盘)收盘序列 running peak → trough 的最大跌幅。

**对照**
- 无条件基率:universe 内每一天同口径。
- 随机对照:抽**同样个数的簇首日**,块抽样(平稳块自助,apparatus.stationary_bootstrap_index,mean_block=20),
  1,000 次,种子 232;用 apparatus.null_distribution / percentile_of。

**判定门槛**
- 独立事件簇 < 8 ⇒ **只报不判**(不写「显著 / 不显著」)。

**副列(只报不判)**
- C 且 stable_supply_30d < −0.02(该特征最早可得日 2019-01-01)。

纪律:只读 SELECT;不改代码、不做 DDL、不入库;翻页带 order=;零分布/盈亏只用 src/data/evaluation/apparatus.py。
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta

import numpy as np

BASE = os.environ["SUPABASE_URL"].rstrip("/") + "/rest/v1"
KEY = os.environ["SUPABASE_KEY"]
HEADERS = {"apikey": KEY, "Authorization": f"Bearer {KEY}", "Accept": "application/json"}

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_spec = importlib.util.spec_from_file_location("apparatus", os.path.join(ROOT, "src", "data", "evaluation", "apparatus.py"))
apparatus = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(apparatus)

FEATURES = ["breadth_above_ma50", "dist_200", "vol_pct_3y", "stable_supply_30d"]
CACHE = "/Volumes/CometCloudAI/cometcloud-local/research/t232_cache"
HORIZON = 28
CLUSTER_GAP = 10
SEED = 232
N_NULL = 1000

# 条件 C 的阈值(预注册,不扫参)
C_BREADTH_MAX = 0.10
C_DIST_LO, C_DIST_HI = 0.0, 0.10
C_VOL_MAX = 0.20
SUPPLY_MAX = -0.02


# ── 取数 ────────────────────────────────────────────────────────────────────

def get(path: str, params: dict) -> list[dict]:
    q = "&".join(f"{k}={urllib.parse.quote(str(v))}" for k, v in params.items())
    req = urllib.request.Request(f"{BASE}/{path}?{q}", headers=HEADERS)
    with urllib.request.urlopen(req, timeout=180) as r:
        body = r.read().decode()
    return json.loads(body) if body else []


def fetch_all(table: str, filters: dict, order: str, columns: str = "*") -> list[dict]:
    """翻页读,一律带 order=(PostgREST 不带 order 时边界会漂);服务端行数上限 1000。"""
    rows: list[dict] = []
    offset = 0
    while True:
        params = dict(filters)
        params.update({"select": columns, "order": order, "limit": "1000", "offset": str(offset)})
        page = get(table, params)
        rows.extend(page)
        if len(page) < 1000:
            break
        offset += 1000
    return rows


def fetch() -> None:
    os.makedirs(CACHE, exist_ok=True)
    for f in FEATURES:
        rows = fetch_all("state_daily", {"entity": "eq.panel", "feature": f"eq.{f}"}, "d.asc",
                         "d,feature,value,source,code_ref,computed_at")
        ds = [r["d"] for r in rows]
        with open(f"{CACHE}/state_{f}.json", "w") as fh:
            json.dump(rows, fh)
        print(f"{f}: {len(rows)} rows, {ds[0]} → {ds[-1]}, nulls={sum(1 for r in rows if r['value'] is None)}")
    for src, cols in (("binance_hist", "trade_date,open,high,low,close,volume"), ("coingecko", "trade_date,close")):
        rows = fetch_all("ohlcv_daily", {"symbol": "eq.BTC", "source": f"eq.{src}"}, "trade_date.asc", cols)
        with open(f"{CACHE}/btc_{src}.json", "w") as fh:
            json.dump(rows, fh)
        ds = [r["trade_date"] for r in rows]
        print(f"BTC {src}: {len(rows)} rows, {ds[0]} → {ds[-1]}")


# ── 计算 ────────────────────────────────────────────────────────────────────

def ma(closes: list[float], n: int) -> list[float | None]:
    out: list[float | None] = [None] * len(closes)
    s = 0.0
    for i, c in enumerate(closes):
        s += c
        if i >= n:
            s -= closes[i - n]
        if i >= n - 1:
            out[i] = s / n
    return out


def load():
    st = {}
    for f in FEATURES:
        rows = json.load(open(f"{CACHE}/state_{f}.json"))
        st[f] = {r["d"]: r["value"] for r in rows}
    btc = json.load(open(f"{CACHE}/btc_binance_hist.json"))
    btc.sort(key=lambda r: r["trade_date"])
    dates = [r["trade_date"] for r in btc]
    closes = [float(r["close"]) for r in btc]
    return st, dates, closes


def clusters(days: list[str], gap: int = CLUSTER_GAP) -> list[list[str]]:
    """相邻间隔 ≤ gap 天的满足日归为一簇;返回每簇的首日。"""
    out: list[list[str]] = []
    for d in sorted(days):
        if out:
            prev = date.fromisoformat(out[-1][-1])
            if (date.fromisoformat(d) - prev).days <= gap:
                out[-1].append(d)
                continue
        out.append([d])
    return out


def per_day_stats(dates, closes, m200, idx, day_list, shift=0):
    """对每个日子算:碰线 / 28 日收益 / 28 日最大回撤。shift=1 = 信号日往后挪一天(稳健性)。"""
    n = len(dates)
    st = {}
    for d in day_list:
        i = idx.get(d)
        if i is None or i + HORIZON + shift >= n or i + shift < 199:
            continue
        j = i + shift  # 入场日
        k_end = j + HORIZON
        touch = False
        for k in range(j + 1, k_end + 1):
            if closes[k] < m200[k]:
                touch = True
                break
        ret = closes[k_end] / closes[j] - 1.0
        peak, mdd = closes[j], 0.0
        for k in range(j, k_end + 1):
            peak = max(peak, closes[k])
            mdd = min(mdd, closes[k] / peak - 1.0)
        st[d] = {"touch": int(touch), "ret": ret, "mdd": mdd,
                 "dist_t": closes[j] / m200[j] - 1.0, "entry": closes[j]}
    return st


def summarize(days: list[str], st: dict) -> dict:
    if not days:
        return {"n": 0, "n_touch": 0, "touch_rate": None, "ret_mean": None,
                "ret_p10": None, "ret_p50": None, "ret_p90": None,
                "mdd_mean": None, "mdd_median": None, "mdd_worst": None}
    touch = [st[d]["touch"] for d in days]
    rets = sorted(st[d]["ret"] for d in days)
    mdds = sorted(st[d]["mdd"] for d in days)

    def q(a, p):
        if not a:
            return None
        k = min(len(a) - 1, max(0, int(round(p * (len(a) - 1)))))
        return float(a[k])

    return {
        "n": len(days),
        "touch_rate": float(np.mean(touch)),
        "n_touch": int(sum(touch)),
        "ret_mean": float(np.mean(rets)),
        "ret_p10": q(rets, 0.10), "ret_p50": q(rets, 0.50), "ret_p90": q(rets, 0.90),
        "mdd_mean": float(np.mean(mdds)),
        "mdd_median": q(mdds, 0.50), "mdd_worst": float(mdds[0]),
    }


def run() -> None:
    st, dates, closes = load()
    m200 = ma(closes, 200)
    idx = {d: i for i, d in enumerate(dates)}
    n = len(dates)

    # ── universe:C 的三个特征都非空 + BTC 侧还剩满 28 根日线 ──
    last_ok = dates[n - HORIZON - 1]
    universe = [d for d in sorted(st["breadth_above_ma50"])
                if st["breadth_above_ma50"][d] is not None
                and st["dist_200"][d] is not None
                and st["vol_pct_3y"][d] is not None
                and d <= last_ok]
    stats = per_day_stats(dates, closes, m200, idx, universe)
    universe = [d for d in universe if d in stats]

    # ── 条件 C ──
    def is_c(d):
        return (st["breadth_above_ma50"][d] <= C_BREADTH_MAX
                and C_DIST_LO <= st["dist_200"][d] <= C_DIST_HI
                and st["vol_pct_3y"][d] < C_VOL_MAX)

    qual = [d for d in universe if is_c(d)]
    cls = clusters(qual)
    cluster_firsts = [c[0] for c in cls]

    # 满足 C 但没有满 28 天前瞻数据的日子(= 当下正在发生的那一簇)
    live = [d for d in sorted(st["breadth_above_ma50"])
            if d > last_ok and st["breadth_above_ma50"][d] is not None
            and st["dist_200"][d] is not None and st["vol_pct_3y"][d] is not None and is_c(d)]
    live_cls = clusters(live)

    # ── 副列:C 且 stable_supply_30d < −0.02(只报不判) ──
    qual_s = [d for d in qual if st["stable_supply_30d"].get(d) is not None
              and st["stable_supply_30d"][d] < SUPPLY_MAX]
    cls_s = clusters(qual_s)
    firsts_s = [c[0] for c in cls_s]

    cond = summarize(cluster_firsts, stats)
    base = summarize(universe, stats)
    cond_s = summarize(firsts_s, stats)

    # 每个簇首日的明细(可逐条核)
    detail = []
    for c in cls:
        t = c[0]
        i = idx[t]
        win = list(range(i + 1, i + HORIZON + 1))
        rel = [closes[k] / m200[k] - 1.0 for k in win]
        touch_k = [k for k in win if closes[k] < m200[k]]
        s = stats[t]
        detail.append({
            "cluster_first": t, "n_members": len(c), "members": c,
            "state": {"breadth_above_ma50": st["breadth_above_ma50"][t], "dist_200": st["dist_200"][t],
                      "vol_pct_3y": st["vol_pct_3y"][t], "stable_supply_30d": st["stable_supply_30d"][t]},
            "btc": {"entry_close": s["entry"], "ma200_at_t": m200[i], "dist_t_binance": s["dist_t"],
                    "exit_close": closes[i + HORIZON], "ret28": s["ret"], "mdd": s["mdd"]},
            "touch": s["touch"], "first_touch_date": dates[touch_k[0]] if touch_k else None,
            "min_rel_ma200_in_window": min(rel),
        })
    live_detail = [{"cluster_first": c[0], "members": c,
                    "state": {f: st[f][c[0]] for f in FEATURES},
                    "cluster_size": len(c)} for c in live_cls]

    # ── 随机对照:抽同样个数的簇首日,块抽样,种子 232 ──
    n_draw = len(cluster_firsts)
    uni = universe

    def rep_touch(rng):
        ids = apparatus.stationary_bootstrap_index(len(uni), 20.0, 1, rng)[0][:n_draw]
        return float(np.mean([stats[uni[j]]["touch"] for j in ids]))

    def rep_ret(rng):
        ids = apparatus.stationary_bootstrap_index(len(uni), 20.0, 1, rng)[0][:n_draw]
        return float(np.mean([stats[uni[j]]["ret"] for j in ids]))

    def rep_mdd(rng):
        ids = apparatus.stationary_bootstrap_index(len(uni), 20.0, 1, rng)[0][:n_draw]
        return float(np.mean([stats[uni[j]]["mdd"] for j in ids]))

    actual = cond["touch_rate"]
    if n_draw == 0:
        null_touch = null_ret = null_mdd = null_touch_iid = np.array([])
    else:
        null_touch = apparatus.null_distribution(rep_touch, N_NULL, SEED, actual=actual)
        null_ret = apparatus.null_distribution(rep_ret, N_NULL, SEED + 1, actual=cond["ret_mean"])
        null_mdd = apparatus.null_distribution(rep_mdd, N_NULL, SEED + 2, actual=cond["mdd_mean"])

        # iid 变体(块长=1,apparatus 文档里同一函数的退化)—— 稳健性,不是主口径
        def rep_touch_iid(rng):
            ids = apparatus.stationary_bootstrap_index(len(uni), 1.0, 1, rng)[0][:n_draw]
            return float(np.mean([stats[uni[j]]["touch"] for j in ids]))

        null_touch_iid = apparatus.null_distribution(rep_touch_iid, N_NULL, SEED, actual=actual)

    res = {
        "prereg": {
            "condition_C": f"breadth_above_ma50 ≤ {C_BREADTH_MAX} 且 dist_200 ∈ [{C_DIST_LO}, {C_DIST_HI}] "
                           f"且 vol_pct_3y < {C_VOL_MAX}",
            "cluster_gap_days": CLUSTER_GAP, "horizon_days": HORIZON,
            "window": "t+1 … t+28(binance_hist 日线);入场 = t 日收盘",
            "touch_def": "窗口内任一天 close < 当日 200 日简单均线",
            "null": f"抽同样个数的簇首日,平稳块自助 mean_block=20,{N_NULL} 次,种子 {SEED}",
        },
        "data": {
            "state_range": [min(st["breadth_above_ma50"]), max(st["breadth_above_ma50"])],
            "vol_pct_3y_null_until": "2021-07-12(C 的最早可得日 2021-07-13)",
            "btc_range": [dates[0], dates[-1]],
            "universe": [universe[0], universe[-1]], "universe_n": len(universe),
            "last_day_with_28_forward_bars": last_ok,
        },
        "condition_C": {
            "n_qualifying_days": len(qual),
            "n_clusters": len(cls), "cluster_sizes": [len(c) for c in cls],
            "cluster_firsts": cluster_firsts,
            "cluster_members": {c[0]: c for c in cls},
            "qualifying_days": {d: {f: st[f][d] for f in FEATURES} for d in qual},
            "cluster_detail": detail,
            "stats": cond,
        },
        "live_episode": {
            "note": "满足 C 但还没有满 28 天前瞻数据(无法计量);到期 ≈ 首日 + 28 天",
            "clusters": live_detail,
            "resolves_on": [(date.fromisoformat(c[0]) + timedelta(days=HORIZON)).isoformat() for c in live_cls],
        },
        "unconditional": {"stats": base},
        "diff_touch_rate": (None if cond["touch_rate"] is None else cond["touch_rate"] - base["touch_rate"]),
        "random_control": {
            "n_draw": n_draw, "n_null": N_NULL, "seed": SEED,
            "null_touch_mean": float(np.mean(null_touch)) if null_touch.size else None,
            "null_touch_p05": float(np.quantile(null_touch, 0.05)) if null_touch.size else None,
            "null_touch_p50": float(np.quantile(null_touch, 0.50)) if null_touch.size else None,
            "null_touch_p95": float(np.quantile(null_touch, 0.95)) if null_touch.size else None,
            "actual_touch_rate": actual,
            "percentile_of_actual": apparatus.percentile_of(actual, null_touch),
            "percentile_of_actual_iid": apparatus.percentile_of(actual, null_touch_iid),
            "null_ret_mean": float(np.mean(null_ret)) if null_ret.size else None,
            "percentile_ret_mean": apparatus.percentile_of(cond["ret_mean"], null_ret),
            "null_mdd_mean": float(np.mean(null_mdd)) if null_mdd.size else None,
            "percentile_mdd_mean": apparatus.percentile_of(cond["mdd_mean"], null_mdd),
        },
        "sub_column_stable_supply": {
            "cond": f"再加 stable_supply_30d < {SUPPLY_MAX}",
            "n_qualifying_days": len(qual_s), "n_clusters": len(cls_s),
            "cluster_firsts": firsts_s, "stats": cond_s,
        },
        "verdict": None,
    }

    # ── 稳健性:信号日挪一天 / 用簇末日 ──
    stats_s1 = per_day_stats(dates, closes, m200, idx, universe, shift=1)
    uni_s1 = [d for d in universe if d in stats_s1]
    cond_s1 = summarize([d for d in cluster_firsts if d in stats_s1], stats_s1)
    base_s1 = summarize(uni_s1, stats_s1)
    lasts = [c[-1] for c in cls]
    cond_last = summarize(lasts, stats)
    res["robustness"] = {
        "shift_plus_1_day": {"condition_C": cond_s1, "unconditional": base_s1,
                             "diff_touch_rate": (None if cond_s1["touch_rate"] is None
                                                 else cond_s1["touch_rate"] - base_s1["touch_rate"])},
        "cluster_last_day": cond_last,
    }

    # ── 稳健性:只看信号日在标记线之上的日子(状态特征与本序列口径一致时) ──
    above = [d for d in universe if stats[d]["dist_t"] > 0]
    cond_above = summarize([d for d in cluster_firsts if d in set(above)], stats)
    base_above = summarize(above, stats)
    res["robustness"]["btc_above_ma200_at_t"] = {
        "condition_C": cond_above, "unconditional": base_above,
        "diff_touch_rate": (None if cond_above["touch_rate"] is None
                            else cond_above["touch_rate"] - base_above["touch_rate"]),
        "n_above": len(above),
    }

    # 可比子集:与 C 同一条带(自算距线 0~10%,在线之上)的全部日子 —— C 的同带对照
    band = [d for d in universe if 0.0 < stats[d]["dist_t"] <= 0.10]
    base_band = summarize(band, stats)
    cond_band = summarize([d for d in cluster_firsts if d in set(band)], stats)
    res["robustness"]["btc_0_10pct_above_ma200_at_t"] = {
        "condition_C": cond_band, "unconditional": base_band,
        "diff_touch_rate": (None if cond_band["touch_rate"] is None
                            else cond_band["touch_rate"] - base_band["touch_rate"]),
        "n_band": len(band),
    }

    # ── 探索性(未预注册,只报):用 binance 自算的线重做 C 的两个变体,样本更大 ──
    def c_like(need_breadth: bool) -> dict:
        days = [d for d in universe
                if 0.0 < stats[d]["dist_t"] <= 0.10
                and st["vol_pct_3y"][d] < C_VOL_MAX
                and (not need_breadth or st["breadth_above_ma50"][d] <= C_BREADTH_MAX)]
        cl = clusters(days)
        firsts = [c[0] for c in cl]
        return {"n_days": len(days), "n_clusters": len(cl),
                "per_day": summarize(days, stats), "cluster_firsts": summarize(firsts, stats)}

    res["exploratory_c_like_binance_band"] = {
        "note": "未预注册的探索性切分:把 dist_200 换成自算的 BTC 距线(0~10%),其余条件照 C;"
                "样本比 C 大,用来给前向预期定概率;不作判定",
        "band_plus_vol": c_like(False),
        "band_plus_vol_plus_breadth": c_like(True),
    }

    # ── 状态延续率(给前向预期用:满足某条件的日子,28 天后该条件还在的概率) ──
    def persistence(feat: str, cond_now, cond_next) -> dict:
        hits = tot = 0
        for d in universe:
            v = st[feat].get(d)
            if v is None or not cond_now(v):
                continue
            d2 = (date.fromisoformat(d) + timedelta(days=HORIZON)).isoformat()
            v2 = st[feat].get(d2)
            if v2 is None:
                continue
            tot += 1
            hits += int(bool(cond_next(v2)))
        return {"n": tot, "keep_rate": (hits / tot) if tot else None}

    res["persistence_28d"] = {
        "dist_200_in_0_10_then_gt_0": persistence("dist_200", lambda v: 0.0 <= v <= 0.10, lambda v: v > 0),
        "breadth_le_010_then_le_010": persistence("breadth_above_ma50", lambda v: v <= 0.10, lambda v: v <= 0.10),
        "vol_lt_010_then_lt_010": persistence("vol_pct_3y", lambda v: v < 0.10, lambda v: v < 0.10),
        "note": "同口径:满足条件的日子中,28 天后条件仍成立的比例(universe 内)",
    }

    # 判定:簇 < 8 只报不判
    if len(cls) < 8:
        res["verdict"] = ("只报不判:独立事件簇 %d 个 < 8,样本不足以做判定" % len(cls))
    elif cond["touch_rate"] is None:
        res["verdict"] = "只报不判:条件 C 无可用样本"
    else:
        res["verdict"] = (f"可判:簇 {len(cls)} 个,碰线率 {cond['touch_rate']:.3f} vs 无条件 {base['touch_rate']:.3f},"
                          f"随机对照第 {res['random_control']['percentile_of_actual']:.3f} 分位")

    with open(os.path.join(ROOT, "docs", "research", "T-232_results.json"), "w") as fh:
        json.dump(res, fh, ensure_ascii=False, indent=1, default=str)

    print(json.dumps({k: v for k, v in res.items() if k not in ("condition_C",)}, ensure_ascii=False, indent=1, default=str))
    print("qual days:", len(qual), "clusters:", len(cls), "firsts:", cluster_firsts)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "fetch":
        fetch()
    elif cmd == "run":
        run()
    else:
        print("usage: fetch|run")
