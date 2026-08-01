#!/usr/bin/env python3
"""
Venue integrity gate — preflight stage.

Answers the question no completeness check can: is this number the RIGHT ASSET?

Background (2026-08-01): `cis_provider.BINANCE_SYMBOLS` mapped HYPE to Binance
spot HYPERUSDT, which is Hyperlane — $0.0558 against Hyperliquid's $52.32. The
engine scored Hyperliquid using Hyperlane's order book for months, producing
grade D / UNDERWEIGHT through a +256% run. loop_health passed the whole time,
because the field was populated. A populated wrong number is invisible to a
completeness check and obvious to a cross-venue one.

Checks, in order of severity:
  FAIL  price dispersion across venues exceeds the reject threshold, or a venue
        is rejected as an outlier  -> a mapping points at the wrong asset
  FAIL  zero venues resolved for an asset in the universe
  WARN  degraded coverage (< MIN_VENUES_FOR_CONSENSUS venues responded)
  WARN  venue registry past its review cadence
  WARN  unverified (asset, venue) pairs — where the next collision comes from

Usage:
    python scripts/check_venue_integrity.py               # whole registry
    python scripts/check_venue_integrity.py --symbols HYPE,MKR
    python scripts/check_venue_integrity.py --json

Exit codes: 0 clean (warnings allowed) · 1 FAIL present · 2 harness error.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402

from src.data.venues.consolidator import (  # noqa: E402
    MIN_VENUES_FOR_CONSENSUS,
    OUTLIER_REJECT_RATIO,
    fetch_consolidated,
)
from src.data.venues.registry import (  # noqa: E402
    REVIEW_CADENCE_DAYS,
    SYMBOL_MAP,
    registry_age_days,
    unverified_pairs,
)

CONCURRENCY = 6

# Inclusion Standard v2.0, criterion 1 (Liquidity): 30d average daily volume
# >= $5M. Enforced at intake but never re-checked on existing members — which
# is how MKR stayed in the universe after the Sky redenomination left it at
# $440k/day with $0 market cap, while the product surface kept publishing
# "fundamentals accelerating" on a 320-day-stale price panel. Same criterion,
# now enforced continuously instead of once.
LIQUIDITY_FLOOR_USD = 5_000_000


async def _one(sem: asyncio.Semaphore, client: httpx.AsyncClient, sym: str):
    async with sem:
        try:
            return sym, await fetch_consolidated(sym, client=client)
        except Exception as e:  # noqa: BLE001
            return sym, e


async def run(symbols: list[str]) -> tuple[list[dict], list[str], list[str]]:
    fails: list[str] = []
    warns: list[str] = []
    rows: list[dict] = []

    sem = asyncio.Semaphore(CONCURRENCY)
    async with httpx.AsyncClient(timeout=10) as client:
        results = await asyncio.gather(*[_one(sem, client, s) for s in symbols])

    for sym, res in results:
        if isinstance(res, Exception):
            fails.append(f"{sym}: consolidation raised {type(res).__name__}: {res}")
            continue
        if res is None:
            fails.append(f"{sym}: no venue resolved — asset is invisible to the engine")
            continue

        rows.append(res.to_dict())

        if res.venues_rejected:
            fails.append(
                f"{sym}: venue(s) {', '.join(res.venues_rejected)} rejected as price "
                f"outliers — mapping likely points at the WRONG ASSET "
                f"(dispersion {res.price_dispersion:.2%})"
            )
        elif res.price_dispersion > OUTLIER_REJECT_RATIO:
            fails.append(
                f"{sym}: cross-venue price dispersion {res.price_dispersion:.2%} "
                f"exceeds {OUTLIER_REJECT_RATIO:.0%} with no majority to arbitrate — "
                f"venues {', '.join(res.venues_used)}"
            )
        elif res.degraded:
            warns.append(f"{sym}: degraded — {res.degraded_reason}")

        # Continuous re-check of Inclusion Standard v2.0 criterion 1.
        if res.volume_24h_usd < LIQUIDITY_FLOOR_USD:
            fails.append(
                f"{sym}: consolidated 24h volume ${res.volume_24h_usd:,.0f} is below the "
                f"${LIQUIDITY_FLOOR_USD:,.0f} Inclusion Standard v2.0 liquidity floor "
                f"(criterion 1) — asset no longer qualifies for the universe; "
                f"check for a redenomination/rebrand before anything user-facing "
                f"references it"
            )

        if res.venues_failed:
            warns.append(f"{sym}: venue(s) unreachable: {', '.join(res.venues_failed)}")

    age = registry_age_days()
    if age > REVIEW_CADENCE_DAYS:
        warns.append(
            f"venue registry last reviewed {age}d ago (cadence {REVIEW_CADENCE_DAYS}d) — "
            "re-verify mappings and bump REVIEWED_AT"
        )

    gaps = unverified_pairs(symbols)
    if gaps:
        warns.append(
            f"{len(gaps)} unverified (asset, venue) pair(s): "
            + ", ".join(f"{a}/{v}" for a, v in gaps[:8])
            + (" ..." if len(gaps) > 8 else "")
        )

    return rows, fails, warns


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", help="comma-separated; default = whole registry")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()

    symbols = ([s.strip().upper() for s in args.symbols.split(",") if s.strip()]
               if args.symbols else sorted(SYMBOL_MAP.keys()))

    try:
        rows, fails, warns = asyncio.run(run(symbols))
    except Exception as e:  # noqa: BLE001
        print(f"FAIL  harness error: {type(e).__name__}: {e}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps({"rows": rows, "fails": fails, "warns": warns}, indent=2))
        return 1 if fails else 0

    print(f"{'asset':8}{'price':>12}{'24h vol':>16}{'OI (gross)':>16}"
          f"{'disp':>9}{'HHI':>7}{'conf':>7}  venues")
    for r in sorted(rows, key=lambda x: x["asset"]):
        used = ",".join(v.replace("_perp", "").replace("binance_spot", "bn_spot")
                        for v in r["venues_used"])
        print(f"{r['asset']:8}{r['price']:>12,.4f}{'$'+format(r['volume_24h_usd'],',.0f'):>16}"
              f"{'$'+format(r['open_interest_usd'],',.0f'):>16}"
              f"{r['price_dispersion']:>9.4%}{r['oi_concentration']:>7.2f}"
              f"{r['confidence']:>7.2f}  {used}")

    print()
    for w in warns:
        print(f"WARN  {w}")
    for f in fails:
        print(f"FAIL  {f}")

    print()
    if fails:
        print(f"FAIL — {len(fails)} integrity failure(s), {len(warns)} warning(s)")
        return 1
    print(f"PASS — {len(rows)} assets consolidated, {len(warns)} warning(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
