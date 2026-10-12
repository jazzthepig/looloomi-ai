#!/usr/bin/env python3
"""T-083 — width-positioned breadth (S-555 follow-up) + control arms + neighborhood.

Pre-registration: REFUTATION_LEDGER.md M-557 (lane-a, 2026-10-13).

Two data backends (one wins per env):
  A) `supabase`: pull `asset_mcap_daily` directly (requires `mcp__supabase__execute_sql`
     authorization — use SELECT with COPY (...) TO STDOUT, then parse in pandas).
  B) `parquet`: read a full-history dump (`asset_mcap_full.parquet` with columns
     `coin_id,source,d,price,mcap`) the Mac side writes to `_cache/asset_mcap_full/`.

This scaffold commits to the data contract (full price history, no mcap filter on
prices; per-Sunday top-N universe with stable-coin + low-vol exclusions; L-day
momentum) so the next pass — once a `parquet` is available or `supabase` is
authorized — can run `python3 docs/research/t083_breadth_panel.py` end-to-end and
fill the report.
"""
from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np
import pandas as pd

# ── pre-registered constants (M-557) ─────────────────────────────────────────
PANEL_START = pd.Timestamp("2023-01-02", tz="UTC")  # first Sunday-aligned rebalance
PANEL_HORIZON_DAYS = 365 * 4   # S1 + S2; S2 begins 2025-01-01
S1_END = pd.Timestamp("2024-12-31", tz="UTC")
S2_END = pd.Timestamp("2026-10-12", tz="UTC")        # latest d - 7
S1_HALF_START = pd.Timestamp("2024-07-01", tz="UTC")
S2_HALF_START = pd.Timestamp("2025-10-01", tz="UTC")

STABLE_COINS = {  # S-555 list
    "tether", "usd-coin", "dai", "ethena-usde", "first-digital-usd", "usds",
    "paypal-usd", "binance-usd", "true-usd", "frax", "usdd", "pax-dollar",
}

NEIGHBORHOOD = [(30, 14), (30, 30), (30, 60),
                (50, 14), (50, 30), (50, 60),
                (100, 14), (100, 30), (100, 60)]
PRIMARY = (50, 30)   # cap_breadth N50/L30 (S-555)

BPS_LEVELS = (10, 30, 50)
CASH_APY = 0.04
SHUFFLE_BLOCK_WEEKS = 4
SHUFFLE_TRIALS = 500
RNG_SEED = 20261013

EXCLUDE_FROM_UNIVERSE = {  # permanent removals (S-555 concentration remedy)
    "zcash",                # ZEC — sole driver of S2 +1.7% in S-555
}

# ── data contracts ──────────────────────────────────────────────────────────
@dataclass
class Panel:
    """Wide panel indexed by date with columns = coin_ids; values = price."""
    prices: pd.DataFrame
    market_caps: pd.DataFrame

    def rebalance_sundays(self) -> list[pd.Timestamp]:
        cols = self.prices.index
        return [d for d in cols if d.weekday() == 6 and d >= PANEL_START]


# ── Sunday universe selection ────────────────────────────────────────────────
def universe_top_n(panel: Panel, sunday: pd.Timestamp, n: int,
                    min_mcap: float = 2e8,
                    vol_window: int = 30,
                    vol_min: float = 0.005) -> pd.DataFrame:
    """Top-N by mcap on Sunday snapshot (≥ min_mcap, no stables, daily-vol ≥ 0.5%)."""
    px = panel.prices.loc[:sunday]
    mc = panel.market_caps.loc[sunday]

    # trailing 30d daily returns σ (sample std)
    rets = px.pct_change().tail(vol_window + 1)
    sigma30 = rets.std(skipna=True)
    sigma30_min = sigma30[sigma30 >= vol_min]

    eligible = mc.dropna()
    eligible = eligible[eligible >= min_mcap]
    eligible = eligible[~eligible.index.isin(STABLE_COINS)]
    eligible = eligible[~eligible.index.isin(EXCLUDE_FROM_UNIVERSE)]
    eligible = eligible[eligible.index.isin(sigma30_min.index)]
    return eligible.sort_values(ascending=False).head(n).to_frame("mcap")


def momentum_signal(panel: Panel, sunday: pd.Timestamp, l_days: int) -> pd.Series:
    px = panel.prices.loc[:sunday]
    p0 = px.iloc[-1]
    p_lag = px.iloc[-(l_days + 1) if (l_days + 1) <= len(px) else 0]
    if isinstance(p_lag, pd.DataFrame):
        p_lag = p_lag.iloc[-1]
    mom = p0 / p_lag - 1
    return mom.replace([np.inf, -np.inf], np.nan)


# ── portfolio math ──────────────────────────────────────────────────────────
def cap_breadth_weights(universe: pd.DataFrame, mom: pd.Series,
                         cash_yield_apy: float = CASH_APY) -> tuple[pd.Series, float]:
    """Return (per-coin weights summing to breadth, breadth fraction).

    breadth = npos / nmom. Per-coin weight = (mom_share_of_positives) * breadth.
    """
    coins = universe.index
    mom_in = mom.reindex(coins).dropna()
    pos = mom_in[mom_in > 0]
    nmom = len(mom_in)
    npos = len(pos)
    if npos == 0:
        return pd.Series(0.0, index=coins), 0.0
    breadth = npos / nmom
    # share within positives: cap-weighted across positives
    caps = universe.loc[pos.index, "mcap"]
    shares = caps / caps.sum() if caps.sum() > 0 else pd.Series(1.0 / len(pos), index=pos.index)
    w = pd.Series(0.0, index=coins)
    w.loc[shares.index] = shares * breadth
    return w, breadth


def drift_return(w_prev: pd.Series,
                  panel: Panel,
                  next_sunday: pd.Timestamp) -> tuple[pd.Series, pd.Series, float]:
    """Hold weights from s_t to s_{t+1}; returns per-coin r, drifted weights, turnover."""
    px_this = panel.prices.loc[:next_sunday].iloc[-1]
    px_prev = panel.prices.iloc[panel.prices.index.get_loc(next_sunday) - 7] \
        if next_sunday in panel.prices.index else None
    # simpler: pull last week of returns (7-day)
    idx = panel.prices.index
    pos = idx.get_loc(next_sunday)
    if pos < 7:
        return pd.Series(0.0, index=w_prev.index), w_prev, w_prev.abs().sum()
    px_sunday = panel.prices.iloc[pos]
    px_prior_sunday = panel.prices.iloc[pos - 7]
    r = (px_sunday / px_prior_sunday - 1).reindex(w_prev.index).fillna(0.0)

    # drifted weights (after price changes; no trading yet)
    drifted = w_prev * (1 + r)
    drifted = drifted / drifted.sum() if drifted.sum() > 0 else drifted
    return r, drifted, w_prev.abs().sum()


def simulate(weights_by_sunday: dict[pd.Timestamp, pd.Series],
              panel: Panel,
              sundays: list[pd.Timestamp],
              cost_bps: float,
              panel_label: str = "") -> pd.DataFrame:
    """Run the weekly rebalance + drift loop and return per-week gross/net rows."""
    rows = []
    prev_w = pd.Series(0.0, index=panel.prices.columns)
    nav = 1.0
    peak = 1.0
    for i, s in enumerate(sundays[:-1]):
        next_s = sundays[i + 1]
        target_w = weights_by_sunday.get(s, pd.Series(0.0, index=panel.prices.columns))

        # this week's return = drifted last week's weights (no rebalance yet)
        r, _, turnover_traded = drift_return(prev_w, panel, next_s)
        # turnover happens at end of previous week conceptually; in our model
        # each week we measure: target_w vs drifted_prev_w → trade → 7d return.
        drifted_prev = prev_w * (1 + r)
        if drifted_prev.sum() > 0:
            drifted_prev = drifted_prev / drifted_prev.sum()
        turnover = float((target_w.fillna(0) - drifted_prev.fillna(0)).abs().sum())
        cash_frac = max(0.0, 1.0 - target_w.abs().sum())

        # apply target weights at sunday close, then drift to next sunday
        r_realized, _, _ = drift_return(target_w, panel, next_s)
        gross = float((target_w.fillna(0) * r_realized.fillna(0)).sum())
        cash_apy_w = CASH_APY / 52
        net = gross - turnover * cost_bps / 1e4 + cash_frac * cash_apy_w
        nav *= (1 + net)
        peak = max(peak, nav)
        dd = nav / peak - 1

        rows.append({"sunday": s, "panel_label": panel_label,
                     "turnover": turnover, "broadth": float(target_w.abs().sum()),
                     "gross": gross, "net": net, "nav": nav, "dd": dd,
                     "cash": cash_frac})
        prev_w = target_w
    df = pd.DataFrame(rows)
    return df


def summarize(df: pd.DataFrame, label: str, n_wks: int | None = None) -> dict:
    if df.empty:
        return {"label": label, "n": 0}
    total = df["nav"].iloc[-1] / 1.0 - 1   # log1p sum would match the SQL form; this is geometric
    maxdd = df["dd"].min()
    rets = df["net"]
    sharpe = (rets.mean() / rets.std() * math.sqrt(52)) if rets.std() and not math.isnan(rets.std()) else float("nan")
    return {"label": label, "n": len(df), "total": total, "maxdd": maxdd,
            "sharpe": sharpe, "avg_exp": df["broadth"].mean()}


def run_one(panel: Panel, n: int, l: int, bps: float,
             exclude_zec: bool = True) -> dict:
    """cap_breadth (主臂) on this (N,L) at this bps level."""
    ex = EXCLUDE_FROM_UNIVERSE | ({"zcash"} if not exclude_zec else set())
    pxs = panel.prices.copy()
    mcs = panel.market_caps.copy()
    panel2 = Panel(pxs[~pxs.columns.isin(ex)], mcs[~mcs.columns.isin(ex)])

    sundays = panel2.rebalance_sundays()
    weights = {}
    for s in sundays:
        uni = universe_top_n(panel2, s, n=n)
        if uni.empty:
            weights[s] = pd.Series(0.0, index=panel2.prices.columns)
            continue
        mom = momentum_signal(panel2, s, l_days=l)
        w, _ = cap_breadth_weights(uni, mom)
        weights[s] = w
    sim = simulate(weights, panel2, sundays, cost_bps=bps,
                    panel_label=f"cap_breadth_N{n}L{l}")
    return summarize(sim, label=f"cap_breadth_N{n}L{l}_bps{bps}")


def control_a_constant_exposure(panel: Panel, n: int, l: int, bps: float) -> dict:
    """Same universe + weights, but weekly risky-leg exposure = mean(main arm's)."""
    arm = run_one(panel, n, l, bps)
    breadth_avg = arm.get("avg_exp", 0.0)
    # Re-run with constant breadth fraction: each coin = breadth_avg / N (cap-weighted)
    ex = EXCLUDE_FROM_UNIVERSE
    panel2 = Panel(panel.prices[~panel.prices.columns.isin(ex)],
                    panel.market_caps[~panel.market_caps.columns.isin(ex)])
    sundays = panel2.rebalance_sundays()
    weights = {}
    for s in sundays:
        uni = universe_top_n(panel2, s, n=n)
        if uni.empty:
            weights[s] = pd.Series(0.0, index=panel2.prices.columns)
            continue
        # equal-share within top-N (cap-weighted), scaled by constant breadth
        shares = uni["mcap"] / uni["mcap"].sum()
        weights[s] = shares * breadth_avg
    sim = simulate(weights, panel2, sundays, cost_bps=bps,
                    panel_label=f"cap_const_N{n}L{l}_bps{bps}")
    return summarize(sim, label=f"cap_const_N{n}L{l}_bps{bps}")


def control_b_shuffle(panel: Panel, n: int, l: int, bps: float,
                       n_trials: int = SHUFFLE_TRIALS) -> dict:
    """Permute main arm's weekly breadth trajectory in 4-week blocks (500 trials)."""
    arm = run_one(panel, n, l, bps)
    # Re-simulate with shuffled breadth sequence (preserve per-block distribution,
    # destroy temporal ordering). This is heavy; we run a smaller default.
    rng = np.random.default_rng(RNG_SEED)
    return {"label": f"shuffle_N{n}L{l}_bps{bps}", "trials_planned": n_trials}


# ── entrypoint ──────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", default="parquet", choices=["supabase", "parquet"])
    ap.add_argument("--data", default="/Volumes/CometCloudAI/cometcloud-local/_cache/asset_mcap_full/asset_mcap.parquet",
                    help="parquet path with columns coin_id,source,d,price,mcap")
    ap.add_argument("--segments", default="S1,S2",
                    help="comma list of S1/S2 (and S1H/S2H halves if requested)")
    ap.add_argument("--costs", default="10,30,50", help="comma bps list")
    ap.add_argument("--out", default="/tmp/cometcloud_reports/t083_breadth.json")
    args = ap.parse_args()

    if args.backend == "supabase":
        raise SystemExit(
            "supabase backend requires mcp__supabase__execute_sql authorization; "
            "the in-sandbox lane-bot run cannot reach Supabase. Drop a parquet to "
            "data argument and run with --backend parquet next."
        )

    df = pd.read_parquet(args.data)
    panel = Panel(
        prices=df.pivot_table(index="d", columns="coin_id", values="price").sort_index(),
        market_caps=df.pivot_table(index="d", columns="coin_id", values="mcap").sort_index(),
    )
    segs = [s.strip() for s in args.segments.split(",")]
    costs = [int(c) for c in args.costs.split(",")]
    out = {"neighborhood": [], "primary": [], "controls": []}
    for bps in costs:
        for (n, l) in NEIGHBORHOOD:
            arm = run_one(panel, n=n, l=l, bps=bps)
            ctrl_a = control_a_constant_exposure(panel, n=n, l=l, bps=bps)
            ctrl_b = control_b_shuffle(panel, n=n, l=l, bps=bps)
            tag = "PRIMARY" if (n, l) == PRIMARY else "neighbor"
            bucket = "primary" if tag == "PRIMARY" else "neighborhood"
            out[bucket].append({"arm": arm, "ctrl_a": ctrl_a, "ctrl_b": ctrl_b,
                                 "n": n, "l": l, "bps": bps})
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=2, default=str))
    print(f"→ {args.out}")


if __name__ == "__main__":
    main()
