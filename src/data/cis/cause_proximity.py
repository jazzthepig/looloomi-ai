"""
Cause-proximity / 出圈 layer — the soul axis made measurable (ARCHITECTURE.md 大象无形,
METHODOLOGY_CORE §3). CIS tells you the QUALITY of a consensus; cause-proximity tells you
WHERE ON THE DIFFUSION CURVE that consensus currently sits — and therefore how fragile the
marginal price is.

The thesis (not a precise law — a labeled, evidence-tiered estimate):
  A consensus is SAFE while it is still upstream / in-circle (held by few, informed,
  concentrated) and DANGEROUS once it has diffused OUT of that circle to the mass (retail
  has arrived, the marginal buyer is the last buyer). The danger is NOT high consensus
  itself — it is high consensus *after 出圈*. Gold, a single parabolic hot stock, an
  all-in memecoin: same pattern — mass FOMO into a niche, marginal liquidity exhausted.

We do NOT fabricate a stage number we can't support. Evidence tiers, best-first:
  1. onchain_holders   — D3 holder-dispersion stage (Dune). The gold standard. Plugged in
                         when Minimax-A delivers the query_id (`holder_concentration.py`).
  2. attention_diffusion — D4 attention (CoinGecko trending + euphoric sentiment + swelling
                         watchlist). LIVE. A low-cap asset high in retail trending with
                         one-sided sentiment = diffusion accelerating out-of-circle.
  3. market_proxy      — always-available floor from the universe's own market data
                         (size + momentum extension + sentiment). Never missing.

Output per asset (inline, agent/investor-readable):
  cause_proximity = {
    out_of_circle_risk : "low" | "elevated" | "high"
    risk_score         : 0..1   (marginal-buyer fragility, the Risk-Meter input)
    stage              : 0..1 | None   (position on the diffusion curve; None unless D3)
    drivers            : [str, …]      (why)
    source             : onchain_holders | attention_diffusion | market_proxy
    confidence         : 0..1
  }

Two assets with identical CIS can carry very different cause-proximity risk — that is the
whole point: beta+ comes from being closer to the cause, not from the reflection (CIS).
"""
from __future__ import annotations

import math
from typing import Any

# risk-score weights (sum=1.0 over the four diffusion drivers)
_W_ATTENTION = 0.35   # D4: mass attention into a niche
_W_MOMENTUM  = 0.30   # parabolic extension = diffusion happening now
_W_EUPHORIA  = 0.20   # one-sided sentiment = last-buyer crowd
_W_SMALLNESS = 0.15   # smaller cap → marginal retail dominates the print

_LOW, _ELEVATED = 0.33, 0.60   # risk_score band cutoffs

_TRADFI_CLASSES = {"US Equity", "US Bond", "EM Equity", "DM Equity", "Commodity", "TradFi"}


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _smallness(market_cap_rank) -> float:
    """0 = mega-cap (rank 1, diffusion long completed = mature/stable), 1 = small/niche
    (rank ~1000, marginal retail dominates). log-scaled."""
    if not market_cap_rank or market_cap_rank <= 0:
        return 0.5
    return _clamp01(math.log10(market_cap_rank) / 3.0)   # rank 1→0, 10→.33, 100→.67, 1000→1


def _momentum_extension(a: dict) -> float:
    """How parabolic/extended is the move — diffusion-in-progress proxy. Uses 30d change
    if present, else the M pillar (0..100), else 7d/24h. >~120% 30d → fully extended."""
    for k in ("price_change_percentage_30d", "change_30d", "pct_30d"):
        v = a.get(k)
        if v is not None:
            try:
                return _clamp01(float(v) / 120.0)
            except (TypeError, ValueError):
                pass
    pillars = a.get("pillars") or {}
    m = pillars.get("M") or pillars.get("m") or a.get("m_pillar")
    if m is not None:
        try:
            # M well above neutral (50) = strong momentum = extended
            return _clamp01((float(m) - 50.0) / 40.0)
        except (TypeError, ValueError):
            pass
    for k in ("price_change_percentage_7d", "change_7d", "price_change_percentage_24h"):
        v = a.get(k)
        if v is not None:
            try:
                return _clamp01(float(v) / 40.0)
            except (TypeError, ValueError):
                pass
    return 0.3


def _euphoria_from_market(a: dict) -> float:
    """Inline euphoria proxy from the S pillar (sentiment, 0..100) when no D4 vote skew."""
    pillars = a.get("pillars") or {}
    s = pillars.get("S") or pillars.get("s") or a.get("s_pillar")
    if s is not None:
        try:
            return _clamp01((float(s) - 50.0) / 50.0)   # 50→0, 100→1
        except (TypeError, ValueError):
            pass
    return 0.3


def _band(score: float) -> str:
    return "low" if score < _LOW else ("elevated" if score < _ELEVATED else "high")


def _drivers(attention: float, momentum: float, euphoria: float, smallness: float,
             a: dict, att: dict | None) -> list[str]:
    out: list[str] = []
    if smallness > 0.6 and attention > 0.5:
        out.append("small/niche-cap sitting high in retail attention (mass FOMO pattern)")
    if momentum > 0.6:
        out.append("price extended — diffusion in progress, marginal buyer late")
    if euphoria > 0.6:
        out.append("one-sided euphoric sentiment — last-buyer crowd")
    if att and att.get("watchlist_users"):
        try:
            if float(att["watchlist_users"]) > 50_000:
                out.append("swelling CoinGecko watchlist — attention stock building")
        except (TypeError, ValueError):
            pass
    if not out:
        out.append("consensus still upstream / in-circle — no out-of-circle stress detected")
    return out


def estimate_inline(a: dict, attention: dict | None = None,
                    holder: dict | None = None) -> dict:
    """
    Cause-proximity estimate for one asset. NO network. `attention` (D4 row for this symbol)
    and `holder` (D3 stage for this symbol) are optional upgrades; absent → market_proxy floor.

    attention row (from trending_log): {attention_score, sentiment_up, watchlist_users, …}
    holder row    (from stage_series): {stage, disp_accel, chuquan}
    """
    asset_class = a.get("asset_class")
    rank = a.get("market_cap_rank") or a.get("rank")

    # ── diffusion drivers ─────────────────────────────────────────────
    smallness = _smallness(rank)
    momentum = _momentum_extension(a)

    if attention:
        att_score = attention.get("attention_score")
        attention_drv = _clamp01(float(att_score)) if att_score is not None else 0.3
        sent_up = attention.get("sentiment_up")
        euphoria = _clamp01((float(sent_up) - 50.0) / 50.0) if sent_up is not None else _euphoria_from_market(a)
        source = "attention_diffusion"
        confidence = 0.7
    else:
        attention_drv = 0.3
        euphoria = _euphoria_from_market(a)
        source = "market_proxy"
        confidence = 0.4

    # TradFi / listed: on-chain diffusion is off-chain & invisible; risk model degrades.
    if asset_class in _TRADFI_CLASSES:
        confidence = min(confidence, 0.35)

    risk_score = _clamp01(
        _W_ATTENTION * attention_drv + _W_MOMENTUM * momentum
        + _W_EUPHORIA * euphoria + _W_SMALLNESS * smallness
    )

    # ── stage: only when D3 holder data is present (don't fabricate it) ──
    stage = None
    chuquan = False
    if holder and holder.get("stage") is not None:
        try:
            stage = _clamp01(float(holder["stage"]))
            chuquan = bool(holder.get("chuquan"))
            source = "onchain_holders"
            confidence = 0.85
            # a fired 出圈 acceleration alert overrides the band upward
            if chuquan:
                risk_score = max(risk_score, 0.65)
        except (TypeError, ValueError):
            stage = None

    out = {
        "out_of_circle_risk": _band(risk_score),
        "risk_score": round(risk_score, 3),
        "stage": round(stage, 3) if stage is not None else None,
        "drivers": _drivers(attention_drv, momentum, euphoria, smallness, a, attention),
        "source": source,
        "confidence": round(confidence, 2),
    }
    if chuquan:
        out["chuquan_alert"] = True
    return out


def attach_cause_proximity(universe: list, attention_map: dict | None = None,
                           holder_map: dict | None = None) -> None:
    """
    Mutate each asset in place with an inline `cause_proximity` block.
    attention_map / holder_map are optional {SYMBOL_UPPER: row} lookups (D4 / D3); when
    absent every asset still gets the market_proxy floor — never missing.
    """
    attention_map = attention_map or {}
    holder_map = holder_map or {}
    for a in universe:
        if not isinstance(a, dict):
            continue
        sym = (a.get("symbol") or a.get("asset_id") or "").upper()
        try:
            a["cause_proximity"] = estimate_inline(
                a, attention_map.get(sym), holder_map.get(sym)
            )
        except Exception:
            # never break the universe on one asset
            a["cause_proximity"] = {
                "out_of_circle_risk": "low", "risk_score": 0.0, "stage": None,
                "drivers": ["unavailable"], "source": "market_proxy", "confidence": 0.0,
            }


# ── self-test: three archetypes ─────────────────────────────────────────────
def _selftest():
    universe = [
        {"symbol": "BTC", "market_cap_rank": 1,
         "pillars": {"M": 60, "S": 65}, "price_change_percentage_30d": 8},
        {"symbol": "ZANO", "market_cap_rank": 401,            # small-cap, trending, euphoric
         "pillars": {"M": 88, "S": 92}, "price_change_percentage_30d": 140},
        {"symbol": "AAPL", "asset_class": "US Equity", "market_cap_rank": 1,
         "pillars": {"M": 55, "S": 58}, "price_change_percentage_30d": 4},
    ]
    attention_map = {
        "ZANO": {"attention_score": 0.71, "sentiment_up": 94.0, "watchlist_users": 138_036},
        "BTC":  {"attention_score": 0.10, "sentiment_up": 62.0, "watchlist_users": 1_500_000},
    }
    holder_map = {
        # ZANO mid-diffusion with a fired 出圈 acceleration
        "ZANO": {"stage": 0.78, "disp_accel": 2.1, "chuquan": True},
    }
    attach_cause_proximity(universe, attention_map, holder_map)
    for a in universe:
        cp = a["cause_proximity"]
        print(f"{a['symbol']:6} risk={cp['out_of_circle_risk']:8} score={cp['risk_score']:.2f} "
              f"stage={cp['stage']} src={cp['source']:18} conf={cp['confidence']}")
        for d in cp["drivers"]:
            print(f"        · {d}")
    z = universe[1]["cause_proximity"]
    assert z["out_of_circle_risk"] == "high", "ZANO (small+trending+euphoric+出圈) must be high"
    assert z["source"] == "onchain_holders" and z.get("chuquan_alert"), "D3 must win + flag 出圈"
    assert universe[0]["cause_proximity"]["out_of_circle_risk"] == "low", "BTC mature = low"
    print("\n✓ archetypes resolve: mega-cap mature = low; small-cap mass-FOMO + 出圈 = high.")


if __name__ == "__main__":
    _selftest()
