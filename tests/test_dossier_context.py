"""③ 档案的背景栏(S-844 / S-848):按时点、没测到不当 0、维度打架要列出来。"""
from src.data.execution import dossier_context as dc


def _state(d, st, tk=None, lend=None):
    rows = [{"d": d, "feature": "stable_supply_30d", "value": st}]
    if tk is not None:
        rows.append({"d": d, "feature": "taker_buy_share_30d", "value": tk})
    if lend is not None:
        rows.append({"d": d, "feature": "stable_lend_apy_7d", "value": lend})
    return rows


def test_halving_month_and_phase():
    assert dc.halving_month("2026-11-12") == 30.7
    assert dc.halving_phase(dc.halving_month("2026-11-12")) == "30-48m"
    assert dc.halving_phase(dc.halving_month("2025-10-06")) == "12-18m"
    assert dc.halving_phase(dc.halving_month("2026-04-01")) == "18-30m"
    assert dc.halving_month("2024-04-20") == 0.0
    assert dc.halving_month("2010-01-01") is None


def test_asof_never_looks_ahead():
    rows = [{"d": "2026-11-10", "value": 1.0}, {"d": "2026-11-13", "value": 9.0}]
    assert dc.asof(rows, "2026-11-12")["value"] == 1.0
    assert dc.asof(rows, "2026-11-09") is None
    assert dc.asof([{"d": "2026-11-10", "value": None}], "2026-11-12") is None


def test_build_reproduces_the_day_that_prompted_it():
    """11-12 的实测读数:稳定币在抽、MVRV 1.37、利差 2.65 → 3.30、减半后第 30.7 个月。"""
    state = _state("2026-11-12", -0.0379, tk=0.5067, lend=4.23) + _state("2026-10-15", -0.0040)
    macro = [{"d": "2026-11-11", "series": "btc_mvrv", "value": 1.37}, {"d": "2026-11-11", "series": "btc_puell", "value": 0.906},
             {"d": "2026-11-11", "series": "btc_hash_30d", "value": -0.057}, {"d": "2026-11-12", "series": "hy_oas", "value": 3.30},
             {"d": "2026-09-11", "series": "hy_oas", "value": 2.65}, {"d": "2026-11-12", "series": "vix", "value": 18.7},
             {"d": "2026-11-12", "series": "vix3m", "value": 20.1}]
    c = dc.build("2026-11-12", state, macro)
    assert c["halving_month"] == 30.7 and c["halving_phase"] == "30-48m"
    assert c["stable_supply_30d"] == -0.0379 and c["stable_supply_30d_d"] == "2026-11-12" and c["stable_supply_30d_4w_ago"] == -0.004
    assert c["btc_mvrv"] == 1.37 and c["btc_mvrv_d"] == "2026-11-11" and c["hy_oas_60d_ago"] == 2.65
    assert c["reads"] == {"stable_supply": "draining", "taker": "buyers_aggressive", "valuation": "above_cost_basis",
                          "credit": "widening", "vix_term": "contango", "halving": "30-48m"}
    joined = " | ".join(c["conflicts"])
    assert "MVRV > 1" in joined and "稳定币供应在收缩" in joined and "信用利差在走阔" in joined
    assert set(c["missing"]) == {"ust_2y", "ust_10y", "ust_10y_real", "fed_funds", "usd_broad", "btc_etf_flow"}      # 这几条当天还没进库:列名字,不给 0


def test_unmeasured_is_absent_not_zero_and_stale_is_refused():
    macro = [{"d": "2026-10-20", "series": "btc_mvrv", "value": 1.5}]          # 23 天前 ⇒ 太旧
    c = dc.build("2026-11-12", _state("2026-11-12", 0.01), macro)
    assert "btc_mvrv" not in c and "taker_buy_share_30d" not in c and "hy_oas" not in c
    assert any(m.startswith("btc_mvrv(stale 2026-10-20") for m in c["missing"]) and "taker_buy_share_30d" in c["missing"]
    assert "valuation" not in c["reads"] and "taker" not in c["reads"] and c["reads"]["stable_supply"] == "adding"
    assert all(v is not None for k, v in c.items() if k != "missing")


def test_future_rows_cannot_enter_and_no_conflict_is_an_empty_list():
    state = _state("2026-11-13", -0.9) + _state("2026-11-12", 0.02, tk=0.52)
    c = dc.build("2026-11-12", state, [{"d": "2026-11-13", "series": "btc_mvrv", "value": 0.5}])
    assert c["stable_supply_30d"] == 0.02 and "btc_mvrv" not in c
    assert c["conflicts"] == []


def test_agent_dossier_carries_context_under_a_new_author_version():
    from src.data.execution import agent_judgment as aj
    doc = aj.dossier({"d": "2026-11-12", "inputs": {"btc_close": 74000.0, "context": {"halving_month": 30.8}}, "probs": {}}, [])
    assert doc["state"]["context"] == {"halving_month": 30.8}
    assert aj.AUTHOR_VERSION == "v3"


def test_weekly_structure_matches_the_week_it_first_fired_and_reads_only_the_past():
    """10-25 那周第一次亮(80,154 < 10 周均线,且 < 4 周前的 84,472);10-18 那周还没亮;11-01 的收盘进不了 10-25 的读数。"""
    w = [("2026-08-16", 62900), ("2026-08-23", 77734), ("2026-08-30", 77682), ("2026-09-06", 80342), ("2026-09-13", 76842), ("2026-09-20", 81178),
         ("2026-09-27", 84472), ("2026-10-04", 86530), ("2026-10-11", 83773), ("2026-10-18", 82116), ("2026-10-25", 80154), ("2026-11-01", 78354)]
    a = dc.weekly_structure("2026-10-25", w)
    assert a["weekly_d"] == "2026-10-25" and a["weekly_down"] is True and a["weekly_lower_closes"] == 3 and a["weekly_close"] == 80154.0
    assert dc.weekly_structure("2026-10-24", w)["weekly_down"] is False and dc.weekly_structure("2026-10-24", w)["weekly_d"] == "2026-10-18"
    assert dc.weekly_structure("2026-10-25", w[:5]) == {}


def test_price_fine_money_leaving_is_listed_and_options_and_inflows_are_carried_raw():
    w = [(f"2026-0{m}-{dd:02d}", 60000 + i * 1500) for i, (m, dd) in enumerate([(7, 19), (7, 26), (8, 2), (8, 9), (8, 16), (8, 23), (8, 30), (9, 6), (9, 13), (9, 20), (9, 27)])]
    w.append(("2026-10-04", 86530))
    c = dc.build("2026-10-04", _state("2026-10-04", -0.001, tk=0.4899), [], w,
                 [{"d": "2026-10-04", "skew_30d": -3.21, "term_slope": 1.5, "pc_vol_ratio": None}, {"d": "2026-10-05", "skew_30d": 99.0}],
                 [{"d": "2026-10-03", "exchange": "a", "inflow_1w_usd": 2e8}, {"d": "2026-10-03", "exchange": "b", "inflow_1w_usd": -5e7},
                  {"d": "2026-10-02", "exchange": "a", "inflow_1w_usd": 9e9}])
    assert c["reads"]["weekly"] == "ok" and c["reads"]["stable_supply"] == "draining"
    joined = " | ".join(c["conflicts"])
    assert "价格好看、钱在走" in joined and "没有主动买盘的上涨" in joined
    assert c["options_skew_30d"] == -3.21 and c["options_d"] == "2026-10-04" and "options_pc_vol_ratio" not in c
    assert c["cex_inflow_1w_usd"] == 150000000.0 and c["cex_inflow_d"] == "2026-10-03" and c["cex_inflow_n_exchanges"] == 2
    assert "cex_inflow" not in " ".join(c["reads"])


def test_optional_blocks_missing_are_named_not_zeroed():
    c = dc.build("2026-11-12", _state("2026-11-12", 0.01), [], [], [], [])
    assert {"weekly_structure", "options_btc", "cex_inflow_1w_usd"} <= set(c["missing"])
    assert "weekly_down" not in c and "cex_inflow_1w_usd" not in c


def test_rates_and_dollar_read_direction_and_policy_path():
    macro = [{"d": "2026-11-12", "series": "ust_2y", "value": 4.35}, {"d": "2026-09-11", "series": "ust_2y", "value": 3.90},
             {"d": "2026-11-12", "series": "fed_funds", "value": 4.08}, {"d": "2026-11-04", "series": "usd_broad", "value": 121.0},
             {"d": "2026-09-05", "series": "usd_broad", "value": 119.5}]
    c = dc.build("2026-11-12", _state("2026-11-12", 0.01), macro)
    assert c["ust_2y_60d_ago"] == 3.9 and c["usd_broad"] == 121.0 and c["usd_broad_d"] == "2026-11-04"      # 8 天前的美元读数不算太旧
    assert c["reads"]["rates_2y"] == "rising" and c["reads"]["policy_path"] == "market_prices_hikes" and c["reads"]["usd"] == "stronger"
    assert any("2 年期利率在升" in x for x in c["conflicts"])
    c2 = dc.build("2026-11-12", _state("2026-11-12", -0.02), [{"d": "2026-10-20", "series": "ust_2y", "value": 4.0}])
    assert "ust_2y" not in c2 and "rates_2y" not in c2["reads"]                                              # 23 天前的收益率拒收


def test_etf_flow_sums_use_only_sessions_known_by_the_date():
    flows = [("2026-11-06", -4.30e8), ("2026-11-07", -4.12e8), ("2026-11-10", -2.01e8), ("2026-11-11", -0.95e8), ("2026-11-12", -3.00e8),
             ("2026-11-13", 9.0e9)]                                                                           # 明天才可得的那条不许进
    macro = [{"d": d, "series": "btc_etf_net_flow_usd", "value": v} for d, v in flows]
    c = dc.build("2026-11-12", _state("2026-11-12", -0.01), macro)
    assert c["btc_etf_flow_5d_bn"] == -1.438 and c["btc_etf_flow_d"] == "2026-11-12" and "btc_etf_flow_20d_bn" not in c
    assert c["reads"]["btc_etf_flow"] == "outflow"
    c2 = dc.build("2026-11-12", _state("2026-11-12", -0.01), [])
    assert "btc_etf_flow_5d_bn" not in c2 and "btc_etf_flow" in c2["missing"] and "btc_etf_flow" not in c2["reads"]
