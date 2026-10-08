"""T-071 / Strategy 4 — 5 spec equal-weight daily return series export.

Exports the 4th strategy (5-spec equal-weight blend) daily return series from
2023-01-02 to the last available day, with 10bp single-side turnover cost,
to JSON for the portfolio-layer replay (T-070 / S-511 / Seth's
`_portfolio_layer_loop`).

Reuses the M-208h sealed spec functions (spec_m86 / spec_m87 / spec_m88 /
spec_m113 / spec_m115) and the M-208h cost convention (10bp per |Δret|).
The five-spec equal-weight aggregation matches the M-208h C2 control
(`five_spec_equal_daily` helper in M-208h_run_2026-10-07.py).

Spec functions use only data ≤ d (no lookahead): returns are computed from
panel close-to-close moves, regime is tagged at t-1 (lag-1 BTC vs 200d MA +
panel 60d vol vs 252d median), and the spec rebalance windows (weekly /
14d) look only at formation windows ending ≤ d.

Output:
  /Users/sbb/Projects/looloomi-ai-lane-c/research/series/strategy4_blend_daily.json
  {
    "rows":   [{"d": "YYYY-MM-DD", "ret": float}, ...],
    "specs":  ["m86", "m87", "m88-base", "m113", "m115"],
    "weights": "equal",
    "cost_bps": 10,
    "as_of":  UTC ISO,
    "script": "cometcloud-local path"
  }

Days with no return (NaN) are dropped; missing days are NOT back-filled with 0.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# ---- Paths ----
WORKTREE = Path("/Users/sbb/Projects/looloomi-ai-lane-c")
CC_ROOT = Path("/Volumes/CometCloudAI/cometcloud-local")
M208_DIR = CC_ROOT / "research" / "t006"
LOADER = M208_DIR / "M-208_in_sample_loader_2026-10-07.py"
SPEC_PNL = M208_DIR / "M-208_spec_pnl_2026-10-07.py"
OUT_PATH = WORKTREE / "research" / "series" / "strategy4_blend_daily.json"

# Per M-208h §2.2 (sealed): 10bp single-side (labeled) — applied via the same
# formula M-208h_run_2026-10-07.py uses: `r -= cost_bp_per_turn / 10000 * |Δr|`
# where cost_bp_per_turn = COST_BP_PER_SIDE / 100 = 0.1. The effective rate
# on |Δr| is 0.1 / 10000 = 1e-5 (the M-208h C2 "+16.77%" number is built on
# this exact formula; matching it bit-for-bit is what T-071 demands).
COST_BPS = 10
COST_BP_PER_TURN = COST_BPS / 100  # 0.1 — must match M-208h_run line
                                     # `cost_bp_per_turn=COST_BP_PER_SIDE / 100`
SPECS5 = ["m86", "m87", "m88-base", "m113", "m115"]
SERIES_START = "2023-01-02"  # per T-071 acceptance

# ---- Dynamic import of M-208 loader & spec_pnl (filenames contain '-') ----
def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

_loader = _load("m208_loader", LOADER)
_spec = _load("m208_spec", SPEC_PNL)

load_panel_close = _loader.load_panel_close
regime_tagger = _loader.regime_tagger
spec_m88 = _spec.spec_m88
spec_m86 = _spec.spec_m86
spec_m87 = _spec.spec_m87
spec_m113 = _spec.spec_m113
spec_m115 = _spec.spec_m115


def ann_sr(daily_ret: pd.Series) -> float:
    sd = float(daily_ret.std(ddof=1))
    if sd < 1e-8:
        return 0.0
    return float(daily_ret.mean() / sd * math.sqrt(252))


def equal_weight_blend(spec_rets: dict, dates: pd.DatetimeIndex) -> pd.Series:
    """5-spec equal-weight daily returns over the given date index."""
    r = pd.Series(0.0, index=dates)
    n = 0
    for s in SPECS5:
        sr = spec_rets[s]
        if s not in spec_rets:
            raise KeyError(f"missing spec {s}")
        r = r + sr.reindex(dates).fillna(0.0)
        n += 1
    return r / n


def apply_turnover_cost(daily_ret: pd.Series, cost_bp_per_turn: float) -> pd.Series:
    """Per M-208h `portfolio_stats`: r_adj = r - (cost_bp_per_turn / 10000) * |Δr|.

    Day 0 has no prior day → cost = 0 (Δr is NaN → filled to 0).

    For T-071 we use cost_bp_per_turn = COST_BPS / 100 = 0.1 to match
    M-208h_run_2026-10-07.py's exact formula; the effective rate is
    0.1 / 10000 = 1e-5 per unit of |Δr|.
    """
    r = daily_ret.copy()
    delta = r.diff().abs().fillna(0.0)
    return r - (cost_bp_per_turn / 10000.0) * delta


def main():
    print(f"[T-071] loading panel + regime ...", flush=True)
    panel = load_panel_close()
    print(f"  panel: {len(panel)} days × {len(panel.columns)} symbols", flush=True)

    regime = regime_tagger(panel)

    print(f"[T-071] computing 5 spec daily returns ...", flush=True)
    spec_rets = {
        "m86": spec_m86(panel, regime),
        "m87": spec_m87(panel, regime),
        "m88-base": spec_m88(panel, regime, "base"),
        "m113": spec_m113(panel, regime),
        "m115": spec_m115(panel, regime),
    }
    for s in SPECS5:
        n_valid = int(spec_rets[s].notna().sum())
        print(f"  {s}: {n_valid} valid days", flush=True)

    print(f"[T-071] blending 5-spec equal weight ...", flush=True)
    daily = equal_weight_blend(spec_rets, panel.index)

    # Filter to SERIES_START onward. Index from CSV load is string-typed ("YYYY-MM-DD"),
    # so use string comparison (lexicographic == chronological on ISO dates).
    daily = daily.loc[daily.index >= SERIES_START]

    # Apply turnover cost (M-208h sealed formula: r -= (COST_BPS/100)/10000 * |Δr|)
    daily_cost = apply_turnover_cost(daily, COST_BP_PER_TURN)

    # Drop NaN (days with no return available)
    n_before = len(daily_cost)
    daily_cost = daily_cost.dropna()
    n_dropped = n_before - len(daily_cost)
    print(f"  total days: {n_before}, dropped (NaN): {n_dropped}", flush=True)

    if len(daily_cost) == 0:
        raise RuntimeError("empty series after NaN drop")

    first = str(daily_cost.index[0])
    last = str(daily_cost.index[-1])
    print(f"  range: {first} → {last}", flush=True)

    # Compound sanity for the OOS window that T-071 checks against M-208h.
    # Index is string-typed, so use string comparison.
    mask = (daily_cost.index >= "2025-01-01") & (daily_cost.index <= "2026-08-13")
    window = daily_cost.loc[mask]
    if len(window):
        nav = (1 + window).cumprod()
        cum = float(nav.iloc[-1] - 1)
        sr = ann_sr(window)
        peak = nav.cummax()
        dd = float((nav / peak - 1).min())
        print(f"  OOS 2025-01-01 → 2026-08-13: cum={cum:.4f} SR={sr:.4f} MaxDD={dd:.4f}", flush=True)
    else:
        cum = None
        print(f"  OOS window empty (panel shorter than 2025-01-01 → 2026-08-13)", flush=True)

    # ---- Write JSON ----
    rows = [{"d": str(idx), "ret": float(v)} for idx, v in daily_cost.items()]
    as_of = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    payload = {
        "rows": rows,
        "specs": list(SPECS5),
        "weights": "equal",
        "cost_bps": COST_BPS,
        "as_of": as_of,
        "script": "cometcloud-local/research/t006/M-208h_run_2026-10-07.py::five_spec_equal_daily (M-208h C2 control, sealed 10bp turnover cost); spec funcs via M-208_in_sample_loader + M-208_spec_pnl (sealed 2026-10-07)",
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"[T-071] wrote {OUT_PATH} ({len(rows)} rows)", flush=True)
    if cum is not None:
        print(f"[T-071] OOS compound = {cum*100:.2f}% (M-208h C2 target +16.77%, |Δ| < 0.5pp check: {abs(cum - 0.1677)*100:.3f}pp)", flush=True)
    return cum


if __name__ == "__main__":
    main()
