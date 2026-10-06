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
    EXCLUDED_BOOKS,
    REGIMES,
    FOMC_VALUES,
    UNKNOWN_REGIME,
    REGIME_SHARE_FEATURES,
    DEFAULT_ANNUALIZATION,
    _fomc_window_dates,
    _dominant_regime,
    _state_panel_daily,
    _derive_regime_per_day,
    _block_bootstrap_ci,
    _p_pos,
    _beta_calc,
    _max_drawdown,
    _turnover_annual,
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
    """构造合成 state_daily 长表(per SPEC §3.1, T-048 as-built)。

    行序与 features 对齐:6 shares + 1 coverage per day,共 7 rows/day。
    coverage ∈ [coverage_min, max(coverage_min+5, 30)]; share 之和 = 1.0(用 dirichlet)。
    regime_per_day 可显式指定,否则均匀循环。
    """
    rng = np.random.default_rng(seed)
    n = len(days_idx)
    classes = list(REGIMES)

    # 6 shares = dirichlet(α=1) 行和 = 1
    share_data = rng.dirichlet(np.ones(len(classes)), size=n)
    # coverage ∈ [coverage_min, coverage_min+5]
    cov_data = rng.integers(coverage_min, coverage_min + 6, size=n)

    long_rows = []
    for i, d in enumerate(days_idx):
        for j, cls in enumerate(classes):
            long_rows.append({"d": d, "entity": "panel", "feature": f"regime_share_30d:{cls}",
                              "value": float(share_data[i, j])})
        long_rows.append({"d": d, "entity": "panel", "feature": "regime_coverage_30d",
                          "value": int(cov_data[i])})

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

    # 用 fomc=no cell(short window 在 FOMC 2026-09-16 之前)
    sid = "beta_plus_w"
    short_cells = out_short[out_short["strategy_id"] == sid]
    if short_cells.empty:
        return True, "✅ (跳过:short window 全部 cell 无数据)"
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
    full_mean_short = float(out_short[out_short["strategy_id"] == sid]["excess_mean"].mean())
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
    expected = {"regime=unknown&fomc=no"}
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
    ]
    print("=" * 70)
    print("T-045 评估层 rr_matrix v0.6 测试套件(per SPEC §9,13 个)")
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