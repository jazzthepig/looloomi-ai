"""CIS v2 影子写入端(S-668):同一个 d 跟着 v1 正式发布走;个股宇宙不含 ETF 与本地挂牌;周市值配当周最后一个收盘;
v1 没发就不算;一个 d 只写一次;有分比例写进结果。"""
import asyncio
import datetime as dt

from src.data.cis import v2, v2_shadow as sh


def test_equity_universe_is_companies_only():
    eu = sh.equity_universe(["AAPL", "1398.HK", "NESN.SW", "V", "NVO"])
    assert "AAPL" in eu and "V" in eu and "NVO" in eu
    assert "1398.HK" not in eu and "NESN.SW" not in eu, "本地挂牌这一版不算(股数要换汇)"
    assert not {"SPY", "QQQ", "XLF"} & set(eu), "ETF 不是公司"


def test_weekly_close_is_the_last_close_on_or_before_the_week_date():
    rows = [{"key": "A", "d": "2026-10-09", "mcap_usd": 100.0}, {"key": "A", "d": "2026-10-16", "mcap_usd": 110.0}]
    closes = {"A": [("2026-10-08", 9.0), ("2026-10-09", 10.0), ("2026-10-15", 11.0), ("2026-10-19", 99.0)]}
    assert sh.weekly_closes(rows, closes)["A"] == [("2026-10-09", 100.0, 10.0), ("2026-10-16", 110.0, 11.0)]


def test_rows_carry_group_version_and_coverage():
    d = dt.date(2026, 10, 21)
    crypto = {"BTC": {"size": 30, "stability": -0.02, "supply": 0.0, "f": 80, "o": 70},
              "ETH": {"size": 29, "stability": -0.03, "supply": -0.01, "f": 70, "o": 60}}
    equity = {"AAPL": {"size": 28, "stability": -0.02, "supply": 0.01}, "XX": {"size": None, "stability": None, "supply": None}}
    rows = sh.shadow_rows(d, crypto, equity, "2026-10-22T06:00:00+00:00")
    assert {r["grp"] for r in rows} == {"crypto", "equity"} and all(r["code_ref"] == v2.CODE_REF for r in rows)
    assert sh.coverage(rows, "equity", 2) == 0.5 and sh.coverage(rows, "crypto", 2) == 1.0


class _Fake:
    def __init__(self, official, done=False):
        self.official, self.done, self.written = official, done, None

    async def read_all(self, table, params):
        if table == "cis_v2_daily":
            return [{"symbol": "BTC"}] if self.done else []
        if table == "cis_official_daily":
            return self.official
        if table == "asset_mcap_daily":
            base = dt.date(2026, 7, 1)
            return [{"coin_id": "bitcoin", "d": (base + dt.timedelta(days=i)).isoformat(), "price": 100 + i,
                     "mcap": (100 + i) * 19.0e6} for i in range(115)]
        if table == "world50_mcap_weekly":
            base = dt.date(2025, 9, 5)
            return [{"key": "AAPL", "d": (base + dt.timedelta(weeks=i)).isoformat(), "mcap_usd": 3e12 + i * 1e9}
                    for i in range(60)]
        if table == "ohlcv_daily":
            base = dt.date(2025, 9, 1)
            return [{"symbol": "AAPL", "trade_date": (base + dt.timedelta(days=i)).isoformat(), "close": 200 + (i % 7)}
                    for i in range(420)]
        return []

    async def insert(self, table, rows):
        self.written = (table, rows)

        class R:
            ok, why = True, None
        return R()


def _run(monkeypatch, fake):
    import src.api.store as store
    import src.data.style.header as header
    monkeypatch.setattr(header, "_read_all", fake.read_all)
    monkeypatch.setattr(store, "supabase_insert_table", fake.insert)
    return asyncio.run(sh.run_once(dt.datetime(2026, 10, 22, 6, 30, tzinfo=dt.timezone.utc)))


def test_waits_for_v1_and_writes_once(monkeypatch):
    r = _run(monkeypatch, _Fake(official=[]))
    assert r["refused"] and r["written"] == 0 and "v1 正式还没发布" in r["reason"]
    r = _run(monkeypatch, _Fake(official=[{"symbol": "BTC", "pillar_f": 80, "pillar_o": 70}], done=True))
    assert r["written"] == 0 and "只发一次" in r["reason"]
    f = _Fake(official=[{"symbol": "BTC", "pillar_f": 80, "pillar_o": 70}])
    r = _run(monkeypatch, f)
    assert r["ok"] and f.written[0] == "cis_v2_daily" and r["d"] == "2026-10-21"
    btc = next(x for x in f.written[1] if x["symbol"] == "BTC")
    assert btc["grp"] == "crypto" and btc["n_dims"] == 5 and btc["raw"]["f"] == 80
    assert any(x["symbol"] == "AAPL" and x["grp"] == "equity" for x in f.written[1])
    assert set(r["coverage"]) == {"crypto", "equity"}
