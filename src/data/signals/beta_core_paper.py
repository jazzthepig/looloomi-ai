"""
Beta Core Book — the ① layer's live forward record (Seth, 2026-08-07).
=====================================================================

WHY THIS EXISTS. On 2026-08-07 an oversight review found that all five paper books
accruing a forward track record were long/short, gross ~1.0, market neutral — the ④
construction that CLAUDE.md says "discards beta by construction", that produced the
R76–R94 graveyard, and that S-103 and S-105 refuted again that same day. Layer ①,
which the return hierarchy calls the FoF core AND the benchmark every sleeve is
measured against, had **zero days of forward record**. Twenty-five days of the only
resource that cannot be accelerated had gone to the wrong construction.

WHAT IT RUNS.  ① hold the panel  ×  ③ time the total exposure.
  · equal-weight the coverage panel, long only, no shorts, no neutralisation
  · ex-ante volatility target (S-78: beats ex-post stops — Sharpe 0.79→1.01,
    DD −53.9%→−23.8%; and tightening a stop INCREASES cumulative drawdown through
    high-water resets)
  · the ⓠ regime override caps total exposure at one of {0.0, 0.5, 1.0, 1.3}

WHAT IT DELIBERATELY DOES NOT DO. No selection, no tilt, no shorting, no attempt to
be early to anything. S-106 measured why: return arrives in 0.8% of days and 45.9%
of a big day's move lands inside a four-hour window, so a book that tries to time
entry is arithmetically late. The same measurement showed big days CLUSTER 3.8x —
which is precisely why *staying in* is the capturable form of the same phenomenon.

THE BENCHMARK IS MARKED IN THE SAME ROW, every day. S-103 found `bench` was BTC on
7,706 of 7,743 outcome rows; re-benchmarking to hold-the-panel turned t=−12.42 into
t=−0.65 and flipped one tier's sign. A benchmark chosen at analysis time is one you
can choose wrong, so this book does not offer the choice: `benchmark_nav` is the
equal-weight panel at 1.0x gross, marked alongside, and excess is arithmetic.

State → Redis `beta_core:state`.  NAV → Supabase `beta_core_nav`.
"""
from __future__ import annotations

import datetime as dt
import logging

import numpy as np

_log = logging.getLogger("beta_core")
_STATE_KEY = "beta_core:state"
_FEE = 0.0005
_REBAL_DAYS = 7
_VOL_TARGET = 0.60          # annualised. Crypto panel realised vol runs 0.5–1.2.
_VOL_LOOKBACK = 30
_ALLOWED_CAPS = (0.0, 0.5, 1.0, 1.3)
_MAX_SCALAR = 1.3           # the vol scalar alone may never lever past the ③ ceiling


def _equal_weights(symbols: list[str]) -> dict[str, float]:
    """Layer ① in one line: hold the panel. No view, by design — the view lives in
    layer ③ (how much), never in layer ① (which)."""
    if not symbols:
        return {}
    w = 1.0 / len(symbols)
    return {s: w for s in symbols}


def _realized_vol(ret: np.ndarray, lookback: int = _VOL_LOOKBACK) -> float:
    """Annualised realised vol of the EQUAL-WEIGHT panel, not of a single asset —
    the book holds the panel, so the panel's vol is the risk being targeted."""
    if ret.shape[0] < lookback:
        return float("nan")
    panel = np.nanmean(ret[-lookback:], axis=1)
    sd = float(np.nanstd(panel))
    return sd * np.sqrt(365.0) if sd == sd else float("nan")


def _vol_scalar(rv: float) -> float:
    """Ex-ante vol target. NaN in ⇒ 1.0 out (I1: unmeasured is not zero, and it is
    also not an excuse to lever — an unknown vol gets the neutral scalar, never a
    large one)."""
    if rv != rv or rv <= 0:
        return 1.0
    return float(min(_VOL_TARGET / rv, _MAX_SCALAR))


# The canonical regime vocabulary is exactly these seven (cis_provider._CANONICAL_REGIMES).
# The FIRST version of this file mapped invented labels — CRISIS, CAPITULATION,
# EUPHORIA, EXPANSION, BULL, BEAR — none of which exist in that set. Measured on the
# live table: only RISK_OFF (40.2 % of days) and RISK_ON (12.3 %) ever matched, so
# **47.5 % of days silently fell through to full exposure** and layer ③ was inert
# without saying so. The invented names were half-remembered from EXPOSURE_BANDS_V1,
# which is a different vocabulary keyed off a different input — two label sets
# conflated, exactly like `asset_class` and `bench` before it.
_REGIME_CAP: dict[str, float] = {
    "RISK_OFF":    0.5,
    "TIGHTENING":  0.5,
    "STAGFLATION": 0.5,
    "NEUTRAL":     1.0,
    "EASING":      1.0,   # supportive but not a licence to lever
    "RISK_ON":     1.3,
    "GOLDILOCKS":  1.3,
}

# What actually decides the cap, in priority order. Recorded on every row so the ③
# claim is auditable rather than assumed:
#   'stablecoin_band' — the ⓠ spec's real driver (stablecoin supply Δ28d → 5-band
#                       hysteresis → EXPOSURE_BANDS_V1). NOT yet wired live: the
#                       research path reads a Mac-side JSON that Railway cannot see.
#   'regime_map'      — the seven canonical regimes above. Coarse on purpose.
#   'unmapped_regime' — a label outside the canonical set. Caps at 1.0 but says so,
#                       because a new regime name must never read as a neutral call.
#   'no_regime'       — the feed returned nothing.
# Collapsing the last two into 'regime_map' would make "③ never ran" indistinguishable
# from "③ ran and chose 1.0" — the same conflation as a -2 sentinel folded into 0.


def _exposure_cap(regime: str | None) -> tuple[float, str]:
    """③ layer. Returns (cap, source). Deliberately coarse: a continuous exposure
    function invites fitting, and the ⓠ spec's criterion is not Sharpe but 'did
    exposure come down in the first third of the drawdown'.

    HONEST STATE: the spec's real driver is the stablecoin-supply band, and its own
    frozen comment records that 2025-26 carries NO stablecoin signal by design — so
    during this forward window the cap would sit at 1.0 even with that path wired,
    and the book is effectively pure ①. Saying that in the row is worth more than a
    mapping that produces 1.0 for the wrong reason."""
    if not regime:
        return 1.0, "no_regime"
    r = str(regime).strip().upper().replace("-", "_").replace(" ", "_")
    if r in _REGIME_CAP:
        return _REGIME_CAP[r], "regime_map"
    return 1.0, "unmapped_regime"


async def _load_panel():
    from src.research.strategies.causal_positioning import DEFAULT_UNIVERSE, load_binance_panel
    s = dt.date.today() - dt.timedelta(days=120)
    _, close, fmean, fsum = load_binance_panel(DEFAULT_UNIVERSE, start=(s.year, s.month, s.day))
    ret = np.zeros_like(close)
    ret[1:] = np.nan_to_num((close[1:] - close[:-1]) / close[:-1])
    px = {DEFAULT_UNIVERSE[i]: float(close[-1, i]) for i in range(close.shape[1])}
    return DEFAULT_UNIVERSE, close, ret, px


_REGIME_DWELL_DAYS = 5   # see below; equals the gate's minimum holding period


async def _regime_history(days: int = 30) -> list[str]:
    """Last `days` days of daily-modal regime, oldest first.

    Reads Supabase because Redis holds only TODAY's value, and a dwell filter needs
    a history by construction. One small query per daily mark is affordable — this
    is the daily loop, not /health, which is contractually I/O-free."""
    import os

    import httpx
    base, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY")
    if not base or not key:
        return []
    since = (dt.date.today() - dt.timedelta(days=days + 5)).isoformat()
    url = (f"{base}/rest/v1/cis_scores?select=recorded_at,macro_regime"
           f"&recorded_at=gte.{since}&macro_regime=not.is.null"
           f"&order=recorded_at.asc&limit=20000")
    try:
        async with httpx.AsyncClient(timeout=8) as c:
            r = await c.get(url, headers={"apikey": key, "Authorization": f"Bearer {key}"})
            rows = r.json() if r.status_code == 200 else []
    except Exception as e:
        _log.warning("[beta_core] regime history unavailable: %s", e)
        return []
    from collections import Counter, defaultdict
    per_day: dict[str, Counter] = defaultdict(Counter)
    for row in rows:
        d = str(row.get("recorded_at", ""))[:10]
        raw = row.get("macro_regime")
        if d and raw:
            per_day[d][str(raw).strip().upper().replace("-", "_").replace(" ", "_")] += 1
    return [per_day[d].most_common(1)[0][0] for d in sorted(per_day)]


async def _current_regime() -> tuple[str | None, str | None]:
    """Returns (confirmed, raw). CONFIRMED is what sizes the book; RAW is recorded
    beside it so the filter's effect is visible rather than assumed.

    WHY THE FILTER (S-117/S-118). The raw label has a MEDIAN RUN OF 3 DAYS and 51 %
    of its runs last ≤3 days — more than half its "regime changes" revert inside
    three days. Sizing a book off that is a book overturned every three days. A
    causal 5-day dwell takes the median run to 19 days, which clears the gate's
    5-day minimum hold and makes the trigger legitimate for the first time.

    The dwell length is NOT tuned: it equals the minimum holding period the SHIP
    gate already requires, so it is a constraint imported from elsewhere rather
    than a parameter chosen against a return. Its cost is real and stated — every
    accepted switch is up to 4 days late, which for a de-risking trigger is four
    days of a drawdown taken at full size.

    Falls back to the Redis single value when history is unavailable: a gap in the
    NAV series is worse than a day sized off an unfiltered label, and the row says
    which path was taken."""
    from src.data.cis.cis_provider import canonical_regime
    raw: str | None = None
    try:
        from src.data.market.data_layer import _redis_get
        blob = await _redis_get("cis:local_scores")
        if isinstance(blob, dict):
            raw = canonical_regime(blob.get("macro_regime") or blob.get("regime"))
    except Exception as e:
        _log.warning("[beta_core] live regime unavailable: %s", e)

    hist = await _regime_history()
    if len(hist) >= _REGIME_DWELL_DAYS:
        from src.research.validation.state_persistence import dwell_filter
        if raw:
            hist = hist + [raw]          # today's live value closes the series
        confirmed = dwell_filter(hist, _REGIME_DWELL_DAYS)[-1]
        return canonical_regime(confirmed), raw
    return raw, raw                      # too little history to filter — say so by
                                         # returning them equal, not by silence


async def _recover_state_from_nav(px: dict) -> dict | None:
    """Rebuild book state from the durable NAV table after a Redis loss.

    Returns None only when Postgres has no history either — i.e. a genuine first
    run. Anything else is recovered, because the difference between "we never
    started" and "we lost the cache" is 60 days of gate progress and the two look
    identical from Redis alone.

    The recovered `mark_prices` are TODAY's, not the lost day's, so the missed span
    contributes no return rather than a fabricated one. That understates the curve
    slightly and is the correct direction to be wrong in: a gap that shows up as
    flat is auditable, a gap filled by interpolation is not.
    """
    import os

    import httpx
    base, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY")
    if not base or not key:
        return None
    url = (f"{base}/rest/v1/beta_core_nav?select=mark_date,nav,benchmark_nav,top_weights"
           f"&order=mark_date.desc&limit=1")
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(url, headers={"apikey": key, "Authorization": f"Bearer {key}"})
            rows = r.json() if r.status_code == 200 else []
    except Exception as e:
        _log.warning("[beta_core] state recovery read failed: %s", e)
        return None
    if not rows:
        return None
    last = rows[0]
    base_w = _equal_weights(list(px))
    return {
        "inception": last["mark_date"], "nav": float(last["nav"]),
        "benchmark_nav": float(last.get("benchmark_nav") or 1.0),
        "weights": base_w, "base_weights": base_w,
        "mark_prices": dict(px),
        "last_rebal": last["mark_date"], "last_mark": last["mark_date"],
        "recovered": True,
    }


async def mark_and_rebalance(dry_run: bool = False) -> dict:
    from src.data.market.data_layer import _redis_get, _redis_set
    today = dt.date.today()
    try:
        symbols, close, ret, px = await _load_panel()
    except Exception as e:
        return {"status": "error", "reason": str(e)[:120]}
    if len(px) < 5:
        return {"status": "skipped", "reason": "insufficient_live_data"}

    rv = _realized_vol(ret)
    scalar = _vol_scalar(rv)
    regime, regime_raw = await _current_regime()
    cap, cap_source = _exposure_cap(regime)
    # Record when the dwell filter actually CHANGED the decision. Without this the
    # row cannot distinguish "the filter did nothing today" from "the filter is not
    # running" — the same class as cap_source, and the reason the inert mapping in
    # S-116 stayed invisible for a whole first mark.
    if regime_raw is not None and regime != regime_raw:
        cap_source = f"{cap_source}+dwell{_REGIME_DWELL_DAYS}(raw={regime_raw})"
    base = _equal_weights([s for s in symbols if s in px])
    gross = min(scalar, cap) if cap > 0 else 0.0
    weights = {s: w * gross for s, w in base.items()}

    state = await _redis_get(_STATE_KEY)
    if not isinstance(state, dict) or not state.get("weights"):
        # Redis lost the state. Do NOT re-inception — rebuild from Postgres first.
        #
        # This book's entire value is calendar continuity: 60 forward days is the gate,
        # and a silent restart at NAV 1.0 would reset the clock while looking completely
        # healthy in the logs. That is S-105 exactly (the strategy library spent 12 days
        # in a 24h-TTL Redis key because nothing noticed the durable write failing), and
        # here it would be worse, because the lost thing is time rather than rows.
        # MEMORY says Supabase is the system of record; Redis is a cache. So treat it
        # as one: cache miss ⇒ read through, never ⇒ start over.
        state = await _recover_state_from_nav(px)
        if state is not None:
            _log.warning("[beta_core] redis state missing — recovered from beta_core_nav "
                         "(nav=%.6f, inception=%s)", state["nav"], state["inception"])
            if not dry_run:
                await _redis_set(_STATE_KEY, state, ttl=0)

    if not isinstance(state, dict) or not state.get("weights"):
        state = {"inception": today.isoformat(), "nav": 1.0, "benchmark_nav": 1.0,
                 "weights": weights, "base_weights": base,
                 "mark_prices": {s: px[s] for s in base if s in px},
                 "last_rebal": today.isoformat(), "last_mark": today.isoformat()}
        if not dry_run:
            await _redis_set(_STATE_KEY, state, ttl=0)
            await _write(today, 1.0, 1.0, 0.0, 0.0, cap, regime, scalar, rv,
                         len(weights), gross, 0.0, True, weights,
                         f"inception · cap_source={cap_source}")
        return {"status": "inception", "nav": 1.0, "gross": round(gross, 3),
                "regime": regime, "date": today.isoformat()}

    if state.get("last_mark") == today.isoformat():
        return {"status": "already_marked", "nav": state["nav"], "date": today.isoformat()}

    mp = state["mark_prices"]
    prev_w = state["weights"]
    prev_base = state.get("base_weights") or _equal_weights(list(mp))

    # BOOK leg and BENCHMARK leg are computed from the SAME prices on the SAME day.
    # Any divergence between them is exposure timing and nothing else, which is the
    # only claim layer ③ makes.
    book_ret = sum(w * (px[s] / mp[s] - 1.0) for s, w in prev_w.items()
                   if s in px and s in mp and mp[s] > 0)
    bench_ret = sum(w * (px[s] / mp[s] - 1.0) for s, w in prev_base.items()
                    if s in px and s in mp and mp[s] > 0)

    nav = state["nav"] * (1.0 + book_ret)
    bench_nav = state.get("benchmark_nav", 1.0) * (1.0 + bench_ret)

    last_rebal = dt.date.fromisoformat(state["last_rebal"])
    rebalanced, cost = False, 0.0
    # Rebalance on cadence OR when the exposure cap moves — a regime change is
    # precisely the moment the book is supposed to act, and waiting for the weekly
    # slot would defeat the only mechanism being tested.
    cap_changed = abs(sum(abs(v) for v in prev_w.values()) - gross) > 0.05
    if (today - last_rebal).days >= _REBAL_DAYS or cap_changed:
        turn = sum(abs(weights.get(s, 0.0) - prev_w.get(s, 0.0))
                   for s in set(weights) | set(prev_w))
        cost = _FEE * turn
        nav *= (1.0 - cost)
        rebalanced = True

    new_w = weights if rebalanced else prev_w
    state = {**state, "nav": nav, "benchmark_nav": bench_nav,
             "weights": new_w, "base_weights": base,
             "mark_prices": {s: px[s] for s in base if s in px},
             "last_rebal": today.isoformat() if rebalanced else state["last_rebal"],
             "last_mark": today.isoformat()}
    if not dry_run:
        await _redis_set(_STATE_KEY, state, ttl=0)
        await _write(today, nav, bench_nav, book_ret, bench_ret, cap, regime, scalar, rv,
                     len(new_w), sum(abs(v) for v in new_w.values()), cost, rebalanced,
                     new_w, f"cap_source={cap_source}")
    return {"status": "marked", "nav": round(nav, 5), "benchmark_nav": round(bench_nav, 5),
            "daily_return_pct": round(book_ret * 100, 3),
            "excess_pct": round((book_ret - bench_ret) * 100, 3),
            "exposure_cap": cap, "cap_source": cap_source, "regime": regime,
            "realized_vol_30d": round(rv, 3),
            "rebalanced": rebalanced, "date": today.isoformat()}


async def _write(d, nav, bench_nav, dret, bret, cap, regime, scalar, rv,
                 n, gross, cost, rebal, weights, note):
    from src.api.store import supabase_insert_table
    top = ",".join(f"{s}:{w:.3f}" for s, w in sorted(weights.items(), key=lambda kv: -kv[1])[:3])
    try:
        await supabase_insert_table("beta_core_nav", [{
            "mark_date": d.isoformat(), "nav": round(nav, 6),
            "benchmark_nav": round(bench_nav, 6),
            "daily_return": round(dret, 6), "benchmark_return": round(bret, 6),
            "excess_return": round(dret - bret, 6),
            "exposure_cap": cap, "regime": regime,
            "vol_target_scalar": round(scalar, 4),
            "realized_vol_30d": None if rv != rv else round(rv, 4),   # I1: NaN → null
            "n_positions": n, "gross": round(gross, 4), "cost": round(cost, 6),
            "rebalanced": rebal, "top_weights": top, "note": note}])
    except Exception as e:
        _log.warning("[beta_core] nav write: %s", e)


async def continuity_state() -> dict:
    """Is the clock actually running? For /health.

    A book whose only product is elapsed time fails by NOT WRITING, and a loop that
    catches its exception and sleeps 24h fails exactly that way — silently, with a
    green process and a log line nobody reads. So continuity is measured against the
    calendar rather than inferred from the absence of errors: `days_since_mark` and
    `missing_days` come from the durable table, not from in-process counters, because
    an in-process counter resets on the deploy that broke the marking.

    `gate_days_remaining` is included so that nobody reads a 20-day curve as evidence.
    """
    import datetime as _dt
    import os

    import httpx
    base, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY")
    if not base or not key:
        return {"configured": False}
    url = f"{base}/rest/v1/beta_core_nav?select=mark_date&order=mark_date.asc&limit=500"
    try:
        async with httpx.AsyncClient(timeout=8) as c:
            r = await c.get(url, headers={"apikey": key, "Authorization": f"Bearer {key}"})
            rows = r.json() if r.status_code == 200 else []
    except Exception as e:
        return {"configured": True, "error": str(e)[:120]}
    if not rows:
        return {"configured": True, "marks": 0, "started": False,
                "gate_days_remaining": 60,
                "note": "book has never marked — the clock is NOT running"}
    days = [_dt.date.fromisoformat(x["mark_date"]) for x in rows]
    span = (days[-1] - days[0]).days + 1
    since = (_dt.date.today() - days[-1]).days
    return {
        "configured": True, "marks": len(days), "started": True,
        "inception": days[0].isoformat(), "last_mark": days[-1].isoformat(),
        "days_since_mark": since,
        # calendar span minus rows written: the gap the process cannot see itself
        "missing_days": max(0, span - len(days)),
        "gate_days_remaining": max(0, 60 - len(days)),
        # one skipped day is a hiccup; two means the loop is not running
        "stalled": since >= 2,
    }


async def get_curve(limit: int = 400) -> dict:
    """Serve the curve WITH its benchmark. A layer-① curve shown without
    hold-the-panel beside it is unreadable — the whole question is the difference."""
    import os
    import httpx
    base, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY")
    if not base or not key:
        return {"rows": [], "error": "supabase_unconfigured"}
    url = (f"{base}/rest/v1/beta_core_nav?select=*&order=mark_date.asc&limit={limit}")
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(url, headers={"apikey": key, "Authorization": f"Bearer {key}"})
            rows = r.json() if r.status_code == 200 else []
    except Exception as e:
        return {"rows": [], "error": str(e)[:120]}
    if not rows:
        return {"rows": [], "days": 0}
    first, last = rows[0], rows[-1]
    cum = last["nav"] / first["nav"] - 1.0
    bcum = last["benchmark_nav"] / first["benchmark_nav"] - 1.0
    return {
        "rows": rows, "days": len(rows),
        "inception": first["mark_date"], "as_of": last["mark_date"],
        "total_return_pct": round(100 * cum, 3),
        "benchmark_return_pct": round(100 * bcum, 3),
        "excess_pct": round(100 * (cum - bcum), 3),
        # the gate is 60 forward days; surfacing the shortfall stops anyone reading a
        # 20-day curve as evidence
        "days_to_gate": max(0, 60 - len(rows)),
    }
