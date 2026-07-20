"""
R45 deepening — cadence sweep + sub-period OOS decomposition.
======================================================================================
Owner: Seth, 2026-07-20. Triggered by R45's two unresolved ambiguities:

  (a) **Cost fragility.** Composite CIS L/S t=+2.24 gross → t=+1.68 at 5 bps turnover
      (dies below the 1.96 bar). Was the edge true but daily-rebal overfit to turnover,
      or was the edge's scale simply insufficient to survive realistic frictions? A
      cadence sweep distinguishes these: weekly rebal drops turnover ~5×, biweekly ~10×,
      monthly ~20×. At 5 bps cost, weekly clears t>1.96 if daily was overfit; if not,
      the "edge scale insufficient" verdict holds and R45 closes.

  (b) **OOS instability.** Last-30% OOS flips composite to t=+0.33 and pillar_O to
      t=−0.45. Was this a specific-regime collapse (signal alive elsewhere, just dead
      in 2025-10 → 2026-06) or uniform death (R45 final)? Sub-period cuts per calendar
      window show where the edge lives and where it dies.

Per Jazz 2026-07-20: "现在不要立刻改，再继续深化研究." This is DIAGNOSTIC, not production
modification — the goal is to resolve R45's ambiguities, not to ship a CIS v5 weight.

Reuses loaders + `tercile_ls` + `factor_absorption.absorption_test` from
`cis_quality_absorption.py`. Output to `reports/cis_quality_robustness/<date>/`.

Compliance: positioning language only; no trade-direction vocabulary.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from src.research.validation.cis_quality_absorption import (
    CIS_HISTORY_DIR, OHLCV_DIR,
    load_cis_history_wide, load_daily_returns, tercile_ls,
)
from src.research.validation.factor_absorption import absorption_test


# ─────────────────────────────────────────────────────────────────────────────
# Cadence
# ─────────────────────────────────────────────────────────────────────────────
def cadence_ls(score_wide: pd.DataFrame, rets: pd.DataFrame,
               rebal_days: int = 1, cost_bps: float = 0.0,
               k_terciles: int = 3) -> pd.Series:
    """Long top-tercile / short bottom-tercile with fixed rebalance CADENCE.

    On days 0, rebal_days, 2*rebal_days, ...: compute fresh weights from the
    lagged score at that date. On other days, HOLD previous weights (no
    turnover, no cost). Cost charged ONLY on rebal days as |w − prev_w| × cost_bps.

    rebal_days=1 → daily rebal (matches `tercile_ls`).
    rebal_days=7 → weekly.
    rebal_days=21 → monthly (~3 wks used here for monthly approximation).
    """
    common = sorted(set(score_wide.columns) & set(rets.columns))
    if len(common) < 6:
        return pd.Series(0.0, index=rets.index)
    score = score_wide[common]
    r = rets[common]
    score_lag = score.reindex(r.index).ffill().shift(1)

    fac = pd.Series(0.0, index=r.index)
    prev_w = pd.Series(0.0, index=common)
    for i, date in enumerate(r.index):
        rr = r.loc[date].reindex(common).fillna(0.0)
        if i % rebal_days == 0:
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
            turnover = float((w - prev_w).abs().sum())
            fac.loc[date] = float((w * rr).sum()) - turnover * cost_bps / 1e4
            prev_w = w
        else:
            fac.loc[date] = float((prev_w * rr).sum())
    return fac


def cadence_sweep(score_wide: pd.DataFrame, rets: pd.DataFrame, known_arrs: dict,
                  cadences=(1, 3, 5, 7, 14, 21),
                  cost_grid=(0.0, 5.0, 10.0),
                  label: str = "factor") -> dict:
    """Run cadence × cost grid. Returns nested dict {(cad, bps): result}."""
    out = {}
    for cad in cadences:
        fac = cadence_ls(score_wide, rets, rebal_days=cad, cost_bps=0.0)
        fac = fac.reindex(rets.index).fillna(0.0)
        for bps in cost_grid:
            fac_c = cadence_ls(score_wide, rets, rebal_days=cad, cost_bps=bps)
            fac_c = fac_c.reindex(rets.index).fillna(0.0)
            r = absorption_test(fac_c.values, known_arrs,
                                nw_lags=6, periods_per_year=365)
            r["turnover_ann"] = float(estimate_turnover_ann(score_wide, rets, cad))
            out[(cad, bps)] = r
    return out


def estimate_turnover_ann(score_wide: pd.DataFrame, rets: pd.DataFrame,
                          rebal_days: int) -> float:
    """Estimate annualized turnover by sampling a handful of rebal days."""
    common = sorted(set(score_wide.columns) & set(rets.columns))
    score = score_wide[common].reindex(rets.index).ffill().shift(1)
    samp = list(range(0, len(rets.index), rebal_days))[:20]
    weights_seq = []
    for i in samp:
        date = rets.index[i]
        s_row = score.loc[date].dropna()
        if len(s_row) < 6:
            continue
        try:
            ranks = pd.qcut(s_row, q=3, labels=False, duplicates="drop")
        except ValueError:
            continue
        top_label, bot_label = ranks.max(), ranks.min()
        if top_label == bot_label:
            continue
        w = pd.Series(0.0, index=common)
        top = ranks[ranks == top_label].index
        bot = ranks[ranks == bot_label].index
        w.loc[top] = 1.0 / len(top)
        w.loc[bot] = -1.0 / len(bot)
        weights_seq.append(w)
    if len(weights_seq) < 2:
        return 0.0
    turnovers = [float((weights_seq[i + 1] - weights_seq[i]).abs().sum())
                 for i in range(len(weights_seq) - 1)]
    avg_to = np.mean(turnovers) if turnovers else 0.0
    return avg_to * 365 / rebal_days


# ─────────────────────────────────────────────────────────────────────────────
# Sub-period OOS
# ─────────────────────────────────────────────────────────────────────────────
def quarter_cuts(start: pd.Timestamp, end: pd.Timestamp, n_windows: int = 6):
    """Fixed-width sub-periods. Returns list of (label, s, e) tuples."""
    n_days = (end - start).days
    width = n_days // n_windows
    cuts = []
    for i in range(n_windows):
        s = start + pd.Timedelta(days=i * width)
        e = (start + pd.Timedelta(days=(i + 1) * width)) if i < n_windows - 1 else end
        cuts.append((f"W{i+1}", s, e))
    return cuts


def sub_period_absorption(fac: pd.Series, known_arrs: dict,
                          periods, nw_lags=6, periods_per_year=365) -> list:
    """Run absorption_test per (label, s, e) window."""
    out = []
    if not isinstance(fac.index, pd.DatetimeIndex):
        fac = fac.copy()
        fac.index = pd.to_datetime(fac.index)
    fac = fac.reindex(fac.index).fillna(0.0)
    fac_arr = fac.values
    for label, s, e in periods:
        mask = (fac.index >= s) & (fac.index <= e)
        mask = np.asarray(mask)
        if int(mask.sum()) < 30:
            out.append({"label": label, "n": int(mask.sum()),
                        "alpha_t": np.nan, "alpha_ann_pct": np.nan,
                        "raw_t": np.nan, "alpha_significant": False})
            continue
        f_sub = fac_arr[mask]
        k_sub = {k: v[mask] for k, v in known_arrs.items()}
        try:
            r = absorption_test(f_sub, k_sub, nw_lags=nw_lags,
                                periods_per_year=periods_per_year)
            r["label"] = label
            r["n"] = int(mask.sum())
            r["alpha_significant"] = bool(r["alpha_significant"])
            out.append(r)
        except Exception as ex:
            out.append({"label": label, "n": int(mask.sum()), "error": str(ex)})
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Master run
# ─────────────────────────────────────────────────────────────────────────────
def run(out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    print("=== R45 deepening — cadence sweep + sub-period OOS ===\n")

    cis = load_cis_history_wide()
    rets = load_daily_returns()

    lo = max(cis["date"].min(), rets.index.min())
    hi = min(cis["date"].max(), rets.index.max())
    rets = rets.loc[(rets.index >= lo) & (rets.index <= hi)]
    tradeable = sorted(set(cis["asset"]) & set(rets.columns))
    print(f"Window: {lo.date()} → {hi.date()}  ·  {len(rets)} days  ·  "
          f"{len(tradeable)} assets\n")

    f_market = rets[tradeable].mean(axis=1).fillna(0.0)
    cum = (1 + f_market).cumprod()
    trail30 = cum / cum.shift(30) - 1
    f_momentum = (np.sign(trail30.shift(1)).fillna(0.0) * f_market)
    known_arrs = {"market": f_market.values, "momentum": f_momentum.values}

    # Score matrices
    def wide(col):
        return cis.pivot_table(index="date", columns="asset", values=col)

    score_mats = {"CIS": wide("cis_score"), "pillar_O": wide("O"),
                  "pillar_S": wide("S")}

    # ═══════ CADENCE SWEEP ═══════
    print("══ Cadence sweep (composite CIS) ══\n")
    cad_grid = (1, 3, 5, 7, 14, 21)
    cost_grid = (0.0, 5.0, 10.0)
    cadence_results = {}
    for name, mat in score_mats.items():
        print(f"-- {name}")
        cadence_results[name] = cadence_sweep(mat, rets[tradeable], known_arrs,
                                              cadences=cad_grid,
                                              cost_grid=cost_grid,
                                              label=name)
        # print summary
        for cad in cad_grid:
            r = cadence_results[name][(cad, 5.0)]
            tag = "✓" if r["alpha_significant"] else "✗"
            print(f"   rebal={cad:>2}d  5bps  t={r['alpha_t']:+.2f}  "
                  f"ann={r['alpha_ann_pct']:+.1f}%  {tag}  "
                  f"turnover≈{r['turnover_ann']:.1f}")
        print()

    # ═══════ SUB-PERIOD ABSORPTION ═══════
    print("\n══ Sub-period OOS (6 fixed-width windows, daily rebal) ══\n")
    periods = quarter_cuts(rets.index.min(), rets.index.max(), n_windows=6)
    sub_period_results = {}
    for name, mat in score_mats.items():
        # Daily rebal factor for sub-period decomposition
        fac = tercile_ls(mat, rets[tradeable]).reindex(rets.index).fillna(0.0)
        sp = sub_period_absorption(fac, known_arrs, periods)
        sub_period_results[name] = sp
        for r in sp:
            n = r.get("n", "?")
            t = r.get("alpha_t", float("nan"))
            ann = r.get("alpha_ann_pct", float("nan"))
            print(f"   {r['label']:>3}  n={n:>3}  α_t={t:+.2f}  α_ann={ann:+.1f}%")
        print()

    out = {
        "window": f"{lo.date()} → {hi.date()}",
        "n_days": len(rets),
        "n_assets": len(tradeable),
        "cadence_results": {k: {f"{c}_{int(b)}": v for (c, b), v in d.items()}
                             for k, d in cadence_results.items()},
        "sub_period_results": sub_period_results,
        "sub_period_labels": [p[0] for p in periods],
        "sub_period_dates": [(str(p[1].date()), str(p[2].date())) for p in periods],
    }
    (out_dir / "verdict.json").write_text(json.dumps(out, indent=2, default=str))
    report = format_report(out)
    (out_dir / "REPORT.md").write_text(report)
    print(report)
    print(f"\nSaved: {out_dir/'verdict.json'} + {out_dir/'REPORT.md'}")
    return out


def format_report(out: dict) -> str:
    L = []
    L.append("# R45 Deepening — Cadence Sweep + Sub-period OOS\n")
    L.append(f"**Window:** {out['window']}  ·  **Days:** {out['n_days']}  ·  "
             f"**Universe:** {out['n_assets']} assets\n")
    L.append("Per Jazz 2026-07-20: do NOT change CIS yet. This deepens the "
             "diagnostic, not the production methodology.\n")

    # ─── Cadence × cost grid (CIS) ───
    L.append("## Cadence × cost grid (composite CIS, daily-rebal baseline = R45)\n")
    L.append("`t` = Newey-West residual-α t-stat after {market, momentum}. "
             "**Bold** = clears t > 1.96.\n")
    cads = (1, 3, 5, 7, 14, 21)
    costs = (0.0, 5.0, 10.0)
    L.append("| rebal (d) | turnover≈ | 0 bps t | 5 bps t | 10 bps t | first-cad-at-5bps-to-clear |")
    L.append("|--:|--:|--:|--:|--:|--:|")
    for cad in cads:
        to = out["cadence_results"]["CIS"][f"{cad}_0"]["turnover_ann"]
        ts = []
        for bps in costs:
            r = out["cadence_results"]["CIS"][f"{cad}_{int(bps)}"]
            t = r["alpha_t"]
            ts.append(f"**{t:+.2f}**" if r["alpha_significant"] else f"{t:+.2f}")
        first_clear = "—"
        for cad2 in cads:
            r = out["cadence_results"]["CIS"][f"{cad2}_5"]
            if r["alpha_significant"]:
                first_clear = f"**{cad2}d** (t={r['alpha_t']:+.2f})"
                break
        L.append(f"| {cad} | {to:.1f} | {ts[0]} | {ts[1]} | {ts[2]} | {first_clear} |")

    # Same for pillar_O and pillar_S
    for fac_name in ("pillar_O", "pillar_S"):
        L.append(f"\n### {fac_name}\n")
        L.append("| rebal (d) | turnover≈ | 0 bps t | 5 bps t | 10 bps t | first-cad-at-5bps-to-clear |")
        L.append("|--:|--:|--:|--:|--:|--:|")
        first_clear = "—"
        for cad in cads:
            to = out["cadence_results"][fac_name][f"{cad}_0"]["turnover_ann"]
            ts = []
            for bps in costs:
                r = out["cadence_results"][fac_name][f"{cad}_{int(bps)}"]
                t = r["alpha_t"]
                ts.append(f"**{t:+.2f}**" if r["alpha_significant"] else f"{t:+.2f}")
            L.append(f"| {cad} | {to:.1f} | {ts[0]} | {ts[1]} | {ts[2]} | {first_clear} |")
            if first_clear == "—" and out["cadence_results"][fac_name][f"{cad}_5"]["alpha_significant"]:
                r = out["cadence_results"][fac_name][f"{cad}_5"]
                first_clear = f"**{cad}d** (t={r['alpha_t']:+.2f})"

    # ─── Sub-period absorption ───
    L.append("\n## Sub-period α_t (6 fixed-width windows, daily rebal)\n")
    L.append("Per-window Newey-West residual-α t after {market, momentum}. "
             "**Bold** = clears t > 1.96. n = days in window.\n")
    L.append("| Window | dates | n | CIS t | pillar_O t | pillar_S t |")
    L.append("|--:|---|--:|--:|--:|--:|")
    for i, label in enumerate(out["sub_period_labels"]):
        s, e = out["sub_period_dates"][i]
        dates_str = f"{s} → {e}"
        cells = []
        for fac_name in ("CIS", "pillar_O", "pillar_S"):
            r = out["sub_period_results"][fac_name][i]
            t = r.get("alpha_t", float("nan"))
            t_str = f"**{t:+.2f}**" if abs(t) > 1.96 and not np.isnan(t) else f"{t:+.2f}"
            cells.append(t_str)
        n = out["sub_period_results"]["CIS"][i].get("n", "?")
        L.append(f"| {label} | {dates_str} | {n} | {cells[0]} | {cells[1]} | {cells[2]} |")

    # ─── Synthesis ───
    L.append("\n## Synthesis (per Jazz: deepening, not action)\n")

    # (a) Cadence verdict
    cad_clears = {}
    for fac_name in ("CIS", "pillar_O", "pillar_S"):
        for cad in cads:
            r = out["cadence_results"][fac_name][f"{cad}_5"]
            if r["alpha_significant"]:
                cad_clears.setdefault(fac_name, cad)
                break
    if cad_clears:
        for fac, cad in cad_clears.items():
            r = out["cadence_results"][fac][f"{cad}_5"]
            L.append(f"- **{fac}** clears t>1.96 at 5 bps when rebal ≥ **{cad}d** "
                     f"(5bps t={r['alpha_t']:+.2f}, ann={r['alpha_ann_pct']:+.1f}%) — "
                     f"daily-rebal was overfit to turnover-flavored returns.")
    else:
        L.append("- **No factor clears 5bps-costed t>1.96 at any cadence (1d-21d).** "
                 "R45's 'edge scale insufficient' verdict holds: slowing rebal "
                 "doesn't restore the edge to a book-factor level.")

    # (b) Sub-period verdict
    L.append("")
    win_counts = {}
    for fac_name in ("CIS", "pillar_O", "pillar_S"):
        win_counts[fac_name] = sum(
            1 for r in out["sub_period_results"][fac_name]
            if not np.isnan(r.get("alpha_t", np.nan)) and abs(r["alpha_t"]) > 1.96)
        total = len(out["sub_period_results"][fac_name])
        L.append(f"- **{fac_name}** clear-t windows: "
                 f"**{win_counts[fac_name]} / {total}** "
                 f"({win_counts[fac_name]/total*100:.0f}%)")

    # (c) Pattern: is OOS-flip signal-specific?
    L.append("")
    sub_cis_oos = []
    for fac_name in ("CIS", "pillar_O"):
        rs = out["sub_period_results"][fac_name]
        signs = [np.sign(r.get("alpha_t", 0)) for r in rs if not np.isnan(r.get("alpha_t", np.nan))]
        n_pos = sum(1 for s in signs if s > 0)
        n_neg = sum(1 for s in signs if s < 0)
        L.append(f"- **{fac_name}** sub-period sign distribution: "
                 f"{n_pos} positive / {n_neg} negative of {len(signs)} valid windows. "
                 + ("Concentrated flip ⇒ regime-specific death (regime-conditioning is the upgrade path)."
                    if (min(n_pos, n_neg) > 0 and max(n_pos, n_neg) >= 4 * min(n_pos, n_neg))
                    else "Mixed signs ⇒ partial regime conditioning."))

    return "\n".join(L)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", type=Path,
                    default=Path(f"reports/cis_quality_robustness/{datetime.now():%Y-%m-%d}"))
    args = ap.parse_args()
    run(args.out_dir)
