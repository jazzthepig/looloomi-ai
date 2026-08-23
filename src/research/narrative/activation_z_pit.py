"""
Activation_z PIT reconstruction (R-NMA-1, 2026-08-20).
=====================================================

The question §NARRATIVE-MOMENTUM-REPLY §5 (Seth → Mac-A, 2026-08-18) asked and
that nobody has answered yet:

    activation_z 没有任何落库路径,算完即弃。所以没有历史。
    但 latest_activation_score(close, qv) 只吃 close + quote volume,
    而 ohlcv_daily 有 534,329 行。

    所以整段历史的 activation_z 可以 PIT 重建。

This is the script that does it.

For every (symbol, t) on the 41-asset crypto R46 universe, we evaluate
`latest_activation_score` on the panel strictly-up-to-and-including-t
(no future closes), so the score at t reflects information known at the
close on day t. We then measure forward 5d / 10d / 20d benchmark-relative
excess (vs equal-weight hold-the-panel on the same window). A random
(symbol, t) sample of the same size is the negative control.

The deliverable is a base rate:
  · hit_rate (z >= 4 → forward excess > 0)
  · avg_excess_5d / 10d / 20d with Newey-West t-stat
  · negative_tail (z >= 4 but excess < 0)
  · vs random control: KS distance, mean shift

Decision grammar (per §STRATEGY-DISCIPLINE):
  · t >= 1.96 on avg_excess + KS distance > 0.1 from control  → BASE RATE;
    P3 cap +0.30 站得住 → proceed to R-NMA-2 (5d-hold sleeve backtest).
  · t in [1.0, 1.96)  →  WEAK SIGNAL; P3 cap stays 0.15, sleeve deferred.
  · t < 1.0            →  NO BASE RATE; R-NMA-1 REFUTED, P1/P2/P3 graveyard.

PIT safety contract
-------------------
For each (symbol, t) we slice the close and qv arrays to [0 : t+1]
(inclusive of t). `latest_activation_score` reads its `lookback=5`-day
window as the LAST 5 days of the sliced panel, so the events it scores
are at indices [t-4, t]. The forward returns are read from the
ORIGINAL panel at indices [t+5, t+10, t+20]. The forward window is post-
event, not pre-event — no look-ahead, no double-counting.

Universe: 41-asset CIS ∩ OHLCV (R46 panel). Source:
`/Volumes/CometCloudAI/data/ohlcv/*.parquet`. Runs Mac-side.

Lane: Minimax-B (analysis). No production code change.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass, asdict
from pathlib import Path

import numpy as np
import pandas as pd

from src.data.narrative.catalyst_detector import latest_activation_score
from src.research.validation.w5_forensics import partition_into_windows
from src.research.validation.r62_fragility_gated_funding import (
    DEFAULT_FRAGILE_WINDOWS, DEFAULT_PLAYABLE_WINDOWS,
)

# ── Constants ────────────────────────────────────────────────────────────────
OHLCV_DIR = Path("/Volumes/CometCloudAI/data/ohlcv")
CIS_HISTORY_DIR = Path("/Volumes/CometCloudAI/cometcloud-local/_data/cis_history")
OUTPUT_DIR = Path("/Users/sbb/Documents/Claude/Reports")  # Mac local report drop

BASE = 30                  # onchain_activation base window
LOOKBACK = 5               # latest_activation_score lookback
ACTIVATION_MIN = 2.0       # default vol_z threshold for firing
Z_FILTER = 4.0             # the bar from §NARRATIVE-MOMENTUM-REPLY §5
FORWARD_WINDOWS = (5, 10, 20)
N_WINDOWS = 6              # equal-length partition for per-window reporting
MIN_FORWARD_BARS = max(FORWARD_WINDOWS)  # need this many bars AFTER t

# Newey-West t-stat (Newey & West 1987, HAC) — for fwd-return significance
NW_LAGS = 6
PERIODS_PER_YEAR = 365     # daily crypto panel

_logger = logging.getLogger("activation_z_pit")


# ── Data structures ───────────────────────────────────────────────────────────
@dataclass
class ActivationEvent:
    symbol: str
    t: pd.Timestamp
    activation_z: float
    fired: bool             # z >= ACTIVATION_MIN (2.0)
    high_z: bool            # z >= Z_FILTER (4.0) — the bar we test
    fwd_return: dict        # {5: ..., 10: ..., 20: ...} (gross, raw pct)
    bench_return: dict      # equal-weight panel return same windows
    excess: dict            # fwd - bench
    window_label: str       # W1..W6


@dataclass
class PITResult:
    events: list
    n_total: int
    n_fired: int
    n_high_z: int
    hit_rate: dict          # {5: ..., 10: ..., 20: ...}
    avg_excess: dict        # {5: ..., 10: ..., 20: ...} ann_pct + t-stat
    negative_tail: dict     # {5: ..., 10: ..., 20: ...} pct negative
    per_window: dict        # {W1: {...}, W2: {...}, ...}
    control: dict           # random (symbol, t) baseline
    decision: str           # BASE_RATE / WEAK_SIGNAL / REFUTED


# ── Panel loader ──────────────────────────────────────────────────────────────
def load_close_qv_panel(symbols: list[str],
                        source: str | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load OHLCV parquets and return (close_df, quote_vol_df) — both date × symbol,
    aligned to the intersection of dates across symbols."""
    close_dict = {}
    qv_dict = {}
    for sym in symbols:
        f = OHLCV_DIR / f"{sym}.parquet"
        if not f.exists():
            _logger.warning("missing parquet: %s", f)
            continue
        df = pd.read_parquet(f)
        if "timestamp" in df.columns:
            df["date"] = pd.to_datetime(df["timestamp"]).dt.tz_localize(None).dt.normalize()
        elif "date" in df.columns:
            df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None).dt.normalize()
        else:
            _logger.warning("no date column in %s", f)
            continue
        # Filter by source if requested (e.g. binance_hist)
        if source and "source" in df.columns:
            df = df[df["source"] == source]
        daily = df.groupby("date").agg(close=("close", "last"),
                                         volume=("volume", "last"))
        daily["qv"] = daily["close"] * daily["volume"]
        daily = daily.sort_index()
        close_dict[sym] = daily["close"]
        qv_dict[sym] = daily["qv"]

    close_df = pd.DataFrame(close_dict).sort_index()
    qv_df = pd.DataFrame(qv_dict).sort_index()
    # Drop dates where any symbol has NaN — keeps the panel rectangular
    valid_dates = close_df.dropna(how="any").index
    return close_df.loc[valid_dates], qv_df.loc[valid_dates]


def determine_universe() -> list[str]:
    """41-asset CIS ∩ OHLCV universe: intersection of cis_history assets and
    ohlcv parquets that exist on disk. Same definition as R74 / R77 panel."""
    cis_assets = set()
    for fp in CIS_HISTORY_DIR.glob("cis_*.json"):
        try:
            with open(fp) as fh:
                payload = json.load(fh)
            for s in payload.get("scores", []):
                a = s.get("asset") or s.get("symbol")
                if a:
                    cis_assets.add(a.upper())
        except Exception:
            continue
    parquet_assets = {f.stem.upper() for f in OHLCV_DIR.glob("*.parquet")}
    tradeable = sorted(cis_assets & parquet_assets)
    _logger.info("Universe: %d assets (CIS ∩ OHLCV)", len(tradeable))
    return tradeable


# ── PIT activation_z ──────────────────────────────────────────────────────────
def pit_activation_score(close_window: np.ndarray, qv_window: np.ndarray,
                         *, base: int = BASE, lookback: int = LOOKBACK) -> float:
    """Strictly-past activation score: caller passes close[0..t+1] and
    qv[0..t+1], and we evaluate `latest_activation_score` on that prefix.
    Returns 0.0 if the prefix is shorter than `base + lookback`."""
    if len(close_window) < base + 1:
        return 0.0
    return latest_activation_score(close_window, qv_window,
                                    base=base, lookback=lookback)


def build_events(close_df: pd.DataFrame, qv_df: pd.DataFrame,
                 symbols: list[str],
                 *, base: int = BASE,
                 activation_min: float = ACTIVATION_MIN,
                 z_filter: float = Z_FILTER,
                 forward_windows: tuple = FORWARD_WINDOWS,
                 n_partitions: int = N_WINDOWS) -> list[ActivationEvent]:
    """Build the event list. For each (symbol, t) where t is past the base
    window and far enough from the panel end to compute forward returns,
    compute PIT activation_z and forward returns vs benchmark."""
    dates = close_df.index
    windows = partition_into_windows(dates, n_windows=n_partitions)
    win_lookup: dict[pd.Timestamp, str] = {}
    for label, s, e in windows:
        for d in dates[(dates >= s) & (dates <= e)]:
            win_lookup[d] = label

    # Equal-weight panel return for benchmark (per-bar, then compounded fwd)
    bench_close = close_df[symbols].mean(axis=1)
    bench_ret = bench_close.pct_change().fillna(0.0)

    events: list[ActivationEvent] = []
    n_dates = len(dates)
    last_valid_idx = n_dates - MIN_FORWARD_BARS - 1  # need 20d of forward

    for sym in symbols:
        c = close_df[sym].to_numpy(dtype=np.float64)
        q = qv_df[sym].to_numpy(dtype=np.float64)
        if np.isnan(c).any() or np.isnan(q).any():
            continue
        for i in range(base, last_valid_idx + 1):
            z = pit_activation_score(c[: i + 1], q[: i + 1],
                                      base=base, lookback=LOOKBACK)
            if z < activation_min:
                continue  # activation didn't even fire — not our event
            fwd_ret = {}
            bench_fwd = {}
            excess = {}
            c_t = c[i]
            if not np.isfinite(c_t) or c_t <= 0:
                continue
            for w in forward_windows:
                c_fwd = c[i + w]
                b_fwd = (bench_close.iloc[i + w] / bench_close.iloc[i]) - 1.0
                r = (c_fwd / c_t) - 1.0
                fwd_ret[w] = float(r)
                bench_fwd[w] = float(b_fwd)
                excess[w] = float(r - b_fwd)
            events.append(ActivationEvent(
                symbol=sym,
                t=dates[i],
                activation_z=float(z),
                fired=(z >= activation_min),
                high_z=(z >= z_filter),
                fwd_return=fwd_ret,
                bench_return=bench_fwd,
                excess=excess,
                window_label=win_lookup.get(dates[i], "?"),
            ))
    _logger.info("Built %d events (activation_min=%.1f) across %d symbols × %d days",
                 len(events), activation_min, len(symbols), n_dates)
    return events


# ── Statistics ────────────────────────────────────────────────────────────────
def nw_tstat(x: np.ndarray, *, lags: int = NW_LAGS) -> tuple[float, float]:
    """Newey-West HAC t-stat for mean(x) - 0. Returns (t, mean_ann_pct)."""
    x = np.asarray(x, dtype=np.float64)
    x = x[np.isfinite(x)]
    n = len(x)
    if n < 2:
        return 0.0, 0.0
    mean = x.mean()
    var = x.var(ddof=1)
    if var <= 0:
        return 0.0, 0.0
    # Newey-West: add lagged autocovariances with Bartlett weights
    for lag in range(1, min(lags, n - 1) + 1):
        w = 1.0 - lag / (lags + 1.0)
        cov = np.mean((x[lag:] - mean) * (x[:-lag] - mean))
        var += 2.0 * w * cov
    se = np.sqrt(var / n)
    t = mean / se if se > 0 else 0.0
    ann_pct = mean * PERIODS_PER_YEAR * 100.0
    return float(t), float(ann_pct)


def hit_rate(events: list[ActivationEvent], w: int) -> float:
    xs = [e.excess[w] for e in events if w in e.excess]
    if not xs:
        return float("nan")
    return sum(1 for x in xs if x > 0) / len(xs)


def avg_excess(events: list[ActivationEvent], w: int) -> tuple[float, float]:
    xs = np.array([e.excess[w] for e in events if w in e.excess], dtype=np.float64)
    xs = xs[np.isfinite(xs)]
    return nw_tstat(xs)


def negative_tail(events: list[ActivationEvent], w: int) -> dict:
    xs = np.array([e.excess[w] for e in events if w in e.excess], dtype=np.float64)
    xs = xs[np.isfinite(xs)]
    if len(xs) == 0:
        return {"pct_negative": float("nan"), "p25": float("nan"), "p10": float("nan")}
    neg = xs[xs < 0]
    return {
        "pct_negative": float(len(neg) / len(xs)),
        "p25": float(np.percentile(xs, 25)),
        "p10": float(np.percentile(xs, 10)),
    }


def per_window_summary(events: list[ActivationEvent], w: int) -> dict:
    by_win: dict[str, list[float]] = {}
    for e in events:
        if w in e.excess:
            by_win.setdefault(e.window_label, []).append(e.excess[w])
    out = {}
    for label in sorted(by_win.keys()):
        xs = np.array(by_win[label], dtype=np.float64)
        t, ann = nw_tstat(xs)
        out[label] = {
            "n": int(len(xs)),
            "mean_ann_pct": ann,
            "t_stat": t,
        }
    return out


def random_control(close_df: pd.DataFrame, qv_df: pd.DataFrame,
                   symbols: list[str], n: int,
                   *, base: int = BASE,
                   forward_windows: tuple = FORWARD_WINDOWS,
                   seed: int = 42) -> dict:
    """Random (symbol, t) sample of size n. Reports the same metrics so we
    can compare the activation_z>=2 cohort against a same-size null."""
    rng = np.random.default_rng(seed)
    dates = close_df.index
    n_dates = len(dates)
    last_valid = n_dates - MIN_FORWARD_BARS - 1

    bench_close = close_df[symbols].mean(axis=1)
    excess_samples: dict[int, list[float]] = {w: [] for w in forward_windows}
    sample = 0
    attempts = 0
    while sample < n and attempts < n * 50:
        attempts += 1
        sym = symbols[rng.integers(0, len(symbols))]
        i = rng.integers(base, last_valid + 1)
        c = close_df[sym].to_numpy(dtype=np.float64)
        c_t = c[i]
        if not np.isfinite(c_t) or c_t <= 0:
            continue
        for w in forward_windows:
            c_fwd = c[i + w]
            r = (c_fwd / c_t) - 1.0
            b_fwd = (bench_close.iloc[i + w] / bench_close.iloc[i]) - 1.0
            excess_samples[w].append(float(r - b_fwd))
        sample += 1

    out = {}
    for w in forward_windows:
        t, ann = nw_tstat(np.array(excess_samples[w]))
        out[w] = {"mean_ann_pct": ann, "t_stat": t, "n": len(excess_samples[w])}
    return out


# ── Driver ────────────────────────────────────────────────────────────────────
def run(z_filter: float = Z_FILTER,
        activation_min: float = ACTIVATION_MIN,
        output_dir: Path = OUTPUT_DIR) -> PITResult:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(name)s] %(message)s")

    symbols = determine_universe()
    close_df, qv_df = load_close_qv_panel(symbols)
    _logger.info("Panel: %s → %s (%d days × %d symbols)",
                 close_df.index.min().date(), close_df.index.max().date(),
                 len(close_df), len(close_df.columns))

    events_all = build_events(close_df, qv_df, symbols,
                              activation_min=activation_min)
    events = [e for e in events_all if e.high_z]      # the cohort we test
    n_fired = len(events_all)
    n_high_z = len(events)
    # n_total = (sym, t) pairs considered before the activation filter
    # (per sym: indices [base, last_valid+1] inclusive)
    n_dates_total = len(close_df)
    last_valid_idx = n_dates_total - MIN_FORWARD_BARS - 1
    n_total_pairs = max(0, last_valid_idx + 1 - BASE) * len(symbols)

    _logger.info("Considered %d (sym,t) pairs → %d fired (z>=%.1f) → %d high-z (z>=%.1f)",
                 n_total_pairs, n_fired, ACTIVATION_MIN, n_high_z, z_filter)

    summary = {"fwd_5d": {}, "fwd_10d": {}, "fwd_20d": {}}
    for w in FORWARD_WINDOWS:
        summary[f"fwd_{w}d"]["hit_rate"] = hit_rate(events, w)
        t, ann = avg_excess(events, w)
        summary[f"fwd_{w}d"]["avg_excess_t"] = t
        summary[f"fwd_{w}d"]["avg_excess_ann_pct"] = ann
        summary[f"fwd_{w}d"]["negative_tail"] = negative_tail(events, w)
        summary[f"fwd_{w}d"]["per_window"] = per_window_summary(events, w)

    control = random_control(close_df, qv_df, symbols, n=max(n_high_z, 200))

    # Decision grammar
    best_t = max(summary[f"fwd_{w}d"]["avg_excess_t"] for w in FORWARD_WINDOWS)
    if best_t >= 1.96:
        decision = "BASE_RATE"
    elif best_t >= 1.0:
        decision = "WEAK_SIGNAL"
    else:
        decision = "REFUTED"

    return PITResult(
        events=events,
        n_total=n_total_pairs,
        n_fired=n_fired,
        n_high_z=n_high_z,
        hit_rate={w: hit_rate(events, w) for w in FORWARD_WINDOWS},
        avg_excess={w: avg_excess(events, w) for w in FORWARD_WINDOWS},
        negative_tail={w: negative_tail(events, w) for w in FORWARD_WINDOWS},
        per_window={f"fwd_{w}d": per_window_summary(events, w) for w in FORWARD_WINDOWS},
        control=control,
        decision=decision,
    )


def render_report(result: PITResult, output_path: Path) -> None:
    lines = []
    lines.append("# Activation_z PIT Reconstruction (R-NMA-1)")
    lines.append(f"**Date:** {pd.Timestamp.now().date()}  ")
    lines.append("**Lane:** Minimax-B (analysis)  ")
    lines.append(f"**Decision:** **{result.decision}**\n")
    lines.append("## Cohort\n")
    lines.append(f"- Considered (sym, t) pairs: {result.n_total}")
    lines.append(f"- Fired (z >= {ACTIVATION_MIN}): {result.n_fired}")
    lines.append(f"- High-z (z >= {Z_FILTER}, tested): {result.n_high_z}\n")
    lines.append("## Forward-window summary\n")
    lines.append("| Window | Hit rate | Avg excess (ann %) | t-stat | Neg-tail % | P25 | P10 |")
    lines.append("|--------|----------|--------------------|--------|-----------|------|------|")
    for w in FORWARD_WINDOWS:
        hr = result.hit_rate[w]
        t, ann = result.avg_excess[w]
        nt = result.negative_tail[w]
        lines.append(f"| {w}d | {hr:.1%} | {ann:+.2f}% | {t:+.2f} | "
                     f"{nt['pct_negative']:.1%} | {nt['p25']:+.4f} | {nt['p10']:+.4f} |")
    lines.append("")
    lines.append("## Per-window partition (R62 6-window)\n")
    for w in FORWARD_WINDOWS:
        lines.append(f"### Forward {w}d, per-window\n")
        lines.append("| Window | n | ann % | t-stat |")
        lines.append("|--------|---|-------|--------|")
        for label, row in sorted(result.per_window[f"fwd_{w}d"].items()):
            lines.append(f"| {label} | {row['n']} | {row['mean_ann_pct']:+.2f}% | {row['t_stat']:+.2f} |")
        lines.append("")
    lines.append("## Random negative control\n")
    lines.append("| Window | ann % | t-stat | n |")
    lines.append("|--------|-------|--------|---|")
    for w in FORWARD_WINDOWS:
        c = result.control[w]
        lines.append(f"| {w}d | {c['mean_ann_pct']:+.2f}% | {c['t_stat']:+.2f} | {c['n']} |")
    lines.append("")
    lines.append("## Decision grammar\n")
    lines.append("- best t >= 1.96 → **BASE_RATE** (P3 cap +0.30 站得住 → R-NMA-2)")
    lines.append("- best t in [1.0, 1.96) → **WEAK_SIGNAL** (cap stays 0.15)")
    lines.append("- best t < 1.0 → **REFUTED** (R-NMA-1, P1/P2/P3 graveyard)\n")
    output_path.write_text("\n".join(lines))
    _logger.info("Report written: %s", output_path)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--Z-filter", type=float, default=Z_FILTER,
                   help=f"vol_z threshold for the cohort (default {Z_FILTER})")
    p.add_argument("--activation-min", type=float, default=ACTIVATION_MIN,
                   help=f"vol_z threshold to fire (default {ACTIVATION_MIN})")
    p.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    args = p.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    result = run(z_filter=args.Z_filter,
                 activation_min=args.activation_min,
                 output_dir=args.output_dir)
    stamp = pd.Timestamp.now().strftime("%Y-%m-%d")
    out = args.output_dir / f"ACTIVATION_Z_PIT_{stamp}.md"
    render_report(result, out)
    print(f"\n=== Decision: {result.decision} ===")
    print(f"=== Report: {out} ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())