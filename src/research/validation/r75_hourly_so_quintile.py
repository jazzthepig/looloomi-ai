"""
R75 — Hourly S/O stability + Δ-quintile research (Seth, 2026-07-22).

Uses genuine sub-day CIS snapshots from ``/api/v1/cis/history/{symbol}``.
Daily observations are never expanded into synthetic hourly rows.  The pre-declared
maturity floor is 30 calendar days, 720 valid hours, and 12 assets; before that the
only admissible verdict is PREMATURE / INCONCLUSIVE, regardless of provisional t.

This is research-only.  It does not change CIS scores, weights, grades, signals,
the Mac Mini engine, or the push contract.
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import httpx
import numpy as np
import pandas as pd

from src.research.validation.cis_quality_absorption import OHLCV_DIR
from src.research.validation.factor_absorption import absorption_test
from src.research.validation.w5_forensics_external import load_funding_daily

R75_PILLARS = ("S", "O")
DELTA_LOOKBACKS = (1, 4, 8, 24)
CADENCES = (1, 4, 8, 24)
COST_GRID = (0.0, 5.0, 10.0)
K_QUINTILES = 5
MIN_CALENDAR_DAYS = 30.0
MIN_HOURLY_OBS = 720
MIN_ASSETS = 12
OOS_FRAC = 0.30
PERIODS_PER_YEAR = 365 * 24
NW_LAGS = 24
DEFAULT_API_BASE = "https://web-production-0cdf76.up.railway.app/api/v1"

_PILLAR_FIELDS = {"S": "pillar_s", "O": "pillar_o"}


def _finite_float(value):
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def normalize_hourly_history(rows: list[dict], pillar: str) -> tuple[pd.Series, dict]:
    """Normalize genuine snapshots to one value per UTC hour.

    The latest observation *within* each hour is retained.  Missing hours remain
    missing — there is deliberately no resampling/forward-fill step.
    """
    pillar = pillar.upper()
    if pillar not in _PILLAR_FIELDS:
        raise ValueError(f"pillar must be one of {tuple(_PILLAR_FIELDS)}, got {pillar!r}")
    field = _PILLAR_FIELDS[pillar]
    parsed = []
    non_null = 0
    for order, row in enumerate(rows):
        value = _finite_float(row.get(field))
        if value is None or not row.get("recorded_at"):
            continue
        ts = pd.to_datetime(row["recorded_at"], utc=True, errors="coerce")
        if pd.isna(ts):
            continue
        non_null += 1
        parsed.append((ts, order, value))
    if not parsed:
        empty = pd.Series(dtype=float, name=pillar)
        return empty, {
            "input_rows": len(rows), "non_null_rows": non_null,
            "unique_hours": 0, "duplicate_rows": 0,
            "first_hour": None, "last_hour": None,
        }

    frame = pd.DataFrame(parsed, columns=["timestamp", "order", "value"])
    frame = frame.sort_values(["timestamp", "order"])
    frame["hour"] = frame["timestamp"].dt.floor("h").dt.tz_localize(None)
    duplicate_rows = int(len(frame) - frame["hour"].nunique())
    hourly = frame.groupby("hour", sort=True)["value"].last().astype(float)
    hourly.name = pillar
    return hourly, {
        "input_rows": len(rows),
        "non_null_rows": non_null,
        "unique_hours": int(len(hourly)),
        "duplicate_rows": duplicate_rows,
        "first_hour": hourly.index.min().isoformat(),
        "last_hour": hourly.index.max().isoformat(),
    }


def build_hourly_pillar_panel(histories: dict[str, list[dict]], pillar: str) -> tuple[pd.DataFrame, dict]:
    """Build an hour × asset panel without fabricating missing timestamps."""
    columns: dict[str, pd.Series] = {}
    metadata = {}
    for symbol, rows in sorted(histories.items()):
        series, meta = normalize_hourly_history(rows, pillar)
        metadata[symbol.upper()] = meta
        if not series.empty:
            columns[symbol.upper()] = series
    panel = pd.DataFrame(columns).sort_index() if columns else pd.DataFrame()
    return panel, metadata


def _canonical_symbol(stem: str) -> str:
    sym = stem.upper().replace("-", "").replace("_", "")
    for suffix in ("USDT", "USD", "PERP"):
        if sym.endswith(suffix) and len(sym) > len(suffix):
            sym = sym[: -len(suffix)]
            break
    return sym


def load_hourly_returns(assets: Iterable[str], ohlcv_dir: Path = OHLCV_DIR) -> pd.DataFrame:
    """Load real hourly closes and return an hour × asset return matrix."""
    wanted = {str(a).upper() for a in assets}
    series = {}
    for path in sorted(Path(ohlcv_dir).glob("*.parquet")):
        sym = _canonical_symbol(path.stem)
        if sym not in wanted or sym in series:
            continue
        frame = pd.read_parquet(path)
        ts_col = "timestamp" if "timestamp" in frame.columns else "date" if "date" in frame.columns else None
        if ts_col is None or "close" not in frame.columns:
            continue
        ts = pd.to_datetime(frame[ts_col], utc=True, errors="coerce").dt.tz_localize(None).dt.floor("h")
        close = pd.Series(pd.to_numeric(frame["close"], errors="coerce").values, index=ts)
        close = close[~close.index.isna()].groupby(level=0).last().sort_index()
        series[sym] = close.pct_change(fill_method=None)
    return pd.DataFrame(series).sort_index() if series else pd.DataFrame()


def align_score_to_next_bar(score: pd.DataFrame, return_index: pd.DatetimeIndex) -> pd.DataFrame:
    """A score observed during hour t may only act on the return at t+1."""
    return score.reindex(return_index).shift(1)


def delta_score(panel: pd.DataFrame, lookback_hours: int, mode: str = "stable") -> pd.DataFrame:
    """Create stability or signed Δ scores from genuine hourly observations."""
    if lookback_hours < 1:
        raise ValueError("lookback_hours must be >= 1")
    prior = panel.reindex(panel.index - pd.Timedelta(hours=lookback_hours)).copy()
    prior.index = panel.index
    delta = panel - prior
    if mode == "stable":
        return -delta.abs()  # high score = smallest absolute move
    if mode == "positive":
        return delta
    if mode == "negative":
        return -delta
    raise ValueError("mode must be stable, positive, or negative")


def hourly_ls(score: pd.DataFrame, returns: pd.DataFrame, *, cadence_hours: int = 1,
              cost_bps: float = 0.0, k: int = K_QUINTILES,
              min_assets: int = MIN_ASSETS) -> pd.Series:
    """Cross-sectional top-minus-bottom return with next-bar PIT lag."""
    common = sorted(set(score.columns) & set(returns.columns))
    if len(common) < min_assets:
        return pd.Series(0.0, index=returns.index)
    r = returns[common].sort_index()
    lagged = align_score_to_next_bar(score[common], r.index)
    out = pd.Series(0.0, index=r.index)
    prev = pd.Series(0.0, index=common)
    for i, hour in enumerate(r.index):
        rr = r.loc[hour].reindex(common).fillna(0.0)
        if i % cadence_hours == 0:
            row = lagged.loc[hour].dropna()
            weights = pd.Series(0.0, index=common)
            if len(row) >= min_assets:
                try:
                    ranks = pd.qcut(row, q=k, labels=False, duplicates="drop")
                except ValueError:
                    ranks = pd.Series(dtype=float)
                if not ranks.empty and ranks.max() != ranks.min():
                    top = ranks[ranks == ranks.max()].index
                    bottom = ranks[ranks == ranks.min()].index
                    if len(top) and len(bottom):
                        weights.loc[top] = 1.0 / len(top)
                        weights.loc[bottom] = -1.0 / len(bottom)
            turnover = float((weights - prev).abs().sum())
            out.loc[hour] = float((weights * rr).sum()) - turnover * cost_bps / 1e4
            prev = weights
        else:
            out.loc[hour] = float((prev * rr).sum())
    return out


def _known_factors(returns: pd.DataFrame) -> dict[str, np.ndarray]:
    market = returns.mean(axis=1).fillna(0.0)
    trail = (1.0 + market).rolling(24, min_periods=24).apply(np.prod, raw=True) - 1.0
    momentum = np.sign(trail.shift(1).fillna(0.0)) * market
    return {"market": market.values, "momentum": momentum.values}


def _absorption(series: pd.Series, known: dict, start: int = 0) -> dict:
    y = np.asarray(series, dtype=float)[start:]
    factors = {k: np.asarray(v, dtype=float)[start:] for k, v in known.items()}
    if len(y) < max(30, NW_LAGS + 5) or np.nanstd(y) < 1e-15:
        return {"n": len(y), "alpha_t": float("nan"), "alpha_ann_pct": float("nan")}
    try:
        return absorption_test(np.nan_to_num(y), factors, nw_lags=NW_LAGS,
                               periods_per_year=PERIODS_PER_YEAR)
    except (ValueError, np.linalg.LinAlgError):
        return {"n": len(y), "alpha_t": float("nan"), "alpha_ann_pct": float("nan")}


def maturity_status(panels: dict[str, pd.DataFrame], min_assets: int = MIN_ASSETS) -> dict:
    """Frozen 30d / 720h / 12-asset gate, evaluated conservatively across S and O."""
    stats = {}
    for pillar, panel in panels.items():
        if panel.empty:
            stats[pillar] = {"calendar_days": 0.0, "valid_hours": 0, "assets": 0}
            continue
        valid = panel.notna().sum(axis=1) >= min_assets
        active = panel.index[valid]
        days = 0.0 if len(active) < 2 else (active.max() - active.min()).total_seconds() / 86400.0
        stats[pillar] = {
            "calendar_days": round(days, 2), "valid_hours": int(valid.sum()),
            "assets": int((panel.notna().sum(axis=0) > 0).sum()),
        }
    mature = bool(stats) and all(
        s["calendar_days"] >= MIN_CALENDAR_DAYS
        and s["valid_hours"] >= MIN_HOURLY_OBS
        and s["assets"] >= min_assets
        for s in stats.values()
    )
    return {"mature": mature, "thresholds": {
        "calendar_days": MIN_CALENDAR_DAYS, "hourly_obs": MIN_HOURLY_OBS,
        "assets": min_assets,
    }, "by_pillar": stats}


def fetch_histories(symbols: Iterable[str], *, days: int = 30,
                    api_base: str = DEFAULT_API_BASE) -> dict[str, list[dict]]:
    """Fetch public, real CIS history. Empty responses stay empty; no fallback data."""
    out = {}
    with httpx.Client(timeout=30.0) as client:
        for symbol in sorted({s.upper() for s in symbols}):
            try:
                resp = client.get(f"{api_base.rstrip('/')}/cis/history/{symbol}", params={"days": days})
                resp.raise_for_status()
                payload = resp.json()
                out[symbol] = payload.get("history", []) if isinstance(payload, dict) else []
            except Exception:
                out[symbol] = []
    return out


def _candidate_assets(ohlcv_dir: Path = OHLCV_DIR) -> list[str]:
    ohlcv_assets = sorted({_canonical_symbol(p.stem) for p in Path(ohlcv_dir).glob("*.parquet")})
    if not ohlcv_assets:
        return []
    funding = load_funding_daily(assets=ohlcv_assets)
    return sorted(set(ohlcv_assets) & set(funding.columns))


def run(*, out_dir: Path, days: int = 30, api_base: str = DEFAULT_API_BASE,
        ohlcv_dir: Path = OHLCV_DIR, coverage_only: bool = False) -> dict:
    """Fetch → normalize → align → provisional sweep → maturity-gated verdict."""
    assets = _candidate_assets(ohlcv_dir)
    if not assets:
        result = {"r_number": "R75", "verdict": "INCONCLUSIVE", "reason": "no funding/OHLCV assets"}
        _write_outputs(result, out_dir)
        return result

    histories = fetch_histories(assets, days=days, api_base=api_base)
    panels, coverage = {}, {}
    for pillar in R75_PILLARS:
        panels[pillar], coverage[pillar] = build_hourly_pillar_panel(histories, pillar)
    maturity = maturity_status(panels)
    result = {
        "r_number": "R75", "generated_at": datetime.now(timezone.utc).isoformat(),
        "construction": {
            "pillars": list(R75_PILLARS), "delta_lookbacks_hours": list(DELTA_LOOKBACKS),
            "cadences_hours": list(CADENCES), "cost_bps": list(COST_GRID),
            "k": K_QUINTILES, "score": "-abs(delta): stable-high / largest-move-low",
            "oos_fraction": OOS_FRAC, "periods_per_year": PERIODS_PER_YEAR,
            "nw_lags": NW_LAGS, "universe": "funding ∩ hourly-CIS ∩ hourly-OHLCV",
        },
        "maturity": maturity, "coverage": coverage, "cells": [], "headline": None,
    }

    if coverage_only:
        result["verdict"] = "MATURE" if maturity["mature"] else "PREMATURE"
        result["reason"] = "coverage-only run"
        _write_outputs(result, out_dir)
        return result

    returns = load_hourly_returns(assets, ohlcv_dir)
    common_assets = sorted(set(returns.columns) & set(panels["S"].columns) & set(panels["O"].columns))
    if len(common_assets) < MIN_ASSETS:
        result.update({"verdict": "INCONCLUSIVE", "reason": f"only {len(common_assets)} common assets"})
        _write_outputs(result, out_dir)
        return result
    common_index = returns.index
    for panel in panels.values():
        common_index = common_index.intersection(panel.index)
    returns = returns.loc[common_index, common_assets]
    known = _known_factors(returns)

    series_by_cell = {}
    for pillar in R75_PILLARS:
        panel = panels[pillar].reindex(index=common_index, columns=common_assets)
        for lookback in DELTA_LOOKBACKS:
            scores = {
                "stable": delta_score(panel, lookback, "stable"),
                "positive": delta_score(panel, lookback, "positive"),
                "negative": delta_score(panel, lookback, "negative"),
            }
            for cadence in CADENCES:
                for bps in COST_GRID:
                    row = {"pillar": pillar, "lookback_hours": lookback,
                           "cadence_hours": cadence, "cost_bps": bps}
                    for mode, score in scores.items():
                        fac = hourly_ls(score, returns, cadence_hours=cadence,
                                        cost_bps=bps, k=K_QUINTILES)
                        series_by_cell[(pillar, lookback, cadence, bps, mode)] = fac
                        fit = _absorption(fac, known)
                        row[f"{mode}_alpha_t"] = fit.get("alpha_t")
                        row[f"{mode}_alpha_ann_pct"] = fit.get("alpha_ann_pct")
                    result["cells"].append(row)

    gross = [c for c in result["cells"] if c["cost_bps"] == 0.0
             and math.isfinite(c.get("stable_alpha_t", float("nan")))]
    if not gross:
        result.update({"verdict": "INCONCLUSIVE", "reason": "no evaluable stability cell"})
        _write_outputs(result, out_dir)
        return result
    best = max(gross, key=lambda c: c["stable_alpha_t"])
    key = (best["pillar"], best["lookback_hours"], best["cadence_hours"])
    gross_fac = series_by_cell[key + (0.0, "stable")]
    cost_fac = series_by_cell[key + (5.0, "stable")]
    cut = int((1.0 - OOS_FRAC) * len(cost_fac))
    full_gross = _absorption(gross_fac, known)
    full_cost = _absorption(cost_fac, known)
    oos_cost = _absorption(cost_fac, known, start=cut)
    pos = _absorption(series_by_cell[key + (0.0, "positive")], known)
    neg = _absorption(series_by_cell[key + (0.0, "negative")], known)
    checks = {
        "gross": bool(full_gross.get("alpha_t", -math.inf) > 1.96),
        "cost_5bps": bool(full_cost.get("alpha_t", -math.inf) > 1.96),
        "oos_5bps": bool(oos_cost.get("alpha_t", -math.inf) > 1.96),
    }
    result["headline"] = {
        "pillar": key[0], "lookback_hours": key[1], "cadence_hours": key[2],
        "gross": full_gross, "cost_5bps": full_cost, "oos_5bps": oos_cost,
        "matched_signed_controls": {"positive_delta": pos, "negative_delta": neg},
        "oos_cut": cut, "checks": checks,
    }
    if not maturity["mature"]:
        result.update({"verdict": "PREMATURE", "reason": "pre-declared 30d/720h/12-asset gate not met; no strategy credit"})
    elif all(checks.values()):
        result.update({"verdict": "SURVIVES", "reason": "stability premium clears gross, cost, and OOS gates"})
    elif sum(checks.values()) == 2:
        result.update({"verdict": "PARTIAL", "reason": "two of three statistical gates pass"})
    else:
        result.update({"verdict": "REFUTED", "reason": "stability premium fails at least two gates"})
    _write_outputs(result, out_dir)
    return result


def _fmt(value, digits=2):
    try:
        value = float(value)
        return "n/a" if not math.isfinite(value) else f"{value:+.{digits}f}"
    except (TypeError, ValueError):
        return "n/a"


def format_report(result: dict) -> str:
    maturity = result.get("maturity", {})
    lines = [
        "# R75 — Hourly S/O Stability + Δ-Quintile",
        "", f"**Status:** **{result.get('verdict', 'INCONCLUSIVE')}**  ",
        f"**Reason:** {result.get('reason', '')}", "",
        "## 1. Frozen contract", "",
        "Genuine sub-day snapshots only; no daily→hourly synthetic forward-fill. Score at hour t may act only on return t+1.",
        "Primary factor is long the most stable S/O quintile and short the largest absolute-move quintile.", "",
        "## 2. Data maturity", "",
        "| Pillar | Calendar days | Valid hours | Assets |", "|---|---:|---:|---:|",
    ]
    for pillar, s in maturity.get("by_pillar", {}).items():
        lines.append(f"| {pillar} | {s['calendar_days']:.2f} | {s['valid_hours']} | {s['assets']} |")
    lines += ["", f"Frozen minimum: {MIN_CALENDAR_DAYS:.0f} days / {MIN_HOURLY_OBS} hours / {MIN_ASSETS} assets. Mature={maturity.get('mature', False)}.", ""]
    headline = result.get("headline")
    if headline:
        lines += ["## 3. Provisional headline — no credit before maturity", "",
                  f"Cell: pillar {headline['pillar']}, Δ={headline['lookback_hours']}h, rebalance={headline['cadence_hours']}h.", "",
                  "| Check | α_t | Ann. residual α | Pass |", "|---|---:|---:|:---:|",
                  f"| Gross | {_fmt(headline['gross'].get('alpha_t'))} | {_fmt(headline['gross'].get('alpha_ann_pct'))}% | {'YES' if headline['checks']['gross'] else 'NO'} |",
                  f"| 5bps | {_fmt(headline['cost_5bps'].get('alpha_t'))} | {_fmt(headline['cost_5bps'].get('alpha_ann_pct'))}% | {'YES' if headline['checks']['cost_5bps'] else 'NO'} |",
                  f"| 5bps last-30% OOS | {_fmt(headline['oos_5bps'].get('alpha_t'))} | {_fmt(headline['oos_5bps'].get('alpha_ann_pct'))}% | {'YES' if headline['checks']['oos_5bps'] else 'NO'} |", "",
                  "Signed controls are diagnostic only and are compared at this exact cell.", ""]
    lines += ["## 4. Verdict", "", f"**{result.get('verdict', 'INCONCLUSIVE')}** — {result.get('reason', '')}.", "",
              "No CIS scoring, grade, signal, weight, Mac Mini, Shadow, or push-contract change is made by R75."]
    return "\n".join(lines) + "\n"


def _json_safe(obj):
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        return None if not math.isfinite(float(obj)) else float(obj)
    return obj


def _write_outputs(result: dict, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    safe = _json_safe(result)
    (out_dir / "verdict.json").write_text(json.dumps(safe, indent=2, ensure_ascii=False) + "\n")
    (out_dir / "REPORT.md").write_text(format_report(safe))


def main() -> None:
    parser = argparse.ArgumentParser(description="R75 genuine-hourly S/O stability research")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--api-base", default=DEFAULT_API_BASE)
    parser.add_argument("--ohlcv-dir", type=Path, default=OHLCV_DIR)
    parser.add_argument("--coverage-only", action="store_true")
    parser.add_argument("--out-dir", type=Path,
                        default=Path("reports/r75_hourly_so_quintile/2026-07-22"))
    args = parser.parse_args()
    result = run(out_dir=args.out_dir, days=args.days, api_base=args.api_base,
                 ohlcv_dir=args.ohlcv_dir, coverage_only=args.coverage_only)
    print(format_report(result))


if __name__ == "__main__":
    main()
