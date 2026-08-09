"""
§5b Two-Layer Book — live PAPER track record (Seth, 2026-07-21).
=================================================================

Ships the §TRADER_TOM §5b two-layer book (R55/R57) as a live, daily-marked paper sleeve so
the FORWARD out-of-sample clock starts running. R57's sharpest limitation was *"forward P&L
cannot be measured yet"* — this module is the fix. It is the only thing we cannot buy later.

ARCHITECTURE — overlay-only (`V5c × I(C > +0.20)`).
  R55 validated architectures D (0.5/0.5) and H (regime-multiple) on the full in-sample.
  R57's held-out OOS then showed **overlay-only is the one that survives**: it sat FLAT
  through the Earlier-OOS bear (0/61 days engaged) and preserved capital, while D and H
  inherited V5c exposure and lost (−0.360 SR each). Overlay discipline is a property, not an
  in-sample fit. So the deployed shape is the conservative one the OOS actually endorses.

🚦 CORE-HEALTH GATE — the honest part.
  R57's structural finding: the V5c core is **dead** — 7/262 days engaged (2.7%) since
  2025-11 in the post-Nov BTC downtrend. A book on a dead core should sit FLAT, and it must
  say so out loud rather than fabricate a core to fill the silence. So this sleeve:
    · marks NAV every day regardless (a flat day is a real, recorded observation),
    · reports `core_state` = live | dead each mark, with trailing-90d engagement,
    · holds target size at ZERO while the core is dead — no invented trades.
  This is what makes it deployable THIS WEEK without shipping a curve-fit: the book goes to
  production now and tells the truth, including the truth that it is currently flat.

🔁 HOT-SWAPPABLE CORE (Redis `two_layer_paper:core`).
  Mirrors combined_book's self-recalibrating nucleus. When §CORE-BAKEOFF (Minimax-B) produces
  a core that is alive in the current regime, write its config to that key and the book
  engages with NO code deploy. Core selection is data, not code.

⚠️ POINT-IN-TIME: the research C detector (interpretation_c.py) normalizes chop with a
  FULL-SAMPLE 95th percentile and funding with full-sample mean/std — look-ahead bias. This
  production implementation uses TRAILING-ONLY rolling windows so every score at time t uses
  only data ≤ t. Live scores may therefore differ modestly from the research CSV. That is
  correct, not a bug (see pit_guard.py).

State → Redis `two_layer_paper:state`; NAV curve → Supabase `two_layer_paper_nav`.
Compliance: internal research/paper book. Positioning language only in any surfaced output.
"""
from __future__ import annotations

import datetime as dt
import logging

import numpy as np

_log = logging.getLogger("two_layer_paper")

_STATE_KEY = "two_layer_paper:state"
_CORE_KEY = "two_layer_paper:core"
_FAPI = "https://fapi.binance.com/fapi/v1"

UNIVERSE = ["BTC", "ETH", "SOL"]

# ── Deployed core config (V5c). Overridable at runtime via Redis _CORE_KEY. ──
DEFAULT_CORE = {
    "name": "v5c",
    "fast": 54,
    "slow": 126,
    "long_only": True,
}

C_GATE = 0.20              # strict long gate (R53/R54 Pareto cell)
C_SMOOTH_D = 30            # 30d smoothing of the raw regime score
C_SHORT_PENALTY = 1.5      # short-reluctant calibration (engine-side)
_NORM_WIN = 252            # trailing window for PIT-safe normalization
_FEE = 0.0005              # 5bps/side on turnover
_CORE_MIN_ENGAGEMENT = 0.05   # <5% of trailing 90d engaged ⇒ core structurally dead
_ENGAGEMENT_WIN = 90


# ── data ──────────────────────────────────────────────────────────────────────
async def _fetch_daily(universe: list[str]) -> dict:
    """{coin: {"close": np.ndarray daily closes, "funding": np.ndarray daily mean funding}}."""
    import httpx
    out: dict = {}
    async with httpx.AsyncClient(timeout=25, headers={"User-Agent": "cometcloud"}) as c:
        for coin in universe:
            tk = coin + "USDT"
            try:
                kl = (await c.get(f"{_FAPI}/klines",
                                  params={"symbol": tk, "interval": "1d", "limit": 400})).json()
                if not isinstance(kl, list) or len(kl) < 200:
                    continue
                close = np.array([float(k[4]) for k in kl], dtype=float)
                funding = np.array([])
                try:
                    fr = (await c.get(f"{_FAPI}/fundingRate",
                                      params={"symbol": tk, "limit": 1000})).json()
                    if isinstance(fr, list) and fr:
                        byday: dict = {}
                        for x in fr:
                            byday.setdefault(int(x["fundingTime"]) // 86400000, []).append(
                                float(x["fundingRate"]))
                        funding = np.array([sum(v) / len(v) for _, v in sorted(byday.items())],
                                           dtype=float)
                except Exception as e:            # funding is optional — C degrades to 2 factors
                    _log.warning("[two_layer] funding %s: %s", coin, e)
                out[coin] = {"close": close, "funding": funding}
            except Exception as e:
                _log.warning("[two_layer] klines %s: %s", coin, e)
    return out


# ── primitives ────────────────────────────────────────────────────────────────
def _ema(x: np.ndarray, n: int) -> np.ndarray:
    a = 2.0 / (n + 1)
    out = np.empty_like(x, dtype=float)
    out[0] = x[0]
    for i in range(1, len(x)):
        out[i] = a * x[i] + (1 - a) * out[i - 1]
    return out


def _roll(x: np.ndarray, win: int, fn) -> np.ndarray:
    """Trailing-only rolling reduction — value at t uses x[max(0,t-win+1) : t+1]. PIT-safe."""
    out = np.full(len(x), np.nan)
    for i in range(len(x)):
        seg = x[max(0, i - win + 1): i + 1]
        seg = seg[~np.isnan(seg)]
        if len(seg) >= 20:
            out[i] = fn(seg)
    return out


def core_position(close: np.ndarray, core: dict) -> np.ndarray:
    """Binary core position from the (hot-swappable) core config. 1.0 = engaged long."""
    f, s = _ema(close, int(core.get("fast", 54))), _ema(close, int(core.get("slow", 126)))
    if core.get("long_only", True):
        return np.where(f > s, 1.0, 0.0)
    return np.sign(f - s)


def regime_score_c(close: np.ndarray, funding: np.ndarray) -> np.ndarray:
    """Interpretation-C engine-side regime score on [-1,+1], PIT-safe (trailing normalization).

    C = 0.5·V5c-strength + 0.3·chop_norm + 0.2·funding_norm, 30d-smoothed, short-reluctant.
    Falls back to renormalized 2-factor when funding is unavailable.
    """
    n = len(close)
    # F1 — continuous V5c trend strength (tanh of trailing z-score of the EMA spread)
    diff = _ema(close, 54) - _ema(close, 126)
    mu, sd = _roll(diff, 60, np.mean), _roll(diff, 60, np.std)
    with np.errstate(divide="ignore", invalid="ignore"):
        z = np.where((sd > 1e-9) & ~np.isnan(sd), (diff - mu) / sd, np.nan)
    f1 = np.tanh(z / 2.0)

    # F2 — chop: coefficient of variation of |returns|; normalized by TRAILING p95
    rets = np.zeros(n); rets[1:] = close[1:] / close[:-1] - 1
    ar = np.abs(rets)
    cv_s, cv_m = _roll(ar, 30, np.std), _roll(ar, 30, np.mean)
    with np.errstate(divide="ignore", invalid="ignore"):
        cv = np.where((cv_m > 1e-9) & ~np.isnan(cv_m), cv_s / cv_m, np.nan)
    p95 = _roll(cv, _NORM_WIN, lambda s: np.percentile(s, 95))
    with np.errstate(divide="ignore", invalid="ignore"):
        f2 = np.clip(1.0 - 2.0 * cv / np.where(p95 > 1e-9, p95, np.nan), -1, 1)

    # F3 — funding momentum: 14d mean, trailing z, sign-flipped (crowded long ⇒ fragile)
    f3 = np.full(n, np.nan)
    if funding is not None and len(funding) >= 40:
        fd = funding[-n:] if len(funding) >= n else np.concatenate(
            [np.full(n - len(funding), np.nan), funding])
        f14 = _roll(fd, 14, np.mean)
        fmu, fsd = _roll(f14, _NORM_WIN, np.mean), _roll(f14, _NORM_WIN, np.std)
        with np.errstate(divide="ignore", invalid="ignore"):
            fz = np.where((fsd > 1e-12) & ~np.isnan(fsd), (f14 - fmu) / fsd, np.nan)
        f3 = np.tanh(-fz)

    # combine with renormalized weights over the factors actually available at each t
    w1, w2, w3 = 0.5, 0.3, 0.2
    raw = np.full(n, np.nan)
    for i in range(n):
        parts, wts = [], []
        for v, w in ((f1[i], w1), (f2[i], w2), (f3[i], w3)):
            if not np.isnan(v):
                parts.append(v); wts.append(w)
        if wts and sum(wts) >= 0.5:          # need at least the trend factor
            raw[i] = float(np.dot(parts, wts) / sum(wts))
    raw = np.clip(raw, -1, 1)

    smooth = _roll(raw, C_SMOOTH_D, np.mean)
    out = smooth.copy()
    neg = ~np.isnan(out) & (out < 0)
    out[neg] = out[neg] / C_SHORT_PENALTY     # short-reluctant
    return out


# ── core health ───────────────────────────────────────────────────────────────
def core_health(pos: np.ndarray) -> dict:
    """Is the core alive in the CURRENT regime? R57: V5c ran 2.7% engaged since 2025-11."""
    tail = pos[-_ENGAGEMENT_WIN:]
    tail = tail[~np.isnan(tail)]
    eng = float(np.mean(np.abs(tail) > 0)) if len(tail) else 0.0
    return {
        "engagement_90d": round(eng, 4),
        "state": "live" if eng >= _CORE_MIN_ENGAGEMENT else "dead",
        "threshold": _CORE_MIN_ENGAGEMENT,
    }


async def _live_core() -> dict:
    """Hot-swappable core config — §CORE-BAKEOFF winner lands here with no code deploy."""
    try:
        from src.data.market.data_layer import _redis_get
        c = await _redis_get(_CORE_KEY)
        if isinstance(c, dict) and c.get("fast") and c.get("slow"):
            return c
    except Exception:
        pass
    return DEFAULT_CORE


def target_weights(data: dict, core: dict) -> tuple[dict, dict]:
    """Today's target book + diagnostics. Overlay-only: w = core × I(C > gate), equal-weight.

    Returns ({coin: weight}, diagnostics). Weights are ZERO when the core is dead — the book
    records an honest flat rather than inventing exposure.
    """
    per, health = {}, {}
    for coin, d in data.items():
        px = d["close"]
        if len(px) < 200:
            continue
        pos = core_position(px, core)
        c = regime_score_c(px, d.get("funding"))
        h = core_health(pos)
        engaged = bool(pos[-1] > 0)
        gate_open = bool(not np.isnan(c[-1]) and c[-1] > C_GATE)
        per[coin] = {
            "core_engaged": engaged,
            "c_score": None if np.isnan(c[-1]) else round(float(c[-1]), 4),
            "gate_open": gate_open,
            "core_state": h["state"],
            "engagement_90d": h["engagement_90d"],
        }
        health[coin] = h

    live = [c for c in per if per[c]["core_state"] == "live"]
    book_state = "live" if live else "core_dead"
    if book_state == "core_dead":
        return {}, {"book_state": book_state, "per_asset": per,
                    "reason": "core structurally dead (R57) — holding zero size, marking flat"}

    firing = [c for c in live if per[c]["core_engaged"] and per[c]["gate_open"]]
    w = {c: round(1.0 / len(live), 4) for c in firing}
    return w, {"book_state": book_state, "per_asset": per,
               "reason": f"{len(firing)}/{len(live)} live-core assets pass the C gate"}


# ── daily mark ────────────────────────────────────────────────────────────────
async def mark_and_rebalance(dry_run: bool = False) -> dict:
    """Daily NAV mark of the §5b book. Idempotent per calendar day. Marks flat days too."""
    from src.data.market.data_layer import _redis_get, _redis_set
    today = dt.date.today()
    data = await _fetch_daily(UNIVERSE)
    if not data:
        return {"status": "skipped", "reason": "no_market_data"}

    core = await _live_core()
    w_tgt, diag = target_weights(data, core)
    last_px = {c: float(d["close"][-1]) for c, d in data.items()}

    state = await _redis_get(_STATE_KEY)
    if not isinstance(state, dict) or "nav" not in state:
        state = {"inception": today.isoformat(), "nav": 1.0, "weights": w_tgt,
                 "mark_prices": last_px, "last_mark": today.isoformat(),
                 "core_name": core.get("name", "v5c")}
        if not dry_run:
            await _redis_set(_STATE_KEY, state, ttl=0)
            await _write_nav(today, 1.0, 0.0, w_tgt, 0.0, diag, core)
        return {"status": "inception", "nav": 1.0, "book_state": diag["book_state"],
                "n": len(w_tgt), "date": today.isoformat()}

    if state.get("last_mark") == today.isoformat():
        return {"status": "already_marked", "nav": state["nav"], "date": today.isoformat()}

    w_held, mp = state.get("weights", {}) or {}, state.get("mark_prices", {}) or {}
    price_pnl = 0.0
    for c, wi in w_held.items():
        if c in last_px and mp.get(c, 0) > 0:
            price_pnl += wi * (last_px[c] / mp[c] - 1.0)

    turn = sum(abs(w_tgt.get(c, 0.0) - w_held.get(c, 0.0)) for c in set(w_tgt) | set(w_held))
    cost = _FEE * turn
    daily_ret = price_pnl - cost
    nav = float(state["nav"]) * (1.0 + daily_ret)

    state = {**state, "nav": nav, "weights": w_tgt, "mark_prices": last_px,
             "last_mark": today.isoformat(), "core_name": core.get("name", "v5c")}
    if not dry_run:
        await _redis_set(_STATE_KEY, state, ttl=0)
        await _write_nav(today, nav, daily_ret, w_tgt, cost, diag, core)
    return {"status": "marked", "nav": round(nav, 5),
            "daily_return_pct": round(daily_ret * 100, 3),
            "book_state": diag["book_state"], "gross": round(sum(abs(x) for x in w_tgt.values()), 3),
            "n": len(w_tgt), "date": today.isoformat()}


async def _write_nav(d, nav, dret, weights, cost, diag, core):
    from src.api.store import supabase_insert_table
    try:
        await supabase_insert_table("two_layer_paper_nav", [{
            "mark_date": d.isoformat(), "nav": round(nav, 6), "daily_return": round(dret, 6),
            "gross": round(sum(abs(x) for x in weights.values()), 4),
            "n_positions": len(weights), "cost": round(cost, 6),
            # S-122. `core_name` defaulted to "v5c": an unnamed core would attribute
            # this NAV mark to a specific model version that may not be what ran, and
            # the whole point of the column is knowing which core produced the curve.
            "book_state": diag.get("book_state"), "core_name": core.get("name"),
            # "FLAT" claimed a deliberate flat book. An empty weights dict can also
            # mean the weighting failed, and the two must stay distinguishable —
            # n_positions carries the count, book_state carries the reason.
            "positions": ",".join(f"{k}:{v:+.2f}" for k, v in sorted(weights.items())) or None,
            "note": diag.get("reason", "")[:200]}])
    except Exception as e:
        _log.warning("[two_layer] nav write: %s", e)


async def get_curve(limit: int = 400) -> dict:
    """NAV curve + honest summary for the endpoint (incl. how much of the life was flat)."""
    import os
    import httpx
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_KEY", "")
    if not (url and key):
        return {"status": "skipped"}
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(f"{url}/rest/v1/two_layer_paper_nav",
                            params={"select": "mark_date,nav,daily_return,gross,book_state,"
                                              "core_name,positions,note",
                                    "order": "mark_date.asc", "limit": str(limit)},
                            headers={"apikey": key, "Authorization": f"Bearer {key}"})
            rows = r.json() if r.status_code == 200 else []
    except Exception as e:
        return {"status": "error", "error": str(e)[:120]}
    if not rows:
        return {"status": "no_data", "note": "§5b paper book not yet marked"}

    navs = [x["nav"] for x in rows]
    rets = [x["daily_return"] for x in rows if x.get("daily_return") is not None]
    engaged = [x for x in rows if (x.get("gross") or 0) > 0]
    sharpe = (float(np.mean(rets) / np.std(rets) * np.sqrt(365))
              if len(rets) > 5 and np.std(rets) > 0 else None)
    peak = np.maximum.accumulate(navs)
    dd = float((peak - navs).max() / peak.max()) if navs else 0.0
    return {"status": "ok", "days": len(rows), "inception": rows[0]["mark_date"],
            "nav": navs[-1], "return_pct": round((navs[-1] / navs[0] - 1) * 100, 2),
            "ann_sharpe": round(sharpe, 2) if sharpe else None,
            "max_dd_pct": round(dd * 100, 2),
            "days_engaged": len(engaged), "days_flat": len(rows) - len(engaged),
            "engagement_pct": round(100.0 * len(engaged) / len(rows), 1),
            "core_name": rows[-1].get("core_name"), "latest": rows[-1], "curve": rows}


if __name__ == "__main__":
    import asyncio
    import json
    print(json.dumps(asyncio.run(mark_and_rebalance(dry_run=True)), indent=2))
