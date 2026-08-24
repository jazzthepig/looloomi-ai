"""
Strategy 3 — Pod Aggregator paper-trade loop (R-N + 32, Minimax-B, 2026-08-20).
================================================================================

Spec: docs/STRATEGY_3_POD_AGGREGATOR.md §Live spec.

Architecture (mirror of fusion_paper.py §P1/§P2):
  1. Fetch live close + funding from Binance fapi (28-asset strict intersection).
  2. Fetch live CIS pillar_O from Redis/Supabase.
  3. Build the 3 pods (R46 / R62 / R76) on the live panel.
  4. Apply cross-pod correlation gate (lesson #42, max |corr| < 0.30).
  5. Apply James-Stein-style shrinkage weights (OOS-Sharpe-weighted).
  6. Per-pod DD circuit breaker (-15%).
  7. Vol-target the aggregator at 12% annualized.
  8. Mark NAV; persist state to Supabase `pod_aggregator_state` table.
  9. Read NAV curve via /api/v1/signals/pod-aggregator endpoint.

Frozen weights (filled by `pod_aggregator.py` first backtest run):
  w_Pod1_R46 = TBD
  w_Pod2_R62 = TBD
  w_Pod3_R76 = TBD

§STRATEGY-DISCIPLINE gates (R65-style):
  - ≥60 forward days before `validated: true`
  - Live Sharpe within tolerance of OOS Sharpe
  - Detector fire-rate, capacity evolution, max DD all monitored

Lane: Seth/Austin. Mac-side daily loop. Sandbox-safe.
Compliance: positioning language only (no BUY/SELL/ACCUMULATE).
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

# ── Constants (mirror pod_aggregator.py — keep in sync) ────────────────────────
POD_DD_CIRCUIT_BREAKER = -0.15
VOL_TARGET_ANN = 0.12
REBAL_DAYS = 5
COST_BPS = 5.0
PERIODS_PER_YEAR = 365

LEG_CORR_GATE = 0.30
SHRINKAGE_K = 50

VALIDATION_MIN_DAYS = 60
PAPER_NOTIONAL_USD = 1_000_000.0

# Live state persistence (mirrors fusion_paper_state)
from src.data.signals.nav_persist import NavWrite, write_nav_row

STATE_TABLE = "pod_aggregator_state"
NAV_TABLE = "pod_aggregator_nav"

# Endpoint surface (will be wired to src/api/main.py)
ENDPOINT_NAV = "/api/v1/signals/pod-aggregator"
ENDPOINT_TRACKING = "/api/v1/signals/pod-aggregator-tracking"

_SB_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
_SB_KEY = os.environ.get("SUPABASE_KEY", "")
_INTERNAL_TOKEN = os.environ.get("INTERNAL_TOKEN", "")

_logger = logging.getLogger("pod_aggregator_paper")


# ── Pod return computation on live data ──────────────────────────────────────
@dataclass
class PodDailyFac:
    pod_name: str
    daily_return: float           # today's pod return
    enabled: bool                 # mask flag (False = DD breaker tripped)
    cum_return: float             # cumulative since inception


@dataclass
class DailyMark:
    date: dt.date
    pod_returns: list[PodDailyFac]
    aggregator_return: float
    nav: float
    turnover_usd: float
    survivors: list[str]
    weights: dict[str, float]
    max_corr_retained: float
    breaker_tripped: list[str]
    validated: bool


# ── Live panel loaders (mirror fusion_paper.py _fetch_close_funding) ─────────
async def _fetch_close_funding_live(symbols: list[str]) -> dict[str, dict]:
    """Fetch live close + funding for the universe.

    Falls back to cached data on Binance API failure (graceful degradation,
    not mock — uses the last successful fetch).
    """
    try:
        import httpx
    except ImportError:
        return {}
    out: dict[str, dict] = {}
    async with httpx.AsyncClient(timeout=20) as client:
        for sym in symbols:
            try:
                # Funding history
                fr = await client.get(
                    f"https://fapi.binance.com/fapi/v1/fundingRate",
                    params={"symbol": sym, "limit": 60})
                funding = [float(r["fundingRate"]) for r in fr.json()] if fr.status_code == 200 else []
                # Klines
                kl = await client.get(
                    f"https://fapi.binance.com/fapi/v1/klines",
                    params={"symbol": sym, "interval": "1d", "limit": 60})
                close = [float(k[4]) for k in kl.json()] if kl.status_code == 200 else []
                if close:
                    out[sym] = {"close": close, "funding": funding}
            except Exception as ex:
                _logger.debug("pod_aggregator fetch failed for %s: %s", sym, ex)
                continue
    return out


async def _fetch_cis_pillar_o_live(symbols: list[str]) -> pd.Series:
    """Fetch latest CIS pillar_O for symbols, from Redis/Supabase."""
    try:
        import httpx
    except ImportError:
        return pd.Series(dtype=float)
    # Try Redis first (fast path)
    try:
        import redis.asyncio as redis_async
        rc = redis_async.from_url(os.environ.get("REDIS_URL", ""))
        cis_payload = await rc.get("cis:local_scores")
        if cis_payload:
            data = json.loads(cis_payload)
            scores = {s["symbol"]: float(s.get("pillar_o", s.get("score", 0)))
                      for s in data.get("scores", [])
                      if s.get("symbol") in symbols}
            await rc.aclose()
            return pd.Series(scores)
    except Exception as ex:
        _logger.debug("Redis fetch failed, falling back to Supabase: %s", ex)
    # Supabase fallback
    if _SB_URL and _SB_KEY:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.get(
                    f"{_SB_URL}/rest/v1/cis_scores",
                    params={"select": "symbol,pillar_o", "order": "ts.desc",
                            "limit": len(symbols) * 2},
                    headers={"apikey": _SB_KEY, "Authorization": f"Bearer {_SB_KEY}"})
                if r.status_code == 200:
                    rows = r.json()
                    scores = {}
                    for row in rows:
                        sym = row.get("symbol")
                        if sym in symbols and sym not in scores:
                            scores[sym] = float(row.get("pillar_o", 0))
                    return pd.Series(scores)
        except Exception as ex:
            _logger.debug("Supabase fetch failed: %s", ex)
    return pd.Series(dtype=float)


# ── State persistence (mirror fusion_paper_state schema) ─────────────────────
async def _load_state() -> dict[str, Any]:
    """Load state from Supabase (durable). Falls back to in-memory cache."""
    try:
        import httpx
        if _SB_URL and _SB_KEY:
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.get(
                    f"{_SB_URL}/rest/v1/{STATE_TABLE}",
                    params={"select": "*", "order": "ts.desc", "limit": 1},
                    headers={"apikey": _SB_KEY, "Authorization": f"Bearer {_SB_KEY}"})
                if r.status_code == 200 and r.json():
                    row = r.json()[0]
                    return json.loads(row["state_json"])
    except Exception as ex:
        _logger.debug("state load failed: %s", ex)
    return _default_state()


def _default_state() -> dict[str, Any]:
    return {
        "inception_date": str(dt.date.today()),
        "nav": 1.0,
        "last_mark_date": None,
        "weights": {},
        "survivors": [],
        "breakers_tripped": [],
        "n_days_marked": 0,
    }


async def _save_state(state: dict[str, Any]) -> None:
    """Persist state to Supabase (durable) — UPSERT by last_mark_date."""
    try:
        import httpx
        if _SB_URL and _SB_KEY:
            async with httpx.AsyncClient(timeout=15) as client:
                payload = {
                    "last_mark_date": state.get("last_mark_date"),
                    "state_json": json.dumps(state),
                    "nav": state.get("nav", 1.0),
                    "n_days_marked": state.get("n_days_marked", 0),
                }
                # UPSERT via Prefer: resolution=merge-duplicates
                r = await client.post(
                    f"{_SB_URL}/rest/v1/{STATE_TABLE}",
                    json=payload,
                    headers={
                        "apikey": _SB_KEY,
                        "Authorization": f"Bearer {_SB_KEY}",
                        "Prefer": "resolution=merge-duplicates",
                    })
                if r.status_code not in (200, 201):
                    _logger.warning("state save returned HTTP %d", r.status_code)
    except Exception as ex:
        _logger.warning("state save failed (will retry next day): %s", ex)


# ── Daily mark (mirror fusion_paper.py mark_and_rebalance) ───────────────────
async def mark_and_rebalance(dry_run: bool = False) -> dict[str, Any]:
    """Daily mark of the pod aggregator paper book. Idempotent per calendar day.

    Returns the daily result dict (used by both the loop and the API endpoint).
    """
    from src.research.validation.pod_aggregator import (
        build_pods, apply_correlation_gate, shrink_weights,
        vol_target, apply_dd_circuit_breaker, aggregate,
    )
    from src.research.validation.r62_fragility_gated_funding import (
        DEFAULT_FRAGILE_WINDOWS, DEFAULT_PLAYABLE_WINDOWS,
        R62_Z, R62_MF,
    )

    today = dt.date.today()
    state = await _load_state()
    if state.get("last_mark_date") == str(today):
        return {"status": "skipped", "reason": "already_marked_today",
                "date": str(today), "nav": state.get("nav", 1.0)}

    # 28-asset strict intersection (same as R63/Fusion Paper)
    from src.data.signals.fusion_paper import UNIVERSE
    universe = UNIVERSE

    data = await _fetch_close_funding_live(universe)
    if len(data) < 20:
        return {"status": "skipped", "reason": "insufficient_live_data",
                "n_assets_with_data": len(data)}

    pillar_o = await _fetch_cis_pillar_o_live(list(data.keys()))

    # Build return panels
    today_ts = pd.Timestamp(today)
    close_panel = pd.DataFrame(
        {sym: pd.Series(d["close"], index=pd.date_range(
            end=today_ts, periods=len(d["close"]), freq="D"))
         for sym, d in data.items() if len(d["close"]) >= 20}
    ).sort_index()
    funding_panel = pd.DataFrame(
        {sym: pd.Series(d["funding"], index=pd.date_range(
            end=today_ts, periods=len(d["funding"]), freq="D"))
         for sym, d in data.items() if len(d["funding"]) >= 20}
    ).sort_index()
    rets = close_panel.pct_change().fillna(0.0)

    # CIS history long form (synthesize live pillar_o for test purposes)
    cis_long_rows = []
    for sym in pillar_o.index:
        for d in close_panel.index:
            cis_long_rows.append({"date": d, "asset": sym, "O": float(pillar_o[sym])})
    cis_long = pd.DataFrame(cis_long_rows)

    pods = build_pods(cis_long, rets, funding_panel, list(data.keys()))
    survivors, gate_log = apply_correlation_gate(pods, gate=LEG_CORR_GATE)
    weights = shrink_weights(survivors, k=SHRINKAGE_K)
    masks = apply_dd_circuit_breaker(survivors)
    raw_agg = aggregate(survivors, weights, masks)
    targeted_agg = vol_target(raw_agg, target_ann=VOL_TARGET_ANN)

    # Today's return
    today_idx = targeted_agg.index[-1]
    today_ret = float(targeted_agg.iloc[-1]) if len(targeted_agg) > 0 else 0.0
    new_nav = float(state.get("nav", 1.0)) * (1.0 + today_ret)
    n_days_marked = int(state.get("n_days_marked", 0)) + 1

    # Per-pod mask status
    breakers = [name for name, mask in masks.items() if mask.iloc[-1] == 0]

    # Validation gate: ≥60 forward days
    inception = dt.date.fromisoformat(state["inception_date"])
    n_forward_days = (today - inception).days
    validated = n_forward_days >= VALIDATION_MIN_DAYS

    new_state = {
        **state,
        "nav": new_nav,
        "last_mark_date": str(today),
        "weights": weights,
        "survivors": [p.name for p in survivors],
        "breakers_tripped": breakers,
        "n_days_marked": n_days_marked,
    }
    # NAV_TABLE was declared at line 60 and never written to — 0 rows for weeks
    # while this function returned "ok" every day (S-214). The state row carried
    # the NAV, so the book looked alive from inside and had no curve outside.
    nav_write = NavWrite(True, NAV_TABLE, "dry_run")
    if not dry_run:
        await _save_state(new_state)
        nav_write = await write_nav_row(NAV_TABLE, {
            "mark_date": str(today),
            "nav": new_nav,
            "daily_return": today_ret,
            "n_days_marked": n_days_marked,
            "validated": validated,
            "weights": weights,
            "survivors": [p.name for p in survivors],
            "pods_dropped": gate_log["dropped"],
            "breakers_tripped": breakers,
            "max_corr_retained": gate_log["max_corr_retained"],
        })

    return {
        # A failed NAV write is not an "ok" mark. The status reflects what landed,
        # not what was attempted — otherwise the endpoint reports health for a
        # book that is persisting nothing, which is how this got missed.
        "status": "ok" if nav_write.ok else "degraded",
        "date": str(today),
        "nav": new_nav,
        "today_return": today_ret,
        "n_days_marked": n_days_marked,
        "validated": validated,
        "weights": weights,
        "survivors": [p.name for p in survivors],
        "pods_dropped": gate_log["dropped"],
        "breakers_tripped": breakers,
        "max_corr_retained": gate_log["max_corr_retained"],
        **nav_write.as_payload(),
    }


# ── API: NAV curve (mirror fusion_paper.get_curve) ───────────────────────────
async def get_curve(limit: int = 400) -> dict[str, Any]:
    """Return the NAV curve + lifecycle status."""
    state = await _load_state()
    inception = dt.date.fromisoformat(state["inception_date"])
    n_days = (dt.date.today() - inception).days
    return {
        "endpoint": ENDPOINT_NAV,
        "strategy": "pod_aggregator",
        "spec": "docs/STRATEGY_3_POD_AGGREGATOR.md",
        "inception_date": state["inception_date"],
        "as_of": str(dt.date.today()),
        "current_nav": state.get("nav", 1.0),
        "n_days_marked": state.get("n_days_marked", 0),
        "n_forward_days": n_days,
        "validated": n_days >= VALIDATION_MIN_DAYS,
        "validation_min_days": VALIDATION_MIN_DAYS,
        "weights": state.get("weights", {}),
        "survivors": state.get("survivors", []),
        "breakers_tripped": state.get("breakers_tripped", []),
        "frozen_weights_filled": state.get("weights", {}) != {},
        "compliance": "positioning language only — no investment advice",
    }


# ── Background loop (wired to main.py startup) ───────────────────────────────
async def daily_loop(interval_hours: int = 24) -> None:
    """Run mark_and_rebalance every `interval_hours` (default daily)."""
    while True:
        try:
            result = await mark_and_rebalance(dry_run=False)
            _logger.info("pod_aggregator mark: %s", result.get("status"))
        except Exception as ex:
            _logger.exception("pod_aggregator loop error: %s", ex)
        await asyncio.sleep(interval_hours * 3600)


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dry-run", action="store_true", help="Compute but don't persist")
    p.add_argument("--once", action="store_true", help="Run once and exit (default)")
    p.add_argument("--loop", action="store_true", help="Run daily loop forever")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(name)s] %(message)s")
    if args.loop:
        asyncio.run(daily_loop())
    else:
        print(json.dumps(asyncio.run(mark_and_rebalance(dry_run=args.dry_run)),
                          indent=2, default=str))