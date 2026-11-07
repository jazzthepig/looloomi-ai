"""S-751 ✅ 落地(11-07):Binance 整币下架观察名单 + 前向记录 —— 筛选与 T-272 一字不差、到期才结算、没价不写 0。"""
import asyncio
import datetime as dt
from pathlib import Path

from src.data.signals import delisting_watch as dw

ROOT = Path(__file__).resolve().parents[1]


def test_screen_and_extract_match_t272():
    assert dw.screen_title("Binance Will Delist EPIC, QUICK on 2026-10-28")
    assert not dw.screen_title("Binance Will Delist ABC/BTC Trading Pair") and not dw.screen_title("Notice of Removal of Spot Trading Pairs - 2026-10-01")
    assert not dw.screen_title("Binance Margin Will Delist XYZ Isolated Margin Pairs")
    assert dw.extract_symbols("Binance Will Delist EPIC, QUICK and ZZZ on 2026-10-28") == ["EPIC", "QUICK", "ZZZ"]
    assert dw.extract_symbols("Binance Will Delist HNT (2023-03-17)") == ["HNT"]


def test_entries_take_the_first_announcement_and_tag_forward():
    ev = [{"ts": "2026-11-08T10:00:00+00:00", "title": "Binance Will Delist AAA, BBB on 2026-11-20"},
          {"ts": "2025-05-01T10:00:00+00:00", "title": "Binance Will Delist AAA on 2025-05-10"},
          {"ts": "2025-06-01T10:00:00+00:00", "title": "Binance Will Delist CCC/BTC Trading Pair"}]
    e = {x["symbol"]: x for x in dw.entries(ev)}
    assert set(e) == {"AAA", "BBB"} and e["AAA"]["d0"] == "2025-05-01" and e["AAA"]["kind"] == "backfill"
    assert e["BBB"]["kind"] == "forward" and e["BBB"]["d0"] == "2026-11-08"


def test_settle_only_when_matured_and_never_zero_for_missing():
    d0 = dt.date(2026, 10, 1)
    px = {(d0 + dt.timedelta(k)).isoformat(): 1.0 - 0.01 * k for k in range(40)}
    btc = {(d0 + dt.timedelta(k)).isoformat(): 100.0 for k in range(40)}
    e = {"symbol": "X", "announced_at": "2026-10-01T09:00:00+00:00", "d0": "2026-10-01", "title": "t", "kind": "backfill"}
    r = dw.settle(e, px, btc, dt.date(2026, 11, 7))
    assert abs(r["excess_30d"] - (0.70 - 1.0)) < 1e-9 and abs(r["excess_7d"] - (0.93 - 1.0)) < 1e-9 and r["settled_at"]
    early = dw.settle(e, px, btc, dt.date(2026, 10, 20))
    assert early["excess_30d"] is None and early["excess_7d"] is not None and early["settled_at"] is None, "没到期不结算"
    gone = dw.settle(e, {}, btc, dt.date(2026, 11, 7))
    assert gone["excess_30d"] is None and gone["price_source"] is None, "下架后没价 ⇒ 空着,不写 0"


def test_watchlist_window_and_run_once(monkeypatch):
    now = dt.datetime(2026, 11, 7, 12, tzinfo=dt.timezone.utc)
    rows = [{"symbol": "OLD", "announced_at": "2026-01-01T00:00:00+00:00"}, {"symbol": "NEW", "announced_at": "2026-10-20T00:00:00+00:00"}]
    assert [x["symbol"] for x in dw.watchlist(rows, now)] == ["NEW"]
    written = []

    async def read(table, params):
        if table == "events":
            return [{"ts": "2026-10-14T08:00:00+00:00", "title": "Binance Will Delist EPIC, QUICK on 2026-10-28"}]
        return [{"symbol": s, "d": (dt.date(2026, 10, 14) + dt.timedelta(k)).isoformat(), "price": p}
                for s, p in (("BTC", 100.0), ("EPIC", 1.0)) for k in range(30)]

    async def upsert(table, rows, on_conflict=None):
        written.extend(rows)
        return True
    r = asyncio.run(dw.run_once(now, read, upsert))
    assert r["ok"] and r["written"] == 2 and set(r["watch"]) == {"EPIC", "QUICK"}
    assert all(set(x) <= set(dw.WRITES_COLUMNS[dw.TABLE]) for x in written)
    q = [x for x in written if x["symbol"] == "QUICK"][0]
    assert q["excess_7d"] is None and q["price_source"] is None


def test_wiring():
    assert "async def _delisting_watch_loop" in (ROOT / "src/api/main.py").read_text(encoding="utf-8")
    mig = (ROOT / "migrations/2026-11-07_delisting_watch.sql").read_text(encoding="utf-8")
    assert all(c in mig for c in dw.WRITES_COLUMNS[dw.TABLE])
