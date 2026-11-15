"""T-395 / S-890:「状态取长处 v2」纸面前向账 —— 内核与研究脚本逐日相同、开账一次、晚到的源要等、拿不到的写明、不进真钱路径。"""
from __future__ import annotations

import ast
import asyncio
import datetime as dt
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import src.data.universe.state_book as sb  # noqa: E402

D0 = dt.date(2023, 1, 1)


def _research():
    spec = importlib.util.spec_from_file_location("s869_research", ROOT / "docs/research/s869_strategy_state.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _synthetic(n_days: int = 900, seed: int = 395):
    rng = np.random.default_rng(seed)
    days = [D0 + dt.timedelta(days=i) for i in range(n_days)]
    t = np.sign(np.cumsum(rng.normal(0, 1, n_days)) + 1e-9)
    l = np.sign(np.sin(np.arange(n_days) / 37.0) + 1e-9)
    labs = {d: {"R": "升", "W": "好", "T": "线下" if t[i] < 0 else "线上", "L": "抽" if l[i] < 0 else "注"} for i, d in enumerate(days)}
    names = ("A", "B", "C", "D")
    panel = {}
    for j, k in enumerate(names):
        start = 30 * j                                          # 成员起点不同 ⇒ 有的日子「不足 60 个观测」不可持有
        panel[k] = {d: float(rng.normal(0.0004 * (j + 1), 0.01 * (j + 1))) for d in days[start:]}
    return days, labs, panel


def test_kernel_equals_the_research_walk_on_a_fixed_roster() -> None:
    """生产内核(scaled + step + 格子)与 `s869_strategy_state.walk` 在同一份输入上逐日相同(名单固定 = S-890 的做法)。"""
    m = _research()
    days, labs, panel = _synthetic()
    roster = {"T线下·L抽": ["A", "C"], "T线下·L注": [], "T线上·L抽": ["B"], "T线上·L注": ["A", "B", "C", "D"]}
    months = [d for i, d in enumerate(days) if (i == 0 or d.month != days[i - 1].month) and (d - days[0]).days >= 60]
    tables = {mm: {"strength": roster, "good": []} for mm in months}
    sc_r = m._scaled(panel)
    res = m.walk(labs, tables, sc_r, m.G2, "cond")["series"]
    sc = {k: sb.scaled(v) for k, v in panel.items()}
    assert all(abs(sc[k][d][0] - sc_r[k][d]) < 1e-15 for k in panel for d in sc_r[k]) and all(set(sc[k]) == set(sc_r[k]) for k in panel)
    mine_roster = {f"{c[1:3]}·{c[-1]}": tuple(v) for c, v in roster.items()}
    n = 0
    for d, r in res.items():
        lab = labs.get(d - dt.timedelta(days=1))
        c = sb.cell_of("TxL", -1.0 if lab["T"] == "线下" else 1.0, -1.0 if lab["L"] == "抽" else 1.0, None)
        mine, _ = sb.step(list(mine_roster.get(c, ())), sc, d)
        assert abs(mine - r) < 1e-15, (d, mine, r)
        n += 1
    assert n > 700


def test_lead_axis_uses_only_strictly_earlier_values_and_needs_365_of_them() -> None:
    vals = {D0 + dt.timedelta(days=i): float(np.sin(i / 9.0)) for i in range(500)}
    lab = sb.lead_labels(vals)
    first = D0 + dt.timedelta(days=365)
    assert min(lab) == first, "更早的值不足 365 个的日子没有状态"
    prior = [vals[D0 + dt.timedelta(days=i)] for i in range(365)]
    assert lab[first] == (vals[first] > np.mean(prior))
    later = {**vals, **{d: v + 100 for d, v in vals.items() if d > first + dt.timedelta(days=50)}}
    lab2 = sb.lead_labels(later)
    assert all(lab2[d] == lab[d] for d in lab if d <= first + dt.timedelta(days=50)), "后来的值不许改变更早的标签"


def test_cells_follow_the_registered_axes() -> None:
    assert sb.cell_of("TxLEAD", -0.13, None, True) == "线下·主流领"
    assert sb.cell_of("TxLEAD", 0.02, -0.04, False) == "线上·二线领"
    assert sb.cell_of("TxL", -0.13, None, True) is None, "需要的轴缺了 ⇒ 没有格子"
    assert sb.cell_of("TxL", -0.13, -0.05, None) == "线下·抽" and sb.cell_of("T_ONLY", 0.0, None, None) == "线上"
    assert sb.cell_of("HOLD_ALL", None, None, None) == "全部"


def test_rosters_are_the_frozen_november_ones_and_every_member_is_accounted_for() -> None:
    assert sb.ROSTER_MONTH == "2026-11-01" and sb.START == "2026-11-15"
    assert sb.ROSTERS["TxLEAD"]["线下·主流领"] == ("s823_r6",)
    assert sb.ROSTERS["TxLEAD"]["线上·主流领"] == ("X1V", "R-v2", "carry_b_top_rc")
    assert sb.ROSTERS["T_ONLY"]["线下"] == ("XAUUSD",)
    assert set(sb.ROSTERS["HOLD_ALL"]["全部"]) == set(sb.PANEL) and len(sb.PANEL) == 26
    for arm, cells in sb.ROSTERS.items():
        for c, names in cells.items():
            assert set(names) <= set(sb.PANEL), (arm, c)
    assert set(sb.SOURCES) | set(sb.UNAVAILABLE) | set(sb.EXCLUDED) == set(sb.PANEL)
    assert not (set(sb.SOURCES) & set(sb.UNAVAILABLE)) and "carry_b_top_rc" in sb.EXCLUDED


def test_excess_and_weekend_legs() -> None:
    raw = {D0 + dt.timedelta(days=i): 0.01 for i in range(5)}
    cash = {D0 + dt.timedelta(days=1): 0.001, D0 + dt.timedelta(days=3): 0.002}
    ex = sb.excess(raw, cash, True)
    assert [round(ex[D0 + dt.timedelta(days=i)], 6) for i in range(5)] == [0.01, 0.009, 0.009, 0.008, 0.008], "向前沿用;最早一天之前 = 0"
    assert sb.excess(raw, cash, False) == raw, "R-v2 / 闸门空不扣现金"
    fri = dt.date(2026, 11, 13)
    r, known = sb.extend_weekend({fri - dt.timedelta(days=1): 0.01, fri: 0.02})
    assert known == fri + dt.timedelta(days=2) and r[fri + dt.timedelta(days=1)] == 0.0 and r[fri + dt.timedelta(days=2)] == 0.0
    _, known = sb.extend_weekend({dt.date(2026, 11, 11): 0.0})
    assert known == dt.date(2026, 11, 11)


def _inputs(cutoff: dt.date, late: dict | None = None):
    days = [dt.date(2026, 5, 1) + dt.timedelta(days=i) for i in range((cutoff - dt.date(2026, 5, 1)).days + 1)]
    rng = np.random.default_rng(7)
    rets, known = {}, {}
    for k in sb.SOURCES:
        last = (late or {}).get(k, cutoff)
        rets[k] = {d: float(rng.normal(0.0005, 0.01)) for d in days if d <= last}
        known[k] = last
    t = {d: (-0.1 if d >= dt.date(2026, 11, 10) else 0.05) for d in days}           # 11-10 起线下
    l = {d: -0.04 for d in days}
    lead = {d: True for d in days}
    return {"t": t, "l": l, "lead": lead, "rets": rets, "known": known, "missing": {}}


def test_plan_opens_once_names_what_cannot_be_held_and_waits_for_late_sources() -> None:
    cut = dt.date(2026, 11, 20)
    p = sb.plan_rows(_inputs(cut), {}, cut.isoformat())
    by = {}
    for r in p["nav"]:
        by.setdefault(r["arm"], []).append(r)
    assert set(by) == set(sb.ARMS)
    assert all(v[0]["d"] == sb.START and v[0]["nav"] == 1.0 and v[0]["ret"] is None for v in by.values())
    assert all(v[-1]["d"] == cut.isoformat() for v in by.values())
    lead = [r for r in by["TxLEAD"] if r["ret"] is not None]
    assert all(r["ret"] == 0.0 for r in lead), "线下 · 主流领 = R6,拿不到 ⇒ 现金"
    st = [h for h in p["holdings"] if h["arm"] == "TxLEAD" and h["key"] == "_state"]
    assert st and all("线下·主流领" in h["note"] and "拿不到 s823_r6" in h["note"] for h in st)
    assert all(h["as_of"] < "2026-11-20" for h in p["holdings"]), "持仓行记在决定那天(d − 1)"
    t_only = [h for h in p["holdings"] if h["arm"] == "T_ONLY" and h["key"] == "XAUUSD"]
    assert t_only and all(0 < h["weight"] <= sb.MAX_SCALE for h in t_only), "线下 ⇒ 只拿金"
    assert p["now"]["TxLEAD"]["cell"] == "线下·主流领" and "s823_r6" in p["now"]["TxLEAD"]["cannot_hold"]

    # 金晚到一天:T_ONLY 停在前一天等它;HOLD_ALL 也等;TxLEAD 不拿金,照写
    p2 = sb.plan_rows(_inputs(cut, late={"XAUUSD": cut - dt.timedelta(days=1)}), {}, cut.isoformat())
    last = {a: max(r["d"] for r in p2["nav"] if r["arm"] == a) for a in sb.ARMS}
    assert last["T_ONLY"] == "2026-11-19" and last["HOLD_ALL"] == "2026-11-19" and last["TxLEAD"] == "2026-11-20"
    # 晚到超过 LAG_GRACE_DAYS:按不可持有记、写明,不再等
    p3 = sb.plan_rows(_inputs(cut, late={"XAUUSD": cut - dt.timedelta(days=5)}), {}, cut.isoformat())
    assert max(r["d"] for r in p3["nav"] if r["arm"] == "T_ONLY") == "2026-11-17"
    assert any("XAUUSD" in n and "晚到" in n for n in p3["notes"])


def test_state_missing_waits_then_is_recorded_as_cash() -> None:
    cut = dt.date(2026, 11, 20)
    x = _inputs(cut)
    x["l"] = {d: v for d, v in x["l"].items() if d != cut - dt.timedelta(days=1)}
    p = sb.plan_rows(x, {}, cut.isoformat())
    assert max(r["d"] for r in p["nav"] if r["arm"] == "TxL") == "2026-11-19", "前一天的 L 还没出 ⇒ 等"
    x["l"] = {d: v for d, v in x["l"].items() if d != dt.date(2026, 11, 16)}
    p = sb.plan_rows(x, {}, cut.isoformat())
    r17 = [r for r in p["nav"] if r["arm"] == "TxL" and r["d"] == "2026-11-17"]
    assert r17 and r17[0]["ret"] == 0.0
    assert any(h["note"].startswith("状态缺") for h in p["holdings"] if h["arm"] == "TxL" and h["as_of"] == "2026-11-16")


class _DB:
    def __init__(self):
        self.tables = {"forward_book_holdings": [], "forward_book_nav": []}

    async def get_all(self, tail):
        return [dict(r) for r in self.tables.get(tail.split("?")[0], [])]

    async def upsert(self, table, rows, on_conflict):
        keys = on_conflict.split(",")
        cur = {tuple(r[k] for k in keys): r for r in self.tables[table]}
        for r in rows:
            cur[tuple(r[k] for k in keys)] = dict(r)
        self.tables[table] = list(cur.values())
        return SimpleNamespace(ok=True, why=None)


def test_run_writes_from_start_never_rewrites_and_is_cheap_when_up_to_date(monkeypatch) -> None:
    import src.api.store as store
    db = _DB()
    state = {"cut": dt.date(2026, 11, 20), "calls": 0}

    async def fake_inputs(cutoff):
        state["calls"] += 1
        return _inputs(dt.date.fromisoformat(cutoff))
    monkeypatch.setattr(sb, "_get_all", db.get_all)
    monkeypatch.setattr(sb, "load_inputs", fake_inputs)
    monkeypatch.setattr(store, "supabase_upsert_table", db.upsert)
    sb._LAST_FULL.clear()
    assert asyncio.run(sb.run_state_book("2026-11-14"))["waiting"]
    r = asyncio.run(sb.run_state_book(sb.START))
    assert r["ok"] and r["nav_written"] == 4 and {x["nav"] for x in db.tables["forward_book_nav"]} == {1.0}, "开账那天收盘就有第一行"
    sb._LAST_FULL.clear()
    r = asyncio.run(sb.run_state_book("2026-11-20"))
    assert r["ok"] and r["nav_written"] == 4 * 5, r
    before = {(x["arm"], x["d"]): x["nav"] for x in db.tables["forward_book_nav"]}
    assert asyncio.run(sb.run_state_book("2026-11-20")) == {"ok": True, "up_to_date": "2026-11-20"}
    assert state["calls"] == 2
    sb._LAST_FULL.clear()
    asyncio.run(sb.run_state_book("2026-11-23"))
    after = {(x["arm"], x["d"]): x["nav"] for x in db.tables["forward_book_nav"]}
    assert all(after[k] == v for k, v in before.items()), "写过的天不改"
    assert max(d for (_, d) in after) == "2026-11-23" and len(after) == 4 * 9
    # 落后的臂(等成员的源)⇒ 同一个 cutoff 3 小时内只整段读一次
    db.tables["forward_book_nav"] = [x for x in db.tables["forward_book_nav"] if not (x["arm"] == "HOLD_ALL" and x["d"] == "2026-11-23")]
    t0 = dt.datetime(2026, 11, 24, 1, tzinfo=dt.timezone.utc)
    sb._LAST_FULL.update({"cutoff": "2026-11-23", "at": t0})
    assert "throttled" in asyncio.run(sb.run_state_book("2026-11-23", now=t0 + dt.timedelta(hours=1)))


def test_wired_into_the_hourly_loop_and_never_into_a_real_money_path() -> None:
    mult = (ROOT / "src/data/signals/multiplier.py").read_text(encoding="utf-8")
    assert "run_state_book" in mult and "from src.data.universe.state_book import run_state_book" in mult
    paths = list((ROOT / "src/data/execution").rglob("*.py")) + [ROOT / "src/api/routers/executor.py"]
    for p in paths:
        if not p.exists():
            continue
        tree = ast.parse(p.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                mod = getattr(node, "module", "") or ""
                names = [a.name for a in node.names]
                assert "state_book" not in mod and not any("state_book" in n for n in names), f"{p} 不许读纸面账"


def test_load_inputs_reads_every_source_and_says_which_it_could_not(monkeypatch) -> None:
    import pandas as pd
    import src.data.universe.forward_books as fb
    days = pd.date_range("2024-01-01", "2026-11-14", freq="D")
    rng = np.random.default_rng(11)
    px = 100 * np.exp(np.cumsum(rng.normal(0, 0.02, len(days))))
    closes = {k: pd.Series(px * (1 + i), index=days) for i, k in enumerate(("BTC", "ETH", "CORE"))}
    fund = {k: pd.Series(0.05, index=days) for k in ("BTC", "ETH", "CORE")}

    async def tom_inputs(end):
        return closes, fund
    cal = [d.date() for d in days if d >= pd.Timestamp("2026-04-01")]
    tables = {
        "state_daily": ([{"d": d.isoformat(), "feature": f, "value": v} for d in cal
                         for f, v in (("dist_200", -0.1), ("stable_supply_30d", -0.04), ("stable_lend_apy_7d", 4.0))]),
        "r_money_daily": [{"d": d.isoformat(), "nav": 1 + 0.001 * i} for i, d in enumerate(cal) if d >= dt.date(2026, 10, 19)],
        "ohlcv_daily": [{"trade_date": d.isoformat(), "close": 100 + i} for i, d in enumerate(cal) if d.weekday() < 5],
        "style_index_pit_daily": [{"d": d.isoformat(), "style": s, "ret": 0.001} for d in cal for s in sb.STYLES if s != "meme"],
    }
    lead_rows = [{"d": (dt.date(2019, 1, 1) + dt.timedelta(days=i)).isoformat(), "value": float(np.sin(i / 30))} for i in range(2870)]

    async def get_all(tail):
        name = tail.split("?")[0]
        if name == "state_daily" and "style_rel_majors_30d" in tail:
            return lead_rows
        return [dict(r) for r in tables.get(name, [])]
    monkeypatch.setattr(fb, "tom_inputs", tom_inputs)
    monkeypatch.setattr(sb, "_get_all", get_all)
    x = asyncio.run(sb.load_inputs("2026-11-14"))
    assert set(x["rets"]) == set(sb.SOURCES) - {"style_meme"} and x["missing"] == {"style_meme": "style_index_pit_daily meme 读不到"}
    assert x["known"]["X1V"] == dt.date(2026, 11, 14) and x["known"]["ACWI"] == dt.date(2026, 11, 15), "11-14 是周六;周五收盘 ⇒ 周末已知"
    assert x["lead"] and x["t"][dt.date(2026, 11, 14)] == -0.1
    cash = 4.0 / 100 / 365
    d = dt.date(2026, 11, 10)
    assert abs(x["rets"]["style_ai"][d] - (0.001 - cash)) < 1e-12, "占本金的扣现金"
    assert abs(x["rets"]["R-v2"][d] - (tables["r_money_daily"][22]["nav"] / tables["r_money_daily"][21]["nav"] - 1)) < 1e-12, "R-v2 不扣"
    p = sb.plan_rows(x, {}, "2026-11-14")
    assert {r["arm"] for r in p["nav"]} == set(sb.ARMS)


def test_the_daily_loops_run_off_the_event_loop() -> None:
    """S-862:每小时循环里的逐日 Python 循环要进线程,不然会卡住整个应用的事件循环。"""
    src = (ROOT / "src/data/universe/state_book.py").read_text(encoding="utf-8")
    assert "asyncio.to_thread(_kernel_members" in src and "asyncio.to_thread(plan_rows" in src
