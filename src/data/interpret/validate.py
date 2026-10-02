"""T-041 / M-196 —— 解读层的预注册检验。判据见台账 M-196(B 写,先于本代码);这里只实现,不改判据。

**实现细节(跑之前写死,M-196 没有写到的地方由 Seth 定,不看结果再改):**
- 被检验的分布 = `pooled`(全部可用角度的相似日合在一起);各角度单独的结果另报,不参与裁决。
- 目标 = 六个「风格相对大币」的 30 天收益差(M-196 §6 第 1 条优先看相对收益)。
- 无条件对照 B:对测试日 t,取 t − 30 天及以前**全部**日子的同一指标的 30 天收益差(只用过去)。
- 每个测试日一个配对观察:六个价差 × 三个分位(p25/p50/p75)的分位数损失平均。
- 显著性:30 天块 bootstrap(10,000 次),单侧;p = 重抽样中位数 ≥ 0 的比例。
- 裁决在**样本外(2024-01 起)**;样本内 2023 一并报告。
- 随机基线:每个测试日,每个可用角度从同样的候选池(早于 t − 30 天、在该空间有数据的日子)随机抽与真实同样多的日子。
- T4 方向:A 用 pooled 中位数的符号,B 用无条件中位数的符号;分歧日 = |ΔQL| 前 1/3。
"""
from __future__ import annotations

from typing import Any, Mapping, Optional

import numpy as np
import pandas as pd

#: M-196 §6 第 1 条列出的六个价差(不含 top_l1,预注册没有它)
SPREADS = ("second_l1_l2-majors", "app-majors", "ai-majors", "meme-majors",
           "defi-majors", "infra_tokenization-majors")
QUANTS = ((0.25, "p25"), (0.5, "median"), (0.75, "p75"))
OOS_START = pd.Timestamp("2024-01-01")
SI = (pd.Timestamp("2023-01-01"), pd.Timestamp("2023-12-31"))
BLOCK = 30
N_BOOT = 10_000


def pinball(y: float, q: float, alpha: float) -> float:
    return (1 - alpha) * (q - y) if y < q else alpha * (y - q)


def mean_qloss(dist: Mapping[str, Mapping[str, float]], actual: Mapping[str, float]) -> Optional[float]:
    """一个测试日:各价差 × 三个分位的分位数损失平均。共同键不足 3 个 ⇒ None。"""
    vals = []
    for k in SPREADS:
        if k in dist and k in actual and actual[k] is not None:
            for a, name in QUANTS:
                vals.append(pinball(float(actual[k]), float(dist[k][name]), a))
    return float(np.mean(vals)) if len(vals) >= 9 else None


def unconditional(forward: pd.DataFrame, t: pd.Timestamp, horizon: int = 30) -> dict[str, dict[str, float]]:
    """t − horizon 天及以前全部日子的前向价差分布(只用过去)。`forward`:行 = 起始日,列 = 价差。"""
    past = forward[forward.index <= t - pd.Timedelta(days=horizon)]
    out = {}
    for k in past.columns:
        v = past[k].dropna().to_numpy()
        if len(v) >= 30:
            out[k] = {"p25": float(np.percentile(v, 25)), "median": float(np.median(v)),
                      "p75": float(np.percentile(v, 75)), "p_up": float((v > 0).mean())}
    return out


def block_bootstrap_p(x: np.ndarray, block: int = BLOCK, n: int = N_BOOT, seed: int = 0) -> float:
    """单侧 p:块 bootstrap 重抽样的中位数 ≥ 0 的比例(H1:中位数 < 0)。"""
    x = np.asarray(x, dtype=float)
    x = x[~np.isnan(x)]
    if len(x) < block:
        return float("nan")
    rng = np.random.default_rng(seed)
    nb = int(np.ceil(len(x) / block))
    starts = rng.integers(0, len(x) - block + 1, size=(n, nb))
    idx = (starts[:, :, None] + np.arange(block)[None, None, :]).reshape(n, -1)[:, :len(x)]
    return float((np.median(x[idx], axis=1) >= 0).mean())


def ece(p: np.ndarray, hit: np.ndarray, bins: int = 10) -> float:
    p, hit = np.asarray(p, float), np.asarray(hit, float)
    edges = np.linspace(0, 1, bins + 1)
    tot, err = len(p), 0.0
    for i in range(bins):
        m = (p >= edges[i]) & ((p < edges[i + 1]) if i < bins - 1 else (p <= edges[i + 1]))
        if m.any():
            err += m.sum() / tot * abs(p[m].mean() - hit[m].mean())
    return float(err)


def evaluate(days: list[dict], *, label: str) -> dict[str, Any]:
    """`days`:每个测试日一条 {d, A: 分布, B: 分布, R: 随机基线分布(可无), actual: 价差实际值}。"""
    rows = []
    for x in days:
        qa, qb = mean_qloss(x["A"], x["actual"]), mean_qloss(x["B"], x["actual"])
        if qa is None or qb is None:
            continue
        qr = mean_qloss(x["R"], x["actual"]) if x.get("R") else None
        keys = [k for k in SPREADS if k in x["A"] and k in x["B"] and k in x["actual"]]
        rows.append({"d": x["d"], "dq": qa - qb, "dq_rand": (qr - qb) if qr is not None else np.nan,
                     "pa": [x["A"][k]["p_up"] for k in keys], "pb": [x["B"][k]["p_up"] for k in keys],
                     "hit": [float(x["actual"][k] > 0) for k in keys],
                     "in_a": [float(x["actual"][k] >= x["A"][k]["p25"] and x["actual"][k] <= x["A"][k]["p75"]) for k in keys],
                     "in_b": [float(x["actual"][k] >= x["B"][k]["p25"] and x["actual"][k] <= x["B"][k]["p75"]) for k in keys],
                     "dir_a": [float(np.sign(x["A"][k]["median"]) == np.sign(x["actual"][k])) for k in keys],
                     "dir_b": [float(np.sign(x["B"][k]["median"]) == np.sign(x["actual"][k])) for k in keys]})
    if len(rows) < BLOCK:
        return {"label": label, "n_days": len(rows), "overall": "INCONCLUSIVE", "why": "测试日不足一个块长"}
    df = pd.DataFrame(rows)
    dq = df["dq"].to_numpy()
    t1_p = block_bootstrap_p(dq)
    t1 = bool(np.median(dq) < 0 and t1_p < 0.05)
    flat = lambda col: np.concatenate(df[col].to_numpy())
    ece_a, ece_b = ece(flat("pa"), flat("hit")), ece(flat("pb"), flat("hit"))
    cov_a, cov_b = abs(0.5 - flat("in_a").mean()), abs(0.5 - flat("in_b").mean())
    rng = np.random.default_rng(1)
    boot_e, boot_c = [], []
    n = len(df)
    for _ in range(2000):                       # T2/T3 的差值区间:按天的块 bootstrap
        nb = int(np.ceil(n / BLOCK))
        st = rng.integers(0, n - BLOCK + 1, size=nb)
        ix = np.concatenate([np.arange(s, s + BLOCK) for s in st])[:n]
        sub = df.iloc[ix]
        fa = lambda c: np.concatenate(sub[c].to_numpy())
        boot_e.append(ece(fa("pb"), fa("hit")) - ece(fa("pa"), fa("hit")))
        boot_c.append(abs(0.5 - fa("in_b").mean()) - abs(0.5 - fa("in_a").mean()))
    ce, cc = np.percentile(boot_e, [2.5, 97.5]), np.percentile(boot_c, [2.5, 97.5])
    t2 = bool(ece_a < ece_b and ce[0] > 0)
    t3 = bool(cov_a < cov_b and cc[0] > 0)
    third = df["dq"].abs() >= df["dq"].abs().quantile(2 / 3)
    hit_a = float(np.concatenate(df.loc[third, "dir_a"].to_numpy()).mean())
    hit_b = float(np.concatenate(df.loc[third, "dir_b"].to_numpy()).mean())
    t4 = bool(hit_a > hit_b + 0.10)
    dr = (df["dq"] - df["dq_rand"]).to_numpy()
    rb_p = block_bootstrap_p(dr) if np.isfinite(dr).sum() >= BLOCK else float("nan")
    rb = bool(np.isfinite(rb_p) and np.nanmedian(df["dq"]) < np.nanmedian(df["dq_rand"]) and rb_p < 0.05)
    tests = {"t1_quantile_loss": t1, "t2_calibration": t2, "t3_coverage": t3,
             "t4_discrimination": t4, "random_baseline": rb}
    return {"label": label, "n_days": n, "n_independent_windows": n // BLOCK,
            "t1": {"median_dq": float(np.median(dq)), "p": t1_p, "pass": t1},
            "t2": {"ece_a": ece_a, "ece_b": ece_b, "ci_b_minus_a": [float(ce[0]), float(ce[1])], "pass": t2},
            "t3": {"cov_err_a": cov_a, "cov_err_b": cov_b, "ci_b_minus_a": [float(cc[0]), float(cc[1])], "pass": t3},
            "t4": {"hit_a": hit_a, "hit_b": hit_b, "pass": t4},
            "random": {"median_dq_real": float(np.nanmedian(df["dq"])),
                       "median_dq_rand": float(np.nanmedian(df["dq_rand"])), "p": rb_p, "pass": rb},
            "overall": "PASS" if all(tests.values()) else "FAIL"}


# ── 运行(Railway 上跑:需要风格指数与相似度空间)────────────────────────────

async def run(seed: int = 7) -> dict[str, Any]:
    """按 M-196 回放 2023-01 起每一天,算 A / B / 随机基线,分样本内、样本外裁决,结果落 `interpretation_validation_runs`。"""
    import asyncio
    from datetime import datetime, timezone
    from src.api.store import supabase_insert_table
    from src.data.interpret import interpret as it

    lv, spaces = await it._load()
    last = lv["majors"].last_valid_index()
    fwd = pd.DataFrame({d: it.forward_returns(lv, d) for d in lv.index}).T
    fwd = fwd[[c for c in SPREADS if c in fwd.columns]]
    rng = np.random.default_rng(seed)

    def one(d):
        a = it.interpret_day(d, lv, spaces, {})
        actual = {k: v for k, v in (a["realized"] or {}).items() if k in SPREADS}
        if not actual:
            return None
        rand_fw = []
        for ang, body in a["angles"].items():
            n = len(body["analogs"])
            if not n:
                continue
            pool = spaces[ang].dropna(how="all")
            pool = pool.index[pool.index <= d - pd.Timedelta(days=it.MIN_GAP_DAYS)]
            for x in rng.choice(pool, size=min(n, len(pool)), replace=False):
                rand_fw.append(it.forward_returns(lv, pd.Timestamp(x)))
        per_angle = {ang: body["fwd"] for ang, body in a["angles"].items() if body["analogs"]}
        return {"d": d, "A": a["pooled"], "B": unconditional(fwd, d), "R": it.summarize(rand_fw),
                "actual": actual, "per_angle": per_angle}

    days = pd.date_range(SI[0], last - pd.Timedelta(days=30), freq="D")
    recs = [r for r in await asyncio.to_thread(lambda: [one(d) for d in days]) if r]
    si = [r for r in recs if SI[0] <= r["d"] <= SI[1]]
    oos = [r for r in recs if r["d"] >= OOS_START]
    res = {"prereg": "M-196", "interpret_code_ref": it.CODE_REF,
           "in_sample_2023": evaluate(si, label="SI 2023"),
           "out_of_sample_2024+": evaluate(oos, label="OOS 2024+"),
           "by_angle_oos": {ang: evaluate([{**r, "A": r["per_angle"][ang], "R": None} for r in oos
                                           if ang in r["per_angle"]], label=f"OOS · 只用 {ang}")
                            for ang in ("style", "macro", "micro")}}
    res["verdict"] = res["out_of_sample_2024+"]["overall"]
    # S-462:结果里有 NaN(某个角度没有随机基线时的 p 值等)—— JSON 不收 NaN,首两次运行算出了 FAIL 却一行都没写进去。
    from src.api.store import sanitize_floats
    res = sanitize_floats(res)
    row = {"run_at": datetime.now(timezone.utc).isoformat(), "prereg": "M-196",
           "code_ref": it.CODE_REF, "verdict": res["verdict"], "result": res}
    w = await supabase_insert_table("interpretation_validation_runs", [row])
    res["written"] = bool(w.ok)
    res["write_error"] = None if w.ok else str(getattr(w, "why", ""))[:300]
    return res
