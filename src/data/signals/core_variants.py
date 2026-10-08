"""① 的候选定义 —— 拿掉单币上限、真正的动量加权,对照 BTC 与随机权重(T-072 / S-517)。

## 为什么

Jazz 10-08:「解开单一资产上限限制,采用真正的动量加权。」S-516:现行 ①(24 名市值加权、单币 ≤ 40%)
2023–24 与 2025–26 两段、总收益 / 回撤 / 夏普每一项都输给单持 BTC —— 单币上限把约六成放在山寨上,
而这一轮是 BTC 占优的周期。

## 预注册(2026-10-08,写代码之前,改任何一项 = 新起点)

    面板    现行 24 名(core_cap.panel_universe),binance_hist 收盘(前推价当缺)
    节奏    每周一再平衡;权重只用 d−1 收盘及以前的数据;持仓日间按价格漂移;成本 10 bps × 换手
    臂      cap_c40       现行 ①(对照;应与 multiplier_daily core_replay 基本一致)
            cap_uncapped  市值加权,不设上限
            mom90         w ∝ max(0, 90 日收益);没有一个为正 ⇒ 退回 cap_uncapped
            mom90_x_cap   w ∝ 市值 × max(0, 90 日收益);同样退回
            btc           单持 BTC(基准)
    对照    BTC · 现行 ① · 随机权重(每个再平衡日对当时有价的币取 Dirichlet(1) 权重,500 次)的分位
    窗口    2023–2024 / 2025-01-01 → 起点 / 起点(2026-10-08)后前向

## 偏差

24 名是今天的名单回填(幸存者);动量族在 S-428 里已被看好;2025–26 的 BTC 占优已知 —— 回放是描述,前向才是检验。

## 判活判据(规则 5b ②)

    select max(d) from core_variants_daily where arm = 'mom90';   -- = 昨天(UTC)
"""
from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Optional

import numpy as np
import pandas as pd

TABLE = "core_variants_daily"
WRITES_TABLES = (TABLE,)
ARMS = ("cap_c40", "cap_uncapped", "mom90", "mom90_x_cap", "btc")
LOOKBACK = 90
COST_BPS = 10.0
CAP_C40 = 0.40
REPLAY_START = pd.Timestamp("2023-01-02")
HOLDOUT_START = pd.Timestamp("2025-01-01")
INCEPTION = pd.Timestamp("2026-10-08")
N_RANDOM, SEED = 500, 517
CODE_REF = "T-072 core variants v1"

WeightFn = Callable[[pd.Timestamp, pd.DataFrame, pd.DataFrame, list], dict]


def _norm(raw: Mapping[str, float]) -> dict[str, float]:
    raw = {s: float(v) for s, v in raw.items() if v is not None and math.isfinite(float(v)) and float(v) > 0}
    tot = sum(raw.values())
    return {s: v / tot for s, v in raw.items()} if tot > 0 else {}


def capped(raw: Mapping[str, float], cap: float) -> dict[str, float]:
    """比例分配后单币 ≤ cap,超出部分按未触顶者比例重分(与 core_cap.capped_weights 同一算法,α=1)。"""
    w = _norm(raw)
    if not w or len(w) * cap < 1 - 1e-12:
        return w
    fixed: dict[str, float] = {}
    for _ in range(len(w) + 1):
        over = {s for s, v in w.items() if s not in fixed and v > cap + 1e-12}
        if not over:
            break
        for s in over:
            fixed[s] = cap
        rest = {s: raw[s] for s in w if s not in fixed}
        left = 1 - sum(fixed.values())
        tot = sum(rest.values())
        w = {**fixed, **{s: left * v / tot for s, v in rest.items()}}
    return w


def momentum(px: pd.DataFrame, d: pd.Timestamp, names: list) -> dict[str, float]:
    """d−1 收盘相对 d−1−LOOKBACK 收盘的收益。任一端缺 ⇒ 不给分(不猜)。"""
    a, b = d - pd.Timedelta(days=1), d - pd.Timedelta(days=1 + LOOKBACK)
    if a not in px.index or b not in px.index:
        return {}
    out = {}
    for s in names:
        pa, pb = px.at[a, s], px.at[b, s]
        if pd.notna(pa) and pd.notna(pb) and pb > 0:
            out[s] = float(pa / pb - 1)
    return out


def target_weights(arm: str, d: pd.Timestamp, px: pd.DataFrame, mcap_prev: pd.DataFrame, names: list) -> dict:
    """纯函数。某个臂在再平衡日 d 的目标权重(只用 d−1 及以前)。"""
    mc = mcap_prev.loc[d] if d in mcap_prev.index else pd.Series(dtype=float)
    caps = {s: mc.get(s) for s in names if pd.notna(mc.get(s))}
    if arm == "btc":
        return {"BTC": 1.0} if "BTC" in names else {}
    if arm == "cap_c40":
        return capped(caps, CAP_C40)
    if arm == "cap_uncapped":
        return _norm(caps)
    mom = momentum(px, d, names)
    pos = {s: m for s, m in mom.items() if m > 0}
    if arm == "mom90":
        return _norm(pos) or _norm(caps)
    if arm == "mom90_x_cap":
        return _norm({s: caps[s] * m for s, m in pos.items() if s in caps}) or _norm(caps)
    raise ValueError(f"未知臂 {arm}")


def simulate(rets: pd.DataFrame, targets: Mapping[pd.Timestamp, Mapping[str, float]]) -> pd.Series:
    """纯函数。rets:日简单收益(行 = 日,列 = 币,缺 = 0 当天不动);targets:再平衡日 → 目标权重。
    再平衡日的收益用新权重;之后权重随价格漂移;成本 = COST_BPS × Σ|新 − 漂移后|。"""
    cols = list(rets.columns)
    r = rets.fillna(0.0).to_numpy()
    w = np.zeros(len(cols))
    out = np.zeros(len(rets))
    for i, d in enumerate(rets.index):
        cost = 0.0
        if d in targets:
            new = np.array([targets[d].get(c, 0.0) for c in cols])
            cost = float(np.abs(new - w).sum()) * COST_BPS / 1e4
            w = new
        port = float(w @ r[i])
        out[i] = port - cost
        grown = w * (1 + r[i])
        tot = grown.sum()
        w = grown / tot if tot > 0 else w
    return pd.Series(out, index=rets.index)


def _stats(x: pd.Series) -> dict[str, Optional[float]]:
    if len(x) < 2:
        return {"n": len(x), "total": None, "maxdd": None, "sharpe": None}
    nav = (1 + x).cumprod()
    sd = float(x.std())
    return {"n": int(len(x)), "total": round(float(nav.iloc[-1] - 1), 5),
            "maxdd": round(float((nav / nav.cummax() - 1).min()), 5),
            "sharpe": round(float(x.mean() / sd * math.sqrt(365)), 3) if sd > 0 else None}


def random_baseline(rets: pd.DataFrame, rebal_days: list, quoted: Mapping[pd.Timestamp, list],
                    n: int = N_RANDOM, seed: int = SEED) -> np.ndarray:
    """每个再平衡日对当时有价的币取 Dirichlet(1) 权重;返回 n 条路径的日收益矩阵(n × 天)。"""
    rng = np.random.default_rng(seed)
    out = np.zeros((n, len(rets)))
    for k in range(n):
        tg = {}
        for d in rebal_days:
            names = quoted.get(d) or []
            if names:
                tg[d] = dict(zip(names, rng.dirichlet(np.ones(len(names)))))
        out[k] = simulate(rets, tg).to_numpy()
    return out


def evaluate(arm_rets: Mapping[str, pd.Series], rand: Optional[np.ndarray], idx: pd.DatetimeIndex,
             end: pd.Timestamp) -> dict[str, Any]:
    windows = {"in_sample_2023_2024": (REPLAY_START, HOLDOUT_START - pd.Timedelta(days=1)),
               "holdout_2025_to_inception": (HOLDOUT_START, INCEPTION),
               "forward": (INCEPTION + pd.Timedelta(days=1), end)}
    out: dict[str, Any] = {"caveat": "24 名今天名单回填;2025–26 的 BTC 占优已知 —— 回放是描述,前向才是检验(S-517)"}
    for name, (lo, hi) in windows.items():
        sel = (idx >= lo) & (idx <= hi)
        if sel.sum() < 2:
            out[name] = {"n": int(sel.sum())}
            continue
        w: dict[str, Any] = {a: _stats(s[sel]) for a, s in arm_rets.items()}
        if rand is not None:
            tots = np.prod(1 + rand[:, sel], axis=1) - 1
            w["random_weights"] = {"p50": round(float(np.percentile(tots, 50)), 5),
                                   "p95": round(float(np.percentile(tots, 95)), 5)}
            for a, s in arm_rets.items():
                t = w[a]["total"]
                w[a]["pct_vs_random"] = round(float((tots < t).mean()), 4) if t is not None else None
        out[name] = w
    return out


def build(px: pd.DataFrame, mcap_prev: pd.DataFrame, end: pd.Timestamp,
          n_random: int = N_RANDOM) -> tuple[list[dict], dict[str, Any]]:
    """纯函数。px:面板收盘(前推价已为 NaN);mcap_prev:行 = d、值 = d−1 市值。"""
    px = px.sort_index()
    names = list(px.columns)
    rets = (px / px.shift(1) - 1).loc[(px.index >= REPLAY_START) & (px.index <= end)]
    days = list(rets.index)
    rebal = [d for d in days if d == days[0] or d.weekday() == 0]
    quoted = {d: [s for s in names if pd.notna(px.at[d - pd.Timedelta(days=1), s])]
              if (d - pd.Timedelta(days=1)) in px.index else [] for d in rebal}
    arm_rets: dict[str, pd.Series] = {}
    for arm in ARMS:
        tg = {d: target_weights(arm, d, px, mcap_prev, quoted[d]) for d in rebal}
        arm_rets[arm] = simulate(rets, tg)
    rand = random_baseline(rets, rebal, quoted, n=n_random) if n_random else None
    ev = evaluate(arm_rets, rand, rets.index, end)
    now = datetime.now(timezone.utc).isoformat()
    rows = []
    for arm, s in arm_rets.items():
        nav = (1 + s).cumprod()
        for d, v in s.items():
            rows.append({"d": d.date().isoformat(), "arm": arm, "ret": round(float(v), 8),
                         "nav": round(float(nav[d]), 8), "inception": INCEPTION.date().isoformat(),
                         "code_ref": CODE_REF, "computed_at": now})
    last = rebal[-1]
    ev["latest_weights"] = {a: {k: round(v, 4) for k, v in sorted(target_weights(a, last, px, mcap_prev, quoted[last]).items(),
                                                                   key=lambda kv: -kv[1])[:8]}
                            for a in ARMS}
    ev["latest_rebalance"] = last.date().isoformat()
    return rows, ev


async def run_once() -> dict[str, Any]:
    import asyncio

    from src.api.store import supabase_upsert_table
    from src.data.market.panel_read import read_panel
    from src.data.signals.core_cap import PRICE_SOURCE, _mcap_prev, panel_universe

    target = pd.Timestamp.now(tz="UTC").tz_localize(None).normalize() - pd.Timedelta(days=1)
    panel = list(panel_universe())
    start = (REPLAY_START - pd.Timedelta(days=LOOKBACK + 10)).date().isoformat()
    p = await read_panel(panel, start=start, source=PRICE_SOURCE)
    idx = pd.to_datetime(p.days)
    px = pd.DataFrame(p.close, index=idx, columns=p.symbols, dtype=float)
    px = px.mask(pd.DataFrame(p.filled, index=idx, columns=p.symbols))
    px = px.reindex(pd.date_range(px.index.min(), px.index.max(), freq="D"))
    if px.index.max() < target:
        return {"ok": False, "refused": True, "written": 0, "reason": f"面板收盘只到 {px.index.max().date()}"}
    mc = await _mcap_prev(panel, start)
    rows, ev = await asyncio.to_thread(build, px, mc, target)
    for i in range(0, len(rows), 2000):
        res = await supabase_upsert_table(TABLE, rows[i:i + 2000], on_conflict="d,arm")
        if not res.ok:
            return {"ok": False, "refused": False, "written": i, "reason": f"写入失败:{res.why}"}
    return {"ok": True, "refused": False, "written": len(rows), "reason": f"回放至 {target.date()}", "eval": ev}
