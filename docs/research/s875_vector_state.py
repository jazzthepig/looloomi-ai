"""S-875:把「状态」换成矢量库里的那条融合向量 —— 今天最像历史上的哪些日子,那些日子之后 60 天哪些策略有超额,就拿哪些。

Jazz 2026-11-15:「你的模拟有走我们的矢量数据库吗?」—— 没有。S-869 – S-874 的状态是手挑的四个标量轴(其中两个进了组合)。
他说的「特定矢量下」本来就是向量空间里的邻域。这里用**生产的那条向量**(`src/data/state/fused_knn.py`:56 个冻结的键、
按时点标准化、同一个距离函数),不另造一条。预期、判据与后果写在台账 S-875(先登记,后计算)。只描述 + 一本纸面账的候选配方。

每月第一天 m(只用当时已经知道的):
  今天的向量 = m 之前最后一个有向量的日子 D;邻居 = D − 61 天及以前、距离最近的 K = 150 天(它们之后 60 天的结果在 m 之前都已发生);
  邻居按间隔 ≤ 5 天并成段;每条策略在每一段上取「之后 60 天累计超额」的段内平均,得到 E_1 … E_n;
  长处(与 S-871 的 v2 同构):n ≥ 5 段;均值 > 0 且 年化的 均值 / 波动 ≥ 0.5;盈亏比 ≥ 2;去掉最好一段仍 > 0;均值 > 该策略在全部可用历史日上的均值。
  当月持有判为长处的策略,等风险(与 S-869 同一套缩放,上限 3 倍);没有就拿现金。
对照:同期的 T × L 版(S-871)、全拿(B0)、只拿无条件好的(B1);
安慰剂:邻居换成「同样段数、同样段长、位置随机」的历史日(200 次)—— 分开「向量邻域有信息」与「随便拿一批聚成段的历史日也能挑出东西」。

用法(仓库根目录;取数与 s851 同一个 get()):
    python3 docs/research/s875_vector_state.py --selftest
    python3 docs/research/s875_vector_state.py            # 写 docs/research/s875_results.json
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
_argv, sys.argv = sys.argv, [sys.argv[0], "--rules", "v2"]
_sp = importlib.util.spec_from_file_location("s869", os.path.join(HERE, "s869_strategy_state.py"))
M = importlib.util.module_from_spec(_sp)
_sp.loader.exec_module(M)
sys.argv = _argv
_fp = importlib.util.spec_from_file_location("fused_knn", os.path.join(ROOT, "src", "data", "state", "fused_knn.py"))
FK = importlib.util.module_from_spec(_fp)
_fp.loader.exec_module(FK)

OUT = "docs/research/s875_results.json"
K, EXCL, H, GAP, N_PLACEBO, SEED = 150, 61, 60, 5, 200, 875
MIN_EP, MIN_RATIO, MIN_PAYOFF, MIN_VEC_HISTORY = 5, 0.5, 2.0, 730
NDIM = len(FK.KEYS)


def to_matrix(vecs: dict) -> tuple[list, np.ndarray]:
    ds = sorted(vecs)
    return ds, np.array([[np.nan if x is None else float(x) for x in vecs[d]] for d in ds])


def dists(a: np.ndarray, B: np.ndarray) -> np.ndarray:
    """与 fused_knn.distance 同一个定义的向量化写法:两边都有值的维度上的欧氏距离 × √(维数 / 重合);重合不足 ⇒ inf。"""
    both = ~np.isnan(a)[None, :] & ~np.isnan(B)
    n = both.sum(1)
    d2 = np.where(both, (np.nan_to_num(B) - np.nan_to_num(a)[None, :]) ** 2, 0.0).sum(1)
    out = np.sqrt(d2 * NDIM / np.maximum(n, 1))
    out[n < FK.MIN_OVERLAP * NDIM] = np.inf
    return out


def neighbours(ds: list, X: np.ndarray, i: int) -> list[int]:
    """第 i 天的邻居(下标):日期 ≤ ds[i] − EXCL 天,距离最近的 K 个。"""
    lim = ds[i] - dt.timedelta(days=EXCL)
    hi = int(np.searchsorted(np.array([d.toordinal() for d in ds]), lim.toordinal(), side="right"))
    if hi < K:
        return []
    dd = dists(X[i], X[:hi])
    order = np.argsort(dd, kind="stable")[:K]
    return sorted(int(j) for j in order if np.isfinite(dd[j]))


def blocks(idx: list[int], ds: list) -> list[list[int]]:
    out, cur = [], []
    for j in idx:
        if cur and (ds[j] - ds[cur[-1]]).days > GAP:
            out.append(cur)
            cur = []
        cur.append(j)
    return out + ([cur] if cur else [])


def forward(rets: dict) -> dict:
    """D → D + 1 … D + H 的累计超额(H 天都要有)。"""
    days = sorted(rets)
    if not days:
        return {}
    cs = np.concatenate([[0.0], np.cumsum(np.log1p(np.array([rets[d] for d in days])))])
    pos = {d: i for i, d in enumerate(days)}
    one = dt.timedelta(days=1)
    out = {}
    for d in [days[0] - one] + days:
        a, b = pos.get(d + one), pos.get(d + dt.timedelta(days=H))
        if a is not None and b is not None and b - a == H - 1:
            out[d] = float(np.exp(cs[b + 1] - cs[a]) - 1)
    return out


def is_strength(E: np.ndarray, base_mean: float) -> bool:
    if len(E) < MIN_EP or E.mean() <= 0 or E.std() <= 0:
        return False
    if E.mean() / E.std() * np.sqrt(M.ANN / H) < MIN_RATIO or M.payoff_ratio(E) < MIN_PAYOFF:
        return False
    return bool(np.delete(E, int(np.argmax(E))).mean() > 0 and E.mean() > base_mean)


def walk(ds: list, X: np.ndarray, fwd: dict, scaled: dict, picker=None, detail: bool = False) -> dict:
    """picker(i, real_blocks) → 段的列表(每段是下标列表);None ⇒ 真邻居。"""
    one = dt.timedelta(days=1)
    ordn = np.array([d.toordinal() for d in ds])
    months = [d for k, d in enumerate(ds) if (k == 0 or d.month != ds[k - 1].month) and (d - ds[0]).days >= MIN_VEC_HISTORY]
    port, sel, info = {}, {}, {}
    for mi, m in enumerate(months):
        i = int(np.searchsorted(ordn, m.toordinal())) - 1               # m 之前最后一个有向量的日子
        if i < 0:
            continue
        real = blocks(neighbours(ds, X, i), ds)
        eps = real if picker is None else picker(i, real)
        lim = ds[i] - dt.timedelta(days=EXCL)
        picks = []
        for k, f in fwd.items():
            E = np.array([np.mean([f[ds[j]] for j in b if ds[j] in f]) for b in eps if any(ds[j] in f for j in b)])
            past = [v for d, v in f.items() if d <= lim]
            if len(past) >= 365 and is_strength(E, float(np.mean(past))):
                picks.append(k)
        sel[m.isoformat()] = sorted(picks)
        if detail:
            yrs = {}
            for b in real:
                yrs[str(ds[b[0]].year)] = yrs.get(str(ds[b[0]].year), 0) + len(b)
            info[m.isoformat()] = {"asof": ds[i].isoformat(), "n_neighbours": sum(len(b) for b in real), "n_blocks": len(real), "days_by_year": yrs}
        end = months[mi + 1] if mi + 1 < len(months) else ds[-1] + one + one
        d = m
        while d < end:
            rs = [scaled[k][d] for k in picks if d in scaled[k]]
            port[d] = float(np.mean(rs)) if rs else 0.0
            d += one
    return {"series": port, "selection": sel, "info": info}


def random_picker(ds: list, rng):
    def pick(i, real):
        lim = ds[i] - dt.timedelta(days=EXCL)
        hi = int(np.searchsorted(np.array([d.toordinal() for d in ds]), lim.toordinal(), side="right"))
        out = []
        for b in real:
            if hi - len(b) <= 0:
                continue
            s = int(rng.integers(0, hi - len(b) + 1))
            out.append(list(range(s, s + len(b))))
        return out
    return pick


def run(vecs: dict, states: dict | None, panel: dict, n_placebo: int = N_PLACEBO) -> dict:
    ds, X = to_matrix(vecs)
    scaled = M._scaled(panel)
    fwd = {k: forward(r) for k, r in panel.items()}
    real = walk(ds, X, fwd, scaled, detail=True)
    days = sorted(real["series"])
    out = {"knn": {"perf": M.perf(real["series"]), "last_selection": real["selection"][max(real["selection"])] if real["selection"] else [],
                   "last_info": real["info"][max(real["info"])] if real["info"] else {}}}
    yr = {}
    for d in days:
        yr.setdefault(str(d.year), []).append(real["series"][d])
    out["knn"]["yearly"] = {y: round(float(np.prod(1 + np.array(v)) - 1), 4) for y, v in yr.items()}
    out["knn"]["n_picks_by_month"] = {m: len(v) for m, v in real["selection"].items()}
    sub = lambda s: {d: s[d] for d in days if d in s}                      # noqa: E731 —— 对照都截到同一段日子
    b0 = {d: (float(np.mean([scaled[k][d] for k in panel if d in scaled[k]])) if any(d in scaled[k] for k in panel) else 0.0) for d in days}
    out["B0_all_equal_risk"] = {"perf": M.perf(b0)}
    if states is not None:
        tb = M.month_tables(states, panel)
        out["TxL_v2_same_window"] = {"perf": M.perf(sub(M.walk(states, tb, scaled, M.G2, "cond")["series"]))}
        out["B1_good_unconditional_same_window"] = {"perf": M.perf(sub(M.walk(states, tb, scaled, M.G2, "uncond")["series"]))}
    rng = np.random.default_rng(SEED)
    ratios = np.array([M.perf(walk(ds, X, fwd, scaled, picker=random_picker(ds, rng))["series"]).get("ratio", 0.0) for _ in range(n_placebo)])
    r = out["knn"]["perf"].get("ratio", 0.0)
    out["knn"]["placebo"] = {"n": int(n_placebo), "ratio_median": round(float(np.median(ratios)), 3), "ratio_q90": round(float(np.quantile(ratios, 0.9)), 3),
                             "percentile_of_real_ratio": round(float((ratios < r).mean()), 3)}
    out["meta"] = {"n_vector_days": len(ds), "first": ds[0].isoformat(), "last": ds[-1].isoformat(), "n_strategies": len(panel),
                   "K": K, "exclude_days": EXCL, "horizon_d": H, "dims": NDIM}
    return out


def load_vectors_live() -> dict:
    rows = M_get("feature_matrix_daily", {"select": "d,f", "d": "gte.2019-01-01", "order": "d.asc"})
    return {dt.date.fromisoformat(k): v for k, v in FK.pit_vectors(rows).items()}


def M_get(path: str, params: dict) -> list:
    sp = importlib.util.spec_from_file_location("s851", os.path.join(HERE, "s851_watch_base_rate.py"))
    S = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(S)
    return S.get(path, params)


def synthetic():
    """合成:前 12 维带着一个持续几十天的状态,其余是噪声;两条策略各在一种状态下之后 60 天有超额。"""
    rng = np.random.default_rng(SEED)
    days = [dt.date(2019, 1, 1) + dt.timedelta(days=i) for i in range(2500)]
    reg, cur = [], 0
    for _ in days:
        cur = 1 - cur if rng.random() < 1 / 80 else cur
        reg.append(cur)
    vecs = {d: [float((1.5 if reg[i] else -1.5) + rng.normal(0, 0.5)) if j < 12 else float(rng.normal(0, 1.0)) for j in range(NDIM)] for i, d in enumerate(days)}
    panel = {k: {} for k in ("works_in_1", "works_in_0", "noise", "always_down")}
    for i, d in enumerate(days[1:], start=1):
        r = reg[i - 1]
        panel["works_in_1"][d] = float(rng.normal(0.004 if r else -0.001, 0.02))
        panel["works_in_0"][d] = float(rng.normal(-0.001 if r else 0.004, 0.02))
        panel["noise"][d] = float(rng.normal(0.0, 0.02))
        panel["always_down"][d] = float(rng.normal(-0.003, 0.02))
    return vecs, panel


if __name__ == "__main__":
    selftest = "--selftest" in sys.argv
    if selftest:
        vecs, panel = synthetic()
        states = None
    else:
        vecs = load_vectors_live()
        states = M.load_states()
        panel, _ = M.load_panel()
    out = run(vecs, states, panel, n_placebo=(20 if selftest else N_PLACEBO))
    for k in ("meta", "knn", "TxL_v2_same_window", "B0_all_equal_risk", "B1_good_unconditional_same_window"):
        if k in out:
            v = {kk: vv for kk, vv in out[k].items() if kk != "n_picks_by_month"} if isinstance(out[k], dict) else out[k]
            print(k.upper(), json.dumps(v, ensure_ascii=False), flush=True)
    if selftest:
        ds, X = to_matrix(vecs)
        a, b = vecs[ds[900]], vecs[ds[300]]
        a2 = [None if j % 7 == 0 else x for j, x in enumerate(a)]
        for u, w in ((a, b), (a2, b)):
            ref = FK.distance(u, w)
            got = float(dists(np.array([np.nan if x is None else x for x in u]), np.array([[np.nan if x is None else x for x in w]]))[0])
            assert ref is not None and abs(ref - got) < 1e-9, (ref, got)
        nb = neighbours(ds, X, 2000)
        assert len(nb) == K and max(ds[j] for j in nb) <= ds[2000] - dt.timedelta(days=EXCL), "邻居里混进了结果还没出来的日子"
        assert out["knn"]["perf"]["ratio"] > out["B0_all_equal_risk"]["perf"]["ratio"] and out["knn"]["placebo"]["percentile_of_real_ratio"] >= 0.9, out["knn"]
        # 不偷看:某天之后的收益全部反号,那天之前各月的名单不许变
        cut = ds[1600]
        p2 = {k: {d: (v if d <= cut else -v) for d, v in r.items()} for k, r in panel.items()}
        s1 = walk(ds, X, {k: forward(r) for k, r in panel.items()}, M._scaled(panel))["selection"]
        s2 = walk(ds, X, {k: forward(r) for k, r in p2.items()}, M._scaled(p2))["selection"]
        early = [m for m in s1 if dt.date.fromisoformat(m) <= cut]
        assert early and all(s1[m] == s2[m] for m in early), "月初的名单用到了之后的收益"
        print("SELFTEST OK")
    else:
        json.dump(out, open(OUT, "w"), ensure_ascii=False, indent=1)
        print("WROTE", OUT)
