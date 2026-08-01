"""
Venue consolidation — regression suite.

Every test here is a production defect found on 2026-08-01, frozen so it cannot
return silently. The HYPE case ran for months precisely because nothing asserted
on it: the fix in e321053 patched the live feed and added a *completeness*
check, which passes happily on a populated-but-wrong number.

Completeness asks "is there a value". These tests ask "is it the right asset".
No network — all pure-function assertions on the consolidation math.
"""
import pytest

from src.data.venues.consolidator import (
    VenueQuote,
    consolidate,
    volume_weighted_median,
    MIN_VENUES_FOR_CONSENSUS,
    OUTLIER_REJECT_RATIO,
)
from src.data.venues.registry import (
    NOT_LISTED,
    SYMBOL_MAP,
    VENUES,
    registry_age_days,
    unverified_pairs,
    venue_symbol,
    REVIEW_CADENCE_DAYS,
)


# ── The collision that started this ───────────────────────────────────────────

def test_hype_never_maps_to_binance_spot():
    """HYPERUSDT on Binance spot is Hyperlane ($0.0558), not Hyperliquid
    ($52.32). This mapping cost us a +256% run. It must stay verified-absent."""
    assert SYMBOL_MAP["HYPE"]["binance_spot"] == NOT_LISTED
    assert venue_symbol("HYPE", "binance_spot") is None


def test_hype_has_real_perp_venues():
    """The asset does trade — on perps. fapi and the native venue both list it."""
    assert venue_symbol("HYPE", "binance_perp") == "HYPEUSDT"
    assert venue_symbol("HYPE", "hyperliquid") == "HYPE"


def test_wrong_asset_mapping_is_rejected_not_averaged():
    """The 937x case, replayed. A venue pointing at the wrong asset must be
    DROPPED from consensus — not averaged in, which would have poisoned the
    price by ~1/3 and left no trace."""
    quotes = [
        VenueQuote("binance_perp", "perp", 52.215, 440_776_876, 248_099_084, 0.00005),
        VenueQuote("hyperliquid", "perp", 52.179, 314_380_583, 1_174_350_988, 0.0000125),
        VenueQuote("bybit_perp", "perp", 52.201, 178_204_752, 201_211_810, 0.0001),
        VenueQuote("binance_spot", "spot", 0.0558, 592_562, 0.0, None),   # Hyperlane
    ]
    r = consolidate("HYPE", quotes)
    assert r is not None
    assert "binance_spot" in r.venues_rejected
    assert r.price == pytest.approx(52.2, abs=0.1)
    assert r.degraded is True
    assert "outlier" in r.degraded_reason


def test_real_hype_snapshot_consolidates_to_measured_values():
    """Live numbers taken 2026-08-01. Single-venue sourcing undercounts volume
    by 2.1x-5.2x and OI by up to 6.5x; the consolidated view is the sum."""
    quotes = [
        VenueQuote("binance_perp", "perp", 52.215, 440_776_876, 248_099_084, 0.00005),
        VenueQuote("hyperliquid", "perp", 52.179, 314_380_583, 1_174_350_988, 0.0000125),
        VenueQuote("bybit_perp", "perp", 52.201, 178_204_752, 201_211_810, 0.0001),
    ]
    r = consolidate("HYPE", quotes)
    assert r.volume_24h_usd == pytest.approx(933_362_211, rel=1e-6)
    assert r.open_interest_usd == pytest.approx(1_623_661_882, rel=1e-6)
    assert r.price_dispersion < 0.001          # 7bp — arbitrage converges price
    assert r.degraded is False
    assert r.confidence > 0.9


# ── Aggregation rules differ by quantity ──────────────────────────────────────

def test_funding_is_never_averaged():
    """The 8x cross-venue funding spread is the net-positioning signal. An
    average would destroy it; a single venue would never see it."""
    quotes = [
        VenueQuote("binance_perp", "perp", 52.2, 440e6, 248e6, 0.00005),
        VenueQuote("hyperliquid", "perp", 52.2, 314e6, 1174e6, 0.0000125),
        VenueQuote("bybit_perp", "perp", 52.2, 178e6, 201e6, 0.0001),
    ]
    r = consolidate("HYPE", quotes)
    assert len(r.funding_by_venue) == 3
    assert r.funding_spread == pytest.approx(0.0001 - 0.0000125)


def test_spot_volume_counts_but_spot_oi_does_not():
    """Spot has no open interest. Adding a spot venue must not inflate OI."""
    quotes = [
        VenueQuote("binance_perp", "perp", 100.0, 1_000, 5_000, 0.0001),
        VenueQuote("hyperliquid", "perp", 100.0, 1_000, 5_000, 0.0001),
        VenueQuote("binance_spot", "spot", 100.0, 1_000, 0.0, None),
    ]
    r = consolidate("X", quotes)
    assert r.open_interest_usd == 10_000
    assert r.volume_24h_usd == 3_000


def test_oi_concentration_detects_native_venue_dominance():
    """Hyperliquid holds 72% of HYPE open interest on 34% of volume. Venue
    composition is a fact about the holder base, not plumbing noise."""
    quotes = [
        VenueQuote("binance_perp", "perp", 52.2, 440e6, 248e6, 0.00005),
        VenueQuote("hyperliquid", "perp", 52.2, 314e6, 1174e6, 0.0000125),
        VenueQuote("bybit_perp", "perp", 52.2, 178e6, 201e6, 0.0001),
    ]
    r = consolidate("HYPE", quotes)
    assert r.oi_concentration > 0.5           # HHI — one venue dominates
    hl = next(q for q in quotes if q.venue == "hyperliquid")
    bn = next(q for q in quotes if q.venue == "binance_perp")
    assert hl.turnover < 0.4 and bn.turnover > 1.5   # 6.6x behavioural gap


# ── Volume-weighted median (CME CF / Kaiko recipe) ────────────────────────────

def test_vwm_is_manipulation_resistant():
    """A tiny venue printing a wild price must not move the consensus."""
    assert volume_weighted_median([(100, 1e9), (101, 1e9), (500, 1)]) == pytest.approx(101)


def test_vwm_ignores_trade_fragmentation():
    """CME's stated property: splitting one large trade into parts must not
    change the result."""
    whole = volume_weighted_median([(100, 10), (102, 90)])
    split = volume_weighted_median([(100, 10), (102, 45), (102, 45)])
    assert whole == split


def test_vwm_single_venue_and_zero_weights():
    assert volume_weighted_median([(42.0, 0)]) == 42.0
    assert volume_weighted_median([(10, 0), (20, 0), (30, 0)]) == 20.0
    with pytest.raises(ValueError):
        volume_weighted_median([])


# ── Degradation: never fabricate, always flag (hard rule #9) ──────────────────

def test_zero_venues_returns_none_never_a_number():
    assert consolidate("X", []) is None
    assert consolidate("X", [VenueQuote("v", "perp", 0.0)]) is None


def test_thin_coverage_is_flagged_not_hidden():
    r = consolidate("X", [VenueQuote("binance_perp", "perp", 100.0, 1e6, 1e6, 0.0)])
    assert r is not None and r.degraded is True
    assert r.confidence < 0.5
    assert "venue" in r.degraded_reason


def test_two_disagreeing_venues_are_not_arbitrated():
    """With two venues there is no majority. Guessing which is right is how a
    wrong number becomes authoritative — flag instead."""
    r = consolidate("X", [
        VenueQuote("binance_perp", "perp", 100.0, 1e6, 1e6, 0.0),
        VenueQuote("bybit_perp", "perp", 200.0, 1e6, 1e6, 0.0),
    ])
    assert r.venues_rejected == []
    assert r.degraded is True
    assert r.confidence < 0.3


def test_failed_venues_are_reported_not_swallowed():
    r = consolidate("X", [
        VenueQuote("binance_perp", "perp", 100.0, 1e6, 1e6, 0.0),
        VenueQuote("hyperliquid", "perp", 100.0, 1e6, 1e6, 0.0),
        VenueQuote("bybit_perp", "perp", 100.0, 1e6, 1e6, 0.0),
    ], failed=["okx_perp"])
    assert r.venues_failed == ["okx_perp"]
    assert r.degraded is False          # a failed venue is not a bad number


def test_confidence_tracks_dispersion_not_a_constant():
    """CIS shipped confidence as a hardcoded 0.7/1.0. Confidence must be earned
    from cross-venue agreement (Pyth's principle), not asserted."""
    tight = consolidate("X", [
        VenueQuote("binance_perp", "perp", 100.00, 1e6, 1e6, 0.0),
        VenueQuote("hyperliquid", "perp", 100.02, 1e6, 1e6, 0.0),
        VenueQuote("bybit_perp", "perp", 100.01, 1e6, 1e6, 0.0),
    ])
    loose = consolidate("X", [
        VenueQuote("binance_perp", "perp", 100.0, 1e6, 1e6, 0.0),
        VenueQuote("hyperliquid", "perp", 101.5, 1e6, 1e6, 0.0),
        VenueQuote("bybit_perp", "perp", 101.0, 1e6, 1e6, 0.0),
    ])
    assert tight.confidence > loose.confidence
    assert tight.confidence > 0.9


# ── Registry hygiene: the "set once, never re-checked" class ──────────────────

def test_every_universe_asset_is_explicit_on_every_venue():
    """No implicit gaps. An unverified (asset, venue) pair is where the next
    ticker collision comes from — a future refactor templates a symbol and
    silently points at the wrong asset."""
    gaps = unverified_pairs(list(SYMBOL_MAP.keys()))
    assert gaps == [], f"unverified asset/venue pairs: {gaps}"


def test_no_symbol_map_entry_targets_an_unknown_venue():
    for asset, row in SYMBOL_MAP.items():
        for vname in row:
            assert vname in VENUES, f"{asset} references unknown venue {vname}"


def test_registry_review_is_not_stale():
    """The three defects behind this module were all 'set once, never
    re-checked'. A registry without an enforced review date reproduces them."""
    age = registry_age_days()
    assert age <= REVIEW_CADENCE_DAYS, (
        f"venue registry last reviewed {age}d ago (cadence {REVIEW_CADENCE_DAYS}d) — "
        "re-verify symbol mappings and venue eligibility, then bump REVIEWED_AT"
    )


if __name__ == "__main__":
    # Runnable without pytest so scripts/preflight.sh can gate on it the same
    # way it gates the other discipline suites (`python3 -m tests.test_*`).
    import sys as _sys
    import traceback as _tb

    _fns = [(n, f) for n, f in sorted(globals().items())
            if n.startswith("test_") and callable(f)]
    _failed = 0
    for _n, _f in _fns:
        try:
            _f()
        except Exception:                                    # noqa: BLE001
            _failed += 1
            print(f"  ✗ {_n}")
            _tb.print_exc()
    if _failed:
        print(f"  ✗ venue consolidation: {_failed}/{len(_fns)} FAILED")
        _sys.exit(1)
    print(f"  ✓ venue consolidation ({len(_fns)} checks) — "
          "wrong-asset mappings rejected, no fabrication, registry explicit")
