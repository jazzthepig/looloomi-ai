"""S-690 前向标签的内核:与研究 SQL 在同一天的截面上逐名一致(2024-11-11,189 名,当天 23 张票)。"""
from pathlib import Path

from src.data.signals.oi_leverage import H_CUT, avg_ranks, size_neutral_pct, tag_row

FIX = Path(__file__).resolve().parent / "fixtures" / "s690_cs_20241111.txt"
REF = Path(__file__).resolve().parents[1] / "docs" / "research" / "s690_p.txt"


def _rows():
    out = []
    for tok in FIX.read_text().strip().split(";"):
        s, oi, m = tok.split("|")
        out.append({"sym": s, "oi": float(oi), "mcap": float(m)})
    return out


def test_parity_with_research_sql_on_2024_11_11():
    pm = size_neutral_pct(_rows())
    assert len(pm) == 189
    ref = {}
    for tok in REF.read_text().strip().split(";"):
        s, d, p, n, _ = tok.split("|")
        if d == "2024-11-11" and p:
            ref[s] = float(p)
    assert len(ref) == 23
    assert max(abs(pm[s] - v) for s, v in ref.items()) < 1e-5


def test_ranks_and_small_universe():
    assert avg_ranks([3.0, 1.0, 3.0]) == [2.5, 1.0, 2.5]
    assert size_neutral_pct([{"sym": "A", "oi": 1, "mcap": 3e7}]) == {}
    assert size_neutral_pct([{"sym": "A", "oi": 1, "mcap": 1e6}, {"sym": "B", "oi": 1, "mcap": 1e6},
                             {"sym": "C", "oi": 1, "mcap": 1e6}]) == {}, "below $20M cap is out"


def test_tag_row_high_and_missing():
    t = {"ticket_id": "x", "symbol": "ARB", "signal_d": "2024-11-16"}
    assert tag_row(t, {"ARB": 0.91}, 191)["high"] is True and H_CUT == 2 / 3
    assert tag_row(t, {"ARB": 0.40}, 191)["high"] is False
    miss = tag_row(t, {}, 0, "当天的 Binance OI 归档还没落库(隔天才有)")
    assert miss["p"] is None and miss["high"] is None and "归档" in miss["why_missing"]


def test_generic_kernel_matches_the_oi_mcap_kernel():
    from src.data.signals.oi_leverage import size_neutral_pct_of
    rows = _rows()
    a = size_neutral_pct(rows)
    b = size_neutral_pct_of([{"sym": r["sym"], "v": r["oi"] / r["mcap"], "mcap": r["mcap"]} for r in rows if r["mcap"] >= 2e7])
    assert a.keys() == b.keys() and max(abs(a[k] - b[k]) for k in a) < 1e-12
    assert size_neutral_pct_of([{"sym": "A", "v": None, "mcap": 3e7}] * 5) == {}, "没有因子值的名字不进"


def test_factor_values_f3_and_f7_use_only_what_is_known_at_d():
    import datetime as dt
    from src.data.signals.oi_leverage import factor_values
    d = dt.date(2026, 10, 27)
    rs = [{"d": (d - dt.timedelta(days=k)).isoformat(), "oi_close": 100.0 if k == 30 else 150.0,
           "taker_ratio_mean": 1.0 + k / 100} for k in range(0, 40)]
    rs.append({"d": (d + dt.timedelta(days=1)).isoformat(), "oi_close": 1e9, "taker_ratio_mean": 9.0})   # d 之后的行不许用
    v = factor_values(sorted(rs, key=lambda r: r["d"]), d)
    import math
    assert abs(v["q3"] - math.log(1.5)) < 1e-12
    assert abs(v["f7"] - (1.0 + sum(range(7)) / 700)) < 1e-12
    short = [r for r in rs if r["d"] >= (d - dt.timedelta(days=3)).isoformat() and r["d"] <= d.isoformat()]
    assert factor_values(short, d) == {"q3": None, "f7": None}, "不到 5 天主动买卖比、没有 d−30 的张数 ⇒ 空"


def test_extra_tags_record_but_never_block():
    from src.data.signals.oi_leverage import extra_tags
    t = {"ticket_id": "x", "symbol": "ARB", "signal_d": "2026-10-27"}
    r = extra_tags(t, {"p3": {"ARB": 0.9}, "p7": {"ARB": 0.1}})
    assert r == {"p_doi30": 0.9, "high_doi30": True, "p_taker7": 0.1}
    assert extra_tags(t, {"p3": {}, "p7": {}}) == {"p_doi30": None, "high_doi30": None, "p_taker7": None}
