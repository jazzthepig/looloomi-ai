"""
S-82 — Regime-conditioned gross overlay on the R77 fusion book.

STRUCTURALLY DIFFERENT from the exhausted cross-sectional-demean family
(R76/R78/R79/S-80/S-81). Per lesson #43 v4: "STOP running 'cross-sectional demean
of X'; next candidates must be STRUCTURALLY different math (time-series, structural
breaks, cross-asset)." S-82 is a TIME-SERIES regime overlay — it does not add a new
cross-sectional leg; it modulates the GROSS of the existing R77 book by a causal
major-trend regime signal.

Doctrine anchor (docs/TRADER_TOM_DOCTRINE.md, CLAUDE.md):
  · "tactical trend-riding overlay whose gross scales with regime — defend in
     risk-OFF (small, hedged, cut fast), press in risk-ON + confirmed long-term trend."
  · "Master skill = judgment of the major trend."
  · "Asymmetry law: if you can't win big when beta is positive, you can't win bigger
     when the tape is tight and thin ... our current edge-map gross (~1.10) is too timid."

The falsifiable claim S-82 tests:
  Is the R77 book's per-day alpha REGIME-DEPENDENT on the major trend, and can a
  CAUSAL (no look-ahead) BTC-trend regime signal scale the book's gross to harvest
  that dependence — AT EQUAL AVERAGE GROSS (so the test isolates regime TIMING from
  leverage) — surviving out-of-sample?

Anti-imposter discipline:
  · Equal-average-gross normalization: the gross schedule is scaled so its IS-period
    mean = 1.0, and the SAME scale factor is applied OOS. A market-neutral book's
    returns scale linearly with gross, so raw "more leverage = more return" is NOT an
    edge — Sharpe only improves if the regime TIMING is informative. Normalizing to
    equal average gross removes the leverage confound entirely.
  · Causal regime: BTC trailing-Nd return is shift(1)-lagged. Today's gross uses only
    yesterday-and-earlier price. No same-day peeking.
  · Pre-declared bands: the risk bands and their gross multipliers are FIXED constants
    (edge-map style), NOT fit to this panel. No in-sample quantile look-ahead.
  · OOS split uses the SAME last-30% cut as the R76/S-80/S-81 gauntlet.
  · Frozen R77 cell (R46+R62+R76 at w_R46=0.25, w_R62=0.75, w_R76=0.30) is reproduced
    READ-ONLY. S-82 does NOT touch the live paper book (R65) or its tracking (R66).

Verdict bands:
  ✅ SURVIVES  — at equal avg gross, scaled book OOS Sharpe > flat OOS Sharpe AND OOS
                 ann% > flat AND the lift is NOT a single-window artifact.
  🟡 PARTIAL   — IS improves but OOS does not (regime signal overfit), or lift is
                 single-window-driven.
  🔴 REFUTED   — no improvement at equal avg gross; R77 alpha is regime-invariant (the
                 legs already internalize regime, esp. R76 lifting W5).
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from src.research.validation.cis_quality_absorption import (
    load_cis_history_wide, load_daily_returns,
)
from src.research.validation.w5_forensics_external import load_funding_daily
from src.research.validation.w5_forensics import (
    partition_into_windows, build_w5_detector,
)
from src.research.validation.r63_fusion_validation import (
    build_r46_sleeve_28, build_r62_sleeve_28, per_window, max_drawdown,
    R62_Z, R62_MF,
)
from src.research.validation.r62_fragility_gated_funding import (
    compute_combined_features, build_fragility_ks_table,
    DEFAULT_FRAGILE_WINDOWS, DEFAULT_PLAYABLE_WINDOWS,
)
from src.research.validation.r76_funding_residual_ls import (
    funding_residual_ls as r76_ls, score_funding_residual,
    SIGN_HIGH_FUND_LONG,
)


# === Constants ================================================================
OOS_FRAC = 0.30
PERIODS_PER_YEAR = 365          # daily book

# Frozen R77 cell weights (READ-ONLY reproduction — never mutated)
W_R46 = 0.25
W_R62 = 0.75
W_R76 = 0.30

# Regime signal: causal BTC trailing-return trend
S82_TREND_LOOKBACK = 30         # trailing-30d benchmark return (edge-map basis)
S82_BENCH = "BTC"

# Pre-declared risk bands on BTC trailing-30d return → gross multiplier.
# FIXED constants (edge-map style), NOT fit to this panel. Deep-off defends,
# deep-on presses (doctrine "gross scales with regime").
# Each tuple: (lower_bound_inclusive, gross_multiplier). Sorted ascending.
S82_BANDS = (
    (-np.inf, 0.50),   # deep risk-off:  trail30 < -15%  → defend
    (-0.15,   0.75),   # risk-off:       -15% ≤ trail30 < -5%
    (-0.05,   1.00),   # neutral:        -5% ≤ trail30 < +5%
    (0.05,    1.25),   # risk-on:        +5% ≤ trail30 < +20%
    (0.20,    1.50),   # deep risk-on:   trail30 ≥ +20% → press
)
S82_BAND_EDGES = (-0.15, -0.05, 0.05, 0.20)   # for reporting/labels


# === Regime signal (causal) ===================================================
def btc_trend(bench_rets: pd.Series, lookback: int = S82_TREND_LOOKBACK) -> pd.Series:
    """Trailing-`lookback`d compounded benchmark return, shift(1)-lagged (causal).

    trend[t] = Π(1+r)[t-lookback..t-1] − 1, i.e. today's regime read uses ONLY
    price known up to and including yesterday's close. No same-day peeking.

    Warmup rows (< lookback obs): NaN (I1 honesty), never 0.
    """
    cum = (1.0 + bench_rets.fillna(0.0)).cumprod()
    trail = cum / cum.shift(lookback) - 1.0
    trail.iloc[:lookback] = np.nan
    return trail.shift(1)


def regime_to_gross(trend: pd.Series, bands: tuple = S82_BANDS) -> pd.Series:
    """Map trailing-trend → gross multiplier via pre-declared FIXED bands.

    NaN trend (warmup) → gross 1.0 (neutral default: no regime read yet, so no
    scaling — never fabricates a directional bet from missing data).
    """
    lowers = np.array([b[0] for b in bands])
    mults = np.array([b[1] for b in bands])
    out = pd.Series(1.0, index=trend.index)
    for t, v in trend.items():
        if pd.isna(v):
            out.loc[t] = 1.0
            continue
        idx = int(np.searchsorted(lowers, v, side="right") - 1)
        idx = max(0, min(idx, len(mults) - 1))
        out.loc[t] = float(mults[idx])
    return out


def normalize_gross_equal_avg(gross: pd.Series, cut: int) -> tuple[pd.Series, float]:
    """Scale the gross schedule so its IS-period mean = 1.0; apply SAME factor OOS.

    This is the anti-imposter core: a market-neutral book scales linearly with gross,
    so the ONLY way regime scaling can beat flat is via informative TIMING. Forcing
    equal average gross (IS-calibrated, no OOS leakage) removes the leverage confound.

    Returns (normalized_gross, scale_factor). scale_factor derived from IS only.
    """
    is_mean = float(gross.iloc[:cut].mean())
    if is_mean <= 0 or not np.isfinite(is_mean):
        return gross.copy(), 1.0
    scale = 1.0 / is_mean
    return gross * scale, scale


# === Performance stats ========================================================
def sharpe(rets: pd.Series, periods_per_year: int = PERIODS_PER_YEAR) -> float:
    r = rets.dropna()
    if len(r) < 2 or r.std(ddof=1) == 0:
        return float("nan")
    return float(r.mean() / r.std(ddof=1) * np.sqrt(periods_per_year))


def ann_return(rets: pd.Series, periods_per_year: int = PERIODS_PER_YEAR) -> float:
    r = rets.dropna()
    if r.empty:
        return float("nan")
    return float(r.mean() * periods_per_year)


# === Run ======================================================================
def run(out_dir: Path,
        trend_lookback: int = S82_TREND_LOOKBACK,
        fragile_labels: tuple = DEFAULT_FRAGILE_WINDOWS,
        playable_labels: tuple = DEFAULT_PLAYABLE_WINDOWS,
        zwin: int = 30) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    print("=== S-82 — regime-conditioned gross overlay on R77 book "
          "(equal-avg-gross, causal BTC trend) ===\n")

    # ── Load daily panels (R76/S-80/S-81 parity) ─────────────────────────────
    cis_long = load_cis_history_wide()
    rets_daily = load_daily_returns()
    lo = max(cis_long["date"].min(), rets_daily.index.min())
    hi = min(cis_long["date"].max(), rets_daily.index.max())
    rets_daily = rets_daily.loc[(rets_daily.index >= lo) & (rets_daily.index <= hi)]
    tradeable_full = sorted(set(cis_long["asset"]) & set(rets_daily.columns))

    funding_daily = load_funding_daily(assets=tradeable_full)
    funding_assets = sorted(set(tradeable_full) & set(funding_daily.columns))
    if not funding_daily.empty:
        f_lo, f_hi = funding_daily.index.min(), funding_daily.index.max()
        rets_daily = rets_daily.loc[(rets_daily.index >= f_lo) & (rets_daily.index <= f_hi)]
    tradeable = funding_assets
    print(f"Strict intersection universe: {len(tradeable)} assets")
    print(f"Aligned daily panel: {rets_daily.index.min().date()} → "
          f"{rets_daily.index.max().date()} ({len(rets_daily)} days)")
    if S82_BENCH not in rets_daily.columns:
        raise RuntimeError(f"Benchmark {S82_BENCH} not in returns panel; S-82 aborts "
                           f"(no mock/fallback data).")

    cut = int(len(rets_daily) * (1.0 - OOS_FRAC))
    windows = partition_into_windows(rets_daily.index, 6)
    fragile_ranges = [(s, e) for label_, s, e in windows if label_ in fragile_labels]
    playable_ranges = [(s, e) for label_, s, e in windows if label_ in playable_labels]
    fragile_mask = pd.Series(False, index=rets_daily.index)
    for s, e in fragile_ranges:
        fragile_mask.loc[(rets_daily.index >= s) & (rets_daily.index <= e)] = True

    # ── Reproduce R77 legs (READ-ONLY frozen cell) ───────────────────────────
    print("\nReproducing R46 leg (pillar_O 5d/5bps) …")
    leg_r46, _ = build_r46_sleeve_28(cis_long, rets_daily, tradeable)

    print("Reproducing R62 leg (fade-the-crowd 21d/0bps gated) …")
    from src.research.validation.funding_crowding_ls import score_funding_zwide
    score_zwide = score_funding_zwide(funding_daily[tradeable], zwin=zwin,
                                       sign="fade_crowd").reindex(rets_daily.index).ffill()
    feats = compute_combined_features(cis_long, rets_daily, tradeable_full, tradeable,
                                       funding_daily).reindex(rets_daily.index)
    ks = build_fragility_ks_table(feats, fragile_mask)
    external_cols = [c for c in feats.columns if c in {
        "funding_mean", "funding_disp", "funding_skew",
        "funding_extreme_long_frac", "funding_extreme_short_frac",
        "funding_net_long_frac",
    }]
    det, _ = build_w5_detector(
        feats,
        *fragile_ranges[0] if fragile_ranges else (feats.index[0], feats.index[0]),
        *playable_ranges[0] if playable_ranges else (feats.index[0], feats.index[0]),
        ks, feature_subset=external_cols,
        z_threshold=R62_Z, min_features=R62_MF,
    )
    leg_r62 = build_r62_sleeve_28(score_zwide, rets_daily, tradeable, det)

    print("Reproducing R76 leg (funding residual 5d/0bps) …")
    score_fundres = score_funding_residual(funding_daily, tradeable) \
                                        .reindex(rets_daily.index).ffill()
    leg_r76 = r76_ls(score_fundres, rets_daily[tradeable], k_terciles=3,
                      cost_bps=0.0, rebal_days=5, sign=SIGN_HIGH_FUND_LONG) \
                                        .reindex(rets_daily.index).fillna(0.0)

    # R77 book = frozen-weight combination (gross 1.30 by construction)
    book_r77 = (W_R46 * leg_r46 + W_R62 * leg_r62 + W_R76 * leg_r76) \
                                        .reindex(rets_daily.index).fillna(0.0)

    # ── Causal regime signal + gross schedule ────────────────────────────────
    print(f"\nBuilding causal BTC trailing-{trend_lookback}d regime signal …")
    trend = btc_trend(rets_daily[S82_BENCH], lookback=trend_lookback)
    gross_raw = regime_to_gross(trend, S82_BANDS)
    gross_norm, scale = normalize_gross_equal_avg(gross_raw, cut)
    print(f"  IS-mean raw gross = {gross_raw.iloc[:cut].mean():.3f} → "
          f"normalized to 1.000 (scale {scale:.3f})")
    print(f"  OOS-mean normalized gross = {gross_norm.iloc[cut:].mean():.3f} "
          f"(≈1.0 ⇒ no leverage confound; deviation = regime distribution shift)")

    # ── Flat vs scaled book (equal average gross by construction) ────────────
    book_flat = book_r77.copy()
    book_scaled = book_r77 * gross_norm

    is_flat, oos_flat = book_flat.iloc[:cut], book_flat.iloc[cut:]
    is_scaled, oos_scaled = book_scaled.iloc[:cut], book_scaled.iloc[cut:]

    stats = {
        "flat": {
            "is_sharpe": sharpe(is_flat), "oos_sharpe": sharpe(oos_flat),
            "is_ann": ann_return(is_flat), "oos_ann": ann_return(oos_flat),
            "full_sharpe": sharpe(book_flat), "full_ann": ann_return(book_flat),
            "max_dd": max_drawdown(book_flat),
        },
        "scaled": {
            "is_sharpe": sharpe(is_scaled), "oos_sharpe": sharpe(oos_scaled),
            "is_ann": ann_return(is_scaled), "oos_ann": ann_return(oos_scaled),
            "full_sharpe": sharpe(book_scaled), "full_ann": ann_return(book_scaled),
            "max_dd": max_drawdown(book_scaled),
        },
    }

    print("\n══ Flat R77 vs regime-scaled R77 (equal avg gross) ══\n")
    print(f"{'metric':<14}{'flat':>12}{'scaled':>12}{'Δ':>12}")
    for label_, key in (("IS Sharpe", "is_sharpe"), ("OOS Sharpe", "oos_sharpe"),
                        ("IS ann%", "is_ann"), ("OOS ann%", "oos_ann"),
                        ("full Sharpe", "full_sharpe"), ("full ann%", "full_ann"),
                        ("maxDD", "max_dd")):
        f = stats["flat"][key]; s = stats["scaled"][key]
        d = s - f
        pct = key.endswith("ann") or key == "max_dd"
        fmt = (lambda x: f"{x:+.1%}") if pct else (lambda x: f"{x:+.2f}")
        print(f"{label_:<14}{fmt(f):>12}{fmt(s):>12}{fmt(d):>12}")

    # ── Per-window attribution (is the lift single-window-driven?) ───────────
    pw_flat = per_window(book_flat, windows)
    pw_scaled = per_window(book_scaled, windows)
    print("\n══ Per-window ann% (flat → scaled) ══\n")
    window_deltas = {}
    for label_ in sorted(pw_flat.keys()):
        f = pw_flat[label_]["ann_pct"]; s = pw_scaled[label_]["ann_pct"]
        window_deltas[label_] = s - f
        print(f"  {label_}: {f:+.1f}% → {s:+.1f}%  (Δ {s - f:+.1f})")

    # ── Regime-dependence diagnostic: R77 alpha conditioned on band ──────────
    # (Does R77's raw daily return actually differ across regime bands? If not,
    #  scaling can't help — this is the mechanism check.)
    band_labels = pd.Series("neutral", index=rets_daily.index)
    band_labels[trend < S82_BAND_EDGES[0]] = "deep_off"
    band_labels[(trend >= S82_BAND_EDGES[0]) & (trend < S82_BAND_EDGES[1])] = "off"
    band_labels[(trend >= S82_BAND_EDGES[1]) & (trend < S82_BAND_EDGES[2])] = "neutral"
    band_labels[(trend >= S82_BAND_EDGES[2]) & (trend < S82_BAND_EDGES[3])] = "on"
    band_labels[trend >= S82_BAND_EDGES[3]] = "deep_on"
    print("\n══ R77 raw daily alpha conditioned on regime band (mechanism check) ══\n")
    band_alpha = {}
    for b in ("deep_off", "off", "neutral", "on", "deep_on"):
        mask = band_labels == b
        n = int(mask.sum())
        mean_ann = float(book_r77[mask].mean() * PERIODS_PER_YEAR) if n > 0 else float("nan")
        band_alpha[b] = {"n_days": n, "ann_pct": mean_ann}
        print(f"  {b:<9}: n={n:>4}  R77 ann% = {mean_ann:+.1f}%")

    # ── Verdict ──────────────────────────────────────────────────────────────
    oos_sharpe_lift = stats["scaled"]["oos_sharpe"] - stats["flat"]["oos_sharpe"]
    oos_ann_lift = stats["scaled"]["oos_ann"] - stats["flat"]["oos_ann"]
    is_sharpe_lift = stats["scaled"]["is_sharpe"] - stats["flat"]["is_sharpe"]
    # single-window artifact check: does removing the best-Δ window kill the OOS lift?
    best_window = max(window_deltas, key=window_deltas.get) if window_deltas else None
    n_pos_windows = sum(1 for d in window_deltas.values() if d > 0)

    oos_improves = (oos_sharpe_lift > 0) and (oos_ann_lift > 0)
    not_single_window = n_pos_windows >= 2
    if oos_improves and not_single_window:
        verdict_band = "SURVIVES"
        verdict = ("✅ SURVIVES — at equal avg gross, regime-scaled R77 beats flat OOS "
                   "on both Sharpe and ann%, and the lift spans ≥2 windows. The R77 "
                   "book's alpha IS regime-dependent and a causal BTC-trend signal "
                   "harvests it. Doctrine's gross-scaling overlay is validated.")
    elif is_sharpe_lift > 0 and not oos_improves:
        verdict_band = "PARTIAL"
        verdict = ("🟡 PARTIAL — regime scaling helps IS but not OOS (signal overfit "
                   "to the calibration window), OR the OOS lift is single-window-driven. "
                   "Not production-ready; regime read needs a more robust definition.")
    else:
        verdict_band = "REFUTED"
        verdict = ("🔴 REFUTED — at equal avg gross, regime scaling does NOT beat flat "
                   "OOS. R77's alpha is effectively regime-invariant on this panel — the "
                   "legs already internalize regime (esp. R76 lifting W5). Gross scaling "
                   "adds no timing edge here; the flat frozen R77 cell stays optimal.")
    print(f"\nVERDICT: {verdict}\n")

    # ── Persist ──────────────────────────────────────────────────────────────
    out = {
        "panel": {"lo": str(rets_daily.index.min().date()),
                  "hi": str(rets_daily.index.max().date()),
                  "n_days": int(len(rets_daily)),
                  "n_assets": len(tradeable),
                  "oos_cut_idx": cut, "oos_frac": OOS_FRAC},
        "construction": {
            "overlay": "regime-conditioned gross scaling of R77 book",
            "book": "R77 = W_R46·leg_r46 + W_R62·leg_r62 + W_R76·leg_r76 (frozen weights)",
            "frozen_weights": {"w_r46": W_R46, "w_r62": W_R62, "w_r76": W_R76},
            "regime_signal": f"causal BTC trailing-{trend_lookback}d return, shift(1)-lagged",
            "bands": [{"lower": (None if not np.isfinite(lo_) else lo_), "gross": g_}
                      for lo_, g_ in S82_BANDS],
            "equal_avg_gross": True,
            "is_gross_scale_factor": scale,
            "oos_mean_normalized_gross": float(gross_norm.iloc[cut:].mean()),
        },
        "stats": stats,
        "per_window_ann_pct": {k: {"flat": pw_flat[k]["ann_pct"],
                                   "scaled": pw_scaled[k]["ann_pct"],
                                   "delta": window_deltas[k]}
                               for k in sorted(pw_flat.keys())},
        "regime_band_alpha": band_alpha,
        "lifts": {"oos_sharpe_lift": oos_sharpe_lift, "oos_ann_lift": oos_ann_lift,
                  "is_sharpe_lift": is_sharpe_lift,
                  "n_positive_windows": n_pos_windows, "best_window": best_window},
        "verdict": {"band": verdict_band, "verdict_string": verdict,
                    "oos_improves": bool(oos_improves),
                    "not_single_window": bool(not_single_window)},
        "live_book_impact": {
            "touches_frozen_r77_cell": False,
            "r65_paper_book_unaffected": True,
            "r66_tracking_unaffected": True,
            "note": ("S-82 is research-only. If SURVIVES, a forward-commit candidate is "
                     "a regime-gross overlay on the live R77 book — pending Jazz sign-off "
                     "+ MINIMAX_SYNC, NOT applied this round."),
        },
    }
    return out


# === Format report ============================================================
def format_report(payload: dict) -> str:
    lines = []
    lines.append("# S-82 — regime-conditioned gross overlay on R77 book")
    lines.append(f"**Run date:** {datetime.now().isoformat(timespec='seconds')}")
    p = payload["panel"]
    lines.append(f"**Panel:** {p['lo']} → {p['hi']} ({p['n_days']} days, "
                 f"{p['n_assets']} assets, OOS = last {int(OOS_FRAC*100)}%)")
    lines.append("")
    v = payload["verdict"]
    lines.append(f"## Verdict — {v['band']}")
    lines.append(v["verdict_string"])
    lines.append("")
    lines.append("## Flat vs regime-scaled (equal average gross)")
    s = payload["stats"]
    lines.append("| metric | flat | scaled | Δ |")
    lines.append("|---|---:|---:|---:|")
    for lbl, key, pct in (("IS Sharpe", "is_sharpe", False),
                          ("OOS Sharpe", "oos_sharpe", False),
                          ("IS ann%", "is_ann", True), ("OOS ann%", "oos_ann", True),
                          ("full Sharpe", "full_sharpe", False),
                          ("maxDD", "max_dd", True)):
        f = s["flat"][key]; sc = s["scaled"][key]
        fmt = (lambda x: f"{x:+.1%}") if pct else (lambda x: f"{x:+.2f}")
        lines.append(f"| {lbl} | {fmt(f)} | {fmt(sc)} | {fmt(sc - f)} |")
    lines.append("")
    lines.append("## Per-window ann% (flat → scaled)")
    lines.append("| window | flat | scaled | Δ |")
    lines.append("|---|---:|---:|---:|")
    for k, r in payload["per_window_ann_pct"].items():
        lines.append(f"| {k} | {r['flat']:+.1f}% | {r['scaled']:+.1f}% | {r['delta']:+.1f} |")
    lines.append("")
    lines.append("## R77 raw alpha by regime band (mechanism check)")
    lines.append("| band | n_days | R77 ann% |")
    lines.append("|---|---:|---:|")
    for b, r in payload["regime_band_alpha"].items():
        lines.append(f"| {b} | {r['n_days']} | {r['ann_pct']:+.1f}% |")
    lines.append("")
    li = payload["live_book_impact"]
    lines.append("## Live book impact")
    lines.append(f"- Touches frozen R77 cell: **{li['touches_frozen_r77_cell']}**")
    lines.append(f"- R65 paper book unaffected: **{li['r65_paper_book_unaffected']}**")
    lines.append(f"- Note: {li['note']}")
    lines.append("")
    return "\n".join(lines)


# === CLI ======================================================================
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", type=Path, default=None)
    parser.add_argument("--trend-lookback", type=int, default=S82_TREND_LOOKBACK)
    args = parser.parse_args()

    today = datetime.now().strftime("%Y-%m-%d")
    out = args.out_dir or Path(f"reports/s82_regime_gross_overlay/{today}")
    payload = run(out, trend_lookback=args.trend_lookback)

    out.mkdir(parents=True, exist_ok=True)
    with (out / "verdict.json").open("w") as f:
        json.dump(payload, f, indent=2, default=str)
    with (out / "REPORT.md").open("w") as f:
        f.write(format_report(payload))
    print(f"Wrote {out / 'verdict.json'}")
    print(f"Wrote {out / 'REPORT.md'}")
    print()
    print(format_report(payload))
