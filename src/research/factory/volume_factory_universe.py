"""
Volume Factory — K=24 universe follow-up to R29 (Seth, 2026-07-18).
====================================================================
R29 marked the volume-axis investigation INCONCLUSIVE on the K=5 A-S1 substrate. R29's
honest verdict called for the next step: "populate the substrate with volume + taker-buy
columns for the 24-name universe (one Binance fetch per name, 1000-bar pagination, ~1
hour wall-clock) and re-run."

This script does exactly that:
  1. Fetch the 19 ADDITIONAL symbols (the 5 A-S1 majors are already on disk) from
     Binance fapi klines with the same columns + same window (2025-01-01 → 2026-07-17).
     Saves to `/{SYMBOL}_1d_ohlcv.csv` matching the A-S1 format exactly so the existing
     `volume_factory.load_a_s1_panel(symbols=[...])` reads them with no change.
  2. Build a K=24 panel.
  3. Run the SAME three candidates (volume_price_trend / taker_buy_imbalance /
     volume_weighted_momentum) through the SAME honest gate (_xs_weights / _bt /
     _walkforward / evaluate_universe).
  4. Report annSR + walk-forward folds + DSR survivors.

Honest scope: this is THE R29 resolver — same hypothesis, ~5× more cross-section,
~21%→100% statistical power. If R29 still doesn't survive here, it gets REFUTED.

CLI usage (run from repo root):
    python3 -m src.research.factory.volume_factory_universe --fetch-only
    python3 -m src.research.factory.volume_factory_universe --run-only
    python3 -m src.research.factory.volume_factory_universe            # do both
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import sys
import time
from pathlib import Path

import httpx
import numpy as np

# Reuse the existing volume_factory infra — same mechanism, no re-implementation.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.research.factory.volume_factory import (   # noqa: E402
    AS1_DIR, load_a_s1_panel, signal_library, _bt, A_S1_SYMBOLS,
)
from src.research.factory.signal_factory import _walkforward, FEE as _FACTORY_FEE   # noqa: E402
FEE = _FACTORY_FEE
from src.research.validation.deflated_sharpe import evaluate_universe  # noqa: E402
from src.research.strategies.causal_positioning import DEFAULT_UNIVERSE   # noqa: E402

# Mapping matches the A-S1 CSV schema documented in MANIFEST.md:
#   date, open, high, low, close, volume_base, volume_quote, trades,
#   taker_buy_base, taker_buy_quote, close_time_iso
# Binance fapi kline array: [open_time, o, h, l, c, volume, close_time, quote_volume,
#   trades, taker_buy_base, taker_buy_quote, _]
_CSV_COLUMNS = ["date", "open", "high", "low", "close",
                "volume_base", "volume_quote", "trades",
                "taker_buy_base", "taker_buy_quote", "close_time_iso"]


def fetch_symbol_ohlcv(symbol: str, start_iso: str = "2025-01-01",
                        end_iso: str = "2026-07-17") -> list[dict]:
    """Fetch one symbol's daily klines matching the A-S1 CSV schema. Saves next to A-S1 files."""
    out_p = AS1_DIR / f"{symbol}_1d_ohlcv.csv"
    out_p.parent.mkdir(parents=True, exist_ok=True)
    start_ms = int(dt.datetime.fromisoformat(start_iso).timestamp() * 1000)
    end_ms = int(dt.datetime.fromisoformat(end_iso).timestamp() * 1000)
    sym = f"{symbol}USDT"
    rows: list[dict] = []
    cur = start_ms
    client = httpx.Client(timeout=25, headers={"User-Agent": "research"})
    try:
        while cur < end_ms:
            j = client.get("https://fapi.binance.com/fapi/v1/klines",
                           params={"symbol": sym, "interval": "1d", "startTime": cur,
                                   "limit": 1000}).json()
            if not j:
                break
            for k in j:
                rows.append({
                    "date":            dt.datetime.fromtimestamp(int(k[0]) / 1000, dt.timezone.utc).strftime("%Y-%m-%d"),
                    "open":            k[1], "high": k[2], "low": k[3], "close": k[4],
                    "volume_base":     k[5], "volume_quote": k[7],
                    "trades":          k[8],
                    "taker_buy_base":  k[9], "taker_buy_quote": k[10],
                    "close_time_iso":  dt.datetime.fromtimestamp(int(k[6]) / 1000, dt.timezone.utc).isoformat(),
                })
            cur = int(j[-1][0]) + 86_400_000
            if len(j) < 1000 or cur > end_ms:
                break
            time.sleep(0.05)   # be a good citizen — Binance public endpoint
    finally:
        client.close()
    # write atomically (write-temp + rename) so a partial fetch doesn't corrupt prior CSVs
    tmp = out_p.with_suffix(".csv.tmp")
    with tmp.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=_CSV_COLUMNS)
        w.writeheader()
        w.writerows(rows)
    tmp.rename(out_p)
    print(f"  …{symbol}: {len(rows)} rows → {out_p}")
    return rows


def fetch_symbol_ohlcv(symbol: str, start_iso: str = "2025-01-01",
                        end_iso: str = "2026-07-17") -> list[dict]:
    """Fetch one symbol's daily klines matching the A-S1 CSV schema. Saves next to A-S1 files."""
    out_p = AS1_DIR / f"{symbol}_1d_ohlcv.csv"
    out_p.parent.mkdir(parents=True, exist_ok=True)
    start_ms = int(dt.datetime.fromisoformat(start_iso).timestamp() * 1000)
    end_ms = int(dt.datetime.fromisoformat(end_iso).timestamp() * 1000)
    sym = f"{symbol}USDT"
    rows: list[dict] = []
    cur = start_ms
    client = httpx.Client(timeout=25, headers={"User-Agent": "research"})
    try:
        while cur < end_ms:
            j = client.get("https://fapi.binance.com/fapi/v1/klines",
                           params={"symbol": sym, "interval": "1d", "startTime": cur,
                                   "limit": 1000}).json()
            if not j:
                break
            for k in j:
                rows.append({
                    "date":            dt.datetime.fromtimestamp(int(k[0]) / 1000, dt.timezone.utc).strftime("%Y-%m-%d"),
                    "open":            k[1], "high": k[2], "low": k[3], "close": k[4],
                    "volume_base":     k[5], "volume_quote": k[7],
                    "trades":          k[8],
                    "taker_buy_base":  k[9], "taker_buy_quote": k[10],
                    "close_time_iso":  dt.datetime.fromtimestamp(int(k[6]) / 1000, dt.timezone.utc).isoformat(),
                })
            cur = int(j[-1][0]) + 86_400_000
            if len(j) < 1000 or cur > end_ms:
                break
            time.sleep(0.05)   # be a good citizen — Binance public endpoint
    finally:
        client.close()
    # write atomically (write-temp + rename) so a partial fetch doesn't corrupt prior CSVs
    tmp = out_p.with_suffix(".csv.tmp")
    with tmp.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=_CSV_COLUMNS)
        w.writeheader()
        w.writerows(rows)
    tmp.rename(out_p)
    print(f"  …{symbol}: {len(rows)} rows → {out_p}")
    return rows


def fetch_universe(symbols: list[str] = None,
                    start_iso: str = "2025-01-01", end_iso: str = "2026-07-17") -> dict:
    """Fetch every symbol in `symbols` (default: all 24). Skips ones already on disk."""
    syms = symbols or DEFAULT_UNIVERSE
    skipped, fetched = [], []
    for s in syms:
        if (AS1_DIR / f"{s}_1d_ohlcv.csv").exists():
            skipped.append(s); continue
        try:
            fetch_symbol_ohlcv(s, start_iso, end_iso)
            fetched.append(s)
        except Exception as e:
            print(f"  !!{s}: fetch failed — {e}")
    print(f"\nFetched: {len(fetched)} · Skipped (already on disk): {len(skipped)}")
    return {"fetched": fetched, "skipped": skipped}


def run_volume_universe(symbols: list[str] = None) -> dict:
    """The honest R29 resolver — same 3 candidates, K=24 panel."""
    syms = symbols or DEFAULT_UNIVERSE
    days, close, vbase, vquote, taker_buy_quote = load_a_s1_panel(symbols=syms)
    ret = np.zeros_like(close); ret[1:] = np.nan_to_num((close[1:] - close[:-1]) / close[:-1])
    lib = signal_library(close, vbase, vquote, taker_buy_quote)
    fsum = np.zeros_like(close)               # T2 funding carry = 0 on volume-only
    pnl = {name: _bt(W, ret, fsum) for name, W in lib.items()}
    warm = 30
    series = {name: p[warm:] for name, p in pnl.items()}
    wf = _walkforward(series)
    evals = evaluate_universe({n: list(s) for n, s in series.items()}, dsr_threshold=0.95)
    ann = {n: (float(s.mean() / s.std() * np.sqrt(365)) if s.std() > 0 else 0.0)
           for n, s in series.items()}
    survivors = [e.name for e in evals if e.survives]
    return {
        "universe_size": len(syms), "days": len(days),
        "n_signals": len(lib),
        "ann_sharpe": {n: round(a, 2) for n, a in ann.items()},
        "wf": wf, "survivors": survivors, "evals": evals,
        "note": "K=24 follow-up to R29 (K=5 inconclusive). Same hypotheses; ~5× cross-section.",
    }


def _print_run_result(res: dict):
    print(f"\n=== VOLUME FACTORY — K={res['universe_size']} · {res['days']} days "
          f"(follow-up to R29) ===\n")
    print(f"{'signal':24} {'annSR':>6} {'WF':>5} {'pos_folds':>9} {'robust':>7}")
    for n in res["ann_sharpe"]:
        w = res["wf"][n]
        a = res["ann_sharpe"][n]
        print(f"{n:24} {a:>6.2f} {w['pos_folds']}/5  {w['mean_fold_sr']:>9.2f} "
              f"{'YES' if w['robust'] else 'no':>7}")
    print(f"\nDSR survivors (>=0.95): {len(res['survivors'])} — "
          f"{res['survivors'] if res['survivors'] else 'NONE'}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--fetch-only", action="store_true")
    ap.add_argument("--run-only",    action="store_true")
    ap.add_argument("--start", default="2025-01-01")
    ap.add_argument("--end",   default="2026-07-17")
    args = ap.parse_args()

    if not args.run_only:
        print(f"=== Fetching universe OHLCV (window {args.start} → {args.end}) ===\n")
        fetch_universe(start_iso=args.start, end_iso=args.end)
    if args.fetch_only:
        sys.exit(0)

    print(f"\n=== Running volume factory on K={len(DEFAULT_UNIVERSE)} universe ===")
    res = run_volume_universe(symbols=DEFAULT_UNIVERSE)
    _print_run_result(res)
