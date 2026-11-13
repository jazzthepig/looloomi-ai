"""S-683 做空纸面臂的内核与采集:单票语义 = 研究模拟器、闸门 = r_tickets_scan、平仓票不改、数据没到不推进。"""
import datetime as dt
import io
import sys
import zipfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "docs" / "research"))
import short_lab_common as sl  # noqa: E402
from src.data.market import perp_bv_daily as bv  # noqa: E402
from src.data.signals import short_paper as sp  # noqa: E402


def _bars(o, h, l, c, start="2026-10-20", qv=1e7):
    d0 = dt.date.fromisoformat(start)
    return {"d": [(d0 + dt.timedelta(days=i)).isoformat() for i in range(len(c))],
            "o": np.array(o, float), "h": np.array(h, float), "l": np.array(l, float), "c": np.array(c, float),
            "qv": np.full(len(c), qv)}


# ── 单票语义与研究逐行相同 ─────────────────────────────────────────────────────────────────────────
def test_ticket_matches_the_research_simulator_on_stop_gap_time_and_rule():
    cases = [
        (_bars([100, 100, 101, 102], [100, 105, 131, 103], [100, 99, 100, 100], [100, 101, 102, 101]), 0.30, 10, None, None),
        (_bars([100, 100, 150, 150], [100, 101, 155, 151], [100, 99, 149, 149], [100, 100, 150, 150]), 0.30, 10, None, None),
        (_bars([100] * 8, [101] * 8, [90] * 8, [95] * 8), 0.30, 3, None, None),
        (_bars([100, 100, 98, 90, 91], [100, 101, 99, 92, 92], [99, 97, 96, 89, 90], [100, 98, 97, 91, 91]), 0.0, 30,
         (lambda a, j: j == 2), 110.0),
    ]
    for a, s, n, rule, stop in cases:
        p = sp.short_ticket(a, 0, s, n, exit_rule=rule, stop_px=stop)
        r = sl.short_ticket(a, 0, s, n, exit_rule=rule, stop_px=stop)
        assert (p["exit_d"], p["why"], p["exit_px"], p["entry_px"], p["stop_px"]) == \
               (r["exit_d"], r["why"], r["exit_px"], r["entry_px"], r["stop_px"])
        assert abs((p["gross"] - 2 * sp.COST_SIDE) / p["risk"] - r["r"]) < 1e-12


def test_signal_on_the_last_bar_is_pending_and_blocks_the_coin():
    a = _bars([100] * 3, [101] * 3, [99] * 3, [100] * 3)
    t = sp.short_ticket(a, 2, 0.5, 60)
    assert t["status"] == "pending"
    later = {**sp.short_ticket(_bars([100] * 6, [101] * 6, [99] * 6, [100] * 6), 4, 0.5, 60), "pair": "XUSDT"}
    out = sp.chain([{**t, "pair": "XUSDT"}, later])
    assert [x["signal_d"] for x in out] == [t["signal_d"]], "pending 占位:同币后面的信号不进"


def test_invalid_stop_means_no_ticket_like_research():
    a = _bars([100, 100, 100], [100, 100, 100], [99, 99, 99], [100, 100, 100])
    assert sp.short_ticket(a, 0, 0.0, 30, stop_px=99.0) is None


# ── 闸门 = r_tickets_scan 的 _rt_gate 取反 ──────────────────────────────────────────────────────────
def test_gate_is_open_until_200_rows_then_closed_below_its_200_day_mean():
    d0 = dt.date(2025, 1, 1)
    rows = [{"d": (d0 + dt.timedelta(days=i)).isoformat(), "ret": 0.01} for i in range(220)]
    rows += [{"d": (d0 + dt.timedelta(days=220 + i)).isoformat(), "ret": -0.05} for i in range(40)]
    g = sp.gate_closed_by_day(rows)
    assert g[rows[150]["d"]] is False, "n < 200 ⇒ 开"
    assert g[rows[219]["d"]] is False, "涨势里 ⇒ 开"
    assert g[rows[-1]["d"]] is True, "跌到 200 日均值下 ⇒ 关"


# ── 数据没到 ⇒ 停在前一天 ───────────────────────────────────────────────────────────────────────────
def test_target_day_refuses_a_day_with_too_few_contracts():
    today = dt.date(2026, 10, 30)
    full = {f"P{i}USDT": _bars([1] * 10, [1] * 10, [1] * 10, [1] * 10, start="2026-10-20") for i in range(10)}
    for k in list(full)[:5]:                                         # 一半合约 10-29 还没到
        full[k] = {x: v[:-1] for x, v in full[k].items()}
    gate = {(dt.date(2026, 10, 20) + dt.timedelta(days=i)).isoformat(): False for i in range(10)}
    d, why = sp.target_day(full, gate, today)
    assert d == "2026-10-28" and "90%" in why


# ── 平仓票的价格字段不改,资金费字段可以更新 ───────────────────────────────────────────────────────
def test_closed_ticket_price_fields_are_frozen_and_drift_is_reported():
    old = {"ticket_id": "x", "status": "closed", "entry_d": "2026-10-27", "entry_px": 1.0, "stop_px": 1.5,
           "exit_d": "2026-11-05", "exit_px": 0.9, "why": "time"}
    same = {**old, "funding": 0.01, "r_net": 0.22}
    moved = {**old, "exit_px": 0.95}
    w, drift = sp.merge_tickets([same], [old])
    assert w == [same] and drift == []
    w, drift = sp.merge_tickets([moved], [old])
    assert w == [] and drift and "exit_px" in drift[0]


# ── 对冲腿与钱曲线 ─────────────────────────────────────────────────────────────────────────────────
def test_a_new_signal_next_to_an_open_ticket_still_gets_written():
    """11-13 实测:H 臂有 6 张已开的票时来了新信号,那一轮起每次写入都是 PGRST102(All object keys must match),`last_d` 停在 11-11。
    等待中的票只有 8 列,已开的票是全列 —— 一次批量写入里键必须完全相同。"""
    import asyncio
    a = _bars([100, 100, 101, 102], [100, 101, 102, 103], [100, 99, 100, 101], [100, 101, 102, 102])
    pend = {"pair": "NEWUSDT", "symbol": "NEW", "signal_d": a["d"][-1], "status": "pending"}
    t_open = sp.short_ticket(a, 1, 0.30, 10)
    assert t_open and t_open["status"] == "open"
    rows = [sp.finish({**t_open, "pair": "OLDUSDT", "symbol": "OLD"}, a, {}, None, sp.ARM_H), sp.finish(pend, a, {}, None, sp.ARM_H),
            sp.finish({**t_open, "pair": "OL2USDT", "symbol": "OL2"}, a, {}, None, sp.ARM_H)]
    assert set(rows[0]) != set(rows[1]), "前提:两种票的列确实不同(哪天相同了,这条测试就该改)"
    calls = []

    class R:
        def __init__(self, ok, why=""):
            self.ok, self.why = ok, why

    async def postgrest(table, batch, on_conflict=None):               # 和 PostgREST 一样:一批里键不一致就整批拒收
        calls.append([r["ticket_id"] for r in batch])
        return R(len({tuple(sorted(r)) for r in batch}) == 1, "PGRST102 All object keys must match")
    assert not asyncio.run(postgrest(sp.TICKETS, rows)).ok, "原来的写法:一批写 ⇒ 被拒"
    calls.clear()
    r = asyncio.run(sp.write_tickets(postgrest, rows))
    assert r.ok and sorted(x for c in calls for x in c) == sorted(r_["ticket_id"] for r_ in rows) and len(calls) == 2
    assert calls[0] == [rows[0]["ticket_id"], rows[2]["ticket_id"]], "同一种键的行还在同一批、顺序不变"
    assert all("entry_px" not in r_ for r_ in sp.by_keyset(rows)[1]), "不拿 None 补齐等待中的票"

    async def down(table, batch, on_conflict=None):
        calls.append("x")
        return R(False, "HTTP 503")
    calls.clear()
    bad = asyncio.run(sp.write_tickets(down, rows))
    assert not bad.ok and bad.why == "HTTP 503" and len(calls) == 1, "第一组失败就停,原因原样交回"


def test_hedge_leg_is_btc_open_to_open_minus_cost_and_long_funding():
    a = _bars([100] * 6, [101] * 6, [90] * 6, [95] * 6, start="2026-10-26")
    btc = _bars([100, 100, 110, 110, 110, 110], [111] * 6, [99] * 6, [110] * 6, start="2026-10-26")
    t = {**sp.short_ticket(a, 0, 0.5, 2), "pair": "NEWUSDT", "symbol": "NEW", "listing_d": "2026-10-20"}
    fund = {"BTC": {"2026-10-27": 0.001, "2026-10-28": 0.001}}
    row = sp.finish(t, a, fund, btc, sp.ARM_L)
    assert t["exit_d"] == "2026-10-29" and abs(row["hedge_ret"] - (110 / 100 - 1 - 2 * sp.COST_SIDE - 0.002)) < 1e-12
    assert abs(row["r_hedged"] - (row["r_net"] * 0.5 + row["hedge_ret"]) / 0.5) < 1e-12


def test_money_flat_short_pays_cost_and_cap_limits_concurrency():
    bars = {f"P{i}USDT": _bars([100] * 12, [101] * 12, [99] * 12, [100] * 12, start="2026-10-26") for i in range(12)}
    rows = []
    for p, a in bars.items():
        t = {**sp.short_ticket(a, 0, 0.3, 5), "pair": p, "symbol": p[:-4]}
        rows.append(sp.finish(t, a, {}, None, sp.ARM_H))
    curve = sp.money(rows, bars, None, "2026-10-26", "2026-11-06", sp.ARM_H, cap=10)
    assert curve[-1]["nav"] < 1.0, "平价进出的空单要付成本"
    assert curve[-1]["taken"] == 10 and curve[-1]["skipped"] == 2


# ── 采集的纯函数 ───────────────────────────────────────────────────────────────────────────────────
def test_keep_matches_the_research_universe_filter():
    assert bv.keep("BTCUSDT") and bv.keep("1000PEPEUSDT")
    assert not bv.keep("BTCDOMUSDT") and not bv.keep("BTCUSDT_251226") and not bv.keep("ETHUSDC") and not bv.keep("龙虾USDT")


def test_parse_klines_zip_reads_header_and_microsecond_files():
    rows = ["open_time,open,high,low,close,volume,close_time,quote_volume,count,tbv,tbqv,ignore",
            "1761436800000,1,2,0.5,1.5,10,1761523199999,15,1,1,1,0",
            "1761523200000000,1.5,2,1,1.8,10,1761609599999999,18,1,1,1,0"]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("X-1d-2025-10.csv", "\n".join(rows))
    got = bv.parse_klines_zip(buf.getvalue())
    assert got == [("2025-10-26", 1.0, 2.0, 0.5, 1.5, 15.0, 1.0), ("2025-10-27", 1.5, 2.0, 1.0, 1.8, 18.0, 1.0)]   # 11-05:+ taker 买入报价额


def test_parse_index_pages():
    x = (b"<ListBucketResult><IsTruncated>true</IsTruncated>"
         b"<CommonPrefixes><Prefix>data/futures/um/daily/klines/AAAUSDT/</Prefix></CommonPrefixes>"
         b"<CommonPrefixes><Prefix>data/futures/um/daily/klines/BBBUSDT/</Prefix></CommonPrefixes></ListBucketResult>")
    assert bv.parse_index_prefixes(x) == (["AAAUSDT", "BBBUSDT"], True)
    y = (b"<Contents><Key>data/futures/um/daily/klines/A/1d/A-1d-2026-10-01.zip</Key></Contents>"
         b"<Contents><Key>data/futures/um/daily/klines/A/1d/A-1d-2026-10-01.zip.CHECKSUM</Key></Contents>")
    assert bv.parse_index_days(y) == ["2026-10-01"]


def test_plan_uses_months_for_whole_months_days_for_the_rest_and_stops_at_dead_from():
    today = dt.date(2026, 10, 26)
    pairs = [{"pair": "AUSDT", "first_d": "2020-01-01", "active": True},
             {"pair": "BUSDT", "first_d": "2026-10-21", "active": True},
             {"pair": "CUSDT", "first_d": "2025-11-20", "active": True, "dead_from": "2025-12-03"},
             {"pair": "DUSDT", "first_d": "2025-01-01", "active": False},
             {"pair": "EUSDT", "first_d": "2021-03-01", "active": False, "dead_from": "2021-05-01"}]
    p = bv.plan(pairs, {}, today)
    a = [w for pair, w, m in p if pair == "AUSDT"]
    assert "2020-01" in a and "2025-12" in a and "2026-09" in a and "2026-10-01" in a and "2026-10-25" in a and "2026-10-26" not in a
    assert sorted(w for pair, w, m in p if pair == "BUSDT") == [f"2026-10-{d}" for d in range(21, 26)]
    assert sorted(w for pair, w, m in p if pair == "CUSDT") == ["2025-11-20", "2025-11-21", "2025-11-22", "2025-11-23", "2025-11-24", "2025-11-25",
                                                                 "2025-11-26", "2025-11-27", "2025-11-28", "2025-11-29", "2025-11-30", "2025-12-01", "2025-12-02"]
    assert not any(pair == "DUSDT" for pair, _, _ in p), "不活跃又不知死期 ⇒ 没有区间"
    assert sorted(w for pair, w, m in p if pair == "EUSDT") == ["2021-03", "2021-04"], "11-05:死币也补到 dead_from 前一天 —— 留出段才有死币"
    covered = bv.plan(pairs[:1], {"AUSDT": {"min_d": "2025-12-01", "max_d": "2026-10-23"}}, today)
    assert [w for _, w, _ in covered][:2] == ["2026-10-25", "2026-10-24"], "先补缺的尾巴,最近的先取"
    assert [w for _, w, _ in covered][2:4] == ["2025-11", "2025-10"] and "2020-01" in [w for _, w, _ in covered], "再往前补到上市月(11-05 起整个永续史)"
    assert not any("2026-0" in w for _, w, _ in covered), "已覆盖的段不重取"


def test_month_days_falls_back_to_daily_files():
    assert bv.month_days("2026-02", dt.date(2026, 10, 1))[-1] == "2026-02-28"
    assert bv.month_days("2026-10", dt.date(2026, 10, 3)) == ["2026-10-01", "2026-10-02", "2026-10-03"]


# ── S-683 修订:只做加密合约 ───────────────────────────────────────────────────────────────────────
def test_coin_universe_excludes_tradfi_and_unclassified_and_reports_new_ones():
    pairs = [{"pair": "BTCUSDT", "first_d": "2019-09-08", "kind": "coin"},
             {"pair": "NEWUSDT", "first_d": "2026-10-22", "kind": "coin"},
             {"pair": "IBKRUSDT", "first_d": "2026-10-21", "kind": "tradfi"},
             {"pair": "MYSTUSDT", "first_d": "2026-10-23", "kind": None},
             {"pair": "TSLAUSDT", "first_d": "2026-01-28", "kind": "tradfi"}]
    coins, excluded = sp.coin_universe(pairs, "2026-10-26", "2026-10-30")
    assert coins == {"BTCUSDT", "NEWUSDT"}
    assert excluded == ["IBKRUSDT:tradfi", "MYSTUSDT:未分类"], "窗口里上市却被排除的要报出来;老的 TSLA 不在窗口"


def test_classify_marks_only_contracts_with_a_coingecko_coin_id():
    tickers = [{"symbol": "NEWUSDT", "coin_id": "new-token"}, {"symbol": "IBKRUSDT", "coin_id": None}]
    rows = bv.classify(["NEWUSDT", "IBKRUSDT", "GHOSTUSDT"], tickers, "2026-10-25T00:00:00+00:00")
    assert [(r["pair"], r["kind"], r["symbol"]) for r in rows] == [("NEWUSDT", "coin", "NEW")], \
        "没有 coin_id 的不分类(可能是股票,也可能是 CG 还没对上的新币),下一轮再查"


def test_repair_tasks_refetch_months_missing_taker_flow():
    """11-05(T-243):tbqv 后加,已有行缺它 —— 整月走月档、当月走缺的那几天、死币只到 dead_from 前一天。"""
    today = dt.date(2026, 11, 5)
    gaps = [{"pair": "AUSDT", "month": "2026-10", "n_null": 31, "min_d": "2026-10-01", "max_d": "2026-10-31"},
            {"pair": "AUSDT", "month": "2026-11", "n_null": 4, "min_d": "2026-11-01", "max_d": "2026-11-05"},
            {"pair": "DUSDT", "month": "2026-11", "n_null": 3, "min_d": "2026-11-01", "max_d": "2026-11-03"},
            {"pair": None, "month": "2026-10"}]
    t = bv.repair_tasks(gaps, today, {"DUSDT": "2026-11-03"})
    assert ("AUSDT", "2026-10", True) in t
    assert [w for p, w, m in t if p == "AUSDT" and not m] == ["2026-11-04", "2026-11-03", "2026-11-02", "2026-11-01"], "不取今天"
    assert [w for p, w, m in t if p == "DUSDT"] == ["2026-11-02", "2026-11-01"]
    assert t == sorted(t, key=lambda x: x[1], reverse=True)


def test_hole_tasks_find_missing_days_inside_coverage():
    """11-05(T-238 v2):2026-10-28 整天缺,plan 看不见中间的洞 —— 过完的月走月档、当月走日档、最近 3 天不算洞。"""
    today = dt.date(2026, 11, 20)
    counts = [{"d": (dt.date(2026, 10, 20) + dt.timedelta(days=i)).isoformat(), "n": 880} for i in range(31)]
    counts = [c for c in counts if c["d"] not in ("2026-10-28", "2026-11-12")] + [{"d": "2026-11-05", "n": 300}]
    counts = [c for c in counts if not (c["d"] == "2026-11-05" and c["n"] == 880)]
    pairs = [{"pair": "AUSDT"}, {"pair": "BUSDT"}, {"pair": "CUSDT"}]
    cov = {"AUSDT": {"min_d": "2026-01-01", "max_d": "2026-11-19"}, "BUSDT": {"min_d": "2026-10-29", "max_d": "2026-11-19"}}
    t = bv.hole_tasks(counts, pairs, cov, today)
    assert ("AUSDT", "2026-10", True) in t and not any(p == "BUSDT" and w == "2026-10" for p, w, _ in t), "洞在 B 上市之前"
    assert ("AUSDT", "2026-11-05", False) in t and ("BUSDT", "2026-11-05", False) in t, "行数塌一半也算洞"
    assert ("AUSDT", "2026-11-12", False) in t
    assert not any(p == "CUSDT" for p, _, _ in t), "没有覆盖的合约不补"
    assert not any(w >= "2026-11-17" for _, w, m in t if not m), "最近 3 天是还没上传,不是洞"
    assert bv.hole_tasks([], pairs, cov, today) == []


def test_hole_tasks_skip_days_upstream_never_published():
    """11-05:data.binance.vision 自己没有 2026-10-28 —— 记成 upstream_missing 跳过,不每轮重取整月。"""
    today = dt.date(2026, 11, 20)
    counts = [{"d": (dt.date(2026, 10, 20) + dt.timedelta(days=i)).isoformat(), "n": 880} for i in range(31)]
    counts = [c for c in counts if c["d"] != "2026-10-28"]
    assert "2026-10-28" in bv.hole_days_from(counts, today)
    pairs, cov = [{"pair": "AUSDT"}], {"AUSDT": {"min_d": "2026-01-01", "max_d": "2026-11-19"}}
    assert bv.hole_tasks(counts, pairs, cov, today) == [("AUSDT", "2026-10", True)]
    assert bv.hole_tasks(counts, pairs, cov, today, skip={"2026-10-28"}) == []


def test_a_single_missing_day_does_not_mark_a_contract_dead():
    """11-05(lane-c T-246):GRTUSDT / ZENUSDT / MDTUSDT 被一天的 404 标了死期却一直有新 bar —— 标死之前必须看那天之后还有没有档。"""
    src = (Path(__file__).resolve().parents[1] / "src/data/market/perp_bv_daily.py").read_text(encoding="utf-8")
    i, j = src.find("for pair, when in list(dead.items()):"), src.find("upd = [{**{k: known[p].get(k)")
    assert 0 < i < j, "标死之前的核对要在写 dead_from 之前"
    block = src[i:j]
    assert "get_binance_vision_um_daily(KIND, pair, when, index=True" in block and "if later:" in block and "dead.pop(pair" in block
