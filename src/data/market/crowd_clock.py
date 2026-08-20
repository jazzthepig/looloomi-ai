"""
Crowd Clock — the behavioral-phase primitive (Seth, 2026-07-17).
================================================================
Trader Tom doctrine (docs/TRADER_TOM_DOCTRINE.md): the durable, non-decaying edge is the
crowd's EMOTIONAL cycle, not the macro regime. We already run a macro-regime detector
(RISK_ON/OFF) but had NO behavioral clock. This is it — one primitive that measures where
the crowd sits on the eternal loop:

    capitulation → accumulation → markup → euphoria → distribution → (markdown) → capitulation

Built ENTIRELY from data we already store — no new feeds:
  · FNG (fear/greed)                     — sentiment axis
  · BTC 30d / 7d change                  — trend axis + acceleration
  · mean funding positioning pressure    — leverage crowding (−pressure = crowded longs)
  · CIS grade dispersion                 — differentiation (leaders separating vs all-together)
  · volume expansion (optional)          — participation / climax

Design principles (the bar in CLAUDE.md):
  · Transparent + interpretable — rule-based soft memberships, every driver exposed. No black box.
  · HONEST — this is a CANDIDATE. It is NOT outcome-validated. We instrument it (persist daily
    phase) so a later resolver can test "does phase X precede forward asymmetry?" and REFUTE or
    keep it (Refutation Ledger R22). Until then it carries no predictive claim.
  · Compliance — positioning language only; the posture note is a research read, not advice.

One clock, freely fusable (ARCHITECTURE.md): every surface reads the SAME phase — Diagnose can
color by it, the two-layer book can size by it (mean-reversion sleeve wakes at capitulation,
trend sleeve presses at markup), the signal feed narrates it.
"""
from __future__ import annotations

import logging

_logger = logging.getLogger(__name__)

# Phase order around the clock (degrees on the dial; a full loop).
PHASES = ["capitulation", "accumulation", "markup", "euphoria", "distribution"]
_PHASE_ANGLE = {"capitulation": 234, "accumulation": 162, "markup": 90, "euphoria": 18, "distribution": 306}

# Positioning-safe posture read per phase (research read, NOT advice). Ties the clock to the
# two-layer book doctrine: mean-reversion sleeve wakes at fear, trend sleeve presses at markup.
_PHASE_POSTURE = {
    "capitulation":  "Fear extreme — a selective mean-reversion window, NOT a broad long: at a 30d horizon momentum has beaten reversal in crypto (R24), so size the contrarian sleeve modestly and wait for its own deep-extreme trigger.",
    "accumulation":  "Basing — quiet accumulation of quality; low urgency, build the core.",
    "markup":        "Trend-confirmation phase — the window to press confirmed strength (the trend sleeve's home).",
    "euphoria":      "Late-cycle strength — trim into it, defend; crowded longs are flush fuel, do not chase.",
    "distribution":  "Topping — reduce gross, hedge; leadership narrowing as the marginal buyer thins.",
}


def _relu(x: float) -> float:
    return x if x > 0 else 0.0


def _clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def compute_crowd_clock(fng: float | None, chg30: float | None, chg7: float | None,
                        mean_pressure: float | None, dispersion_std: float | None,
                        volume_ratio: float | None) -> dict:
    """Pure function: raw inputs → {phase, phase_scores, confidence, angle, drivers, posture, axes}.

    Inputs (all optional; missing ones degrade gracefully to neutral):
      fng            : Fear & Greed 0..100
      chg30, chg7    : BTC % change over 30d / 7d
      mean_pressure  : mean funding positioning_pressure across majors
                       (convention: −1 = crowded LONGS, +1 = crowded SHORTS)
      dispersion_std : std of CIS scores across the universe (differentiation)
      volume_ratio   : aggregate volume vs baseline (>1 = expansion)
    """
    # ── normalize to signed axes ───────────────────────────────────────────────
    greed = _clip(((fng if fng is not None else 50) - 50) / 50.0, -1, 1)   # −1 fear .. +1 greed
    t30 = _clip((chg30 if chg30 is not None else 0) / 20.0, -1, 1)          # 20% ≈ full trend
    t7 = _clip((chg7 if chg7 is not None else 0) / 10.0, -1, 1)
    accel = _clip(t7 - t30, -1, 1)                                          # >0 short-term accelerating up
    long_crowd = _clip(-(mean_pressure if mean_pressure is not None else 0), -1, 1)  # +1 = crowded LONG
    disp = _clip((dispersion_std if dispersion_std is not None else 8) / 15.0, 0, 1) # leaders separating
    vol = _clip(((volume_ratio if volume_ratio is not None else 1.0) - 1) / 0.5, -1, 1)

    # ── soft phase memberships (transparent rules) ─────────────────────────────
    s = {
        # fear + downtrend, amplified by a volume climax and crowded shorts
        "capitulation": _relu(-greed) * _relu(-t30) * (0.6 + 0.4 * _relu(vol)) * (1 + 0.3 * _relu(-long_crowd)),
        # fear→neutral, price basing (small |trend|) turning up, quiet
        "accumulation": _relu(0.5 - abs(greed + 0.15)) * _relu(0.5 - abs(t30)) * (0.6 + 0.4 * _relu(accel)) * (1 - 0.3 * _relu(long_crowd)),
        # greed rising, uptrend, leaders separating — FADES into euphoria as greed goes extreme
        "markup":       _relu(greed) * _relu(t30) * (0.5 + 0.5 * disp) * (1 - 0.6 * _relu((greed - 0.6) / 0.4)),
        # extreme greed, strong uptrend, crowded longs, climax
        "euphoria":     1.3 * _relu(greed - 0.35) * _relu(t30) * (0.6 + 0.6 * _relu(long_crowd)) * (0.7 + 0.3 * _relu(vol)),
        # greed high but rolling over (accel<0), crowded longs, dispersion falling
        "distribution": _relu(greed) * _relu(-accel) * (0.5 + 0.5 * _relu(long_crowd)) * (0.6 + 0.4 * (1 - disp)),
    }
    # guarantee a signal even in dead-neutral tape
    if max(s.values()) < 1e-6:
        s["accumulation"] = 0.15

    total = sum(s.values()) or 1.0
    scores = {k: round(v / total, 3) for k, v in s.items()}
    phase = max(scores, key=scores.get)
    ordered = sorted(scores.values(), reverse=True)
    confidence = round(ordered[0] - (ordered[1] if len(ordered) > 1 else 0), 3)  # margin = conviction

    # needle angle = winner, nudged toward the runner-up neighbor for a smooth dial
    angle = float(_PHASE_ANGLE[phase])

    # ── plain-language drivers (what put us here) ──────────────────────────────
    drivers = []
    if fng is not None:
        drivers.append(f"Fear & Greed {int(fng)}/100 ({'fear' if greed < -0.2 else 'greed' if greed > 0.2 else 'neutral'})")
    if chg30 is not None:
        drivers.append(f"BTC 30d {chg30:+.1f}% ({'up-trend' if t30 > 0.15 else 'down-trend' if t30 < -0.15 else 'basing'})")
    if mean_pressure is not None:
        drivers.append("leverage crowded long" if long_crowd > 0.25 else "leverage crowded short" if long_crowd < -0.25 else "leverage balanced")
    if dispersion_std is not None:
        drivers.append("leaders separating" if disp > 0.55 else "moving together")

    return {
        "phase": phase,
        "phase_scores": scores,
        "confidence": confidence,
        "angle": angle,
        "axes": {"greed": round(greed, 2), "trend": round(t30, 2), "accel": round(accel, 2),
                 "long_crowd": round(long_crowd, 2), "dispersion": round(disp, 2), "volume": round(vol, 2)},
        "drivers": drivers,
        "posture": _PHASE_POSTURE[phase],
        "status": "candidate",
        "disclaimer": "Behavioral-phase candidate — instrumented for validation, NOT yet outcome-proven. "
                      "Positioning read only; not investment advice.",
    }


async def get_crowd_clock() -> dict:
    """Assemble live inputs from data we ALREADY cache (Redis cis:local_scores + cis:positioning
    + FNG), compute the clock, persist today's snapshot for later validation. Never raises."""
    fng = chg30 = chg7 = mean_pressure = disp_std = vol_ratio = None
    try:
        from src.api.store import redis_get_key
        cis = await redis_get_key("cis:local_scores") or {}
        pos = await redis_get_key("cis:positioning") or {}
        uni = cis.get("assets") or cis.get("universe") or []

        # BTC trend
        btc = next((a for a in uni if (a.get("symbol") or a.get("asset_id") or "").upper() == "BTC"), None)
        if btc:
            chg30 = _to_f(btc.get("change_30d") or btc.get("chg_30d") or btc.get("price_change_30d"))
            chg7 = _to_f(btc.get("change_7d") or btc.get("chg_7d") or btc.get("price_change_7d"))

        # CIS dispersion (std of scores)
        scores = [_to_f(a.get("cis_score") or a.get("score")) for a in uni]
        scores = [x for x in scores if x is not None]
        if len(scores) >= 5:
            m = sum(scores) / len(scores)
            disp_std = (sum((x - m) ** 2 for x in scores) / len(scores)) ** 0.5

        # mean funding positioning pressure
        if isinstance(pos, dict) and pos:
            ps = [(_to_f((v or {}).get("positioning_pressure"))) for v in pos.values() if isinstance(v, dict)]
            ps = [x for x in ps if x is not None]
            if ps:
                mean_pressure = sum(ps) / len(ps)
    except Exception as e:
        _logger.warning(f"[CROWD-CLOCK] redis assemble failed: {e}")

    # FNG — from macro-pulse (the reliable path; raw Redis get_fear_greed comes up null on Railway)
    try:
        from src.api.routers.market import get_macro_pulse
        mp = await get_macro_pulse()
        if isinstance(mp, dict):
            fng = _to_f(mp.get("fear_greed_value") or (mp.get("fng") or {}).get("value"))
    except Exception:
        pass

    # BTC trend + CIS dispersion — fall back to the live CIS universe (same source the leaderboard
    # uses) when the raw cis:local_scores Redis key is empty/absent (it is, on Railway).
    if chg30 is None or disp_std is None:
        try:
            from src.api.routers.cis import get_cis_universe
            u = await get_cis_universe()
            uni = (u or {}).get("universe", []) or []
            if chg30 is None:
                btc = next((a for a in uni if (a.get("symbol") or a.get("asset_id") or "").upper() == "BTC"), None)
                if btc:
                    chg30 = _to_f(btc.get("change_30d") or btc.get("chg_30d") or btc.get("price_change_30d"))
                    chg7 = chg7 if chg7 is not None else _to_f(btc.get("change_7d") or btc.get("chg_7d"))
            if disp_std is None:
                sc = [_to_f(a.get("cis_score") or a.get("score")) for a in uni]
                sc = [x for x in sc if x is not None]
                if len(sc) >= 5:
                    mm = sum(sc) / len(sc)
                    disp_std = (sum((x - mm) ** 2 for x in sc) / len(sc)) ** 0.5
        except Exception as e:
            _logger.warning(f"[CROWD-CLOCK] universe fallback failed: {e}")

    clock = compute_crowd_clock(fng, chg30, chg7, mean_pressure, disp_std, vol_ratio)
    # guard: don't show a confident phase when the two core axes (sentiment + trend) are both missing
    if fng is None and chg30 is None:
        clock["phase"] = "insufficient_data"
        clock["confidence"] = 0.0
        clock["posture"] = "Warming up — sentiment and trend inputs unavailable; no phase read yet."
    clock["inputs"] = {"fng": fng, "btc_chg_30d": chg30, "btc_chg_7d": chg7,
                       "mean_positioning_pressure": round(mean_pressure, 3) if mean_pressure is not None else None,
                       "cis_dispersion_std": round(disp_std, 2) if disp_std is not None else None}
    await _persist_daily(clock)
    return clock


def _to_f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


async def _persist_daily(clock: dict) -> None:
    """Persist one snapshot/day → Redis (current) + best-effort Supabase `crowd_clock_log`
    (the falsifiability substrate: later a resolver matches phase → forward 30d asymmetry).
    Idempotent per UTC day. Never raises."""
    import datetime as _dt
    try:
        from src.api.store import redis_get_key, redis_set_key
        await redis_set_key("crowd:clock", clock, ttl=3 * 3600)
        day = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")
        # S-184, same class as S-180. This is an idempotency key, and
        # `redis_get_key` answers None for a MISS and None for an ERROR alike —
        # so a transport failure reads as "not logged yet" and we insert a
        # SECOND row for the same day. A dedup check whose failure mode is a
        # duplicate is not a dedup check.
        #
        # Fail CLOSED: if we could not ask, assume it was logged and skip. A
        # missing day is a visible gap someone can backfill; a duplicate day is
        # a silent double-count in every aggregate built on this table.
        from src.api.store import redis_get_key_status
        _logged, _st = await redis_get_key_status(f"crowd:clock:logged:{day}")
        if _logged or _st in ("error", "unconfigured"):
            if _st == "error":
                _logger.warning("[CROWD-CLOCK] dedup read errored for %s — "
                                "skipping the insert rather than risking a "
                                "duplicate row", day)
            return
        row = {"date": day, "phase": clock["phase"], "confidence": clock["confidence"],
               "angle": clock["angle"], **{f"in_{k}": v for k, v in (clock.get("inputs") or {}).items()}}
        try:
            from src.api.store import supabase_insert_table
            await supabase_insert_table("crowd_clock_log", [row])
        except Exception:
            pass   # table may not exist yet (see scripts/supabase_crowd_clock.sql) — Redis snapshot still stands
        await redis_set_key(f"crowd:clock:logged:{day}", True, ttl=25 * 3600)
    except Exception as e:
        _logger.warning(f"[CROWD-CLOCK] persist failed: {e}")


if __name__ == "__main__":   # quick sanity — the archetypes must resolve
    import json
    cases = {
        "deep fear crash":  dict(fng=12, chg30=-28, chg7=-15, mean_pressure=0.6, dispersion_std=6, volume_ratio=1.6),
        "quiet base":       dict(fng=42, chg30=2, chg7=1, mean_pressure=0.0, dispersion_std=7, volume_ratio=0.8),
        "healthy markup":   dict(fng=62, chg30=14, chg7=8, mean_pressure=-0.2, dispersion_std=12, volume_ratio=1.1),
        "blow-off top":     dict(fng=86, chg30=22, chg7=18, mean_pressure=-0.8, dispersion_std=5, volume_ratio=1.7),
        "rolling over":     dict(fng=71, chg30=9, chg7=-3, mean_pressure=-0.6, dispersion_std=6, volume_ratio=1.0),
    }
    for name, kw in cases.items():
        c = compute_crowd_clock(**kw)
        print(f"{name:18s} → {c['phase']:14s} conf={c['confidence']:.2f}  {c['posture'][:48]}")
