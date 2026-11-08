"""S-763 / S-758 ✅ 之后(11-07):上币 / 上永续的前向记录 —— 口径、首次公告、到期才结算、没价不写 0。"""
import asyncio
import datetime as dt
from pathlib import Path

from src.data.signals import event_watch as ew

ROOT = Path(__file__).resolve().parents[1]


def test_keep_and_first_announcement():
    ev = [{"ts": "2026-11-08T10:00:00+00:00", "kind": "listing", "title": "Binance Will List FOO (FOO)", "symbols": ["FOO"], "payload": {"scope": "spot"}},
          {"ts": "2026-11-09T10:00:00+00:00", "kind": "listing", "title": "Binance Will List FOO again", "symbols": ["FOO"], "payload": {"scope": "spot"}},
          {"ts": "2026-11-08T10:00:00+00:00", "kind": "listing", "title": "Binance Will Add New Trading Pairs", "symbols": ["BAR"], "payload": {"scope": "spot"}},
          {"ts": "2026-11-08T10:00:00+00:00", "kind": "listing", "title": "Binance Margin Will Add", "symbols": ["BAZ"], "payload": {"scope": "margin"}},
          {"ts": "2025-01-01T10:00:00+00:00", "kind": "perp_listing", "title": "Binance Futures Will Launch USDⓈ-Margined QUX Perpetual", "symbols": ["QUX"], "payload": {"scope": "margin"}},
          {"ts": "2025-01-01T10:00:00+00:00", "kind": "perp_listing", "title": "Binance Futures Will Launch COIN-M ZZZ", "symbols": ["ZZZ"], "payload": {"scope": "futures"}}]
    e = {(x["kind"], x["symbol"]): x for x in ew.entries(ev)}
    assert set(e) == {("listing", "FOO"), ("perp_listing", "QUX")}
    assert e[("listing", "FOO")]["announced_at"].startswith("2026-11-08") and e[("listing", "FOO")]["cohort"] == "forward"
    assert e[("perp_listing", "QUX")]["cohort"] == "backfill", "USDⓈ-Margined 的 scope 被标成 margin 也要算永续"


def test_settle_waits_for_late_open_and_maturity():
    e = {"kind": "listing", "symbol": "FOO", "announced_at": "2026-06-01T08:00:00+00:00", "d0": "2026-06-01", "title": "t", "cohort": "backfill"}
    d0 = dt.date(2026, 6, 1)
    px = {(d0 + dt.timedelta(k)).isoformat(): 1.0 for k in range(3, 120)}           # 公告后第 3 天才开盘
    btc = {(d0 + dt.timedelta(k)).isoformat(): 100.0 for k in range(0, 120)}
    r = ew.settle(e, px, btc, dt.date(2026, 11, 7))
    assert r["excess_30d"] == 0.0 and r["excess_90d"] == 0.0 and r["settled_at"]
    early = ew.settle(e, px, btc, dt.date(2026, 7, 20))
    assert early["excess_30d"] is not None and early["excess_90d"] is None and early["settled_at"] is None
    gone = ew.settle(e, {}, btc, dt.date(2026, 11, 7))
    assert gone["excess_30d"] is None and gone["price_source"] is None, "没价 ⇒ 空着"


def test_recent_and_run_once():
    now = dt.datetime(2026, 11, 20, tzinfo=dt.timezone.utc)
    rows = [{"symbol": "FOO", "announced_at": "2026-11-08T10:00:00+00:00"}, {"symbol": "FOO", "announced_at": "2026-01-01T00:00:00+00:00"}]
    assert len(ew.recent(rows, "foo", now)) == 1
    written = []

    async def read(table, params):
        if table == "events":
            return [{"ts": "2026-11-08T10:00:00+00:00", "kind": "listing", "title": "Binance Will List FOO", "symbols": ["FOO"], "payload": {"scope": "spot"}}]
        return [{"symbol": "BTC", "d": "2026-11-08", "price": 100.0}]

    async def upsert(table, rows, on_conflict=None):
        written.extend(rows)
        return True
    r = asyncio.run(ew.run_once(now, read, upsert))
    assert r["ok"] and r["forward"] == 1 and written[0]["excess_30d"] is None
    assert all(set(x) <= set(ew.WRITES_COLUMNS[ew.TABLE]) for x in written)


def test_wiring():
    main = (ROOT / "src/api/main.py").read_text(encoding="utf-8")
    assert "from src.data.signals.event_watch import run_once" in main
    mig = (ROOT / "migrations/2026-11-07_binance_event_watch.sql").read_text(encoding="utf-8")
    assert all(c in mig for c in ew.WRITES_COLUMNS[ew.TABLE])


def test_upbit_krw_first_listing_is_recorded_separately():
    """11-08 S-770 ✅:Upbit 只记 KRW 上币(krw = true),每个代号第一次;BTC / USDT 市场与 krw 不明的不记;前向从 11-08 起。"""
    ev = [{"ts": "2026-11-08T03:00:00+00:00", "kind": "listing", "source": "upbit", "title": "KRW 마켓 디지털 자산 추가 (FOO)",
           "symbols": ["FOO"], "payload": {"krw": True}},
          {"ts": "2026-11-07T03:00:00+00:00", "kind": "listing", "source": "upbit", "title": "BTC 마켓 디지털 자산 추가 (FOO)",
           "symbols": ["FOO"], "payload": {"krw": False}},
          {"ts": "2026-11-05T03:00:00+00:00", "kind": "listing", "source": "upbit", "title": "KRW 마켓 디지털 자산 추가 (BAR)",
           "symbols": ["BAR"], "payload": {"krw": True}},
          {"ts": "2018-03-22T03:00:00+00:00", "kind": "listing", "source": "upbit", "title": "x", "symbols": ["BAZ"], "payload": {"krw": None}},
          {"ts": "2026-11-08T03:00:00+00:00", "kind": "listing", "title": "Binance Will List FOO", "symbols": ["FOO"], "payload": {"scope": "spot"}}]
    e = {(x["kind"], x["symbol"]): x for x in ew.entries(ev)}
    assert set(e) == {(ew.UPBIT_KIND, "FOO"), (ew.UPBIT_KIND, "BAR"), ("listing", "FOO")}, "同一个代号在两个所各记一条"
    assert e[(ew.UPBIT_KIND, "FOO")]["cohort"] == "forward" and e[(ew.UPBIT_KIND, "BAR")]["cohort"] == "backfill"
    mig = (ROOT / "migrations/2026-11-08_event_watch_upbit.sql").read_text(encoding="utf-8")
    assert all(f"'{k}'" in mig for k in ew.KINDS), "表的 kind 约束要认得每一类"
