"""T-135 美元净流动性:单位换算、按可得日(不前视)、三个分量缺一不出行、观测原样入库。"""
from src.data.market import cis_inputs as ci


def _obs():
    # 周三观测(2026-09-02、09-09);逆回购每天
    return {"WALCL": [("2026-09-02", 6_600_000.0), ("2026-09-09", 6_610_000.0)],      # 百万美元
            "WTREGEN": [("2026-09-02", 800_000.0), ("2026-09-09", 750_000.0)],          # 百万美元(FRED 原样)
            "RRPONTSYD": [("2026-09-01", 100.0), ("2026-09-02", 90.0), ("2026-09-03", 80.0),
                          ("2026-09-09", 70.0), ("2026-09-10", 60.0)]}


def test_net_liquidity_is_dated_by_when_it_was_known_not_when_it_was_observed():
    rows = {r["d"]: r["value"] for r in ci.net_liquidity_rows(_obs(), "2026-09-01", "2026-09-12")}
    assert "2026-09-03" not in rows, "09-02 的周数据 09-04 才算已知 —— 之前不出行,不猜"
    # 09-04:资产负债表 6,600 − 财政部 800 − 逆回购(09-03 的 80,09-04 可得)= 5,720
    assert rows["2026-09-04"] == 6600 - 800 - 80
    assert rows["2026-09-10"] == 6600 - 800 - 70, "09-09 的周数据要到 09-11 才可得;逆回购 09-09 的值 09-10 可得"
    assert rows["2026-09-11"] == 6610 - 750 - 60
    assert rows["2026-09-12"] == rows["2026-09-11"], "没有新数 ⇒ 沿用最近一次已知的"


def test_observations_are_stored_as_observed_in_billions():
    r = ci.fred_rows("WALCL", [("2026-09-02", 6_600_000.0)])
    assert r == [{"series": "fed_balance_sheet", "d": "2026-09-02", "value": 6600.0, "source": "fred"}]
    assert ci.fred_rows("WTREGEN", [("2026-10-14", 883_373.0)])[0]["value"] == 883.373, "财政部存款也是百万美元"
    assert ci.fred_rows("RRPONTSYD", [("2017-12-29", 1.0)]) == [], "历史起点之前的不收"


def test_a_missing_component_means_no_row():
    obs = _obs()
    obs["WTREGEN"] = []
    assert ci.net_liquidity_rows(obs, "2026-09-01", "2026-09-12") == []


def test_credit_series_are_stored_on_their_availability_date_and_kept_apart():
    """11-06(T-258):HY 利差 / VIX3M 按可得日(观测日 + 1)入库;不进 FRED_SERIES(净流动性要三条齐全,信用读不到不能挡它)。"""
    from src.data.market import cis_inputs as ci
    rows = ci.credit_rows("BAMLH0A0HYM2", [("2026-11-04", 3.12), ("2026-11-05", float("nan"))], since="2026-01-01")
    assert rows == [{"series": "hy_oas", "d": "2026-11-05", "value": 3.12, "source": "fred"}]
    assert not set(ci.CREDIT_SERIES) & set(ci.FRED_SERIES)


def test_rates_and_dollar_series_are_ingested_by_availability_date():
    """S-844 / S-848:库里此前一条收益率都没有。美元指数周一才发布上一周 ⇒ 可得日要保守。"""
    want = {"DGS2": "ust_2y", "DGS10": "ust_10y", "DFII10": "ust_10y_real", "DFF": "fed_funds", "DTWEXBGS": "usd_broad"}
    for fid, name in want.items():
        assert ci.CREDIT_SERIES[fid][0] == name
    assert ci.CREDIT_SERIES["DTWEXBGS"][2] >= 8 and ci.CREDIT_SERIES["DGS2"][2] == 1
    rows = ci.credit_rows("DGS2", [("2026-11-06", 4.31), ("2026-11-07", float("nan"))], since="2026-01-01")
    assert rows == [{"series": "ust_2y", "d": "2026-11-07", "value": 4.31, "source": "fred"}]
    assert ci.credit_rows("DTWEXBGS", [("2026-11-06", 121.2)], since="2026-01-01")[0]["d"] == "2026-11-14"
    assert not set(ci.CREDIT_SERIES) & set(ci.FRED_SERIES)
