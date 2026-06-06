"""
Per-asset CIS narrative — a short, compliance-safe "why this grade" explanation
shown on the asset cards (leaderboard, radar, widget, mobile).

Source priority (resolved in cis.py):
  1. LLM narrative pushed by the Mac Mini (LM Studio / Gemma) — richer prose.
  2. This deterministic generator — always available, zero-cost, compliance-safe.

The deterministic path is the never-blank floor: when LM Studio is down (it is
resource-constrained and frequently OOMs), the cards still show a meaningful
two-sentence read derived from the pillar breakdown. The moment the engine
pushes an LLM `narrative`, that takes over automatically.

Compliance (CLAUDE.md rule #1): positioning language only — never buy/sell/hold.
"""
from __future__ import annotations

from typing import Any

# Pillar display names + phrasings by strength band.
_PILLAR_NAME = {
    "F": "fundamentals",
    "M": "momentum",
    "O": "risk-adjusted profile",
    "S": "sentiment",
    "A": "relative alpha",
}
_STRONG = {
    "F": "solid fundamentals",
    "M": "strong momentum",
    "O": "a clean risk-adjusted profile",
    "S": "constructive sentiment",
    "A": "strong relative alpha",
}
_WEAK = {
    "F": "soft fundamentals",
    "M": "fading momentum",
    "O": "elevated risk",
    "S": "weak sentiment",
    "A": "lagging alpha",
}

_SIGNAL_PHRASE = {
    "STRONG OUTPERFORM": "screens as a clear outperformer",
    "OUTPERFORM":        "positions to outperform",
    "NEUTRAL":           "screens neutral",
    "UNDERPERFORM":      "positions to underperform",
    "UNDERWEIGHT":       "screens underweight",
}

_REGIME_NOTE = {
    "RISK_ON":     "a risk-on backdrop",
    "RISK_OFF":    "a risk-off backdrop",
    "TIGHTENING":  "a tightening regime",
    "EASING":      "an easing regime",
    "STAGFLATION": "a stagflationary regime",
    "GOLDILOCKS":  "a goldilocks regime",
}


def _pillars(asset: dict) -> dict:
    """Resolve canonical pillar values {F,M,O,S,A} from nested or flat shapes."""
    out: dict[str, float] = {}
    nested = asset.get("pillars") if isinstance(asset.get("pillars"), dict) else {}
    flat = {str(k).lower(): v for k, v in asset.items()}
    alias = {"F": ["f"], "M": ["m"], "O": ["o", "r"], "S": ["s"], "A": ["a"]}
    for k in ("F", "M", "O", "S", "A"):
        v = nested.get(k)
        if v is None:
            v = nested.get(k.lower())
        if v is None:
            for a in alias[k]:
                if flat.get(a) is not None:
                    v = flat[a]
                    break
        try:
            out[k] = float(v) if v is not None else None
        except (TypeError, ValueError):
            out[k] = None
    return out


def build_asset_narrative(asset: dict, regime: str | None = None) -> str:
    """
    Two compliance-safe sentences: sentence 1 = what's driving the grade,
    sentence 2 = the notable tension / caveat.
    """
    sym = (asset.get("symbol") or "").upper() or "This asset"
    grade = asset.get("grade") or ""
    signal = (asset.get("signal") or "").upper()
    reg = (regime or asset.get("macro_regime") or "").upper()

    pil = _pillars(asset)
    present = {k: v for k, v in pil.items() if v is not None}

    sig_phrase = _SIGNAL_PHRASE.get(signal, "screens neutral")
    grade_clause = f"{grade}-grade" if grade else "graded"

    # ── Sentence 1: strengths ────────────────────────────────────────────────
    if present:
        ranked = sorted(present.items(), key=lambda kv: kv[1], reverse=True)
        strong = [k for k, v in ranked if v >= 65][:2]
        if strong:
            strengths = " and ".join(_STRONG[k] for k in strong)
            s1 = f"{sym} {sig_phrase} on {strengths}"
        else:
            # nothing strong — lead with the least-weak pillar, hedged
            top_k, top_v = ranked[0]
            s1 = f"{sym} {sig_phrase}, anchored by its {_PILLAR_NAME[top_k]}"
    else:
        s1 = f"{sym} is {grade_clause} and {sig_phrase}"

    if reg in _REGIME_NOTE:
        s1 += f" in {_REGIME_NOTE[reg]}"
    s1 += "."

    # ── Sentence 2: tension / caveat ─────────────────────────────────────────
    s2 = ""
    if present:
        ranked_asc = sorted(present.items(), key=lambda kv: kv[1])
        weak = [k for k, v in ranked_asc if v <= 45][:2]
        if weak:
            weaknesses = " and ".join(_WEAK[k] for k in weak)
            s2 = f"The {grade_clause} read is tempered by {weaknesses}."
        else:
            # no clear weakness — name the lowest pillar as the watch item
            low_k, low_v = ranked_asc[0]
            s2 = f"The main watch item is its {_PILLAR_NAME[low_k]}."
    if not s2:
        s2 = "Pillar detail is limited, so treat the read as provisional."

    return f"{s1} {s2}"


def attach_narratives(universe: list, regime: str | None = None) -> None:
    """
    Mutate each asset in place: keep an LLM `narrative` if one was pushed,
    otherwise fill the deterministic one. Sets `narrative_source`.
    """
    for a in universe:
        if not isinstance(a, dict):
            continue
        existing = (a.get("narrative") or "").strip()
        if existing:
            a.setdefault("narrative_source", "llm")
        else:
            a["narrative"] = build_asset_narrative(a, regime)
            a["narrative_source"] = "deterministic"
