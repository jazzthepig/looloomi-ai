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


def _equity(n=60, shares0=1000.0, share_growth=0.0, div_yield=0.0):
    """周频 (周日期, 市值, 总回报复权收盘, 股数)。市值 = 股数 × 原始收盘(world50 的做法);
    复权收盘 = 原始收盘 × 之后的分红折扣 —— 越早的周被往下改得越多(ohlcv_daily 的 eodhd 收盘就是这样)。"""
    weeks = [dt.date(2025, 1, 3) + dt.timedelta(weeks=i) for i in range(n)]
    rows = []
    for i, w in enumerate(weeks):
        raw_px = 10.0 * (1 + 0.005 * i)
        sh = shares0 * (1 + share_growth) ** (i / 52)
        adj = raw_px * (1 - div_yield) ** ((n - 1 - i) / 52)
        rows.append((w.isoformat(), sh * raw_px, adj, sh))
    return rows


def test_equity_net_issuance_comes_from_filed_shares():
    asof = dt.date(2025, 1, 3) + dt.timedelta(weeks=59)
    b, s = v2.equity_inputs(_equity(share_growth=-0.03), asof), v2.equity_inputs(_equity(share_growth=0.05), asof)
    assert b["supply"] > 0 > s["supply"], "回购的股数在减 ⇒ 正;增发 ⇒ 负"
    assert b["supply"] == pytest.approx(0.03, abs=1e-9) and b["shares"] == pytest.approx(1000.0 * 0.97 ** (59 / 52))
    assert b["stability"] is not None and b["size"] == pytest.approx(math.log(_equity(share_growth=-0.03)[-1][1]))


def test_a_dividend_payer_with_flat_shares_is_not_a_buyback():
    """10-23 的错:市值 ÷ 复权收盘 = 股数 × 原始价 / 复权价,一个 7% 股息、股数不变的公司被算成一年回购约 7%
    (实测 VZ −7.6%、MO −6.9%;CMCSA 再加上一次分拆的台阶 −14.8%)。股数直接读,这个差就没有了。"""
    rows = _equity(div_yield=0.07)
    asof = dt.date(2025, 1, 3) + dt.timedelta(weeks=59)
    assert v2.equity_inputs(rows, asof)["supply"] == pytest.approx(0.0, abs=1e-12)
    old_way = -((rows[-1][1] / rows[-1][2]) / (rows[-53][1] / rows[-53][2]) - 1)
    assert old_way > 0.06, "旧推法在这里会给出 ≈ 7% 的「回购」—— 这个测试钉的就是它"


def test_partial_week_rows_collapse_to_one_row_per_week():
    """world50 每轮写本周目前为止的最后一天,同一周的旧行留着(10-14 / 10-15 / 10-16 三行)。
    不并成一行的话,「26 周周收益」里混进日收益,稳定被压低。"""
    base = _equity(n=40)
    last = dt.date.fromisoformat(base[-1][0])
    extra = [((last - dt.timedelta(days=k)).isoformat(), base[-1][1] * (1 + 0.02 * k), base[-1][2] * (1 + 0.02 * k), base[-1][3])
             for k in (1, 2)]                                     # 同一周、更早的两天,价格不同
    with_extra = sorted(base + extra, key=lambda r: r[0])
    assert v2.equity_inputs(with_extra, last) == v2.equity_inputs(base, last), "同一周只认最后一行"


def test_without_filed_shares_there_is_no_supply_dimension():
    three = [(d, m, c) for d, m, c, _ in _equity(share_growth=0.05)]
    out = v2.equity_inputs(three, dt.date(2025, 1, 3) + dt.timedelta(weeks=59))
    assert out["supply"] is None and out["shares"] is None, "没有股数就不推 —— 宁可缺,不给错的"
    assert out["size"] is not None and out["stability"] is not None


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
