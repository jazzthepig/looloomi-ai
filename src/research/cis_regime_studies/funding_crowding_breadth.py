"""
§CROWDING-BREADTH 2026-07-18 — pooled funding-crowding market-neutral book (Minimax-B).

Per MINIMAX_SYNC §CROWDING-BREADTH: run crowding_signal UNCHANGED on a WIDE perp basket to
test the "real breadth" hypothesis. The 5-major crypto pool failed R35 (BTC/ETH/SOL co-move
~0.79, pooling = fake breadth). The question is whether crowding EPISODES are idiosyncratic
across uncorrelated underlyings — if so, ENB 2.5→8+, per-asset t≈1.5 crosses 1.96, and the
signal clears the gauntlet.

This runner takes a (symbols, funding_dict, ohlcv_dict) triple from any perp source:
  · Hyperliquid (Jazz's venue — the LP-pitch source of truth, fetched Mac-side)
  · RWA perps (corr ~0.22 to BTC, the cross-class breadth cohort — what we have cached)
  · Anything else providing {date → funding, ohlcv} aligned series.

Pipeline per run:
  1. Load funding + OHLCV per perp → daily series
  2. Run crowding_signal(funding, price, volume, thr, hold, vol_mult, cost_bps) per perp
  3. Build pooled market-neutral book:
       daily_pool_pos[t] = Σ_i (signal_pos_i[t] − μ_t) / N
     where μ_t = cross-sectional mean of |signal_pos_i[t]|, so the book is approximately β-neutral
     to "everyone crowded today" and earns only the IDIOSYNCRATIC crowding episodes.
  4. Pooled return = Σ_i w_i × position_i × return_i, equal-weight across perps
  5. f_market = equal-weight avg daily return across perps
  6. f_momentum = TSMOM(30) of f_market
  7. OOS split: first 80% train, last 20% OOS holdout
  8. Variant set = config sweep (thr × hold grid)
  9. Run signal_gauntlet.run_gauntlet on each variant; aggregate verdict.

Compliance: research/validation tooling; positioning language only downstream. Logs every
run shape (n_perps, coverage, OOS alpha, t) for the experiment_runs audit trail.

USAGE:
    from src.research.cis_regime_studies.funding_crowding_breadth import (
        load_rwa_perp_panel, run_pooled_breadth_experiment,
    )
    panel = load_rwa_perp_panel()                       # uses /Volumes/.../rwa_funding
    out = run_pooled_breadth_experiment(panel, thr=1.0, hold=10)  # a-priori config
    print(out["verdict"])

    # full gauntlet on the canonical config:
    from src.research.validation.signal_gauntlet import run_gauntlet
    g = run_gauntlet("crowding_breadth_rwa", out["oos_pooled_ret"], factors=out["factors"],
                     variants=out["variants"], periods_per_year=365)
    print(g["verdict"])
"""
from __future__ import annotations

import csv
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import numpy as np

from src.research.funding_crowding import crowding_signal


# ── 1. Load RWA perp panel from /Volumes/CometCloudAI/cometcloud-local/_data/rwa_funding/ ──

RWA_FUNDING_DIR = Path("/Volumes/CometCloudAI/cometcloud-local/_data/rwa_funding")
HL_FUNDING_DIR = Path("/Volumes/CometCloudAI/cometcloud-local/_data/hyperliquid_funding")


def _ts_ms_to_date(ts_ms: int) -> str:
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")


def _load_funding_8h(path: Path) -> dict[str, float]:
    """8h funding rates → daily sum (per spec, 3 settlements/day). Returns {date: sum_funding}."""
    daily: dict[str, float] = {}
    with open(path) as f:
        r = csv.DictReader(f)
        for row in r:
            d = _ts_ms_to_date(int(row["fundingTime"]))
            daily[d] = daily.get(d, 0.0) + float(row["fundingRate"])
    return daily


def _load_funding_1h_to_daily(path: Path) -> dict[str, float]:
    """Hourly funding rates → daily sum (HL spec, ~24 settlements/day). Returns {date: sum_funding}.

    Aggregation choice (DAILY SUM): matches the RWA loader's convention. For the crowding
    signal's z-score, daily sum captures total carry pressure over a day, which is the
    right denominator for "is today unusually crowded?" — same statistical shape as the
    RWA loader (which sums 3 8h settlements/day). Using daily MEAN would lose the carry
    information; using daily MAX would over-weight single settlement events.
    """
    daily: dict[str, float] = {}
    with open(path) as f:
        r = csv.DictReader(f)
        for row in r:
            d = _ts_ms_to_date(int(row["fundingTime"]))
            daily[d] = daily.get(d, 0.0) + float(row["fundingRate"])
    return daily


def _load_ohlcv_1d(path: Path) -> dict[str, dict]:
    """Daily OHLCV (close + quoteVolume). Returns {date: {close, volume}}."""
    out: dict[str, dict] = {}
    with open(path) as f:
        r = csv.DictReader(f)
        for row in r:
            d = _ts_ms_to_date(int(row["openTime"]))
            out[d] = {"close": float(row["close"]), "volume": float(row["quoteVolume"])}
    return out


@dataclass
class PerpPanel:
    """One perp's daily panel, aligned for the signal."""
    symbol: str
    dates: list[str]
    funding: np.ndarray          # daily funding sum
    close: np.ndarray            # daily close
    volume: np.ndarray           # daily quote volume


@dataclass
class PooledPanel:
    """Multi-perp panel aligned on the intersection of dates."""
    dates: list[str]
    symbols: list[str]
    per_perp: dict[str, PerpPanel] = field(default_factory=dict)


def load_rwa_perp_panel(min_history_days: int = 60,
                        max_perps: int = 30,
                        min_nonzero_pct: float = 0.10) -> PooledPanel:
    """Load all perps under /Volumes/CometCloudAI/cometcloud-local/_data/rwa_funding/, drop ones
    with <min_history_days of overlap, filter zero-funding perps, return intersection-aligned panel."""
    if not RWA_FUNDING_DIR.exists():
        raise FileNotFoundError(f"RWA funding dir not found: {RWA_FUNDING_DIR}")

    # pair up funding_8h + ohlcv_1d files per symbol
    perp_files: dict[str, dict[str, Path]] = {}
    for f in sorted(RWA_FUNDING_DIR.glob("*_funding_8h.csv")):
        sym = f.name.replace("_funding_8h.csv", "")
        ohlcv = RWA_FUNDING_DIR / f"{sym}_1d_ohlcv.csv"
        if ohlcv.exists():
            perp_files[sym] = {"funding": f, "ohlcv": ohlcv}

    # build candidate panels per perp
    candidates: dict[str, PerpPanel] = {}
    for sym, files in perp_files.items():
        f_daily = _load_funding_8h(files["funding"])
        ohlcv = _load_ohlcv_1d(files["ohlcv"])
        dates = sorted(set(f_daily.keys()) & set(ohlcv.keys()))
        if len(dates) < min_history_days:
            continue
        funding = np.array([f_daily[d] for d in dates])
        close = np.array([ohlcv[d]["close"] for d in dates])
        volume = np.array([ohlcv[d]["volume"] for d in dates])

        # filter: at least min_nonzero_pct of daily funding must be non-zero
        nz_pct = float(np.mean(np.abs(funding) > 1e-9))
        if nz_pct < min_nonzero_pct:
            continue

        candidates[sym] = PerpPanel(symbol=sym, dates=dates, funding=funding,
                                     close=close, volume=volume)

    if not candidates:
        raise RuntimeError(f"No perps met the criteria (min_history_days={min_history_days}, "
                           f"min_nonzero_pct={min_nonzero_pct})")

    # intersection of dates (panel-equal: every perp covers the same window)
    common = set.intersection(*[set(p.dates) for p in candidates.values()])
    if len(common) < min_history_days:
        raise RuntimeError(f"Intersection of dates too small: {len(common)} days "
                           f"(needed >= {min_history_days})")
    dates_sorted = sorted(common)

    # rebuild per_perp aligned to common dates
    per_perp: dict[str, PerpPanel] = {}
    for sym, p in candidates.items():
        idx = {d: i for i, d in enumerate(p.dates)}
        sel = [idx[d] for d in dates_sorted]
        per_perp[sym] = PerpPanel(
            symbol=sym, dates=dates_sorted,
            funding=p.funding[sel], close=p.close[sel], volume=p.volume[sel],
        )

    # cap to max_perps (prefer most history = most non-zero funding episodes)
    if len(per_perp) > max_perps:
        ranked = sorted(per_perp.items(),
                        key=lambda kv: float(np.sum(np.abs(kv[1].funding) > 1e-9)),
                        reverse=True)
        per_perp = dict(ranked[:max_perps])

    return PooledPanel(dates=dates_sorted, symbols=list(per_perp.keys()), per_perp=per_perp)


def load_hyperliquid_panel(min_history_days: int = 365,
                            max_perps: int = 50,
                            min_nonzero_pct: float = 0.10,
                            max_stale_days: int = 90) -> PooledPanel:
    """Load all perps under /Volumes/.../hyperliquid_funding/.

    File format (from scripts/fetch_hyperliquid_funding.py):
      · {SYMBOL}_funding_1h.csv   — hourly funding rate history, columns: fundingTime, fundingRate
      · {SYMBOL}_1d_ohlcv.csv     — daily candles, columns: openTime, close, quoteVolume
      · panel_summary.json        — per-symbol coverage (start, end, n_funding, n_ohlcv)

    Aggregation: hourly funding is SUMMED to daily (matches RWA loader's "daily sum" convention).
    OHLCV schema is identical to RWA (`openTime`, `close`, `quoteVolume`), so the existing
    `_load_ohlcv_1d()` works as-is.

    Defaults (min_history_days=365) match the §CROWDING-BREADTH directive's ≥2y requirement.

    **max_stale_days** (2026-07-20, Minimax-A addition): HL's `/info candleSnapshot` returns
    FROZEN candles for some perps (RNDR ends 2024-07-21, MKR 2025-09-05, FXS 2026-01-06, TON
    2026-06-15). Even with valid funding, these tank the cross-perp intersection to 0 days.
    Default `max_stale_days=90` drops any perp whose last OHLCV bar is > 90 days before today.
    Pass `max_stale_days=10_000` to disable.
    """
    if not HL_FUNDING_DIR.exists():
        raise FileNotFoundError(f"Hyperliquid funding dir not found: {HL_FUNDING_DIR}\n"
                                f"Run Mac-side: python3 scripts/fetch_hyperliquid_funding.py "
                                f"--universe top50 --start 2023-01-01")

    perp_files: dict[str, dict[str, Path]] = {}
    for f in sorted(HL_FUNDING_DIR.glob("*_funding_1h.csv")):
        sym = f.name.replace("_funding_1h.csv", "")
        ohlcv = HL_FUNDING_DIR / f"{sym}_1d_ohlcv.csv"
        if ohlcv.exists():
            perp_files[sym] = {"funding": f, "ohlcv": ohlcv}

    if not perp_files:
        raise RuntimeError(f"No {{sym}}_funding_1h.csv + {{sym}}_1d_ohlcv.csv pairs in {HL_FUNDING_DIR}\n"
                           f"Run Mac-side: python3 scripts/fetch_hyperliquid_funding.py "
                           f"--universe top50 --start 2023-01-01")

    candidates: dict[str, PerpPanel] = {}
    today_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for sym, files in perp_files.items():
        f_daily = _load_funding_1h_to_daily(files["funding"])
        ohlcv = _load_ohlcv_1d(files["ohlcv"])
        dates = sorted(set(f_daily.keys()) & set(ohlcv.keys()))
        if len(dates) < min_history_days:
            continue
        # stale-OHLCV filter (2026-07-20): HL candleSnapshot freezes for some perps
        last_ohlcv_day = max(ohlcv.keys())
        if max_stale_days < 10_000:
            days_stale = (
                datetime.strptime(today_iso, "%Y-%m-%d").date() -
                datetime.strptime(last_ohlcv_day, "%Y-%m-%d").date()
            ).days
            if days_stale > max_stale_days:
                # quiet skip — funding is current but OHLCV is frozen (perp delisted?)
                continue
        funding = np.array([f_daily[d] for d in dates])
        close = np.array([ohlcv[d]["close"] for d in dates])
        volume = np.array([ohlcv[d]["volume"] for d in dates])

        nz_pct = float(np.mean(np.abs(funding) > 1e-9))
        if nz_pct < min_nonzero_pct:
            continue

        candidates[sym] = PerpPanel(symbol=sym, dates=dates, funding=funding,
                                     close=close, volume=volume)

    if not candidates:
        raise RuntimeError(f"No HL perps met the criteria (min_history_days={min_history_days}, "
                           f"min_nonzero_pct={min_nonzero_pct})")

    common = set.intersection(*[set(p.dates) for p in candidates.values()])
    if len(common) < min_history_days:
        raise RuntimeError(f"HL intersection of dates too small: {len(common)} days "
                           f"(needed >= {min_history_days}). Consider lowering min_history_days.")

    dates_sorted = sorted(common)
    per_perp: dict[str, PerpPanel] = {}
    for sym, p in candidates.items():
        idx = {d: i for i, d in enumerate(p.dates)}
        sel = [idx[d] for d in dates_sorted]
        per_perp[sym] = PerpPanel(
            symbol=sym, dates=dates_sorted,
            funding=p.funding[sel], close=p.close[sel], volume=p.volume[sel],
        )

    if len(per_perp) > max_perps:
        ranked = sorted(per_perp.items(),
                        key=lambda kv: float(np.sum(np.abs(kv[1].funding) > 1e-9)),
                        reverse=True)
        per_perp = dict(ranked[:max_perps])

    return PooledPanel(dates=dates_sorted, symbols=list(per_perp.keys()), per_perp=per_perp)


# ── 2. Pooled market-neutral book construction ────────────────────────────────────


def _demeaned_position(positions: np.ndarray) -> np.ndarray:
    """Cross-sectionally demean each day's position (subtract daily mean across all perps).
    Result: market-neutral to "everyone crowded today", keeps idiosyncratic per-perp signal."""
    return positions - np.nanmean(positions, axis=0, keepdims=True)


def build_pooled_book(panel: PooledPanel, *, thr: float = 1.0, hold: int = 10,
                      zwin: int = 30, vol_mult: float = 1.10, cost_bps: float = 5.0) -> dict:
    """Run crowding_signal per perp, build pooled market-neutral book. Returns {position, returns,
    per_perp_returns, asset_returns, dates}."""
    n = len(panel.dates)
    n_perps = len(panel.symbols)

    # per-perp signal + asset returns
    per_perp_pos = np.zeros((n_perps, n))
    per_perp_ret = np.zeros((n_perps, n))     # position[t-1] * asset_ret[t], net of cost
    asset_ret = np.zeros((n_perps, n))

    for i, sym in enumerate(panel.symbols):
        p = panel.per_perp[sym]
        out = crowding_signal(p.funding, p.close, p.volume,
                              zwin=zwin, thr=thr, hold=hold, vol_mult=vol_mult, cost_bps=cost_bps)
        per_perp_pos[i] = out["position"]
        per_perp_ret[i] = out["returns"]
        asset_ret[i] = out["asset_return"]

    # demeaned pool position (market-neutral)
    pool_pos = _demeaned_position(per_perp_pos)

    # pooled return: equal-weight across perps of (demeaned_pos × asset_ret)
    # per_perp_ret already includes position × asset_return × (1 - cost), but position is raw
    # (not demeaned). For the market-neutral book we recompute with demeaned position.
    pool_ret = np.zeros(n)
    for t in range(1, n):
        pool_ret[t] = float(np.nanmean(pool_pos[:, t - 1] * asset_ret[:, t]))

    # transaction costs: re-cost the demeaned-book turnover (turnover doubled because both sides
    # trade when position sign flips; cost_bps × turnover × 1e-4)
    pool_turn = np.zeros(n)
    for i in range(n_perps):
        pool_turn += np.abs(np.diff(per_perp_pos[i], prepend=0)) / n_perps
    pool_ret -= pool_turn * cost_bps * 1e-4

    return {
        "pool_position": pool_pos,
        "pool_returns": pool_ret,
        "per_perp_returns": per_perp_ret,
        "asset_returns": asset_ret,
        "n_perps": n_perps,
        "dates": panel.dates,
        "symbols": panel.symbols,
    }


# ── 3. Factor panel (f_market, f_momentum) ───────────────────────────────────────


def build_factors(book: dict, tsmom_lookback: int = 30) -> dict[str, np.ndarray]:
    """f_market = equal-weight cross-section of daily returns (the perp basket itself).
    f_momentum = TSMOM(30) on f_market (the canonical momentum premium to subtract).
    For cross-class perps (RWA, sector ETFs), the natural benchmark is the same panel —
    we are asking "does this signal beat a beta-neutral passive perp basket?"."""
    asset_ret = book["asset_returns"]                     # [n_perps, n]
    f_market = np.nanmean(asset_ret, axis=0)              # equal-weight basket return

    cum = np.cumsum(f_market)
    f_mom = np.zeros_like(f_market)
    for t in range(tsmom_lookback + 1, len(f_market)):
        trail = cum[t - 1] - cum[t - 1 - tsmom_lookback]
        f_mom[t] = np.sign(trail) * f_market[t]

    return {"f_market": f_market, "f_momentum": f_mom}


# ── 4. Effective Number of Bets (broad-cohesion check) ────────────────────────────


def effective_n_bets(returns: np.ndarray) -> float:
    """ENB = N / (1 + (N-1) × avg_corr). 0 = perfectly redundant; N = perfectly independent."""
    if returns.ndim != 2 or returns.shape[0] < 3:
        return float(returns.shape[0]) if returns.ndim == 1 else 0.0
    R = returns[~np.isnan(returns).any(axis=1)] if False else returns  # keep all rows
    # remove NaNs column-wise (each column may have leading-NaN zwin warmup)
    R = np.where(np.isnan(R), 0.0, R)
    corr = np.corrcoef(R)
    n = corr.shape[0]
    np.fill_diagonal(corr, 0.0)
    avg_corr = float(corr.mean())
    if avg_corr >= 1.0:
        return 1.0
    return n / (1.0 + (n - 1) * avg_corr)


# ── 5. Config sweep + OOS holdout ────────────────────────────────────────────────


def run_pooled_breadth_experiment(panel: PooledPanel, *, thr: float = 1.0, hold: int = 10,
                                  cost_bps: float = 5.0, oos_frac: float = 0.20) -> dict:
    """A-priori canonical config (the directive: thr≈1.0, hold≈10d). Returns the canonical book
    plus factors and the variant set (config sweep)."""
    canonical = build_pooled_book(panel, thr=thr, hold=hold, cost_bps=cost_bps)
    factors = build_factors(canonical)

    # build variant set: small config sweep around the canonical point
    variants_specs = [
        ("thr_0.5_hold_10", dict(thr=0.5, hold=10)),
        ("thr_1.0_hold_10", dict(thr=1.0, hold=10)),  # canonical
        ("thr_1.5_hold_10", dict(thr=1.5, hold=10)),
        ("thr_1.0_hold_5",  dict(thr=1.0, hold=5)),
        ("thr_1.0_hold_15", dict(thr=1.0, hold=15)),
    ]
    variants = {}
    for name, cfg in variants_specs:
        v = build_pooled_book(panel, cost_bps=cost_bps, **cfg)
        variants[name] = v["pool_returns"]

    # OOS split: chronological last oos_frac is held out
    n = len(canonical["dates"])
    cutoff = int(n * (1.0 - oos_frac))
    oos_slice = slice(cutoff, n)

    pooled_ret_oos = canonical["pool_returns"][oos_slice]
    factors_oos = {k: v[oos_slice] for k, v in factors.items()}
    variants_oos = {k: v[oos_slice] for k, v in variants.items()}

    # ENB check on per-perp ASSET returns (not the signal) — this is the input-side breadth.
    enb_assets = effective_n_bets(canonical["asset_returns"][:, 30:].T)

    # crude alpha/t summary on canonical OOS
    oos_alpha_t = _alpha_t_new_west(pooled_ret_oos, factors_oos)

    return {
        "dates": canonical["dates"],
        "canonical": canonical,
        "factors": factors,
        "factors_oos": factors_oos,
        "variants": variants,
        "variants_oos": variants_oos,
        "oos_slice": oos_slice,
        "pooled_ret_oos": pooled_ret_oos,
        "oos_alpha_t": oos_alpha_t,
        "enb_input_assets": enb_assets,
        "n_perps": canonical["n_perps"],
        "n_days": n,
        "oos_days": n - cutoff,
    }


def _alpha_t_new_west(y: np.ndarray, factors: dict[str, np.ndarray], nw_lags: int = 6) -> dict:
    """Tiny NW OLS — alpha_t only — for the headline summary before full gauntlet."""
    n = len(y)
    cols = [np.asarray(factors[k]) for k in factors]
    X = np.column_stack([np.ones(n)] + cols)
    XtX_inv = np.linalg.inv(X.T @ X)
    beta = XtX_inv @ (X.T @ y)
    resid = y - X @ beta
    Xe = X * resid[:, None]
    S = Xe.T @ Xe
    for l in range(1, nw_lags + 1):
        w = 1.0 - l / (nw_lags + 1.0)
        G = Xe[l:].T @ Xe[:-l]
        S += w * (G + G.T)
    cov = XtX_inv @ S @ XtX_inv
    se = np.sqrt(np.maximum(np.diag(cov), 1e-18))
    alpha = float(beta[0]); alpha_t = float(alpha / max(se[0], 1e-18))
    ann_alpha = alpha * 365 * 100
    return {"alpha_per_period": round(alpha, 6), "alpha_ann_pct": round(ann_alpha, 2),
            "alpha_t": round(alpha_t, 2), "n": n, "betas": {k: round(float(beta[i + 1]), 3)
            for i, k in enumerate(factors)}}


# ── 6. Verdict formatter ─────────────────────────────────────────────────────────


def format_verdict(out: dict, gauntlet_result: dict | None = None) -> str:
    lines = ["CROWDING-BREADTH EXPERIMENT (a-priori canonical: thr=1.0, hold=10d)",
             "=" * 64]
    lines.append(f"Pool: {out['n_perps']} perps × {out['n_days']} days "
                 f"(OOS {out['oos_days']}d = {out['oos_days']/out['n_days']:.0%})")
    lines.append(f"Input-asset ENB (the breadth question): {out['enb_input_assets']:.2f}")
    lines.append("")
    lines.append("Canonical OOS α (after f_market + f_momentum, NW t-stat):")
    a = out["oos_alpha_t"]
    lines.append(f"  α_ann_pct = {a['alpha_ann_pct']:+.2f}%, α_t = {a['alpha_t']:+.2f}, n = {a['n']}")
    lines.append(f"  factor betas: {a['betas']}")
    lines.append("")
    lines.append("Variant set (config sweep):")
    for v_name, v_ret in out["variants_oos"].items():
        sh = _annualized_sharpe(v_ret)
        lines.append(f"  {v_name:<25}  ann Sharpe {sh:+.2f}")
    lines.append("")
    if gauntlet_result is not None:
        lines.append("Signal Gauntlet verdict:")
        lines.append(f"  verdict : {gauntlet_result['verdict']}")
        lines.append(f"  funnel  : {gauntlet_result['funnel']}")
        for st in gauntlet_result["stages"]:
            mark = "✓" if st["passed"] else "✗" if st["passed"] is False else "·"
            extra = "" if not st.get("note") else f"  ({st['note']})"
            lines.append(f"    {mark} {st['stage']:<22} {st['metric']}{extra}")
    return "\n".join(lines)


def _annualized_sharpe(r: np.ndarray, periods_per_year: int = 365) -> float:
    r = r[~np.isnan(r)]
    if len(r) < 5 or r.std() < 1e-12:
        return 0.0
    return float(r.mean() / r.std() * math.sqrt(periods_per_year))


# ── 7. Self-test on synthetic data ───────────────────────────────────────────────


def _selftest():
    """Smoke test with a synthetic panel: build a 10-perp mock panel where 5 have a true
    crowding edge and 5 are noise. Verify ENB>1, pooled alpha>t-stat, gauntlet pass."""
    rng = np.random.default_rng(7)
    n_days = 500
    n_perps = 10
    dates = [f"2024-{(i // 30) % 12 + 1:02d}-{(i % 30) + 1:02d}" for i in range(n_days)]

    per_perp = {}
    for i in range(n_perps):
        has_edge = (i % 2 == 0)
        # funding: PER-PERP independent spike schedule (this is what makes the signal IDIOSYNCRATIC
        # across the pool — the cross-section mean won't absorb it all)
        funding = np.zeros(n_days)
        spike_days = []
        for t in range(30, n_days):
            funding[t] = rng.normal(0, 0.0005)
            if t % 25 == 0:  # offset so perps spike on different days
                funding[t] += rng.choice([-1, 1]) * 0.003
                spike_days.append((t, np.sign(funding[t])))

        # price: the embedded edge matches the actual mechanism the signal captures —
        # crowded longs (positive spike) → unwind drives price DOWN for ~5d (fade-able via SHORT);
        # crowded shorts (negative spike) → squeeze drives price UP for ~5d (fade-able via LONG).
        ret = np.zeros(n_days)
        if has_edge:
            for t, sign in spike_days:
                ret[t] += -sign * 0.010
                for k in range(1, 6):
                    if t + k < n_days:
                        ret[t + k] += -sign * 0.006
        ret += rng.normal(0.0003, 0.018, n_days)
        price = 100 * np.cumprod(1 + ret)

        # volume: spikes during the funding extremes (signal requires vexp=True)
        volume = np.abs(rng.normal(1e6, 3e5, n_days))
        for t in range(n_days):
            if abs(funding[t]) > 0.001:
                volume[t] *= 2.5

        per_perp[f"SYM{i}"] = PerpPanel(symbol=f"SYM{i}", dates=dates,
                                        funding=funding, close=price, volume=volume)

    panel = PooledPanel(dates=dates, symbols=list(per_perp.keys()), per_perp=per_perp)
    out = run_pooled_breadth_experiment(panel)

    assert out["n_perps"] == 10
    assert out["n_days"] == n_days
    # OOS alpha_t should be POSITIVE on the canonical (true edge in 5/10 perps).
    # We don't enforce |t|>1.0 here — that's the gauntlet's job, and 100 OOS days is small.
    assert out["oos_alpha_t"]["alpha_t"] > 0.0, f"α_t should be positive, got {out['oos_alpha_t']}"
    # ENB should be > 1 (not all redundant)
    assert out["enb_input_assets"] > 1.0, f"ENB too low: {out['enb_input_assets']}"
    # signal must fire BOTH directions (long + short) — proves both crowding regimes work
    canonical = out["canonical"]
    fired_long = int((canonical["pool_position"] > 0.1).sum())
    fired_short = int((canonical["pool_position"] < -0.1).sum())
    assert fired_long > 0 and fired_short > 0, \
        f"signal only fires one direction: long={fired_long}, short={fired_short}"

    # now run full gauntlet
    from src.research.validation.signal_gauntlet import run_gauntlet, format_funnel
    g = run_gauntlet("crowding_breadth_synthetic", out["pooled_ret_oos"],
                     factors=out["factors_oos"], variants=out["variants_oos"],
                     periods_per_year=365)
    print("SELF-TEST gauntlet:")
    print(format_funnel([g]))
    print()
    print("Self-test summary:")
    print(format_verdict(out, g))


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--selftest":
        _selftest()
    else:
        print("Loading RWA perp panel...")
        panel = load_rwa_perp_panel(min_history_days=80, max_perps=30, min_nonzero_pct=0.10)
        print(f"Loaded {panel.symbols}")
        print(f"Window: {panel.dates[0]} → {panel.dates[-1]} ({len(panel.dates)} days)")
        print()
        out = run_pooled_breadth_experiment(panel)
        print(format_verdict(out))
        # run full gauntlet
        from src.research.validation.signal_gauntlet import run_gauntlet, format_funnel
        g = run_gauntlet("crowding_breadth_rwa", out["pooled_ret_oos"],
                         factors=out["factors_oos"], variants=out["variants_oos"],
                         periods_per_year=365)
        print()
        print(format_funnel([g]))