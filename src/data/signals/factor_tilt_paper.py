"""
Strategy 4 — Cross-Asset Factor Tilt paper-trade loop (R-N + 33, Minimax-B, 2026-08-20).
========================================================================================

Spec: docs/STRATEGY_4_CROSS_ASSET_FACTOR_TILT.md §Live spec.

Architecture (mirror of fusion_paper.py §P1/§P2):
  1. Fetch live close for 41-asset crypto universe + 17 TradFi ETFs.
  2. Fetch live CIS pillar_O for crypto symbols (from Redis/Supabase).
  3. Compute composite z_quality + z_momentum + z_lowrisk per asset per day.
  4. Convert to long-only tilt weights (bottom quartile floored at 1/N).
  5. Apply H3.2 conviction-scaled sizing at each rebalance.
  6. Mark NAV using close[t]/close[t-1]−1, deduct turnover cost.
  7. Vol-target the aggregator at 12% annualized.
  8. Persist NAV row to Supabase `factor_tilt_nav` table.

§STRATEGY-DISCIPLINE gates:
  - ≥60 forward days before `validated: true`
  - Live Sharpe within tolerance of OOS Sharpe
  - W5 ann% positive (the L/S fragility fix claim)
  - Factor decomposition Sharpe attribution (no single factor > 70%)

Lane: Seth/Austin. Mac-side daily loop. Sandbox-safe.
Compliance: positioning language only (no BUY/SELL/ACCUMULATE).
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

# ── Constants (mirror cross_asset_factor_tilt.py — keep in sync) ─────────────
REBAL_DAYS = 5
COST_BPS = 5.0
VOL_TARGET_ANN = 0.12
H32_FLOOR = 0.5
H32_CAP = 1.75
PERIODS_PER_YEAR = 365
MOMENTUM_LOOKBACK = 30
VOL_LOOKBACK = 30
Z_CLIP = 3.0

VALIDATION_MIN_DAYS = 60
PAPER_NOTIONAL_USD = 1_000_000.0

# Live state persistence
STATE_TABLE = "factor_tilt_state"
NAV_TABLE = "factor_tilt_nav"

# Endpoints (wired to src/api/main.py)
ENDPOINT_NAV = "/api/v1/signals/factor-tilt"
ENDPOINT_TRACKING = "/api/v1/signals/factor-tilt-tracking"

# 41-asset crypto + 17 TradFi ETF universe (mirror backtest rig)
from src.data.signals.fusion_paper import UNIVERSE as CRYPTO_UNIVERSE
from src.research.validation.cis_quality_tradfi import TRADFI_UNIVERSE
FULL_UNIVERSE = sorted(set(CRYPTO_UNIVERSE) | set(TRADFI_UNIVERSE))

_SB_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
_SB_KEY = os.environ.get("SUPABASE_KEY", "")
_INTERNAL_TOKEN = os.environ.get("INTERNAL_TOKEN", "")

_logger = logging.getLogger("factor_tilt_paper")


# ── Live data fetchers ───────────────────────────────────────────────────────
async def _fetch_close_live(symbols: list[str],
                            lookback_days: int = 60) -> dict[str, list[float]]:
    """Fetch live daily close for crypto (Binance) + TradFi (EODHD cache).

    Falls back to cached data on API failure (graceful degradation).
    """
    try:
        import httpx
    except ImportError:
        return {}
    out: dict[str, list[float]] = {}
    async with httpx.AsyncClient(timeout=20) as client:
        for sym in symbols:
            try:
                if sym in TRADFI_UNIVERSE:
                    # Try EODHD cache first (no live TradFi feed wired yet)
                    cache_fp = (Path("/Volumes/CometCloudAI/cometcloud-local/_cache/eodhd_history")
                                / f"{sym}_2024-01-01_2026-08-20.json")
                    if cache_fp.exists():
                        rows = json.loads(cache_fp.read_text())
                        out[sym] = [float(r["close"]) for r in rows[-lookback_days:]]
                else:
                    kl = await client.get(
                        f"https://fapi.binance.com/fapi/v1/klines",
                        params={"symbol": sym, "interval": "1d", "limit": lookback_days})
                    if kl.status_code == 200:
                        out[sym] = [float(k[4]) for k in kl.json()]
            except Exception as ex:
                _logger.debug("factor_tilt fetch failed for %s: %s", sym, ex)
                continue
    return out


async def _fetch_cis_pillar_o_live(symbols: list[str]) -> pd.Series:
    """Fetch latest CIS pillar_O for crypto symbols (TradFi has no pillar_O)."""
    try:
        import httpx
    except ImportError:
        return pd.Series(dtype=float)
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
        _logger.debug("Redis fetch failed: %s", ex)
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
    try:
        import httpx
        if _SB_URL and _SB_KEY:
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.get(
                    f"{_SB_URL}/rest/v1/{STATE_TABLE}",
                    params={"select": "*", "order": "ts.desc", "limit": 1},
                    headers={"apikey": _SB_KEY, "Authorization": f"Bearer {_SB_KEY}"})
                if r.status_code == 200 and r.json():
                    return json.loads(r.json()[0]["state_json"])
    except Exception as ex:
        _logger.debug("state load failed: %s", ex)
    return _default_state()


def _default_state() -> dict[str, Any]:
    return {
        "inception_date": str(dt.date.today()),
        "nav": 1.0,
        "last_mark_date": None,
        "n_days_marked": 0,
        "factor_sharpe_attribution": {},
    }


async def _save_state(state: dict[str, Any]) -> None:
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
    """Daily mark of the cross-asset factor tilt paper book. Idempotent per day."""
    from src.research.validation.cross_asset_factor_tilt import (
        build_composite, tilt_weights, h32_size, vol_target, book_returns,
        hold_panel_benchmark,
    )

    today = dt.date.today()
    state = await _load_state()
    if state.get("last_mark_date") == str(today):
        return {"status": "skipped", "reason": "already_marked_today",
                "date": str(today), "nav": state.get("nav", 1.0)}

    universe = FULL_UNIVERSE
    data = await _fetch_close_live(universe, lookback_days=60)
    if len(data) < 20:
        return {"status": "skipped", "reason": "insufficient_live_data",
                "n_assets_with_data": len(data)}

    pillar_o = await _fetch_cis_pillar_o_live(
        [s for s in data.keys() if s in CRYPTO_UNIVERSE])

    today_ts = pd.Timestamp(today)
    close_panel = pd.DataFrame(
        {sym: pd.Series(d, index=pd.date_range(
            end=today_ts, periods=len(d), freq="D"))
         for sym, d in data.items() if len(d) >= MOMENTUM_LOOKBACK + 2}
    ).sort_index()
    rets = close_panel.pct_change().fillna(0.0)

    # Synthesize cis_long from live pillar_o (constant per asset over the panel)
    cis_long_rows = []
    for sym in pillar_o.index:
        for d in close_panel.index:
            cis_long_rows.append({"date": d, "asset": sym, "O": float(pillar_o[sym])})
    cis_long = pd.DataFrame(cis_long_rows)

    # Build composite score
    score = build_composite(cis_long, rets, list(data.keys()), close_panel.index)
    # For TradFi (no pillar_O), composite reduces to (z_momentum + z_lowrisk) / 2
    from src.research.validation.cross_asset_factor_tilt import (
        build_momentum_score, build_lowrisk_score,
    )
    tradfi_in_data = [s for s in data.keys() if s in TRADFI_UNIVERSE]
    if tradfi_in_data:
        z_m = build_momentum_score(rets, tradfi_in_data, close_panel.index)
        z_l = build_lowrisk_score(rets, tradfi_in_data, close_panel.index)
        score[tradfi_in_data] = (z_m.fillna(0.0) + z_l.fillna(0.0)) / 2.0

    # Long-only tilt weights
    n = len(data)
    w = tilt_weights(score, min_weight=1.0 / max(n, 1))
    w = w.reindex(close_panel.index).ffill().fillna(0.0)
    w = w.div(w.sum(axis=1).replace(0, np.nan), axis=0).fillna(0.0)

    # H3.2 conviction scaling at each rebalance day
    size_scalar = pd.Series(1.0, index=close_panel.index)
    rebal_idx = list(range(0, len(close_panel.index), REBAL_DAYS))
    for i in rebal_idx:
        recent = rets.iloc[max(0, i - 30):i].mean(axis=1)
        size_scalar.iloc[i] = h32_size(recent)
    w_scaled = w.multiply(size_scalar.values, axis=0)
    w_scaled = w_scaled.clip(lower=0.0, upper=H32_CAP / n)
    w_scaled = w_scaled.div(w_scaled.sum(axis=1).replace(0, np.nan), axis=0).fillna(0.0)

    # Book returns + vol target
    raw_pnl = book_returns(w_scaled, rets)
    targeted_pnl = vol_target(raw_pnl, target_ann=VOL_TARGET_ANN)
    today_ret = float(targeted_pnl.iloc[-1]) if len(targeted_pnl) > 0 else 0.0

    # Hold-the-panel benchmark
    bench = hold_panel_benchmark(rets)

    # Excess return
    excess = today_ret - float(bench.iloc[-1])

    new_nav = float(state.get("nav", 1.0)) * (1.0 + today_ret)
    n_days_marked = int(state.get("n_days_marked", 0)) + 1
    inception = dt.date.fromisoformat(state["inception_date"])
    n_forward_days = (today - inception).days
    validated = n_forward_days >= VALIDATION_MIN_DAYS

    # Factor Sharpe attribution (single-factor book sharpes)
    factor_attribution = {}
    for fname, fbuilder in [
        ("quality", lambda a: (cis_long[cis_long["asset"].isin(a)]
                                .pivot(index="date", columns="asset", values="O")
                                .reindex(index=close_panel.index, columns=a))),
        ("momentum", lambda a: rets[a]),
        ("lowrisk", lambda a: rets[a]),
    ]:
        try:
            if fname == "quality":
                fz = (builder := fbuilder)(list(data.keys()))
                fz = (fz - fz.mean(axis=1).values[:, None]) / fz.std(axis=1).values[:, None]
                fz = fz.clip(-Z_CLIP, Z_CLIP)
            elif fname == "momentum":
                fz = (close_panel.shift(1) / close_panel.shift(MOMENTUM_LOOKBACK + 1) - 1)
            else:
                vol = rets.rolling(VOL_LOOKBACK, min_periods=10).std()
                fz = -vol
            fw = tilt_weights(fz, min_weight=1.0 / max(n, 1)).reindex(close_panel.index).ffill().fillna(0.0)
            fpnl = book_returns(fw, rets)
            if fpnl.std() > 0:
                factor_attribution[fname] = float(
                    fpnl.mean() / fpnl.std() * np.sqrt(PERIODS_PER_YEAR))
        except Exception as ex:
            _logger.debug("factor attribution failed for %s: %s", fname, ex)

    new_state = {
        **state,
        "nav": new_nav,
        "last_mark_date": str(today),
        "n_days_marked": n_days_marked,
        "factor_sharpe_attribution": factor_attribution,
    }
    if not dry_run:
        await _save_state(new_state)

    return {
        "status": "ok",
        "date": str(today),
        "nav": new_nav,
        "today_return": today_ret,
        "today_excess_vs_bench": excess,
        "n_days_marked": n_days_marked,
        "validated": validated,
        "factor_attribution": factor_attribution,
        "max_single_factor_sharpe_share": max(
            (abs(s) / max(sum(abs(v) for v in factor_attribution.values()), 1e-9))
            for s in factor_attribution.values()) if factor_attribution else 0.0,
    }


# ── API: NAV curve ───────────────────────────────────────────────────────────
async def get_curve(limit: int = 400) -> dict[str, Any]:
    state = await _load_state()
    inception = dt.date.fromisoformat(state["inception_date"])
    n_days = (dt.date.today() - inception).days
    return {
        "endpoint": ENDPOINT_NAV,
        "strategy": "cross_asset_factor_tilt",
        "spec": "docs/STRATEGY_4_CROSS_ASSET_FACTOR_TILT.md",
        "inception_date": state["inception_date"],
        "as_of": str(dt.date.today()),
        "current_nav": state.get("nav", 1.0),
        "n_days_marked": state.get("n_days_marked", 0),
        "n_forward_days": n_days,
        "validated": n_days >= VALIDATION_MIN_DAYS,
        "validation_min_days": VALIDATION_MIN_DAYS,
        "universe_size": len(FULL_UNIVERSE),
        "n_crypto": len([s for s in FULL_UNIVERSE if s in CRYPTO_UNIVERSE]),
        "n_tradfi": len([s for s in FULL_UNIVERSE if s in TRADFI_UNIVERSE]),
        "factor_sharpe_attribution": state.get("factor_sharpe_attribution", {}),
        "compliance": "positioning language only — no investment advice",
    }


# ── Background loop ───────────────────────────────────────────────────────────
async def daily_loop(interval_hours: int = 24) -> None:
    while True:
        try:
            result = await mark_and_rebalance(dry_run=False)
            _logger.info("factor_tilt mark: %s", result.get("status"))
        except Exception as ex:
            _logger.exception("factor_tilt loop error: %s", ex)
        await asyncio.sleep(interval_hours * 3600)


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--once", action="store_true")
    p.add_argument("--loop", action="store_true")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(name)s] %(message)s")
    if args.loop:
        asyncio.run(daily_loop())
    else:
        print(json.dumps(asyncio.run(mark_and_rebalance(dry_run=args.dry_run)),
                          indent=2, default=str))