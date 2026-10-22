"""CIS v2 内核(S-668):方向、窗口、按时点、等权合成、不足两维不打分、宏观 ETF 不打分。"""
import datetime as dt
import math

import pytest

from src.data.cis import v2


def _crypto(n=120, start=dt.date(2026, 6, 1), price=10.0, drift=0.0, vol=0.0, supply0=100.0, supply_growth=0.0):
    rows = []
    for i in range(n):
        d = start + dt.timedelta(days=i)
        p = price * math.exp(drift * i + (vol if i % 2 else -vol))
        s = supply0 * (1 + supply_growth * i / n)
        rows.append((d.isoformat(), p, p * s))
    return rows


def test_constants_are_the_preregistered_ones():
    assert v2.CODE_REF == "cis-v2.0" and v2.MIN_DIMS == 2
    assert (v2.CRYPTO_WINDOW_DAYS, v2.EQUITY_VOL_WEEKS, v2.EQUITY_SUPPLY_WEEKS) == (90, 26, 52)
    assert v2.DIMS["crypto"] == ("size", "stability", "supply", "f", "o")
    assert v2.DIMS["equity"] == ("size", "stability", "supply"), "个股这一版没有基本面 —— 明说,不补代理"


def test_crypto_dimensions_point_the_right_way_and_ignore_the_future():
    asof = "2026-09-20"
    calm, wild = _crypto(vol=0.01), _crypto(vol=0.08)
    assert v2.crypto_inputs(calm, asof)["stability"] > v2.crypto_inputs(wild, asof)["stability"]
    diluting, tight = _crypto(supply_growth=0.5), _crypto(supply_growth=0.0)
    assert v2.crypto_inputs(diluting, asof)["supply"] < v2.crypto_inputs(tight, asof)["supply"] == pytest.approx(0.0)
    fut = _crypto() + [("2026-12-01", 1e9, 1e18)]
    assert v2.crypto_inputs(fut, asof) == v2.crypto_inputs(_crypto(), asof), "asof 之后的行不能影响分数"
    assert v2.crypto_inputs(_crypto(n=20), asof)["stability"] is None, "窗口内不足 80% 的日子 ⇒ 不算"
    assert v2.crypto_inputs(_crypto(n=60, start=dt.date(2026, 1, 1)), asof)["size"] is None, "最近没有价 ⇒ 不打分"


def test_equity_net_issuance_is_shares_not_market_cap():
    weeks = [dt.date(2025, 1, 3) + dt.timedelta(weeks=i) for i in range(60)]
    buyback = [(w.isoformat(), 1000.0 * (1 + 0.01 * i) * (1 - 0.001 * i), 1 + 0.01 * i) for i, w in enumerate(weeks)]
    issuer = [(w.isoformat(), 1000.0 * (1 + 0.01 * i) * (1 + 0.002 * i), 1 + 0.01 * i) for i, w in enumerate(weeks)]
    asof = weeks[-1]
    b, s = v2.equity_inputs(buyback, asof), v2.equity_inputs(issuer, asof)
    assert b["supply"] > 0 > s["supply"], "回购的股数在减 ⇒ 正;增发 ⇒ 负"
    assert b["stability"] is not None and b["size"] == pytest.approx(math.log(buyback[-1][1]))


def test_percentile_ranks_and_ties():
    assert v2.pct_rank({"a": 1.0, "b": 2.0, "c": 3.0}) == {"a": 0.0, "b": 0.5, "c": 1.0}
    assert v2.pct_rank({"a": 1.0, "b": 1.0, "c": None}) == {"a": 0.5, "b": 0.5}
    assert v2.pct_rank({"a": 7.0}) == {"a": 0.5}


def test_composite_is_equal_weight_and_refuses_with_fewer_than_two_dims():
    raw = {"BTC": {"size": 30, "stability": -0.02, "supply": 0.0, "f": 80, "o": 70},
           "ALT": {"size": 20, "stability": -0.08, "supply": -0.3, "f": 40, "o": 30},
           "NEW": {"size": 18, "stability": None, "supply": None, "f": None, "o": None}}
    s = v2.score_group("crypto", raw)
    assert s["BTC"]["score"] == 100.0 and s["BTC"]["n_dims"] == 5
    assert s["ALT"]["score"] == 10.0, "NEW 也参加规模排名:ALT 规模 0.5,其余四维 0 ⇒ (0.5 + 0 × 4) ÷ 5"
    assert s["NEW"]["score"] is None and set(s["NEW"]["missing"]) == {"stability", "supply", "f", "o"}
    with pytest.raises(ValueError):
        v2.score_group("macro", raw)
