"""T-045 评估层 rr_matrix —— lane B 的 v0.6(纯函数 + 13 个用例),Seth 合并时改了三处(S-496):
  ① bootstrap 种子由 `hash()` 改成 crc32 —— Python 的字符串 hash 每个进程随机(PYTHONHASHSEED),
    「同一输入多次调用 = 同一输出」只在同一个进程里成立,跨天重算会抖;
  ② rel_maxdd 的基准回撤改为在账本自己的窗口上算 —— 原来拿 ① 的全历史(含 2022)比账本的几十天;
  ③ FOMC 日期改正三个(2025-12-10、2026-10-28、2026-12-09),并收进 `FOMC_DECISION_DATES`。
下面是 B 的原说明。

T-045 评估层 rr_matrix — 纯函数 compute_rr_matrix v0.6

Per SPEC v0.6 (2026-10-06):
- 输入 = 数据,无 IO / 无副作用 / 同一输入多次调用 = 同一输出。
- 状态输入对齐 T-048 as-built:regime_share_30d:<6 类> + regime_coverage_30d
- regime 派生:argmax(6 shares) / coverage<20 → 'unknown'(per §Seth-1006d #1)
- 7 类 cells(6 + UNKNOWN)× 2 fomc = 14 cells/strategy
- 年化 365 (per §Seth-1006d #3)
- 全样本 CI 走真 bootstrap(per §Seth-1006d #5),不可靠时 None
- cell = 描述;L3 ci_lo 入门槛 = l3-v2(per §Seth-1006d #6)
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Iterable, Optional
import math
import sys
import zlib

import numpy as np
import pandas as pd


# 11 有效账本(per SPEC §4.1)+ family + n_variants_tried
DEFAULT_N_VARIANTS: dict[str, int] = {
    "core_cap": 4,         # cap_a1 + cap_a05 + ew_a0 + cap_a1_u(S-556)
    "beta_core": 1,
    "beta_plus_w": 2,      # w + m
    "beta_plus_m": 2,
    "tokenization_tilt": 1,
    "hl_mech": 2,          # MECH + JEV
    "hl_jev": 2,
    "causal_paper": 1,
    "scalable_book": 1,
    "combined_book": 1,
    "dingge_paper": 1,
}

# 排除的维度(无 SHIP 价值)
EXCLUDED_BOOKS: frozenset[str] = frozenset({"fusion_paper", "two_layer_paper"})

# 6 类 macro regime(per T-048 as-built,per §Seth-1006d #2)
REGIMES: tuple[str, ...] = (
    "EASING", "NEUTRAL", "RISK_OFF", "RISK_ON", "STAGFLATION", "TIGHTENING",
)

# UNKNOWN = 第 7 类(regime 缺失 / coverage 不足 / 任一分量 NaN / 和 ≠ 1)
# Per §Seth-1006d #1:不许默认 RISK_ON
UNKNOWN_REGIME: str = "unknown"

# FOMC 二维
FOMC_VALUES: tuple[str, ...] = ("yes", "no")

# T-048 as-built 的 6 个 share 列(per §3.1)
REGIME_SHARE_FEATURES: tuple[str, ...] = tuple(f"regime_share_30d:{c}" for c in REGIMES)

# coverage 阈值(per §3.2)<=20 视为不足
REGIME_COVERAGE_MIN: int = 20

# share 之和偏离 1.0 的容差
REGIME_SHARE_SUM_TOL: float = 0.05

# T-068 价格特征(state_daily 里按时点的面板列,无条件全样本)— 主格子 = trend × vol 6 格
STATE_DIST_200_FEATURE: str = "dist_200"     # (price - 200d MA) / 200d MA;>0 = 价格在 200d MA 之上
STATE_VOL_PCT_3Y_FEATURE: str = "vol_pct_3y" # 已为滚动 3 年的 vol 分位 ∈ [0, 1]

# 主格子 bucket 标签
TREND_BUCKETS: tuple[str, ...] = ("UP", "DOWN")  # dist_200 > 0 ⇒ UP,≤0 ⇒ DOWN
VOL_BUCKETS: tuple[str, ...] = ("LO", "MID", "HI")
# vol 三档切点:vol_pct_3y 本身就是滚动 3 年的分位 [0,1],切点用常数 1/3, 2/3(按时点,
# 不用全样本分位 — 避免看未来)。见 T-068 acceptance.check。
VOL_CUT_QUANTILES: tuple[float, ...] = (1.0 / 3.0, 2.0 / 3.0)

# trend_vol 缺任一字段时(任意 NaN)归 `TREND_VOL_UNKNOWN`,不进 6 主格
TREND_VOL_UNKNOWN: str = "UNKNOWN"

# annualization(per §Seth-1006d #3)
DEFAULT_ANNUALIZATION: int = 365


def _stable(*parts) -> int:
    """跨进程稳定的小整数(0–999),用于 bootstrap 种子 —— 不用 hash():它每个进程随机。"""
    return zlib.crc32("|".join(str(p) for p in parts).encode("utf-8")) % 1000


#: FOMC 议息决议日(会议第二天,美东 14:00 公布)。来源:美联储公布的日程;B 的 CSV 有三处错日(S-496 已改)。
FOMC_DECISION_DATES: tuple[date, ...] = tuple(date.fromisoformat(x) for x in (
    "2022-01-26", "2022-03-16", "2022-05-04", "2022-06-15", "2022-07-27", "2022-09-21", "2022-11-02", "2022-12-14",
    "2023-02-01", "2023-03-22", "2023-05-03", "2023-06-14", "2023-07-26", "2023-09-20", "2023-11-01", "2023-12-13",
    "2024-01-31", "2024-03-20", "2024-05-01", "2024-06-12", "2024-07-31", "2024-09-18", "2024-11-07", "2024-12-18",
    "2025-01-29", "2025-03-19", "2025-05-07", "2025-06-18", "2025-07-30", "2025-09-17", "2025-10-29", "2025-12-10",
    "2026-01-28", "2026-03-18", "2026-04-29", "2026-06-17", "2026-07-29", "2026-09-16", "2026-10-28", "2026-12-09",
))


def _fomc_window_dates(fomc_dates: Iterable[date], window: int = 4) -> set[pd.Timestamp]:
    """Per SPEC §3.3:会议前 1 天 ~ 会议后 2 天 = 4 天 window。

    Returns: set of pd.Timestamp of all dates that fall inside any window.
    """
    out: set[pd.Timestamp] = set()
    for d in fomc_dates:
        ts = pd.Timestamp(d)
        for delta in range(-1, window - 1):   # -1, 0, 1, 2 → 4 天
            out.add(ts + pd.Timedelta(days=delta))
    return out


def _dominant_regime(row: pd.Series) -> str:
    """Per SPEC §3.2:regime = argmax(6 shares) / 异常 → UNKNOWN。

    row: 一个 Series,索引 = feature 名(`regime_share_30d:*` + `regime_coverage_30d`)
    返回:6 类之一 + 'unknown'。
    """
    # 1. coverage 检查
    if "regime_coverage_30d" not in row.index:
        return UNKNOWN_REGIME
    cov = row["regime_coverage_30d"]
    if pd.isna(cov) or cov < REGIME_COVERAGE_MIN:
        return UNKNOWN_REGIME

    # 2. 6 shares 完整性
    shares = {}
    for cls in REGIMES:
        feat = f"regime_share_30d:{cls}"
        if feat not in row.index or pd.isna(row[feat]):
            return UNKNOWN_REGIME
        shares[cls] = float(row[feat])

    # 3. 之和 ≈ 1.0
    s = sum(shares.values())
    if abs(s - 1.0) > REGIME_SHARE_SUM_TOL:
        return UNKNOWN_REGIME

    # 4. argmax
    return max(shares, key=shares.get)


def _state_panel_daily(state_daily: pd.DataFrame, as_of: pd.Timestamp) -> pd.DataFrame:
    """Per SPEC §3.1 + §5.1:取 d ≤ as_of_state, entity='panel', features = 6 shares + coverage + T-068 价格特征。
    PIT 严格 — 过线直接 throw(per SPEC §1.3)。

    Returns: wide-form DataFrame with columns:
        d,
        regime_share_30d:EASING, regime_share_30d:NEUTRAL, ..., regime_coverage_30d,
        dist_200, vol_pct_3y
    (一行 / 日;缺分量取 None)
    """
    if state_daily is None or state_daily.empty:
        return pd.DataFrame(
            columns=["d"] + list(REGIME_SHARE_FEATURES) + ["regime_coverage_30d",
                      STATE_DIST_200_FEATURE, STATE_VOL_PCT_3Y_FEATURE]
        )
    required = {"d", "entity", "feature", "value"}
    missing = required - set(state_daily.columns)
    if missing:
        raise ValueError(f"state_daily 缺列:{missing};期望至少 {required}")
    sd = state_daily[state_daily["d"] <= as_of].copy()
    panel = sd[sd["entity"] == "panel"]
    if panel.empty:
        return pd.DataFrame(
            columns=["d"] + list(REGIME_SHARE_FEATURES) + ["regime_coverage_30d",
                      STATE_DIST_200_FEATURE, STATE_VOL_PCT_3Y_FEATURE]
        )

    # 只保留 regime + T-068 价格特征
    keep = (set(REGIME_SHARE_FEATURES) | {"regime_coverage_30d"}
            | {STATE_DIST_200_FEATURE, STATE_VOL_PCT_3Y_FEATURE})
    panel_filt = panel[panel["feature"].isin(keep)]

    pivot = panel_filt.pivot_table(
        index="d", columns="feature", values="value", aggfunc="last"
    )
    pivot = pivot.reset_index()
    # 确保所有列都存在(缺则 NaN)
    for col in list(REGIME_SHARE_FEATURES) + ["regime_coverage_30d",
                                              STATE_DIST_200_FEATURE, STATE_VOL_PCT_3Y_FEATURE]:
        if col not in pivot.columns:
            pivot[col] = np.nan
    return pivot


def _derive_regime_per_day(state_panel: pd.DataFrame) -> pd.Series:
    """Per SPEC §3.2:对 state_panel 每行调用 _dominant_regime,返回 regime_per_day。"""
    if state_panel.empty:
        return pd.Series(dtype=object)
    rows = []
    for _, row in state_panel.iterrows():
        rows.append((row["d"], _dominant_regime(row)))
    return pd.Series([r[1] for r in rows], index=pd.DatetimeIndex([r[0] for r in rows]), name="regime")


def _classify_vol_bucket(vol_pct_3y: float) -> str:
    """Per T-068 acceptance:切点是常数(1/3, 2/3),不是全样本分位(避免看未来)。

    vol_pct_3y ∈ [0, 1]:vol_lo ⇒ < 1/3;vol_mid ⇒ ∈ [1/3, 2/3);vol_hi ⇒ ≥ 2/3。
    NaN/缺 ⇒ TREND_VOL_UNKNOWN。
    """
    if pd.isna(vol_pct_3y):
        return TREND_VOL_UNKNOWN
    lo_cut, hi_cut = VOL_CUT_QUANTILES
    if vol_pct_3y < lo_cut:
        return "LO"
    if vol_pct_3y < hi_cut:
        return "MID"
    return "HI"


def _derive_trend_vol_per_day(state_panel: pd.DataFrame) -> pd.Series:
    """Per T-068 acceptance.check:主格子 = state_daily 面板特征按时点。

    返回:Series(index=d, name='trend_vol'),值 = 'UP_LO' / 'UP_MID' / 'UP_HI' /
    'DOWN_LO' / 'DOWN_MID' / 'DOWN_HI' / 'UNKNOWN'。
    - dist_200 是「(price - 200d MA) / 200d MA」:>0 ⇒ UP,≤0 ⇒ DOWN。
    - vol_pct_3y 是滚动 3 年的 vol 分位 ∈ [0,1]:<1/3=LO,∈[1/3,2/3)=MID,≥2/3=HI。
    - 任一字段 NaN ⇒ UNKNOWN(不归主格)。
    - 切点是常数,不用全样本分位 — 同一日期在 2024 年算与今天算落在同一格(无前视)。
    """
    if state_panel.empty:
        return pd.Series(dtype=object)
    rows = []
    for _, row in state_panel.iterrows():
        d = row["d"]
        dist = row.get(STATE_DIST_200_FEATURE, np.nan)
        vol = row.get(STATE_VOL_PCT_3Y_FEATURE, np.nan)
        if pd.isna(dist) or pd.isna(vol):
            label = TREND_VOL_UNKNOWN
        else:
            trend = "UP" if float(dist) > 0 else "DOWN"
            vol_bucket = _classify_vol_bucket(float(vol))
            label = f"{trend}_{vol_bucket}"
        rows.append((d, label))
    return pd.Series([r[1] for r in rows], index=pd.DatetimeIndex([r[0] for r in rows]), name="trend_vol")


def _sliding_block_sample(rng: np.random.Generator, arr: np.ndarray, block_size: int,
                          n_blocks: int) -> np.ndarray:
    """T-059 滑动块 + 随机起点 + 首尾相接 — 公用于 _block_bootstrap_ci / _p_pos。

    n_blocks 个块,每块长度 = block_size;每块的起点 s ∈ [0, n) 随机抽,
    块内下标 (s + k) mod n(首尾相接)。所有 n 天都能被选中 — 修旧 bug
    (20 ≤ n < 40 时固定非重叠块 ⇒ n_blocks=1 ⇒ 只重抽前 20 天那一个块)。
    """
    n = len(arr)
    starts = rng.integers(0, n, size=n_blocks)
    idx = np.empty(n_blocks * block_size, dtype=np.int64)
    for k, s in enumerate(starts):
        idx[k * block_size:(k + 1) * block_size] = (s + np.arange(block_size, dtype=np.int64)) % n
    return arr[idx]


def _block_bootstrap_ci(ret_series: pd.Series, block_size: int | None = None,
                        n_bootstrap: int = 1000, ci: float = 0.95,
                        seed: int | None = None) -> tuple[float, float, float]:
    """Per SPEC §2 step 3 + §10.5 + T-059 acceptance(2026-10-07):块 bootstrap 95% CI + excess_mean。

    行为契约(T-059 acceptance):
    - 滑动块、随机起点、首尾相接 — 通过 _sliding_block_sample;
    - 块长 = min(20, n // 2),大样本就是 20;有效 block 被 n 限制不会越界。
    - n < 40:ci_lo / ci_hi = NaN(per §Seth-1006d #5 + T-059);excess_mean 用满全部 n 天(修旧 bug,
      n ∈ [20, 40) 时 em = 前 20 天均值、CI 是单点的退化)。
    - n == 0:em = 0.0, CI = NaN。

    Returns: (excess_mean, ci_lo, ci_hi)。
    """
    arr = ret_series.dropna().to_numpy()
    n = len(arr)
    if n == 0:
        return 0.0, float("nan"), float("nan")
    excess_mean_full = float(arr.mean())
    if n < 40:
        # n < 40 时 CI 不可靠,返回 NaN;但 excess_mean 用全样本(arr.mean())— 显式声明用满 n 天
        return excess_mean_full, float("nan"), float("nan")
    bs = min(20, max(1, n // 2))
    if block_size is not None:
        bs = min(block_size, max(1, n // 2))
    n_blocks = max(1, -(-n // bs))   # ceil(n / bs) — 保证每张天在一次 sample 里期望至少 1 次被覆盖
    rng = np.random.default_rng(seed)
    boot_means = np.empty(n_bootstrap, dtype=float)
    for i in range(n_bootstrap):
        boot_means[i] = _sliding_block_sample(rng, arr, bs, n_blocks).mean()
    alpha = 1 - ci
    ci_lo = float(np.quantile(boot_means, alpha / 2))
    ci_hi = float(np.quantile(boot_means, 1 - alpha / 2))
    return excess_mean_full, ci_lo, ci_hi


def _p_pos(ret_series: pd.Series, block_size: int | None = None,
           n_bootstrap: int = 1000, seed: int | None = None) -> float:
    """T-059 acceptance:bootstrap 里超额 > 0 的比例。规则与 _block_bootstrap_ci 完全一致。

    - n == 0:NaN。
    - n < 40:NaN(per acceptance "p_pos 同一规则",修旧 _p_pos binary {0, 1} bug)。
    - n ≥ 40:滑动块 + 随机起点 + 首尾相接;bs = min(20, n//2);n_blocks = ceil(n/bs)。
    """
    arr = ret_series.dropna().to_numpy()
    n = len(arr)
    if n == 0:
        return float("nan")
    if n < 40:
        return float("nan")   # per acceptance — 不写 binary {0, 1}
    bs = min(20, max(1, n // 2))
    if block_size is not None:
        bs = min(block_size, max(1, n // 2))
    n_blocks = max(1, -(-n // bs))
    rng = np.random.default_rng(seed)
    p_pos_count = 0
    for _ in range(n_bootstrap):
        sample = _sliding_block_sample(rng, arr, bs, n_blocks)
        if sample.mean() > 0:
            p_pos_count += 1
    return float(p_pos_count / n_bootstrap)


def _beta_calc(book_ret: pd.Series, bench_ret: pd.Series) -> float:
    """对 ① 的 β(per SPEC §2 step 5)。"""
    a, b = book_ret.align(bench_ret, join="inner")
    a, b = a.dropna(), b.dropna()
    if len(a) < 2 or b.var() == 0:
        return float("nan")
    return float(a.cov(b) / b.var())


def _max_drawdown(nav: pd.Series) -> float:
    return float((nav / nav.cummax() - 1).min())


def _turnover_annual(weights_history: pd.DataFrame | None) -> float:
    """粗估年化换手(per SPEC §2 step 5)。
    weights_history 为 None 时返回 NaN(纯函数不依赖外部数据)。
    """
    if weights_history is None or weights_history.empty:
        return float("nan")
    diffs = weights_history.diff().abs().sum(axis=1).dropna()
    turnover_d = diffs / 2.0
    return float(turnover_d.mean() * DEFAULT_ANNUALIZATION)


# ── T-069:随机组合基准 + outlier ────────────────────────────────────────────────
# Per T-069 acceptance.check:每本账 × 格子:随机组合 1,000 次(按日期块抽样),
# 与账本「同宇宙、同底层加权(β+ / 代币化 / beta_core 等权底,cis_tilt 市值底)、
# 同持仓数、同换手、同单币上限」,给 p05/p50/p95/p99 + pct_vs_random;
# outlier = 实测 > 随机 p99。
#
# 设计要点:
# ① 零信号账本 = 一本与随机组合采用同一规则(同 spec,无私有信号)的账本;
#    其 excess_mean 是随机分布中的一个样本。pct_vs_random(实际在随机分布里的秩)
#    应当近似均匀(KS p > 0.05)。这是算法的自检 —— 若不通过,随机基准本身有偏。
# ② 埋了信号的账本 = 系统性挑赢家。其 excess_mean 应当远离随机主体,
#    pct_vs_random > 0.95,被识别为 outlier。
# ③ 等权底 vs 市值底:抽到的不同 weighted「等权 vs 市值」风格不应被算法误识为
#    信号 —— 在「等权跑赢市值」的样本里,等权零信号账本的 pct_vs_random 仍近似均匀
#    (见 acceptance.expect 第三条)。

# 单币上限默认值(S-473 起 ① 解除了 40% 上限;但 β+ / 代币化等用 40% 作默认)
DEFAULT_SINGLE_NAME_CAP: float = 0.40

# 默认持仓数(per §3:β+ / 代币化 = 24 名的子集)
DEFAULT_N_POSITIONS: int = 12

# 默认再平衡周期
DEFAULT_TURNOVER_DAYS: int = 7


def _weighted_portfolio_rets(rets: pd.DataFrame, weights: pd.Series) -> pd.Series:
    """Calcuate weighted portfolio daily returns from per-asset returns + weights.
    weights sums to 1, indexed by symbol. NaN days treated as 0 (no rebalance = no P&L).
    """
    if rets.empty:
        return pd.Series(dtype=float)
    aligned_w = weights.reindex(rets.columns).fillna(0.0)
    seg = rets.fillna(0.0)
    return seg.values @ aligned_w.values  # numpy 1d @ 2d


def _panel_benchmark_nav(rets: pd.DataFrame) -> pd.Series:
    """默认基准 = 面板等权。NaN 日按 0 处理,不跨缺口复利(S-272)。"""
    if rets.empty:
        return pd.Series(dtype=float)
    daily = rets.mean(axis=1, skipna=True).fillna(0.0)
    return (1 + daily).cumprod()


def simulate_random_portfolio(
    rets: pd.DataFrame,
    n_positions: int,
    weighting: str,
    single_name_cap: float = DEFAULT_SINGLE_NAME_CAP,
    market_caps: Optional[pd.Series] = None,
    turnover_days: int = DEFAULT_TURNOVER_DAYS,
    rng: Optional[np.random.Generator] = None,
) -> pd.Series:
    """构造一个随机组合的日 NAV(research / 测试用)。

    Parameters
    ----------
    rets           : 资产日收益宽表(columns=symbols, DatetimeIndex 升序)
    n_positions    : 每调仓周期持仓数(不能 > n_cols)
    weighting      : 'equal' / 'market_cap'
    single_name_cap: 单币上限(市值底时启用,默认 0.40)
    market_caps    : 仅 market_cap 加权需要;None ⇒ fallback 等权
    turnover_days  : 调仓周期(默认 7 天)

    Returns
    -------
    NAV index(从第一天起累计,起点 = 1.0)。

    Notes
    -----
    - 纯函数 + RNG 决定:同一 seed 同一输出。
    - 调仓日 = 序列起点 + 0, +turnover_days, +2*turnover_days, ...
    - 任一日某资产无数据 ⇒ 那天该仓位的有效权重按可投比重新分配。
    """
    rng = rng if rng is not None else np.random.default_rng()
    n_cols = rets.shape[1]
    if n_cols == 0:
        return pd.Series(dtype=float)
    n_pos = max(1, min(n_positions, n_cols))
    n_days = len(rets)
    if n_days == 0:
        return pd.Series(dtype=float)
    # 调仓日(含末尾一次)
    rb_idx = list(range(0, n_days, turnover_days))
    if rb_idx[-1] != n_days:
        rb_idx.append(n_days)

    port_rets: list[pd.Series] = []
    for i in range(len(rb_idx) - 1):
        start, end = rb_idx[i], rb_idx[i + 1]
        members = rng.choice(rets.columns, size=n_pos, replace=False)

        if weighting == "equal":
            w = pd.Series(1.0 / n_pos, index=members)
        elif weighting == "market_cap":
            if market_caps is None:
                w = pd.Series(1.0 / n_pos, index=members)
            else:
                mc = pd.Series({m: float(market_caps.get(m, 1.0)) for m in members})
                w = (mc / mc.sum()).clip(upper=single_name_cap)
                # 单币上限后的剩余再归一
                excess = 1.0 - w.sum()
                if excess > 0 and not w.empty:
                    w = w + excess * (1.0 / n_pos)
            # 防退化(全 clip 到 cap 后剩余放回等权)
            if w.sum() <= 0:
                w = pd.Series(1.0 / n_pos, index=members)
            else:
                w = w / w.sum()
        else:
            raise ValueError(f"unknown weighting: {weighting!r}")

        seg = rets.iloc[start:end]
        seg_filled = seg.fillna(0.0)
        aligned_w = w.reindex(seg_filled.columns).fillna(0.0).values
        port_rets.append(pd.Series(seg_filled.values @ aligned_w, index=seg.index))

    if not port_rets:
        return pd.Series(dtype=float)
    daily = pd.concat(port_rets).sort_index()
    return (1 + daily).cumprod()


def compute_random_baseline(
    rets: pd.DataFrame,
    n_positions: int,
    weighting: str,
    single_name_cap: float = DEFAULT_SINGLE_NAME_CAP,
    market_caps: Optional[pd.Series] = None,
    turnover_days: int = DEFAULT_TURNOVER_DAYS,
    n_random: int = 1000,
    seed: int = 42,
) -> dict:
    """跑 n_random 次随机组合,返回分布(p05/p50/p95/p99 + 原始分布)。

    Returns
    -------
    dict with: p05, p50, p95, p99, mean, std, distribution (1d ndarray),
    n_random, n_valid (过滤掉全 NaN 的样本数)
    """
    bench_nav = _panel_benchmark_nav(rets)
    if bench_nav.empty:
        return {"p05": float("nan"), "p50": float("nan"), "p95": float("nan"),
                "p99": float("nan"), "mean": float("nan"), "std": float("nan"),
                "distribution": np.array([]), "n_random": n_random, "n_valid": 0}
    bench_ret = bench_nav.pct_change().dropna()

    sample = np.empty(n_random, dtype=float)
    n_valid = 0
    for i in range(n_random):
        rng_i = np.random.default_rng(seed + i)
        nav = simulate_random_portfolio(rets, n_positions, weighting,
                                        single_name_cap, market_caps,
                                        turnover_days, rng_i)
        pr = nav.pct_change().dropna()
        pr, bx = pr.align(bench_ret, join="inner")
        excess = (pr - bx).dropna()
        if len(excess) > 0:
            sample[i] = float(excess.mean())
            n_valid += 1
        else:
            sample[i] = float("nan")

    valid = sample[~np.isnan(sample)]
    if len(valid) == 0:
        return {"p05": float("nan"), "p50": float("nan"), "p95": float("nan"),
                "p99": float("nan"), "mean": float("nan"), "std": float("nan"),
                "distribution": valid, "n_random": n_random, "n_valid": n_valid}
    return {
        "p05": float(np.percentile(valid, 5)),
        "p50": float(np.percentile(valid, 50)),
        "p95": float(np.percentile(valid, 95)),
        "p99": float(np.percentile(valid, 99)),
        "mean": float(valid.mean()),
        "std": float(valid.std(ddof=0)),
        "distribution": valid,
        "n_random": n_random,
        "n_valid": int(n_valid),
    }


def pct_vs_random(actual: float, distribution: np.ndarray) -> float:
    """Fraction of random samples strictly less than `actual`.

    零信号账本(随机抽样中的一个样本):pct_vs_random ~ U[0, 1](KS p > 0.05)。
    埋了信号的账本:实际远超随机主体,pct_vs_random > 0.95。
    全部样本 NaN ⇒ NaN。
    """
    if len(distribution) == 0 or np.isnan(actual):
        return float("nan")
    return float((distribution < actual).mean())


def is_outlier(actual: float, distribution: np.ndarray, q: float = 0.99) -> bool:
    """actual > distribution 的 q 分位 ⇒ True。"""
    if len(distribution) == 0 or np.isnan(actual):
        return False
    return bool(actual > float(np.percentile(distribution, q * 100)))


@dataclass(frozen=True)
class RandomBookSpec:
    """T-069 用的随机组合 spec:每一本账的「构造规则」,与 compute_rr_matrix 的 book → spec 一一对应。

    Per T-069 acceptance.check:
      - 同宇宙:由调用方提供 universe_returns(spec 不存 panel 数据,纯函数读外部 panel)
      - 同底层加权:β+ / 代币化 / beta_core = 'equal';cis_tilt = 'market_cap'
      - 同持仓数:n_positions(default = 12)
      - 同换手:turnover_days(default = 7)
      - 同单币上限:single_name_cap(default = 0.40)
    """
    book_id: str
    weighting: str                      # 'equal' or 'market_cap'
    n_positions: int = DEFAULT_N_POSITIONS
    single_name_cap: float = DEFAULT_SINGLE_NAME_CAP
    turnover_days: int = DEFAULT_TURNOVER_DAYS


# 默认 book → weighting 映射(per T-069 acceptance.check)
DEFAULT_BOOK_WEIGHTING: dict[str, str] = {
    "beta_core":         "equal",
    "beta_plus_w":       "equal",
    "beta_plus_m":       "equal",
    "tokenization_tilt": "equal",
    "cis_tilt":          "market_cap",
    # 其它(cap / hl / ④ / event)暂未指定 → fallback equal
}


def compute_outlier_table(
    book_specs: dict[str, RandomBookSpec],
    panel_returns: pd.DataFrame,        # 共同 universe 的日收益宽表
    book_excess: dict[str, pd.Series],  # book → (cell 无关的)excess 时间序列
    cell_membership: dict[str, pd.Series], # cell_id → (DatetimeIndex 上 bool)
    n_random: int = 1000,
    seed: int = 42,
) -> pd.DataFrame:
    """为每本账本 × 格子一行,跑 T-069 随机基准 + outlier。

    Parameters
    ----------
    book_specs      : {book_id: spec}
    panel_returns   : 资产日收益宽表(共同 universe,NaN = 当天不可投)
    book_excess     : {book_id: Pd.Series of excess per day}(routinely 从 compute_rr_matrix 提供)
    cell_membership : {cell_id: bool Series on same dates}(cell_id 例: 'trend_vol=UP_HI' / 'macro=RISK_ON&fomc=no')
    n_random        : 每格随机组合数(默认 1000,per T-069 acceptance.check)
    seed            : RNG 主种子(per 算法 determinism)

    Returns
    -------
    DataFrame with cols:
        d, book_id, cell, cell_id, n_days,
        actual_excess, p05, p50, p95, p99, distribution,
        pct_vs_random, is_outlier
    """
    rows: list[dict] = []
    n_cols = panel_returns.shape[1]
    if n_cols == 0:
        return pd.DataFrame()

    for book_id, spec in book_specs.items():
        if book_id not in book_excess:
            continue
        ex = book_excess[book_id].dropna()
        if ex.empty:
            continue

        for cell_id, mask in cell_membership.items():
            # 屏蔽那些日期
            dates_in_cell = set(mask.index[mask])
            ex_cell = ex[ex.index.isin(dates_in_cell)]
            if len(ex_cell) < 2:
                continue
            actual_excess = float(ex_cell.mean())
            cell_dates = pd.DatetimeIndex(ex_cell.index)
            rets_cell = panel_returns.reindex(cell_dates).dropna(how="all")
            if rets_cell.empty or rets_cell.shape[1] == 0:
                continue

            bl = compute_random_baseline(
                rets=rets_cell,
                n_positions=min(spec.n_positions, rets_cell.shape[1]),
                weighting=spec.weighting,
                single_name_cap=spec.single_name_cap,
                turnover_days=spec.turnover_days,
                n_random=n_random,
                seed=seed + _stable(book_id, cell_id),
            )
            dist = bl["distribution"]
            pv = pct_vs_random(actual_excess, dist)
            outlier = is_outlier(actual_excess, dist, q=0.99)

            rows.append({
                "d": pd.Timestamp.now(tz=None).normalize(),
                "book_id": book_id,
                "cell": cell_id,
                "n_days": int(len(ex_cell)),
                "actual_excess": actual_excess,
                "p05": bl["p05"], "p50": bl["p50"], "p95": bl["p95"], "p99": bl["p99"],
                "pct_vs_random": pv,
                "is_outlier": bool(outlier),
            })
    return pd.DataFrame(rows)


def compute_rr_matrix(
    book_navs: dict[str, pd.Series],
    bench_nav: pd.Series,
    state_daily: Optional[pd.DataFrame],
    fomc_dates: Iterable[date],
    as_of: pd.Timestamp,
    block_size: int = 20,
    n_bootstrap: int = 1000,
    shrinkage_k: float = 30.0,
    annualization: int = DEFAULT_ANNUALIZATION,
    n_variants: Optional[dict[str, int]] = None,
    weights_history: Optional[dict[str, pd.DataFrame]] = None,
    seed: int = 42,
) -> pd.DataFrame:
    """Per SPEC §5:每本账本 × 每个 cell 一个分布行。
    cell = (regime ∈ REGIMES + UNKNOWN_REGIME) × fomc ∈ FOMC_VALUES = 14 cells/strategy。

    Parameters
    ----------
    book_navs     : {strategy_id: NAV index(DatetimeIndex, 升序)}
    bench_nav     : ① registry.core_nav NAV index(per §Seth-1006d #4)
                    = core_alpha_daily 回放 + core_cap 前向同一序列
    state_daily   : (d, entity, feature, value) — T-048 long format;None = 全缺
    fomc_dates    : iterable of date — FOMC 会议日(2022-2026 共 40 次)
    as_of         : UTC 重算日
    block_size    : bootstrap 块大小(per §2 step 3)
    n_bootstrap   : bootstrap 次数
    shrinkage_k   : 经验贝叶斯 K(per §2 step 4)
    annualization : 年化系数(per §10.7,默认 365 = crypto 7×24)
    n_variants    : strategy family 映射(None = DEFAULT_N_VARIANTS)
    weights_history: {strategy_id: weights df};None = turnover = NaN
    seed          : bootstrap RNG 种子(per §5 determinism)

    Returns
    -------
    DataFrame with cols:
        d, strategy_id, cell, n_days, excess_mean, ci_lo, ci_hi, p_pos,
        beta, rel_maxdd, turnover, n_variants_tried

    分工(per §5.2 / §Seth-1006d #6):
        本函数输出 cell = 分布(excess_mean + p_pos + n_days + CI),用于描述 / 备份。
        L3 配置层准入 = l3-v2 任意时刻 ci_lo > 0,**不**由本函数判定。
    """
    as_of = pd.Timestamp(as_of)
    if as_of.tzinfo is not None:
        as_of = as_of.tz_localize(None)   # 统一 UTC naive
    nv = n_variants if n_variants is not None else DEFAULT_N_VARIANTS

    # 1. 状态表(per SPEC §3.1 + §5.1)
    state_panel = _state_panel_daily(state_daily, as_of)

    # 1.1 派生 regime_per_day(per §3.2)
    regime_per_day = _derive_regime_per_day(state_panel)

    # 1.2 派生 trend_vol_per_day(per T-068 acceptance.check:主格子 = 价格特征按时点)
    trend_vol_per_day = _derive_trend_vol_per_day(state_panel)

    # 2. FOMC 窗口(per SPEC §3.3)
    fomc_set = _fomc_window_dates(fomc_dates, window=4)

    # 3. 基准收益(对 ① registry.core_nav)
    bench_ret = bench_nav.pct_change().dropna()
    if bench_ret.empty:
        raise ValueError("bench_nav 没有任何收益点 — 无法评估")

    # 4. 全样本 mean + 真实 CI(per §Seth-1006d #5)
    # 用 block bootstrap 计算,不用单点;不可靠时 None
    full_sample_excess: dict[str, float] = {}
    full_sample_ci: dict[str, tuple[float | None, float | None]] = {}
    for sid, nav in book_navs.items():
        if sid in EXCLUDED_BOOKS:
            continue
        if nav is None or nav.empty:
            continue
        br = nav.pct_change().dropna()
        br, bx = br.align(bench_ret, join="inner")
        excess = (br - bx).dropna()
        if excess.empty:
            continue
        seed_full = seed + _stable(sid, "FULL_SAMPLE")
        em, lo, hi = _block_bootstrap_ci(excess, block_size=block_size,
                                         n_bootstrap=n_bootstrap, seed=seed_full)
        full_sample_excess[sid] = em
        full_sample_ci[sid] = (lo if not math.isnan(lo) else None,
                               hi if not math.isnan(hi) else None)

    # 5. 遍历每本有效账本
    rows: list[dict] = []
    for sid, nav in book_navs.items():
        if sid in EXCLUDED_BOOKS:
            continue
        if nav is None or nav.empty:
            continue

        # 5.1 收益与基准对齐
        book_ret = nav.pct_change().dropna()
        book_ret, bench_aligned = book_ret.align(bench_ret, join="inner")
        excess_all = (book_ret - bench_aligned).dropna()
        if excess_all.empty:
            continue

        # 5.2 β + rel_maxdd(per §2 step 5)
        beta = _beta_calc(book_ret, bench_aligned)
        maxdd_book = _max_drawdown(nav)
        _bw = bench_nav[(bench_nav.index >= nav.index.min()) & (bench_nav.index <= nav.index.max())]
        maxdd_bench = _max_drawdown(_bw) if len(_bw) >= 2 else float("nan")   # 同一窗口(S-496)
        rel_maxdd = maxdd_book - maxdd_bench

        # 5.3 turnover(per §2 step 5)
        wh = (weights_history or {}).get(sid)
        turnover = _turnover_annual(wh)

        # 5.4 全样本 excess_mean + CI(per §Seth-1006d #5)
        full_mean = full_sample_excess.get(sid, 0.0)
        full_ci_lo, full_ci_hi = full_sample_ci.get(sid, (None, None))

        # 5.5 切片 cell — 用 regime_per_day + trend_vol_per_day + FOMC 维度
        # merged = excess_all + regime + trend_vol + fomc yes/no
        df = pd.DataFrame({"ret": excess_all})
        df["d"] = df.index
        # join regime
        if not regime_per_day.empty:
            merged = df.join(regime_per_day.rename("regime"), how="left")
        else:
            merged = df.copy()
            merged["regime"] = UNKNOWN_REGIME  # 全缺状态 → UNKNOWN(per §Seth-1006d #1)
        # 缺 regime → UNKNOWN
        merged["regime"] = merged["regime"].fillna(UNKNOWN_REGIME)
        # join trend_vol(T-068:主格子);缺 dist_200 / vol_pct_3y ⇒ UNKNOWN
        if not trend_vol_per_day.empty:
            merged = merged.join(trend_vol_per_day.rename("trend_vol"), how="left")
        else:
            merged["trend_vol"] = TREND_VOL_UNKNOWN
        merged["trend_vol"] = merged["trend_vol"].fillna(TREND_VOL_UNKNOWN)
        # FOMC 维度
        merged["fomc"] = merged.index.map(
            lambda d: "yes" if pd.Timestamp(d) in fomc_set else "no"
        )

        # 5.6a trend_vol 主格子(per T-068:6 格 = 2 trend × 3 vol,不计 FOMC;切点常数 1/3, 2/3)
        for trend in TREND_BUCKETS:
            for volb in VOL_BUCKETS:
                tv_label = f"{trend}_{volb}"
                cell_label = f"trend_vol={tv_label}"
                cell_mask = merged["trend_vol"] == tv_label
                cell_ret = merged.loc[cell_mask, "ret"].dropna()

                n_days = int(len(cell_ret))
                if n_days < 1:
                    continue

                seed_this = seed + _stable(sid, "TV", tv_label)
                excess_mean, ci_lo, ci_hi = _block_bootstrap_ci(
                    cell_ret, block_size=block_size, n_bootstrap=n_bootstrap, seed=seed_this
                )
                p_pos = _p_pos(cell_ret, block_size=block_size, n_bootstrap=n_bootstrap, seed=seed_this)

                excess_mean_ann = excess_mean * annualization
                ci_lo_ann = ci_lo * annualization if not math.isnan(ci_lo) else float("nan")
                ci_hi_ann = ci_hi * annualization if not math.isnan(ci_hi) else float("nan")

                if n_days < shrinkage_k:
                    shrink = n_days / (n_days + shrinkage_k)
                    excess_mean_ann = shrink * excess_mean_ann + (1 - shrink) * full_mean * annualization
                    if full_ci_lo is not None:
                        ci_lo_ann = shrink * ci_lo_ann + (1 - shrink) * full_ci_lo * annualization
                    if full_ci_hi is not None:
                        ci_hi_ann = shrink * ci_hi_ann + (1 - shrink) * full_ci_hi * annualization

                if math.isnan(ci_lo_ann):
                    ci_lo_out: float | None = None
                else:
                    ci_lo_out = ci_lo_ann
                if math.isnan(ci_hi_ann):
                    ci_hi_out: float | None = None
                else:
                    ci_hi_out = ci_hi_ann

                rows.append({
                    "d": as_of,
                    "strategy_id": sid,
                    "cell": cell_label,
                    "n_days": n_days,
                    "excess_mean": excess_mean_ann,
                    "ci_lo": ci_lo_out,
                    "ci_hi": ci_hi_out,
                    "p_pos": p_pos,
                    "beta": beta,
                    "rel_maxdd": rel_maxdd,
                    "turnover": turnover,
                    "n_variants_tried": nv.get(sid, 1),
                })

        # 5.6 遍历 cell — 6 类 + UNKNOWN × yes/no(per T-068:保留 macro= 前缀的描述格)
        all_regimes = list(REGIMES) + [UNKNOWN_REGIME]
        for regime in all_regimes:
            for fomc_v in FOMC_VALUES:
                cell_label = f"macro={regime}&fomc={fomc_v}"
                cell_mask = (merged["regime"] == regime) & (merged["fomc"] == fomc_v)
                cell_ret = merged.loc[cell_mask, "ret"].dropna()

                n_days = int(len(cell_ret))
                if n_days < 1:
                    continue

                # bootstrap + p_pos(per §2 step 3)
                seed_this = seed + _stable(sid, regime, fomc_v)
                excess_mean, ci_lo, ci_hi = _block_bootstrap_ci(
                    cell_ret, block_size=block_size, n_bootstrap=n_bootstrap, seed=seed_this
                )
                p_pos = _p_pos(cell_ret, block_size=block_size, n_bootstrap=n_bootstrap, seed=seed_this)

                # 年化(per §10.7)
                excess_mean_ann = excess_mean * annualization
                ci_lo_ann = ci_lo * annualization if not math.isnan(ci_lo) else float("nan")
                ci_hi_ann = ci_hi * annualization if not math.isnan(ci_hi) else float("nan")

                # 小样本收缩(per §2 step 4)
                if n_days < shrinkage_k:
                    shrink = n_days / (n_days + shrinkage_k)
                    excess_mean_ann = shrink * excess_mean_ann + (1 - shrink) * full_mean * annualization
                    if full_ci_lo is not None:
                        ci_lo_ann = shrink * ci_lo_ann + (1 - shrink) * full_ci_lo * annualization
                    if full_ci_hi is not None:
                        ci_hi_ann = shrink * ci_hi_ann + (1 - shrink) * full_ci_hi * annualization

                # NaN → None for JSON 友好
                if math.isnan(ci_lo_ann):
                    ci_lo_out: float | None = None
                else:
                    ci_lo_out = ci_lo_ann
                if math.isnan(ci_hi_ann):
                    ci_hi_out: float | None = None
                else:
                    ci_hi_out = ci_hi_ann

                rows.append({
                    "d": as_of,
                    "strategy_id": sid,
                    "cell": cell_label,
                    "n_days": n_days,
                    "excess_mean": excess_mean_ann,
                    "ci_lo": ci_lo_out,
                    "ci_hi": ci_hi_out,
                    "p_pos": p_pos,
                    "beta": beta,
                    "rel_maxdd": rel_maxdd,
                    "turnover": turnover,
                    "n_variants_tried": nv.get(sid, 1),
                })

    return pd.DataFrame(rows)


# ── I/O(Seth,S-496):读登记表与状态层,整表重算写 rr_matrix_daily ───────────────────

TABLE = "rr_matrix_daily"
WRITES_TABLES = (TABLE,)
CODE_REF = "T-045 rr_matrix v0.6+S-496"


def rows_for_db(df: pd.DataFrame, as_of: pd.Timestamp) -> list[dict]:
    """DataFrame → 可写库的行:日期写 ISO,NaN / inf 写 None(S-489:非有限数不进 JSON)。"""
    out = []
    now = datetime.now(timezone.utc).isoformat()
    for r in df.to_dict("records"):
        row = {}
        for k, v in r.items():
            if k == "d":
                v = pd.Timestamp(as_of).date().isoformat()
            elif isinstance(v, (float, np.floating)):
                v = float(v) if math.isfinite(float(v)) else None
            elif isinstance(v, (np.integer,)):
                v = int(v)
            row[k] = v
        row["code_ref"] = CODE_REF
        row["computed_at"] = now
        out.append(row)
    return out


async def run_once() -> dict:
    """每天一份:as_of = ① 最新一天。读不到 ① 或状态层 ⇒ 不写(读不到 ≠ 没有)。"""
    import asyncio
    from src.api.store import supabase_upsert_table
    from src.data.accounting.registry import load_navs
    from src.data.style.header import _read_all

    navs, _bench = await load_navs()
    from src.data.accounting.registry import core_nav
    bench = await core_nav(start="2022-01-01")
    if bench is None or bench.dropna().empty:
        return {"ok": False, "refused": False, "written": 0, "reason": "① NAV 读不到 —— 不出 rr_matrix"}
    as_of = pd.Timestamp(bench.dropna().index.max())
    # 10-16:T-068 的 6 个价格特征格子只在 compute_rr_matrix 里算,这里的读取漏了 dist_200 / vol_pct_3y ——
    # 于是 trend_vol 全是 UNKNOWN、6 格一行都不写(上线后 rr_matrix_daily 只有 macro 格)。
    feats = ["regime_coverage_30d"] + list(REGIME_SHARE_FEATURES) + [STATE_DIST_200_FEATURE, STATE_VOL_PCT_3Y_FEATURE]
    st = await _read_all("state_daily", {"select": "d,entity,feature,value", "entity": "eq.panel",
                                         "feature": "in.(" + ",".join(feats) + ")", "order": "d.asc"})
    if not st:
        return {"ok": False, "refused": False, "written": 0, "reason": "state_daily 读不到 —— 不出 rr_matrix"}
    sd = pd.DataFrame(st)
    sd["d"] = pd.to_datetime(sd["d"])
    books = {k: v.dropna().sort_index() for k, v in navs.items() if v is not None and not v.dropna().empty}
    df = await asyncio.to_thread(compute_rr_matrix, books, bench.dropna().sort_index(), sd,
                                 FOMC_DECISION_DATES, as_of)
    rows = rows_for_db(df, as_of)
    for i in range(0, len(rows), 1000):
        res = await supabase_upsert_table(TABLE, rows[i:i + 1000], on_conflict="d,strategy_id,cell")
        if not res.ok:
            return {"ok": False, "refused": False, "written": i, "reason": f"写入失败:{res.why}"}
    return {"ok": True, "refused": False, "written": len(rows), "as_of": as_of.date().isoformat(),
            "reason": f"{as_of.date()}:{df['strategy_id'].nunique() if len(df) else 0} 本账 × 格子 = {len(rows)} 行"}
