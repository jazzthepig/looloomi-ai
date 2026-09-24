"""S-416 — `fetch_panel` 必须读过 PostgREST 的 1000 行上限。

`PAGE = 10_000` 配 `if len(batch) < PAGE: break`:服务端每页只给 1000 行,
于是第一页就满足「比我要的少」,循环退出。实测 2026-09-24 读回 25 个标的 × 40 天,
止于 2025-11-12 —— `market_state_writer` 和 `panel_read` 的唯一读价路径一直在读一个旧切片。

这里用一个**每页最多给 1000 行**的假服务端,喂 2,500 行,断言三件事:
全部读到 · 读到空页才停 · 标的过滤真的下推到了查询里。
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SERVER_CAP = 1000


def test_reads_every_row_past_the_cap() -> None:
    from src.data.vector import market_state_writer as w

    rows = [{"symbol": f"S{i % 5}", "trade_date": f"2026-{1 + (i // 150) % 12:02d}-{1 + i % 28:02d}",
             "close": 1.0 + i, "volume": 1.0, "source": "coingecko_pro_ohlc"} for i in range(2500)]
    seen_params: list[dict] = []

    async def fake_get(path, params):
        seen_params.append(dict(params))
        off, lim = int(params["offset"]), int(params["limit"])
        batch = rows[off: off + min(lim, SERVER_CAP)]
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
    assert int(seen_params[-1]["offset"]) >= len(rows), "没有读到空页就停了"
    assert seen_params[0].get("symbol") == "in.(S1,S2)", f"标的过滤没下推:{seen_params[0]}"
    print(f"  ✓ 2,500 行在每页 {SERVER_CAP} 的上限下全部读到({len(seen_params)} 次请求,末页为空)")
    print("  ✓ 标的过滤下推到查询里")


if __name__ == "__main__":
    print("── S-416 fetch_panel 分页 ──")
    test_reads_every_row_past_the_cap()
    print("\n✅ 1/1 passed")
