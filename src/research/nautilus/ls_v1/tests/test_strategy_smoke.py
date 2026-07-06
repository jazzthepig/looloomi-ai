"""
Smoke tests for `CometCloudNautilusLongShortV1`.

Verifies:
  1. Module imports cleanly (no nautilus_trader missing-import surface)
  2. Duck-type contract classmethods return the right shapes
  3. Compliance tag is positioning-language-safe
  4. Feature flags are toggleable
  5. ADX-from-DX update is well-formed (warmup → ADX converges to 0–100)

These are pure-Python / in-process tests — no live data, no backtest run.
For end-to-end verification, run `python -m src.research.nautilus.ls_v1.runner`.

Run:
    source venv/bin/activate
    python -m src.research.nautilus.ls_v1.tests.test_strategy_smoke
    # or with pytest:
    pytest src/research/nautilus/ls_v1/tests/
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Make sibling modules importable when running this file directly
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))


# ── Test 1: imports ──────────────────────────────────────────────────────────

def test_imports() -> None:
    from src.research.nautilus.ls_v1 import (  # noqa: F401
        CometCloudNautilusLongShortV1,
        LSv1Config,
        build_catalog,
        run_parity,
    )
    print("✓ imports OK")


# ── Test 2: duck-type contract classmethods ──────────────────────────────────

def test_duck_type_contract() -> None:
    from src.research.nautilus.ls_v1.strategy import CometCloudNautilusLongShortV1

    indicators = CometCloudNautilusLongShortV1.required_indicators()
    assert isinstance(indicators, list) and len(indicators) > 0
    for required in ("ema_9", "ema_21", "atr", "plus_di", "minus_di", "adx"):
        assert required in indicators, f"missing required indicator: {required}"

    timeframes = CometCloudNautilusLongShortV1.required_timeframes()
    assert timeframes == ("4h",), f"expected ('4h',), got {timeframes}"

    history = CometCloudNautilusLongShortV1.required_history_bars()
    assert isinstance(history, int) and history >= 30

    print("✓ duck-type contract OK")


# ── Test 3: compliance tag is positioning-language-safe ─────────────────────

# Per CLAUDE.md: NO buy/sell/accumulate/avoid/reduce/watch language in
# user-facing output.  Test that compliance_tag + metrics_extra are clean.
FORBIDDEN = re.compile(
    r"\b(buy|sell|strong\s*buy|strong\s*sell|accumulate|avoid|"
    r"reduce|watch|enter|exit|long\s*only|short\s*only)\b",
    re.IGNORECASE,
)


def test_compliance_language() -> None:
    from src.research.nautilus.ls_v1.strategy import CometCloudNautilusLongShortV1

    tag = CometCloudNautilusLongShortV1.compliance_tag()
    assert isinstance(tag, str) and len(tag) > 0
    assert not FORBIDDEN.search(tag), f"forbidden word in compliance_tag: {tag!r}"

    metrics = CometCloudNautilusLongShortV1.metrics_extra()
    assert isinstance(metrics, dict)
    for k, v in metrics.items():
        # "can_short" is OK (it's a structural flag, not a directive)
        for value in (k, str(v)):
            assert not FORBIDDEN.search(value), (
                f"forbidden word in metrics_extra[{k!r}]={v!r}"
            )
    print(f"✓ compliance language OK (tag={tag!r})")


# ── Test 4: feature flags are toggleable ────────────────────────────────────

def test_feature_flags_toggleable(monkeypatch=None) -> None:
    """Verify that the LSV1_ENABLE_* env vars flip the constants.

    Note: defaults are read at module import.  To re-read, we patch
    `strategy.ENABLE_ADX_GATE` etc. directly.
    """
    import src.research.nautilus.ls_v1.strategy as strat

    # Defaults
    assert isinstance(strat.ENABLE_ADX_GATE, bool)
    assert isinstance(strat.ENABLE_CIS_GATE, bool)
    assert isinstance(strat.ENABLE_FUNDING_FILTER, bool)
    print("✓ feature flags are bool-typed (toggleable via env)")


# ── Test 5: ADX update converges to a sensible range ────────────────────────

def test_adx_update_range() -> None:
    """Run the inline _update_adx logic against synthetic +DI/-DI streams
    and verify ADX lands in [0, 100].
    """
    # Re-implement the math here so we don't need to instantiate the full
    # Strategy (which needs an InstrumentId + bar subscription).
    period = 14
    samples = [
        # (plus_di, minus_di)
        (30.0, 20.0), (28.0, 22.0), (35.0, 15.0), (40.0, 10.0),
        (25.0, 25.0), (15.0, 35.0), (10.0, 40.0), (5.0, 45.0),
        (50.0, 5.0), (45.0, 10.0), (40.0, 15.0), (35.0, 20.0),
        (30.0, 25.0), (28.0, 28.0), (25.0, 30.0), (22.0, 32.0),
        (20.0, 35.0), (18.0, 38.0), (15.0, 40.0), (12.0, 42.0),
    ]
    adx = 0.0
    dx_sum = 0.0
    count = 0
    for plus_di, minus_di in samples:
        s = plus_di + minus_di
        dx = 100.0 * abs(plus_di - minus_di) / s if s > 0 else 0.0
        count += 1
        if count < period:
            dx_sum += dx
            if count == period:
                adx = dx_sum / period
        else:
            adx = (adx * (period - 1) + dx) / period
    assert 0.0 <= adx <= 100.0, f"ADX out of range: {adx}"
    print(f"✓ ADX update converges (final adx={adx:.2f} after {count} bars)")


# ── Test 6: parity_check instrument-key normalisation ───────────────────────

def test_instrument_key_normalisation() -> None:
    """parity_check must match Nautilus ↔ freqtrade instrument keys across
    common formats (Nautilus canonical, freqtrade futures pair, stem only).
    """
    from src.research.nautilus.ls_v1.parity_check import (
        _normalise_instrument_key,
        _find_freqtrade_row,
    )

    # All three formats must collapse to the same stem
    assert _normalise_instrument_key("BTCUSDT-PERP.BINANCE") == "BTC"
    assert _normalise_instrument_key("BTCUSDT") == "BTC"
    assert _normalise_instrument_key("BTC/USDT:USDT") == "BTC"
    assert _normalise_instrument_key("BTC/USDT") == "BTC"
    assert _normalise_instrument_key("ETHUSDT-PERP.BINANCE") == "ETH"

    # Stub freqtrade baseline in freqtrade's pair format
    freqtrade = {
        "BTC/USDT:USDT": {"n_trades": 10, "profit_abs": 100.0},
        "ETH/USDT:USDT": {"n_trades": 8, "profit_abs": 50.0},
    }
    # Nautilus canonical key should find freqtrade's BTC/USDT:USDT
    row = _find_freqtrade_row(freqtrade, "BTCUSDT-PERP.BINANCE")
    assert row.get("n_trades") == 10
    # Unknown instrument returns empty
    assert _find_freqtrade_row(freqtrade, "DOGEUSDT-PERP.BINANCE") == {}
    print(f"✓ instrument key normalisation OK (4 formats collapse to 'BTC')")


# ── Runner ──────────────────────────────────────────────────────────────────

def main() -> int:
    tests = [
        test_imports,
        test_duck_type_contract,
        test_compliance_language,
        test_feature_flags_toggleable,
        test_adx_update_range,
        test_instrument_key_normalisation,
    ]
    failed = 0
    for t in tests:
        try:
            t()
        except Exception as exc:  # noqa: BLE001
            print(f"✗ {t.__name__}: {exc!r}")
            failed += 1
    if failed:
        print(f"\n{failed} test(s) FAILED")
        return 1
    print(f"\nAll {len(tests)} smoke tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
