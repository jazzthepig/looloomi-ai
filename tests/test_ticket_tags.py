"""R-v2 票的稀释标签(S-665 前向):symbol 对齐、取市值最大的 coin_id、7 天容差、缺数据写原因不写 0。"""
import asyncio
import datetime as dt
import math

import pytest

from src.data.signals import ticket_tags as tt


def test_symbol_and_coin_choice():
    assert tt.norm_symbol("1000PEPE") == "PEPE" and tt.norm_symbol("uni") == "UNI"
    assert tt.pick_coin([{"symbol": "UNI", "coin_id": "uniswap", "mcap": 5e9},
                         {"symbol": "UNI", "coin_id": "unicorn-fart", "mcap": 1e5}]) == {"UNI": "uniswap"}


def test_dilution_is_the_90_day_log_supply_change_with_a_7_day_tolerance():
    d0 = dt.date(2026, 7, 1)
    ser = [(d0 + dt.timedelta(days=k), 100.0 + k * 0.1) for k in range(0, 120, 3)]   # 每 3 天一个点
    t = {"ticket_id": "UNI:2026-10-01", "symbol": "UNI", "signal_d": "2026-10-01"}
    row = tt.tag(t, "uniswap", ser)
    assert row["dil90"] == pytest.approx(math.log(row["supply_t"] / row["supply_t90"]))
    assert row["dil90"] > 0 and row["why_missing"] is None
    late = tt.tag({**t, "signal_d": "2026-12-31"}, "uniswap", ser)
    assert late["dil90"] is None and "7 天" in late["why_missing"]
    assert tt.tag(t, None, [])["why_missing"].startswith("asset_mcap_daily")


def test_tagger_tags_only_untagged_tickets(monkeypatch):
    written = []

    async def read_all(table, params):
        if table == "r_tickets_paper":
            return [{"ticket_id": "A:2026-10-01", "symbol": "A", "signal_d": "2026-10-01"},
                    {"ticket_id": "B:2026-10-01", "symbol": "B", "signal_d": "2026-10-01"}]
        if table == "r_ticket_tags":
            return [{"ticket_id": "B:2026-10-01"}]
        if table == "asset_mcap_daily":
            return [{"symbol": "A", "coin_id": "a", "d": "2026-07-03", "price": 1.0, "mcap": 100.0},
                    {"symbol": "A", "coin_id": "a", "d": "2026-10-01", "price": 1.0, "mcap": 110.0}]
        raise AssertionError(table)

    class Last:
        ok, rows, reason = True, [{"d": "2026-10-01"}], "ok"

    async def sb_get(table, params):
        return Last()

    async def upsert(table, rows, on_conflict):
        written.extend(rows)
        return True

    monkeypatch.setattr("src.data.style.header._read_all", read_all)
    monkeypatch.setattr("src.data.vector.market_state_writer._sb_get", sb_get)
    monkeypatch.setattr("src.api.store.supabase_upsert_table", upsert)
    out = asyncio.run(tt.tag_new_tickets())
    assert out["tagged"] == 1 and [w["ticket_id"] for w in written] == ["A:2026-10-01"]
    assert written[0]["dil90"] == pytest.approx(math.log(1.1)) and out["high_dil"] == 1
