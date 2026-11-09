"""11-08 对手盘地图:六张前向记录表并成一个读面;基率必须有台账出处;一张表读不到不能当成「没有事件」。"""
import asyncio
import datetime as dt
from pathlib import Path

from src.data.signals import crowd_map as cm

ROOT = Path(__file__).resolve().parents[1]
NOW = dt.datetime(2026, 11, 20, 1, 0, tzinfo=dt.timezone.utc)


def test_every_base_rate_cites_a_ledger_entry_that_exists():
    led = ROOT / "REFUTATION_LEDGER.md"
    text = led.read_text(encoding="utf-8") if led.exists() else None        # 台账是私有文件(S-501),CI 上没有就只查格式
    for kind, b in cm.BASE_RATES.items():
        assert b["ledger"].startswith("S-") and b["vs"] and b["n"] > 0 and -1 < b["median_30d"] < 0, kind
        if text is not None:
            import re
            heads = {m.group(1) for m in re.finditer(r"^#{2,3} (S-\d+)\b", text, flags=re.M)}
            for ref in re.findall(r"S-\d+", b["ledger"]):
                assert ref in heads, (kind, ref)


def test_events_from_each_table_and_stacking():
    today = NOW.date()
    ev = (cm.to_events("binance_event_watch", [{"symbol": "foo", "d0": "2026-11-15", "kind": "upbit_krw_listing", "title": "t"}], today)
          + cm.to_events("crowding_watch", [{"symbol": "FOO", "d": "2026-11-17", "kind": "squeeze", "x30": None}], today)
          + cm.to_events("attention_watch", [{"symbol": "BAR", "d": "2026-11-01", "z": 4.2, "excess_30d": None}], today)
          + cm.to_events("delisting_watch", [{"symbol": "BAZ", "d0": "2026-11-10", "kind": "x"}], today)
          + cm.to_events("crowding_watch", [{"symbol": "QUX", "d": "2026-11-17", "kind": "other"}], today))
    kinds = {(e["symbol"], e["kind"]) for e in ev}
    assert kinds == {("FOO", "upbit_krw_listing"), ("FOO", "squeeze"), ("BAR", "attention_spike"), ("BAZ", "delisting")}
    foo = [e for e in ev if e["symbol"] == "FOO" and e["kind"] == "squeeze"][0]
    assert foo["age_days"] == 3 and foo["so_far_30d"] is None and foo["base"]["ledger"] == "S-781"
    s = cm.summarize(ev)
    assert s["stacked"] == [{"symbol": "FOO", "kinds": ["squeeze", "upbit_krw_listing"]}] and s["by_kind"]["delisting"] == 1


def test_unreadable_table_is_reported_not_silenced():
    async def read(table, params):
        assert "order" in params
        if table == "events":
            return [{"ts": "2026-10-01T00:00:00Z", "title": "Binance Will Extend the Monitoring Tag to Include BAR on 2026-10-01"}]   # 别的币 ⇒ 过滤掉
        assert params["symbol"] == "eq.FOO"
        if table == "attention_watch":
            raise RuntimeError("boom")
        if table == "crowding_watch":
            return [{"symbol": "FOO", "d": "2026-11-17", "kind": "squeeze"}]
        return []
    r = asyncio.run(cm.active(NOW, days=30, symbol="foo", read=read))
    assert r["n"] == 1 and r["missing"] == ["attention_watch: RuntimeError"] and r["ok"]


def test_monitoring_tags_are_current_state_not_a_window():
    rows = [{"ts": "2024-01-01T00:00:00Z", "title": "Binance Will Add Monitoring Tag on AAA, BBB (2024-01-01)"},
            {"ts": "2024-06-01T00:00:00Z", "title": "Binance Will Remove the Monitoring Tag on BBB (2024-06-01)"},
            {"ts": "2025-01-01T00:00:00Z", "title": "Binance Will Extend the Monitoring Tag to Include AAA, CCC and Remove the Seed Tag for DDD"}]
    ev = cm.active_tags(rows, NOW.date())
    assert [(e["symbol"], e["d"]) for e in ev] == [("AAA", "2024-01-01"), ("CCC", "2025-01-01")], "移除的不算;种子标签不算;记这一段打上的日子"
    assert ev[0]["base"]["ledger"] == "S-753 / S-789" and ev[0]["base"]["n"] == 60, "S-789:逐句解析后的事件集重量"
