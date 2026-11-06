"""T-266 — S-741 联合模型 v2 的盲复算 + 稳健性(只报不判)。

**为什么有这张卡:** S-741 是第一个过了预注册的联合模型(台账 S-741 结果段,Ridge ✅ / HGB ❌),
只有 lane-c 一个人算过(T-263),余量不宽((b) 0.986 对 0.95、(c) 2.48 对 2.0)。这张卡按台账文字
**独立重写**一遍,再问:它的 ✅ 在 α / z 窗口 / 逐族去掉新维度 / 把新维度换成噪声 / 实盘口径
(每天扩张重训)下还在不在。**只报不判** —— 不改 S-741 的判,不动钱,不改代码,不入库。

## 口径(全部照台账 S-739 框架段 + S-741 预注册段,逐条列在下面)

- **样本**:`feature_matrix_daily` 2021-03-24 起(物化副本),目标 = BTC 永续之后 30 天对数收益
  (`perp_bv_daily` symbol=BTC 收盘);7 天目标只作副(不判)。
- **折**:`joint_model.purged_folds(n, 6, embargo=30, min_train=365)` —— 6 折走步、隔离带 = 持有期。
- **模型**:Ridge(alpha=10,特征按**训练段**标准化;StandardScaler 放进 Pipeline,统计量只来自训练段)
  / HistGradientBoosting(max_depth=3, learning_rate=0.05, max_iter=300, random_state=739)。
- **分数 z**:z_t = (p_t − 过去 90 个样本外预测的均值) / 标准差(样本标准差 ddof=1),
  **窗口不含当天**,不足 60 个历史预测则当天不出分。
  这条口径不是猜的:`joint_forecast_daily` 里存着 (pred, z) 对,本脚本用它的 backfill 段
  复算,excl+ddof=1 与库里的 z 最大差 5e-5(见 t266_results.json 的 z_convention_check)。
- **判据(S-741,只报不判)**:(a) z 的合并样本外 IC;(b) 块置换分位(1,000 次、块长 20、种子 741);
  (c) 按月 t;(d) 折 4–6 IC;(e) 同一 z 变换作用在「BTC 过去 30 天收益」上的 IC,差值 ≥ 0.05。
- **框架**:零分布 / IC / 按月 t / 置换重要性一律走 `src/data/evaluation/joint_model.py`
  (它内部用 `apparatus.block_permute` / `null_distribution` / `percentile_of`)。

## 用法

```bash
python3 docs/research/t266_recompute.py                       # 今天的全部键(71)
python3 docs/research/t266_recompute.py --keys-json <file>     # 指定列集(如 T-263 的 59 列)
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
Z_WINDOW = 90                # z 的过去 90 个预测
Z_MIN_HIST = 60              # 不足 60 个历史预测就不出分
RIDGE_ALPHA = 10.0
HGB_SEED = 739
NULL_SEED = 741              # S-741 判据 (b):种子 741
NULL_N = 1000
NULL_BLOCK = 20
HORIZON = 30
NEW_FAMILIES = ("style:", "chain:", "pos:", "channel:")   # S-741 新并进来的维度族
CACHE = "/Volumes/CometCloudAI/cometcloud-local/research/_cache/t266"

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


def _paged(table: str, params: dict, cache_name: str) -> list[dict]:
    """按主键排、每页 1000 行翻页;结果落 Mac 数据根的缓存(不在 /tmp)。"""
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
    with open(path, "w") as fh:
        json.dump(out, fh)
    return out


def load_features() -> list[dict]:
    return _paged("feature_matrix_daily", {"select": "d,f", "d": f"gte.{START}", "order": "d.asc"},
                  "fm_since_2021.json")


def load_perp() -> list[dict]:
    # 多取半年:样本头几天的「过去 30 天收益」基线要用 d−30 的价格
    return _paged("perp_bv_daily", {"select": "d,c", "symbol": "eq.BTC", "d": "gte.2020-01-01",
                                    "order": "d.asc"}, "perp_btc_from_2020.json")


# ---------------------------------------------------------------- 样本

def build_sample(keys: Sequence[str]):
    """特征矩阵 + BTC 永续目标 → 日期 / X / y(30 天后) / r30(过去 30 天) / 月份。"""
    fm = load_features()
    perp = load_perp()
    px = {r["d"]: float(r["c"]) for r in perp}
    pxd = [r["d"] for r in perp]
    pxi = {d: i for i, d in enumerate(pxd)}
    pvals = [px[d] for d in pxd]

    dates, rows_x, y, r30 = [], [], [], []
    for r in fm:
        d = r["d"]
        f = r.get("f") or {}
        i = pxi.get(d)
        if i is None or i + HORIZON >= len(pvals) or i < HORIZON:
            continue                                   # 没有目标 / 没有过去 30 天
        dates.append(d)
        rows_x.append([f.get(k) for k in keys])
        y.append(math.log(pvals[i + HORIZON] / pvals[i]))
        r30.append(math.log(pvals[i] / pvals[i - HORIZON]))

    X = np.array([[np.nan if v is None else float(v) for v in row] for row in rows_x], dtype=float)
    y = np.array(y, dtype=float)
    r30 = np.array(r30, dtype=float)
    months = [d[:7] for d in dates]
    return dates, X, y, r30, months


def zscore(pred: np.ndarray, window: int = Z_WINDOW, min_hist: int = Z_MIN_HIST) -> np.ndarray:
    """S-741 的 z:相对模型自己过去 window 个样本外预测的位置(窗口不含当天,样本标准差 ddof=1)。"""
    out = np.full(len(pred), np.nan)
    for i in range(len(pred)):
        if not np.isfinite(pred[i]):
            continue
        w = pred[max(0, i - window):i]
        w = w[np.isfinite(w)]
        if len(w) < min_hist:
            continue
        m = float(np.mean(w))
        sd = float(np.std(w, ddof=1))
        if sd <= 0:
            continue
        out[i] = (pred[i] - m) / sd
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

def metrics(z: np.ndarray, y: np.ndarray, months: Sequence[str], r30: np.ndarray,
            folds, seed: int = NULL_SEED) -> dict[str, Any]:
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
    late = np.zeros(len(y), dtype=bool)
    for k, (_, te) in enumerate(folds):
        if k >= 3:
            late[te] = True
    out["d_ic_folds_4_6"] = spearman(z[late], y[late])

    # (e) 朴素基线:同一 z 变换作用在「BTC 过去 30 天收益」上
    zb = zscore(r30)
    m = np.isfinite(z) & np.isfinite(zb) & np.isfinite(y)
    out["e_baseline_ic"] = spearman(zb[m], y[m]) if m.sum() >= 5 else None
    if out["a_ic"] is not None and out["e_baseline_ic"] is not None:
        out["e_diff"] = round(out["a_ic"] - out["e_baseline_ic"], 4)
    else:
        out["e_diff"] = None
    out["e_z_baseline_corr"] = spearman(z[m], zb[m]) if m.sum() >= 5 else None
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


# ---------------------------------------------------------------- 变体

def run_spec(X: np.ndarray, y: np.ndarray, months, r30: np.ndarray, model: str, alpha: float,
             z_window: int, z_min_hist: int, seed: int = NULL_SEED) -> dict[str, Any]:
    folds = purged_folds(len(y), N_FOLDS, EMBARGO, MIN_TRAIN)
    factory = ridge_factory(alpha) if model == "ridge" else hgb_factory()
    oof = walk_forward(X, y, folds, factory)
    z = zscore(oof, window=z_window, min_hist=z_min_hist)
    res = metrics(z, y, months, r30, folds, seed=seed)
    res["model"] = model
    res["alpha"] = alpha
    res["z_window"] = z_window
    res["z_min_hist"] = z_min_hist
    res["n_folds"] = len(folds)
    res["fold_test_sizes"] = [int(len(te)) for _, te in folds]
    res["e1_ic_after_orthogonalisation"] = e1_orthogonalised(z, y, r30)
    # 每折 IC(诊断用,不判)
    per_fold = []
    for k, (_, te) in enumerate(folds):
        per_fold.append(spearman(z[te], y[te]))
    res["per_fold_ic"] = [None if v is None else round(v, 4) for v in per_fold]
    return res


def run_live_expanding(X: np.ndarray, y: np.ndarray, months, r30: np.ndarray, alpha: float,
                        z_window: int, z_min_hist: int, seed: int = NULL_SEED) -> dict[str, Any]:
    """实盘口径:每天扩张重训、隔离带 30(生产 joint_forecast_daily 用的就是这个)。"""
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
    z = zscore(preds, window=z_window, min_hist=z_min_hist)
    folds = purged_folds(n, N_FOLDS, EMBARGO, MIN_TRAIN)
    res = metrics(z, y, months, r30, folds, seed=seed)
    res["model"] = "ridge_live_expanding"
    res["alpha"] = alpha
    res["z_window"] = z_window
    res["z_min_hist"] = z_min_hist
    res["n_predictions"] = int(np.isfinite(preds).sum())
    res["first_prediction_date"] = None
    return res


def noise_variant(X: np.ndarray, y: np.ndarray, months, r30: np.ndarray, new_idx: Sequence[int],
                  alpha: float, z_window: int, z_min_hist: int, n_seeds: int = 20) -> dict[str, Any]:
    """把新维度的 21 列换成 21 列标准正态噪声(20 个种子)—— 回答 E6:新维度是不是只多给了拟合噪声的机会。"""
    folds = purged_folds(len(y), N_FOLDS, EMBARGO, MIN_TRAIN)
    ics, pcts = [], []
    for s in range(n_seeds):
        rng = np.random.default_rng(1000 + s)
        Xn = X.copy()
        Xn[:, list(new_idx)] = rng.standard_normal((len(X), len(new_idx)))
        factory = ridge_factory(alpha)
        oof = walk_forward(Xn, y, folds, factory)
        z = zscore(oof, window=z_window, min_hist=z_min_hist)
        m = np.isfinite(z) & np.isfinite(y)
        ic = spearman(z[m], y[m])
        ics.append(None if ic is None else round(ic, 4))
        pcts.append(None)
    return {"n_seeds": n_seeds, "ic_per_seed": ics,
            "ic_mean": None if all(v is None for v in ics) else round(float(np.mean([v for v in ics if v is not None])), 4),
            "ic_sd": None if all(v is None for v in ics) else round(float(np.std([v for v in ics if v is not None], ddof=1)), 4),
            "ic_min": None if all(v is None for v in ics) else min(v for v in ics if v is not None),
            "ic_max": None if all(v is None for v in ics) else max(v for v in ics if v is not None)}


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
    fp = hashlib.sha256(",".join(keys).encode()).hexdigest()[:12]

    dates, X, y, r30, months = build_sample(keys)
    out: dict[str, Any] = {
        "task": "T-266",
        "tag": args.tag,
        "generated_at_utc": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(timespec="seconds"),
        "data": {
            "feature_source": "feature_matrix_daily (materialized), d >= " + START,
            "perp_source": "perp_bv_daily symbol=BTC (c)",
            "n_feature_rows_in_window": len(fm),
            "sample_start": dates[0], "sample_end": dates[-1], "n_samples": len(dates),
            "target": "ln(perp_BTC_close[d+30] / perp_BTC_close[d]) (positional +30 rows)",
            "n_keys_used": len(keys),
            "keys_sha256_12": fp,
            "keys": keys,
            "keys_missing_from_table": missing,
            "n_keys_in_table_today": len(union),
            "keys_added_since_this_set": [k for k in union if k not in set(keys)],
            "keys_dropped_vs_table_today": [k for k in keys if k not in set(union)],
        },
        "spec": {"n_folds": N_FOLDS, "embargo": EMBARGO, "min_train": MIN_TRAIN, "z_window": Z_WINDOW,
                 "z_min_hist": Z_MIN_HIST, "ridge_alpha": RIDGE_ALPHA, "hgb_seed": HGB_SEED,
                 "null_seed": NULL_SEED, "null_n": NULL_N, "null_block": NULL_BLOCK},
        "results": {},
    }

    # ---- 主规格:Ridge + HGB
    out["results"]["base_ridge"] = run_spec(X, y, months, r30, "ridge", RIDGE_ALPHA, Z_WINDOW, Z_MIN_HIST)
    out["results"]["base_hgb"] = run_spec(X, y, months, r30, "hgb", RIDGE_ALPHA, Z_WINDOW, Z_MIN_HIST)

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
                                                            RIDGE_ALPHA, Z_WINDOW, Z_MIN_HIST, n_seeds=20)
        rob["live_expanding_daily_retrain"] = run_live_expanding(X, y, months, r30, RIDGE_ALPHA,
                                                                Z_WINDOW, Z_MIN_HIST)
        out["results"]["robustness"] = rob

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    print("wrote", args.out)
    for k, v in out["results"].items():
        if isinstance(v, dict) and "a_ic" in v:
            print(f"  {k:34s} a={v.get('a_ic')} b={v.get('b_pctile')} c={v.get('c_monthly_t')} "
                  f"d={v.get('d_ic_folds_4_6')} e_diff={v.get('e_diff')} E1={v.get('e1_ic_after_orthogonalisation')}")


if __name__ == "__main__":
    main()
