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


def test_hard_rule_plan_filter_skips_new_and_forces_exit():
    """Jazz 11-07:Binance 宣布整币下架 ⇒ 不开新票、已有持仓当天开盘出场;1000 前缀也认。"""
    now = dt.datetime(2026, 11, 7, tzinfo=dt.timezone.utc)
    excl = dw.exclusion_set([{"symbol": "STORJ", "announced_at": "2026-08-20T00:00:00+00:00"},
                             {"symbol": "PEPE", "announced_at": "2026-10-01T00:00:00+00:00"},
                             {"symbol": "OLD", "announced_at": "2024-01-01T00:00:00+00:00"}], now)
    assert excl == {"STORJ", "PEPE"}, "窗口 365 天:更早的代号可能已被新币复用"
    plan = {"ready": True, "enter": [{"ticket_id": "a", "symbol": "STORJ"}, {"ticket_id": "b", "symbol": "UNI"}],
            "hold": [{"ticket_id": "c", "symbol": "1000PEPE"}, {"ticket_id": "d", "symbol": "SOL"}], "exit": []}
    out = dw.apply_to_plan(plan, excl)
    assert [e["symbol"] for e in out["enter"]] == ["UNI"] and [e["symbol"] for e in out["skipped_delist"]] == ["STORJ"]
    assert [h["symbol"] for h in out["hold"]] == ["SOL"]
    assert out["exit"] == [{"ticket_id": "c", "symbol": "1000PEPE", "why": "binance_delisting", "at": "today_open"}]
    assert out["delist_filter"]["forced_exit"] == ["1000PEPE"]


def test_plan_fails_closed_when_the_list_is_unreadable(monkeypatch):
    import src.data.style.header as hdr
    from src.data.execution import ticket_plan as tpm
    asof = "2026-11-06"

    async def fake(table, params):
        if table == "r_tickets_paper":
            return [{"ticket_id": "X:1", "symbol": "STORJ", "signal_d": asof, "status": "pending", "atr14": 0.4},
                    {"ticket_id": "Y:1", "symbol": "UNI", "signal_d": asof, "status": "pending", "atr14": 0.4}]
        if table == "r_tickets_state":
            return [{"last_d": asof}]
        if table == "ohlcv_daily":
            return [{"symbol": s, "trade_date": asof, "close": 8.0} for s in ("STORJ", "UNI")]
        if table == "delisting_watch":
            if fake.fail:
                raise RuntimeError("delisting_watch 读不到")
            return [{"symbol": "STORJ", "announced_at": "2026-08-20T00:00:00+00:00"}]
        if table in ("regime_calls", "j_tickets", "oi_lev_snapshot_daily"):
            return []
        raise AssertionError(table)
    fake.fail = False
    monkeypatch.setattr(hdr, "_read_all", fake)
    monkeypatch.delenv("R_V2_RISK_FRAC", raising=False)
    p = asyncio.run(tpm.load_ticket_plan(asof))
    assert [e["symbol"] for e in p["enter"]] == ["UNI"] and p["delist_filter"]["skipped"] == ["STORJ"]
    fake.fail = True
    p = asyncio.run(tpm.load_ticket_plan(asof))
    assert p["enter"] == [] and p["delist_filter"]["status"] == "read_error", "读不到名单 ⇒ 不开新票"


def test_long_book_panels_are_checked():
    assert dw.panel_conflicts({"STORJ", "XMR"}) == {}, "11-07:面板与全部下架代币零交集"
    hit = dw.panel_conflicts({"ONDO"})
    assert hit and all(v == ["ONDO"] for v in hit.values())
