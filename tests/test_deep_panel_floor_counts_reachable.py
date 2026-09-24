"""S-415 — deep panel 的覆盖率地板只数「能回答的」符号。

2026-09-23 实测:262 个符号里 123 个在 Binance 现货上不存在(永续命名、已下架、HL 独有名),
每一轮都回空,覆盖率被永久钉在 53%,70% 地板每轮拒绝写入 —— binance_hist 自 09-08 起一行没进。
hyperliquid_collector 在 S-204 修过一模一样的形状,这个文件没跟上。

三条:
1. 回空(下架)不算失败:139 活 + 123 回空 ⇒ 写入
2. 真故障仍然挡住:活的里面大面积报错 ⇒ 拒绝
3. 全体回空 ⇒ 拒绝(绝对地板),不能因为分母变 0 就放行
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _run(live: int, dead: int, broken: int) -> dict:
    from src.data.market import deep_panel_collector as dp
    import src.api.store as st
    from src.api.store_result import StoreResult

    syms = [f"L{i}" for i in range(live)] + [f"D{i}" for i in range(dead)] + [f"E{i}" for i in range(broken)]

    async def fake_fetch(s, days):
        if s.startswith("L"):
            return s, [{"symbol": s, "trade_date": "2026-09-22", "close": 1.0, "source": "binance_hist"}], None
        if s.startswith("D"):
            return s, [], "empty (delisted or unlisted pair?)"
        return s, [], "HTTPStatusError: 418"

    async def fake_up(table, rows, on_conflict):
        return StoreResult.ok_(value=True)

    async def no_frontier():
        return None

    old = (dp._fetch_one, st.supabase_upsert_table, dp._BATCH_PAUSE_S, dp._panel_frontier)
    dp._fetch_one, st.supabase_upsert_table, dp._BATCH_PAUSE_S, dp._panel_frontier = fake_fetch, fake_up, 0, no_frontier
    try:
        return asyncio.run(dp.collect_deep_panel(symbols=syms, days=14))
    finally:
        dp._fetch_one, st.supabase_upsert_table, dp._BATCH_PAUSE_S, dp._panel_frontier = old


def test_delisted_symbols_do_not_block_the_write() -> None:
    r = _run(live=139, dead=123, broken=0)
    assert r["written"] and r["ok"], r
    assert r["symbols_reachable"] == 139 and r["symbols_delisted"] == 123, r
    print("  ✓ 139 活 + 123 回空 ⇒ 写入;回空单独报告,不算失败")


def test_real_errors_still_block() -> None:
    r = _run(live=100, dead=50, broken=80)
    assert not r["written"] and r.get("refused"), r
    print("  ✓ 活的里面 44% 报错 ⇒ 拒绝写入")


def test_everything_empty_is_refused_not_passed() -> None:
    r = _run(live=5, dead=257, broken=0)
    assert not r["written"], "分母只剩 5 个时 100% 成功率依然是空的 —— 绝对地板必须挡住"
    print("  ✓ 只剩 5 个活符号 ⇒ 拒绝(绝对地板)")


if __name__ == "__main__":
    print("── S-415 deep panel 地板分母 ──")
    test_delisted_symbols_do_not_block_the_write()
    test_real_errors_still_block()
    test_everything_empty_is_refused_not_passed()
    print("\n✅ 3/3 passed")
