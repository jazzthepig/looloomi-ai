"""S-473:① = 市值加权、单币 ≤ 40%。权重函数、再平衡节奏、记账走公用内核、登记表与 L3 指向它。"""
import numpy as np
import pandas as pd
import pytest

from src.data.signals import core_cap as cc


def test_capped_weights_respects_the_cap_and_sums_to_one():
    mc = {"BTC": 60.0, "ETH": 20.0, "SOL": 10.0, "XRP": 5.0, "ADA": 5.0}
    w = cc.capped_weights(mc, 1.0)
    assert w["BTC"] == pytest.approx(0.40)
    assert sum(w.values()) == pytest.approx(1.0)
    assert max(w.values()) <= 0.40 + 1e-9
    # 超出部分按其余的原始市值比例分:ETH : SOL = 2 : 1 仍保持
    assert w["ETH"] / w["SOL"] == pytest.approx(2.0)


def test_capped_weights_iterates_when_redistribution_pushes_another_over():
    mc = {"BTC": 50.0, "ETH": 45.0, "SOL": 3.0, "XRP": 1.0, "ADA": 1.0}
    w = cc.capped_weights(mc, 1.0)
    assert w["BTC"] == pytest.approx(0.40) and w["ETH"] == pytest.approx(0.40)
    assert sum(w.values()) == pytest.approx(1.0)


def test_alpha_zero_is_equal_weight_and_missing_mcap_is_excluded():
    w = cc.capped_weights({"A": 100.0, "B": 1.0, "C": 3.0, "D": float("nan")}, 0.0)
    assert set(w) == {"A", "B", "C"} and all(v == pytest.approx(1 / 3) for v in w.values())


def test_infeasible_cap_raises_instead_of_breaking_it():
    with pytest.raises(ValueError):
        cc.capped_weights({"A": 1.0, "B": 1.0}, 1.0)


def _panel(days, syms, seed=0):
    rng = np.random.default_rng(seed)
    px = pd.DataFrame(100 * np.exp(np.cumsum(0.02 * rng.standard_normal((len(days), len(syms))), axis=0)),
                      index=days, columns=syms)
    mc = pd.DataFrame({s: 1e9 * (i + 1) ** 2 for i, s in enumerate(syms)}, index=days)
    return px, mc


def test_path_rebalances_on_inception_and_mondays_only_and_core_is_capped():
    days = pd.date_range(cc.INCEPTION, periods=12, freq="D")
    syms = ["A", "B", "C", "D", "E"]
    px, mc = _panel(days, syms)
    rows = cc.compute_path(px, mc, [], "test")
    core = [r for r in rows if r["arm"] == cc.CORE_ARM]
    assert len(core) == 12 and core[0]["nav"] == pytest.approx(1 - core[0]["turnover"] * cc.COST_BPS / 1e4)
    rebal_days = {pd.Timestamp(r["d"]) for r in core if r["rebalanced"]}
    assert rebal_days == {d for d in days if d == cc.INCEPTION or d.weekday() == 0}
    assert all(r["max_weight"] <= 0.40 + 1e-6 for r in core if r["rebalanced"])
    assert {r["arm"] for r in rows} == set(cc.ARMS)


def test_path_refuses_a_day_with_too_little_priced_weight():
    days = pd.date_range(cc.INCEPTION, periods=4, freq="D")
    px, mc = _panel(days, ["A", "B", "C", "D", "E"])
    px.loc[days[2], "E"] = np.nan          # E 是最大市值 ⇒ 40% 无报价
    px.loc[days[2], "D"] = np.nan
    with pytest.raises(ValueError):
        cc.compute_path(px, mc, [], "test")


def test_registry_and_allocator_point_at_the_cap_weighted_core():
    from src.data.accounting.registry import BOOKS
    from src.data.allocation import allocator as al
    by_id = {b.id: b for b in BOOKS}
    assert al.CORE == "core_cap" and by_id["core_cap"].layer == "①"
    assert by_id["core_cap"].table == cc.TABLE and by_id["core_cap"].arm == cc.CORE_ARM
    assert by_id["beta_core"].layer == "②"          # 原 ①,登记永远在(v0.2 P2)
    assert [b.id for b in BOOKS if b.layer == "①"] == ["core_cap"]


def test_scorecard_tells_one_day_from_unreadable():
    from src.data.accounting.registry import scorecard_rows
    one = pd.Series([0.999], index=pd.to_datetime(["2026-10-02"]))
    rows = {r["id"]: r for r in scorecard_rows({"core_cap": one}, {})}
    assert "只有起点一天" in rows["core_cap"]["note"]
    assert rows["beta_core"]["note"] == "没有可用的 NAV"


def test_rebalance_refuses_when_mcap_covers_too_little_of_the_panel():
    days = pd.date_range(cc.INCEPTION, periods=3, freq="D")
    syms = ["A", "B", "C", "D", "E"]
    px, mc = _panel(days, syms)
    mc.loc[cc.INCEPTION, ["A", "B"]] = np.nan          # 只有 3/5 = 60% 有市值
    with pytest.raises(ValueError):
        cc.compute_path(px, mc, [], "test")


def test_quarantine_label_is_not_a_source():
    from src.data.market import source_freshness as sf
    rows = [{"source": "binance_hist_ffill", "last_bar": "2026-08-08", "age_days": 57,
             "symbols_recent": 0, "symbols_typical": None},
            {"source": "binance_hist", "last_bar": "2026-10-03", "age_days": 1,
             "symbols_recent": 200, "symbols_typical": 210}]
    hs = sf.from_rows(rows)
    assert [h.source for h in hs] == ["binance_hist"]
    assert "binance_hist_ffill" not in sf.overall(hs)["unregistered_sources"]


def test_ops_console_does_not_call_the_core_price_source_retired():
    import importlib.util, pathlib
    spec = importlib.util.spec_from_file_location("oc", pathlib.Path(__file__).resolve().parents[1] / "scripts/ops_console.py")
    oc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(oc)
    assert "binance_hist" not in oc.RETIRED_BY_POLICY and cc.PRICE_SOURCE == "binance_hist"


def test_ls_books_are_scored_against_the_core_not_equal_weight(monkeypatch):
    """S-482:成绩单的基准 = ① 本身(回放段 α=1 + 前向段 core_cap),不是等权面板。"""
    import asyncio
    from src.data.accounting import registry as reg
    import src.api.store as store
    import src.data.style.header as hdr

    async def fake_rpc(fn, payload):
        assert fn == "core_alpha_daily"
        return [{"alpha": 1.0, "d": "2026-10-01", "ret": 0.01}, {"alpha": 0.0, "d": "2026-10-01", "ret": 0.5},
                {"alpha": 1.0, "d": "2026-10-02", "ret": 0.02}, {"alpha": 1.0, "d": "2026-10-03", "ret": 0.9}]

    async def fake_read_all(table, params):
        assert table == cc.TABLE and params["arm"] == f"eq.{cc.CORE_ARM}"
        return [{"d": "2026-10-02", "nav": 0.999}, {"d": "2026-10-03", "nav": 0.999 * 1.03}]
    monkeypatch.setattr(store, "supabase_rpc", fake_rpc)
    monkeypatch.setattr(hdr, "_read_all", fake_read_all)
    s = asyncio.run(reg._core_benchmark())
    # 10-01、10-02 用回放(α=1),10-03 用前向(+3%),回放里 10-03 的 +90% 不用;α=0 的行不用
    assert s.iloc[-1] == pytest.approx(1.01 * 1.02 * 1.03)
    assert all(b.benchmark in ("core",) or b.benchmark.startswith("arm:") or b.benchmark == "own_benchmark_nav"
               for b in reg.BOOKS)


def test_ops_console_files_old_force_mark_beats_as_no_action():
    import importlib.util, pathlib
    spec = importlib.util.spec_from_file_location("oc2", pathlib.Path(__file__).resolve().parents[1] / "scripts/ops_console.py")
    oc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(oc)
    rows = {"rows": [{"loop": "_book_fusion_loop", "verdict": "failing", "stale_build": True, "age_s": 343 * 3600,
                      "last_error": "durable_write_failed", "n_consecutive_failures": 1},
                     {"loop": "_style_header_loop", "verdict": "failing", "stale_build": False, "age_s": 600,
                      "last_error": "timeout", "n_consecutive_failures": 1}]}
    out = {c["name"]: c["remedy_class"] for c in oc._classify_loops(rows)}
    assert out == {"_book_fusion_loop": "no_action", "_style_header_loop": "act_now"}
