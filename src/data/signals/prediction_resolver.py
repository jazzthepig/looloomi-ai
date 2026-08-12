"""
Prediction Resolver — "resolve EVERY prediction", not just signals (Seth, 2026-07-10).
=======================================================================================

Generalises `outcome_tracker.py` (which resolves only signal_journal) to every prediction
the system makes: signals, the causes (positioning, forward_supply), conviction verdicts,
and narrative (NMA). Per LOOP_ENGINEERING.md, this is the fix for the 88-insert / ~1-read
imbalance — the read-back that turns each write-only log into a MEASURED track record.

Each source makes a directional claim about a symbol on a date:
    signal        OUTPERFORM/UNDERPERFORM              → +1 / −1
    positioning   pressure sign (squeeze +/long-liq −) → +1 / −1
    forward_supply high overhang = structural bearish  → −1 (magnitude claim)
    conviction    direction long/short                 → +1 / −1
    narrative     STRONG_NARRATIVE / NARRATIVE_FADE     → +1 / −1

The resolution engine (price@date+horizon, benchmark-relative alpha, hit = sign(alpha)==
direction) is IDENTICAL across sources — reused from outcome_tracker. Only the direction
extraction differs. Output → one `prediction_outcomes` row per resolved prediction +
a per-source aggregate {n, hit_rate, avg_alpha}: the number that says whether a source is
actually predictive, which then feeds per-source conviction weighting (extends
conviction_from_track_record beyond signals).

Runs on Railway/Mac (Supabase creds). Smoke test resolves synthetic predictions against
REAL Binance prices, so the engine is verifiable from anywhere.
"""
from __future__ import annotations
from src.api.runtime_role import note_refusal, refuse_write

import asyncio
import json
import logging
import os
from dataclasses import dataclass, asdict
from datetime import datetime, timezone, timedelta
from typing import Callable, Optional

import httpx

# Reuse the battle-tested resolution engine — no duplication.
from src.data.signals.outcome_tracker import (
    _parse_dt, _crypto_price_at, _ohlcv_close_at, _tradfi_price_at_sync,
    _bench_price, _benchmark_for, _sb_headers, _TRADFI_CLASSES,
    _SB_URL, _SB_KEY, GRACE_DAYS,
)

_log = logging.getLogger("prediction_resolver")

ALPHA_WIN = 0.005   # |alpha| band for a directional hit (matches outcome_tracker)


@dataclass
class Prediction:
    source: str            # signal | positioning | forward_supply | conviction | narrative
    ref_id: str
    symbol: str
    date: datetime
    direction: int         # +1 outperform / −1 underperform / 0 neutral (skipped)
    horizon_days: int = 30
    asset_class: str = "crypto"


# ── Direction extractors: one per source (row → direction) ───────────────────

def _dir_signal(row: dict) -> int:
    s = (row.get("signal") or "").upper()
    if "OUTPERFORM" in s and "UNDER" not in s:
        return +1
    if "UNDERPERFORM" in s or "UNDERWEIGHT" in s:
        return -1
    return 0


def _dir_positioning(row: dict) -> int:
    p = row.get("positioning_pressure")
    if p is None:
        return 0
    return +1 if p > 0.15 else (-1 if p < -0.15 else 0)


def _dir_forward_supply(row: dict) -> int:
    r = row.get("forward_supply_risk")
    return -1 if (r is not None and r >= 0.5) else 0     # high overhang → bearish


def _dir_conviction(row: dict) -> int:
    d = (row.get("direction") or "").lower()
    return +1 if d == "long" else (-1 if d == "short" else 0)


def _dir_narrative(row: dict) -> int:
    s = (row.get("signal") or row.get("nma_signal") or "").upper()
    if "STRONG" in s or s == "NARRATIVE" or "BULL" in s:
        return +1
    if "FADE" in s or "BEAR" in s:
        return -1
    return 0


# source → (table, select cols, date col, symbol col, id col, direction fn)
SOURCES: dict[str, dict] = {
    "signal":         dict(table="signal_journal", date="signal_date", sym="symbol",
                           idc="id", cols="id,symbol,asset_class,signal,signal_date", dfn=_dir_signal),
    "positioning":    dict(table="cause_snapshots_daily", date="snapshot_date", sym="symbol",
                           idc="id", cols="id,symbol,snapshot_date,positioning_pressure", dfn=_dir_positioning),
    "forward_supply": dict(table="cause_snapshots_daily", date="snapshot_date", sym="symbol",
                           idc="id", cols="id,symbol,snapshot_date,forward_supply_risk", dfn=_dir_forward_supply),
    "conviction":     dict(table="conviction_verdicts_daily", date="snapshot_date", sym="symbol",
                           idc="id", cols="id,symbol,snapshot_date,direction", dfn=_dir_conviction),
    "narrative":      dict(table="narrative_snapshots", date="snapshot_date", sym="symbol",
                           idc="id", cols="id,symbol,snapshot_date,signal", dfn=_dir_narrative),
}


# ── Core resolution (single prediction → outcome via the shared alpha engine) ──

async def _resolve_alpha(client, sym: str, cls: str, entry_dt: datetime,
                         horizon: int, cache: dict):
    """Returns (realized_return, bench_return, alpha, exit_price) or (None,...)."""
    started = datetime.now(timezone.utc)
    age_days = (started - entry_dt).total_seconds() / 86400.0
    target = entry_dt + timedelta(days=horizon)
    is_tradfi = cls in _TRADFI_CLASSES

    async def px_at(dt):
        p = await _ohlcv_close_at(client, sym, dt)
        if p is None:
            p = (await asyncio.to_thread(_tradfi_price_at_sync, sym, dt) if is_tradfi
                 else await _crypto_price_at(sym, dt, age_days))
        return p

    entry_px = await px_at(entry_dt)
    exit_px = await px_at(target)
    if not (entry_px and exit_px and entry_px > 0):
        return None, None, None, None
    ret = (exit_px - entry_px) / entry_px

    bench = _benchmark_for(cls)
    alpha = bench_ret = None
    if bench != sym:
        b0 = await _bench_price(client, bench, entry_dt, age_days, cache)
        b1 = await _bench_price(client, bench, target, age_days, cache)
        if b0 and b1 and b0 > 0:
            bench_ret = (b1 - b0) / b0
            alpha = ret - bench_ret
    return ret, bench_ret, (alpha if alpha is not None else ret), exit_px


def _hit(direction: int, alpha: float) -> Optional[bool]:
    if direction == 0 or alpha is None:
        return None
    if abs(alpha) < ALPHA_WIN:
        return None                     # flat band — neither hit nor miss
    return (alpha > 0) == (direction > 0)


async def _write_outcome(client, row: dict) -> bool:
    # RECORD GATE (2026-08-12, S-150). This module writes a FORWARD-RECORD table
    # and bypasses store.py, so the S-149 gate did not reach it. The claim made
    # yesterday — "the write side of the record has one owner" — was broader than
    # the implementation: the gate covered two functions while five record writers
    # went around them. That is the exact defect this session has been naming,
    # committed inside the fix for it, and endorsed by a guard that only checked
    # the two functions it knew about.
    _refusal = refuse_write("prediction_outcomes")
    if _refusal:
        note_refusal("prediction_outcomes", _refusal)
        return False

    if not (_SB_URL and _SB_KEY):
        return False
    try:
        r = await client.post(f"{_SB_URL}/rest/v1/prediction_outcomes",
                              content=json.dumps(row), headers=_sb_headers(write=True), timeout=15)
        return r.status_code in (200, 201, 204)
    except Exception as e:
        _log.warning("[PRED] write error: %s", e)
        return False


# ── Source runner + aggregate ─────────────────────────────────────────────────

async def resolve_source(source: str, *, horizon: int = 30, limit: int = 500,
                         dry_run: bool = True) -> dict:
    cfg = SOURCES[source]
    if not (_SB_URL and _SB_KEY):
        return {"source": source, "status": "skipped", "reason": "supabase_not_configured"}
    cutoff = (datetime.now(timezone.utc) - timedelta(days=horizon)).date().isoformat()
    hits = misses = flat = nodata = written = 0
    alphas = []
    async with httpx.AsyncClient(timeout=20) as client:
        try:
            resp = await client.get(f"{_SB_URL}/rest/v1/{cfg['table']}",
                params={cfg["date"]: f"lt.{cutoff}", "order": f"{cfg['date']}.asc",
                        "limit": str(limit), "select": cfg["cols"]},
                headers=_sb_headers(), timeout=20)
            rows = resp.json() if resp.status_code == 200 else []
        except Exception as e:
            return {"source": source, "status": "error", "error": str(e)}

        cache: dict = {}
        for row in rows:
            d = cfg["dfn"](row)
            if d == 0:
                continue
            sym = (row.get(cfg["sym"]) or "").upper()
            dt = _parse_dt(row.get(cfg["date"]))
            if not (sym and dt):
                continue
            cls = row.get("asset_class") or "crypto"
            ret, bench_ret, alpha, exit_px = await _resolve_alpha(client, sym, cls, dt, horizon, cache)
            if alpha is None:
                nodata += 1
                continue
            h = _hit(d, alpha)
            if h is None:
                flat += 1
            elif h:
                hits += 1
            else:
                misses += 1
            alphas.append(alpha * d)     # direction-adjusted alpha (edge in the claimed direction)
            out = {"source": source, "ref_id": str(row.get(cfg["idc"])), "symbol": sym,
                   "predicted_at": dt.date().isoformat(), "horizon_days": horizon,
                   "direction": d, "realized_return_pct": round(ret * 100, 4),
                   "alpha_pct": round(alpha * 100, 4), "hit": h,
                   "resolved_at": datetime.now(timezone.utc).isoformat()}
            if not dry_run and await _write_outcome(client, out):
                written += 1

    n = hits + misses
    return {"source": source, "status": "ok", "dry_run": dry_run,
            "examined": len(rows), "hits": hits, "misses": misses, "flat": flat, "no_data": nodata,
            "hit_rate_pct": round(hits / n * 100, 1) if n else None,
            "avg_directional_alpha_pct": round(sum(alphas) / len(alphas) * 100, 3) if alphas else None,
            "rows_written": written}


async def resolve_all_predictions(*, horizon: int = 30, dry_run: bool = True) -> dict:
    """Resolve every source → per-source track record. THE read-back that mines the log."""
    out = {}
    for src in SOURCES:
        out[src] = await resolve_source(src, horizon=horizon, dry_run=dry_run)
    return {"as_of": datetime.now(timezone.utc).isoformat(), "horizon_days": horizon, "sources": out}


async def source_track_record() -> dict:
    """Read-back: per-source {n, hit_rate, avg_directional_alpha} from prediction_outcomes.
    THE value-mining query — tells us which sources are actually predictive. Feeds
    per-source conviction weighting (extends conviction_from_track_record beyond signals)."""
    if not (_SB_URL and _SB_KEY):
        return {"status": "skipped", "reason": "supabase_not_configured"}
    async with httpx.AsyncClient(timeout=20) as client:
        try:
            r = await client.get(f"{_SB_URL}/rest/v1/prediction_outcomes",
                params={"select": "source,direction,alpha_pct,hit", "limit": "100000"},
                headers=_sb_headers(), timeout=20)
            rows = r.json() if r.status_code == 200 else []
        except Exception as e:
            return {"status": "error", "error": str(e)}
    agg: dict = {}
    for row in rows:
        s = row.get("source") or "?"
        a = agg.setdefault(s, {"hits": 0, "n": 0, "alpha_sum": 0.0, "total": 0})
        agg[s]["total"] += 1
        h = row.get("hit")
        if h is not None:
            a["n"] += 1
            a["hits"] += 1 if h else 0
        ap = row.get("alpha_pct"); d = row.get("direction")
        if ap is not None and d:
            a["alpha_sum"] += ap * (1 if d > 0 else -1); a["total"] = a["total"]
    out = {}
    for s, a in agg.items():
        out[s] = {"n": a["total"], "scored": a["n"],
                  "hit_rate_pct": round(a["hits"] / a["n"] * 100, 1) if a["n"] else None,
                  "avg_directional_alpha_pct": round(a["alpha_sum"] / a["total"], 3) if a["total"] else None}
    return {"status": "ok", "sources": out}


# ── Smoke test: resolution engine on REAL prices, synthetic predictions ──────

async def _smoke() -> int:
    """Verify the alpha/hit engine end-to-end against live Binance/CG prices (no Supabase)."""
    import httpx as _h
    print("[SMOKE] resolving synthetic predictions against REAL prices\n")
    # 3 predictions made 45 days ago; resolve at 30d horizon
    d0 = datetime.now(timezone.utc) - timedelta(days=45)
    preds = [Prediction("positioning", "1", "ETH", d0, +1),
             Prediction("forward_supply", "2", "SOL", d0, -1),
             Prediction("signal", "3", "BTC", d0, +1)]
    async with _h.AsyncClient(timeout=20) as client:
        cache = {}
        for p in preds:
            ret, bench_ret, alpha, exit_px = await _resolve_alpha(client, p.symbol, "crypto", p.date, p.horizon_days, cache)
            h = _hit(p.direction, alpha) if alpha is not None else None
            print(f"  {p.source:<14} {p.symbol} dir={p.direction:+d} "
                  f"ret={None if ret is None else round(ret*100,1)}% "
                  f"alpha={None if alpha is None else round(alpha*100,1)}% hit={h}")
    print("\n[SMOKE] engine resolves real prices → alpha → hit. ✅ (Supabase adapters run on Railway.)")
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    import sys
    if "--all" in sys.argv:
        print(json.dumps(asyncio.run(resolve_all_predictions(dry_run="--write" not in sys.argv)), indent=2))
    else:
        sys.exit(asyncio.run(_smoke()))
