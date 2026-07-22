"""
Trend-Confirmation signal — the survivor extracted from the Crowd Clock backtest (Seth 2026-07-17).
====================================================================================================
The Crowd Clock's contrarian claim was refuted (R24), but the discovery yielded a REAL, cross-asset
edge when we decomposed it: **sentiment adds forward return ON TOP OF momentum**. The crowd's
agreement CONFIRMS a trend; its disbelief flags a weak one. This is the extracted feature.

Cross-asset base rates (forward-30d mean return, Δ vs unconditional baseline, 2018→2026 full history,
Fear&Greed + Binance daily; `src/research/crowd_clock_backtest.py` + decomposition):

    state             BTC Δ      ETH Δ      SOL Δ     read
    uptrend + GREED   +3.64%     +5.50%    +13.69%    CONFIRMED up — strongest; the trend the crowd backs
    uptrend + fear    −1.53%     −4.39%    −13.42%    UNCONFIRMED up — a rally the crowd distrusts; do not chase
    downtrend         −2.31%     −2.19%     −5.95%    down — defensive; NO contrarian bounce at 30d
    (sentiment adds over plain uptrend: +1.64 / +3.39 / +7.49 — it is NOT a momentum relabel)

DOCTRINE FIT (Trader Tom): ride the CONFIRMED trend, distrust the unconfirmed one — the opposite of
naive contrarianism. Momentum is the base; sentiment agreement is the confirmation filter.

HONEST STATUS — ⛔ FAILED WALK-FORWARD OOS (R24 Follow-up 3). The "sentiment adds over momentum" edge
was a 2018-2022 phenomenon: in the ≥2023 holdout it collapsed (BTC −0.35pp, SOL +0.69pp — gone; only
ETH +2.21pp weakly survived). Plain trend/momentum persists OOS; the SENTIMENT confirmation does NOT.
So this is a DOCUMENTED NEGATIVE result — **do NOT size it.** Kept for the record and as a display/
context lens only. Momentum (which we already have) is the survivor; the Crowd Clock's incremental
value over momentum is NOT established out-of-sample. Compliance: positioning language only.
"""
from __future__ import annotations

# trend threshold (30d %); sentiment split at FNG 50. Kept deliberately simple — the edge is the
# INTERACTION (trend × agreement), not a finely-tuned cutoff (which would overfit, R1).
_TREND_UP = 3.0     # 30d change above this = uptrend (small deadband around 0)
_TREND_DN = -3.0
_GREED = 55.0       # FNG above = crowd agreement (greed); below 45 = disbelief (fear)
_FEAR = 45.0


def trend_confirmation(chg30: float | None, fng: float | None) -> dict:
    """Per-asset: 30d trend × crowd sentiment → confirmation state. Momentum base, sentiment filter.
    Positioning read only; a validated candidate, not advice."""
    if chg30 is None or fng is None:
        return {"state": "unknown", "score": 0.0, "note": "insufficient data"}
    up = chg30 >= _TREND_UP
    dn = chg30 <= _TREND_DN
    greed = fng >= _GREED
    fear = fng <= _FEAR

    if up and greed:
        return {"state": "confirmed_up", "score": 1.0, "direction": "OUTPERFORM",
                "note": "Uptrend the crowd confirms (greed) — the strongest forward setup; press the trend."}
    if up and fear:
        return {"state": "unconfirmed_up", "score": 0.2, "direction": "NEUTRAL",
                "note": "Uptrend the crowd distrusts (fear) — a weak rally; do not chase, wait for confirmation."}
    if dn and fear:
        return {"state": "confirmed_down", "score": -0.8, "direction": "UNDERPERFORM",
                "note": "Downtrend with fear — defensive; no contrarian bounce edge at a 30d horizon."}
    if dn and greed:
        return {"state": "unconfirmed_down", "score": -0.4, "direction": "UNDERPERFORM",
                "note": "Downtrend with lingering greed — complacency; distribution/top risk."}
    return {"state": "neutral", "score": 0.0, "direction": "NEUTRAL",
            "note": "No clear trend or split sentiment — stand aside."}


async def get_trend_confirmation(symbol: str = "BTC") -> dict:
    """Live read for an asset from cached data (CIS universe 30d change + FNG). Best-effort."""
    chg30 = fng = None
    try:
        from src.api.store import redis_get_key
        cis = await redis_get_key("cis:local_scores") or {}
        uni = cis.get("assets") or cis.get("universe") or []
        a = next((x for x in uni if (x.get("symbol") or x.get("asset_id") or "").upper() == symbol.upper()), None)
        if a:
            v = a.get("change_30d") or a.get("chg_30d") or a.get("price_change_30d")
            chg30 = float(v) if v is not None else None
    except Exception:
        pass
    try:
        from src.data.market.data_layer import get_fear_greed
        fg = await get_fear_greed()
        if isinstance(fg, dict):
            fng = float(fg.get("value") or fg.get("fng") or fg.get("score"))
    except Exception:
        pass
    r = trend_confirmation(chg30, fng)
    r["symbol"] = symbol.upper()
    r["inputs"] = {"chg_30d": chg30, "fng": fng}
    r["compliance"] = "Positioning language only; validated candidate, not investment advice."
    return r


if __name__ == "__main__":
    for chg, f, lbl in [(15, 70, "up+greed"), (15, 30, "up+fear"), (-15, 25, "down+fear"),
                        (-15, 70, "down+greed"), (1, 50, "flat")]:
        r = trend_confirmation(chg, f)
        print(f"{lbl:12s} chg30={chg:+3d} fng={f:2d} -> {r['state']:16s} score={r['score']:+.1f}  {r['note'][:56]}")
