"""T-444 / S-924(盲复算):S-920 / S-923 的**做空一侧** —— 照书面口径自己写特征拼装、走步、模型、七条判据。

本脚本是**独立复算**:不读 lane-a 的 s920_meta_label.py / s923_cluster_null.py 及其产物,只照卡面文字实现。
第一层(4 小时线、指标、进出场票)直接 import `docs/research/s916_jazz_4h_rules.py`:
    sys.argv 先设成 [x, "--mgmt", "atr3", "--dmin", "0.01", "--cap", "20"] 再 import(卡面指定)。
s916 的 `load_live()` 里除了 4h 线还会去装状态四格(本卡用不到),故只复制它装载 4h 线的那 4 行(query 参数、
过滤、to_4h 聚合完全一致),打印同样的 `loaded` 行。

口径(全部照卡面):
  ① 每张票:决定根 k = 进场那根的下标 − 1;平仓时间 = 进场时间 + 4 小时 × 持有根数;标签 = R > 0。
  ② 16 个特征(k 那根收盘为止):
     币内 8 个:dist_e50 / e20_e50 / atr_pct / bbw / ret_6 / ret_42 / dist200_coin / ret_30d
     日线 8 个:fund7(funding_daily 按币 7 日滚动均值 × 3 × 365)+ 市场 6 个(feature_matrix_daily.f)
                + joint_z(joint_forecast_daily.z)
     日线类一律取 D − 1 及以前最近的一天、且距 D − 1 不超过 3 天(D = 进场时间的 UTC 日期),否则缺。
  ③ 走步:测试年 2022 / 2023 / 2024 / 2025(2025 含 2026 至今);训练 = 平仓时间早于(测试年 1 月 1 日 − 30 天)的票,
     少于 150 张跳过;评估 = 2023 / 2024 / 2025 三折合并。
  ④ 模型写死:logit = 训练段中位数填缺(整列缺填 0)→ 训练段均值/标准差标准化(标准差 0 当 1)
     → LogisticRegression(C=0.1, max_iter=2000);hgb = HistGradientBoostingClassifier(max_depth=3,
     learning_rate=0.05, max_iter=200, min_samples_leaf=50, l2_regularization=1.0, random_state=920),
     缺失原样喂,训练段整列缺失的列在训练与测试里都置 0。
  ⑤ 折内三档:按预测概率**升序**稳定排序(第 0 名 = 概率最低),第 rank 名归档 min(2, rank × 3 // n);
     档 2 = 上一档(概率最高的三分之一)。
  ⑥ 七条判据:
     [S-920] c1 合并增量(上一档均值 − 全部均值)≥ 0.15
             c2 折内逐张打乱预测 1,000 次(种子 920)的分位 ≥ 0.95
             c3 三个评估年里上一档 > 全部的年数 ≥ 2
             c4 合并 AUC(标签 R > 0)≥ 0.55
     [S-923] c5 每折按进场时间排好、预测整体循环平移 o 张(o ∈ [n//10, 9n//10) 均匀取,1,000 次,种子 923)的分位 ≥ 0.95
             c6 按天等权(同一天的票先天内平均再对天平均)上一档 − 全部 ≥ 0.15
             c7 11 个币逐个从评估里拿掉(不重训)的最小增量 > 0
  分位定义:观测统计量在零分布里的经验百分位(= #{null < obs}/N,相等计半),故 ≥ 0.95 = 观测压过 95% 的零假设样本。

用法(仓库根目录;环境里有只读的 SUPABASE_URL / SUPABASE_KEY):
    python3 docs/research/s924_blind_short.py --selftest
    nohup python3 docs/research/s924_blind_short.py > docs/research/s924_run.txt 2>&1 &
"""
from __future__ import annotations

import bisect
import datetime as dt
import importlib.util
import json
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
UTC = dt.timezone.utc

COINS = ("BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "AVAX", "DOGE", "LINK", "NEAR", "SUI")
RULE = "BR_S"                       # 破位回抽确认单(空)—— 本卡是「做空一侧」
FEATS = ("dist_e50", "e20_e50", "atr_pct", "bbw", "ret_6", "ret_42", "dist200_coin", "ret_30d",
         "fund7", "dist_200", "style_rel_majors_30d", "stable_supply_30d", "funding_7d_ann_binance",
         "pos:btc_crowd_ln", "taker_buy_share_30d", "joint_z")
MKT_KEYS = ("dist_200", "style_rel_majors_30d", "stable_supply_30d", "funding_7d_ann_binance",
            "pos:btc_crowd_ln", "taker_buy_share_30d")
TEST_YEARS = (2022, 2023, 2024, 2025)
EVAL_YEARS = (2023, 2024, 2025)     # 合并评估 = 这三折
EMBARGO_DAYS = 30
MIN_TRAIN = 150
N_PERM = 1000
SEED_PERM, SEED_SHIFT = 920, 923
OUT_JSON = "docs/research/s924_results.json"
NAN = float("nan")


# ── 第一层(s916):4h 线 + 指标 + 票 ──────────────────────────────────────────────
def load_first_layer():
    argv = sys.argv
    sys.argv = [argv[0], "--mgmt", "atr3", "--dmin", "0.01", "--cap", "20"]
    try:
        sp = importlib.util.spec_from_file_location("s916_jazz", os.path.join(HERE, "s916_jazz_4h_rules.py"))
        m = importlib.util.module_from_spec(sp)
        sp.loader.exec_module(m)
    finally:
        sys.argv = argv
    assert m.MGMT == "atr3" and abs(m.DMIN - 0.01) < 1e-12 and m.CAP == 20, (m.MGMT, m.DMIN, m.CAP)
    return m


def load_bars(S916, cache=None):
    """照 s916.load_live() 里装载 4h 线的那几行(query 参数与过滤完全一致)。"""
    meta_path = (cache + ".meta.json") if cache else None
    if cache and os.path.exists(cache):
        obj = pickle_load(cache)
        bars, rows = (obj["bars"], obj.get("rows", {})) if isinstance(obj, dict) and "bars" in obj else (obj, {})
        if meta_path and os.path.exists(meta_path):
            try:
                rows = {**json.load(open(meta_path)), **rows}
            except Exception:  # noqa: BLE001
                pass
        for coin in COINS:
            n = rows.get(coin)
            if n is None:
                print("loaded", coin, "cached →", len(bars[coin]["c"]), "4h", flush=True)
            else:
                print("loaded", coin, n, "hourly →", len(bars[coin]["c"]), "4h", flush=True)
        return bars
    bars, counts = {}, {}
    for coin in COINS:
        rows = S916.S.get("ohlcv_hourly", {"select": "ts,open,high,low,close", "symbol": f"eq.{coin}",
                                           "source": "eq.binance_hist", "order": "ts.asc"})
        rows = [r for r in rows if all(r.get(k) is not None for k in ("open", "high", "low", "close"))]
        bars[coin] = S916.to_4h(rows)
        if bars[coin]["t"] and bars[coin]["t"][0].tzinfo is None:
            bars[coin]["t"] = [x.replace(tzinfo=UTC) for x in bars[coin]["t"]]
        counts[coin] = len(rows)
        print("loaded", coin, len(rows), "hourly →", len(bars[coin]["c"]), "4h", flush=True)
    if cache:
        try:
            pickle_dump(cache, {"bars": bars, "rows": counts})
            json.dump(counts, open(cache + ".meta.json", "w"))
        except Exception as e:  # noqa: BLE001
            print("cache write failed", type(e).__name__, str(e)[:120], flush=True)
    return bars


def pickle_load(path):
    import pickle
    with open(path, "rb") as fh:
        return pickle.load(fh)


def pickle_dump(path, obj):
    import pickle
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "wb") as fh:
        pickle.dump(obj, fh, protocol=4)
    os.replace(tmp, path)


# ── 日线表 ──────────────────────────────────────────────────────────────────────
class Daily:
    """三张日线表 + as-of 规则:取 D − 1 及以前最近的一天,且距 D − 1 不超过 3 天,否则缺。"""

    def __init__(self, fund, fm, jz):
        self.fund = fund          # {sym: (dates[list[date]], vals[list[float]])}
        self.fm = fm              # {date: f dict}
        self.jz = jz              # {date: z}

    @staticmethod
    def asof_idx(dates, D):
        """D = 进场时间的 UTC 日期;返回 (下标, 该天) 或 (None, None)。"""
        target = D - dt.timedelta(days=1)
        i = bisect.bisect_right(dates, target) - 1
        if i < 0:
            return None, None
        d0 = dates[i]
        if (target - d0).days > 3:
            return None, None
        return i, d0

    def fund7(self, sym, D):
        if sym not in self.fund:
            return NAN
        dates, vals = self.fund[sym]
        i, d0 = self.asof_idx(dates, D)
        if i is None:
            return NAN
        lo = d0 - dt.timedelta(days=6)
        w = [v for d, v in zip(dates, vals) if lo <= d <= d0 and v is not None and not math.isnan(v)]
        if not w:
            return NAN
        return float(np.mean(w)) * 3.0 * 365.0

    def mkt(self, key, D):
        dates = self._fm_dates
        i, d0 = self.asof_idx(dates, D)
        if i is None:
            return NAN
        f = self.fm.get(d0) or {}
        v = f.get(key)
        return NAN if v is None else float(v)

    def joint_z(self, D):
        dates = self._jz_dates
        i, d0 = self.asof_idx(dates, D)
        if i is None:
            return NAN
        v = self.jz.get(d0)
        return NAN if v is None else float(v)

    def finalize(self):
        self._fm_dates = sorted(self.fm.keys())
        self._jz_dates = sorted(self.jz.keys())


def load_daily(S916):
    S = S916.S
    fund = {}
    rows = S.get("funding_daily", {"select": "symbol,d,funding_rate", "symbol": "in.(" + ",".join(COINS) + ")",
                                  "order": "symbol.asc,d.asc"})
    per = {}
    for r in rows:
        per.setdefault(r["symbol"], []).append((dt.date.fromisoformat(str(r["d"])[:10]), r["funding_rate"]))
    for sym, lst in per.items():
        lst.sort()
        fund[sym] = ([d for d, _ in lst], [float(v) if v is not None else NAN for _, v in lst])
    print("funding_daily rows", len(rows), "symbols", len(fund), flush=True)

    fm = {}
    rows = S.get("feature_matrix_daily", {"select": "d,f", "d": "gte.2019-01-01", "order": "d.asc"})
    for r in rows:
        fm[dt.date.fromisoformat(str(r["d"])[:10])] = (r.get("f") or {})
    print("feature_matrix_daily rows", len(rows), flush=True)

    jz = {}
    rows = S.get("joint_forecast_daily", {"select": "d,z,computed_at", "d": "gte.2019-01-01", "order": "d.asc"})
    for r in rows:
        d = dt.date.fromisoformat(str(r["d"])[:10])
        v = r.get("z")
        if v is None:
            continue
        if d not in jz or str(r.get("computed_at") or "") > jz[d][1]:
            jz[d] = (float(v), str(r.get("computed_at") or ""))
    jz = {d: v for d, (v, _) in jz.items()}
    print("joint_forecast_daily rows", len(rows), "with z", len(jz), flush=True)

    d = Daily(fund, fm, jz)
    d.finalize()
    return d


# ── 票与特征 ───────────────────────────────────────────────────────────────────
def build_tickets(S916, bars):
    """每个币的 BR_S 票;返回 (票列表, 每币 4h 指标)。"""
    tix, inds = [], {}
    for coin in COINS:
        b = bars.get(coin)
        if not b or len(b["c"]) < 1300:
            print("skip", coin, "bars", 0 if not b else len(b["c"]), flush=True)
            continue
        ind = S916.indicators(b)
        inds[coin] = ind
        idx = {t: i for i, t in enumerate(b["t"])}
        for (t0, side, R, hold) in S916.tickets(b, ind, RULE):
            j0 = idx.get(t0)
            if j0 is None:
                continue
            tix.append({"coin": coin, "t": t0, "exit": t0 + dt.timedelta(hours=4 * int(hold)),
                        "r": float(R), "k": j0 - 1, "j0": j0, "side": int(side)})
    print("tickets", RULE, len(tix), flush=True)
    return tix, inds


def coin_feats(b, ind, k):
    """币内 8 个特征(k 那根收盘为止)。缺 = NaN。"""
    c = b["c"]
    out = {}
    e50 = ind["e50"][k]
    out["dist_e50"] = (c[k] / e50 - 1.0) if (k >= 0 and e50 == e50 and e50 != 0) else NAN
    e20 = ind["e20"][k]
    out["e20_e50"] = (e20 / e50 - 1.0) if (e20 == e20 and e50 == e50 and e50 != 0) else NAN
    atr = ind["atr"][k]
    out["atr_pct"] = (atr / c[k]) if (atr == atr and c[k]) else NAN
    bu, bl = ind["bu"][k], ind["bl"][k]
    out["bbw"] = ((bu - bl) / c[k]) if (bu == bu and bl == bl and c[k]) else NAN
    out["ret_6"] = (c[k] / c[k - 6] - 1.0) if (k >= 6 and c[k - 6]) else NAN
    out["ret_42"] = (c[k] / c[k - 42] - 1.0) if (k >= 42 and c[k - 42]) else NAN
    out["dist200_coin"] = (c[k] / float(np.mean(c[k - 1199:k + 1])) - 1.0) if (k >= 1199 and np.mean(c[k - 1199:k + 1])) else NAN
    out["ret_30d"] = (c[k] / c[k - 180] - 1.0) if (k >= 180 and c[k - 180]) else NAN
    return out


def all_feats(t, b, ind, daily):
    D = t["t"].date()
    f = coin_feats(b, ind, t["k"])
    f["fund7"] = daily.fund7(t["coin"], D)
    for key in MKT_KEYS:
        f[key] = daily.mkt(key, D)
    f["joint_z"] = daily.joint_z(D)
    return f


def feature_matrix(tix, bars, inds, daily):
    for t in tix:
        t["f"] = all_feats(t, bars[t["coin"]], inds[t["coin"]], daily)
    X = np.array([[t["f"][k] for k in FEATS] for t in tix], dtype=float) if tix else np.zeros((0, len(FEATS)))
    return X


# ── 模型 ───────────────────────────────────────────────────────────────────────
def fit_logit(Xtr, ytr, Xte):
    med = np.zeros(Xtr.shape[1])
    for j in range(Xtr.shape[1]):
        col = Xtr[:, j][~np.isnan(Xtr[:, j])]
        med[j] = float(np.median(col)) if len(col) else 0.0        # 整列缺 → 0
    A = np.where(np.isnan(Xtr), med, Xtr)
    B = np.where(np.isnan(Xte), med, Xte)
    mu = A.mean(axis=0)
    sd = A.std(axis=0)
    sd = np.where(sd == 0, 1.0, sd)
    A = (A - mu) / sd
    B = (B - mu) / sd
    if len(set(ytr.tolist())) < 2:
        return np.full(len(B), float(np.mean(ytr)) if len(ytr) else 0.5)
    from sklearn.linear_model import LogisticRegression
    m = LogisticRegression(C=0.1, max_iter=2000)
    m.fit(A, ytr)
    return m.predict_proba(B)[:, 1]


def fit_hgb(Xtr, ytr, Xte):
    A, B = Xtr.copy(), Xte.copy()
    for j in range(A.shape[1]):
        if np.all(np.isnan(A[:, j])):
            A[:, j] = 0.0
            B[:, j] = 0.0
    if len(set(ytr.tolist())) < 2:
        return np.full(len(B), float(np.mean(ytr)) if len(ytr) else 0.5)
    from sklearn.ensemble import HistGradientBoostingClassifier
    m = HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05, max_iter=200, min_samples_leaf=50,
                                       l2_regularization=1.0, random_state=920)
    m.fit(A, ytr)
    return m.predict_proba(B)[:, 1]


# ── 统计 ───────────────────────────────────────────────────────────────────────
def tier_of(pred):
    """按预测概率**升序**稳定排序(第 0 名 = 概率最低),档 = min(2, rank × 3 // n);档 2 = 上一档。"""
    n = len(pred)
    order = np.argsort(np.asarray(pred), kind="stable")
    ranks = np.empty(n, dtype=int)
    ranks[order] = np.arange(n)
    return np.minimum(2, ranks * 3 // n)


def combined_lift(folds, preds):
    """folds: [{r: np.array}];preds: [np.array];返回 (lift, top_mean, all_mean, tiers)。"""
    allr = np.concatenate([f["r"] for f in folds]) if folds else np.zeros(0)
    top = []
    for f, p in zip(folds, preds):
        t = tier_of(p)
        top.append(f["r"][t == 2])
    top = np.concatenate(top) if top else np.zeros(0)
    if not len(top) or not len(allr):
        return NAN, NAN, (float(allr.mean()) if len(allr) else NAN), []
    return float(top.mean() - allr.mean()), float(top.mean()), float(allr.mean()), top


def pct(nulls, obs):
    a = np.asarray(nulls, dtype=float)
    if not len(a) or not np.isfinite(obs):
        return NAN
    return float((np.sum(a < obs) + 0.5 * np.sum(a == obs)) / len(a))


def day_lift(folds, preds, days):
    """按天等权:同一天的票先天内平均再对天平均;上一档 − 全部。"""
    per_day_top, per_day_all = {}, {}
    for f, p, d in zip(folds, preds, days):
        t = tier_of(p)
        for rr, tt, dd in zip(f["r"], t, d):
            per_day_all.setdefault(dd, []).append(rr)
            if tt == 2:
                per_day_top.setdefault(dd, []).append(rr)
    ks = [d for d in per_day_top if d in per_day_all]
    if not ks:
        return NAN
    return float(np.mean([np.mean(per_day_top[d]) for d in ks]) - np.mean([np.mean(per_day_all[d]) for d in ks]))


def day_diag(folds, preds):
    """日维度诊断(为什么按天等权会与逐票口径分歧):票集中在几天?最好的那一天贡献多少?"""
    pt, pa, pn, pc = {}, {}, {}, {}
    for f, p in zip(folds, preds):
        t = tier_of(p)
        for rr, tt, m in zip(f["r"], t, f["meta"]):
            d = m["t"].date()
            pa.setdefault(d, []).append(rr)
            pn[d] = pn.get(d, 0) + 1
            pc[d] = pc.get(d, 0) + 1
            if tt == 2:
                pt.setdefault(d, []).append(rr)
    ks = sorted(pt)
    dl = {str(d): float(np.mean(pt[d]) - np.mean(pa[d])) for d in ks}
    tot = float(np.sum([np.sum(pt[d]) for d in ks]))
    best = max(ks, key=lambda d: float(np.sum(pt[d]))) if ks else None
    n_all_days = len(pa)
    out = {"n_days_all": n_all_days, "n_days_with_top": len(ks),
           "tickets_per_day_max": max(pn.values()) if pn else 0,
           "tickets_per_day_median": float(np.median(list(pn.values()))) if pn else 0,
           "days_with_ge2_tickets": sum(1 for v in pn.values() if v >= 2),
           "top_R_total": tot,
           "best_day": str(best) if best else None,
           "best_day_top_R": float(np.sum(pt[best])) if best else 0.0,
           "best_day_share_of_top_R": (float(np.sum(pt[best])) / tot) if (best and tot) else None,
           "best_day_n_tickets": pn.get(best, 0) if best else 0,
           "day_lift_sorted_desc": sorted(dl.values(), reverse=True)[:5],
           "day_lift_sorted_asc": sorted(dl.values())[:5],
           "n_days_day_lift_negative": sum(1 for v in dl.values() if v < 0),
           "day_lift_all_days": dl}
    return out


def loco_min(folds, preds, coins):
    """11 个币逐个从评估里拿掉(不重训),重算合并增量,取最小。"""
    out = {}
    for c in coins:
        masks = [np.array([t["coin"] != c for t in f["meta"]]) for f in folds]
        if not masks or any(m.sum() == 0 for m in masks):
            continue
        keep = [{"r": f["r"][m], "meta": [t for t, k in zip(f["meta"], m) if k]} for f, m in zip(folds, masks)]
        pp = [p[m] for p, m in zip(preds, masks)]
        l, _, _, _ = combined_lift(keep, pp)
        out[c] = l
    return (min(out.values()) if out else NAN), out


def run_cell(model, folds, n_perm=N_PERM):
    """folds: [{year, meta, r, Xtr, ytr}] —— 评估折(按进场时间排好),训练段已按走步给定。"""
    if not folds:
        empty = {"model": model, "n_eval": 0, "all_r": NAN, "top_r": NAN, "lift": NAN, "perm_pct": NAN,
                 "years_top_beats_all": 0, "auc": NAN, "shift_pct": NAN, "day_lift": NAN, "loco_min": NAN,
                 "loco": {}, "per_year": {}, "pred_head": [],
                 "criteria": {k: False for k in ("c1_lift_ge_0.15", "c2_perm_pct_ge_0.95", "c3_years_ge_2",
                                               "c4_auc_ge_0.55", "c5_shift_pct_ge_0.95", "c6_day_lift_ge_0.15",
                                               "c7_loco_min_gt_0")}}
        return empty
    preds = []
    for f in folds:
        Xte = np.array([[t["f"][k] for k in FEATS] for t in f["meta"]], dtype=float)
        preds.append(fit_logit(f["Xtr"], f["ytr"], Xte) if model == "logit" else fit_hgb(f["Xtr"], f["ytr"], Xte))
    lift, top_mean, all_mean, _ = combined_lift(folds, preds)
    n_eval = sum(len(f["meta"]) for f in folds)
    # AUC
    ys = [np.array([1 if t["r"] > 0 else 0 for t in f["meta"]], dtype=int) for f in folds]
    y_all = np.concatenate(ys) if ys else np.zeros(0)
    p_all = np.concatenate(preds) if preds else np.zeros(0)
    try:
        from sklearn.metrics import roc_auc_score
        auc = float(roc_auc_score(y_all, p_all)) if len(set(y_all.tolist())) > 1 else NAN
    except Exception:  # noqa: BLE001
        auc = NAN
    # 逐年:上一档 > 全部
    years_beats = 0
    per_year = {}
    for f, p in zip(folds, preds):
        yr = f["year"]
        t = tier_of(p)
        tm = float(f["r"][t == 2].mean()) if (t == 2).any() else NAN
        am = float(f["r"].mean())
        per_year[yr] = {"top_r": tm, "all_r": am, "n": len(f["r"])}
        if np.isfinite(tm) and tm > am:
            years_beats += 1
    per_year_day = {}
    try:
        for f, p in zip(folds, preds):
            per_year_day[f["year"]] = day_lift([f], [p], [[m["t"].date() for m in f["meta"]]])
    except Exception:  # noqa: BLE001
        per_year_day = {}
    # 零分布 1:折内逐张打乱预测(种子 920)
    rng = np.random.default_rng(SEED_PERM)
    null_perm = []
    for _ in range(n_perm):
        pp = []
        for p in preds:
            q = p.copy()
            rng.shuffle(q)
            pp.append(q)
        null_perm.append(combined_lift(folds, pp)[0])
    perm_pct = pct(null_perm, lift)
    # 零分布 2:每折按进场时间排好、预测整体循环平移(种子 923)
    rng2 = np.random.default_rng(SEED_SHIFT)
    null_shift = []
    for _ in range(n_perm):
        pp = []
        for f, p in zip(folds, preds):
            n = len(p)
            lo, hi = n // 10, (9 * n) // 10
            if hi <= lo:
                pp.append(p)
                continue
            o = int(rng2.integers(lo, hi))
            pp.append(np.roll(p, o))
        null_shift.append(combined_lift(folds, pp)[0])
    shift_pct = pct(null_shift, lift)
    # 按天等权
    days = [[t["t"].date() for t in f["meta"]] for f in folds]
    dl = day_lift(folds, preds, days)
    # 留一币
    lm, lo_map = loco_min(folds, preds, COINS)
    try:
        dd = day_diag(folds, preds)
    except Exception:  # noqa: BLE001
        dd = {}
    crit = {
        "c1_lift_ge_0.15": bool(np.isfinite(lift) and lift >= 0.15),
        "c2_perm_pct_ge_0.95": bool(np.isfinite(perm_pct) and perm_pct >= 0.95),
        "c3_years_ge_2": bool(years_beats >= 2),
        "c4_auc_ge_0.55": bool(np.isfinite(auc) and auc >= 0.55),
        "c5_shift_pct_ge_0.95": bool(np.isfinite(shift_pct) and shift_pct >= 0.95),
        "c6_day_lift_ge_0.15": bool(np.isfinite(dl) and dl >= 0.15),
        "c7_loco_min_gt_0": bool(np.isfinite(lm) and lm > 0),
    }
    return {"model": model, "n_eval": n_eval, "all_r": all_mean, "top_r": top_mean, "lift": lift,
            "perm_pct": perm_pct, "years_top_beats_all": years_beats, "auc": auc, "shift_pct": shift_pct,
            "day_lift": dl, "loco_min": lm, "loco": lo_map, "per_year": per_year, "per_year_day_lift": per_year_day,
            "day_diag": dd, "criteria": crit, "pred_head": [float(x) for x in p_all[:5]]}


def fmt(x):
    if x is None:
        return "nan"
    if isinstance(x, float) and not math.isfinite(x):
        return "nan"
    if isinstance(x, float):
        return f"{x:.4f}"
    return str(x)


def cell_line(tag, c, n_cand):
    parts = [f"CELL {tag}", f"n_candidates={n_cand}", f"n_eval={c['n_eval']}", f"all_r={fmt(c['all_r'])}",
             f"top_r={fmt(c['top_r'])}", f"lift={fmt(c['lift'])}", f"perm_pct={fmt(c['perm_pct'])}",
             f"years_top_beats_all={c['years_top_beats_all']}", f"auc={fmt(c['auc'])}",
             f"shift_pct={fmt(c['shift_pct'])}", f"day_lift={fmt(c['day_lift'])}", f"loco_min={fmt(c['loco_min'])}"]
    for k, v in c["criteria"].items():
        parts.append(f"{k}={int(v)}")
    return " ".join(parts)


# ── 主流程 ─────────────────────────────────────────────────────────────────────
def walk_forward(tix, X, years=TEST_YEARS, min_train=MIN_TRAIN):
    """返回 {year: (train_idx, eval_idx)} 与评估折(按进场时间排好)。"""
    ex = np.array([t["exit"] for t in tix])
    en = np.array([t["t"] for t in tix])
    out = {}
    for y in years:
        ystart = dt.datetime(y, 1, 1, tzinfo=UTC)
        cutoff = ystart - dt.timedelta(days=EMBARGO_DAYS)
        tr = np.where(ex < cutoff)[0]
        if len(tr) < min_train:
            print("fold", y, "skipped: train", len(tr), "<", min_train, flush=True)
            continue
        if y == max(years):
            ev = np.where(en >= ystart)[0]
        else:
            yend = dt.datetime(y + 1, 1, 1, tzinfo=UTC)
            ev = np.where((en >= ystart) & (en < yend))[0]
        ev = np.array(sorted(ev, key=lambda i: tix[i]["t"]))
        out[y] = (tr, ev)
        print("fold", y, "train", len(tr), "eval", len(ev), flush=True)
    return out


def build_folds(tix, X, wf, years):
    """评估折:每折带上走步给的训练段(平仓时间早于测试年起 30 天)。"""
    folds = []
    for y in years:
        if y not in wf:
            continue
        tr, ev = wf[y]
        if not len(ev):
            print("fold", y, "no eval tickets — skipped", flush=True)
            continue
        folds.append({"year": y, "meta": [tix[i] for i in ev], "r": np.array([tix[i]["r"] for i in ev]),
                      "Xtr": X[tr], "ytr": np.array([1 if tix[i]["r"] > 0 else 0 for i in tr], dtype=int)})
    return folds


def run_live(n_perm=N_PERM):
    S916 = load_first_layer()
    cache = "/Volumes/CometCloudAI/cometcloud-local/research/s924_bars.pkl"
    bars = load_bars(S916, cache=cache)
    daily = load_daily(S916)
    tix, inds = build_tickets(S916, bars)
    X = feature_matrix(tix, bars, inds, daily)
    wf = walk_forward(tix, X)
    n_cand = len(tix)
    res = {"n_candidates": n_cand, "folds": {str(y): {"train": len(wf[y][0]), "eval": len(wf[y][1])} for y in wf},
           "n_missing": {k: int(np.sum(np.isnan(X[:, j]))) for j, k in enumerate(FEATS)} if len(X) else {}}
    print("MISSING", json.dumps(res["n_missing"], ensure_ascii=False), flush=True)
    ev_folds = build_folds(tix, X, wf, EVAL_YEARS)
    print("EVAL folds", [(f["year"], len(f["meta"])) for f in ev_folds], flush=True)
    cells = {}
    for model in ("logit", "hgb"):
        c = run_cell(model, ev_folds, n_perm=n_perm)
        cells[f"short|{model}"] = c
        print(cell_line(f"short|{model}", c, n_cand), flush=True)
        dd = c.get("day_diag") or {}
        try:
            print("DAY", f"short|{model}", "days_all", dd.get("n_days_all"), "days_with_top", dd.get("n_days_with_top"),
                  "days_ge2_tickets", dd.get("days_with_ge2_tickets"), "tickets_per_day_max", dd.get("tickets_per_day_max"),
                  "best_day", dd.get("best_day"), "best_day_n", dd.get("best_day_n_tickets"),
                  "best_day_share_topR", fmt(dd.get("best_day_share_of_top_R")),
                  "neg_day_lift_days", dd.get("n_days_day_lift_negative"),
                  "per_year_day_lift", json.dumps(c.get("per_year_day_lift"), ensure_ascii=False), flush=True)
        except Exception as e:  # noqa: BLE001
            print("DAY diag failed", type(e).__name__, str(e)[:120], flush=True)
    # FEAT:评估样本前 5 张票(按进场时间)
    allt = [t for f in ev_folds for t in f["meta"]]
    allt.sort(key=lambda t: t["t"])
    for t in allt[:5]:
        vals = ",".join(f"{k}={t['f'][k]:.6g}" for k in FEATS)
        print(f"FEAT {t['coin']}|{t['t'].isoformat()}|r={t['r']:.4f}|{vals}", flush=True)
    res["cells"] = cells
    res["feat_head"] = [{"coin": t["coin"], "t": t["t"].isoformat(), "r": t["r"],
                         "f": {k: (None if not math.isfinite(t["f"][k]) else t["f"][k]) for k in FEATS}}
                        for t in allt[:5]]
    json.dump(res, open(OUT_JSON, "w"), ensure_ascii=False, indent=1, default=str)
    print("WROTE", OUT_JSON, flush=True)


# ── 自检 ───────────────────────────────────────────────────────────────────────
def synth_daily(dates, seed=4242):
    """合成三张日线表(覆盖 2018-01-01 → 2026-12-31)。"""
    rng = np.random.default_rng(seed)
    fund = {}
    for i, c in enumerate(COINS[:3]):
        dd = sorted(dates)
        fund[c] = (dd, list(rng.normal(0.00005, 0.0003, len(dd))))
    fm = {}
    for d in dates:
        fm[d] = {k: float(rng.normal()) for k in MKT_KEYS}
        fm[d]["taker_buy_share_30d"] = float(rng.uniform(0.3, 0.7))
    jz = {d: float(rng.normal()) for d in dates}
    d = Daily(fund, fm, jz)
    d.finalize()
    return d


def synth_bars(n_years=6, n_coins=6, seed=4242):
    """合成 4h 线(小时线聚合),带下行漂移 ⇒ BR_S 触发较多。"""
    rng = np.random.default_rng(seed)
    bars, start = {}, dt.datetime(2019, 1, 1, tzinfo=UTC)
    n_h = 24 * 365 * n_years
    for j, coin in enumerate(COINS[:n_coins]):
        rows, px = [], 100.0 * (1 + 0.3 * j)
        for k in range(n_h):
            drift = -0.00025 + 0.0004 * math.sin(k / (24 * 90 + 13 * j))
            o = px
            px = max(0.5, px * math.exp(drift + 0.008 * rng.standard_normal()))
            hi = max(o, px) * (1 + abs(0.003 * rng.standard_normal()))
            lo = min(o, px) * (1 - abs(0.003 * rng.standard_normal()))
            rows.append({"ts": (start + dt.timedelta(hours=k)).isoformat(),
                         "open": o, "high": hi, "low": lo, "close": px})
        bars[coin] = S916_G.to_4h(rows)
    return bars


def selftest():
    global S916_G
    S916_G = load_first_layer()
    print("== selftest:合成数据", flush=True)
    bars = synth_bars()
    dates = [dt.date(2018, 1, 1) + dt.timedelta(days=i) for i in range((dt.date(2026, 12, 31) - dt.date(2018, 1, 1)).days + 1)]
    daily = synth_daily(dates)
    tix, inds = build_tickets(S916_G, bars)
    X = feature_matrix(tix, bars, inds, daily)
    assert X.shape[1] == len(FEATS), X.shape
    wf = walk_forward(tix, X)
    ev_folds = build_folds(tix, X, wf, EVAL_YEARS)
    for model in ("logit", "hgb"):
        c = run_cell(model, ev_folds, n_perm=30)
        print(cell_line(f"short|{model}", c, len(tix)), flush=True)
        assert "lift" in c and len(c["criteria"]) == 7
    # 未来数据检查:截短序列后,截断点之前的票的特征不变
    print("== selftest:截短序列后特征不变", flush=True)
    coin = next(iter(bars))
    b = bars[coin]
    ind = S916_G.indicators(b)
    cut = len(b["c"]) // 2
    bc = {"t": b["t"][:cut], "o": b["o"][:cut], "h": b["h"][:cut], "l": b["l"][:cut], "c": b["c"][:cut]}
    indc = S916_G.indicators(bc)
    tix_f = [t for t in tix if t["coin"] == coin]
    tkc = []
    idxc = {t: i for i, t in enumerate(bc["t"])}
    for (t0, side, R, hold) in S916_G.tickets(bc, indc, RULE):
        j0 = idxc.get(t0)
        if j0 is None:
            continue
        tkc.append({"coin": coin, "t": t0, "exit": t0 + dt.timedelta(hours=4 * int(hold)), "r": float(R),
                    "k": j0 - 1, "j0": j0, "side": int(side)})
    n_cmp = 0
    full_by_t = {t["t"]: t for t in tix_f}
    for tc in tkc:
        tf = full_by_t.get(tc["t"])
        if tf is None or tf["j0"] != tc["j0"] or tc["k"] < 1300:
            continue
        ff = coin_feats(b, ind, tf["k"])
        fc = coin_feats(bc, indc, tc["k"])
        for k in FEATS[:8]:
            a, bb = ff[k], fc[k]
            assert (math.isnan(a) and math.isnan(bb)) or abs(a - bb) < 1e-12, (k, a, bb, tf["t"])
        n_cmp += 1
    assert n_cmp > 0, "没有可比对的票(截短检查没跑起来)"
    print("SELFTEST OK 比对票数", n_cmp, flush=True)


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        np_perm = N_PERM
        if "--nperm" in sys.argv:
            np_perm = int(sys.argv[sys.argv.index("--nperm") + 1])
        run_live(n_perm=np_perm)
