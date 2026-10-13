"""S-543 策略拼组合 · S-544 规模 / 容量口径 · S-545 基金星级 —— 纯函数测试。"""
import math

import numpy as np
import pandas as pd
import pytest

from src.api.contracts import fund
from src.data.accounting import capacity as cap
from src.data.accounting.combine import LAYER_SOURCE, MIN_DAYS, combine, parse_weights


def _nav(rets, start="2026-01-01"):
    idx = pd.date_range(start, periods=len(rets) + 1, freq="D")
    return pd.Series(np.cumprod([1.0] + [1 + r for r in rets]), index=idx)


# ── S-543 拼组合 ────────────────────────────────────────────────────────────

def test_parse_weights_percent_fraction_and_junk():
    assert parse_weights("a:60,b:0.4") == {"a": 0.6, "b": 0.4}
    assert parse_weights("a:0.3,a:0.2") == {"a": 0.5}
    assert parse_weights("a:-0.2,b:x,c,:0.5,d:0") == {}


def test_single_book_full_weight_is_the_book():
    rng = np.random.default_rng(1)
    r = rng.normal(0.001, 0.02, 40)
    out = combine({"a": _nav(r)}, {"a": 1.0}, {"a": "①"})
    assert out["ok"] and out["days"] == 40 and out["estimable"] and not out["annualised"]
    assert out["portfolio"]["ann_return"] is None and out["portfolio"]["sharpe"] is None
    assert out["portfolio"]["total_return"] == pytest.approx(np.prod(1 + r) - 1)
    assert out["books"][0]["risk_contribution"] == pytest.approx(1.0)
    assert out["return_sources_by_layer"] == {"beta": pytest.approx(r.sum())}


def test_cash_earns_zero_and_scales_the_book():
    r = np.full(30, 0.01)
    out = combine({"a": _nav(r)}, {"a": 0.5}, {"a": "①"})
    assert out["cash_weight"] == 0.5
    assert out["portfolio"]["total_return"] == pytest.approx(1.005 ** 30 - 1)


def test_weights_over_one_are_normalised():
    r = np.full(25, 0.01)
    out = combine({"a": _nav(r), "b": _nav(r)}, {"a": 1.0, "b": 1.0}, {"a": "①", "b": "④"})
    assert out["cash_weight"] == 0.0
    assert sum(b["weight"] for b in out["books"]) == pytest.approx(1.0)


def test_risk_contributions_sum_to_one_and_sources_by_layer():
    rng = np.random.default_rng(7)
    ra, rb = rng.normal(0, 0.03, 60), rng.normal(0, 0.01, 60)
    out = combine({"a": _nav(ra), "b": _nav(rb)}, {"a": 0.6, "b": 0.4}, {"a": "①", "b": "④"})
    rc = [b["risk_contribution"] for b in out["books"]]
    assert sum(rc) == pytest.approx(1.0)
    assert set(out["return_sources_by_layer"]) == {"beta", "alpha"}
    assert sum(out["return_sources_by_layer"].values()) == pytest.approx(
        sum(0.6 * x + 0.4 * y for x, y in zip(ra, rb)))
    assert out["correlation"]["a"]["a"] == pytest.approx(1.0)


def test_short_window_is_described_not_annualised():
    out = combine({"a": _nav([0.01] * 5)}, {"a": 1.0}, {"a": "②"})
    assert out["ok"] and not out["estimable"] and out["days"] < MIN_DAYS
    assert out["portfolio"]["ann_return"] is None and out["portfolio"]["sharpe"] is None


def test_window_is_the_shared_record_only():
    a = _nav([0.01] * 40, start="2026-01-01")
    b = _nav([0.0] * 10, start="2026-02-01")
    out = combine({"a": a, "b": b}, {"a": 0.5, "b": 0.5}, {"a": "①", "b": "③"})
    assert out["days"] == 9                     # b 的 10 个收益日里与 a 重叠的部分
    assert out["window"][0] >= "2026-02-01"


def test_missing_book_is_refused_not_zero():
    out = combine({"a": _nav([0.01] * 30)}, {"a": 0.5, "z": 0.5}, {"a": "①"})
    assert not out["ok"] and "z" in out["reason"]


def test_vs_core_splits_beta_from_residual():
    rng = np.random.default_rng(3)
    c = rng.normal(0.002, 0.03, 400)
    port_r = 1.2 * c + 0.0005
    out = combine({"x": _nav(port_r)}, {"x": 1.0}, {"x": "①+③"}, core=_nav(c))
    vc = out["vs_core"]
    assert vc["beta"] == pytest.approx(1.2, rel=1e-6)
    assert vc["r2"] == pytest.approx(1.0)
    assert vc["alpha_ann"] == pytest.approx(0.0005 * 365, rel=1e-6)


def test_every_registry_layer_has_a_source():
    from src.data.accounting.registry import BOOKS
    unknown = {b.layer for b in BOOKS} - set(LAYER_SOURCE)
    assert not unknown, f"layers without a return-source label: {unknown}"


# ── S-544 规模 / 容量 ───────────────────────────────────────────────────────

def test_fund_sizes_and_fees_are_the_ruling():
    assert fund.TARGET_AUM_USD == 30_000_000 and fund.DESIGN_AUM_USD == 500_000_000
    assert fund.FEES["strategies"]["management_fee"] == 0.0 and fund.FEES["strategies"]["performance_fee"] is True
    assert fund.FEES["regulated_fund_wrapper"]["performance_fee"] is True


def test_las_defaults_come_from_the_fund_contract():
    import inspect
    from src.data.cis.cis_provider import calculate_las
    src = inspect.getsource(calculate_las)
    assert "TARGET_AUM_USD" in src or "fund" in src
    for p in ("aum", "max_position_pct", "participation_rate"):
        assert inspect.signature(calculate_las).parameters[p].default is None


def test_asset_row_days_and_capacity():
    adv = 1_000_000_000.0
    row = cap.asset_row("X", "L1", adv)
    assert row["days_to_build_at_target"] == pytest.approx(
        fund.TARGET_AUM_USD * fund.SATELLITE_POSITION_PCT / (adv * fund.PARTICIPATION_RATE))
    assert row["capacity_aum_usd"] == pytest.approx(
        adv * fund.PARTICIPATION_RATE * fund.BUILD_DAYS / fund.SATELLITE_POSITION_PCT)
    assert row["ok_at_target"] and row["ok_at_design"]
    thin = cap.asset_row("Y", "RWA", 1_000_000.0)
    assert not thin["ok_at_target"] and not thin["ok_at_design"]


def test_asset_without_volume_is_not_treated_as_liquid():
    row = cap.asset_row("Z", "L1", None)
    assert row["capacity_aum_usd"] is None and not row["ok_at_target"] and not row["ok_at_design"]


def test_book_row_binding_name_and_missing_volume():
    adv = {"BTC": 30e9, "SKY": 10e6}
    row = cap.book_row("b", {"BTC": 0.4, "SKY": 0.02, "NEW": 0.01}, adv)
    assert row["binding"]["symbol"] == "SKY"
    assert row["capacity_aum_usd"] == pytest.approx(10e6 * fund.PARTICIPATION_RATE * fund.BUILD_DAYS / 0.02)
    assert row["missing_adv"] == ["NEW"]
    assert row["ok_at_target"] is (row["days_to_build_at_target"] <= fund.BUILD_DAYS)
    empty = cap.book_row("e", {"NEW": 1.0}, adv)
    assert empty["capacity_aum_usd"] is None and empty["missing_adv"] == ["NEW"]


# ── S-545 基金星级 ──────────────────────────────────────────────────────────

def test_fund_stars_bands():
    from src.api.routers.vault import fund_stars
    assert [fund_stars(x) for x in (0, 19.9, 20, 59, 60, 79, 80, 99, 100)] == [1, 1, 2, 3, 4, 4, 5, 5, 5]
    assert fund_stars(None) is None and fund_stars("n/a") is None


def test_public_fund_view_has_stars_not_letter_grade():
    from src.api.routers.vault import _VAULT_FUNDS, STAR_BASIS, fund_view
    for f in _VAULT_FUNDS:
        v = fund_view(f)
        assert "grade" not in v and v["rating_basis"] == STAR_BASIS
        total = (f.get("scores") or {}).get("total")
        assert v["stars"] == (None if total is None else max(1, min(5, int(math.floor(float(total) / 20)) + 1)))


def test_every_book_has_a_public_english_name():
    """页面是英文的、对外的:登记表里的中文名和内部编号(S-/M-/DECISIONS)不能出站。"""
    import re
    from src.data.accounting.combine import PUBLIC
    from src.data.accounting.registry import BOOKS
    assert {b.id for b in BOOKS} <= set(PUBLIC)
    for name, desc in PUBLIC.values():
        txt = name + desc
        assert not re.search(r"[一-鿿]", txt), txt
        assert not re.search(r"\b[SMR]-?\d{2,}\b|DECISIONS", txt), txt


def test_under_a_year_is_never_annualised_and_a_year_is():
    """S-543 上线实测:31 天 +12% 被年化成 +292%、Sharpe 8.5。不足一年不年化(GIPS)。"""
    short = combine({"a": _nav([0.004] * 31)}, {"a": 1.0}, {"a": "②"})
    assert short["estimable"] and not short["annualised"]
    assert short["portfolio"]["ann_return"] is None and short["portfolio"]["sharpe"] is None
    assert short["portfolio"]["ann_vol"] is not None
    year = combine({"a": _nav([0.0002] * 365)}, {"a": 1.0}, {"a": "①"})
    assert year["annualised"] and year["portfolio"]["ann_return"] == pytest.approx(1.0002 ** 365 - 1)


def test_gaps_align_levels_before_returns():
    """一本账缺几天时,两本账的收益必须覆盖同一段时间:先对齐 NAV 再算收益。"""
    idx = pd.date_range("2026-01-01", periods=10, freq="D")
    a = pd.Series(np.cumprod([1.0] + [1.01] * 9), index=idx)
    b = pd.Series(np.cumprod([1.0] + [1.02] * 9), index=idx).drop(idx[3:6])
    out = combine({"a": a, "b": b}, {"a": 0.5, "b": 0.5}, {"a": "①", "b": "④"})
    assert out["days"] == 6 and out["calendar_days"] == 9
    ra = out["books"][0]["book_return"]
    assert ra == pytest.approx(1.01 ** 9 - 1)          # a 在 b 的缺口上算的是同一段 4 天的收益


def test_strategy_page_regime_uses_the_official_spelling_map():
    """S-548:策略页的市场状态来自正式序列(RISK_ON),要换成策略表的键(Risk-On),否则 regime_adaptive 落回默认权重。"""
    from src.api.routers.strategies import _REGIME_BLEND, regime_label
    for off in ("RISK_ON", "RISK_OFF", "TIGHTENING", "EASING", "STAGFLATION", "GOLDILOCKS", "risk-on"):
        assert regime_label(off) in _REGIME_BLEND, off
    assert regime_label(None) is None and regime_label("??") is None
    import inspect
    from src.api.routers import strategies
    src = inspect.getsource(strategies)
    assert src.count("await _current_regime()") >= 3, "list / detail / compare must read the official state"


def test_series_endpoint_serves_only_our_own_books() -> None:
    """S-565:研究(含 lane)读账本序列不用数据库 key;只给我们算出来的账本,不给数据商的原始价格。"""
    import asyncio
    import pytest
    from fastapi import HTTPException
    from src.api.routers.portfolio_builder import SERIES_TABLES, portfolio_series
    assert "ohlcv_daily" not in SERIES_TABLES and "asset_mcap_daily" not in SERIES_TABLES
    for bad in (dict(table="ohlcv_daily"), dict(table="core_cap_daily", start="2023-13-01"),
                dict(table="core_cap_daily", arm="x;drop")):
        with pytest.raises(HTTPException) as e:
            asyncio.run(portfolio_series(**{"arm": None, "start": "2023-01-01", **bad}))
        assert e.value.status_code == 400
