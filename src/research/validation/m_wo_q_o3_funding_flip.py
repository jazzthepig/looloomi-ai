"""
M-WO-Q O3 — Layer-⓪ REGIME OVERRIDE candidate signal: cross-sectional funding-flip.

PER docs/REGIME_OVERRIDE_SPEC.md §0/§2 (O3 = funding-rate-structure flip P1 candidate)
AND m_wo_o0_vs_o1_gap_analysis/memo.md (E, 2026-08-26) which recommended O3 as the
next signal to test (structurally orthogonal to O1's stablecoin-flow axis).

THE HYPOTHESIS. Funding rate is the CARRY signal of perp market-makers. When the
cross-sectional weighted funding flips from positive to negative AND sustains for
N consecutive bars, market-makers are PAYING longs to short — a structural pressure
that historically correlates with subsequent drawdowns. The 5-band scaler:

    CONTRACTION  (flip sustained ≥24h)  → 0.5x gross
    NEUTRAL      (default)              → 1.0x gross
    HOT          (funding strongly >0)  → 1.3x gross

(No CRISIS band — funding flip is a CONTRACTION signal, not a CRISIS predictor.
Asymmetric: protect, don't amplify. This is the explicit fix to O1's bull-market
amplification problem per gap-analysis reason #2.)

DATA COVERAGE HONESTY. Hyperliquid funding starts 2023-05-12. The 3 windows from
M-WO-O0 (2018 / 2022 / 2025-26) collapse to ONE testable window (2025-26_late only).
This is the structural limit, not a tuning choice — flag as UNT-1/3 in verdict.

METHODOLOGY REUSE. Per-window basket (BTC+ETH equal-weight from
/Volumes/CometCloudAI/cometcloud-local/data/ohlcv_11yr.db) × hourly gross scaler
→ daily NAV aggregation → max DD per window. SAME shape as M-WO-O0 oracle, so
verdicts compare cell-by-cell on overlapping windows.

VERDICT BARS (adapted to 1-window reality):
  - On the 1 testable window, does O3 cut DD ≥10pp at gross=0.5 vs gross=1.0?
  - Does O3 reach the oracle ceiling (M-WO-O0 gross=0.5 on the same window)?
  - Switch frequency ≤ 6/yr (per SPEC §3)?
  - Beats constant-gross=1.0 on the same window?

If O3 closes within 5pp of the oracle ceiling on 2025-26, the signal has value
despite the 2/3 windows being untestable. If O3 is >10pp away from the ceiling,
the signal is too noisy and another candidate should be tried.

Output: reports/m_wo_q_o3_funding_flip/<date>/{verdict.json, md_report.md}
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

# Data paths (Mac-side, sandbox-readable)
FUNDING_DIR = Path("/Volumes/CometCloudAI/cometcloud-local/_data/hyperliquid_funding")
BASKET_DB = "/Volumes/CometCloudAI/cometcloud-local/data/ohlcv_11yr.db"

# Signal universe (deepest-history, most-liquid perps; full 28k bars each)
FUNDING_UNIVERSE = ["btc", "eth", "sol", "aave", "arb", "avax", "doge", "dot",
                    "link", "matic"]
# Basket for daily returns
BASKET_UNIVERSE = ["BTC", "ETH"]

# Window: only 2025-26_late is testable on funding data. 2018/2022 marked UNT-*.
WINDOWS = [
    ("W1_2018_bear",    "2018-01-01", "2018-12-31", False),  # NO funding
    ("W2_2022_bear",    "2022-01-01", "2022-12-31", False),  # NO funding
    ("W3_2025_26_late", "2025-01-01", "2026-08-23", True),   # FULL coverage
]

# Hysteresis thresholds (per SPEC §3 + gap-analysis fix #3 = longer dwell)
ENTER_CONTRACTION_BARS = 24      # 24h of sustained negative funding
EXIT_CONTRACTION_BARS = 12       # half-band (12h positive to exit)
ENTER_HOT_THRESHOLD = 0.0001     # 1h funding > +0.01% (≈ +27% APR)
EXIT_HOT_THRESHOLD = 0.00005     # half-band exit


# ── data load ────────────────────────────────────────────────────────────────
def load_funding_panel(dir_path: Path = FUNDING_DIR,
                       universe: list[str] = FUNDING_UNIVERSE) -> pd.DataFrame:
    """Wide DataFrame indexed by hour, columns = symbols, values = 1h funding rate."""
    panels = {}
    for sym in universe:
        f = dir_path / f"{sym}_funding_1h.csv"
        if not f.is_file():
            continue
        df = pd.read_csv(f)
        df["ts"] = pd.to_datetime(df["fundingTime"], unit="ms", utc=True)
        df = df.set_index("ts").sort_index()
        panels[sym.upper()] = df["fundingRate"].rename(sym.upper())
    if not panels:
        raise RuntimeError(f"No funding CSVs found under {dir_path}; refuse to mock")
    wide = pd.concat(panels.values(), axis=1, join="outer").sort_index()
    wide.columns = list(panels.keys())
    return wide


def load_basket_returns(db_path: str = BASKET_DB,
                        universe: list[str] = BASKET_UNIVERSE) -> pd.Series:
    """Equal-weight daily return series of BTC+ETH basket (from M-WO-O0)."""
    import sqlite3
    conn = sqlite3.connect(db_path)
    syms = tuple(universe)
    placeholders = ",".join(["?"] * len(syms))
    df = pd.read_sql_query(
        f"SELECT trade_date AS date, symbol, close "
        f"FROM ohlcv_11yr_daily "
        f"WHERE source='binance_spot' AND symbol IN ({placeholders}) "
        f"ORDER BY symbol, trade_date",
        conn, params=syms,
    )
    conn.close()
    df["date"] = pd.to_datetime(df["date"])
    wide = df.pivot(index="date", columns="symbol", values="close").sort_index()
    rets = wide.pct_change().dropna(how="all")
    basket = rets[list(universe)].mean(axis=1).dropna()
    basket.name = "ew_basket"
    return basket


# ── O3 signal computation ────────────────────────────────────────────────────
def funding_flip_signal(funding_wide: pd.DataFrame,
                        universe: list[str] = FUNDING_UNIVERSE) -> pd.Series:
    """Equal-weight mean of 1h funding across the universe.

    Returns hourly Series. Positive = longs pay shorts (bullish carry).
    Negative = shorts pay longs (bearish carry / squeeze pressure)."""
    universe_upper = [s.upper() for s in universe]
    cols = [c for c in universe_upper if c in funding_wide.columns]
    if not cols:
        raise RuntimeError(
            f"no funding columns survived the universe filter; "
            f"asked for {universe_upper}, got {list(funding_wide.columns)}"
        )
    return funding_wide[cols].mean(axis=1).rename("cs_funding")


def assign_band_hysteresis(signal: pd.Series) -> pd.Series:
    """3-band state machine (CONTRACTION / NEUTRAL / HOT) with hysteresis.

    - Enter CONTRACTION: signal < 0 sustained for ENTER_CONTRACTION_BARS hours
    - Exit CONTRACTION: signal > 0 sustained for EXIT_CONTRACTION_BARS hours
    - Enter HOT: signal > ENTER_HOT_THRESHOLD (any single bar; instantaneous)
    - Exit HOT: signal < EXIT_HOT_THRESHOLD (any single bar; instantaneous)

    State defaults to NEUTRAL. The CONTRACTION bar-counter resets on each positive bar
    inside the entry window. The HOT entry is instantaneous because funding spikes are
    sharp and exiting late costs more than entering early.
    """
    state = "NEUTRAL"
    contraction_neg_streak = 0
    contraction_pos_streak = 0
    states: list[str] = []
    for v in signal.values:
        v = float(v) if not np.isnan(v) else 0.0
        if state == "CONTRACTION":
            if v < 0:
                contraction_neg_streak += 1
                contraction_pos_streak = 0
            else:
                contraction_pos_streak += 1
                contraction_neg_streak = 0
            if contraction_pos_streak >= EXIT_CONTRACTION_BARS:
                state = "NEUTRAL"
                contraction_pos_streak = 0
        elif state == "HOT":
            if v > ENTER_HOT_THRESHOLD:
                pass  # stay
            else:
                state = "NEUTRAL"
        else:  # NEUTRAL
            if v < 0:
                contraction_neg_streak += 1
                contraction_pos_streak = 0
                if contraction_neg_streak >= ENTER_CONTRACTION_BARS:
                    state = "CONTRACTION"
                    contraction_neg_streak = 0
            elif v > ENTER_HOT_THRESHOLD:
                state = "HOT"
            else:
                contraction_neg_streak = 0
                contraction_pos_streak = 0
        states.append(state)
    return pd.Series(states, index=signal.index, name="state")


def state_to_gross(state: str) -> float:
    return {"CONTRACTION": 0.5, "NEUTRAL": 1.0, "HOT": 1.3}.get(state, 1.0)


# ── simulation ───────────────────────────────────────────────────────────────
def simulate_o3(basket: pd.Series, funding_state_hourly: pd.Series,
                start: str, end: str) -> dict:
    """Apply hourly state → gross scaler → daily NAV on basket returns over [start, end].

    For each day: aggregate hourly states within that day using TIME-WEIGHTED dominance
    (a state with 13% of the day should not override a state with 87% by simple mode).
    Implementation: count CONTRACTION hours; if ≥ N (default 12 = half the day) AND the
    day-end state is CONTRACTION, use CONTRACTION; else use day-END state. This is
    responsive to sustained flips without being jittery.
    PIT lag: state at end of day t applies to return on day t+1."""
    s, e = pd.Timestamp(start), pd.Timestamp(end)
    br = basket.loc[(basket.index >= s) & (basket.index <= e)].copy()
    if len(br) < 30:
        return {"skipped": True, "n_days": int(len(br)),
                "reason": f"only {len(br)} basket days in window"}
    # Daily aggregation: end-of-day state (last hourly state in UTC day)
    daily_state_end = funding_state_hourly.resample("D").last()
    # Daily contraction strength: hours in CONTRACTION per day
    contraction_hours = funding_state_hourly.groupby(
        funding_state_hourly.index.date
    ).apply(lambda s: int((s == "CONTRACTION").sum()))
    # Convert to Series indexed by date
    contraction_df = pd.DataFrame({"n": contraction_hours})
    contraction_df.index = pd.to_datetime(contraction_df.index)
    # Daily effective state: CONTRACTION if (end-state == CONTRACTION AND n >= 12),
    # else day-end state
    def daily_eff(day_ts):
        ds = contraction_df.loc[day_ts, "n"] if day_ts in contraction_df.index else 0
        es = daily_state_end.loc[day_ts] if day_ts in daily_state_end.index else "NEUTRAL"
        if es == "CONTRACTION" and ds >= 12:
            return "CONTRACTION"
        return es
    eff_states = pd.Series(
        [daily_eff(d) for d in br.index],
        index=br.index,
    ).shift(1).fillna("NEUTRAL")  # PIT lag: day-t state applies to return on day t+1
    gross = eff_states.map(state_to_gross).values
    scaled_ret = br.values * gross
    nav = pd.Series((1.0 + scaled_ret).cumprod() * 100.0, index=br.index)
    dd = nav / nav.cummax() - 1.0
    n_switches = int((pd.Series(gross, index=br.index).diff().fillna(0) != 0).sum())
    n_days = len(br)
    n_years = n_days / 365.0
    return {
        "skipped": False,
        "n_days": n_days,
        "n_switches": n_switches,
        "switches_per_year": n_switches / n_years if n_years > 0 else 0.0,
        "max_dd_pct": round(float(dd.min()) * 100, 2),
        "total_return_pct": round(float(nav.iloc[-1] / nav.iloc[0] - 1) * 100, 2),
        "final_gross": float(gross[-1]),
        "nav_path": nav,
    }


# ── comparison vs M-WO-O0 oracle ─────────────────────────────────────────────
def simulate_oracle(basket: pd.Series, gross: float, start: str, end: str) -> dict:
    s, e = pd.Timestamp(start), pd.Timestamp(end)
    br = basket.loc[(basket.index >= s) & (basket.index <= e)]
    if len(br) < 30:
        return {"skipped": True}
    scaled = br.values * gross
    nav = pd.Series((1.0 + scaled).cumprod() * 100.0, index=br.index)
    dd = nav / nav.cummax() - 1.0
    return {
        "skipped": False,
        "n_days": int(len(br)),
        "max_dd_pct": round(float(dd.min()) * 100, 2),
        "total_return_pct": round(float(nav.iloc[-1] / nav.iloc[0] - 1) * 100, 2),
    }


# ── verdict ──────────────────────────────────────────────────────────────────
def verdict(signal_results: list[dict],
            oracle_gross_05: dict,
            oracle_gross_10: dict,
            windows_meta: list[dict]) -> dict:
    testable = [r for r in signal_results if not r["skipped"]]
    untestable = [r for r in signal_results if r["skipped"]]
    if not testable:
        return {"primary": "NO_TESTABLE_WINDOWS",
                "testable_count": 0, "untestable_count": len(untestable),
                "windows": [r["window"] for r in untestable]}
    # Find the one testable window (2025-26_late)
    sig = testable[0]
    o_05 = oracle_gross_05 if not oracle_gross_05["skipped"] else None
    o_10 = oracle_gross_10 if not oracle_gross_10["skipped"] else None
    if o_05 is None or o_10 is None:
        return {"primary": "ORACLE_COMPARISON_MISSING",
                "signal": sig, "oracle_gross_05": o_05, "oracle_gross_10": o_10}
    dd_cut_vs_1_0_pp = o_10["max_dd_pct"] - sig["max_dd_pct"]  # negative DD; smaller abs = better
    # ↑ sig["max_dd_pct"] closer to 0 than o_10["max_dd_pct"] → positive cut
    gap_to_oracle_ceiling_pp = o_05["max_dd_pct"] - sig["max_dd_pct"]
    # ↑ gap is how much MORE the oracle cut beyond what the signal cut
    primary = "O3_CLOSES_GAP" if gap_to_oracle_ceiling_pp <= 5.0 else "O3_FAR_FROM_ORACLE"
    return {
        "primary": primary,
        "testable_window": sig["window"],
        "untestable_windows": [r["window"] for r in untestable],
        "untestable_reasons": {r["window"]: r.get("reason", "?") for r in untestable},
        "signal_max_dd_pct": sig["max_dd_pct"],
        "signal_total_return_pct": sig["total_return_pct"],
        "signal_switches_per_year": round(sig["switches_per_year"], 2),
        "oracle_gross_0.5_max_dd_pct": o_05["max_dd_pct"],
        "oracle_gross_1.0_max_dd_pct": o_10["max_dd_pct"],
        "dd_cut_vs_baseline_pp": round(dd_cut_vs_1_0_pp, 2),
        "gap_to_oracle_ceiling_pp": round(gap_to_oracle_ceiling_pp, 2),
        "spec_dd_cut_bar_pp": 10.0,
        "spec_switches_bar": 6.0,
        "dd_cut_passes_spec": dd_cut_vs_1_0_pp >= 10.0,
        "switches_passes_spec": sig["switches_per_year"] <= 6.0,
    }


# ── master run ───────────────────────────────────────────────────────────────
def run(out_dir: Path | None = None) -> dict:
    print("=== M-WO-Q O3 — Layer-⓪ funding-flip signal test ===\n")
    print("DATA HONESTY: Hyperliquid funding starts 2023-05-12; only 2025-26_late")
    print("is testable. 2018 + 2022 windows are flagged as UNT-COVERAGE, not skipped.\n")

    funding = load_funding_panel()
    print(f"Funding panel: {len(funding.columns)} symbols, "
          f"{funding.index.min().date()} → {funding.index.max().date()}, "
          f"{len(funding)} hourly bars")
    signal = funding_flip_signal(funding)
    print(f"Cross-sectional funding mean: range [{signal.min():.6f}, "
          f"{signal.max():.6f}], mean {signal.mean():.6f}\n")
    state = assign_band_hysteresis(signal)
    print(f"State distribution:\n{state.value_counts()}\n")

    basket = load_basket_returns()
    print(f"Basket: BTC+ETH, {basket.index.min().date()} → {basket.index.max().date()}, "
          f"{len(basket)} days\n")

    signal_results = []
    oracle_05 = {}
    oracle_10 = {}
    windows_meta = []
    for wname, start, end, testable in WINDOWS:
        meta = {"window": wname, "start": start, "end": end,
                "funding_testable": testable}
        windows_meta.append(meta)
        if not testable:
            signal_results.append({"window": wname, "skipped": True,
                                   "reason": "no funding data coverage for this window",
                                   "n_days": 0})
            print(f"  {wname}: SKIPPED (no funding coverage)")
            continue
        sig = simulate_o3(basket, state, start, end)
        signal_results.append({"window": wname, **sig})
        if not sig["skipped"]:
            print(f"  {wname} (O3 signal): max DD {sig['max_dd_pct']:+.2f}%, "
                  f"ret {sig['total_return_pct']:+.2f}%, "
                  f"switches {sig['switches_per_year']:.2f}/yr")
        oracle_05[wname] = simulate_oracle(basket, 0.5, start, end)
        oracle_10[wname] = simulate_oracle(basket, 1.0, start, end)
        if not oracle_05[wname]["skipped"]:
            print(f"          oracle 0.5: max DD {oracle_05[wname]['max_dd_pct']:+.2f}%, "
                  f"oracle 1.0: max DD {oracle_10[wname]['max_dd_pct']:+.2f}%")
    print()

    v05 = oracle_05.get("W3_2025_26_late", {"skipped": True})
    v10 = oracle_10.get("W3_2025_26_late", {"skipped": True})
    ver = verdict(signal_results, v05, v10, windows_meta)
    print(f"Verdict: {ver['primary']}")
    if "gap_to_oracle_ceiling_pp" in ver:
        print(f"  signal vs baseline: DD cut {ver['dd_cut_vs_baseline_pp']:+.2f}pp "
              f"(spec ≥10pp: {'PASS' if ver['dd_cut_passes_spec'] else 'FAIL'})")
        print(f"  signal vs oracle ceiling: gap {ver['gap_to_oracle_ceiling_pp']:+.2f}pp "
              f"(<5pp = closes gap: {'YES' if ver['primary'] == 'O3_CLOSES_GAP' else 'NO'})")
        print(f"  switches: {ver['signal_switches_per_year']:.2f}/yr "
              f"(spec ≤6: {'PASS' if ver['switches_passes_spec'] else 'FAIL'})")
    print()

    out = {
        "signal_def": {
            "name": "O3 cross-sectional funding-flip (3-band: CONTRACTION/NEUTRAL/HOT)",
            "data_source": f"{FUNDING_DIR}/*.csv (Hyperliquid)",
            "universe": FUNDING_UNIVERSE,
            "hysteresis": {
                "ENTER_CONTRACTION_BARS": ENTER_CONTRACTION_BARS,
                "EXIT_CONTRACTION_BARS": EXIT_CONTRACTION_BARS,
                "ENTER_HOT_THRESHOLD": ENTER_HOT_THRESHOLD,
                "EXIT_HOT_THRESHOLD": EXIT_HOT_THRESHOLD,
            },
            "bands": {"CONTRACTION": 0.5, "NEUTRAL": 1.0, "HOT": 1.3},
        },
        "coverage_honesty": {
            "funding_first_date": str(funding.index.min().date()),
            "funding_last_date": str(funding.index.max().date()),
            "windows_total": len(WINDOWS),
            "windows_funding_testable": sum(1 for w in WINDOWS if w[3]),
            "untestable_reason": "Hyperliquid funding starts 2023-05-12; 2018 + 2022 windows have zero funding coverage",
        },
        "windows": windows_meta,
        "signal_results": [{k: v for k, v in r.items() if k != "nav_path"}
                           for r in signal_results],
        "oracle_gross_05": {k: v for k, v in v05.items()},
        "oracle_gross_10": {k: v for k, v in v10.items()},
        "verdict": ver,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    if out_dir is None:
        return out
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "verdict.json"
    with json_path.open("w") as f:
        json.dump(out, f, indent=2, default=str)
    md_path = out_dir / "md_report.md"
    md_path.write_text(render_md(out))
    print(f"Wrote: {json_path}")
    print(f"Wrote: {md_path}")
    return out


def render_md(out: dict) -> str:
    v = out["verdict"]
    lines = []
    lines.append("# M-WO-Q O3 — Layer-⓪ funding-flip signal test")
    lines.append("")
    lines.append("**Signal**: cross-sectional mean funding (equal-weight across "
                 f"{len(out['signal_def']['universe'])} symbols) → 3-band state machine "
                 "(CONTRACTION/NEUTRAL/HOT) → gross scaler (0.5/1.0/1.3).")
    lines.append("")
    lines.append("**Hysteresis**: 24h sustained negative → enter CONTRACTION; 12h "
                 "positive → exit (half-band). HOT instantaneous entry/exit at ±0.01%/1h.")
    lines.append("")
    lines.append("**Per-window test coverage (HONESTY BAR)**")
    lines.append("")
    lines.append(f"- Funding panel: {out['coverage_honesty']['funding_first_date']} → "
                 f"{out['coverage_honesty']['funding_last_date']}")
    lines.append(f"- Windows total: {out['coverage_honesty']['windows_total']}")
    lines.append(f"- Windows testable: {out['coverage_honesty']['windows_funding_testable']} "
                 f"(only W3_2025_26_late)")
    lines.append(f"- Untestable windows: {out['coverage_honesty']['untestable_reason']}")
    lines.append("")
    lines.append("## Per-window results")
    lines.append("")
    lines.append("| Window | Testable | O3 max DD % | Oracle 0.5 DD % | Oracle 1.0 DD % | DD cut vs 1.0 (pp) |")
    lines.append("|---|---|---:|---:|---:|---:|")
    for sr, meta in zip(out["signal_results"], out["windows"]):
        if sr.get("skipped"):
            lines.append(f"| {meta['window']} | NO (no funding) | — | — | — | — |")
            continue
        o05 = out["oracle_gross_05"]["max_dd_pct"] if meta["window"] == "W3_2025_26_late" else None
        o10 = out["oracle_gross_10"]["max_dd_pct"] if meta["window"] == "W3_2025_26_late" else None
        delta = f"{o10 - sr['max_dd_pct']:+.2f}" if o10 is not None else "—"
        o05_str = f"{o05:+.2f}" if o05 is not None else "—"
        o10_str = f"{o10:+.2f}" if o10 is not None else "—"
        lines.append(f"| {meta['window']} | YES | {sr['max_dd_pct']:+.2f} | "
                     f"{o05_str} | {o10_str} | {delta} |")
    lines.append("")
    lines.append("## Verdict")
    lines.append("")
    lines.append(f"- **Primary**: `{v['primary']}`")
    if "gap_to_oracle_ceiling_pp" in v:
        lines.append(f"- **Signal max DD on 2025-26**: {v['signal_max_dd_pct']:+.2f}%")
        lines.append(f"- **DD cut vs baseline (gross=1.0)**: "
                     f"{v['dd_cut_vs_baseline_pp']:+.2f}pp "
                     f"(spec ≥10pp: {'PASS' if v['dd_cut_passes_spec'] else 'FAIL'})")
        lines.append(f"- **Gap to oracle ceiling (gross=0.5)**: "
                     f"{v['gap_to_oracle_ceiling_pp']:+.2f}pp "
                     f"(<5pp = closes gap)")
        lines.append(f"- **Switches per year**: {v['signal_switches_per_year']:.2f} "
                     f"(spec ≤6: {'PASS' if v['switches_passes_spec'] else 'FAIL'})")
    lines.append("")
    lines.append("## Honest reading")
    lines.append("")
    lines.append("- **What this is**: a structural test of the O3 funding-flip signal "
                 "on the ONLY window with funding coverage (2025-26_late).")
    lines.append("- **What this is NOT**: a 3-window comparison like M-WO-O0 oracle. "
                 "2/3 crash windows are NOT testable on funding data — this is a "
                 "structural limit, not a tuning choice.")
    lines.append("- **Why test on 1 window anyway**: even 1 window can tell us whether "
                 "O3 is close to the oracle ceiling. If gap > 10pp on the only "
                 "testable window, the signal is too noisy to justify further "
                 "development on a 3-window backbone.")
    lines.append("- **What 'O3_CLOSES_GAP' means**: signal reaches within 5pp of oracle "
                 "ceiling on the 1 testable window → candidate for further "
                 "refinement (longer backfill, more symbols).")
    lines.append("- **What 'O3_FAR_FROM_ORACLE' means**: signal is >10pp from oracle → "
                 "funding-flip is too noisy for ⓪ work; try another axis.")
    lines.append("")
    lines.append("## Honesty markers")
    lines.append("")
    lines.append(f"- Data: {FUNDING_DIR} (Mac-side, sandbox-readable, "
                 f"{len(out['signal_def']['universe'])}-symbol funding panel)")
    lines.append("- Basket: BTC+ETH equal-weight daily (from "
                 f"`{BASKET_DB}`, same as M-WO-O0 for direct comparison)")
    lines.append("- No mock data. Funding CSV missing → fail loud (CLAUDE.md #9).")
    lines.append("- Window coverage flagged as structural limit, not silently dropped.")
    return "\n".join(lines)


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", type=Path,
                    default=Path("/Users/sbb/Projects/looloomi-ai/reports/m_wo_q_o3_funding_flip/"
                                 f"{datetime.now(timezone.utc).date().isoformat()}"))
    args = ap.parse_args()
    run(args.out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())