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
    """Run the weekly rebalance + drift loop and return per-week gross/net rows.

    Vectorizable via `simulate_fast(W, R, cost_bps)` for the shuffle path; this
    pandas-loop variant is kept for the main arm so the per-week ledger is
    inspectable.
    """
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


def simulate_fast(W: np.ndarray, R: np.ndarray, cost_bps: float,
                   cash_apy: float = CASH_APY) -> tuple[float, float]:
    """Vectorized single-trial weekly rebalance + drift / same logic as simulate().

    W: (T, N) per-coin target weights at each rebalance Sunday
    R: (T, N) per-coin weekly returns
    Returns (total_return, max_drawdown).
    """
    T, _ = W.shape
    nav = 1.0
    peak = 1.0
    max_dd = 0.0
    prev_w = np.zeros(W.shape[1])
    cash_apy_w = cash_apy / 52
    for t in range(T):
        target_w = W[t]
        cash_frac = max(0.0, 1.0 - float(np.abs(target_w).sum()))
        if t > 0 and prev_w.sum() > 0:
            drifted = prev_w * (1 + R[t - 1])
            drifted_sum = drifted.sum()
            if drifted_sum > 0:
                drifted = drifted / drifted_sum * prev_w.sum()
            else:
                drifted = prev_w.copy()
        else:
            drifted = prev_w.copy()
        turnover = float(np.abs(target_w - drifted).sum())
        gross = float((target_w * R[t]).sum())
        net = gross - turnover * cost_bps / 1e4 + cash_frac * cash_apy_w
        nav *= 1 + net
        peak = max(peak, nav)
        max_dd = min(max_dd, nav / peak - 1)
        prev_w = target_w
    return nav - 1, max_dd


def block_permutation_indices(T: int, block_size: int,
                                rng: np.random.Generator) -> np.ndarray:
    """Return a permutation of [0..T) produced by permuting contiguous blocks.

    T weeks are split into floor(T/block_size) full blocks of `block_size` weeks;
    any leftover tail (< block_size weeks) stays in place at the end. This is the
    time-series shuffle used by control_b_shuffle — same marginal distribution per
    week, no temporal ordering.
    """
    n_full_blocks = T // block_size
    n_keep = n_full_blocks * block_size
    if n_full_blocks < 2:
        return np.arange(T)
    perm = rng.permutation(n_full_blocks)
    out = np.concatenate(
        [np.arange(p * block_size, (p + 1) * block_size) for p in perm]
    )
    if n_keep < T:
        out = np.concatenate([out, np.arange(n_keep, T)])
    return out


def summarize(df: pd.DataFrame, label: str, n_wks: int | None = None) -> dict:
    if df.empty:
        return {"label": label, "n": 0}
    total = df["nav"].iloc[-1] / 1.0 - 1   # log1p sum would match the SQL form; this is geometric
    maxdd = df["dd"].min()
    rets = df["net"]
    sharpe = (rets.mean() / rets.std() * math.sqrt(52)) if rets.std() and not math.isnan(rets.std()) else float("nan")
    return {"label": label, "n": len(df), "total": total, "maxdd": maxdd,
            "sharpe": sharpe, "avg_exp": df["broadth"].mean()}


def slice_for_segment(panel: Panel, segment: str) -> Panel:
    """Return a panel whose prices/mcaps are restricted to the segment's dates."""
    if segment == "S1":
        start, end = PANEL_START, S1_END
    elif segment == "S2":
        start, end = pd.Timestamp("2025-01-01", tz="UTC"), S2_END
    elif segment == "S1H":
        start, end = S1_HALF_START, S1_END
    elif segment == "S2H":
        start, end = S2_HALF_START, S2_END
    else:
        raise ValueError(f"unknown segment {segment}")
    mask = (panel.prices.index >= start) & (panel.prices.index <= end)
    return Panel(panel.prices.loc[mask], panel.market_caps.loc[mask])


def build_main_arm_panel(panel: Panel, n: int, l: int,
                          exclude_zec: bool = True) -> tuple[Panel, list[pd.Timestamp],
                                                                np.ndarray, np.ndarray]:
    """Build (panel, sundays, W, R) for the cap_breadth main arm on (N,L)."""
    ex = EXCLUDE_FROM_UNIVERSE | ({"zcash"} if not exclude_zec else set())
    pxs = panel.prices[~panel.prices.columns.isin(ex)]
    mcs = panel.market_caps[~panel.market_caps.columns.isin(ex)]
    panel2 = Panel(pxs, mcs)

    sundays = panel2.rebalance_sundays()
    W = np.zeros((len(sundays) - 1, len(panel2.prices.columns)))
    for i, s in enumerate(sundays[:-1]):
        uni = universe_top_n(panel2, s, n=n)
        if uni.empty:
            continue
        mom = momentum_signal(panel2, s, l_days=l)
        w, _ = cap_breadth_weights(uni, mom)
        W[i] = w.reindex(panel2.prices.columns).fillna(0).values

    R = np.zeros((len(sundays) - 1, len(panel2.prices.columns)))
    for i in range(1, len(sundays)):
        idx = panel2.prices.index
        cur = panel2.prices.iloc[idx.get_loc(sundays[i])]
        prev = panel2.prices.iloc[idx.get_loc(sundays[i - 1])]
        R[i - 1] = (cur / prev - 1).fillna(0).values

    return panel2, sundays, W, R


def run_one(panel: Panel, n: int, l: int, bps: float,
             segment: str | None = None,
             exclude_zec: bool = True) -> dict:
    """cap_breadth (主臂) on this (N,L) at this bps level.

    If `segment` is provided, the panel is sliced first and only that segment's
    metrics are returned; otherwise the full panel is used.
    """
    seg_panel = slice_for_segment(panel, segment) if segment else panel
    ex = EXCLUDE_FROM_UNIVERSE | ({"zcash"} if not exclude_zec else set())
    pxs = seg_panel.prices.copy()
    mcs = seg_panel.market_caps.copy()
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
    return summarize(sim, label=f"cap_breadth_N{n}L{l}_bps{bps}_seg{segment or 'ALL'}")


def control_a_constant_exposure(panel: Panel, n: int, l: int, bps: float,
                                  segment: str | None = None) -> dict:
    """Same universe + weights, but weekly risky-leg exposure = mean(main arm's)."""
    arm = run_one(panel, n, l, bps, segment=segment)
    breadth_avg = arm.get("avg_exp", 0.0)
    seg_panel = slice_for_segment(panel, segment) if segment else panel
    ex = EXCLUDE_FROM_UNIVERSE
    panel2 = Panel(seg_panel.prices[~seg_panel.prices.columns.isin(ex)],
                    seg_panel.market_caps[~seg_panel.market_caps.columns.isin(ex)])
    sundays = panel2.rebalance_sundays()
    weights = {}
    for s in sundays:
        uni = universe_top_n(panel2, s, n=n)
        if uni.empty:
            weights[s] = pd.Series(0.0, index=panel2.prices.columns)
            continue
        shares = uni["mcap"] / uni["mcap"].sum()
        weights[s] = shares * breadth_avg
    sim = simulate(weights, panel2, sundays, cost_bps=bps,
                    panel_label=f"cap_const_N{n}L{l}_bps{bps}")
    return summarize(sim, label=f"cap_const_N{n}L{l}_bps{bps}_seg{segment or 'ALL'}")


def control_b_shuffle(panel: Panel, n: int, l: int, bps: float,
                       segment: str | None = None,
                       n_trials: int = SHUFFLE_TRIALS,
                       block_size: int = SHUFFLE_BLOCK_WEEKS,
                       rng_seed: int = RNG_SEED) -> dict:
    """4-week block permutation of the main arm's per-coin weight sequence.

    For each of `n_trials` independent random permutations:
      - partition the T rebalance weeks into contiguous `block_size`-week blocks
      - randomly permute the blocks (tail weeks that don't fill a block stay put)
      - re-simulate the portfolio with the permuted weight sequence
    Aggregate (p50, p90) of total return and max drawdown across trials.

    The same marginal distribution per week is preserved; only temporal ordering
    is destroyed. This is the random-timing control for whether main arm's edge
    (if any) comes from "when" rather than "what".
    """
    seg_panel = slice_for_segment(panel, segment) if segment else panel
    _panel2, sundays, W, R = build_main_arm_panel(seg_panel, n=n, l=l,
                                                   exclude_zec=True)
    T = W.shape[0]
    if T < block_size * 2:
        return {"label": f"shuffle_N{n}L{l}_bps{bps}_seg{segment}",
                "trials": 0, "p50_total": float("nan"), "p90_total": float("nan"),
                "p50_maxdd": float("nan"), "p90_maxdd": float("nan"),
                "note": f"segment too short (T={T}) for {block_size}-week blocks"}

    rng = np.random.default_rng(rng_seed)
    totals = np.empty(n_trials, dtype=np.float64)
    maxdds = np.empty(n_trials, dtype=np.float64)
    for k in range(n_trials):
        perm = block_permutation_indices(T, block_size, rng)
        W_shuf = W[perm]
        total, maxdd = simulate_fast(W_shuf, R, cost_bps=bps)
        totals[k] = total
        maxdds[k] = maxdd

    return {
        "label": f"shuffle_N{n}L{l}_bps{bps}_seg{segment or 'ALL'}",
        "trials": int(n_trials),
        "block_size_weeks": int(block_size),
        "rng_seed": int(rng_seed),
        "p50_total": float(np.percentile(totals, 50)),
        "p90_total": float(np.percentile(totals, 90)),
        "p10_total": float(np.percentile(totals, 10)),
        "p50_maxdd": float(np.percentile(maxdds, 50)),
        "p90_maxdd": float(np.percentile(maxdds, 90)),
        "mean_total": float(totals.mean()),
        "std_total": float(totals.std()),
    }


# ── entrypoint ──────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", default="parquet", choices=["supabase", "parquet"])
    ap.add_argument("--data", default="/Volumes/CometCloudAI/cometcloud-local/_cache/asset_mcap_full/asset_mcap.parquet",
                    help="parquet path with columns coin_id,source,d,price,mcap")
    ap.add_argument("--segments", default="S1,S2,S1H,S2H",
                    help="comma list of S1/S2/S1H/S2H segments to evaluate")
    ap.add_argument("--costs", default="10,30,50", help="comma bps list")
    ap.add_argument("--n-trials", type=int, default=SHUFFLE_TRIALS,
                    help="shuffle permutations per (segment, n, bps) — M-037 forces 500")
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
    out = {"primary": [], "neighborhood": [], "shuffle_meta": {
        "trials_per_run": args.n_trials,
        "block_size_weeks": SHUFFLE_BLOCK_WEEKS,
        "rng_seed": RNG_SEED,
    }}
    for seg in segs:
        for bps in costs:
            for (n, l) in NEIGHBORHOOD:
                arm = run_one(panel, n=n, l=l, bps=bps, segment=seg)
                ctrl_a = control_a_constant_exposure(panel, n=n, l=l, bps=bps,
                                                       segment=seg)
                ctrl_b = control_b_shuffle(panel, n=n, l=l, bps=bps, segment=seg,
                                              n_trials=args.n_trials)
                bucket = "primary" if (n, l) == PRIMARY else "neighborhood"
                out[bucket].append({"segment": seg, "n": n, "l": l, "bps": bps,
                                     "arm": arm, "ctrl_a": ctrl_a, "ctrl_b": ctrl_b})
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=2, default=str))
    print(f"→ {args.out}")


if __name__ == "__main__":
    main()
