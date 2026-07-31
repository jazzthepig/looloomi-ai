"""
M-WO-2 PARTIAL — Pillar sign-stability on the 11yr CIS historical panel.

Per §DIRECTIVE 2026-07-27 M-WO-2:
    Re-run: (a) R46/pillar_O 5d cadence, (b) R78 relative-momentum,
    (c) R79 vol-residual, (d) S-78 macro×vol map — on the full panel with
    per-CYCLE sub-windows (2018 bear / 2020-21 bull / 2022 bear / 2023-24
    recovery / 2025-26 bear) + event counting.

BLOCKED on the OHLCV side:
- The 11yr OHLCV daily price panel (`ohlcv_daily source='binance_hist'`) does
  NOT exist on disk. The local ohlcv buffer has only:
  - coingecko: 365d × 25 symbols (2025-07-27 → 2026-07-26)
  - eodhd: 250d × 33 symbols (2025-07-28 → 2026-07-24)
- The parquet files at /Volumes/CometCloudAI/data/ohlcv/*.parquet are HOURLY
  729d × 52 symbols (2024-06-07 → 2026-06-07), NOT 11yr daily.
- R46/R78/R79/S-78 all require daily returns (close-to-close) for the 3-check
  gauntlet. Without OHLCV, only pillar-score time-series analysis is possible.

PARTIAL DELIVERABLE (this module):
- Per-pillar (F/M/O/S/A) sign-stability analysis on the 11yr CIS panel.
- Two views per pillar:
  1. 1-day persistence: rank-IC of pillar(t) vs pillar(t+1) — high IC = pillar
     carries information day-to-day; low/negative = pure noise.
  2. 5-day reversal/momentum: rank-IC of pillar(t) vs Δpillar(t, t+5) — high
     positive IC = mean-reverting (predicts reversal); negative = momentum.
- Per-year sign count (#years positive).
- Per-cycle breakdown (2018 bear / 2020-21 bull / 2022 bear / 2023-24
  recovery / 2025-26 bear) — the §DIRECTIVE's exact cycle list.

This is a PILLAR-ONLY analysis (no fwd-return IC). Full 3-check gauntlet on
the 11yr panel requires the OHLCV extension (Option A per §DIRECTIVE).

Output:
- reports/m_wo2_pillar_sign_stability_11yr/<date>/{verdict.json, REPORT.md}
- machine-readable: per-year, per-cycle, per-pillar IC + sign stability.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

# ── Paths & constants ────────────────────────────────────────────────────────
PANEL_PATH = Path("_data/cis_historical/cis_historical_11yr.csv")
PILLARS = ["pillar_f", "pillar_m", "pillar_o", "pillar_s", "pillar_a"]

# §DIRECTIVE-M-WO-2 exact cycle windows
CYCLES = [
    ("2018_bear", "2018-01-01", "2018-12-31"),
    ("2020-21_bull", "2020-03-01", "2021-11-30"),
    ("2022_bear", "2022-01-01", "2022-12-31"),
    ("2023-24_recovery", "2023-01-01", "2024-12-31"),
    ("2025-26_bear", "2025-01-01", "2026-07-31"),
]

# Forward windows for the two IC views
PERSISTENCE_HORIZON = 1    # pillar(t) vs pillar(t+1)
DELTA_HORIZON = 5          # pillar(t) vs Δpillar(t, t+5)


# ── Per-pillar daily panel builder ───────────────────────────────────────────
def build_pillar_panel(csv_path: Path) -> pd.DataFrame:
    """Read the 11yr CIS CSV, parse dates, return long-format DataFrame.

    Returns: columns = [date, symbol, pillar_f, pillar_m, pillar_o,
                         pillar_s, pillar_a, macro_regime]
    """
    df = pd.read_csv(csv_path)
    df["date"] = pd.to_datetime(df["recorded_at"]).dt.normalize()
    # macro_regime may have mixed casing; normalize to UPPER_SNAKE
    df["macro_regime"] = df["macro_regime"].astype(str).str.upper()
    keep_cols = ["date", "symbol", "macro_regime"] + PILLARS
    df = df[keep_cols].drop_duplicates(subset=["date", "symbol"]).sort_values(
        ["date", "symbol"]).reset_index(drop=True)
    return df


# ── Per-pillar × per-day rank IC computation ────────────────────────────────
def daily_rank_ic(panel: pd.DataFrame, pillar: str, horizon: int,
                  mode: str = "persistence") -> pd.Series:
    """Compute daily cross-sectional Spearman rank-IC.

    mode='persistence': IC of pillar(t) vs pillar(t+horizon)
    mode='delta':       IC of pillar(t) vs [pillar(t+horizon) − pillar(t)]

    Returns a Series indexed by date with NaN for days with insufficient assets.
    """
    if mode == "persistence":
        forward = panel.groupby("symbol")[pillar].shift(-horizon)
    elif mode == "delta":
        forward = (panel.groupby("symbol")[pillar].shift(-horizon)
                   - panel[pillar])
    else:
        raise ValueError(f"unknown mode: {mode}")

    df = pd.DataFrame({"date": panel["date"], "x": panel[pillar], "y": forward})
    out = {}
    for d, g in df.groupby("date"):
        sub = g.dropna()
        if len(sub) < 5:
            continue
        rho, _ = spearmanr(sub["x"].values, sub["y"].values)
        out[d] = float(rho)
    return pd.Series(out).sort_index()


# ── Per-year + per-cycle aggregation ────────────────────────────────────────
def aggregate_period(ic_series: pd.Series, period_label: str,
                     period_start: str, period_end: str) -> dict:
    """Aggregate daily IC for a period: mean, t-stat, sign stability, n_days."""
    # Honor tz-awareness of the index: utc_localize naive inputs if needed.
    idx = ic_series.index
    if idx.tz is not None:
        ts_start = pd.Timestamp(period_start, tz=idx.tz)
        ts_end = pd.Timestamp(period_end, tz=idx.tz)
    else:
        ts_start = pd.Timestamp(period_start)
        ts_end = pd.Timestamp(period_end)
    mask = (ic_series.index >= ts_start) & (ic_series.index <= ts_end)
    sub = ic_series.loc[mask].dropna()
    n = len(sub)
    if n == 0:
        return {"label": period_label, "n_days": 0, "mean_ic": float("nan"),
                "t_stat": float("nan"), "n_positive_days": 0,
                "sign_stability": float("nan")}
    mean_ic = float(sub.mean())
    std_ic = float(sub.std(ddof=1)) if n > 1 else 0.0
    # t-stat against 0 (mean IC significantly different from 0)
    t_stat = (mean_ic / (std_ic / np.sqrt(n))) if std_ic > 0 else 0.0
    n_pos = int((sub > 0).sum())
    sign_stability = n_pos / n if n > 0 else float("nan")
    return {
        "label": period_label,
        "start": period_start,
        "end": period_end,
        "n_days": int(n),
        "mean_ic": mean_ic,
        "std_ic": std_ic,
        "t_stat": float(t_stat),
        "n_positive_days": n_pos,
        "sign_stability": float(sign_stability),
    }


# ── Per-year aggregation (all years in panel) ────────────────────────────────
def per_year_aggregation(ic_series: pd.Series) -> list[dict]:
    years = sorted(set(ic_series.index.year))
    return [aggregate_period(ic_series, str(y), f"{y}-01-01", f"{y}-12-31")
            for y in years]


# ── Run ──────────────────────────────────────────────────────────────────────
def run(out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    print("=== M-WO-2 PARTIAL — Pillar sign-stability on 11yr CIS panel ===\n")
    print("BLOCKED on OHLCV: 11yr daily OHLCV not on disk.")
    print("Running pillar-score time-series analysis only (per §DATA-ALIGN ②.C.1).\n")

    panel = build_pillar_panel(PANEL_PATH)
    print(f"Panel: {panel['date'].min().date()} → {panel['date'].max().date()}")
    print(f"  symbols: {panel['symbol'].nunique()}")
    print(f"  days:    {panel['date'].nunique()}")
    print(f"  rows:    {len(panel)}")
    for p in PILLARS:
        nn = panel[p].notna().sum()
        print(f"  {p}: {nn}/{len(panel)} non-null ({nn/len(panel):.1%})")
    print()

    # Per-pillar IC series (persistence + delta)
    payload = {
        "panel": {
            "lo": str(panel["date"].min().date()),
            "hi": str(panel["date"].max().date()),
            "n_symbols": int(panel["symbol"].nunique()),
            "n_days": int(panel["date"].nunique()),
            "n_rows": int(len(panel)),
        },
        "blocking_note": (
            "11yr daily OHLCV not on disk. Full R46/R78/R79/S-78 re-runs need "
            "OHLCV extension (Option A per §DIRECTIVE). This module delivers "
            "pillar-score time-series sign-stability only, not fwd-return IC."
        ),
        "horizons": {
            "persistence_horizon_days": PERSISTENCE_HORIZON,
            "delta_horizon_days": DELTA_HORIZON,
        },
        "cycles": [{"label": lab, "start": s, "end": e} for lab, s, e in CYCLES],
        "pillars": {},
    }

    for pillar in PILLARS:
        print(f"\n=== {pillar.upper()} ===")
        ic_persist = daily_rank_ic(panel, pillar, PERSISTENCE_HORIZON,
                                    mode="persistence")
        ic_delta = daily_rank_ic(panel, pillar, DELTA_HORIZON, mode="delta")

        per_year = {
            "persistence": per_year_aggregation(ic_persist),
            "delta": per_year_aggregation(ic_delta),
        }
        per_cycle = {
            "persistence": [aggregate_period(ic_persist, lab, s, e)
                            for lab, s, e in CYCLES],
            "delta": [aggregate_period(ic_delta, lab, s, e)
                      for lab, s, e in CYCLES],
        }

        # Sign-stability across years (persistence view, the cleanest test)
        yearly_p = per_year["persistence"]
        n_pos_y = sum(1 for y in yearly_p if y["mean_ic"] > 0)
        n_neg_y = sum(1 for y in yearly_p if y["mean_ic"] <= 0)
        sign_stab_y = n_pos_y / len(yearly_p) if yearly_p else float("nan")
        print(f"  persistence: sign_stab across years = "
              f"{n_pos_y}/{len(yearly_p)} = {sign_stab_y:.1%}")
        print(f"  delta:       sign_stab across years = "
              f"{sum(1 for y in per_year['delta'] if y['mean_ic']>0)}/{len(per_year['delta'])}")

        payload["pillars"][pillar] = {
            "persistence_ic_daily_count": int(ic_persist.notna().sum()),
            "delta_ic_daily_count": int(ic_delta.notna().sum()),
            "per_year": per_year,
            "per_cycle": per_cycle,
            "sign_stability_persistence": {
                "n_positive_years": n_pos_y,
                "n_negative_years": n_neg_y,
                "n_total_years": len(yearly_p),
                "stability_fraction": sign_stab_y,
            },
        }

    # Aggregate sign-stability across all 5 pillars (the §DATA-ALIGN scoreboard)
    scoreboard = {}
    for pillar in PILLARS:
        ss = payload["pillars"][pillar]["sign_stability_persistence"]
        scoreboard[pillar] = ss["stability_fraction"]
    print("\n=== Sign-stability scoreboard (persistence, per-pillar) ===")
    for p, v in scoreboard.items():
        print(f"  {p}: {v:.1%}")
    payload["sign_stability_scoreboard"] = scoreboard

    return payload


def format_report(payload: dict) -> str:
    lines = []
    lines.append("# M-WO-2 PARTIAL — Pillar Sign-Stability on 11yr CIS Panel")
    lines.append(f"**Run date:** {datetime.now().isoformat(timespec='seconds')}")
    p = payload["panel"]
    lines.append(f"**Panel:** {p['lo']} → {p['hi']} "
                 f"({p['n_days']} days, {p['n_symbols']} symbols, "
                 f"{p['n_rows']:,} rows)")
    lines.append("")
    lines.append("## ⚠️ Blocking note")
    lines.append(payload["blocking_note"])
    lines.append("")
    lines.append("## Horizons")
    lines.append(f"- persistence_horizon_days = {payload['horizons']['persistence_horizon_days']}")
    lines.append(f"- delta_horizon_days = {payload['horizons']['delta_horizon_days']}")
    lines.append("")
    lines.append("## Cycles (per §DIRECTIVE-M-WO-2)")
    for c in payload["cycles"]:
        lines.append(f"- **{c['label']}**: {c['start']} → {c['end']}")
    lines.append("")
    lines.append("## Sign-Stability Scoreboard (persistence, % of years positive)")
    for pillar, stab in payload["sign_stability_scoreboard"].items():
        lines.append(f"- **{pillar}**: {stab:.1%}")
    lines.append("")
    lines.append("## Per-Pillar Detail")
    for pillar in PILLARS:
        pl = payload["pillars"][pillar]
        ss = pl["sign_stability_persistence"]
        lines.append("")
        lines.append(f"### {pillar}")
        lines.append(f"- persistence IC daily n = {pl['persistence_ic_daily_count']}")
        lines.append(f"- sign_stability (persistence, years): "
                     f"{ss['n_positive_years']}/{ss['n_total_years']} = "
                     f"{ss['stability_fraction']:.1%}")
        lines.append("")
        lines.append("**Per-year (persistence)**")
        lines.append("| year | n_days | mean_IC | t_stat | sign_stab |")
        lines.append("|---:|---:|---:|---:|---:|")
        for y in pl["per_year"]["persistence"]:
            lines.append(f"| {y['label']} | {y['n_days']} | "
                         f"{y['mean_ic']:+.3f} | {y['t_stat']:+.2f} | "
                         f"{y['sign_stability']:.0%} |")
        lines.append("")
        lines.append("**Per-cycle (persistence)**")
        lines.append("| cycle | n_days | mean_IC | t_stat | sign_stab |")
        lines.append("|:---|---:|---:|---:|---:|")
        for c in pl["per_cycle"]["persistence"]:
            lines.append(f"| {c['label']} | {c['n_days']} | "
                         f"{c['mean_ic']:+.3f} | {c['t_stat']:+.2f} | "
                         f"{c['sign_stability']:.0%} |")
        lines.append("")
        lines.append("**Per-cycle (delta — reversal/momentum)**")
        lines.append("| cycle | n_days | mean_IC | t_stat | sign_stab |")
        lines.append("|:---|---:|---:|---:|---:|")
        for c in pl["per_cycle"]["delta"]:
            lines.append(f"| {c['label']} | {c['n_days']} | "
                         f"{c['mean_ic']:+.3f} | {c['t_stat']:+.2f} | "
                         f"{c['sign_stability']:.0%} |")
    return "\n".join(lines)


# ── CLI ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", type=Path, default=None)
    args = parser.parse_args()

    today = datetime.now().strftime("%Y-%m-%d")
    out = args.out_dir or Path(f"reports/m_wo2_pillar_sign_stability_11yr/{today}")
    payload = run(out)

    out.mkdir(parents=True, exist_ok=True)
    with (out / "verdict.json").open("w") as f:
        json.dump(payload, f, indent=2, default=str)
    with (out / "REPORT.md").open("w") as f:
        f.write(format_report(payload))

    print(f"\nWrote {out}/verdict.json")
    print(f"Wrote {out}/REPORT.md")