"""
Cause persistence — write daily cause snapshots + conviction verdicts to Supabase.

WHY THIS EXISTS:
    Per ARCHITECTURE.md, the causes (forward-supply overhang, positioning pressure)
    are the UPSTREAM signal — beta+ comes from being closer to the cause, not the
    reflection. P1 backtest (forced-seller short + squeeze-long) needs HISTORICAL
    cause data to validate that the kernel actually predicts forward returns.

    Currently `refresh_forward_supply` + `refresh_positioning` only cache to Redis
    (TTL 6h for supply, 30min for positioning). After this module:
      - Each daily refresh writes one row per symbol to `cause_snapshots_daily`
      - Each conviction synthesis writes one row per symbol to `conviction_verdicts_daily`
      - A separate backfill loop walks forward returns into `cause_outcomes`

    Once ≥6mo of cause_snapshots_daily accumulates, the cause backtest can run for
    real (today it's gated on data accumulation).

USAGE:
    # In main.py refresh loops (Railway deployment):
    await refresh_forward_supply()        → returns map
    await persist_forward_supply_daily()  → writes one row per symbol

    await refresh_positioning()
    await persist_positioning_daily()

    # Conviction synthesis:
    rows = rank_universe(universe, band_tiers, band)
    await persist_conviction_verdicts(rows, band=band, regime=regime)
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Iterable

logger = logging.getLogger(__name__)


def _supabase_config() -> tuple[str, str] | None:
    """Return (url, key) from env, or None if missing. Auth via supabase headers."""
    url = os.environ.get("SUPABASE_URL") or os.environ.get("SUPABASE_REST_URL")
    key = (os.environ.get("SUPABASE_SERVICE_KEY") or os.environ.get("SUPABASE_KEY")
           or os.environ.get("SUPABASE_ANON_KEY"))
    if not url or not key:
        return None
    return url, key


async def _post_table(table: str, rows: list[dict], on_conflict: str | None = None) -> int:
    """POST rows to a Supabase table. Returns count written. -1 on failure."""
    cfg = _supabase_config()
    if not cfg:
        logger.debug(f"[CAUSE-PERSIST] Supabase not configured; skipping write to {table}")
        return -1
    url, key = cfg
    import httpx
    base = url.rstrip("/") + f"/rest/v1/{table}"
    hdr = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=minimal",
    }
    written = 0
    try:
        async with httpx.AsyncClient(timeout=60) as c:
            for i in range(0, len(rows), 500):
                chunk = rows[i:i + 500]
                r = await c.post(base, headers=hdr, json=chunk)
                if r.status_code in (200, 201, 204):
                    written += len(chunk)
                else:
                    logger.warning(
                        f"[CAUSE-PERSIST] {table} chunk {i} failed: "
                        f"{r.status_code} {r.text[:200]}"
                    )
                    return written
    except Exception as e:
        logger.warning(f"[CAUSE-PERSIST] {table} write failed: {e}")
        return written
    return written


# ── Forward supply persistence ───────────────────────────────────────────────

async def persist_forward_supply_daily(fmap: dict, cis_universe: list[dict] | None = None) -> int:
    """Write today's forward-supply snapshot to `cause_snapshots_daily`.

    Args:
        fmap:        {SYMBOL: {forward_supply_risk, float_ratio, overhang}}
        cis_universe: optional current CIS universe for cross-validation cols
    """
    if not fmap:
        return 0
    today = datetime.now(timezone.utc).date().isoformat()
    cis_by_sym = {}
    if cis_universe:
        for a in cis_universe:
            sym = (a.get("symbol") or a.get("asset_id") or "").upper()
            if sym:
                cis_by_sym[sym] = a
    rows = []
    for sym, v in (fmap or {}).items():
        if not isinstance(v, dict):
            continue
        cis = cis_by_sym.get(sym.upper(), {})
        rows.append({
            "snapshot_date": today,
            "symbol": sym.upper(),
            "forward_supply_risk": v.get("forward_supply_risk"),
            "float_ratio": v.get("float_ratio"),
            "overhang": v.get("overhang"),
            "cis_score": cis.get("cis_score"),
            "signal": cis.get("signal"),
            "macro_regime": cis.get("macro_regime"),
            "source": "live_refresh_fwd_supply",
        })
    n = await _post_table("cause_snapshots_daily", rows)
    if n > 0:
        logger.info(f"[CAUSE-PERSIST] forward_supply: {n} rows for {today}")
    return max(n, 0)


# ── Positioning persistence ──────────────────────────────────────────────────

async def persist_positioning_daily(pmap: dict, cis_universe: list[dict] | None = None) -> int:
    """Write today's positioning snapshot to `cause_snapshots_daily`.

    The schema has ONE row per (date, symbol) with both causes. So we update
    existing forward_supply rows with positioning columns when they exist;
    otherwise insert fresh rows with positioning only.
    """
    if not pmap:
        return 0
    today = datetime.now(timezone.utc).date().isoformat()
    cis_by_sym = {}
    if cis_universe:
        for a in cis_universe:
            sym = (a.get("symbol") or a.get("asset_id") or "").upper()
            if sym:
                cis_by_sym[sym] = a
    rows = []
    for sym, v in (pmap or {}).items():
        if not isinstance(v, dict):
            continue
        cis = cis_by_sym.get(sym.upper(), {})
        rows.append({
            "snapshot_date": today,
            "symbol": sym.upper(),
            "positioning_pressure": v.get("positioning_pressure"),
            "funding_rate": v.get("funding"),
            "oi_usd": v.get("oi_usd"),
            "cis_score": cis.get("cis_score"),
            "signal": cis.get("signal"),
            "macro_regime": cis.get("macro_regime"),
            "source": "live_refresh_positioning",
        })
    n = await _post_table("cause_snapshots_daily", rows)
    if n > 0:
        logger.info(f"[CAUSE-PERSIST] positioning: {n} rows for {today}")
    return max(n, 0)


# ── Conviction verdicts persistence ─────────────────────────────────────────

async def persist_conviction_verdicts(rows: list[dict], band: str, regime: str) -> int:
    """Write today's conviction verdicts (compute_conviction output) to Supabase.

    Each row = one asset's kernel verdict (direction/conviction/edge/causes).
    The schema has named-play flags (`is_forced_seller_short`, `is_squeeze_long`,
    `is_long_liq_short`) so the backtest can filter without re-deriving.
    """
    if not rows:
        return 0
    today = datetime.now(timezone.utc).date().isoformat()
    out = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        fs = float(r.get("forward_supply_risk") or 0.0)
        pos = float(r.get("positioning_pressure") or 0.0)
        direction = r.get("direction")
        out.append({
            "snapshot_date": today,
            "symbol": r.get("symbol"),
            "direction": direction,
            "conviction": r.get("conviction"),
            "adjusted_edge_pct": r.get("adjusted_edge_pct"),
            "expected_edge_pct": r.get("expected_edge_pct"),
            "basis": r.get("basis"),
            "confidence": r.get("confidence"),
            "action": r.get("action"),
            "forward_supply_risk": fs,
            "positioning_pressure": pos,
            "in_circle": r.get("in_circle"),
            "season": r.get("season"),
            "quality_score": r.get("quality_score"),
            "executability": r.get("executability"),
            "is_forced_seller_short": bool(direction == "short" and fs >= 0.5),
            "is_squeeze_long": bool(direction == "long" and pos >= 0.3),
            "is_long_liq_short": bool(direction == "short" and pos <= -0.5),
            "macro_regime": regime,
            "source": "conviction_kernel",
        })
    n = await _post_table("conviction_verdicts_daily", out)
    if n > 0:
        logger.info(f"[CAUSE-PERSIST] conviction verdicts: {n} rows for {today} "
                    f"(band={band}, regime={regime})")
    return max(n, 0)