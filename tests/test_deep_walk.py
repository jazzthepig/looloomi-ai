"""往回走的守卫 (S-269)。

这个文件里只有一条真正重要的断言:

    **一个孤立的空块不得终止回溯。**

「这个标的还没上线」和「数据源在这段有洞」在一个空块上完全同形。
以第一个空块为终止条件,会在遇到缺口时把它**之前的全部历史静默丢掉** ——
而结果是一个天数更少、但看起来完全正常的面板。没有任何东西会报错。

第二条:**要求多深与实际多深是两个字段。** S-260 那次
`market_state_writer` 要 2022-01-01、实际只拿到 343 天,那个差额在任何日志里
都看不见,直到有人去数行数。
"""
from __future__ import annotations

import asyncio
import datetime as dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data.market.deep_walk import (                # noqa: E402
    FAILED, FLOOR, HIT_CAP, MAX_EMPTY_CHUNKS, NO_DATA,
    REACHED_FLOOR, REACHED_GENESIS, plan, summarise, walk_symbol,
)

_FAIL: list[str] = []
TODAY = dt.date(2026, 9, 2)


def _check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'✓' if ok else '✗'} {label}" + (f"\n      {detail}" if not ok else ""))
    if not ok:
        _FAIL.append(f"{label}{(' — ' + detail) if detail else ''}")


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _fetcher(*, genesis: dt.date = None, holes: set = None, fail_at: int = None):
    """假的抓取器:`genesis` 之前返回空,`holes` 里的块也返回空。"""
    holes = holes or set()
    calls = {"n": 0}

    async def f(coin_id, start, end):
        calls["n"] += 1
        if fail_at is not None and calls["n"] == fail_at:
            raise RuntimeError("模拟网络失败")
        if start in holes:
            return []
        if genesis and end < genesis:
            return []
        return [{"d": start.isoformat(), "close": 1.0}]

    f.calls = calls
    return f


def t_an_isolated_hole_does_not_terminate_the_walk():
    """**本文件的理由。** 一个洞不是起点。"""
    # 2020 上线;在 2023 附近挖一个洞。回溯必须跨过它继续走到 2020。
    genesis = dt.date(2020, 1, 1)
    # 找出会落在 2023 附近的那个块的 start
    probe = _fetcher(genesis=genesis)
    r0 = _run(walk_symbol("X", "x", fetch_chunk=probe, end=TODAY))
    _check("无洞时走到起点", r0.verdict == REACHED_GENESIS, f"{r0.verdict}: {r0.reason}")
    baseline_earliest = r0.earliest_reached

    # 现在在中途插一个洞:取一个确实被访问过、且晚于 genesis 的块起点
    mid = dt.date(2023, 6, 1)
    hole = None
    cur = TODAY
    from src.data.market.deep_walk import _windows_backwards
    for s, e in _windows_backwards(TODAY):
        if s <= mid <= e:
            hole = s
            break
    _check("找到一个位于中途的块作洞", hole is not None and hole > genesis, str(hole))

    holed = _fetcher(genesis=genesis, holes={hole})
    r = _run(walk_symbol("X", "x", fetch_chunk=holed, end=TODAY))
    _check("跨过孤立的洞,仍走到同一个起点",
           r.earliest_reached == baseline_earliest,
           f"有洞 {r.earliest_reached} vs 无洞 {baseline_earliest}")
    _check("洞被计数但不终止", r.n_empty_chunks >= 1 and r.verdict == REACHED_GENESIS,
           f"empty={r.n_empty_chunks} verdict={r.verdict}")

    # 判别性:若门槛是 1,这个洞就会终止回溯 —— 证明这个常数在做事。
    _check(f"MAX_EMPTY_CHUNKS = {MAX_EMPTY_CHUNKS} > 1(1 会把洞当起点)",
           MAX_EMPTY_CHUNKS > 1)


def t_walk_stops_at_the_symbols_own_genesis_not_at_2013():
    """2024 才上线的代币不该被问 2013 的事。"""
    late = _fetcher(genesis=dt.date(2024, 1, 1))
    r = _run(walk_symbol("NEW", "new", fetch_chunk=late, end=TODAY))
    _check("判 reached_genesis", r.verdict == REACHED_GENESIS, r.verdict)
    _check("实际起点接近 2024,不是 2013",
           r.earliest_reached and r.earliest_reached[:4] in ("2023", "2024"),
           str(r.earliest_reached))
    # 全量从 2013 走要 ~28 块;从自己的起点停只要 ~7 块。
    _check(f"只用了 {r.n_chunks_called} 次调用(全量约 28)",
           r.n_chunks_called < 15, str(r.n_chunks_called))

    old = _fetcher(genesis=dt.date(2010, 1, 1))
    r2 = _run(walk_symbol("BTC", "bitcoin", fetch_chunk=old, end=TODAY))
    _check("老资产走到档位下界 2013", r2.verdict == REACHED_FLOOR, r2.verdict)
    _check("最早日期不早于 FLOOR",
           r2.earliest_reached and r2.earliest_reached >= FLOOR.isoformat(),
           str(r2.earliest_reached))


def t_requested_and_actual_depth_are_separate_fields():
    """S-260:要求 2022-01-01、实际 343 天,而那个差额过去看不见。"""
    r = _run(walk_symbol("NEW", "new",
                         fetch_chunk=_fetcher(genesis=dt.date(2024, 1, 1)),
                         end=TODAY))
    _check("requested_start 是我们要的", r.requested_start == FLOOR.isoformat(),
           r.requested_start)
    _check("earliest_reached 是实际拿到的", r.earliest_reached != r.requested_start,
           f"{r.earliest_reached} vs {r.requested_start}")
    _check("差额被算出来", r.shortfall_days is not None and r.shortfall_days > 3000,
           str(r.shortfall_days))
    _check("depth_days 是实际深度", r.depth_days is not None and r.depth_days < 1200,
           str(r.depth_days))


def t_no_data_is_distinguished_from_genesis():
    """一根都没拿到 ≠ 走到了起点 —— 前者多半是 coin_id 错了。"""
    r = _run(walk_symbol("BAD", "not-a-coin",
                         fetch_chunk=_fetcher(genesis=dt.date(2099, 1, 1)),
                         end=TODAY))
    _check("一根都没有 → NO_DATA(不是 reached_genesis)", r.verdict == NO_DATA,
           r.verdict)
    _check("原因指向 coin_id 映射", "coin_id" in r.reason, r.reason)
    _check("earliest_reached 是 None,不是今天", r.earliest_reached is None)


def t_failure_keeps_what_was_already_fetched():
    """中途失败不丢已拿到的 —— 但深度必须如实报到失败点为止。"""
    f = _fetcher(genesis=dt.date(2015, 1, 1), fail_at=4)
    r = _run(walk_symbol("X", "x", fetch_chunk=f, end=TODAY))
    _check("判 FAILED", r.verdict == FAILED, r.verdict)
    _check("已拿到的不丢", r.n_candles > 0, str(r.n_candles))
    _check("earliest 报到失败前", r.earliest_reached is not None)
    _check("原因写明已拿到多少", "不丢" in r.reason, r.reason)


def t_cap_is_a_guardrail_not_an_expected_depth():
    """走满上限 ⇒ 更可能是循环坏了,必须显式判 HIT_CAP 而不是静默返回。"""
    r = _run(walk_symbol("X", "x", fetch_chunk=_fetcher(genesis=dt.date(1990, 1, 1)),
                         end=TODAY, floor=dt.date(1990, 1, 1), max_chunks=5))
    _check("触上限 → HIT_CAP", r.verdict == HIT_CAP, r.verdict)
    _check("原因明说不静默截断", "不静默截断" in r.reason, r.reason)
    _check("已拿到的仍然报出", r.n_candles > 0)


def t_plan_states_the_upper_bound_not_a_guess():
    p = plan(262)
    _check(f"262 标的上界 {p.est_calls_max:,} 次 = 月额度的 {p.pct_of_monthly}%",
           p.est_calls_max == 262 * p.max_chunks_each)
    _check("占比算出来且很小", 0 < p.pct_of_monthly < 5, str(p.pct_of_monthly))
    _check("说明里点破这是上界不是期望", "上界" in p.note and "实际远低于" in p.note,
           p.note)


def t_summary_reports_the_shortest_not_just_the_average():
    """横截面窗口由最短的那批决定,不由平均决定。"""
    from src.data.market.deep_walk import DeepResult
    rs = [DeepResult(f"s{i}", f"c{i}", REACHED_GENESIS, "", "2013-01-01",
                     (TODAY - dt.timedelta(days=d)).isoformat(), 100, 5, 1)
          for i, d in enumerate([4000] * 200 + [200] * 62)]
    s = summarise(rs)
    _check("中位数落在长的那批", s["median_depth_days"] > 3000,
           str(s["median_depth_days"]))
    _check("p10 暴露出短的那批", s["p10_depth_days"] < 1000, str(s["p10_depth_days"]))
    _check("最短也报出来", s["min_depth_days"] < 300, str(s["min_depth_days"]))
    _check("说明点破窗口由最短决定", "最短的那批决定" in s["reason"], s["reason"])

    empty = summarise([DeepResult("x", "y", NO_DATA, "", "2013-01-01")])
    _check("全无数据 → 中位数是 None 而不是 0", empty["median_depth_days"] is None)
    _check("原因指向 coin_id", "coin_id" in empty["reason"], empty["reason"])


if __name__ == "__main__":
    print("── 深度回溯守卫 (S-269) ──")
    for name, fn in sorted(globals().items()):
        if name.startswith("t_"):
            fn()
    if _FAIL:
        print(f"\n🔴 {len(_FAIL)} FAILED:")
        for f in _FAIL:
            print(f"   - {f}")
        sys.exit(1)
    print("\n✓ 深度回溯守卫全绿")
