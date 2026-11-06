"""融合状态近邻臂(11-06,Jazz「新的 vector 都增补上了么?决策编排都接上了么?」)。

③ 决定原来的近邻臂读 `market_state_vectors`(24 维、契约冻结、两维预留)—— 11-06 新并进来的风格 / 链上 / 持仓结构 /
渠道 / 场所 / 政治 / 稳定币发行方与链 **一个都不在里面**。这里用融合特征表 `feature_matrix_daily` 另建一条向量:

- **键冻结**(`KEYS`,56 个):2021-06 → 2026-11 覆盖率 ≥ 80% 的键,去掉会单调漂移的水平量(总市值 / 总成交 / 净流动性 /
  币数 / 覆盖率)—— 漂移的水平量在扩张 z 里永远偏高,距离会被它们独占。换键 = 新预注册。
- **按时点标准化**:每个键在每一天用**严格更早**的历史算均值 / 标准差(至少 `MIN_HIST` 天),得到当天的 z;
  所以历史上每一天的向量都只用了那天以前的信息。
- **距离**:两天都有值的维度上的欧氏距离,按 √(D / 重合维数) 放大;重合 < `MIN_OVERLAP` 的不比。
- **基率**:最近的 `K` 个历史日(排除最近 31 天 —— 结果没出)之后 30 日 BTC 三档频率,按独立段数向无条件频率收缩
  (与原近邻臂同一口径:`exposure_decision.knn_rates`)。

只是描述臂 + 情景记分作者(`seth:exposure-knn-fused`),不进规则、不动钱。S-745 预注册了它与原近邻臂 / 基率臂的前向比较。
"""
from __future__ import annotations

import datetime as dt
import math
from typing import Any, Optional

AUTHOR = "seth:exposure-knn-fused"
K = 150
MIN_HIST = 365
MIN_OVERLAP = 0.7
EXCLUDE_DAYS = 31
KEYS = (
    "breadth_above_ma50", "chain:dex_30v30", "chain:dex_to_total_vol", "chain:fees_30v30", "chain:tvl_30d", "channel:rwa_30d",
    "channel:tokenized_30d", "cycle:deterioration", "cycle:shift_pct", "cycle:turning", "dist_200", "dvol:btc_pct_1y",
    "funding_7d_ann_binance", "macro:epu", "macro:fng", "macro:gpr", "macro:gpr_act", "macro:gpr_threat", "mom_20", "mom_200", "mom_60",
    "pol:conflict", "pol:sanctions", "pol:trade_war", "pos:alt_crowd_median_ln", "pos:alt_smart_minus_crowd_median",
    "pos:alt_taker_median_ln", "pos:btc_crowd_ln", "pos:btc_smart_minus_crowd", "pos:btc_top_pos_ln", "spy_ret_21",
    "stable_supply_30d", "stable:DAI_30d", "stable:USDC_30d", "stable:USDT_30d", "stablechain:arbitrum_30d", "stablechain:bsc_30d",
    "stablechain:ethereum_30d", "stablechain:solana_30d", "stablechain:tron_30d", "style_rel_majors_30d", "style:ai_rel30",
    "style:app_eq_minus_cap_30", "style:app_rel30", "style:defi_rel30", "style:infra_tokenization_rel30", "style:meme_rel30",
    "style:second_l1_l2_rel30", "style:top_l1_rel30", "taker_buy_share_30d", "venue:coinbase_share_spot30", "venue:korea_share_spot30",
    "vol_30", "vol_pct_3y", "vratio_30_180", "xasset:btc_qqq_corr60")


def _num(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def pit_vectors(rows: list[dict]) -> dict[str, list[Optional[float]]]:
    """纯函数。feature_matrix 行(d, f)→ {d: z 向量};每个键只用严格更早的值算均值 / 标准差(Welford),历史 < MIN_HIST ⇒ None。"""
    rows = sorted(rows, key=lambda r: str(r["d"]))
    stats = {k: [0, 0.0, 0.0] for k in KEYS}                               # n, mean, M2
    out: dict[str, list[Optional[float]]] = {}
    for r in rows:
        f = r.get("f") or {}
        vec: list[Optional[float]] = []
        for k in KEYS:
            n, mu, m2 = stats[k]
            x = _num(f.get(k))
            z = None
            if x is not None and n >= MIN_HIST:
                sd = math.sqrt(m2 / (n - 1)) if n > 1 else 0.0
                z = (x - mu) / sd if sd > 0 else None
            vec.append(None if z is None else round(max(-6.0, min(6.0, z)), 4))
            if x is not None:                                              # 当天的值在算完当天的 z 之后才进统计
                n += 1
                d1 = x - mu
                mu += d1 / n
                m2 += d1 * (x - mu)
                stats[k] = [n, mu, m2]
        out[str(r["d"])[:10]] = vec
    return out


def distance(a: list[Optional[float]], b: list[Optional[float]]) -> Optional[float]:
    """纯函数。两天都有值的维度上的欧氏距离,按 √(D / 重合) 放大;重合 < MIN_OVERLAP ⇒ None。"""
    pairs = [(x, y) for x, y in zip(a, b) if x is not None and y is not None]
    if len(pairs) < MIN_OVERLAP * len(KEYS):
        return None
    return math.sqrt(sum((x - y) ** 2 for x, y in pairs) * len(KEYS) / len(pairs))


def rates(vectors: dict[str, list[Optional[float]]], fwd: dict[str, float], d: str, k: int = K) -> dict[str, Any]:
    """纯函数。d 当天(或之前 3 天内最近一天)的向量 → 近邻基率;与 `exposure_decision.knn_rates` 同一收缩口径。"""
    from src.data.execution.exposure_decision import HORIZON_D, SHRINK_K, outcome_bin
    day = dt.date.fromisoformat(d)
    vd = max((x for x in vectors if x <= d and (day - dt.date.fromisoformat(x)).days <= 3), default=None)
    allc = {"down": 0, "flat": 0, "up": 0}
    for r in fwd.values():
        allc[outcome_bin(r)] += 1
    tot = sum(allc.values()) or 1
    p_all = {kk: v / tot for kk, v in allc.items()}
    if vd is None:
        return {"probs": None, "n": 0, "segments": 0, "vector_d": None, "why": "当天没有融合向量"}
    cutoff = (day - dt.timedelta(days=EXCLUDE_DAYS)).isoformat()
    today = vectors[vd]
    cand = []
    for x, v in vectors.items():
        if x > cutoff or x not in fwd:
            continue
        dist = distance(today, v)
        if dist is not None:
            cand.append((dist, x))
    if len(cand) < k:
        return {"probs": None, "n": 0, "segments": 0, "vector_d": vd, "why": f"可比的历史日只有 {len(cand)} 个(< {k})"}
    near = sorted(cand)[:k]
    counts = {"down": 0, "flat": 0, "up": 0}
    for _, x in near:
        counts[outcome_bin(fwd[x])] += 1
    segs, last = 0, None
    for x in sorted(dt.date.fromisoformat(x) for _, x in near):
        if last is None or (x - last).days >= HORIZON_D:
            segs += 1
        last = x
    p_k = {kk: v / k for kk, v in counts.items()}
    probs = {kk: (segs * p_k[kk] + SHRINK_K * p_all[kk]) / (segs + SHRINK_K) for kk in counts}
    t = sum(probs.values()) or 1
    return {"probs": {kk: round(v / t, 3) for kk, v in probs.items()}, "n": k, "segments": segs, "vector_d": vd,
            "nearest": [x for _, x in near[:5]], "why": None}


async def load_vectors() -> dict[str, list[Optional[float]]]:
    from src.data.style.header import _read_all
    rows = await _read_all("feature_matrix_daily", {"select": "d,f", "d": "gte.2019-01-01", "order": "d.asc"})
    return pit_vectors(rows)
