"""S-436 — CoinGecko /ohlc/range stamps each daily candle with its CLOSE time.

The candle for day D arrives stamped D+1 00:00 UTC. Reading the stamp as D labelled every
coingecko_pro_ohlc row a day late (CG(D) matched Binance(D-1) to 0.02%, 18/18 days).
"""
import asyncio
from datetime import datetime, timezone

from src.data.market import data_layer as dl


class _Resp:
    status_code = 200

    def __init__(self, payload):
        self._p = payload

    def json(self):
        return self._p

    def raise_for_status(self):
        return None


class _Client:
    def __init__(self, payload):
        self._p = payload

    async def get(self, *a, **k):
        return _Resp(self._p)


def _ms(y, m, d):
    return int(datetime(y, m, d, tzinfo=timezone.utc).timestamp() * 1000)


def test_candle_stamped_at_midnight_is_the_previous_day(monkeypatch):
    payload = [[_ms(2026, 9, 28), 1, 2, 0.5, 84417.0],
               [_ms(2026, 9, 29), 2, 3, 1.5, 84076.0]]
    monkeypatch.setattr(dl, "CG_API_KEY", "test")
    monkeypatch.setattr(dl, "_get_cg_client", lambda: _Client(payload))
    monkeypatch.setattr(dl, "_cache_get", lambda *a, **k: None)
    monkeypatch.setattr(dl, "_cache_set", lambda k, v: v)

    async def _none(*a, **k):
        return None
    monkeypatch.setattr(dl, "_redis_get", _none)
    monkeypatch.setattr(dl, "_redis_set", _none)
    out = asyncio.run(dl.get_cg_ohlc_range("bitcoin", 0, 1, strict=True))
    assert [r["trade_date"] for r in out] == ["2026-09-27", "2026-09-28"]
    assert out[-1]["close"] == 84076.0


def test_router_volume_uses_the_same_convention():
    import inspect
    from src.api.routers import ohlcv
    src = inspect.getsource(ohlcv)
    assert "timedelta(days=1)).date()" in src
