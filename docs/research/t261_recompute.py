"""T-261 —— S-737 状态 × 动作地图的盲复算 + 稳健性(只报不判)。

Seth/lane-b 的 T-257 已经算过一遍 S-737;这张卡是** blind 复算**:口径只照台账 REFUTATION_LEDGER.md 的
S-737 预注册段(2026-11-06 05:59 UTC)自己写,写完再对照 T-257 的结果,差 > 0.5pp 的逐条找原因。

## 口径(全部照台账 S-737 预注册段,写死不调)

- **数据**:视图 `feature_matrix_daily`(d, f jsonb);价 `perp_bv_daily` 的 BTCUSDT;DVOL `deriv_vol_daily`(currency=BTC)。
- **状态**:台账写 14 个特征,含 `oi_chg_30d` —— 但该键在视图里只有 10/2866 行有值(0.35%),
  拿它做标准化 + k-means 会把样本砍到几乎为零 ⇒ 按卡的口径用 **13 特征(去掉 oi_chg_30d)**,
  这是本卡第一个与台账字面不同的地方,报告里写明。
  13 个:`mom_20 / mom_60 / mom_200 / dist_200 / vol_30 / vratio_30_180 / breadth_above_ma50 /
  funding_7d_ann_binance / taker_buy_share_30d / stable_supply_30d / cycle:deterioration /
  dvol:btc_pct_1y / macro:vix`(macro:vix 缺值的日子不入样本)。
- **标准化 + k-means**:只用训练期 2021-03-01 → 2023-12-31 的均值/标准差标准化;
  KMeans(k=6, random_state=737, n_init=20);留出期 2024-01-01 → 最后一个 30 天结果已到期的日子,
  用训练期的中心分配类别。
- **动作**(入场日 d,d+1 开盘进;结果 = 占入场现货的 %):
  - A1 持有 BTC 30 天(现货,d+1 开盘进 → d+31 收盘出)
  - A2 空仓(0)
  - A3 战术空单(S-736 的出场:止损 1.5 ATR、止盈 2.5 ATR、+1R 后保本、15 根时间止损,1 倍名义)
  - A4 买 30 天 90% 看跌持有到期(Black-Scholes,σ = DVOL/100,r = 0,无偏斜、无买卖价差)
  - A5 30 天 90/80 看跌价差(同上)
  - A6 持有 BTC + A4(保护性多头)
- **判据**:「条件优势」= 训练期均值 > 0 **且** 留出期均值 > 0 **且** 留出期块自助
  (`apparatus.ab_test` 对 A2,块均长 20 天)p 值经 Benjamini–Hochberg(6 × 5 = 30 格,q = 0.10)后仍显著。
  A6 对 A1:留出期 p05 改善 ≥ 均值损失的 2 倍。
- **稳健性(只报)**:k = 5 / 7(同种子);去掉 macro:vix;A4/A6 的看跌按 DVOL + 9 个波动点定价;
  A6 改成 60 天看跌。

零分布 / A/B 只用 `src/data/evaluation/apparatus.py`;多特征检验只用
`src/data/evaluation/joint_model.py`;本卡没有联合模型(只有 k-means 状态分类),故不碰 joint_model 的模型面。

只读库,不写库,不改代码。
"""
from __future__ import annotations

import json
import math
import os
import urllib.request
from typing import Any, Optional

import numpy as np

from src.data.evaluation.apparatus import ab_test

CACHE = os.environ.get("T261_CACHE", "/tmp/t261")
SEED = 737
TRAIN_START, TRAIN_END = "2021-03-01", "2023-12-31"
HOLDOUT_START = "2024-01-01"

FEATURES_13 = [
    "mom_20", "mom_60", "mom_200", "dist_200", "vol_30", "vratio_30_180",
    "breadth_above_ma50", "funding_7d_ann_binance", "taker_buy_share_30d",
    "stable_supply_30d", "cycle:deterioration", "dvol:btc_pct_1y", "macro:vix",
]
FEATURES_NO_VIX = [f for f in FEATURES_13 if f != "macro:vix"]

# ── 读库(只读;分页一律带 order) ────────────────────────────────────────────────

def _headers() -> dict:
    url = os.environ["SUPABASE_URL"].rstrip("/")
    key = os.environ["SUPABASE_KEY"]
    return url, {"apikey": key, "Authorization": "Bearer " + key}


def _fetch(table: str, query: str, order_col: str, extra: str = "", page: int = 1000) -> list[dict]:
    url, h = _headers()
    rows: list[dict] = []
    off = 0
    while True:
        full = f"{url}/rest/v1/{table}?select={query}&order={order_col}&limit={page}&offset={off}"
        if extra:
            full += "&" + extra
        req = urllib.request.Request(full, headers=h)
        chunk = json.load(urllib.request.urlopen(req))
        if not chunk:
            break
        rows.extend(chunk)
        if len(chunk) < page:
            break
        off += page
    return rows


def load_cached(name: str, loader) -> list[dict]:
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, name)
    if os.path.exists(path):
        return json.load(open(path))
    data = loader()
    json.dump(data, open(path, "w"))
    return data


def load_all() -> tuple[list[dict], list[dict], list[dict]]:
    fmd = load_cached("fmd.json", lambda: _fetch("feature_matrix_daily", "*", "d.asc"))
    dvol = load_cached("dvol.json", lambda: _fetch("deriv_vol_daily", "*", "d.asc", "currency=eq.BTC"))
    btc = load_cached("btc.json", lambda: _fetch("perp_bv_daily", "*", "d.asc", "pair=eq.BTCUSDT"))
    return fmd, dvol, btc


# ── 面板 ──────────────────────────────────────────────────────────────────────

def build_panel(fmd: list[dict]) -> dict:
    """d -> {特征: 值}。缺失就是缺失(不当 0)。"""
    panel: dict[str, dict] = {}
    for r in fmd:
        f = r.get("f") or {}
        panel[r["d"]] = {k: f.get(k) for k in set(FEATURES_13)}
    return panel


def build_px(btc: list[dict]) -> dict:
    rows = sorted(btc, key=lambda r: r["d"])
    return {
        "dates": [r["d"] for r in rows],
        "o": np.array([r["o"] for r in rows], float),
        "h": np.array([r["h"] for r in rows], float),
        "l": np.array([r["l"] for r in rows], float),
        "c": np.array([r["c"] for r in rows], float),
    }


def build_dvol(dvol: list[dict]) -> dict:
    rows = sorted(dvol, key=lambda r: r["d"])
    return {r["d"]: r["dvol_close"] for r in rows}


# ── k-means 状态 ──────────────────────────────────────────────────────────────

def fit_states(panel: dict, dates: list[str], features: list[str], k: int) -> dict:
    """训练期标准化 + KMeans;留出期用训练中心分配。返回 labels(索引对齐 dates)、centers、样本掩码。"""
    from sklearn.cluster import KMeans

    def vec(d: str) -> Optional[list]:
        row = panel.get(d)
        if row is None:
            return None
        vals = []
        for f in features:
            v = row.get(f)
            if v is None or (isinstance(v, float) and not math.isfinite(v)):
                return None
            vals.append(float(v))
        return vals

    ok_all = [d for d in dates if vec(d) is not None]
    tr = [d for d in ok_all if TRAIN_START <= d <= TRAIN_END]
    Xtr = np.array([vec(d) for d in tr], float)
    mu = Xtr.mean(axis=0)
    sd = Xtr.std(axis=0)
    sd = np.where(sd <= 0, 1.0, sd)
    Ztr = (Xtr - mu) / sd
    km = KMeans(n_clusters=k, random_state=SEED, n_init=20).fit(Ztr)
    centers = km.cluster_centers_

    labels = np.full(len(dates), -1, int)
    for i, d in enumerate(dates):
        v = vec(d)
        if v is None:
            continue
        z = (np.array(v) - mu) / sd
        labels[i] = int(np.argmin(((centers - z) ** 2).sum(axis=1)))
    return {"labels": labels, "centers": centers, "mu": mu, "sd": sd, "features": features,
            "raw_centers": centers * sd + mu, "n_train": len(tr)}


def match_cluster(base_fit: dict, var_fit: dict) -> int:
    """把基准规格的某个中心投影到变体的特征空间里找最近中心(变体特征 ⊆ 基准特征)。"""
    feats = var_fit["features"]
    idx = [base_fit["features"].index(f) for f in feats]
    raw = base_fit["raw_centers"][idx]
    z = (raw - var_fit["mu"]) / var_fit["sd"]
    return int(np.argmin(((var_fit["centers"] - z) ** 2).sum(axis=1)))


# ── 动作 ─────────────────────────────────────────────────────────────────────

def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def put_price(S: float, K: float, T: float, sigma: float) -> float:
    """Black-Scholes 欧式看跌(无股息,r = 0)。"""
    if T <= 0 or sigma <= 0:
        return max(K - S, 0.0)
    st = sigma * math.sqrt(T)
    d1 = (math.log(S / K) + 0.5 * sigma * sigma * T) / st
    d2 = d1 - st
    return K * norm_cdf(-d2) - S * norm_cdf(-d1)


def atr14(px: dict, i: int) -> Optional[float]:
    """截至 i 的 ATR14 = 近 14 根真实波幅的均值。"""
    if i < 13:
        return None
    trs = []
    for j in range(i - 13, i + 1):
        h, l = px["h"][j], px["l"][j]
        pc = px["c"][j - 1]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return float(np.mean(trs))


def sim_actions(px: dict, dvol: dict, dates: list[str],
                horizon: int = 30, vol_add: float = 0.0, put_tenor: int = 30) -> dict:
    """对每个入场日 d,算出六个动作的收益(占入场现货 %)。A3 是唯一的路径依赖动作。"""
    n = len(dates)
    o, h, l, c = px["o"], px["h"], px["l"], px["c"]
    res = {k: np.full(n, np.nan) for k in ["A1", "A2", "A3", "A4", "A5", "A6"]}
    idx_of = {d: i for i, d in enumerate(dates)}

    for d in dates:
        i = idx_of[d]
        if i + 1 >= n:
            continue
        ei = i + 1
        xi = i + 1 + horizon
        if xi >= n:
            continue
        S = o[ei]
        if not (S > 0):
            continue
        res["A2"][i] = 0.0
        # A1 持有
        a1 = c[xi] / S - 1.0
        res["A1"][i] = a1
        # 看跌定价:σ 取入场前一日(d 日)的 DVOL(入场在 d+1 开盘,当天收盘的 DVOL 那时不可知)
        sig = dvol.get(d)
        if sig is None:
            continue
        sigma = (sig + vol_add) / 100.0
        T = put_tenor / 365.0
        K = 0.9 * S
        p90 = put_price(S, K, T, sigma)
        K80 = 0.8 * S
        p80 = put_price(S, K80, T, sigma)
        Sx = c[xi]
        # A4:买 30 天 90% 看跌,持有到期
        a4 = (max(K - Sx, 0.0) - p90) / S
        res["A4"][i] = a4
        # A5:90/80 看跌价差(买 90 卖 80)
        payoff = max(K - Sx, 0.0) - max(K80 - Sx, 0.0)
        res["A5"][i] = (payoff + (p80 - p90)) / S
        # A6:持有 BTC + A4
        res["A6"][i] = a1 + a4
        # A3:战术空单
        a = atr14(px, i)
        if a is None or a <= 0:
            continue
        sl = S + 1.5 * a
        tp = S - 2.5 * a
        one_r = 1.5 * a
        exit_px = None
        moved = False
        for b in range(ei, min(ei + 15, n)):
            hi, lo = h[b], l[b]
            if hi >= sl and lo <= tp:
                exit_px = sl            # 同一根 bar 既碰止损又碰止盈 ⇒ 按止损(保守)
                break
            if hi >= sl:
                exit_px = sl
                break
            if lo <= tp:
                exit_px = tp
                break
            if not moved and c[b] <= S - one_r:   # 浮盈达 +1R ⇒ 止损移到进场价
                sl = S
                moved = True
        if exit_px is None:
            last = min(ei + 14, n - 1)
            exit_px = c[last]
        res["A3"][i] = 1.0 - exit_px / S
    return res


# ── 判据 ─────────────────────────────────────────────────────────────────────

def bh_reject(pvals: list[float], q: float = 0.10) -> list[bool]:
    m = len(pvals)
    if m == 0:
        return []
    arr = np.asarray(pvals, float)
    order = np.argsort(arr)
    thresh = q * (np.arange(1, m + 1) / m)
    passed = arr[order] <= thresh
    out = np.zeros(m, bool)
    if passed.any():
        kmax = int(np.max(np.where(passed)[0]))
        out[order[: kmax + 1]] = True
    return list(out)


def segments(dates: list[str]) -> int:
    """独立段数:相隔 ≥ 30 天才算新的一段(台账字面)。"""
    if not dates:
        return 0
    ds = [np.datetime64(d) for d in dates]
    segs = 1
    for a, b in zip(ds, ds[1:]):
        if (b - a).astype(int) >= 30:
            segs += 1
    return segs


def eval_spec(panel: dict, panel_dates: list[str], px: dict, dvol: dict, features: list[str], k: int,
              horizon: int = 30, vol_add: float = 0.0, put_tenor: int = 30) -> dict:
    """一个规格 = 一套状态 + 一套动作 ⇒ 30 格的数字 + BH + 今天落哪类。

    状态标签按 **panel 日期轴**(feature_matrix_daily 的全部日子)打 —— 打标不需要未来价格;
    动作按 perp 日期轴算,再对齐到 panel 轴。"""
    fit = fit_states(panel, panel_dates, features, k)
    labels = fit["labels"]
    px_dates = px["dates"]
    act_px = sim_actions(px, dvol, px_dates, horizon=horizon, vol_add=vol_add, put_tenor=put_tenor)
    pidx = {d: i for i, d in enumerate(px_dates)}

    def reindex(arr: np.ndarray) -> np.ndarray:
        out = np.full(len(panel_dates), np.nan)
        for i, d in enumerate(panel_dates):
            j = pidx.get(d)
            if j is not None:
                out[i] = arr[j]
        return out

    act = {k2: reindex(v) for k2, v in act_px.items()}

    train_mask = np.array([TRAIN_START <= d <= TRAIN_END for d in panel_dates])
    hold_mask = np.array([HOLDOUT_START <= d for d in panel_dates])

    cells = []
    for ci in range(k):
        for ak in ["A1", "A3", "A4", "A5", "A6"]:
            r = act[ak]
            tr_v = r[train_mask & (labels == ci)]
            ho_v = r[hold_mask & (labels == ci)]
            tr_v = tr_v[np.isfinite(tr_v)]
            ho_v = ho_v[np.isfinite(ho_v)]
            # ab_test 要同一组日期 ⇒ 用留出期的日期掩码,两侧同长
            m = hold_mask & (labels == ci) & np.isfinite(r) & np.isfinite(act["A2"])
            a = act["A2"][m]
            b = r[m]
            p = None
            verdict = None
            if m.sum() >= 40:
                res = ab_test(a, b, mean_block=20.0, n_boot=2000, seed=SEED)
                p = res["p_b_le_a"]
                verdict = res["verdict"]
            cells.append({
                "cluster": ci, "action": ak,
                "train_mean": round(float(np.mean(tr_v)), 6) if tr_v.size else None,
                "train_n": int(tr_v.size),
                "hold_mean": round(float(np.mean(ho_v)), 6) if ho_v.size else None,
                "hold_p05": round(float(np.percentile(ho_v, 5)), 6) if ho_v.size else None,
                "hold_n": int(ho_v.size),
                "p_b_le_a": p, "verdict": verdict,
            })
    pv = [c["p_b_le_a"] for c in cells]
    pv_masked = [x if x is not None else 1.0 for x in pv]
    rej = bh_reject(pv_masked, q=0.10)
    for c, rj in zip(cells, rej):
        c["bh_reject"] = bool(rj)
        c["conditional_edge"] = bool(
            c["train_mean"] is not None and c["hold_mean"] is not None
            and c["train_mean"] > 0 and c["hold_mean"] > 0 and rj
        )

    # A6 对 A1 的保护代价判据
    a6_vs_a1 = []
    for ci in range(k):
        row = {}
        for ak in ["A1", "A6"]:
            rr = act[ak]
            ho = rr[hold_mask & (labels == ci)]
            ho = ho[np.isfinite(ho)]
            row[ak] = {"hold_mean": float(np.mean(ho)) if ho.size else None,
                       "hold_p05": float(np.percentile(ho, 5)) if ho.size else None,
                       "n": int(ho.size)}
        if row["A1"]["hold_mean"] is not None and row["A6"]["hold_mean"] is not None:
            d_p05 = row["A6"]["hold_p05"] - row["A1"]["hold_p05"]
            mean_loss = row["A1"]["hold_mean"] - row["A6"]["hold_mean"]
            row["p05_improve"] = d_p05
            row["mean_loss"] = mean_loss
            row["protect_pays"] = bool(d_p05 >= 2.0 * mean_loss)
        a6_vs_a1.append(row)

    # 「今天落在哪一类」= 最后一个特征齐全的日子(打标不需要未来价格)
    valid = [i for i in range(len(panel_dates)) if labels[i] >= 0]
    anchor_i = valid[-1] if valid else None
    anchor = {"date": panel_dates[anchor_i], "cluster": int(labels[anchor_i])} if anchor_i is not None else None
    # 最后一个 30 天结果已到期的日子(留出期的实际边界)
    matured = [i for i in range(len(panel_dates)) if labels[i] >= 0 and np.isfinite(act["A1"][i])]
    last_matured = panel_dates[matured[-1]] if matured else None

    # 每类样本日数与独立段数
    per_cluster = []
    for ci in range(k):
        for tag, mask in [("train", train_mask), ("hold", hold_mask)]:
            ds = [panel_dates[i] for i in range(len(panel_dates)) if mask[i] and labels[i] == ci]
            per_cluster.append({"cluster": ci, "period": tag, "n_days": len(ds),
                                "n_segments": segments(ds)})

    return {"fit": fit, "act": act, "cells": cells, "a6_vs_a1": a6_vs_a1,
            "anchor": anchor, "last_matured": last_matured, "per_cluster": per_cluster,
            "labels": labels, "dates": panel_dates,
            "hold_feature_days": int(((hold_mask) & (labels >= 0)).sum()),
            "hold_action_days": int(((hold_mask) & (labels >= 0) & np.isfinite(act["A1"])).sum()),
            "train_feature_days": int(((train_mask) & (labels >= 0)).sum()),
            "train_action_days": int(((train_mask) & (labels >= 0) & np.isfinite(act["A1"])).sum()),
            }


def today_put_quote(px: dict, dvol: dict, d: str) -> dict:
    """最新一个特征齐全日 d 的 30 天 90% 看跌报价(占现货 %):DVOL 平值 vs +9 波动点。

    入场在 d+1 开盘;若 d+1 没有 perp 行(最新一天),用 d 的收盘价当现货代理,并注明。"""
    dates = px["dates"]
    if d not in dates:
        return {}
    i = dates.index(d)
    sig = dvol.get(d)
    if sig is None:
        return {}
    if i + 1 < len(dates):
        S = float(px["o"][i + 1])
        basis = "entry_open(d+1)"
        entry_date = dates[i + 1]
    else:
        S = float(px["c"][i])
        basis = "close_proxy(d)"
        entry_date = None
    if not (S > 0):
        return {}
    out_q = {"asof": d, "entry_date": entry_date, "basis": basis, "spot": S, "dvol": sig}
    for tag, add in [("dvol_flat", 0.0), ("dvol_plus_9", 9.0)]:
        sigma = (sig + add) / 100.0
        p90 = put_price(S, 0.9 * S, 30 / 365.0, sigma)
        p80 = put_price(S, 0.8 * S, 30 / 365.0, sigma)
        out_q[tag] = {"put90_pct_spot": round(p90 / S * 100, 4),
                      "put80_pct_spot": round(p80 / S * 100, 4),
                      "spread_net_credit_pct_spot": round((p90 - p80) / S * 100, 4)}
    return out_q


def main() -> None:
    fmd, dvol_rows, btc_rows = load_all()
    fmd = sorted(fmd, key=lambda r: r["d"])
    panel = build_panel(fmd)
    panel_dates = [r["d"] for r in fmd]
    px = build_px(btc_rows)
    dvol = build_dvol(dvol_rows)

    out: dict[str, Any] = {
        "meta": {
            "card": "T-261", "seed": SEED,
            "features_base": FEATURES_13, "features_no_vix": FEATURES_NO_VIX,
            "train": [TRAIN_START, TRAIN_END], "holdout_start": HOLDOUT_START,
            "panel_rows": len(fmd), "panel_first": fmd[0]["d"], "panel_last": fmd[-1]["d"],
            "dvol_rows": len(dvol_rows), "perp_btc_rows": len(btc_rows),
            "perp_first": px["dates"][0], "perp_last": px["dates"][-1],
            "feature_coverage": {f: sum(1 for r in fmd if (r.get("f") or {}).get(f) is not None)
                                 for f in FEATURES_13 + ["oi_chg_30d"]},
        },
    }

    # ── 基准规格:13 特征、k=6、σ=DVOL、30 天看跌 ──
    base = eval_spec(panel, panel_dates, px, dvol, FEATURES_13, 6)
    anchor_ci = base["anchor"]["cluster"] if base["anchor"] else None
    out["base"] = {
        "anchor": base["anchor"], "anchor_cluster": anchor_ci,
        "last_matured": base["last_matured"],
        "days": {"train_feature": base["train_feature_days"], "train_action": base["train_action_days"],
                 "hold_feature": base["hold_feature_days"], "hold_action": base["hold_action_days"]},
        "cells": base["cells"], "a6_vs_a1": base["a6_vs_a1"],
        "per_cluster": base["per_cluster"],
        "centers": base["fit"]["centers"].tolist(),
        "raw_centers": {str(i): dict(zip(base["fit"]["features"], base["fit"]["raw_centers"][i].tolist()))
                        for i in range(len(base["fit"]["raw_centers"]))},
        "features": base["fit"]["features"], "n_train": base["fit"]["n_train"],
        "passed_bh": [c for c in base["cells"] if c["bh_reject"]],
        "today_put_quote": today_put_quote(px, dvol, base["anchor"]["date"]) if base["anchor"] else {},
    }

    # ── 稳健性变体 ──
    variants = [
        {"name": "k5", "features": FEATURES_13, "k": 5, "horizon": 30, "vol_add": 0.0, "put_tenor": 30},
        {"name": "k7", "features": FEATURES_13, "k": 7, "horizon": 30, "vol_add": 0.0, "put_tenor": 30},
        {"name": "no_vix", "features": FEATURES_NO_VIX, "k": 6, "horizon": 30, "vol_add": 0.0, "put_tenor": 30},
        {"name": "vol_plus_9", "features": FEATURES_13, "k": 6, "horizon": 30, "vol_add": 9.0, "put_tenor": 30},
        {"name": "put_60d", "features": FEATURES_13, "k": 6, "horizon": 60, "vol_add": 0.0, "put_tenor": 60},
    ]
    out["variants"] = {}
    for v in variants:
        spec = eval_spec(panel, panel_dates, px, dvol, v["features"], v["k"],
                         horizon=v["horizon"], vol_add=v["vol_add"], put_tenor=v["put_tenor"])
        centers = spec["fit"]["centers"]
        # 与基准的 anchor 类别(按中心最近)匹配
        match = None
        if anchor_ci is not None:
            bc = base["fit"]["raw_centers"][anchor_ci]
            idx = [base["fit"]["features"].index(f) for f in spec["fit"]["features"]]
            z = (bc[idx] - spec["fit"]["mu"]) / spec["fit"]["sd"]
            match = int(np.argmin(((centers - z) ** 2).sum(axis=1)))
        row_a6 = None
        if match is not None:
            c = [x for x in spec["cells"] if x["cluster"] == match and x["action"] == "A6"]
            row_a6 = c[0] if c else None
        out["variants"][v["name"]] = {
            "spec": v, "match_cluster": match, "anchor": spec["anchor"],
            "anchor_cluster": spec["anchor"]["cluster"] if spec["anchor"] else None,
            "a6_at_match": row_a6,
            "passed_bh": [c for c in spec["cells"] if c["bh_reject"]],
            "passed_conditional_edge": [c for c in spec["cells"] if c["conditional_edge"]],
            "a6_vs_a1_at_match": spec["a6_vs_a1"][match] if match is not None else None,
            "per_cluster": spec["per_cluster"],
            "days": {"train_feature": spec["train_feature_days"], "hold_feature": spec["hold_feature_days"]},
            "n_cells": len(spec["cells"]),
        }

    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "t261_results.json"), "w") as fh:
        json.dump(out, fh, indent=2, ensure_ascii=False, default=str)
    print(json.dumps({
        "anchor": out["base"]["anchor"], "days": out["base"]["days"],
        "last_matured": out["base"]["last_matured"],
        "today_put_quote": out["base"]["today_put_quote"],
        "passed_bh": [(c["cluster"], c["action"], c["hold_mean"], c["p_b_le_a"]) for c in out["base"]["passed_bh"]],
        "variants": {k: {"match": v["match_cluster"], "anchor": v["anchor"],
                         "a6": (v["a6_at_match"] or {}).get("hold_mean"),
                         "p": (v["a6_at_match"] or {}).get("p_b_le_a"),
                         "bh": (v["a6_at_match"] or {}).get("bh_reject")}
                     for k, v in out["variants"].items()},
    }, ensure_ascii=False, indent=1, default=str))


if __name__ == "__main__":
    main()
