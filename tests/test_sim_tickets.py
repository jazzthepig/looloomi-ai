"""S-647 代入模拟引擎:决策走实盘的 ticket_actions;止损、跳空、资金费、保证金拒单、整户强平、放贷、回撤刹车各守一条。"""
import pytest

from src.exec_host import sim_tickets as st


def _t(tid="A", sym="UNI", entry=10, exit_off=3, stop=0.1, path=None, major=False):
    path = path or ((10.0, 10.5, 9.8, 10.2, 0.0),) * 5
    return st.SimTicket(tid=tid, symbol=sym, entry_day=entry, exit_off=exit_off, paper_exit_off=exit_off,
                        stop_frac=stop, path=tuple(path), signal_day=entry - 1, major=major)


NOFRIC = st.Venue(slip_bps=0, slip_bps_major=0, stop_slip_bps=0, stop_slip_bps_major=0, fee_bps=0)


def test_entry_size_and_exit_follow_the_live_decision_function():
    path = [(10.0, 10.0, 10.0, 10.0, 0.0), (11.0, 11.0, 11.0, 11.0, 0.0), (12.0, 12.0, 12.0, 12.0, 0.0),
            (13.0, 13.0, 13.0, 13.0, 0.0)]
    r = st.simulate([_t(path=path, exit_off=3)], 10_000.0, 1.0, venue=NOFRIC, start_day=10, end_day=13)
    # 风险 0.5% × 1 万 = $50 ÷ 止损 10% = $500 名义 = 50 张;第 3 天开盘(13)出 ⇒ +$150
    assert r.entered == 1 and r.equity[-1] == pytest.approx(10_150.0)
    assert r.equity[1] == pytest.approx(10_050.0), "持有期按收盘盯市"


def test_stop_fills_at_the_stop_or_at_a_gap_open():
    gap = [(10.0, 10.0, 10.0, 10.0, 0.0), (8.0, 8.5, 7.5, 8.0, 0.0)]          # 第二天跳空到 8 < 止损 9
    r = st.simulate([_t(path=gap, exit_off=None)], 10_000.0, 1.0, venue=NOFRIC, start_day=10, end_day=11)
    assert r.stops == 1 and r.equity[-1] == pytest.approx(10_000.0 - 50 * 2.0), "跳空按开盘 8 成交,亏 2 元 / 张"
    touch = [(10.0, 10.0, 10.0, 10.0, 0.0), (9.5, 9.6, 8.5, 9.2, 0.0)]
    r = st.simulate([_t(path=touch, exit_off=None)], 10_000.0, 1.0, venue=NOFRIC, start_day=10, end_day=11)
    assert r.equity[-1] == pytest.approx(10_000.0 - 50 * 1.0), "盘中碰到按止损线 9 成交"


def test_longs_pay_positive_funding_and_idle_cash_earns_lending():
    path = [(10.0, 10.0, 10.0, 10.0, 0.001)] * 3
    r = st.simulate([_t(path=path, exit_off=None)], 10_000.0, 1.0, venue=NOFRIC, start_day=10, end_day=12,
                    apy_for_day=lambda d: 0.0)
    assert r.funding == pytest.approx(3 * 500 * 0.001)
    r2 = st.simulate([_t(path=path, exit_off=None)], 10_000.0, 1.0, venue=NOFRIC, start_day=10, end_day=10,
                     apy_for_day=lambda d: 0.0365)
    assert r2.lending == pytest.approx((10_000 - 0.5 - 500 / 5) * 0.0001, rel=1e-6), "保证金(名义 ÷ 5)不计息"


def test_exchange_refuses_an_order_without_enough_free_margin():
    flat = ((10.0, 10.0, 10.0, 10.0, 0.0),) * 2
    tight = [_t(tid=f"T{i}", sym=f"C{i}", stop=0.01, exit_off=None, path=flat) for i in range(2)]
    # 风险 0.5% × 5 倍 × 1 万 = $250 ÷ 1% ⇒ 单票封顶分到资金一半 = $25,000;币的最大杠杆 3 ⇒ 每张保证金 $8,333
    v3 = st.Venue(slip_bps=0, slip_bps_major=0, stop_slip_bps=0, stop_slip_bps_major=0, fee_bps=0, max_lev=3.0)
    r = st.simulate(tight, 10_000.0, 5.0, venue=v3, start_day=10, end_day=10)
    assert r.entered == 1 and r.refused.get("保证金不够") == 1


def test_whole_account_is_liquidated_when_lows_breach_maintenance():
    crash = [(10.0, 10.0, 10.0, 10.0, 0.0), (10.0, 10.0, 7.6, 9.0, 0.0)]       # 盘中 −24%,止损在 −50% 不触发
    tks = [_t(tid=f"T{i}", sym=f"C{i}", stop=0.5, exit_off=None, path=crash) for i in range(2)]
    # 每张名义 $20,000(合计 4 倍权益):低点亏 $9,600,权益剩 $400 < 维持保证金 $3,040
    r = st.simulate(tks, 10_000.0, 5.0, risk_frac=0.2, venue=NOFRIC, start_day=10, end_day=11)
    assert r.entered == 2 and r.liquidations == 1 and r.equity[-1] < 10_000 * 0.05


def test_brake_cuts_new_ticket_risk_after_a_drawdown():
    assert st.brake(4.0, 100.0, 100.0) == 4.0
    assert st.brake(4.0, 85.0, 100.0) == pytest.approx(2.0)
    assert st.brake(4.0, 50.0, 100.0) == pytest.approx(1.0), "下限 0.25 × L"


def test_non_hl_tickets_are_refused_not_substituted():
    a, b = _t(tid="A", sym="ZIL"), _t(tid="B", sym="UNI")
    r = st.simulate([a, b], 10_000.0, 1.0, venue=NOFRIC, executable=lambda t: t.symbol != "ZIL", start_day=10,
                    end_day=10)
    assert r.entered == 1 and sum(r.refused.values()) == 1


def test_stats():
    s = st.stats([110.0, 90.0, 121.0], 100.0, days_per_year=3)
    assert s["cagr"] == pytest.approx(0.21) and s["mdd"] == pytest.approx(90 / 110 - 1)


def test_with_cash_lent_out_a_liquidation_only_takes_what_sits_on_hl():
    crash = [(10.0, 10.0, 10.0, 10.0, 0.0), (10.0, 10.0, 7.6, 9.0, 0.0)]
    tks = [_t(tid=f"T{i}", sym=f"C{i}", stop=0.5, exit_off=None, path=crash) for i in range(2)]
    pooled = st.simulate(tks, 10_000.0, 5.0, risk_frac=0.2, venue=NOFRIC, start_day=10, end_day=11)
    split = st.simulate(tks, 10_000.0, 5.0, risk_frac=0.2, venue=NOFRIC, start_day=10, end_day=11,
                        collateral_mult=1.0, apy_for_day=lambda d: 0.0)
    # HL 上只留 1 × 初始保证金($8,000):低点亏 $9,600 ⇒ 强平,HL 上的钱归零;放贷里的 $2,000 还在
    assert split.liquidations == 1 and split.equity[-1] == pytest.approx(2_000.0)
    assert pooled.equity[-1] < 1_000, "钱都在 HL 上时,同一次强平吃掉的是整个账户"


def test_all_cash_on_hl_earns_nothing():
    path = [(10.0, 10.0, 10.0, 10.0, 0.0)] * 3
    r = st.simulate([_t(path=path, exit_off=None)], 10_000.0, 1.0, venue=NOFRIC, start_day=10, end_day=12,
                    apy_for_day=lambda d: 0.05, collateral_mult=float("inf"))
    assert r.lending == 0.0
    r = st.simulate([_t(path=path, exit_off=None)], 10_000.0, 1.0, venue=NOFRIC, start_day=10, end_day=12,
                    apy_for_day=lambda d: 0.0365, collateral_mult=2.0)
    assert r.lending == pytest.approx(3 * (10_000 - 200) * 0.0001, rel=1e-3), "HL 上留 2 × $100 保证金,其余放贷"


def test_cut_policy_halves_open_positions_once_per_drawdown_and_resets_on_a_new_high():
    path = [(10.0, 10.0, 10.0, 10.0, 0.0), (10.0, 10.0, 10.0, 7.0, 0.0), (7.0, 7.0, 7.0, 7.0, 0.0),
            (7.0, 7.0, 7.0, 7.0, 0.0), (7.0, 7.0, 7.0, 7.0, 0.0)]
    tks = [_t(tid="A", sym="UNI", stop=0.5, exit_off=None, path=path)]
    # 风险 20% × 1 万 ÷ 50% = $4,000 名义 = 400 张;第 2 天收盘 7 ⇒ 权益 $8,800(−12%)不触发
    r = st.simulate(tks, 10_000.0, 1.0, risk_frac=0.2, policy="cut", cut_dd=0.15, venue=NOFRIC, start_day=10,
                    end_day=14)
    assert r.cuts == 0
    # 收盘 6 ⇒ 权益 $8,400(−16%)⇒ 次日开盘减半(200 张按 6 成交),之后不再减
    deep = [(10.0, 10.0, 10.0, 10.0, 0.0), (10.0, 10.0, 10.0, 6.0, 0.0), (6.0, 6.0, 6.0, 5.0, 0.0),
            (5.0, 5.0, 5.0, 4.0, 0.0), (4.0, 4.0, 4.0, 4.0, 0.0)]
    r = st.simulate([_t(tid="A", sym="UNI", stop=0.5, exit_off=None, path=deep)], 10_000.0, 1.0, risk_frac=0.2,
                    policy="cut", cut_dd=0.15, venue=NOFRIC, start_day=10, end_day=14)
    assert r.cuts == 1
    assert r.equity[-1] == pytest.approx(10_000 - 200 * 4 - 200 * 5), "一半在开盘 6 减掉,另一半之后在止损线 5 出"
