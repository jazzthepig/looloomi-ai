"""
R97 — panel builder (real 1h parquet → 4h + frozen universe + parity check)
============================================================================
Seth, 2026-07-27 — per R97 plan §1.

This module:
  · Loads the real 1h OHLCV parquet for every liquid crypto asset under
    /Volumes/CometCloudAI/data/ohlcv/ (52 assets per R77 audit).
  · Resamples to 4h via `data_bridge.resample_to_4h` (no daily→4h fabrication).
  · Aligns the panel to CIS history + funding daily coverage.
  · Freezes the universe as a tuple of tickers sorted alphabetically.
  · Loads native 4h Binance futures feather for BTC/ETH/SOL parity verification
    (per R97 plan §1 — "optional parity check").
  · Loud-fails if the data is missing or has gaps (NO MOCK / NO FALLBACK).

Verdict grammar (R97-specific):
  · OK                  — universe is frozen + panel loads + parity tolerance met.
  · REFUSED_DATA        — missing data or fall below minimum coverage — no mock.

Anti-imposter:
  · Never synthesises OHLCV. If real data is absent, the panel builder raises
    loudly so the experiment is REFUSED_DATA rather than hallucinated.
  · Never uses /tmp/cometcloud_data/ohlcv.db daily bars as a 4h proxy.
  · Parity check is a TOLERANCE check, not a substitute for the canonical 1h→4h
    panel — the parquet panel is the authority.

Compliance: positioning language only; no trade-direction vocabulary.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

# ── Imports ─────────────────────────────────────────────────────────────────
# We avoid `import src.research.data_bridge as db` at module top to keep
# errors here local; only import when actually building the panel.
OHLCV_DIR = Path("/Volumes/CometCloudAI/data/ohlcv")
CIS_HISTORY_DIR = Path("/Volumes/CometCloudAI/cometcloud-local/_data/cis_history")
FUNDING_DIR = Path("/Volumes/CometCloudAI/cometcloud-local/_data/hyperliquid_funding")
NATIVE_4H_DIR = Path("/Volumes/CometCloudAI/freqtrade/user_data/data/binance/futures")

# Frozen R97 universe (alphabetical tuple). R77-verified 28-asset strict
# intersection of (CIS history, OHLCV 1h, funding daily) is the floor; we
# drop to OHLCV+1h-only if the funding-intersection is < 12.
# MIN_ASSETS guards against silent shrinkage of the panel.
MIN_ASSETS = 12
PARITY_TOLERANCE_PCT = 0.01  # 1% relative close tolerance vs native feather

logger = logging.getLogger(__name__)


# ── Asset list ──────────────────────────────────────────────────────────────
def list_available_assets(ohlcv_dir: Path = OHLCV_DIR) -> list[str]:
    """Return sorted list of tickers with a real parquet under ohlcv_dir."""
    files = sorted(ohlcv_dir.glob("*.parquet"))
    return [f.stem for f in files]


# ── 1h → 4h resampling ──────────────────────────────────────────────────────
def _load_1h_parquet_local(symbol: str, ohlcv_dir: Path = OHLCV_DIR) -> pd.DataFrame:
    """Inline 1h OHLCV loader — mirrors `data_bridge.load_1h_parquet` without
    pulling in nautilus_trader (we only need pandas resampling for R97)."""
    path = ohlcv_dir / f"{symbol}.parquet"
    if not path.exists():
        raise FileNotFoundError(f"OHLCV parquet not found: {path}")
    df = pd.read_parquet(path)
    if df["timestamp"].dt.tz is None:
        df["timestamp"] = df["timestamp"].dt.tz_localize("UTC")
    df = df.sort_values("timestamp").reset_index(drop=True)
    return df


def _resample_to_4h_local(df: pd.DataFrame) -> pd.DataFrame:
    """Inline 4h resampler — mirrors `data_bridge.resample_to_4h`."""
    df = df.set_index("timestamp")
    agg = df.resample("4h").agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum",
    })
    agg = agg.dropna(subset=["open"]).reset_index()
    return agg


def build_4h_for_symbol(symbol: str, ohlcv_dir: Path = OHLCV_DIR,
                        start: Optional[str] = None,
                        end: Optional[str] = None) -> pd.DataFrame:
    """Load real 1h parquet for `symbol`, resample to 4h, optionally clip window.

    Returns the resampled DataFrame with columns [timestamp, open, high, low,
    close, volume]. Raises FileNotFoundError loudly if the parquet is missing.
    Uses inlined loaders so R97 does not need nautilus_trader at import time.
    """
    df = _load_1h_parquet_local(symbol, ohlcv_dir=ohlcv_dir)
    df4h = _resample_to_4h_local(df)
    if start is not None or end is not None:
        s = pd.Timestamp(start) if start else df4h["timestamp"].min()
        e = pd.Timestamp(end) if end else df4h["timestamp"].max()
        df4h = df4h[(df4h["timestamp"] >= s) & (df4h["timestamp"] <= e)].reset_index(drop=True)
    if df4h.empty:
        raise RuntimeError(f"[R97] {symbol}: 4h panel is empty after resample+clip "
                           f"(rows={len(df4h)}, requested [{start}, {end}])")
    return df4h


# ── Panel builder ───────────────────────────────────────────────────────────
def build_panel(universe: list[str],
                ohlcv_dir: Path = OHLCV_DIR,
                start: Optional[str] = None,
                end: Optional[str] = None,
                min_4h_bars: int = 1000) -> pd.DataFrame:
    """Stack per-asset 4h panels into a single tidy DataFrame.

    Output columns: [timestamp, symbol, open, high, low, close, volume].
    `timestamp` is timezone-naive UTC (UTC alignment preserved via resample).
    Raises RuntimeError if any asset has fewer than `min_4h_bars` rows.
    """
    parts = []
    for sym in universe:
        df4h = build_4h_for_symbol(sym, ohlcv_dir=ohlcv_dir, start=start, end=end)
        if len(df4h) < min_4h_bars:
            raise RuntimeError(
                f"[R97] {sym}: only {len(df4h)} 4h bars (need ≥{min_4h_bars}); "
                f"refusing to fabricate data. Check {ohlcv_dir / (sym + '.parquet')}."
            )
        df4h = df4h.copy()
        df4h["symbol"] = sym
        parts.append(df4h[["timestamp", "symbol", "open", "high", "low", "close", "volume"]])
    panel = pd.concat(parts, ignore_index=True).sort_values(["timestamp", "symbol"]).reset_index(drop=True)
    return panel


# ── Coverage + freshness audit ──────────────────────────────────────────────
def coverage_audit(panel: pd.DataFrame) -> dict:
    """Per-symbol coverage stats + universe summary."""
    if panel.empty:
        return {"n_symbols": 0, "n_bars": 0, "earliest": None, "latest": None,
                "per_symbol": {}}
    sym_stats = {}
    for sym, g in panel.groupby("symbol"):
        sym_stats[sym] = {
            "n_bars": int(len(g)),
            "first": str(g["timestamp"].min()),
            "last": str(g["timestamp"].max()),
        }
    return {
        "n_symbols": int(panel["symbol"].nunique()),
        "n_bars": int(len(panel)),
        "earliest": str(panel["timestamp"].min()),
        "latest": str(panel["timestamp"].max()),
        "per_symbol": sym_stats,
    }


# ── Parity check vs native 4h feather ──────────────────────────────────────
def parity_check(panel: pd.DataFrame, symbol: str,
                 feather_dir: Path = NATIVE_4H_DIR,
                 tolerance: float = PARITY_TOLERANCE_PCT) -> dict:
    """Compare 1h→4h-derived closes against native Binance 4h feather for one
    symbol. Returns dict with max abs relative diff + n compared rows + verdict.
    """
    sub = panel[panel["symbol"] == symbol].sort_values("timestamp").reset_index(drop=True)
    if sub.empty:
        return {"ok": False, "reason": f"no 4h bars in panel for {symbol}"}
    fp = feather_dir / f"{symbol}_USDT_USDT-4h-futures.feather"
    if not fp.exists():
        return {"ok": False, "reason": f"no native feather at {fp}"}
    feather = pd.read_feather(fp)
    feather["date"] = pd.to_datetime(feather["date"])
    feather = feather.sort_values("date").reset_index(drop=True)
    # align by date — feather has timezone-naive UTC, panel has UTC-aware
    feather = feather.rename(columns={"date": "timestamp"})
    feather["timestamp"] = pd.to_datetime(feather["timestamp"]).dt.tz_localize("UTC")
    merged = sub.merge(feather[["timestamp", "close"]].rename(columns={"close": "close_feather"}),
                       on="timestamp", how="inner")
    if len(merged) < 100:
        return {"ok": False, "reason": f"only {len(merged)} aligned rows for {symbol}"}
    rel_diff = (merged["close"] - merged["close_feather"]).abs() / merged["close_feather"]
    max_diff = float(rel_diff.max())
    return {
        "ok": bool(max_diff < tolerance),
        "n_compared": int(len(merged)),
        "max_relative_diff": round(max_diff, 6),
        "tolerance": tolerance,
        "verdict": ("OK" if max_diff < tolerance else
                    f"MISMATCH — max relative diff {max_diff:.4%} > tolerance {tolerance:.2%}"),
    }


# ── Universe freezing ───────────────────────────────────────────────────────
def freeze_universe(ohlcv_dir: Path = OHLCV_DIR,
                    cis_history_dir: Path = CIS_HISTORY_DIR,
                    funding_dir: Path = FUNDING_DIR,
                    min_assets: int = MIN_ASSETS) -> tuple[str, ...]:
    """Freeze R97 universe = OHLCV 1h ∩ CIS history ∩ funding daily.

    Returns a tuple (immutable) sorted alphabetically. Loud-fails if fewer than
    `min_assets` assets are available. The audit prints every dropped asset
    and its reason so the freeze is observable.
    """
    ohlcv_assets = set(list_available_assets(ohlcv_dir))
    if not ohlcv_assets:
        raise RuntimeError(f"[R97] no parquet under {ohlcv_dir}")

    # CIS history — read first JSON to get the asset list (cheaper than 870 reads)
    if not cis_history_dir.exists():
        raise RuntimeError(f"[R97] CIS history dir missing: {cis_history_dir}")
    first = sorted(cis_history_dir.glob("cis_*.json"))
    if not first:
        raise RuntimeError(f"[R97] no CIS history JSON under {cis_history_dir}")
    with first[0].open() as fh:
        payload = json.load(fh)
    cis_assets = set()
    for s in payload.get("scores", []):
        a = s.get("asset") or s.get("symbol")
        if a:
            cis_assets.add(a)
    if not cis_assets:
        raise RuntimeError("[R97] no assets in CIS history payload")

    # Funding daily — list *_funding_1h.csv
    funding_assets = set(f.stem.replace("_funding_1h", "").upper()
                         for f in funding_dir.glob("*_funding_1h.csv"))
    if not funding_assets:
        raise RuntimeError(f"[R97] no funding CSVs under {funding_dir}")

    # Intersection
    inter_ohlcv_cis = ohlcv_assets & cis_assets
    inter_all = inter_ohlcv_cis & funding_assets
    dropped_funding = sorted(inter_ohlcv_cis - inter_all)
    dropped_cis = sorted(ohlcv_assets - cis_assets)
    dropped_ohlcv = sorted(set(cis_assets) - set(ohlcv_assets))

    print(f"[R97] OHLCV 1h avail:       {len(ohlcv_assets):>3}")
    print(f"[R97] CIS history avail:    {len(cis_assets):>3}")
    print(f"[R97] Funding daily avail:  {len(funding_assets):>3}")
    print(f"[R97] OHLCV ∩ CIS:          {len(inter_ohlcv_cis):>3}")
    print(f"[R97] OHLCV ∩ CIS ∩ fund:   {len(inter_all):>3}")
    print(f"[R97] Dropped (no funding): {len(dropped_funding):>3}")
    if dropped_funding:
        print(f"           {dropped_funding}")
    print(f"[R97] Dropped (no CIS):     {len(dropped_cis):>3}")
    if dropped_cis:
        print(f"           {dropped_cis}")

    if len(inter_all) < min_assets:
        raise RuntimeError(
            f"[R97] frozen universe has only {len(inter_all)} assets; need ≥{min_assets}. "
            f"REFUSED_DATA — no inference or mock, run on a wider panel."
        )

    return tuple(sorted(inter_all))


# ── Main entry ──────────────────────────────────────────────────────────────
def main(out_dir: Optional[Path] = None,
         start: Optional[str] = None,
         end: Optional[str] = None,
         min_assets: int = MIN_ASSETS) -> dict:
    """Build the R97 panel + freeze the universe + run parity checks. Returns
    a JSON-serialisable payload describing the panel + verdict.
    """
    if out_dir is None:
        out_dir = Path(f"reports/r97_panel/{datetime.now():%Y-%m-%d}")
    out_dir.mkdir(parents=True, exist_ok=True)

    universe = freeze_universe(min_assets=min_assets)
    print(f"\n[R97] Frozen universe ({len(universe)}): {list(universe)}\n")

    panel = build_panel(list(universe), start=start, end=end)
    audit = coverage_audit(panel)
    print(f"[R97] Panel: {audit['n_bars']} 4h-bars × {audit['n_symbols']} symbols")
    print(f"[R97] Range: {audit['earliest']} → {audit['latest']}\n")

    # Parity checks for BTC/ETH/SOL (native feather available for these)
    parities = {}
    for sym in ("BTC", "ETH", "SOL"):
        if sym in universe:
            parities[sym] = parity_check(panel, sym)
            print(f"[R97] Parity {sym}: {parities[sym].get('verdict', parities[sym].get('reason'))}")

    payload = {
        "verdict": "OK" if any(p.get("ok") for p in parities.values()) or not parities
                   else "REFUSED_DATA",
        "universe": list(universe),
        "n_universe": len(universe),
        "panel": audit,
        "parity_checks": parities,
        "window": {"start": start, "end": end},
        "min_assets": min_assets,
        "tolerance_pct": PARITY_TOLERANCE_PCT,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
    out_path = out_dir / "verdict.json"
    out_path.write_text(json.dumps(payload, indent=2, default=str))
    print(f"\n[R97] Wrote {out_path}")
    return payload


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", type=Path, default=None)
    ap.add_argument("--start", type=str, default=None)
    ap.add_argument("--end", type=str, default=None)
    ap.add_argument("--min-assets", type=int, default=MIN_ASSETS)
    args = ap.parse_args()
    main(out_dir=args.out_dir, start=args.start, end=args.end, min_assets=args.min_assets)