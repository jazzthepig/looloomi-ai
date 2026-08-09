"""Quick band-alpha scan across multiple regime axes.

Hypothesis: R77 raw daily alpha is regime-invariant. S-82/R82 already proved it on
the BTC-trailing-30d axis. The question is whether OTHER axes show dependence —
if some axis DOES show dependence, that's a candidate for A1/A2. If ALL axes are
flat, A path is closed.

This is a SCAN, not a research module. No smoke tests, no verdict grammar.
Output: a single JSON with band-alpha distribution per axis.

Axes tested:
  1. BTC trailing-30d (baseline — already REFUTED via S-82)
  2. BTC trailing-90d (longer-horizon trend — different timescale)
  3. BTC 30d realized vol (vol-level axis)
  4. BTC 30d vol-of-vol (vol-regime-change axis)
  5. Cross-sectional funding dispersion (crowding axis)
  6. ETH/BTC 30d return ratio (cross-asset rotation axis)
  7. R77's own 30d return (autocorrelation — does alpha cluster?)

For each axis: 5 quantile bands, report n_days + R77 ann% per band.
If any band has ann% > 2× or < 0.5× the panel mean, that's a candidate.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from src.research.validation.cis_quality_absorption import (
    load_cis_history_wide, load_daily_returns,
)
from src.research.validation.w5_forensics_external import load_funding_daily
from src.research.validation.r63_fusion_validation import (
    build_r46_sleeve_28, build_r62_sleeve_28, max_drawdown,
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
from src.research.validation.w5_forensics import (
    partition_into_windows, build_w5_detector,
)
from src.research.validation.funding_crowding_ls import score_funding_zwide

PERIODS_PER_YEAR = 365
OOS_FRAC = 0.30
W_R46, W_R62, W_R76 = 0.25, 0.75, 0.30


def load_r77_returns() -> tuple[pd.Series, dict]:
    """Reproduce R77 frozen-cell returns (READ-ONLY). Returns (book_r77, meta)."""
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
    bench_rets = rets_daily["BTC"]

    cut = int(len(rets_daily) * (1.0 - OOS_FRAC))
    windows = partition_into_windows(rets_daily.index, 6)
    fragile_ranges = [(s, e) for label_, s, e in windows if label_ in DEFAULT_FRAGILE_WINDOWS]
    playable_ranges = [(s, e) for label_, s, e in windows if label_ in DEFAULT_PLAYABLE_WINDOWS]
    fragile_mask = pd.Series(False, index=rets_daily.index)
    for s, e in fragile_ranges:
        fragile_mask.loc[(rets_daily.index >= s) & (rets_daily.index <= e)] = True

    leg_r46, _ = build_r46_sleeve_28(cis_long, rets_daily, tradeable)
    score_zwide = score_funding_zwide(funding_daily[tradeable], zwin=30,
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
    score_fundres = score_funding_residual(funding_daily, tradeable) \
                                        .reindex(rets_daily.index).ffill()
    leg_r76 = r76_ls(score_fundres, rets_daily[tradeable], k_terciles=3,
                      cost_bps=0.0, rebal_days=5, sign=SIGN_HIGH_FUND_LONG) \
                                        .reindex(rets_daily.index).fillna(0.0)
    book_r77 = (W_R46 * leg_r46 + W_R62 * leg_r62 + W_R76 * leg_r76) \
                                        .reindex(rets_daily.index).fillna(0.0)

    meta = {
        "panel_lo": str(rets_daily.index.min().date()),
        "panel_hi": str(rets_daily.index.max().date()),
        "n_days": int(len(rets_daily)),
        "n_assets": len(tradeable),
        "oos_cut": cut,
        "r77_full_sharpe": float(book_r77.mean() / book_r77.std() * np.sqrt(PERIODS_PER_YEAR)),
        "r77_full_ann": float(book_r77.mean() * PERIODS_PER_YEAR),
        "r77_max_dd": float(max_drawdown(book_r77)),
        "bench_rets": bench_rets,
        "rets": rets_daily,
        "funding_daily": funding_daily,
        "tradeable": tradeable,
    }
    return book_r77, meta


def trailing_return(rets: pd.Series, lookback: int) -> pd.Series:
    """Causal trailing-Nd compounded return, shift(1)-lagged."""
    cum = (1.0 + rets.fillna(0.0)).cumprod()
    trail = cum / cum.shift(lookback) - 1.0
    trail.iloc[:lookback] = np.nan
    return trail.shift(1)


def quantile_bands_is_oos(signal: pd.Series, n_bands: int = 5,
                          is_end: int = None) -> tuple[pd.Series, list]:
    """Quintile band labels (q1..q5) — IS-fit edges, OOS same edges (NO leakage).

    Edges computed on IS period ONLY. Same edges applied to OOS rows. This is the
    anti-imposter discipline: a regime definition that re-fits on the full panel
    is a look-ahead band assignment. Edges are FROZEN at IS end; OOS observations
    fall into whatever IS-quintile their value lands in.

    Returns (band_labels, edges). `edges` is the 6-element list (5 bins).
    """
    if is_end is None:
        raise ValueError("is_end is required for anti-look-ahead quantile bands")
    is_signal = signal.iloc[:is_end].dropna()
    if len(is_signal) < n_bands * 5:
        return pd.Series("nan", index=signal.index), []
    edges = list(np.quantile(is_signal, np.linspace(0, 1, n_bands + 1)))
    edges[0] -= 1e-9
    edges[-1] += 1e-9
    out = pd.Series("nan", index=signal.index)
    labels = [f"q{i+1}" for i in range(n_bands)]
    for i in range(n_bands):
        mask = (signal >= edges[i]) & (signal <= edges[i+1])
        out[mask] = labels[i]
    return out, edges


def fixed_bands(signal: pd.Series, edges: tuple) -> pd.Series:
    """Fixed-edge bands. NaN where signal is NaN."""
    out = pd.Series("nan", index=signal.index)
    labels = [f"q{i+1}" for i in range(len(edges) + 1)]
    for i in range(len(edges) + 1):
        if i == 0:
            mask = signal < edges[0]
        elif i == len(edges):
            mask = signal >= edges[-1]
        else:
            mask = (signal >= edges[i-1]) & (signal < edges[i])
        out[mask] = labels[i]
    return out


def band_alpha(book: pd.Series, bands: pd.Series, label: str) -> dict:
    """R77 ann% per band."""
    out = {"label": label, "bands": {}}
    for b in sorted(set(bands.unique())):
        if b == "nan":
            continue
        mask = bands == b
        n = int(mask.sum())
        if n < 5:
            continue
        sub = book[mask].dropna()
        ann = float(sub.mean() * PERIODS_PER_YEAR) if not sub.empty else float("nan")
        sharpe = float(sub.mean() / sub.std() * np.sqrt(PERIODS_PER_YEAR)) if len(sub) > 1 else float("nan")
        out["bands"][b] = {
            "n_days": n,
            "ann_pct": ann,
            "sharpe": sharpe,
        }
    out["range_pct"] = max(v["ann_pct"] for v in out["bands"].values()) - \
                       min(v["ann_pct"] for v in out["bands"].values())
    out["panel_mean_ann"] = float(book.mean() * PERIODS_PER_YEAR)
    return out


def main():
    print("Loading R77 book …")
    book_r77, meta = load_r77_returns()
    print(f"  Panel {meta['panel_lo']} → {meta['panel_hi']} ({meta['n_days']} days)")
    print(f"  R77 full Sharpe = {meta['r77_full_sharpe']:+.2f}, "
          f"ann% = {meta['r77_full_ann']:+.1f}%, maxDD = {meta['r77_max_dd']:+.1%}")
    print()

    axes = []

    # Axis 1: BTC trailing-30d (BASELINE — S-82/R82 already flat)
    sig = trailing_return(meta["bench_rets"], 30)
    axes.append(("btc_trail30", "quantile", sig, None))

    # Axis 2: BTC trailing-90d (longer horizon)
    sig = trailing_return(meta["bench_rets"], 90)
    axes.append(("btc_trail90", "quantile", sig, None))

    # Axis 3: BTC trailing-180d (very long horizon — what regime is "secular bull")
    sig = trailing_return(meta["bench_rets"], 180)
    axes.append(("btc_trail180", "quantile", sig, None))

    # Axis 4: BTC 30d realized vol (annualized)
    vol30 = meta["bench_rets"].rolling(30).std() * np.sqrt(PERIODS_PER_YEAR)
    axes.append(("btc_vol30", "quantile", vol30.shift(1), None))

    # Axis 5: BTC 30d vol-of-vol (rolling std of 30d vol)
    vol_of_vol = vol30.rolling(30).std()
    axes.append(("btc_vol_of_vol30", "quantile", vol_of_vol.shift(1), None))

    # Axis 6: ETH/BTC 30d return ratio (cross-asset rotation)
    eth_btc_ratio = meta["rets"]["ETH"] / meta["rets"]["BTC"] if "ETH" in meta["rets"].columns else None
    if eth_btc_ratio is not None:
        sig = trailing_return(eth_btc_ratio.fillna(0), 30)
        axes.append(("eth_btc_ratio_trail30", "quantile", sig, None))

    # Axis 7: cross-sectional funding dispersion (crowding)
    fd = meta["funding_daily"][meta["tradeable"]]
    if not fd.empty:
        funding_disp = fd.std(axis=1)
        axes.append(("funding_disp", "quantile", funding_disp.reindex(meta["rets"].index).ffill().shift(1), None))

    # Axis 8: BTC 5d return (short-term momentum — different timescale from trail30)
    sig = trailing_return(meta["bench_rets"], 5)
    axes.append(("btc_trail5", "quantile", sig, None))

    results = {"meta": {k: v for k, v in meta.items() if not isinstance(v, (pd.Series, pd.DataFrame))}, "axes": []}
    is_end = meta["oos_cut"]
    for label, mode, sig, edges in axes:
        if sig.dropna().empty:
            continue
        if mode == "quantile":
            bands, fitted_edges = quantile_bands_is_oos(sig, n_bands=5, is_end=is_end)
        else:
            bands = fixed_bands(sig, edges)
            fitted_edges = list(edges) if edges else []
        ba = band_alpha(book_r77, bands, label)
        ba["fitted_edges_is_only"] = [float(e) for e in fitted_edges]
        ba["oos_cut_idx"] = is_end

        # IS-only / OOS-only split per band — the final anti-imposter check
        is_book = book_r77.iloc[:is_end]
        oos_book = book_r77.iloc[is_end:]
        is_bands = bands.iloc[:is_end]
        oos_bands = bands.iloc[is_end:]
        ba["bands_is"] = {}
        ba["bands_oos"] = {}
        for b in sorted(set(bands.unique())):
            if b == "nan":
                continue
            for tag, sub_book, sub_bands in (("is", is_book, is_bands), ("oos", oos_book, oos_bands)):
                mask = sub_bands == b
                n = int(mask.sum())
                if n < 3:
                    continue
                sub = sub_book[mask].dropna()
                ann = float(sub.mean() * PERIODS_PER_YEAR) if not sub.empty else float("nan")
                sharpe = float(sub.mean() / sub.std() * np.sqrt(PERIODS_PER_YEAR)) if len(sub) > 1 else float("nan")
                if tag == "is":
                    ba["bands_is"][b] = {"n_days": n, "ann_pct": ann, "sharpe": sharpe}
                else:
                    ba["bands_oos"][b] = {"n_days": n, "ann_pct": ann, "sharpe": sharpe}

        results["axes"].append(ba)
        print(f"══ {label} (n={sig.dropna().shape[0]} valid, edges fit on first {is_end} rows) ══")
        print(f"   {'band':<5} {'n_F':>5} {'full_ann%':>10} {'shp':>6}   "
              f"{'n_IS':>5} {'IS_ann%':>9} {'IS_shp':>7}   "
              f"{'n_OOS':>5} {'OOS_ann%':>9} {'OOS_shp':>7}")
        for b in sorted(ba["bands"].keys()):
            r_f = ba["bands"][b]
            r_is = ba["bands_is"].get(b, {})
            r_oos = ba["bands_oos"].get(b, {})
            print(f"   {b:<5} {r_f['n_days']:>5} {r_f['ann_pct']:>+10.2f} {r_f['sharpe']:>+6.2f}   "
                  f"{r_is.get('n_days', '–'):>5} {r_is.get('ann_pct', float('nan')):>+9.2f} {r_is.get('sharpe', float('nan')):>+7.2f}   "
                  f"{r_oos.get('n_days', '–'):>5} {r_oos.get('ann_pct', float('nan')):>+9.2f} {r_oos.get('sharpe', float('nan')):>+7.2f}")
        print(f"   → range (full) = {ba['range_pct']:+.2f}pp  "
              f"range IS = {max(v['ann_pct'] for v in ba['bands_is'].values()) - min(v['ann_pct'] for v in ba['bands_is'].values()):+.2f}pp  "
              f"range OOS = {max(v['ann_pct'] for v in ba['bands_oos'].values()) - min(v['ann_pct'] for v in ba['bands_oos'].values()):+.2f}pp")
        print(f"   panel mean (full) = {ba['panel_mean_ann']:+.2f}%")
        print()

    # Identify candidates: any axis where range > 1.0pp AND a band ann% > 2× panel mean
    print("══ CANDIDATES (IS-only edges · range > 1.0pp AND best band > 2× panel mean) ══")
    candidates = []
    for ax in results["axes"]:
        if ax["range_pct"] > 1.0:
            best = max(ax["bands"].items(), key=lambda kv: kv[1]["ann_pct"])
            worst = min(ax["bands"].items(), key=lambda kv: kv[1]["ann_pct"])
            if best[1]["ann_pct"] > 2 * ax["panel_mean_ann"] or worst[1]["ann_pct"] < 0:
                candidates.append({
                    "axis": ax["label"],
                    "best_band": best[0],
                    "best_ann_pct": best[1]["ann_pct"],
                    "worst_band": worst[0],
                    "worst_ann_pct": worst[1]["ann_pct"],
                    "range_pct": ax["range_pct"],
                })
                print(f"  ★ {ax['label']}: best {best[0]}={best[1]['ann_pct']:+.2f}%  "
                      f"worst {worst[0]}={worst[1]['ann_pct']:+.2f}%  range={ax['range_pct']:+.2f}pp")
    if not candidates:
        print("  (none — all axes show flat band-alpha even with IS-only edges)")
    print()

    out_dir = Path("/tmp/a0_band_alpha_scan")
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "scan.json").open("w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"Wrote {out_dir / 'scan.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
