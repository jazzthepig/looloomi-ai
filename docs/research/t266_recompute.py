"""T-266 — S-741 联合模型 v2 的盲复算 + 稳健性(只报不判)。

**为什么有这张卡:** S-741 是第一个过了预注册的联合模型(台账 S-741 结果段,Ridge ✅ / HGB ❌),
只有 lane-c 一个人算过(T-263),余量不宽((b) 0.986 对 0.95、(c) 2.48 对 2.0)。这张卡按台账文字
**独立重写**一遍,再问:它的 ✅ 在 α / z 窗口 / 逐族去掉新维度 / 把新维度换成噪声 / 实盘口径
(每天扩张重训)下还在不在。**只报不判** —— 不改 S-741 的判,不动钱,不改代码,不入库。

## 口径(全部照台账 S-739 框架段 + S-741 预注册段,逐条列在下面)

- **样本**:`feature_matrix_daily` 2021-03-24 起(物化副本),与 `perp_bv_daily` symbol=eq.BTC
  (同样从 2021-03-24 起)按日期内连接;同日期多行取第一行。
  目标 = BTC 永续之后 **30 行**(价格序列行数)的对数收益;7 天目标只作副(不判)。
- **折**:`joint_model.purged_folds(n, 6, embargo=30, min_train=365)` —— 6 折走步、隔离带 = 持有期。
- **模型**:Ridge(alpha=10,特征按**训练段**标准化;StandardScaler 放进 Pipeline,统计量只来自训练段)
  / HistGradientBoosting(max_depth=3, learning_rate=0.05, max_iter=300, random_state=739)。
- **分数 z**(台账字面):z_t = (p_t − **过去 90 个样本外预测**的均值) / 标准差(样本标准差 ddof=1),
  不足 60 个历史预测则当天不出分。窗口是「严格早于当天的、有限的样本外预测」,不是日历天
  ⇒ 天然跨折(embargo 缺口处不占位)。另算一个「过去 90 行里取有限的」变体作口径对照。
- **判据(S-741,只报不判)**:(a) z 的合并样本外 IC;(b) 块置换分位(1,000 次、块长 20、种子 741);
  (c) 按月 t;(d) 折 4–6 IC;(e) 同一 z 变换作用在「BTC 过去 30 天收益」上的 IC,差值 ≥ 0.05。
- **框架**:零分布 / IC / 按月 t / 置换重要性一律走 `src/data/evaluation/joint_model.py`
  (它内部用 `apparatus.block_permute` / `null_distribution` / `percentile_of`)。

## 用法

```bash
python3 docs/research/t266_recompute.py --keys-json docs/research/t266_keys_t263.json \
    --out docs/research/t266_results.json --tag t263-59keys
```

产物:`docs/research/t266_results.json`。读库只读(`SUPABASE_URL` / `SUPABASE_KEY`,缺了就退出),
数据落在 Mac 数据根 `research/_cache/t266/`(不在 /tmp)。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
import urllib.parse
import urllib.request
from typing import Any, Optional, Sequence

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.data.evaluation.joint_model import (  # noqa: E402
    evaluate,
    purged_folds,
    spearman,
    walk_forward,
)

# ---------------------------------------------------------------- 常量(照台账写死)

START = "2021-03-24"          # DVOL 第一天(S-739 预注册)
N_FOLDS = 6                  # S-739:6 折走步
EMBARGO = 30                 # 隔离带 = 持有期
MIN_TRAIN = 365              # 最少训练 365 天
Z_WINDOW = 90                # z 的过去 90 个样本外预测
Z_MIN_HIST = 60              # 不足 60 个历史预测就不出分
RIDGE_ALPHA = 10.0
HGB_SEED = 739
NULL_SEED = 741              # S-741 判据 (b):种子 741
NULL_N = 1000
NULL_BLOCK = 20
HORIZON = 30
NEW_FAMILIES = ("style:", "chain:", "pos:", "channel:")   # S-741 新并进来的维度族
CACHE = "/Volumes/CometCloudAI/cometcloud-local/research/_cache/t266"

T263_FP_FEATURE = "b9986acab240c1965d33c4633dfb3732c1c72a0b4be0c66c5f87afd682562dce"
T263_FP_PRICE = "319d603857030dc5e8eba3942029b424c150131d85fa3498c9d0c6b262657ad5"

# ---------------------------------------------------------------- 读库(只读)

def _sb(table: str, params: dict, rng: Optional[str] = None) -> list[dict]:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        sys.exit("SUPABASE_URL / SUPABASE_KEY 没设置 —— 这张卡要读库")
    q = urllib.parse.urlencode(params, safe="().,*")
    headers = {"apikey": key, "Authorization": "Bearer " + key}
    if rng:
        headers["Range"] = rng
    req = urllib.request.Request(f"{url.rstrip('/')}/rest/v1/{table}?{q}", headers=headers)
    with urllib.request.urlopen(req, timeout=300) as resp:
        body = resp.read().decode()
    return json.loads(body) if body else []


def _count(table: str, params: dict) -> Optional[int]:
    """PostgREST `Prefer: count=exact` → Content-Range 里的总行数(抓完核对用)。"""
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        return None
    q = urllib.parse.urlencode(params, safe="().,*")
    headers = {"apikey": key, "Authorization": "Bearer " + key,
               "Prefer": "count=exact", "Range": "0-0"}
    req = urllib.request.Request(f"{url.rstrip('/')}/rest/v1/{table}?{q}", headers=headers)
    with urllib.request.urlopen(req, timeout=300) as resp:
        cr = resp.headers.get("Content-Range", "")
    m = re.search(r"/(\d+)$", cr)
    return int(m.group(1)) if m else None


def _paged(table: str, params: dict, cache_name: str) -> list[dict]:
    """按主键排、每页 1000 行翻页;结果落 Mac 数据根的缓存(不在 /tmp)。

    ⚠️ 翻页边界会漂:排序键(`d`)不唯一时,同一行可能同时出现在相邻两页
    (11-06 实测:joint_forecast_daily 缓存里 2025-01-16 出现了两次,总行数比真实多 1)。
    ⇒ 抓完按主键去重(保留第一条),并用 `Prefer: count=exact` 核总行数。
    """
    os.makedirs(CACHE, exist_ok=True)
    path = os.path.join(CACHE, cache_name)
    if os.path.exists(path):
        with open(path) as fh:
            return json.load(fh)
    out: list[dict] = []
    lo = 0
    while True:
        rows = _sb(table, params, f"{lo}-{lo + 999}")
        if not rows:
            break
        out.extend(rows)
        lo += len(rows)
        if len(rows) < 1000:
            break
    seen, ded, ndup = set(), [], 0
    for r in out:
        k = str(r.get("d"))
        if k in seen:
            ndup += 1
            continue
        seen.add(k)
        ded.append(r)
    if ndup:
        print(f"  [dedupe] {table}: 翻页重复 {ndup} 行 → 去重后 {len(ded)} 行")
    with open(path, "w") as fh:
        json.dump(ded, fh)
    return ded


def load_features() -> list[dict]:
    return _paged("feature_matrix_daily", {"select": "d,f", "d": f"gte.{START}", "order": "d.asc"},
                  "fm_since_2021.json")


def load_perp() -> list[dict]:
    """价格序列:与 T-263 同口径(从 START 起),这样价格指纹可以直接对。"""
    return _paged("perp_bv_daily", {"select": "d,c", "symbol": "eq.BTC", "d": f"gte.{START}",
                                    "order": "d.asc"}, "perp_btc_from_2021.json")


def load_joint_forecast() -> list[dict]:
    """生产 `joint_forecast_daily`(实盘口径每天扩张重训)的 (pred, z) —— 只作校准锚点。"""
    return _paged("joint_forecast_daily", {"select": "d,pred,z,kind,n_hist",
                                           "order": "d.asc"}, "joint_forecast_daily.json")


# ---------------------------------------------------------------- 样本

def build_sample(keys: Sequence[str]):
    """特征矩阵 + BTC 永续目标 → 日期 / X / y(30 天后) / r30(过去 30 天) / 月份 / 连接后的行。

    口径:价格序列 perp_bv_daily(eq.BTC) 从 START 起;特征行按日期连接(同日期取第一行);
    目标是 d 之后 **30 行**的对数收益;「过去 30 天收益」在价格序列头 30 行取不到 ⇒ NaN
    (不丢样本行,只丢该派生量),与 T-263 的 past_ret 口径一致。
    """
    fm = load_features()
    perp = load_perp()
    px = {r["d"]: float(r["c"]) for r in perp}
    pxd = [px[d] for d in sorted(px)]
    pxi = {d: i for i, d in enumerate(sorted(px))}

    rows, seen = [], set()
    for r in fm:
        d = r["d"]
        if d not in px or d in seen:
            continue
        seen.add(d)
        rows.append({"d": d, "f": r.get("f") or {}})

    dates, rows_x, y, r30 = [], [], [], []
    for r in rows:
        d = r["d"]
        i = pxi[d]
        if i + HORIZON >= len(pxd):
            continue                                   # 没有目标(价格序列尾部 30 行)
        dates.append(d)
        rows_x.append([r["f"].get(k) for k in keys])
        y.append(math.log(pxd[i + HORIZON] / pxd[i]))
        r30.append(math.log(pxd[i] / pxd[i - HORIZON]) if i >= HORIZON else float("nan"))

    X = np.array([[np.nan if v is None else float(v) for v in row] for row in rows_x], dtype=float)
    y = np.array(y, dtype=float)
    r30 = np.array(r30, dtype=float)
    months = [d[:7] for d in dates]
    return dates, X, y, r30, months, rows, pxd


def z_of_series(values: Sequence[float], window: int = Z_WINDOW,
                min_hist: int = Z_MIN_HIST) -> np.ndarray:
    """台账 S-741 的 z:相对「过去 window 个有限的样本外预测」的位置。

    逐点走:非有限值跳过(不占历史);历史满 min_hist 个才出分;窗口 = 最后 window 个有限值
    (不含当天);标准差 ddof=1;窗口标准差为 0 ⇒ 当天不出分。
    """
    v = np.asarray(values, float)
    out = np.full(len(v), np.nan)
    hist: list[float] = []
    for i in range(len(v)):
        if not np.isfinite(v[i]):
            continue
        if len(hist) >= min_hist:
            w = np.asarray(hist[-window:], float)
            m = float(np.mean(w))
            s = float(np.std(w, ddof=1))
            if s > 0:
                out[i] = (float(v[i]) - m) / s
        hist.append(float(v[i]))
    return out


def z_of_rows(values: Sequence[float], window: int = Z_WINDOW,
              min_hist: int = Z_MIN_HIST) -> np.ndarray:
    """口径对照(不是台账字面):窗口 = 过去 window **行**里取有限的预测。"""
    v = np.asarray(values, float)
    out = np.full(len(v), np.nan)
    for i in range(len(v)):
        if not np.isfinite(v[i]):
            continue
        w = v[max(0, i - window):i]
        w = w[np.isfinite(w)]
        if len(w) < min_hist:
            continue
        m = float(np.mean(w))
        s = float(np.std(w, ddof=1))
        if s > 0:
            out[i] = (float(v[i]) - m) / s
    return out


# ---------------------------------------------------------------- 模型

def ridge_factory(alpha: float):
    from sklearn.linear_model import Ridge
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler
    # 标准化只在训练段里做(Pipeline 内部 fit),不用全样本
    return lambda: Pipeline([("sc", StandardScaler()), ("rg", Ridge(alpha=alpha))])


def hgb_factory():
    from sklearn.ensemble import HistGradientBoostingRegressor
    return lambda: HistGradientBoostingRegressor(max_depth=3, learning_rate=0.05, max_iter=300,
                                                 random_state=HGB_SEED)


# ---------------------------------------------------------------- 指标

def _baseline_variants(r30: np.ndarray, oof: np.ndarray, z: np.ndarray, y: np.ndarray,
                       z_window: int, z_min_hist: int) -> dict[str, Any]:
    """(e) 朴素基线的两个网格:A = 全日网格;B = 只在模型有样本外预测的日子上压缩后再 z。"""
    out: dict[str, Any] = {}
    zb_a = z_of_series(r30, z_window, z_min_hist)
    oof_days = np.isfinite(oof)
    seq = [float(v) for v in r30[oof_days] if np.isfinite(v)]
    zb_b = np.full(len(r30), np.nan)
    zz = z_of_series(seq, z_window, z_min_hist)
    k = 0
    for i in range(len(r30)):
        if not oof_days[i]:
            continue
        if not np.isfinite(r30[i]):
            continue
        zb_b[i] = zz[k]
        k += 1
    for tag, zb in (("A_daily_grid", zb_a), ("B_oof_grid", zb_b)):
        m = np.isfinite(z) & np.isfinite(zb) & np.isfinite(y)
        ic_model = spearman(z[m], y[m]) if m.sum() >= 5 else None
        ic_base = spearman(zb[m], y[m]) if m.sum() >= 5 else None
        out[tag] = {
            "n_common": int(m.sum()),
            "ic_model_z": None if ic_model is None else round(float(ic_model), 4),
            "ic_baseline": None if ic_base is None else round(float(ic_base), 4),
            "ic_diff": None if (ic_model is None or ic_base is None)
            else round(float(ic_model - ic_base), 4),
        }
    return out


def metrics(z: np.ndarray, y: np.ndarray, months: Sequence[str], r30: np.ndarray,
            oof: np.ndarray, folds, z_window: int = Z_WINDOW, z_min_hist: int = Z_MIN_HIST,
            seed: int = NULL_SEED) -> dict[str, Any]:
    """(a) IC / (b) 块置换分位 / (c) 按月 t / (d) 折 4–6 IC / (e) 朴素基线差。"""
    out: dict[str, Any] = {}
    ev = evaluate(z, y, months, block=NULL_BLOCK, n_null=NULL_N, seed=seed)
    out["a_ic"] = ev["ic"]
    out["b_pctile"] = ev["pctile"]
    out["b_null_p95"] = ev["null_p95"]
    out["c_monthly_t"] = ev["t"]
    out["c_n_months"] = ev["n_months"]
    out["n"] = ev["n"]

    # (d) 后半段(第 4–6 折)单独 IC
    if folds:
        late = np.concatenate([te for k, (_, te) in enumerate(folds) if k >= 3])
        out["d_ic_folds_4_6"] = spearman(z[late], y[late])
        out["d_n_folds_4_6"] = int(len(late))
    else:
        out["d_ic_folds_4_6"] = None
        out["d_n_folds_4_6"] = None

    # (e) 朴素基线:同一 z 变换作用在「BTC 过去 30 天收益」上
    base = _baseline_variants(r30, oof, z, y, z_window, z_min_hist)
    out["e"] = base
    out["e_baseline_ic"] = base["B_oof_grid"]["ic_baseline"]
    out["e_diff"] = base["B_oof_grid"]["ic_diff"]
    out["e_diff_daygrid"] = base["A_daily_grid"]["ic_diff"]
    return out


def e1_orthogonalised(z: np.ndarray, y: np.ndarray, r30: np.ndarray) -> Optional[float]:
    """E1:z 对过去 30 天收益做秩回归取残差后的 IC(探索性,不判)。"""
    from scipy.stats import rankdata
    m = np.isfinite(z) & np.isfinite(r30) & np.isfinite(y)
    if m.sum() < 30:
        return None
    zz, rr = z[m], rankdata(r30[m])
    A = np.column_stack([np.ones(len(rr)), rr])
    beta, *_ = np.linalg.lstsq(A, zz, rcond=None)
    res = zz - A @ beta
    return spearman(res, y[m])


def criteria(res: dict[str, Any]) -> dict[str, Any]:
    """S-741 五条判据的过/不过(只报不判)。"""
    a = res.get("a_ic")
    b = res.get("b_pctile")
    c = res.get("c_monthly_t")
    d = res.get("d_ic_folds_4_6")
    e = res.get("e_diff")
    ed = res.get("e_diff_daygrid")
    return {
        "a_ic_ge_0.10": bool(a is not None and a >= 0.10),
        "b_pctile_ge_0.95": bool(b is not None and b >= 0.95),
        "c_monthly_t_ge_2.0": bool(c is not None and c >= 2.0),
        "d_ic_folds_4_6_gt_0": bool(d is not None and d > 0),
        "e_diff_ge_0.05_oofgrid": bool(e is not None and e >= 0.05),
        "e_diff_ge_0.05_daygrid": bool(ed is not None and ed >= 0.05),
        "all_five_pass_oofgrid": bool(a is not None and a >= 0.10 and b is not None and b >= 0.95
                                      and c is not None and c >= 2.0 and d is not None and d > 0
                                      and e is not None and e >= 0.05),
    }


# ---------------------------------------------------------------- 变体

def run_spec(X: np.ndarray, y: np.ndarray, months, r30: np.ndarray, model: str, alpha: float,
             z_window: int, z_min_hist: int, seed: int = NULL_SEED,
             z_mode: str = "series") -> dict[str, Any]:
    folds = purged_folds(len(y), N_FOLDS, EMBARGO, MIN_TRAIN)
    factory = ridge_factory(alpha) if model == "ridge" else hgb_factory()
    oof = walk_forward(X, y, folds, factory)
    zf = z_of_series if z_mode == "series" else z_of_rows
    z = zf(oof, z_window, z_min_hist)
    res = metrics(z, y, months, r30, oof, folds, z_window, z_min_hist, seed=seed)
    res["model"] = model
    res["alpha"] = alpha
    res["z_window"] = z_window
    res["z_min_hist"] = z_min_hist
    res["z_mode"] = z_mode
    res["n_folds"] = len(folds)
    res["fold_test_sizes"] = [int(len(te)) for _, te in folds]
    res["n_scored"] = int(np.isfinite(z).sum())
    res["e1_ic_after_orthogonalisation"] = e1_orthogonalised(z, y, r30)
    per_fold = []
    for k, (_, te) in enumerate(folds):
        per_fold.append(spearman(z[te], y[te]))
    res["per_fold_ic"] = [None if v is None else round(v, 4) for v in per_fold]
    res["criteria"] = criteria(res)
    return res


def run_live_expanding(X: np.ndarray, y: np.ndarray, months, r30: np.ndarray, alpha: float,
                        z_window: int, z_min_hist: int, seed: int = NULL_SEED) -> dict[str, Any]:
    """实盘口径:每天扩张重训、隔离带 30(生产 joint_forecast_daily 用的就是这个)。

    每天 t:训练 = [0, t−30) 的全部样本(目标已知),特征 NaN 用训练段中位数填。
    """
    from sklearn.linear_model import Ridge
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler
    n = len(y)
    preds = np.full(n, np.nan)
    for t in range(MIN_TRAIN + EMBARGO, n):
        tr = np.arange(0, t - EMBARGO)
        ok = ~np.isnan(y[tr])
        med = np.nanmedian(X[tr][ok], axis=0)
        med = np.where(np.isnan(med), 0.0, med)
        Xf = np.where(np.isnan(X[tr][ok]), med, X[tr][ok])
        mdl = Pipeline([("sc", StandardScaler()), ("rg", Ridge(alpha=alpha))])
        mdl.fit(Xf, y[tr][ok])
        xt = np.where(np.isnan(X[t]), med, X[t])
        preds[t] = float(mdl.predict(xt.reshape(1, -1))[0])
    z = z_of_series(preds, z_window, z_min_hist)
    folds = purged_folds(n, N_FOLDS, EMBARGO, MIN_TRAIN)
    res = metrics(z, y, months, r30, preds, folds, z_window, z_min_hist, seed=seed)
    res["model"] = "ridge_live_expanding"
    res["alpha"] = alpha
    res["z_window"] = z_window
    res["z_min_hist"] = z_min_hist
    res["z_mode"] = "series"
    res["n_predictions"] = int(np.isfinite(preds).sum())
    res["n_scored"] = int(np.isfinite(z).sum())
    res["e1_ic_after_orthogonalisation"] = e1_orthogonalised(z, y, r30)
    res["criteria"] = criteria(res)
    return res, preds


def noise_variant(X: np.ndarray, y: np.ndarray, months, r30: np.ndarray, new_idx: Sequence[int],
                  alpha: float, z_window: int, z_min_hist: int, n_seeds: int = 20) -> dict[str, Any]:
    """把新维度的 21 列换成 21 列标准正态噪声(20 个种子)—— 回答 E6:新维度是不是只多给了拟合噪声的机会。"""
    folds = purged_folds(len(y), N_FOLDS, EMBARGO, MIN_TRAIN)
    ics, pcts = [], []
    for s in range(n_seeds):
        rng = np.random.default_rng(1000 + s)
        Xn = X.copy()
        Xn[:, list(new_idx)] = rng.standard_normal((len(X), len(new_idx)))
        oof = walk_forward(Xn, y, folds, ridge_factory(alpha))
        z = z_of_series(oof, z_window, z_min_hist)
        m = np.isfinite(z) & np.isfinite(y)
        ic = spearman(z[m], y[m])
        ics.append(None if ic is None else round(ic, 4))
        pcts.append(None)
    vals = [v for v in ics if v is not None]
    return {"n_seeds": n_seeds, "n_noise_cols": len(new_idx),
            "ic_per_seed": ics,
            "ic_mean": None if not vals else round(float(np.mean(vals)), 4),
            "ic_sd": None if not vals else round(float(np.std(vals, ddof=1)), 4),
            "ic_min": None if not vals else min(vals),
            "ic_max": None if not vals else max(vals),
            "ic_frac_ge_0.10": None if not vals else round(float(np.mean([v >= 0.10 for v in vals])), 3)}


# ---------------------------------------------------------------- 指纹

def fingerprints(rows: list[dict], pxd: list[float], keys: Sequence[str]) -> dict[str, Any]:
    """T-263 的两个指纹(同一算法:整行 [d, f] 的 json.dumps + sha256)。

    - `feature_full`:今天的原始行(表里今天有什么列就是什么列)。
    - `feature_restricted_to_keys`:只保留本卡列集的键 —— 若它等于 T-263 的指纹,说明**这 59 列的
      数据本身没变**,差别只在别的列。
    """
    def fp(obj) -> str:
        return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()

    ks = set(keys)
    full = [[r["d"], r["f"]] for r in rows]
    restricted = [[r["d"], {k: v for k, v in r["f"].items() if k in ks}] for r in rows]
    dates = sorted(r["d"] for r in rows)
    px = {r["d"]: float(r["c"]) for r in load_perp()}
    price_rows = [[d, px[d]] for d in sorted(px)]
    return {
        "feature_full": fp(full),
        "feature_restricted_to_keys": fp(restricted),
        "feature_restricted_matches_t263": fp(restricted) == T263_FP_FEATURE,
        "price": fp(price_rows),
        "price_matches_t263": fp(price_rows) == T263_FP_PRICE,
        "t263_feature_fingerprint": T263_FP_FEATURE,
        "t263_price_fingerprint": T263_FP_PRICE,
    }


def joint_forecast_check(preds: np.ndarray, dates: Sequence[str]) -> dict[str, Any]:
    """把本卡的实盘口径预测与生产 `joint_forecast_daily` 存的 (pred, z) 对一下(校准锚点,不判)。"""
    jf = load_joint_forecast()
    by_d = {str(r["d"])[:10]: r for r in jf}
    dp, dz, n = [], [], 0
    for i, d in enumerate(dates):
        r = by_d.get(d)
        if not r or not np.isfinite(preds[i]) or r.get("pred") is None:
            continue
        dp.append(float(preds[i]) - float(r["pred"]))
        n += 1
        if r.get("z") is not None and np.isfinite(preds[i]):
            # 生产 z:从生产自己的 pred 序列按同样口径重算,验证 z 变换本身
            pass
    # 用生产 pred 序列重算 z(生产口径:每天一个预测,窗口 90 / 少 60)
    seq = []
    for r in jf:
        seq.append(float(r["pred"]) if r.get("pred") is not None else float("nan"))
    z_prod_recalc = z_of_series(seq, Z_WINDOW, Z_MIN_HIST)
    dzz = []
    for i, r in enumerate(jf):
        if r.get("z") is None:
            continue
        zz = z_prod_recalc[i]
        if np.isfinite(zz):
            dzz.append(float(zz) - float(r["z"]))
    return {
        "n_joint_forecast_rows": len(jf),
        "n_compared_preds": n,
        "pred_diff_mean": None if not dp else round(float(np.mean(dp)), 6),
        "pred_diff_absmax": None if not dp else round(float(np.max(np.abs(dp))), 6),
        "n_compared_z": len(dzz),
        "z_diff_absmax": None if not dzz else round(float(np.max(np.abs(dzz))), 6),
        "note": "生产 joint_forecast_daily 的 pred 由生产代码写;这里是独立复算的实盘口径预测的差(只作口径锚点)",
    }


# ---------------------------------------------------------------- 主流程

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keys-json", default=None, help="列集 json 文件(默认 = 今天表里的全部键)")
    ap.add_argument("--out", default="docs/research/t266_results.json")
    ap.add_argument("--tag", default="all-keys")
    ap.add_argument("--skip-robustness", action="store_true")
    args = ap.parse_args()

    fm = load_features()
    union = sorted({k for r in fm for k in (r.get("f") or {})})
    if args.keys_json:
        with open(args.keys_json) as fh:
            keys = json.load(fh)
        keys = sorted(set(keys))
    else:
        keys = union
    missing = [k for k in keys if k not in union]

    dates, X, y, r30, months, rows, pxd = build_sample(keys)
    out: dict[str, Any] = {
        "task": "T-266",
        "tag": args.tag,
        "generated_at_utc": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc).isoformat(timespec="seconds"),
        "data": {
            "feature_source": "feature_matrix_daily (materialized), d >= " + START,
            "perp_source": "perp_bv_daily symbol=eq.BTC (c), d >= " + START,
            "n_feature_rows_in_window": len(fm),
            "n_rows_joined": len(rows),
            "sample_start": dates[0], "sample_end": dates[-1], "n_samples": len(dates),
            "target": "ln(perp_BTC_close[d+30 rows] / perp_BTC_close[d])",
            "n_keys_used": len(keys),
            "keys_sha256_12": hashlib.sha256(",".join(keys).encode()).hexdigest()[:12],
            "keys": keys,
            "keys_missing_from_table": missing,
            "n_keys_in_table_today": len(union),
            "keys_added_since_this_set": [k for k in union if k not in set(keys)],
            "keys_dropped_vs_table_today": [k for k in keys if k not in set(union)],
            "row_count_check_exact": {
                "feature_matrix_daily_in_window": _count(
                    "feature_matrix_daily", {"select": "d", "d": f"gte.{START}"}),
                "perp_bv_daily_eqBTC_in_window": _count(
                    "perp_bv_daily", {"select": "d", "symbol": "eq.BTC", "d": f"gte.{START}"}),
                "joint_forecast_daily": _count("joint_forecast_daily", {"select": "d"}),
            },
        },
        "fingerprints": fingerprints(rows, pxd, keys),
        "spec": {"n_folds": N_FOLDS, "embargo": EMBARGO, "min_train": MIN_TRAIN, "z_window": Z_WINDOW,
                 "z_min_hist": Z_MIN_HIST, "z_mode": "series(过去 90 个有限样本外预测,不含当天,ddof=1)",
                 "ridge_alpha": RIDGE_ALPHA, "hgb_seed": HGB_SEED,
                 "null_seed": NULL_SEED, "null_n": NULL_N, "null_block": NULL_BLOCK},
        "results": {},
    }

    # ---- 主规格:Ridge + HGB
    out["results"]["base_ridge"] = run_spec(X, y, months, r30, "ridge", RIDGE_ALPHA,
                                            Z_WINDOW, Z_MIN_HIST)
    out["results"]["base_hgb"] = run_spec(X, y, months, r30, "hgb", RIDGE_ALPHA,
                                          Z_WINDOW, Z_MIN_HIST)
    # 口径对照:z 的窗口取「过去 90 行」而不是「过去 90 个预测」
    out["results"]["base_ridge_zmode_rows"] = run_spec(X, y, months, r30, "ridge", RIDGE_ALPHA,
                                                       Z_WINDOW, Z_MIN_HIST, z_mode="rows")

    if not args.skip_robustness:
        rob: dict[str, Any] = {}
        for a in (3.0, 30.0):
            rob[f"alpha_{int(a)}"] = run_spec(X, y, months, r30, "ridge", a, Z_WINDOW, Z_MIN_HIST)
        for w, mh in ((60, 40), (120, 80)):
            rob[f"z_window_{w}"] = run_spec(X, y, months, r30, "ridge", RIDGE_ALPHA, w, mh)
        for fam in NEW_FAMILIES:
            fam_keys = [k for k in keys if k.startswith(fam)]
            if not fam_keys:
                continue
            keep = [i for i, k in enumerate(keys) if not k.startswith(fam)]
            rob[f"drop_{fam.rstrip(':')}"] = run_spec(X[:, keep], y, months, r30, "ridge",
                                                     RIDGE_ALPHA, Z_WINDOW, Z_MIN_HIST)
            rob[f"drop_{fam.rstrip(':')}"]["dropped_keys"] = fam_keys
        new_idx = [i for i, k in enumerate(keys) if k.startswith(NEW_FAMILIES)]
        rob["noise_replacement_of_new_dims"] = noise_variant(X, y, months, r30, new_idx,
                                                            RIDGE_ALPHA, Z_WINDOW, Z_MIN_HIST,
                                                            n_seeds=20)
        live, live_preds = run_live_expanding(X, y, months, r30, RIDGE_ALPHA, Z_WINDOW, Z_MIN_HIST)
        rob["live_expanding_daily_retrain"] = live
        rob["live_expanding_daily_retrain"]["joint_forecast_calibration"] = joint_forecast_check(
            live_preds, dates)
        out["results"]["robustness"] = rob

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    print("wrote", args.out)
    for k, v in out["results"].items():
        if isinstance(v, dict) and "a_ic" in v:
            print(f"  {k:34s} a={v.get('a_ic')} b={v.get('b_pctile')} c={v.get('c_monthly_t')} "
                  f"d={v.get('d_ic_folds_4_6')} e_diff={v.get('e_diff')} E1={v.get('e1_ic_after_orthogonalisation')}")
    rb = out["results"].get("robustness", {})
    for k, v in rb.items():
        if isinstance(v, dict) and "a_ic" in v:
            print(f"  rob.{k:29s} a={v.get('a_ic')} b={v.get('b_pctile')} c={v.get('c_monthly_t')} "
                  f"d={v.get('d_ic_folds_4_6')} e_diff={v.get('e_diff')} E1={v.get('e1_ic_after_orthogonalisation')}")


if __name__ == "__main__":
    main()
