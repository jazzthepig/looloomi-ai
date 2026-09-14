"""Smoke test for A-21 vault NAV tick — pure math layer.

The async tick_vault_nav() needs Supabase + panel (network). This test
covers the deterministic math + state-validation portion of the tick,
which is where the actual business logic lives.

Tests:

  T1: positions_value: 3 longs + 1 short → correct sign per side
  T2: positions_value: empty positions → nav_usd=0, missing=[]
  T3: positions_value: missing price → missing=[sym] recorded (callable
      must surface, not fabricate per NAV_POLICY §3)
  T4: positions_value: rounding to 8 decimals (matches vault_nav_tick
      numeric column precision)
  T5: load_share_count: row with positive share_count → returns it
  T6: load_share_count: row missing → ValueError
  T7: load_share_count: NULL share_count → ValueError
  T8: load_share_count: share_count <= 0 → ValueError

The async force-tick endpoint and the Supabase writes are tested via
the actual /internal/vault-tick/{vault_id} curl after deploy — not here.
These tests are CI-portable: no DB, no secrets, no network.
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, "/Users/sbb/Projects/looloomi-ai")

from src.data.vault.positions import positions_value, load_share_count


def test_t1_long_short_sign():
    positions = [
        {"symbol": "USDC", "qty": 100_000, "side": "LONG"},
        {"symbol": "WETH", "qty": 50, "side": "LONG"},
        {"symbol": "WBTC", "qty": 1, "side": "LONG"},
        {"symbol": "ETH-PERP", "qty": 10, "side": "SHORT"},   # negative contribution
    ]
    prices = {"USDC": 1.0, "WETH": 3000.0, "WBTC": 60000.0,
              "ETH-PERP": 3005.0}
    out = positions_value(positions, prices)
    # USDC: 100k * 1 = 100k LONG
    # WETH: 50 * 3000 = 150k LONG
    # WBTC: 1 * 60000 = 60k LONG
    # ETH-PERP SHORT: -10 * 3005 = -30050
    # total = 100k + 150k + 60k - 30050 = 279,950
    print(f"  T1 nav_usd={out['nav_usd']} missing={out['missing_prices']}")
    assert abs(out["nav_usd"] - 279_950) < 1e-6
    assert out["missing_prices"] == []
    holdings_by_sym = {h["symbol"]: h for h in out["holdings"]}
    assert holdings_by_sym["USDC"]["value_usd"] == 100_000.0
    assert holdings_by_sym["ETH-PERP"]["value_usd"] == -30_050.0
    print("✓ T1: long + short positions → correct signed nav_usd")


def test_t2_empty_positions():
    out = positions_value([], {"USDC": 1.0})
    print(f"  T2 nav_usd={out['nav_usd']} holdings={out['holdings']}")
    assert out["nav_usd"] == 0.0
    assert out["holdings"] == []
    assert out["missing_prices"] == []
    print("✓ T2: empty positions → nav_usd=0, no fabrication")


def test_t3_missing_price_surfaced():
    """If a symbol has no current price, we MUST surface it, not skip."""
    positions = [
        {"symbol": "USDC", "qty": 1000, "side": "LONG"},
        {"symbol": "OBSCURE-TOKEN", "qty": 100, "side": "LONG"},
    ]
    prices = {"USDC": 1.0}     # OBSCURE-TOKEN missing
    out = positions_value(positions, prices)
    print(f"  T3 missing_prices={out['missing_prices']} nav_usd={out['nav_usd']}")
    assert "OBSCURE-TOKEN" in out["missing_prices"]
    # Partial nav is still computed (USDC) but caller must BLOCK on missing
    assert out["nav_usd"] == 1000.0   # USDC only
    assert len(out["holdings"]) == 1
    print("✓ T3: missing price surfaced (caller BLOCKs per NAV_POLICY §3)")


def test_t4_rounding_8_decimals():
    """All values rounded to 8 decimals (matches vault_nav_tick numeric)."""
    positions = [{"symbol": "WETH", "qty": 0.123456789012345,
                  "side": "LONG"}]
    prices = {"WETH": 3000.00000001}
    out = positions_value(positions, prices)
    print(f"  T4 nav_usd={out['nav_usd']}")
    # 0.123456789012345 * 3000.00000001 = 370.37036705...
    # Rounded to 8 decimals
    assert out["nav_usd"] == 370.37036704  # standard banker's rounding to 8
    # Verify it's stored at ≤ 8 decimal places
    assert len(str(out["nav_usd"]).split(".")[-1]) <= 8
    print("✓ T4: 8-decimal rounding (matches vault_nav_tick numeric column)")


def test_t5_share_count_normal():
    sc = load_share_count({"vault_id": "demo-vault", "share_count": 1000.0})
    print(f"  T5 share_count={sc}")
    assert sc == 1000.0
    print("✓ T5: positive share_count → returns float")


def test_t6_share_count_no_row():
    try:
        load_share_count(None)
        assert False, "should have raised"
    except ValueError as e:
        print(f"  T6 raised: {str(e)[:80]}")
        assert "查无此" in str(e) or "share_count" in str(e)
    print("✓ T6: missing vault_state row → ValueError")


def test_t7_share_count_null():
    try:
        load_share_count({"vault_id": "demo-vault", "share_count": None})
        assert False, "should have raised"
    except ValueError as e:
        print(f"  T7 raised: {str(e)[:80]}")
        assert "NULL" in str(e)
    print("✓ T7: NULL share_count → ValueError")


def test_t8_share_count_zero_or_negative():
    for bad in (0.0, -1.0, -100.5):
        try:
            load_share_count({"vault_id": "demo-vault", "share_count": bad})
            assert False, f"should have raised for share_count={bad}"
        except ValueError as e:
            print(f"  T8 raised for share_count={bad}: {str(e)[:60]}")
            assert "> 0" in str(e)
    print("✓ T8: share_count <= 0 → ValueError")


if __name__ == "__main__":
    print("=== A-21 vault NAV tick (pure-math layer) smoke ===\n")
    test_t1_long_short_sign()
    test_t2_empty_positions()
    test_t3_missing_price_surfaced()
    test_t4_rounding_8_decimals()
    test_t5_share_count_normal()
    test_t6_share_count_no_row()
    test_t7_share_count_null()
    test_t8_share_count_zero_or_negative()
    print(f"\n=== All A-21 vault tick math tests passed (8/8) ===")
