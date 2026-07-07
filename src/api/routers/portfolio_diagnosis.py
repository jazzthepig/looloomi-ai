"""
Portfolio diagnosis — the product, not a leaderboard.

The thesis (Jazz, 2026-06): we are not a magician promising 500x memecoins. We are
a good assistant that helps an investor capture **beta+** on quality assets, read
through the CIS lens, personalized to what they actually hold. The interaction is a
**diagnosis**: feed in a book (via API, wallet, or an uploaded screenshot the
backend parses) and get back an honest read plus the few moves that tighten it
toward beta+.

This module is the brain — input-agnostic. Holdings come in as
`[{symbol, weight?}]`; the diagnosis is the same however they arrived.

Voice: honest assistant. No hype, no alpha-promises, positioning language only.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter

router = APIRouter()


@router.post("/api/v1/portfolio/diagnose")
async def diagnose(payload: dict):
    """
    One object (your book) + one action (Diagnose).
    Body: {"holdings": [{"symbol": "BTC", "weight": 30}, ...]}  (weight optional)
    Returns an honest, beta+-oriented read of the book + the few moves.
    Same action a human taps and an agent calls.
    """
    from src.api.routers.cis import get_cis_universe
    holdings = payload.get("holdings") or []
    universe = await get_cis_universe()
    band_ctx = None
    try:
        from src.api.routers.signals import compute_current_band
        band_ctx = await compute_current_band()   # for the conviction fusion (timing + executability)
    except Exception:
        band_ctx = None
    return diagnose_portfolio(holdings, universe, band_ctx)

# Grade → bucket. KEEP = institutional quality; WATCH = acceptable; TRIM = below bar.
_KEEP = {"A+", "A", "B+"}
_WATCH = {"B", "C+"}
_GRADE_RANK = {"A+": 8, "A": 7, "B+": 6, "B": 5, "C+": 4, "C": 3, "D": 2, "F": 1}


def _by_symbol(universe: list) -> dict:
    return {(a.get("symbol") or "").upper(): a for a in universe if a.get("symbol")}


def _best_in_class(universe: list, asset_class: str, exclude: set) -> dict | None:
    """Highest-CIS asset in a class, for rotation suggestions."""
    pool = [
        a for a in universe
        if a.get("asset_class") == asset_class
        and (a.get("symbol") or "").upper() not in exclude
        and a.get("grade") in _KEEP
    ]
    if not pool:
        return None
    return max(pool, key=lambda a: a.get("cis_score") or 0)


def diagnose_portfolio(holdings: list[dict], universe_data: dict, band_ctx: dict | None = None) -> dict:
    """
    holdings: [{"symbol": "BTC", "weight": 0.3}, ...]  (weights optional → equal)
    universe_data: the /api/v1/cis/universe response.
    band_ctx: optional current-band read ({current_band, tiers_now}) — enriches each holding
      with the conviction fusion (quality × in-circle × timing × executability), so an illiquid
      B+ name is flagged 'watch, not core' instead of a blind 'keep'.
    Returns an honest, beta+-oriented diagnosis.
    """
    universe = universe_data.get("universe") or []
    regime = universe_data.get("macro_regime") or "—"
    idx = _by_symbol(universe)
    _band = (band_ctx or {}).get("current_band")
    _tiers = (band_ctx or {}).get("tiers_now") or {}
    illiquid_w = 0.0

    # normalize weights
    hs = [{"symbol": (h.get("symbol") or "").upper(),
           "weight": h.get("weight")} for h in holdings if h.get("symbol")]
    if not hs:
        return {"error": "no holdings"}
    if all(h["weight"] is None for h in hs):
        for h in hs:
            h["weight"] = 1.0 / len(hs)
    else:
        tot = sum(h["weight"] or 0 for h in hs) or 1.0
        for h in hs:
            h["weight"] = (h["weight"] or 0) / tot

    rows, keep, watch, trim = [], [], [], []
    wsum_cis, w_with_score, off_standard_w = 0.0, 0.0, 0.0
    held = {h["symbol"] for h in hs}

    for h in hs:
        sym, w = h["symbol"], h["weight"]
        a = idx.get(sym)
        if not a:
            # not in the curated universe → fails the institutional standard
            row = {"symbol": sym, "weight": round(w, 4), "grade": None,
                   "cis": None, "signal": None, "asset_class": None,
                   "bucket": "trim", "reason": "not in the institutional universe (unrated / off-standard)"}
            trim.append(row); off_standard_w += w
        else:
            grade = a.get("grade") or "—"
            cis = a.get("cis_score")
            if isinstance(cis, (int, float)):
                wsum_cis += cis * w; w_with_score += w
            bucket = "keep" if grade in _KEEP else ("watch" if grade in _WATCH else "trim")
            reason = a.get("narrative") or ""
            row = {"symbol": sym, "weight": round(w, 4), "grade": grade,
                   "cis": cis, "signal": a.get("signal"),
                   "asset_class": a.get("asset_class"), "bucket": bucket, "reason": reason}
            if band_ctx:
                try:
                    from src.data.cis.conviction import compute_conviction
                    cv = compute_conviction(a, _tiers, _band)
                    row.update({"conviction": cv["conviction"], "direction": cv["direction"],
                                "conviction_action": cv["action"], "executability": cv["executability"],
                                "in_circle": cv["in_circle"], "season": cv.get("season")})
                    if cv["executability"] in ("illiquid", "thin"):
                        illiquid_w += w
                except Exception:
                    pass
            (keep if bucket == "keep" else watch if bucket == "watch" else trim).append(row)
            if bucket == "trim":
                off_standard_w += w
        rows.append(row)

    avg_cis = round(wsum_cis / w_with_score, 1) if w_with_score else None
    book_grade = next((g for g, r in sorted(_GRADE_RANK.items(), key=lambda x: -x[1])
                       if avg_cis is not None and _cis_to_rank(avg_cis) >= r), "—")

    # The few moves — at most 4, highest-weight problems first.
    moves = []
    for row in sorted(trim, key=lambda r: -r["weight"])[:4]:
        sym = row["symbol"]
        alt = None
        if row.get("asset_class"):
            alt = _best_in_class(universe, row["asset_class"], held)
        # concise, assistant-voice reason
        if row.get("grade"):
            why = f"{row['grade']}, {(row.get('signal') or 'below bar').lower()} in this regime"
        else:
            why = "off-standard — not in the institutional universe"
        if alt:
            moves.append({
                "action": "rotate",
                "from": sym, "to": alt.get("symbol"),
                "detail": f"Rotate {sym} ({why}) → {alt.get('symbol')} "
                          f"({alt.get('grade')}, same class).",
            })
        else:
            moves.append({
                "action": "trim",
                "from": sym,
                "detail": f"Trim {sym} — {why}.",
            })

    # Honest one-line verdict.
    off_pct = round(off_standard_w * 100)
    illiquid_pct = round(illiquid_w * 100)
    if off_pct >= 40:
        verdict = (f"Heavy off-standard exposure: {off_pct}% of the book sits below the "
                   f"institutional bar. The moves below tighten it toward beta+.")
    elif off_pct >= 15:
        verdict = (f"Solid core, but {off_pct}% is off-standard. A few rotations lift the "
                   f"whole book's quality.")
    else:
        verdict = (f"Clean book — {off_pct}% off-standard. Mostly hold; minor tilts only.")
    # Executability is a separate axis from quality: a high-grade book you can't size is a
    # different problem than a low-grade one. Flag it honestly.
    if illiquid_pct >= 20:
        verdict += (f" Note: {illiquid_pct}% sits in illiquid names — quality may be fine but "
                    f"you can't build or exit size cleanly there.")

    return {
        "as_of_regime": regime,
        "current_band": _band,
        "book": {
            "avg_cis": avg_cis,
            "grade": book_grade,
            "off_standard_pct": off_pct,
            "illiquid_pct": illiquid_pct,
            "n_holdings": len(hs),
            "keep": len(keep), "watch": len(watch), "trim": len(trim),
        },
        "verdict": verdict,
        "moves": moves,
        "holdings": rows,
        "note": "Diagnosis is positioning guidance toward enhanced beta, not investment "
                "advice or a promise of returns.",
    }


def _cis_to_rank(cis: float) -> int:
    # mirror the grade thresholds so book_grade matches a single CIS
    if cis >= 85: return 8
    if cis >= 75: return 7
    if cis >= 65: return 6
    if cis >= 55: return 5
    if cis >= 45: return 4
    if cis >= 35: return 3
    if cis >= 25: return 2
    return 1
