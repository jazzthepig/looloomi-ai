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

from datetime import date, datetime, timezone
from typing import Iterable, Optional
import math
import sys
import zlib

import numpy as np
import pandas as pd


# 11 有效账本(per SPEC §4.1)+ family + n_variants_tried
DEFAULT_N_VARIANTS: dict[str, int] = {
    "core_cap": 3,         # cap_a1 + cap_a05 + ew_a0
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
    """Per SPEC §3.1 + §5.1:取 d ≤ as_of_state, entity='panel', features = 6 shares + coverage。
    PIT 严格 — 过线直接 throw(per SPEC §1.3)。

    Returns: wide-form DataFrame with columns:
        d, regime_share_30d:EASING, regime_share_30d:NEUTRAL, ..., regime_coverage_30d
    (一行 / 日;缺分量取 None)
    """
    if state_daily is None or state_daily.empty:
        return pd.DataFrame(columns=["d"] + list(REGIME_SHARE_FEATURES) + ["regime_coverage_30d"])
    required = {"d", "entity", "feature", "value"}
    missing = required - set(state_daily.columns)
    if missing:
        raise ValueError(f"state_daily 缺列:{missing};期望至少 {required}")
    sd = state_daily[state_daily["d"] <= as_of].copy()
    panel = sd[sd["entity"] == "panel"]
    if panel.empty:
        return pd.DataFrame(columns=["d"] + list(REGIME_SHARE_FEATURES) + ["regime_coverage_30d"])

    # 只保留 regime 相关 features
    keep = set(REGIME_SHARE_FEATURES) | {"regime_coverage_30d"}
    panel_filt = panel[panel["feature"].isin(keep)]

    pivot = panel_filt.pivot_table(
        index="d", columns="feature", values="value", aggfunc="last"
    )
    pivot = pivot.reset_index()
    # 确保所有列都存在(缺则 NaN)
    for col in list(REGIME_SHARE_FEATURES) + ["regime_coverage_30d"]:
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


def _block_bootstrap_ci(ret_series: pd.Series, block_size: int = 20, n_bootstrap: int = 1000,
                        ci: float = 0.95, seed: int | None = None) -> tuple[float, float, float]:
    """Per SPEC §2 step 3 + §10.5:块 bootstrap 95% CI + excess_mean。

    Block size 20 天 ≈ 1 个月(per §10.5 Politis & Romano + 业界惯例)。
    Returns: (excess_mean, ci_lo, ci_hi)。
    当 n < block_size 或不可靠时,ci_lo / ci_hi = NaN(per §Seth-1006d #5:不写单点)。
    """
    arr = ret_series.dropna().to_numpy()
    n = len(arr)
    if n < block_size:
        # 样本不够一个 block:返回 NaN CI(per §Seth-1006d #5)
        return float(arr.mean()) if n > 0 else 0.0, float("nan"), float("nan")
    n_blocks = max(1, n // block_size)
    rng = np.random.default_rng(seed)
    boot_means = np.empty(n_bootstrap, dtype=float)
    for i in range(n_bootstrap):
        idx = rng.integers(0, n_blocks, size=n_blocks)
        sample = np.concatenate([arr[j * block_size:(j + 1) * block_size] for j in idx])
        boot_means[i] = sample.mean()
    excess_mean = float(boot_means.mean())
    alpha = 1 - ci
    ci_lo = float(np.quantile(boot_means, alpha / 2))
    ci_hi = float(np.quantile(boot_means, 1 - alpha / 2))
    return excess_mean, ci_lo, ci_hi


def _p_pos(ret_series: pd.Series, block_size: int = 20, n_bootstrap: int = 1000, seed: int | None = None) -> float:
    """bootstrap 里超额 > 0 的比例(per SPEC §2 step 3)。"""
    arr = ret_series.dropna().to_numpy()
    n = len(arr)
    if n == 0:
        return float("nan")
    if n < block_size:
        block_size = max(1, n)
    n_blocks = max(1, n // block_size)
    rng = np.random.default_rng(seed)
    p_pos_count = 0
    for _ in range(n_bootstrap):
        idx = rng.integers(0, n_blocks, size=n_blocks)
        sample = np.concatenate([arr[j * block_size:(j + 1) * block_size] for j in idx])
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

        # 5.5 切片 cell — 用 regime_per_day + FOMC 维度
        # merged = excess_all + regime_per_day + fomc yes/no
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
        # FOMC 维度
        merged["fomc"] = merged.index.map(
            lambda d: "yes" if pd.Timestamp(d) in fomc_set else "no"
        )

        # 5.6 遍历 cell — 6 类 + UNKNOWN × yes/no
        all_regimes = list(REGIMES) + [UNKNOWN_REGIME]
        for regime in all_regimes:
            for fomc_v in FOMC_VALUES:
                cell_label = f"regime={regime}&fomc={fomc_v}"
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
    feats = ["regime_coverage_30d"] + list(REGIME_SHARE_FEATURES)
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
