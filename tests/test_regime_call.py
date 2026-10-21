"""Jazz ⓪ 开关:判断的校验与生效、计划叠加、J 票状态机(与 r_tickets_scan 同序)、记分卡、主机风险倍数上限。"""
import asyncio
import datetime as dt

import pytest

from src.data.execution import book_of_truth as bt
from src.data.execution import regime_call as rc
from src.exec_host import tickets as tk

UTC = dt.timezone.utc
NOW = dt.datetime(2026, 10, 21, 14, 0, tzinfo=UTC)
NAMES = ["BTC", "ETH", "HYPE", "UNI", "kPEPE"]


def _call(id_, at, state="on", conviction=1, battlefield=(), close=(), days=14):
    at = at if isinstance(at, dt.datetime) else dt.datetime.fromisoformat(at).replace(tzinfo=UTC)
    return {"id": id_, "at": at.isoformat(), "state": state, "conviction": conviction, "battlefield": list(battlefield),
            "close_coins": list(close), "note": "", "effective_d": at.date().isoformat(),
            "expires_at": (at + dt.timedelta(days=days)).isoformat()}


# ── 一条判断 ────────────────────────────────────────────────────────────────────────────────────────────
def test_validate_resolves_hl_names_and_freezes_the_effective_day():
    row, why = rc.validate_call({"state": "on", "conviction": 2, "battlefield": ["hype", "PEPE"], "note": "第二段"},
                                NAMES, NOW)
    assert not why and row["battlefield"] == ["HYPE", "kPEPE"] and row["conviction"] == 2
    assert row["effective_d"] == "2026-10-21" and row["expires_at"].startswith("2026-11-04")


@pytest.mark.parametrize("body,needle", [
    ({"state": "maybe"}, "state"),
    ({"state": "on", "battlefield": ["NOPE"]}, "不是 HL"),
    ({"state": "off", "battlefield": ["HYPE"]}, "只在 state = on"),
    ({"state": "on", "battlefield": ["HYPE"], "close": ["HYPE"]}, "同时在战场和离场"),
    ({"state": "on", "days": 90}, "days"),
    ({"state": "on", "conviction": 5}, "conviction"),
    ({"state": "on", "battlefield": ["A", "B", "C", "D", "E", "F"]}, "最多"),
    ({"state": "on", "leverage": 5}, "未知字段"),
])
def test_validate_refuses_with_a_reason(body, needle):
    row, why = rc.validate_call(body, NAMES, NOW)
    assert row is None and any(needle in w for w in why), why


def test_unreadable_hl_listing_refuses_coin_names_but_not_a_plain_off():
    assert rc.validate_call({"state": "on", "battlefield": ["HYPE"]}, None, NOW)[0] is None
    row, why = rc.validate_call({"state": "off", "conviction": 3}, None, NOW)
    assert row and row["conviction"] == 1, "信心只在 on 时有意义"


def test_governing_call_is_the_latest_live_one_for_that_asof():
    a = _call(1, "2026-10-20T09:00:00", "on", days=14)
    b = _call(2, "2026-10-21T14:00:00", "off", days=1)
    assert rc.governing_call([a, b], "2026-10-20")["id"] == 1, "21 日下午的判断管 asof 21(22 日 00:45 执行),不管 20"
    assert rc.governing_call([a, b], "2026-10-21")["id"] == 2
    assert rc.governing_call([a, b], "2026-10-22")["id"] == 1, "b 22 日 14:00 到期,asof 22 的那一轮在 23 日 ⇒ 回到 a"
    assert rc.governing_call([a], "2026-11-04") is None, "到期 ⇒ 系统默认"


# ── 计划叠加 ────────────────────────────────────────────────────────────────────────────────────────────
def _plan(ready=True):
    return {"asof": "2026-10-21", "ready": ready, "risk_frac": 0.005, "cap": 10,
            "enter": [{"ticket_id": "SOL:2026-10-21", "symbol": "SOL", "stop_frac": 0.1}],
            "hold": [{"ticket_id": "AAVE:2026-10-01", "symbol": "AAVE"}], "exit": []}


J_PEND = {"ticket_id": "J:HYPE:2026-10-21", "coin": "HYPE", "status": "pending", "signal_d": "2026-10-21",
          "atr14": 4.0, "ref_close": 80.0, "risk_mult": 1.5}
J_OPEN = {"ticket_id": "J:UNI:2026-10-10", "coin": "UNI", "status": "open", "entry_d": "2026-10-11", "exit_flag": False}
J_FLAG = {"ticket_id": "J:kPEPE:2026-10-05", "coin": "kPEPE", "status": "open", "exit_flag": True, "exit_why": "human"}


def test_overlay_on_multiplies_risk_and_adds_battlefield_tickets_and_keeps_them_held():
    p = rc.overlay(_plan(), _call(1, "2026-10-20T09:00:00", "on", conviction=2), [J_PEND, J_OPEN, J_FLAG])
    sol, hype = p["enter"]
    assert sol["risk_mult"] == 1.5 and hype["symbol"] == "HYPE" and hype["stop_frac"] == pytest.approx(0.125)
    assert hype["risk_mult"] == 1.5 and hype["book"] == "jazz"
    assert {h["ticket_id"] for h in p["hold"]} == {"AAVE:2026-10-01", "J:UNI:2026-10-10"}, "主机对不在 hold 里的票一律出场"
    assert [x["ticket_id"] for x in p["exit"]] == ["J:kPEPE:2026-10-05"] and p["exit"][0]["why"] == "human"


def test_overlay_off_blocks_every_new_ticket_but_keeps_positions():
    p = rc.overlay(_plan(), _call(1, "2026-10-20T09:00:00", "off"), [J_PEND, J_OPEN])
    assert not p["enter"] and [b["ticket_id"] for b in p["blocked_by_call"]] == ["SOL:2026-10-21"]
    assert {h["ticket_id"] for h in p["hold"]} == {"AAVE:2026-10-01", "J:UNI:2026-10-10"}


def test_overlay_flat_exits_everything_including_r_v2_tickets():
    p = rc.overlay(_plan(), _call(1, "2026-10-20T09:00:00", "flat"), [J_OPEN])
    assert not p["enter"] and not p["hold"]
    assert {x["ticket_id"]: x["why"] for x in p["exit"]} == {"AAVE:2026-10-01": "flat: Jazz ⓪",
                                                             "J:UNI:2026-10-10": "flat: Jazz ⓪"}


def test_overlay_without_a_call_is_the_system_default_and_a_not_ready_plan_is_untouched():
    p = rc.overlay(_plan(), None, [])
    assert p["enter"][0]["risk_mult"] == 1.0 and p["regime_call"]["source"] == "system_default"
    q = rc.overlay(_plan(ready=False), _call(1, "2026-10-20T09:00:00", "flat"), [J_OPEN])
    assert q["hold"] == _plan()["hold"] and q["regime_call"]["state"] == "flat"


def test_plan_fails_closed_when_the_calls_cannot_be_read(monkeypatch):
    from src.data.execution import ticket_plan as tp

    async def fake(table, params):
        if table == "r_tickets_paper":
            return [{"ticket_id": "SOL:2026-10-21", "symbol": "SOL", "signal_d": "2026-10-21", "status": "pending",
                     "atr14": 10.0}]
        if table == "r_tickets_state":
            return [{"last_d": "2026-10-21"}]
        if table == "ohlcv_daily":
            return [{"symbol": "SOL", "trade_date": "2026-10-21", "close": 100.0}]
        raise RuntimeError("regime_calls 读不到")

    monkeypatch.setattr("src.data.style.header._read_all", fake)
    p = asyncio.run(tp.load_ticket_plan("2026-10-21"))
    assert p["ready"] is False and not p["enter"] and "不开不平" in p["why"]


# ── J 票状态机 ──────────────────────────────────────────────────────────────────────────────────────────
def _bars(start="2026-09-01", n=50, px=10.0, rng=0.2):
    d0 = dt.date.fromisoformat(start)
    return [((d0 + dt.timedelta(days=k)).isoformat(), px, px + rng, px - rng, px) for k in range(n)]


def _with(bars, day, o, h, l, c):
    return [b if b[0] != day else (day, o, h, l, c) for b in bars]


def test_battlefield_opens_a_pending_ticket_that_fills_next_open_with_a_2_5_atr_stop():
    bars = _bars()                                                 # 平价 10,ATR ≈ 0.4
    call = _call(7, "2026-10-01T09:00:00", "on", conviction=3, battlefield=["HYPE"])
    ind = {"HYPE": rc.indicators(bars)}
    ch, last = rc.j_scan_days({}, ind, [call], dt.date(2026, 10, 1), dt.date(2026, 10, 2))
    t = ch["J:HYPE:2026-10-01"]
    assert last == dt.date(2026, 10, 2) and t["status"] == "open" and t["entry_d"] == "2026-10-02"
    assert t["stop_px"] == pytest.approx(10.0 - 2.5 * 0.4) and t["risk_mult"] == 2.0 and t["call_id"] == 7
    assert len(ch) == 1, "已有在持的 J 票 ⇒ 同一个币不再开第二张"


def test_stop_sma20_time_and_gap_exits_follow_the_kernel_order():
    call = _call(1, "2026-10-01T09:00:00", "on", battlefield=["HYPE"])
    base = _bars(n=80)
    ind = {"HYPE": rc.indicators(base)}
    ch, _ = rc.j_scan_days({}, ind, [call], dt.date(2026, 10, 1), dt.date(2026, 10, 2))
    t = ch["J:HYPE:2026-10-01"]
    stop = t["stop_px"]
    # 盘中碰到止损 ⇒ 按止损线
    hit = rc.indicators(_with(base, "2026-10-05", 10.0, 10.1, stop - 0.01, 9.5))
    c1, _ = rc.j_scan_days({t["ticket_id"]: t}, {"HYPE": hit}, [], dt.date(2026, 10, 3), dt.date(2026, 10, 5))
    x = c1[t["ticket_id"]]
    assert x["status"] == "closed" and x["exit_reason"] == "stop" and x["exit_px"] == pytest.approx(stop)
    assert x["r_mult"] == pytest.approx(-1 - 0.004 * 10.0 / (10.0 - stop))
    # 跳空到止损下 ⇒ 按开盘
    gap = rc.indicators(_with(base, "2026-10-05", 8.0, 8.1, 7.9, 8.0))
    c2, _ = rc.j_scan_days({t["ticket_id"]: t}, {"HYPE": gap}, [], dt.date(2026, 10, 3), dt.date(2026, 10, 5))
    assert c2[t["ticket_id"]]["exit_px"] == 8.0
    # 收盘破 SMA20 ⇒ 标记,次日开盘出 —— 但要先站上过一次 SMA20(10-04 收 10.1)
    dip = rc.indicators(_with(_with(_with(base, "2026-10-04", 10.0, 10.2, 9.9, 10.1),
                                    "2026-10-05", 10.0, 10.1, 9.9, 9.95), "2026-10-06", 9.97, 10.0, 9.9, 9.95))
    c3, _ = rc.j_scan_days({t["ticket_id"]: t}, {"HYPE": dip}, [], dt.date(2026, 10, 3), dt.date(2026, 10, 6))
    y = c3[t["ticket_id"]]
    assert y["exit_reason"] == "sma20" and y["exit_d"] == "2026-10-06" and y["exit_px"] == 9.97
    # 回调里进场、还没站上过 SMA20 ⇒ 收在 SMA20 下面不出(只有止损管着)
    weak = rc.indicators(_with(base, "2026-10-05", 10.0, 10.1, 9.9, 9.95))
    c5, _ = rc.j_scan_days({t["ticket_id"]: t}, {"HYPE": weak}, [], dt.date(2026, 10, 3), dt.date(2026, 10, 7))
    assert c5[t["ticket_id"]]["status"] == "open" and not c5[t["ticket_id"]]["exit_flag"]
    # 120 根到期(平价、不破 SMA20 的走势里)
    up = [(d, 10 + k * 0.01, 10 + k * 0.01 + 0.2, 10 + k * 0.01 - 0.2, 10 + k * 0.01 + 0.005)
          for k, (d, *_r) in enumerate(_bars(n=200))]
    c4, _ = rc.j_scan_days({t["ticket_id"]: t}, {"HYPE": rc.indicators(up)}, [], dt.date(2026, 10, 3),
                           dt.date(2027, 3, 1))
    assert c4[t["ticket_id"]]["exit_reason"] == "time" and c4[t["ticket_id"]]["bars_held"] == 120


def test_human_close_and_flat_exit_at_the_next_open_and_are_labelled():
    call = _call(1, "2026-10-01T09:00:00", "on", battlefield=["HYPE"])
    ind = {"HYPE": rc.indicators(_bars(n=80))}
    ch, _ = rc.j_scan_days({}, ind, [call], dt.date(2026, 10, 1), dt.date(2026, 10, 2))
    t = ch["J:HYPE:2026-10-01"]
    close = _call(2, "2026-10-03T09:00:00", "on", close=["HYPE"])
    c1, _ = rc.j_scan_days({t["ticket_id"]: t}, ind, [call, close], dt.date(2026, 10, 3), dt.date(2026, 10, 4))
    assert c1[t["ticket_id"]]["exit_reason"] == "human" and c1[t["ticket_id"]]["exit_d"] == "2026-10-04"
    flat = _call(3, "2026-10-03T09:00:00", "flat")
    c2, _ = rc.j_scan_days({t["ticket_id"]: t}, ind, [call, flat], dt.date(2026, 10, 3), dt.date(2026, 10, 4))
    assert c2[t["ticket_id"]]["exit_reason"] == "flat"
    assert not [k for k in c2 if k != t["ticket_id"]], "flat 不开新票"


def test_a_coin_without_twenty_bars_gets_no_ticket_and_a_silent_coin_is_closed_after_ten_days():
    call = _call(1, "2026-10-01T09:00:00", "on", battlefield=["NEW"])
    ch, _ = rc.j_scan_days({}, {"NEW": rc.indicators(_bars(start="2026-09-20", n=12))}, [call],
                           dt.date(2026, 10, 1), dt.date(2026, 10, 1))
    assert not ch, "上市不足 20 根 ⇒ ATR / SMA20 不可信,不开"
    t = {"ticket_id": "J:OLD:2026-09-01", "coin": "OLD", "status": "open", "entry_d": "2026-09-02", "entry_px": 10.0,
         "stop_px": 9.0, "bars_held": 3}
    c, _ = rc.j_scan_days({t["ticket_id"]: t}, {"OLD": rc.indicators(_bars(start="2026-08-01", n=40))}, [],
                          dt.date(2026, 9, 15), dt.date(2026, 9, 20))
    assert c[t["ticket_id"]]["exit_reason"] == "no_data" and c[t["ticket_id"]]["exit_d"] == "2026-09-09"


# ── 记分卡 ──────────────────────────────────────────────────────────────────────────────────────────────
def test_scorecard_counts_blocked_r_conviction_j_tickets_and_flat_savings():
    on2 = _call(1, "2026-10-01T09:00:00", "on", conviction=2, days=5)
    off = _call(2, "2026-10-06T09:00:00", "off", days=5)
    flat = _call(3, "2026-10-12T09:00:00", "flat", days=2)
    rv2 = [{"ticket_id": "A:2026-10-02", "symbol": "A", "signal_d": "2026-10-02", "status": "closed", "r_mult": 2.0,
            "entry_d": "2026-10-03", "entry_px": 10.0, "stop_px": 9.0, "exit_d": "2026-10-20"},
           {"ticket_id": "B:2026-10-07", "symbol": "B", "signal_d": "2026-10-07", "status": "closed", "r_mult": -1.0},
           {"ticket_id": "C:2026-10-08", "symbol": "C", "signal_d": "2026-10-08", "status": "closed", "r_mult": 3.0}]
    js = [{"ticket_id": "J:HYPE:2026-10-01", "call_id": 1, "status": "closed", "r_mult": 4.0, "risk_mult": 1.5}]
    s = rc.scorecard([on2, off, flat], js, rv2, {("A", "2026-10-13"): 12.0})
    by = {c["id"]: c for c in s["calls"]}
    assert by[1]["j_r"] == 6.0 and by[1]["conviction_extra_r"] == pytest.approx(1.0), "J 票按风险倍数加权;A 多拿 0.5 × 2R"
    assert by[2]["blocked_rv2"] == 2 and by[2]["blocked_rv2_r"] == 2.0, "off 挡掉 B(−1)和 C(+3):机会成本 +2R"
    # flat 那天 A 还开着:按 13 日开盘 12 平 = 2R − 成本,纸面最后 2R ⇒ 只省下成本那一点(负)
    assert by[3]["flat_tickets"] == 1 and by[3]["flat_saved_r"] == pytest.approx(-0.04)
    assert s["totals"]["human_edge_r"] == pytest.approx(6.0 + 1.0 - 2.0 - 0.04)


# ── 主机与真相之书 ──────────────────────────────────────────────────────────────────────────────────────
def test_host_caps_the_conviction_multiplier_at_two():
    tplan = {"risk_frac": 0.005, "cap": 10, "portfolio_leverage": 1,
             "enter": [{"ticket_id": "J:HYPE:2026-10-21", "symbol": "HYPE", "stop_frac": 0.1, "risk_mult": 9}],
             "hold": [], "exit": []}
    act = tk.ticket_actions(tplan, {}, {}, {"HYPE": 80.0}, {"HYPE": 2}, 10_000.0, set())
    (e,) = act["entries"]
    assert e["risk_usd"] == pytest.approx(10_000 * 0.005 * 2.0), "Railway 给错也只到 2 倍"


def test_book_of_truth_reads_j_ticket_refs_and_always_takes_them():
    assert bt.parse_ref("r_v2:J:HYPE:2026-10-21:enter") == ("J:HYPE:2026-10-21", "enter", "")
    j = {"ticket_id": "J:HYPE:2026-10-21", "symbol": "HYPE", "signal_d": "2026-10-21", "status": "open",
         "entry_d": "2026-10-22", "entry_px": 80.0, "stop_px": 70.0}
    r = bt.reconcile([j], [], [], mode="live", asof="2026-10-25")
    assert r["tickets"][0]["class"] == "no_record", "J 票不走 R-v2 的满额先到先得:人选了没进就是违规"


# ── IO 路径(假的库与 HL)────────────────────────────────────────────────────────────────────────────────
class _Ok:
    def __bool__(self):
        return True


def test_plan_carries_the_call_and_the_j_ticket_through_the_loader(monkeypatch):
    from src.data.execution import ticket_plan as tp
    call = _call(3, "2026-10-20T09:00:00", "on", conviction=2, battlefield=["HYPE"])

    async def fake(table, params):
        return {"r_tickets_paper": [], "r_tickets_state": [{"last_d": "2026-10-21"}], "ohlcv_daily": [],
                "regime_calls": [call], "j_tickets": [J_PEND]}[table]

    monkeypatch.setattr("src.data.style.header._read_all", fake)
    p = asyncio.run(tp.load_ticket_plan("2026-10-21"))
    assert p["ready"] and p["regime_call"]["id"] == 3 and p["enter"][0]["ticket_id"] == "J:HYPE:2026-10-21"


def test_post_call_writes_one_row_and_reads_its_id_back(monkeypatch):
    rows = []

    async def names():
        return NAMES

    async def insert(table, r):
        rows.extend({**x, "id": len(rows) + 1} for x in r)
        return _Ok()

    async def read_all(table, params):
        return rows

    monkeypatch.setattr(rc, "hl_perp_names", names)
    monkeypatch.setattr("src.api.store.supabase_insert_table", insert)
    monkeypatch.setattr("src.data.style.header._read_all", read_all)
    r = asyncio.run(rc.post_call({"state": "on", "battlefield": ["hype"], "note": "x"}, NOW))
    assert r["ok"] and r["call"]["id"] == 1 and r["call"]["battlefield"] == ["HYPE"] and "2026-10-22" in r["executes"]
    bad = asyncio.run(rc.post_call({"state": "on", "battlefield": ["nope"]}, NOW))
    assert not bad["ok"] and len(rows) == 1


def test_j_scan_advances_writes_and_refuses_when_hl_is_down(monkeypatch):
    call = _call(1, "2026-10-19T09:00:00", "on", battlefield=["HYPE"])
    store = {"j_tickets_state": [{"last_d": "2026-10-19"}], "regime_calls": [call], "j_tickets": []}
    writes = []

    async def read_all(table, params):
        return store[table]

    async def upsert(table, r, on_conflict):
        writes.append((table, r))
        return _Ok()

    async def bars(coins, start):
        return {"HYPE": _bars(start="2026-09-01", n=50)}

    monkeypatch.setattr("src.data.style.header._read_all", read_all)
    monkeypatch.setattr("src.api.store.supabase_upsert_table", upsert)
    monkeypatch.setattr(rc, "hl_daily", bars)
    now = dt.datetime(2026, 10, 21, 0, 45, tzinfo=UTC)
    r = asyncio.run(rc.run_j_scan(now))
    assert r["status"] == "ok" and r["detail"]["to"] == "2026-10-20"
    (jt, rows), (st, srow) = writes
    assert jt == "j_tickets" and rows[0]["ticket_id"] == "J:HYPE:2026-10-20" and srow[0]["last_d"] == "2026-10-20"

    async def down(coins, start):
        raise RuntimeError("HL 502")

    monkeypatch.setattr(rc, "hl_daily", down)
    store["j_tickets_state"] = [{"last_d": "2026-10-19"}]
    r2 = asyncio.run(rc.run_j_scan(now))
    assert r2["status"] == "refused" and "停在 2026-10-19" in r2["reason"]
