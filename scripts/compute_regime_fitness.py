#!/usr/bin/env python3
"""
CometCloud CIS — Regime Fitness Calculator
==========================================
Computes Pearson correlation between each pillar score and 7-day realized return
for every macro regime. Populates the cis_regime_fitness table.

This is the Simons feedback loop: which pillar actually predicts returns in each regime?
Dynamic pillar weight adjustment in CIS v4 engine uses these correlations.

Return computation priority:
  1. trade_results.realized_return_7d  — actual Freqtrade fills (gold standard)
  2. CoinGecko price return              — actual market return via CG market_chart API
  3. score-change proxy                  — METHODOLOGICALLY FLAWED, last resort only

Only return sources 1 and 2 are valid for Simons validation. Source 3 is flagged
with return_source="score_proxy" so results can be weighted accordingly.

Usage:
    python scripts/compute_regime_fitness.py
    python scripts/compute_regime_fitness.py --window 30   # days of history to use
    python scripts/compute_regime_fitness.py --dry-run     # print results, don't write

Requirements:
    pip install httpx python-dotenv

Environment:
    SUPABASE_URL  — Supabase project URL
    SUPABASE_KEY  — Anon or service role key
    COINGECKO_API_KEY — Optional: CoinGecko Pro API key (higher rate limits)

Author: Seth
"""

import argparse
import json
import math
import os
import sys
import time
from datetime import datetime, timezone, date, timedelta
from typing import Optional

import httpx
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY", os.getenv("SUPABASE_KEY", ""))
CG_API_KEY = os.getenv("COINGECKO_API_KEY", "")

#: S-202. Minimum DISTINCT DAYS before an IC is reported. Not a pair count —
#: assets co-move, so N names on one day is closer to one observation than to N.
#: 20 is chosen to be plainly insufficient-until-it-is-not rather than tuned:
#: with 6 days available today the honest output is "not yet", and that is the
#: output we want, stated, rather than a number nobody can defend.
MIN_INDEPENDENT_DAYS = 20

PILLARS = ["pillar_f", "pillar_m", "pillar_o", "pillar_s", "pillar_a"]
PILLAR_LABELS = {"pillar_f": "F", "pillar_m": "M", "pillar_o": "O", "pillar_s": "S", "pillar_a": "A"}

# CoinGecko ID mapping for top assets (from cis_v4_engine)
CG_IDS = {
    "BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana", "BNB": "binancecoin",
    "XRP": "ripple", "ADA": "cardano", "DOGE": "dogecoin", "DOT": "polkadot",
    "AVAX": "avalanche-2", "LINK": "chainlink", "MATIC": "polygon",
    "UNI": "uniswap", "AAVE": "aave", "MKR": "maker", "SNX": "havven",
    "LTC": "litecoin", "BCH": "bitcoin-cash", "ATOM": "cosmos",
    "NEAR": "near", "FTM": "fantom", "OP": "optimism", "ARB": "arbitrum",
    "LDO": "lido-dao", "CBETH": "coinbase-wrapped-staked-ether",
    "EUR": "euro", "JPY": "japanese-yen", "GBP": "british-pound",
    "GLD": "gold", "SPY": "spdr-s-p-500-trust", "TLT": "ishares-20-year-treasury-bond-etf",
}

# ── Supabase helpers ───────────────────────────────────────────────────────────

def sb_get(path: str, params: dict = None) -> dict:
    """GET from Supabase REST API."""
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }
    url = f"{SUPABASE_URL}/rest/v1/{path}"
    r = httpx.get(url, headers=headers, params=params, timeout=60)
    r.raise_for_status()
    return r.json()


def sb_post(path: str, payload: list) -> dict:
    """POST (upsert) to Supabase REST API."""
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }
    url = f"{SUPABASE_URL}/rest/v1/{path}"
    r = httpx.post(url, headers=headers, json=payload, timeout=60)
    r.raise_for_status()
    return r


# ── CoinGecko helpers ─────────────────────────────────────────────────────────

def cg_headers() -> dict:
    headers = {"Accept": "application/json", "User-Agent": "CometCloud/1.0"}
    if CG_API_KEY:
        headers["x-cg-pro-api-key"] = CG_API_KEY
    return headers


def cg_price_return(cg_id: str, target_ts: int) -> Optional[float]:
    """
    Fetch CoinGecko market_chart and compute 7d price return at target_ts.
    Returns price(t+7d)/price(t) - 1 or None if data unavailable.
    target_ts is unix timestamp for the entry date.
    """
    base = "https://pro-api.coingecko.com/api/v3" if CG_API_KEY else "https://api.coingecko.com/api/v3"
    url = f"{base}/coins/{cg_id}/market_chart"
    params = {"vs_currency": "usd", "days": "40", "interval": "daily"}
    try:
        resp = httpx.get(url, headers=cg_headers(), params=params, timeout=15)
        if resp.status_code != 200:
            return None
        data = resp.json()
        prices = data.get("prices", [])
        if not prices:
            return None
        # Build a ts→price dict
        price_map: dict[int, float] = {}
        for ts, price in prices:
            price_map[int(ts // 1000)] = price
        # Find price at target_ts
        if target_ts not in price_map:
            # find nearest within 1 day
            candidates = [t for t in price_map if abs(t - target_ts) <= 86400]
            if not candidates:
                return None
            target_ts = min(candidates, key=lambda t: abs(t - target_ts))
        price_t = price_map[target_ts]
        # Find price at target_ts + 7 days (±2 days tolerance)
        target_future = target_ts + 7 * 86400
        candidates = [t for t in price_map if abs(t - target_future) <= 2 * 86400]
        if not candidates:
            return None
        future_ts = min(candidates, key=lambda t: abs(t - target_future))
        price_future = price_map[future_ts]
        if price_t <= 0:
            return None
        return (price_future - price_t) / price_t
    except Exception:
        return None


# ── Stats helpers ──────────────────────────────────────────────────────────────

def pearson_r(xs: list[float], ys: list[float]) -> Optional[float]:
    """Pearson correlation coefficient. Returns None if < 3 pairs."""
    n = len(xs)
    if n < 3:
        return None
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    den_x = math.sqrt(sum((x - mean_x) ** 2 for x in xs))
    den_y = math.sqrt(sum((y - mean_y) ** 2 for y in ys))
    if den_x == 0 or den_y == 0:
        return None
    return num / (den_x * den_y)


# ── Data fetching ────────────────────────────────────────────────────────────────

def fetch_trade_results(window_days: int) -> dict:
    """
    Fetch trade_results with realized_return_7d.
    Returns {symbol: {entry_time: realized_return_7d, ...}}
    """
    print(f"  Fetching trade_results (window={window_days}d)...")
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=window_days)).isoformat()
        rows = sb_get("trade_results", {
            "select": "symbol,entry_time,realized_return_7d",
            "realized_return_7d": "not.is.null",
            "entry_time": f"gte.{cutoff}",
        })
        result: dict = {}
        for row in rows:
            sym = row.get("symbol", "").upper()
            entry = row.get("entry_time", "")[:10]
            ret = row.get("realized_return_7d")
            if sym and entry and ret is not None:
                result.setdefault(sym, {})[entry] = ret
        print(f"  → {len(rows)} trade_results rows with realized_return_7d")
        return result
    except Exception as e:
        print(f"  → trade_results query failed: {e}")
        return {}


def fetch_historical_rows(window_days: int) -> list[dict]:
    """
    Fetch cis_scores rows that:
      - have a non-null macro_regime
      - have pillar scores
      - are within the window
    """
    print(f"  Fetching cis_scores rows (window={window_days}d, needs macro_regime)...")
    all_rows = []
    offset = 0
    page_size = 1000
    cutoff = (datetime.now(timezone.utc) - timedelta(days=window_days)).isoformat()

    while True:
        params = {
            "select": "symbol,score,pillar_f,pillar_m,pillar_o,pillar_s,pillar_a,macro_regime,recorded_at",
            "macro_regime": "not.is.null",
            "pillar_f": "not.is.null",
            "recorded_at": f"gte.{cutoff}",
            "order": "symbol.asc,recorded_at.asc",
            "limit": str(page_size),
            "offset": str(offset),
        }
        page = sb_get("cis_scores", params)
        if not page:
            break
        all_rows.extend(page)
        if len(page) < page_size:
            break
        offset += page_size

    print(f"  → {len(all_rows)} rows with macro_regime + pillars")
    return all_rows


def compute_7d_returns(rows: list[dict], trade_results: dict) -> list[dict]:
    """
    Compute 7-day realized return for each cis_scores row.

    Priority:
      1. trade_results.realized_return_7d  — actual fills from Freqtrade
      2. CoinGecko price return            — actual market return
      3. score-change proxy                — METHODOLOGICALLY FLAWED (flagged)

    Returns enriched list with `return_7d` and `return_source` fields.
    """
    # Pre-fetch CoinGecko price data per symbol (batch 30d chart per symbol)
    cg_cache: dict = {}   # symbol → {ts: price}
    symbols_with_cg = set()
    rate_limited = False

    for row in rows:
        sym = row["symbol"].upper()
        if sym not in CG_IDS or sym in symbols_with_cg:
            continue
        if rate_limited:
            break
        cg_id = CG_IDS[sym]
        entry_ts_str = row["recorded_at"]
        try:
            entry_ts = int(datetime.fromisoformat(entry_ts_str.replace("Z", "+00:00")).timestamp())
        except Exception:
            continue
        prices = _fetch_cg_prices(cg_id, entry_ts)
        if prices is None:
            rate_limited = True
            continue
        cg_cache[sym] = prices
        symbols_with_cg.add(sym)
        time.sleep(0.5)  # rate limit

    enriched = []
    sources = {"trade_results": 0, "coingecko_price": 0, "score_proxy": 0}

    by_symbol: dict = {}
    for row in rows:
        sym = row["symbol"].upper()
        by_symbol.setdefault(sym, []).append(row)

    for sym, sym_rows in by_symbol.items():
        sym_rows.sort(key=lambda r: r["recorded_at"])
        n = len(sym_rows)

        # Build CG price map if available
        cg_prices = cg_cache.get(sym, {}) if sym in symbols_with_cg else {}

        for i, row in enumerate(sym_rows):
            entry_date = row["recorded_at"][:10]
            return_7d = None
            source = None

            # 1. Try trade_results
            trade_map = trade_results.get(sym, {})
            if entry_date in trade_map:
                return_7d = trade_map[entry_date]
                source = "trade_results"
                sources["trade_results"] += 1

            # 2. Try CoinGecko price return
            elif sym in CG_IDS and cg_prices:
                try:
                    entry_ts = int(datetime.fromisoformat(row["recorded_at"].replace("Z", "+00:00")).timestamp())
                except Exception:
                    entry_ts = None
                if entry_ts and entry_ts in cg_prices:
                    price_t = cg_prices[entry_ts]
                    future_ts = entry_ts + 7 * 86400
                    # Find nearest future price within 2 days
                    candidates = [t for t in cg_prices if abs(t - future_ts) <= 2 * 86400]
                    if candidates:
                        future_ts_nearest = min(candidates, key=lambda t: abs(t - future_ts))
                        price_future = cg_prices[future_ts_nearest]
                        if price_t > 0:
                            return_7d = (price_future - price_t) / price_t
                            source = "coingecko_price"
                            sources["coingecko_price"] += 1

            # 3. Score-change proxy (METHODOLOGICALLY FLAWED — flagged)
            if return_7d is None:
                target_dt = row["recorded_at"][:10]
                future_score = None
                for j in range(i + 1, min(i + 12, n)):
                    future_dt = sym_rows[j]["recorded_at"][:10]
                    d0 = date.fromisoformat(target_dt)
                    d1 = date.fromisoformat(future_dt)
                    delta = (d1 - d0).days
                    if 6 <= delta <= 8:
                        future_score = sym_rows[j].get("score")
                        break
                if future_score is not None and row.get("score") and row["score"] > 0:
                    return_7d = (future_score - row["score"]) / row["score"]
                    source = "score_proxy"
                    sources["score_proxy"] += 1

            enriched.append({**row, "return_7d": return_7d, "return_source": source})

    total = len(enriched)
    valid = sources["trade_results"] + sources["coingecko_price"]
    print(f"  Return sources: {valid}/{total} valid (trade_results={sources['trade_results']}, "
          f"coingecko={sources['coingecko_price']}, score_proxy={sources['score_proxy']})")
    return enriched


def _fetch_cg_prices(cg_id: str, anchor_ts: int) -> Optional[dict]:
    """Fetch 40d daily prices from CoinGecko. Returns {ts: price}."""
    base = "https://pro-api.coingecko.com/api/v3" if CG_API_KEY else "https://api.coingecko.com/api/v3"
    url = f"{base}/coins/{cg_id}/market_chart"
    params = {"vs_currency": "usd", "days": "40", "interval": "daily"}
    try:
        resp = httpx.get(url, headers=cg_headers(), params=params, timeout=15)
        if resp.status_code == 429:
            return None
        if resp.status_code != 200:
            return None
        prices = resp.json().get("prices", [])
        return {int(ts // 1000): price for ts, price in prices}
    except Exception:
        return None


def compute_fitness(rows: list[dict], window_days: int) -> list[dict]:
    """
    For each (regime, pillar, return_source) combination, compute Pearson r vs 7d return.
    Writes to cis_regime_fitness. Marks source="score_proxy" clearly so weights
    derived from it are flagged as unvalidated.
    """
    usable = [r for r in rows if r.get("return_7d") is not None]
    print(f"\n  Rows with 7d return: {len(usable)} / {len(rows)}")

    by_regime: dict = {}
    for row in usable:
        reg = row["macro_regime"]
        by_regime.setdefault(reg, []).append(row)

    results = []
    now = datetime.now(timezone.utc).isoformat()

    for regime, regime_rows in sorted(by_regime.items()):
        n = len(regime_rows)
        print(f"\n  Regime: {regime} ({n} samples)")
        for pillar_col in PILLARS:
            label = PILLAR_LABELS[pillar_col]
            for source in ["trade_results", "coingecko_price", "score_proxy"]:
                filtered = [r for r in regime_rows if r.get("return_source") == source]
                if len(filtered) < 5:
                    continue
                xs = [r[pillar_col] for r in filtered if r.get(pillar_col) is not None]
                ys = [r["return_7d"] for r in filtered
                      if r.get(pillar_col) is not None and r["return_7d"] is not None]
                pairs = [(x, y) for x, y in zip(xs, ys) if y is not None]
                if len(pairs) < 5:
                    continue

                # ── S-202: the unit of independence is the DAY ───────────────
                # `len(pairs) >= 5` passes on five observations from ONE day.
                # Measured 2026-08-23 after backfilling realized_return_7d: the
                # RISK_ON bucket held 23 observations spanning a single day, and
                # its five pillar ICs came out IDENTICAL at −0.017 — the
                # signature of a collapsed cross-section, not five findings.
                # TIGHTENING held 64 observations across six days.
                #
                # Assets move together. Twenty-three names on one day is closer
                # to one observation than to twenty-three, so a pair count
                # overstates the sample by roughly the width of the panel. An IC
                # computed on it is noise, and feeding it into a weight
                # multiplier would tilt CIS on that noise — worse than the
                # neutral weights it replaces, because neutral is at least
                # honest about knowing nothing.
                _days = {r.get("recorded_at", "")[:10] for r in filtered
                         if r.get(pillar_col) is not None and r.get("return_7d") is not None}
                _days.discard("")
                if len(_days) < MIN_INDEPENDENT_DAYS:
                    print(f"    Pillar {label} ({source}): SKIPPED — {len(pairs)} pairs "
                          f"but only {len(_days)} independent day(s), floor is "
                          f"{MIN_INDEPENDENT_DAYS}")
                    continue
                xs_c = [p[0] for p in pairs]
                ys_c = [p[1] for p in pairs]
                r = pearson_r(xs_c, ys_c)
                if r is None:
                    continue
                flag = " [SCORE PROXY - UNVALIDATED]" if source == "score_proxy" else ""
                print(f"    Pillar {label} ({source}): r={r:+.3f} (n={len(pairs)}){flag}")
                results.append({
                    "regime": regime,
                    "pillar": label,
                    "correlation": round(r, 4),
                    "n_samples": len(pairs),
                    "return_source": source,
                    "window_days": window_days,
                    "computed_at": now,
                })

    return results


def main():
    parser = argparse.ArgumentParser(description="CometCloud CIS Regime Fitness Calculator")
    parser.add_argument("--window", type=int, default=90, help="Days of history to analyze (default 90)")
    parser.add_argument("--dry-run", action="store_true", help="Print results, don't write to Supabase")
    args = parser.parse_args()

    if not SUPABASE_URL or not SUPABASE_KEY:
        print("ERROR: SUPABASE_URL and SUPABASE_KEY must be set")
        sys.exit(1)

    print("=" * 60)
    print("  CometCloud CIS — Regime Fitness Calculator")
    print(f"  Window: {args.window}d | Dry run: {args.dry_run}")
    print("=" * 60)
    print()

    print("[1/4] Fetching trade_results (realized_return_7d)...")
    trade_results = fetch_trade_results(args.window)

    print("\n[2/4] Fetching cis_scores historical rows...")
    rows = fetch_historical_rows(args.window)
    if not rows:
        print("  No rows with macro_regime found. Run reconstruct_cis_history.py first.")
        sys.exit(1)

    print("\n[3/4] Computing 7-day returns (priority: trade_results → CG → score proxy)...")
    rows = compute_7d_returns(rows, trade_results)

    print("\n[4/4] Computing pillar correlations per regime...")
    fitness_rows = compute_fitness(rows, args.window)

    print(f"\n  Results: {len(fitness_rows)} (regime, pillar, source) pairs")

    if args.dry_run:
        print("\n  [DRY RUN] Would insert:")
        for row in sorted(fitness_rows, key=lambda r: (r["regime"], r["pillar"])):
            flag = " [UNVALIDATED]" if row["return_source"] == "score_proxy" else ""
            print(f"    {row['regime']:15s} | {row['pillar']} | "
                  f"r={row['correlation']:+.3f} | n={row['n_samples']} | {row['return_source']}{flag}")
        return

    if not fitness_rows:
        print("  Nothing to insert.")
        return

    # Only write rows from validated sources unless --include-proxy
    validated = [r for r in fitness_rows if r["return_source"] != "score_proxy"]
    proxy_rows = [r for r in fitness_rows if r["return_source"] == "score_proxy"]

    if validated:
        print(f"\n  Writing {len(validated)} validated rows to cis_regime_fitness...")
        sb_post("cis_regime_fitness", validated)
        print(f"  ✓ {len(validated)} rows inserted")
    if proxy_rows:
        print(f"  {len(proxy_rows)} score_proxy rows NOT inserted (methodologically invalid). "
              "Run with --include-proxy to force insert.")
        print("  Score-proxy correlations are flagged in return_source column for transparency.")

    print("\nDone.")
    print("  → cis_regime_fitness table updated. Freqtrade reads pillar weights per regime from here.")
    print("  → Only trade_results + CoinGecko price returns are valid Simons inputs.")
    print("  → Re-run weekly as more trade data accumulates.")


if __name__ == "__main__":
    main()
