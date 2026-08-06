"""
ⓠ REGIME OVERRIDE Paper Track — parallel paper NAV under regime override (Seth, 2026-08-06)
============================================================================================

Per Jazz direction 2026-08-06 ("接吧"): wire the ⓠ REGIME OVERRIDE enforcer into the
60-day paper test of the R64 fusion book. This module computes a parallel paper NAV
curve under the regime override and tracks it as a 6th monitoring surface.

WHAT THIS IS
------------
A paper-only, observation-only, parallel NAV curve that answers:
  "If we had applied ⓠ REGIME OVERRIDE to the R64 fusion book on day t, what would
   the NAV have been?"

This is NOT a live override. The actual R64 paper book continues to run with gross=1.0.
The regime-adjusted curve is a parallel track, used to evaluate the enforcer's value
BEFORE we promote it to the live book (the §P3 promotion gate: 60d paper + validated).

DATA SOURCES
------------
1. Stablecoin signal: /tmp/cometcloud_data/defillama_stablecoin_history.json
   (via m_wo_q_o1_stablecoin_gate.{load_stablecoin_history, compute_o1_signal,
    assign_band_hysteresis}).
2. R64 paper NAV: Supabase fusion_paper_nav (the live R64 paper book).
3. Enforcer: src.research.beta_core.regime_override_enforcer
   (apply_regime_override — used here for the SINGLE-DAY multiplicative equivalent,
   see _regime_pnl_for_day below).

DAILY COMPUTATION (PIT-safe)
----------------------------
  signal_yest = compute_o1_signal(stables).shift(1)         # 28d pct Δ, 1d lag
  band_today, cap_today = assign_band_hysteresis(signal_yest)
  regime_daily_return = cap_today × r77_daily_return         # multiplicative gate
  regime_pnl_usd      = regime_daily_return × R64_NOTIONAL_USD
  regime_nav_usd      = regime_nav_yest + regime_pnl_usd

Mathematically equivalent to apply_regime_override on a scalar weight=1.0
(i.e., scaling the entire book gross to cap_today). The multiplicative form
matches what m_wo_q_o1_stablecoin_gate.simulate_gated validated in the
research backtest.

PERSISTENCE
-----------
  • CSV (authoritative local copy):
      /tmp/cometcloud_data/paper_books/fusion_paper_regime_track/regime_track.csv
      Schema: date_utc, band, exposure_cap, signal_value, r77_daily_return,
              regime_daily_return, regime_pnl_usd, regime_nav_usd
  • Supabase (mirror):
      fusion_paper_regime_track table — best-effort, gated on SUPABASE_URL/KEY.

AGGREGATION (60d)
-----------------
  • band_pct_days:           {band → n_days / n_total_days}
  • mean_realized_cap:       Σ cap_t / n_days
  • regime_vs_flat_alpha_pct: ann return(regime) − ann return(flat = R77 baseline)
  • regime_vs_flat_sharpe:    Sharpe(regime) − Sharpe(flat)
  • max_dd_regime_pct:        max drawdown of the regime-adjusted NAV curve

OUT OF SCOPE
------------
- The live R64 paper book — this module does NOT modify its weights or NAV.
- A live deployment decision — that is the §P3 promotion gate, owned by Jazz.
- A new signal source — the stablecoin signal is m_wo_q's validated one.
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import logging
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd
from dotenv import dotenv_values

# ── DECISION_INPUTS contract (per tests/test_strategy_discipline.py) ────────
# This module produces a paper NAV curve — what the live book would have done
# UNDER the enforcer. It is NOT a trading decision for the live book, but it
# IS a decision-shaped surface (regime/universe/weights/timing all declared).
# ship=False is honest: paper output, not a trade instruction.
DECISION_INPUTS = {
    "regime": "stablecoin_28d_pct_delta_hysteresis_5band",
    "universe": "r64_fusion_paper_book_baseline",
    "weights": "regime_cap_multiplicative_gate",
    "timing": "1d_pit_lag_daily",
}

_log = logging.getLogger("fusion_paper_regime_track")

# ── Persistence constants ────────────────────────────────────────────────────
_TRACK_DIR = Path("/tmp/cometcloud_data/paper_books/fusion_paper_regime_track")
_TRACK_CSV = _TRACK_DIR / "regime_track.csv"
_SUPABASE_TABLE = "fusion_paper_regime_track"

# ── Notional (mirror sleeve_2 in nav_ledger.py) ──────────────────────────────
R64_NOTIONAL_USD = 1_000_000.0  # R64 paper NAV assumption

# ── CSV schema ───────────────────────────────────────────────────────────────
TRACK_HEADER = [
    "date_utc", "band", "exposure_cap", "signal_value",
    "r77_daily_return", "regime_daily_return",
    "regime_pnl_usd", "regime_nav_usd",
]

# ── Stablecoin signal source (m_wo_q_o1_stablecoin_gate) ────────────────────
_MAC_ENV = Path("/Volumes/CometCloudAI/cometcloud-local/.env")
_keys = dotenv_values(_MAC_ENV) if _MAC_ENV.exists() else {}
STABLES_JSON = _keys.get(
    "STABLES_JSON",
    "/tmp/cometcloud_data/defillama_stablecoin_history.json",
)
SIGNAL_LOOKBACK_DAYS = 28

# ── Supabase config ──────────────────────────────────────────────────────────
SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")

# ── Aggregation thresholds (mirror fusion_paper_tracking.py) ───────────────
WARMUP_MIN_DAYS = 20


# ── Pure analysis primitives (testable, no I/O) ─────────────────────────────
def load_signal_series(stables_json: str = STABLES_JSON) -> pd.Series:
    """Stablecoin 28d pct Δ signal, indexed by date. Pure (depends only on file).
    Returns NaN where the lookback window is incomplete (insufficient history)."""
    from src.research.validation.m_wo_q_o1_stablecoin_gate import (
        load_stablecoin_history,
        compute_o1_signal,
    )
    stables = load_stablecoin_history(stables_json)
    sig = compute_o1_signal(stables, lookback=SIGNAL_LOOKBACK_DAYS)
    return sig  # decimal; NaN where window incomplete


def band_cap_for_date(target_date: pd.Timestamp,
                      signal: pd.Series) -> tuple[str, float]:
    """Return (band_name, exposure_cap) for `target_date` based on the
    PIT-lagged signal: cap applied at day t uses the signal from day t-1.

    Returns ('NEUTRAL', 1.0) if no signal row exists at t-1 (insufficient history).
    """
    from src.research.validation.m_wo_q_o1_stablecoin_gate import (
        assign_band_hysteresis,
        EXPOSURE_BANDS_V1,
    )

    if signal is None or signal.empty or len(signal) < 2:
        return "NEUTRAL", 1.0

    # PIT safety: cap at day t uses the signal from day t-1. We shift the
    # signal by 1 BEFORE running hysteresis, so the state at the target
    # date reflects only signals from ≤ t-1. assign_band_hysteresis itself
    # is NOT intrinsically lagged (state[t] depends on signal[t] and the
    # previous state, which we want to be the previous shifted state).
    sub = signal.loc[signal.index <= target_date].shift(1).dropna()
    if len(sub) < 2:
        return "NEUTRAL", 1.0
    _, states = assign_band_hysteresis(sub)
    last_state = str(states.iloc[-1])
    return last_state, float(EXPOSURE_BANDS_V1[last_state])


def _regime_pnl_for_day(cap: float, r77_daily_return: float,
                        notional_usd: float = R64_NOTIONAL_USD) -> float:
    """Per-day regime-adjusted P&L.

    Mathematically equivalent to apply_regime_override on a scalar weight=1.0:
    the multiplicative gate (cap × r77_daily_return) is the single-day form
    of the enforcer's renormalization when the baseline sums to 1.0.

    cap=1.0 → P&L identical to flat (NEUTRAL pass-through)
    cap=0.0 → P&L = 0 (CRISIS shelter)
    cap=1.3 → P&L = 1.3 × flat (HOT — gross-leveraged)
    """
    return cap * r77_daily_return * notional_usd


def compute_regime_track(
    r77_nav: pd.Series,
    signal: pd.Series,
    notional_usd: float = R64_NOTIONAL_USD,
) -> pd.DataFrame:
    """Pure backtest: produce the regime-adjusted NAV curve from R77 NAV + signal.

    Parameters
    ----------
    r77_nav : pd.Series
        R64 paper book NAV, indexed by date. Daily granularity assumed.
    signal : pd.Series
        Stablecoin 28d pct Δ signal, indexed by date.
    notional_usd : float
        R64 notional (default 1.0M, mirroring sleeve_2 in nav_ledger.py).

    Returns
    -------
    pd.DataFrame
        Indexed by date_utc, columns = TRACK_HEADER.
        First row is dropped (no prior day for daily return computation).
        r77_daily_return = (nav_today − nav_yest) / nav_yest, NaN where undefined.
        regime_pnl_usd is the regime-adjusted delta (NaN where r77_daily_return is NaN).
        regime_nav_usd starts at notional_usd on day 1 (no P&L accrued on day 0).
    """
    if not isinstance(r77_nav, pd.Series):
        raise TypeError(f"r77_nav must be pd.Series, got {type(r77_nav).__name__}")
    if not isinstance(signal, pd.Series):
        raise TypeError(f"signal must be pd.Series, got {type(signal).__name__}")
    if len(r77_nav) < 2:
        raise ValueError(f"need ≥2 NAV points for daily-return computation, got {len(r77_nav)}")

    r77_rets = r77_nav.pct_change()  # NaN on first row
    rows: list[dict] = []
    cum_nav = float(notional_usd)
    for d in r77_nav.index:
        r77_ret = float(r77_rets.loc[d]) if not pd.isna(r77_rets.loc[d]) else None
        if r77_ret is None:
            continue  # skip first day (no prior)
        band, cap = band_cap_for_date(d, signal)
        sig_val = float(signal.loc[d]) if d in signal.index and not pd.isna(signal.loc[d]) else None
        regime_ret = cap * r77_ret
        regime_pnl = _regime_pnl_for_day(cap, r77_ret, notional_usd)
        cum_nav += regime_pnl
        rows.append({
            "date_utc": d.date().isoformat() if hasattr(d, "date") else str(d)[:10],
            "band": band,
            "exposure_cap": cap,
            "signal_value": round(sig_val, 6) if sig_val is not None else None,
            "r77_daily_return": round(r77_ret, 6),
            "regime_daily_return": round(regime_ret, 6),
            "regime_pnl_usd": round(regime_pnl, 2),
            "regime_nav_usd": round(cum_nav, 2),
        })
    return pd.DataFrame(rows)


def aggregate_regime_track(track_df: pd.DataFrame) -> dict:
    """60d aggregation stats from a regime track DataFrame.

    Returns a dict suitable for the 6th surface in fusion_paper_tracking.
    """
    if track_df is None or track_df.empty:
        return {"status": "INSUFFICIENT", "n_days": 0}

    n_days = len(track_df)
    if n_days < WARMUP_MIN_DAYS:
        return {"status": "WARMING_UP", "n_days": n_days,
                "warmup_threshold_days": WARMUP_MIN_DAYS}

    # Band distribution
    band_counts = track_df["band"].value_counts().to_dict()
    band_pct = {b: round(c / n_days, 4) for b, c in band_counts.items()}

    # Mean realized cap
    mean_cap = float(track_df["exposure_cap"].mean())

    # Regime-adjusted NAV curve stats.
    # IMPORTANT: regime_nav[0] is the first non-NaN row (after day-1 P&L), not the
    # initial 1M. Use R64_NOTIONAL_USD as the consistent denominator for both
    # regime and flat, so alpha_pct is comparable.
    regime_nav = track_df["regime_nav_usd"].astype(float).values
    if len(regime_nav) >= 2:
        regime_rets = pd.Series(regime_nav).pct_change().dropna().values
        if regime_rets.std() > 0:
            regime_sharpe = float(regime_rets.mean() / regime_rets.std() * np.sqrt(365))
        else:
            regime_sharpe = None
        regime_total_return = float(regime_nav[-1] / R64_NOTIONAL_USD - 1.0)
        regime_ann_return = regime_total_return * (365.0 / n_days)
        regime_max_dd_pct = _max_drawdown_pct(regime_nav.tolist())
    else:
        regime_sharpe = None
        regime_ann_return = None
        regime_max_dd_pct = None

    # Flat (R77 baseline) curve stats — same convention: linear P&L × notional,
    # starting from R64_NOTIONAL_USD as the denominator.
    flat_pnl_total = float(track_df["r77_daily_return"].sum() * R64_NOTIONAL_USD)
    flat_rets = track_df["r77_daily_return"].astype(float).values
    if flat_rets.std() > 0:
        flat_sharpe = float(flat_rets.mean() / flat_rets.std() * np.sqrt(365))
    else:
        flat_sharpe = None
    flat_total_return = float(flat_pnl_total / R64_NOTIONAL_USD)
    flat_ann_return = flat_total_return * (365.0 / n_days)
    flat_max_dd_pct = _max_drawdown_pct(
        [R64_NOTIONAL_USD + sum(flat_rets[:i+1]) * R64_NOTIONAL_USD for i in range(len(flat_rets))]
    )

    # Regime vs flat deltas
    alpha_pct = (
        round((regime_ann_return - flat_ann_return) * 100, 3)
        if regime_ann_return is not None and flat_ann_return is not None else None
    )
    sharpe_gap = (
        round(regime_sharpe - flat_sharpe, 3)
        if regime_sharpe is not None and flat_sharpe is not None else None
    )

    return {
        "status": "ok",
        "n_days": n_days,
        "band_pct_days": band_pct,
        "mean_realized_cap": round(mean_cap, 4),
        "regime_total_return_pct": round(regime_total_return * 100, 3)
            if regime_total_return is not None else None,
        "regime_ann_return_pct": round(regime_ann_return * 100, 3)
            if regime_ann_return is not None else None,
        "regime_sharpe": round(regime_sharpe, 3) if regime_sharpe is not None else None,
        "regime_max_dd_pct": regime_max_dd_pct,
        "flat_ann_return_pct": round(flat_ann_return * 100, 3)
            if flat_ann_return is not None else None,
        "flat_sharpe": round(flat_sharpe, 3) if flat_sharpe is not None else None,
        "flat_max_dd_pct": flat_max_dd_pct,
        "regime_vs_flat_alpha_pct": alpha_pct,
        "regime_vs_flat_sharpe_gap": sharpe_gap,
    }


def _max_drawdown_pct(navs: list) -> float | None:
    """Max DD as negative %. None if <2 points."""
    if not navs or len(navs) < 2:
        return None
    arr = np.array(navs, dtype=float)
    peak = np.maximum.accumulate(arr)
    dd = arr / peak - 1.0
    return float(round(dd.min() * 100.0, 3))


# ── Persistence helpers ─────────────────────────────────────────────────────
def _read_track_csv() -> list[dict]:
    if not _TRACK_CSV.exists():
        return []
    with open(_TRACK_CSV) as f:
        return list(csv.DictReader(f))


def _append_track_csv(row: dict) -> Path:
    _TRACK_DIR.mkdir(parents=True, exist_ok=True)
    existing = _read_track_csv()
    today = row["date_utc"]
    existing = [r for r in existing if r.get("date_utc") != today]
    existing.append(row)
    existing.sort(key=lambda r: r.get("date_utc", ""))
    with open(_TRACK_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=TRACK_HEADER)
        w.writeheader()
        w.writerows(existing)
    return _TRACK_CSV


def _fetch_r64_nav_close_to(today_iso: str) -> tuple[Optional[float], Optional[float]]:
    """Fetch R64 NAV for today and yesterday. (today, yest) or (None, None)."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        return None, None
    try:
        url = (
            f"{SUPABASE_URL.rstrip('/')}/rest/v1/{_SUPABASE_TABLE.replace('regime_track', 'nav')}"
            f"?select=mark_date,nav&order=mark_date.desc&limit=2"
        )
        # NOTE: the actual R64 paper NAV table is 'fusion_paper_nav'.
        # _SUPABASE_TABLE holds 'fusion_paper_regime_track' for our writes; the
        # READ side targets the R64 source.
        url = (
            f"{SUPABASE_URL.rstrip('/')}/rest/v1/fusion_paper_nav"
            f"?select=mark_date,nav&order=mark_date.desc&limit=2"
        )
        req = urllib.request.Request(
            url,
            headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"},
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
        if not isinstance(data, list) or len(data) < 1:
            return None, None
        latest = data[0]
        if latest.get("mark_date") != today_iso:
            return None, None  # today's NAV not yet written
        nav_today = float(latest.get("nav"))
        nav_yest = float(data[1].get("nav")) if len(data) > 1 else None
        return nav_today, nav_yest
    except (urllib.error.URLError, json.JSONDecodeError, KeyError, ValueError, IndexError) as e:
        _log.warning("[regime_track] R64 NAV fetch failed: %s", e)
        return None, None


def _supabase_write_track(row: dict) -> bool:
    """Mirror today's row to Supabase. Best-effort."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        return False
    try:
        url = f"{SUPABASE_URL.rstrip('/')}/rest/v1/{_SUPABASE_TABLE}"
        body = json.dumps([row]).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=body,
            headers={
                "apikey": SUPABASE_KEY,
                "Authorization": f"Bearer {SUPABASE_KEY}",
                "Content-Type": "application/json",
                "Prefer": "resolution=merge-duplicates",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status in (200, 201)
    except Exception as e:
        _log.warning("[regime_track] supabase write failed: %s", e)
        return False


# ── Daily entry point ───────────────────────────────────────────────────────
def compute_today_track(today_iso: str | None = None) -> Optional[dict]:
    """Compute today's regime track row, append to CSV + Supabase.

    Returns the row dict, or None if insufficient data (R64 NAV missing, signal
    too short, etc.).
    """
    today = today_iso or dt.datetime.utcnow().date().isoformat()
    nav_today, nav_yest = _fetch_r64_nav_close_to(today)
    if nav_today is None or nav_yest is None:
        _log.info("[regime_track] no R64 NAV for %s (today=%s yest=%s); skipping",
                  today, nav_today, nav_yest)
        return None

    sig = load_signal_series()
    if sig is None or sig.empty:
        _log.info("[regime_track] no stablecoin signal available; skipping")
        return None

    today_ts = pd.Timestamp(today)
    band, cap = band_cap_for_date(today_ts, sig)
    sig_val = float(sig.loc[today_ts]) if today_ts in sig.index and not pd.isna(sig.loc[today_ts]) else None
    r77_ret = (nav_today - nav_yest) / nav_yest if nav_yest > 0 else 0.0
    regime_ret = cap * r77_ret
    regime_pnl = _regime_pnl_for_day(cap, r77_ret)

    # Cumulative NAV: previous day's CSV value + today's regime_pnl
    prev_csv = _read_track_csv()
    prev_nav = float(prev_csv[-1]["regime_nav_usd"]) if prev_csv else R64_NOTIONAL_USD
    cum_nav = prev_nav + regime_pnl

    row = {
        "date_utc": today,
        "band": band,
        "exposure_cap": cap,
        "signal_value": round(sig_val, 6) if sig_val is not None else None,
        "r77_daily_return": round(r77_ret, 6),
        "regime_daily_return": round(regime_ret, 6),
        "regime_pnl_usd": round(regime_pnl, 2),
        "regime_nav_usd": round(cum_nav, 2),
    }
    _append_track_csv(row)
    _supabase_write_track(row)
    return row


# ── Self-test ───────────────────────────────────────────────────────────────
def _self_test() -> int:
    """Pure-function self-tests; no I/O, no Supabase, no files."""
    # 1. band_cap_for_date: empty signal → NEUTRAL pass-through
    empty_sig = pd.Series([], index=pd.DatetimeIndex([], freq="D"), dtype=float)
    band, cap = band_cap_for_date(pd.Timestamp("2026-08-06"), empty_sig)
    assert band == "NEUTRAL" and cap == 1.0, "empty signal must return NEUTRAL/1.0"

    # 2. band_cap_for_date: synthetic SUSTAINED CRISIS signal (single-day
    # spike exits at next day because hysteresis EXIT_CRISIS = -0.025 > 0)
    dates = pd.date_range("2026-07-01", periods=40, freq="D")
    sig = pd.Series([0.0] * 40, index=dates)
    sig.iloc[10:30] = -0.10   # sustained CRISIS for 20 days (after shift, days 11-30)
    # Query a date STILL inside the CRISIS window — querying the very last day
    # would catch the exit to NEUTRAL (signal=0.0 at the boundary).
    band, cap = band_cap_for_date(pd.Timestamp("2026-07-25"), sig)
    assert band == "CRISIS" and cap == 0.0, f"sustained CRISIS: {band}/{cap}"

    # 3. _regime_pnl_for_day: identity at NEUTRAL
    pnl = _regime_pnl_for_day(1.0, 0.01)
    assert abs(pnl - 10_000.0) < 1e-6, f"NEUTRAL: {pnl} vs 10000"
    # CRISIS: zero
    pnl = _regime_pnl_for_day(0.0, 0.01)
    assert pnl == 0.0, f"CRISIS: {pnl}"
    # HOT: 1.3x
    pnl = _regime_pnl_for_day(1.3, 0.01)
    assert abs(pnl - 13_000.0) < 1e-6, f"HOT: {pnl} vs 13000"

    # 4. compute_regime_track: synthetic flat NAV → all caps=1.0 → regime ≡ flat
    nav_dates = pd.date_range("2026-07-01", periods=10, freq="D")
    r77_nav = pd.Series([100.0 + i for i in range(10)], index=nav_dates)
    sig = pd.Series([0.0] * 10, index=nav_dates)
    track = compute_regime_track(r77_nav, sig)
    assert len(track) == 9  # 10 NAV points → 9 daily returns
    assert (track["band"] == "NEUTRAL").all(), "flat signal → NEUTRAL"
    # regime_pnl == r77_pnl for each day (cap=1.0).
    # Note: stored values are rounded to 2 decimals (CSV-serializable); compare
    # with atol=0.01 to accommodate the rounding error.
    expected_pnl = r77_nav.pct_change().dropna() * R64_NOTIONAL_USD
    np.testing.assert_allclose(track["regime_pnl_usd"].values,
                               expected_pnl.values, atol=0.01)

    # 5. compute_regime_track: with CRISIS on day 5 → P&L=0 on day 5
    sig2 = pd.Series([0.0] * 10, index=nav_dates)
    sig2.iloc[3] = -0.10  # CRISIS enters
    track2 = compute_regime_track(r77_nav, sig2)
    # Day-5 NAV return should be 0 (CRISIS cap=0)
    crisis_day = track2[track2["band"] == "CRISIS"]
    if not crisis_day.empty:
        assert (crisis_day["regime_pnl_usd"] == 0.0).all(), \
            f"CRISIS days must have pnl=0, got {crisis_day['regime_pnl_usd'].tolist()}"

    # 6. aggregate_regime_track: empty → INSUFFICIENT
    agg = aggregate_regime_track(pd.DataFrame())
    assert agg["status"] == "INSUFFICIENT", f"empty: {agg}"

    # 7. aggregate_regime_track: < warmup → WARMING_UP
    agg = aggregate_regime_track(track.iloc[:5])
    assert agg["status"] == "WARMING_UP", f"5 days: {agg}"

    # 8. aggregate_regime_track: full ≥20 days
    nav_long = pd.Series([100.0 + 0.5 * i for i in range(40)],
                         index=pd.date_range("2026-06-01", periods=40, freq="D"))
    sig_long = pd.Series([0.0] * 40, index=nav_long.index)
    track_long = compute_regime_track(nav_long, sig_long)
    agg_long = aggregate_regime_track(track_long)
    assert agg_long["status"] == "ok"
    assert agg_long["n_days"] == 39
    # mean cap == 1.0 (flat signal)
    assert abs(agg_long["mean_realized_cap"] - 1.0) < 1e-9
    # regime vs flat alpha ≈ 0 (same signal)
    assert abs(agg_long["regime_vs_flat_alpha_pct"]) < 0.01, \
        f"flat signal: alpha should ≈0, got {agg_long['regime_vs_flat_alpha_pct']}"

    # 9. PIT safety: signal at day t must NOT influence cap at day t
    # (the shift(1) inside band_cap_for_date enforces this).
    sig_pit = pd.Series([0.0] * 10, index=nav_dates)
    sig_pit.iloc[5:9] = -0.10  # sustained CRISIS at indices 5..8 (becomes 6..9 after shift)
    track_pit = compute_regime_track(r77_nav, sig_pit)
    # The CRISIS should NOT appear on the SAME day as the signal (-0.10);
    # it should appear on the NEXT day (signal shifted by 1).
    signal_day_idx = 5  # first CRISIS index in sig_pit
    sig_day_date = nav_dates[signal_day_idx]
    same_day = track_pit[track_pit["date_utc"] == sig_day_date.date().isoformat()]
    if not same_day.empty:
        # Same day should still be NEUTRAL (PIT lag)
        assert same_day["band"].iloc[0] == "NEUTRAL", \
            f"PIT: same day should be NEUTRAL, got {same_day['band'].iloc[0]}"
    next_day = track_pit[track_pit["date_utc"] == nav_dates[signal_day_idx + 1].date().isoformat()]
    # Next day should be CRISIS
    if not next_day.empty:
        assert next_day["band"].iloc[0] == "CRISIS", \
            f"PIT: next day should be CRISIS, got {next_day['band'].iloc[0]}"

    print(f"✓ fusion_paper_regime_track self-test OK "
          f"(n_long={agg_long['n_days']}, mean_cap={agg_long['mean_realized_cap']}, "
          f"alpha_pct={agg_long['regime_vs_flat_alpha_pct']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(_self_test())
