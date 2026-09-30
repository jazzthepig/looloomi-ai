"""T-039 风格表头:两个维度(层级每币一个、板块每币多个)、PIT 档位、时间戳语义、指数计算、拒绝条件。"""
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from src.data.style import header as h
from src.data.style import taxonomy as t


def test_tier_and_sectors_are_independent_dimensions():
    """Jazz 09-30:「公链和分类不冲突,NEAR 也是区块链里 AI 最重要的。」"""
    assert t.classify("NEAR", ["artificial-intelligence", "layer-1"]) == ("l1", frozenset({"ai"}))
    assert t.classify("TAO", ["artificial-intelligence", "layer-1"]) == ("l1", frozenset({"ai"}))
    assert t.classify("INJ", ["decentralized-finance-defi", "layer-1", "real-world-assets-rwa"]) == \
        ("l1", frozenset({"defi", "infra_tokenization"}))
    assert t.classify("DOGE", ["layer-1", "meme-token"]) == ("l1", frozenset({"meme"}))
    assert t.classify("FET", ["artificial-intelligence"]) == ("app", frozenset({"ai"}))
    assert t.classify("ARB", ["layer-2"]) == ("l2", frozenset())
    assert t.classify("BTC", ["layer-1"]) == ("majors", frozenset())
    assert t.classify("STETH", ["liquid-staking-tokens", "decentralized-finance-defi"]) is None


def test_l1_tier_is_point_in_time():
    base = {f"L{i}": "l1" for i in range(12)} | {"ARB": "l2", "UNI": "app"}
    mc = {f"L{i}": 100 - i for i in range(12)} | {"ARB": 50, "UNI": 10}
    s = t.resolve_tiers(base, mc)
    assert s["L0"] == "top_l1" and s["L9"] == "top_l1" and s["L10"] == "second_l1_l2"
    assert s["ARB"] == "second_l1_l2" and s["UNI"] == "app"
    s2 = t.resolve_tiers(base, dict(mc, L11=1000))            # 某天 L11 市值冲进前 10
    assert s2["L11"] == "top_l1" and s2["L9"] == "second_l1_l2"
    assert "L3" not in t.resolve_tiers(base, {k: v for k, v in mc.items() if k != "L3"})


def test_a_coin_sits_in_one_tier_and_every_sector_it_belongs_to():
    tier = {"NEAR": "l1", "FET": "app", "SOL": "l1"}
    sec = {"NEAR": frozenset({"ai"}), "FET": frozenset({"ai"}), "SOL": frozenset()}
    m = t.members_by_index(tier, sec, {"NEAR": 5e9, "FET": 1e9, "SOL": 8e10})
    assert "NEAR" in m["ai"] and "FET" in m["ai"] and "NEAR" in m["top_l1"]
    assert sum("NEAR" in v for k, v in m.items() if k in t.TIERS) == 1


def test_market_chart_midnight_point_is_the_previous_day_and_now_point_is_dropped():
    ms = lambda y, m, d, hh=0: int(datetime(y, m, d, hh, tzinfo=timezone.utc).timestamp() * 1000)
    pts = h.parse_market_chart([[ms(2026, 9, 28), 1.0], [ms(2026, 9, 29), 2.0], [ms(2026, 9, 29, 13), 3.0]],
                               [[ms(2026, 9, 28), 10.0], [ms(2026, 9, 29), 20.0]])
    assert [p["d"] for p in pts] == ["2026-09-27", "2026-09-28"] and pts[-1]["price"] == 2.0


def test_capped_weights_respect_the_cap_and_sum_to_one():
    w = h.capped_weights(pd.Series({"A": 90.0, "B": 5.0, "C": 3.0, "D": 2.0}))
    assert abs(w.sum() - 1) < 1e-9 and w.max() <= 0.40 + 1e-9
    w2 = h.capped_weights(pd.Series({"BTC": 70.0, "ETH": 30.0}))       # 两个成员:上限做不到 ⇒ 真实市值权重
    assert np.allclose(w2.values, [0.7, 0.3])


def _frame(days, cols):
    return pd.DataFrame(cols, index=pd.date_range("2026-01-01", periods=days, freq="D"))


def test_sector_index_includes_chains_that_carry_the_tag():
    px = _frame(3, {"NEAR": [1, 1.2, 1.2], "FET": [1, 1.1, 1.1], "RNDR": [1, 1.0, 1.0], "SOL": [1, 1, 1]})
    mc = _frame(3, {"NEAR": [5e9] * 3, "FET": [1e9] * 3, "RNDR": [1e9] * 3, "SOL": [8e10] * 3})
    tier = {"NEAR": "l1", "FET": "app", "RNDR": "app", "SOL": "l1"}
    sec = {"NEAR": frozenset({"ai"}), "FET": frozenset({"ai"}), "RNDR": frozenset({"ai"}), "SOL": frozenset()}
    rows = h.compute_style_index(px, mc, tier, sec, start="2026-01-02", end="2026-01-02")
    ai = next(r for r in rows if r["style"] == "ai" and r["weighting"] == "equal")
    assert ai["dimension"] == "sector" and "NEAR" in ai["members"] and abs(ai["ret"] - 0.1) < 1e-12


def test_index_uses_previous_day_caps_and_refuses_thin_days():
    px = _frame(5, {"A": [1, 1.1, 1.21, 1.21, 1.21], "B": [1] * 5, "C": [1, 1, 1, 1.1, 1.1], "M": [1, 2, 2, 2, 2]})
    mc = _frame(5, {"A": [300e6] * 5, "B": [100e6] * 5, "C": [100e6] * 5, "M": [5e6] * 5})
    tier = {"A": "app", "B": "app", "C": "app", "M": "app"}
    sec = {"A": frozenset({"defi"}), "B": frozenset({"defi"}), "C": frozenset({"defi"}), "M": frozenset({"meme"})}
    rows = h.compute_style_index(px, mc, tier, sec, start="2026-01-02", end="2026-01-05")
    defi_eq = [r for r in rows if r["style"] == "defi" and r["weighting"] == "equal"]
    assert len(defi_eq) == 4 and abs(defi_eq[0]["ret"] - 0.1 / 3) < 1e-12
    cap = next(r for r in rows if r["style"] == "defi" and r["weighting"] == "cap" and r["d"] == "2026-01-02")
    assert cap["top_member"] == "A" and cap["top_weight"] <= 0.40 + 1e-9
    assert not any(r["style"] == "meme" for r in rows)            # 成员不够 ⇒ 不出行,不是 0
    assert all(r["basis"] == h.BASIS_BACKFILL for r in rows)


def test_a_missing_day_breaks_the_return_instead_of_spanning_it():
    idx = pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-04"])
    px = pd.DataFrame({"A": [1, 1, 2], "B": [1, 1, 2], "C": [1, 1, 2]}, index=idx)
    mc = pd.DataFrame({"A": [1e9] * 3, "B": [1e9] * 3, "C": [1e9] * 3}, index=idx)
    rows = h.compute_style_index(px, mc, {k: "app" for k in "ABC"}, {k: frozenset({"ai"}) for k in "ABC"},
                                 start="2026-01-02", end="2026-01-04")
    assert [r["d"] for r in rows if r["style"] == "ai" and r["weighting"] == "equal"] == ["2026-01-02"]


def test_levels_continue_from_the_stored_level():
    px = _frame(3, {"A": [1, 1.1, 1.1], "B": [1, 1.1, 1.1], "C": [1, 1.1, 1.1]})
    mc = _frame(3, {"A": [1e9] * 3, "B": [1e9] * 3, "C": [1e9] * 3})
    rows = h.compute_style_index(px, mc, {k: "app" for k in "ABC"}, {k: frozenset({"ai"}) for k in "ABC"},
                                 start="2026-01-02", end="2026-01-02", prev_level={("ai", "equal"): 2.0})
    assert abs(next(r for r in rows if r["style"] == "ai" and r["weighting"] == "equal")["level"] - 2.2) < 1e-12


def test_majors_need_only_two_members():
    px = _frame(3, {"BTC": [1, 1.1, 1.1], "ETH": [1, 1.2, 1.2]})
    mc = _frame(3, {"BTC": [2e12] * 3, "ETH": [5e11] * 3})
    rows = h.compute_style_index(px, mc, {"BTC": "majors", "ETH": "majors"}, start="2026-01-02", end="2026-01-02")
    eq = next(r for r in rows if r["style"] == "majors" and r["weighting"] == "equal")
    assert abs(eq["ret"] - 0.15) < 1e-12 and eq["dimension"] == "tier"
    cap = next(r for r in rows if r["style"] == "majors" and r["weighting"] == "cap")
    assert abs(cap["ret"] - (0.8 * 0.1 + 0.2 * 0.2)) < 1e-12 and abs(cap["top_weight"] - 0.8) < 1e-12


def test_tiny_caps_and_bad_prints_stay_out():
    """v1 首轮:等权单日「收益」+116,682% —— 小市值币的坏点。"""
    px = _frame(3, {"A": [1, 1.1, 1.1], "B": [1, 1.1, 1.1], "C": [1, 1.1, 1.1], "D": [1, 1.1, 1.1],
                    "TINY": [1e-6, 1.0, 1.0], "GLITCH": [1, 1000, 1000]})
    mc = _frame(3, {k: [1e9] * 3 for k in "ABCD"} | {"TINY": [1e6] * 3, "GLITCH": [1e9] * 3})
    rows = h.compute_style_index(px, mc, {k: "app" for k in px.columns},
                                 {k: frozenset({"meme"}) for k in px.columns}, start="2026-01-02", end="2026-01-02")
    eq = next(r for r in rows if r["style"] == "meme" and r["weighting"] == "equal")
    assert "TINY" not in eq["members"] and "GLITCH" not in eq["members"] and eq["n_dropped"] == 1
    assert abs(eq["ret"] - 0.1) < 1e-12


def test_price_pegged_tokens_are_cash_not_style_exposure():
    n = 40
    rng = np.random.default_rng(1)
    cols = {k: np.cumprod(1 + 0.03 * rng.standard_normal(n)) for k in ("A", "B", "C")}
    cols["TBILL"] = 1 + 0.0001 * np.arange(n)
    px = _frame(n, cols)
    mc = _frame(n, {k: [1e9] * n for k in cols})
    rows = h.compute_style_index(px, mc, {k: "app" for k in cols}, {k: frozenset({"infra_tokenization"}) for k in cols},
                                 start="2026-02-05", end="2026-02-09")
    assert rows and all("TBILL" not in r["members"] for r in rows)


def test_book_exposure_tiers_sum_to_one_sectors_may_overlap():
    w = {"BTC": 0.3, "ETH": 0.2, "NEAR": 0.25, "DOGE": 0.25, "ZZZ": 0.0}
    tiers = {"BTC": "majors", "ETH": "majors", "NEAR": "top_l1", "DOGE": "top_l1"}
    sec = {"NEAR": frozenset({"ai"}), "DOGE": frozenset({"meme"})}
    sh = {(d, k): v for d, k, v in h.exposure_shares(w, tiers, sec)}
    assert abs(sum(v for (d, _), v in sh.items() if d == "tier") - 1) < 1e-12
    assert abs(sh[("tier", "top_l1")] - 0.5) < 1e-12 and abs(sh[("sector", "ai")] - 0.25) < 1e-12
    sh2 = {(d, k): v for d, k, v in h.exposure_shares({"BTC": 0.5, "NEW": 0.5}, tiers, sec)}
    assert abs(sh2[("tier", "unclassified")] - 0.5) < 1e-12


def test_extra_members_cover_panel_coins_missing_from_category_lists():
    assert t.EXTRA_MEMBERS["TON"][0] == "the-open-network"
    assert {"DOT", "ATOM", "POLYX"} <= set(t.EXTRA_MEMBERS)
    assert set(t.STYLES) == set(t.TIERS) | set(t.SECTORS) and not set(t.TIERS) & set(t.SECTORS)


def test_public_style_index_route_rejects_unknown_styles(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from src.api.routers import ohlcv
    app = FastAPI(); app.include_router(ohlcv.router)
    c = TestClient(app)
    assert c.get("/api/v1/style/index?style=nope").status_code == 400
    assert c.get("/api/v1/style/index?style=ai&weighting=weird").status_code == 422
