"""L/S state payload builder — S-397 §5b ④ Jev overlay feature engineering.

For each cadence (7d default), build a 30-field-ish L/S context that Jev reads
to produce 10 pair × {Choice, Score, Noul} = 30 calibrated judgments.

## Field budget (cardinality cap = 255)

For 5 symbols:
  - 5 × per-symbol fields (5 each) = 25
  - cross-asset fields = 10
  - total ≈ 35 fields (well under cap)

For 12 symbols (chunked-batch future):
  - 12 × 5 = 60 per-symbol
  - 10 cross = 10
  - total ≈ 70 fields (still safe; 30 → 66 pair questions × 3 prims = 198 Qs)

## Per-symbol fields (5 each)

1. `mom_30`  — 30d momentum (pct_change)
2. `mom_60`  — 60d momentum (pct_change)
3. `vol_30`  — 30d realized vol (annualized)
4. `breadth_pos` — close position relative to 200d MA (0 = at MA, 1 = above)
5. `cs_score`     — cross-sectional rank within universe (0 = worst, 1 = best)

## Cross-asset fields (10)

1. `regime`           — macro_regime canonical 7 (EASING|TIGHT|...)
2. `btc_dominance`    — BTC.D 0-1
3. `funding_rate_btc` — BTC perp funding (annualized, fraction)
4. `breadth_200ma`    — panel-wide breadth above 200d MA
5. `cross_skew`       — panel return skewness 30d
6. `panel_age_days`   — panel freshness
7. `panel_n_symbols`  — universe size
8. `vol_20d_panel`    — panel-level realized vol
9. `cadence_days`     — rebalance cadence for context
10. `cost_bps_rt`     — round-trip cost assumption (for Jev context)

## NaN discipline (Vadim principle)

Per `vadim.blog/ai-first-crypto-trading-principles`: every feature refuses
when it does not know (returns `None`, never 0). Zero is a real value; missing
is a real signal ("I don't know"). Jev should treat None as "insufficient
evidence" — bias toward neutral.
"""
from __future__ import annotations

import datetime as dt
import math
import statistics
from typing import Any, Mapping, Optional, Sequence


# ── NaN-safe helpers (mirror spec_runner.py discipline) ─────────────────────


def _finite(xs: Sequence[Optional[float]]) -> list[float]:
    """Drop None / NaN / inf. Order preserved."""
    out: list[float] = []
    for x in xs:
        if x is None:
            continue
        try:
            f = float(x)
        except (TypeError, ValueError):
            continue
        if math.isnan(f) or math.isinf(f):
            continue
        out.append(f)
    return out


def _mom(closes: Mapping[str, float], lag: int) -> Optional[float]:
    """`lag`-day momentum: closes[-1] / closes[-1-lag] - 1. None if insufficient."""
    ds = sorted(closes)
    if len(ds) <= lag or ds[-1 - lag] not in closes:
        return None
    a = closes[ds[-1 - lag]]
    b = closes[ds[-1]]
    if not a:
        return None
    return b / a - 1.0


def _vol(closes: Mapping[str, float], window: int) -> Optional[float]:
    """`window`-day realized vol (daily returns), annualized."""
    ds = sorted(closes)
    if len(ds) < window + 1:
        return None
    rets: list[float] = []
    for i in range(1, window + 1):
        a = closes[ds[-i - 1]]
        b = closes[ds[-i]]
        if a and b:
            rets.append(b / a - 1.0)
    if len(rets) < 5:
        return None
    s = statistics.stdev(rets) if len(rets) > 1 else 0.0
    return s * math.sqrt(365) if s else 0.0


def _breadth_position(closes: Mapping[str, float], ma_window: int = 200) -> Optional[float]:
    """Close position relative to 200d MA. 0 = at MA, >0 above, <0 below.

    Returns None if insufficient history (<ma_window + 1 days).
    """
    ds = sorted(closes)
    if len(ds) < ma_window + 1:
        return None
    window_closes = [closes[d] for d in ds[-ma_window:]]
    finite = _finite(window_closes)
    if len(finite) < ma_window // 2:
        return None
    ma = sum(finite) / len(finite)
    if ma == 0:
        return None
    last = closes[ds[-1]]
    return last / ma - 1.0


# ── Per-symbol feature builder ──────────────────────────────────────────────


def _per_symbol_features(closes_by_sym: Mapping[str, Mapping[str, float]]) -> dict[str, dict[str, Any]]:
    """Build the 5-field per-symbol feature dict for each symbol in the panel."""
    out: dict[str, dict[str, Any]] = {}
    universe = list(closes_by_sym.keys())
    # Cross-sectional rank needs all symbols' mom_60 first.
    mom_60_by_sym = {s: _mom(closes_by_sym[s], 60) for s in universe}
    finite_mom = {s: v for s, v in mom_60_by_sym.items() if v is not None}
    sorted_mom = sorted(finite_mom.items(), key=lambda kv: kv[1])

    for sym, closes in closes_by_sym.items():
        feats: dict[str, Any] = {
            "mom_30": _mom(closes, 30),
            "mom_60": mom_60_by_sym[sym],
            "vol_30": _vol(closes, 30),
            "breadth_pos": _breadth_position(closes, 200),
            "cs_score": None,  # filled below
        }
        # CS rank: 0 = worst, 1 = best (NaN-safe — None if symbol is NaN)
        if sym in finite_mom and len(sorted_mom) > 1:
            rank = next(i for i, (s, _) in enumerate(sorted_mom) if s == sym)
            feats["cs_score"] = rank / (len(sorted_mom) - 1)
        out[sym] = feats
    return out


# ── Cross-asset feature builder ─────────────────────────────────────────────


def _cross_asset_features(
    *,
    universe: Sequence[str],
    panel_age_days: Optional[int],
    cadence_days: int,
    cost_bps_rt: float,
    regime: Optional[str] = None,
    btc_dominance: Optional[float] = None,
    funding_rate_btc: Optional[float] = None,
    breadth_200ma: Optional[float] = None,
    cross_skew: Optional[float] = None,
    vol_20d_panel: Optional[float] = None,
) -> dict[str, Any]:
    """Build the 10-field cross-asset dict. Every field may be None if upstream
    data is missing — Jev treats None as "insufficient evidence", not as 0.
    """
    return {
        "regime": regime,
        "btc_dominance": btc_dominance,
        "funding_rate_btc": funding_rate_btc,
        "breadth_200ma": breadth_200ma,
        "cross_skew": cross_skew,
        "panel_age_days": panel_age_days,
        "panel_n_symbols": len(universe),
        "vol_20d_panel": vol_20d_panel,
        "cadence_days": int(cadence_days),
        "cost_bps_rt": float(cost_bps_rt),
    }


# ── Public API ──────────────────────────────────────────────────────────────


def build_ls_context(
    *,
    bar_ts: str,
    universe: Sequence[str],
    closes_by_sym: Mapping[str, Mapping[str, float]],
    panel_age_days: Optional[int],
    cadence_days: int = 7,
    cost_bps_rt: float = 10.0,
    regime: Optional[str] = None,
    btc_dominance: Optional[float] = None,
    funding_rate_btc: Optional[float] = None,
    breadth_200ma: Optional[float] = None,
    cross_skew: Optional[float] = None,
    vol_20d_panel: Optional[float] = None,
) -> dict[str, Any]:
    """Build the full L/S state payload for `bar_ts`.

    Returns a dict shaped for `JevDecisionBackend.evaluate_batch(state_payload, ...)`.
    Field count target: ~35 for 5 symbols (well under 255 cardinality cap).

    `bar_ts` is REQUIRED (Jev needs it to correlate decisions to bars).
    All other fields may be None if upstream data is missing — that's a real
    signal ("I don't know"), not a missing value.
    """
    if not bar_ts:
        raise ValueError("bar_ts is REQUIRED")
    if len(universe) < 2:
        raise ValueError(
            f"universe must have ≥ 2 symbols for L/S pairs, got {len(universe)}"
        )
    # Only build per-symbol features for symbols actually in the universe —
    # extra symbols in `closes_by_sym` are ignored (they may be future-expansion
    # candidates).
    in_universe = {s: closes_by_sym[s] for s in universe if s in closes_by_sym}
    if len(in_universe) < 2:
        raise ValueError(
            f"universe has {len(universe)} symbols but only {len(in_universe)} "
            f"have closes — need ≥2 to build pair features"
        )

    per_sym = _per_symbol_features(in_universe)
    cross = _cross_asset_features(
        universe=list(in_universe.keys()),
        panel_age_days=panel_age_days,
        cadence_days=cadence_days,
        cost_bps_rt=cost_bps_rt,
        regime=regime,
        btc_dominance=btc_dominance,
        funding_rate_btc=funding_rate_btc,
        breadth_200ma=breadth_200ma,
        cross_skew=cross_skew,
        vol_20d_panel=vol_20d_panel,
    )

    return {
        "bar_ts": bar_ts,
        "universe": list(in_universe.keys()),
        "per_symbol": per_sym,
        "cross_asset": cross,
    }


def count_fields(state: Mapping[str, Any]) -> int:
    """Total fields in the state payload (for cardinality-cap sanity check).

    Per-symbol features count as 5 fields each (the 5 fixed feature names).
    Cross-asset counts as 10 (the 10 fixed field names).
    The top-level keys (bar_ts, universe, per_symbol, cross_asset) DO NOT
    count individually — they're structural.
    """
    per_sym = state.get("per_symbol") or {}
    n_per_sym_fields = 5 * len(per_sym) if per_sym else 0
    cross = state.get("cross_asset") or {}
    n_cross_fields = 10 if cross else 0
    return n_per_sym_fields + n_cross_fields


__all__ = [
    "build_ls_context",
    "count_fields",
]
