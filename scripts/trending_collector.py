#!/usr/bin/env python3
"""
D4 — attention-diffusion (出圈) collector. Uses CoinGecko FULLY (we pay for Pro — use it):
  1. `search/trending`          → retail-attention rank
  2. `/coins/{id}` community     → twitter / reddit / telegram crowd size
  3. `/coins/{id}` sentiment     → up/down vote skew (herd euphoria)
  4. `/coins/{id}` watchlist     → how many CG users are watching (attention stock)

Per METHODOLOGY_CORE §3 + ARCHITECTURE 大象无形: the danger is when attention has diffused
OUT of the informed circle to the mass — sharpest tell is a LOW-market-cap asset sitting
HIGH in retail trending AND with euphoric sentiment + a swelling watchlist (mass FOMO into
a niche: the gold / single-hot-stock / all-in-memecoin pattern). Mega-caps trending is
normal; a rank-200 coin at #1 trending with 90% up-votes is the out-of-circle alarm.

Forward-accumulating: trending/sentiment are current snapshots (no history), so we log
daily → attention HISTORY builds going forward (persistence + climb become usable).
Landing uses the backend service_role write path (anon writes revoked post-§SEC), so the
daily loop runs on Railway; also runnable standalone for the logic.

SOURCE POLICY (DATA_CAPTURE_SPEC, aligned 2026-06-25): CoinGecko Pro is primary. If
COINGECKO_API_KEY is set we hit the Pro host (pro-api) for rate headroom; else the free
host (community_data / sentiment_votes / watchlist_portfolio_users are on free too).
"""
import math
import os
from datetime import datetime, timezone

import httpx

_KEY = os.getenv("COINGECKO_API_KEY", "").strip()
_BASE = "https://pro-api.coingecko.com/api/v3" if _KEY else "https://api.coingecko.com/api/v3"
_HEADERS = {"x-cg-pro-api-key": _KEY} if _KEY else {}


def _get(path: str, params: dict = None) -> dict:
    r = httpx.get(f"{_BASE}{path}", params=params or {}, headers=_HEADERS, timeout=25)
    r.raise_for_status()
    return r.json()


def fetch_trending() -> list:
    out = []
    for c in _get("/search/trending").get("coins", []):
        it = c.get("item", {})
        out.append({
            "symbol": (it.get("symbol") or "").upper(),
            "coingecko_id": it.get("id"),
            "trending_rank": (it.get("score") or 0) + 1,   # 1 = most-trending
            "market_cap_rank": it.get("market_cap_rank"),
        })
    return out


def fetch_community(coingecko_id: str) -> dict:
    """Per-coin attention depth: sentiment vote skew + watchlist users + social reach.
    Best-effort — returns {} on any error so the daily loop never breaks on one coin."""
    try:
        d = _get(f"/coins/{coingecko_id}", {
            "localization": "false", "tickers": "false", "market_data": "false",
            "community_data": "true", "developer_data": "false", "sparkline": "false",
        })
        comm = d.get("community_data", {}) or {}
        return {
            "sentiment_up": d.get("sentiment_votes_up_percentage"),      # 0..100
            "watchlist_users": d.get("watchlist_portfolio_users"),
            "twitter_followers": comm.get("twitter_followers"),
            "reddit_subscribers": comm.get("reddit_subscribers"),
            "telegram_users": comm.get("telegram_channel_user_count"),
        }
    except Exception:
        return {}


def attention_score(trending_rank: int, market_cap_rank, sentiment_up=None) -> float:
    """0..1. High when a LOW-cap asset is HIGH in trending (mass FOMO into a niche =
    out-of-circle), amplified by euphoric one-sided sentiment. Mega-caps trending → low."""
    pos = max(0.0, 1.0 - (trending_rank - 1) / 15.0)        # #1 → 1.0, #15 → ~0.07
    niche = 0.5 if not market_cap_rank else min(1.0, math.log10(market_cap_rank) / 3.0)
    base = pos * niche
    # euphoria amplifier: one-sided up-votes (>70%) push attention toward the danger end
    if sentiment_up is not None:
        euphoria = max(0.0, (sentiment_up - 50.0) / 50.0)   # 50% → 0, 100% → 1
        base *= (1.0 + 0.5 * euphoria)                       # up to +50%
    return round(min(1.0, base), 4)


def trending_rows(date_iso: str = None, enrich: bool = True) -> list:
    date_iso = date_iso or datetime.now(timezone.utc).isoformat()
    rows = []
    for t in fetch_trending():
        comm = fetch_community(t["coingecko_id"]) if (enrich and t.get("coingecko_id")) else {}
        rows.append({
            "recorded_at": date_iso,
            "symbol": t["symbol"],
            "coingecko_id": t["coingecko_id"],
            "trending_rank": t["trending_rank"],
            "market_cap_rank": t["market_cap_rank"],
            "attention_score": attention_score(t["trending_rank"], t["market_cap_rank"],
                                                comm.get("sentiment_up")),
            "sentiment_up": comm.get("sentiment_up"),
            "watchlist_users": comm.get("watchlist_users"),
            "twitter_followers": comm.get("twitter_followers"),
            "reddit_subscribers": comm.get("reddit_subscribers"),
            "telegram_users": comm.get("telegram_users"),
            "source": "coingecko_pro" if _KEY else "coingecko_free",
        })
    return rows


async def collect_trending() -> dict:
    """Land today's trending snapshot into Supabase `trending_log` (service_role, Railway)."""
    from src.api.store import supabase_insert_table
    rows = trending_rows()
    if not rows:
        return {"ok": False, "rows": 0}
    ok = await supabase_insert_table("trending_log", rows)
    return {"ok": bool(ok), "rows": len(rows)}


# ── CREATE TABLE (run once in Supabase SQL editor; anon has no write — service_role only) ──
CREATE_SQL = """
create table if not exists trending_log (
  id bigserial primary key,
  recorded_at timestamptz not null default now(),
  symbol text not null,
  coingecko_id text,
  trending_rank int,
  market_cap_rank int,
  attention_score real,
  sentiment_up real,
  watchlist_users bigint,
  twitter_followers bigint,
  reddit_subscribers bigint,
  telegram_users bigint,
  source text default 'coingecko'
);
create index if not exists idx_trending_recorded on trending_log(recorded_at desc);
create index if not exists idx_trending_symbol on trending_log(symbol, recorded_at desc);
alter table trending_log enable row level security;
drop policy if exists trending_select on trending_log;
create policy trending_select on trending_log for select using (true);  -- public read; writes = service_role only
"""


if __name__ == "__main__":
    rows = trending_rows()
    src = rows[0]["source"] if rows else "n/a"
    print(f"trending snapshot ({src}) — {len(rows)} coins (high score = low-cap trending high + euphoric = 出圈 risk):")
    print(f"  {'SYM':8} {'trend':>5} {'cap':>6} {'sent%':>6} {'watch':>9}  attention")
    for r in sorted(rows, key=lambda x: -x["attention_score"])[:10]:
        print(f"  {r['symbol']:8} #{r['trending_rank']:<4} {str(r['market_cap_rank']):>6} "
              f"{str(r['sentiment_up']):>6} {str(r['watchlist_users']):>9}  {r['attention_score']}")
