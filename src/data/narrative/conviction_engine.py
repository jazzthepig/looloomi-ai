"""
Conviction Engine — the AI-augmented beta-plus candidate surfacer (Seth 2026-07-15).
=====================================================================================

Composes the CONVICTION_METHODOLOGY 4-layer stack into a ranked WATCHLIST of structural-winner
candidates for DISCRETIONARY human+AI conviction (it surfaces; it does NOT trade). Honest after
R21: no single layer predicts — the value is the CONJUNCTION (L1∧L2∧L3∧L4).

  L1 MOAT       — moat_map membership + moat quality (durable capability? reflexive loop?)   [gate]
  L2 CATALYST   — on-chain activation (vol/price z) × optional narrative event→moat match
  L3 FUND-MOM   — fundamental_momentum (revenue accel + run-rate)                             [filter]
  L4 TREND      — price confirmation (market starting to agree; avoid the falling knife)

  ConvictionScore = moat_quality × (0.40·L2 + 0.35·L3 + 0.25·L4)

Surfaces {symbol, score, L1..L4, reflexive_loop, drivers}. Data: Binance fapi (px+vol) +
DeFiLlama revenue (via fundamental_momentum) + moat_map + catalyst_detector. Pure stdlib + numpy.
"""
from __future__ import annotations

import json
import urllib.request

import numpy as np

from src.data.narrative.moat_map import MOAT_MAP, ACTIVATING_CONDITIONS
from src.data.narrative.catalyst_detector import latest_activation_score, classify_event
from src.data.narrative.fundamental_momentum import fundamental_momentum

# moat asset → (DeFiLlama revenue slug, Binance symbol)
REGISTRY = {
    "HYPE": ("hyperliquid", "HYPE"), "ONDO": ("ondo-finance", "ONDO"), "GMX": ("gmx", "GMX"),
    "UNI": ("uniswap", "UNI"), "MKR": ("makerdao", "MKR"), "ENA": ("ethena", "ENA"),
    "AAVE": ("aave", "AAVE"), "PENDLE": ("pendle", "PENDLE"), "JUP": ("jupiter", "JUP"),
    "LINK": ("chainlink", "LINK"),
}
_PERP = "https://fapi.binance.com/fapi/v1/klines"


def _clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def _klines(sym: str, limit: int = 120):
    try:
        u = f"{_PERP}?symbol={sym}USDT&interval=1d&limit={limit}"
        r = json.loads(urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": "cc"}), timeout=15).read())
        close = np.array([float(k[4]) for k in r]); qv = np.array([float(k[7]) for k in r])
        return close, qv
    except Exception:
        return np.array([]), np.array([])


def _moat_quality(moat) -> float:
    """L1: durable-capability breadth + reflexive loop → 0..1."""
    return round(_clamp(0.55 * min(len(moat.capabilities) / 4.0, 1.0) + (0.45 if moat.reflexive_loop else 0.0)), 3)


def _trend_score(close) -> float:
    """L4: price starting to confirm — above 30d mean AND positive 30d momentum → 0..1."""
    if len(close) < 60:
        return 0.0
    mom30 = close[-1] / close[-30] - 1.0
    above = 1.0 if close[-1] > close[-30:].mean() else 0.0
    return round(_clamp(0.5 * above + 0.5 * _clamp(0.5 + mom30 * 2)), 3)


def evaluate(asset: str, events: list[str] | None = None) -> dict | None:
    moat = MOAT_MAP.get(asset)
    reg = REGISTRY.get(asset)
    if not moat or not reg:
        return None
    slug, sym = reg
    close, qv = _klines(sym)
    if len(close) < 60:
        return None
    # L1
    mq = _moat_quality(moat)
    # L2 — on-chain activation (0..~10 → 0..1) × narrative match bonus
    act = latest_activation_score(close, qv)
    act_n = _clamp(act / 6.0)
    narrative_hit = False
    if events:
        conds = set()
        for e in events:
            conds |= set(classify_event(e))
        activated_caps = set()
        for c in conds:
            activated_caps |= set(ACTIVATING_CONDITIONS.get(c, []))
        narrative_hit = bool(activated_caps & set(moat.capabilities))
    l2 = round(_clamp(act_n * (1.3 if narrative_hit else 1.0)), 3)
    # L3 — fundamental momentum
    fm = fundamental_momentum(slug)
    l3 = fm.get("score", 0.0)
    # L4 — trend confirmation
    l4 = _trend_score(close)

    score = round(mq * (0.40 * l2 + 0.35 * l3 + 0.25 * l4), 3)
    drivers = []
    if narrative_hit: drivers.append("narrative catalyst activates the moat")
    if act >= 2: drivers.append(f"on-chain activation z={act}")
    if fm.get("revenue_accel_pct", 0) > 10: drivers.append(f"revenue accelerating +{fm['revenue_accel_pct']}%")
    if moat.reflexive_loop: drivers.append("reflexive fee→token loop")
    if l4 > 0.6: drivers.append("price confirming")
    return {"symbol": asset, "conviction_score": score,
            "L1_moat_quality": mq, "L2_catalyst": l2, "L3_fundamental_momentum": l3, "L4_trend": l4,
            "reflexive_loop": moat.reflexive_loop,
            "revenue_30d_usd": fm.get("revenue_30d_usd"), "revenue_accel_pct": fm.get("revenue_accel_pct"),
            "activation_z": act, "narrative_hit": narrative_hit,
            "thesis": moat.thesis, "drivers": drivers or ["moat present; awaiting catalyst"]}


def get_watchlist(events: list[str] | None = None) -> dict:
    """Ranked conviction candidates. `events` = recent news/macro strings (optional narrative half)."""
    rows = []
    for a in MOAT_MAP:
        try:
            r = evaluate(a, events)
            if r:
                rows.append(r)
        except Exception:
            continue
    rows.sort(key=lambda r: -r["conviction_score"])
    return {"as_of": __import__("datetime").datetime.utcnow().isoformat(),
            "n": len(rows), "candidates": rows,
            "basis": "L1 moat × (L2 catalyst + L3 fundamental momentum + L4 trend); conjunction-first (R21)",
            "compliance": "candidates for discretionary conviction, NOT a signal; positioning language only; not advice"}


if __name__ == "__main__":
    import json as _j
    print(_j.dumps(get_watchlist(events=["Trump weekend war, oil spikes, TradFi closed"]), indent=2, default=str)[:2000])
