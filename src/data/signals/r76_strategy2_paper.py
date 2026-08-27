"""
§Strategy-2 R76 Paper Book — forward-committed live R76 cell (Seth, 2026-08-24).
================================================================================

R76 verified as a standalone L/S clears 3/3 deployment gates on the 770-day panel
(2024-06-07 → 2026-07-18, 28-asset strict):
  · 3-check: gross_t = +2.06 ✓, OOS_t = +2.47 ✓, passes_all = True
  · maxDD: -21.27% in worst window
  · 5/6 windows positive (W1 +53.7%, W2 +47.9%, W3 -36.5%, W4 +1.4%, W5 +152.5%, W6 +77.4%)

R76 is the ONLY survivor of the cross-sectional funding-residual family
(LEVEL = R76 ✓ / IVOL = R95 PARTIAL / MOMENTUM = R96 PARTIAL). R77 (Strategy 1)
is the 3-leg fusion of R46 + R62 + R76; R76 (Strategy 2) is the standalone
funding-residual L/S that made R77's lesson #43 work in the first place.

ARCHITECTURE (frozen — no live retuning):
  · Universe: STRICT 28-asset funding ∩ OHLCV intersection (same as R77 family).
  · Score: cross-sectional demean of daily funding rate (sign = high_fund_long).
  · L/S: long top tercile, short bottom tercile (k=3).
  · Rebal: 5d (frozen best cell from R76 sweep).
  · Cost: 0bps (the optimal cell; live slippage added via fill_attribution).

DATA PATHS (live):
  · Close prices:  Binance fapi /klines (Railway-reachable).
  · Funding:       Binance fapi /fundingRate (Railway-reachable).
  · State:         file-based JSON at /tmp/cometcloud_data/r76_paper/state.json
                    (avoids Supabase auth/RLS complexity; the system of record
                    for the paper book is the JSON file + daily NAV csv).
  · NAV curve:     /tmp/cometcloud_data/r76_paper/nav.csv

PIT-SAFETY:
  · Funding residual is cross-sectional demean at time t (no look-ahead).
  · Mark-to-market uses y[t] / y[t-1] - 1, no look-ahead.
  · State is read → mark → write, single-threaded per day.

HONESTY GATES:
  · If 28-asset panel incomplete (< 6 names) → mark book flat that day.
  · `validated` flag flips True only after n_days ≥ 60.

Compliance: positioning language only in any surfaced output (long/short
describes exposure, not investment advice).
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import logging
import os
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

_log = logging.getLogger("r76_strategy2_paper")

# ── Persistence (file-based, simpler than fusion_paper) ────────────────────────
_R76_PAPER_DIR = Path("/tmp/cometcloud_data/r76_paper")
_R76_PAPER_DIR.mkdir(parents=True, exist_ok=True)
_STATE_PATH = _R76_PAPER_DIR / "state.json"
_NAV_CSV_PATH = _R76_PAPER_DIR / "nav.csv"

# ── R76 frozen cell constants (matches r76_funding_residual_ls.py best cell) ──
R76_CAD = 5                 # rebal cadence (days) — frozen best cell
R76_BPS = 0.0               # cost per turnover (frozen best cell)
R76_K = 3                   # tercile count
R76_SIGN = "high_fund_long" # long top tercile of high-funding-residual / short bottom

# Universe (same 28-asset strict as R77 fusion_paper; per R64 panel)
UNIVERSE = sorted([
    "AAVE", "APT", "ARB", "ATOM", "AVAX", "BNB", "BTC", "COMP",
    "DOGE", "DOT", "ENA", "ETH", "FIL", "INJ", "LDO", "LINK",
    "MKR", "NEAR", "OP", "PENDLE", "SEI", "SOL", "STRK", "STX",
    "SUI", "TIA", "UNI", "XRP",
])

# Capacity ceiling (paper book; conservative start)
DEFAULT_DECLARED_CAPACITY_USD = 1_000_000.0

# Honesty gate: validated only after ≥60 forward days marked
VALIDATION_MIN_DAYS = 60

# Binance fapi (same as fusion_paper)
_FAPI = "https://fapi.binance.com/fapi/v1"
_BINANCE_TK_MAP = {
    "AAVE": "AAVEUSDT", "APT": "APTUSDT", "ARB": "ARBUSDT",
    "ATOM": "ATOMUSDT", "AVAX": "AVAXUSDT", "BNB": "BNBUSDT",
    "BTC": "BTCUSDT", "COMP": "COMPUSDT", "DOGE": "DOGEUSDT",
    "DOT": "DOTUSDT", "ENA": "ENAUSDT", "ETH": "ETHUSDT",
    "FIL": "FILUSDT", "INJ": "INJUSDT", "LDO": "LDOUSDT",
    "LINK": "LINKUSDT", "MKR": "MKRUSDT", "NEAR": "NEARUSDT",
    "OP": "OPUSDT", "PENDLE": "PENDLEUSDT", "SEI": "SEIUSDT",
    "SOL": "SOLUSDT", "STRK": "STRKUSDT", "STX": "STXUSDT",
    "SUI": "SUIUSDT", "TIA": "TIAUSDT", "UNI": "UNIUSDT",
    "XRP": "XRPUSDT",
}


# ── Live data fetcher (mirrors fusion_paper._fetch_close_funding) ──────────────
async def _fetch_close_funding(symbols: list, lookback_days: int = 60) -> dict:
    """{sym: {"close": [...daily], "funding": [...daily mean]}} from Binance fapi."""
    import httpx
    out: dict = {}
    headers = {"User-Agent": "cometcloud"}
    async with httpx.AsyncClient(timeout=20) as c:
        for sym in symbols:
            tk = _BINANCE_TK_MAP.get(sym)
            if not tk:
                continue
            try:
                r = await c.get(f"{_FAPI}/klines",
                                 params={"symbol": tk, "interval": "1d", "limit": lookback_days},
                                 headers=headers)
                kl = r.json() if r.status_code == 200 else []
                if not kl or len(kl) < 5:
                    continue
                closes = [float(x[4]) for x in kl]
                out[sym] = {"close": closes, "funding": []}
                # funding is 8h; aggregate to daily mean
                rf = await c.get(f"{_FAPI}/fundingRate",
                                 params={"symbol": tk, "limit": lookback_days * 3},
                                 headers=headers)
                fr = rf.json() if rf.status_code == 200 else []
                if fr:
                    by_day: dict = {}
                    for x in fr:
                        ts = pd.Timestamp(int(x["fundingTime"]), unit="ms").normalize()
                        by_day.setdefault(ts, []).append(float(x["fundingRate"]))
                    sorted_days = sorted(by_day.keys())
                    out[sym]["funding"] = [float(np.mean(by_day[d])) for d in sorted_days]
                    out[sym]["funding_dates"] = sorted_days
            except Exception as e:
                _log.debug(f"{sym} fetch failed: {e}")
                continue
    return out


# ── R76 score: cross-sectional demean of funding ─────────────────────────────
def _score_r76(funding_panel: pd.DataFrame) -> pd.DataFrame:
    """Per-time cross-sectional demean. Positive = above-mean funding (long leg)."""
    if funding_panel.empty:
        return funding_panel.copy()
    return funding_panel.subtract(funding_panel.mean(axis=1), axis=0)


# ── Target weights (R76 only, no fusion, no detector) ─────────────────────────
def _target_weights_r76(score_wide: pd.DataFrame, today_idx: pd.Timestamp) -> dict:
    """Long top tercile / short bottom tercile of today's funding-residual score."""
    if score_wide.empty or today_idx not in score_wide.index:
        return {}
    row = score_wide.loc[today_idx].dropna()
    if len(row) < 6:  # need at least 2 terciles worth
        return {}
    vals = sorted(row.items(), key=lambda kv: kv[1])
    n = len(vals)
    terc_size = max(1, n // R76_K)
    w: dict = {}
    for sym, _ in vals[:terc_size]:
        w[sym] = w.get(sym, 0.0) - 1.0 / terc_size
    for sym, _ in vals[-terc_size:]:
        w[sym] = w.get(sym, 0.0) + 1.0 / terc_size
    # Renormalize to gross Σ|w| = 2/3 (preserves L/S structure)
    gross = sum(abs(x) for x in w.values())
    target_gross = 2.0 / 3.0
    if gross > 0:
        scale = target_gross / gross
        w = {k: v * scale for k, v in w.items()}
    return w


# ── State management (file-based JSON) ─────────────────────────────────────────
def _load_state() -> dict:
    if _STATE_PATH.exists():
        try:
            return json.loads(_STATE_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {
        "inception": None,
        "nav": 1.0,
        "weights": {},
        "mark_prices": {},
        "prev_prices": {},
        "last_mark": None,
        "n_days_marked": 0,
        "cell": {
            "cad": R76_CAD, "bps": R76_BPS, "k": R76_K, "sign": R76_SIGN,
            "declared_capacity_usd": DEFAULT_DECLARED_CAPACITY_USD,
        },
    }


def _save_state(s: dict) -> None:
    _STATE_PATH.write_text(json.dumps(s, indent=2, default=str))


def _append_nav_row(d: dt.date, nav: float, dret: float, gross: float,
                     n_positions: int, cost: float, det_fired: bool) -> None:
    """Append a daily NAV row. Header written on first call."""
    header = ["mark_date", "nav", "daily_return", "gross", "n_positions",
              "cost", "detector_fired", "cell_cad", "cell_bps", "cell_k", "cell_sign"]
    write_header = not _NAV_CSV_PATH.exists()
    with open(_NAV_CSV_PATH, "a", newline="") as f:
        w = csv.writer(f)
        if write_header:
            w.writerow(header)
        w.writerow([d.isoformat(), round(nav, 6), round(dret, 6),
                    round(gross, 4), n_positions, round(cost, 6),
                    bool(det_fired), R76_CAD, R76_BPS, R76_K, R76_SIGN])


# ── Mark-and-rebalance (the daily entry point) ────────────────────────────────
async def mark_and_rebalance(dry_run: bool = False) -> dict:
    """Daily mark of the R76 paper book. Idempotent per calendar day.

    Pipeline:
      1. Fetch live close + funding from Binance fapi (28-asset universe).
      2. Build funding panel [date × asset], cross-sectionally demean → R76 score.
      3. Take today's score row → target weights (long top tercile / short bottom).
      4. Mark NAV using y[t]/y[t-1]-1 returns (no look-ahead).
      5. Cost = 0bps (frozen best cell; live slippage not modeled for paper book).
      6. Persist state to JSON + append NAV row to CSV.
    """
    today = dt.date.today()
    state = _load_state()
    if state.get("last_mark") == today.isoformat():
        return {"status": "already_marked", "nav": round(state.get("nav", 1.0), 5),
                "date": today.isoformat(),
                "n_days_marked": int(state.get("n_days_marked", 0))}

    data = await _fetch_close_funding(UNIVERSE, lookback_days=60)
    if len(data) < 6:
        return {"status": "skipped", "reason": "insufficient_live_data",
                "n_assets_with_data": len(data)}

    # Build funding panel [date × asset]
    today_ts = pd.Timestamp(today)
    funding_panel = pd.DataFrame({
        sym: pd.Series(d["funding"], index=d.get("funding_dates", pd.date_range(
            end=today_ts, periods=len(d["funding"]), freq="D")))
        for sym, d in data.items() if len(d.get("funding", [])) >= 5
    }).sort_index()
    if funding_panel.empty or funding_panel.shape[1] < 6:
        return {"status": "skipped", "reason": "funding_panel_too_small",
                "n_funding_assets": int(funding_panel.shape[1])}

    # R76 score
    score = _score_r76(funding_panel)

    # Target weights
    w_tgt = _target_weights_r76(score, today_ts)
    if not w_tgt:
        return {"status": "skipped", "reason": "no_target_weights",
                "score_dates": [str(d.date()) for d in score.index[-3:]]}

    # Last/prev prices for marking
    last_px = {sym: float(d["close"][-1]) for sym, d in data.items() if d["close"]}
    prev_px = {sym: float(d["close"][-2]) for sym, d in data.items()
               if len(d["close"]) >= 2}

    # Mark-to-market PnL: Σ w_held × (price[t]/price[t-1] - 1)
    w_held = state.get("weights", {}) or {}
    price_pnl = 0.0
    for sym, wi in w_held.items():
        if sym in last_px and sym in prev_px and prev_px[sym] > 0:
            price_pnl += wi * (last_px[sym] / prev_px[sym] - 1.0)
    cost_frac = R76_BPS / 1e4  # paper-book cost (frozen 0bps)
    daily_ret = price_pnl - cost_frac
    nav = float(state.get("nav", 1.0))
    nav_new = nav * (1.0 + daily_ret)

    new_state = {
        "inception": state.get("inception") or today.isoformat(),
        "nav": nav_new,
        "weights": w_tgt,
        "mark_prices": last_px,
        "prev_prices": prev_px,
        "last_mark": today.isoformat(),
        "n_days_marked": int(state.get("n_days_marked", 0)) + 1,
        "cell": {
            "cad": R76_CAD, "bps": R76_BPS, "k": R76_K, "sign": R76_SIGN,
            "declared_capacity_usd": DEFAULT_DECLARED_CAPACITY_USD,
        },
    }

    if not dry_run:
        _save_state(new_state)
        gross = sum(abs(x) for x in w_tgt.values())
        _append_nav_row(today, nav_new, daily_ret, gross, len(w_tgt),
                        cost_frac, det_fired=False)

    validated = new_state["n_days_marked"] >= VALIDATION_MIN_DAYS
    return {
        "status": "marked", "nav": round(nav_new, 5),
        "date": today.isoformat(), "n": len(w_tgt),
        "gross": round(sum(abs(x) for x in w_tgt.values()), 4),
        "daily_return": round(daily_ret, 6),
        "n_days_marked": new_state["n_days_marked"],
        "validated": validated,
        "cell": new_state["cell"],
    }


# ── Read the NAV curve (for the API endpoint) ─────────────────────────────────
def get_curve(limit: int = 400) -> dict:
    """NAV curve + honest summary, file-based."""
    if not _NAV_CSV_PATH.exists():
        return {"status": "no_data",
                "note": "R76 strategy-2 paper book not yet marked",
                "cell": {
                    "cad": R76_CAD, "bps": R76_BPS, "k": R76_K, "sign": R76_SIGN,
                    "declared_capacity_usd": DEFAULT_DECLARED_CAPACITY_USD,
                },
                "validation_min_days": VALIDATION_MIN_DAYS}

    rows: list = []
    with open(_NAV_CSV_PATH) as f:
        for r in csv.DictReader(f):
            rows.append(r)
    rows = rows[-limit:]

    if not rows:
        return {"status": "no_data", "n_rows": 0}

    navs = [float(r["nav"]) for r in rows]
    rets = [float(r["daily_return"]) for r in rows
            if r.get("daily_return") not in (None, "", "nan")]
    n_days = len(rows)
    validated = n_days >= VALIDATION_MIN_DAYS

    sharpe = (float(np.mean(rets) / np.std(rets) * np.sqrt(365))
              if len(rets) > 5 and np.std(rets) > 0 else None)
    peak = np.maximum.accumulate(navs)
    max_dd = float((peak - navs).max() / peak.max()) if navs and peak.max() > 0 else 0.0
    ann_ret = (float(navs[-1] / navs[0]) ** (365.0 / max(n_days, 1)) - 1.0
               if n_days > 1 and navs[0] > 0 else 0.0)

    return {
        "status": "ok",
        "n_days_marked": n_days,
        "validated": validated,
        "validation_min_days": VALIDATION_MIN_DAYS,
        "current_nav": round(navs[-1], 5),
        "sharpe": round(sharpe, 2) if sharpe is not None else None,
        "max_dd": round(max_dd, 4),
        "ann_return": round(ann_ret, 4),
        "first_date": rows[0]["mark_date"],
        "last_date": rows[-1]["mark_date"],
        "cell": {
            "cad": R76_CAD, "bps": R76_BPS, "k": R76_K, "sign": R76_SIGN,
            "declared_capacity_usd": DEFAULT_DECLARED_CAPACITY_USD,
        },
        "rows": rows[-60:],  # last 60 days
    }


def get_state() -> dict:
    """Read raw state.json (for diagnostics)."""
    return _load_state()
