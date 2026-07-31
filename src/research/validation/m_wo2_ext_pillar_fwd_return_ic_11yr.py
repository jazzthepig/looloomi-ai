"""
M-WO-2 EXTENDED — Pillar × fwd-return IC on the 11yr joint panel.

Per §DIRECTIVE 2026-07-27 M-WO-2 (the binding follow-up):
    Re-run R46/R78/R79/S-78 on the 11yr panel with per-cycle sign stability.

This module fulfills the ORIGINAL §DIRECTIVE-M-WO-2 ask (per-pillar IC ×
REGIME × CYCLE on forward returns) — the M-WO-2 PARTIAL module
(m_wo2_pillar_sign_stability_11yr.py) only did pillar-vs-pillar IC. The
full M-WO-2 needs pillar-vs-fwd-return IC, which requires OHLCV.

Inputs:
  - CIS 11yr: _data/cis_historical/cis_historical_11yr.csv (75,478 rows)
  - OHLCV 11yr: /tmp/cometcloud_data/ohlcv_11yr.db (95,328 rows,
    binance_spot source)
  - Cross-link tier: TIER-I (BOTH CIS+OHLCV ≥2000d, 20 symbols)

Methodology:
  - For each (date, symbol) in the CIS panel, compute next-day fwd-return
    from the OHLCV panel (close[t+1] / close[t] - 1).
  - Per-pillar IC: cross-sectional Spearman rank-IC of pillar(t) vs
    fwd-return(t, t+1), per day.
  - Per-year + per-cycle aggregation across the §DIRECTIVE-M-WO-2 cycle
    list.
  - Sign-stability scoreboard per pillar.
  - PIT-safe: fwd-return uses close[t+1], pillar uses score at date t.

This re-tests the §DATA-ALIGN ②.C.1 question on the full 11yr panel:
does pillar (especially pillar_O) predict forward returns across cycles?

If pillar_O IC is positive + t>1.96 across cycles, R46 IS the underlying
mechanism (pillar_O → fwd-return). If negative or unstable, R46 was a
panel artifact.

Output:
  - reports/m_wo2_ext_pillar_fwd_return_ic_11yr/<date>/{verdict.json, REPORT.md}
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

# ── Paths & constants ────────────────────────────────────────────────────────
CIS_PATH = Path("_data/cis_historical/cis_historical_11yr.csv")
OHLCV_DB = Path("/tmp/cometcloud_data/ohlcv_11yr.db")
PILLARS = ["pillar_f", "pillar_m", "pillar_o", "pillar_s", "pillar_a"]

# §DIRECTIVE-M-WO-2 cycle windows
CYCLES = [
    ("2018_bear", "2018-01-01", "2018-12-31"),
    ("2020-21_bull", "2020-03-01", "2021-11-30"),
    ("2022_bear", "2022-01-01", "2022-12-31"),
    ("2023-24_recovery", "2023-01-01", "2024-12-31"),
    ("2025-26_bear", "2025-01-01", "2026-07-31"),
]

# TIER-I binding set (BOTH CIS+OHLCV ≥2000d) — from cross-link report
TIER_I_SYMBOLS = [
    "AAVE", "ADA", "ALGO", "ATOM", "AVAX", "BNB", "BTC", "COMP", "DOT",
    "ETH", "FIL", "HBAR", "INJ", "LINK", "LTC", "NEAR", "RUNE", "SOL",
    "UNI", "XRP",
]

# Forward horizon (next-day)
FWD_HORIZON_DAYS = 1


# ── Panel loaders ────────────────────────────────────────────────────────────
def load_cis() -> pd.DataFrame:
    df = pd.read_csv(CIS_PATH)
    df["date"] = pd.to_datetime(df["recorded_at"]).dt.normalize()
    # Strip tz to align with OHLCV (tz-naive UTC dates)
    if df["date"].dt.tz is not None:
        df["date"] = df["date"].dt.tz_localize(None)
    df["macro_regime"] = df["macro_regime"].astype(str).str.upper()
    return df[["date", "symbol"] + PILLARS].drop_duplicates(
        subset=["date", "symbol"]).sort_values(["date", "symbol"]).reset_index(drop=True)


def load_ohlcv(tier_i_only: bool = True) -> pd.DataFrame:
    """Load daily OHLCV (close prices) from the 11yr sqlite."""
    conn = sqlite3.connect(str(OHLCV_DB))
    where = ""
    if tier_i_only:
        sym_list = ",".join(f"'{s}'" for s in TIER_I_SYMBOLS)
        where = f" WHERE symbol IN ({sym_list})"
    df = pd.read_sql(f"SELECT symbol, trade_date, close FROM ohlcv_11yr_daily{where}",
                     conn)
    conn.close()
    df["date"] = pd.to_datetime(df["trade_date"]).dt.normalize()
    df = df.sort_values(["symbol", "date"]).reset_index(drop=True)
    return df


def build_fwd_returns(ohlcv: pd.DataFrame) -> pd.DataFrame:
    """Compute next-day fwd-return per (symbol, date)."""
    ohlcv = ohlcv.copy()
    ohlcv["fwd_return"] = ohlcv.groupby("symbol")["close"].shift(-FWD_HORIZON_DAYS) / ohlcv["close"] - 1.0
    return ohlcv[["date", "symbol", "close", "fwd_return"]]


# ── Join + per-pillar IC ────────────────────────────────────────────────────
def build_joined(cis: pd.DataFrame, ohlcv: pd.DataFrame) -> pd.DataFrame:
    """Inner join CIS × OHLCV on (date, symbol). PIT-safe: fwd-return is
    close[t+1]/close[t]-1, so a pillar score at date t is paired with
    next-day return.
    """
    fwd = build_fwd_returns(ohlcv)
    return cis.merge(fwd[["date", "symbol", "fwd_return"]], on=["date", "symbol"], how="inner")


def daily_rank_ic_fwd_return(joined: pd.DataFrame, pillar: str) -> pd.Series:
    """Cross-sectional Spearman rank-IC of pillar(t) vs fwd-return(t, t+1)
    per day. Returns Series indexed by date with NaN for invalid days.
    """
    df = pd.DataFrame({
        "date": joined["date"], "x": joined[pillar], "y": joined["fwd_return"]
    })
    out = {}
    for d, g in df.groupby("date"):
        sub = g.dropna()
        if len(sub) < 5:
            continue
        # Need non-zero fwd-return variance for spearmanr
        if sub["y"].std() == 0 or sub["x"].std() == 0:
            continue
        rho, _ = spearmanr(sub["x"].values, sub["y"].values)
        out[d] = float(rho)
    return pd.Series(out).sort_index()


def aggregate_period(ic: pd.Series, label: str, start: str, end: str) -> dict:
    idx = ic.index
    if idx.tz is not None:
        ts_start = pd.Timestamp(start, tz=idx.tz)
        ts_end = pd.Timestamp(end, tz=idx.tz)
    else:
        ts_start = pd.Timestamp(start)
        ts_end = pd.Timestamp(end)
    sub = ic.loc[(ic.index >= ts_start) & (ic.index <= ts_end)].dropna()
    n = len(sub)
    if n == 0:
        return {"label": label, "n_days": 0, "mean_ic": float("nan"),
                "t_stat": float("nan"), "n_positive_days": 0,
                "sign_stability": float("nan")}
    mean = float(sub.mean())
    std = float(sub.std(ddof=1)) if n > 1 else 0.0
    t = (mean / (std / np.sqrt(n))) if std > 0 else 0.0
    n_pos = int((sub > 0).sum())
    sign_stab = n_pos / n if n > 0 else float("nan")
    return {"label": label, "start": start, "end": end, "n_days": int(n),
            "mean_ic": mean, "std_ic": std, "t_stat": float(t),
            "n_positive_days": n_pos, "sign_stability": float(sign_stab)}


def per_year_aggregation(ic: pd.Series) -> list[dict]:
    years = sorted(set(ic.index.year))
    return [aggregate_period(ic, str(y), f"{y}-01-01", f"{y}-12-31") for y in years]


def per_cycle_aggregation(ic: pd.Series) -> list[dict]:
    return [aggregate_period(ic, lab, s, e) for lab, s, e in CYCLES]


# ── Run ──────────────────────────────────────────────────────────────────────
def run(out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    print("=== M-WO-2 EXTENDED — Pillar × fwd-return IC on 11yr joint panel ===\n")
    print(f"TIER-I binding set: {len(TIER_I_SYMBOLS)} symbols (≥2000d OHLCV × CIS)")
    print(f"CYCLES: {len(CYCLES)}")
    print()

    cis = load_cis()
    print(f"CIS panel: {len(cis):,} rows × {cis['symbol'].nunique()} syms")
    ohlcv = load_ohlcv(tier_i_only=True)
    print(f"OHLCV panel (TIER-I): {len(ohlcv):,} rows × {ohlcv['symbol'].nunique()} syms")
    joined = build_joined(cis, ohlcv)
    print(f"Joined (CIS × OHLCV): {len(joined):,} rows × "
          f"{joined['symbol'].nunique()} syms over {joined['date'].nunique()} days")
    print(f"  fwd_return non-null: {joined['fwd_return'].notna().sum():,}")
    print()

    payload = {
        "panel": {
            "cis_rows": int(len(cis)),
            "cis_symbols": int(cis["symbol"].nunique()),
            "ohlcv_rows_tier_i": int(len(ohlcv)),
            "ohlcv_symbols_tier_i": int(ohlcv["symbol"].nunique()),
            "joined_rows": int(len(joined)),
            "joined_symbols": int(joined["symbol"].nunique()),
            "joined_days": int(joined["date"].nunique()),
            "fwd_return_non_null": int(joined["fwd_return"].notna().sum()),
        },
        "horizons": {"fwd_return_days": FWD_HORIZON_DAYS},
        "tier_i_symbols": TIER_I_SYMBOLS,
        "cycles": [{"label": lab, "start": s, "end": e} for lab, s, e in CYCLES],
        "blocking_note": (
            "TIER-I (BOTH CIS+OHLCV ≥2000d) provides 20-symbol binding set. "
            "Per-cycle sign stability is the §DIRECTIVE-M-WO-2 acceptance criterion. "
            "PIT-safe: pillar(t) vs fwd-return(t, t+1)."
        ),
        "pillars": {},
    }

    scoreboard = {}
    for pillar in PILLARS:
        print(f"\n=== {pillar.upper()} ===")
        ic = daily_rank_ic_fwd_return(joined, pillar)
        per_year = per_year_aggregation(ic)
        per_cycle = per_cycle_aggregation(ic)
        n_pos_y = sum(1 for y in per_year if y["mean_ic"] > 0)
        sign_stab_y = n_pos_y / len(per_year) if per_year else float("nan")
        print(f"  n_days_with_ic: {ic.notna().sum()}")
        print(f"  per-year sign_stab: {n_pos_y}/{len(per_year)} = {sign_stab_y:.1%}")
        print(f"  per-cycle sign_stab: " + ", ".join(
            f"{c['label']}={c['sign_stability']:.1%}" for c in per_cycle
        ))
        scoreboard[pillar] = sign_stab_y
        payload["pillars"][pillar] = {
            "n_daily_ic": int(ic.notna().sum()),
            "per_year": per_year,
            "per_cycle": per_cycle,
            "sign_stability_years": {
                "n_positive": n_pos_y,
                "n_total": len(per_year),
                "stability_fraction": sign_stab_y,
            },
        }

    payload["sign_stability_scoreboard"] = scoreboard

    # Per-cycle winners per pillar
    cycle_winners = {}
    for c in CYCLES:
        lab = c[0]
        cycle_winners[lab] = {
            pillar: payload["pillars"][pillar]["per_cycle"][i]["mean_ic"]
            for i, pillar in enumerate(PILLARS)
        }
    payload["cycle_winners"] = cycle_winners

    return payload


def format_report(payload: dict) -> str:
    p = payload["panel"]
    lines = []
    lines.append("# M-WO-2 EXTENDED — Pillar × Fwd-Return IC on 11yr Joint Panel")
    lines.append(f"**Run date:** {datetime.now(timezone.utc).isoformat(timespec='seconds')}")
    lines.append(f"**Joined panel:** {p['joined_rows']:,} rows × "
                 f"{p['joined_symbols']} syms × {p['joined_days']:,} days")
    lines.append(f"**Fwd-return non-null**: {p['fwd_return_non_null']:,}")
    lines.append(f"**TIER-I binding set**: {len(payload['tier_i_symbols'])} symbols")
    lines.append("")
    lines.append("## §DIRECTIVE-M-WO-2 ASK")
    lines.append(payload["blocking_note"])
    lines.append("")
    lines.append("## Sign-Stability Scoreboard (per-year, % of years positive)")
    for pillar, stab in payload["sign_stability_scoreboard"].items():
        lines.append(f"- **{pillar}**: {stab:.1%}")
    lines.append("")
    lines.append("## Per-Pillar × Per-Cycle fwd-return IC (BINDING)")
    lines.append("| pillar | 2018_bear | 2020-21_bull | 2022_bear | 2023-24_recovery | 2025-26_bear |")
    lines.append("|:---|---:|---:|---:|---:|---:|")
    for pillar in PILLARS:
        c = payload["pillars"][pillar]["per_cycle"]
        cells = []
        for c_entry in c:
            if c_entry["mean_ic"] != c_entry["mean_ic"]:
                cells.append("—")
            else:
                cells.append(f"{c_entry['mean_ic']:+.3f}")
        lines.append(f"| {pillar} | " + " | ".join(cells) + " |")
    lines.append("")
    lines.append("## Per-Pillar × Per-Cycle t-stat BINDING")
    lines.append("| pillar | 2018_bear | 2020-21_bull | 2022_bear | 2023-24_recovery | 2025-26_bear |")
    lines.append("|:---|---:|---:|---:|---:|---:|")
    for pillar in PILLARS:
        c = payload["pillars"][pillar]["per_cycle"]
        cells = []
        for c_entry in c:
            if c_entry["t_stat"] != c_entry["t_stat"]:
                cells.append("—")
            else:
                cells.append(f"{c_entry['t_stat']:+.2f}")
        lines.append(f"| {pillar} | " + " | ".join(cells) + " |")
    lines.append("")
    lines.append("## Per-Pillar Per-Year Detail (persistence + fwd-return)")
    for pillar in PILLARS:
        pl = payload["pillars"][pillar]
        lines.append(f"\n### {pillar}")
        lines.append(f"- n_daily_ic: {pl['n_daily_ic']}")
        lines.append(f"- sign_stab (years): {pl['sign_stability_years']['n_positive']}"
                     f"/{pl['sign_stability_years']['n_total']} = "
                     f"{pl['sign_stability_years']['stability_fraction']:.1%}")
        lines.append("")
        lines.append("| year | n_days | mean_IC | t_stat | sign_stab |")
        lines.append("|---:|---:|---:|---:|---:|")
        for y in pl["per_year"]:
            lines.append(f"| {y['label']} | {y['n_days']} | "
                         f"{y['mean_ic']:+.3f} | {y['t_stat']:+.2f} | "
                         f"{y['sign_stability']:.0%} |")
    return "\n".join(lines)


# ── CLI ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", type=Path, default=None)
    args = parser.parse_args()

    today = datetime.now().strftime("%Y-%m-%d")
    out = args.out_dir or Path(f"reports/m_wo2_ext_pillar_fwd_return_ic_11yr/{today}")
    payload = run(out)

    out.mkdir(parents=True, exist_ok=True)
    with (out / "verdict.json").open("w") as f:
        json.dump(payload, f, indent=2, default=str)
    with (out / "REPORT.md").open("w") as f:
        f.write(format_report(payload))

    print(f"\nWrote {out}/verdict.json")
    print(f"Wrote {out}/REPORT.md")
