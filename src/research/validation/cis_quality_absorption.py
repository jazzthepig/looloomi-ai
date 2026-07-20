"""
CIS-quality absorption re-run — the honest adversarial test of our own core product.
======================================================================================
Owner: Seth, 2026-07-19. Triggered by §CIS-HISTORY-BACKFILL landing (870 daily snapshots
2024-03-01 → 2026-07-18 at `/Volumes/CometCloudAI/cometcloud-local/_data/cis_history/`,
full F/M/O/S/A pillars, real reconstruction — NOT the price-tercile proxy).

Jazz's steer (2026-07-19): "有比 cis 策略更好的，我们就用，这样 cis 才会升级."
→ This is NOT "prove CIS works." It's: measure whether the CIS-quality factor carries
  RESIDUAL alpha after the known premia (market + momentum), and — the sharper question —
  WHICH pillar carries it, and whether anything SIMPLER than the composite beats it.
  If a single pillar dominates and the composite dilutes it, that is the signal to
  upgrade CIS (reweight toward the pillar that pays). The graveyard is the asset.

Construction (no look-ahead):
  · f_market   = equal-weight universe daily return (cross-section mean).
  · f_momentum = TSMOM(30) on f_market (sign of trailing-30d cum return × today's mkt ret).
  · f_cis      = long top-tercile / short bottom-tercile by COMPOSITE cis_score, lagged 1d.
  · f_pillar_X = same tercile L/S sorted by pillar X ∈ {F, M, O, S, A}, lagged 1d.

Absorption (OLS + Newey-West, via factor_absorption.absorption_test):
  · Per factor: raw α_t (is there an edge at all?) and residual α_t after {market, momentum}.
  · Composite CIS after {market, momentum, best-single-pillar}: does the composite add
    anything over its strongest component pillar?

Verdict grammar (per §ABSORPTION-SWEEP):
  · residual α_t > 1.96  → RESIDUAL ALPHA (genuine orthogonal edge, earns a book line)
  · raw sig but residual not → ABSORBED (old wine — market/momentum in a CIS costume)
  · raw not sig → NO EDGE to absorb.

Sandbox-safe: reads the drive directly (no Mac round-trip). Pure numpy/pandas.
Compliance: positioning language only; no trade-direction vocabulary.
"""
from __future__ import annotations

import argparse
import glob
import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from src.research.validation.factor_absorption import absorption_test

CIS_HISTORY_DIR = Path("/Volumes/CometCloudAI/cometcloud-local/_data/cis_history")
OHLCV_DIR = Path("/Volumes/CometCloudAI/data/ohlcv")

PILLAR_KEYS = {"F": "pillar_f", "M": "pillar_m", "O": "pillar_o", "S": "pillar_s", "A": "pillar_a"}


def load_cis_history_wide(cis_history_dir: Path = CIS_HISTORY_DIR) -> pd.DataFrame:
    """Load every cis_YYYY-MM-DD.json into long form with composite + all 5 pillars.

    Returns: long DataFrame [date, asset, cis_score, F, M, O, S, A].
    Date is derived from the filename (snapshots carry only 'timestamp').
    """
    rows = []
    for fp in sorted(glob.glob(str(cis_history_dir / "cis_*.json"))):
        d_date = pd.to_datetime(Path(fp).stem.replace("cis_", "")).normalize()
        with open(fp) as fh:
            payload = json.load(fh)
        for s in payload.get("scores", []):
            asset = s.get("asset") or s.get("symbol")
            if asset is None:
                continue
            pil = s.get("pillars", {}) or {}
            row = {"date": d_date, "asset": asset, "cis_score": _f(s.get("cis_score"))}
            # pillars: prefer top-level pillar_x, fall back to nested pillars{f,m,r/o,s,a}
            row["F"] = _f(s.get("pillar_f", pil.get("f")))
            row["M"] = _f(s.get("pillar_m", pil.get("m")))
            row["O"] = _f(s.get("pillar_o", pil.get("o", pil.get("r"))))  # legacy r→O
            row["S"] = _f(s.get("pillar_s", pil.get("s")))
            row["A"] = _f(s.get("pillar_a", pil.get("a")))
            rows.append(row)
    df = pd.DataFrame(rows)
    return df.sort_values(["date", "asset"]).reset_index(drop=True)


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return np.nan


def load_daily_returns(ohlcv_dir: Path = OHLCV_DIR) -> pd.DataFrame:
    """Load all OHLCV parquets, resample hourly→daily close, return daily-return matrix
    (date × asset)."""
    all_rets = {}
    for f in sorted(ohlcv_dir.glob("*.parquet")):
        sym = f.stem
        df = pd.read_parquet(f)
        if "timestamp" in df.columns:
            df["date"] = pd.to_datetime(df["timestamp"]).dt.tz_localize(None).dt.normalize()
        elif "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None).dt.normalize()
        else:
            continue
        daily = df.groupby("date")["close"].last().sort_index()
        all_rets[sym] = daily.pct_change()
    return pd.DataFrame(all_rets)


def tercile_ls(score_wide: pd.DataFrame, rets: pd.DataFrame,
               k_terciles: int = 3, cost_bps: float = 0.0) -> pd.Series:
    """Long top-tercile / short bottom-tercile daily return, ranking lagged 1 day.

    score_wide: date × asset score matrix (composite or single pillar).
    rets:       date × asset DAILY return matrix.
    cost_bps:   per-side transaction cost in bps, charged on the day's turnover
                (|Δweight| summed across names). 0 = gross (default).
    Returns a daily factor-return Series aligned to rets.index.
    """
    common = sorted(set(score_wide.columns) & set(rets.columns))
    if len(common) < 6:
        return pd.Series(0.0, index=rets.index)
    score = score_wide[common]
    r = rets[common]

    # Lag the ranking by 1 day: rank known at t-1 is applied to returns at t.
    score_lag = score.reindex(r.index).ffill().shift(1)

    fac = pd.Series(0.0, index=r.index)
    prev_w = pd.Series(0.0, index=common)
    for date in r.index:
        s_row = score_lag.loc[date].dropna()
        w = pd.Series(0.0, index=common)
        if len(s_row) >= 6:
            try:
                ranks = pd.qcut(s_row, q=k_terciles, labels=False, duplicates="drop")
            except ValueError:
                ranks = (s_row >= s_row.median()).astype(int)
            top_label, bot_label = ranks.max(), ranks.min()
            if top_label != bot_label:
                top = ranks[ranks == top_label].index
                bot = ranks[ranks == bot_label].index
                if len(top) and len(bot):
                    w.loc[top] = 1.0 / len(top)
                    w.loc[bot] = -1.0 / len(bot)
        rr = r.loc[date].reindex(common).fillna(0.0)
        gross = float((w * rr).sum())
        turnover = float((w - prev_w).abs().sum())
        fac.loc[date] = gross - turnover * cost_bps / 1e4
        prev_w = w
    return fac


def run(out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    print("=== CIS-quality absorption re-run (real CIS history) ===\n")

    cis = load_cis_history_wide()
    print(f"CIS history: {cis['date'].nunique()} days, {cis['asset'].nunique()} assets, "
          f"{cis['date'].min().date()} → {cis['date'].max().date()}")

    rets = load_daily_returns()
    print(f"OHLCV daily returns: {rets.shape[0]} days × {rets.shape[1]} assets, "
          f"{rets.index.min().date()} → {rets.index.max().date()}")

    # Overlap window
    lo = max(cis["date"].min(), rets.index.min())
    hi = min(cis["date"].max(), rets.index.max())
    rets = rets.loc[(rets.index >= lo) & (rets.index <= hi)]
    print(f"Overlap window: {lo.date()} → {hi.date()} ({len(rets)} days)\n")

    tradeable = sorted(set(cis["asset"]) & set(rets.columns))
    print(f"Tradeable universe (CIS ∩ OHLCV): {len(tradeable)} assets\n")

    # Known factors
    f_market = rets[tradeable].mean(axis=1).fillna(0.0)          # equal-weight universe
    cum = (1 + f_market).cumprod()
    trail30 = cum / cum.shift(30) - 1
    f_momentum = (np.sign(trail30.shift(1)).fillna(0.0) * f_market)

    # CIS factors: composite + per-pillar
    def wide(col):
        return cis.pivot_table(index="date", columns="asset", values=col)

    score_mats = {"CIS": wide("cis_score")}
    for p in "FMOSA":
        score_mats[f"pillar_{p}"] = wide(p)

    factors = {}
    for name, mat in score_mats.items():
        factors[name] = tercile_ls(mat, rets[tradeable])

    known = {"market": f_market.reindex(rets.index).fillna(0.0).values,
             "momentum": f_momentum.reindex(rets.index).fillna(0.0).values}

    # Absorption per factor (GROSS, full window)
    results = {}
    for name, fac in factors.items():
        fac = fac.reindex(rets.index).fillna(0.0)
        res = absorption_test(fac.values, known, nw_lags=6, periods_per_year=365)
        results[name] = res

    # Does the composite add over its best single pillar?
    pillar_alpha_t = {p: results[f"pillar_{p}"]["alpha_t"] for p in "FMOSA"}
    best_pillar = max(pillar_alpha_t, key=lambda p: abs(pillar_alpha_t[p]))
    best_pillar_series = factors[f"pillar_{best_pillar}"].reindex(rets.index).fillna(0.0).values
    known_plus = dict(known, best_pillar=best_pillar_series)
    cis_over_best = absorption_test(
        factors["CIS"].reindex(rets.index).fillna(0.0).values, known_plus,
        nw_lags=6, periods_per_year=365)

    # === ROBUSTNESS 1: OOS time split (70/30) — does the residual α survive out of sample? ===
    cut = int(len(rets) * 0.70)
    oos_idx = rets.index[cut:]
    oos_split = {}
    for name, fac in factors.items():
        fac = fac.reindex(rets.index).fillna(0.0)
        k_oos = {kk: vv[cut:] for kk, vv in known.items()}
        res_oos = absorption_test(fac.values[cut:], k_oos, nw_lags=6, periods_per_year=365)
        oos_split[name] = {"alpha_ann_pct": res_oos["alpha_ann_pct"],
                           "alpha_t": res_oos["alpha_t"], "n": res_oos["n"]}

    # === ROBUSTNESS 2: cost sensitivity (turnover-charged) for CIS + best pillar ===
    cost_curve = {}
    for name, col in [("CIS", "cis_score"), (f"pillar_{best_pillar}", best_pillar)]:
        mat = score_mats[name]
        cost_curve[name] = {}
        for bps in (0.0, 5.0, 10.0, 20.0):
            fc = tercile_ls(mat, rets[tradeable], cost_bps=bps).reindex(rets.index).fillna(0.0)
            r_ = absorption_test(fc.values, known, nw_lags=6, periods_per_year=365)
            cost_curve[name][bps] = {"raw_ann_pct": r_["raw_ann_pct"], "raw_t": r_["raw_t"],
                                     "alpha_ann_pct": r_["alpha_ann_pct"], "alpha_t": r_["alpha_t"]}

    out = {
        "window": f"{lo.date()} → {hi.date()}",
        "n_days": len(rets),
        "n_assets": len(tradeable),
        "tradeable": tradeable,
        "factors": results,
        "best_pillar_by_alpha_t": best_pillar,
        "pillar_alpha_t": pillar_alpha_t,
        "cis_over_best_pillar": cis_over_best,
        "oos_split": oos_split,
        "oos_window": f"{oos_idx[0].date()} → {oos_idx[-1].date()}",
        "cost_curve": cost_curve,
    }

    (out_dir / "verdict.json").write_text(json.dumps(out, indent=2, default=str))
    report = format_report(out)
    (out_dir / "REPORT.md").write_text(report)
    print(report)
    print(f"\nSaved: {out_dir/'verdict.json'} + {out_dir/'REPORT.md'}")
    return out


def format_report(out: dict) -> str:
    L = []
    L.append("# CIS-quality Absorption Re-run — REPORT")
    L.append(f"\n**Window:** {out['window']}  ·  **Days:** {out['n_days']}  ·  "
             f"**Universe:** {out['n_assets']} assets (CIS ∩ OHLCV)")
    L.append("\n## Per-factor absorption (raw vs residual-α after market + momentum)\n")
    L.append("| Factor | raw ann% | raw t | resid-α ann% | resid-α t | R² | β_mkt | β_mom | verdict |")
    L.append("|---|--:|--:|--:|--:|--:|--:|--:|---|")
    for name, r in out["factors"].items():
        bm = r["factor_betas"].get("market", {})
        bmo = r["factor_betas"].get("momentum", {})
        vshort = ("RESIDUAL α" if r["alpha_significant"]
                  else "ABSORBED" if r["raw_significant"]
                  else "no edge")
        L.append(f"| {name} | {r['raw_ann_pct']:+.1f} | {r['raw_t']:+.2f} | "
                 f"{r['alpha_ann_pct']:+.1f} | {r['alpha_t']:+.2f} | {r['r2']:.2f} | "
                 f"{bm.get('beta','—')} | {bmo.get('beta','—')} | {vshort} |")
    bp = out["best_pillar_by_alpha_t"]
    cob = out["cis_over_best_pillar"]
    L.append(f"\n## Does composite CIS add over its best pillar?")
    L.append(f"\nBest single pillar by |resid-α t|: **{bp}** "
             f"(α_t = {out['pillar_alpha_t'][bp]:+.2f}).")
    L.append(f"\nComposite CIS after {{market, momentum, pillar_{bp}}}: "
             f"resid-α = {cob['alpha_ann_pct']:+.1f}%/yr, t = {cob['alpha_t']:+.2f} → "
             + ("**composite adds orthogonal edge over its best pillar**"
                if cob["alpha_significant"]
                else "**composite adds nothing over its best pillar** "
                     "(the pillar carries it; the blend dilutes)."))

    # OOS split
    L.append(f"\n## Robustness 1 — OOS time split (last 30%: {out['oos_window']})\n")
    L.append("| Factor | OOS resid-α ann% | OOS resid-α t | n |")
    L.append("|---|--:|--:|--:|")
    for name, o in out["oos_split"].items():
        L.append(f"| {name} | {o['alpha_ann_pct']:+.1f} | {o['alpha_t']:+.2f} | {o['n']} |")

    # Cost sensitivity
    L.append(f"\n## Robustness 2 — cost sensitivity (turnover-charged, daily rebal)\n")
    L.append("| Factor | bps/side | raw ann% | raw t | resid-α ann% | resid-α t |")
    L.append("|---|--:|--:|--:|--:|--:|")
    for name, curve in out["cost_curve"].items():
        for bps, r in curve.items():
            L.append(f"| {name} | {bps:.0f} | {r['raw_ann_pct']:+.1f} | {r['raw_t']:+.2f} | "
                     f"{r['alpha_ann_pct']:+.1f} | {r['alpha_t']:+.2f} |")

    L.append("\n## Read (per Jazz: use whatever is best, so CIS upgrades)")
    cis_r = out["factors"]["CIS"]
    if cis_r["alpha_significant"]:
        L.append("- Composite CIS carries genuine residual α → keep as a book factor.")
    elif cis_r["raw_significant"]:
        L.append("- Composite CIS is ABSORBED by market+momentum → as a *long/short factor* "
                 "it is beta in a costume. Its value is as a QUALITY/RISK filter, not a return "
                 "predictor (consistent with H1). The upgrade path is pillar reweighting.")
    else:
        L.append("- Composite CIS L/S shows no standalone edge on this window.")
    surviving = [n for n, r in out["factors"].items() if r["alpha_significant"]]
    L.append(f"- Factors with residual α (t>1.96): "
             f"{', '.join(surviving) if surviving else 'NONE'}.")
    bp = out["best_pillar_by_alpha_t"]
    cob = out["cis_over_best_pillar"]
    if cob["alpha_significant"]:
        L.append(f"- Composite CIS adds orthogonal edge over pillar_{bp} → keep the blend.")
    else:
        # the actionable signal — pillar dominates, the blend dilutes.
        L.append(f"- **Composite CIS adds NOTHING over pillar_{bp}** "
                 f"(t={cob['alpha_t']:+.2f} after controlling for best pillar).")
        L.append(f"- **Upgrade path: reweight CIS toward pillar_{bp}** (the pillar that pays) "
                 f"and away from the pillars that dilute. pillar_S in particular carries no "
                 f"return edge on this window (α_t = {out['pillar_alpha_t']['S']:+.2f}).")
        # OOS + cost check on the upgrade hypothesis
        oos_best = out['oos_split'][f'pillar_{bp}']
        if oos_best['alpha_t'] > 1.96:
            L.append(f"- pillar_{bp} survives OOS (t={oos_best['alpha_t']:+.2f}, n={oos_best['n']}) "
                     f"→ upgrade is REAL, not in-sample fit.")
        elif oos_best['alpha_t'] > 1.0:
            L.append(f"- pillar_{bp} OOS t={oos_best['alpha_t']:+.2f} — promising but below "
                     f"the 1.96 bar. Watch, do not declare victory.")
        else:
            L.append(f"- pillar_{bp} OOS t={oos_best['alpha_t']:+.2f} — does NOT survive cleanly. "
                     f"Upgrade hypothesis is suggestive, not confirmed.")
    return "\n".join(L)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", type=Path,
                    default=Path(f"reports/cis_quality_absorption/{datetime.now():%Y-%m-%d}"))
    args = ap.parse_args()
    run(args.out_dir)
