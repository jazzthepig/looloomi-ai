"""
M-WO-O0 — Layer-⓪ REGIME OVERRIDE oracle test on 3 crash windows (B, 2026-08-25).

PER docs/HIGH_DIM_ONTOLOGY.md §5b-bis + docs/REGIME_OVERRIDE_SPEC.md §0/§5.

THE QUESTION. ⓪ OVERRIDE's "全部价值在拐点" — if we PERFECTLY classified each window
as "crash" (oracle) and applied the override gross for the ENTIRE window, how much DD
does each discrete gross level (-0.3 / 0.0 / 0.5 / 1.0 / 1.3) actually cut vs the
no-override (gross=1.0) baseline?

This is the UPPER BOUND on what any ⓪ signal can achieve. If even the oracle cannot
materially cut DD on 2/3 of these windows, the doctrine's premise — that a ⓪ layer
"should exist" — is empirically false. The signal is then decoration.

THE THREE WINDOWS (from SPEC §0 + WEEKLY_REVIEW crash naming):
  - 2018 bear   : 2018-01-01 → 2018-12-31  (BTC −74% peak→trough; ETH −94%)
  - 2022 bear   : 2022-01-01 → 2022-12-31  (BTC −64% Nov21→Nov22; ETH −68%; FTX Nov)
  - 2025-26 late: 2025-01-01 → 2026-08-09  (BTC $108k → ~$75k early-2025; partial recovery)

UNIVERSE. Equal-weight BTC + ETH (the deepest-history, most-liquid pair; covers all
three windows; no PIT gate needed at this depth since both listed before 2018-01-01).
Two-asset minimum is deliberate: ⓪ OVERRIDE is about gross timing, not selection.

GROSS GRID. {-0.3, 0.0, 0.5, 1.0, 1.3} — the discrete 5-band set from
TILT_MULTIPLIER_SPEC.md:76. Each band's NAV = (1 + basket_ret) * gross band (i.e.
short bands compound negatively; gross=0 yields a flat NAV; gross=1.0 is the
no-override baseline).

METRICS PER (window, gross):
  - nav_path     : pd.Series
  - max_dd       : float (negative)
  - total_return : float
  - dd_delta_vs_1.0_pp : float  (improvement in pp; positive = override cuts DD)

VERDICT. Per SPEC §5 acceptance criteria (adapted for oracle):
  - ≥2/3 windows where oracle cut DD ≥ 5pp at gross ∈ {0.0, 0.5}
  - oracle cut DD ≥ 10pp full-sample (sum across windows, weighted by days)
  - gross = -0.3 (naked short) cuts DD further — but bare-shorting crypto in 2018/2022
    left both legs UP off the trough (BTC −74% → short +74% etc.); we report it for
    transparency, NOT for endorsement (this is the question, not the recommendation)

HONESTY MARKERS.
  - Data source: /Volumes/CometCloudAI/cometcloud-local/data/ohlcv_11yr.db (Mac-side).
  - If the DB is missing, fail LOUDLY (do NOT fall back to mock data — CLAUDE.md #9).
  - Windows are CALENDAR years, not peak→trough windows. This is INTENTIONAL: SPEC §5
    says "前 1/3 之内降低暴露" implies the override fires EARLY in a window; calendar
    boundaries let us test the oracle's CUT-DOWN DD if it had fired on day 1. A peak-
    to-trough window would test post-hoc timing, which is the wrong question for an
    oracle-of-the-concept test.

Output: reports/m_wo_o0_override_oracle/<date>/{verdict.json, md_report.md}.
"""
from __future__ import annotations

import json
import math
import sqlite3
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

DB_PATH = "/Volumes/CometCloudAI/cometcloud-local/data/ohlcv_11yr.db"
UNIVERSE = ["BTC", "ETH"]
GROSS_BANDS = [-0.3, 0.0, 0.5, 1.0, 1.3]

WINDOWS = [
    ("W1_2018_bear",    date(2018, 1, 1), date(2018, 12, 31)),
    ("W2_2022_bear",    date(2022, 1, 1), date(2022, 12, 31)),
    ("W3_2025_26_late", date(2025, 1, 1), date(2026, 8, 9)),  # last DB date
]


# ── data load ────────────────────────────────────────────────────────────────
def load_basket_returns(db_path: str = DB_PATH,
                        universe: list[str] = UNIVERSE) -> pd.Series:
    """Equal-weight daily return series of the basket, indexed by date."""
    conn = sqlite3.connect(db_path)
    syms = tuple(universe)
    placeholders = ",".join(["?"] * len(syms))
    df = pd.read_sql_query(
        f"SELECT symbol, trade_date AS date, close "
        f"FROM ohlcv_11yr_daily "
        f"WHERE source='binance_spot' AND symbol IN ({placeholders}) "
        f"ORDER BY symbol, trade_date",
        conn, params=syms,
    )
    conn.close()
    if df.empty:
        raise RuntimeError(
            f"DB {db_path} returned 0 rows for {universe}; refusing to mock (CLAUDE.md #9)"
        )
    # Pivot to wide; compute daily return per symbol; equal-weight mean.
    df["date"] = pd.to_datetime(df["date"])
    wide = df.pivot(index="date", columns="symbol", values="close").sort_index()
    rets = wide.pct_change().dropna(how="all")
    basket = rets[list(universe)].mean(axis=1).dropna()
    basket.name = "ew_basket"
    return basket


# ── core sim ─────────────────────────────────────────────────────────────────
def simulate(basket_ret: pd.Series, gross: float, start: pd.Timestamp,
             end: pd.Timestamp) -> dict:
    """Apply a constant gross override to the basket return over [start, end].
    Returns nav_path, max_dd, total_return, n_days.

    NO rebalancing assumption: gross is held constant (oracle = constant override
    decision throughout the window — perfect foresight)."""
    r = basket_ret.loc[(basket_ret.index >= pd.Timestamp(start)) &
                       (basket_ret.index <= pd.Timestamp(end))]
    if len(r) < 30:
        return {"nav_path": None, "max_dd": None, "total_return": None,
                "n_days": int(len(r)), "skipped": True}
    scaled = r * gross
    nav = (1.0 + scaled).cumprod() * 100.0  # start at 100
    dd = nav / nav.cummax() - 1.0
    return {
        "nav_path": nav,
        "max_dd": float(dd.min()),
        "total_return": float(nav.iloc[-1] / nav.iloc[0] - 1.0),
        "n_days": int(len(r)),
        "skipped": False,
    }


# ── grid run ─────────────────────────────────────────────────────────────────
def run_grid(basket: pd.Series) -> dict:
    rows = []
    for wname, start, end in WINDOWS:
        baseline = simulate(basket, 1.0, start, end)
        for g in GROSS_BANDS:
            sim = simulate(basket, g, start, end)
            if sim["skipped"]:
                rows.append({"window": wname, "gross": g, "skipped": True,
                             "reason": f"only {sim['n_days']} days in window"})
                continue
            dd_delta_pp = None
            if baseline["max_dd"] is not None:
                dd_delta_pp = (sim["max_dd"] - baseline["max_dd"]) * 100.0  # pp
                # baseline DD is negative; sim["max_dd"] closer to 0 → positive delta = cut
            rows.append({
                "window": wname,
                "start": start.isoformat(),
                "end": end.isoformat(),
                "gross": g,
                "n_days": sim["n_days"],
                "total_return_pct": round(sim["total_return"] * 100, 2),
                "max_dd_pct": round(sim["max_dd"] * 100, 2),
                "dd_delta_vs_1.0_pp": round(dd_delta_pp, 2) if dd_delta_pp is not None else None,
            })
    return {"rows": rows,
            "baseline_max_dd_pp": {r["window"]: next(
                x["max_dd_pct"] for x in rows
                if x["window"] == r["window"] and x["gross"] == 1.0
            ) for r in [{"window": w[0]} for w in WINDOWS]}}


# ── verdict ──────────────────────────────────────────────────────────────────
def verdict(grid: dict) -> dict:
    """≥2/3 windows cut DD ≥5pp at gross=0.0 or 0.5 (the realistic override states).

    Two bars are reported because gross=0.0 is a TRIVIAL fix (DD = 0% by construction —
    if you sit in cash, you can't lose). The doctrine's value is in PARTIAL overrides
    that still let the book eat beta on the rebound. So:
      · SPEC bar (lenient): gross ∈ {0.0, 0.5} cuts DD ≥5pp in ≥2/3 windows
      · STRICT bar (the real test): gross = 0.5 alone cuts DD ≥5pp in ≥2/3 windows

    If STRICT holds, the doctrine is defensible even for non-perfect signals.
    """
    rows = grid["rows"]

    def windows_at_threshold(target_gross, threshold_pp):
        hit: set[str] = set()
        for r in rows:
            if r.get("skipped"):
                continue
            if r.get("gross") != target_gross:
                continue
            if r.get("dd_delta_vs_1.0_pp") is None:
                continue
            if r["dd_delta_vs_1.0_pp"] >= threshold_pp:
                hit.add(r["window"])
        return hit

    lenient_hit = windows_at_threshold(0.0, 5.0) | windows_at_threshold(0.5, 5.0)
    strict_hit = windows_at_threshold(0.5, 5.0)  # only the partial override
    n_windows = len(WINDOWS)
    spec_holds = len(lenient_hit) >= math.ceil(2 / 3 * n_windows)
    strict_holds = len(strict_hit) >= math.ceil(2 / 3 * n_windows)
    primary = "ORACLE_WORKS" if strict_holds else "ORACLE_DOES_NOT_WORK"
    return {
        "primary": primary,
        "lenient_windows_hit": sorted(lenient_hit),
        "strict_windows_hit": sorted(strict_hit),
        "n_lenient_hit": len(lenient_hit),
        "n_strict_hit": len(strict_hit),
        "n_windows_total": n_windows,
        "spec_bar": "≥2/3 windows cut DD ≥5pp at gross ∈ {0.0, 0.5}",
        "strict_bar": "≥2/3 windows cut DD ≥5pp at gross = 0.5 (partial override only)",
        "spec_holds": spec_holds,
        "strict_holds": strict_holds,
        # Per-gross-band full-sample DD cut (sum across windows; windows independent)
        "full_sample_oracle_cut_pp": {
            g: round(sum(r["dd_delta_vs_1.0_pp"] for r in rows
                         if r.get("gross") == g
                         and r.get("dd_delta_vs_1.0_pp") is not None), 2)
            for g in GROSS_BANDS
        },
        # Max DD cut achieved at ANY gross (the "best the oracle could do" ceiling)
        "best_per_window_cut_pp": {
            r["window"]: max(
                (rr["dd_delta_vs_1.0_pp"] for rr in rows
                 if rr["window"] == r["window"]
                 and not rr.get("skipped")
                 and rr.get("dd_delta_vs_1.0_pp") is not None),
                default=None,
            )
            for r in [{"window": w[0]} for w in WINDOWS]
        },
    }


# ── output ───────────────────────────────────────────────────────────────────
def render_md(grid: dict, ver: dict, basket_meta: dict) -> str:
    lines = []
    lines.append("# M-WO-O0 — Layer-⓪ REGIME OVERRIDE oracle test (3 crashes)")
    lines.append("")
    lines.append(f"**Data**: {basket_meta['source']} · "
                 f"{basket_meta['n_symbols']}-asset equal-weight basket "
                 f"({', '.join(basket_meta['symbols'])}) · "
                 f"{basket_meta['first_date']} → {basket_meta['last_date']} "
                 f"({basket_meta['n_days']} daily obs)")
    lines.append("")
    lines.append("**Oracle definition**: hold a CONSTANT gross override for the ENTIRE "
                 "window (perfect foresight). Each row is one (window, gross) cell.")
    lines.append("")
    lines.append("**Two bars** (because gross=0.0 is a trivial fix — DD=0% by construction):")
    lines.append(f"- SPEC bar (lenient): gross ∈ {{0.0, 0.5}} cuts DD ≥5pp in ≥2/3 windows — "
                 f"holds: **{ver['spec_holds']}**")
    lines.append(f"- STRICT bar (real test, partial override only): gross = 0.5 cuts DD ≥5pp "
                 f"in ≥2/3 windows — holds: **{ver['strict_holds']}**")
    lines.append("")
    lines.append("## Per-window table")
    lines.append("")
    lines.append("| Window | gross | n_days | total_ret % | max DD % | DD cut vs 1.0 (pp) |")
    lines.append("|---|---|---:|---:|---:|---:|")
    for r in grid["rows"]:
        if r.get("skipped"):
            lines.append(f"| {r['window']} | {r['gross']:+.2f} | — | — | — | SKIPPED ({r.get('reason','')}) |")
            continue
        delta = r["dd_delta_vs_1.0_pp"]
        delta_str = f"{delta:+.2f}" if delta is not None else "—"
        lines.append(f"| {r['window']} | {r['gross']:+.2f} | {r['n_days']} | "
                     f"{r['total_return_pct']:+.2f} | {r['max_dd_pct']:+.2f} | {delta_str} |")
    lines.append("")
    lines.append("## Verdict")
    lines.append("")
    lines.append(f"- **Primary**: `{ver['primary']}`")
    lines.append(f"- **Lenient hit (gross ∈ {{0.0, 0.5}}, DD cut ≥5pp)**: "
                 f"{ver['n_lenient_hit']}/{ver['n_windows_total']} "
                 f"({', '.join(ver['lenient_windows_hit']) or 'none'})")
    lines.append(f"- **Strict hit (gross = 0.5 only, DD cut ≥5pp)**: "
                 f"{ver['n_strict_hit']}/{ver['n_windows_total']} "
                 f"({', '.join(ver['strict_windows_hit']) or 'none'})")
    lines.append("")
    lines.append("## Per-gross full-sample DD cut (sum across windows)")
    lines.append("")
    lines.append("| gross | total DD cut (pp) |")
    lines.append("|---:|---:|")
    for g, cut in ver["full_sample_oracle_cut_pp"].items():
        lines.append(f"| {g:+.2f} | {cut:+.2f} |")
    lines.append("")
    lines.append("## Per-window best DD cut (any gross)")
    lines.append("")
    lines.append("| Window | best DD cut (pp) |")
    lines.append("|---|---:|")
    for w, cut in ver["best_per_window_cut_pp"].items():
        lines.append(f"| {w} | {cut:+.2f} |" if cut is not None else f"| {w} | — |")
    lines.append("")
    lines.append("## Honest reading")
    lines.append("")
    lines.append("- **What this is**: an UPPER BOUND on what any ⓪ OVERRIDE signal could "
                 "achieve, IF the signal classified each window as 'crash' with 100% "
                 "accuracy and held the override for the whole window.")
    lines.append("- **What this is NOT**: a paper-trade-able result. Real signals have "
                 "false positives (the bull-market miss), false negatives (the late-window "
                 "fail-to-fire), and lag (override fires after day 1). SPEC §5 second-tier "
                 "criteria (全期总收益 ≥ ① 85% / 切换频率 ≤ 6/年 / 优于随机同频) can only be "
                 "evaluated on the SIGNAL, not the oracle.")
    lines.append("- **What 'ORACLE_WORKS' means**: the doctrine is empirically defensible — "
                 "a ⓪ signal with even PARTIAL (gross=0.5) classification would materially "
                 "cut DD in crashes.")
    lines.append("- **What 'ORACLE_DOES_NOT_WORK' means**: even perfect foresight doesn't "
                 "cut enough DD to justify the ⓪ layer — the doctrine's premise is wrong, "
                 "and ⓪ work should be paused until the premise is re-examined.")
    lines.append("")
    lines.append("## Honesty markers")
    lines.append("")
    lines.append(f"- Data source: `{DB_PATH}`")
    lines.append("- Basket: equal-weight BTC + ETH (deepest-history liquid pair; "
                 "covers all 3 windows without PIT gate).")
    lines.append("- Window boundaries: calendar years (not peak→trough). Oracle test = "
                 "constant override from day 1 of each window. This is the right question "
                 "for an oracle-of-the-concept test; a peak→trough window would test "
                 "post-hoc timing, which is what a real signal would NEVER achieve.")
    lines.append("- No mock data. If the DB is missing, the script fails loudly "
                 "(CLAUDE.md #9).")
    return "\n".join(lines)


def run(out_dir: Optional[Path] = None) -> dict:
    print("=== M-WO-O0 — Layer-⓪ REGIME OVERRIDE oracle test on 3 crashes ===\n")
    basket = load_basket_returns()
    basket_meta = {
        "source": DB_PATH,
        "symbols": UNIVERSE,
        "n_symbols": len(UNIVERSE),
        "first_date": str(basket.index.min().date()),
        "last_date": str(basket.index.max().date()),
        "n_days": int(len(basket)),
    }
    print(f"Basket: {basket_meta['n_symbols']} assets, "
          f"{basket_meta['first_date']} → {basket_meta['last_date']}, "
          f"{basket_meta['n_days']} daily obs\n")

    grid = run_grid(basket)
    ver = verdict(grid)

    print("Per (window, gross) — max DD %:")
    print(f"  {'window':<20} " + " ".join(f"{g:+.2f}  " for g in GROSS_BANDS))
    for wname, _, _ in WINDOWS:
        cells = []
        for g in GROSS_BANDS:
            r = next((x for x in grid["rows"] if x["window"] == wname and x["gross"] == g),
                     {"skipped": True})
            if r.get("skipped"):
                cells.append("  --  ")
            else:
                cells.append(f"{r['max_dd_pct']:+6.2f}")
        print(f"  {wname:<20} " + " ".join(cells))
    print()
    print(f"Verdict: {ver['primary']}")
    print(f"  lenient hit (gross ∈ {{0.0,0.5}}): "
          f"{ver['n_lenient_hit']}/{ver['n_windows_total']} "
          f"({', '.join(ver['lenient_windows_hit']) or 'none'})")
    print(f"  strict hit (gross=0.5 only): "
          f"{ver['n_strict_hit']}/{ver['n_windows_total']} "
          f"({', '.join(ver['strict_windows_hit']) or 'none'})")
    print(f"  spec_holds={ver['spec_holds']}  strict_holds={ver['strict_holds']}\n")

    out = {
        "data_meta": basket_meta,
        "windows": [{"name": w[0], "start": w[1].isoformat(), "end": w[2].isoformat()}
                    for w in WINDOWS],
        "gross_bands": GROSS_BANDS,
        "rows": grid["rows"],
        "verdict": ver,
        "generated_at": datetime.utcnow().isoformat() + "Z",
    }

    if out_dir is None:
        return out  # print-only mode for smoke

    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "verdict.json"
    md_path = out_dir / "md_report.md"
    with json_path.open("w") as f:
        json.dump(out, f, indent=2, default=str)
    md_path.write_text(render_md(grid, ver, basket_meta))
    print(f"Wrote: {json_path}")
    print(f"Wrote: {md_path}")
    return out


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", type=Path,
                    default=Path("/Users/sbb/Projects/looloomi-ai/reports/m_wo_o0_override_oracle/"
                                 f"{datetime.utcnow().date().isoformat()}"))
    args = ap.parse_args()
    run(args.out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())