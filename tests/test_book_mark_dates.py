"""S-483:按 00:05 UTC 估值点打标的账本,mark_date 覆盖的是前一天;交给成绩单与 L3 前统一到市场日。"""
import asyncio

import pandas as pd

from src.data.accounting import registry as reg


def test_valuation_books_are_declared():
    by = {b.id: b for b in reg.BOOKS}
    for k in ("beta_core", "causal_paper", "scalable_book", "combined_book", "dingge_paper", "fusion_paper", "two_layer_paper"):
        assert by[k].stamp == "valuation_next_day", k
    for k in ("core_cap", "beta_plus_w", "beta_plus_m", "tokenization_tilt", "hl_mech", "hl_jev"):
        assert by[k].stamp == "close", k


def test_load_navs_shifts_valuation_books_to_the_market_day(monkeypatch):
    import src.data.style.header as hdr

    async def fake_read_all(table, params):
        if table == "beta_core_nav":
            return [{"mark_date": "2026-10-03", "nav": 1.0, "benchmark_nav": 1.0, "inception_id": "v5"},
                    {"mark_date": "2026-10-04", "nav": 1.01, "benchmark_nav": 1.0, "inception_id": "v5"}]
        if table == "causal_paper_nav":
            return [{"mark_date": "2026-10-03", "nav": 1.0, "daily_return": 0.0},
                    {"mark_date": "2026-10-04", "nav": 0.99, "daily_return": -0.01}]
        if table == "core_cap_daily":
            return [{"d": "2026-10-02", "arm": "cap_a1", "nav": 0.999}, {"d": "2026-10-03", "arm": "cap_a1", "nav": 1.005}]
        return []

    async def fake_core():
        return pd.Series([1.0, 1.01], index=pd.to_datetime(["2026-10-02", "2026-10-03"]))
    monkeypatch.setattr(hdr, "_read_all", fake_read_all)
    monkeypatch.setattr(reg, "_core_benchmark", fake_core)
    navs, bench = asyncio.run(reg.load_navs())
    assert list(navs["beta_core"].index.strftime("%Y-%m-%d")) == ["2026-10-02", "2026-10-03"]
    assert list(navs["causal_paper"].index.strftime("%Y-%m-%d")) == ["2026-10-02", "2026-10-03"]
    assert list(navs["core_cap"].index.strftime("%Y-%m-%d")) == ["2026-10-02", "2026-10-03"]   # 内核账本不动
    assert bench["beta_core"] is not None and bench["beta_core"].index.max() == pd.Timestamp("2026-10-03")
