"""v0.2 阶段 1 公用记账内核:漂移、成本、滞后在调用方、读不到就拒绝、两本现有账本逐位复现。"""
import numpy as np
import pandas as pd
import pytest

from src.data.accounting.nav_kernel import run_nav


def _px():
    idx = pd.date_range("2026-01-01", periods=4, freq="D")
    return pd.DataFrame({"A": [100, 110, 121, 121], "B": [100, 100, 100, 50]}, index=idx, dtype=float)


def test_weights_drift_with_prices_and_cost_is_turnover_times_bps():
    px = _px()
    d = list(px.index)
    rows = run_nav(px, {d[0]: {"A": 0.5, "B": 0.5}}, cost_bps=10, min_quoted_weight=0.5)
    assert rows[0]["turnover"] == 1.0 and abs(rows[0]["nav"] - (1 - 0.001)) < 1e-15
    assert abs(rows[1]["ret_gross"] - 0.05) < 1e-15                   # 0.5×10% + 0.5×0
    assert abs(rows[1]["w"]["A"] - 0.55 / 1.05) < 1e-15               # 权重随价漂移
    assert rows[3]["ret_gross"] < 0                                    # B 腰斩被记进去


def test_the_kernel_trades_on_the_day_it_is_told_lag_is_the_callers_job():
    px = _px()
    d = list(px.index)
    rows = run_nav(px, {d[0]: {"A": 1.0}, d[2]: {"B": 1.0}}, cost_bps=0, min_quoted_weight=0.5)
    assert [r["traded"] for r in rows] == [True, False, True, False]
    assert abs(rows[2]["ret_gross"] - 0.10) < 1e-15                    # 成交日当天的收益仍属于旧持仓
    assert abs(rows[3]["ret_gross"] + 0.5) < 1e-15                     # 之后才是新持仓


def test_unreadable_holdings_refuse_instead_of_recording_a_flat_day():
    px = _px()
    px.iloc[2, 0] = np.nan
    with pytest.raises(ValueError, match="读不到"):
        run_nav(px, {px.index[0]: {"A": 0.9, "B": 0.1}}, cost_bps=0, min_quoted_weight=0.5)


def test_missing_quote_counts_as_filled_not_hidden():
    px = _px()
    px.iloc[2, 1] = np.nan
    rows = run_nav(px, {px.index[0]: {"A": 0.5, "B": 0.5}}, cost_bps=0, min_quoted_weight=0.4)
    assert rows[2]["n_filled"] == 1


def test_existing_books_are_reproduced_bit_for_bit():
    """beta_plus 与 tokenization_tilt 迁到公用内核前后逐位一致(迁移时用固定种子的合成面板对照过)。"""
    import inspect
    from src.data.signals import beta_plus_momentum as bp, tokenization_tilt as tt
    assert "run_nav" in inspect.getsource(bp._simulate)
    assert "run_nav" in inspect.getsource(tt.compute_path)
    assert "nav *= 1 + ret" not in inspect.getsource(bp) and "nav *= 1 + ret" not in inspect.getsource(tt)


def test_scorecard_compares_each_book_to_its_benchmark_over_its_own_dates():
    from src.data.accounting import registry as rg
    idx = pd.date_range("2026-09-01", periods=10, freq="D")
    navs = {"beta_plus_w": pd.Series(np.linspace(1, 1.10, 10), index=idx)}
    bench = {"beta_plus_w": pd.Series(np.linspace(1, 1.30, 10), index=pd.date_range("2026-08-27", periods=10, freq="D"))}
    navs["beta_plus_w"] = navs["beta_plus_w"].drop(idx[3])                 # 缺一天
    row = next(r for r in rg.scorecard_rows(navs, bench) if r["id"] == "beta_plus_w")
    assert row["missing_days"] == 1 and abs(row["total_return"] - 0.10) < 1e-12
    seg = bench["beta_plus_w"][bench["beta_plus_w"].index >= idx[0]]
    assert abs(row["benchmark_return"] - (seg.iloc[-1] / seg.iloc[0] - 1)) < 1e-12   # 同一段日期
    assert row["accounting"] == "shared_kernel"
    empty = next(r for r in rg.scorecard_rows({}, {}) if r["id"] == "causal_paper")
    assert empty["note"] == "没有可用的 NAV"


def test_registry_never_drops_books_and_flags_untrusted_ones():
    from src.data.accounting import registry as rg
    ids = [b.id for b in rg.BOOKS]
    assert len(ids) == len(set(ids)) and {"beta_core", "fusion_paper", "two_layer_paper"} <= set(ids)
    assert "T-026" in next(b for b in rg.BOOKS if b.id == "fusion_paper").caveat
