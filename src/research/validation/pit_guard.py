"""
Point-in-Time Guard — temporal-leakage protection for LLM-derived features (Seth, 2026-07-18).
================================================================================================
Ben Wellington (Two Sigma, TWIML #736) names the sharpest risk for an LLM-heavy shop like ours:
a pretrained model SMUGGLES THE FUTURE into a point-in-time backtest. Ask an LLM "is Enron healthy?"
as of 2000 and it already "knows" Enron collapsed in 2001 — its parametric memory contaminates the
feature. No amount of clean input fixes this if the model's world-knowledge postdates the signal.

This guard runs four checks on any LLM-derived feature BEFORE its backtest is trusted:

  1. MODEL-CUTOFF        — the model's knowledge cutoff must predate the earliest signal date, OR the
                           feature must be provably input-only (no parametric world-knowledge used).
  2. INPUT-TIMESTAMP     — every document/datum fed to the model is timestamped ≤ the signal date.
  3. ANACHRONISM-SCAN    — the model's OUTPUT must not reference events/years after the signal date.
  4. ANONYMIZATION-PROBE — ★ Wellington's Enron test, mechanized: run the feature with the entity
                           named vs masked. If the score MOVES, the model is leaning on its memory of
                           the entity's future, not the provided point-in-time data → LEAKAGE.

The anonymization probe is the load-bearing one: it catches parametric leakage even when the inputs
are clean and the model claims no anachronism. Compliance: research/validation tooling.
"""
from __future__ import annotations

import datetime as _dt
import difflib
import re

_T_DATE = _dt.date


# ── 1. model knowledge cutoff ────────────────────────────────────────────────
def check_model_cutoff(model_cutoff: _T_DATE, earliest_signal_date: _T_DATE,
                       input_only: bool = False) -> dict:
    """Parametric world-knowledge is safe only if the model's cutoff predates the earliest signal —
    unless the feature is provably input-only (the model reasons ONLY over provided PIT context)."""
    safe = (model_cutoff < earliest_signal_date) or input_only
    return {"check": "model_cutoff", "passed": bool(safe),
            "model_cutoff": str(model_cutoff), "earliest_signal": str(earliest_signal_date),
            "detail": ("input-only feature — parametric memory not used" if input_only and model_cutoff >= earliest_signal_date
                       else "model knowledge predates signals — safe" if safe
                       else "⛔ MODEL CUTOFF POSTDATES SIGNALS — parametric memory is contaminated; make the feature "
                            "input-only or use a model whose cutoff predates the backtest window")}


# ── 2. input timestamps ──────────────────────────────────────────────────────
def check_input_timestamps(items: list[tuple], signal_date: _T_DATE) -> dict:
    """items: list of (id, timestamp_date). Every input must be ≤ the signal date (no look-ahead)."""
    viol = [i for (i, ts) in items if ts > signal_date]
    return {"check": "input_timestamps", "passed": not viol, "n_inputs": len(items),
            "violations": viol,
            "detail": "all inputs ≤ signal date" if not viol else f"⛔ {len(viol)} input(s) postdate the signal date"}


# ── 3. anachronism scan ──────────────────────────────────────────────────────
def anachronism_scan(output_text: str, signal_date: _T_DATE, future_terms: list[str] | None = None) -> dict:
    """Scan the model's OUTPUT for references to years after the signal date (and optional known-future
    terms). A feature that 'explains' a name using post-date facts has smuggled the future in."""
    yrs = [int(y) for y in re.findall(r"\b(?:19|20)\d{2}\b", output_text or "")]
    future_yrs = sorted({y for y in yrs if y > signal_date.year})
    hit_terms = [t for t in (future_terms or []) if t.lower() in (output_text or "").lower()]
    ok = not future_yrs and not hit_terms
    return {"check": "anachronism", "passed": ok, "future_years": future_yrs, "future_terms": hit_terms,
            "detail": "no future references" if ok else "⛔ output references facts after the signal date"}


# ── 4. ★ anonymization probe (Wellington's Enron test, mechanized) ────────────
def anonymization_probe(feature_fn, inputs: str, entity_name: str,
                        placeholder: str = "ENTITY_X", num_threshold: float = 0.15,
                        text_sim_floor: float = 0.6) -> dict:
    """Run the feature with the entity NAMED vs MASKED. If the output moves materially, the model is
    using its memory of the entity (its future), not the provided PIT data → parametric LEAKAGE.

    feature_fn: callable(input_text) -> float | str. Numeric → compare |Δ| vs num_threshold;
                text → compare difflib similarity vs text_sim_floor.
    """
    named = feature_fn(inputs)
    masked_inputs = re.sub(re.escape(entity_name), placeholder, inputs, flags=re.IGNORECASE)
    masked = feature_fn(masked_inputs)

    if isinstance(named, (int, float)) and isinstance(masked, (int, float)):
        delta = abs(float(named) - float(masked))
        leaked = delta > num_threshold
        metric = {"named": round(float(named), 4), "masked": round(float(masked), 4), "abs_delta": round(delta, 4),
                  "threshold": num_threshold}
    else:
        sim = difflib.SequenceMatcher(None, str(named), str(masked)).ratio()
        leaked = sim < text_sim_floor
        metric = {"similarity": round(sim, 3), "floor": text_sim_floor}
    return {"check": "anonymization_probe", "passed": not leaked, **metric,
            "detail": ("⛔ parametric leakage — the feature depends on KNOWING the entity, not the PIT data"
                       if leaked else "feature driven by provided data, not entity memory")}


# ── aggregate audit ──────────────────────────────────────────────────────────
def pit_audit(checks: list[dict]) -> dict:
    """Aggregate the individual checks into one verdict. ANY failure ⇒ the feature is NOT PIT-safe."""
    failed = [c["check"] for c in checks if not c.get("passed")]
    return {"pit_safe": not failed, "failed_checks": failed, "checks": checks,
            "verdict": "PIT-SAFE — no temporal leakage detected" if not failed
                       else f"⛔ NOT PIT-SAFE — leakage via: {', '.join(failed)}. Do NOT trust this feature's backtest."}


if __name__ == "__main__":
    import json
    sig = _dt.date(2000, 6, 30)

    # mock LLM feature: a health score. The LEAKY one "remembers" Enron is doomed (parametric memory);
    # the SAFE one reads only the provided margin number.
    def leaky_health(text: str) -> float:
        return 0.10 if "enron" in text.lower() else 0.60          # score collapses only when it SEES the name
    def safe_health(text: str) -> float:
        m = re.search(r"margin=([0-9.]+)", text)                  # reasons only over provided PIT data
        return float(m.group(1)) if m else 0.5

    doc = "Company Enron Q2 filing: margin=0.55, revenue growing."
    print("LEAKY feature:")
    print(json.dumps(pit_audit([
        check_model_cutoff(_dt.date(2024, 1, 1), sig),                       # modern model, cutoff >> 2000
        check_input_timestamps([("filing", _dt.date(2000, 5, 1))], sig),
        anachronism_scan("Enron looks fine as of this filing.", sig),
        anonymization_probe(leaky_health, doc, "Enron"),
    ]), indent=2))

    print("\nSAFE feature (input-only, same modern model):")
    print(json.dumps(pit_audit([
        check_model_cutoff(_dt.date(2024, 1, 1), sig, input_only=True),
        check_input_timestamps([("filing", _dt.date(2000, 5, 1))], sig),
        anachronism_scan("Margin is 0.55 as provided.", sig),
        anonymization_probe(safe_health, doc, "Enron"),
    ]), indent=2))
