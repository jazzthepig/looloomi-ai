"""A Binance 451 must surface as a named error, not `string index out of range` (S-607 follow-up)."""
import pytest

from src.research.strategies.causal_positioning import _binance_rows


class _R:
    def __init__(self, status, body):
        self.status_code, self._b = status, body

    def json(self):
        return self._b


def test_451_object_body_raises_with_status():
    with pytest.raises(RuntimeError, match="HTTP 451"):
        _binance_rows(_R(451, {"code": 0, "msg": "restricted"}), "klines", "BTCUSDT")


def test_200_object_body_raises_not_iterates():
    with pytest.raises(RuntimeError, match="expected a list"):
        _binance_rows(_R(200, {"code": -1121}), "klines", "BTCUSDT")


def test_200_list_passes_through():
    rows = [[1, 2, 3, 4, 5]]
    assert _binance_rows(_R(200, rows), "klines", "BTCUSDT") is rows
