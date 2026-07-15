"""
顶格 RWA Paper Sleeve — live forward track record (Seth 2026-07-15).
====================================================================

The 顶格 volume-gated strategy CANNOT be backtest-validated: every episode of this instrument
class (tokenized-RWA perps) is from 2026 — no genuine out-of-sample exists yet (experiment_runs
dingge_rwa_strategy_20260715 → candidate/premature, IS +8.8% / OOS −1.9%). So we do the honest
thing: deploy it as a LIVE PAPER book that trades the rule forward and accrues a real, dated
track record. In ~2-3 months this either earns the word or is refuted on data it didn't overfit.

Rule (entry-time direction, decided from side + 量能, identical to the study):
  · short_crowded (−cap): LONG (squeeze) unless volume dead (<0.9×)
  · long_crowded  (+cap): LONG if volume expands (>1.1×); SHORT if dead (<0.9×); else skip
Entry ≈15d after the 顶格 event (old trend resets, volume is readable); hold to event+35d.
Equal-weight paper book: each position = 10% of NAV, max ~10 concurrent.

State → Redis `dingge_paper:state` (survives restarts). NAV curve → Supabase `dingge_paper_nav`.
Data: Binance fapi funding + daily klines. Pure numpy + project Redis/Supabase helpers.
"""
from __future__ import annotations

import datetime as dt
import logging

import numpy as np

from src.data.signals.dingge_rwa import RWA_PERPS, _client, _funding, _klv, _episodes

_log = logging.getLogger("dingge_paper")
_STATE_KEY = "dingge_paper:state"

VOL_UP, VOL_DEAD = 1.10, 0.90
ENTRY_LAG, HOLD = 15, 20            # enter +15d after event, hold 20d (→ event+35d)
POS_WEIGHT = 0.10                   # 10% of NAV per position
MAX_OPEN = 10


def _direction(side: int, vol_ratio: float) -> int:
    if side < 0:
        return +1 if vol_ratio >= VOL_DEAD else 0
    if vol_ratio > VOL_UP:
        return +1
    if vol_ratio < VOL_DEAD:
        return -1
    return 0


def _last_close(K: dict):
    if not K:
        return None
    return K[max(K)][0]


async def mark_and_trade(dry_run: bool = False) -> dict:
    """Daily: close due positions, open new 顶格 entries, mark NAV. Idempotent per day."""
    from src.data.market.data_layer import _redis_get, _redis_set
    today = dt.date.today()

    state = await _redis_get(_STATE_KEY)
    if not isinstance(state, dict) or "nav" not in state:
        state = {"nav": 1.0, "realized": 0.0, "open": [], "closed": 0,
                 "traded": [], "inception": today.isoformat(), "last_mark": None}

    if state.get("last_mark") == today.isoformat():
        return {"status": "already_marked", "nav": state["nav"], "date": today.isoformat()}

    # pull fresh data for the universe once
    data = {}
    with _client() as client:
        for s in RWA_PERPS:
            try:
                fu = _funding(client, s); K = _klv(client, s)
                if fu and K:
                    data[s] = (fu, K)
            except Exception:
                continue

    opened_today = closed_today = 0
    unreal = 0.0
    still_open = []

    # ── 1) close due positions ──
    for p in state["open"]:
        K = data.get(p["sym"], (None, {}))[1]
        px_now = _last_close(K) or p["entry_px"]
        exit_d = dt.date.fromisoformat(p["exit_date"])
        if today >= exit_d:
            r = (px_now / p["entry_px"] - 1.0) * p["dir"] * POS_WEIGHT
            state["realized"] += r
            state["closed"] += 1
            closed_today += 1
        else:
            still_open.append(p)
    state["open"] = still_open

    # ── 2) detect new entries (event ~15d ago, direction fires, not already traded) ──
    for s, (fu, K) in data.items():
        if len(state["open"]) >= MAX_OPEN:
            break
        kd = sorted(K)
        for d, side in _episodes(fu):
            age = (today - d).days
            if not (ENTRY_LAG - 1 <= age <= ENTRY_LAG + 1):
                continue
            key = f"{s}@{d.isoformat()}"
            if key in state["traded"]:
                continue
            pre = [x for x in kd if x < d]
            fut = [x for x in kd if x >= d]
            if len(pre) < 15 or len(fut) < ENTRY_LAG + 1:
                continue
            volpre = np.mean([K[x][1] for x in pre[-15:]])
            volpost = np.mean([K[x][1] for x in fut[1:ENTRY_LAG + 1]])
            if volpre <= 0:
                continue
            direction = _direction(side, volpost / volpre)
            if direction == 0:
                state["traded"].append(key)      # decided-skip: don't re-check
                continue
            entry_px = _last_close(K)
            if not entry_px:
                continue
            state["open"].append({
                "sym": s, "dir": direction, "event_date": d.isoformat(),
                "entry_date": today.isoformat(), "entry_px": entry_px,
                "exit_date": (d + dt.timedelta(days=ENTRY_LAG + HOLD)).isoformat(),
                "side": side, "vol_ratio": round(volpost / volpre, 2)})
            state["traded"].append(key)
            opened_today += 1
            if len(state["open"]) >= MAX_OPEN:
                break

    # ── 3) mark unrealized on open book ──
    for p in state["open"]:
        K = data.get(p["sym"], (None, {}))[1]
        px_now = _last_close(K) or p["entry_px"]
        unreal += (px_now / p["entry_px"] - 1.0) * p["dir"] * POS_WEIGHT

    nav = 1.0 + state["realized"] + unreal
    state["nav"] = nav
    state["last_mark"] = today.isoformat()
    state["traded"] = state["traded"][-500:]     # bound memory

    if not dry_run:
        await _redis_set(_STATE_KEY, state, ttl=0)
        await _write_nav(today, nav, state["realized"], unreal, len(state["open"]),
                         state["closed"], opened_today, closed_today, state["open"])
    return {"status": "marked", "nav": round(nav, 5),
            "realized_pct": round(state["realized"] * 100, 2),
            "unrealized_pct": round(unreal * 100, 2),
            "open": len(state["open"]), "opened_today": opened_today,
            "closed_today": closed_today, "date": today.isoformat()}


async def _write_nav(d, nav, realized, unreal, n_open, closed, opened_today, closed_today, book):
    from src.api.store import supabase_insert_table
    detail = [{"sym": p["sym"], "dir": p["dir"], "vr": p.get("vol_ratio"),
               "entry": p["entry_date"], "exit": p["exit_date"]} for p in book]
    try:
        await supabase_insert_table("dingge_paper_nav", [{
            "mark_date": d.isoformat(), "nav": round(nav, 6),
            "realized_pnl": round(realized, 6), "unrealized_pnl": round(unreal, 6),
            "open_positions": n_open, "closed_trades": closed,
            "opened_today": opened_today, "closed_today": closed_today,
            "detail": detail}])
    except Exception as e:
        _log.warning("[dingge_paper] nav write: %s", e)


async def get_curve(limit: int = 400) -> dict:
    """NAV curve + summary for the endpoint."""
    import os, httpx
    url = os.environ.get("SUPABASE_URL", "").rstrip("/"); key = os.environ.get("SUPABASE_KEY", "")
    if not (url and key):
        return {"status": "skipped"}
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(f"{url}/rest/v1/dingge_paper_nav",
                            params={"select": "mark_date,nav,realized_pnl,unrealized_pnl,open_positions,closed_trades",
                                    "order": "mark_date.asc", "limit": str(limit)},
                            headers={"apikey": key, "Authorization": f"Bearer {key}"})
            rows = r.json() if r.status_code == 200 else []
    except Exception as e:
        return {"status": "error", "error": str(e)[:120]}
    if not rows:
        return {"status": "no_data", "note": "sleeve not yet marked"}
    navs = [x["nav"] for x in rows]
    return {"status": "ok", "days": len(rows), "inception": rows[0]["mark_date"],
            "nav": navs[-1], "return_pct": round((navs[-1] - 1) * 100, 2),
            "closed_trades": rows[-1].get("closed_trades"), "latest": rows[-1], "curve": rows}


if __name__ == "__main__":
    import asyncio, json
    print(json.dumps(asyncio.run(mark_and_trade(dry_run=True)), indent=2))
