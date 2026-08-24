"""Bulk fan-out belongs on a paid source (S-205).

Jazz, 2026-08-23: 不可以那么依赖任何免费 api,大量多资产会被封啊。多并发高需求量
的我们要以 pro 的 coingecko 为主要来源。

He had said this before. It was violated twice in one week anyway:

  · deep_panel_collector — 262 symbols against Binance's free mirror. One symbol
    reachable; the panel sat dead for days (S-190).
  · hyperliquid_collector — 232 symbols against a free DEX endpoint at ~53 req/s.
    HTTP 429 on 57 including BTC, coverage 56%, write refused two days (S-204).

Both were "fixed" at the symptom — a floor that blocks, a gentler pace. Neither
touched the rule. A reminder given and violated twice is not a reminder; it has
to be something that fails a build.

AND THE REAL LESSON WAS CHEAPER THAN THE FIX. Hyperliquid's metaAndAssetCtxs
returns markPx, oraclePx, funding, openInterest and day volume for ALL 232 perps
in ONE request. The 232-call loop existed because nobody looked for a bulk
endpoint. The rate limit was not a wall to pace against — it was the venue
saying the question was wrong.
"""
import ast
import pathlib

import pytest

from src.data.market.source_policy import (
    assert_bulk_source, SourcePolicyError, BULK_THRESHOLD,
    PAID_SOURCES, FREE_SOURCES, bulk_endpoint_for)
from tests._source import code_only

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_a_bulk_fanout_over_a_free_source_raises():
    with pytest.raises(SourcePolicyError) as e:
        assert_bulk_source(232, "hyperliquid", job="daily bars")
    msg = str(e.value)
    assert "232" in msg and "free source" in msg
    assert "coingecko_pro" in msg, "the error must name where it SHOULD go"
    assert "metaAndAssetCtxs" in msg, (
        "when the free source has a bulk endpoint the error must say so — that "
        "is the actual fix, not a gentler pace")


def test_paid_sources_may_fan_out():
    assert_bulk_source(17000, "coingecko_pro", job="breadth")
    assert_bulk_source(500, "eodhd", job="tradfi bars")


def test_a_targeted_query_against_a_free_source_is_fine():
    """This is not 'free sources are bad'. One question is fine; a fan-out is not."""
    assert_bulk_source(BULK_THRESHOLD, "hyperliquid", job="targeted")


def test_the_threshold_needs_no_judgement_at_the_call_site():
    assert BULK_THRESHOLD <= 10, (
        f"threshold {BULK_THRESHOLD} — the two incidents were 262 and 232, and "
        f"any honest bulk job is far above this, so it should never be a close call")


def test_the_two_burned_sources_are_classified_free():
    for s in ("hyperliquid", "binance", "binance_vision", "yfinance"):
        assert s in FREE_SOURCES, f"{s} burned us; it must be classified free"
    assert "coingecko_pro" in PAID_SOURCES and "eodhd" in PAID_SOURCES


def test_the_venue_bulk_endpoint_is_recorded():
    hl = bulk_endpoint_for("hyperliquid")
    assert any("metaAndAssetCtxs" in k for k in hl), (
        "the one-call endpoint must be discoverable from the policy, or the "
        "next person writes the 232-call loop again")


def test_the_hyperliquid_fanout_is_gated():
    src = code_only((ROOT / "src/data/market/hyperliquid_collector.py").read_text())
    fn = src.split("async def collect_hyperliquid")[1]
    gate = fn.find("assert_bulk_source(")
    loop = fn.find("asyncio.gather(")
    assert gate > 0, "the per-symbol path must consult the policy"
    assert gate < loop, "the gate must run BEFORE the fan-out, not alongside it"


def test_the_one_call_snapshot_exists_and_does_not_loop():
    src = code_only((ROOT / "src/data/market/hyperliquid_collector.py").read_text())
    fn = src.split("async def venue_snapshot")[1].split("\nasync def ")[0]
    assert "metaAndAssetCtxs" in fn
    assert "Semaphore" not in fn and "gather" not in fn, (
        "venue_snapshot must be ONE request — a loop here would recreate the "
        "problem it exists to remove")
    assert "return None" in fn or "_f" in fn, (
        "absent venue fields must be None, not 0.0 (I1) — a funding rate of 0.0 "
        "and an unknown funding rate size a book differently")


def test_no_new_module_fans_out_over_a_free_endpoint_uncounted():
    """Static sweep: a per-symbol loop against a free host, with no policy call
    in the same function. Matches the CONSTRUCT (a loop plus a free URL), not a
    name — see tests/_source.py for why that distinction keeps mattering."""
    FREE_HOSTS = ("api.hyperliquid.xyz", "data-api.binance.vision",
                  "fapi.binance.com", "api.binance.com")
    offenders = []
    for path in (ROOT / "src/data").rglob("*.py"):
        if "__pycache__" in str(path):
            continue
        src = code_only(path.read_text())
        if not any(h in src for h in FREE_HOSTS):
            continue
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            body = ast.get_source_segment(src, fn) or ""
            if not any(h in body for h in FREE_HOSTS):
                continue
            # A FAN-OUT is a gather over a VARIABLE-LENGTH list — `gather(*[...])`
            # — not any gather at all. `_binance_perp` awaits three fixed
            # endpoints for ONE symbol; the first version of this scan flagged
            # it, which is the same "matched a construct that merely resembles
            # the target" error this file's siblings keep hitting. The Starred
            # argument is the distinction, and it is exact.
            fans_out = False
            for node in ast.walk(fn):
                if not isinstance(node, ast.Call):
                    continue
                name = (node.func.attr if isinstance(node.func, ast.Attribute)
                        else getattr(node.func, "id", None))
                if name == "gather" and any(isinstance(a, ast.Starred) for a in node.args):
                    fans_out = True
                if name == "Semaphore":
                    fans_out = True
            gated = "assert_bulk_source" in body
            if fans_out and not gated:
                offenders.append(f"{path.relative_to(ROOT)}::{fn.name}")
    assert not offenders, (
        "fan-out over a free endpoint with no source-policy gate:\n  "
        + "\n  ".join(offenders)
        + "\n(check bulk_endpoint_for(source) first — the venue may answer in one call)")


def test_the_scanners_blind_spot_is_stated_not_hidden():
    """This sweep only sees a fan-out when the loop AND the free URL sit in the
    SAME function. `consolidator.fetch_venue_overlay` gathers over venues while
    the URLs live in `_binance_perp` one call down — invisible here.

    That case is not a violation (it fans out over VENUES for one asset, ~5
    requests, not over assets), but the blind spot is real and the next one
    might be. Stated rather than left implicit, because an empty check and a
    passing check look identical from outside — the failure mode this whole
    session kept finding.

    Closing it properly needs a call-graph, which is worth doing when a second
    instance appears and not before."""
    scanned, with_urls = 0, 0
    FREE_HOSTS = ("api.hyperliquid.xyz", "data-api.binance.vision",
                  "fapi.binance.com", "api.binance.com")
    for path in (ROOT / "src/data").rglob("*.py"):
        if "__pycache__" in str(path):
            continue
        scanned += 1
        if any(h in code_only(path.read_text()) for h in FREE_HOSTS):
            with_urls += 1
    assert scanned > 20, f"only {scanned} modules scanned — the sweep is not reaching src/data"
    assert with_urls >= 3, (
        f"only {with_urls} modules reference a free host; the sweep should be "
        f"finding several — if this drops to 0 the scan has silently stopped working")
    print(f"\n  scanned {scanned} modules · {with_urls} touch a free host "
          f"· cross-function fan-outs NOT covered (stated blind spot)")
