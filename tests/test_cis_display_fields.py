"""TradFi size fields on the CIS universe surface (src/data/cis/display_fields.py)."""
from src.data.cis.display_fields import apply_size_fix


def _rows():
    return [
        {"symbol": "NVDA", "asset_class": "US Equity", "price": 200.0, "market_cap": 554e9, "volume_24h": 80e6},
        {"symbol": "SPY", "asset_class": "US Equity", "price": 700.0, "market_cap": 660e9, "volume_24h": 30e6},
        {"symbol": "FXI", "asset_class": "FX", "price": 30.0, "market_cap": 13e9, "volume_24h": 10e6},
        {"symbol": "BTC", "asset_class": "L1", "price": 80000.0, "market_cap": 1.6e12, "volume_24h": 1e9},
    ]


def test_volume_becomes_dollars_and_single_stock_mcap_uses_filed_shares():
    rows = _rows()
    n = apply_size_fix(rows, {"NVDA": 24.1e9})
    nvda, spy, fxi, btc = rows
    assert nvda["volume_24h"] == 80e6 * 200 and nvda["volume_24h_shares"] == 80e6
    assert nvda["market_cap"] == 24.1e9 * 200 and nvda["market_cap_reported"] == 554e9
    assert spy["market_cap"] == 660e9 and spy["market_cap_basis"] == "as_reported"   # ETF: no share count → as reported
    assert fxi["asset_class"] == "EM Equity" and fxi["asset_class_reported"] == "FX"
    assert btc["volume_24h"] == 1e9 and "volume_basis" not in btc                      # crypto untouched
    assert n == 3


def test_idempotent_on_a_cached_payload():
    rows = _rows()
    apply_size_fix(rows, {"NVDA": 24.1e9})
    apply_size_fix(rows, {"NVDA": 24.1e9})          # the universe payload is cached; a second pass must not re-multiply
    assert rows[0]["volume_24h"] == 80e6 * 200
    assert rows[0]["market_cap"] == 24.1e9 * 200
