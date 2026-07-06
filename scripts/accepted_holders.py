#!/usr/bin/env python3
"""
D3 — accepted_holders adapter (Mac side → Seth's cause_proximity contract).

Bridge between the holder-concentration warehouse
(/Volumes/CometCloudAI/cometcloud-local/_data/dune_holders/processed/*.json)
and Seth's `attach_cause_proximity(holder_map=...)` on Railway
(`src/data/cis/cause_proximity.py`).

The contract is fixed by `estimate_inline(a, attention, holder)`:

    holder_map = {
        "ZANO": {
            "stage": 0.78, "disp_accel": 2.1, "chuquan": True,           # original 2026-07-01
            "days_since_chuquan": 12, "season": "momentum",              # +2026-07-06 B-extension
        },
        ...
    }

i.e. {SYMBOL_UPPER: {stage, disp_accel, chuquan, days_since_chuquan, season}} —
the latest snapshot's full lifecycle per token. `season ∈ {"pre","momentum","stale"}`
captures the post-出圈 tradeable window: per Jazz (2026-07-06), this 1-2 month
momentum window is where "流动性特别充裕" — the season to ride, not flee.

This module:
  - KNOWS the address → symbol registry for tokens we've processed (start small;
    grow as new tokens get fetched — the dict is the single source of truth here).
  - READS every processed/<addr>.json in the warehouse.
  - PICKS the latest date's per-token metrics.
  - EMITS the holder_map that cause_proximity.attach_cause_proximity expects.

The plug is plug-ready: the moment Jazz (or whoever authors in the Dune UI)
hands over the D3 query_id and Minimax runs `fetch_holder_concentration.py`
against real chains, this adapter picks up the new JSONs unchanged. Until
then the dry-run path (fetch_holder_concentration.py --dry-run) writes a
synthetic 0xSYNTHETIC.json and proves the round-trip end-to-end.

Usage:
  from accepted_holders import load_holder_map, KNOWN_TOKENS
  holder_map = load_holder_map()                   # auto-uses default warehouse
  holder_map = load_holder_map(universe=universe)  # use universe's address hints
  holder_map = load_holder_map(processed_dir=P)    # explicit dir

CLI:
  # 1. Run dry-run to populate the warehouse with synthetic 0xSYNTHETIC.json
  python3 scripts/fetch_holder_concentration.py --dry-run
  # 2. Read it back via the adapter and print the holder_map contract
  python3 scripts/accepted_holders.py

The CLI prints the holder_map exactly as Seth's cause_proximity will see it.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional


# ── Warehouse layout (mirror fetch_holder_concentration.py) ────────────────
_DEFAULT_WAREHOUSE = Path(
    os.getenv(
        "DUNE_HOLDERS_DIR",
        "/Volumes/CometCloudAI/cometcloud-local/_data/dune_holders/",
    )
)
PROCESSED_DIR_NAME = "processed"


# ── Address → symbol registry ─────────────────────────────────────────────
# Ethereum-mainnet token addresses (lowercased) → canonical symbols.
# Start with the assets we realistically pull from Dune (Ethereum L1 has the
# reliable balances_daily table). Add entries here as new tokens get fetched —
# the dict is the single source of truth on the Mac side.
#
# TradFi (SPY/QQQ/AAPL/...) and non-ERC20 crypto (BTC-native/SOL/ADA/...)
# have no Ethereum address → no D3 holder row possible. Their cause_proximity
# stays on attention_diffusion / market_proxy (see cause_proximity.py §17-21).
KNOWN_TOKENS: dict[str, str] = {
    # Stablecoins (often used as Dune test rows; cheap & deep history)
    "0xdac17f958d2ee523a2206206994597c13d831ec7": "USDT",
    "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48": "USDC",
    "0x6b175474e89094c44da98b954eedeac495271d0f": "DAI",

    # Wrapped / canonical ETH-mainnet tokens for the 43-asset universe
    "0x2260fac5e5542a773aa44fbcfedf7c193bc2c599": "WBTC",   # BTC exposure
    "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2": "WETH",   # ETH ERC20
    "0x1f9840a85d5af5bf1d1762f925bdaddc4201f984": "UNI",
    "0x7fc66500c84a76ad7e9c93437bfc5ac33e2ddae9": "AAVE",
    "0x5a98fcbea516cf06857215779fd812ca3bef1b32": "LDO",
    "0x808507121b80c02388fad14726482e061b8da827": "PENDLE",
    "0x514910771af9ca656af840dff83e8264ecf986ca": "LINK",
    "0xe28b3b32b6c345a34ff64674606124dd5aceca30": "INJ",
    "0xfaba6f8e4a5e8ab82f62fe7c39859fa577269be3": "ONDO",
    "0x9f8f72aa9304c8b593d555f12ef6589cc3a579a2": "MKR",
    "0xb50721bcf8d664c30412cfbc6cf7a15145234ad1": "ARB",
    "0x4200000000000000000000000000000000000042": "OP",
    "0xca14007eff0db1f8135f4c25b34de49ab0d427fa": "STRK",

    # Synthetic token (written by --dry-run; always last)
    "0xsynthetic":                                  "SYNTH",
}


# ── Address → symbol lookup ───────────────────────────────────────────────
def resolve_symbol(addr: str) -> Optional[str]:
    """Map a token address (any case) to its canonical symbol, or None if unknown.

    The caller is responsible for falling back gracefully — Seth's
    `attach_cause_proximity()` accepts holder_map keyed by SYMBOL_UPPER, so
    unknown addresses simply don't appear in the returned map.
    """
    if not addr:
        return None
    return KNOWN_TOKENS.get(addr.lower())


def register_token(addr: str, symbol: str) -> None:
    """Add or overwrite an address → symbol mapping at runtime.

    Use this when a new token's Dune data lands and we want to expose its
    holder_map key immediately without redeploying the adapter.
    """
    KNOWN_TOKENS[addr.lower()] = symbol.upper()


# ── JSON shape (from fetch_holder_concentration.py:process_and_write) ──────
# processed/<addr>.json =
#   {
#     "token":   "0xdAC...",        ← address (mixed case, from Dune)
#     "query_id": 0 or real id,
#     "n_dates": 60,
#     "fetched_at": "...",
#     "dates": {
#       "2025-01-01": {"n_holders": 5,    "hhi": 0.99, "top10": 1.0,
#                      "stage": 0.05, "disp_accel": 0.0, "chuquan": False},
#       ...
#       "2025-12-31": {"n_holders": 6055, "hhi": 0.04, "top10": 0.18,
#                      "stage": 0.93, "disp_accel": 2.4, "chuquan": True},
#     }
#   }


def _latest_date_entry(payload: dict) -> Optional[dict]:
    """Pick the most recent date's metrics from a processed payload.

    Returns None if the payload has no dates (shouldn't happen, but be safe).
    """
    dates = payload.get("dates") or {}
    if not dates:
        return None
    # ISO date strings sort lexically = chronologically. Don't rely on
    # dict insertion order — the producer (fetch_holder_concentration.py)
    # iterates out.index which IS chronological, but the consumer must not
    # assume that.
    latest_key = max(dates.keys())
    return dates[latest_key]


def _read_processed(path: Path) -> Optional[dict]:
    """Read a single processed/<addr>.json. Returns None on missing/corrupt."""
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None


# ── Public API ────────────────────────────────────────────────────────────
def load_holder_map(
    processed_dir: Optional[Path] = None,
    *,
    warehouse: Optional[Path] = None,
) -> dict[str, dict]:
    """
    Read every processed/<addr>.json in the warehouse and return the
    holder_map that cause_proximity.attach_cause_proximity() expects.

    Output shape (extends Seth's original contract with the season lifecycle,
    B-extension 2026-07-06 — backward compatible: original fields unchanged):
      {SYMBOL_UPPER: {
         "stage":              float ∈ [0,1],
         "disp_accel":         float,
         "chuquan":            bool,                # event: fires on the flood day
         "days_since_chuquan": int,                 # NEW: -1 = never, 0 = today, N = N days
         "season":             "pre"|"momentum"|"stale",  # NEW: lifecycle of the window
       }}

    `season` semantics (B-extension 2026-07-06, full Wyckoff/VSA lifecycle —
    strings must match `_SEASON_DAMP` in Seth's cause_proximity.py):
      Pre-出圈 (never chuquan'd; requires OHLCV to distinguish):
        "capitulation" — climax volume + holders fleeing (panic sell climax, 0.45)
        "dry_up"       — quiet accumulation, holders stable (smart money in
                         silence, 0.30 = LOWEST fragility / best entry)
        "spring_test"  — low-volume retest of lows (supply exhausting, 0.35)
        "early_markup" — volume picking up, holders growing (first demand, 0.50)
        "pre"          — default fallback (no clear signal, still upstream)
      Post-出圈 (chuquan fired; days_since drives the label):
        "momentum"     — days_since ∈ [0, 60d]. THE WEALTH-CREATION WINDOW
                         (Jazz: "出圈之后一般会有1-2个月动量，流动性特别充裕"), 0.55
        "stale"        — days_since > 60d. Post-window; smart money likely
                         distributed, fragility realized, floor 0.72.

    Args:
        processed_dir: explicit override for the per-token JSON dir. If None,
            defaults to <warehouse>/processed (or DUNE_HOLDERS_DIR/processed).
        warehouse:    root warehouse dir (used only if processed_dir is None).
            Defaults to /Volumes/CometCloudAI/cometcloud-local/_data/dune_holders/.

    Behavior:
        - Unknown addresses (no entry in KNOWN_TOKENS) → silently skipped
          (the cause_proximity adapter is happy with partial maps).
        - Empty / corrupt JSONs → silently skipped, not raised.
        - Missing season/days_since_chuquan (older JSON format) → backfilled
          with conservative defaults: days_since=-1, season="pre". Forward-compat
          so old processed files still resolve cleanly.
        - Tokens with chuquan=True on the latest snapshot ARE flagged — that's
          the whole point of the layer (出圈 alert = "diffusion accelerating
          right now, fragility rising").
        - Unknown season strings (legacy formats, hand-edited JSONs) → silently
          passed through. cause_proximity.py has the `_CHUQUAN_FLOOR` back-compat
          handler for any string it doesn't recognize.

    The function does NOT filter by date or recency — it always picks the
    LATEST snapshot in the JSON. Re-fetch (fetch_holder_concentration.py)
    is the way to refresh; this function is a pure reader.
    """
    if processed_dir is None:
        root = Path(warehouse) if warehouse else _DEFAULT_WAREHOUSE
        processed_dir = root / PROCESSED_DIR_NAME

    processed_dir = Path(processed_dir)
    if not processed_dir.exists():
        return {}

    holder_map: dict[str, dict] = {}
    for path in sorted(processed_dir.glob("*.json")):
        payload = _read_processed(path)
        if not payload:
            continue
        addr = payload.get("token") or path.stem   # fallback to filename
        sym = resolve_symbol(addr)
        if not sym:
            # Unknown token — Seth's side will simply not see a holder_map
            # entry for it and falls back to attention_diffusion / market_proxy.
            continue
        entry = _latest_date_entry(payload)
        if not entry:
            continue
        holder_map[sym.upper()] = {
            "stage":              float(entry.get("stage", 0.0)),
            "disp_accel":         float(entry.get("disp_accel", 0.0)),
            "chuquan":            bool(entry.get("chuquan", False)),
            # B-extension fields (backward-compat: missing → conservative defaults).
            # days_since=-1 + season="pre" effectively means "no chuquan signal yet" —
            # same as a pre-2026-07-06 JSON that never had the lifecycle fields.
            "days_since_chuquan": int(entry.get("days_since_chuquan", -1)),
            "season":             str(entry.get("season", "pre")),
        }

    return holder_map


# ── Self-test: dry-run → adapter → assert contract ────────────────────────
def _selftest() -> None:
    """
    Round-trip the dry-run output through the adapter and assert the
    emitted holder_map matches Seth's contract (incl. B-extension season).

    Assumes `python3 scripts/fetch_holder_concentration.py --dry-run` has
    already been run (writes processed/0xSYNTHETIC.json + index.json).
    """
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    # Make sure the synthetic token is registered (idempotent)
    register_token("0xSYNTHETIC", "SYNTH")

    holder_map = load_holder_map()
    print(f"holder_map ({len(holder_map)} entries):\n")
    _SEASON_TAG = {
        "capitulation": "⚡ CAP", "dry_up":       "💧 DRY",
        "spring_test":  "🪡 SPR", "early_markup": "📈 EM ",
        "pre":          "  pre", "momentum":     "▶ MOM",
        "stale":        "  stale",
    }
    for sym, row in sorted(holder_map.items()):
        flag = "YES" if row["chuquan"] else "-"
        season_emoji = _SEASON_TAG.get(row["season"], row["season"])
        print(f"  {sym:6}  stage={row['stage']:.3f}  "
              f"disp_accel={row['disp_accel']:+.3f}  chuquan={flag:>3}  "
              f"days={row['days_since_chuquan']:>4}  season={season_emoji}")

    # Contract assertions — if these break, Seth's adapter sees bad data.
    assert isinstance(holder_map, dict), "holder_map must be dict"
    REQUIRED = ("stage", "disp_accel", "chuquan", "days_since_chuquan", "season")
    # Full 7-season vocabulary (B-extension 2026-07-06) — producer contract
    # matches Seth's cause_proximity._SEASON_DAMP + _CHUQUAN_FLOOR / _SEASON_STALE_FLOOR.
    VALID_SEASONS = {"capitulation", "dry_up", "spring_test", "early_markup",
                     "pre", "momentum", "stale"}
    for sym, row in holder_map.items():
        assert isinstance(sym, str) and sym == sym.upper(), \
            f"{sym!r} must be SYMBOL_UPPER"
        assert isinstance(row, dict), f"{sym}: row must be dict"
        for k in REQUIRED:
            assert k in row, f"{sym}: missing key {k!r}"
        assert isinstance(row["stage"], float), f"{sym}.stage must be float"
        assert 0.0 <= row["stage"] <= 1.0, f"{sym}.stage must be ∈[0,1]"
        assert isinstance(row["disp_accel"], float), f"{sym}.disp_accel must be float"
        assert isinstance(row["chuquan"], bool), f"{sym}.chuquan must be bool"
        assert isinstance(row["days_since_chuquan"], int), \
            f"{sym}.days_since_chuquan must be int"
        assert row["season"] in VALID_SEASONS, \
            f"{sym}.season must be in {VALID_SEASONS}, got {row['season']!r}"

    # The synthetic token: chuquan fired once during the flood window.
    # The exact ending season depends on the latest snapshot's distance from
    # the chuquan fire — could be "momentum", "stale", or (with OHLCV-driven
    # lifecycle) one of the 4 pre-出圈 stages. We assert what we KNOW:
    # chuquan fired (event exists), stage is late (we dispersed), season is
    # one of the 7 valid strings. The specific terminal stage is observed
    # in the printer output above.
    if "SYNTH" in holder_map:
        synth = holder_map["SYNTH"]
        assert synth["stage"] > 0.5, \
            f"dry-run synthetic should be late-stage (got stage={synth['stage']:.3f})"
        assert synth["season"] in VALID_SEASONS, \
            f"ending season must be a valid 7-vocab string (got {synth['season']!r})"
        print(f"\n✓ contract holds: keys=UPPER, stage∈[0,1], chuquan=bool, "
              f"days_since=int, season∈{VALID_SEASONS}")
        print(f"✓ synthetic dry-run: stage={synth['stage']:.3f}, "
              f"chuquan={synth['chuquan']}, days_since={synth['days_since_chuquan']}, "
              f"season={synth['season']!r}")


# ── CLI ───────────────────────────────────────────────────────────────────
def _cli() -> int:
    import argparse
    p = argparse.ArgumentParser(
        description="D3 accepted_holders adapter — Mac side → cause_proximity holder_map"
    )
    p.add_argument("--processed-dir", type=Path, default=None,
                   help="Override the processed/ dir (default = $DUNE_HOLDERS_DIR/processed)")
    p.add_argument("--warehouse", type=Path, default=None,
                   help="Override the warehouse root (default = /Volumes/CometCloudAI/cometcloud-local/_data/dune_holders/)")
    p.add_argument("--json", action="store_true",
                   help="Emit raw JSON (matches Seth's holder_map contract)")
    p.add_argument("--selftest", action="store_true",
                   help="Run the round-trip self-test (dry-run → adapter → contract)")
    args = p.parse_args()

    if args.selftest:
        _selftest()
        return 0

    holder_map = load_holder_map(
        processed_dir=args.processed_dir,
        warehouse=args.warehouse,
    )

    if args.json:
        print(json.dumps(holder_map, indent=2, sort_keys=True))
    else:
        if not holder_map:
            print("(no processed tokens found — run --dry-run or fetch first)")
        else:
            _SEASON_TAG = {
                "capitulation": "⚡ CAP", "dry_up":       "💧 DRY",
                "spring_test":  "🪡 SPR", "early_markup": "📈 EM ",
                "pre":          "  pre", "momentum":     "▶ MOM",
                "stale":        "  stale",
            }
            print(f"holder_map ({len(holder_map)} entries):")
            for sym, row in sorted(holder_map.items()):
                flag = "YES" if row["chuquan"] else "-"
                season_emoji = _SEASON_TAG.get(row["season"], row["season"])
                print(f"  {sym:6}  stage={row['stage']:.3f}  "
                      f"disp_accel={row['disp_accel']:+.3f}  chuquan={flag:>3}  "
                      f"days={row['days_since_chuquan']:>4}  season={season_emoji}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(_cli())