"""S-690 真钱进场过滤(Jazz 10-27「直接应用」):d 收盘那一刻的 OI/市值快照 → 挡 p ≥ 2/3 的票。

守的东西:快照截面与研究同一个内核;只有 d+1 窗口里拍的快照算数;窗口内没快照就这一轮不开新票、过了窗口照常进;
被挡的票不腾位置;快照对不上归档就自动停用;读不到快照 ⇒ 不开新票,持有与出场照常。
"""
import asyncio
import datetime as dt

import pytest

from src.data.signals import oi_leverage as ol

D = dt.date(2026, 10, 27)
IN = dt.datetime(2026, 10, 28, 0, 7, tzinfo=dt.timezone.utc)
LATE = dt.datetime(2026, 10, 28, 3, 0, tzinfo=dt.timezone.utc)


def test_face_value_multipliers():
    assert ol.parse_mult("1000PEPE") == 1000 and ol.parse_mult("1000000MOG") == 1_000_000
    assert ol.parse_mult("1MBABYDOGE") == 1_000_000 and ol.parse_mult("1INCH") == 1 and ol.parse_mult("BTC") == 1


def test_pick_tickers_keeps_usdt_perps_in_the_universe():
    tk = [{"symbol": "BTCUSDT", "coin_id": "bitcoin", "open_interest_usd": 9e9, "converted_last": {"usd": "100000"},
           "contract_type": "perpetual"},
          {"symbol": "BTCUSDC", "coin_id": "bitcoin", "open_interest_usd": 1e9, "contract_type": "perpetual"},
          {"symbol": "ETHUSDT", "coin_id": "ethereum", "open_interest_usd": 5e9, "last": 3000, "contract_type": "futures"},
          {"symbol": "DOGEUSDT", "coin_id": "dogecoin", "open_interest_usd": 1e9, "last": "0.2"},
          {"symbol": "XYZUSDT", "coin_id": "xyz", "open_interest_usd": 1e6, "last": 1}]
    out = ol.pick_tickers(tk, ["BTC", "ETH", "DOGE"])
    assert set(out) == {"BTC", "DOGE"}, "USDC 合约、交割合约、宇宙外的名字都不要"
    assert out["BTC"] == {"coin_id": "bitcoin", "oi_usd": 9e9, "last_usd": 100000.0}
    assert out["DOGE"]["last_usd"] == 0.2


def _uni(n=12):
    syms = [f"C{i:02d}" for i in range(n)]
    tk = {s: {"coin_id": s.lower(), "oi_usd": 1e6 * (i + 1) ** 2, "last_usd": 1.0} for i, s in enumerate(syms)}
    mk = [{"id": s.lower(), "current_price": 1.0, "market_cap": 3e7 * (i + 1)} for i, s in enumerate(syms)]
    return syms, tk, mk


def test_snapshot_rows_use_the_research_kernel_and_record_why_names_are_out():
    syms, tk, mk = _uni()
    tk["C00"] = {**tk["C00"], "last_usd": 1.2}                         # 映射错了:CG 价与合约价差 17%
    mk[1] = {**mk[1], "market_cap": 1e7}                               # 市值不够
    del tk["C02"]                                                      # 合约不在 CG 行情里
    rows = ol.snapshot_rows(D, syms, tk, mk, IN.isoformat())
    by = {r["symbol"]: r for r in rows}
    assert "映射" in by["C00"]["why_out"] and "2,000 万" in by["C01"]["why_out"] and "CoinGecko" in by["C02"]["why_out"]
    cand = [{"sym": s, "oi": tk[s]["oi_usd"], "mcap": 3e7 * (i + 1)} for i, s in enumerate(syms) if i > 2]
    ref = ol.size_neutral_pct(cand)
    assert {s: by[s]["p"] for s in ref} == {s: round(v, 5) for s, v in ref.items()}
    assert all(by[s]["n_cs"] == 9 and by[s]["in_cs"] for s in ref) and by["C00"]["p"] is None


def test_only_a_snapshot_taken_in_the_d_plus_one_window_counts():
    assert ol.in_window(D, IN) and not ol.in_window(D, LATE)
    assert not ol.in_window(D, dt.datetime(2026, 10, 27, 23, 59, tzinfo=dt.timezone.utc)), "d 还没收盘"


def _snap(p, at=IN, sym="AAA"):
    return {"d": D.isoformat(), "symbol": sym, "kind": "live", "p": p, "n_cs": 110, "snap_at": at.isoformat()}


E = [{"ticket_id": "AAA:2026-10-27", "symbol": "AAA"}, {"ticket_id": "BBB:2026-10-27", "symbol": "BBB"}]
FRESH = {"n_pairs": 0, "h_agree": None, "rho": None}


def test_high_tickets_are_skipped_and_names_outside_the_snapshot_still_enter():
    kept, skipped, info = ol.filter_enter(E, D.isoformat(), [_snap(0.9), _snap(0.2, sym="CCC")], FRESH, IN)
    assert [s["ticket_id"] for s in skipped] == ["AAA:2026-10-27"] and skipped[0]["oi_p"] == 0.9
    assert [k["ticket_id"] for k in kept] == ["BBB:2026-10-27"] and kept[0]["oi_p"] is None
    assert info["status"] == "applied"
    kept, skipped, _ = ol.filter_enter(E, D.isoformat(), [_snap(0.66)], FRESH, IN)
    assert not skipped, "0.66 < 2/3"


def test_no_snapshot_waits_inside_the_window_then_enters_unfiltered():
    kept, held, info = ol.filter_enter(E, D.isoformat(), [], FRESH, IN)
    assert not kept and len(held) == 2 and info["status"] == "waiting_snapshot"
    kept, held, info = ol.filter_enter(E, D.isoformat(), [], FRESH, LATE)
    assert len(kept) == 2 and not held and info["status"] == "unavailable"
    late_snap = [_snap(0.9, at=LATE)]
    kept, _, info = ol.filter_enter(E, D.isoformat(), late_snap, FRESH, LATE)
    assert len(kept) == 2 and info["status"] == "unavailable", "窗口外拍的不算 d 收盘"


def test_audit_switches_the_filter_off_when_the_snapshot_disagrees_with_the_archive():
    good = [{"p": i / 400, "p_archive": i / 400} for i in range(400)]
    bad = [{"p": i / 400, "p_archive": 1 - i / 400} for i in range(400)]
    g, b = ol.agreement(good), ol.agreement(bad)
    assert g["h_agree"] == 1.0 and g["rho"] == 1.0 and b["rho"] == -1.0
    assert ol.audit_verdict(g)[0] and not ol.audit_verdict(b)[0]
    assert ol.audit_verdict(ol.agreement(bad[:100]))[0], "名字对不够之前照用(Jazz 直接应用)"
    kept, skipped, info = ol.filter_enter(E, D.isoformat(), [_snap(0.9)], b, IN)
    assert len(kept) == 2 and not skipped and info["status"] == "disabled_by_audit"


def test_tag_row_carries_the_live_reading():
    t = {"ticket_id": "x", "symbol": "ARB", "signal_d": "2026-10-27"}
    r = ol.tag_row(t, {}, 0, "归档还没落库", {"ARB": 0.8})
    assert r["p"] is None and r["p_live"] == 0.8 and r["high_live"] is True


# ── 计划里接上 ─────────────────────────────────────────────────────────────
def _fake(snap, fail=False):
    async def fake(table, params):
        if table == "r_tickets_paper":
            return [{"ticket_id": "AAA:2026-10-27", "symbol": "AAA", "signal_d": "2026-10-27", "status": "pending",
                     "atr14": 1.0},
                    {"ticket_id": "BBB:2026-10-27", "symbol": "BBB", "signal_d": "2026-10-27", "status": "pending",
                     "atr14": 1.0}]
        if table == "r_tickets_state":
            return [{"last_d": "2026-10-27"}]
        if table == "ohlcv_daily":
            return [{"symbol": "AAA", "trade_date": "2026-10-27", "close": 10.0},
                    {"symbol": "BBB", "trade_date": "2026-10-27", "close": 10.0}]
        if table == ol.SNAP_TABLE:
            if fail:
                raise RuntimeError("oi_lev_snapshot_daily 读不到")
            return snap if params.get("d", "").startswith("eq.") else []
        if table in ("regime_calls", "j_tickets"):
            return []
        raise AssertionError(table)
    return fake


def test_plan_skips_the_high_ticket_without_freeing_its_slot(monkeypatch):
    from src.data.execution import ticket_plan as tp
    monkeypatch.setattr("src.data.style.header._read_all", _fake([_snap(0.9)]))
    p = asyncio.run(tp.load_ticket_plan("2026-10-27", now=IN))
    assert p["ready"] and [e["symbol"] for e in p["enter"]] == ["BBB"]
    assert [s["symbol"] for s in p["skipped_oi"]] == ["AAA"] and p["oi_filter"]["status"] == "applied"
    assert not p["skipped_cap"], "被挡的票不腾位置,也不算满额跳过"


def test_plan_opens_nothing_new_when_the_snapshot_cannot_be_read(monkeypatch):
    from src.data.execution import ticket_plan as tp
    monkeypatch.setattr("src.data.style.header._read_all", _fake([], fail=True))
    p = asyncio.run(tp.load_ticket_plan("2026-10-27"))
    assert p["ready"] and not p["enter"] and len(p["skipped_oi"]) == 2 and p["oi_filter"]["status"] == "read_error"


def test_live_snapshot_refuses_outside_the_window(monkeypatch):
    async def fake(table, params):
        assert table == "deriv_metrics_daily"
        return [{"symbol": "BTC", "d": "2026-10-26"}]
    monkeypatch.setattr("src.data.style.header._read_all", fake)
    r = asyncio.run(ol.snapshot_once(now=LATE, kind="live"))
    assert r["status"] == "refused" and "窗口" in r["reason"]


@pytest.mark.parametrize("hour,ok", [(0, True), (1, True), (2, False)])
def test_window_is_two_hours(hour, ok):
    assert ol.in_window(D, dt.datetime(2026, 10, 28, hour, 30, tzinfo=dt.timezone.utc)) is ok
