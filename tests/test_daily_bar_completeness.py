"""S-644(2026-10-21):binance_hist 只放已收盘的 UTC 日;读它做决定的三条循环在固定的 UTC 时刻跑。

发现:`_deep_panel_loop` 在 22:59 UTC 跑了一轮,把 Binance 还没收盘的 10-20 日线(少最后一小时)写进了 binance_hist,
要等 24 小时后的下一轮才会被覆盖;R-v2 的前向票与 ① 在这一天里读到的是半根 K 线。三条日循环都是「启动 + N 秒,
然后每 24 小时」,于是每次部署都把它们挪到一天里不同的时刻 —— 执行器拿到计划的时间也跟着漂。
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _kline(day: datetime, close: float) -> dict:
    return {"time": int(day.timestamp() * 1000), "open": close, "high": close, "low": close, "close": close,
            "volume": 1.0}


def test_the_unclosed_candle_of_today_is_never_written(monkeypatch):
    import src.data.market.data_layer as dl
    from src.data.market import deep_panel_collector as dpc
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    kl = [_kline(today - timedelta(days=2), 1.0), _kline(today - timedelta(days=1), 2.0), _kline(today, 3.0)]

    async def fake(pair, interval, months=1):
        return kl
    monkeypatch.setattr(dl, "get_klines_binance", fake)
    sym, rows, err = asyncio.run(dpc._fetch_one("BTC", 14))
    assert err is None
    days = [r["trade_date"] for r in rows]
    assert days == [(today - timedelta(days=2)).date().isoformat(), (today - timedelta(days=1)).date().isoformat()]
    assert all(r["close"] != 3.0 for r in rows), "今天这根(还没收盘)不能进 binance_hist"


def _loop_body(src: str, name: str) -> str:
    return src.split(f"async def {name}", 1)[1].split("@app.on_event", 1)[0]


def test_the_daily_loops_run_at_fixed_utc_times_in_dependency_order():
    src = (ROOT / "src" / "api" / "main.py").read_text(encoding="utf-8")
    deep, style, tickets = (_loop_body(src, n) for n in ("_deep_panel_loop", "_style_pit_loop", "_r_tickets_paper_loop"))
    # 深盘 00:10 → 风格指数 00:30 → R-v2 每小时第 45 分(第一次 00:45)。不再「上一轮 + 24 小时」。
    assert "await _sleep_until_utc(0, 10)" in deep and "sleep(24 * 3600)" not in deep
    assert "await _sleep_until_utc(0, 30)" in style and "sleep(24 * 3600)" not in style
    assert ", 45)" in tickets and "_asyncio.sleep(3600)" not in tickets
