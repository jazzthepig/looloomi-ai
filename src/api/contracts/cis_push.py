"""
CIS Push Contract — canonical schema + normalizer for /internal/cis-scores.

This module is the SINGLE SOURCE OF TRUTH for the Mac Mini → Railway payload
shape. Not MINIMAX_SYNC prose, not Shadow/, not the Mac Mini code copy. The
receiver runs every push through `normalize_cis_payload()`, which:

  1. accepts the current (legacy) shapes the engine actually sends, and
  2. emits ONE canonical shape so every downstream consumer (Supabase history,
     leaderboard, agent API, signal feed) reads the same fields.

Why this exists — drift confirmed live 2026-06-05:
  • Mac Mini flattens pillars to `f/m/r/s/a` (On-chain → `r`); Railway read
    nested `pillars.O` → O was None on every T1 asset. Normalizer maps r/o → O.
  • Mac Mini sends `data_tier: 1` (int) / top-level "T1"; Railway compared to
    the string "T1" → T1 assets mislabeled T2. Normalizer canonicalizes.

Design rules:
  • RESILIENT, never fatal. A single malformed asset is skipped with a warning,
    never a 422 — a bad field must not blank the whole leaderboard.
  • Pure-python (no hard pydantic dependency in the hot path). Pydantic is used
    only for the static schema echo (`canonical_schema()`).
  • Reports drift: returns a list of warnings the receiver logs loudly, so
    silent drift becomes a visible alarm.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

_log = logging.getLogger("cis_contract")

SCHEMA_VERSION = "1.0"

# Canonical pillar keys
PILLARS = ("F", "M", "O", "S", "A")

# Accepted aliases for each canonical pillar (lowercased lookups).
# NB: On-chain/Risk-Adjusted pillar travels as O canonically but the engine
# emits it as `r` (Risk-Adjusted) — both map to O.
_PILLAR_ALIASES = {
    "F": ("f", "pillar_f", "fundamental"),
    "M": ("m", "pillar_m", "momentum"),
    "O": ("o", "r", "pillar_o", "pillar_r", "onchain", "risk_adjusted", "risk-adjusted"),
    "S": ("s", "pillar_s", "sentiment", "sensitivity"),
    "A": ("a", "pillar_a", "alpha"),
}

_VALID_GRADES  = {"A+", "A", "B+", "B", "C+", "C", "D", "F"}
_VALID_SIGNALS = {
    "STRONG OUTPERFORM", "OUTPERFORM", "NEUTRAL", "UNDERPERFORM", "UNDERWEIGHT",
}

# Compliance safety net (CLAUDE.md rule #1 + compliance-language skill).
# CometCloud holds no 投顾 license — buy/sell/hold language must never reach
# users. The engine should emit positioning-only signals, but if a
# non-compliant term leaks through (observed live: MANTLE "HOLD"), the boundary
# rewrites it using the documented substitution table. Anything unmapped falls
# back to NEUTRAL with a loud warning — losing a directional read on a malformed
# signal is acceptable; a compliance breach is not.
_SIGNAL_REMAP = {
    "HOLD":        "NEUTRAL",
    "BUY":         "OUTPERFORM",
    "STRONG BUY":  "STRONG OUTPERFORM",
    "ACCUMULATE":  "OUTPERFORM",
    "ADD":         "OUTPERFORM",
    "SELL":        "UNDERPERFORM",
    "STRONG SELL": "UNDERWEIGHT",
    "REDUCE":      "UNDERWEIGHT",
    "AVOID":       "UNDERWEIGHT",
}


def _to_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
        return f if f == f else None  # drop NaN
    except (TypeError, ValueError):
        return None


def _canon_data_tier(asset_tier: Any, top_level_tier: Any) -> str:
    """
    Canonicalize to 'T1' / 'T2'. Accepts per-asset int 1/2, str 'T1'/'T2'/'1',
    or falls back to a top-level payload data_tier. Default 'T2'.
    """
    for raw in (asset_tier, top_level_tier):
        if raw is None:
            continue
        s = str(raw).strip().upper()
        if s in ("T1", "1", "TIER1", "TIER 1"):
            return "T1"
        if s in ("T2", "2", "TIER2", "TIER 2"):
            return "T2"
    return "T2"


def _extract_pillars(asset: dict) -> dict:
    """
    Build canonical nested pillars {F,M,O,S,A}. Prefers an explicit nested
    `pillars` dict but fills any missing/None canonical key from flat aliases
    — this is what recovers O from the engine's `r`.
    """
    out: dict[str, float | None] = {k: None for k in PILLARS}
    nested = asset.get("pillars")
    if isinstance(nested, dict):
        for k in PILLARS:
            if k in nested:
                out[k] = _to_float(nested[k])
            elif k.lower() in nested:
                out[k] = _to_float(nested[k.lower()])
    # Lowercased flat view of the whole asset for alias lookup
    flat = {str(k).lower(): v for k, v in asset.items()}
    for canon in PILLARS:
        if out[canon] is None:
            for alias in _PILLAR_ALIASES[canon]:
                if alias in flat and flat[alias] is not None:
                    val = _to_float(flat[alias])
                    if val is not None:
                        out[canon] = val
                        break
    return out


def _normalize_asset(asset: dict, top_level_tier: Any) -> tuple[dict | None, list[str]]:
    """Return (canonical_asset, warnings) or (None, warnings) if unusable."""
    warns: list[str] = []
    symbol = (asset.get("symbol") or asset.get("asset") or "").upper().strip()
    if not symbol:
        return None, ["asset dropped: no symbol"]

    score = _to_float(asset.get("cis_score"))
    if score is None:
        score = _to_float(asset.get("score"))
    raw = _to_float(asset.get("raw_cis_score"))
    if raw is None:
        raw = score

    grade = (asset.get("grade") or "").strip()
    if grade and grade not in _VALID_GRADES:
        warns.append(f"{symbol}: unknown grade '{grade}'")

    signal = (asset.get("signal") or "").strip().upper()
    if signal and signal not in _VALID_SIGNALS:
        if signal in _SIGNAL_REMAP:
            warns.append(f"{symbol}: COMPLIANCE remap signal '{signal}' -> '{_SIGNAL_REMAP[signal]}'")
            signal = _SIGNAL_REMAP[signal]
        else:
            warns.append(f"{symbol}: COMPLIANCE non-compliant signal '{signal}' -> 'NEUTRAL'")
            signal = "NEUTRAL"

    pillars = _extract_pillars(asset)
    if pillars["O"] is None and (
        "r" in {k.lower() for k in asset} or isinstance(asset.get("pillars"), dict)
    ):
        warns.append(f"{symbol}: O pillar unresolved")

    data_tier = _canon_data_tier(asset.get("data_tier"), top_level_tier)

    # OVERLAY onto a copy of the original asset — this preserves every display
    # field downstream consumers read (price, market_cap, volume_24h, tvl,
    # change_24h, etc.) and, crucially, keeps the ORIGINAL `data_tier` value/type
    # so the live /api/v1/cis/universe merge (which compares `data_tier == 1`)
    # is not disturbed. We only fix what's broken and add canonical mirrors.
    canon = dict(asset)
    canon["symbol"]        = symbol
    canon["asset_name"]    = asset.get("asset_name") or asset.get("name") or ""
    canon["cis_score"]     = score
    canon["raw_cis_score"] = raw
    canon["grade"]         = grade or None
    canon["signal"]        = signal or None
    canon["asset_class"]   = asset.get("asset_class") or asset.get("class") or ""
    # canonical nested pillars with O recovered from r/o — overwrites a broken
    # pillars dict that had O=None
    canon["pillars"]       = pillars
    canon["pillar_f"]      = pillars["F"]
    canon["pillar_m"]      = pillars["M"]
    canon["pillar_o"]      = pillars["O"]
    canon["pillar_s"]      = pillars["S"]
    canon["pillar_a"]      = pillars["A"]
    # canonical tier label ("T1"/"T2") WITHOUT clobbering the original
    # `data_tier` (kept for merge compat). Persistence layers use this.
    canon["data_tier_label"] = data_tier
    if canon.get("confidence") is None:
        canon["confidence"] = 1.0 if data_tier == "T1" else 0.8
    return canon, warns


def normalize_cis_payload(payload: dict) -> dict:
    """
    Normalize a raw /internal/cis-scores payload to canonical v1.

    Returns:
      {
        "schema_version": str,          # as received ("legacy" if absent)
        "version_ok": bool,             # matches SCHEMA_VERSION
        "pushed_at": str (ISO),
        "model": str | None,
        "provenance": {engine_git_sha, config_hash, host},
        "macro": {regime, ...},
        "macro_regime": str | None,
        "universe": [canonical asset, ...],
        "warnings": [str, ...],         # drift signals — caller should log loud
        "counts": {"received": n, "normalized": m, "dropped": k, "t1": x, "t2": y},
      }
    """
    warnings: list[str] = []

    raw_universe = payload.get("universe")
    if raw_universe is None:
        raw_universe = payload.get("assets")  # legacy alias
        if raw_universe is not None:
            warnings.append("payload used legacy key 'assets' (canonical: 'universe')")
    if not isinstance(raw_universe, list):
        raw_universe = []

    schema_version = str(payload.get("schema_version") or "legacy")
    version_ok = schema_version == SCHEMA_VERSION
    if schema_version == "legacy":
        warnings.append(
            "payload missing 'schema_version' — treated as legacy; "
            "Minimax should send schema_version='1.0' (MINIMAX_SYNC §2)"
        )
    elif not version_ok:
        warnings.append(
            f"schema_version '{schema_version}' != expected '{SCHEMA_VERSION}'"
        )

    # pushed_at: accept ISO or epoch (int/float) under several legacy keys
    pushed_raw = (
        payload.get("pushed_at") or payload.get("timestamp")
        or payload.get("push_timestamp")
    )
    pushed_at = _canon_timestamp(pushed_raw)

    macro = payload.get("macro") or {}
    if not isinstance(macro, dict):
        macro = {}
    macro_regime = payload.get("macro_regime") or macro.get("regime")
    if macro_regime and not macro.get("regime"):
        macro = {**macro, "regime": macro_regime}

    provenance = payload.get("provenance") or {}
    if not isinstance(provenance, dict):
        provenance = {}
    prov = {
        "engine_git_sha": provenance.get("engine_git_sha") or payload.get("engine_version"),
        "config_hash":    provenance.get("config_hash"),
        "host":           provenance.get("host"),
    }
    if not any(prov.values()):
        warnings.append("payload missing 'provenance' — cannot trace which Mac Mini build produced these scores")

    top_level_tier = payload.get("data_tier")

    universe: list[dict] = []
    dropped = 0
    for a in raw_universe:
        if not isinstance(a, dict):
            dropped += 1
            continue
        canon, w = _normalize_asset(a, top_level_tier)
        warnings.extend(w)
        if canon is None:
            dropped += 1
        else:
            universe.append(canon)

    t1 = sum(1 for a in universe if a.get("data_tier_label") == "T1")
    t2 = len(universe) - t1

    # Deduplicate noisy per-asset warnings while keeping order
    seen = set()
    deduped = [w for w in warnings if not (w in seen or seen.add(w))]

    return {
        "schema_version": schema_version,
        "version_ok":     version_ok,
        "pushed_at":      pushed_at,
        "model":          payload.get("model"),
        "provenance":     prov,
        "macro":          macro,
        "macro_regime":   macro_regime,
        "universe":       universe,
        "warnings":       deduped,
        "counts": {
            "received":   len(raw_universe),
            "normalized": len(universe),
            "dropped":    dropped,
            "t1":         t1,
            "t2":         t2,
        },
    }


def _canon_timestamp(raw: Any) -> str:
    """ISO-8601 UTC string from ISO str or epoch (s or ms)."""
    if raw is None:
        return datetime.now(timezone.utc).isoformat()
    if isinstance(raw, (int, float)):
        ts = float(raw)
        if ts > 1e12:   # milliseconds
            ts /= 1000.0
        try:
            return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
        except Exception:
            return datetime.now(timezone.utc).isoformat()
    return str(raw)


def canonical_schema() -> dict:
    """
    JSON-serializable description of the canonical v1 contract, served by
    GET /internal/cis-scores/schema so Minimax can self-check at runtime
    instead of reading a stale Shadow copy.
    """
    return {
        "schema_version": SCHEMA_VERSION,
        "endpoint": "POST /internal/cis-scores",
        "auth": "X-Internal-Token header (INTERNAL_TOKEN)",
        "required_top_level": ["schema_version", "universe", "pushed_at"],
        "recommended_top_level": ["model", "provenance", "macro", "macro_regime"],
        "provenance_fields": ["engine_git_sha", "config_hash", "host"],
        "asset_fields": {
            "required": ["symbol", "cis_score", "grade", "signal", "asset_class", "data_tier"],
            "pillars": "nested object with keys F, M, O, S, A",
            "optional": [
                "asset_name", "raw_cis_score", "las", "confidence",
                "percentile_rank", "recommended_weight", "class_rank",
                "global_rank", "coingecko_id", "data_quality_score",
                "narrative", "narrative_source", "executability",
            ],
            "narrative": "optional two-sentence LLM scorecard note (compliance-safe, "
                         "positioning language only). If absent, the API fills a "
                         "deterministic fallback from the pillars.",
            "executability": "optional order-book-derived liquidity block "
                             "{spread_bps, slippage_curve, max_notional_at, source: "
                             "'macmini_orderbook'}. If absent, the API fills a "
                             "square-root-impact estimate from 24h volume.",
        },
        "accepted_legacy_aliases": {
            "universe": ["assets"],
            "pushed_at": ["timestamp", "push_timestamp (epoch ms)"],
            "data_tier": ["int 1/2", "top-level data_tier"],
            "pillars": ["flat f/m/r/s/a (r->O)", "pillar_f/.../pillar_a"],
        },
        "enums": {
            "grade": sorted(_VALID_GRADES),
            "signal": sorted(_VALID_SIGNALS),
        },
    }
