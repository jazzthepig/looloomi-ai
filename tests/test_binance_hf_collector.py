"""S-509:Binance 小时线 + 永续资金费率续接。纯函数与翻页逻辑,不联网。"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.market import binance_hf_collector as hf  # noqa: E402
from src.data.market.source_policy import (  # noqa: E402
    MARKET_DATA, SourcePolicyError, assert_purpose_source,
)

H = 3_600_000
T0 = 1_786_000_000_000 - (1_786_000_000_000 % H)   # 整点


def _k(open_ms: int, close_px: float = 100.0) -> list:
    # [open, o, h, l, c, vol, close_time, quote_vol, trades, taker_buy_base, taker_buy_quote, ignore]
    return [open_ms, "99", "101", "98", str(close_px), "10", open_ms + H - 1, "1000", 42, "6", "600", "0"]


def test_hourly_rows_maps_taker_and_drops_the_unclosed_bar() -> None:
    rows = hf.hourly_rows("BTC", [_k(T0), _k(T0 + H)], now_ms=T0 + H + 5)
    assert len(rows) == 1, "收盘时刻 ≥ now 的那根不能写 —— 半根冒充整根"
    r = rows[0]
    assert r["ts"].startswith(hf._iso(T0)[:19]) and r["taker_buy_base"] == 6.0
    assert r["quote_volume"] == 1000.0 and r["trades"] == 42 and r["source"] == "binance_hist"


def test_funding_time_is_floored_to_the_hour_and_bad_rates_are_skipped() -> None:
    rows = hf.funding_rows("ETH", [
        {"fundingTime": T0 + 7, "fundingRate": "0.0001", "markPrice": ""},
        {"fundingTime": T0 + 8 * H, "fundingRate": "n/a"},
    ])
    assert len(rows) == 1, "读不出的费率要跳过,不能补 0"
    assert rows[0]["funding_time"] == hf._iso(T0), "毫秒尾数会在 PK 上造出重复行"
    assert rows[0]["mark_price"] is None and rows[0]["venue"] == "binance_perp"


def test_hourly_paging_stops_on_a_short_page_and_reports_pending_at_the_cap() -> None:
    calls: list[int] = []

    def fake(pages: int, full_last: bool):
        async def get_page(pair: str, start: int):
            assert pair == "BTCUSDT"
            calls.append(start)
            i = len(calls) - 1
            n = hf.PAGE if (i < pages - 1 or full_last) else 5
            return [_k(start + j * H) for j in range(n)]
        return get_page

    now = T0 + 10_000 * H
    rows, more = asyncio.run(hf.fetch_hourly(fake(2, False), "BTC", T0, now))
    assert len(calls) == 2 and not more and len(rows) == hf.PAGE + 5
    assert calls[1] == T0 + hf.PAGE * H, "下一页从上一页最后一根之后开始"

    calls.clear()
    rows, more = asyncio.run(hf.fetch_hourly(fake(99, True), "BTC", T0, now))
    assert len(calls) == hf.MAX_PAGES_HOURLY and more, "到页数上限还没补完 ⇒ pending,不是安静的一天"


def test_coverage_floor_refuses_partial_rounds() -> None:
    assert hf.coverage_ok(7, 10) and not hf.coverage_ok(6, 10) and not hf.coverage_ok(0, 0)


def test_funding_secondary_is_registered_but_still_needs_the_explicit_flag() -> None:
    assert_purpose_source(MARKET_DATA, "binance_perp", n_assets=len(hf.HF_SYMBOLS),
                          job="t", secondary_ok=True)
    with pytest.raises(SourcePolicyError):
        assert_purpose_source(MARKET_DATA, "binance_perp", n_assets=len(hf.HF_SYMBOLS), job="t")


def test_loop_is_scheduled_with_liveness_and_a_loop_attempt_record() -> None:
    main = (ROOT / "src/api/main.py").read_text(encoding="utf-8")
    assert "async def _binance_hf_loop" in main and "_start_binance_hf_loop" in main
    assert '_record_loop_attempt(\n                "_binance_hf_loop"' in main
    from src.api.liveness import LIVENESS_SLOS
    assert "_binance_hf_loop" in LIVENESS_SLOS


def test_collector_does_not_add_a_fetch_entrypoint() -> None:
    """取数入口只减不增(S-302):请求只经 data_layer,写入端自己不出外网。"""
    from scripts.loop_status import _HTTP_MARKERS, _PRICE_PRIMITIVES
    src = (ROOT / "src/data/market/binance_hf_collector.py").read_text(encoding="utf-8")
    assert not (any(k in src for k in _PRICE_PRIMITIVES) and any(m in src for m in _HTTP_MARKERS))
