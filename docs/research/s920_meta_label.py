"""S-920:在规则触发的那一刻做二次判断(meta-labeling)—— 规则出候选单,模型用触发当时已知的特征判断「这一张接不接」。

Jazz 11-26:「是不是现在这些策略都是非常机械的简单因子叠加?有没有做特征组合还有算法优化的?」→「按你建议来先做」。
S-916 – S-919 量出:4 小时突破回踩的进场本身只比随机好一点点;要问的是,触发那一刻已经在库里的资金费、拥挤度、波动、
状态、联合模型的分数,能不能把「会赚的那几张」挑出来。

候选单(第一层,不改):`s916_jazz_4h_rules.py` 的 BR_L(突破回踩做多)与 BR_S(破位回抽做空),管法 = 3 倍 ATR 吊灯、止损下限 1%、
单张截 +20R(S-919 的稳健口径),11 个币。标签 = 这张票 R > 0。
特征(16 个,写死;都只用到决定那根 4 小时收盘为止,日线 / 市场的取进场 UTC 日的前一天):
  币 · 4 小时:离 EMA50、EMA20 / EMA50、ATR / 价、布林带宽 / 价、近 6 根收益、近 42 根收益;
  币 · 日:7 日资金费(年化)、离 200 日均线(4 小时收盘的 1,200 根均值)、近 30 天收益(180 根);
  市场(`feature_matrix_daily` 原值):dist_200、style_rel_majors_30d、stable_supply_30d、funding_7d_ann_binance、pos:btc_crowd_ln、
  taker_buy_share_30d;联合模型分数 z(`joint_forecast_daily`,2022-04 起,之前为缺)。
模型(参数写死,不调):① L2 逻辑回归(训练段标准化、缺值填训练段中位数、C = 0.1);② 梯度提升树
(HistGradientBoostingClassifier:深 3、学习率 0.05、200 轮、叶子 ≥ 50、L2 = 1.0、种子 920,缺值原生处理)。多空各自一套。
走步:测试年 2022 / 2023 / 2024 / 2025(2025-01-01 → 末);训练 = 平仓时间早于测试年 1 月 1 日减 30 天的票(隔离带 = 持有期上限)。
每折里按预测概率分三档。
判(每个模型 × 方向各判,看 2023 起合并的样本外):(a) 上一档均值 R − 全部均值 R ≥ +0.15R;(b) 折内打乱预测 1,000 次,
上一档均值 R 的分位 ≥ 0.95;(c) 2023 / 2024 / 2025 三年里至少两年「上一档 − 全部」> 0;(d) AUC ≥ 0.55。四条全过 = 站得住。
预期与后果写在台账 S-920(先登记,后计算)。

用法(仓库根目录;环境里有只读的 SUPABASE_URL / SUPABASE_KEY):
    python3 docs/research/s920_meta_label.py --selftest
    nohup python3 docs/research/s920_meta_label.py > docs/research/s920_run.txt 2>&1 &      # 写 s920_results.json
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


def _load(name, path):
    sp = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


_argv, sys.argv = sys.argv, [sys.argv[0], "--mgmt", "atr3", "--dmin", "0.01", "--cap", "20"]
R = _load("s916", os.path.join(HERE, "s916_jazz_4h_rules.py"))      # 第一层 = S-919 的 atr3 稳健口径
sys.argv = _argv
S = R.S

OUT = "docs/research/s920_results.json"
PRIMARY = {"BR_L": 1, "BR_S": -1}
MARKET_KEYS = ("dist_200", "style_rel_majors_30d", "stable_supply_30d", "funding_7d_ann_binance", "pos:btc_crowd_ln", "taker_buy_share_30d")
FEATURES = ("dist_e50", "e20_e50", "atr_pct", "bbw", "ret_6", "ret_42", "fund7", "dist200_coin", "ret_30d",
            *MARKET_KEYS, "joint_z")
TEST_YEARS = (2022, 2023, 2024, 2025)
EVAL_YEARS = (2023, 2024, 2025)
EMBARGO = dt.timedelta(days=30)
N_PERM, SEED = 1000, 920
MIN_TRAIN = 150
LOGIT_C = 0.1
HGB = dict(max_depth=3, learning_rate=0.05, max_iter=200, min_samples_leaf=50, l2_regularization=1.0, random_state=SEED)


# ── 特征 ──────────────────────────────────────────────────────────────────────

def asof(dates: list, vals: list, d: dt.date, max_age: int):
    i = bisect.bisect_right(dates, d) - 1
    return vals[i] if i >= 0 and (d - dates[i]).days <= max_age else None


def coin_features(b: dict, ind: dict, k: int) -> dict:
    """决定那根(k)收盘为止的币 · 4 小时特征。"""
    c = b["c"]
    f = {"dist_e50": c[k] / ind["e50"][k] - 1, "e20_e50": ind["e20"][k] / ind["e50"][k] - 1,
         "atr_pct": ind["atr"][k] / c[k] if not math.isnan(ind["atr"][k]) else np.nan,
         "bbw": (ind["bu"][k] - ind["bl"][k]) / c[k] if not math.isnan(ind["bu"][k]) else np.nan,
         "ret_6": c[k] / c[k - 6] - 1 if k >= 6 else np.nan, "ret_42": c[k] / c[k - 42] - 1 if k >= 42 else np.nan,
         "dist200_coin": c[k] / c[k - 1199:k + 1].mean() - 1 if k >= 1199 else np.nan,
         "ret_30d": c[k] / c[k - 180] - 1 if k >= 180 else np.nan}
    return f


def candidates(bars: dict, fund: dict, market: dict, jz: tuple) -> list:
    """第一层的票 + 触发那一刻的特征。fund = {币: (日期列表, 7 日年化列表)};market = {日期: {键: 值}};jz = (日期列表, z 列表)。"""
    mdays = sorted(market)
    out = []
    for coin, b in bars.items():
        ind = R.indicators(b)
        pos = {t: i for i, t in enumerate(b["t"])}
        for rule, side in PRIMARY.items():
            for t_entry, s, r, nbars in R.tickets(b, ind, rule):
                k = pos[t_entry] - 1                         # 决定那根 = 进场 / 成交那根的前一根
                d1 = t_entry.date() - dt.timedelta(days=1)
                f = coin_features(b, ind, k)
                fd, fv = fund.get(coin, ([], []))
                f["fund7"] = asof(fd, fv, d1, 3)
                mi = bisect.bisect_right(mdays, d1) - 1
                mrow = market[mdays[mi]] if mi >= 0 and (d1 - mdays[mi]).days <= 3 else {}
                for key in MARKET_KEYS:
                    f[key] = mrow.get(key)
                f["joint_z"] = asof(jz[0], jz[1], d1, 3)
                out.append({"coin": coin, "rule": rule, "side": side, "t": t_entry, "exit_t": t_entry + dt.timedelta(hours=4 * nbars),
                            "r": float(r), **{q: (np.nan if f.get(q) is None else float(f[q])) for q in FEATURES}})
    return out


# ── 模型与走步 ────────────────────────────────────────────────────────────────

def _matrix(rows: list) -> np.ndarray:
    return np.array([[x[q] for q in FEATURES] for x in rows], dtype=float)


def fit_predict(kind: str, train: list, test: list) -> tuple:
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.linear_model import LogisticRegression
    Xtr, Xte = _matrix(train), _matrix(test)
    y = np.array([x["r"] > 0 for x in train], dtype=int)
    if len(set(y)) < 2:
        return np.full(len(test), float(y.mean())), None
    if kind == "logit":
        med = np.nanmedian(Xtr, axis=0)
        med = np.where(np.isnan(med), 0.0, med)
        Xtr, Xte = np.where(np.isnan(Xtr), med, Xtr), np.where(np.isnan(Xte), med, Xte)
        mu, sd = Xtr.mean(axis=0), Xtr.std(axis=0)
        sd = np.where(sd > 0, sd, 1.0)
        m = LogisticRegression(C=LOGIT_C, max_iter=2000)
        m.fit((Xtr - mu) / sd, y)
        return m.predict_proba((Xte - mu) / sd)[:, 1], dict(zip(FEATURES, [round(float(v), 3) for v in m.coef_[0]]))
    allnan = np.isnan(Xtr).all(axis=0)
    if allnan.any():
        # 11-26(T-441):sklearn 1.9 的直方图分箱遇到训练段整列缺失会崩(2022 折的 joint_z —— 联合模型 2022-04 才有分数)。
        # 按常数列处理 = 这一折不在这一列上分裂;与 lane-a 的 `_s920_run_patched.py` 同一口径,结果不变。
        Xtr, Xte = Xtr.copy(), Xte.copy()
        Xtr[:, allnan] = 0.0
        Xte[:, allnan] = 0.0
    m = HistGradientBoostingClassifier(**HGB)
    m.fit(Xtr, y)
    return m.predict_proba(Xte)[:, 1], None


def auc(y: np.ndarray, p: np.ndarray) -> float | None:
    pos, neg = p[y == 1], p[y == 0]
    if not len(pos) or not len(neg):
        return None
    order = np.argsort(np.r_[pos, neg], kind="mergesort")
    ranks = np.empty(len(order))
    ranks[order] = np.arange(1, len(order) + 1)
    allv = np.r_[pos, neg]
    for v in np.unique(allv):                              # 并列取平均秩
        idx = allv == v
        ranks[idx] = ranks[idx].mean()
    return float((ranks[:len(pos)].sum() - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg)))


def terciles(p: np.ndarray) -> np.ndarray:
    """折内按预测分三档:2 = 上,1 = 中,0 = 下(并列按出现顺序稳定切)。"""
    o = np.argsort(p, kind="mergesort")
    out = np.empty(len(p), dtype=int)
    n = len(p)
    for rank, i in enumerate(o):
        out[i] = min(2, rank * 3 // max(n, 1))
    return out


def walk(cands: list, side: int, kind: str) -> dict:
    rows = sorted([x for x in cands if x["side"] == side], key=lambda x: x["t"])
    folds, coefs = [], None
    for y in TEST_YEARS:
        start = dt.datetime(y, 1, 1, tzinfo=dt.timezone.utc)
        end = dt.datetime(y + 1, 1, 1, tzinfo=dt.timezone.utc) if y < TEST_YEARS[-1] else dt.datetime(2100, 1, 1, tzinfo=dt.timezone.utc)
        train = [x for x in rows if x["exit_t"] < start - EMBARGO]
        test = [x for x in rows if start <= x["t"] < end]
        if len(train) < MIN_TRAIN or not test:
            folds.append({"year": y, "n_train": len(train), "n_test": len(test), "skipped": True})
            continue
        p, cf = fit_predict(kind, train, test)
        if cf is not None:
            coefs = cf
        folds.append({"year": y, "n_train": len(train), "n_test": len(test), "p": p, "r": np.array([x["r"] for x in test]),
                      "tc": terciles(p)})
    return {"folds": folds, "coefs_last_fold": coefs}


def judge(w: dict, rng) -> dict:
    ev = [f for f in w["folds"] if not f.get("skipped") and f["year"] in EVAL_YEARS]
    per_year = {}
    for f in w["folds"]:
        if f.get("skipped"):
            per_year[f["year"]] = {"skipped": True, "n_train": f["n_train"]}
            continue
        top = f["r"][f["tc"] == 2]
        per_year[f["year"]] = {"n": int(len(f["r"])), "all": round(float(f["r"].mean()), 3), "top": round(float(top.mean()), 3) if len(top) else None,
                               "bottom": round(float(f["r"][f["tc"] == 0].mean()), 3) if (f["tc"] == 0).any() else None,
                               "auc": (lambda a: round(a, 3) if a is not None else None)(auc((f["r"] > 0).astype(int), f["p"]))}
    if not ev:
        return {"per_year": per_year, "holds": False, "why": "评估年没有可用的折"}
    r_all = np.concatenate([f["r"] for f in ev])
    top_all = np.concatenate([f["r"][f["tc"] == 2] for f in ev])
    lift = float(top_all.mean() - r_all.mean())
    null = []
    for _ in range(N_PERM):
        tops = []
        for f in ev:
            perm = rng.permutation(len(f["p"]))
            tops.append(f["r"][terciles(f["p"][perm]) == 2])
        null.append(float(np.concatenate(tops).mean()))
    pct = float((np.array(null) < top_all.mean()).mean())
    a = auc((r_all > 0).astype(int), np.concatenate([f["p"] for f in ev]))
    years_pos = sum(1 for f in ev if f["r"][f["tc"] == 2].mean() - f["r"].mean() > 0)
    crit = {"lift_ge_0.15": lift >= 0.15, "perm_pct_ge_0.95": pct >= 0.95, "years_pos_ge_2": years_pos >= 2, "auc_ge_0.55": (a or 0) >= 0.55}
    return {"per_year": per_year, "pooled": {"n": int(len(r_all)), "all_r": round(float(r_all.mean()), 3), "top_r": round(float(top_all.mean()), 3),
                                             "lift": round(lift, 3), "perm_pct": round(pct, 3), "auc": round(a, 3) if a is not None else None,
                                             "years_top_beats_all": years_pos},
            "criteria": crit, "holds": all(crit.values())}


def run(cands: list) -> dict:
    rng = np.random.default_rng(SEED)
    out = {"n_candidates": {r: sum(1 for x in cands if x["rule"] == r) for r in PRIMARY}, "features": list(FEATURES), "results": {}}
    for side, name in ((1, "long"), (-1, "short")):
        for kind in ("logit", "hgb"):
            w = walk(cands, side, kind)
            j = judge(w, rng)
            j["coefs_last_fold"] = w["coefs_last_fold"]
            out["results"][f"{name}|{kind}"] = j
    out["n_holds"] = sum(1 for v in out["results"].values() if v.get("holds"))
    return out


# ── 装载 ──────────────────────────────────────────────────────────────────────

def load_live() -> tuple:
    bars, _ = R.load_live()
    fund = {}
    for coin in bars:
        rows = S.get("funding_daily", {"select": "d,funding_rate", "symbol": f"eq.{coin}", "order": "d.asc"})
        days = [S.D(r["d"]) for r in rows if r.get("funding_rate") is not None]
        rates = [float(r["funding_rate"]) for r in rows if r.get("funding_rate") is not None]
        f7 = [float(np.mean(rates[max(0, i - 6):i + 1])) * 3 * 365 for i in range(len(rates))]
        fund[coin] = (days, f7)
    mrows = S.get("feature_matrix_daily", {"select": "d,f", "d": "gte.2017-01-01", "order": "d.asc"})
    market = {S.D(r["d"]): {k: (r.get("f") or {}).get(k) for k in MARKET_KEYS} for r in mrows}
    jrows = S.get("joint_forecast_daily", {"select": "d,z", "order": "d.asc"})
    jz = ([S.D(r["d"]) for r in jrows if r.get("z") is not None], [float(r["z"]) for r in jrows if r.get("z") is not None])
    print("loaded funding", {k: len(v[0]) for k, v in fund.items()}, "market", len(market), "joint_z", len(jz[0]), flush=True)
    return bars, fund, market, jz


def synthetic() -> tuple:
    bars, _ = R.synthetic()
    rng = np.random.default_rng(SEED)
    d0, fund, market = dt.date(2019, 1, 1), {}, {}
    days = [d0 + dt.timedelta(days=i) for i in range(365 * 6)]
    for coin in bars:
        fund[coin] = (days, list(rng.normal(0.05, 0.1, len(days))))
    for d in days:
        market[d] = {k: float(rng.normal()) for k in MARKET_KEYS}
    jz = (days[1200:], list(rng.normal(size=len(days) - 1200)))
    return bars, fund, market, jz


if __name__ == "__main__":
    selftest = "--selftest" in sys.argv
    if selftest:
        N_PERM = 30
    bars, fund, market, jz = synthetic() if selftest else load_live()
    cands = candidates(bars, fund, market, jz)
    out = run(cands)
    print("COUNTS", json.dumps({"n_candidates": out["n_candidates"], "n_holds": out["n_holds"]}, ensure_ascii=False), flush=True)
    for k, v in out["results"].items():
        print("RESULT", k, "| pooled", json.dumps(v.get("pooled"), ensure_ascii=False), "| crit", json.dumps(v.get("criteria")),
              "| HOLDS" if v.get("holds") else "", flush=True)
        print("YEARS", k, json.dumps(v["per_year"], ensure_ascii=False), flush=True)
        if v.get("coefs_last_fold"):
            top = sorted(v["coefs_last_fold"].items(), key=lambda kv: -abs(kv[1]))[:8]
            print("COEFS", k, json.dumps(top, ensure_ascii=False), flush=True)
    if selftest:
        # 特征不用之后的数据:截短序列,同一张票的特征相同
        b = bars["AAA"]
        cut = len(b["c"]) // 2
        bc = {k: v[:cut] for k, v in b.items()}
        full = {(x["t"], x["rule"]): x for x in candidates({"AAA": b}, fund, market, jz)}
        part = [x for x in candidates({"AAA": bc}, fund, market, jz) if x["t"] < b["t"][cut - 200]]
        assert part and all(all((np.isnan(x[q]) and np.isnan(full[(x["t"], x["rule"])][q])) or x[q] == full[(x["t"], x["rule"])][q]
                                for q in FEATURES) for x in part), "特征用到了之后的数据"
        # 隔离带:训练的平仓时间都早于测试年开始 − 30 天
        rows = sorted([x for x in cands if x["side"] == 1], key=lambda x: x["t"])
        start = dt.datetime(2023, 1, 1, tzinfo=dt.timezone.utc)
        assert all(x["exit_t"] < start - EMBARGO for x in rows if x["exit_t"] < start - EMBARGO)
        assert auc(np.array([0, 0, 1, 1]), np.array([0.1, 0.2, 0.3, 0.4])) == 1.0 and auc(np.array([1, 0]), np.array([0.5, 0.5])) == 0.5
        assert list(terciles(np.array([0.1, 0.9, 0.5, 0.2, 0.8, 0.3]))) == [0, 2, 1, 0, 2, 1]
        assert set(out["results"]) == {"long|logit", "long|hgb", "short|logit", "short|hgb"}
        print("SELFTEST OK")
    else:
        json.dump(out, open(OUT, "w"), ensure_ascii=False, indent=1, default=str)
        print("WROTE", OUT)
