"""
Conviction synthesis — Fusion #1 (ARCHITECTURE.md: Diagnose = the one thing).

Every prior layer answers ONE question; nothing fuses them into a single per-asset verdict:
  · CIS raw grade      → is the asset GOOD (regime-neutral quality)?
  · cause_proximity    → are we EARLY (upstream / in-circle) or LATE (出圈 / fragile)?
  · edge map × band    → is the TAPE rewarding this signal tier right NOW? (empirical, own outcomes)
  · executability      → can we actually ACT (liquidity / size)?

`compute_conviction` fuses them into `{conviction 0..1, direction, action, drivers}`. It is
ANCHORED on the empirical edge map (expected 30d alpha for this tier × current band — a real
outcome, not an invented weight), then tilted by the asset's own quality, in-circle-ness, and
executability. Honest by construction: a thin edge cell → low conviction; an illiquid name →
discounted no matter how high its grade. Compliance-safe: positioning language only.
"""
from __future__ import annotations


def _clamp(x, lo, hi):
    return max(lo, min(hi, x))


def _num(x, default=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


_CONVICTION_SCALE = 8.0   # |adjusted 30d alpha %| that maps to full conviction (1.0)
_DIR_THRESHOLD = 1.0      # |adjusted alpha %| below this → neutral (no actionable edge)
# Forward-supply (the UPSTREAM cause): maximal forced-dilution overhang shifts the signed edge
# down by this many alpha-points — bearish, so it trims a long and strengthens a short. This is
# the one factor that is a cause (a decision already made), not a reflection of price. Calibratable.
_FS_WEIGHT = 6.0
# Positioning (upstream cause #2, reflexive): signed leverage pressure shifts the edge — a bullish
# squeeze setup (+) adds, a bearish long-liquidation setup (−) subtracts. Faster-moving than supply.
_POS_WEIGHT = 5.0


def _exec_factor(ex: dict) -> tuple[float, str]:
    """0.3..1.0 tradeability multiplier + a tier label. An asset we can't put size on is
    discounted hard regardless of grade (the illiquidity a grade alone hides)."""
    if not isinstance(ex, dict):
        return 0.6, "unknown"
    tier = (ex.get("liquidity_tier") or "").lower()
    base = {"liquid": 1.0, "deep": 1.0, "moderate": 0.75, "mid": 0.75,
            "thin": 0.5, "illiquid": 0.4}.get(tier, 0.6)
    mn = _num(ex.get("max_notional_50bps_usd")) or _num(ex.get("max_notional_25bps_usd"))
    if mn <= 0 and tier in ("illiquid", "thin", ""):
        base = min(base, 0.35)   # literally can't size → hard discount
    return base, (tier or "unknown")


def compute_conviction(asset: dict, band_tiers: dict, current_band: str) -> dict:
    """Fuse one asset into a conviction verdict for the CURRENT band.
    band_tiers: {signal: {avg_alpha_pct, alpha_win_pct, n}} for the live band (from the edge map).
    """
    sym = (asset.get("symbol") or asset.get("asset_id") or "").upper()
    grade = asset.get("grade") or "—"
    signal = str(asset.get("signal") or "").strip().upper()
    quality = _num(asset.get("raw_cis_score") or asset.get("cis_score"))
    cp = asset.get("cause_proximity") or {}
    fragility = _clamp(_num(cp.get("risk_score")), 0.0, 1.0)
    in_circle = round(1.0 - fragility, 3)
    season = cp.get("season")
    stage = cp.get("stage")
    ex_factor, liq_tier = _exec_factor(asset.get("executability") or {})

    # ── empirical anchor: this tier's expected 30d alpha in the current band ──
    # `avg_alpha_pct` is EB-SHRUNK upstream (thin cells pulled to the structural prior), so it's
    # usable regardless of raw n — the sample size feeds CONFIDENCE, not a hard discard.
    cell = (band_tiers or {}).get(signal) or {}
    edge = cell.get("avg_alpha_pct")
    edge_n = int(cell.get("n") or 0)
    edge_known = edge is not None

    # ── asset-specific tilts (multipliers around 1.0) ──
    q_mult = 0.70 + 0.60 * _clamp(quality / 100.0, 0.0, 1.0)   # 0.70 (F) .. 1.30 (A+)
    p_mult = 0.60 + 0.80 * in_circle                            # 0.60 (out-of-circle) .. 1.40 (upstream)

    drivers = []
    if edge_known:
        adjusted = edge * q_mult * p_mult * ex_factor
        basis = "edge_map"
    else:
        # no trustworthy edge cell → fall back to quality-only conviction (flagged), timing-agnostic
        adjusted = (quality - 55.0) / 5.0 * p_mult * ex_factor   # ~ +/- per grade-notch above/below B
        basis = "quality_fallback"
        drivers.append(f"thin edge cell (n={edge_n}) — conviction from quality, not timing")

    # ── UPSTREAM CAUSE: forward supply overhang (known forced dilution) — bearish directional ──
    fs = _clamp(_num((asset.get("forward_supply") or {}).get("forward_supply_risk")), 0.0, 1.0)
    if fs > 0:
        adjusted = round(adjusted - _FS_WEIGHT * fs, 3)   # shift signed edge DOWN (trim long / boost short)
    pos = _clamp(_num((asset.get("positioning") or {}).get("positioning_pressure")), -1.0, 1.0)
    if pos:
        adjusted = round(adjusted + _POS_WEIGHT * pos, 3)  # + squeeze (bullish) / − long-liq (bearish)

    # direction + magnitude
    if adjusted >= _DIR_THRESHOLD:
        direction = "long"
    elif adjusted <= -_DIR_THRESHOLD:
        direction = "short"
    else:
        direction = "neutral"
    conviction = round(_clamp(abs(adjusted) / _CONVICTION_SCALE, 0.0, 1.0), 3)

    # confidence = weakest link (cause-proximity source, edge sample, executability)
    cp_conf = _num(cp.get("confidence"), 0.4)
    ex_conf = _num((asset.get("executability") or {}).get("confidence"), 0.6)
    n_conf = _clamp(edge_n / 100.0, 0.0, 1.0) if edge_known else 0.3
    confidence = round(min(cp_conf, ex_conf, 0.4 + 0.6 * n_conf), 2)

    # ── drivers (why) ──
    if quality >= 65:
        drivers.append(f"quality {grade} (raw {quality:.0f}) — upstream grade")
    elif quality < 45:
        drivers.append(f"weak quality {grade} (raw {quality:.0f})")
    if in_circle >= 0.7:
        drivers.append("in-circle / upstream — marginal buyer not yet exhausted")
    elif fragility >= 0.6:
        drivers.append("out-of-circle — diffused to the crowd, fragile")
    if season in ("momentum", "dry_up", "spring_test", "early_markup", "capitulation"):
        drivers.append(f"{season} season — accumulation/opportunity window")
    elif season == "stale":
        drivers.append("stale — post-出圈 window closed")
    if liq_tier in ("illiquid", "thin"):
        drivers.append(f"{liq_tier} — cannot size; conviction discounted")
    if fs >= 0.3:
        drivers.insert(0, f"UPSTREAM: {fs:.0%} forward-supply overhang — known dilution ahead (bearish)")
    if abs(pos) >= 0.5:
        drivers.insert(0, f"UPSTREAM: leverage {'squeeze setup (bullish)' if pos > 0 else 'long-liquidation setup (bearish)'} (pos {pos:+.2f})")
    if edge_known:
        drivers.append(f"{signal} tier in {current_band}: {edge:+.1f}% expected 30d alpha (n={edge_n})")

    action = _action(direction, conviction, liq_tier)

    return {
        "symbol": sym, "name": asset.get("name"), "asset_class": asset.get("asset_class"),
        "grade": grade, "signal": signal, "current_band": current_band,
        "quality_score": round(quality, 1),
        "in_circle": in_circle, "season": season, "stage": stage,
        "forward_supply_risk": round(fs, 3),
        "positioning_pressure": round(pos, 3),
        "expected_edge_pct": edge if edge_known else None,
        "adjusted_edge_pct": round(adjusted, 2),
        "executability": liq_tier,
        "conviction": conviction, "direction": direction,
        "confidence": confidence, "basis": basis,
        "action": action, "drivers": drivers[:5],
    }


def _action(direction: str, conviction: float, liq_tier: str) -> str:
    if liq_tier in ("illiquid", "thin") and direction == "long":
        return "quality present but not sizeable — watch, not a core overweight (illiquid)"
    if direction == "long":
        if conviction >= 0.6:
            return "high-conviction OVERWEIGHT candidate — upstream quality + favorable tape"
        if conviction >= 0.3:
            return "constructive — modest OVERWEIGHT tilt"
        return "mild positive lean — small tilt at most"
    if direction == "short":
        if conviction >= 0.6:
            return "high-conviction UNDERWEIGHT — weak quality and/or unfavorable tape"
        if conviction >= 0.3:
            return "UNDERWEIGHT tilt"
        return "mild negative lean"
    return "NEUTRAL — no actionable edge in the current tape; benchmark weight"


def rank_universe(universe: list, band_tiers: dict, current_band: str) -> list:
    """Conviction for every asset, sorted by signed edge (best longs first, best shorts last)."""
    rows = []
    for a in universe:
        if not isinstance(a, dict):
            continue
        try:
            rows.append(compute_conviction(a, band_tiers, current_band))
        except Exception:
            continue
    rows.sort(key=lambda r: r.get("adjusted_edge_pct", 0.0), reverse=True)
    return rows


_MAX_NAME_FRAC = 0.22   # risk limit: no single name > 22% of its side's gross (assessment W3)


def _capped_weights(convs: dict, budget: float, cap: float) -> dict:
    """Water-fill conviction → weights with a hard per-name cap. Names that would breach `cap`
    are pinned there and the remaining budget re-proportions among the rest; if capacity
    (n × cap) < budget the book stays UNDER-deployed (honest — thin breadth ⇒ smaller gross,
    never over-concentrated). All inputs positive; returns positive weights."""
    out: dict = {}
    active = {s: c for s, c in convs.items() if c > 0}
    b = budget
    for _ in range(len(active) + 1):
        if not active or b <= 1e-9:
            break
        tot = sum(active.values())
        prop = {s: b * c / tot for s, c in active.items()}
        over = [s for s, w in prop.items() if w >= cap - 1e-12]
        if not over:
            for s, w in prop.items():
                out[s] = round(w, 4)
            break
        for s in over:
            out[s] = round(cap, 4)
            b -= cap
            del active[s]
    return out


def conviction_book(universe: list, band_tiers: dict, current_band: str,
                    shorts_ok: bool = False, gross: float = 1.0,
                    max_names: int = 15, min_conviction: float = 0.15,
                    short_budget_frac: float = 0.5) -> dict:
    """The strategy as the kernel's OUTPUT — a signed target book {SYMBOL: weight}.

    This is what the paper sleeve trades: not the narrow risk-meter weighting, but the full
    conviction (reflection + 出圈 + forward-supply + positioning + executability). The named
    plays fall out of it for free — a high forward-supply name lands as a conviction SHORT
    (the forced-seller short), a quality crowded-short lands as a conviction LONG (the squeeze).
    Untradeable (illiquid/thin) names are dropped — we never target size we can't put on.

    shorts_ok gates the short book on regime (only true falling-market regimes). gross is the
    long budget; shorts get `short_budget_frac × gross`. Weights ∝ conviction, top `max_names` a side.
    """
    rows = rank_universe(universe, band_tiers, current_band)
    tradeable = [r for r in rows if r.get("executability") not in ("illiquid", "thin")
                 and r.get("conviction", 0) >= min_conviction]
    longs = [r for r in tradeable if r["direction"] == "long"][:max_names]
    shorts = ([r for r in tradeable if r["direction"] == "short"][:max_names] if shorts_ok else [])

    book: dict = {}
    long_conv = {r["symbol"]: r["conviction"] for r in longs}
    for s, w in _capped_weights(long_conv, gross, _MAX_NAME_FRAC * gross).items():
        book[s] = w
    if shorts:
        sbudget = gross * short_budget_frac
        short_conv = {r["symbol"]: r["conviction"] for r in shorts}
        for s, w in _capped_weights(short_conv, sbudget, _MAX_NAME_FRAC * sbudget).items():
            book[s] = -w
    return book
