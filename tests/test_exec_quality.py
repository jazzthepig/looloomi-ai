"""执行质量日表(10-30):fill_log.execution_quality 的第一个消费者。
钉住:滑点符号、空跑 sleeve 滑点为空不为 0、没有结果的意图单列、每天一行 + 累计行、对外只出聚合、锚进 forward_anchor_daily。"""
import pytest

from src.data.execution import exec_quality as eq


def _i(iid, sleeve, side, mid, bid, ask, ts="2026-10-30T15:44:26+00:00", notional=175.0):
    return {"intent_id": iid, "ts_decision": ts, "symbol": "SPYX", "side": side, "target_notional_usd": notional,
            "decision_mid": mid, "decision_bid": bid, "decision_ask": ask, "sleeve": sleeve, "signal_ref": "t25:x",
            "order_type": "taker", "limit_price": mid * 1.005, "recorded_at": ts}


def _o(iid, px, status="filled", notional=175.31, fee=0.1227, mid_after=None):
    return {"intent_id": iid, "ts_resolved": "2026-10-30T15:44:30+00:00", "status": status, "filled_notional_usd": notional,
            "avg_fill_price": px, "fee_usd": fee, "liquidity": "taker", "seconds_to_resolve": 0.4,
            "mid_at_resolve": mid_after, "note": "oid=1", "recorded_at": "x"}


def test_the_first_real_fills_price_against_the_decision_mid():
    # 10-30 15:44 UTC 的两笔真单(SPYX 762.41 → 762.23、XAUT0 3908.1 → 3907.5):买在中间价之下 = 负滑点(市场给的)
    intents = [_i("a", "t25_legs_live", "buy", 762.41, 762.18, 762.64), _i("b", "t25_legs_live", "buy", 3908.1, 3906.2, 3910.0,
                                                                            notional=117.18)]
    outs = [_o("a", 762.23), _o("b", 3907.5, notional=117.225, fee=0.082)]
    rows = eq.rows_for(intents, outs, "2026-10-31")
    assert [(r["span"], r["d"]) for r in rows] == [("day", "2026-10-30"), ("since_inception", "2026-10-31")]
    r = rows[1]
    assert r["n_intents"] == 2 and r["n_filled"] == 2 and r["fill_rate"] == 1.0 and r["n_unresolved"] == 0
    assert r["mean_slippage_bps"] == pytest.approx(((762.23 / 762.41 - 1) + (3907.5 / 3908.1 - 1)) / 2 * 1e4, abs=1e-3)
    assert r["mean_slippage_bps"] < 0 and r["mean_fee_bps"] > 0
    assert r["implementation_shortfall_bps"] == pytest.approx(r["mean_slippage_bps"] + r["mean_fee_bps"], abs=1e-3)
    assert r["median_quoted_spread_bps"] == pytest.approx(max((0.46 / 762.41), (3.8 / 3908.1)) * 1e4, abs=0.01), "偶数个取上中位"
    assert r["first_d"] == "2026-10-30" and r["note"] and "only 2 intents" in r["note"]


def test_sell_slippage_flips_sign_and_unfilled_orders_cost_opportunity():
    intents = [_i("s", "x1v_spot", "sell", 100.0, 99.9, 100.1), _i("e", "x1v_spot", "buy", 100.0, 99.9, 100.1)]
    outs = [_o("s", 99.9, notional=100.0, fee=0.05), _o("e", None, status="expired", notional=0.0, fee=0.0, mid_after=101.0)]
    r = eq.rows_for(intents, outs, "2026-10-31")[-1]
    assert r["mean_slippage_bps"] == pytest.approx(10.0, abs=1e-6), "卖在中间价之下 = 我们付的 10 bps"
    assert r["mean_opportunity_bps"] == pytest.approx(100.0, abs=1e-6), "没成交、价格跑了 1% = 机会成本 100 bps"
    assert r["fill_rate"] == 0.5


def test_dry_run_sleeves_record_intents_only_and_live_gaps_are_counted_not_hidden():
    intents = [_i("d1", "t25_legs_host_dry", "buy", 762.41, 762.18, 762.64), _i("l1", "t25_legs_live", "buy", 762.41, 762.18, 762.64)]
    rows = {(r["sleeve"], r["span"]): r for r in eq.rows_for(intents, [], "2026-10-31")}
    dry = rows[("t25_legs_host_dry", "since_inception")]
    assert dry["n_intents"] == 1 and dry["fill_rate"] is None and dry["mean_slippage_bps"] is None and dry["n_unresolved"] == 0
    assert "空跑" in dry["note"] and dry["median_quoted_spread_bps"] > 0, "空跑也记报价时的价差"
    live = rows[("t25_legs_live", "since_inception")]
    assert live["n_unresolved"] == 1 and live["n_resolved"] == 0 and "没有结果行" in live["note"]


def test_recent_window_keeps_day_rows_only_for_recent_days_but_the_cumulative_row_sees_everything():
    intents = [_i("old", "x1v_spot", "buy", 100.0, 99.9, 100.1, ts="2026-10-01T00:30:00+00:00"),
               _i("new", "x1v_spot", "buy", 100.0, 99.9, 100.1, ts="2026-10-30T00:30:00+00:00")]
    rows = eq.rows_for(intents, [_o("old", 100.1, notional=100.0), _o("new", 100.0, notional=100.0)], "2026-10-31")
    assert [r["d"] for r in rows if r["span"] == "day"] == ["2026-10-30"]
    assert [r["n_intents"] for r in rows if r["span"] == "since_inception"] == [2]


def test_public_rows_are_aggregates_without_direction_words_or_symbols():
    rows = [{"d": "2026-10-30", "sleeve": "t25_legs_live", "span": "since_inception", "n_intents": 2, "n_resolved": 2,
             "n_unresolved": 0, "n_filled": 2, "fill_rate": 1.0, "notional_usd": 292.5, "mean_slippage_bps": -1.9,
             "mean_fee_bps": 7.0, "mean_opportunity_bps": None, "implementation_shortfall_bps": 5.1,
             "median_quoted_spread_bps": 6.0, "note": None, "code_ref": "x", "computed_at": "x", "first_d": "2026-10-30"},
            {"d": "2026-10-29", "sleeve": "t25_legs_live", "span": "since_inception", "n_intents": 1, "n_resolved": 1,
             "n_unresolved": 0, "n_filled": 1, "fill_rate": 1.0, "notional_usd": 100.0, "code_ref": "x", "computed_at": "x"},
            {"d": "2026-10-30", "sleeve": "t25_legs_host_dry", "span": "since_inception", "n_intents": 2, "code_ref": "x"}]
    pub = eq.public_rows(rows)
    assert [(r["sleeve"], r["d"], r["live"]) for r in pub] == [("t25_legs_host_dry", "2026-10-30", False),
                                                                ("t25_legs_live", "2026-10-30", True)]
    text = str(pub) + eq.HOW_TO_READ_EXEC
    for w in ("buy", "sell", "symbol", "code_ref", "computed_at", "BUY", "SELL"):
        assert w not in text, w


def test_the_table_is_anchored_and_the_loop_is_registered():
    from src.data.accounting import anchor
    from src.api import liveness
    assert anchor.KEYS["execution_quality_daily"] == ("sleeve", "span")
    assert "_exec_quality_loop" in liveness.LIVENESS_SLOS
    import pathlib
    main = pathlib.Path(__file__).resolve().parents[1] / "src" / "api" / "main.py"
    assert "_exec_quality_loop" in main.read_text(encoding="utf-8")
