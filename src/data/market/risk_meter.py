"""
Risk Meter — the judgment→behavior link. Turns the per-asset cause-proximity (出圈)
signal into actual position sizing, and reads the whole book's out-of-circle fragility.

This is the LIVE sizing layer, deliberately separate from the historical backtest
(`scripts/rebalance_engine.py`). Cause-proximity (D4 attention, D3 holders) is a
FORWARD signal with no backtestable history — using it in a historical backtest would
be look-ahead. So the backtest stays grade-only (validated, honest), and the Risk Meter
applies the out-of-circle haircut on top of the *current* live state only.

Thesis (ARCHITECTURE 大象无形, METHODOLOGY_CORE §3): two assets with the same CIS grade
are NOT equally safe to hold. The one whose consensus has diffused out-of-circle (mass
retail arrived, marginal buyer exhausted) is fragile — trim it. The one still upstream
(concentrated, in-circle) earns its full conviction weight. beta+ comes from being closer
to the cause, not from the reflection.

  meter_adjusted_weights(universe, regime) → grade-driven weights, then:
    long  factor ×= (1 − HAIRCUT · risk · confidence)     # de-risk crowded/late longs
    short factor ×= (1 + SHORT_BOOST · risk · confidence)  # a weak asset that just went
                                                            # out-of-circle confirms the short
  portfolio_risk_meter(weights, universe) → one 0..1 needle = weighted out-of-circle
    fragility of the long book + the top holdings dragging it.

Weights are recomputed from current state every call — never a frozen rule.
"""
from __future__ import annotations

# Grade → long weight factor (mirrors rebalance_engine; kept local so this module is
# importable on Railway without the script's /Volumes paths).
GRADE_FACTOR = {"A+": 1.5, "A": 1.2, "B+": 1.0, "B": 0.7, "C+": 0.4, "C": 0.2, "D": 0.0, "F": 0.0}
SHORT_GRADE_FACTOR = {"A+": 0.0, "A": 0.0, "B+": 0.0, "B": 0.0, "C+": 0.2, "C": 0.4, "D": 0.6, "F": 0.6}
REGIME_FACTOR = {
    "Risk-On": 1.00, "Goldilocks": 1.00, "Easing": 1.00, "Neutral": 0.80,
    "Risk-Off": 0.50, "Tightening": 0.50, "Stagflation": 0.50,
}
MAX_SHORT_PCT = 0.30

HAIRCUT = 0.60        # out-of-circle risk trims up to 60% of a long weight (× confidence)
SHORT_BOOST = 0.30    # out-of-circle risk on a weak name boosts the short up to +30%

# Conviction tilt — grounded in the 30-day benchmark-relative track record
# (signal_track_record / TRACK_RECORD_2026-07-01.md): STRONG OUTPERFORM delivered ~+3.3%
# alpha, plain OUTPERFORM was ~flat/negative. So we size UP the proven top-conviction tier
# and UNDERWEIGHT the broad tier. A TILT, not a gate (CIS is never a hard gate) — plain
# OUTPERFORM is reduced, not zeroed; unknown signal degrades to 1.0 (grade-only behavior).
CONVICTION_FACTOR = {
    "STRONG OUTPERFORM": 1.30,
    "OUTPERFORM":        0.60,
    "NEUTRAL":           0.35,
    "UNDERPERFORM":      0.0,
    "UNDERWEIGHT":       0.0,
}

CONVICTION_MIN_N = 50    # need this many resolved outcomes in a tier before the data overrides the prior
_RISK_OFF = {"Risk-Off", "Tightening", "Stagflation"}


def _conviction_of(a: dict, factors: dict | None = None) -> float:
    sig = str(a.get("signal") or "").strip().upper()
    return (factors or CONVICTION_FACTOR).get(sig, 1.0)


def conviction_from_track_record(rows: list) -> dict:
    """Derive per-signal conviction factors from the latest signal_track_record batch —
    the SELF-TUNING step. Guardrails so a noisy window can't run the book:
      - only override the hardcoded prior when a tier has ≥ CONVICTION_MIN_N resolved outcomes
      - blend win-rate (vs 50% coin-flip) with avg alpha, then CLAMP to [0.2, 1.5]
    Returns the prior with data-backed tiers overwritten. Empty/short data → pure prior."""
    factors = dict(CONVICTION_FACTOR)
    if not rows:
        return factors
    agg: dict = {}
    for r in rows:
        try:
            sig = str(r.get("signal") or "").strip().upper()
            n = int(r.get("n") or 0)
            if not sig or n <= 0:
                continue
            a = float(r.get("avg_alpha_pct") or 0.0)
            w = float(r.get("alpha_win_pct") or 0.0)
            t = agg.setdefault(sig, {"n": 0, "aw": 0.0, "ww": 0.0})
            t["n"] += n; t["aw"] += a * n; t["ww"] += w * n
        except (TypeError, ValueError):
            continue
    for sig, t in agg.items():
        if t["n"] < CONVICTION_MIN_N:
            continue
        avg_alpha = t["aw"] / t["n"]
        avg_win = t["ww"] / t["n"]
        # win/50 = above/below coin-flip on beating benchmark; alpha adds magnitude
        dc = (avg_win / 50.0) * (1.0 + avg_alpha * 0.08)
        factors[sig] = round(max(0.2, min(1.5, dc)), 3)
    return factors


def _norm_regime(r: str | None) -> str:
    if not r:
        return "Neutral"
    s = str(r).strip().upper().replace("_", "-").replace(" ", "-")
    return {
        "RISK-ON": "Risk-On", "GOLDILOCKS": "Goldilocks", "EASING": "Easing",
        "NEUTRAL": "Neutral", "RISK-OFF": "Risk-Off", "TIGHTENING": "Tightening",
        "STAGFLATION": "Stagflation",
    }.get(s, "Neutral")


def _grade_of(a: dict) -> str:
    g = a.get("grade") or a.get("cis_grade") or ""
    return str(g).strip()


def _risk_conf(a: dict) -> tuple[float, float]:
    """(out_of_circle_risk_score, confidence) from the asset's cause_proximity block."""
    cp = a.get("cause_proximity") or {}
    try:
        risk = float(cp.get("risk_score") or 0.0)
    except (TypeError, ValueError):
        risk = 0.0
    try:
        conf = float(cp.get("confidence") or 0.0)
    except (TypeError, ValueError):
        conf = 0.0
    return max(0.0, min(1.0, risk)), max(0.0, min(1.0, conf))


def meter_adjusted_weights(universe: list, regime: str | None = None, conviction_override: dict | None = None) -> dict:
    """
    Signed target weights from current CIS grade, de-risked by cause-proximity.
    Returns {symbol: {raw_weight, meter_weight, grade, risk_score, haircut}}.
    Long gross + short gross ≤ REGIME_FACTOR[regime].
    """
    scale = REGIME_FACTOR.get(_norm_regime(regime), 0.80)
    rows = []
    for a in universe:
        if not isinstance(a, dict):
            continue
        sym = (a.get("symbol") or a.get("asset_id") or "").upper()
        if not sym:
            continue
        g = _grade_of(a)
        risk, conf = _risk_conf(a)
        conv = _conviction_of(a, conviction_override)   # self-tuning track-record conviction tilt
        lf = GRADE_FACTOR.get(g, 0.0) * conv     # grade × proven conviction
        sf = SHORT_GRADE_FACTOR.get(g, 0.0)
        # raw (grade-only) and meter-adjusted factors
        if lf > 0:
            haircut = HAIRCUT * risk * conf
            rows.append({"sym": sym, "grade": g, "risk": risk, "conf": conf, "conviction": conv,
                         "raw": lf, "adj": lf * (1.0 - haircut), "haircut": haircut, "side": 1})
        elif sf > 0 and MAX_SHORT_PCT > 0:
            boost = SHORT_BOOST * risk * conf
            rows.append({"sym": sym, "grade": g, "risk": risk, "conf": conf,
                         "raw": -sf, "adj": -sf * (1.0 + boost), "haircut": -boost, "side": -1})

    def _normalize(key: str) -> dict:
        gross = sum(abs(r[key]) for r in rows)
        if gross <= 0:
            return {r["sym"]: 0.0 for r in rows}
        k = scale / gross
        out = {}
        for r in rows:
            w = r[key] * k
            if r["side"] < 0:
                w = max(w, -MAX_SHORT_PCT * scale)
            out[r["sym"]] = w
        return out

    raw_w = _normalize("raw")
    adj_w = _normalize("adj")
    result = {}
    for r in rows:
        result[r["sym"]] = {
            "grade": r["grade"],
            "conviction": r.get("conviction", 1.0),
            "raw_weight": round(raw_w.get(r["sym"], 0.0), 4),
            "meter_weight": round(adj_w.get(r["sym"], 0.0), 4),
            "risk_score": round(r["risk"], 3),
            "confidence": round(r["conf"], 2),
            "haircut": round(r["haircut"], 3),
        }
    return result


def portfolio_risk_meter(weights: dict, universe: list, regime: str | None = None) -> dict:
    """
    One 0..1 needle = exposure-weighted out-of-circle fragility of the LONG book, plus
    the holdings dragging it. This is the Risk Meter reading.
    """
    cp_by_sym = {}
    for a in universe:
        if isinstance(a, dict):
            sym = (a.get("symbol") or a.get("asset_id") or "").upper()
            if sym:
                cp_by_sym[sym] = a.get("cause_proximity") or {}

    long_w_sum = 0.0
    weighted_risk = 0.0
    contributors = []
    for sym, w in weights.items():
        mw = w.get("meter_weight", 0.0) if isinstance(w, dict) else w
        if mw <= 0:
            continue
        risk = (w.get("risk_score") if isinstance(w, dict) else None)
        if risk is None:
            cp = cp_by_sym.get(sym, {})
            risk = float(cp.get("risk_score") or 0.0)
        long_w_sum += mw
        weighted_risk += mw * risk
        contributors.append({
            "symbol": sym, "weight": round(mw, 4), "risk_score": round(risk, 3),
            "contribution": round(mw * risk, 4),
            "drivers": (cp_by_sym.get(sym, {}) or {}).get("drivers", []),
        })

    reading = round(weighted_risk / long_w_sum, 3) if long_w_sum > 0 else 0.0
    band = "low" if reading < 0.33 else ("elevated" if reading < 0.60 else "high")
    contributors.sort(key=lambda c: -c["contribution"])
    return {
        "reading": reading,                         # 0..1 needle
        "band": band,
        "long_gross": round(long_w_sum, 4),
        "regime": _norm_regime(regime),
        "interpretation": _interpret(band, regime),
        "top_risk_contributors": contributors[:5],
    }


def _interpret(band: str, regime: str | None) -> str:
    reg = _norm_regime(regime)
    if band == "high":
        base = "Long book is crowded — consensus has diffused out-of-circle; marginal buyers exhausted. Trim the flagged names."
    elif band == "elevated":
        base = "Some holdings are mid-diffusion; watch the flagged names for an out-of-circle acceleration."
    else:
        base = "Long book is still upstream / in-circle — conviction is held by concentrated, informed holders."
    if reg in _RISK_OFF and band != "high":
        base += " (Risk-Off regime already caps gross exposure.)"
    return base


def build_risk_meter(universe: list, regime: str | None = None, conviction_override: dict | None = None) -> dict:
    """One-shot: meter-adjusted weights + the portfolio Risk Meter reading."""
    weights = meter_adjusted_weights(universe, regime, conviction_override)
    meter = portfolio_risk_meter(weights, universe, regime)
    return {"regime": _norm_regime(regime), "meter": meter, "weights": weights}


# ── Rebalance planner (pure, no I/O) ──────────────────────────────────────────
# Turns meter-adjusted target weights + the current book into a low-frequency
# rebalance plan. Low-frequency triggers (mirrors scripts/rebalance_engine):
#   regime change  ·  monthly (day 1 or >30d since last)  ·  any |Δweight| ≥ MIN_DW
# Churn guard: non-critical rebalances wait MIN_HOLD_DAYS (regime change overrides).
MIN_DW = 0.05            # 5% absolute weight move to count as a trigger / resize
MIN_OPEN_W = 0.01        # don't open a name below 1% target weight
MIN_TRADE_USD = 25.0     # ignore dust trades
MIN_HOLD_DAYS = 14
RESIZE_DW = 0.10         # only resize an existing hold if its weight drifts ≥10%


def plan_rebalance(target: dict, current: dict, nav: float, state: dict,
                   regime: str, now) -> dict:
    """
    target  : {SYM: signed_weight}      (from meter_adjusted_weights → meter_weight)
    current : {SYM: {"order_id","notional","side"}}  open METER_REBAL positions
    state   : {"last_rebal": iso|None, "last_regime": str|None}
    Returns {triggered, reason, opens:[{sym,notional,side}], closes:[order_id],
             resizes:[{sym,order_id,notional,side}]}.
    """
    from datetime import datetime
    target = {s: w for s, w in (target or {}).items() if abs(w) >= MIN_OPEN_W}
    current = current or {}
    cur_w = {}
    for s, p in current.items():
        sign = 1.0 if (p.get("side", "LONG") == "LONG") else -1.0
        cur_w[s] = sign * (float(p.get("notional") or 0) / nav if nav > 0 else 0.0)

    # trigger detection
    regime_change = bool(state.get("last_regime")) and state["last_regime"] != regime
    last = state.get("last_rebal")
    days_since = 999
    if last:
        try:
            d0 = datetime.fromisoformat(str(last).replace("Z", "+00:00"))
            days_since = (now - d0).days
        except Exception:
            days_since = 999
    monthly = (now.day == 1 and days_since >= 25) or days_since >= 30
    max_dw = max([abs(target.get(s, 0.0) - cur_w.get(s, 0.0))
                  for s in set(target) | set(cur_w)] or [0.0])
    drift_trigger = max_dw >= MIN_DW

    triggered = regime_change or monthly or drift_trigger
    if triggered and not regime_change and days_since < MIN_HOLD_DAYS and not monthly:
        triggered = False  # churn guard
    reason = ("regime_change" if regime_change else
              "monthly" if monthly else
              "drift" if drift_trigger else "none")
    if not triggered:
        return {"triggered": False, "reason": "churn_guard" if max_dw >= MIN_DW else "none",
                "opens": [], "closes": [], "resizes": [], "max_dw": round(max_dw, 3)}

    opens, closes, resizes = [], [], []
    for s in set(target) | set(cur_w):
        tw = target.get(s, 0.0)
        held = current.get(s)
        if not held:
            notion = abs(tw) * nav
            if notion >= MIN_TRADE_USD:
                opens.append({"sym": s, "notional": round(notion, 2),
                              "side": "LONG" if tw > 0 else "SHORT"})
            continue
        held_side = held.get("side", "LONG")
        target_side = "LONG" if tw > 0 else ("SHORT" if tw < 0 else None)
        if target_side is None or target_side != held_side:
            closes.append(held["order_id"])          # dropped or flipped → close
            if target_side is not None:
                notion = abs(tw) * nav
                if notion >= MIN_TRADE_USD:
                    opens.append({"sym": s, "notional": round(notion, 2), "side": target_side})
        elif abs(tw - cur_w.get(s, 0.0)) >= RESIZE_DW:
            resizes.append({"sym": s, "order_id": held["order_id"],
                            "notional": round(abs(tw) * nav, 2), "side": target_side})
    return {"triggered": True, "reason": reason, "opens": opens, "closes": closes,
            "resizes": resizes, "max_dw": round(max_dw, 3)}


# ── self-test ───────────────────────────────────────────────────────────────
def _selftest():
    universe = [
        {"symbol": "BTC", "grade": "A",
         "cause_proximity": {"risk_score": 0.10, "confidence": 0.7, "drivers": ["upstream"]}},
        {"symbol": "ZANO", "grade": "A+",          # high grade BUT out-of-circle → should trim hard
         "cause_proximity": {"risk_score": 0.85, "confidence": 0.85, "drivers": ["mass FOMO", "extended"]}},
        {"symbol": "SOL", "grade": "B+",
         "cause_proximity": {"risk_score": 0.30, "confidence": 0.7, "drivers": ["mild"]}},
        {"symbol": "DOGE", "grade": "D",           # weak + out-of-circle → short confirmed/boosted
         "cause_proximity": {"risk_score": 0.70, "confidence": 0.7, "drivers": ["late retail"]}},
    ]
    rm = build_risk_meter(universe, "Neutral")
    print(f"Risk Meter: reading={rm['meter']['reading']} band={rm['meter']['band']} regime={rm['regime']}")
    print(f"  → {rm['meter']['interpretation']}\n")
    print(f"  {'sym':6} {'grade':5} {'raw_w':>7} {'meter_w':>8} {'risk':>5} {'haircut':>8}")
    for sym, w in rm["weights"].items():
        print(f"  {sym:6} {w['grade']:5} {w['raw_weight']:>7} {w['meter_weight']:>8} "
              f"{w['risk_score']:>5} {w['haircut']:>8}")
    z = rm["weights"]["ZANO"]
    assert z["meter_weight"] < z["raw_weight"], "out-of-circle A+ must be trimmed below its raw grade weight"
    d = rm["weights"]["DOGE"]
    assert d["meter_weight"] < d["raw_weight"] <= 0, "weak out-of-circle name: short boosted (more negative)"
    print("\n✓ judgment→behavior: out-of-circle A+ trimmed; weak out-of-circle short boosted; meter reads the book.")


if __name__ == "__main__":
    _selftest()
