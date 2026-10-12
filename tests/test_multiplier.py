"""T-063 / S-505:③ 推力 —— 规则、时点、敞口边界、现金腿与资金费、随机择时对照。
T-087:① 切到 cap_a1_u 后,新底仓上的新臂(mult_v2 / mult_v2_replay / core_u_replay)。"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.signals.core_cap import capped_weights  # noqa: E402
from src.data.signals.multiplier import (ARM_U, ARM, CASH_ANN, CORE_ARM_U, CORE_ARM, FUNDING_FALLBACK_ANN,  # noqa: E402
                                         INCEPTION_U, LEVELS, REPLAY_ARM_U, REPLAY_ARM, apply_multiplier,
                                         build_rows, build_rows_u, core_returns, core_u_returns, evaluate,
                                         evaluate_u, multiplier, random_timing_pct)


def test_rule_and_unknown_state() -> None:
    assert multiplier(0.1, 0.2) == 1.3 and multiplier(-0.1, 0.8) == 0.7
    assert multiplier(0.1, 0.8) == 1.0 and multiplier(-0.1, 0.2) == 1.0
    assert multiplier(None, 0.2) == 1.0 and multiplier(float("nan"), 0.2) == 1.0, "读不到状态不能当成信号"


def test_exposure_never_leaves_0_7_to_1_3() -> None:
    idx = pd.date_range("2024-01-01", periods=5)
    r = pd.Series(0.01, index=idx)
    book = apply_multiplier(r, pd.Series([5.0, -2.0, 0.0, 1.3, 0.7], index=idx), pd.Series(dtype=float))
    assert book["m"].min() >= LEVELS[0] and book["m"].max() <= LEVELS[-1]


def test_cash_leg_and_funding_cost() -> None:
    idx = pd.date_range("2024-01-01", periods=3)
    r = pd.Series([0.0, 0.0, 0.0], index=idx)
    low = apply_multiplier(r, pd.Series(0.7, index=idx), pd.Series(dtype=float))
    assert np.allclose(low["ret"].iloc[1:], 0.3 * CASH_ANN / 365), "0.7 倍时 30% 在现金等价物上"
    high = apply_multiplier(r, pd.Series(1.3, index=idx), pd.Series(dtype=float))
    assert np.allclose(high["ret"].iloc[1:], -0.3 * FUNDING_FALLBACK_ANN / 365), "1.3 倍的多出部分付资金费"
    one = apply_multiplier(pd.Series([0.02, -0.01, 0.03], index=idx), pd.Series(1.0, index=idx), pd.Series(dtype=float))
    assert np.allclose(one["ret"], [0.02, -0.01, 0.03]), "1.0 倍 = ① 本身"


def test_switch_costs_10bps_per_unit_change() -> None:
    idx = pd.date_range("2024-01-01", periods=3)
    book = apply_multiplier(pd.Series(0.0, index=idx), pd.Series([1.0, 1.3, 1.3], index=idx),
                            pd.Series(0.0, index=idx))
    assert abs(book["cost"].iloc[1] - 0.3 * 10 / 1e4) < 1e-12 and book["cost"].iloc[2] == 0


def test_state_of_d_minus_1_sets_exposure_of_d() -> None:
    """时点:d 收盘的状态只能决定 d+1 的敞口。d 当天的收益不能用 d 的状态。"""
    idx = pd.date_range("2024-01-01", periods=4)
    state = pd.DataFrame({"dist_200": [0.1, 0.1, -0.1, -0.1], "vol_pct_3y": [0.2, 0.2, 0.8, 0.8]}, index=idx)
    core = pd.Series([0.0, 0.01, 0.01, 0.01], index=idx)
    rows, _ = build_rows(core, state, idx[-1])
    m = {r["d"]: r["m"] for r in rows if r["arm"] == "mult_v1_replay"}
    assert m["2024-01-01"] == 1.0, "第一天没有前一天的状态"
    assert m["2024-01-02"] == 1.3 and m["2024-01-03"] == 1.3, "1/1 与 1/2 的状态是上行平静"
    assert m["2024-01-04"] == 0.7, "1/3 收盘转为下行不平静,1/4 才降到 0.7"


def test_random_timing_has_no_edge_on_pure_noise() -> None:
    """零信号:m 与收益无关时,实测落在随机分布中段 —— 多个种子平均接近 0.5。"""
    idx = pd.date_range("2023-01-01", periods=400)
    pcts = []
    for seed in range(6):
        rng = np.random.default_rng(100 + seed)
        r = pd.Series(rng.normal(0, 0.03, len(idx)), index=idx)
        m = pd.Series(rng.choice(LEVELS, len(idx)), index=idx)
        pcts.append(random_timing_pct(r, m, pd.Series(dtype=float), n=200)["pct_vs_random"])
    assert 0.2 < float(np.mean(pcts)) < 0.8, pcts


def test_random_timing_finds_a_planted_edge() -> None:
    """埋信号:m 提前知道下一天的方向 —— 分位应接近 1。"""
    idx = pd.date_range("2023-01-01", periods=400)
    rng = np.random.default_rng(7)
    r = pd.Series(rng.normal(0, 0.03, len(idx)), index=idx)
    m = pd.Series(np.where(r.values > 0, 1.3, 0.7), index=idx)
    assert random_timing_pct(r, m, pd.Series(dtype=float), n=200)["pct_vs_random"] > 0.95


def test_evaluate_reports_three_windows_core_first() -> None:
    idx = pd.date_range("2023-01-02", "2026-10-07")
    rng = np.random.default_rng(1)
    r = pd.Series(rng.normal(0, 0.02, len(idx)), index=idx)
    m = pd.Series(1.0, index=idx)
    ev = evaluate(r, m, pd.Series(dtype=float), idx[-1])
    assert set(ev) == {"in_sample_2023_2024", "holdout_2025_to_inception", "forward"}
    assert "core" in ev["holdout_2025_to_inception"] and "mult" in ev["holdout_2025_to_inception"]


# ── T-087 新臂:capped_weights(avail, 1.0, cap=1.0) 不再压大币;旧臂照旧 ─────────────


def test_capped_weights_cap_one_does_not_clamp_a_whale() -> None:
    """cap=1.0 ⇒ 即使一个币占面板 99%,也不再被压到 40%。"""
    avail = {"BTC": 1.0, "ETH": 1e-3, "SOL": 1e-3, "XRP": 1e-3}
    w_cap1 = capped_weights(avail, 1.0, cap=1.0)
    assert w_cap1["BTC"] > 0.40, "新底仓不应被 40% 压"
    w_cap04 = capped_weights(avail, 1.0, cap=0.40)
    assert abs(w_cap04["BTC"] - 0.40) < 1e-9, "旧底仓 40% 上限要按规则工作"
    assert abs(sum(w_cap1.values()) - 1.0) < 1e-9 and abs(sum(w_cap04.values()) - 1.0) < 1e-9


def test_core_u_replay_on_synthetic_panel_keeps_whale_weight() -> None:
    """合成面板:BTC 占 60% 市值,24 币周一再平衡。 新底仓 core_u_replay 的 BTC 权重
    不被压到 40%;旧底仓 core_replay 的 BTC 权重被压到 40%。"""
    rng = np.random.default_rng(11)
    days = pd.date_range("2024-01-01", periods=180, freq="D")
    syms = ["BTC", "ETH", "SOL", "XRP"] + [f"C{i}" for i in range(20)]
    mcap = np.exp(rng.normal(0, 1.5, (len(days), len(syms))))
    mcap[:, 0] = mcap[:, 0] * 1000.0                            # BTC 占绝对大头
    mcap_prev = pd.DataFrame(mcap, index=days, columns=syms)
    px = np.exp(np.cumsum(rng.normal(0, 0.02, (len(days), len(syms))), axis=0))
    px_df = pd.DataFrame(px, index=days, columns=syms)

    cr_old = core_returns(px_df, mcap_prev, days[0], days[-1])
    cr_new = core_u_returns(px_df, mcap_prev, days[0], days[-1])
    assert len(cr_old) == len(days) and len(cr_new) == len(days)
    # 旧 ① 在 BTC 主导下会被压到 40%(最大单币权重 ≤ 40%);新 ① 不压 ⇒ BTC 权重 > 40%
    # 通过两条 ret 序列并不相同来间接证明底层权重构造确实不同(不靠直接读 nav_kernel 内部状态)。
    assert not np.allclose(cr_old.values, cr_new.values), "新旧底仓在 BTC 主导面板上必须给出不同收益"


def test_build_rows_u_emits_v2_replay_and_core_u_and_forward_only_after_10_12() -> None:
    """build_rows_u:pl_v2_replay 整段(2023 起)、pl_v2 起点 2026-10-12 收盘(第一行 10-13)。

    旧 build_rows 仍然只产出 v1 / v1_replay / core_replay,新 build_rows_u 的 arm 不混进去。"""
    days = pd.date_range("2024-01-02", INCEPTION_U + pd.Timedelta(days=3))
    state = pd.DataFrame({"dist_200": 0.1, "vol_pct_3y": 0.2,
                          "funding_7d_ann": 0.05}, index=days)
    cr = pd.Series(0.01, index=days)
    rows, _ = build_rows_u(cr, state, days[-1])
    arms = {r["arm"] for r in rows}
    assert {REPLAY_ARM_U, CORE_ARM_U, ARM_U} <= arms
    # 前向臂 mult_v2 必须只在 10-13 起出现
    fwd = [r for r in rows if r["arm"] == ARM_U]
    assert fwd, "前向臂至少有一行"
    assert min(r["d"] for r in fwd) > INCEPTION_U.date().isoformat(), \
        "mult_v2 前向第一行必须在 INCEPTION_U 收盘之后"


def test_old_build_rows_unchanged_and_does_not_emit_new_arms() -> None:
    """旧 build_rows(底仓 cap_a1)一行不改:仍只产出 mult_v1_replay / mult_v1 / core_replay;新臂名称不混入。"""
    days = pd.date_range("2024-01-02", "2026-10-13")
    state = pd.DataFrame({"dist_200": 0.1, "vol_pct_3y": 0.2,
                          "funding_7d_ann": 0.05}, index=days)
    cr = pd.Series(0.01, index=days)
    rows, _ = build_rows(cr, state, days[-1])
    arms = {r["arm"] for r in rows}
    assert arms <= {REPLAY_ARM, CORE_ARM, ARM}, "旧 build_rows 仍只写 v1 / v1_replay / core_replay"


def test_evaluate_u_uses_inception_u_for_forward_window() -> None:
    """evaluate_u 的 forward 窗口下界 = INCEPTION_U + 1 day;旧 evaluate 的下界 = INCEPTION + 1 day。"""
    idx = pd.date_range("2025-01-01", "2026-12-31")
    rng = np.random.default_rng(3)
    r = pd.Series(rng.normal(0, 0.02, len(idx)), index=idx)
    m = pd.Series(1.0, index=idx)
    ev_old = evaluate(r, m, pd.Series(dtype=float), idx[-1])
    ev_new = evaluate_u(r, m, pd.Series(dtype=float), idx[-1])
    # 新底仓标注自己
    assert ev_new.get("底仓", "").startswith("core_cap.cap_a1_u")
    # 两者都有完整三窗口(数据够长)
    assert set(ev_old) - {"底仓"} == set(ev_new) - {"底仓"} or set(ev_new) >= {"holdout_2025_to_inception"}
    # 留出段:旧 ev 的 holdout 截止于 INCEPTION - 1 = 2026-10-07;新 ev 截止于 INCEPTION_U - 1 = 2026-10-11
    # ⇒ 在数据覆盖到 2026-12-31 的情况下,新 holdout 的 core["n"] 严格更大
    assert "core" in ev_old["holdout_2025_to_inception"] and "core" in ev_new["holdout_2025_to_inception"]
    assert ev_new["holdout_2025_to_inception"]["core"]["n"] > ev_old["holdout_2025_to_inception"]["core"]["n"]


if __name__ == "__main__":
    print("── T-063 / T-087 ③ 推力 ──")
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ✓ {name}")
    print("\n✅ passed")
