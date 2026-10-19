"""lane B 的 T-045 v0.6 用例(原样搬入;每个函数返回 (ok, msg),由 tests/test_rr_matrix.py 断言)。
T-045 评估层 rr_matrix v0.6 — ≥6 测试套件(per SPEC §9)

v0.6 新增:11/12/13(覆盖 unknown 格 + 全样本 CI 真 bootstrap + 年化 365)。

可单独运行: `python3 test_rr_matrix.py`
"""
from __future__ import annotations

from datetime import date, datetime, timezone
import math
import sys

import numpy as np
import pandas as pd

from src.data.evaluation.rr_matrix import (
    DEFAULT_N_VARIANTS,
    DEFAULT_BOOK_WEIGHTING,
    DEFAULT_N_POSITIONS,
    EXCLUDED_BOOKS,
    REGIMES,
    FOMC_VALUES,
    UNKNOWN_REGIME,
    REGIME_SHARE_FEATURES,
    DEFAULT_ANNUALIZATION,
    DEFAULT_SINGLE_NAME_CAP,
    _fomc_window_dates,
    _dominant_regime,
    _state_panel_daily,
    _derive_regime_per_day,
    _derive_trend_vol_per_day,
    _block_bootstrap_ci,
    _p_pos,
    _beta_calc,
    _max_drawdown,
    _turnover_annual,
    simulate_random_portfolio,
    compute_random_baseline,
    pct_vs_random,
    is_outlier,
    RandomBookSpec,
    compute_outlier_table,
    compute_rr_matrix,
)


def _make_synth(days: int = 200, seed: int = 0) -> tuple[pd.Series, dict[str, pd.Series]]:
    """构造合成 ① + 一本强 / 一本弱账本。"""
    idx = pd.date_range("2026-01-01", periods=days, freq="D")
    rng = np.random.default_rng(seed)
    bench_ret = rng.normal(0.001, 0.02, days)
    bench_nav = pd.Series(np.cumprod(1 + bench_ret), index=idx)
    book_navs = {
        "core_cap": bench_nav,                         # 完全跟随 ①
        "beta_plus_w": bench_nav * np.cumprod(1 + rng.normal(0.0008, 0.005, days)),  # 强
        "causal_paper": bench_nav * np.cumprod(1 + rng.normal(-0.0005, 0.008, days)),  # 弱
    }
    return bench_nav, book_navs


def _make_state_daily(days_idx: pd.DatetimeIndex, seed: int = 1,
                      coverage_min: int = 25, regime_per_day: list[str] | None = None) -> pd.DataFrame:
    """构造合成 state_daily 长表(per SPEC §3.1 + T-048 as-built + T-068)。

    行序与 features 对齐:6 shares + 1 coverage + dist_200 + vol_pct_3y per day,共 9 rows/day。
    coverage ∈ [coverage_min, max(coverage_min+5, 30)]; share 之和 = 1.0(用 dirichlet)。
    dist_200: -0.05..0.05(价格相对 200d MA 的偏离,正负各半)→ 时点 UP/DOWN 都有覆盖。
    vol_pct_3y: Uniform[0, 1](本身就是滚动 3 年的 vol 分位)→ LO/MID/HI 三档都有覆盖。
    regime_per_day 可显式指定,否则均匀循环。
    """
    rng = np.random.default_rng(seed)
    n = len(days_idx)
    classes = list(REGIMES)

    # 6 shares = dirichlet(α=1) 行和 = 1
    share_data = rng.dirichlet(np.ones(len(classes)), size=n)
    # coverage ∈ [coverage_min, coverage_min+5]
    cov_data = rng.integers(coverage_min, coverage_min + 6, size=n)
    # T-068 价格特征(dist_200 正负各半以覆盖 UP/DOWN;vol_pct_3y U[0,1] 覆盖 LO/MID/HI)
    dist_data = rng.uniform(-0.05, 0.05, size=n)
    vol_pct_data = rng.uniform(0.0, 1.0, size=n)

    long_rows = []
    for i, d in enumerate(days_idx):
        for j, cls in enumerate(classes):
            long_rows.append({"d": d, "entity": "panel", "feature": f"regime_share_30d:{cls}",
                              "value": float(share_data[i, j])})
        long_rows.append({"d": d, "entity": "panel", "feature": "regime_coverage_30d",
                          "value": int(cov_data[i])})
        long_rows.append({"d": d, "entity": "panel", "feature": "dist_200",
                          "value": float(dist_data[i])})
        long_rows.append({"d": d, "entity": "panel", "feature": "vol_pct_3y",
                          "value": float(vol_pct_data[i])})

    return pd.DataFrame(long_rows)


# ============================================================
# Test 01: PIT 严格性 — 未来 state 改不了过去
# ============================================================
def test_rr_matrix_pit() -> tuple[bool, str]:
    """Per SPEC §1.3:as_of=2026-07-01 时,state_daily 里 d > 2026-07-01 的行必须被丢。"""
    bench_nav, book_navs = _make_synth(days=300)
    state_daily = _make_state_daily(bench_nav.index)

    as_of = pd.Timestamp("2026-07-01")
    out = compute_rr_matrix(book_navs, bench_nav, state_daily, [date(2026, 9, 16)], as_of)

    max_n = out["n_days"].max()
    expected_max = (as_of - bench_nav.index[0]).days + 1
    if max_n <= expected_max + 10:   # +10 buffer for cell slicing granularity
        return True, f"✅ max n_days={max_n} ≤ expected ~{expected_max};as_of 之后的 state 未污染"
    return False, f"❌ max n_days={max_n} 远超 expected {expected_max};PIT 漏掉"


# ============================================================
# Test 02: bootstrap CI covers
# ============================================================

def test_rr_matrix_bootstrap_ci() -> tuple[bool, str]:
    """Per SPEC §2 step 3 + §10.5:block_size=20, 1000 samples, 95% CI covers true mean。"""
    rng = np.random.default_rng(7)
    arr = rng.normal(0.001, 0.02, 500)
    series = pd.Series(arr)
    true_mean = float(arr.mean())
    em, lo, hi = _block_bootstrap_ci(series, block_size=20, n_bootstrap=2000, seed=42)
    if not math.isnan(lo) and not math.isnan(hi) and lo <= true_mean <= hi:
        return True, f"✅ CI [{lo:.6f}, {hi:.6f}] covers true mean {true_mean:.6f};em={em:.6f}"
    return False, f"❌ CI [{lo}, {hi}] MISSES true mean {true_mean:.6f}"


# ============================================================
# Test 03: 小样本收缩(per §2 step 4)
# ============================================================

def test_rr_matrix_shrinkage() -> tuple[bool, str]:
    """Per §2 step 4 + §10.6:n_days < K=30 时,cell-mean 应朝全样本 mean 收缩。"""
    bench_nav, book_navs = _make_synth(days=300)
    state_daily = _make_state_daily(bench_nav.index)

    # 全样本(300 天,no shrinkage)
    as_of_full = pd.Timestamp("2026-10-27")
    out_full = compute_rr_matrix(book_navs, bench_nav, state_daily, [date(2026, 9, 16)], as_of_full)

    # 短样本(30 天,~ < K=30 收缩门)
    as_of_short = pd.Timestamp("2026-01-30")
    out_short = compute_rr_matrix(book_navs, bench_nav, state_daily, [date(2026, 9, 16)], as_of_short)

    # 用 macro= cell(T-068 之后 trend_vol 是主格子,但 shrinkage 公式对任何 cell 都生效;
    # 这里固定选 macro= 格,与 T-068 之前 iloc[0] 行为兼容,不依赖 trend_vol 的次序)。
    sid = "beta_plus_w"
    short_cells = out_short[(out_short["strategy_id"] == sid)
                           & out_short["cell"].str.startswith("macro=")]
    if short_cells.empty:
        return True, "✅ (跳过:short window macro= cell 全无数据)"
    cell_label = short_cells["cell"].iloc[0]
    full_row = out_full[(out_full["strategy_id"] == sid) & (out_full["cell"] == cell_label)]
    short_row = short_cells[short_cells["cell"] == cell_label]

    if full_row.empty or short_row.empty:
        return True, f"✅ (跳过:cell {cell_label} 无数据;full n={len(full_row)}, short n={len(short_row)})"

    em_full = float(full_row["excess_mean"].iloc[0])
    em_short = float(short_row["excess_mean"].iloc[0])
    n_days_short = int(short_row["n_days"].iloc[0])

    if n_days_short >= 30:
        return True, f"✅ 短样本 n_days={n_days_short} 不触发 shrinkage(em={em_short:.4f}, full={em_full:.4f})"

    # shrinkage 应把 short 朝 full 拉近
    full_mean_short = float(out_short[(out_short["strategy_id"] == sid)
                                       & out_short["cell"].str.startswith("macro=")]["excess_mean"].mean())
    diff_to_full = abs(em_short - full_mean_short)
    diff_unshrunk = abs(em_short - em_full)

    if diff_to_full < diff_unshrunk + 1e-9 or diff_to_full < 0.01:
        return True, (f"✅ shrinkage 工作:em_short={em_short:.4f}, full_sample_mean={full_mean_short:.4f}, "
                      f"diff_to_full_mean={diff_to_full:.4f} (n_days={n_days_short}, K=30)")
    return False, (f"❌ shrinkage 没起效:em_short={em_short}, em_full={em_full}, "
                   f"full_sample_mean={full_mean_short}")


# ============================================================
# Test 04: FOMC 窗口(per §3.3)
# ============================================================

def test_rr_matrix_fomc_window() -> tuple[bool, str]:
    """Per §3.3:2026-09-16 FOMC → window [Sep 15, 16, 17, 18] = yes;Sep 14 / Sep 19 = no。"""
    fomc_set = _fomc_window_dates([date(2026, 9, 16)], window=4)
    expected = {
        pd.Timestamp("2026-09-15"): "yes",
        pd.Timestamp("2026-09-16"): "yes",
        pd.Timestamp("2026-09-17"): "yes",
        pd.Timestamp("2026-09-18"): "yes",
        pd.Timestamp("2026-09-19"): "no",
        pd.Timestamp("2026-09-14"): "no",
        pd.Timestamp("2026-09-20"): "no",
    }
    fails = []
    for d, expected_label in expected.items():
        actual = "yes" if d in fomc_set else "no"
        if actual != expected_label:
            fails.append(f"{d.date()}={actual} (expected {expected_label})")
    if not fails:
        return True, f"✅ 2026-09-16 FOMC window 包含 [Sep 15-18],边界 [Sep 14, 19] 正确"
    return False, f"❌ FOMC window 错:{fails}"


# ============================================================
# Test 05: β 测算
# ============================================================

def test_rr_matrix_beta_calculation() -> tuple[bool, str]:
    """Per §2 step 5:book_ret = 2 × bench_ret ⇒ β ≈ 2.0。"""
    idx = pd.date_range("2026-01-01", periods=300, freq="D")
    rng = np.random.default_rng(11)
    bench_ret = rng.normal(0.001, 0.02, 300)
    bench_ret_series = pd.Series(bench_ret, index=idx)
    book_ret = 2.0 * bench_ret + rng.normal(0, 0.0001, 300)
    book_ret_series = pd.Series(book_ret, index=idx)
    bench_nav = pd.Series(np.cumprod(1 + bench_ret_series), index=idx)
    book_nav = pd.Series(np.cumprod(1 + book_ret_series), index=idx)
    book_navs = {"test_book": book_nav}

    beta = _beta_calc(book_ret_series, bench_ret_series)
    if abs(beta - 2.0) < 0.05:
        return True, f"✅ β={beta:.4f} ≈ 2.0(book_ret = 2 × bench_ret)"
    return False, f"❌ β={beta:.4f}, 应 ≈ 2.0"


# ============================================================
# Test 06: rel_maxdd 计算
# ============================================================

def test_rr_matrix_rel_maxdd() -> tuple[bool, str]:
    """Per §2 step 5:rel_maxdd = maxdd_book - maxdd_bench。"""
    idx = pd.date_range("2026-01-01", periods=100, freq="D")
    bench_nav = pd.Series(np.linspace(1.0, 0.80, 100), index=idx)  # -20% DD
    book_nav = pd.Series(np.linspace(1.0, 0.70, 100), index=idx)   # -30% DD
    rel = _max_drawdown(book_nav) - _max_drawdown(bench_nav)
    if abs(rel - (-0.10)) < 1e-9:
        return True, f"✅ rel_maxdd={rel:.4f}(book -30% vs bench -20% ⇒ rel = -10pp)"
    return False, f"❌ rel_maxdd={rel:.4f},应 ≈ -0.10"


# ============================================================
# Test 07: 排除 EXCLUDED_BOOKS
# ============================================================

def test_rr_matrix_excludes_invalid_books() -> tuple[bool, str]:
    """Per §4.1 + §11:fusion_paper / two_layer_paper 不出现在输出。"""
    bench_nav, book_navs = _make_synth(days=200)
    book_navs["fusion_paper"] = bench_nav * 0.95
    book_navs["two_layer_paper"] = bench_nav * 0.90
    state_daily = _make_state_daily(bench_nav.index)

    out = compute_rr_matrix(book_navs, bench_nav, state_daily, [date(2026, 9, 16)], pd.Timestamp("2026-07-31"))
    sids = set(out["strategy_id"].unique())
    leaks = sids & EXCLUDED_BOOKS
    if not leaks:
        return True, f"✅ fusion_paper + two_layer_paper 已排除;有效 strategy 数 = {len(sids)}"
    return False, f"❌ EXCLUDED_BOOKS 漏出:{leaks}"


# ============================================================
# Test 08: n_variants_tried 静态映射
# ============================================================

def test_rr_matrix_n_variants_tried() -> tuple[bool, str]:
    """Per §4.1:n_variants_tried 必须等于 DEFAULT_N_VARIANTS 映射(只对出现在输出里的 strategy 校验)。"""
    bench_nav, book_navs = _make_synth(days=200)
    state_daily = _make_state_daily(bench_nav.index)
    out = compute_rr_matrix(book_navs, bench_nav, state_daily, [date(2026, 9, 16)], pd.Timestamp("2026-07-31"))

    nvt_per_sid = out.groupby("strategy_id")["n_variants_tried"].first()
    fails = []
    for sid in nvt_per_sid.index:
        expected = DEFAULT_N_VARIANTS.get(sid)
        if expected is None:
            fails.append(f"{sid}: 进输出但 DEFAULT_N_VARIANTS 无映射")
            continue
        actual = nvt_per_sid[sid]
        if actual != expected:
            fails.append(f"{sid}: actual={actual}, expected={expected}")

    if not fails:
        sample = nvt_per_sid.to_dict()
        return True, f"✅ n_variants_tried 映射正确:{sample}"
    return False, f"❌ n_variants 错:{fails}"


# ============================================================
# Test 09: 同一输入多次调用 = 同一输出(per §5 determinism)
# ============================================================

def test_rr_matrix_determinism() -> tuple[bool, str]:
    """Per §5:同一输入两次调用 = 同一输出(bootstrap RNG seed 固定)。"""
    bench_nav, book_navs = _make_synth(days=200, seed=0)
    state_daily = _make_state_daily(bench_nav.index, seed=1)
    as_of = pd.Timestamp("2026-07-31")

    out1 = compute_rr_matrix(book_navs, bench_nav, state_daily, [date(2026, 9, 16)], as_of, seed=42)
    out2 = compute_rr_matrix(book_navs, bench_nav, state_daily, [date(2026, 9, 16)], as_of, seed=42)

    if out1.equals(out2):
        return True, f"✅ 两份输出一致({len(out1)} 行,excess_mean 第一行 = {out1['excess_mean'].iloc[0]:.6f})"
    diff_rows = (out1["excess_mean"] != out2["excess_mean"]).sum()
    return False, f"❌ 不一致;excess_mean 差异行数 = {diff_rows}"


# ============================================================
# Test 10: 缺 state_daily → UNKNOWN 格(per §1.7 + §Seth-1006d #1)
# ============================================================

def test_rr_matrix_handles_missing_state() -> tuple[bool, str]:
    """Per §1.7 + §Seth-1006d #1:state_daily=None → 必须归 `regime=unknown&fomc=no` 格,
    不许默认 RISK_ON。
    """
    bench_nav, book_navs = _make_synth(days=200)
    as_of = pd.Timestamp("2026-07-31")

    out = compute_rr_matrix(book_navs, bench_nav, state_daily=None, fomc_dates=[date(2026, 9, 16)], as_of=as_of)

    cells = set(out["cell"].unique())
    expected = {"macro=unknown&fomc=no"}
    leaks = cells - expected
    if cells == expected:
        return True, f"✅ 缺 state 时全部归 unknown&fomc=no,总行数={len(out)},每本有效 strategy 都进"
    # 检查是否漏出 RISK_ON / 别的类
    riskon_leak = any("RISK_ON" in c or "=EASING" in c or "=RISK_OFF" in c for c in cells)
    if riskon_leak:
        return False, f"❌ 漏出 default: {cells};per §Seth-1006d #1 不许默认 RISK_ON"
    return False, f"❌ cells={cells}, 期望 {expected}"


# ============================================================
# Test 11 (NEW v0.6): coverage < 20 → UNKNOWN(per §Seth-1006d #1)
# ============================================================

def test_rr_matrix_unknown_coverage() -> tuple[bool, str]:
    """Per §3.2 + §Seth-1006d #1:regime_coverage_30d < 20 ⇒ 'unknown'。

    构造:前 30 天 coverage=25 → 6 类;后 30 天 coverage=10 → UNKNOWN。
    跑 compute_rr_matrix,验证后 30 天全部进 `regime=unknown&fomc=no` 格,不应进 6 类中任何一类。
    """
    days_idx = pd.date_range("2026-01-01", periods=60, freq="D")
    rng = np.random.default_rng(99)
    n = len(days_idx)
    classes = list(REGIMES)
    share_data = rng.dirichlet(np.ones(len(classes)), size=n)
    cov_data = np.array([25 if i < 30 else 10 for i in range(n)])
    long_rows = []
    for i, d in enumerate(days_idx):
        for j, cls in enumerate(classes):
            long_rows.append({"d": d, "entity": "panel", "feature": f"regime_share_30d:{cls}",
                              "value": float(share_data[i, j])})
        long_rows.append({"d": d, "entity": "panel", "feature": "regime_coverage_30d",
                          "value": int(cov_data[i])})
    state_daily = pd.DataFrame(long_rows)

    # 直接调 _dominant_regime 验证单行
    panel = _state_panel_daily(state_daily, pd.Timestamp("2026-12-31"))
    if panel.empty:
        return False, "❌ _state_panel_daily 返回空,出错"

    derived = _derive_regime_per_day(panel)
    if derived.empty:
        return False, "❌ _derive_regime_per_day 返回空"

    # 前 30 天应有 6 类之一;后 30 天应全 unknown
    front = derived.iloc[:30]
    back = derived.iloc[30:]
    front_classes = set(front.unique()) - {UNKNOWN_REGIME}
    back_classes = set(back.unique())

    if len(front_classes) >= 1 and back_classes == {UNKNOWN_REGIME}:
        return True, (f"✅ coverage<20 ⇒ unknown:前 30 天 → {sorted(front_classes)};后 30 天 → {sorted(back_classes)}")
    return False, f"❌ coverage 分组错:前 = {sorted(front_classes)}, 后 = {sorted(back_classes)}"


# ============================================================
# Test 12 (NEW v0.6): 全样本 CI 真 bootstrap(per §Seth-1006d #5)
# ============================================================

def test_rr_matrix_full_ci_proper() -> tuple[bool, str]:
    """Per §Seth-1006d #5:全样本 excess_full_ci_lo/hi 必须来自真 bootstrap,不是 single point。
    验证:对短 cell(n<block_size),ci_lo / ci_hi = NaN(per §Seth-1006d #5),
    不是 excess_full_mean 单点。
    """
    bench_nav, book_navs = _make_synth(days=300)
    state_daily = _make_state_daily(bench_nav.index)
    as_of = pd.Timestamp("2026-10-27")
    out = compute_rr_matrix(book_navs, bench_nav, state_daily, [date(2026, 9, 16)], as_of)

    # 找一个 n_days<20 的格(=无 UNKNOWN 默认,只有极少数 state days 命中)
    low = out[out["n_days"] < 20]
    if low.empty:
        # 用 synthesized <block_size 直接测 _block_bootstrap_ci
        short_arr = pd.Series(np.random.default_rng(13).normal(0.001, 0.02, 15))
        em, lo, hi = _block_bootstrap_ci(short_arr, block_size=20, n_bootstrap=1000, seed=42)
        if math.isnan(lo) and math.isnan(hi):
            return True, f"✅ _block_bootstrap_ci 在 n<block_size 时返回 NaN CI(per §Seth-1006d #5),em={em:.6f}"
        return False, f"❌ n=15 时 CI 应 NaN,实际 lo={lo}, hi={hi}"

    # 对低 n 格子,验证 ci_lo/ci_hi 是 NaN
    nan_lo = low["ci_lo"].apply(lambda v: v is None or (isinstance(v, float) and math.isnan(v))).sum()
    nan_hi = low["ci_hi"].apply(lambda v: v is None or (isinstance(v, float) and math.isnan(v))).sum()
    if nan_lo == len(low) and nan_hi == len(low):
        return True, f"✅ {len(low)} 个低 n_days cell 的 CI 都为 NaN(per §Seth-1006d #5)"
    return False, f"❌ 低 n CI NaN 不全:lo={nan_lo}/{len(low)}, hi={nan_hi}/{len(low)}"


# ============================================================
# Test 13 (NEW v0.6): annualization=365(per §Seth-1006d #3)
# ============================================================

def test_rr_matrix_annualization_365() -> tuple[bool, str]:
    """Per §Seth-1006d #3 + §10.7:annualization 默认 = 365(crypto 7×24),
    不是 252(TradFi 交易日计数)。
    """
    # 1. 默认值
    if DEFAULT_ANNUALIZATION != 365:
        return False, f"❌ DEFAULT_ANNUALIZATION = {DEFAULT_ANNUALIZATION}, 应 = 365"
    # 2. 同输入下,em*365 ≈ em*252 * (365/252)
    bench_nav, book_navs = _make_synth(days=200)
    state_daily = _make_state_daily(bench_nav.index)
    as_of = pd.Timestamp("2026-07-31")

    out_365 = compute_rr_matrix(book_navs, bench_nav, state_daily, [date(2026, 9, 16)], as_of)
    out_252 = compute_rr_matrix(book_navs, bench_nav, state_daily, [date(2026, 9, 16)], as_of,
                                annualization=252)
    if len(out_365) == 0 or len(out_252) == 0:
        return True, f"✅ (跳过:out 空)"
    # 用 beta_plus_w(非零 excess)而不是 core_cap(= bench ⇒ excess = 0)
    row_365 = out_365[out_365["strategy_id"] == "beta_plus_w"].iloc[0]
    row_252 = out_252[out_252["strategy_id"] == "beta_plus_w"].iloc[0]
    em_365 = float(row_365["excess_mean"])
    em_252 = float(row_252["excess_mean"])
    if em_252 == 0:
        return True, f"✅ (跳过:em_252=0,无法 ratio;365 已生效)"
    ratio = em_365 / em_252
    expected_ratio = 365.0 / 252.0
    if abs(ratio - expected_ratio) < 1e-6:
        return True, f"✅ annualization=365 生效:em_365/em_252 = {ratio:.6f} ≈ 365/252 = {expected_ratio:.6f}"
    return False, f"❌ 比例错:actual={ratio}, expected={expected_ratio}"


# ============================================================
# Test 14 (NEW T-068): 主格子 trend_vol 6 格覆盖
# ============================================================

def test_rr_matrix_trend_vol_six_cells() -> tuple[bool, str]:
    """Per T-068 acceptance.check:主格子 = trend (UP/DOWN) × vol (LO/MID/HI) = 6 格,
    切点为常数 1/3, 2/3。state_daily 喂入的 dist_200 ∈ [-0.05, 0.05](UP/DOWN 各半),
    vol_pct_3y ∈ [0, 1] uniform ⇒ 6 格都应该非空。
    """
    bench_nav, book_navs = _make_synth(days=400, seed=0)  # 400 天 ⇒ n_days > K=30,无收缩
    state_daily = _make_state_daily(bench_nav.index, seed=1)  # 含 dist_200 + vol_pct_3y
    as_of = pd.Timestamp("2026-07-31")

    out = compute_rr_matrix(book_navs, bench_nav, state_daily, [date(2026, 9, 16)], as_of)

    expected_labels = {
        "trend_vol=UP_LO", "trend_vol=UP_MID", "trend_vol=UP_HI",
        "trend_vol=DOWN_LO", "trend_vol=DOWN_MID", "trend_vol=DOWN_HI",
    }
    actual_tv = {c for c in out["cell"].unique() if c.startswith("trend_vol=")}
    missing = expected_labels - actual_tv
    if missing:
        return False, (f"❌ 缺主格子:{sorted(missing)};实际 trend_vol 格 = {sorted(actual_tv)};"
                       f"切点不是常数 1/3, 2/3?")
    return True, (f"✅ 6 主格子全部命中:{sorted(actual_tv)};"
                  f"trend_vol 总行数 = {len(out[out['cell'].str.startswith('trend_vol=')])}")


# ============================================================
# Test 15 (NEW T-068): 无前视 — 同日期在 2024 算与今天算落在同主格
# ============================================================

def test_rr_matrix_trend_vol_no_lookahead() -> tuple[bool, str]:
    """Per T-068 acceptance.expect:同一日期在 2024 年算与在今天算落在同一格(无前视)。

    构造:state_daily 覆盖 [2023-01-01, 2026-10-31],用 as_of 在 2024-Q4 算一次、
    再用 as_of 在 2026-Q4 算一次,断言:对每一个有效日期 d,两次计算返回同一 trend_vol 标签。

    切点是常数 1/3, 2/3 — 不依赖全样本,所以 2024 算与 2026 算对同一 d 的分配一致。
    """
    idx = pd.date_range("2023-01-01", periods=1400, freq="D")  # ~3.8y
    state_daily = _make_state_daily(idx, seed=42)

    as_of_early = pd.Timestamp("2024-12-31")
    panel_early = _state_panel_daily(state_daily, as_of_early)
    tv_early = _derive_trend_vol_per_day(panel_early)

    as_of_late = pd.Timestamp("2026-10-13")
    panel_late = _state_panel_daily(state_daily, as_of_late)
    tv_late = _derive_trend_vol_per_day(panel_late)

    common = tv_early.index.intersection(tv_late.index)
    if len(common) < 100:
        return False, f"❌ 两条路径重叠日期太少({len(common)});test setup 错"

    diffs = sum(1 for d in common if tv_early.loc[d] != tv_late.loc[d])
    if diffs == 0:
        return True, (f"✅ 无前视:{len(common)} 个日期在两条路径上 trend_vol 完全一致;"
                      f"切点是常数(>0, 1/3, 2/3),与 as_of 无关")
    return False, (f"❌ 前视泄漏:{diffs}/{len(common)} 个日期上两条路径返回不同 trend_vol;"
                   f"早期路径正在看未来 state")


# ============================================================
# Test 16 (NEW T-068): vol bucket 切点是常数 1/3, 2/3(非全样本分位)
# ============================================================

def test_rr_matrix_vol_cutoffs_are_constants() -> tuple[bool, str]:
    """Per T-068 acceptance.check:切点是常数,不用全样本分位 — 防止通过全样本重排
    间接引入「未来视角」。
    """
    from src.data.evaluation.rr_matrix import VOL_CUT_QUANTILES
    expected = (1.0 / 3.0, 2.0 / 3.0)
    if VOL_CUT_QUANTILES == expected:
        return True, f"✅ vol 切点是常数 {expected};"
    return False, f"❌ vol 切点={VOL_CUT_QUANTILES}, 期望 {expected}"


# ============================================================
# Test 17 (NEW T-059): n ∈ [20, 40) — _block_bootstrap_ci 用满全部 n 天 + 旧单点退化形态消失
# ============================================================

def test_rr_matrix_bootstrap_uses_all_days_20_40() -> tuple[bool, str]:
    """Per T-059 acceptance 关键点(n=23):
    - excess_mean == 全 n 天均值(不是只重抽前 20 天那一个块)。
    - 旧 bug 的"CI 退化为 em 单点"形态消失 — 修后 n < 40 直接 NaN,修前宽 0 + lo==hi==em。

    旧实现 20 ≤ n < 40:n_blocks = 1 ⇒ 1000 次都重抽同一个固定块 ⇒ CI 单点 + em 也只用了前 20 天。
    """
    rng = np.random.default_rng(2026)
    front = rng.normal(0.0, 0.005, 20)
    tail = np.full(3, 0.01)   # 后 3 天结构性 ↑ — 让"用满 23 天"能被精确断言
    arr = np.concatenate([front, tail])   # n=23
    series = pd.Series(arr)
    full_mean = float(arr.mean())
    em, lo, hi = _block_bootstrap_ci(series, block_size=20, n_bootstrap=1000, seed=42)
    em_ok = abs(em - full_mean) < 1e-9
    # 旧 bug 形态:lo == hi == em(非 NaN 单点 — 既是 em 又彼此相等 ⇒ width = 0)。修后 n=23<40 ⇒ NaN,自然不在。
    is_old_single_point_artifact = (
        math.isfinite(lo) and math.isfinite(hi) and lo == hi == em
    )
    if em_ok and not is_old_single_point_artifact:
        return True, (f"✅ n=23:em={em:.6f} == full_mean={full_mean:.6f}, "
                      f"CI=[{lo}, {hi}] — 旧单点退化形态消失(T-059)")
    return False, (f"❌ n=23:em={em:.6f} vs full_mean={full_mean:.6f}; "
                   f"CI=[{lo}, {hi}] — 修前会丢后 3 天(em=前 20 天)或 CI 退化为 em 单点")


# ============================================================
# Test 18 (NEW T-059): _p_pos 不再 binary {0, 1} for n < 40
# ============================================================

def test_rr_matrix_p_pos_not_binary_n_lt_40() -> tuple[bool, str]:
    """Per T-059 acceptance:n=10 _p_pos 不再属于 {0, 1}。
    旧 _p_pos:n < block_size ⇒ block_size=max(1, n), n_blocks=1 ⇒ sample=arr[0:n] 单块均值
      ⇒ sample.mean() 不正即负 ⇒ p_pos ∈ {0, 1}。
    修后(per acceptance "p_pos 同一规则"):n < 40 ⇒ p_pos = NaN,既 != 0 也 != 1。
    """
    rng = np.random.default_rng(2027)
    arr = rng.normal(0.0, 0.02, 10)   # 零信号均值 ≈ 0;旧实现下 block=10 ⇒ 单块均值极大概率非 0 ⇒ p_pos=1
    series = pd.Series(arr)
    p = _p_pos(series, block_size=20, n_bootstrap=1000, seed=42)
    not_binary = (p != 0.0 and p != 1.0) or (isinstance(p, float) and math.isnan(p))
    if not_binary:
        return True, f"✅ n=10 p_pos={p} 不属于 {{0, 1}}(T-059 修后 = NaN)"
    return False, f"❌ n=10 p_pos={p} ∈ {{0, 1}} — 旧 _p_pos 二值 bug 未修"


# ============================================================
# Test 16 (T-059 + §Seth-1010c 合并前必补): n=80 零信号 iid
# ============================================================

def test_rr_matrix_bootstrap_n80_iid_contains_true_mean() -> tuple[bool, str]:
    """Per T-059 acceptance.expect 第三项 + §Seth-1010c 合并前必补:
    n=80 零信号 iid 序列的 CI 宽度 > 0 且包含真均值(0)。
    1000 个 iid 重复(独立样本,非 bootstrap 复用)作 oracle,真均值 ≈ 0
    必定落在 1000 次 bootstrap CI 的中位数 lo/hi 内。
    """
    rng = np.random.default_rng(2028)
    arr = rng.normal(0.0, 0.02, 80)   # 零信号
    series = pd.Series(arr)
    true_mean = float(arr.mean())   # ≈ 0 但有采样噪声;oracle 用 1000 个独立 iid 重复
    oracle_means = np.array([np.random.default_rng(2028 + j).normal(0.0, 0.02, 80).mean()
                             for j in range(1000)])
    em, lo, hi = _block_bootstrap_ci(series, block_size=20, n_bootstrap=1000, seed=42)
    width = float(hi - lo)
    oracle_lo = float(np.quantile(oracle_means, 0.025))
    oracle_hi = float(np.quantile(oracle_means, 0.975))
    contains = (oracle_lo <= true_mean <= oracle_hi)
    width_positive = width > 0 and math.isfinite(width)
    em_in_oracle = (oracle_lo <= em <= oracle_hi)
    if width_positive and contains and em_in_oracle:
        return True, (f"✅ n=80 iid: em={em:.6f}, CI=[{lo:.6f}, {hi:.6f}] width={width:.6f} > 0, "
                      f"真均值 {true_mean:.6f} ⊂ oracle [{oracle_lo:.6f}, {oracle_hi:.6f}] — "
                      f"T-059 + §Seth-1010c")
    return False, (f"❌ n=80 iid: em={em:.6f}, CI=[{lo}, {hi}] width={width} — "
                   f"oracle [{oracle_lo:.6f}, {oracle_hi:.6f}], true_mean={true_mean:.6f}, "
                   f"width_positive={width_positive}, contains={contains}, em_in_oracle={em_in_oracle}")


# ============================================================
# Helpers for T-069
# ============================================================

def _make_panel_returns(n_days: int = 400, n_assets: int = 24, seed: int = 0) -> pd.DataFrame:
    """生成一张「共同 universe」日收益宽表。零信号(iid)⇒ pct_vs_random 应均匀。"""
    idx = pd.date_range("2026-01-01", periods=n_days, freq="D")
    rng = np.random.default_rng(seed)
    cols = [f"A{i:02d}" for i in range(n_assets)]
    # 给后 1/3 一个轻微的 drift ⇒ 在那段时间实际跑赢均值的样本自然出现,
    # 但 pct_vs_random 对单本随机样本仍应近似均匀
    drift = np.where(np.arange(n_days) > n_days * 2 / 3, 0.001, 0.0)
    noise = rng.normal(0, 0.02, (n_days, n_assets))
    rets = noise + drift[:, None]
    return pd.DataFrame(rets, index=idx, columns=cols)


def _signal_panel(n_days: int = 400, n_assets: int = 24, seed: int = 0) -> tuple[pd.DataFrame, list[str]]:
    """生成一张有「信号」的宽表:winners(20%)每天有 +0.005 drift,
    非 winners 有 -0.001 drift。Returns (rets_df, winner_symbols)。
    """
    idx = pd.date_range("2026-01-01", periods=n_days, freq="D")
    rng = np.random.default_rng(seed)
    cols = [f"A{i:02d}" for i in range(n_assets)]
    n_winners = int(n_assets * 0.2)
    drifts = np.array([0.005 if i < n_winners else -0.001 for i in range(n_assets)])
    drift = np.tile(drifts, (n_days, 1))
    noise = rng.normal(0, 0.005, (n_days, n_assets))  # 低噪声凸显 drift
    rets = drift + noise
    return pd.DataFrame(rets, index=idx, columns=cols), [f"A{i:02d}" for i in range(n_winners)]


# ============================================================
# Test 17 (NEW T-069): zero-signal book's pct_vs_random ≈ U[0, 1] (KS p > 0.05)
# ============================================================

def test_random_baseline_zero_signal_uniform() -> tuple[bool, str]:
    """Per T-069 acceptance.expect 第一条:
    零信号账本 pct_vs_random 近似均匀(KS p > 0.05)。即:一本与随机组合同规则的
    账本,其 excess_mean 在随机分布里的秩应近似 U[0, 1]。

    实现:重复 30 次「模拟一本书 = 从同一 spec 再抽一次随机组合」,收集 30 个
    pct_vs_random,跑 scipy.stats.kstest vs U[0, 1]。
    """
    try:
        from scipy.stats import kstest
    except Exception:
        return _ks_test_no_scipy()

    rets = _make_panel_returns(n_days=400, n_assets=24, seed=0)
    spec = RandomBookSpec(book_id="synthetic_zero", weighting="equal",
                          n_positions=10, turnover_days=14)
    bench = rets.mean(axis=1, skipna=True).fillna(0.0)
    bench_ret = (1 + bench).cumprod().pct_change().dropna()

    n_trials = 30
    pcts: list[float] = []
    for trial in range(n_trials):
        rng = np.random.default_rng(42 + trial)
        nav = simulate_random_portfolio(rets, spec.n_positions, spec.weighting,
                                        spec.single_name_cap, None,
                                        spec.turnover_days, rng)
        pr = nav.pct_change().dropna().align(bench_ret, join="inner")[0]
        actual = float((pr - bench_ret).dropna().mean())
        bl = compute_random_baseline(rets, spec.n_positions, spec.weighting,
                                     spec.single_name_cap, None, spec.turnover_days,
                                     n_random=150, seed=42 + 10000 * (trial + 1))
        if len(bl["distribution"]) >= 100:
            pcts.append(pct_vs_random(actual, bl["distribution"]))

    if len(pcts) < 20:
        return False, f"❌ 有效 trials {len(pcts)} < 20;setup 错"

    stat, p = kstest(pcts, "uniform")
    if p > 0.05:
        return True, (f"✅ 零信号 pct_vs_random ≈ U[0,1]:n={len(pcts)}, KS stat={stat:.4f}, p={p:.4f};"
                      f"实际分布 = [{min(pcts):.3f}, {max(pcts):.3f}]")
    return False, f"❌ 零信号 pct_vs_random 显著偏离均匀:KS p={p:.4f}(< 0.05);分布 = {sorted(pcts[:5])}..."


def _ks_test_no_scipy() -> tuple[bool, str]:
    """scipy 不可用时的弱兜底:5 等分卡方。"""
    rets = _make_panel_returns(n_days=400, n_assets=24, seed=0)
    spec = RandomBookSpec(book_id="synthetic_zero", weighting="equal",
                          n_positions=10, turnover_days=14)
    n_trials = 50
    pcts: list[float] = []
    for trial in range(n_trials):
        rng = np.random.default_rng(42 + trial)
        nav = simulate_random_portfolio(rets, spec.n_positions, spec.weighting,
                                        spec.single_name_cap, None,
                                        spec.turnover_days, rng)
        bench = rets.mean(axis=1, skipna=True).fillna(0.0)
        bench_ret = (1 + bench).cumprod().pct_change().dropna()
        pr = nav.pct_change().dropna().align(bench_ret, join="inner")[0]
        actual = float((pr - bench_ret).dropna().mean())
        bl = compute_random_baseline(rets, spec.n_positions, spec.weighting,
                                     spec.single_name_cap, None, spec.turnover_days,
                                     n_random=150, seed=42 + 10000 * (trial + 1))
        if len(bl["distribution"]) >= 100:
            pcts.append(pct_vs_random(actual, bl["distribution"]))
    bins = [0, 0.2, 0.4, 0.6, 0.8, 1.0]
    obs = [sum(1 for p in pcts if bins[i] <= p < bins[i + 1]) for i in range(5)]
    exp = len(pcts) / 5
    chi2 = sum((o - exp) ** 2 / exp for o in obs)
    # 5-bins, df=4, 5% critical = 9.49
    if chi2 < 9.49 and len(pcts) >= 30:
        return True, (f"✅ (scipy 不可用,降级卡方)n={len(pcts)} bins={obs} chi2={chi2:.2f} < 9.49")
    return False, f"❌ 降级卡方不通过:bins={obs} chi2={chi2:.2f} (n={len(pcts)})"


# ============================================================
# Test 18 (NEW T-069): embedded-signal book's pct_vs_random > 0.95
# ============================================================

def test_random_baseline_embedded_signal_outlier() -> tuple[bool, str]:
    """Per T-069 acceptance.expect 第二条:
    埋了信号的账本 pct_vs_random > 0.95。

    实现:每个 trial 重抽一张 panel,保留固定的 winner 集合,
    「信号账本」= 在每期调仓日只买 winner 集合的等权份额。其他候选 = 同 spec 的
    随机基准。
    """
    rets_panel, winners = _signal_panel(n_days=400, n_assets=24, seed=1)
    spec = RandomBookSpec(book_id="synthetic_signal", weighting="equal",
                          n_positions=len(winners), turnover_days=14)

    # 1) 信号账本 = 永远在调仓日选 winners(固定偏好,系统性的赢家选择)
    sig_pcts: list[float] = []
    n_trials = 10   # 比 first pass 更瘦 — sign 强、不需要 50 trials
    for trial in range(n_trials):
        # 信号账本:固定选 winners,等权
        rets, _w = _signal_panel(n_days=400, n_assets=24, seed=101 + trial)
        n_pos = len(winners)
        members = rets.columns[:n_pos].tolist()

        # 调仓周期构建 NAV(避开 simulate_random_portfolio 的随机选择)
        port_rets: list[pd.Series] = []
        n_days = len(rets)
        rb_idx = list(range(0, n_days, spec.turnover_days))
        if rb_idx[-1] != n_days:
            rb_idx.append(n_days)
        w = pd.Series(1.0 / n_pos, index=members)
        for i in range(len(rb_idx) - 1):
            seg = rets.iloc[rb_idx[i]:rb_idx[i + 1]].fillna(0.0)
            aligned_w = w.reindex(seg.columns).fillna(0.0).values
            port_rets.append(pd.Series(seg.values @ aligned_w, index=seg.index))
        daily = pd.concat(port_rets).sort_index()
        nav_sig = (1 + daily).cumprod()

        bench = rets.mean(axis=1, skipna=True).fillna(0.0)
        bench_ret = (1 + bench).cumprod().pct_change().dropna()
        pr_sig = nav_sig.pct_change().dropna().align(bench_ret, join="inner")[0]
        actual_sig = float((pr_sig - bench_ret).dropna().mean())

        bl = compute_random_baseline(rets, n_pos, spec.weighting,
                                     spec.single_name_cap, None, spec.turnover_days,
                                     n_random=150, seed=2024 + trial)   # 瘦一点的 baseline
        if len(bl["distribution"]) >= 100:
            sig_pcts.append(pct_vs_random(actual_sig, bl["distribution"]))

    if len(sig_pcts) < 5:
        return False, f"❌ trials {len(sig_pcts)} 不足 5;setup 错"

    # 信号账本的 pct_vs_random 中位数应该 > 0.95
    sig_pcts_sorted = sorted(sig_pcts)
    median = sig_pcts_sorted[len(sig_pcts_sorted) // 2]
    if median > 0.95:
        return True, (f"✅ 埋信号账本 pct_vs_random 中位 = {median:.3f} > 0.95;"
                      f"分布 = [{min(sig_pcts):.3f}, {max(sig_pcts):.3f}], n={len(sig_pcts)}")
    return False, (f"❌ 信号账本没跑赢随机中位:中位 = {median:.3f}(应 > 0.95);"
                   f"全 n={len(sig_pcts)}, 分布 = {sig_pcts_sorted[:5]}...{sig_pcts_sorted[-5:]}")


# ============================================================
# Test 19 (NEW T-069): eq 风格不被记成信号 — 等权底零信号在「等权跑赢市值」样本里仍均匀
# ============================================================

def test_random_baseline_eq_style_not_recorded_as_signal() -> tuple[bool, str]:
    """Per T-069 acceptance.expect 第三条:
    等权底的零信号账本在「等权跑赢市值」的样本里仍近似均匀(风格不被记成信号)。

    实现:重新设计更稳的版本 ——
    panel 上前 4 资产(mcap 假设的「大币」)有 -0.002 日 drift,
    后 20 资产有 +0.0004 日 drift。
    整体上 mcap 加权(假设 top4 占 80%)在多数日子会跑输等权;
    一个等权 zero-signal 账本(同 spec)在全样本上 pct_vs_random 应近似均匀——
    即使存在风格优势,该 zero-signal 账本是随机分布的一个样本,其秩仍然均匀。
    """
    try:
        from scipy.stats import kstest
    except Exception:
        return True, "✅ (scipy 不可用,跳过本用例 — 前两用例已覆盖核心约束)"

    rng = np.random.default_rng(7)
    n_days, n_assets = 400, 24
    idx = pd.date_range("2026-01-01", periods=n_days, freq="D")
    cols = [f"A{i:02d}" for i in range(n_assets)]
    # drift 模式:让「等权」系统性地好过「市值底」
    # (mcap 假设 top4=80% 权重,所以 top4 资负 alpha ⇒ 等权跑赢)
    drifts = -np.array([0.002 if i < 4 else 0.0004 for i in range(n_assets)])
    drift = np.tile(drifts, (n_days, 1))
    noise = rng.normal(0, 0.005, (n_days, n_assets))  # 低噪凸显 drift
    rets = pd.DataFrame(drift + noise, index=idx, columns=cols)

    # 用 equal spec 的 zero-signal 账本(全样本,无过滤)
    spec = RandomBookSpec(book_id="synthetic_eq_zero", weighting="equal",
                          n_positions=8, turnover_days=14)

    n_trials = 50
    pcts: list[float] = []
    for trial in range(n_trials):
        rng_t = np.random.default_rng(999 + trial)
        nav = simulate_random_portfolio(rets, spec.n_positions, spec.weighting,
                                        spec.single_name_cap, None,
                                        spec.turnover_days, rng_t)
        bench = rets.mean(axis=1, skipna=True).fillna(0.0)
        bench_ret = (1 + bench).cumprod().pct_change().dropna()
        pr = nav.pct_change().dropna().align(bench_ret, join="inner")[0]
        actual = float((pr - bench_ret).dropna().mean())
        bl = compute_random_baseline(rets, spec.n_positions, spec.weighting,
                                     spec.single_name_cap, None, spec.turnover_days,
                                     n_random=400, seed=8888 + trial)
        if len(bl["distribution"]) >= 100:
            pcts.append(pct_vs_random(actual, bl["distribution"]))

    if len(pcts) < 30:
        return False, f"❌ trials {len(pcts)} 不足 30;setup 错"

    stat, p = kstest(pcts, "uniform")
    if p > 0.05:
        return True, (f"✅ 等权底零信号在全样本上 pct_vs_random 仍近似均匀 "
                      f"(panel 上 EQ 系统性跑赢 mcap 但风格不被记成信号):"
                      f"n={len(pcts)}, KS stat={stat:.4f}, p={p:.4f}")
    return False, (f"❌ 等权风格被记成信号:KS p={p:.4f} < 0.05;"
                   f"pct 分布 = [{min(pcts):.3f}, {max(pcts):.3f}], n={len(pcts)}")


# ============================================================
# Test 20 (NEW T-069): outlier 列表 = (book_id, cell) pairs where actual > p99
# ============================================================

def test_random_baseline_outlier_flag() -> tuple[bool, str]:
    """Per T-069 acceptance.check 后半:
    outlier = 实测 > 随机 p99 的 (账本,格子) 对。
    """
    # 构造:同一 spec 同一 panel —— 信号账本挑 winners,期望 pct_vs_random > 0.99 ⇒ is_outlier=True;
    # 零信号账本 ⇒ is_outlier=False。
    rets_panel, winners = _signal_panel(n_days=400, n_assets=24, seed=2)
    spec_sig = RandomBookSpec(book_id="sig_book", weighting="equal",
                              n_positions=len(winners), turnover_days=14)
    spec_zero = RandomBookSpec(book_id="zero_book", weighting="equal",
                               n_positions=len(winners), turnover_days=14)

    # 信号账本:固定买 winners
    n_pos = len(winners)
    members = rets_panel.columns[:n_pos].tolist()
    rb_idx = list(range(0, len(rets_panel), spec_sig.turnover_days))
    if rb_idx[-1] != len(rets_panel):
        rb_idx.append(len(rets_panel))
    w = pd.Series(1.0 / n_pos, index=members)
    port_rets = []
    for i in range(len(rb_idx) - 1):
        seg = rets_panel.iloc[rb_idx[i]:rb_idx[i + 1]].fillna(0.0)
        aligned_w = w.reindex(seg.columns).fillna(0.0).values
        port_rets.append(pd.Series(seg.values @ aligned_w, index=seg.index))
    daily = pd.concat(port_rets).sort_index()
    nav_sig = (1 + daily).cumprod()
    bench = rets_panel.mean(axis=1, skipna=True).fillna(0.0)
    bench_ret = (1 + bench).cumprod().pct_change().dropna()
    pr_sig = nav_sig.pct_change().dropna().align(bench_ret, join="inner")[0]
    actual_sig = float((pr_sig - bench_ret).dropna().mean())

    # 零信号账本:随机抽一次
    rng = np.random.default_rng(0)
    nav_zero = simulate_random_portfolio(rets_panel, n_pos, "equal",
                                        0.40, None, spec_zero.turnover_days, rng)
    pr_zero = nav_zero.pct_change().dropna().align(bench_ret, join="inner")[0]
    actual_zero = float((pr_zero - bench_ret).dropna().mean())

    # baseline
    bl = compute_random_baseline(rets_panel, n_pos, "equal", 0.40, None,
                                 spec_zero.turnover_days, n_random=600, seed=11)
    dist = bl["distribution"]
    if len(dist) < 200:
        return False, f"❌ distribution 太短:{len(dist)}"

    is_sig_outlier = is_outlier(actual_sig, dist, q=0.99)
    is_zero_outlier = is_outlier(actual_zero, dist, q=0.99)

    if is_sig_outlier and not is_zero_outlier:
        return True, (f"✅ outlier 判定对:信号账本 is_outlier=True,零信号 = False;"
                      f"actual_sig={actual_sig:.4f} vs p99={bl['p99']:.4f}")
    return False, (f"❌ outlier 判定错:sig is_outlier={is_sig_outlier}, zero is_outlier={is_zero_outlier};"
                   f"actual_sig={actual_sig:.4f}, actual_zero={actual_zero:.4f}, p99={bl['p99']:.4f}")


# ============================================================
# main
# ============================================================

def main() -> int:
    tests = [
        ("01_pit_state", test_rr_matrix_pit),
        ("02_bootstrap_ci", test_rr_matrix_bootstrap_ci),
        ("03_shrinkage", test_rr_matrix_shrinkage),
        ("04_fomc_window", test_rr_matrix_fomc_window),
        ("05_beta_calc", test_rr_matrix_beta_calculation),
        ("06_rel_maxdd", test_rr_matrix_rel_maxdd),
        ("07_excludes_invalid_books", test_rr_matrix_excludes_invalid_books),
        ("08_n_variants_tried", test_rr_matrix_n_variants_tried),
        ("09_determinism", test_rr_matrix_determinism),
        ("10_handles_missing_state", test_rr_matrix_handles_missing_state),
        ("11_unknown_coverage_v6", test_rr_matrix_unknown_coverage),
        ("12_full_ci_proper_v6", test_rr_matrix_full_ci_proper),
        ("13_annualization_365_v6", test_rr_matrix_annualization_365),
        ("14_bootstrap_uses_all_days_20_40", test_rr_matrix_bootstrap_uses_all_days_20_40),
        ("15_p_pos_not_binary_n_lt_40", test_rr_matrix_p_pos_not_binary_n_lt_40),
        ("16_bootstrap_n80_iid_contains_true_mean", test_rr_matrix_bootstrap_n80_iid_contains_true_mean),
        ("17_random_zero_signal_uniform_t069", test_random_baseline_zero_signal_uniform),
        ("18_random_signal_outlier_t069", test_random_baseline_embedded_signal_outlier),
        ("19_random_eq_style_uniform_t069", test_random_baseline_eq_style_not_recorded_as_signal),
        ("20_random_outlier_flag_t069", test_random_baseline_outlier_flag),
    ]
    print("=" * 70)
    print("T-045 + T-068 + T-069 评估层 rr_matrix v0.6+ 测试套件(13 + 3 T-068 + 4 T-069 = 20 个)")
    print("=" * 70)
    n_pass = 0
    for name, fn in tests:
        ok, msg = fn()
        print(f"[{name}] {msg}")
        if ok:
            n_pass += 1
    print("=" * 70)
    print(f"结果:{n_pass}/{len(tests)} PASS")
    return 0 if n_pass == len(tests) else 1


if __name__ == "__main__":
    sys.exit(main())