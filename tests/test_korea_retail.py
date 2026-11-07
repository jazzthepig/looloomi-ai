"""韩国散户数据写端(11-07):Upbit 日线只留已收盘的日子、标签当天取 OR、公告标题解析。"""
import datetime as dt

from src.data.market import korea_retail as k


def _c(d, close=100.0):
    return {"candle_date_time_utc": f"{d}T00:00:00", "opening_price": 1, "high_price": 2, "low_price": 0.5, "trade_price": close,
            "candle_acc_trade_volume": 10, "candle_acc_trade_price": 1000}


def test_today_candle_is_dropped_and_non_krw_markets_are_ignored():
    today = dt.date(2026, 11, 7)
    rows = k.candle_rows("KRW-DOGE", [_c("2026-11-07"), _c("2026-11-06"), _c("2026-11-05")], today)
    assert [r["d"] for r in rows] == ["2026-11-06", "2026-11-05"], "今天那根还没收盘,不能落库"
    assert rows[0]["symbol"] == "DOGE" and rows[0]["vol_krw"] == 1000
    assert k.candle_rows("BTC-DOGE", [_c("2026-11-06")], today) == []


def test_flags_are_or_across_the_day():
    d, now = dt.date(2026, 11, 7), dt.datetime(2026, 11, 7, 12, tzinfo=dt.timezone.utc)
    mk = [{"market": "KRW-CYBER", "market_event": {"warning": False, "caution": {"TRADING_VOLUME_SOARING": False}}},
          {"market": "BTC-ETH", "market_event": {"warning": True}}]
    prev = {"KRW-CYBER": {"warning": True, "caution": {"TRADING_VOLUME_SOARING": True}}}
    rows = k.event_rows(mk, d, now, prev)
    assert len(rows) == 1 and rows[0]["warning"] is True and rows[0]["caution"]["TRADING_VOLUME_SOARING"] is True
    assert rows[0]["n_caution"] == 1 and set(rows[0]["caution"]) == set(k.CAUTION_KEYS)


def test_notice_titles():
    cases = {
        "하이브달러(HBD) 거래지원 종료 안내 (12/7 15:00)": ("delisting", ["HBD"], []),
        "콜렉터크립트(CARDS) 신규 거래지원 안내 (KRW, BTC, USDT 마켓)": ("listing", ["CARDS"], ["KRW", "BTC", "USDT"]),
        "닐리온(NIL) KRW 마켓 디지털 자산 추가": ("listing", ["NIL"], ["KRW"]),
        "커브(CRV) KRW, USDT 마켓 디지털 자산 추가": ("listing", ["CRV"], ["KRW", "USDT"]),
        "이더리움(ETH/KRW) 상장": ("listing", ["ETH"], ["KRW"]),
        "ETH/KRW 상장 및 전체 거래 오픈 안내": ("listing", ["ETH"], ["KRW"]),
        "스팀달러(SBD), 블록틱스(TIX) 상장 안내": ("listing", ["SBD", "TIX"], []),
        "BTC, USDT 마켓 신규 거래지원 안내 (BICO, BMT, NIL, GWEI) (BICO, BMT, NIL, GWEI 거래지원 개시 시점 추가 변경 안내)":
            ("listing", ["BICO", "BMT", "NIL", "GWEI"], ["BTC", "USDT"]),
        "인젝티브(INJ) 거래 유의 종목 지정 안내": ("warning", ["INJ"], []),
        "질리카(ZIL) 거래 유의 종목 지정 기간 연장 안내": ("warning_extend", ["ZIL"], []),
        "스타게이트파이낸스(STG), 레이어제로(ZRO) 유의 촉구 안내": ("caution_urge", ["STG", "ZRO"], []),
        "썬더코어(TT) 거래지원 종료 안내 (거래지원 종료 일정 변경 안내)": ("delisting", ["TT"], []),
    }
    for title, (kind, syms, mks) in cases.items():
        assert (k.notice_kind(title), k.notice_symbols(title), k.notice_markets(title)) == (kind, syms, mks), title
    assert k.notice_kind("신규가입자 거래 오픈 연기 (오픈 완료)") is None


def test_parse_notices_converts_kst_to_utc_and_unknown_market_is_none():
    p = {"data": {"notices": [
        {"id": 6739, "title": "콜렉터크립트(CARDS) 신규 거래지원 안내 (KRW, BTC, USDT 마켓)", "first_listed_at": "2026-11-05T15:03:03+09:00"},
        {"id": 1, "title": "리피오크레딧네트워크(RCN) 상장", "listed_at": "2017-11-07T19:43:19+09:00"},
        {"id": 2, "title": "입출금 일시 중단 안내", "listed_at": "2026-11-05T15:03:03+09:00"}]}}
    rows = k.parse_notices(p)
    assert len(rows) == 2 and rows[0]["ts"].startswith("2026-11-05T06:03:03") and rows[0]["source"] == "upbit"
    assert rows[0]["payload"]["krw"] is True and rows[1]["payload"]["krw"] is None, "标题没写市场 ⇒ 不知道,不是 False"
