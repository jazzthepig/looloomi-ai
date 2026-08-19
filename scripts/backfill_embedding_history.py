#!/usr/bin/env python3
"""
M-WO-D1 — backfill `asset_embeddings_history` from cis_scores × ohlcv_daily.

WHY. `asset_embeddings` is a 72-row single snapshot, so style rotation cannot be
backtested and `DECISION_PATH_SPEC §3` has been blocked on that alone. Everything
shipped in the last two weeks fixed delivery (breaker, bounded lock, security,
observability); none of it touched the intelligence gap. This closes it.

WHAT THE RAW MATERIAL ACTUALLY IS (measured, not assumed):
  cis_scores  109,176 rows · 436 distinct days · 2025-05-03 → 2026-08-06 · 76 symbols
    · 2025-05 → 2026-03  pillars 100 %, 34 symbols  ← 11 clean months, ~11k asset-days
    · 2026-04            pillars  20.8 %            ← coverage collapsed when the
    · 2026-05            pillars   4.0 %              universe expanded 34 → 72
    · 2026-06/07         pillars  ~67-70 %
    · 2026-08            pillars 100 %, 58 symbols
  So the usable history is far better than "72 rows" suggested — but it is NOT
  uniform, and a backtest that ignores the 2026-04/05 hole will read a pipeline
  outage as a regime change.

THE I1 PROBLEM THAT SHAPES THIS SCRIPT. `cis_scores` has no market columns at
all. Passed naively to `generate_embedding`, six dims take fabricated defaults —
mcap 1e6, changes 0, volume 0, ath 50 — IDENTICAL for every asset on every day.
That does not just lose information, it pulls every historical vector together
and manufactures cluster structure from nothing. Worse, `_clamp` swallowed NaN
into the upper bound (verified: `max(0.0, min(1.0, nan)) == 1.0`), so an
unmeasured market cap would have presented as a trillion-dollar asset while the
vector still looked well-formed.

So: five of those six dims are RECONSTRUCTED from `ohlcv_daily` (changes, volume
and ATH distance are all functions of price, and we hold 228k rows back to 2015);
`market_cap` is not recoverable historically and stays NaN. Every row records
`measured_dims` so a consumer can filter instead of guessing.

Usage:
    python3 scripts/backfill_embedding_history.py --from 2025-05-01 --to 2026-08-06
    python3 scripts/backfill_embedding_history.py --pilot          # 30 days, no write
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.data.vector.embedder import (  # noqa: E402
    ASSET_DIMS_V2, SCHEMA_VERSION, generate_embedding,
    # S-178: honesty rules owned by embedder.py so both writers of
    # asset_embeddings_history share one definition (see the note at
    # MIN_MEASURED_DIMS below).
    measured_dims, source_completeness, is_thin, vec_to_pg_row,
    MIN_MEASURED_DIMS as _EMBEDDER_MIN_MEASURED_DIMS,
)

SB_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SB_KEY = os.environ.get("SUPABASE_KEY", "")
HEAD = {"apikey": SB_KEY, "Authorization": f"Bearer {SB_KEY}",
        "Content-Type": "application/json"}

# A row whose measured dims fall below this is not written at all. Writing it
# would put a mostly-NaN vector in the same table as a good one, and the next
# person to query the table would have no reason to suspect the difference.
#
# S-178: this file is where the value ORIGINATED, and it is no longer where it
# LIVES — embedder.py owns it so both writers of asset_embeddings_history share
# one floor. Kept here as a name, asserted against the owner rather than
# re-declared: a second constant that merely happens to agree today is how two
# writers drift tomorrow.
MIN_MEASURED_DIMS = _EMBEDDER_MIN_MEASURED_DIMS
assert MIN_MEASURED_DIMS == 10, (
    f"MIN_MEASURED_DIMS moved to embedder.py and is now {MIN_MEASURED_DIMS}. "
    f"This file documented 10 of 27 dims as the write floor; if the owner changed "
    f"it, the change is real and this assertion is the place to acknowledge it — "
    f"do not silently follow.")


def _get(path: str, params: dict) -> list:
    q = "&".join(f"{k}={v}" for k, v in params.items())
    req = urllib.request.Request(f"{SB_URL}/rest/v1/{path}?{q}", headers=HEAD)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read()) or []


def _page(path: str, params: dict, page: int = 1000) -> list:
    out, off = [], 0
    while True:
        rows = _get(path, {**params, "limit": page, "offset": off})
        out += rows
        if len(rows) < page:
            return out
        off += page


def load_prices(lo: str, hi: str) -> dict:
    """{symbol: [(date, close, volume)]} ordered oldest→newest."""
    # ohlcv_daily_canonical, NOT ohlcv_daily. The base table is multi-source by
    # design — unique key (symbol, trade_date, source) — so a naive read returns
    # duplicated trading days whose volume columns are ~62,000x apart (CoinGecko
    # reports USD notional, Binance base units) and whose closes diverge by up to
    # 5% on the same day. 48,582 such pairs across 57 symbols, 2017→2026. The view
    # applies deterministic source precedence so this cannot be got wrong silently.
    rows = _page("ohlcv_daily_canonical", {
        "select": "symbol,trade_date,close,volume",
        "trade_date": f"gte.{lo}", "order": "symbol.asc,trade_date.asc",
    })
    rows = [r for r in rows if r["trade_date"] <= hi]
    by = defaultdict(list)
    for r in rows:
        by[r["symbol"].upper()].append(
            (r["trade_date"], float(r["close"] or 0), float(r["volume"] or 0)))
    return by


def market_block(series: list, i: int) -> dict:
    """Reconstruct the market fields that ARE functions of price.

    `market_cap` is deliberately absent — it is not derivable from OHLCV and must
    stay unmeasured rather than be approximated by something that merely
    correlates with it. An approximation here would be invisible downstream.
    """
    if i < 0 or i >= len(series):
        return {}
    _, c0, v0 = series[i]
    out: dict = {"volume_24h": v0 or None}

    def chg(n: int):
        j = i - n
        if j < 0:
            return None
        cj = series[j][1]
        return ((c0 - cj) / cj * 100.0) if cj else None

    out["change_24h"] = chg(1)
    out["change_7d"] = chg(7)
    out["change_30d"] = chg(30)

    hi = max((s[1] for s in series[:i + 1]), default=0.0)   # PIT running max only
    out["ath_distance_pct"] = ((hi - c0) / hi * 100.0) if hi > 0 else None
    return {k: v for k, v in out.items() if v is not None}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="lo", default="2025-05-01")
    ap.add_argument("--to", dest="hi", default=date.today().isoformat())
    ap.add_argument("--pilot", action="store_true", help="last 30d, no write")
    a = ap.parse_args()
    if a.pilot:
        a.lo = (date.today() - timedelta(days=30)).isoformat()

    if not SB_URL or not SB_KEY:
        print("SUPABASE_URL / SUPABASE_KEY not set"); return 2

    print(f"→ window {a.lo} … {a.hi}{'  [PILOT, no write]' if a.pilot else ''}")
    prices = load_prices((date.fromisoformat(a.lo) - timedelta(days=45)).isoformat(), a.hi)
    print(f"  prices: {len(prices)} symbols")
    pidx = {s: {d: i for i, (d, _, _) in enumerate(v)} for s, v in prices.items()}

    scores = _page("cis_scores", {
        "select": "symbol,recorded_at,score,grade,asset_class,macro_regime,las,confidence,"
                  "pillar_f,pillar_m,pillar_o,pillar_s,pillar_a",
        "recorded_at": f"gte.{a.lo}", "order": "symbol.asc,recorded_at.asc",
    })
    scores = [r for r in scores if r["recorded_at"][:10] <= a.hi]
    print(f"  cis_scores: {len(scores)} rows")

    # PIT-ordered pillar history per symbol — drives the v2 stability dims. Only
    # data at or before t may enter (I2), which the oldest→newest ordering gives.
    hist: dict = defaultdict(list)
    seen: set = set()
    out_rows, skipped_thin, skipped_nopillar = [], 0, 0

    for r in scores:
        sym, d = r["symbol"].upper(), r["recorded_at"][:10]
        if (sym, d) in seen:
            continue           # one row per symbol-day; first wins (earliest of the day)
        seen.add((sym, d))

        if r["pillar_f"] is None:
            skipped_nopillar += 1
            continue

        asset = {
            "symbol": sym, "asset_class": r.get("asset_class"),
            "cis_score": r.get("score"), "las": r.get("las"),
            "confidence": r.get("confidence"),
            "pillars": {"F": r["pillar_f"], "M": r["pillar_m"], "O": r["pillar_o"],
                        "S": r["pillar_s"], "A": r["pillar_a"]},
        }
        ser = prices.get(sym, [])
        i = pidx.get(sym, {}).get(d)
        if i is None and ser:
            i = max((k for k, (dd, _, _) in enumerate(ser) if dd <= d), default=None)
        if i is not None:
            asset.update(market_block(ser, i))

        prior = hist[sym][-1]["pillars"] if hist[sym] else None
        vec = generate_embedding(
            asset, macro_regime=r.get("macro_regime") or "Neutral",
            prior_pillars=prior, pillar_history=hist[sym][-20:] + [asset],
            unmeasured_as_nan=True,
        )
        hist[sym].append(asset)

        # S-178: honesty rules moved to embedder.py so BOTH writers of this table
        # share one definition. This file computed them inline and the Mac daily
        # push computed none — one honest writer and one not, on one table, which
        # is S-169's shape. The local MIN_MEASURED_DIMS above is kept only as the
        # documented origin of the value; the helpers are now the source.
        measured = measured_dims(vec)
        if is_thin(vec):
            skipped_thin += 1
            continue

        out_rows.append(vec_to_pg_row(
            d, sym, vec,
            asset_class=r.get("asset_class"),
            macro_regime=r.get("macro_regime"),
        ))

    print(f"  built {len(out_rows)} rows · skipped {skipped_nopillar} (no pillars) "
          f"· {skipped_thin} (<{MIN_MEASURED_DIMS} measured dims)")
    if out_rows:
        comp = sorted(r["measured_dims"] for r in out_rows)
        print(f"  measured_dims  min={comp[0]} p50={comp[len(comp)//2]} max={comp[-1]} "
              f"of {ASSET_DIMS_V2}")
        days = sorted({r['d'] for r in out_rows})
        print(f"  coverage: {len(days)} days {days[0]} → {days[-1]} · "
              f"{len({r['symbol'] for r in out_rows})} symbols")

    if a.pilot:
        print("PILOT — nothing written."); return 0

    for i in range(0, len(out_rows), 500):
        chunk = out_rows[i:i + 500]
        req = urllib.request.Request(
            f"{SB_URL}/rest/v1/asset_embeddings_history?on_conflict=d,symbol",
            data=json.dumps(chunk).encode(),
            headers={**HEAD, "Prefer": "resolution=merge-duplicates,return=minimal"},
            method="POST")
        with urllib.request.urlopen(req, timeout=120) as resp:
            if resp.status not in (200, 201, 204):
                print(f"  ✗ chunk {i} → HTTP {resp.status}"); return 1
        print(f"  ✓ wrote {i + len(chunk)}/{len(out_rows)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
