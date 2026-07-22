"""
R66 — Live NAV accrual monitoring for the R64 fusion paper book (Seth, 2026-07-21).
=====================================================================================

R65 deployed the fusion paper book. R66 is the missing piece: the daily judgment layer
that holds the deployed sleeve ACCOUNTABLE in real time, before the 60-day `validated`
flag flips true. Without it, the book accrues silently and we discover slippage at day
60. With it, we know every day whether the live curve is tracking its OOS expectation
and what the fragility detector is doing.

FIVE monitor surfaces (one per judgment the operator needs to make):

  1. **LIVE-vs-OOS SHARPE GAP** — `gap = live_ann_sharpe − r64_oos_ann_sharpe`.
     R64 forward reference is the OOS t-stat from the fusion verdict (+2.38 α_t over
     219 OOS days ≈ ann Sharpe proxy). Status: on_track (gap ≥ −0.75), DRIFT
     (gap < −0.75), WARMING_UP (<20 days).

  2. **DETECTOR FIRE-RATE** — what % of forward days has the fragility detector fired?
     R62 reference is 8.2% (fragile_hit_rate from the production cell). Persistent
     >30% fires means the live regime is structurally fragile — sleeve is correctly
     sitting at zero, but the cell may need retirement.

  3. **CAPACITY EVOLUTION** — distribution of `fill_ratio_overall` + `weighted_slippage_bps`
     across the live window. Status: ok (mean fill > 0.95, mean slip < 10bps),
     EROSION (mean fill 0.85-0.95 OR slip 10-20bps), BREACH (any day BREACHED OR
     mean fill < 0.85 OR slip > 20bps).

  4. **P3 LIFECYCLE EVENTS** — structured log of every meaningful state transition:
     DETECTOR_PERSISTENT_HIGH, FILL_RATIO_DROP, SLIPPAGE_BREACH, NAV_DRAWDOWN,
     INSUFFICIENT_DATA, BOOK_INCEPTION. These are the §P3 disclosures — what the
     book did, when, and why.

  5. **VALIDATION COUNTDOWN** — `days_remaining = max(0, 60 − n_days_marked)`. Honest
     "validated = false until 60 forward days" gate.

DATA:
  · Reads live NAV from Supabase `fusion_paper_nav` (R65's table).
  · Writes lifecycle events to Supabase `fusion_paper_lifecycle`.
  · Tracks state in Redis `fusion_paper:tracking` for fast endpoint reads.

This is a MONITOR — it does NOT retune, does NOT block the live book, does NOT
trigger trades. It emits information. The operator decides what to do with it.
"""
from __future__ import annotations

import datetime as dt
import logging
import os
from typing import Optional

import numpy as np

_log = logging.getLogger("fusion_paper_tracking")

# ── Persistence ──────────────────────────────────────────────────────────────
_LIFECYCLE_TABLE = "fusion_paper_lifecycle"
_NAV_TABLE = "fusion_paper_nav"
_STATE_KEY = "fusion_paper:tracking"

# ── R64 forward reference (from R64 verdict) ─────────────────────────────────
# OOS α_t = +2.38 over 219 OOS days. For a Sharpe proxy, we approximate ann Sharpe
# ≈ α_t / sqrt(219/365) — but the honest reading is: this is the BACKTEST OOS
# expectation we are tracking against, NOT a forecast. Use the t-stat directly.
R64_OOS_ALPHA_T = 2.38
R64_OOS_DAYS = 219
R64_OOS_ANN_SHARPE_PROXY = 1.69   # from R64 verdict (gross Sharpe at w=0.25)

# ── R62 detector reference (from R62 best cell) ─────────────────────────────
R62_DETECTOR_FIRE_RATE = 0.082    # 8.2% from R62 best cell hit-rate
R62_DETECTOR_HIGH_THRESHOLD = 0.30  # persistent 30%+ = structural fragility

# ── Capacity thresholds (from fill_attribution.py defaults) ──────────────────
CAP_FILL_OK = 0.95
CAP_FILL_EROSION = 0.85
CAP_SLIP_OK_BPS = 10.0
CAP_SLIP_EROSION_BPS = 20.0

# ── Validation gate ─────────────────────────────────────────────────────────
VALIDATION_MIN_DAYS = 60
WARMUP_MIN_DAYS = 20
SHARPE_GAP_DRIFT_THRESHOLD = -0.75  # gap < -0.75 → DRIFT


# ── Supabase helpers (lazy imports) ─────────────────────────────────────────
async def _read_nav_curve(limit: int = 400) -> list:
    """Read the live NAV curve from Supabase."""
    import httpx
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_KEY", "")
    if not (url and key):
        return []
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(f"{url}/rest/v1/{_NAV_TABLE}",
                            params={"select": "mark_date,nav,daily_return,gross,fill_ratio_overall,"
                                              "weighted_slippage_bps,capacity_status,"
                                              "detector_fired,n_positions",
                                    "order": "mark_date.asc", "limit": str(limit)},
                            headers={"apikey": key, "Authorization": f"Bearer {key}"})
            return r.json() if r.status_code == 200 else []
    except Exception as e:
        _log.warning("[tracking] nav read: %s", e)
        return []


async def _emit_lifecycle_event(event_type: str, payload: dict) -> bool:
    """Write a lifecycle event to Supabase. Best-effort."""
    from src.api.store import supabase_insert_table
    try:
        # Keep this as a JSON object so the migration's JSONB column remains queryable.
        await supabase_insert_table(_LIFECYCLE_TABLE, [{
            "event_date": dt.date.today().isoformat(),
            "event_type": event_type,
            "payload": payload,
        }])
        return True
    except Exception as e:
        _log.warning("[tracking] lifecycle emit: %s", e)
        return False


# ── Pure analysis primitives (testable, no I/O) ─────────────────────────────
def _live_sharpe(rets: list, periods_per_year: int = 365) -> Optional[float]:
    """Ann Sharpe from a list of daily returns. None if <5 non-null points."""
    arr = np.array([r for r in rets if r is not None], dtype=float)
    if len(arr) < 5 or arr.std() == 0:
        return None
    return float(arr.mean() / arr.std() * np.sqrt(periods_per_year))


def _sharpe_gap_status(live_sharpe: Optional[float], n_days: int) -> dict:
    """Compare live Sharpe to R64 OOS proxy. Status: on_track / DRIFT / WARMING_UP."""
    if n_days < WARMUP_MIN_DAYS or live_sharpe is None:
        return {"status": "WARMING_UP",
                "gap": None, "n_days": n_days,
                "warmup_threshold_days": WARMUP_MIN_DAYS,
                "note": f"need ≥{WARMUP_MIN_DAYS} days before gap is meaningful"}
    gap = live_sharpe - R64_OOS_ANN_SHARPE_PROXY
    status = "DRIFT" if gap < SHARPE_GAP_DRIFT_THRESHOLD else "on_track"
    return {"status": status, "gap": round(gap, 3), "n_days": n_days,
            "live_sharpe": round(live_sharpe, 3),
            "r64_oos_ann_sharpe_proxy": R64_OOS_ANN_SHARPE_PROXY,
            "drift_threshold": SHARPE_GAP_DRIFT_THRESHOLD}


def _detector_fire_status(detector_fired_series: list, n_days: int) -> dict:
    """Compare live detector fire-rate to R62 reference (8.2%)."""
    if n_days < WARMUP_MIN_DAYS or not detector_fired_series:
        return {"status": "WARMING_UP", "fire_rate": None, "n_days": n_days}
    fires = sum(1 for x in detector_fired_series if x)
    rate = fires / len(detector_fired_series)
    if rate > R62_DETECTOR_HIGH_THRESHOLD:
        status = "PERSISTENT_HIGH"
    elif rate > R62_DETECTOR_FIRE_RATE * 1.5:  # 1.5× reference = soft anomaly
        status = "elevated"
    else:
        status = "normal"
    return {"status": status,
            "fire_rate": round(rate, 4),
            "n_days": n_days,
            "n_fires": fires,
            "r62_reference": R62_DETECTOR_FIRE_RATE,
            "high_threshold": R62_DETECTOR_HIGH_THRESHOLD}


def _capacity_evolution(fill_ratios: list, slippages_bps: list, statuses: list,
                         n_days: int) -> dict:
    """Capacity health: distribution of fill ratio + slippage + capacity status."""
    if n_days < WARMUP_MIN_DAYS or not fill_ratios:
        return {"status": "WARMING_UP", "n_days": n_days}
    fill_clean = [f for f in fill_ratios if f is not None]
    slip_clean = [s for s in slippages_bps if s is not None]
    mean_fill = float(np.mean(fill_clean)) if fill_clean else None
    mean_slip = float(np.mean(slip_clean)) if slip_clean else None
    breach_days = sum(1 for s in statuses if s == "BREACHED")
    breach_rate = breach_days / max(1, n_days)

    if breach_days > 0 or (mean_fill is not None and mean_fill < CAP_FILL_EROSION) \
            or (mean_slip is not None and mean_slip > CAP_SLIP_EROSION_BPS):
        status = "BREACH"
    elif (mean_fill is not None and mean_fill < CAP_FILL_OK) \
            or (mean_slip is not None and mean_slip > CAP_SLIP_OK_BPS):
        status = "EROSION"
    else:
        status = "ok"
    return {
        "status": status,
        "n_days": n_days,
        "mean_fill_ratio": round(mean_fill, 4) if mean_fill is not None else None,
        "mean_weighted_slippage_bps": round(mean_slip, 2) if mean_slip is not None else None,
        "max_weighted_slippage_bps": round(float(max(slip_clean)), 2) if slip_clean else None,
        "breach_days": breach_days,
        "breach_rate": round(breach_rate, 4),
        "status_distribution": {s: sum(1 for x in statuses if x == s)
                                 for s in set(statuses) if s},
    }


def _validation_countdown(n_days: int) -> dict:
    """Days remaining until the §P3 `validated` flag flips true."""
    return {
        "n_days_marked": n_days,
        "validation_threshold_days": VALIDATION_MIN_DAYS,
        "days_remaining": max(0, VALIDATION_MIN_DAYS - n_days),
        "validated": n_days >= VALIDATION_MIN_DAYS,
        "validation_pct": round(100.0 * n_days / VALIDATION_MIN_DAYS, 1),
    }


def _max_drawdown_pct(navs: list) -> Optional[float]:
    """Max DD as negative %. None if no data."""
    if not navs:
        return None
    arr = np.array(navs, dtype=float)
    peak = np.maximum.accumulate(arr)
    dd = arr / peak - 1.0
    return float(dd.min() * 100.0)


def detect_lifecycle_events(snapshot: dict, prev_snapshot: Optional[dict] = None) -> list:
    """Inspect a monitoring snapshot; emit structured P3 lifecycle events.

    Returns a list of {event_type, payload} dicts ready for Supabase insert.
    """
    events: list = []
    today = dt.date.today().isoformat()
    prev = prev_snapshot or {}

    def _status_changed(surface: str, status: str) -> bool:
        """Emit alert-like lifecycle events once per status transition."""
        previous = prev.get(surface, {}).get("status")
        return previous != status

    # ── WARMING_UP: book hasn't reached warmup threshold yet
    if (snapshot.get("sharpe_gap", {}).get("status") == "WARMING_UP"
            and _status_changed("sharpe_gap", "WARMING_UP")):
        events.append({"event_type": "WARMING_UP",
                       "payload": {"n_days": snapshot["validation_countdown"]["n_days_marked"],
                                   "warmup_threshold_days": WARMUP_MIN_DAYS,
                                   "note": "live NAV not yet warm — tracking uninformative"}})

    # ── BOOK_INCEPTION: first mark
    v = snapshot.get("validation_countdown", {})
    if v.get("n_days_marked") == 1:
        events.append({"event_type": "BOOK_INCEPTION",
                       "payload": {"date": today,
                                   "cell": snapshot.get("r64_cell_reference"),
                                   "declared_capacity_usd": snapshot.get("declared_capacity_usd")}})

    # ── DETECTOR_PERSISTENT_HIGH: detector fires >30% (vs R62 ref 8.2%)
    d = snapshot.get("detector_fire", {})
    if (d.get("status") == "PERSISTENT_HIGH"
            and _status_changed("detector_fire", "PERSISTENT_HIGH")):
        events.append({"event_type": "DETECTOR_PERSISTENT_HIGH",
                       "payload": {"fire_rate": d["fire_rate"],
                                   "reference": d["r62_reference"],
                                   "threshold": d["high_threshold"],
                                   "n_days": d["n_days"],
                                   "interpretation": "live regime structurally fragile — "
                                                      "sleeve correctly holding zero, but cell may need retirement"}})

    # ── CAPACITY_BREACH: any day hit BREACH status
    c = snapshot.get("capacity", {})
    if c.get("status") == "BREACH" and _status_changed("capacity", "BREACH"):
        events.append({"event_type": "CAPACITY_BREACH",
                       "payload": {"breach_days": c["breach_days"],
                                   "breach_rate": c["breach_rate"],
                                   "mean_fill": c.get("mean_fill_ratio"),
                                   "mean_slip_bps": c.get("mean_weighted_slippage_bps"),
                                   "interpretation": "fill-attribution surfacing capacity ceiling — "
                                                      "review declared capacity vs live ADV"}})

    # ── SHARPE_DRIFT: live Sharpe materially below OOS expectation
    s = snapshot.get("sharpe_gap", {})
    if s.get("status") == "DRIFT" and _status_changed("sharpe_gap", "DRIFT"):
        events.append({"event_type": "SHARPE_DRIFT",
                       "payload": {"gap": s["gap"],
                                   "live_sharpe": s.get("live_sharpe"),
                                   "oos_sharpe_ref": s.get("r64_oos_ann_sharpe_proxy"),
                                   "n_days": s["n_days"],
                                   "drift_threshold": s.get("drift_threshold"),
                                   "interpretation": "live curve materially below OOS expectation — "
                                                      "investigate before cell credibility erodes"}})

    # ── VALIDATED: 60 days hit for the first time
    if v.get("validated") and not prev.get("validation_countdown", {}).get("validated"):
        events.append({"event_type": "VALIDATED",
                       "payload": {"date": today, "n_days": v["n_days_marked"],
                                   "live_sharpe": s.get("live_sharpe"),
                                   "max_dd_pct": snapshot.get("max_dd_pct"),
                                   "interpretation": "§P3 lifecycle gate cleared — cell credit-eligible "
                                                      "for live deployment decision"}})

    return events


# ── Master monitor: reads NAV, computes snapshot, returns full report ───────
async def compute_tracking_snapshot() -> dict:
    """Read the live NAV curve, build the full monitoring snapshot."""
    rows = await _read_nav_curve()
    n_days = len(rows)

    rets = [r.get("daily_return") for r in rows]
    navs = [r.get("nav") for r in rows if r.get("nav") is not None]
    fires = [bool(r.get("detector_fired")) for r in rows]
    fills = [r.get("fill_ratio_overall") for r in rows]
    slips = [r.get("weighted_slippage_bps") for r in rows]
    statuses = [r.get("capacity_status") for r in rows]

    live_sharpe = _live_sharpe(rets)

    snapshot = {
        "as_of": dt.date.today().isoformat(),
        "r64_cell_reference": {
            "w_R46": 0.25,
            "r46_cad": 5, "r46_bps": 5.0,
            "r62_cad": 21, "r62_bps": 0.0,
            "r62_zwin": 30, "r62_z": 0.5, "r62_mf": 2,
            "r62_features": "external",
            "oos_alpha_t": R64_OOS_ALPHA_T,
            "oos_ann_sharpe_proxy": R64_OOS_ANN_SHARPE_PROXY,
            "oos_days": R64_OOS_DAYS,
        },
        "declared_capacity_usd": 5_000_000.0,
        "validation_countdown": _validation_countdown(n_days),
        "sharpe_gap": _sharpe_gap_status(live_sharpe, n_days),
        "detector_fire": _detector_fire_status(fires, n_days),
        "capacity": _capacity_evolution(fills, slips, statuses, n_days),
        "max_dd_pct": round(_max_drawdown_pct(navs), 3) if navs else None,
        "n_engaged_days": sum(1 for r in rows if (r.get("gross") or 0) > 0),
        "n_flat_days": sum(1 for r in rows if (r.get("gross") or 0) == 0),
        "engagement_pct": round(100.0 * sum(1 for r in rows if (r.get("gross") or 0) > 0) / max(1, n_days), 1),
    }

    # Read previous snapshot for transition detection
    prev_snapshot = None
    try:
        from src.api.store import redis_get_key
        prev_snapshot = await redis_get_key(_STATE_KEY)
    except Exception:
        pass

    # Detect lifecycle events + emit
    events = detect_lifecycle_events(snapshot, prev_snapshot)
    snapshot["lifecycle_events"] = events
    for ev in events:
        await _emit_lifecycle_event(ev["event_type"], ev["payload"])

    # Persist this snapshot as the new prev state
    try:
        from src.api.store import redis_set_key
        await redis_set_key(_STATE_KEY, snapshot, ttl=0)
    except Exception as e:
        _log.warning("[tracking] state save: %s", e)

    return snapshot


# ── Self-test ────────────────────────────────────────────────────────────────
def _self_test() -> int:
    """Pure-function self-tests; no I/O, no Supabase, no Redis."""
    # 1. Live Sharpe: flat → None for std=0
    s = _live_sharpe([0.0] * 10)
    assert s is None
    # Random returns → finite Sharpe
    s2 = _live_sharpe([0.01, -0.005, 0.002, 0.001, -0.003, 0.004, -0.001, 0.0, 0.002, -0.002])
    assert s2 is not None and isinstance(s2, float)

    # 2. Sharpe gap: < 20 days = WARMING_UP
    g1 = _sharpe_gap_status(None, 10)
    assert g1["status"] == "WARMING_UP"
    g2 = _sharpe_gap_status(0.5, 50)
    assert g2["status"] == "DRIFT", f"gap {g2['gap']} should be DRIFT"
    g3 = _sharpe_gap_status(2.0, 50)
    assert g3["status"] == "on_track"

    # 3. Detector fire: empty/warmup
    d1 = _detector_fire_status([], 10)
    assert d1["status"] == "WARMING_UP"
    d2 = _detector_fire_status([False] * 100, 100)
    assert d2["status"] == "normal"
    d3 = _detector_fire_status([True] * 50 + [False] * 50, 100)
    assert d3["status"] == "PERSISTENT_HIGH", f"50% should be PERSISTENT_HIGH"

    # 4. Capacity evolution
    c1 = _capacity_evolution([], [], [], 10)
    assert c1["status"] == "WARMING_UP"
    c2 = _capacity_evolution([0.99] * 50, [5.0] * 50, ["ok"] * 50, 50)
    assert c2["status"] == "ok"
    c3 = _capacity_evolution([0.90] * 50, [12.0] * 50, ["ok"] * 50, 50)
    assert c3["status"] == "EROSION", f"fill=0.90 + slip=12 should be EROSION"
    c4 = _capacity_evolution([0.99] * 49 + [0.0], [5.0] * 50, ["ok"] * 49 + ["BREACHED"], 50)
    assert c4["status"] == "BREACH"

    # 5. Validation countdown
    v1 = _validation_countdown(0)
    assert v1["days_remaining"] == 60 and not v1["validated"]
    v2 = _validation_countdown(45)
    assert v2["days_remaining"] == 15 and not v2["validated"]
    v3 = _validation_countdown(60)
    assert v3["days_remaining"] == 0 and v3["validated"]

    # 6. Max DD
    dd = _max_drawdown_pct([1.0, 1.1, 1.2, 1.0, 0.95, 1.05])
    assert dd is not None and dd < 0  # should be negative

    # 7. Lifecycle events
    snap = {
        "validation_countdown": {"n_days_marked": 1},
        "sharpe_gap": {"status": "WARMING_UP"},
        "detector_fire": {"status": "PERSISTENT_HIGH", "fire_rate": 0.45,
                          "r62_reference": 0.082, "high_threshold": 0.30, "n_days": 80},
        "capacity": {"status": "ok", "breach_days": 0, "breach_rate": 0,
                     "mean_fill_ratio": 0.97, "mean_weighted_slippage_bps": 5.5},
        "r64_cell_reference": "...",
        "declared_capacity_usd": 5_000_000.0,
    }
    evs = detect_lifecycle_events(snap, None)
    types = {e["event_type"] for e in evs}
    assert "BOOK_INCEPTION" in types
    assert "DETECTOR_PERSISTENT_HIGH" in types
    assert "WARMING_UP" in types

    # 8. Transition event: previous was not validated, now is
    snap2 = dict(snap)
    snap2["validation_countdown"] = {"n_days_marked": 60, "validated": True}
    snap2["sharpe_gap"] = {"status": "on_track", "live_sharpe": 1.5}
    prev_snap = {"validation_countdown": {"validated": False}}
    evs2 = detect_lifecycle_events(snap2, prev_snap)
    types2 = {e["event_type"] for e in evs2}
    assert "VALIDATED" in types2, f"VALIDATED event missing on transition, got {types2}"

    print(f"✓ fusion_paper_tracking self-test OK "
          f"(live_sharpe={s2:.3f}, gap_DRAFT_45d={g2['gap']}, fire_PERSISTENT={d3['fire_rate']}, "
          f"validation_countdown_days={v2['days_remaining']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(_self_test())
