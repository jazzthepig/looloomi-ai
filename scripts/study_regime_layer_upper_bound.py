#!/usr/bin/env python3
"""
S-136 — What is the ③ regime layer WORTH, at its theoretical maximum?
=====================================================================

THE QUESTION S-135 LEFT OPEN. Holding the cap constant, a loose cap plus vol
targeting beat a tight one (ret/DD 0.580 at cap 1.3 vs 0.445 at cap 0.5). But the
real ③ does not hold the cap constant — it switches on the macro regime. So:
does switching add anything over the best constant policy?

WHY THIS RUNS WITHOUT THE REGIME LABELS. The obvious way to answer is to replay
our actual `daily_macro_regime` series, which lives in Supabase and is currently
unreachable (SUPABASE_KEY empty). Rather than substitute a plausible-looking
regime — the exact degraded-value pattern the S-122 guard exists to catch — this
asks a question that does not need them:

    give the switcher PERFECT FORESIGHT and see if it wins.

If an oracle that knows the future barely beats a constant cap, then no real
regime detector can help, because every real detector is strictly worse than the
oracle. An upper bound is a refutation tool: it can kill a whole design without
the data, though it can never confirm one.

THREE ORACLES, in increasing order of how much they cheat:

  vol-oracle      knows the realised vol of the NEXT 30 days and picks the cap
                  that a vol-based regime rule would want. This is the honest
                  bound on "perfect RISK-regime detection" — it is what our ③
                  claims to be, done flawlessly.
  drawdown-oracle knows whether the next 30 days contain a drawdown worse than
                  −10 % and de-risks if so. This is ⓠ's own stated criterion
                  ("did exposure come down in the first third of the drawdown"),
                  granted perfectly.
  return-oracle   knows the sign of the next 30 days' return. Absurd — this is
                  market timing, not regime detection — and included only to
                  bound the entire space. If even the DRAWDOWN oracle is close to
                  the constant policy, the gap to this one is the part of ③ that
                  was never about risk.

READING IT. The number that matters is return-per-drawdown against
hold-the-panel, because ③'s claim is not more return, it is the same beta with
less of the pain. `gap_to_oracle` is the headroom every future regime-detection
effort is competing for; if it is small, that effort is capped before it starts.

RUN (no credentials — reads Binance directly):
    python3 scripts/study_regime_layer_upper_bound.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.data.signals.beta_core_paper import (  # noqa: E402
    _MAX_SCALAR, _VOL_LOOKBACK, _VOL_TARGET, _realized_vol)
from scripts.study_har_rv_vs_trailing import (  # noqa: E402
    ANN, _max_drawdown, load_panel, panel_daily_returns, trailing_vol_series)

ALLOWED_CAPS = (0.5, 1.0, 1.3)      # beta_core_paper._ALLOWED_CAPS minus 0.0
HORIZON = 30                        # the window an oracle is allowed to see
DD_TRIGGER = -0.10


def _outcome(panel_ret: np.ndarray, gross: np.ndarray) -> dict:
    """PIT: today's return is earned on yesterday's exposure."""
    book = np.concatenate([[0.0], gross[:-1] * panel_ret[1:]])
    nav_b = np.cumprod(1.0 + book)
    nav_p = np.cumprod(1.0 + panel_ret)
    ann = 365.0 / panel_ret.size
    dd_b, dd_p = _max_drawdown(nav_b), _max_drawdown(nav_p)
    return {
        "mean_gross": float(np.mean(gross)),
        "total_pct": 100.0 * (nav_b[-1] - 1.0),
        "panel_pct": 100.0 * (nav_p[-1] - 1.0),
        "maxdd_pct": 100.0 * dd_b,
        "panel_maxdd_pct": 100.0 * dd_p,
        "vol_ann": float(np.std(book) * ANN),
        "ret_per_dd": float((nav_b[-1] ** ann - 1.0) / abs(dd_b or 1e-9)),
        "panel_ret_per_dd": float((nav_p[-1] ** ann - 1.0) / abs(dd_p or 1e-9)),
    }


def _scalar(vol_ann: np.ndarray) -> np.ndarray:
    with np.errstate(divide="ignore", invalid="ignore"):
        s = np.minimum(_VOL_TARGET / vol_ann, _MAX_SCALAR)
    return np.where(np.isfinite(s), s, 1.0)


def forward_vol(panel_ret: np.ndarray, h: int = HORIZON) -> np.ndarray:
    """Realised vol of days t+1 … t+h. THE FUTURE — oracle use only."""
    n = panel_ret.size
    out = np.full(n, np.nan)
    for t in range(n - h - 1):
        w = panel_ret[t + 1:t + 1 + h]
        if np.isfinite(w).sum() >= h // 2:
            out[t] = float(np.nanstd(w)) * ANN
    return out


def forward_dd(panel_ret: np.ndarray, h: int = HORIZON) -> np.ndarray:
    n = panel_ret.size
    out = np.full(n, np.nan)
    for t in range(n - h - 1):
        w = panel_ret[t + 1:t + 1 + h]
        if not np.isfinite(w).all():
            continue
        nav = np.cumprod(1.0 + w)
        out[t] = _max_drawdown(nav)
    return out


def forward_ret(panel_ret: np.ndarray, h: int = HORIZON) -> np.ndarray:
    n = panel_ret.size
    out = np.full(n, np.nan)
    for t in range(n - h - 1):
        w = panel_ret[t + 1:t + 1 + h]
        if np.isfinite(w).all():
            out[t] = float(np.prod(1.0 + w) - 1.0)
    return out


def main() -> int:
    try:
        symbols, ret = load_panel()
    except Exception as e:
        print(f"🔴 could not load the Binance panel: {e}")
        return 1
    panel = panel_daily_returns(ret)
    n = panel.size
    vol_ann = trailing_vol_series(panel)

    # Evaluate on the same test half S-135 used, so the two studies are comparable
    # and neither gets to pick its own window after seeing the answer.
    lo = int(n * 0.6)
    hi = n - HORIZON - 1

    m = np.isfinite(panel[lo:hi]) & np.isfinite(vol_ann[lo:hi])
    idx = np.arange(lo, hi)[m]
    r = panel[idx]
    sc = _scalar(vol_ann)[idx]

    fv = forward_vol(panel)[idx]
    fd = forward_dd(panel)[idx]
    fr = forward_ret(panel)[idx]

    print(f"panel: {len(symbols)} symbols × {n} days · "
          f"evaluating {r.size} days (test half, {HORIZON}d oracle horizon)")
    print(f"benchmark = hold the panel, gross 1.0 · caps {ALLOWED_CAPS}\n")

    rows: list[tuple[str, dict]] = []

    # ── constant-cap policies (what S-135 measured) ──────────────────────────
    for cap in ALLOWED_CAPS:
        rows.append((f"constant cap {cap}", _outcome(r, np.minimum(sc, cap))))

    # ── vol-oracle: perfect knowledge of the NEXT 30 days' realised vol ──────
    # It picks the cap a flawless risk-regime rule would want: de-risk into high
    # forward vol, allow the top cap into low forward vol. Thresholds are the
    # panel's own terciles rather than tuned numbers — a tuned oracle would be
    # measuring the tuning.
    q1, q2 = np.nanpercentile(fv, [33.3, 66.7])
    cap_vol = np.where(fv > q2, 0.5, np.where(fv < q1, 1.3, 1.0))
    rows.append(("ORACLE vol (30d fwd)", _outcome(r, np.minimum(sc, cap_vol))))

    # ── drawdown-oracle: ⓠ's own criterion, granted perfectly ────────────────
    cap_dd = np.where(fd < DD_TRIGGER, 0.5, 1.3)
    rows.append((f"ORACLE drawdown<{DD_TRIGGER:.0%}", _outcome(r, np.minimum(sc, cap_dd))))

    # ── return-oracle: bounds the whole space (this is market timing) ────────
    cap_ret = np.where(fr > 0, 1.3, 0.5)
    rows.append(("ORACLE return sign", _outcome(r, np.minimum(sc, cap_ret))))

    p = rows[0][1]
    print(f"  {'policy':<24} {'gross̄':>7} {'total':>9} {'maxDD':>8} "
          f"{'vol':>6} {'ret/DD':>7}")
    print(f"  {'hold the panel':<24} {1.000:>7.3f} {p['panel_pct']:>8.1f}% "
          f"{p['panel_maxdd_pct']:>7.1f}% {'':>6} {p['panel_ret_per_dd']:>7.3f}")
    for name, o in rows:
        print(f"  {name:<24} {o['mean_gross']:>7.3f} {o['total_pct']:>8.1f}% "
              f"{o['maxdd_pct']:>7.1f}% {o['vol_ann']:>6.2f} {o['ret_per_dd']:>7.3f}")

    best_const = max(rows[:len(ALLOWED_CAPS)], key=lambda kv: kv[1]["ret_per_dd"])
    vol_oracle = rows[len(ALLOWED_CAPS)][1]
    dd_oracle = rows[len(ALLOWED_CAPS) + 1][1]

    print("\n── WHAT THIS BOUNDS ──")
    bc_name, bc = best_const
    print(f"  best CONSTANT policy : {bc_name}  ret/DD {bc['ret_per_dd']:.3f}")
    for label, o in (("vol", vol_oracle), ("drawdown", dd_oracle)):
        gap = (o["ret_per_dd"] - bc["ret_per_dd"]) / abs(bc["ret_per_dd"])
        print(f"  {label:<8} oracle ceiling : ret/DD {o['ret_per_dd']:.3f}  "
              f"→ headroom {100*gap:+.1f}% over the best constant cap")

    gap_vol = (vol_oracle["ret_per_dd"] - bc["ret_per_dd"]) / abs(bc["ret_per_dd"])
    gap_dd = (dd_oracle["ret_per_dd"] - bc["ret_per_dd"]) / abs(bc["ret_per_dd"])
    print("\n── VERDICT ──")
    if max(gap_vol, gap_dd) < 0.10:
        print("  A PERFECT regime switcher gains <10% over a constant cap.")
        print("  Every real detector is strictly worse than the oracle, so the ③")
        print("  regime-cap layer cannot pay for itself no matter how good the")
        print("  detection gets. The headroom is the budget, and it is spent before")
        print("  anyone starts. Simplify ③ to vol targeting under a fixed cap and")
        print("  put the effort into ② instead.")
    else:
        print(f"  A perfect switcher gains {100*max(gap_vol, gap_dd):.0f}% over the best")
        print("  constant cap. That is the ENTIRE budget available to regime detection,")
        print("  and a real detector captures some fraction of it. Worth continuing")
        print("  only if our measured regime accuracy makes that fraction meaningful.")
    print("\n  Bounds: one panel, one split, 30d oracle horizon, terciles from the")
    print("  same window the oracle is scored on (which FLATTERS the oracle — the")
    print("  bound is therefore conservative in the right direction).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
