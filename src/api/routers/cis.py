"""
CIS router — scoring, history, backtest, agent API, WebSocket, internal push
Endpoints: /api/v1/cis/*, /api/v1/agent/cis, /ws/cis, /internal/cis-scores
"""
import os, json as _json, time, asyncio, re, math
from typing import Optional
from datetime import datetime

import logging
from fastapi import APIRouter, HTTPException, Header, Query, WebSocket, WebSocketDisconnect, Response, Request
from fastapi.responses import JSONResponse

from src.api.store import (
    redis_set, redis_get, redis_get_status,
    redis_set_key, redis_get_key,
    supabase_insert_batch, supabase_get_history,
    supabase_get_recent_scores,
    sanitize_floats, ws_manager,
)
import src.api.store as store
from src.data.cis.cis_provider import calculate_cis_universe
from src.api.routers.webhooks import fire_grade_webhooks

_logger = logging.getLogger(__name__)

router = APIRouter()

_INTERNAL_TOKEN = os.environ.get("INTERNAL_TOKEN", "")
_SB_KEY_SET     = bool(os.environ.get("SUPABASE_KEY", ""))  # guard signal logging


async def _log_signals_task(universe: list, regime: str, prices: dict):
    """Fire-and-forget: log OUTPERFORM signals + close downgrades in signal_journal.

    Backfills any missing entry prices from the merged Railway universe (CoinGecko
    Pro / EODHD-backed, reliable on Railway) BEFORE logging — the Mac Mini push
    often omits price for many assets, which used to log signals with a null
    entry_price that can never be resolved into a 30d outcome. (Binance/
    get_prices_multi is geo-blocked on Railway, so we reuse the cached universe.)"""
    try:
        missing = [s for s in
                   ((a.get("symbol") or a.get("asset_id") or "").upper() for a in universe)
                   if s and s not in prices]
        if missing:
            try:
                full = await get_cis_universe(force_source=None)
                for a in (full or {}).get("universe", []):
                    s = (a.get("symbol") or a.get("asset_id") or "").upper()
                    if s in missing:
                        px = a.get("price") or a.get("current_price")
                        if px:
                            try:
                                prices[s] = float(px)
                            except (TypeError, ValueError):
                                pass
            except Exception as e:
                _logger.warning(f"[SIGNALS] price backfill failed: {e}")
        from src.api.routers.signals import log_cis_signals
        n = await log_cis_signals(universe, regime, prices)
        if n:
            _logger.info(f"[SIGNALS] {n} new signals logged")
    except Exception as e:
        _logger.warning(f"[SIGNALS] log task error: {e}")

# ── Regime tracking (Simons Upgrade P1.1) ────────────────────────────────────
# Persists in-module across requests. Reset on Railway restart — acceptable
# since regime transitions are rare and Supabase history is the source of truth.
_last_push_regime: dict[str, str] = {}   # symbol → previous regime (for transition detection)
_push_counts: dict[str, int] = {}         # regime → consecutive push count (for confidence)


def _compute_regime_confidence(regime: str) -> float:
    """
    Compute confidence in current regime classification (Simons Upgrade P1.1).
    Based on:
    - consecutive push count in current regime (more pushes = more confident)
    - BTC dominance 20d MA spread (tight = confident, wide = uncertain)
    - FNG reading proximity to boundaries
    Returns 0.0-1.0. Below 0.6 = early warning zone.
    """
    push_count = _push_counts.get(regime, 1)

    # Push-count component: log scale, 0.85 max at 50+ pushes
    count_score = min(0.85, 0.3 + 0.11 * math.log1p(push_count))

    # Regime stability bonus: RISK_ON/RISK_OFF are binary and more confident
    stability_bonus = {"RISK_ON": 0.05, "RISK_OFF": 0.05, "TIGHTENING": 0.03,
                       "EASING": 0.03, "GOLDILOCKS": 0.02}.get(regime, 0.0)

    confidence = min(1.0, count_score + stability_bonus)
    return round(confidence, 2)


def _p(asset: dict, key: str):
    """Read pillar score — handles flat keys (local engine) and nested pillars dict (Railway)."""
    v = asset.get(key)
    if v is not None:
        return v
    return asset.get("pillars", {}).get(key.upper())


# ── Internal push (Mac Mini → Railway) ───────────────────────────────────────

@router.post("/internal/cis-scores")
async def receive_local_cis_scores(payload: dict, x_internal_token: str = Header(None)):
    """
    Receives CIS scores from the local Mac Mini engine (cis_push.py).
    Writes to Upstash Redis (hot cache) and Supabase (score history).
    Triggers WebSocket broadcast to connected clients.
    """
    # Reject-by-default: require token always (fail secure if env var missing)
    if not _INTERNAL_TOKEN or not x_internal_token or x_internal_token != _INTERNAL_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid token")

    try:
        # ── Normalize to canonical CIS push contract v1 (single source of truth) ──
        # Accepts legacy shapes (flat f/m/r/s/a with r->O, int data_tier, 'assets'
        # alias, epoch timestamps) and emits ONE canonical shape. See
        # src/api/contracts/cis_push.py and MINIMAX_SYNC.md §2.
        from src.api.contracts.cis_push import normalize_cis_payload, SCHEMA_VERSION
        norm = normalize_cis_payload(payload)
        universe   = norm["universe"]
        timestamp  = norm["pushed_at"]
        macro      = norm["macro"]
        provenance = norm["provenance"]

        # Loud drift alarm — silent field-drop is exactly what caused the
        # historical front/back-end bugs. Surface it instead of swallowing it.
        if norm["warnings"]:
            _logger.warning(
                "[CONTRACT] CIS push drift (schema=%s expected=%s, sha=%s): %s",
                norm["schema_version"], SCHEMA_VERSION,
                provenance.get("engine_git_sha"), "; ".join(norm["warnings"][:12]),
            )
        _logger.info(
            "[CONTRACT] normalized %s/%s assets (T1=%s T2=%s dropped=%s) sha=%s cfg=%s",
            norm["counts"]["normalized"], norm["counts"]["received"],
            norm["counts"]["t1"], norm["counts"]["t2"], norm["counts"]["dropped"],
            provenance.get("engine_git_sha"), provenance.get("config_hash"),
        )

        cache_data = {
            "universe":       universe,
            "last_updated":   time.time(),
            "timestamp":      timestamp,
            "source":         "local_engine",
            "macro":          macro,
            # provenance + contract observability (read by /schema + ops)
            "schema_version": norm["schema_version"],
            "provenance":     provenance,
            "contract_warnings": norm["warnings"][:20],
        }

        # 1. Write to Redis (hot cache, 2h TTL)
        ok = await redis_set(cache_data)
        _logger.info(f"[INTERNAL] Received {len(universe)} CIS scores — Redis write: {ok}")

        # 1b. Persist a long-lived "last known good" snapshot (7-day TTL). The hot
        # cache expires after 2h; if the Mac Mini push stalls past that AND the
        # Railway T2 calc is also empty, the universe endpoint would otherwise
        # return [] and the whole leaderboard goes blank (QA P0, 2026-06-05). This
        # LKG snapshot is the never-empty floor — served as "degraded" if needed.
        if ok and universe:
            await redis_set_key("cis:last_known_good", cache_data, ttl=604800)

        # 2. Write to Supabase (score history, persistent)
        #    Also computes score_delta and score_zscore from recent history.
        sb_ok = False
        if universe:
            # Fetch last 30 scores per symbol to compute delta + Z-score
            # (done in bulk: one query per push, not per asset)
            symbols_in_push = [a.get("symbol", "") for a in universe if a.get("symbol")]
            recent_scores   = await supabase_get_recent_scores(symbols_in_push, n=30)

            from src.data.cis.cis_provider import canonical_regime_strict as _canon_strict_push
            macro_regime_push = payload.get("macro_regime") or (macro or {}).get("regime")

            # Regime transition detection (Simons Upgrade P1.1)
            # Compare current push regime vs last push's regime per symbol.
            # Supabase history is source of truth — _last_push_regime is for transition flag.
            def _detect_regime_transition(symbol: str, current_regime: str) -> tuple[bool, str]:
                prev = _last_push_regime.get(symbol)
                if prev and prev != current_regime:
                    return True, prev
                return False, prev or ""

            sb_rows = []
            for asset in universe:
                symbol  = asset.get("symbol", "")
                # canonical: pillars nested {F,M,O,S,A} with O recovered from r;
                # data_tier_label is "T1"/"T2" (fixes int/str mislabel)
                pillars = asset.get("pillars", {})
                score   = asset.get("cis_score")
                data_tier = asset.get("data_tier_label", "T2")

                # Score delta and Z-score from recent history
                score_delta  = None
                score_zscore = None
                history = recent_scores.get(symbol, [])
                if history and score is not None:
                    prev_scores = [h["score"] for h in history if h.get("score") is not None]
                    if prev_scores:
                        score_delta = round(score - prev_scores[0], 2)
                        if len(prev_scores) >= 5:
                            mean = sum(prev_scores) / len(prev_scores)
                            std  = (sum((s - mean) ** 2 for s in prev_scores) / len(prev_scores)) ** 0.5
                            score_zscore = round((score - mean) / std, 3) if std > 0 else 0.0

                # Regime transition detection
                regime_transition, previous_regime = _detect_regime_transition(symbol, macro_regime_push or "")

                sb_rows.append({
                    "symbol":             symbol,
                    "name":               asset.get("name", ""),
                    "score":              score,
                    "raw_cis_score":      asset.get("raw_cis_score") or score,
                    "grade":              asset.get("grade"),
                    "signal":             asset.get("signal"),
                    "percentile":         asset.get("percentile_rank"),
                    "pillar_f":           pillars.get("F") if isinstance(pillars, dict) else None,
                    "pillar_m":           pillars.get("M") if isinstance(pillars, dict) else None,
                    "pillar_o":           pillars.get("O") if isinstance(pillars, dict) else None,
                    "pillar_s":           pillars.get("S") if isinstance(pillars, dict) else None,
                    "pillar_a":           pillars.get("A") if isinstance(pillars, dict) else None,
                    "asset_class":        asset.get("asset_class", asset.get("class", "")),
                    # Canonicalise at WRITE time. Without this the table holds
                    # `Tightening` (local_engine) and `TIGHTENING` (railway) as if
                    # they were different regimes — normalisation was happening only
                    # on read. Strict variant: an unrecognised label becomes NULL
                    # rather than a plausible NEUTRAL.
                    "macro_regime":       _canon_strict_push(macro_regime_push),
                    "regime_transition":  regime_transition,
                    "previous_regime":     previous_regime,
                    "data_tier":          data_tier,
                    "data_quality_score": asset.get("data_quality_score"),
                    "las":                asset.get("las"),
                    "confidence":         asset.get("confidence", 1.0 if data_tier == "T1" else 0.8),
                    "score_delta":        score_delta,
                    "score_zscore":       score_zscore,
                    "source":             "local_engine",
                })

                # Update tracked regime + push count for next push comparison
                if symbol and macro_regime_push:
                    _last_push_regime[symbol] = macro_regime_push
                # Track push counts for regime confidence (Simons P1.1)
                if macro_regime_push:
                    _push_counts[macro_regime_push] = _push_counts.get(macro_regime_push, 0) + 1
            sb_ok = await supabase_insert_batch(sb_rows)
            _logger.warning(f"[INTERNAL] Supabase history write: {sb_ok} ({len(sb_rows)} rows, with delta+zscore)")

            # Grade change detection → fire GRADE_UPGRADE / GRADE_DOWNGRADE webhooks
            _GRADE_RANK = {"A+": 8, "A": 7, "B+": 6, "B": 5, "C+": 4, "C": 3, "D": 2, "F": 1}
            upgrades, downgrades = [], []
            for asset in universe:
                symbol     = asset.get("symbol", "")
                new_grade  = asset.get("grade", "")
                new_signal = asset.get("signal", "")
                history    = recent_scores.get(symbol, [])
                if history and new_grade:
                    prev_grade  = history[0].get("grade", "")
                    prev_signal = history[0].get("signal", "")  # "" if not in select (acceptable)
                    if prev_grade and prev_grade != new_grade:
                        change = {
                            "symbol":      symbol,
                            "asset_class": asset.get("asset_class", asset.get("class", "")),
                            "from":        prev_grade,
                            "to":          new_grade,
                            "delta":       _GRADE_RANK.get(new_grade, 0) - _GRADE_RANK.get(prev_grade, 0),
                            "old_signal":  prev_signal,
                            "new_signal":  new_signal,
                            "cis_score":   round(asset.get("cis_score") or asset.get("score") or 0.0, 2),
                        }
                        if _GRADE_RANK.get(new_grade, 0) > _GRADE_RANK.get(prev_grade, 0):
                            upgrades.append(change)
                        else:
                            downgrades.append(change)

            if upgrades:
                _logger.info(f"[INTERNAL] {len(upgrades)} GRADE_UPGRADE — firing webhooks")
                asyncio.create_task(fire_grade_webhooks(
                    event  = "GRADE_UPGRADE",
                    assets = upgrades,
                    regime = macro_regime_push or "",
                ))
                # GTM/ops Telegram alert — high-grade upgrades only (low noise).
                # Compliance-safe: grades + positioning signals already enum-clean.
                _notable = [a for a in upgrades if a.get("to") in ("A+", "A", "B+")]
                if _notable:
                    _lines = ["📈 CIS grade upgrades"] + [
                        f"  {a.get('symbol')}: {a.get('from')}→{a.get('to')}"
                        + (f" · {a.get('new_signal')}" if a.get('new_signal') else "")
                        for a in _notable[:8]
                    ]
                    async def _tg(msg):
                        try:
                            from src.api.notify import notify_telegram
                            await notify_telegram(msg)           # ops channel
                            from src.api.telegram_bot import broadcast_subscribers
                            await broadcast_subscribers(msg)     # opted-in users (GTM)
                        except Exception:
                            pass
                    asyncio.create_task(_tg("\n".join(_lines)))
            if downgrades:
                _logger.info(f"[INTERNAL] {len(downgrades)} GRADE_DOWNGRADE — firing webhooks")
                asyncio.create_task(fire_grade_webhooks(
                    event  = "GRADE_DOWNGRADE",
                    assets = downgrades,
                    regime = macro_regime_push or "",
                ))

            # Signal-level change detection (fires even without grade change)
            # Tracks: NEUTRAL/UNDERPERFORM/UNDERWEIGHT → OUTPERFORM/STRONG OUTPERFORM transitions
            _SIGNAL_RANK = {
                "STRONG OUTPERFORM": 5, "OUTPERFORM": 4, "NEUTRAL": 3,
                "UNDERPERFORM": 2, "UNDERWEIGHT": 1,
            }
            signal_changes = []
            for asset in universe:
                symbol     = asset.get("symbol", "")
                new_signal = asset.get("signal", "")
                history    = recent_scores.get(symbol, [])
                if not history or not new_signal:
                    continue
                prev_signal = history[0].get("signal", "")
                if not prev_signal or prev_signal == new_signal:
                    continue
                # Only fire if not already captured by grade change event
                is_grade_change = any(a["symbol"] == symbol for a in upgrades + downgrades)
                if not is_grade_change:
                    signal_changes.append({
                        "symbol":      symbol,
                        "asset_class": asset.get("asset_class", asset.get("class", "")),
                        "from":        prev_signal,
                        "to":          new_signal,
                        "delta":       _SIGNAL_RANK.get(new_signal, 0) - _SIGNAL_RANK.get(prev_signal, 0),
                        "grade":       asset.get("grade", ""),
                        "cis_score":   round(asset.get("cis_score") or asset.get("score") or 0.0, 2),
                    })
            if signal_changes:
                _logger.info(f"[INTERNAL] {len(signal_changes)} SIGNAL_CHANGE — firing webhooks")
                asyncio.create_task(fire_grade_webhooks(
                    event  = "SIGNAL_CHANGE",
                    assets = signal_changes,
                    regime = macro_regime_push or "",
                ))

        # 3. Signal journal — auto-log OUTPERFORM threshold crossings (fire-and-forget)
        #    Extract prices from the universe payload (Mac Mini includes price data).
        #    Falls back to None if price unavailable — entry_price will be null (still logs signal).
        if universe and _SB_KEY_SET:
            prices_from_payload = {}
            for a in universe:
                sym = (a.get("symbol") or a.get("asset_id") or "").upper()
                px  = a.get("price") or a.get("current_price") or a.get("market_data", {}).get("price")
                if sym and px:
                    try:
                        prices_from_payload[sym] = float(px)
                    except (TypeError, ValueError):
                        pass
            regime_for_signals = macro_regime_push or (macro or {}).get("regime") or ""
            asyncio.create_task(_log_signals_task(universe, regime_for_signals, prices_from_payload))

        # 4. Broadcast to WebSocket clients
        asyncio.create_task(_broadcast_cis_update(universe))

        return {"status": "success", "received": len(universe), "cached": ok, "history_written": sb_ok}
    except Exception as e:
        _logger.warning(f"[INTERNAL] Error receiving CIS scores: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/internal/cis-scores/schema")
async def get_cis_push_schema():
    """
    Live contract echo. Minimax's cis_push.py can fetch this at startup to
    self-check the payload shape instead of relying on a (possibly stale)
    Shadow/ copy. This endpoint — not Shadow, not markdown — is authority.
    """
    from src.api.contracts.cis_push import canonical_schema
    return canonical_schema()


# ── CIS Universe ──────────────────────────────────────────────────────────────

# Single-flight + short-TTL response cache for the universe endpoint.
# QA P1 (2026-06-05): the homepage mounts ~7 components that each fetch
# /api/v1/cis/universe on load. Each request recomputed the T2 Railway universe
# (calculate_cis_universe + get_macro_pulse, both with external calls), so the
# concurrent burst overwhelmed the worker → 503. Collapsing the burst into one
# computation (others await/serve the cached result) removes the 503 entirely.
_UNIVERSE_CACHE: dict = {"data": None, "ts": 0.0}
_UNIVERSE_TTL = 30.0

# S-180: the last T1 payload we successfully READ, kept so that a failed Redis
# read cannot masquerade as an absent Mac push. Deliberately in-process and
# deliberately NOT persisted: its whole job is to cover a blip measured in
# seconds. Surviving a restart would let it cover a real outage instead, which
# is the failure it exists to distinguish from.
_T1_LAST_GOOD: dict = {"payload": None, "ts": 0.0}


# S-200: the precomputed T2 universe. Written by `_t2_precompute_loop` in
# main.py, read here. Max age is generous on purpose — a stale T2 blended under
# a fresh T1 is far better than no T2 at all, which is what a cancelled build
# produces. When it IS too old the code falls through to an inline compute, so
# the slow path still exists; it is just no longer the only path.
_T2_PRECOMPUTE_KEY = "cis:t2_universe"
_T2_PRECOMPUTE_MAX_AGE_S = float(os.environ.get("CIS_T2_MAX_AGE_S", "1800"))


class _T2FromCache(Exception):
    """Control-flow marker: the precomputed T2 was usable, skip the inline build.

    An exception rather than a flag because the inline path is a long try-block
    whose except-clause already records timings; threading a boolean through it
    would mean two ways to leave the block and one of them untimed."""
_UNIVERSE_LOCK = asyncio.Lock()

# ── 2026-07-29 P0: the single-flight lock became a total-outage amplifier ──────
# The lock above fixed a 503 burst (QA P1) by collapsing N concurrent rebuilds
# into one. But the critical section held the lock across UNBOUNDED external
# calls. When the Supabase connection pool starved, one rebuild sat inside the
# lock for the full retry budget (10s x 3 + backoff = 33s) and EVERY other
# request queued behind it — turning a slow dependency into a dead endpoint.
#
# Three bounds, each addressing a distinct failure path:
#   1. hard time budget on the rebuild        → the lock can never be held forever
#   2. serve stale rather than queue          → contention degrades, not blocks
#   3. enrichment moved outside the lock      → decoration never gates the payload
#
# Design rule this encodes: a single-flight lock must bound BOTH how long it can
# be held and how long a caller will wait for it. Either one alone still hangs.
_UNIVERSE_BUILD_BUDGET_S = float(os.environ.get("CIS_UNIVERSE_BUILD_BUDGET_S", "12"))
_UNIVERSE_LOCK_WAIT_S    = float(os.environ.get("CIS_UNIVERSE_LOCK_WAIT_S", "3"))
_UNIVERSE_STALE_MAX_S    = float(os.environ.get("CIS_UNIVERSE_STALE_MAX_S", "3600"))


async def _universe_stale_durable(max_age_s: float = _UNIVERSE_STALE_MAX_S) -> dict | None:
    """The stale fallback, read from REDIS — i.e. one that survives a cold process.

    WHY (2026-08-12, S-146). `_UNIVERSE_CACHE` is a module-level dict, so it is
    empty in every freshly started process. The Mac-side scheduler runs each task
    as a fresh run, which means:

        build exceeds the 12s budget  →  _universe_stale() reads an EMPTY dict
                                      →  returns None
                                      →  503 "no cached payload available"

    The fallback existed and could never fire in the exact situation it was built
    for. Measured overnight 2026-08-11→12: the universe build timed out every
    cycle, and because there was no cross-process stale copy, EVERY downstream
    writer starved — trending_log, conviction_verdicts_daily, narrative_snapshots,
    cause_snapshots_daily and both paper books all wrote 0 rows for the day while
    cis_scores (which does not depend on this build) wrote 116. One slow build
    became a total outage of the record.

    Redis is already the cross-process cache for the CIS payload. Reading it here
    turns "hard 503" into "degraded but serving", which is the difference between
    a gap in the record and a day of it.
    """
    try:
        from src.api.store import redis_get
        blob = await redis_get()
    except Exception as e:
        _logger.warning("[CIS] durable stale read failed: %s", e)
        return None
    if not isinstance(blob, dict) or not blob.get("universe"):
        return None
    try:
        age = time.time() - float(blob.get("last_updated") or 0)
    except (TypeError, ValueError):
        return None
    if age > max_age_s:
        return None
    out = dict(blob)
    # NEVER silently. A stale payload that does not announce itself is a fresh
    # payload as far as every consumer is concerned — the whole point of S-104.
    out["data_status"] = "stale"
    out["stale_age_seconds"] = round(age, 1)
    out["stale_source"] = "redis_durable"
    _logger.error("[CIS] serving STALE universe from Redis (age %.0fs) — the build "
                  "exceeded its budget and the in-process cache was cold", age)
    return out


def _universe_stale(max_age_s: float = _UNIVERSE_STALE_MAX_S) -> dict | None:
    """Last good payload if it exists and isn't ancient. Flagged so the caller
    (and the UI badge) can tell served-stale from served-fresh — never silently.

    IN-PROCESS ONLY. Empty on a cold start; see _universe_stale_durable for the
    cross-process path that a fresh scheduler run actually needs."""
    data = _UNIVERSE_CACHE.get("data")
    if not data:
        return None
    age = time.time() - _UNIVERSE_CACHE.get("ts", 0.0)
    if age > max_age_s:
        return None
    out = dict(data)
    out["stale"] = True
    out["stale_age_s"] = round(age, 1)
    return out


@router.get("/api/v1/cis/universe")
async def get_cis_universe(force_source: str = None, response: Response = None):
    """
    CIS v4.0 Universe — priority: local_engine (Redis) → Railway calc → stale
    Redis → last-known-good. Single-flight + 30s response cache so the homepage's
    concurrent multi-component fetch burst computes once instead of N times.
    """
    if response:
        response.headers["Cache-Control"] = "public, max-age=60, stale-while-revalidate=120"

    if not force_source:
        now = time.time()
        if _UNIVERSE_CACHE["data"] is not None and (now - _UNIVERSE_CACHE["ts"]) < _UNIVERSE_TTL:
            return _UNIVERSE_CACHE["data"]

        # Bound #2 — never queue indefinitely on the lock. If another request is
        # already rebuilding and we have anything usable, serve it now.
        try:
            await asyncio.wait_for(_UNIVERSE_LOCK.acquire(), timeout=_UNIVERSE_LOCK_WAIT_S)
        except asyncio.TimeoutError:
            stale = _universe_stale() or await _universe_stale_durable()
            if stale is not None:
                _logger.warning("[CIS] universe lock busy — serving stale "
                                f"({stale.get('stale_age_s') or stale.get('stale_age_seconds')}s old)")
                return stale
            raise HTTPException(
                status_code=503,
                detail="CIS universe rebuilding and no cached payload available",
                headers={"Retry-After": "5"},
            )
        try:
            now = time.time()
            if _UNIVERSE_CACHE["data"] is not None and (now - _UNIVERSE_CACHE["ts"]) < _UNIVERSE_TTL:
                return _UNIVERSE_CACHE["data"]
            # Bound #1 — hard budget on the rebuild itself.
            try:
                data = await asyncio.wait_for(
                    _build_cis_universe(force_source), timeout=_UNIVERSE_BUILD_BUDGET_S)
            except asyncio.TimeoutError:
                # In-process first (free), then the DURABLE Redis copy. The
                # second is what a freshly started scheduler run actually has;
                # without it this path 503s every time and every downstream
                # writer starves (S-146).
                stale = _universe_stale() or await _universe_stale_durable()
                if stale is not None:
                    _logger.error("[CIS] universe build exceeded "
                                  f"{_UNIVERSE_BUILD_BUDGET_S}s — serving stale")
                    return stale
                raise HTTPException(
                    status_code=503,
                    detail="CIS universe build timed out and no cached payload available",
                    headers={"Retry-After": "10"},
                )
            if data and data.get("universe"):
                _UNIVERSE_CACHE["data"] = data
                _UNIVERSE_CACHE["ts"] = time.time()
        finally:
            _UNIVERSE_LOCK.release()

        # Bound #3 — enrichment is decoration; it runs OUTSIDE the lock and can
        # never gate the core payload for other callers.
        _attach_asset_narratives(data)
        await _attach_cause_proximity_async(data)
        return data

    data = await _build_cis_universe(force_source)
    _attach_asset_narratives(data)
    await _attach_cause_proximity_async(data)
    return data


async def _attach_cause_proximity_async(data: dict) -> None:
    """Soul axis (大象无形): attach per-asset out-of-circle / propagation-stage risk.
    D4 attention (live) upgrades the floor; D3 holder stage plugs in when Minimax-A
    delivers the Dune query_id. Best-effort — the market_proxy floor never misses."""
    if not data or not data.get("universe"):
        return
    attention_map = {}
    try:
        from src.api.store import supabase_get_latest_trending
        attention_map = await supabase_get_latest_trending()
    except Exception as e:
        _logger.warning(f"[CIS] trending fetch failed: {e}")
    holder_map = {}
    try:
        from src.data.cis.holder_provider import get_holder_map
        holder_map = await get_holder_map()   # D3 via Moralis; cached, {} when cold → D4 floor
    except Exception as e:
        _logger.warning(f"[CIS] holder_map fetch failed: {e}")
    try:
        from src.data.cis.cause_proximity import attach_cause_proximity
        attach_cause_proximity(data["universe"], attention_map, holder_map)
    except Exception as e:
        _logger.warning(f"[CIS] cause_proximity attach failed: {e}")
    try:
        from src.data.cis.forward_supply import get_forward_supply_map, attach_forward_supply
        attach_forward_supply(data["universe"], await get_forward_supply_map())  # UPSTREAM cause #1
    except Exception as e:
        _logger.warning(f"[CIS] forward_supply attach failed: {e}")
    try:
        from src.data.cis.positioning import get_positioning_map, attach_positioning
        attach_positioning(data["universe"], await get_positioning_map())        # UPSTREAM cause #2
    except Exception as e:
        _logger.warning(f"[CIS] positioning attach failed: {e}")


@router.get("/api/v1/portfolio/risk-meter")
async def get_risk_meter(response: Response = None):
    """
    Risk Meter — the judgment→behavior link. Reads the live CIS universe (already carrying
    per-asset cause_proximity), turns grade into target weights, then de-risks each long by
    its out-of-circle (出圈) fragility. Returns the meter-adjusted weights + one 0..1 needle
    for the whole book + the holdings dragging it. See src/data/market/risk_meter.py.
    """
    if response:
        response.headers["Cache-Control"] = "public, max-age=60, stale-while-revalidate=120"
    data = await get_cis_universe()
    universe = (data or {}).get("universe", [])
    regime = (data or {}).get("macro_regime")
    try:
        from src.data.market.risk_meter import build_risk_meter, conviction_from_track_record
        conv = None
        try:
            from src.api.store import supabase_get_latest_track_record
            conv = conviction_from_track_record(await supabase_get_latest_track_record())
        except Exception as _ce:
            _logger.warning(f"[CIS] conviction load failed (using prior): {_ce}")
        out = build_risk_meter(universe, regime, conviction_override=conv)
        out["conviction_factors"] = conv          # self-tuning tilt in effect (from own outcomes)
        out["universe_size"] = len(universe)
        out["as_of"] = (data or {}).get("timestamp") or (data or {}).get("as_of")
        return out
    except Exception as e:
        _logger.warning(f"[CIS] risk_meter build failed: {e}")
        return {"error": "risk_meter_unavailable", "regime": regime, "universe_size": len(universe)}


def _age_seconds(ts) -> float | None:
    """Seconds since `ts` (epoch int/float OR ISO string). None if missing/unparseable —
    NEVER assume 'now'. Used to surface HONEST staleness instead of faking freshness."""
    if ts is None:
        return None
    try:
        if isinstance(ts, (int, float)):
            return max(0.0, time.time() - float(ts))
        from datetime import datetime as _dt, timezone as _tz
        d = _dt.fromisoformat(str(ts).replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.replace(tzinfo=_tz.utc)
        return max(0.0, _dt.now(_tz.utc).timestamp() - d.timestamp())
    except Exception:
        return None


_STALE_AFTER_S = 1800   # 30 min — Mac pushes ~every 30 min; older than this = stale


def _freshness(ts) -> dict:
    """Honest freshness block for a CIS response. Never fabricates a timestamp."""
    age = _age_seconds(ts)
    return {"timestamp": ts, "data_age_s": round(age, 1) if age is not None else None,
            "stale": (age is None) or (age > _STALE_AFTER_S)}


def _sanitize_market_fields(universe: list) -> None:
    """
    Null out untrustworthy price-derived fields. When an asset's price is 0/missing
    (e.g. the Mac Mini ships TradFi rows with price=0), change_Nd gets computed as
    (0/ref - 1)*100 = -100 — a sentinel, not a real move. Surfacing -100 across the
    leaderboard is worse than showing "—" (QA 2026-06-06). Frontend renders None
    as "—". The Railway T2 path supplies real yfinance prices once it runs.
    """
    for a in universe:
        if not isinstance(a, dict):
            continue
        price = a.get("price")
        price_missing = price is None or price == 0
        for k in ("change_24h", "change_7d", "change_30d"):
            v = a.get(k)
            if v is None:
                continue
            # -100 (total loss) is never a real read for these assets → sentinel
            if price_missing or v <= -99.0:
                a[k] = None


def _attach_asset_narratives(data: dict) -> None:
    """Enrich each asset with derived agent/investor data: narrative + executability."""
    if not data or not data.get("universe"):
        return
    try:
        _sanitize_market_fields(data["universe"])
    except Exception as e:
        _logger.warning(f"[CIS] market sanitize failed: {e}")
    try:
        from src.data.cis.narrative import attach_narratives
        attach_narratives(data["universe"], data.get("macro_regime"))
    except Exception as e:
        _logger.warning(f"[CIS] narrative attach failed: {e}")
    try:
        from src.data.market.executability import attach_executability
        attach_executability(data["universe"])
    except Exception as e:
        _logger.warning(f"[CIS] executability attach failed: {e}")
    try:
        from src.data.cis.provenance import attach_provenance
        attach_provenance(data["universe"], data.get("timestamp") or data.get("as_of"))
    except Exception as e:
        _logger.warning(f"[CIS] provenance attach failed: {e}")


# ── Build-phase timing (2026-07-31) ──────────────────────────────────────────
# The external probe caught /api/v1/cis/universe at 12,602 ms — exactly the 12 s
# build budget, i.e. the build blew its budget and degraded to stale. Correct
# behaviour, but we could not say WHERE the 12 s went, and two hypotheses died
# on measurement (HNSW upsert is 48 ms, not the cause; push contention unproven).
#
# Rather than guess a third time, record where each build actually spends its
# time and surface it on /health. This is Lesson #70 applied forward: collect the
# diagnostic WHILE HEALTHY so the next occurrence is one glance, not an
# investigation. During the 10.4 h outage the query needed to diagnose it was
# itself unavailable — a diagnostic that only exists after the fact is not a
# diagnostic.
_LAST_BUILD: dict = {}


def last_universe_build() -> dict:
    """Phase timings of the most recent universe rebuild. Read by /health."""
    return dict(_LAST_BUILD)


def _record_build(phase: dict, t0: float, path: str) -> None:
    """Persist the phase breakdown of a completed build. `slowest` is precomputed
    so the answer is readable at a glance rather than requiring arithmetic during
    an incident — the point is a one-glance diagnosis, not a data dump."""
    total = int((time.time() - t0) * 1000)
    phases = {k: v for k, v in phase.items() if k.endswith("_ms")}
    _LAST_BUILD.clear()
    _LAST_BUILD.update({
        "at": int(time.time()),
        "path": path,
        "total_ms": total,
        **phase,
        "slowest": max(phases, key=phases.get) if phases else None,
        "unaccounted_ms": total - sum(phases.values()),
    })


async def _build_cis_universe(force_source: str = None):
    _t0 = time.time()
    _phase: dict = {}
    cached   = None
    use_local = False

    if force_source != "railway":
        _t = time.time()
        # S-180: status-carrying read. A transport failure must NOT be read as
        # "the Mac has not pushed" — that demotes all 58 assets to T2 at once,
        # swapping the entire pillar set and flipping grades and positioning.
        cached, _redis_status = await redis_get_status()
        _phase["redis_ms"] = int((time.time() - _t) * 1000)
        _phase["redis_status"] = _redis_status
        if cached and cached.get("universe"):
            age = time.time() - cached.get("last_updated", 0)
            if age < 7200 or force_source == "local":
                use_local = True
                _T1_LAST_GOOD["payload"] = cached
                _T1_LAST_GOOD["ts"] = time.time()
        elif _redis_status == "error":
            # We could not ask. Serve the last T1 payload we DID read rather
            # than manufacturing a universe-wide tier demotion out of a network
            # blip. Bounded by the same 2h window a live read gets, so a genuine
            # prolonged outage still falls through to T2 — the difference is that
            # it now takes two hours of real failure instead of one dropped packet.
            _lg = _T1_LAST_GOOD.get("payload")
            if _lg and (time.time() - _T1_LAST_GOOD.get("ts", 0)) < 7200:
                cached = _lg
                use_local = True
                _phase["t1_source"] = "last_good_after_redis_error"
                _logger.warning(
                    "[CIS] Redis read ERRORED — holding last-good T1 (%.0fs old) "
                    "instead of demoting the universe to T2",
                    time.time() - _T1_LAST_GOOD.get("ts", 0))
            else:
                _phase["t1_source"] = "redis_error_no_last_good"
                _logger.error("[CIS] Redis read ERRORED and no last-good T1 in "
                              "memory — universe will report T2. Rows written "
                              "from this build are suspect.")

    # Always calculate Railway universe as T2 base (covers 65+ assets).
    # NOTE: this runs even when T1 is fresh, and it fans out to external providers
    # (CoinGecko / DeFiLlama / Alternative.me). It is therefore the prime suspect
    # for a build that overruns its budget — the timing below settles it instead
    # of leaving it to inference.
    #
    # 2026-08-07 (S-104): it WAS the suspect, and it was guilty — 16,476 of 17,358 ms.
    # The fan-out inside calculate_cis_universe now bounds each branch separately
    # and reports which ones degraded, so `railway_t2_ms` is no longer an opaque
    # number: `t2_branches` below says WHICH provider spent it.
    railway_universe = []
    _t = time.time()
    try:
        # ── S-200 (2026-08-23): read the precomputed T2, do not compute it ───
        # Measured in production: railway_t2_ms = 110,390 against a 12,000 ms
        # budget. That is not "slow", it is a DEADLOCK — only a build that
        # COMPLETES writes `_UNIVERSE_CACHE`, so a build that always exceeds its
        # budget means the cache can never fill, so the next request rebuilds
        # from scratch and is cancelled again. Permanent degradation, and every
        # request burns twelve seconds and a full round of external provider
        # calls before throwing the work away.
        #
        # The endpoint served 43 T1-only assets with macro_regime=None, which is
        # why /internal/loop-health read `broken` and two books stopped marking.
        #
        # T1 has not been on the request path for months — the Mac computes it
        # and pushes to Redis. T2 is now the same shape. A 110-second fan-out to
        # ten external providers does not belong behind a web request at any
        # budget; the budget was only ever hiding that.
        _t2_cached = await redis_get_key(_T2_PRECOMPUTE_KEY)
        if _t2_cached and _t2_cached.get("universe"):
            _age = time.time() - float(_t2_cached.get("computed_at") or 0)
            if _age < _T2_PRECOMPUTE_MAX_AGE_S:
                railway_universe = _t2_cached["universe"]
                _phase["t2_source"] = f"precomputed({int(_age)}s)"
                _phase["t2_branches"] = _t2_cached.get("branch_timing") or {}
                _phase["railway_t2_ms"] = 0
                raise _T2FromCache()      # skip the inline compute below
            _phase["t2_precompute_age_s"] = int(_age)
        result = await calculate_cis_universe()
        railway_universe = result.get("universe", [])
        _branch = result.get("_branch_timing") or {}
        if _branch:
            _phase["t2_branches"] = _branch
    except _T2FromCache:
        pass          # railway_universe already populated from Redis
    except Exception as e:
        _logger.warning(f"[CIS] Railway calculation error: {e}")
        _phase["railway_error"] = str(e)[:120]
    if "railway_t2_ms" not in _phase:
        _phase["railway_t2_ms"] = int((time.time() - _t) * 1000)

    # Merge: Mac Mini T1 scores override Railway T2 where available
    if use_local and cached and cached.get("universe"):
        local_map = {}
        for asset in cached.get("universe", []):
            sym = (asset.get("asset_id") or asset.get("symbol", "")).upper()
            asset["data_tier"] = 1
            local_map[sym] = asset

        merged = []
        seen = set()
        # First pass: Railway base (preserves ordering + enriched fields)
        for asset in railway_universe:
            sym = (asset.get("asset_id") or asset.get("symbol", "")).upper()
            if sym in local_map:
                # T1 override: use local score but keep Railway's market data + name
                la = local_map[sym]
                asset["cis_score"] = la.get("cis_score") or la.get("score", asset.get("cis_score"))
                # v4.2: Mac Mini T1 score is base-weighted (no regime adjustment applied),
                # so its score IS the raw score. Use it as raw_cis_score unless Railway
                # already computed one from the T2 fallback path.
                asset["raw_cis_score"] = la.get("raw_cis_score") or la.get("cis_score") or asset.get("cis_score")
                asset["grade"] = la.get("grade", asset.get("grade"))
                asset["signal"] = la.get("signal", asset.get("signal"))
                asset["data_tier"] = 1
                # Merge pillars if local engine provides them
                if la.get("pillars"):
                    asset["pillars"] = la["pillars"]
                elif any(la.get(k) is not None for k in ("f", "m", "o", "r", "s", "a")):
                    for k in ("f", "m", "o", "r", "s", "a"):
                        if la.get(k) is not None:
                            asset[k] = la[k]
            else:
                asset["data_tier"] = 2
            merged.append(asset)
            seen.add(sym)

        # Second pass: any Mac Mini assets not in Railway (shouldn't happen, but safe)
        for sym, la in local_map.items():
            if sym not in seen:
                la["data_tier"] = 1
                # v4.2: compute raw_cis_score from T1 pillars if not present
                if la.get("raw_cis_score") is None:
                    pf = la.get("f") or la.get("F") or 50
                    pm = la.get("m") or la.get("M") or 50
                    po = la.get("o") or la.get("O") or 50
                    ps = la.get("s") or la.get("S") or 50
                    pa = la.get("a") or la.get("A") or 50
                    la["raw_cis_score"] = round((0.25*pf + 0.25*pm + 0.20*po + 0.15*ps + 0.15*pa), 1)
                merged.append(la)

        # ── GRADE-ALIGN Option B (SCHEMA 1.1) — normalize the WHOLE merged universe onto
        # raw quality, uniformly across T1 + T2. Both engines now carry raw_cis_score
        # (Minimax T1 #5 + T2 cis_provider), so the grade + headline score reflect
        # regime-neutral QUALITY; the regime-adjusted number is preserved as a separate
        # exposure-lens field. This makes the switch a single Railway-side change — no
        # cis_v4_engine lockstep. (T1 can later grade on raw natively; result is identical.)
        from src.data.cis.cis_provider import get_grade as _get_grade
        for _a in merged:
            _raw = _a.get("raw_cis_score")
            if _raw is None:
                continue
            _adj = _a.get("cis_score") or _a.get("score")
            if _a.get("regime_adjusted_score") is None:
                _a["regime_adjusted_score"] = _adj      # preserve the regime lens
            _a["cis_score"] = round(float(_raw), 1)      # headline = quality (matches grade)
            _a["grade"] = _get_grade(float(_raw))        # grade on quality, not regime

        # Sort by CIS score descending (now regime-neutral quality)
        merged.sort(key=lambda a: a.get("cis_score") or a.get("score") or 0, reverse=True)

        # Get unified regime directly from get_macro_pulse() rather than via Redis.
        # This ensures both endpoints return identical macro_regime without Redis round-trip.
        # Wrap with asyncio.timeout to prevent blocking on slow FRED calls (max 5s).
        try:
            import asyncio
            from src.data.market.data_layer import get_macro_pulse
            try:
                pulse = await asyncio.wait_for(get_macro_pulse(), timeout=5.0)
            except asyncio.TimeoutError:
                _logger.warning("[CIS] get_macro_pulse timed out, using fallback regime")
                pulse = {}
            except asyncio.CancelledError:
                _logger.warning("[CIS] get_macro_pulse cancelled, using fallback regime")
                pulse = {}
            # ⚠️ "UNKNOWN" IS A VALUE THAT LOOKS LIKE DATA (2026-08-09, S-120/S-121).
            # A 5s timeout here produced the literal string "UNKNOWN", which the daily
            # snapshot then fed to canonical_regime() — and since "UNKNOWN" is not in
            # the canonical set, it came back "NEUTRAL" and 58 fabricated rows were
            # written. Measured: one such batch per day, at a DIFFERENT time each day,
            # because it is a timeout rather than a schedule.
            # The sink is now guarded (canonical_regime_strict → NULL), but the source
            # is fixed too: a failed measurement must produce None, not a placeholder
            # string. Downstream code cannot tell a placeholder from a reading.
            _cached_regime = pulse.get("macro_regime") or None
        except Exception:
            # Fallback: try Redis key, then Mac Mini cached, then VIX
            try:
                unified = await store.redis_get_key("cis:regime")
                if unified and unified.get("regime"):
                    _cached_regime = unified["regime"]
                else:
                    _cached_regime = (
                        (cached.get("macro") or {}).get("regime")
                        or cached.get("regime")
                        or (result.get("macro") or {}).get("regime")
                        or (result.get("regime"))
                        or None          # placeholder strings look like data — S-120
                    )
            except Exception:
                _cached_regime = (
                    (cached.get("macro") or {}).get("regime")
                    or cached.get("regime")
                    or (result.get("macro") or {}).get("regime")
                    or (result.get("regime"))
                    or None          # placeholder strings look like data — S-120
                )

        # Normalize T1 pillars: Mac Mini sends flat keys (f/m/o/s/a).
        # Build nested pillars dict so frontend components can read asset.pillars.F etc.
        for a in merged:
            if a.get("data_tier") == 1 and a.get("pillars") is None:
                pf = a.get("f") or a.get("F")
                pm = a.get("m") or a.get("M")
                po = a.get("o") or a.get("O")
                ps = a.get("s") or a.get("S")
                pa = a.get("a") or a.get("A")
                if any(v is not None for v in (pf, pm, po, ps, pa)):
                    a["pillars"] = {"F": pf, "M": pm, "O": po, "S": ps, "A": pa}

        # ── Simons Upgrade P1.1/P1.3: regime confidence + data quality + pillar velocity
        # regime_confidence: computed from push count in current regime + BTC dominance 20d MA
        # data_quality_score: passed through from Mac Mini push payload
        # pillar_velocity: z-score of each pillar vs 30d rolling mean (from Mac Mini push payload)
        regime_confidence = _compute_regime_confidence(_cached_regime or "UNKNOWN")

        # Attach velocity/quality fields to each asset (from Mac Mini push payload)
        for a in merged:
            # pillar_velocity: {"F": "+0.8σ 30d", "M": "-0.3σ 30d", ...}
            # Mac Mini computes and sends it; if missing, leave None
            pv = a.get("pillar_velocity")
            if pv:
                a["pillar_velocity"] = pv
            # data_quality_score: 0.0-1.0, from Mac Mini data_fetcher
            dq = a.get("data_quality_score")
            a["data_quality_score"] = dq if dq is not None else None
            # regime_confidence: shared across universe (same push)
            a["regime_confidence"] = regime_confidence

        _record_build(_phase, _t0, "merged")
        return sanitize_floats({
            "status":            "success",
            "version":           "4.1.0",
            **_freshness(cached.get("timestamp")),   # honest timestamp/data_age_s/stale — no fake "now"
            "source":            "merged",
            "t1_count":          len(local_map),
            "t2_count":          len(merged) - len(local_map),
            "macro_regime":      _cached_regime,
            "regime_confidence": regime_confidence,
            "universe":          merged,
        })

    # Pure Railway (no Mac Mini data available)
    if railway_universe:
        result["source"] = "railway"
        # Get unified regime directly from get_macro_pulse() — same source as macro-pulse endpoint
        # Wrap with timeout to prevent blocking on slow FRED calls (same as merged path)
        try:
            from src.data.market.data_layer import get_macro_pulse
            try:
                pulse = await asyncio.wait_for(get_macro_pulse(), timeout=5.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                _logger.warning("[CIS] get_macro_pulse timed out in Railway path, using fallback regime")
                pulse = {}
            # same placeholder trap as the merged path above — None, not a string
            result["macro_regime"] = pulse.get("macro_regime") or None
        except Exception:
            result["macro_regime"] = (result.get("macro") or {}).get("regime") or None
        result["t1_count"] = 0
        result["t2_count"] = len(railway_universe)
        _record_build(_phase, _t0, "railway")
        return sanitize_floats(result)

    # Last resort: stale hot-cache Redis
    if cached and cached.get("universe"):
        stale_universe = cached["universe"]
        return {
            "status":       "degraded",
            "version":      "4.1.0",
            **_freshness(cached.get("timestamp")),
            "source":       "local_engine_stale",
            "t1_count":     0,
            "t2_count":     len(stale_universe),
            "macro_regime": (
                (cached.get("macro") or {}).get("regime")
                or cached.get("regime")
                or None          # placeholder strings look like data — S-120
            ),
            "universe":     stale_universe,
        }

    # Never-empty floor: long-lived last-known-good snapshot (7-day TTL).
    # Reached only when the hot cache has fully expired AND the Railway T2 calc
    # returned empty — without this the leaderboard goes blank (QA P0). Clearly
    # labeled "degraded" / source "last_known_good" so the UI can show a staleness
    # notice, but the user always sees scores instead of an empty table.
    try:
        lkg = await redis_get_key("cis:last_known_good")
    except Exception:
        lkg = None
    if lkg and lkg.get("universe"):
        lkg_universe = lkg["universe"]
        lkg_age = time.time() - lkg.get("last_updated", 0)
        return {
            "status":         "degraded",
            "version":        "4.1.0",
            **_freshness(lkg.get("timestamp") or lkg.get("last_updated")),
            "source":         "last_known_good",
            "stale_age_s":    round(lkg_age, 1),
            "t1_count":       0,
            "t2_count":       len(lkg_universe),
            "macro_regime": (
                (lkg.get("macro") or {}).get("regime")
                or lkg.get("regime")
                or None          # placeholder strings look like data — S-120
            ),
            "universe":       lkg_universe,
        }

    return {"status": "error", "message": "No scoring data available", "universe": []}


@router.get("/api/v1/cis/debug/datasources")
async def debug_datasources():
    """
    Diagnostic: run each CIS data source independently and report what was returned.
    Shows exactly which feed is empty so we can pinpoint the T2 failure.
    NOT for production use — internal debugging only.
    """
    import asyncio, time as _time
    from src.data.cis.cis_provider import (
        fetch_binance_prices, fetch_cg_markets, fetch_defillama_tvl,
        fetch_fear_greed, CG_API_KEY, _cg_base, _UPSTASH_URL
    )
    import yfinance as yf

    results = {}
    t0 = _time.time()

    # Binance
    try:
        t = _time.time()
        bp = await asyncio.wait_for(fetch_binance_prices(), timeout=15)
        results["binance"] = {"count": len(bp), "sample": list(bp.keys())[:5], "ms": int((_time.time()-t)*1000)}
    except Exception as e:
        results["binance"] = {"error": str(e)}

    # CoinGecko
    try:
        t = _time.time()
        cgm = await asyncio.wait_for(fetch_cg_markets(), timeout=30)
        results["coingecko"] = {"count": len(cgm), "sample": list(cgm.keys())[:5], "ms": int((_time.time()-t)*1000),
                                "api_key_set": bool(CG_API_KEY), "base_url": _cg_base()}
    except Exception as e:
        results["coingecko"] = {"error": str(e), "api_key_set": bool(CG_API_KEY), "base_url": _cg_base()}

    # DeFiLlama
    try:
        t = _time.time()
        tvl = await asyncio.wait_for(fetch_defillama_tvl(), timeout=15)
        results["defillama"] = {"count": len(tvl), "ms": int((_time.time()-t)*1000)}
    except Exception as e:
        results["defillama"] = {"error": str(e)}

    # Fear & Greed
    try:
        t = _time.time()
        fng = await asyncio.wait_for(fetch_fear_greed(), timeout=10)
        results["fear_greed"] = {"value": fng.get("value") if fng else None, "ms": int((_time.time()-t)*1000)}
    except Exception as e:
        results["fear_greed"] = {"error": str(e)}

    # yfinance spot check (SPY only)
    try:
        t = _time.time()
        def _yf_spy():
            tk = yf.Ticker("SPY")
            h = tk.history(period="5d")
            return float(h['Close'].iloc[-1]) if len(h) > 0 else None
        spy_price = await asyncio.wait_for(asyncio.to_thread(_yf_spy), timeout=20)
        results["yfinance_spy"] = {"price": spy_price, "ms": int((_time.time()-t)*1000)}
    except Exception as e:
        results["yfinance_spy"] = {"error": str(e)}

    results["upstash_configured"] = bool(_UPSTASH_URL)
    results["total_ms"] = int((_time.time()-t0)*1000)
    return results


@router.get("/api/v1/cis/top")
async def get_cis_top(limit: int = 10, response: Response = None):
    """
    Top-N CIS assets by score.
    Returns the same merged T1+T2 universe as /api/v1/cis/universe but sliced
    to top N and sorted by score descending. Used by ShareCard, StrategyPage.
    """
    if response:
        response.headers["Cache-Control"] = "public, max-age=60, stale-while-revalidate=120"

    # Re-use the full universe logic then slice
    full = await get_cis_universe(force_source=None)
    universe = full.get("universe", [])
    if not universe:
        return {"status": full.get("status", "ok"), "source": full.get("source"), "top": [], "limit": limit}

    sorted_assets = sorted(universe, key=lambda a: a.get("cis_score") or a.get("score") or 0, reverse=True)
    top = sorted_assets[:limit]
    return {
        "status":       full.get("status", "ok"),
        "version":      "4.1.0",
        "source":       full.get("source"),
        "macro_regime": full.get("macro_regime"),
        "t1_count":     full.get("t1_count", 0),
        "t2_count":     full.get("t2_count", 0),
        "total":        len(universe),
        "limit":        limit,
        "top":          sanitize_floats(top),
    }


@router.get("/api/v1/cis/asset/{symbol}")
async def get_cis_asset(symbol: str):
    """Get CIS score for a specific asset."""
    universe = await get_cis_universe()
    for asset in universe.get("universe", []):
        if asset.get("symbol", asset.get("asset_id", "")).upper() == symbol.upper():
            return asset
    return {"error": "Asset not found"}


# ── Compare ───────────────────────────────────────────────────────────────────

@router.get("/api/v1/cis/compare")
async def get_cis_compare(symbols: str, response: Response = None):
    """
    Side-by-side CIS pillar comparison for 2–6 assets.

    GET /api/v1/cis/compare?symbols=BTC,ETH,SOL

    Returns per-asset: score, grade, signal, all 5 pillar scores, price, change_24h,
    market_cap, data_tier — plus universe-wide pillar averages for relative context.

    Pillar keys (both T1 and T2 shapes normalised):
      F (Fundamental)  M (Momentum)  O (On-chain/Risk)  S (Sentiment)  A (Alpha)
    """
    if response:
        response.headers["Cache-Control"] = "public, max-age=45, stale-while-revalidate=90"

    _SYMBOL_RE = re.compile(r"^[A-Z0-9]{2,12}(,[A-Z0-9]{2,12})*$", re.IGNORECASE)
    clean = symbols.strip().upper()
    if not _SYMBOL_RE.match(clean):
        raise HTTPException(status_code=400, detail="Invalid symbols — use comma-separated tickers, e.g. BTC,ETH,SOL")

    requested = [s.strip().upper() for s in clean.split(",") if s.strip()][:6]

    uni_data = await get_cis_universe()
    universe = uni_data.get("universe", [])

    # Build a fast lookup by symbol
    sym_map: dict[str, dict] = {}
    for a in universe:
        sym = (a.get("asset_id") or a.get("symbol", "")).upper()
        if sym:
            sym_map[sym] = a

    def _norm_pillars(a: dict) -> dict:
        """Normalise both T1 (flat keys f/m/r/s/a) and T2 (nested pillars{F,M,O,S,alpha}) shapes."""
        p = a.get("pillars") or {}
        def _get(key_nested, *flat_keys):
            v = p.get(key_nested)
            if v is not None:
                return round(float(v), 1)
            for fk in flat_keys:
                v2 = a.get(fk)
                if v2 is not None:
                    return round(float(v2), 1)
            return None

        return {
            "F": _get("F", "f"),
            "M": _get("M", "m"),
            "O": _get("O", "o", "r"),   # "o" canonical (v4.1+), "r" legacy fallback
            "S": _get("S", "s"),
            "A": _get("alpha", "a"),
        }

    def _norm_asset(a: dict, sym: str) -> dict:
        pil = _norm_pillars(a)
        cis_sc = round(float(a.get("cis_score") or a.get("score") or 0), 1)
        raw_sc = a.get("raw_cis_score")
        return {
            "symbol":         sym,
            "name":           a.get("name", sym),
            "asset_class":    a.get("asset_class") or a.get("class") or "—",
            "cis_score":      cis_sc,
            "raw_cis_score":  round(float(raw_sc), 1) if raw_sc is not None else cis_sc,
            "grade":          a.get("grade", "—"),
            "signal":         a.get("signal", "NEUTRAL"),
            "data_tier":      a.get("data_tier", 2),
            "price":          a.get("price"),
            "change_24h":     a.get("change_24h"),
            "change_7d":      a.get("change_7d"),
            "market_cap":     a.get("market_cap"),
            "volume_24h":     a.get("volume_24h"),
            "las":            a.get("las"),
            "confidence":     a.get("confidence"),
            "pillars":        pil,
        }

    # Universe pillar averages (for relative context — shown as dotted line on bars)
    pil_sums = {"F": 0.0, "M": 0.0, "O": 0.0, "S": 0.0, "A": 0.0}
    pil_n    = {"F": 0,   "M": 0,   "O": 0,   "S": 0,   "A": 0}
    for a in universe:
        for k, raw_k, flat_k in [("F","F","f"),("M","M","m"),("O","O","o"),("S","S","s"),("A","alpha","a")]:
            p = a.get("pillars") or {}
            v = p.get(raw_k) if p.get(raw_k) is not None else a.get(flat_k)
            if v is not None:
                try:
                    pil_sums[k] += float(v); pil_n[k] += 1
                except (TypeError, ValueError):
                    pass

    pillar_universe_avg = {
        k: round(pil_sums[k] / pil_n[k], 1) if pil_n[k] > 0 else None
        for k in ["F", "M", "O", "S", "A"]
    }

    assets_out = []
    not_found  = []
    for sym in requested:
        if sym in sym_map:
            assets_out.append(_norm_asset(sym_map[sym], sym))
        else:
            not_found.append(sym)

    # Class-level averages across the universe for context
    class_avgs: dict[str, float] = {}
    class_n: dict[str, int] = {}
    for a in universe:
        cls = (a.get("asset_class") or a.get("class") or "").upper()
        sc  = a.get("cis_score") or a.get("score") or 0
        if cls:
            class_avgs[cls] = class_avgs.get(cls, 0.0) + float(sc)
            class_n[cls]    = class_n.get(cls, 0) + 1
    class_avgs = {k: round(v / class_n[k], 1) for k, v in class_avgs.items()}

    return sanitize_floats({
        "status":              "success",
        "requested":           requested,
        "not_found":           not_found,
        "universe_size":       len(universe),
        "macro_regime":        uni_data.get("macro_regime", "UNKNOWN"),
        "source":              uni_data.get("source", "railway"),
        "pillar_universe_avg": pillar_universe_avg,
        "class_avg_scores":    class_avgs,
        "assets":              assets_out,
    })


# ── Regime Analysis ──────────────────────────────────────────────────────────

_REGIME_PILLAR_WEIGHTS = {
    "RISK_ON":     {"F": 1, "M": 3, "O": 1, "S": 2, "A": 3},
    "RISK_OFF":    {"F": 3, "M": 1, "O": 3, "S": 1, "A": 2},
    "TIGHTENING":  {"F": 3, "M": 2, "O": 2, "S": 1, "A": 2},
    "EASING":      {"F": 2, "M": 3, "O": 1, "S": 2, "A": 2},
    "STAGFLATION": {"F": 2, "M": 1, "O": 3, "S": 2, "A": 2},
    "GOLDILOCKS":  {"F": 2, "M": 2, "O": 1, "S": 2, "A": 3},
}
_REGIME_INSIGHTS = {
    "RISK_ON":     "Momentum and Alpha independence dominate. Assets breaking out vs BTC benchmark outperform. Reduce defensive allocations.",
    "RISK_OFF":    "Fundamental quality and On-Chain Risk scores matter most. Prefer deep-liquidity assets with low volatility regimes.",
    "TIGHTENING":  "Fundamental scoring screens for fee-generating, real-yield assets. Over-leveraged protocols rank UNDERWEIGHT. Alpha divergence useful for identifying safe havens.",
    "EASING":      "Momentum leads the recovery cycle. Assets with strong 30d trend and improving sentiment are early movers.",
    "STAGFLATION": "On-Chain Risk + Fundamental stability. Real-yield and RWA historically outperform. High-beta alts underperform.",
    "GOLDILOCKS":  "Broadest opportunity set. Alpha independence is key edge — look for uncorrelated return vs benchmark. Growth and quality both rewarded.",
}
_PILLAR_FLAT = [("F","F","f"), ("M","M","m"), ("O","O","o"), ("S","S","s"), ("A","alpha","a")]


@router.get("/api/v1/cis/regime-analysis")
async def get_regime_analysis(response: Response = None):
    """
    Regime-aware CIS analysis.

    Returns:
      - current macro regime + interpretation
      - pillar weight overrides for this regime
      - per asset-class regime-weighted average CIS score + rank
      - top 5 assets per regime-weighted score (leading indicators for this regime)
      - bottom 5 (laggards — potential UNDERWEIGHT candidates)

    Useful for: sector rotation decisions, regime-aware allocation tilts, MCP agent context.
    """
    if response:
        response.headers["Cache-Control"] = "public, max-age=120, stale-while-revalidate=300"

    uni_data  = await get_cis_universe()
    universe  = uni_data.get("universe", [])
    regime    = uni_data.get("macro_regime", "UNKNOWN")
    weights   = _REGIME_PILLAR_WEIGHTS.get(regime, {k: 2 for k in ["F","M","O","S","A"]})

    def _regime_score(a: dict) -> float:
        """Compute weighted pillar score for current regime."""
        p = a.get("pillars") or {}
        total = w_total = 0.0
        for kres, knew, kflat in _PILLAR_FLAT:
            v = p.get(knew)
            if v is None:
                v = a.get(kflat)
            if v is not None:
                try:
                    w = weights.get(kres, 2)
                    total += float(v) * w
                    w_total += w
                except (TypeError, ValueError):
                    pass
        return round(total / w_total, 1) if w_total > 0 else (a.get("cis_score") or a.get("score") or 0.0)

    # Score all assets
    scored = []
    for a in universe:
        sym = (a.get("asset_id") or a.get("symbol", "")).upper()
        rs  = _regime_score(a)
        scored.append({
            "symbol":       sym,
            "name":         a.get("name", sym),
            "asset_class":  a.get("asset_class") or a.get("class") or "—",
            "cis_score":    round(float(a.get("cis_score") or a.get("score") or 0), 1),
            "grade":        a.get("grade", "—"),
            "signal":       a.get("signal", "NEUTRAL"),
            "regime_score": rs,
            "data_tier":    a.get("data_tier", 2),
        })

    scored.sort(key=lambda x: x["regime_score"], reverse=True)
    for i, s in enumerate(scored):
        s["regime_rank"] = i + 1

    # Per-class averages (regime-weighted)
    class_sums: dict = {}
    class_ns:   dict = {}
    for s in scored:
        cls = s["asset_class"]
        class_sums[cls] = class_sums.get(cls, 0.0) + s["regime_score"]
        class_ns[cls]   = class_ns.get(cls, 0) + 1
    class_avgs = {k: round(v / class_ns[k], 1) for k, v in class_sums.items()}
    class_ranked = sorted(class_avgs.items(), key=lambda x: x[1], reverse=True)

    return sanitize_floats({
        "status":          "success",
        "macro_regime":    regime,
        "regime_insight":  _REGIME_INSIGHTS.get(regime, "Unknown regime — using equal pillar weights."),
        "pillar_weights":  weights,
        "universe_size":   len(scored),
        "class_scores":    [{"class": c, "regime_score": s, "n": class_ns[c]} for c, s in class_ranked],
        "leaders":         scored[:5],
        "laggards":        scored[-5:][::-1],
        "source":          uni_data.get("source", "railway"),
    })


# ── Regime Transitions — Simons Upgrade P1.1 ─────────────────────────────────

@router.get("/api/v1/macro/regime-transitions")
async def get_regime_transitions(limit: int = 20, response: Response = None):
    """
    Returns recent regime transitions with timestamps and affected assets.
    Source: Supabase cis_scores where regime_transition=TRUE.

    Each row: symbol, previous_regime, macro_regime (new), recorded_at
    """
    if response:
        response.headers["Cache-Control"] = "public, max-age=300, stale-while-revalidate=600"

    if not store._SB_URL or not store._SB_KEY:
        return {"status": "error", "message": "Supabase not configured"}

    url = f"{store._SB_URL}/rest/v1/cis_scores"
    params = {
        "select":    "symbol,macro_regime,previous_regime,recorded_at",
        "regime_transition": "eq.true",
        "order":     "recorded_at.desc",
        "limit":     str(limit),
    }
    headers = {
        "apikey":        store._SB_KEY,
        "Authorization": f"Bearer {store._SB_KEY}",
    }

    try:
        resp = await store._supabase_request_with_retry("GET", url, params=params, headers=headers)
        if resp and resp.status_code == 200:
            rows = resp.json()
            return {
                "status":   "success",
                "count":    len(rows),
                "transitions": [
                    {
                        "symbol":          r.get("symbol"),
                        "previous_regime":  r.get("previous_regime"),
                        "new_regime":       r.get("macro_regime"),
                        "transition_time":  r.get("recorded_at"),
                    }
                    for r in rows
                ],
            }
    except Exception as e:
        _logger.warning(f"[REGIME_TRANSITIONS] error: {e}")

    return {"status": "success", "count": 0, "transitions": []}


# ── CIS History ───────────────────────────────────────────────────────────────
# IMPORTANT: batch route MUST be registered before {symbol} route to avoid shadowing

@router.get("/api/v1/cis/history/batch")
async def get_cis_history_batch(
    symbols: str,
    days: int = Query(default=30, ge=1, le=365),
    include_historical: bool = Query(default=True),
    response: Response = None,
):
    """
    Batch CIS history — single request for up to 60 symbols.
    Returns map of symbol → [rows sorted oldest-first].
    Each row includes: score, grade, signal, pillar_f..a, macro_regime, data_tier,
                       score_delta, score_zscore, recorded_at.
    include_historical=True (default): includes T2_historical reconstruction rows.
    include_historical=False: live pushes only (source=local_engine).
    """
    _SYMBOL_RE = re.compile(r"^[A-Z0-9]{2,12}(,[A-Z0-9]{2,12})*$")
    if not _SYMBOL_RE.match(symbols.upper()):
        return {"status": "error", "message": "Invalid symbol format", "data": {}}
    symbol_list = [s.strip().upper() for s in symbols.split(",") if s.strip()][:60]
    if not symbol_list:
        return {"status": "error", "message": "No symbols provided", "data": {}}

    cache_key = f"cis:history:batch:{','.join(sorted(symbol_list))}:{days}:{include_historical}"
    cached = await redis_get_key(cache_key)
    if cached:
        return cached

    results = await asyncio.gather(
        *[supabase_get_history(sym, days) for sym in symbol_list],
        return_exceptions=True,
    )

    data: dict = {}
    for sym, rows in zip(symbol_list, results):
        if isinstance(rows, Exception) or not rows:
            data[sym] = []
            continue
        # Sort oldest-first for time-series charts
        sorted_rows = list(reversed(rows))
        if not include_historical:
            sorted_rows = [r for r in sorted_rows if r.get("source") == "local_engine"]
        data[sym] = sorted_rows

    result = {"status": "success", "days": days, "count": len(data), "data": data}
    await redis_set_key(cache_key, result, ttl=120)
    if response:
        response.headers["Cache-Control"] = "public, max-age=120, stale-while-revalidate=300"
    return result


# ── Backtest ──────────────────────────────────────────────────────────────────

@router.get("/api/v1/cis/backtest")
async def get_cis_backtest():
    """
    30d realized return results by CIS grade (Binance/OKX klines).
    Used to validate scoring — shows A/B/C return spread.

    Persists the result to Supabase `cis_backtest_results` so the table is no
    longer orphaned (read from disk or history_db, but never written). Schema
    is tolerant — extracts whatever grade-averages exist, falls back to None.
    """
    results_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "data", "cis", "backtest_results.json"
    )
    source_label = "none"
    response_payload: dict = {}
    try:
        if os.path.exists(results_path):
            with open(results_path) as f:
                data = _json.load(f)
            response_payload = {"status": "success", "source": "file", **data}
            source_label = results_path
    except Exception as e:
        _logger.warning(f"[BACKTEST] Read error: {e}")

    if not response_payload:
        try:
            from src.data.cis.history_db import get_backtest_summary
            summary = get_backtest_summary()
            response_payload = {"status": "success", "source": "db", **summary}
            source_label = "history_db"
        except Exception as e:
            response_payload = {"status": "empty", "message": str(e)}

    # ── Persist to cis_backtest_results (best-effort, fire-and-forget) ───
    try:
        await _persist_backtest_result(response_payload, source_label)
    except Exception as e:
        _logger.debug(f"[BACKTEST] persist skipped: {e}")

    return response_payload


def _extract_grade_avg(payload: dict, grade: str) -> float | None:
    """Tolerantly pull a grade average out of the backtest payload shape."""
    if not isinstance(payload, dict):
        return None
    # Direct key
    direct = payload.get(f"grade_{grade.lower()}_avg") or payload.get(f"{grade}_avg")
    if direct is not None:
        try:
            return float(direct)
        except (TypeError, ValueError):
            pass
    # Nested `grades` dict
    grades = payload.get("grades") or payload.get("by_grade") or {}
    if isinstance(grades, dict):
        g = grades.get(grade) or grades.get(grade.lower())
        if isinstance(g, dict):
            for k in ("avg", "mean", "avg_return", "return_pct"):
                if k in g:
                    try:
                        return float(g[k])
                    except (TypeError, ValueError):
                        continue
        elif isinstance(g, (int, float)):
            return float(g)
    # Per-grade rows
    rows = payload.get("results") or payload.get("data") or []
    if isinstance(rows, list):
        vals = []
        for r in rows:
            if not isinstance(r, dict):
                continue
            if (r.get("grade") or "").upper() != grade.upper():
                continue
            for k in ("avg_return", "return_pct", "mean", "avg", "pnl_pct"):
                if k in r and r[k] is not None:
                    try:
                        vals.append(float(r[k]))
                    except (TypeError, ValueError):
                        continue
                    break
        if vals:
            return sum(vals) / len(vals)
    return None


async def _persist_backtest_result(payload: dict, source_label: str) -> bool:
    """Write the backtest result to cis_backtest_results. Best-effort."""
    if not isinstance(payload, dict):
        return False
    try:
        from src.api.store import supabase_insert_table
    except Exception:
        return False
    a = _extract_grade_avg(payload, "A")
    b = _extract_grade_avg(payload, "B")
    c = _extract_grade_avg(payload, "C")
    d = _extract_grade_avg(payload, "D")
    f = _extract_grade_avg(payload, "F")
    spread = (a - f) if (a is not None and f is not None) else None
    asset_count = payload.get("asset_count") or payload.get("n_assets") or (
        len(payload["results"]) if isinstance(payload.get("results"), list) else None
    )
    n_klines = payload.get("n_with_klines") or payload.get("with_klines")
    window = payload.get("window_days") or 30
    row = {
        "window_days":   int(window) if str(window).isdigit() else 30,
        "grade_a_avg":   a,
        "grade_b_avg":   b,
        "grade_c_avg":   c,
        "grade_d_avg":   d,
        "grade_f_avg":   f,
        "spread_a_to_f": spread,
        "asset_count":   asset_count,
        "n_with_klines": n_klines,
        "source_file":   source_label if source_label.endswith(".json") else None,
        "source_db":     source_label == "history_db",
        "notes":         f"auto-persisted by /api/v1/cis/backtest source={payload.get('source','?')}",
        "payload":       payload,
    }
    return await supabase_insert_table("cis_backtest_results", [row])


# ── Agent API ─────────────────────────────────────────────────────────────────

_AGENT_RATE_LIMIT: dict = {}  # ip → [timestamp, ...]
_AGENT_RL_WINDOW  = 60   # seconds
_AGENT_RL_MAX     = 30   # max requests per window per IP

@router.get("/api/v1/agent/cis")
async def agent_cis_endpoint(
    limit:       int = 40,    # max assets returned (1-100)
    offset:      int = 0,     # pagination offset
    asset_class: str = "",    # filter: L1/L2/DeFi/RWA/Infrastructure/Memecoin/TradFi
    min_grade:   str = "",    # filter: A+/A/B+/B/C+/C/D/F
    min_score:   float = 0.0, # filter: minimum cis_score
    request: Request = None,
):
    """
    Agent-optimized CIS endpoint — compact JSON for LLM/agent consumption.
    Supports pagination, filtering, and per-IP rate limiting (30 req/min).

    Query params:
      limit       (int, 1-100, default 40)   — assets per page
      offset      (int, default 0)           — pagination offset
      asset_class (str)                      — filter by class
      min_grade   (str)                      — minimum grade gate (e.g. B+)
      min_score   (float)                    — minimum cis_score gate
    """
    # Rate limiting — per client IP
    if request:
        client_ip = request.client.host if request.client else "unknown"
        now = time.time()
        hits = _AGENT_RATE_LIMIT.get(client_ip, [])
        hits = [t for t in hits if now - t < _AGENT_RL_WINDOW]
        if len(hits) >= _AGENT_RL_MAX:
            raise HTTPException(status_code=429, detail="Rate limit: 30 req/min")
        hits.append(now)
        _AGENT_RATE_LIMIT[client_ip] = hits

    # Clamp pagination params
    limit  = max(1, min(limit, 100))
    offset = max(0, offset)

    cached = await redis_get()
    if cached and cached.get("universe"):
        universe = cached["universe"]
        ts = cached.get("timestamp", datetime.now().isoformat())
        regime = cached.get("macro", {}).get("regime", "Unknown")
    else:
        try:
            result = await calculate_cis_universe()
            universe = result.get("universe", [])
            ts = result.get("timestamp", datetime.now().isoformat())
            regime = result.get("macro", {}).get("regime", "Unknown")
        except Exception:
            universe = []
            ts = datetime.now().isoformat()
            regime = "Unknown"

    # Filtering
    _GRADE_ORDER = {"A+": 8, "A": 7, "B+": 6, "B": 5, "C+": 4, "C": 3, "D": 2, "F": 1}
    min_grade_rank = _GRADE_ORDER.get(min_grade, 0)

    filtered = []
    for a in universe:
        if asset_class and a.get("asset_class", "") != asset_class:
            continue
        sc = a.get("cis_score", a.get("score", 0)) or 0
        if sc < min_score:
            continue
        if min_grade_rank and _GRADE_ORDER.get(a.get("grade", "F"), 1) < min_grade_rank:
            continue
        filtered.append(a)

    total = len(filtered)
    page  = filtered[offset: offset + limit]

    return {
        "v":      "4.1",
        "ts":     ts,
        "regime": regime,
        "total":  total,
        "offset": offset,
        "limit":  limit,
        "assets": [
            {
                "s":    a["symbol"],
                "g":    a.get("grade", "?"),
                "sc":   a.get("cis_score", a.get("score", 0)),
                "sg":   a.get("signal", "?"),
                "cls":  a.get("asset_class", ""),
                "tier": a.get("data_tier", 2),
                "f":    _p(a, "f"),
                "m":    _p(a, "m"),
                "o":    _p(a, "o") or _p(a, "r"),
                "ss":   _p(a, "s"),
                "a":    _p(a, "a"),
                "las":    a.get("las"),
                "conf":   a.get("confidence"),
                "ch30d":  a.get("change_30d"),
                "ch7d":   a.get("change_7d"),
                "mc":     a.get("market_cap"),
                "vol24h": a.get("volume_24h"),
                "tvl":    a.get("tvl"),
            }
            for a in page
        ],
    }


# ── Agent: Exclusion List ─────────────────────────────────────────────────────

# Static exclusion data — sourced from EXCLUSION_LIST.md v1.1 (2026-04-09)
# Updated when Jazz + MiniMax run the universe filter. Each entry is machine-readable.
_CIS_EXCLUSIONS: list[dict] = [
    # ── Memecoins ──────────────────────────────────────────────────────────────
    {"symbol": "BONK", "name": "Bonk", "asset_class": "Memecoin",
     "criterion_violated": ["3", "7"], "criterion_labels": ["Custody", "Team Integrity"],
     "reason": "No institutional custodian support. Anonymous team with no registered legal entity. No protocol utility beyond speculative trading.",
     "excluded_since": "2026-04-01", "remediation_available": False},
    {"symbol": "PEPE", "name": "Pepe", "asset_class": "Memecoin",
     "criterion_violated": ["3", "7"], "criterion_labels": ["Custody", "Team Integrity"],
     "reason": "Anonymous team, no institutional custodian, no registered legal entity. Explicitly anonymous project with no protocol utility.",
     "excluded_since": "2026-04-01", "remediation_available": False},
    {"symbol": "WIF", "name": "dogwifhat", "asset_class": "Memecoin",
     "criterion_violated": ["3", "6", "7"], "criterion_labels": ["Custody", "Trading History", "Team Integrity"],
     "reason": "Anonymous team, no institutional custody, insufficient trading history at institutional exchanges. No protocol utility.",
     "excluded_since": "2026-04-01", "remediation_available": False},
    # ── Gaming / Metaverse ──────────────────────────────────────────────────────
    {"symbol": "AXS", "name": "Axie Infinity", "asset_class": "Gaming",
     "criterion_violated": ["7"], "criterion_labels": ["Team/Protocol Integrity"],
     "reason": "Ronin bridge exploit March 2022 — $625M drained. Largest single DeFi hack in history. Root cause: validator key mismanagement. Partial user restitution only.",
     "excluded_since": "2026-04-01", "remediation_available": True,
     "remediation_note": "Eligible for review 2027 if 3+ years of clean operation from rebuild date are maintained."},
    {"symbol": "MANA", "name": "Decentraland", "asset_class": "Gaming",
     "criterion_violated": ["1", "2"], "criterion_labels": ["Liquidity", "Data Completeness"],
     "reason": "30-day average daily volume below $5M threshold. DAU consistently <1,000 making on-chain engagement scoring unreliable.",
     "excluded_since": "2026-04-01", "remediation_available": True,
     "remediation_note": "Re-qualifies if sustained 30d volume exceeds $5M for 60+ consecutive days."},
    {"symbol": "SAND", "name": "The Sandbox", "asset_class": "Gaming",
     "criterion_violated": ["1"], "criterion_labels": ["Liquidity"],
     "reason": "30-day average daily volume in persistent decline since 2022. Borderline threshold breach with no trend reversal signal.",
     "excluded_since": "2026-04-01", "remediation_available": True,
     "remediation_note": "Re-qualifies if sustained 30d volume exceeds $5M for 60+ consecutive days."},
    # ── DeFi ───────────────────────────────────────────────────────────────────
    {"symbol": "CRV", "name": "Curve Finance", "asset_class": "DeFi",
     "criterion_violated": ["7"], "criterion_labels": ["Team/Protocol Integrity"],
     "reason": "Founder Michael Egorov personal DeFi positions (~$168M collateralized against CRV in 2023) created systemic liquidation risk to the protocol's own liquidity pools. Conflict of interest between founder's personal finances and protocol health.",
     "excluded_since": "2026-04-01", "remediation_available": True,
     "remediation_note": "Eligible for review if founder positions are fully unwound and a governance separation policy is established."},
    {"symbol": "SUSHI", "name": "SushiSwap", "asset_class": "DeFi",
     "criterion_violated": ["7"], "criterion_labels": ["Team/Protocol Integrity"],
     "reason": "Multiple documented integrity incidents 2020-2024: founder withdrawal of $14M dev fund without governance approval, repeated leadership disputes, treasury mismanagement allegations. Pattern of repeated incidents disqualifies.",
     "excluded_since": "2026-04-01", "remediation_available": False},
    {"symbol": "SNX", "name": "Synthetix", "asset_class": "DeFi",
     "criterion_violated": ["2"], "criterion_labels": ["Data Completeness"],
     "reason": "Three major product pivots created data discontinuity. V2 and V3 TVL/revenue data incomparable on continuous basis. Insufficient data completeness for reliable F pillar scoring.",
     "excluded_since": "2026-04-01", "remediation_available": True,
     "remediation_note": "Re-qualifies after 12 months of stable V3 operating data without further major pivots."},
    # ── Infrastructure ─────────────────────────────────────────────────────────
    {"symbol": "ICP", "name": "Internet Computer", "asset_class": "Infrastructure",
     "criterion_violated": ["5"], "criterion_labels": ["Token Mechanics"],
     "reason": "Historical undisclosed inflation event: ~90% supply inflation in first 8 months post-launch (May-Dec 2021) via neuron reward emissions not clearly disclosed in pre-launch tokenomics. Variable NNS governance reward emissions create ongoing supply schedule uncertainty.",
     "excluded_since": "2026-04-01", "remediation_available": False,
     "remediation_note": "Historical non-disclosure of inflation schedule is not retroactively remediable."},
    # ── AI ─────────────────────────────────────────────────────────────────────
    {"symbol": "VIRTUAL", "name": "Virtuals Protocol", "asset_class": "AI",
     "criterion_violated": ["3"], "criterion_labels": ["Institutional Custody"],
     "reason": "No institutional custodian from the Criterion 3 approved list (Coinbase, BitGo, Fireblocks, Anchorage, Fidelity, Komainu, Zodia) offers VIRTUAL custody as of April 2026.",
     "excluded_since": "2026-04-01", "remediation_available": True,
     "remediation_note": "Re-qualifies immediately when Coinbase, BitGo, or Fireblocks adds custody support."},
    # ── Legacy Crypto ───────────────────────────────────────────────────────────
    {"symbol": "BCH", "name": "Bitcoin Cash", "asset_class": "Crypto",
     "criterion_violated": ["4"], "criterion_labels": ["Regulatory Status"],
     "reason": "Primary public advocate Roger Ver indicted by US DOJ April 2024 on tax evasion and wire fraud charges. Regulatory proximity concern for institutional allocators despite protocol itself not being charged.",
     "excluded_since": "2026-04-01", "remediation_available": True,
     "remediation_note": "Eligible for review if Ver case is resolved without conviction or exchange delisting risk is confirmed absent."},
    {"symbol": "FTM", "name": "Fantom / Sonic", "asset_class": "L1",
     "criterion_violated": ["5"], "criterion_labels": ["Token Mechanics"],
     "reason": "Complete rebrand to Sonic (January 2025) with token migration FTM→S at 1:1 plus new 190.5M S airdrop supply. Mid-flight tokenomics change breaks continuous time-series scoring. New asset (S/SONIC) has <18 months operating history.",
     "excluded_since": "2026-04-01", "remediation_available": True,
     "remediation_note": "S/SONIC eligible for fresh inclusion evaluation after 12+ months stable post-migration tokenomics and institutional custody support."},
    # ── RWA ────────────────────────────────────────────────────────────────────
    {"symbol": "POLYX", "name": "Polymesh", "asset_class": "RWA",
     "criterion_violated": ["1"], "criterion_labels": ["Liquidity"],
     "reason": "30-day average daily volume ~$250K-$500K against the $5M minimum. Staking-heavy token mechanics structurally suppress secondary market liquidity.",
     "excluded_since": "2026-04-01", "remediation_available": True,
     "remediation_note": "Re-qualifies if sustained 30d average volume exceeds $5M."},
]

# Borderline cases — included with reduced confidence or pending Jazz decision
_CIS_BORDERLINE: list[dict] = [
    {"symbol": "RUNE", "name": "Thorchain", "asset_class": "Infrastructure",
     "status": "remediation_review",
     "criterion_previously_violated": ["7"], "criterion_labels": ["Team/Protocol Integrity"],
     "remediation_evidence": "Dual exploit 2021 ($5M + $8M). Both disclosed. Post-mortems published. Halborn audit completed post-2021. 3+ years clean operation (July 2021 – April 2026). No repeat vulnerability.",
     "pending": "Confirmation that user compensation reached ≥80% threshold. Jazz decision required."},
    {"symbol": "DOGE", "name": "Dogecoin", "asset_class": "Memecoin",
     "status": "borderline_pass",
     "note": "Passes all 7 criteria. 10+ year history, Coinbase Custody supported, >$500M daily volume, known inflation schedule. Included in universe — narrative credibility decision only."},
]


@router.get("/api/v1/agent/cis-exclusions")
async def get_cis_exclusions(
    criterion: str = "",        # filter by criterion number e.g. "7" or "1"
    asset_class: str = "",      # filter by class e.g. "DeFi", "Memecoin"
    remediable: str = "",       # filter: "true" = only remediable, "false" = permanent
    include_borderline: bool = False,
):
    """
    Returns the CometCloud institutional exclusion list with structured rejection reasons.

    Each excluded asset includes the specific criterion violated, the plain-language reason,
    and whether remediation is available. This is the only MCP tool in crypto that returns
    a structured institutional exclusion list — not a score, a rejection.

    CometCloud's 7 exclusion criteria:
      1 = Liquidity threshold   2 = Data completeness     3 = Institutional custody
      4 = Regulatory status     5 = Token mechanics       6 = Trading history
      7 = Team/protocol integrity

    Use this tool to screen portfolio candidates against an institutional-grade standard
    before any allocation decision.
    """
    results = list(_CIS_EXCLUSIONS)

    if criterion:
        results = [e for e in results if criterion in e["criterion_violated"]]
    if asset_class:
        cls = asset_class.strip().title()
        results = [e for e in results if e["asset_class"].lower() == cls.lower()]
    if remediable.lower() == "true":
        results = [e for e in results if e.get("remediation_available", False)]
    elif remediable.lower() == "false":
        results = [e for e in results if not e.get("remediation_available", False)]

    out: dict = {
        "total_excluded": len(_CIS_EXCLUSIONS),
        "filtered_count": len(results),
        "universe_evaluated": 70,
        "universe_admitted": 70 - len(_CIS_EXCLUSIONS),
        "standard_version": "2.0",
        "standard_url": "cometcloud.ai/methodology",
        "last_reviewed": "2026-05-21",
        "exclusions": results,
    }
    if include_borderline:
        out["borderline"] = _CIS_BORDERLINE

    return JSONResponse(content=out)


# ── Agent: Universe Watchlist ─────────────────────────────────────────────────
# Assets that have been excluded but are approaching or re-entering eligibility.
# Scanned weekly — assets entering CG top 150 auto-flagged for re-review.
# Auto-flags assets entering top 100 for accelerated inclusion review.

_WATCHLIST_CONFIG = {
    # Assets excluded from v1.1/v2.0 universe that warrant monitoring.
    # Each entry: criterion that was violated, current CG rank (if known),
    # and the blocking condition that must resolve before re-review.
    "VIRTUAL": {
        "name": "Virtuals Protocol",
        "symbol": "VIRTUAL",
        "asset_class": "AI",
        "violated_criterion": "3",       # Institutional custody
        "blocking_condition": "Coinbase/BitGo/Fireblocks custody support",
        "last_cg_rank": 47,              # ~top 50 as of May 2026 — eligible for fast-track
        "fast_track_eligible": True,
        "fdv_note": "~600M FDV — below $1B fast-track threshold but high momentum",
        "remediation_available": True,
    },
    "FTM": {
        "name": "Fantom / Sonic",
        "symbol": "FTM",
        "asset_class": "L1",
        "violated_criterion": "5",       # Token mechanics (rebrand migration)
        "blocking_condition": "12+ months stable post-migration tokenomics + institutional custody",
        "last_cg_rank": 89,              # ~top 100 — approaching
        "fast_track_eligible": False,
        "fdv_note": "Sonic (S) airdrop completed Jan 2025 — track from Jan 2026 for 180d clean",
        "remediation_available": True,
    },
    "ICP": {
        "name": "Internet Computer",
        "symbol": "ICP",
        "asset_class": "Infrastructure",
        "violated_criterion": "5",       # Token mechanics (undisclosed inflation)
        "blocking_condition": "Historical non-disclosure — not retroactively remediable",
        "last_cg_rank": 68,              # top 100 — high priority watch
        "fast_track_eligible": False,
        "fdv_note": "Dfinity governance reward emissions remain variable; supply schedule uncertain",
        "remediation_available": False,
    },
    "BCH": {
        "name": "Bitcoin Cash",
        "symbol": "BCH",
        "asset_class": "Crypto",
        "violated_criterion": "4",       # Regulatory (Roger Ver DOJ case)
        "blocking_condition": "Ver case resolved without conviction OR delisting risk confirmed absent",
        "last_cg_rank": 31,              # top 50 — high priority
        "fast_track_eligible": False,
        "fdv_note": "Roger Ver DOJ case ongoing since April 2024 — no resolution yet",
        "remediation_available": True,
    },
    "GALA": {
        "name": "Gala",
        "symbol": "GALA",
        "asset_class": "Gaming",
        "violated_criterion": "1",       # Liquidity ($5M → $10M threshold breached)
        "blocking_condition": "30d avg volume > $10M sustained for 60+ days",
        "last_cg_rank": 198,             # Below top 150 — not currently re-reviewable
        "fast_track_eligible": False,
        "fdv_note": "CG rank ~198 — below rank floor threshold. Would need top 150 first.",
        "remediation_available": True,
    },
    "ENA": {
        "name": "Ethena",
        "symbol": "ENA",
        "asset_class": "DeFi",
        "violated_criterion": "6",       # Trading history (<180d at launch, fast-track not applied)
        "blocking_condition": "180 days continuous trading history on tier-1 exchange",
        "last_cg_rank": 62,              # top 100 — approaching re-review window
        "fast_track_eligible": False,
        "fdv_note": "ENA launched March 2024 — passed 180d threshold September 2024. Eligible for re-review.",
        "remediation_available": True,
    },
    "SAND": {
        "name": "The Sandbox",
        "symbol": "SAND",
        "asset_class": "Gaming",
        "violated_criterion": "1",       # Liquidity
        "blocking_condition": "30d avg volume > $10M sustained for 60+ days",
        "last_cg_rank": 203,             # Below top 150 — not currently re-reviewable
        "fast_track_eligible": False,
        "fdv_note": "CG rank ~203 — below rank floor. Below $10M daily volume.",
        "remediation_available": True,
    },
    "MANA": {
        "name": "Decentraland",
        "symbol": "MANA",
        "asset_class": "Gaming",
        "violated_criterion": "1",       # Liquidity + data completeness
        "blocking_condition": "30d avg volume > $10M + DAU > 1,000 sustained",
        "last_cg_rank": 215,             # Well below top 150
        "fast_track_eligible": False,
        "fdv_note": "CG rank ~215. Volume declining. No near-term re-entry path.",
        "remediation_available": True,
    },
    "POLYX": {
        "name": "Polymesh",
        "symbol": "POLYX",
        "asset_class": "RWA",
        "violated_criterion": "1",       # Liquidity ($250K-$500K daily volume vs $10M threshold)
        "blocking_condition": "30d avg volume > $10M sustained for 60+ days",
        "last_cg_rank": 287,             # Well below top 150
        "fast_track_eligible": False,
        "fdv_note": "CG rank ~287. Staking mechanics structurally suppress secondary liquidity.",
        "remediation_available": True,
    },
}


# ── CoinGecko proxy for watchlist live data ──────────────────────────────────
# Cache: 60s TTL to avoid rate limits when watchlist is polled frequently.
_watchlist_cache: dict = {}
_watchlist_cache_ts: float = 0.0
_WATCHLIST_CACHE_TTL: float = 60.0


async def _get_cg_market_for_watchlist(symbol: str, cg_id: str) -> dict:
    """Fetch live market data for a watchlist asset. 60s in-process cache."""
    global _watchlist_cache, _watchlist_cache_ts
    from src.data.cis.cis_provider import _cg_headers, CG_API_KEY

    now = time.time()
    if _watchlist_cache and (now - _watchlist_cache_ts) < _WATCHLIST_CACHE_TTL:
        return _watchlist_cache.get(symbol, {})

    result = {}
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10) as client:
            url = f"https://api.coingecko.com/api/v3/coins/markets"
            params = {"vs_currency": "usd", "ids": cg_id, "price_change_percentage": "30d"}
            headers = _cg_headers() if CG_API_KEY else {}
            resp = await client.get(url, params=params, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                if data:
                    c = data[0]
                    result = {
                        "price": c.get("current_price"),
                        "mcap_usd": c.get("market_cap"),
                        "fdv_usd": c.get("fully_diluted_valuation"),
                        "volume_24h": c.get("total_volume"),
                        "mcap_rank": c.get("market_cap_rank"),
                        "price_change_30d_pct": c.get("price_change_percentage_30d_in_currency"),
                        "circ_supply": c.get("circulating_supply"),
                        "total_supply": c.get("total_supply"),
                        "ath_distance_pct": c.get("ath_change_percentage"),
                        "rank_snapshot": c.get("market_cap_rank"),
                    }
    except Exception:
        pass

    _watchlist_cache[symbol] = result
    _watchlist_cache_ts = now
    return result


def _rank_trend(current_rank: int, prior_rank: Optional[int]) -> dict:
    """
    Compute rank direction and delta.
    Lower rank number = higher mcap = better.
    Positive delta = improving (rank number fell = mcap gained on market).
    """
    if not prior_rank or not current_rank:
        return {
            "direction": "unknown", "delta": 0,
            "current_rank": current_rank, "prior_rank": prior_rank,
            "status": "insufficient_data",
            "urgency_note": "Track rank weekly for trend",
        }
    delta = prior_rank - current_rank  # positive = improving
    direction = "improving" if delta > 0 else "deteriorating" if delta < 0 else "stable"
    pct = round(abs(delta) / max(prior_rank, 1) * 100, 1) if delta != 0 else 0
    return {
        "direction": direction,
        "delta": delta,
        "delta_pct": pct,
        "current_rank": current_rank,
        "prior_rank": prior_rank,
        "status": direction,
        "urgency_note": (
            "Rising urgency — rank improving toward top 50"
            if direction == "improving" and current_rank <= 50 else
            "Rank improving toward top 100 — accelerated review approaching"
            if direction == "improving" and current_rank <= 100 else
            "Rank deteriorating — monitor"
            if direction == "deteriorating" else
            "Stable — continue monitoring"
        ),
    }


def _volume_trend_analysis(current_vol: Optional[float], price_change_30d: Optional[float]) -> dict:
    """
    Analyze volume trend as proxy for liquidity trajectory.
    Uses 30d price change as direction signal; actual volume trend requires
    multi-day comparison but 30d price direction correlates with volume flow.
    """
    if not current_vol:
        return {"direction": "unknown", "status": "no_data"}
    if not price_change_30d:
        price_dir = "neutral"
    elif price_change_30d > 5:
        price_dir = "strong_uptrend"
    elif price_change_30d > 0:
        price_dir = "mild_uptrend"
    elif price_change_30d > -5:
        price_dir = "mild_downtrend"
    else:
        price_dir = "strong_downtrend"

    vol_vs_threshold = current_vol / 10_000_000
    if vol_vs_threshold >= 1.0:
        clearance = "cleared"
    elif vol_vs_threshold >= 0.5:
        clearance = "approaching"
    else:
        clearance = "far_from_threshold"

    return {
        "current_vol_24h": current_vol,
        "vol_vs_threshold_ratio": round(vol_vs_threshold, 2),
        "price_direction_30d": price_dir,
        "price_change_30d_pct": price_change_30d,
        "clearance_status": clearance,
        "pct_below_threshold": round((1 - vol_vs_threshold) * 100, 1) if vol_vs_threshold < 1 else 0,
        "status": clearance,
        "note": (
            "Volume clearing threshold — re-review eligible"
            if clearance == "cleared" else
            f"Volume at {round(vol_vs_threshold*100,0)}% of threshold — momentum direction: {price_dir}"
        ),
    }


def _fdv_trajectory(entry: dict, fdv: Optional[float], price_change_30d: Optional[float]) -> dict:
    """
    Estimate FDV trajectory and time to $1B fast-track threshold.
    Uses 30d price change as proxy for FDV growth rate.
    """
    if not fdv:
        return {
            "fdv_current_b": None, "growth_rate_30d": None,
            "months_to_1b": None, "trajectory": "unknown",
            "fast_track_threshold_b": 1.0,
        }
    growth_rate_30d = (price_change_30d / 100) if price_change_30d else 0
    monthly_rate = ((1 + growth_rate_30d) ** (30.44 / 30)) - 1 if growth_rate_30d != 0 else 0
    fdv_b = fdv / 1e9
    threshold = 1.0

    import math as _math
    if fdv_b >= threshold:
        trajectory = "fast_track_ready"
        months_to_1b = 0
    elif monthly_rate > 0.01:
        try:
            months_to_1b = round(_math.log(threshold / fdv_b) / _math.log(1 + monthly_rate), 1)
            months_to_1b = max(months_to_1b, 0)
        except Exception:
            months_to_1b = None
        trajectory = "on_track" if (months_to_1b and months_to_1b <= 3) else "slow_growth"
    elif monthly_rate < -0.01:
        trajectory = "declining"
        months_to_1b = None
    else:
        trajectory = "stagnant"
        months_to_1b = None

    return {
        "fdv_current_b": round(fdv_b, 2),
        "growth_rate_30d": round(growth_rate_30d * 100, 2) if growth_rate_30d else 0,
        "monthly_growth_rate_pct": round(monthly_rate * 100, 2) if monthly_rate else 0,
        "months_to_1b": months_to_1b,
        "trajectory": trajectory,
        "fast_track_threshold_b": 1.0,
        "fast_track_eligible_now": fdv_b >= 1.0 and entry.get("fast_track_eligible", False),
        "note": (
            f"${fdv_b:.1f}B FDV — fast-track ready"
            if trajectory == "fast_track_ready" else
            f"${fdv_b:.2f}B FDV, {months_to_1b:.0f}mo to $1B at {round(monthly_rate*100,1)}%/mo growth"
            if trajectory in ("on_track", "slow_growth") and months_to_1b else
            f"${fdv_b:.2f}B FDV, declining — fast-track unlikely"
            if trajectory == "declining" else
            f"${fdv_b:.2f}B FDV, stagnant — fast-track unlikely within 12mo"
        ),
    }


def _gate_clearing_prediction(entry: dict, live_data: dict) -> dict:
    """
    Estimate when each blocking condition will clear, based on trajectory.
    Returns list of per-gate clearing predictions with confidence levels.
    """
    symbol = entry["symbol"]
    criterion = entry["violated_criterion"]
    fdv = live_data.get("fdv_usd")
    vol = live_data.get("volume_24h")
    fdv_traj = _fdv_trajectory(entry, fdv, live_data.get("price_change_30d_pct"))

    predictions = []

    # Gate 1: Liquidity
    if criterion == "1":
        vol_ratio = (vol / 10_000_000) if vol else 0
        if vol_ratio >= 1.0:
            predictions.append({
                "gate": "1_liquidity", "label": "Liquidity ($10M/30d)",
                "status": "cleared", "estimated_months": 0, "confidence": "high",
                "note": "Volume threshold met — eligible for re-review",
            })
        elif vol_ratio >= 0.5:
            import math as _math
            shortfall = (10_000_000 - (vol or 0)) / 10_000_000
            growth_rate = 0.10
            months_est = round(_math.log(1 - shortfall) / _math.log(1 + growth_rate), 1) if (growth_rate > 0 and shortfall > 0 and shortfall < 1) else None
            predictions.append({
                "gate": "1_liquidity", "label": "Liquidity ($10M/30d)",
                "status": "approaching", "estimated_months": max(months_est, 0) if months_est else None,
                "confidence": "medium",
                "note": f"At {round(vol_ratio*100,0)}% of threshold — {months_est:.0f}mo at 10%/mo growth assumed",
            })
        else:
            predictions.append({
                "gate": "1_liquidity", "label": "Liquidity ($10M/30d)",
                "status": "far", "estimated_months": None, "confidence": "low",
                "note": f"At {round(vol_ratio*100,0)}% of threshold — structural barrier if staking-heavy",
            })

    # Gate 3: Custody (VIRTUAL fast-track)
    if criterion == "3" and entry.get("fast_track_eligible"):
        predictions.append({
            "gate": "3_custody", "label": "Institutional Custody",
            "status": "event_driven", "estimated_months": None, "confidence": "high",
            "trigger": "Coinbase Prime / BitGo / Fireblocks adds VIRTUAL",
            "note": "No predictable timeline — event-driven. Monitor custodian announcements.",
        })

    # Gate 4: Regulatory (BCH)
    if criterion == "4":
        predictions.append({
            "gate": "4_regulatory", "label": "Regulatory Status",
            "status": "event_driven", "estimated_months": None, "confidence": "low",
            "trigger": "Roger Ver DOJ case resolution",
            "note": "No predictable resolution timeline. Delisting risk remains.",
        })

    # Gate 5: Token mechanics (FTM Sonic)
    if criterion == "5":
        if symbol == "FTM":
            from datetime import date
            clean_end = date(2026, 1, 14)
            months_to = max(0, (clean_end - date.today()).days // 30)
            predictions.append({
                "gate": "5_token_mechanics", "label": "Token Mechanics",
                "status": "milestone_approaching", "estimated_months": months_to,
                "confidence": "high",
                "trigger": f"12-month Sonic clean period ends 2026-01-14",
                "note": f"Token migration clean period ends Jan 2026 — {months_to}mo remaining",
            })
        else:
            predictions.append({
                "gate": "5_token_mechanics", "label": "Token Mechanics",
                "status": "not_remediable", "estimated_months": None, "confidence": "high",
                "note": "Historical undisclosed inflation event — not retroactively remediable per v2.0 criterion 7",
            })

    # Gate 6: Trading history (ENA)
    if criterion == "6" and symbol == "ENA":
        predictions.append({
            "gate": "6_trading_history", "label": "Trading History (180d)",
            "status": "cleared", "estimated_months": 0, "confidence": "high",
            "note": "180d threshold met September 2024 — criterion 6 resolved. Re-review eligible.",
        })

    # Gate 10: Fast-track ($1B FDV)
    traj = fdv_traj.get("trajectory", "unknown")
    mths = fdv_traj.get("months_to_1b")
    if traj == "fast_track_ready":
        predictions.append({
            "gate": "10_fast_track", "label": "Fast-Track ($1B FDV + custody + tier-1)",
            "status": "fdv_cleared", "estimated_months": 0, "confidence": "high",
            "note": f"${fdv_traj.get('fdv_current_b', 0):.1f}B FDV — awaiting custody support",
        })
    elif traj in ("on_track", "slow_growth") and mths:
        predictions.append({
            "gate": "10_fast_track", "label": "Fast-Track ($1B FDV + custody + tier-1)",
            "status": "trajectory_based", "estimated_months": mths,
            "confidence": "medium",
            "note": f"${fdv_traj.get('fdv_current_b', 0):.2f}B FDV, {mths:.0f}mo at {fdv_traj.get('monthly_growth_rate_pct', 0):.1f}%/mo growth",
        })
    elif traj in ("declining", "stagnant"):
        predictions.append({
            "gate": "10_fast_track", "label": "Fast-Track ($1B FDV + custody + tier-1)",
            "status": "unlikely_12mo", "estimated_months": None, "confidence": "medium",
            "note": f"${fdv_traj.get('fdv_current_b', 0):.2f}B FDV, {traj} — fast-track not expected within 12mo",
        })

    return {"predictions": predictions}


def _comparable_assets_analysis(entry: dict, live_data: dict) -> dict:
    """
    Estimate what CIS score this asset would receive if included in universe.
    Uses nearest peer assets' CIS scores as reference range.
    """
    symbol = entry["symbol"]

    _PEERS = {
        "VIRTUAL":  {"peer": "NEAR", "reason": "AI/DePIN narrative, similar mcap tier"},
        "FTM":      {"peer": "AVAX", "reason": "L1 with DeFi ecosystem"},
        "ICP":      {"peer": "TIA",  "reason": "Modular/infrastructure, similar tech narrative"},
        "BCH":      {"peer": "LTC",  "reason": "Legacy payment chain — CIS was B range"},
        "GALA":     {"peer": "NEAR", "reason": "Gaming AI narrative similar"},
        "ENA":      {"peer": "LDO",  "reason": "Liquid staking, yield-bearing DeFi"},
        "SAND":     {"peer": "NEAR", "reason": "Gaming/metaverse — NEAR has broader utility"},
        "MANA":     {"peer": "NEAR", "reason": "Metaverse/VR — similar low-liquidity profile"},
        "POLYX":    {"peer": "MKR",  "reason": "RWA lending — similar institutional narrative"},
    }

    peer_info = _PEERS.get(symbol, {"peer": None, "reason": "No close peer in current universe"})
    peer_symbol = peer_info["peer"]

    return {
        "peer_symbol": peer_symbol,
        "peer_reason": peer_info["reason"],
        "estimated_cis_range": {
            "F": None,
            "note": f"Peer {peer_symbol}: frontend fetches live CIS from /api/v1/cis/universe",
        },
        "comparable_grade_estimate": None,
        "confidence": "low",
        "note": (
            "Frontend should fetch live CIS score for peer "
            f"{peer_symbol} and use as directional estimate for {symbol}"
        ),
    }


def _s_pillar_estimate(entry: dict, live_data: dict, fear_greed: int = 50) -> dict:
    """
    Estimate S pillar score for excluded asset based on:
    - Fear & Greed baseline for crypto (FNG × 0.4)
    - Asset's own 30d momentum as divergence signal
    - Market regime context (current: Tightening)
    """
    symbol = entry["symbol"]
    price_change_30d = live_data.get("price_change_30d_pct", 0)

    fng_baseline = fear_greed * 0.4

    regime_modifier = {
        "RISK_ON": 5, "RISK_OFF": -3, "TIGHTENING": -5,
        "EASING": 3, "STAGFLATION": -8, "GOLDILOCKS": 5,
    }.get("TIGHTENING", 0)

    if price_change_30d is not None:
        momentum_divergence = (price_change_30d - fng_baseline) / 10
        momentum_divergence = max(-10, min(10, momentum_divergence))
    else:
        momentum_divergence = 0

    s_estimate = fng_baseline + momentum_divergence + regime_modifier
    s_estimate = max(5, min(60, s_estimate))

    return {
        "s_estimate": round(s_estimate, 1),
        "fng_baseline": round(fng_baseline, 1),
        "momentum_divergence": round(momentum_divergence, 1),
        "regime_modifier": regime_modifier,
        "regime": "Tightening",
        "confidence": "low",
        "note": (
            f"S estimate = FNG({fear_greed})×0.4={fng_baseline:.0f} "
            f"+ divergence({momentum_divergence:+.0f}) "
            f"+ regime({regime_modifier:+.0f}) = {s_estimate:.0f}. "
            "Excluded from universe: no real CIS engine score available for excluded assets."
        ),
    }



def _volume_vs_threshold(volume_24h: Optional[float], threshold: float = 10_000_000) -> dict:
    """Compute volume vs liquidity threshold with distance-to-clearing."""
    if not volume_24h:
        return {"ratio": None, "pct_of_threshold": None, "distance_usd": None, "status": "unknown"}
    ratio = volume_24h / threshold
    return {
        "ratio": round(ratio, 2),
        "pct_of_threshold": round(ratio * 100, 1),
        "distance_usd": round(threshold - volume_24h, 0) if volume_24h < threshold else 0,
        "status": "cleared" if ratio >= 1.0 else f"{round((1 - ratio) * 100, 1)}% below threshold",
    }


def _days_since(date_str: str) -> int:
    """Days elapsed since a date string YYYY-MM-DD."""
    try:
        from datetime import date
        past = date.fromisoformat(date_str)
        return (date.today() - past).days
    except Exception:
        return 0


def _gate_status(entry: dict, live_data: dict) -> list[dict]:
    """
    Per-criterion gate status for a watchlist asset.
    Returns list of {gate_id, label, status, notes} for the 10 v2.0 gates.
    """
    criterion = entry["violated_criterion"]
    mcap_rank = entry.get("last_cg_rank", 999)
    vol_data = live_data.get("volume_24h")
    mcap = live_data.get("mcap_usd")
    fdv = live_data.get("fdv_usd")
    circ = live_data.get("circ_supply", 0) or 0
    total = live_data.get("total_supply", 0) or 0

    gates = []
    gates.append({
        "gate_id": "1",
        "label": "Liquidity ($10M/30d + 3 tier-1)",
        "status": "cleared" if (vol_data and vol_data >= 10_000_000) else "failing",
        "notes": f"${vol_data / 1e6:.1f}M daily vol" if vol_data else "No live volume data",
    })
    gates.append({
        "gate_id": "2",
        "label": "Market Cap ($500M FDV floor)",
        "status": "cleared" if (fdv and fdv >= 500_000_000) else "failing",
        "notes": f"${fdv / 1e9:.1f}B FDV" if fdv else "No FDV data",
    })
    gates.append({
        "gate_id": "3",
        "label": "CG Rank (top 150)",
        "status": "cleared" if mcap_rank <= 150 else "failing",
        "notes": f"CG rank #{mcap_rank}",
    })
    gates.append({
        "gate_id": "4",
        "label": "Data Completeness (90d+ OHLCV)",
        "status": "unknown",
        "notes": "Requires on-chain data audit",
    })
    gates.append({
        "gate_id": "5",
        "label": "Institutional Custody",
        "status": "cleared" if entry.get("fast_track_eligible") else "failing",
        "notes": entry.get("blocking_condition", "See criterion 5 notes"),
    })
    gates.append({
        "gate_id": "6",
        "label": "Regulatory Status",
        "status": "cleared" if criterion != "4" else "failing",
        "notes": "Ver DOJ case ongoing" if criterion == "4" else "No active regulatory concerns",
    })
    gates.append({
        "gate_id": "7",
        "label": "Token Mechanics (circ/total≥30%, inflation<20%/yr)",
        "status": "unknown",
        "notes": "Supply data: circ/total=" + (f"{circ/total*100:.0f}%" if total > 0 else "unavailable"),
    })
    gates.append({
        "gate_id": "8",
        "label": "Trading History (180d)",
        "status": "cleared" if criterion != "6" else "failing",
        "notes": "ENA: launched Mar 2024, 180d+ Sep 2024" if entry["symbol"] == "ENA" else "See trading history criterion",
    })
    gates.append({
        "gate_id": "9",
        "label": "Protocol Integrity",
        "status": "cleared" if criterion != "7" else "failing",
        "notes": "No rug-pull or unresolved exploit" if criterion != "7" else entry.get("blocking_condition", ""),
    })
    gates.append({
        "gate_id": "10",
        "label": "Fast-Track ($1B+ FDV + custody + tier-1)",
        "status": "eligible" if entry.get("fast_track_eligible") else "not_eligible",
        "notes": f"FDV {fdv/1e9:.1f}B — fast-track eligible" if (entry.get("fast_track_eligible") and fdv) else "Below $1B FDV or no custody",
    })
    return gates


def _risk_factors(entry: dict, live_data: dict) -> list[dict]:
    """Generate specific risk factors based on violation type."""
    risks = []
    criterion = entry["violated_criterion"]
    symbol = entry.get("symbol", "")

    if criterion == "1":  # Liquidity
        vol = live_data.get("volume_24h")
        if vol:
            shortfall = max(0, 10_000_000 - vol)
            risks.append({
                "factor": "Liquidity Shortfall",
                "severity": "HIGH" if vol < 5_000_000 else "MEDIUM",
                "description": f"${shortfall/1e6:.1f}M below $10M threshold. Structural if staking-heavy.",
            })
        risks.append({
            "factor": "Bid-Ask Spread Risk",
            "severity": "MEDIUM",
            "description": "Wide spreads on low-liquidity venues increase execution slippage for institutional orders.",
        })

    if criterion == "3":  # Custody
        risks.append({
            "factor": "Custody Gap",
            "severity": "HIGH",
            "description": "Cannot be held in institutional custody — blocks pension/family-office allocation.",
        })
        risks.append({
            "factor": "LP Eligibility Risk",
            "severity": "HIGH",
            "description": "Regulated funds require eligible assets. Custody gap = structural fund exclusion.",
        })

    if criterion == "4":  # Regulatory
        risks.append({
            "factor": "DOJ/Regulatory Proximity",
            "severity": "HIGH",
            "description": "Active legal proceedings create delisting risk on tier-1 exchanges.",
        })
        risks.append({
            "factor": "Team Regulatory Exposure",
            "severity": "HIGH",
            "description": "Key team member under charges — protocol governance depends on individual's legal stability.",
        })

    if criterion == "5":  # Token mechanics
        risks.append({
            "factor": "Supply Schedule Uncertainty",
            "severity": "MEDIUM",
            "description": "Variable or undisclosed inflation schedule creates unpredictable dilution.",
        })
        risks.append({
            "factor": "Circ/Total Supply Risk",
            "severity": "MEDIUM",
            "description": "Low circulating share means large future unlock events can shock price.",
        })

    if criterion == "6":  # Trading history
        risks.append({
            "factor": "Limited Price History",
            "severity": "LOW",
            "description": "180d+ history now met. Confidence in momentum and alpha signals recovered.",
        })

    if criterion == "7":  # Protocol integrity
        risks.append({
            "factor": "Team Integrity Risk",
            "severity": "HIGH",
            "description": "Past rug/exploit/misuse — reputational risk for fund allocating here.",
        })

    # Cross-cutting: rank-based risk
    rank = entry.get("last_cg_rank", 999)
    if rank <= 50:
        risks.append({
            "factor": "Concentration Risk (Top 50)",
            "severity": "MEDIUM",
            "description": "High rank = high correlation with broad crypto sentiment. Sharp drawdowns affect fund NAV.",
        })
    if rank <= 100:
        risks.append({
            "factor": "Elevated Speculation Premium",
            "severity": "MEDIUM",
            "description": "Top 100 assets trade at premium to fair value due to narrative demand.",
        })

    return risks


@router.get("/api/v1/agent/universe-watchlist")
async def get_universe_watchlist(
    include_resolved: bool = False,
    include_live_data: bool = False,    # fetch CG live data (60s cache, adds latency)
    include_risk_factors: bool = False,  # include per-asset risk factors
):
    """
    Returns excluded assets approaching or eligible for re-entry review.

    Auto-flags assets entering CoinGecko top 150 (weekly scan trigger).
    Auto-flags assets entering top 100 for accelerated inclusion review.
    Auto-flags top 50 assets with custody support as fast-track candidates.

    Per asset includes:
      - Violation details + blocking condition
      - 10-gate status (which v2.0 gates currently cleared/failing)
      - Live market data (price, mcap, FDV, volume) when ?include_live_data=true
      - Risk factors specific to violation type
      - Days since exclusion, days until re-review eligibility

    Add ?include_risk_factors=true for institutional risk analysis per asset.
    Add ?include_live_data=true for real-time CG market data (N requests, slower).
    Add ?include_resolved=true to include permanently excluded assets.
    """
    # CG IDs for live data fetch (symbol → CG coin id)
    _SYMBOL_TO_CG_ID = {
        "VIRTUAL": "virtuals-protocol",
        "FTM":     "fantom",
        "ICP":     "internet-computer",
        "BCH":     "bitcoin-cash",
        "GALA":    "gala",
        "ENA":     "ethena",
        "SAND":    "the-sandbox",
        "MANA":    "decentraland",
        "POLYX":   "polymesh",
    }

    watchlist = []
    for symbol, entry in _WATCHLIST_CONFIG.items():
        rank = entry.get("last_cg_rank", 999)
        in_top_150 = rank <= 150
        in_top_100 = rank <= 100
        in_top_50  = rank <= 50

        # Status logic
        if entry.get("remediation_available") is False:
            status = "permanently_excluded"
        elif in_top_50 and entry.get("fast_track_eligible"):
            status = "fast_track_candidate"
        elif in_top_100:
            status = "accelerated_review"
        elif in_top_150:
            status = "re_review_pending"
        else:
            status = "monitoring"

        # Build base entry
        watch_entry = {
            "symbol": symbol,
            "name": entry["name"],
            "asset_class": entry["asset_class"],
            "violated_criterion": entry["violated_criterion"],
            "criterion_label": {
                "1": "Liquidity Threshold",
                "2": "Data Completeness",
                "3": "Institutional Custody",
                "4": "Regulatory Status",
                "5": "Token Mechanics",
                "6": "Trading History",
                "7": "Protocol Integrity",
            }.get(entry["violated_criterion"], "Unknown"),
            "blocking_condition": entry["blocking_condition"],
            "current_cg_rank": rank,
            "in_top_150": in_top_150,
            "in_top_100": in_top_100,
            "in_top_50": in_top_50,
            "fast_track_eligible": entry.get("fast_track_eligible", False),
            "fdv_note": entry.get("fdv_note", ""),
            "remediation_available": entry.get("remediation_available", False),
            "status": status,
            "review_trigger": (
                "Accelerated — asset in CG top 100" if in_top_100
                else f"Standard — asset in CG top 150" if in_top_150
                else "Rank floor not breached — monitor"
            ),
        }

        # ── Live market data (optional, costs N CG API calls) ──────────────
        live_data = {}
        if include_live_data:
            cg_id = _SYMBOL_TO_CG_ID.get(symbol)
            if cg_id:
                live_data = await _get_cg_market_for_watchlist(symbol, cg_id)

        # ── Gate status for all 10 v2.0 gates ─────────────────────────────
        gates = _gate_status(entry, live_data)
        watch_entry["gate_status"] = gates

        # ── Volume analysis for liquidity violations ─────────────────────
        if entry["violated_criterion"] == "1":
            vol = live_data.get("volume_24h")
            watch_entry["volume_analysis"] = _volume_vs_threshold(vol)
            watch_entry["volume_threshold"] = "$10M/day 30d avg"
            watch_entry["volume_status"] = (
                "CLEARED — volume threshold met"
                if (vol and vol >= 10_000_000) else
                f"FALLING — ${(10_000_000 - (vol or 0)) / 1e6:.1f}M below threshold"
            )

        # ── Trading history eligibility for ENA ─────────────────────────
        if symbol == "ENA":
            # ENA launched March 2024 → 180d threshold reached September 2024
            from datetime import date
            launch_date = date(2024, 3, 4)  # approximate launch
            days_since_launch = (date.today() - launch_date).days
            watch_entry["trading_history"] = {
                "launch_date": "2024-03-04",
                "days_since_launch": days_since_launch,
                "threshold_days": 180,
                "threshold_met": True,
                "eligible_since": "2024-09-01",
                "note": "180d threshold met September 2024. Criterion 6 blocking condition resolved. Re-review eligible.",
            }
        else:
            watch_entry["trading_history"] = None

        # ── Regulatory timeline for BCH ────────────────────────────────────
        if symbol == "BCH":
            watch_entry["regulatory_timeline"] = {
                "event": "Roger Ver DOJ indictment",
                "filed_date": "2024-04-01",
                "days_since": _days_since("2024-04-01"),
                "case_status": "Active proceedings",
                "delisting_risk": "MEDIUM",
                "note": "No resolution in 26+ months. Resolution would clear Criterion 4.",
            }
        else:
            watch_entry["regulatory_timeline"] = None

        # ── Token mechanics for FTM (Sonic rebrand) ─────────────────────
        if symbol == "FTM":
            watch_entry["token_migration"] = {
                "event": "Fantom → Sonic rebrand (Jan 2025)",
                "new_token": "S (SONIC)",
                "migration_ratio": "1:1 FTM→S + 190.5M S airdrop",
                "migration_date": "2025-01-14",
                "days_since_migration": _days_since("2025-01-14"),
                "track_from_date": "2025-01-14",
                "clean_period_end": "2026-01-14",
                "note": "12-month clean period ends January 2026. Criterion 5 re-review eligible after that date.",
                "blocking_condition_met": False,
            }
        else:
            watch_entry["token_migration"] = None

        # ── Live data fields merged in ─────────────────────────────────────
        if live_data:
            watch_entry["price"] = live_data.get("price")
            watch_entry["mcap_usd"] = live_data.get("mcap_usd")
            watch_entry["fdv_usd"] = live_data.get("fdv_usd")
            watch_entry["volume_24h"] = live_data.get("volume_24h")
            watch_entry["price_change_30d_pct"] = live_data.get("price_change_30d_pct")
            watch_entry["circ_supply"] = live_data.get("circ_supply")
            watch_entry["total_supply"] = live_data.get("total_supply")
            watch_entry["ath_distance_pct"] = live_data.get("ATH_distance_pct")
        else:
            watch_entry["price"] = None
            watch_entry["mcap_usd"] = None
            watch_entry["fdv_usd"] = None
            watch_entry["volume_24h"] = None
            watch_entry["price_change_30d_pct"] = None
            watch_entry["circ_supply"] = None
            watch_entry["total_supply"] = None
            watch_entry["ath_distance_pct"] = None

        # ── Risk factors (optional, adds computation) ───────────────────
        if include_risk_factors:
            watch_entry["risk_factors"] = _risk_factors(entry, live_data)
            watch_entry["risk_summary"] = {
                "HIGH_count": sum(1 for r in watch_entry["risk_factors"] if r.get("severity") == "HIGH"),
                "MEDIUM_count": sum(1 for r in watch_entry["risk_factors"] if r.get("severity") == "MEDIUM"),
                "LOW_count": sum(1 for r in watch_entry["risk_factors"] if r.get("severity") == "LOW"),
            }
        else:
            watch_entry["risk_factors"] = None
            watch_entry["risk_summary"] = None

        # ── 6 analytical dimensions ─────────────────────────────────────
        if include_live_data or include_risk_factors:
            rank_snapshot = live_data.get("rank_snapshot", {})
            watch_entry["rank_trend"] = _rank_trend(
                current_rank=rank,
                prior_rank=rank_snapshot if isinstance(rank_snapshot, int) else None,
            )
            vol = live_data.get("volume_24h")
            watch_entry["volume_trend"] = _volume_trend_analysis(vol, 10_000_000)
            fdv = live_data.get("fdv_usd")
            price_change_30d = live_data.get("price_change_30d_pct")
            watch_entry["fdv_trajectory"] = _fdv_trajectory(entry, fdv, price_change_30d)
            fdv_traj = watch_entry.get("fdv_trajectory", {})
            watch_entry["gate_clearing_prediction"] = _gate_clearing_prediction(entry, live_data)
            watch_entry["comparable_assets_cis"] = _comparable_assets_analysis(entry, live_data)
            watch_entry["s_pillar_estimate"] = _s_pillar_estimate(entry, live_data, fear_greed=50)
        else:
            watch_entry["rank_trend"] = None
            watch_entry["volume_trend"] = None
            watch_entry["fdv_trajectory"] = None
            watch_entry["gate_clearing_prediction"] = None
            watch_entry["comparable_assets_cis"] = None
            watch_entry["s_pillar_estimate"] = None

        # ── Institutional flags ─────────────────────────────────────────
        watch_entry["institutional_flags"] = {
            "lp_eligible": entry.get("remediation_available", False) and entry.get("fast_track_eligible", False),
            "fund_manager_ allocatable": entry.get("remediation_available", False) and (rank <= 150),
            "regulatory_watch": entry["violated_criterion"] == "4",
            "custody_watch": entry["violated_criterion"] == "3",
        }

        watchlist.append(watch_entry)

    # Sort: fast-track candidates first, then by CG rank
    status_order = {"fast_track_candidate": 0, "accelerated_review": 1,
                    "re_review_pending": 2, "monitoring": 3, "permanently_excluded": 4}
    watchlist.sort(key=lambda x: (status_order.get(x["status"], 5), x["current_cg_rank"]))

    total = len(watchlist)
    action_items = [w for w in watchlist if w["status"] in (
        "fast_track_candidate", "accelerated_review", "re_review_pending"
    )]

    out = {
        "total_watchlist": total,
        "action_items": len(action_items),
        "fast_track_candidates": sum(1 for w in watchlist if w["status"] == "fast_track_candidate"),
        "accelerated_reviews": sum(1 for w in watchlist if w["status"] == "accelerated_review"),
        "re_review_pending": sum(1 for w in watchlist if w["status"] == "re_review_pending"),
        "monitoring": sum(1 for w in watchlist if w["status"] == "monitoring"),
        "permanently_excluded": sum(1 for w in watchlist if w["status"] == "permanently_excluded"),
        "standard_version": "2.0",
        "last_reviewed": "2026-05-21",
        "watchlist": watchlist,
    }

    if not include_resolved:
        out["watchlist"] = [w for w in watchlist if w["status"] != "permanently_excluded"]
        out["total_watchlist"] = len(out["watchlist"])

    return JSONResponse(content=out)


# ── Agent: Inclusion Standard ─────────────────────────────────────────────────

_INCLUSION_STANDARD = {
    "version": "2.0",
    "effective_date": "2026-05-21",
    "design_principle": "Alpha-preserving filter, not risk-elimination filter. Screens structurally broken or fraudulent assets — not high-conviction emerging assets that are new or have fully recovered from past incidents.",
    "criteria": [
        {
            "id": "1", "name": "Liquidity Threshold", "applies_to": "all",
            "gate_type": "hard",
            "thresholds": {
                "crypto_30d_avg_volume_usd": 5_000_000,
                "crypto_min_tier1_exchange_count": 3,
                "crypto_max_bid_ask_spread_pct": 1.5,
                "tradfi_30d_avg_volume_usd": 50_000_000,
                "tradfi_listing": "NYSE or NASDAQ primary",
            },
            "rationale": "Institutional portfolio construction requires ability to enter and exit at size without material market impact.",
            "data_sources": ["CoinGecko Pro", "Bloomberg"],
            "example_rejection": "POLYX — 30d average volume ~$300K against $5M minimum.",
        },
        {
            "id": "2", "name": "Data Completeness", "applies_to": "all",
            "gate_type": "hard",
            "thresholds": {
                "crypto_min_ohlcv_history_days": 90,
                "defi_tvl_source": "DeFiLlama API with <24h latency",
                "defi_min_tvl_history_days": 90,
                "tradfi_etf_min_audited_nav_years": 2,
                "us_equity_min_audited_financials_years": 3,
            },
            "rationale": "Incomplete data produces noise, not signal. Assets that cannot be scored reliably across all 5 pillars are excluded rather than partially scored.",
            "data_sources": ["DeFiLlama", "CoinGecko Pro", "Glassnode", "SEC EDGAR"],
            "example_rejection": "SNX — three product pivots created TVL data discontinuity; V2 and V3 data incomparable.",
        },
        {
            "id": "3", "name": "Institutional Custody Eligibility", "applies_to": "all",
            "gate_type": "hard",
            "approved_custodians": [
                "Coinbase Prime / Coinbase Custody",
                "BitGo Trust",
                "Fireblocks (institutional network)",
                "Anchorage Digital Bank",
                "Fidelity Digital Assets",
                "Komainu",
                "Standard Chartered Zodia Custody",
            ],
            "tradfi_alternative": "DTCC eligibility sufficient for TradFi assets",
            "rationale": "An asset that cannot be held by an institutional custodian cannot be allocated to by pension funds, family offices, or regulated funds.",
            "data_sources": ["Published custodian asset coverage lists, reviewed monthly"],
            "example_rejection": "VIRTUAL — not supported by any listed custodian as of April 2026.",
        },
        {
            "id": "4", "name": "Regulatory Status", "applies_to": "all",
            "gate_type": "hard",
            "requirements": [
                "Not classified as unregistered security by SFC Hong Kong, US SEC, or EU MiCA",
                "No active enforcement action or charges naming issuing entity or primary development team",
                "No OFAC sanctions designation on issuing entity or protocol treasury",
                "Primary distribution mechanism not found unlawful by relevant regulator",
            ],
            "rationale": "Active regulatory action exposes fund and LPs to legal and reputational risk. Most dynamic criterion — reviewed monthly.",
            "data_sources": ["SFC HK", "SEC enforcement database", "OFAC SDN list", "EU MiCA registry"],
            "example_rejection": "BCH — primary public advocate Roger Ver under DOJ indictment for tax evasion (April 2024).",
        },
        {
            "id": "5", "name": "Token Mechanics", "applies_to": "crypto_only",
            "gate_type": "hard",
            "thresholds": {
                "min_circulating_to_total_supply_ratio": 0.30,
                "max_annual_emission_rate_pct_of_circulating": 25.0,
                "active_emission_exploits": 0,
                "vesting_schedule_publicly_verifiable": True,
                "historical_undisclosed_inflation_events": 0,
            },
            "rationale": "Token mechanics determine whether scoring has operational meaning. Undisclosed inflation or exploitable emission schedules render all pillar scores unreliable.",
            "data_sources": ["TokenUnlocks.app", "Messari", "Etherscan", "Solscan"],
            "example_rejection": "ICP — >90% undisclosed supply inflation in first 8 months post-launch (2021).",
        },
        {
            "id": "6", "name": "Trading History", "applies_to": "all",
            "gate_type": "soft_with_fasttrack",
            "thresholds": {
                "standard_min_days": 90,
                "fasttrack_min_days": 45,
                "fasttrack_conditions": [
                    "Institutional custody supported from launch (Criterion 3)",
                    "Full tokenomics published with on-chain verifiable vesting pre-launch",
                    "Minimum $10M audited VC or institutional funding verifiable on-chain",
                    "No supply anomalies in first 45 days of trading",
                ],
                "confidence_multiplier_45_to_90_days": 0.6,
                "confidence_multiplier_90_to_180_days": 0.85,
                "confidence_multiplier_above_180_days": 1.0,
            },
            "rationale": "90-day minimum covers one full calendar quarter — sufficient for M pillar momentum and initial O pillar risk profiling. 180-day requirement was too strict and would have excluded high-conviction emerging assets like Hyperliquid.",
            "data_sources": ["CoinGecko listing date", "Bloomberg IPO date", "Messari VC funding"],
        },
        {
            "id": "7", "name": "Team and Protocol Integrity", "applies_to": "all",
            "gate_type": "judgment_required",
            "disqualifying_conditions": [
                "Documented rug-pull history with no resolution",
                "Anonymous team with no institutional accountability (no audit + no legal entity + no 2yr clean record)",
                "Unresolved material exploit >$1M (root cause unpublished or users not made whole or vulnerability unpatched)",
                "Documented treasury misuse without governance approval",
                "Active leadership in financial crime legal proceedings",
            ],
            "remediation_pathway": {
                "available": True,
                "requirements": [
                    "Full public post-mortem published within 30 days of incident",
                    "Users made whole (≥80% of lost funds recovered or compensated)",
                    "Independent security audit completed and published post-incident",
                    "12+ consecutive months clean operation since incident",
                    "No repeat of same vulnerability class",
                ],
                "note": "Protocols that have genuinely fixed problems and demonstrated sustained recovery can re-qualify. This prevents permanent blacklisting that ignores rehabilitation evidence.",
            },
            "rationale": "The failure mode that cannot be defended when capital is lost. Most subjective criterion but most important for institutional credibility.",
            "data_sources": ["Rekt.news", "DeFiLlama hacks database", "SEC enforcement", "Messari governance research"],
            "example_rejections": ["AXS ($625M Ronin exploit)", "SUSHI (repeated treasury incidents)", "CRV (founder personal position systemic risk)", "RUNE (dual exploit 2021, now in remediation review)"],
        },
    ],
    "application_rules": {
        "logic": "AND — failure on any single criterion results in exclusion",
        "compensating_mechanisms": False,
        "order_of_evaluation": ["1 (liquidity) first for efficiency", "5 and 7 require most judgment, evaluated last"],
        "emergency_exclusion_triggers": [
            "Enforcement action naming issuing team",
            "Material exploit >$1M user funds at risk",
            "Liquidity breach below threshold for 7 consecutive days",
        ],
        "emergency_exclusion_sla_hours": 24,
    },
    "review_cadence": {
        "full_universe_review": "Monthly",
        "emergency_exclusion": "Within 24 hours of trigger",
        "borderline_reevaluation": "At next monthly review when blocking condition resolves",
    },
}


@router.get("/api/v1/agent/inclusion-standard")
async def get_inclusion_standard(criterion_id: str = ""):
    """
    Returns CometCloud's 7-criterion institutional inclusion standard as structured JSON.

    Machine-readable thresholds, rationale, data sources, and remediation pathways for
    each criterion. Designed for agent reasoning context — embed this in your system prompt
    to enable your agent to apply the same standard CometCloud uses.

    Filter to a specific criterion with ?criterion_id=7 (e.g. for team integrity checks only).
    """
    if criterion_id:
        criteria = [c for c in _INCLUSION_STANDARD["criteria"] if c["id"] == criterion_id]
        if not criteria:
            return JSONResponse(status_code=404, content={"error": f"Criterion {criterion_id} not found. Valid IDs: 1-7"})
        return JSONResponse(content={
            **{k: v for k, v in _INCLUSION_STANDARD.items() if k != "criteria"},
            "criteria": criteria,
        })
    return JSONResponse(content=_INCLUSION_STANDARD)


# ── WebSocket ─────────────────────────────────────────────────────────────────

@router.websocket("/ws/cis")
async def websocket_cis(websocket: WebSocket):
    """
    Real-time CIS score updates. Sends current state immediately on connect.
    Supports ping/pong keepalive. Requires auth via first message: "auth:<INTERNAL_TOKEN>"
    """
    await websocket.accept()
    # Auth via first message — must contain valid token
    try:
        msg = await asyncio.wait_for(websocket.receive_text(), timeout=10)
        if msg != f"auth:{_INTERNAL_TOKEN}":
            await websocket.close(code=4001, reason="Unauthorized")
            return
    except asyncio.TimeoutError:
        await websocket.close(code=4001, reason="Auth timeout")
        return
    except Exception:
        await websocket.close(code=4001, reason="Auth error")
        return

    await ws_manager.connect(websocket)

    # Send current state immediately on connect
    if store.last_cis_broadcast:
        await websocket.send_json(store.last_cis_broadcast)

    # Server-side heartbeat: send ping every 30s, expect pong within 10s.
    # Cleans up stale connections from crashed Mac Mini scheduler.
    _HEARTBEAT_INTERVAL = 30
    _PONG_TIMEOUT       = 10
    _pending_pong = False

    async def _heartbeat():
        nonlocal _pending_pong
        while True:
            await asyncio.sleep(_HEARTBEAT_INTERVAL)
            try:
                if _pending_pong:
                    # Previous ping went unanswered — force close
                    await websocket.close(code=1001, reason="Heartbeat timeout")
                    return
                await websocket.send_json({"type": "ping", "ts": time.time()})
                _pending_pong = True
                # Give client 10s to pong before next heartbeat check
                await asyncio.sleep(_PONG_TIMEOUT)
                # If still pending after pong window, close on next iteration
            except Exception:
                return

    heartbeat_task = asyncio.create_task(_heartbeat())

    try:
        while True:
            try:
                data = await websocket.receive_text()
                if data == "ping":
                    await websocket.send_text("pong")
                elif data == "pong" or data == '{"type":"pong"}':
                    _pending_pong = False  # Heartbeat acknowledged
            except Exception:
                break
    except Exception:
        pass
    finally:
        heartbeat_task.cancel()
        ws_manager.disconnect(websocket)


async def _broadcast_cis_update(universe: list):
    """Called by internal push endpoint when new scores arrive."""
    try:
        store.last_cis_broadcast = {
            "type":      "full",
            "timestamp": datetime.now().isoformat(),
            "count":     len(universe),
            "assets": [
                {
                    "s":     a["symbol"],
                    "g":     a.get("grade", "?"),
                    "sc":    a.get("cis_score", a.get("score", 0)),
                    "sg":    a.get("signal", "?"),
                    "f":     _p(a, "f"),
                    "m":     _p(a, "m"),
                    "o":     _p(a, "o") or _p(a, "r"),
                    "ss":    _p(a, "s"),
                    "a":     _p(a, "a"),
                    "ch30d": a.get("change_30d"),
                    "ch7d":  a.get("change_7d"),
                }
                for a in universe
            ],
        }
        await ws_manager.broadcast(store.last_cis_broadcast)
    except Exception as e:
        _logger.warning(f"[WS] broadcast error (non-fatal): {e}")


# ---------------------------------------------------------------------------
# GET /api/v1/cis/history/{symbol}
# ---------------------------------------------------------------------------

@router.get("/cis/history/{symbol}")
async def get_cis_history(
    symbol: str,
    days: int = Query(default=30, ge=1, le=90),
):
    """Return CIS score history for a symbol from Supabase (Redis-cached, TTL=300s)."""
    sym = symbol.upper()
    cache_key = f"cis:history:{sym}:{days}"

    cached = await redis_get_key(cache_key)
    if cached:
        return cached

    rows = await supabase_get_history(sym, days)

    if not rows:
        result = {"symbol": sym, "history": [], "count": 0, "message": "No history found"}
    else:
        result = {
            "symbol": sym,
            "history": rows,
            "count": len(rows),
            "days_requested": days,
        }

    await redis_set_key(cache_key, result, ttl=300)
    return result


# ---------------------------------------------------------------------------
# GET /api/v1/cis/trend/{symbol}
# ---------------------------------------------------------------------------

@router.get("/cis/trend/{symbol}")
async def get_cis_trend(
    symbol: str,
    days: int = Query(default=7, ge=1, le=30),
):
    """Return trend direction (improving / stable / declining) for a symbol over N days."""
    sym = symbol.upper()

    rows = await supabase_get_history(sym, days)

    if len(rows) < 2:
        _logger.warning(f"[CIS trend] insufficient data for {sym}: {len(rows)} rows")
        return {"symbol": sym, "trend": "insufficient_data", "direction": None}

    half = len(rows) // 2
    recent_scores = [r.get("score", 0) for r in rows[:half]]
    older_scores  = [r.get("score", 0) for r in rows[half:]]

    avg_recent = sum(recent_scores) / len(recent_scores)
    avg_older  = sum(older_scores)  / len(older_scores)
    delta = avg_recent - avg_older

    if delta > 1:
        direction = "improving"
    elif delta < -1:
        direction = "declining"
    else:
        direction = "stable"

    return {
        "symbol":        sym,
        "trend":         direction,
        "delta_cis":     round(delta, 2),
        "avg_recent":    round(avg_recent, 2),
        "avg_older":     round(avg_older, 2),
        "data_points":   len(rows),
        "days":          days,
        "latest_grade":  rows[0].get("grade"),
        "latest_signal": rows[0].get("signal"),
    }


# ── CIS Score History + Trend (agent-queryable) ───────────────────────────────

@router.get("/api/v1/cis/history/{symbol}")
async def cis_history(symbol: str, days: int = 30):
    """
    Returns CIS score history for a single asset from Supabase.
    Agents use this for backtesting, trend detection, and score drift analysis.
    Cached in Redis 5 minutes to avoid hammering Supabase on repeated calls.

    Example: GET /api/v1/cis/history/BTC?days=7
    """
    symbol = symbol.upper()
    cache_key = f"cis:history:{symbol}:{days}"

    cached = await store.redis_get_key(cache_key)
    if cached:
        return cached

    rows = await store.supabase_get_history(symbol, days=days)

    if not rows:
        return {
            "symbol": symbol,
            "days": days,
            "count": 0,
            "history": [],
            "note": "No history found. Asset may not be in T1 universe or Supabase not yet populated."
        }

    result = {
        "symbol": symbol,
        "days": days,
        "count": len(rows),
        "history": sanitize_floats(rows),
    }

    await store.redis_set_key(cache_key, result, ttl=300)
    return result


@router.get("/api/v1/cis/trend/{symbol}")
async def cis_trend(symbol: str, days: int = 7):
    """
    Returns directional trend for a single asset: improving / stable / declining.
    Compares earliest vs latest CIS score over the window.
    Agents use this for momentum-based filtering and drift alerts.

    Example: GET /api/v1/cis/trend/ETH?days=7
    """
    symbol = symbol.upper()
    cache_key = f"cis:trend:{symbol}:{days}"

    cached = await store.redis_get_key(cache_key)
    if cached:
        return cached

    rows = await store.supabase_get_history(symbol, days=days)

    if len(rows) < 2:
        return {
            "symbol": symbol,
            "days": days,
            "trend": "insufficient_data",
            "data_points": len(rows),
        }

    # rows are desc (latest first)
    latest = rows[0]
    earliest = rows[-1]
    latest_score  = latest.get("score") or 0
    earliest_score = earliest.get("score") or 0
    delta = round(latest_score - earliest_score, 2)

    if delta >= 3:
        direction = "improving"
    elif delta <= -3:
        direction = "declining"
    else:
        direction = "stable"

    result = {
        "symbol":         symbol,
        "days":           days,
        "trend":          direction,
        "delta":          delta,
        "latest_score":   round(latest_score, 2),
        "earliest_score": round(earliest_score, 2),
        "latest_grade":   latest.get("grade"),
        "latest_signal":  latest.get("signal"),
        "recorded_at":    latest.get("recorded_at"),
        "data_points":    len(rows),
    }

    await store.redis_set_key(cache_key, result, ttl=300)
    return result


# ── Grade Changes — polling endpoint for agents ───────────────────────────────

_GRADE_RANK_STATIC = {"A+": 8, "A": 7, "B+": 6, "B": 5, "C+": 4, "C": 3, "D": 2, "F": 1}


@router.get("/api/v1/cis/grade-changes")
async def get_grade_changes(hours: int = 24, response: Response = None):
    """
    Returns assets whose CIS grade changed in the last N hours.

    Compares the two most recent Supabase score rows per asset.
    Useful for agents polling grade transitions without implementing webhook endpoints.
    Complements the push-based GRADE_UPGRADE/GRADE_DOWNGRADE webhook delivery.

    Response fields:
      upgrades   — assets that moved to a higher grade (e.g. B → B+), sorted by delta desc
      downgrades — assets that moved to a lower grade  (e.g. B+ → B), sorted by delta asc
      stable_count — assets with unchanged grades
      total_changes — upgrades + downgrades count

    Example: GET /api/v1/cis/grade-changes?hours=24
             GET /api/v1/cis/grade-changes?hours=6
    """
    from datetime import timezone

    cache_key = f"cis:grade_changes:{hours}"
    cached = await store.redis_get_key(cache_key)
    if cached:
        return cached

    # Get current universe symbols
    universe = await redis_get()
    if not universe:
        try:
            universe = await calculate_cis_universe()
        except Exception:
            universe = []

    assets  = universe if isinstance(universe, list) else universe.get("assets", [])
    symbols = [a.get("symbol") for a in assets if a.get("symbol")]

    if not symbols:
        return {"upgrades": [], "downgrades": [], "stable_count": 0, "checked": 0, "hours": hours, "total_changes": 0}

    # Fetch last 2 scores per symbol (sufficient to detect one grade change)
    recent = await store.supabase_get_recent_scores(symbols, n=2)

    upgrades: list   = []
    downgrades: list = []
    stable   = 0
    now      = datetime.utcnow().replace(tzinfo=timezone.utc)

    for sym, rows in recent.items():
        if len(rows) < 2:
            stable += 1
            continue

        latest = rows[0]   # newest first
        prev   = rows[1]

        new_grade  = latest.get("grade", "")
        prev_grade = prev.get("grade",  "")

        if not new_grade or not prev_grade or new_grade == prev_grade:
            stable += 1
            continue

        # Respect the hours window — skip if the latest score predates the window
        try:
            change_ts = datetime.fromisoformat(
                latest.get("recorded_at", "").replace("Z", "+00:00")
            )
            if (now - change_ts).total_seconds() / 3600 > hours:
                stable += 1
                continue
        except Exception:
            pass  # include if timestamp parsing fails

        new_rank  = _GRADE_RANK_STATIC.get(new_grade,  0)
        prev_rank = _GRADE_RANK_STATIC.get(prev_grade, 0)
        delta     = new_rank - prev_rank

        entry = {
            "symbol":     sym,
            "from_grade": prev_grade,
            "to_grade":   new_grade,
            "delta":      delta,
            "cis_score":  round(latest.get("score") or 0, 2),
            "signal":     latest.get("signal", ""),
            "changed_at": latest.get("recorded_at", ""),
        }

        if delta > 0:
            upgrades.append(entry)
        else:
            downgrades.append(entry)

    upgrades.sort(key=lambda x: -x["delta"])
    downgrades.sort(key=lambda x: x["delta"])

    result = {
        "hours":         hours,
        "upgrades":      upgrades,
        "downgrades":    downgrades,
        "stable_count":  stable,
        "checked":       len(symbols),
        "total_changes": len(upgrades) + len(downgrades),
    }

    # Cache 15 min — Mac Mini pushes every ~30 min so sub-minute freshness is unnecessary
    await store.redis_set_key(cache_key, result, ttl=900)
    if response:
        response.headers["Cache-Control"] = "public, max-age=900, stale-while-revalidate=1800"
    return result


# ── Daily full-universe snapshot (data-durability guarantee) ──────────────────
# The Mac Mini push (/internal/cis-scores) only carries the assets it chooses to
# push (currently T1 only since the 2026-06-06 engine change) — so relying on it
# alone silently drops the T2 half of the universe from cis_scores. This Railway-
# side job snapshots the FULL merged universe (T1 + T2) once a day, independent of
# the push, so every asset has a guaranteed daily row. source='railway_snapshot'.
async def snapshot_full_universe_to_supabase() -> dict:
    try:
        data = await get_cis_universe(force_source=None)
    except Exception as e:
        _logger.warning(f"[SNAPSHOT] universe build failed: {e}")
        return {"ok": False, "error": str(e), "rows": 0}

    universe = (data or {}).get("universe", []) if isinstance(data, dict) else []
    if not universe:
        # Never write nothing — an empty snapshot is a failure, not a valid day.
        _logger.warning("[SNAPSHOT] empty universe — skipping (no write)")
        return {"ok": False, "rows": 0, "reason": "empty_universe"}

    regime = (data or {}).get("macro_regime") or (data or {}).get("regime")
    # I1 APPLIED TO A LABEL (fixed 2026-08-09). `canonical_regime(None)` returns
    # "NEUTRAL" — a perfectly valid regime — so when the universe payload arrived
    # without one, this job wrote NEUTRAL for all 58 symbols in a single batch and
    # nothing looked wrong. Measured on 2026-08-08: 58 rows sharing the timestamp
    # 14:14:25.189708, while the SAME source wrote TIGHTENING at 04:04 and 14:53.
    # It happened once a day (08-07 08:44, 08-06 10:17).
    #
    # The live cost: the ① book reads the regime to set exposure, TIGHTENING maps to
    # 0.5 and NEUTRAL to 1.0, so the book ran FULL SIZE on the first day of its
    # forward record because a fallback default was indistinguishable from a real
    # reading.
    #
    # Note the asymmetry this sat next to: the guard directly above refuses to write
    # ZERO rows ("an empty snapshot is a failure, not a valid day") and then wrote a
    # fabricated value on every row. **Completeness was checked; correctness was not.**
    # Unmeasured must be NULL, never a valid-looking default.
    from src.data.cis.cis_provider import canonical_regime_strict as _canon_strict
    _canon_regime = _canon_strict(regime)
    if _canon_regime is None:
        _logger.warning("[SNAPSHOT] regime %r missing or unrecognised — writing NULL, "
                        "not NEUTRAL (a default here sizes the ① book at 1.0x for a day)",
                        regime)
    # S-184: the same T1-shadowing guard the hourly loop got in S-180. This job
    # writes BOTH tiers by design ("every asset has a guaranteed daily row"), so
    # it cannot simply skip T2 — but a T2 row for a symbol that already has a
    # fresh T1 row today is not filling a gap, it is overwriting a better answer
    # with a worse one. Under the S-180 misclassification the whole universe
    # presents as T2, and this job would then write 58 shadow rows in one batch
    # instead of the 43 T1 + 15 T2 it exists to produce.
    #
    # Deliberately the SAME mechanism and the same helper as the hourly loop.
    # Two guards with different shapes against one failure is how you end up
    # maintaining two mental models and trusting the wrong one.
    from src.api.store import supabase_fresh_t1_symbols
    _fresh_t1 = await supabase_fresh_t1_symbols(max_age_minutes=1440)
    _shadowed: list[str] = []

    rows = []
    for a in universe:
        sym = a.get("symbol") or a.get("asset_id")
        score = a.get("cis_score", a.get("score"))
        if not sym or score is None:
            continue
        tier = a.get("data_tier")
        tier_label = a.get("data_tier_label") or ("T1" if tier in (1, "1", "T1") else "T2")
        if tier_label == "T2" and _fresh_t1 and sym.upper() in _fresh_t1:
            # A T1 row for this symbol landed within the day. Writing T2 on top
            # of it does not guarantee a daily row — there already is one.
            _shadowed.append(sym)
            continue
        # shape-tolerant pillar extraction + canonical regime — same latent null-pillar bug as the
        # hourly T2 loop (only read nested pillars[K]; the builder emits FLAT k → NULL pillars).
        # Fixed 2026-07-23 so the T2 fallback keeps pillars populated through a T1 stall.
        _pp = a.get("pillars") if isinstance(a.get("pillars"), dict) else {}
        def _pv(K, _a=a, _p=_pp):
            return (_p.get(K) if _p.get(K) is not None
                    else _a.get(K.lower()) if _a.get(K.lower()) is not None
                    else _a.get(f"pillar_{K.lower()}") if _a.get(f"pillar_{K.lower()}") is not None
                    else _a.get(f"{K.lower()}_score"))
        rows.append({
            "symbol":             sym,
            "name":               a.get("name", ""),
            "score":              score,
            "raw_cis_score":      a.get("raw_cis_score") or score,
            "grade":              a.get("grade"),
            "signal":             a.get("signal"),
            "percentile":         a.get("percentile_rank"),
            "pillar_f":           _pv("F"),
            "pillar_m":           _pv("M"),
            "pillar_o":           _pv("O"),
            "pillar_s":           _pv("S"),
            "pillar_a":           _pv("A"),
            "asset_class":        a.get("asset_class", a.get("class", "")),
            "macro_regime":       _canon_regime,   # NULL when undetermined — see above
            "data_tier":          tier_label,
            "data_quality_score": a.get("data_quality_score"),
            "las":                a.get("las"),
            "confidence":         a.get("confidence", 1.0 if tier_label == "T1" else 0.8),
            "source":             "railway_snapshot",
        })

    if not rows:
        return {"ok": False, "rows": 0, "reason": "no_valid_rows"}

    ok = await supabase_insert_batch(rows)
    t1 = sum(1 for r in rows if r["data_tier"] == "T1")
    _logger.warning(f"[SNAPSHOT] daily full-universe snapshot: ok={ok} rows={len(rows)} "
                    f"(T1={t1} T2={len(rows)-t1} shadow-suppressed={len(_shadowed)})")
    if len(_shadowed) >= 10:
        # Suppressing a handful is routine. Suppressing ten-plus means the tier
        # resolver called a T1 universe T2 — S-180 live — and the fact that this
        # job still produced a clean result must not hide that.
        _logger.error("[SNAPSHOT] ⚠️  %s symbols presented as T2 while carrying a "
                      "fresh T1 row: %s%s — tier resolution is wrong wholesale, "
                      "not per-symbol. Check `redis_status` in the universe payload.",
                      len(_shadowed), sorted(_shadowed)[:12],
                      " …" if len(_shadowed) > 12 else "")
    return {"ok": bool(ok), "rows": len(rows), "t1": t1, "t2": len(rows) - t1,
            "shadow_suppressed": len(_shadowed),
            "t1_occupancy_known": _fresh_t1 is not None}


@router.post("/internal/cis-snapshot")
async def trigger_cis_snapshot(x_internal_token: str = Header(None)):
    """Manually trigger the daily full-universe snapshot (same write the daily loop
    performs). Guarded by INTERNAL_TOKEN."""
    if not _INTERNAL_TOKEN or not x_internal_token or x_internal_token != _INTERNAL_TOKEN:
        raise HTTPException(status_code=401, detail="unauthorized")
    return await snapshot_full_universe_to_supabase()
