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
