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
    assert set(c["missing"]) == {"ust_2y", "ust_10y", "ust_10y_real", "fed_funds", "usd_broad", "btc_etf_flow", "btc_coinbase_premium",
                                 "dist_200", "funding_7d_ann_binance", "oi_chg_30d", "mom_20", "fng"}      # 没给的:列名字,不给 0


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
    assert aj.AUTHOR_VERSION == "v4" and aj.dossier_version({"context": {"halving_month": 30.8}}) == "v3"


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


def test_coinbase_premium_is_a_7_day_mean_of_closed_days_and_stale_is_refused():
    prem = [(f"2026-11-{x:02d}", v) for x, v in zip(range(5, 13), (-0.0004, -0.0006, -0.0002, 0.0001, -0.0008, -0.0005, -0.0003, -0.0010))]
    macro = [{"d": d, "series": "btc_coinbase_premium", "value": v} for d, v in prem] + [{"d": "2026-11-13", "series": "btc_coinbase_premium", "value": 0.5}]
    c = dc.build("2026-11-12", _state("2026-11-12", -0.01), macro)
    assert c["btc_coinbase_premium_7d_bp"] == round(sum(v for _, v in prem[-7:]) / 7 * 1e4, 1) and c["btc_coinbase_premium_d"] == "2026-11-12"
    assert c["reads"]["us_spot"] == "discount"
    c2 = dc.build("2026-11-20", _state("2026-11-20", -0.01), macro[:-1])                       # 最新一条已是 8 天前
    assert "btc_coinbase_premium_7d_bp" not in c2 and "btc_coinbase_premium" in c2["missing"]


# ── S-855:叙事的量与调 · 大户净仓 · 三张清单 ─────────────────────────────────────────────────────────────

def _days(end, n):
    import datetime as dt
    e = dt.date.fromisoformat(end)
    return [(e - dt.timedelta(days=k)).isoformat() for k in range(n - 1, -1, -1)]


def test_narrative_is_read_against_its_own_history_and_never_ahead():
    ds = _days("2026-11-12", 200)
    vol = [{"d": d, "topic": "ai_chips", "value": 2.5 if i >= 193 else 1.25 if i >= 186 else 1.0} for i, d in enumerate(ds)]
    tone = [{"d": d, "topic": "ai_chips:tone", "value": -3.0 if i >= 193 else -1.0} for i, d in enumerate(ds)]
    ahead = [{"d": "2026-11-13", "topic": "ai_chips", "value": 99.0}, {"d": "2026-11-13", "topic": "ai_chips:tone", "value": 99.0}]
    n = dc.narratives("2026-11-12", vol + tone + ahead)
    it = n["items"]["ai_chips"]
    assert it["vol_x180"] == round(2.5 / ((173 * 1.0 + 7 * 1.25) / 180), 2) and it["vol_chg_7d"] == 1.0, "比的是它自己之前 180 天;上一个 7 天是 1.25"
    assert it["tone_7d"] == -3.0 and it["tone_vs_180"] == -2.0 and n["loudest"] == ["ai_chips"] and "missing" not in n
    quiet = [{"d": d, "topic": "fed_hike", "value": 4.0} for d in ds]                                     # 绝对量更大,但对自己没有变 ⇒ 排在后面
    n2 = dc.narratives("2026-11-12", vol + tone + quiet)
    assert n2["loudest"] == ["ai_chips", "fed_hike"] and n2["items"]["fed_hike"] == {"vol_x180": 1.0, "vol_chg_7d": 0.0}
    assert n2["missing"] == ["fed_hike:tone"], "调那条没有行 ⇒ 点名,不补 0"


def test_narrative_too_old_or_too_short_is_refused():
    ds = _days("2026-11-06", 200)                                                                          # 最新一条在 6 天前
    assert dc.narratives("2026-11-12", [{"d": d, "topic": "ai_chips", "value": 1.0} for d in ds]) == {"missing": ["ai_chips", "ai_chips:tone"]}
    short = [{"d": d, "topic": "boj_yen", "value": 1.0} for d in _days("2026-11-12", 40)]                  # 之前那段不足 60 个读数
    assert "items" not in dc.narratives("2026-11-12", short)
    c = dc.build("2026-11-12", _state("2026-11-12", 0.01), [], narrative_rows=[])
    assert "narratives" in c["missing"] and "narratives" not in c and "narrative_loudest" not in c
    assert "narratives" not in dc.build("2026-11-12", _state("2026-11-12", 0.01), []).get("missing", []), "没传 = 这次没读,不算缺"


def test_whale_net_uses_full_utc_days_and_needs_the_day_seven_days_back():
    def day(d, lg, sh, n=24):
        return [{"ts": f"{d}T{h:02d}:00:00+00:00", "long_usd": lg, "short_usd": sh} for h in range(n)]
    rows = day("2026-11-05", 90e6, 800e6) + day("2026-11-11", 58e6, 830e6) + day("2026-11-12", 54e6, 796e6) + day("2026-11-13", 72e6, 770e6, n=5)
    w = dc.whales("2026-11-13", rows)
    assert w == {"whale_d": "2026-11-12", "whale_long_usd": 54e6, "whale_short_usd": 796e6, "whale_net_usd": -742e6, "whale_net_usd_7d_ago": -710e6}, "只有 5 个小时的那天不算"
    assert "whale_net_usd_7d_ago" not in dc.whales("2026-11-11", rows) and dc.whales("2026-11-11", rows)["whale_d"] == "2026-11-11"
    assert dc.whales("2026-11-20", rows) == {} and dc.whales("2026-11-12", []) == {}
    c = dc.build("2026-11-12", _state("2026-11-12", 0.01), [], whale_rows=[])
    assert "whale_positioning" in c["missing"] and c["checklists"]["distribution"]["items"]["whales_net_long_falling_7d"] == "unreadable"


def test_checklists_on_the_measured_day_accumulation_is_all_no():
    """11-12 库里量到的读数(SQL 另算了一遍):吸筹八条全是 no;盯盘三条不再适用(价格已在 200 日线下方);派发里只剩「资金费仍为正」。"""
    d = "2026-11-12"
    st = ([{"d": d, "feature": f, "value": v} for f, v in (("stable_supply_30d", -0.0477), ("taker_buy_share_30d", 0.5044), ("dist_200", -0.0312),
                                                           ("oi_chg_30d", -0.2304), ("mom_20", -0.1292))]
          + [{"d": "2026-10-15", "feature": "stable_supply_30d", "value": -0.0039}, {"d": "2026-10-15", "feature": "taker_buy_share_30d", "value": 0.4910}]
          + [{"d": x, "feature": "funding_7d_ann_binance", "value": 0.0586 if x == d else 0.0064 + 0.0001 * i} for i, x in enumerate(_days(d, 60))])
    flows = [("2026-10-30", 17.1), ("2026-10-31", -643.3), ("2026-11-03", -398.6), ("2026-11-04", -115.6), ("2026-11-05", 74.6),
             ("2026-11-06", -430.2), ("2026-11-07", -411.9), ("2026-11-10", -201.1), ("2026-11-11", -95.0), ("2026-11-12", -299.9)]
    macro = ([{"d": "2026-11-11", "series": k, "value": v} for k, v in (("btc_mvrv", 1.37), ("btc_hash_30d", -0.0571), ("ust_2y", 4.73), ("fng", 29))]
             + [{"d": "2026-08-13", "series": "ust_2y", "value": 4.20}, {"d": "2026-09-11", "series": "ust_2y", "value": 4.63},
                {"d": "2026-11-12", "series": "hy_oas", "value": 3.30}, {"d": "2026-09-11", "series": "hy_oas", "value": 2.65}]
             + [{"d": x, "series": "btc_etf_net_flow_usd", "value": v * 1e6} for x, v in flows]
             + [{"d": x, "series": "btc_coinbase_premium", "value": -0.00136} for x in _days(d, 7)])
    wk = list(zip(_days("2026-11-08", 64)[::7][-10:], (80342, 76842, 81178, 84472, 86530, 83773, 82116, 80154, 78354, 74851)))
    c = dc.build(d, st, macro, wk, None, [{"d": "2026-11-11", "exchange": "a", "inflow_1w_usd": -1e8}], None, [])
    k = c["checklists"]
    assert c["funding_min_60d"] == 0.0064 and c["ust_2y_91d_ago"] == 4.2 and c["btc_etf_flow_prev5d_bn"] == -1.066 and c["taker_buy_share_30d_4w_ago"] == 0.491
    assert k["accumulation"]["yes"] == 0 and k["accumulation"]["no"] == 8 and k["accumulation"]["unreadable"] == 0, k["accumulation"]
    assert k["watch"]["applies"] == "no" and k["watch"]["items"] == {"taker_below_half": "no", "stable_supply_not_growing": "yes", "ust_2y_above_91d_ago": "yes"}
    assert k["distribution"]["items"] == {"price_10w_high_taker_falling": "no", "cex_net_inflow_1w": "no", "whales_net_long_falling_7d": "unreadable",
                                          "oi_up_price_not": "no", "sentiment_in_greed": "no", "funding_positive": "yes"}
    assert c["reads"]["sentiment"] == "fear" and c["reads"]["funding"] == "longs_pay" and c["reads"]["trend_200d"] == "below"
    joined = " | ".join(c["conflicts"])
    assert "杠杆多头还没走" in joined and "有人在接,或空头在平" in joined


def test_checklist_item_without_its_inputs_is_unreadable_not_no():
    k = dc.checklists({})
    assert all(v == "unreadable" for name in ("watch", "distribution", "accumulation") for v in k[name]["items"].values())
    assert k["watch"]["applies"] == "unreadable" and k["accumulation"]["unreadable"] == 8 and k["distribution"]["unreadable"] == 6
    k2 = dc.checklists({"btc_mvrv": 0.78, "funding_7d_ann_binance": 0.03, "funding_min_60d": -0.02, "dist_200": 0.1, "taker_buy_share_30d": 0.48})
    assert k2["accumulation"]["items"]["mvrv_at_or_below_value_zone"] == "yes" and k2["accumulation"]["items"]["funding_went_negative_then_positive"] == "yes"
    assert k2["watch"]["applies"] == "yes" and k2["watch"]["items"]["taker_below_half"] == "yes" and k2["watch"]["yes"] == 1


def test_the_narrative_list_lives_in_one_place():
    from src.data.market import political_intensity as pi
    ser = dc._narrative_series()
    assert len(ser) == 2 * len(pi.NARRATIVE_TOPICS) and set(ser) <= set(pi.all_series()) and dc.TONE_SUFFIX == pi.TONE_SUFFIX
    assert not set(ser) & set(pi.TOPICS), "政治五条不当叙事读"


# ── ⓪ 简报第一屏(S-849 第 4 条)─────────────────────────────────────────────────────────────────────────

def test_brief_lines_print_only_what_was_measured():
    d = "2026-11-12"
    st = [{"d": d, "feature": "stable_supply_30d", "value": -0.0477}, {"d": d, "feature": "dist_200", "value": -0.0312}]
    c = dc.build(d, st, [{"d": "2026-11-11", "series": "btc_mvrv", "value": 1.37}, {"d": "2026-11-11", "series": "fng", "value": 29}])
    out = dc.lines(c)
    text = "\n".join(out)
    assert out[0].startswith("状态读法(截至 2026-11-12") and "不是指令" in out[0]
    assert "稳定币 30 日 -4.77%" in text and "MVRV 1.37" in text and "恐惧贪婪 29" in text and "距 200 日线 -3.1%" in text
    body = text.split("没读到")[0]                                                                      # 「没读到」那行是名字清单(binance 里有 nan)
    assert "None" not in body and "nan" not in body and "主动买盘" not in body.split("清单")[0], "没量到的不写"
    assert "吸筹清单  0 成立 / 1 没有 / 7 读不到" in text and "这三条不再是先行条件" in text
    assert "没读到" in text and "taker_buy_share_30d" in text
    assert dc.lines({"error": "TimeoutError: x"}) == ["状态读法:读不到(TimeoutError: x)"] and dc.lines({})[0].startswith("状态读法:读不到")
    assert set(dc.LABELS) == {n for b in dc.checklists({}).values() for n in b["items"]}, "每一项都有中文名,也没有多余的"


def _cli(monkeypatch, tmp_path, key=None):
    import importlib.util
    import pathlib
    kf = tmp_path / "regime_call.key"
    if key:
        kf.write_text(key + "\n")
    monkeypatch.setenv("REGIME_CALL_KEY_FILE", str(kf))
    spec = importlib.util.spec_from_file_location("regime_call_cli2", pathlib.Path(__file__).resolve().parent.parent / "scripts" / "regime_call.py")
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    return cli


def test_cli_without_an_action_explains_instead_of_erroring(monkeypatch, tmp_path, capsys):
    """11-13 Jazz 贴回来的是 argparse 的报错(the following arguments are required: state)。不带动作 = 说明能做什么、密钥配了没有;不联网。"""
    cli = _cli(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "_call", lambda *a, **k: (_ for _ in ()).throw(AssertionError("不该联网")))
    monkeypatch.setattr("sys.argv", ["regime_call.py"])
    cli.main()
    out = capsys.readouterr().out
    assert "brief" in out and "status" in out and "还没有" in out and "keygen" in out
    cli2 = _cli(monkeypatch, tmp_path, key="ab" * 32)
    assert "指纹" in cli2.howto("ab" * 32) and "还没有" not in cli2.howto("ab" * 32) and "ab" * 32 not in cli2.howto("ab" * 32), "不带动作时绝不打印密钥本身"


def test_cli_brief_puts_the_state_read_first_and_survives_a_missing_table(monkeypatch, tmp_path, capsys):
    cli = _cli(monkeypatch, tmp_path)
    state = dc.build("2026-11-12", [{"d": "2026-11-12", "feature": "stable_supply_30d", "value": -0.0477}], [])
    monkeypatch.setattr(cli, "_call", lambda m, p, api, body=None: {"ok": True, "state_read": state, "breadth": None, "rows": [], "hl_error": "TimeoutError: hl"})
    monkeypatch.setattr("sys.argv", ["regime_call.py", "brief"])
    cli.main()
    out = capsys.readouterr().out
    assert out.startswith("状态读法(截至 2026-11-12") and "稳定币 30 日 -4.77%" in out and "战场表读不到:TimeoutError: hl" in out


def test_brief_route_keeps_each_half_when_the_other_fails(monkeypatch):
    import asyncio

    import pytest
    from fastapi import HTTPException

    from src.api.routers import executor as ex
    from src.data.execution import battlefield_brief as bb
    monkeypatch.setattr(ex, "require_internal_token", lambda t: "seth")

    async def ctx_ok(d):
        return {"asof": d, "reads": {}}

    async def ctx_bad(d):
        raise TimeoutError("db")

    async def hl_ok(n, now=None):
        return {"at": "2026-11-13T00:00:00", "breadth": {"n": n}, "rows": [{"coin": "BTC"}]}

    async def hl_bad(n, now=None):
        raise RuntimeError("hl down")

    def call(ctx, hl):
        monkeypatch.setattr(dc, "context", ctx)
        monkeypatch.setattr(bb, "build_brief", hl)
        return asyncio.run(ex.regime_call_brief(top=40, x_internal_token="t"))
    r = call(ctx_ok, hl_ok)
    assert r["ok"] and r["breadth"] == {"n": 40} and r["state_read"]["reads"] == {} and len(r["state_read"]["asof"]) == 10
    r = call(ctx_bad, hl_ok)
    assert r["rows"] == [{"coin": "BTC"}] and r["state_read"] == {"error": "TimeoutError: db"}, "状态读不到不挡战场表"
    r = call(ctx_ok, hl_bad)
    assert r["ok"] and r["breadth"] is None and r["rows"] == [] and "hl down" in r["hl_error"] and "asof" in r["state_read"], "战场表读不到不挡状态读法"
    with pytest.raises(HTTPException) as e:
        call(ctx_bad, hl_bad)
    assert e.value.status_code == 502

