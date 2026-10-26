"""2026-10-26:get_cg_derivatives 从 03-22 起读 `base`,而 CoinGecko /derivatives 的行没有这个字段 ⇒ 每次 0 个资产。
字段是 index_id;funding_rate 是百分数(Binance 默认 0.01 = 0.01%/8h)。"""
import asyncio

import src.data.market.data_layer as dl


class _Resp:
    def __init__(self, rows):
        self._rows = rows

    def raise_for_status(self):
        return None

    def json(self):
        return self._rows


class _Client:
    def __init__(self, rows):
        self.rows = rows

    async def get(self, *a, **k):
        return _Resp(self.rows)


ROWS = [  # 字段与 10-26 实取的一行一致(没有 base)
    {"market": "Binance (Futures)", "symbol": "NEARUSDT", "index_id": "NEAR", "price": "4.46", "contract_type": "perpetual",
     "funding_rate": 0.01, "open_interest": 200_000_000.0, "price_percentage_change_24h": 0.2},
    {"market": "Bybit (Futures)", "symbol": "NEARUSDT", "index_id": "NEAR", "price": "4.46", "contract_type": "perpetual",
     "funding_rate": -0.01, "open_interest": 100_000_000.0, "price_percentage_change_24h": 0.2},
    {"market": "X", "symbol": "NEAR-27DEC", "index_id": "NEAR", "price": "4.5", "contract_type": "futures",
     "funding_rate": 5.0, "open_interest": 1e9},
    {"market": "X", "symbol": "FOOUSDT", "index_id": "FOO", "price": "1", "contract_type": "perpetual",
     "funding_rate": 0.01, "open_interest": 1e6},
]


def test_parses_index_id_perpetuals_and_converts_percent(monkeypatch):
    monkeypatch.setattr(dl, "CG_API_KEY", "x")
    monkeypatch.setattr(dl, "_get_cg_client", lambda: _Client(ROWS))
    monkeypatch.setattr(dl, "_cache_get", lambda *a, **k: None)

    async def _none(*a, **k):
        return None
    monkeypatch.setattr(dl, "_redis_get", _none)
    monkeypatch.setattr(dl, "_redis_set", _none)
    out = asyncio.run(dl.get_cg_derivatives())
    by = {r["symbol"]: r for r in out}
    assert set(by) == {"NEAR"}, "dated futures and names outside the list are skipped"
    near = by["NEAR"]
    assert near["open_interest_usd"] == 300_000_000
    # OI 加权:(0.0001·2e8 − 0.0001·1e8) / 3e8 —— 百分数 ÷ 100 成小数
    assert abs(near["funding_rate"] - 0.0001 / 3) < 1e-6          # 输出四舍五入到 6 位
    assert near["funding_signal"] == "neutral" and near["price"] == 4.46
