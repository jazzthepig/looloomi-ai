"""
Causal Positioning Sleeve — live PAPER book (Seth, 2026-07-11).
===============================================================

STATUS (2026-08-08, OVERSIGHT §3 P0 #2): DEMOTED TO RESEARCH RECORD.
Market-neutral L/S construction. S-103 measured the construction as β-confounded
(tier ranks are essentially a β sort; |t| < 2 across all 5 neutralisation tiers).
S-105 measured cost > edge (turnover 45.8×/yr × 4.6%/yr > ~3% best-case effect).
The 25-day forward paper track is retained for SIGNAL-TRAJECTORY continuity
(NOT as product evidence); the loop is NOT being stopped — the graveyard is
the asset. See OVERSIGHT_2026-08.md §0 + §3 for the diagnosis that drove the demotion.

────────────────────────────────────────────────────────────────────────────

Turns the one walk-forward-and-cost-validated edge (causal_positioning: fade funding
crowding, market-neutral, corr +0.002 to swing, weekly-rebal net +1.69@10bps) into a
LIVE paper track record. This is what converts "walk-forward candidate" → "certified with
real marks" and gives an LP an honest number.

Market-neutral cross-sectional book → NAV-marked (not discrete round-trips like the
existing paper trader). State in Redis (survives restarts); NAV curve in Supabase
`causal_paper_nav`. Daily mark, WEEKLY rebalance (the validated deployable cadence).

Binance reachable from Railway since the Singapore region move (2026-07-11).
Pure stdlib + numpy + the project's Redis/Supabase helpers.
"""
from __future__ import annotations

import datetime as dt
import logging

import numpy as np

from src.research.strategies.causal_positioning import DEFAULT_UNIVERSE, positioning_weights

_log = logging.getLogger("causal_paper")

_STATE_KEY = "causal_paper:state"
_FAPI = "https://fapi.binance.com/fapi/v1"
_KWIN = 10
_REBAL_DAYS = 7
_FEE = 0.0005                    # 5bps/side on turnover (conservative for liquid majors)


async def _fetch_live(universe: list[str]) -> dict:
    """{sym: {"close": float, "fmean": [daily mean funding, trailing ~16d]}} from Binance."""
    import httpx
    out: dict = {}
    async with httpx.AsyncClient(timeout=20, headers={"User-Agent": "cometcloud"}) as c:
        for sym in universe:
            tk = sym + "USDT"
            try:
                fr = (await c.get(f"{_FAPI}/fundingRate", params={"symbol": tk, "limit": 60})).json()
                kl = (await c.get(f"{_FAPI}/klines", params={"symbol": tk, "interval": "1d", "limit": 2})).json()
                if not isinstance(fr, list) or not isinstance(kl, list) or not kl:
                    continue
                byday: dict = {}
                for x in fr:
                    d = int(x["fundingTime"]) // 86400000
                    byday.setdefault(d, []).append(float(x["fundingRate"]))
                daily = [sum(v) / len(v) for _, v in sorted(byday.items())]
                out[sym] = {"close": float(kl[-1][4]), "fmean": daily[-16:]}
            except Exception as e:
                _log.warning("[causal_paper] fetch %s: %s", sym, e)
    return out


def _target_weights(live: dict, universe: list[str]) -> dict:
    """Current cross-sectional market-neutral weights (fade funding crowding)."""
    syms = [s for s in universe if s in live and len(live[s]["fmean"]) >= _KWIN]
    if len(syms) < 5:
        return {}
    panel = np.array([live[s]["fmean"][-_KWIN:] for s in syms]).T   # kwin × K
    W = positioning_weights(panel, kwin=_KWIN)                       # kwin × K
    w_now = W[-1]
    return {s: float(w_now[i]) for i, s in enumerate(syms)}


async def mark_and_rebalance(dry_run: bool = False) -> dict:
    """Daily mark of the paper book; weekly rebalance. Idempotent per calendar day."""
    from src.data.market.data_layer import _redis_get, _redis_set
    today = dt.date.today()
    live = await _fetch_live(DEFAULT_UNIVERSE)
    if len(live) < 5:
        return {"status": "skipped", "reason": "insufficient_live_data"}

    state = await _redis_get(_STATE_KEY)
    if not isinstance(state, dict) or not state.get("weights"):
        # inception — start flat at NAV 1.0 with today's target book
        w = _target_weights(live, DEFAULT_UNIVERSE)
        state = {"inception": today.isoformat(), "nav": 1.0, "weights": w,
                 "mark_prices": {s: live[s]["close"] for s in w}, "last_rebal": today.isoformat(),
                 "last_mark": today.isoformat()}
        if not dry_run:
            await _redis_set(_STATE_KEY, state, ttl=0)
            await _write_nav(today, state["nav"], 0.0, sum(abs(x) for x in w.values()),
                             len(w), 0.0, 0.0, 0.0, True, w)
        return {"status": "inception", "nav": 1.0, "n": len(w), "date": today.isoformat()}

    if state.get("last_mark") == today.isoformat():
        return {"status": "already_marked", "nav": state["nav"], "date": today.isoformat()}

    w = state["weights"]; mp = state["mark_prices"]
    # daily P&L of the held book: price move + funding carry (short +funding receives)
    price_pnl = funding_pnl = 0.0
    for s, wi in w.items():
        if s not in live or s not in mp or mp[s] <= 0:
            continue
        price_pnl += wi * (live[s]["close"] / mp[s] - 1.0)
        fund_today = live[s]["fmean"][-1] * 3 if live[s]["fmean"] else 0.0   # ~daily funding
        funding_pnl += -wi * fund_today
    daily_ret = price_pnl + funding_pnl
    nav = state["nav"] * (1.0 + daily_ret)

    # weekly rebalance
    last_rebal = dt.date.fromisoformat(state["last_rebal"])
    cost = 0.0; rebalanced = False; new_w = w
    if (today - last_rebal).days >= _REBAL_DAYS:
        tgt = _target_weights(live, DEFAULT_UNIVERSE)
        if tgt:
            turn = sum(abs(tgt.get(s, 0) - w.get(s, 0)) for s in set(tgt) | set(w))
            cost = _FEE * turn
            nav *= (1.0 - cost)
            new_w = tgt; rebalanced = True

    state = {**state, "nav": nav, "weights": new_w,
             "mark_prices": {s: live[s]["close"] for s in new_w},
             "last_rebal": today.isoformat() if rebalanced else state["last_rebal"],
             "last_mark": today.isoformat()}
    if not dry_run:
        await _redis_set(_STATE_KEY, state, ttl=0)
        longs = sorted(new_w.items(), key=lambda kv: -kv[1])[:3]
        shorts = sorted(new_w.items(), key=lambda kv: kv[1])[:3]
        await _write_nav(today, nav, daily_ret, sum(abs(x) for x in new_w.values()),
                         len(new_w), funding_pnl, price_pnl, cost, rebalanced,
                         dict(longs + shorts))
    return {"status": "marked", "nav": round(nav, 5), "daily_return_pct": round(daily_ret * 100, 3),
            "rebalanced": rebalanced, "date": today.isoformat()}


async def _write_nav(d, nav, dret, gross, n, fpnl, ppnl, cost, rebal, weights):
    from src.api.store import supabase_insert_table
    longs = ",".join(f"{s}:{w:+.2f}" for s, w in sorted(weights.items(), key=lambda kv: -kv[1])[:3])
    shorts = ",".join(f"{s}:{w:+.2f}" for s, w in sorted(weights.items(), key=lambda kv: kv[1])[:3])
    try:
        await supabase_insert_table("causal_paper_nav", [{
            "mark_date": d.isoformat(), "nav": round(nav, 6), "daily_return": round(dret, 6),
            "gross": round(gross, 4), "n_positions": n, "funding_pnl": round(fpnl, 6),
            "price_pnl": round(ppnl, 6), "cost": round(cost, 6), "rebalanced": rebal,
            "top_longs": longs, "top_shorts": shorts}])
    except Exception as e:
        _log.warning("[causal_paper] nav write: %s", e)


async def get_curve(limit: int = 400) -> dict:
    """Read the NAV curve + summary stats from Supabase for the endpoint."""
    import os, httpx
    url = os.environ.get("SUPABASE_URL", "").rstrip("/"); key = os.environ.get("SUPABASE_KEY", "")
    if not (url and key):
        return {"status": "skipped"}
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(f"{url}/rest/v1/causal_paper_nav",
                            params={"select": "mark_date,nav,daily_return,rebalanced,top_longs,top_shorts",
                                    "order": "mark_date.asc", "limit": str(limit)},
                            headers={"apikey": key, "Authorization": f"Bearer {key}"})
            rows = r.json() if r.status_code == 200 else []
    except Exception as e:
        return {"status": "error", "error": str(e)[:120]}
    if not rows:
        return {"status": "no_data", "note": "paper book not yet marked"}
    navs = [x["nav"] for x in rows]; rets = [x["daily_return"] for x in rows if x.get("daily_return") is not None]
    sharpe = (float(np.mean(rets) / np.std(rets) * np.sqrt(365)) if len(rets) > 5 and np.std(rets) > 0 else None)
    cum = navs[-1] / navs[0] - 1 if navs else 0
    peak = np.maximum.accumulate(navs); dd = float((peak - navs).max() / peak.max()) if navs else 0
    return {"status": "ok", "days": len(rows), "inception": rows[0]["mark_date"], "nav": navs[-1],
            "return_pct": round(cum * 100, 2), "ann_sharpe": round(sharpe, 2) if sharpe else None,
            "max_dd_pct": round(dd * 100, 2), "latest": rows[-1], "curve": rows}


if __name__ == "__main__":
    import asyncio, json
    print(json.dumps(asyncio.run(mark_and_rebalance(dry_run=True)), indent=2))
