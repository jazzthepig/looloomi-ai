"""One pinned price route for reading and trading (S-193).

Jazz, 2026-08-20: 交易和读取的 route 都要写死啊,不可以乱来啊 —
"不然就是回测好看,实盘根本没办法用,就算给你接 TradingView 和 Hyperliquid
就是浪费钱."

The defect he is naming: the read path resolved a FALLBACK CHAIN
(binance_hist > hyperliquid > eodhd > coingecko > yfinance) while the trade path
is Hyperliquid alone. Measured the same day, those two disagreed about ETH on
08-19 by seventeen points (+0.22% stored vs +17.57% on the venue). A backtest
priced on the chain and a fill priced on the venue cannot agree, and the gap
surfaces as unattributable slippage rather than as an error.

So the route is pinned, and when the venue cannot answer the result is a
REFUSAL, not a substitute — a refusal stops a backtest, a substitute ships it.
"""
import asyncio
import pathlib

import pytest

from src.data.market import price_route as pr
from tests._source import code_only

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_execution_venue_is_defined_once():
    assert pr.EXECUTION_VENUE == "hyperliquid"
    src = code_only((ROOT / "src/data/market/price_route.py").read_text())
    # The literal must appear once, in the constant. Everything else references it.
    assert src.count('"hyperliquid"') == 1, (
        "the venue must be named in exactly one place — a second literal is how "
        "a trading decision becomes a config tweak someone changes by half")


def test_book_and_execution_share_one_source():
    """A paper book marked anywhere but the venue is measuring a portfolio
    nobody could have held."""
    for purpose in ("execution", "book"):
        assert pr.price_source_for("BTC", True, purpose=purpose) == pr.EXECUTION_VENUE


def test_a_non_tradeable_symbol_is_refused_not_substituted():
    for purpose in ("execution", "book"):
        with pytest.raises(pr.PriceRouteError) as e:
            pr.price_source_for("SOMECOIN", False, purpose=purpose)
        assert "not listed" in str(e.value)


def test_coingecko_is_barred_from_return_series():
    """Its daily series is hourly points collapsed to a date: the value is 'some
    hour of that day'. Fine for a dashboard tile, disqualifying for a return."""
    assert "coingecko" in pr.BARRED_FOR_RETURNS
    assert "coingecko" not in pr.RESEARCH_SOURCES
    assert pr.EXECUTION_VENUE not in pr.BARRED_FOR_RETURNS


def test_the_route_raises_rather_than_returning_none():
    """None gets `or 0`-ed and defaulted into a plausible number three frames up.
    That is S-180, S-185 and S-190 in one sentence."""
    assert issubclass(pr.PriceRouteError, Exception)
    src = code_only((ROOT / "src/data/market/price_route.py").read_text())
    fn = src.split("def price_source_for")[1].split("\nasync def ")[0]
    assert "return None" not in fn, "must raise, not return None"


def test_book_gate_refuses_a_mixed_universe(monkeypatch):
    """Refusing beats silently dropping: a book that quietly shrinks from 24
    names to 9 still reports a NAV, for a different portfolio than the page."""
    async def fake_venue(force=False):
        return {"BTC", "ETH", "SOL"}
    monkeypatch.setattr(pr, "venue_symbols", fake_venue)

    ok = asyncio.run(pr.assert_book_universe(["BTC", "ETH"]))
    assert ok == ["BTC", "ETH"]

    with pytest.raises(pr.PriceRouteError) as e:
        asyncio.run(pr.assert_book_universe(["BTC", "XYZ", "ABC"]))
    msg = str(e.value)
    assert "XYZ" in msg and "could not be held" in msg


def test_split_universe_reports_the_executable_fraction(monkeypatch):
    """66% of our research panel cannot be traded. That must be a number a
    sleeve designer sees, not one they rediscover after building."""
    async def fake_venue(force=False):
        return {"BTC", "ETH"}
    monkeypatch.setattr(pr, "venue_symbols", fake_venue)
    r = asyncio.run(pr.split_universe(["BTC", "ETH", "AAA", "BBB"]))
    assert r["tradeable"] == ["BTC", "ETH"]
    assert r["research_only"] == ["AAA", "BBB"]
    assert r["tradeable_pct"] == 50.0
    assert r["venue"] == pr.EXECUTION_VENUE


def test_unreachable_venue_listing_refuses_to_guess():
    """Not knowing which symbols are tradeable is not permission to assume."""
    src = code_only((ROOT / "src/data/market/price_route.py").read_text())
    fn = src.split("async def venue_symbols")[1].split("\nasync def ")[0]
    assert "raise PriceRouteError" in fn
    assert "last-good" in (ROOT / "src/data/market/price_route.py").read_text(), (
        "a transient outage should hold the last known listing; only a cold "
        "start with no cache may refuse outright")


def test_the_book_goes_through_the_venue_gate():
    """S-193. The ① book loads `load_binance_panel` (262 names); 88 are listed on
    the venue. Marking across all of them produces a NAV for a portfolio that
    could not be held."""
    src = code_only((ROOT / "src/data/signals/beta_core_paper.py").read_text())
    fn = src.split("async def mark_and_rebalance")[1]
    assert "split_universe" in fn, "the book must consult the venue listing"

    gate = fn.find("split_universe")
    load = fn.find("_load_panel()")
    assert 0 <= load < gate, "the gate runs after the panel loads, before marking"

    # Column slicing, not row slicing. `close` is (days, symbols); the first
    # version sliced rows and would have reindexed the book onto a few days
    # while still producing a NAV.
    assert "close[:, keep]" in fn and "ret[:, keep]" in fn, (
        "symbol filtering must slice the COLUMN axis of the (days, symbols) array")
    # Be specific: `symbols = [symbols[i] for i in keep]` is CORRECT (symbols is
    # a 1-D list). The bug shape is row-slicing the 2-D arrays. The first version
    # of this assertion banned the substring "for i in keep]" and therefore
    # flagged the correct symbols line — a guard matching a fragment rather than
    # the construct, for the fifth time this session.
    for wrong in ("close[i] for i in keep", "ret[i] for i in keep"):
        assert wrong not in fn, (
            f"row-slicing ({wrong}) reindexes the book onto trading days while "
            f"still producing a NAV")


def test_the_book_reports_what_it_excluded():
    """A book that quietly shrinks still returns a NAV."""
    src = code_only((ROOT / "src/data/signals/beta_core_paper.py").read_text())
    assert '"venue_excluded"' in src
    assert '"n_positions_marked"' in src


def test_unreachable_venue_stops_the_mark_rather_than_marking_everything():
    src = code_only((ROOT / "src/data/signals/beta_core_paper.py").read_text())
    fn = src.split("async def mark_and_rebalance")[1]
    # Anchor on the CALL, not the import — the name appears in both.
    blk = fn.split("await split_universe(")[1][:900]
    assert "skipped" in blk and "refusing" in blk.lower(), (
        "if the venue listing is unavailable the book must NOT fall back to "
        "marking the unverified full panel — that is substitute-instead-of-refuse")


# ── S-197: chain-agnostic ≠ instrument-agnostic ──────────────────────────────

def test_the_core_book_declares_its_instrument_and_carries_a_funding_field():
    """Jazz released the Solana constraint (2026-08-23: chain-agnostic, follow
    the liquidity). He did NOT release the instrument.

    ARCHITECTURE.md: beta = HOLD. A long perpetual is a synthetic long that pays
    carry, and the ① panel's own 24 names run +23.07% equal-weight annualised
    funding on Hyperliquid (AAVE +110.8%, NEAR +94.4%) — ~26.5%/yr at gross 1.15,
    larger than any alpha demonstrated here.

    `grep -c funding beta_core_paper.py` returned 0 while combined/causal/fusion
    returned 6/11/56. ① was the only book structurally incapable of noticing the
    cost, which is how a perp venue nearly became its execution venue."""
    src = code_only((ROOT / "src/data/signals/beta_core_paper.py").read_text())
    assert "funding_ret" in src, (
        "① must carry a funding field even at zero — the ABSENCE of the field is "
        "what let a carry-bearing venue nearly be adopted uncosted")
    assert '"instrument": "spot"' in src, (
        "the book must declare what it holds; 'we hold spot' should be readable "
        "from the mark, not assumed")
    assert '"funding_return_pct"' in src, "carry must be reported, not just computed"


def test_a_non_zero_carry_on_the_core_book_is_an_alarm():
    src = code_only((ROOT / "src/data/signals/beta_core_paper.py").read_text())
    blk = src.split("funding_ret = 0.0")[1][:400]
    assert "if funding_ret:" in blk and "_log.error" in blk, (
        "non-zero carry means ① has stopped holding spot — that must page, not "
        "quietly change the return")


def test_positioning_is_chain_agnostic_but_names_the_instrument():
    claude = (ROOT / "CLAUDE.md").read_text()
    assert "chain-agnostic" in claude, "the Solana constraint was released 2026-08-23"
    assert "beta = HOLD" in claude and "perpetual" in claude, (
        "releasing the chain must not silently release the instrument — the doc "
        "has to say which one moved")


# ── S-323o: the venue listing must survive a deploy ──────────────────────────
# 2026-09-09 00:05:39, measured: ① `beta_core` refused to mark at the valuation
# point — "cannot reach the execution venue's listing, and no cached copy
# exists." The refusal was correct. The reason there was no cached copy is that
# `_VENUE_CACHE` was a module-level dict, and we had redeployed several times
# that day; every deploy reset it to None.
#
# So the last-good fallback was empty in the one situation it exists for, and a
# day of ①'s forward record — the product — was lost to one HTTP blip at
# midnight. A venue listing changes weekly; the record is daily. Trading an
# unrepeatable day for a transient is a bad trade.

def _reset_route(pr):
    pr._VENUE_CACHE.update(symbols=None, ts=0.0)


def test_a_deploy_does_not_destroy_the_venue_listing(monkeypatch):
    """The exact 2026-09-09 sequence: memory wiped, venue down, mark must live."""
    import time
    import src.data.market.hyperliquid_collector as hc
    import src.api.store as store
    import src.data.market.price_route as pr

    async def _down(client=None):
        return [], "ReadTimeout: venue blipped at the valuation point"

    async def _persisted(key):
        return {"symbols": ["BTC", "ETH", "SOL"], "ts": time.time() - 3600}

    monkeypatch.setattr(hc, "hyperliquid_universe_detailed", _down)
    monkeypatch.setattr(store, "redis_get_key", _persisted)
    _reset_route(pr)                      # ← this IS the deploy

    syms, meta = asyncio.run(
        pr.venue_symbols_detailed(force=True))
    assert syms == {"BTC", "ETH", "SOL"}
    assert meta["source"] == "persisted", (
        "after a deploy the in-memory copy is gone; the persisted one is the "
        "only thing standing between a venue blip and a lost day of ①")


def test_marking_on_a_carried_listing_is_recorded_not_silent(monkeypatch):
    """A carried listing satisfies every check and is not an observation (S-287)."""
    import time
    import src.data.market.hyperliquid_collector as hc
    import src.api.store as store
    import src.data.market.price_route as pr

    async def _down(client=None):
        return [], "ReadTimeout: boom"

    async def _persisted(key):
        return {"symbols": ["BTC", "ETH"], "ts": time.time() - 7200}

    monkeypatch.setattr(hc, "hyperliquid_universe_detailed", _down)
    monkeypatch.setattr(store, "redis_get_key", _persisted)
    _reset_route(pr)

    split = asyncio.run(
        pr.split_universe(["BTC", "ETH"]))
    assert split["listing_meta"]["source"] == "persisted"
    src_txt = (ROOT / "src" / "data" / "signals" / "beta_core_paper.py").read_text()
    assert "listing_meta" in src_txt and "CARRIED venue listing" in src_txt, (
        "the book must record that it marked on a carried listing — otherwise "
        "'observed today' and 'reused from last week' are the same NAV row")


def test_a_stale_persisted_listing_still_refuses(monkeypatch):
    """NEGATIVE CONTROL. Persistence must not become 'guess forever'."""
    import time
    import src.data.market.hyperliquid_collector as hc
    import src.api.store as store
    import src.data.market.price_route as pr

    async def _down(client=None):
        return [], "ReadTimeout: boom"

    async def _ancient(key):
        return {"symbols": ["BTC"], "ts": time.time() - 99 * 24 * 3600}

    monkeypatch.setattr(hc, "hyperliquid_universe_detailed", _down)
    monkeypatch.setattr(store, "redis_get_key", _ancient)
    _reset_route(pr)

    with pytest.raises(pr.PriceRouteError):
        asyncio.run(
            pr.venue_symbols_detailed(force=True))


def test_an_empty_listing_is_not_an_unreachable_venue(monkeypatch):
    """`hyperliquid_universe` used to return [] for BOTH — the S-180 collapse,
    and the fix for it was already written 20 lines below, in `_fetch_one`."""
    import src.data.market.hyperliquid_collector as hc
    import src.api.store as store
    import src.data.market.price_route as pr

    async def _empty(client=None):
        return [], None                      # venue answered: nothing listed

    async def _no_cache(key):
        return None

    monkeypatch.setattr(hc, "hyperliquid_universe_detailed", _empty)
    monkeypatch.setattr(store, "redis_get_key", _no_cache)
    _reset_route(pr)

    with pytest.raises(pr.PriceRouteError) as ei:
        asyncio.run(
            pr.venue_symbols_detailed(force=True))
    assert "EMPTY listing" in str(ei.value), (
        "'the venue lists nothing' and 'we could not ask the venue' have "
        "different fixes and must not render identically")


def test_something_warms_the_persisted_listing_before_the_mark_needs_it():
    """S-323p. Persistence only helps if a WRITE precedes the read.

    S-323o persisted the venue listing so ① could still mark through a venue
    blip at 00:05. But the only callers of split_universe/venue_symbols were
    beta_core_paper (the mark itself) and panel_read — so on a freshly deployed
    process the first read happens before any write, and the persisted copy is
    empty in exactly the scenario it exists for.

    A cache with no writer is not a cache. `_hyperliquid_loop` runs every 6h,
    already talks to the venue, and boots within ~180s of a deploy, so it warms
    the copy long before the next valuation point.
    """
    main_src = (ROOT / "src" / "api" / "main.py").read_text()
    hl = main_src.split("async def _hyperliquid_loop")[1].split("\nasync def ")[0]
    assert "venue_symbols_detailed" in hl, (
        "nothing refreshes the persisted venue listing on a schedule — the "
        "S-323o fallback would be empty on every cold process, which is the "
        "only time it is needed"
    )
    assert "force=True" in hl, (
        "warming must bypass the in-memory TTL, or a warm process never "
        "refreshes the persisted copy"
    )
