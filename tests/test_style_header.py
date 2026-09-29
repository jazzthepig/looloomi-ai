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
    assert t.base_style("FET", ["artificial-intelligence", "layer-1"]) == "ai"
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
    mc = _frame(days, {"A": [300] * days, "B": [100] * days, "C": [100] * days, "M": [5] * days})
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
    mc = pd.DataFrame({"A": [1, 1, 1], "B": [1, 1, 1], "C": [1, 1, 1]}, index=idx)
    rows = h.compute_style_index(px, mc, {"A": "ai", "B": "ai", "C": "ai"}, start="2026-01-02", end="2026-01-04")
    assert [r["d"] for r in rows if r["weighting"] == "equal"] == ["2026-01-02"]


def test_levels_continue_from_the_stored_level():
    px = _frame(3, {"A": [1, 1.1, 1.1], "B": [1, 1.1, 1.1], "C": [1, 1.1, 1.1]})
    mc = _frame(3, {"A": [1] * 3, "B": [1] * 3, "C": [1] * 3})
    rows = h.compute_style_index(px, mc, {"A": "ai", "B": "ai", "C": "ai"}, start="2026-01-02", end="2026-01-02",
                                 prev_level={("ai", "equal"): 2.0})
    r = next(r for r in rows if r["weighting"] == "equal")
    assert abs(r["level"] - 2.2) < 1e-12


def test_every_category_id_maps_to_a_style_slug():
    for style, _ in t.CATEGORY_PRIORITY:
        assert style in t.STYLES or style in ("l1", "l2")
