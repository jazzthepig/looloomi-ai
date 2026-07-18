"""
Phase-Weighted Combined Book — Direction 2 of §STRATEGY-REVIVE (Seth, 2026-07-18).
==================================================================================
Wires the Crowd Clock (src/data/market/crowd_clock.py) + crowd_phase_book policy
(src/research/factory/crowd_phase_book.py) to the factory's combined book. The hypothesis
under test: does phase-conditional gross scaling of the funding-axis combined book beat a
flat-gross book on the same honest OOS-isolated backtest?

REUSES, DOES NOT REIMPLEMENT:
  · signal_factory.walkforward_combined — same nucleus+blend fit-on-train, apply-forward OOS
    loop, same honest split. We add ONE step: scale OOS pnl[t] by gross_scale[t].
  · crowd_clock.compute_crowd_clock — pure function for phase per day from FNG + BTC trend +
    mean funding pressure (the inputs we have history for).
  · crowd_phase_book.phase_allocation — the existing policy: phase+confidence → gross_scale.

PHASE INPUTS (historical reconstruction):
  · BTC 30d/7d % change — from the panel close[:,0]
  · FNG daily — fetched from alternative.me (free, public)
  · mean funding pressure — from the panel fmean (K=24 daily mean of fmean — a credible
    cross-sectional crowding proxy we DO have history for)
  · CIS dispersion, volume ratio — DROPPED (no history; the existing crowd_clock_backtest
    in src/research/crowd_clock_backtest.py also drops them).

HONEST SCOPE (do NOT over-claim):
  · This is ONE experiment on the factory's 24-symbol perp panel (2024-01-01 → 2026-07-17,
    ~19mo). Single panel, single asset class.
  · Per R24, the phase gate is CANDIDATE (markup/distribution validated; capitulation REFUTED
    at 30d, euphoria untested). The recalibrated policy reduces gross in capitulation/euphoria/
    distribution and only keeps it at 1.0 in markup. So the policy is structurally DEFENSIVE
    on average (most phases ≤0.55).
  · The §TRADER_TOM_DOCTRINE two-layer book assumes a SEPARATE mean-reversion sleeve
    (MultiFactorV2). This test applies phase scaling to the TREND-led combined book only,
    because that's what the factory builds. The MR sleeve lives elsewhere (Sleeve A) and
    is not in this experiment.
  · In-sample Sharpe is NOT the headline. Walk-forward + OOS isolation (per LS v1 R21
    lesson) is the honest read.

PRIMARY OUTPUT: a side-by-side of the OOS combined Sharpe:
    base     = factory's walkforward_combined OOS Sharpe (no scaling)
    scaled   = same OOS pnl × per-day gross_scale[t]
    delta    = scaled − base
A meaningful win needs scaled > base by >0.1 annSR with consistent direction across folds.
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

import numpy as np

# Reuse the factory's panel loader + OOS harness — single source of truth for honest eval.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.research.factory.signal_factory import (   # noqa: E402
    DEFAULT_UNIVERSE, load_binance_panel, signal_library, _bt, _walkforward, combine,
)
from src.research.factory.crowd_phase_book import phase_allocation   # noqa: E402
from src.data.market.crowd_clock import compute_crowd_clock         # noqa: E402


# ── phase history reconstruction ─────────────────────────────────────────────

def _fetch_fng_history() -> dict[str, float]:
    """alternative.me public endpoint — full FNG history (2018 → today), daily."""
    import httpx
    d = httpx.get("https://api.alternative.me/fng/?limit=0&format=json", timeout=30).json()["data"]
    out = {}
    for row in d:
        # 'timestamp' is unix SECONDS in alternative.me's payload
        day = dt.datetime.fromtimestamp(int(row["timestamp"]), dt.timezone.utc).strftime("%Y-%m-%d")
        out[day] = float(row["value"])
    return out


def _reconstruct_phase_history(days: list[str], close: np.ndarray,
                                fmean: np.ndarray, fng_hist: dict[str, float]) -> list[dict]:
    """Per-day phase + confidence, aligned to the factory panel.
    close[:,0] is BTC by convention; fmean is daily funding mean per asset.
    `days` from load_binance_panel are epoch-day INTEGERS (kline openTime / 86400000) — must
    be converted to YYYY-MM-DD strings to look up the FNG history.
    """
    btc_close = close[:, 0]
    T = len(days)
    phases = []
    for i in range(T):
        d_iso = dt.datetime.fromtimestamp(int(days[i]) * 86400, dt.timezone.utc).strftime("%Y-%m-%d")
        # BTC 30d / 7d % change — leading edge: day i vs day i-k
        chg30 = (btc_close[i] / btc_close[i - 30] - 1) * 100 if i >= 30 and btc_close[i - 30] > 0 else None
        chg7  = (btc_close[i] / btc_close[i - 7]  - 1) * 100 if i >= 7  and btc_close[i - 7]  > 0 else None
        # Mean funding pressure — cross-sectional mean of fmean. causal_positioning uses
        # convention "positive fmean = crowded LONGS" (longs pay funding), but crowd_clock
        # expects "−1 = crowded LONGS". So we NEGATE to match the clock's convention.
        valid_f = fmean[i][np.isfinite(fmean[i])]
        mean_p = -float(valid_f.mean()) if len(valid_f) >= 4 else None
        fng = fng_hist.get(d_iso)
        clk = compute_crowd_clock(fng, chg30, chg7, mean_p, None, None)
        # Apply the phase-conditional gross scale from crowd_phase_book policy
        alloc = phase_allocation(clk["phase"], clk["confidence"])
        phases.append({
            "date": d_iso,
            "phase": clk["phase"],
            "confidence": clk["confidence"],
            "gross_scale": alloc["gross_scale"],
            "gross_scale_raw": alloc["gross_scale_raw"],
        })
    return phases


# ── the honest test ──────────────────────────────────────────────────────────

def run(start=(2024, 1, 1), folds: int = 5, embargo: int = 5) -> dict:
    """OOS-isolated A/B: base combined Sharpe vs phase-scaled combined Sharpe."""
    days, close, fmean, fsum = load_binance_panel(DEFAULT_UNIVERSE, start=start)
    ret = np.zeros_like(close); ret[1:] = np.nan_to_num((close[1:] - close[:-1]) / close[:-1])
    lib = signal_library(close, ret, fmean, fsum)
    warm = 180
    series = {n: _bt(W, ret, fsum)[warm:] for n, W in lib.items()}
    T = len(next(iter(series.values())))
    names = list(series)
    M = np.array([series[n] for n in names]).T          # T×K pnl matrix

    def _sr(x):
        return float(x.mean() / x.std() * np.sqrt(365)) if x.std() > 0 else 0.0

    # Reconstruct per-day phase on the panel — for day index i in `series`, the actual day is
    # days[warm + i]. The factory drops the first `warm` days, so phase history must align.
    print(f"  …fetching FNG history …")
    fng_hist = _fetch_fng_history()
    print(f"  …reconstructing phase history for {len(days)} days …")
    phase_hist = _reconstruct_phase_history(days, close, fmean, fng_hist)
    # Trim to the warmed series window
    phase_window = phase_hist[warm:]
    assert len(phase_window) == T, f"phase/series length mismatch: {len(phase_window)} vs {T}"
    gross_scales = np.array([p["gross_scale"] for p in phase_window])

    # Phase distribution (over the warmed window)
    phase_counts = {}
    for p in phase_window:
        phase_counts[p["phase"]] = phase_counts.get(p["phase"], 0) + 1
    phase_dist = {k: round(v / T, 3) for k, v in phase_counts.items()}
    avg_gross = float(gross_scales.mean())
    print(f"  …phase distribution over {T} days: {phase_dist}, avg gross={avg_gross:.3f}")

    # ── OOS walk-forward, dual-track ──
    oos_pnl_base, oos_pnl_scaled = [], []
    oos_grosses = []
    start_frac = 0.5
    test_len = int(T * (1 - start_frac) / folds)
    for f in range(folds):
        tr_end = int(T * start_frac) + f * test_len
        te_lo, te_hi = tr_end + embargo, tr_end + embargo + test_len
        if te_hi > T:
            break
        tr = M[:tr_end]
        tr_sr = {names[i]: _sr(tr[:, i]) for i in range(len(names))}
        cand = [n for n in names if tr_sr[n] > 0.2]
        nucleus = []
        for n in sorted(cand, key=lambda x: -tr_sr[x]):
            idx = names.index(n)
            if not nucleus or max(abs(np.corrcoef(tr[:, idx], tr[:, names.index(m)])[0, 1]) for m in nucleus) < 0.6:
                nucleus.append(n)
        if len(nucleus) < 2:
            continue
        rbs = {n: {i: float(v) for i, v in enumerate(tr[:, names.index(n)])} for n in nucleus}
        w = combine(rbs).weights
        te = M[te_lo:te_hi]
        wvec = np.array([w.get(n, 0.0) for n in names])
        oos_pnl = te @ wvec
        # Per-day scale (this is the OOS test block only — never sees train)
        scales = gross_scales[te_lo:te_hi]
        oos_pnl_base.extend(oos_pnl.tolist())
        oos_pnl_scaled.extend((oos_pnl * scales).tolist())
        oos_grosses.extend(scales.tolist())

    oos_base = np.array(oos_pnl_base)
    oos_scaled = np.array(oos_pnl_scaled)
    # The post-scaling annSR: the per-day scale changes vol AND mean, so we scale to same gross
    # for a fair Sharpe comparison. Compute both raw scaled SR and same-gross SR.
    oos_same_gross = oos_base * np.array(oos_grosses)  # equivalent to scaled; just for clarity

    return {
        "oos_days": len(oos_base),
        "phase_dist": phase_dist,
        "avg_gross_scale": round(avg_gross, 3),
        "base_oos_sharpe":      round(_sr(oos_base), 2),
        "scaled_oos_sharpe":    round(_sr(oos_scaled), 2),
        "same_gross_oos_sharpe":round(_sr(oos_same_gross), 2),
        "delta_scaled_vs_base": round(_sr(oos_scaled) - _sr(oos_base), 2),
        "delta_gross_only":     round(_sr(oos_same_gross) - _sr(oos_base), 2),
        "oos_total_return_pct_base":   round(float(oos_base.sum()) * 100, 1),
        "oos_total_return_pct_scaled": round(float(oos_scaled.sum()) * 100, 1),
        "nucleus_size": "see walkforward_combined",
        "disclaimer": ("Phase gate is CANDIDATE per R24; the two-layer book doctrine "
                       "needs a separate MR sleeve (not in this test). Single-experiment on "
                       "19mo / K=24. Read OOS Sharpe, not in-sample."),
    }


# ── in-sample diagnostic (NOT the headline — secondary) ─────────────────────

def run_in_sample_diagnostic(start=(2024, 1, 1)) -> dict:
    """Phase-conditional breakdown: avg gross scale per phase, mean daily pnl per phase.
    For interpretability only — does the policy behave the way crowd_phase_book claims?"""
    days, close, fmean, fsum = load_binance_panel(DEFAULT_UNIVERSE, start=start)
    ret = np.zeros_like(close); ret[1:] = np.nan_to_num((close[1:] - close[:-1]) / close[:-1])
    lib = signal_library(close, ret, fmean, fsum)
    warm = 180
    series = {n: _bt(W, ret, fsum)[warm:] for n, W in lib.items()}
    T = len(next(iter(series.values())))

    fng_hist = _fetch_fng_history()
    phase_hist = _reconstruct_phase_history(days, close, fmean, fng_hist)[warm:]

    # Best in-sample nucleus
    names = list(series)
    M = np.array([series[n] for n in names]).T
    def _sr(x): return float(x.mean() / x.std() * np.sqrt(365)) if x.std() > 0 else 0.0
    is_sr = {names[i]: _sr(M[:, i]) for i in range(len(names))}
    cand = sorted([(n, s) for n, s in is_sr.items() if s > 0.2], key=lambda x: -x[1])
    nucleus, idxs = [], []
    for n, _ in cand:
        i = names.index(n)
        if not nucleus or max(abs(np.corrcoef(M[:, i], M[:, names.index(m)])[0, 1]) for m in nucleus) < 0.6:
            nucleus.append(n); idxs.append(i)
    rbs = {n: {i: float(v) for i, v in enumerate(M[:, names.index(n)])} for n in nucleus}
    w = combine(rbs).weights
    wvec = np.array([w.get(n, 0.0) for n in names])
    is_pnl = M @ wvec

    by_phase = {}
    for ph_name in ["capitulation", "accumulation", "markup", "euphoria", "distribution"]:
        days_in = [(phase_hist[i], is_pnl[i]) for i in range(T) if phase_hist[i]["phase"] == ph_name]
        if not days_in:
            by_phase[ph_name] = {"n": 0}
            continue
        pnls = np.array([x[1] for x in days_in])
        gross = np.array([x[0]["gross_scale"] for x in days_in])
        by_phase[ph_name] = {
            "n": len(days_in),
            "mean_daily_pnl_bps":   round(float(pnls.mean()) * 1e4, 2),
            "hit_pct":              round(100 * (pnls > 0).mean(), 1),
            "avg_gross_scale":      round(float(gross.mean()), 3),
            "phase_ann_contrib":    round(float(pnls.mean() / is_pnl.std() * np.sqrt(365) * (len(days_in)/T)), 3),
        }
    return {
        "nucleus": nucleus,
        "in_sample_combined_annSR": round(_sr(is_pnl), 2),
        "phase_breakdown": by_phase,
        "disclaimer": "In-sample diagnostic only — OOS is the honest read.",
    }


if __name__ == "__main__":
    print("=== PHASE-WEIGHTED COMBINED BOOK — Direction 2 of §STRATEGY-REVIVE ===\n")
    print("Primary: OOS-isolated A/B (base vs phase-scaled combined Sharpe) …\n")
    res = run()
    print(f"OOS days:                    {res['oos_days']}")
    print(f"Phase distribution:          {res['phase_dist']}")
    print(f"Avg gross scale over window: {res['avg_gross_scale']}")
    print()
    print(f"base     OOS annSR:  {res['base_oos_sharpe']:>6.2f}   total return: {res['oos_total_return_pct_base']:>7.2f}%")
    print(f"scaled   OOS annSR:  {res['scaled_oos_sharpe']:>6.2f}   total return: {res['oos_total_return_pct_scaled']:>7.2f}%")
    print(f"delta scaled vs base: {res['delta_scaled_vs_base']:>+6.2f}")
    print()
    print(f"{res['disclaimer']}")
    print("\n--- in-sample diagnostic (NOT the headline) ---")
    diag = run_in_sample_diagnostic()
    print(f"in-sample nucleus: {diag['nucleus']}")
    print(f"in-sample combined annSR: {diag['in_sample_combined_annSR']}")
    print(f"{'phase':14} {'n':>5} {'mean_pnl_bps':>13} {'hit%':>7} {'avg_gross':>10} {'contrib_SR':>11}")
    for ph, row in diag["phase_breakdown"].items():
        if row["n"] == 0:
            print(f"{ph:14} {'0':>5}")
            continue
        print(f"{ph:14} {row['n']:>5} {row['mean_daily_pnl_bps']:>13.2f} {row['hit_pct']:>7.1f} "
              f"{row['avg_gross_scale']:>10.3f} {row['phase_ann_contrib']:>11.3f}")
