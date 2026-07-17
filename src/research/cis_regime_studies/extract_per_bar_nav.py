"""
Extract per-bar NAV from cached multi_window_baseline raw position data
(Minimax-B, 2026-07-17)

Source: reports/multi_window_baseline_<src>_<cis_tag>/<date>/raw/w*.json
Each window has per_instrument[i].positions[] with ts_opened, ts_closed, realized_pnl, realized_return.

For each position, realized_pnl is realized AT ts_closed.
We construct per-bar NAV by aggregating pnl events across all instruments at each
4h bar boundary (the bar in which the position closed receives the realized pnl).

Output: reports/<out>/per_bar_nav.parquet  (timestamped index, NAV column)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from datetime import datetime, timezone
import numpy as np
import pandas as pd


# 4h bar boundaries: 00:00, 04:00, 08:00, 12:00, 16:00, 20:00 UTC
BAR_HOURS = [0, 4, 8, 12, 16, 20]


def ts_to_bar_end(ts_ns: int) -> pd.Timestamp:
    """Convert nanosecond timestamp to its 4h bar-end UTC timestamp."""
    ts = pd.Timestamp(ts_ns, unit='ns', tz='UTC')
    bar_hour = (ts.hour // 4) * 4
    bar_end = ts.floor('4h') + pd.Timedelta(hours=4)  # end of 4h bar
    return bar_end.tz_localize(None) if bar_end.tz is not None else bar_end


def extract_window(raw_path: Path, starting_nav: float = 10_000.0) -> pd.DataFrame:
    """Read a single raw window JSON, return DataFrame indexed by 4h-bar-end with realized_pnl sum.

    IMPORTANT: only count positions whose ts_closed falls within THIS window's OOS range.
    Other windows will report the same position in their OOS too (overlapping IS),
    so to avoid double-counting we filter strictly to OOS.
    """
    d = json.loads(raw_path.read_text())
    oos_start = pd.Timestamp(d['window_dates']['oos_start']).tz_localize(None)
    oos_end = pd.Timestamp(d['window_dates']['oos_end']).tz_localize(None)

    events = []  # list of (bar_end_ts, realized_pnl)
    for r in d.get('per_instrument', []):
        for p in r.get('positions', []):
            pnl = float(p.get('realized_pnl') or 0)
            ts = int(p.get('ts_closed') or 0)
            if ts == 0:
                continue
            bar_end = ts_to_bar_end(ts)
            # STRICT OOS filter — only count positions closed in this window's OOS
            if bar_end < oos_start or bar_end > oos_end:
                continue
            events.append((bar_end, pnl))
    if not events:
        return pd.DataFrame(columns=['realized_pnl']).rename_axis('date')

    df = pd.DataFrame(events, columns=['date', 'realized_pnl'])
    df = df.groupby('date', as_index=True)['realized_pnl'].sum()
    df = df.sort_index()
    return df.to_frame('realized_pnl')


def build_full_nav(raw_dir: Path, starting_nav: float = 10_000.0) -> pd.Series:
    """Aggregate across all windows into a single NAV time series.

    CRITICAL: positions are reported in MULTIPLE overlapping windows (each window
    independently runs the strategy from is_start to oos_end, overlapping 240d with
    the next). A position that closes at time T may appear in windows N, N-1, N-2
    (anywhere it fits). Summing pnl_usd across windows double-counts positions.

    Strategy: dedup by (instrument, ts_closed) — a position can only be closed once,
    so we keep ONE record per unique close event. We use the FIRST occurrence
    (i.e. the latest window that includes the close, which is window N when the
    position closes during N's OOS — that's the window's own attribution).

    Then we walk through all unique close events in chronological order,
    accumulating pnl into NAV.
    """
    # First pass: collect all unique (instrument, ts_closed) -> realized_pnl
    seen = set()  # (instrument, ts_closed_ns)
    unique_events: list[tuple[pd.Timestamp, float]] = []  # (bar_end, pnl)

    # Read all windows and gather all position close events
    all_position_events = []
    for raw_path in sorted(raw_dir.glob('w*.json')):
        d = json.loads(raw_path.read_text())
        if 'error' in d:
            continue
        for r in d.get('per_instrument', []):
            inst = r.get('instrument', 'unknown')
            for p in r.get('positions', []):
                pnl = float(p.get('realized_pnl') or 0)
                ts = int(p.get('ts_closed') or 0)
                if ts == 0:
                    continue
                all_position_events.append({'instrument': inst, 'ts_closed': ts, 'pnl': pnl})

    # Dedup by (instrument, ts_closed) — same trade reported in multiple windows
    for ev in all_position_events:
        key = (ev['instrument'], ev['ts_closed'])
        if key in seen:
            continue
        seen.add(key)
        bar_end = ts_to_bar_end(ev['ts_closed'])
        unique_events.append((bar_end, ev['pnl']))

    print(f'  total position records (with duplicates): {len(all_position_events)}')
    print(f'  unique (instrument, ts_closed) events:   {len(unique_events)}')

    # Sort by bar_end and accumulate NAV
    unique_events.sort(key=lambda x: x[0])
    nav = starting_nav
    records = []
    for bar_end, pnl in unique_events:
        nav += pnl
        records.append({'date': bar_end, 'nav': nav})

    if not records:
        return pd.Series(dtype=float, name='nav')
    df = pd.DataFrame(records).set_index('date')['nav']
    df = df[~df.index.duplicated(keep='last')].sort_index()
    return df


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--raw-dir', type=Path,
                    default=Path('reports/multi_window_baseline_spot_cis_off/2026-07-16/raw'))
    ap.add_argument('--out', type=Path,
                    default=Path('reports/multi_window_baseline_spot_cis_off/2026-07-16/per_bar_nav.parquet'))
    ap.add_argument('--starting-nav', type=float, default=10_000.0)
    args = ap.parse_args(argv)

    if not args.raw_dir.exists():
        print(f'ERROR: {args.raw_dir} not found')
        return 1

    print(f'Reading from: {args.raw_dir}')
    nav = build_full_nav(args.raw_dir, starting_nav=args.starting_nav)
    print(f'Per-bar NAV: {len(nav)} events')
    if len(nav) > 0:
        print(f'  First event: {nav.index[0]}  NAV={nav.iloc[0]:.2f}')
        print(f'  Last event:  {nav.index[-1]}  NAV={nav.iloc[-1]:.2f}')
        print(f'  Net P&L: {nav.iloc[-1] - nav.iloc[0]:+.2f}')

    # Forward-fill to a complete 4h bar grid for downstream analysis
    if len(nav) > 0:
        full_grid = pd.date_range(nav.index[0], nav.index[-1], freq='4h')
        nav_ffill = nav.reindex(full_grid).ffill()
        # also write the event-only series
        args.out.parent.mkdir(parents=True, exist_ok=True)
        nav.to_frame('nav').to_parquet(args.out)
        nav_ffill.to_frame('nav').to_parquet(args.out.with_name('per_bar_nav_ffill.parquet'))
        print(f'Wrote: {args.out}')
        print(f'Wrote: {args.out.with_name("per_bar_nav_ffill.parquet")}  (forward-filled, {len(nav_ffill)} bars)')

        # Also resample to daily end for convenience
        nav_daily = nav_ffill.resample('D').last().ffill()
        nav_daily.to_frame('nav').to_parquet(args.out.with_name('per_day_nav.parquet'))
        print(f'Wrote: {args.out.with_name("per_day_nav.parquet")}  (daily, {len(nav_daily)} days)')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())