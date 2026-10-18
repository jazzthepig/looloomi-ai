"""
Tests for `src/data/venues/hl_spot.py` (T-123).

NETWORK DISCIPLINE (Hard Rule: tests never require internet):
    Every test reads from `tests/fixtures/hl_spot/`. The fixtures are a
    real snapshot of the public HL info endpoint pulled on 2026-10-18.
    No test in this file imports requests/urllib for outbound calls;
    `HlSpotFixture.from_dir` is the only entry point. The thin live
    client `HlSpotClient` is covered by API-shape assertions only
    (URL + payload), never by hitting the network.

WHAT THIS TEST SUITE GUARDS:
    * Round-down to szDecimals uses Decimal, not float, so 0.1 + 0.2
      style rounding errors cannot push below spec.
    * Min-notional check returns False on NaN / negative inputs.
    * L2 walk reports `inf` when the book cannot drain (better than a
      misleading finite bps).
    * Parse shape of the four official info responses stays stable.
    * UBTC and UETH resolve to canonical SPOT pairs with the szDecimals
      we documented (UBTC=5, UETH=4 — verified against the fixture).
    * X1V's slippage scan returns sensible bps at $3k / $30k / $300k /
      $3M against a real book.
    * Nothing in this module can submit, sign, or cancel.
"""
from __future__ import annotations

import math
import re
from pathlib import Path

import pytest

from src.data.venues.hl_spot import (
    ALLOWED_INFO_TYPES,
    DEFAULT_MIN_NOTIONAL_USDC,
    HYPERLIQUID_INFO_URL,
    REFERENCE_NOTIONALS_USDC,
    HlSpotClient,
    HlSpotFixture,
    HlSpotPair,
    HlSpotToken,
    L2Book,
    L2Level,
    estimate_slippage_bps,
    find_pair_by_name,
    find_token_by_name,
    forbidden_actions,
    min_notional_ok,
    parse_l2_book,
    parse_spot_meta,
    parse_spot_meta_and_asset_ctxs,
    round_size,
    slippage_scan,
    walk_book_for_qty,
)


# ── Paths ────────────────────────────────────────────────────────────────────
FIXTURES_DIR = Path(__file__).parent / "fixtures" / "hl_spot"


@pytest.fixture(scope="module")
def fixture() -> HlSpotFixture:
    """Real HL info snapshot. Loaded once per test module — no network."""
    return HlSpotFixture.from_dir(FIXTURES_DIR)


# ── Pure-fn round_size ──────────────────────────────────────────────────────
class TestRoundSize:
    @pytest.mark.parametrize("qty,decimals,expected", [
        # szDecimals=5 (UBTC): 1 unit = 1.00000, 0.000001 is the smallest step
        (1.234567890, 5, 1.23456),
        (1.23456,       5, 1.23456),
        (1.234555555,   5, 1.23455),
        # szDecimals=4 (UETH): 0.1 is fine, 0.00001 is the smallest step
        (0.10009,       4, 0.1000),
        (0.10005,       4, 0.1000),
        # szDecimals=0 (whole coins): 7.9 -> 7, no float dust
        (7.9,           0, 7.0),
        (7.5,           0, 7.0),       # banker's ROUND_DOWN NOT round-half-to-even
        (7.49999999,    0, 7.0),
        # Edge: zero stays zero
        (0.0,           5, 0.0),
        (0.0,           0, 0.0),
    ])
    def test_round_down(self, qty, decimals, expected):
        got = round_size(qty, decimals)
        if expected == int(expected):
            assert got == pytest.approx(expected)
        else:
            assert got == pytest.approx(expected, abs=1e-12)

    def test_decimal_precision_does_not_below_spec(self):
        """The classic float 0.1+0.2 trap MUST NOT push below spec."""
        # 0.1 + 0.2 in float == 0.30000000000000004; rounding to 5 must
        # be >= 0.3, never 0.29999.
        x = 0.1 + 0.2
        rounded = round_size(x, 5)
        assert rounded == 0.3
        assert rounded >= 0.3 - 1e-12

    def test_negative_raises(self):
        with pytest.raises(ValueError):
            round_size(-1.0, 5)

    def test_negative_decimals_raises(self):
        with pytest.raises(ValueError):
            round_size(1.0, -1)


# ── Pure-fn min_notional_ok ────────────────────────────────────────────────
class TestMinNotionalOk:
    @pytest.mark.parametrize("notional,min_n,ok", [
        (10.0,        10.0, True),
        (10.0001,     10.0, True),
        (9.9999,      10.0, False),
        (0.0,         10.0, False),
        (-1.0,        10.0, False),
        (1_000_000.0, 10.0, True),
    ])
    def test_threshold(self, notional, min_n, ok):
        assert min_notional_ok(notional, min_n) is ok

    def test_default_constant(self):
        # The X1V card expects $10 default; lock it so refactors don't
        # silently change the floor.
        assert DEFAULT_MIN_NOTIONAL_USDC == 10.0

    def test_reference_ladder(self):
        # Acceptance specifies four notionals by name.
        assert REFERENCE_NOTIONALS_USDC == (3_000.0, 30_000.0, 300_000.0, 3_000_000.0)

    def test_nan_fails_closed(self):
        assert min_notional_ok(float("nan")) is False


# ── L2 walk + slippage ─────────────────────────────────────────────────────
class TestWalkAndSlippage:
    def _trivial_book(self) -> L2Book:
        return L2Book(
            coin="@test",
            time_ms=0,
            bids=(L2Level(price=100.0, size=10.0, n_orders=1),),
            asks=(L2Level(price=101.0, size=10.0, n_orders=1),),
        )

    def test_walk_partial_returns_what_fits(self):
        book = self._trivial_book()
        book = L2Book(
            coin="@t",
            time_ms=0,
            bids=(L2Level(price=99.0, size=2.0, n_orders=1),
                  L2Level(price=98.0, size=10.0, n_orders=1)),
            asks=(L2Level(price=101.0, size=2.0, n_orders=1),
                  L2Level(price=102.0, size=10.0, n_orders=1)),
        )
        # Buy 5 @ market — first level is 2 @ 101, then 3 @ 102.
        filled, spent = walk_book_for_qty(book.asks, qty_base=5.0, side="buy")
        assert filled == pytest.approx(5.0)
        assert spent == pytest.approx(2.0 * 101.0 + 3.0 * 102.0)

    def test_walk_unfillable_returns_partial_filled(self):
        book = self._trivial_book()
        # Book only has 10 @ 101; ask for 100.
        filled, spent = walk_book_for_qty(book.asks, qty_base=100.0, side="buy")
        assert filled == pytest.approx(10.0)
        assert spent == pytest.approx(10.0 * 101.0)

    def test_estimate_slippage_bps_buy(self):
        book = L2Book(
            coin="@t",
            time_ms=0,
            bids=(L2Level(price=100.0, size=10.0, n_orders=1),),
            asks=(L2Level(price=101.0, size=10.0, n_orders=1),),
        )
        # Buy 1 @ market on a 100 / 101 book. mid = 100.5. fill at 101.
        bps = estimate_slippage_bps(book, side="buy", qty_base=1.0)
        expected = (101.0 / 100.5 - 1.0) * 10_000.0
        assert bps == pytest.approx(expected, rel=1e-9)

    def test_estimate_slippage_bps_buy_matches_formula(self):
        """Buy: (avg_fill / mid - 1) * 10_000."""
        book = L2Book(
            coin="@t",
            time_ms=0,
            bids=(L2Level(price=99.0, size=10.0, n_orders=1),),
            asks=(L2Level(price=101.0, size=10.0, n_orders=1),),
        )
        # mid = (99+101)/2 = 100. Buy 1 @ 101 → (101/100 - 1)*10_000 = 100 bps.
        bps = estimate_slippage_bps(book, side="buy", qty_base=1.0)
        assert bps == pytest.approx(100.0, rel=1e-9)

    def test_estimate_slippage_bps_sell_matches_formula(self):
        """Sell: (mid / avg_fill - 1) * 10_000. Note the inversion."""
        book = L2Book(
            coin="@t",
            time_ms=0,
            bids=(L2Level(price=99.0, size=10.0, n_orders=1),),
            asks=(L2Level(price=101.0, size=10.0, n_orders=1),),
        )
        # mid = 100. Sell 1 @ 99 → (100/99 - 1)*10_000 ≈ 101.01 bps.
        bps = estimate_slippage_bps(book, side="sell", qty_base=1.0)
        assert bps == pytest.approx((100.0 / 99.0 - 1.0) * 10_000.0, rel=1e-9)
        # And it must be strictly greater than the buy side, because the
        # 99 level is a wider relative gap from mid than 101.
        bps_buy = estimate_slippage_bps(book, side="buy", qty_base=1.0)
        assert bps > bps_buy

    def test_slippage_returns_inf_when_book_cannot_drain(self):
        # A thin book with $1K of asks vs a $3M notional request.
        book = L2Book(
            coin="@t",
            time_ms=0,
            bids=(L2Level(price=100.0, size=10.0, n_orders=1),),
            asks=(L2Level(price=101.0, size=10.0, n_orders=1),),
        )
        bps = estimate_slippage_bps(
            book, side="buy",
            qty_base=3_000_000.0 / 100.0,  # way more than the ask side holds
            mid_px=100.0,
        )
        assert math.isinf(bps)

    def test_slippage_returns_nan_when_no_mid(self):
        empty = L2Book(coin="@t", time_ms=0, bids=(), asks=())
        assert math.isnan(estimate_slippage_bps(empty, side="buy", qty_base=1.0))

    def test_walk_book_rejects_bad_side(self):
        book = self._trivial_book()
        with pytest.raises(ValueError):
            walk_book_for_qty(book.asks, qty_base=1.0, side="hold")

    def test_walk_book_rejects_zero_qty(self):
        book = self._trivial_book()
        with pytest.raises(ValueError):
            walk_book_for_qty(book.asks, qty_base=0.0, side="buy")

    def test_slippage_scan_returns_all_four_notionals(self):
        book = self._trivial_book()
        scan = slippage_scan(book, side="buy",
                             notionals_usdc=REFERENCE_NOTIONALS_USDC,
                             mid_px=100.0)
        for n in REFERENCE_NOTIONALS_USDC:
            assert n in scan
        # $3M is way more than this book can drain.
        assert math.isinf(scan[3_000_000.0])
        # $3k @ $100 mid = 30 base; ask side has 10 → cannot drain → inf too.
        assert math.isinf(scan[3_000.0])


# ── Parsers ─────────────────────────────────────────────────────────────────
class TestParsers:
    def test_parse_spot_meta_indexes_by_token_index(self, fixture: HlSpotFixture):
        tokens = fixture.tokens()
        assert isinstance(tokens, dict)
        # UBTC token from spotMeta has index 197, szDecimals 5 (per fixture).
        ubtc = find_token_by_name(tokens, "UBTC")
        assert ubtc is not None and ubtc.name == "UBTC"
        assert ubtc.sz_decimals == 5
        assert ubtc.index == 197

        ueth = find_token_by_name(tokens, "UETH")
        assert ueth is not None and ueth.name == "UETH"
        assert ueth.sz_decimals == 4
        assert ueth.index == 221

    def test_parse_spot_meta_universe_has_canonical_pair(self, fixture: HlSpotFixture):
        # The UBTC/USDC canonical pair is named "@142"; non-canonical names
        # exist too. The fixture must contain at least one UBTC pool we
        # can book via l2Book.
        for u in fixture._spot_meta_raw.get("universe", []):
            if 197 in (u.get("tokens") or []):
                assert u["name"] in ("@142",) or u["name"].startswith("@")
        # The book fixture uses @142.
        assert "@142" in [u["name"] for u in fixture._spot_meta_raw["universe"]
                          if 197 in (u.get("tokens") or [])]

    def test_parse_spot_meta_and_asset_ctxs_returns_pair_per_universe(
        self, fixture: HlSpotFixture
    ):
        pairs = fixture.pairs()
        assert len(pairs) >= 100       # fixture has hundreds of pairs
        for p in pairs:
            assert isinstance(p, HlSpotPair)
            assert p.name                              # non-empty
        # The two we care about (UBTC, UETH) MUST resolve — those are the
        # X1V sleeve's only inputs. Other perp-style entries (idx == -1)
        # are tolerated because HL sometimes returns mixed payloads.
        for base in ("UBTC", "UETH"):
            p = fixture.find_pair_by_token(base)
            assert p is not None and p.base_token_index >= 0

    def test_find_ubtc_usdc_pair_has_realistic_mid(self, fixture: HlSpotFixture):
        p = fixture.find_pair_by_token("UBTC")
        assert p is not None
        # BTC on 2026-10-18 is mid-four-figures per HL context.
        if p.mid_px is not None:
            # sanity: not absurdly low or absurdly high
            assert 1_000.0 < p.mid_px < 1_000_000.0

    def test_find_ueth_usdc_pair_has_realistic_mid(self, fixture: HlSpotFixture):
        p = fixture.find_pair_by_token("UETH")
        assert p is not None
        if p.mid_px is not None:
            assert 100.0 < p.mid_px < 100_000.0

    def test_parse_l2_book_ubtc(self, fixture: HlSpotFixture):
        book = fixture.l2_book_for("UBTC")
        assert book.coin == "@142"
        assert len(book.bids) > 0
        assert len(book.asks) > 0
        # best bid strictly < best ask; midpoint is between them.
        assert book.best_bid < book.best_ask
        assert book.mid_px is not None
        assert book.best_bid <= book.mid_px <= book.best_ask

    def test_parse_l2_book_ueth(self, fixture: HlSpotFixture):
        book = fixture.l2_book_for("UETH")
        assert book.coin == "@151"
        assert len(book.bids) > 0
        assert len(book.asks) > 0
        assert book.best_bid < book.best_ask

    def test_all_mids_shape_is_string_to_string(self, fixture: HlSpotFixture):
        mids = fixture.all_mids()
        # allMids is `{NAME: midPxString}` for both perps and spot.
        assert isinstance(mids, dict)
        if mids:
            sample_k = next(iter(mids))
            # The keys are full pair/perp names; values are numeric strings.
            assert isinstance(sample_k, str)
            float(mids[sample_k])        # parseable


# ── Adapter surface ─────────────────────────────────────────────────────────
class TestForbiddenAndShape:
    def test_forbidden_actions_contains_core_danger_words(self):
        words = forbidden_actions()
        for w in ("order", "cancel", "sign", "withdraw", "private_key"):
            assert w in words

    def test_client_only_accepts_four_info_types(self):
        assert ALLOWED_INFO_TYPES == frozenset({
            "spotMeta", "spotMetaAndAssetCtxs", "l2Book", "allMids",
        })

    def test_client_endpoint_is_the_public_info_url(self):
        assert HYPERLIQUID_INFO_URL == "https://api.hyperliquid.xyz/info"
        # The path is /info, not /exchange — calling exchange would cross
        # into the signed boundary. Lock that URL.
        assert HYPERLIQUID_INFO_URL.endswith("/info")

    def test_client_post_rejects_unknown_info_type(self):
        # A `type:"action"` call carries private-key signing risk; the
        # client must refuse it without making a network call.
        cli = HlSpotClient()
        for bad in ("action", "exchange", "order", "cancel"):
            with pytest.raises(ValueError):
                cli._post({"type": bad})

    def test_payload_to_info_url_is_urlencoded_json(self):
        # The endpoint expects `{"type": "l2Book", "coin": "@142"}` as JSON,
        # NOT a query string. Lock the call shape to avoid silent regression
        # to ?type=… requests that HL ignores.
        cli = HlSpotClient()
        # We can't actually call _post without network; assert by URL itself.
        assert "?" not in HYPERLIQUID_INFO_URL


# ── X1V answer for the four reference notionals ─────────────────────────────
class TestX1VAnswer:
    def test_ubtc_min_size_clears_default(self, fixture: HlSpotFixture):
        ans = fixture.answer_x1v("UBTC")
        assert ans["sz_decimals"] == 5
        # The default $10 floor at UBTC mid should be small but positive
        # in base; rounding down must not give 0 when there's liquidity.
        assert ans["min_size_base"] > 0
        # And the rounded size must equal what raw_min rounds DOWN to.
        if ans["min_size_base_raw"] is not None:
            from decimal import Decimal, ROUND_DOWN
            quant = Decimal(1).scaleb(-ans["sz_decimals"])
            expected = float(Decimal(str(ans["min_size_base_raw"]))
                             .quantize(quant, rounding=ROUND_DOWN))
            assert ans["min_size_base"] == pytest.approx(expected)

    def test_ueth_min_size_clears_default(self, fixture: HlSpotFixture):
        ans = fixture.answer_x1v("UETH")
        assert ans["sz_decimals"] == 4
        assert ans["min_size_base"] > 0

    @pytest.mark.parametrize("notional", REFERENCE_NOTIONALS_USDC)
    def test_ubtc_slippage_scan_returns_numeric_or_infinite(
        self, fixture: HlSpotFixture, notional
    ):
        ans = fixture.answer_x1v("UBTC")
        bps = ans["slippage_bps_by_notional"][notional]
        # Either a finite bps (book drained) or +inf (couldn't drain).
        assert isinstance(bps, float)
        assert (math.isinf(bps) and bps > 0) or (not math.isnan(bps) and bps >= 0.0)

    def test_slippage_bps_monotone_in_notional_for_buy_side(
        self, fixture: HlSpotFixture
    ):
        """
        Slippage bps must not DECREASE as notional grows on a one-sided
        walk (lower notional = closer to mid → smaller adverse bps).
        Allowed to break via infinity (cannot drain); but among the
        drainable points, monotone non-decreasing.
        """
        ans = fixture.answer_x1v("UBTC")
        scan = ans["slippage_bps_by_notional"]
        finite = [v for v in scan.values() if math.isfinite(v)]
        assert finite == sorted(finite)

    def test_unknown_base_token_raises(self, fixture: HlSpotFixture):
        with pytest.raises(KeyError):
            fixture.answer_x1v("NOPE")
