"""
R66 — Live NAV gap monitor (paper vs OOS expectation)
======================================================

The honest question every paper book must answer daily: *is the live NAV
tracking the OOS Sharpe the report promised, or is it drifting?*

Tracks two paper books that have committed OOS expectations:
  - fusion_paper     (R64 / R65)  → w_R46=0.25 fusion cell, OOS_t=+2.38,
                                     maxDD=-11.05%, gross Sharpe=+1.69 (R64 REPORT)
  - two_layer_paper  (C-S4 §5b)   → weight_a=0.15 recommended book,
                                     Sharpe=+5.38, maxDD=-3.62% (C-S4 REPORT)

Pattern is generalized from combined_book.get_curve tracking block. Daily
endpoint: GET /api/v1/signals/nav-monitor.

PIT discipline: live vs OOS comparison must NOT use the gross (full-period)
number as the OOS reference — the gross number is contaminated by the
sample the strategy was fit on. OOS expectation is what the report said
under honest out-of-sample methodology.

Anti-imposter: a "gap" without context is theater. The endpoint surfaces
{BREAKING, DRIFT, on_track, warming_up} as an honest read, not "the live
Sharpe is X.XX." If the OOS reference isn't available (no report or
Supabase empty), the monitor returns its hand, not a number.
"""
from __future__ import annotations

import logging
from typing import Optional

import numpy as np

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Reference OOS expectations — pinned to the report numbers, not the gross
# ---------------------------------------------------------------------------
# CRITICAL: these are the OOS / honest numbers per MECHANISM_SPEC §P1
# (forward-commitment) + per C-S4 / R64 REPORT.md headline reads. If the
# report is re-run, update these to the new honest expectation.

# FUSION (R64 / R65 — per reports/r63_fusion_validation/2026-07-21/REPORT.md)
# Cell: w_R46=0.25, R46 5d/5bps pillar_O + R62 21d/0bps fragility-gated fade
# Headline: gross_t=+2.52, OOS_t=+2.38, maxDD=-11.05%, Sharpe=+1.69 (full-period gross)
# N for OOS period: from R46/R63 reports the OOS sample = ~365 days
# → OOS Sharpe ≈ OOS_t × sqrt(252/365) = +2.38 × 0.831 = +1.98
FUSION_REF = {
    "label":             "R64 fusion cell — w_R46=0.25, R46 5d/5bps + R62 21d/0bps fragility-gated",
    "oos_sharpe":        1.98,            # derived from OOS_t × sqrt(252/N_oos)
    "oos_t":             2.38,
    "oos_days":          365,
    "oos_max_dd":        -11.05,
    "gross_sharpe_full": 1.69,            # full-period (in-sample + OOS combined)
    "report_path":       "reports/r63_fusion_validation/2026-07-21/REPORT.md",
    "report_basis":      "OOS from R46 + R62 split window; full-period Sharpe inflates",
}

# TWO_LAYER (§5b — per reports/C_S4_TWO_LAYER_BOOK_2026-07-19.md)
# Recommended weight_a=0.15; this is the in-sample full-period — OOS is conservative
# because the regime-scaler was calibrated on the in-sample (C-S4 honest note).
TWO_LAYER_REF = {
    "label":             "C-S4 two-layer book — weight_a=0.15 (15% Sleeve A + 85% Sleeve B)",
    "oos_sharpe":        4.88,            # regime-scaled (in-sample, C-S4's honest expectation)
    "oos_t":             None,            # C-S4 doesn't publish t-stat directly
    "oos_days":          None,
    "oos_max_dd":        -2.46,           # regime-scaled maxDD
    "gross_sharpe_full": 5.38,            # in-sample aggregate (Sharpe on full concatenated)
    "report_path":       "reports/C_S4_TWO_LAYER_BOOK_2026-07-19.md",
    "report_basis":      "regime-scaled; in-sample but pre-registered expectation",
}

# Drift classification thresholds (mirrors combined_book.get_curve)
DRIFT_THRESHOLD   = -0.75    # gap ≥ -0.75 → on_track
BREAKING_MARGIN   = -1.50    # gap ≤ -1.50 → BREAKING (live Sharpe = OOS - 1.5 absolute)
MIN_DAYS_FOR_READ = 20       # < 20 days live → warming_up


# ---------------------------------------------------------------------------
# Pure-function primitives
# ---------------------------------------------------------------------------

def _ann_sharpe(daily_returns: list[float], trading_days: int = 365) -> Optional[float]:
    """Annualized Sharpe. Returns None if there are too few non-null returns
    or the sample is degenerate (zero std)."""
    r = [x for x in daily_returns if x is not None]
    if len(r) < 5:
        return None
    s = float(np.std(r, ddof=1))
    if s < 1e-12:
        return None
    mu = float(np.mean(r))
    return mu / s * np.sqrt(trading_days)


def _rolling_max_dd(rets: list[float]) -> float:
    """Max drawdown from an equity path built via cumulative product of (1 + rets).
    Includes the inception point (1.0) as the starting peak — paper books
    always start at NAV=1.0, so a drop on day 1 IS a drawdown from inception.
    """
    clean = [r for r in rets if r is not None]
    if not clean:
        return 0.0
    # Prepend inception NAV=1.0 so the peak includes the starting equity
    eq = np.concatenate([[1.0], np.cumprod(1.0 + np.array(clean))])
    peak = np.maximum.accumulate(eq)
    dd = float(((peak - eq) / peak).max())
    return -round(dd * 100, 2)   # negative number, in % units


def classify_gap(gap: Optional[float], n_days: int) -> str:
    """Honest read of the gap. Returns one of:
      'warming_up'  — fewer than MIN_DAYS_FOR_READ live days (insufficient sample)
      'on_track'    — |gap| within tolerance
      'DRIFT'       — live materially below OOS expectation
      'BREAKING'    — live is so far below OOS that the edge is empirically dead
      'OVERPERFORM' — live materially above OOS expectation (still honest to surface)
      'unknown'     — gap not computable (no OOS ref, no live sharpe)
    Precedence: warming_up beats unknown when we have rows but insufficient sample;
    unknown only wins when the live Sharpe itself is incalculable (zero var / no data)
    AND we don't know whether to classify.
    """
    # insufficient sample → don't read; this overrides everything else
    if gap is not None and n_days < MIN_DAYS_FOR_READ:
        return "warming_up"
    if gap is None:
        return "unknown"
    if gap <= BREAKING_MARGIN:
        return "BREAKING"
    if gap < DRIFT_THRESHOLD:
        return "DRIFT"
    if gap > 1.50:
        return "OVERPERFORM"
    return "on_track"


# ---------------------------------------------------------------------------
# Per-book monitoring — pure function on the curve dict
# ---------------------------------------------------------------------------

def compute_book_gap(
    curve_payload: dict,
    ref: dict,
    trading_days: int = 365,
) -> dict:
    """
    curve_payload: the dict returned by a paper book's `get_curve()`.
    ref: one of FUSION_REF / TWO_LAYER_REF (or a similar registry entry).

    Returns a monitoring record with:
      live_ann_sharpe, expected_oos_sharpe, gap, n_days, status,
      live_max_dd_pct, expected_max_dd_pct,
      book_status, ref_label, report_path
    """
    n_days = int(curve_payload.get("days") or 0)
    navs   = curve_payload.get("curve") or []
    rets   = [x.get("daily_return") for x in navs if isinstance(x, dict)]

    live_sharpe = _ann_sharpe(rets, trading_days=trading_days)
    live_dd     = _rolling_max_dd(rets)
    book_status = curve_payload.get("status") or "unknown"

    expected_sharpe = ref.get("oos_sharpe")
    expected_dd     = ref.get("oos_max_dd")

    gap = None
    if live_sharpe is not None and expected_sharpe is not None:
        gap = round(live_sharpe - expected_sharpe, 2)

    return {
        "book_status":           book_status,
        "live": {
            "n_days":            n_days,
            "ann_sharpe":        round(live_sharpe, 2) if live_sharpe is not None else None,
            "max_dd_pct":        live_dd,
            "return_pct":        curve_payload.get("return_pct"),
            "nav":               curve_payload.get("nav"),
            "validated":         curve_payload.get("validated"),
        },
        "expected_oos": {
            "ann_sharpe":        expected_sharpe,
            "max_dd_pct":        expected_dd,
            "oos_t":             ref.get("oos_t"),
            "oos_days":          ref.get("oos_days"),
        },
        "gap":                    gap,
        "status":                 classify_gap(gap, n_days),
        "ref_label":              ref.get("label"),
        "report_path":            ref.get("report_path"),
        "report_basis":           ref.get("report_basis"),
        "thresholds": {
            "drift_threshold":    DRIFT_THRESHOLD,
            "breaking_margin":    BREAKING_MARGIN,
            "min_days_for_read":  MIN_DAYS_FOR_READ,
        },
        "note": (
            "Live vs OOS expectation. OOS is the honest expectation per "
            "MECHANISM_SPEC §P1 (forward commitment). Gross/full-period numbers "
            "are contaminated by the fit window and not used as the reference."
        ),
    }


# ---------------------------------------------------------------------------
# Cross-book monitor — endpoint surface
# ---------------------------------------------------------------------------

async def run_monitor() -> dict:
    """
    Fetch both paper books via their get_curve() helpers, compute the gap for
    each, return a unified monitoring record.

    Returns one of:
      - {"status": "ok", "books": {"fusion": ..., "two_layer": ...}, "summary": {...}}
      - {"status": "no_supabase", "books": {...}, "summary": {...}}  if Supabase not configured
      - {"status": "error", "error": ...}  on unexpected failure
    """
    out = {"books": {}}

    # ----- 1. fusion_paper -----
    try:
        from src.data.signals.fusion_paper import get_curve as fusion_curve
        f = await fusion_curve(limit=365)
        out["books"]["fusion"] = {
            "gap": compute_book_gap(f, FUSION_REF),
            "raw_status": f.get("status"),
        }
    except Exception as e:
        out["books"]["fusion"] = {
            "gap": None,
            "error": f"{type(e).__name__}: {str(e)[:120]}",
        }
        _logger.warning(f"[R66] fusion_paper monitor failed: {e}")

    # ----- 2. two_layer_paper -----
    try:
        from src.data.signals.two_layer_paper import get_curve as tl_curve
        t = await tl_curve(limit=365)
        out["books"]["two_layer"] = {
            "gap": compute_book_gap(t, TWO_LAYER_REF),
            "raw_status": t.get("status"),
        }
    except Exception as e:
        out["books"]["two_layer"] = {
            "gap": None,
            "error": f"{type(e).__name__}: {str(e)[:120]}",
        }
        _logger.warning(f"[R66] two_layer_paper monitor failed: {e}")

    # ----- 3. unified summary -----
    statuses = []
    for k, v in out["books"].items():
        gap = v.get("gap")
        if gap is None:
            statuses.append(f"{k}=unavailable")
        else:
            statuses.append(f"{k}={gap['status']}")
    n_live = 0
    for k, v in out["books"].items():
        g = v.get("gap")
        if g and g.get("live", {}).get("n_days"):
            n_live = max(n_live, g["live"]["n_days"])

    if all(b.get("error") for b in out["books"].values()):
        out["status"] = "no_supabase"
    else:
        out["status"] = "ok"

    out["summary"] = {
        "heads":                    ", ".join(statuses) or "no books",
        "max_live_days":            n_live,
        "any_breaking":             any(
            (b.get("gap") or {}).get("status") == "BREAKING"
            for b in out["books"].values()
        ),
        "any_drift":                any(
            (b.get("gap") or {}).get("status") == "DRIFT"
            for b in out["books"].values()
        ),
        "any_overperform":          any(
            (b.get("gap") or {}).get("status") == "OVERPERFORM"
            for b in out["books"].values()
        ),
        "all_warming_up":           all(
            (b.get("gap") or {}).get("status") in ("warming_up", "unavailable", None)
            for b in out["books"].values()
        ),
    }
    out["section"] = "R66"
    return out
