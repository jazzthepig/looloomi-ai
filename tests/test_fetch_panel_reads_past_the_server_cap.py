"""S-416 — `fetch_panel` 必须读过 PostgREST 的 1000 行上限。

`PAGE = 10_000` 配 `if len(batch) < PAGE: break`:服务端每页只给 1000 行,
于是第一页就满足「比我要的少」,循环退出。实测 2026-09-24 读回 25 个标的 × 40 天,
止于 2025-11-12 —— `market_state_writer` 和 `panel_read` 的唯一读价路径一直在读一个旧切片。

这里用一个**每页最多给 1000 行**的假服务端,喂 2,500 行,断言三件事:
全部读到 · 读到空页才停 · 标的过滤真的下推到了查询里。

**T-379:翻页方式换成了按键翻页**(第二页起用上一页最后一行的键接着读,不用 OFFSET)。
本文件守的四条**一条没删**,只是「读到空页才停」这条改用按键续读的说法来断言
(最后一次的请求带的是续读谓词,不带 offset)。假服务端也按真的那样**先排序再切页** ——
按键续读只有在服务端按排序键返回行时才成立。
"""
from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SERVER_CAP = 1000

#: `fetch_panel` 的续读谓词形状(T-379)。形状变了 ⇒ 这里断言失败,不许悄悄放过。
_CURSOR = re.compile(
    r"^\(trade_date\.gt\.([^,()]+),and\(trade_date\.eq\.([^,()]+),symbol\.gt\.([^,()]+)\)\)$")


def _sorted_rows(rows: list[dict]) -> list[dict]:
    """按 (trade_date, symbol) 升序 —— 真服务端带 ORDER BY 就是这个顺序。"""
    return sorted(rows, key=lambda r: (str(r["trade_date"]), str(r["symbol"])))


def _after_cursor(rows: list[dict], params: dict) -> list[bool] | None:
    """续读谓词 ⇒ 每行「在游标之后吗」。没有谓词 ⇒ None(走 OFFSET 版)。"""
    pred = params.get("or")
    if not pred:
        return None
    m = _CURSOR.match(pred)
    assert m, f"看不懂的续读谓词(形状变了?):{pred}"
    day, day_eq, sym = m.group(1), m.group(2), m.group(3)
    assert day == day_eq, f"续读谓词里两处日期不一致:{pred}"
    return [(str(r["trade_date"]), str(r["symbol"])) > (day, sym) for r in rows]


def test_reads_every_row_past_the_cap() -> None:
    from src.data.vector import market_state_writer as w

    rows = _sorted_rows(
        [{"symbol": f"S{i % 5}", "trade_date": f"2026-{1 + (i // 150) % 12:02d}-{1 + i % 28:02d}",
          "close": 1.0 + i, "volume": 1.0, "source": "coingecko_pro_ohlc"} for i in range(2500)])
    seen_params: list[dict] = []
    batch_sizes: list[int] = []

    async def fake_get(path, params):
        seen_params.append(dict(params))
        lim = min(int(params["limit"]), SERVER_CAP)
        keep = _after_cursor(rows, params)
        if keep is None:
            off = int(params["offset"])
            batch = rows[off: off + lim]
        else:
            batch = [r for r, k in zip(rows, keep) if k][:lim]
        batch_sizes.append(len(batch))
        return w.SbRead(batch)

    old = w._sb_get
    w._sb_get = fake_get
    try:
        panel, _ = asyncio.run(w.fetch_panel("2026-01-01", source="coingecko_pro_ohlc",
                                             symbols=["S1", "S2"]))
    finally:
        w._sb_get = old

    n = sum(len(v) for v in panel.values())
    distinct = len({(r["symbol"], r["trade_date"]) for r in rows})
    assert n == distinct, f"只读到 {n} 格,应为 {distinct} —— 分页在服务端上限处停了"
    assert batch_sizes and batch_sizes[-1] == 0, f"没有读到空页就停了:{batch_sizes}"
    assert seen_params[0].get("symbol") == "in.(S1,S2)", f"标的过滤没下推:{seen_params[0]}"
    print(f"  ✓ 2,500 行在每页 {SERVER_CAP} 的上限下全部读到({len(seen_params)} 次请求,末页为空)")
    print("  ✓ 标的过滤下推到查询里")


def test_a_higher_server_cap_means_fewer_pages_and_the_same_rows() -> None:
    """T-379 第二步:服务端上限 10,000 时,25,000 行 = 3 页 + 1 个空页;上限还是 1,000 时照样读全(上面那条)。"""
    from src.data.vector import market_state_writer as w

    rows = _sorted_rows(
        [{"symbol": f"S{i % 50}", "trade_date": f"20{20 + i // 18250:02d}-{1 + (i // 1400) % 12:02d}-{1 + (i // 50) % 28:02d}",
          "close": 1.0 + i, "volume": 1.0, "source": "coingecko_pro_ohlc"} for i in range(25000)])
    calls: list[tuple[int, int]] = []
    shapes: list[bool] = []

    def run(cap: int) -> int:
        calls.clear()
        shapes.clear()

        async def fake_get(path, params):
            lim = min(int(params["limit"]), cap)
            keep = _after_cursor(rows, params)
            if keep is None:
                off = int(params["offset"])
                batch = rows[off: off + lim]
            else:
                batch = [r for r, k in zip(rows, keep) if k][:lim]
            calls.append((off if keep is None else -1, lim))
            shapes.append(keep is not None)
            return w.SbRead(batch)

        old_get = w._sb_get
        w._sb_get = fake_get
        try:
            panel, _ = asyncio.run(w.fetch_panel("2020-01-01", source="coingecko_pro_ohlc"))
        finally:
            w._sb_get = old_get
        return sum(len(v) for v in panel.values())

    distinct = len({(r["symbol"], r["trade_date"]) for r in rows})
    n_big = run(10000)
    assert n_big == distinct and len(calls) == 4, f"上限 10,000:应 3 页 + 1 空页,实际 {len(calls)} 次请求、{n_big}/{distinct} 格"
    assert all(lim == w.PANEL_PAGE == 10000 for _, lim in calls)
    assert shapes == [False, True, True, True], f"第一页用 offset,之后用续读谓词:{shapes}"
    n_small = run(1000)
    assert n_small == distinct and len(calls) == 26, f"上限 1,000:要 10,000 只给 1,000 也必须读全,实际 {len(calls)} 次、{n_small}/{distinct}"
    print("  ✓ 上限 10,000:25,000 行 4 次请求;上限 1,000:26 次请求;两次读到的格子相同")


if __name__ == "__main__":
    print("── S-416 fetch_panel 分页 ──")
    test_reads_every_row_past_the_cap()
    test_a_higher_server_cap_means_fewer_pages_and_the_same_rows()
    print("\n✅ 2/2 passed")
