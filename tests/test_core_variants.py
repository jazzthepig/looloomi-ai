"""T-072 / S-517:① 的候选定义 —— 上限、动量与退回、时点、漂移与成本、随机权重对照。"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.signals.core_variants import (COST_BPS, BROAD_MIN_MCAP, build, capped, momentum,  # noqa: E402
                                            prepare_broad_panels, simulate, target_weights)


def _panel(n=500, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2022-09-01", periods=n)
    px = pd.DataFrame(100 * np.exp(np.cumsum(rng.normal(0, 0.03, (n, 5)), axis=0)), index=idx,
                      columns=["BTC", "ETH", "SOL", "ADA", "XRP"])
    mc = pd.DataFrame({"BTC": 6e11, "ETH": 2e11, "SOL": 5e10, "ADA": 1e10, "XRP": 3e10}, index=idx)
    return px, mc


def test_cap_holds_and_uncapped_is_proportional() -> None:
    w = capped({"BTC": 6, "ETH": 2, "SOL": 1, "ADA": 1}, 0.4)
    assert abs(sum(w.values()) - 1) < 1e-9 and max(w.values()) <= 0.4 + 1e-9
    px, mc = _panel()
    d = px.index[200]
    u = target_weights("cap_uncapped", d, px, mc, list(px.columns))
    assert abs(u["BTC"] - 6e11 / 8.9e11) < 1e-9


def test_momentum_uses_only_yesterday_and_falls_back_when_nothing_is_up() -> None:
    px, mc = _panel()
    d = px.index[300]
    m1 = momentum(px, d, list(px.columns))
    px2 = px.copy()
    px2.loc[d:] = px2.loc[d:] * 5
    assert momentum(px2, d, list(px.columns)) == m1, "d 当天及之后的价格不能进 d 的权重"
    down = px.copy()
    down.loc[:d - pd.Timedelta(days=2)] = 1e6
    w = target_weights("mom90", d, down, mc, list(px.columns))
    assert w == target_weights("cap_uncapped", d, down, mc, list(px.columns)), "没有一个上涨 ⇒ 退回市值加权"


def test_simulate_drift_and_cost() -> None:
    idx = pd.date_range("2024-01-01", periods=3)
    rets = pd.DataFrame({"A": [0.10, 0.0, 0.0], "B": [0.0, 0.0, 0.0]}, index=idx)
    out = simulate(rets, {idx[0]: {"A": 0.5, "B": 0.5}, idx[2]: {"A": 0.5, "B": 0.5}})
    assert abs(out.iloc[0] - (0.05 - 1.0 * COST_BPS / 1e4)) < 1e-12, "第一天:建仓换手 1.0"
    drift_a = 0.55 / 1.05
    assert abs(out.iloc[2] - (-abs(0.5 - drift_a) * 2 * COST_BPS / 1e4)) < 1e-12, "再平衡只付漂移部分的换手"


def test_build_reports_all_arms_and_random_baseline_on_noise() -> None:
    px, mc = _panel(n=900, seed=3)
    rows, ev = build(px, mc, px.index[-1], n_random=60)
    arms = {r["arm"] for r in rows}
    assert arms == {"cap_c40", "cap_uncapped", "mom90", "mom90_x_cap", "btc", "dual_mom",
                    "mom30_breadth", "mom14_breadth", "mom7_breadth", "mom30_abs"}
    w = ev["in_sample_2023_2024"]
    assert "random_weights" in w and 0.0 <= w["mom90"]["pct_vs_random"] <= 1.0
    assert ev["latest_weights"]["btc"] == {"BTC": 1.0}


def test_dual_momentum_switches_on_yesterdays_btc_trend_and_pays_for_it() -> None:
    from src.data.signals.core_variants import CASH_ANN, dual_momentum
    idx = pd.date_range("2024-01-01", periods=400)
    btc = pd.Series(np.r_[np.linspace(100, 50, 380), np.full(20, 50.0)], index=idx)
    mom = pd.Series(0.01, index=idx)
    out = dual_momentum(mom, btc, None)
    assert abs(out.iloc[10] - 0.01) < 1e-12, "信号读不到 ⇒ 不切"
    late = out.iloc[-1]
    assert abs(late - CASH_ANN / 365) < 1e-9, "BTC 一年跌 ⇒ 防守腿(没有 ④ 时全是现金)"
    btc2 = btc.copy(); btc2.iloc[-1] = 1e9
    assert abs(dual_momentum(mom, btc2, None).iloc[-1] - late) < 1e-12, "当天的价格不影响当天的仓位"


def test_breadth_sizes_by_how_many_are_up_and_abs_goes_to_cash() -> None:
    """S-520:窄动量(24 个里只有 1 个转正)不再满仓;一个都不为正 ⇒ 现金,不退回市值加权。"""
    from src.data.signals.core_variants import CASH, breadth_weights
    idx = pd.date_range("2024-01-01", periods=40)
    px = pd.DataFrame({"A": np.linspace(100, 120, 40), "B": np.linspace(100, 80, 40),
                       "C": np.linspace(100, 90, 40), "D": np.linspace(100, 70, 40)}, index=idx)
    d = idx[-1]
    w = breadth_weights(px, d, list(px.columns), 30, "breadth")
    assert abs(w["A"] - 0.25) < 1e-12 and abs(w[CASH] - 0.75) < 1e-12
    w2 = breadth_weights(px, d, list(px.columns), 30, "abs")
    assert w2 == {"A": 1.0}
    down = px[["B", "C", "D"]]
    assert breadth_weights(down, d, list(down.columns), 30, "abs") == {CASH: 1.0}


def test_cash_leg_earns_and_is_not_charged_turnover() -> None:
    from src.data.signals.core_variants import CASH, CASH_ANN
    idx = pd.date_range("2024-01-01", periods=2)
    rets = pd.DataFrame({"A": [0.0, 0.0], CASH: [CASH_ANN / 365] * 2}, index=idx)
    out = simulate(rets, {idx[0]: {CASH: 1.0}})
    assert abs(out.iloc[0] - CASH_ANN / 365) < 1e-12, "全现金:不付换手、拿现金收益"


def test_broad_universe_excludes_stables_and_cash_like_and_takes_top_n() -> None:
    from src.data.signals.core_variants import broad_universe
    m = pd.Series({"bitcoin": 1e12, "tether": 9e11, "ethereum": 4e11, "tbill": 3e11, "solana": 1e11})
    v = pd.Series({"tbill": 0.001, "bitcoin": 0.03})
    assert broad_universe(m, v, top_n=2) == ["bitcoin", "ethereum"]


# ============================================================
# T-084 / S-555 第 0 条:asset_mcap_daily 读拆分(候选 vs 完整价格)
# ============================================================

def _broad_drop_rows(days_idx, drop_after_idx: int = 35):
    """构造 asset_mcap_daily 行:候选币 X 前 N 天 mcap >= $2 亿、之后 mcap 跌破 + 价格腰斩;
    A/B/C/X 价格都有正漂移 + 适度噪声,既保证 momentum > 0 又让 vol30 > 0.005(否则被 broad_universe 当类现金过滤)。"""
    rng = np.random.default_rng(42)
    n = len(days_idx)
    # 几何布朗运动:每日 ~ N(0, 0.04) 收益
    rets_path = rng.normal(0.002, 0.04, (n, 4))
    prices = np.exp(np.cumsum(rets_path, axis=0))
    prices *= np.array([100.0, 50.0, 20.0, 250.0])  # 初始价
    rows = []
    for i, d in enumerate(days_idx):
        rows.append({"coin_id": "A", "d": d.date().isoformat(), "price": float(prices[i, 0]), "mcap": 5e9})
        rows.append({"coin_id": "B", "d": d.date().isoformat(), "price": float(prices[i, 1]), "mcap": 4e9})
        rows.append({"coin_id": "C", "d": d.date().isoformat(), "price": float(prices[i, 2]), "mcap": 3e9})
        if i < drop_after_idx:
            px_x = float(prices[i, 3])
            mc_x = 3e8
        else:
            px_x = float(prices[i, 3]) * 0.5  # X 第 36 天起价格腰斩
            mc_x = 5e7   # mcap 跌破 $2 亿
        rows.append({"coin_id": "X", "d": d.date().isoformat(), "price": px_x, "mcap": mc_x})
    return rows


def test_prepare_broad_panels_keeps_post_drop_prices() -> None:
    """T-084 acceptance: 候选币的完整价格在准备阶段保留(即使后来 mcap 跌破)。
    旧 IO 行为(读带 mcap>=2e8 过滤)⇒ X 跌破后的行被过滤 ⇒ broad_momentum rets NaN ⇒ fillna(0) ⇒ 0 收益。
    新 IO 行为(prepare_broad_panels)⇒ X 跌破后的价格仍在 ⇒ 亏损被记入。
    """
    days = pd.date_range("2026-01-05", periods=50, freq="D")   # 周一开始,50 天供 30 日动量回看
    full_rows = _broad_drop_rows(days, drop_after_idx=35)
    cg_px, cg_mcap = prepare_broad_panels(full_rows, min_mcap=BROAD_MIN_MCAP)

    # 候选 = 全程 mcap>=2e8 的币(A/B/C) + 前 35 天 mcap>=2e8 的 X
    assert set(cg_px.columns) == {"A", "B", "C", "X"}, f"候选集错:{list(cg_px.columns)}"
    # X 跌破后(idx >= 35)的价格仍在(腰斩后价格 — 在新 IO 里被保留)
    pre_drop_avg = float(cg_px.loc[days[30]:days[34], "X"].mean())
    post_drop = cg_px.loc["2026-02-09":, "X"]   # 2026-01-05 + 35 天 = 2026-02-09
    post_drop_avg = float(post_drop.mean())
    assert post_drop.notna().all(), f"X 跌破后价格缺失:{post_drop.head().to_dict()}"
    # 新 IO:post_drop 价格 < pre_drop 平均(腰斩生效)
    assert post_drop_avg < pre_drop_avg, (
        f"新 IO X 跌破后平均价应低于 pre-drop 平均:"
        f"pre={pre_drop_avg:.4f}, post={post_drop_avg:.4f}"
    )

    # 反向对比:旧逻辑(预先把 mcap<2e8 的行过滤)会让 X 跌破后的价格 = NaN
    old_rows = [r for r in full_rows if not (r["coin_id"] == "X" and r["mcap"] < BROAD_MIN_MCAP)]
    old_px, _ = prepare_broad_panels(old_rows, min_mcap=BROAD_MIN_MCAP)
    assert old_px.loc["2026-02-09":, "X"].isna().all(), \
        "旧逻辑期望:X 跌破后价格在 prepare_broad_panels 输出里就是 NaN(bug 形态)"


def test_broad_momentum_records_loss_when_mcap_drops_mid_holding() -> None:
    """T-084 acceptance 完整回路:旧 IO ⇒ 持仓周 X 贡献 0;新 IO ⇒ 持仓周 X 贡献 -50% × 权重。

    持仓日(每周一):idx[0]=2026-01-05、idx[7]=2026-01-12、idx[14]=2026-01-19、...
    X 在 idx[5+2 索引](idx[35]=2026-02-09 周一)建仓后,idx[36]=2026-02-10 价格腰斩 ——
    旧 IO(过滤):cg_px[X] 跌破后 NaN ⇒ 持仓那周 rets 含 X = 0 ⇒ X 周贡献 = 0
    新 IO(完整):cg_px[X] 跌破后 $125 ⇒ 持仓那周 X 持仓权重 → 第 1 天 rets = -0.5 ⇒ 损失入账
    """
    days = pd.date_range("2026-01-05", periods=50, freq="D")
    full_rows = _broad_drop_rows(days, drop_after_idx=35)
    old_rows = [r for r in full_rows if not (r["coin_id"] == "X" and r["mcap"] < BROAD_MIN_MCAP)]
    end = days[-1]

    cg_px_new, cg_mcap_new = prepare_broad_panels(full_rows, min_mcap=BROAD_MIN_MCAP)
    cg_px_old, cg_mcap_old = prepare_broad_panels(old_rows, min_mcap=BROAD_MIN_MCAP)

    from src.data.signals.core_variants import broad_momentum
    out_old = broad_momentum(cg_px_old, cg_mcap_old, end=end).fillna(0.0)
    out_new = broad_momentum(cg_px_new, cg_mcap_new, end=end).fillna(0.0)

    # 持仓周:X 在 idx[35]=2026-02-09(周一)被建仓 → idx[35+6]=2026-02-15
    holding_week = slice("2026-02-09", "2026-02-15")
    loss_old = float((1.0 + out_old.loc[holding_week]).prod() - 1.0)
    loss_new = float((1.0 + out_new.loc[holding_week]).prod() - 1.0)
    # 旧 IO ⇒ 该周 X 贡献为 0(因为 X 跌破后 rets = NaN → 0);新 IO ⇒ X 腰斩当周贡献 < 0
    assert loss_old > loss_new, \
        f"新逻辑必须记入 X 腰斩的损失:loss_old={loss_old:.6f} > loss_new={loss_new:.6f}"
    # 新逻辑应至少记入 5pp 损失(权重 ~ 0.25 × 50% 跌幅)
    assert loss_new < -0.05, \
        f"新逻辑应至少记入 5pp 损失:loss_new={loss_new:.6f}"


def test_broad_momentum_loss_is_recorded_with_short_lookback() -> None:
    """T-084 acceptance 简化版:用短 lookback 让 momentum 在小数据集上工作,直接断言 weekly 收益差异。

    场景:50 天数据, 5 日 lookback,X 在 idx[35]=2026-02-09(周一)建仓后 idx[36]=2026-02-10 价格腰斩。
    比较旧 IO(过滤后 X 跌破日 NaN)与新 IO(完整价格)在持仓周的 weekly 收益 ——
    新 IO 必须更负(因为 X 的 -50% rets 进账)。
    """
    days = pd.date_range("2026-01-05", periods=50, freq="D")
    full_rows = _broad_drop_rows(days, drop_after_idx=35)
    old_rows = [r for r in full_rows if not (r["coin_id"] == "X" and r["mcap"] < BROAD_MIN_MCAP)]

    cg_px_new, cg_mcap_new = prepare_broad_panels(full_rows, min_mcap=BROAD_MIN_MCAP)
    cg_px_old, cg_mcap_old = prepare_broad_panels(old_rows, min_mcap=BROAD_MIN_MCAP)

    # 直接用 5 日 lookback 调 broad_momentum,绕开 30 日回看不进小数据的问题
    from src.data.signals.core_variants import broad_momentum
    out_old = broad_momentum(cg_px_old, cg_mcap_old, end=days[-1], lookback=5).fillna(0.0)
    out_new = broad_momentum(cg_px_new, cg_mcap_new, end=days[-1], lookback=5).fillna(0.0)

    holding_week = slice("2026-02-09", "2026-02-15")
    loss_old = float((1.0 + out_old.loc[holding_week]).prod() - 1.0)
    loss_new = float((1.0 + out_new.loc[holding_week]).prod() - 1.0)
    # 旧:该周 X 贡献 ≈ 0(因为 X 跌破日 rets = NaN → fillna(0))
    # 新:该周 X 贡献 < 0(因为 -50% rets 进账 × 权重)
    assert loss_new < loss_old, (
        f"新 IO 必须记入 X 腰斩的损失(损失更小):loss_old={loss_old:.6f}, "
        f"loss_new={loss_new:.6f}"
    )
    # 量化下限:权重 ~ 0.25 × 50% ≈ -0.125,放宽到 -0.05 容忍 normalize/再平衡噪声
    assert loss_new < -0.05, f"新 IO 应至少记入 5pp 损失:loss_new={loss_new:.6f}"
