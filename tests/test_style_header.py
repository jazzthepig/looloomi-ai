"""T-039 风格表头:分类优先级、PIT 档位、时间戳语义、指数计算、拒绝条件。"""
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from src.data.style import header as h
from src.data.style import taxonomy as t


def test_priority_meme_beats_layer1_and_exclusions_win():
    assert t.base_style("BTC", ["layer-1"]) == "majors"
    assert t.base_style("DOGE", ["layer-1", "meme-token"]) == "meme"
    assert t.base_style("NEAR", ["artificial-intelligence", "layer-1"]) == "l1"   # v2:先是一条链
    assert t.base_style("TAO", ["artificial-intelligence", "layer-1"]) == "ai"    # 显式例外
    assert t.base_style("FET", ["artificial-intelligence"]) == "ai"
    assert t.base_style("LINK", ["oracle", "decentralized-finance-defi"]) == "infra_tokenization"
    assert t.base_style("STETH", ["liquid-staking-tokens", "decentralized-finance-defi"]) is None
    assert t.base_style("XYZ", []) is None


def test_l1_tier_is_point_in_time():
    base = {f"L{i}": "l1" for i in range(12)} | {"ARB": "l2", "UNI": "defi"}
    mc = {f"L{i}": 100 - i for i in range(12)} | {"ARB": 50, "UNI": 10}
    s = t.resolve_styles(base, mc)
    assert s["L0"] == "top_l1" and s["L9"] == "top_l1" and s["L10"] == "second_l1_l2"
    assert s["ARB"] == "second_l1_l2" and s["UNI"] == "defi"
    mc2 = dict(mc, L11=1000)                   # 某天 L11 市值冲进前 10
    s2 = t.resolve_styles(base, mc2)
    assert s2["L11"] == "top_l1" and s2["L9"] == "second_l1_l2"
    assert "L3" not in t.resolve_styles(base, {k: v for k, v in mc.items() if k != "L3"})   # 没有 d-1 市值 ⇒ 当天不归类


def test_market_chart_midnight_point_is_the_previous_day_and_now_point_is_dropped():
    ms = lambda y, m, d, hh=0: int(datetime(y, m, d, hh, tzinfo=timezone.utc).timestamp() * 1000)
    pts = h.parse_market_chart([[ms(2026, 9, 28), 1.0], [ms(2026, 9, 29), 2.0], [ms(2026, 9, 29, 13), 3.0]],
                               [[ms(2026, 9, 28), 10.0], [ms(2026, 9, 29), 20.0]])
    assert [p["d"] for p in pts] == ["2026-09-27", "2026-09-28"] and pts[-1]["price"] == 2.0


def test_capped_weights_respect_the_cap_and_sum_to_one():
    w = h.capped_weights(pd.Series({"A": 90.0, "B": 5.0, "C": 3.0, "D": 2.0}))
    assert abs(w.sum() - 1) < 1e-9 and w.max() <= 0.40 + 1e-9
    w2 = h.capped_weights(pd.Series({"A": 90.0, "B": 10.0}))       # 两个成员,40% 上限做不到
    assert np.allclose(w2.values, 0.5)


def _frame(days, cols):
    return pd.DataFrame(cols, index=pd.date_range("2026-01-01", periods=days, freq="D"))


def test_index_uses_previous_day_caps_and_refuses_thin_days():
    days = 5
    px = _frame(days, {"A": [1, 1.1, 1.21, 1.21, 1.21], "B": [1, 1, 1, 1, 1], "C": [1, 1, 1, 1.1, 1.1],
                       "M": [1, 2, 2, 2, 2]})
    mc = _frame(days, {"A": [300e6] * days, "B": [100e6] * days, "C": [100e6] * days, "M": [5e6] * days})
    base = {"A": "defi", "B": "defi", "C": "defi", "M": "meme"}
    rows = h.compute_style_index(px, mc, base, start="2026-01-02", end="2026-01-05")
    defi_eq = [r for r in rows if r["style"] == "defi" and r["weighting"] == "equal"]
    assert len(defi_eq) == 4 and abs(defi_eq[0]["ret"] - 0.1 / 3) < 1e-12
    cap = next(r for r in rows if r["style"] == "defi" and r["weighting"] == "cap" and r["d"] == "2026-01-02")
    assert cap["top_member"] == "A" and cap["top_weight"] <= 0.40 + 1e-9
    assert not any(r["style"] == "meme" for r in rows)            # 只有 1 个成员 ⇒ 不出行,不是 0
    assert all(r["basis"] == h.BASIS_BACKFILL for r in rows)


def test_a_missing_day_breaks_the_return_instead_of_spanning_it():
    idx = pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-04"])
    px = pd.DataFrame({"A": [1, 1, 2], "B": [1, 1, 2], "C": [1, 1, 2]}, index=idx)
    mc = pd.DataFrame({"A": [1e9] * 3, "B": [1e9] * 3, "C": [1e9] * 3}, index=idx)
    rows = h.compute_style_index(px, mc, {"A": "ai", "B": "ai", "C": "ai"}, start="2026-01-02", end="2026-01-04")
    assert [r["d"] for r in rows if r["weighting"] == "equal"] == ["2026-01-02"]


def test_levels_continue_from_the_stored_level():
    px = _frame(3, {"A": [1, 1.1, 1.1], "B": [1, 1.1, 1.1], "C": [1, 1.1, 1.1]})
    mc = _frame(3, {"A": [1e9] * 3, "B": [1e9] * 3, "C": [1e9] * 3})
    rows = h.compute_style_index(px, mc, {"A": "ai", "B": "ai", "C": "ai"}, start="2026-01-02", end="2026-01-02",
                                 prev_level={("ai", "equal"): 2.0})
    r = next(r for r in rows if r["weighting"] == "equal")
    assert abs(r["level"] - 2.2) < 1e-12


def test_every_category_id_maps_to_a_style_slug():
    for style, _ in t.CATEGORY_PRIORITY:
        assert style in t.STYLES or style in ("l1", "l2")


def test_majors_need_only_two_members():
    px = _frame(3, {"BTC": [1, 1.1, 1.1], "ETH": [1, 1.2, 1.2]})
    mc = _frame(3, {"BTC": [2e12] * 3, "ETH": [5e11] * 3})
    rows = h.compute_style_index(px, mc, {"BTC": "majors", "ETH": "majors"}, start="2026-01-02", end="2026-01-02")
    assert {r["weighting"] for r in rows} == {"cap", "equal"}
    eq = next(r for r in rows if r["weighting"] == "equal")
    assert abs(eq["ret"] - 0.15) < 1e-12


def test_tiny_caps_and_bad_prints_stay_out():
    """v1 首轮:等权单日「收益」+116,682% —— 小市值币的坏点。d-1 市值 < 2000 万不进;单日 > +500% 当坏点。"""
    px = _frame(3, {"A": [1, 1.1, 1.1], "B": [1, 1.1, 1.1], "C": [1, 1.1, 1.1], "D": [1, 1.1, 1.1],
                    "TINY": [1e-6, 1.0, 1.0], "GLITCH": [1, 1000, 1000]})
    mc = _frame(3, {"A": [1e9] * 3, "B": [1e9] * 3, "C": [1e9] * 3, "D": [1e9] * 3,
                    "TINY": [1e6] * 3, "GLITCH": [1e9] * 3})
    base = {k: "meme" for k in px.columns}
    rows = h.compute_style_index(px, mc, base, start="2026-01-02", end="2026-01-02")
    eq = next(r for r in rows if r["weighting"] == "equal")
    assert "TINY" not in eq["members"] and "GLITCH" not in eq["members"] and eq["n_dropped"] == 1
    assert abs(eq["ret"] - 0.1) < 1e-12


def test_extra_members_cover_panel_coins_missing_from_category_lists():
    assert t.EXTRA_MEMBERS["TON"][0] == "the-open-network"        # 不是撞名的 Tokamak
    assert {"DOT", "ATOM", "POLYX"} <= set(t.EXTRA_MEMBERS)


def test_price_pegged_tokens_are_cash_not_style_exposure():
    """RWA 分类里混着代币化国债,价格钉在 1:过去 30 天波动 < 0.5% 的币当天不进指数。"""
    n = 40
    rng = np.random.default_rng(1)
    cols = {k: np.cumprod(1 + 0.03 * rng.standard_normal(n)) for k in ("A", "B", "C")}
    cols["TBILL"] = 1 + 0.0001 * np.arange(n)
    px = _frame(n, cols)
    mc = _frame(n, {k: [1e9] * n for k in cols})
    rows = h.compute_style_index(px, mc, {k: "infra_tokenization" for k in cols},
                                 start="2026-02-05", end="2026-02-09")
    assert rows and all("TBILL" not in r["members"] for r in rows)


def test_book_exposure_is_holdings_summed_by_style():
    w = {"BTC": 0.3, "ETH": 0.2, "SOL": 0.25, "DOGE": 0.25, "ZZZ": 0.0}
    st = {"BTC": "majors", "ETH": "majors", "SOL": "top_l1", "DOGE": "meme"}
    sh = h.style_shares(w, st)
    assert abs(sh["majors"] - 0.5) < 1e-12 and abs(sh["meme"] - 0.25) < 1e-12 and "unclassified" not in sh
    sh2 = h.style_shares({"BTC": 0.5, "NEW": 0.5}, st)
    assert abs(sh2["unclassified"] - 0.5) < 1e-12          # 未归类单列,不丢
