"""
Cross-class TradFi extension of R46 quality L/S gauntlet.
============================================================================
Owner: Seth, 2026-07-20. Triggered by Jazz's option C — same 3-check gauntlet
on TradFi ETF universe (SPY, QQQ, IWM, sector ETFs, bond ETFs, commodities)
to test whether the 5d-rebal quality-L/S mechanism is **crypto-specific** or
generalizes to the TradFi cross-section.

What's known (per R46 + multi-regime crypto extension same day):
  * 5d-rebal composite CIS L/S at 5bps: t=+2.64 on 41-asset crypto universe (2024-2026)
  * 5d-rebal pillar_O at 5bps: t=+3.33 on 41-asset crypto universe (2024-2026)
  * Same constructs on narrower 14-major crypto universe: t ≤ +0.79 across all
    cadences — the signal REQUIRES universe breadth to surface.

This module's question: **does the same L/S mechanism work on a properly diverse
TradFi universe?** TradFi ETFs are genuinely heterogeneous (equities vs bonds
vs commodities vs currencies), so breadth should be real even at 15 names.
Compare to crypto 14-major case where 14 correlated majors couldn't carry it.

Pipeline:
  1. EODHD fetch for ~15 ETFs (cache JSON to local disk; re-use if present)
  2. Build quality proxy (momentum + inverse-vol), same as crypto extension
  3. Run cadence × cost grid + absorption on 2022-01 → 2026-06
  4. Compare to crypto 41-asset universe (R46) and crypto 14-major (multiregime)

Compliance: positioning language only.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from pathlib import Path

import httpx
import numpy as np
import pandas as pd

from src.research.validation.cis_quality_robustness import cadence_ls
from src.research.validation.factor_absorption import absorption_test

# Read EODHD key from cometcloud-local/.env
ENV_FILE = Path("/Volumes/CometCloudAI/cometcloud-local/.env")
CACHE_DIR = Path("/Volumes/CometCloudAI/cometcloud-local/_cache/eodhd_history")


def get_eodhd_key() -> str:
    """Read EODHD_API_KEY from the cometcloud-local .env file."""
    if not ENV_FILE.exists():
        raise RuntimeError(f".env not found at {ENV_FILE}")
    for line in ENV_FILE.read_text().splitlines():
        if line.startswith("EODHD_API_KEY="):
            return line.split("=", 1)[1].strip()
    raise RuntimeError("EODHD_API_KEY not in .env")


# TradFi ETF universe — heterogeneous across asset classes (breadth test)
TRADFI_UNIVERSE = [
    # Broad equities
    "SPY", "QQQ", "IWM", "DIA",
    # Sector equity ETFs
    "XLF", "XLK", "XLE", "XLV", "XLY",
    # Bond ETFs
    "TLT", "IEF", "HYG", "LQD",
    # Commodities
    "GLD", "USO", "SLV",
    # Currency (inverse USD)
    "UUP",
]


def fetch_eod(symbol: str, ticker_suffix: str = ".US",
              start: str = "2022-01-01", end: str = "2026-07-16",
              cache: bool = True) -> pd.DataFrame | None:
    """Fetch daily OHLC from EODHD; cache JSON to disk."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_fp = CACHE_DIR / f"{symbol}_{start}_{end}.json"
    if cache and cache_fp.exists():
        data = json.loads(cache_fp.read_text())
    else:
        key = get_eodhd_key()
        url = (f"https://eodhd.com/api/eod/{symbol}{ticker_suffix}"
               f"?period=d&from={start}&to={end}"
               f"&api_token={key}&fmt=json")
        try:
            r = httpx.get(url, timeout=30)
        except Exception as ex:
            print(f"  {symbol}: fetch failed ({ex})")
            return None
        if r.status_code != 200:
            print(f"  {symbol}: HTTP {r.status_code} {r.text[:100]}")
            return None
        try:
            data = r.json()
        except Exception:
            print(f"  {symbol}: bad JSON")
            return None
        if cache:
            cache_fp.write_text(json.dumps(data))
    if not data or not isinstance(data, list):
        print(f"  {symbol}: empty response")
        return None
    df = pd.DataFrame(data)
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
    df = df.set_index("date").sort_index()
    return df[["close"]]


def load_tradfi_panel(symbols: list = TRADFI_UNIVERSE,
                      start: str = "2022-01-01", end: str = "2026-07-16") -> pd.DataFrame:
    """Fetch all symbols, build date × asset CLOSE matrix, return daily returns."""
    out = {}
    for sym in symbols:
        df = fetch_eod(sym, start=start, end=end)
        if df is None:
            continue
        out[sym] = df["close"]
    prices = pd.DataFrame(out).sort_index().ffill()
    return prices.pct_change().dropna(how="all")


def compute_quality_proxy(daily_rets: pd.DataFrame,
                          lookback_ret: int = 90,
                          lookback_vol: int = 30) -> pd.DataFrame:
    """Same as crypto: momentum + inverse-vol, z-scored cross-section per day."""
    ret_mean = daily_rets.rolling(lookback_ret, min_periods=lookback_ret // 2).mean()
    vol = daily_rets.rolling(lookback_vol, min_periods=lookback_vol // 2).std()
    raw = ret_mean + 0.5 * (-vol)
    raw_t = raw.sub(raw.mean(axis=1), axis=0).div(raw.std(axis=1).replace(0, np.nan), axis=0)
    return raw_t.clip(-3, 3)


def known_factors(rets: pd.DataFrame) -> dict:
    f_market = rets.mean(axis=1).fillna(0.0)
    cum = (1 + f_market).cumprod()
    trail30 = cum / cum.shift(30) - 1
    f_momentum = (np.sign(trail30.shift(1)).fillna(0.0) * f_market)
    return {"market": f_market.values, "momentum": f_momentum.values}


def run(out_dir: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    print("=== R46 cross-class TradFi — quality L/S on ETF universe ===\n")

    print(f"Fetching {len(TRADFI_UNIVERSE)} TradFi ETFs via EODHD...")
    rets = load_tradfi_panel()
    print(f"  {rets.shape[0]} days × {rets.shape[1]} assets  ·  "
          f"{rets.index.min().date()} → {rets.index.max().date()}\n")

    if rets.shape[1] < 5:
        return {"error": "Too few symbols fetched"}

    proxy = compute_quality_proxy(rets)
    known_arrs = known_factors(rets)

    print("Cadence × cost sweep (proxy L/S on TradFi ETF cross-section):\n")
    cadences = (1, 3, 5, 7, 14)
    cost_grid = (0.0, 5.0, 10.0)
    grid = {}
    for cad in cadences:
        for bps in cost_grid:
            fac = cadence_ls(proxy, rets, rebal_days=cad,
                             cost_bps=bps).reindex(rets.index).fillna(0.0)
            r = absorption_test(fac.values, known_arrs, nw_lags=6, periods_per_year=365)
            grid[(cad, bps)] = {
                "alpha_t": r["alpha_t"], "alpha_ann_pct": r["alpha_ann_pct"],
                "raw_t": r["raw_t"], "raw_ann_pct": r["raw_ann_pct"],
                "alpha_significant": bool(r["alpha_significant"]),
                "r2": r["r2"],
            }

    # Windowed sub-periods (split by regime)
    windows = [
        ("W1: 2022-01 → 2022-12 (TradFi bear)",
         pd.Timestamp("2022-01-01"), pd.Timestamp("2022-12-31")),
        ("W2: 2023-01 → 2023-12 (recovery)",
         pd.Timestamp("2023-01-01"), pd.Timestamp("2023-12-31")),
        ("W3: 2024-01 → 2024-12 (chop + melt-up late)",
         pd.Timestamp("2024-01-01"), pd.Timestamp("2024-12-31")),
        ("W4: 2025-01 → 2025-12 (S&P melt-up)",
         pd.Timestamp("2025-01-01"), pd.Timestamp("2025-12-31")),
        ("W5: 2026-01 → 2026-06 (chop)",
         pd.Timestamp("2026-01-01"), pd.Timestamp("2026-06-30")),
    ]
    print("\nSub-period OOS (calendar-year windows):\n")
    window_results = []
    for label, s, e in windows:
        mask = (rets.index >= s) & (rets.index <= e)
        rets_w = rets[mask]
        proxy_w = proxy[mask]
        if len(rets_w) < 30:
            continue
        # Run only on 5d/5bps (best from R46)
        fac = cadence_ls(proxy_w, rets_w, rebal_days=5,
                         cost_bps=5.0).reindex(rets_w.index).fillna(0.0)
        kw = known_factors(rets_w)
        r = absorption_test(fac.values, kw, nw_lags=6, periods_per_year=365)
        window_results.append({
            "label": label, "n": int(mask.sum()),
            "alpha_t": r["alpha_t"], "alpha_ann_pct": r["alpha_ann_pct"],
            "alpha_significant": bool(r["alpha_significant"]),
        })
        print(f"  {label[:50]:<50} n={int(mask.sum()):>3}  "
              f"5d/5bps α_t={r['alpha_t']:+.2f}  "
              f"α_ann={r['alpha_ann_pct']:+.1f}%  "
              f"{'✓ clears' if r['alpha_significant'] else '✗ fails'}")

    out = {
        "asset_universe": list(rets.columns),
        "n_days": len(rets),
        "cadence_grid": {f"{c}_{int(b)}": v for (c, b), v in grid.items()},
        "window_results": window_results,
    }
    (out_dir / "verdict.json").write_text(json.dumps(out, indent=2, default=str))
    report = format_report(out)
    (out_dir / "REPORT.md").write_text(report)
    print(f"\n{report}")
    print(f"\nSaved: {out_dir/'verdict.json'} + {out_dir/'REPORT.md'}")
    return out


def format_report(out: dict) -> str:
    L = []
    L.append("# R46 Cross-Class — TradFi Quality L/S (2022-2026)\n")
    L.append(f"**Universe:** {', '.join(out['asset_universe'])}  ·  "
             f"{len(out['asset_universe'])} ETFs across equities / sectors / bonds / "
             f"commodities / currencies  ·  {out['n_days']} trading days\n")
    L.append("Per Jazz 2026-07-20 (option C): same 5d-rebal quality-L/S mechanism, "
             "applied to TradFi ETF cross-section. Tests whether the R46 finding is "
             "**crypto-specific** or **mechanism-general**.\n")

    L.append("## Cadence × cost grid (proxy L/S)\n")
    L.append("| rebal (d) | 0 bps t | 5 bps t | 10 bps t |")
    L.append("|--:|--:|--:|--:|")
    for cad in (1, 3, 5, 7, 14):
        ts = []
        for bps in (0.0, 5.0, 10.0):
            r = out["cadence_grid"][f"{cad}_{int(bps)}"]
            t = r["alpha_t"]
            ts.append(f"**{t:+.2f}**" if r["alpha_significant"] else f"{t:+.2f}")
        L.append(f"| {cad} | {ts[0]} | {ts[1]} | {ts[2]} |")

    L.append("\n## Sub-period OOS (5d-rebal / 5bps, calendar-year cuts)\n")
    L.append("| Window | dates | n | α_t | α_ann%/yr | verdict |")
    L.append("|--:|---|--:|--:|--:|---|")
    for w in out["window_results"]:
        tag = "✓ clears" if w["alpha_significant"] else "✗ fails"
        L.append(f"| {w['label'][:50]} | (per dates) | {w['n']} | "
                 f"{w['alpha_t']:+.2f} | {w['alpha_ann_pct']:+.1f}% | {tag} |")

    # Synthesis
    L.append("\n## Synthesis (vs crypto 41-asset R46 result)\n")

    # Find best cadence × cost
    best_key = None
    best_t = -np.inf
    for k, r in out["cadence_grid"].items():
        if r["alpha_t"] > best_t:
            best_t = r["alpha_t"]
            best_key = k
    cad, bps = best_key.split("_")
    r_best = out["cadence_grid"][best_key]
    tag = "✓ clears" if r_best["alpha_significant"] else "✗ fails"
    L.append(f"- **TradFi best:** `rebal={cad}d, cost={bps}bps` → t={r_best['alpha_t']:+.2f}, "
             f"ann={r_best['alpha_ann_pct']:+.1f}%/yr ({tag})")
    L.append(f"- **Crypto R46 reference (41 assets, 5d/5bps, pillar_O):** t=+3.33, ann=+70.1%/yr ✓✓✓")
    L.append(f"- **Crypto 14-major subset (5d/5bps, same proxy):** t=+0.28–+0.36 (sub-breadth)")

    # Window verdict
    n_clear = sum(1 for w in out["window_results"] if w["alpha_significant"])
    n_pos = sum(1 for w in out["window_results"] if w["alpha_t"] > 0)
    L.append(f"- **5d/5bps across TradFi calendar-year windows:** "
             f"{n_pos}/{len(out['window_results'])} positive, "
             f"{n_clear}/{len(out['window_results'])} clear 1.96")

    if n_clear >= 3:
        L.append("- **Mechanism generalizes to TradFi** — the 5d-rebal quality L/S is "
                 "not crypto-specific. Pillar/edge story applies to ETF cross-section too.")
    elif n_clear == 0:
        L.append("- **Mechanism does NOT generalize** — the 5d-rebal L/S fails on TradFi "
                 "even at proper breadth. R46's crypto finding is contingent on "
                 "crypto microstructure (high vol, persistent cross-section dispersion).")
    else:
        L.append(f"- **Partial generalization** — works in some TradFi regimes, fails in "
                 "others (pattern similar to crypto 14-major result: signal is "
                 "fragile to universe-correlation structure).")

    return "\n".join(L)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", type=Path,
                    default=Path(f"reports/cis_quality_tradfi/{datetime.now():%Y-%m-%d}"))
    args = ap.parse_args()
    run(args.out_dir)
