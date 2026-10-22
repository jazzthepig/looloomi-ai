"""CIS v2 对外视图:公司不给分数与档位(Jazz 10-22);影子进度按连续天数;口径引用 disclosure 的常量。"""
import math

from src.data.cis import v2_view as vw


def _rows():
    return [
        {"symbol": "BTC", "d": "2026-10-22", "grp": "crypto", "score": 86.7, "signal": "STRONG OUTPERFORM", "watch": None,
         "pct": 1.0, "ranks": {"size": 1.0}, "missing": [], "state": {"trend": {"label": "up"}}},
        {"symbol": "AAPL", "d": "2026-10-22", "grp": "equity", "score": 79.0, "signal": None,
         "raw": {"size": math.log(4.0e12), "stability": -0.03, "supply": 0.012, "shares": 1.5e10},
         "state": {"trend": {"label": "up"}}},
    ]


def test_share_change_is_only_shown_when_it_came_from_filed_shares():
    """10-21 及之前的行:supply 是 市值 ÷ 复权收盘 推出来的(股息、分拆算成了回购),行里没有 shares —— 不再对外当事实。"""
    old = vw.company_facts({"size": math.log(1e11), "stability": -0.03, "supply": 0.148})
    assert old["share_count_change_52w"] is None and old["market_cap_usd"] == 100_000_000_000
    new = vw.company_facts({"size": math.log(1e11), "stability": -0.03, "supply": 0.02, "shares": 3.6e9})
    assert new["share_count_change_52w"] == -0.02


def test_companies_get_facts_and_state_but_no_score_or_signal():
    v = vw.build_view(_rows(), 3, 25)
    (c,) = v["companies"]
    assert set(c) == {"symbol", "facts", "state"}, "公司不给分数、不给档位"
    assert c["facts"]["market_cap_usd"] == 4_000_000_000_000 and c["facts"]["share_count_change_52w"] == -0.012
    assert v["crypto"][0]["signal"] == "STRONG OUTPERFORM" and v["status"] == "shadow" and v["official_cis"] == "v1"
    assert "not a forecast" in v["basis"] and "不是预测" in v["basis_zh"]
    assert v["shadow"] == {"crypto_consecutive_days": 3, "switch_after_days": 20, "crypto_universe": 25}


def test_shadow_streak_needs_consecutive_full_days():
    days = [("2026-10-22", 25), ("2026-10-21", 24), ("2026-10-20", 25), ("2026-10-18", 25)]
    assert vw.shadow_streak(days, 25) == 3, "10-19 缺一天 ⇒ 断在 10-20"
    assert vw.shadow_streak([("2026-10-22", 23), ("2026-10-21", 25)], 25) == 0, "最近一天 < 95% ⇒ 0"
    assert vw.shadow_streak([], 25) == 0
