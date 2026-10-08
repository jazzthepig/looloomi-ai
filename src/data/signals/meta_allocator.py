"""类比元配置 —— 按当下状态去历史里找相似日,看策略库里每个策略之后表现,每周重配(T-075 / S-521)。

## 为什么

到 10-08 为止每条规则都是手写阈值;设计里的智能是「策略库 × 状态」:按当下的状态去库里匹配,谁在相似的过去
有效就配谁,每天用新结果修正。这里把它做成按时点、可证伪的版本 —— 机器自己选,人只定菜单与对照。

## 预注册(2026-10-08,写代码之前;常数不调,改 = 新起点)

    策略库   core_variants_daily 全部臂 + ④(research/series/strategy4_blend_daily.json)+ 现金 4%
    状态     STATE_FEATURES(10 维,2023-01 起都有值),每维按截至当天的扩张窗口 z 分数
    匹配     每周一 d:用 d−1 的状态;候选日 t 须满足 t + H ≤ d − 1(结果在 d 之前完全已知);欧氏最近 K 个
    决策     每个策略在 K 个相似日之后 H 天的平均收益;取最高 2 个各半;最高者不如现金 ⇒ 全现金;
             相似日不足 K ⇒ 全现金(不猜);切换 10 bps × 换手(现金腿不计)
    对照     BTC · 全库等权 · 随机挑 2 个(同周频,500 次)分位 · 事后最好的单一策略(参照,不可实现)
             · **状态打乱**(同一规则,状态按 30 天一块打乱 100 次)的分位 —— 主判据;随机挑 2 个会被「能去现金」骗
    窗口     2023-07 → 2024-12 学习期 / 2025-01-01 → 起点 / 起点后前向

## 偏差

菜单里的臂是看过 2023–26 才设计的 —— 元配置不知道未来,但菜单是看过未来的人列的。前向才是检验。

## 判活判据(规则 5b ②)

    select max(d) from meta_allocator_daily where arm = 'meta_knn';   -- = 昨天(UTC)
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Optional

import numpy as np
import pandas as pd

TABLE = "meta_allocator_daily"
WRITES_TABLES = (TABLE,)
ARM = "meta_knn"
STATE_FEATURES = ("dist_200", "vol_pct_3y", "mom_20", "mom_60", "breadth_above_ma50", "style_rel_majors_30d",
                  "vratio_30_180", "taker_buy_share_30d", "spy_ret_21", "stable_supply_30d")
H, K, TOP = 14, 40, 2
CASH_ANN = 0.04
COST_BPS = 10.0
START = pd.Timestamp("2023-07-03")
HOLDOUT_START = pd.Timestamp("2025-01-01")
INCEPTION = pd.Timestamp("2026-10-08")
N_RANDOM, SEED = 500, 521
N_SHUFFLE, BLOCK = 100, 30
CODE_REF = "T-075 meta knn v1"
CASH = "cash"


def expanding_z(state: pd.DataFrame) -> pd.DataFrame:
    """纯函数。每维用截至当天(含)的扩张窗口均值 / 标准差;前 60 天不给值。"""
    mu = state.expanding(min_periods=60).mean()
    sd = state.expanding(min_periods=60).std()
    return (state - mu) / sd.replace(0, np.nan)


def forward_sums(arm_rets: pd.DataFrame, h: int = H) -> pd.DataFrame:
    """纯函数。t 行 = 策略在 t+1 … t+h 的复利收益(t 之后的 h 天)。末尾不足 h 天 ⇒ NaN。"""
    lr = np.log1p(arm_rets)
    fwd = lr[::-1].rolling(h, min_periods=h).sum()[::-1].shift(-1)
    return np.expm1(fwd)


def decide(d: pd.Timestamp, z: pd.DataFrame, fwd: pd.DataFrame, arms: list) -> tuple[dict, dict]:
    """纯函数。返回 (目标权重, 说明)。只用 d−1 的状态与「t + H ≤ d − 1」的相似日。"""
    y = d - pd.Timedelta(days=1)
    if y not in z.index or z.loc[y].isna().any():
        return {CASH: 1.0}, {"why": "当天状态不全"}
    hist = z.loc[(z.index <= d - pd.Timedelta(days=H + 1))].dropna()
    hist = hist[hist.index.isin(fwd.dropna(how="all").index)]
    if len(hist) < K:
        return {CASH: 1.0}, {"why": f"相似日候选只有 {len(hist)} 个 < {K}"}
    dist = np.sqrt(((hist - z.loc[y]) ** 2).sum(axis=1))
    near = dist.nsmallest(K).index
    score = fwd.loc[near, arms].mean(skipna=True).dropna().sort_values(ascending=False)
    cash_h = (1 + CASH_ANN / 365) ** H - 1
    if score.empty or score.iloc[0] <= cash_h:
        return {CASH: 1.0}, {"why": "相似日里没有策略跑赢现金", "top": score.head(3).round(4).to_dict()}
    picks = [a for a in score.index[:TOP] if score[a] > cash_h]
    return {a: 1.0 / len(picks) for a in picks}, {"top": score.head(4).round(4).to_dict(),
                                                    "nearest": [t.date().isoformat() for t in near[:5]]}


def simulate(rets: pd.DataFrame, targets: dict) -> pd.Series:
    """纯函数。每周的目标权重持有到下一次;策略之间不漂移(每个策略自己的净值已含其内部再平衡);
    切换付 COST_BPS × 非现金腿的换手。"""
    cols = list(rets.columns)
    r = rets.fillna(0.0).to_numpy()
    w = np.zeros(len(cols))
    risky = np.array([c != CASH for c in cols], dtype=float)
    out = np.zeros(len(rets))
    for i, d in enumerate(rets.index):
        cost = 0.0
        if d in targets:
            new = np.array([targets[d].get(c, 0.0) for c in cols])
            cost = float((np.abs(new - w) * risky).sum()) * COST_BPS / 1e4
            w = new
        out[i] = float(w @ r[i]) - cost
    return pd.Series(out, index=rets.index)


def _stats(x: pd.Series) -> dict[str, Optional[float]]:
    if len(x) < 2:
        return {"n": len(x), "total": None, "maxdd": None, "sharpe": None}
    nav = (1 + x).cumprod()
    sd = float(x.std())
    return {"n": int(len(x)), "total": round(float(nav.iloc[-1] - 1), 5),
            "maxdd": round(float((nav / nav.cummax() - 1).min()), 5),
            "sharpe": round(float(x.mean() / sd * math.sqrt(365)), 3) if sd > 0 else None}


def build(arm_rets: pd.DataFrame, state: pd.DataFrame, end: pd.Timestamp,
          n_random: int = N_RANDOM, n_shuffle: int = N_SHUFFLE) -> tuple[list[dict], dict[str, Any]]:
    """纯函数。arm_rets:行 = 日,列 = 策略(不含现金);state:行 = 日,列 = STATE_FEATURES。"""
    arm_rets = arm_rets.sort_index()
    arms = list(arm_rets.columns)
    rets = arm_rets.assign(**{CASH: CASH_ANN / 365.0})
    rets = rets.loc[(rets.index >= START) & (rets.index <= end)]
    z = expanding_z(state.reindex(columns=list(STATE_FEATURES)).sort_index())
    fwd = forward_sums(arm_rets)
    days = list(rets.index)
    mondays = [d for d in days if d.weekday() == 0]
    targets, notes = {}, {}
    for d in mondays:
        targets[d], notes[d] = decide(d, z, fwd, arms)
    meta = simulate(rets, targets)
    # 更硬的对照(写进 S-521 的补充,看结果之前):同一规则,但状态按 30 天一块打乱 —— 相似日变成随机日。
    # 随机挑 2 个永远满仓,而元配置可以去现金;在全都不赚钱的世界里光是「会去现金」就能赢随机 —— 那不是会挑。
    shuf = np.zeros((n_shuffle, len(rets)))
    zi = z.index
    blocks = [zi[i:i + BLOCK] for i in range(0, len(zi), BLOCK)]
    rng0 = np.random.default_rng(SEED + 1)
    for k in range(n_shuffle):
        order = rng0.permutation(len(blocks))
        new_vals = np.concatenate([z.loc[blocks[j]].to_numpy() for j in order])[:len(zi)]
        zk = pd.DataFrame(new_vals, index=zi, columns=z.columns)
        tk = {d: decide(d, zk, fwd, arms)[0] for d in mondays}
        shuf[k] = simulate(rets, tk).to_numpy()
    eq = rets[arms].mean(axis=1)
    rng = np.random.default_rng(SEED)
    rand = np.zeros((n_random, len(rets)))
    for k in range(n_random):
        tg = {d: {a: 0.5 for a in rng.choice(arms, size=TOP, replace=False)} for d in mondays}
        rand[k] = simulate(rets, tg).to_numpy()
    windows = {"learning_2023h2_2024": (START, HOLDOUT_START - pd.Timedelta(days=1)),
               "holdout_2025_to_inception": (HOLDOUT_START, INCEPTION),
               "forward": (INCEPTION + pd.Timedelta(days=1), end)}
    ev: dict[str, Any] = {"caveat": "菜单里的臂是看过 2023–26 才设计的;前向才是检验(S-521)"}
    idx = rets.index
    for name, (lo, hi) in windows.items():
        sel = (idx >= lo) & (idx <= hi)
        if sel.sum() < 2:
            ev[name] = {"n": int(sel.sum())}
            continue
        m = _stats(meta[sel])
        tots = np.prod(1 + rand[:, sel], axis=1) - 1
        best = max(arms, key=lambda a: float(np.prod(1 + rets[a][sel]) - 1))
        ev[name] = {"meta": m, "btc": _stats(rets["btc"][sel]) if "btc" in rets else None,
                    "equal_weight_all": _stats(eq[sel]),
                    "random_top2_p50": round(float(np.percentile(tots, 50)), 5),
                    "random_top2_p95": round(float(np.percentile(tots, 95)), 5),
                    "pct_vs_random": round(float((tots < (m["total"] or 0)).mean()), 4),
                    "pct_vs_shuffled_state": round(float(((np.prod(1 + shuf[:, sel], axis=1) - 1) < (m["total"] or 0)).mean()), 4)
                    if n_shuffle else None,
                    "shuffled_state_p50": round(float(np.percentile(np.prod(1 + shuf[:, sel], axis=1) - 1, 50)), 5)
                    if n_shuffle else None,
                    "hindsight_best_single": {"arm": best, **_stats(rets[best][sel])},
                    "share_weeks_cash": round(float(np.mean([targets[d] == {CASH: 1.0} for d in mondays
                                                            if lo <= d <= hi])), 3)}
    picks = pd.Series([",".join(sorted(targets[d])) for d in mondays], index=mondays)
    ev["pick_counts_holdout"] = picks[(picks.index >= HOLDOUT_START)].str.split(",").explode().value_counts().to_dict()
    last = mondays[-1] if mondays else None
    ev["latest"] = {"d": last.date().isoformat() if last is not None else None,
                    "weights": targets.get(last), **(notes.get(last) or {})}
    now = datetime.now(timezone.utc).isoformat()
    nav = (1 + meta).cumprod()
    rows = []
    for d, v in meta.items():
        wk = max((m for m in mondays if m <= d), default=None)
        rows.append({"d": d.date().isoformat(), "arm": ARM, "ret": round(float(v), 8), "nav": round(float(nav[d]), 8),
                     "weights": targets.get(wk) if wk is not None else None,
                     "inception": INCEPTION.date().isoformat(), "code_ref": CODE_REF, "computed_at": now})
    return rows, ev


async def run_once() -> dict[str, Any]:
    from src.api.store import supabase_upsert_table
    from src.data.signals.portfolio_layer import load_strategy4
    from src.data.style.header import _read_all

    target = pd.Timestamp.now(tz="UTC").tz_localize(None).normalize() - pd.Timedelta(days=1)
    cv = await _read_all("core_variants_daily", {"select": "d,arm,ret", "order": "d.asc"})
    if not cv:
        return {"ok": False, "refused": True, "written": 0, "reason": "core_variants_daily 0 行 —— 等 ① 候选那一轮"}
    a = pd.DataFrame(cv)
    a["d"] = pd.to_datetime(a["d"])
    arm_rets = a.pivot_table(index="d", columns="arm", values="ret").astype(float)
    s4 = load_strategy4()
    if s4 is not None:
        arm_rets["strategy4"] = s4.reindex(arm_rets.index)
    if arm_rets.index.max() < target:
        return {"ok": False, "refused": True, "written": 0, "reason": f"策略库只到 {arm_rets.index.max().date()}"}
    st = await _read_all("state_daily", {"select": "d,feature,value", "entity": "eq.panel",
                                         "feature": "in.(" + ",".join(STATE_FEATURES) + ")", "order": "d.asc"})
    sd = pd.DataFrame(st)
    sd["d"] = pd.to_datetime(sd["d"])
    state = sd.pivot_table(index="d", columns="feature", values="value").astype(float)
    import asyncio
    rows, ev = await asyncio.to_thread(build, arm_rets, state, target)
    for i in range(0, len(rows), 2000):
        res = await supabase_upsert_table(TABLE, rows[i:i + 2000], on_conflict="d,arm")
        if not res.ok:
            return {"ok": False, "refused": False, "written": i, "reason": f"写入失败:{res.why}"}
    return {"ok": True, "refused": False, "written": len(rows), "reason": f"回放至 {target.date()}", "eval": ev}
