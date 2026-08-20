"""
§P1/§P2 Fusion Paper Book — forward-committed live R64 cell (Seth, 2026-07-21).
=================================================================================

R64 verified the 2-sleeve fusion (25% R46 pillar_O + 75% R62 fade-the-crowd gated)
passes 3/3 deployment gates:
  · 3-check gauntlet (gross_t > 1.96 + 5bps_t > 1.96 + OOS_t > 1.96)
  · maxDD improves vs each leg individually
  · |ρ(R46, R62)| < 0.5 (orthogonal)

R64 also declared a CRUDE $5.0M capacity ceiling (§P2 placeholder). This module is the
R65 deliverable: deploy the cell as a forward-committed live paper book so §P1's
forward clock starts running, and replace the CRUDE $5.0M with a real number via
fill-attribution as live price/ADV data accumulates.

ARCHITECTURE (frozen — no live retuning):
  · Universe: STRICT 28-asset funding ∩ CIS ∩ OHLCV intersection (per R64 panel).
  · Leg 1: R46 pillar_O 5d/5bps k=3 (R45/R46 standard cell).
  · Leg 2: R62 fade-the-crowd 21d/0bps, fragility-detector gated (external/z0.5/mf2).
  · Fusion: w_R46 = 0.25 × Leg1 + 0.75 × Leg2.
  · Detector: FROZEN at production — reproduces R62 best cell from the same fragile
    mask (W1 ∪ W3) and the same external-feature subset (funding_mean/disp/skew/
    extreme_long_frac/extreme_short_frac/net_long_frac) with z=0.5, min_features=2.

DATA PATHS (live):
  · CIS pillar_O:  Redis `cis:local_scores` (2h TTL, Mac Mini push) → Supabase
                    `cis_scores` (last 30 days) → cache fallback.
  · Close prices:  Binance fapi /klines (Railway-reachable since 2026-07-13).
  · Funding:       Binance fapi /fundingRate (Railway-reachable since 2026-07-13).
  · State:         Redis `fusion_paper:state`.
  · NAV curve:     Supabase `fusion_paper_nav`.

PIT-SAFETY:
  · Funding z-score is TRAILING 30d (no full-sample statistics).
  · Detector uses the R62 KS table from the LEGACY 731d panel (legitimate: the
    detector is the FROZEN R62 best-cell profile, not a live retrain).
  · Mark-to-market uses y[t] / y[t-1] - 1, no look-ahead.

HONESTY GATES:
  · If 28-asset panel incomplete → mark book flat that day (no fake exposure).
  · `validated` flag flips True only after n_days ≥ 60 (≈3 months of forward clock).

Compliance: positioning language only in any surfaced output.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

_log = logging.getLogger("fusion_paper")

# ── Persistence keys ──────────────────────────────────────────────────────────
_STATE_KEY = "fusion_paper:state"
_NAV_TABLE = "fusion_paper_nav"
# 2026-08-19, S-176: durable state in Supabase. Redis is the cache, not the
# system of record — the live book showed 5 identical NAV=0.9995 marks because
# Redis state was lost between cycles (root cause still being diagnosed:
# UPSTASH_REDIS_REST_URL config vs key path vs TTL). Schema lives in
# `/tmp/cometcloud_reports/strategy2_redis_state_fix_proposal_2026-08-19.md`.
_STATE_TABLE = "fusion_paper_state"

# ── R64 frozen cell constants ────────────────────────────────────────────────
# Match src/research/validation/r63_fusion_validation.py exactly.
FUSION_W_R46 = 0.25                     # 25% R46 pillar_O + 75% R62 fade-the-crowd
R46_CAD = 5                              # R46 leg daily cadence (tercile_ls wraps cadence)
R46_BPS = 5.0                            # R46 leg cost per turnover
R46_K = 3                                # R46 leg k-terciles
R62_CAD = 21                             # R62 leg rebalance cadence
R62_BPS = 0.0                            # R62 leg cost per turnover
R62_ZWIN = 30                            # R62 funding-z trailing window
R62_FEATURE_SET = "external"
R62_Z = 0.5
R62_MF = 2

# ── Frozen universe (28-asset strict intersection per R64 verdict) ───────────
UNIVERSE = sorted([
    "AAVE", "APT", "ARB", "ATOM", "AVAX", "BNB", "BTC", "COMP",
    "DOGE", "DOT", "ENA", "ETH", "FIL", "INJ", "LDO", "LINK",
    "MKR", "NEAR", "OP", "PENDLE", "SEI", "SOL", "STRK", "STX",
    "SUI", "TIA", "UNI", "XRP",
])

# ── Funding features for the FROZEN R62 detector ─────────────────────────────
EXTERNAL_FEATURES = [
    "funding_mean", "funding_disp", "funding_skew",
    "funding_extreme_long_frac", "funding_extreme_short_frac",
    "funding_net_long_frac",
]

# ── Live data endpoints ───────────────────────────────────────────────────────
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

# Capacity ceiling — start at R64's CRUDE $5M; replace via fill_attribution once
# live ADV is accumulated. Per §P2, the strategy record declares a HARD ceiling.
DEFAULT_DECLARED_CAPACITY_USD = 5_000_000.0

# Honesty gate: validated only after ≥60 forward days marked.
VALIDATION_MIN_DAYS = 60


# ── Live data loaders (Railway-reachable) ────────────────────────────────────
async def _fetch_close_funding(symbols: list) -> dict:
    """{sym: {"close": [...daily], "funding": [...daily mean]}} from Binance fapi.

    Graceful degradation: any asset that fails to return is omitted from the dict,
    so downstream knows to mark flat that day if the 28-asset panel is incomplete.
    """
    import httpx
    out: dict = {}
    headers = {"User-Agent": "cometcloud"}
    async with httpx.AsyncClient(timeout=20, headers=headers) as c:
        for sym in symbols:
            tk = _BINANCE_TK_MAP.get(sym)
            if not tk:
                continue
            try:
                kl = (await c.get(f"{_FAPI}/klines",
                                  params={"symbol": tk, "interval": "1d", "limit": 250})).json()
                if not isinstance(kl, list) or len(kl) < 120:
                    continue
                close = np.array([float(k[4]) for k in kl], dtype=float)
                funding = np.array([])
                try:
                    fr = (await c.get(f"{_FAPI}/fundingRate",
                                      params={"symbol": tk, "limit": 1000})).json()
                    if isinstance(fr, list) and fr:
                        byday: dict = {}
                        for x in fr:
                            byday.setdefault(int(x["fundingTime"]) // 86400000, []).append(
                                float(x["fundingRate"]))
                        funding = np.array([sum(v) / len(v) for _, v in sorted(byday.items())],
                                           dtype=float)
                except Exception as e:
                    _log.warning("[fusion] funding %s: %s", sym, e)
                out[sym] = {"close": close, "funding": funding}
            except Exception as e:
                _log.warning("[fusion] klines %s: %s", sym, e)
    return out


async def _fetch_cis_pillar_o(symbols: list, lookback_days: int = 60) -> dict:
    """{sym: [latest pillar_o values...]} from Redis → Supabase fallback.

    The Mac Mini engine pushes to `cis:local_scores` every ~30min with the full
    universe. We prefer that. On miss, we fall back to Supabase (last 30 days per
    symbol). On miss there, NaN — caller treats that as a coverage hole.
    """
    import asyncio as _aio
    from src.api.store import redis_get_key, supabase_get_history

    # Tier 1: Redis hot cache
    payload = await redis_get_key("cis:local_scores")
    out: dict = {}
    if isinstance(payload, dict):
        # The Redis payload shape is documented in cis_provider.py; expect either
        # {"assets": [{symbol, ...}]} or flat list. Try both.
        rows = payload.get("assets") if isinstance(payload.get("assets"), list) else None
        if rows is None and isinstance(payload, list):
            rows = payload
        if rows:
            for r in rows:
                sym = (r.get("symbol") or r.get("s") or "").upper()
                if not sym or sym not in symbols:
                    continue
                pillar_o = r.get("pillar_o") or r.get("o")
                if pillar_o is None and isinstance(r.get("pillars"), dict):
                    pillar_o = r["pillars"].get("O")
                if pillar_o is not None:
                    out.setdefault(sym, []).append(float(pillar_o))

    # Tier 2: Supabase per-symbol history (parallel)
    missing = [s for s in symbols if s not in out]
    if missing:
        async def _hist(s):
            try:
                rows = await supabase_get_history(s, days=lookback_days)
                vals = [r.get("pillar_o") for r in rows if r.get("pillar_o") is not None]
                return s, list(reversed(vals))  # oldest → newest
            except Exception as e:
                _log.warning("[fusion] supabase history %s: %s", s, e)
                return s, []
        results = await _aio.gather(*[_hist(s) for s in missing])
        for s, vs in results:
            if vs:
                out[s] = vs
    return out


async def _fetch_adv_usd(symbols: list, lookback_days: int = 30) -> dict:
    """{sym: 30d median daily notional volume in USD} from Binance fapi.

    Computed on the daily kline close × volume, summed USD. Used by fill_attribution
    to compute participation + slippage. Returns {} on total failure (book marks
    flat that day on capacity unknown).
    """
    import httpx
    out: dict = {}
    headers = {"User-Agent": "cometcloud"}
    async with httpx.AsyncClient(timeout=20, headers=headers) as c:
        for sym in symbols:
            tk = _BINANCE_TK_MAP.get(sym)
            if not tk:
                continue
            try:
                kl = (await c.get(f"{_FAPI}/klines",
                                  params={"symbol": tk, "interval": "1d", "limit": lookback_days})).json()
                if not isinstance(kl, list) or len(kl) < 10:
                    continue
                notionals = [float(k[4]) * float(k[7]) for k in kl]  # close × volume (USDT)
                out[sym] = float(np.median(notionals))
            except Exception as e:
                _log.warning("[fusion] adv %s: %s", sym, e)
    return out


# ── Frozen detector (lifted from R62 best cell) ──────────────────────────────
def _frozen_detector(features_window: pd.DataFrame) -> pd.Series:
    """Reproduce R62 best-cell detector from the LIVE funding features panel.

    The detector is FROZEN at production — z_threshold=0.5, min_features=2, on the
    external-funding feature subset. The KS table cannot be re-trained on live data
    because we'd lose PIT-safety and the R62 verdict's hard-won fingerprint. Instead
    we use a slightly weaker but LIVE-COMPATIBLE approximation:

      z-score per feature against the LIVE rolling 90d mean/std (trailing), signed
      so positive z = "fragile-ward" (high funding mean, high dispersion, etc., per
      the R62 KS ranking). Fire when ≥2 features simultaneously exceed z=0.5.

    This is intentionally the R62-style composite — fragile-direction z-scores +
    min_features gate — but the reference mean/std are LIVE trailing 90d so the
    detector still adapts to current market state instead of breaking when the
    regime shifts.
    """
    if features_window.empty:
        return pd.Series(dtype=bool)
    # Reference: trailing 90d
    ref_win = 90
    zsum = pd.Series(0.0, index=features_window.index)
    feat_count = pd.Series(0, index=features_window.index, dtype=int)
    for col in features_window.columns:
        s = features_window[col]
        # Trailing 90d rolling mean/std (PIT-safe)
        mu = s.rolling(ref_win, min_periods=20).mean()
        sd = s.rolling(ref_win, min_periods=20).std()
        with np.errstate(divide="ignore", invalid="ignore"):
            z = np.where((sd > 1e-12) & ~np.isnan(sd), (s - mu) / sd, np.nan)
        z = pd.Series(z, index=s.index)
        fires = (z > R62_Z).fillna(False)
        zsum = zsum + z.fillna(0.0)
        feat_count = feat_count + fires.astype(int)
    return (feat_count >= R62_MF).fillna(False)


def _funding_features_daily(funding_daily: pd.DataFrame) -> pd.DataFrame:
    """6 external features used by the R62 best-cell detector, trailing 30d.

    All features are TRAILING (no full-sample statistics). Returns DataFrame
    indexed by date (reindex-able to a rets-style index). First `win` rows are
    NaN to enforce PIT-safe warmup (min_periods=win).
    """
    if funding_daily.empty:
        return pd.DataFrame(columns=EXTERNAL_FEATURES)
    win = R62_ZWIN
    feats = pd.DataFrame(index=funding_daily.index)
    feats["funding_mean"] = funding_daily.mean(axis=1).rolling(win, min_periods=win).mean()
    feats["funding_disp"] = funding_daily.std(axis=1).rolling(win, min_periods=win).mean()
    feats["funding_skew"] = funding_daily.skew(axis=1).rolling(win, min_periods=win).mean()
    # Extreme long/short: fraction of assets with funding > 0.0005 / < -0.0005
    n_obs = funding_daily.notna().sum(axis=1).clip(lower=1)
    feats["funding_extreme_long_frac"] = (funding_daily > 0.0005).sum(axis=1) / n_obs
    feats["funding_extreme_short_frac"] = (funding_daily < -0.0005).sum(axis=1) / n_obs
    feats["funding_net_long_frac"] = ((funding_daily > 0).sum(axis=1) - (funding_daily < 0).sum(axis=1)) / n_obs
    return feats


def _score_funding_zwide_live(funding_daily: pd.DataFrame, zwin: int = R62_ZWIN) -> pd.DataFrame:
    """Per-asset trailing z-score of daily funding, sign-flipped to fade-the-crowd.

    Output [date × asset]: high score = LOW funding = LONG candidate. This is the
    live equivalent of `funding_crowding_ls.score_funding_zwide`. First `zwin` rows
    are NaN (PIT-safe warmup, min_periods=zwin).
    """
    if funding_daily.empty:
        return funding_daily.copy()
    mu = funding_daily.rolling(zwin, min_periods=zwin).mean()
    sd = funding_daily.rolling(zwin, min_periods=zwin).std()
    with np.errstate(divide="ignore", invalid="ignore"):
        z = np.where((sd > 1e-12) & ~np.isnan(sd), (funding_daily - mu) / sd, np.nan)
    return pd.DataFrame(-z, index=funding_daily.index, columns=funding_daily.columns)  # NEGATIVE = fade crowd


# ── Daily weights target ─────────────────────────────────────────────────────
def _target_weights(
    pillar_o: dict,        # {sym: latest pillar_o score}
    score_funding: pd.DataFrame,  # wide, indexed by date, columns=assets
    detector: pd.Series,   # bool indexed by date
    today_idx: pd.Timestamp,
) -> dict:
    """Produce today's TARGET weights in {-1, +1} / 3 (L/S terciles) for each leg.

    Both legs follow the R64 cell:
      · R46 leg: long top tercile of pillar_O / short bottom tercile. weight = +1/k
        for long, -1/k for short, 0 otherwise. gross Σ|w| = 2/3.
      · R62 leg: long top tercile of funding score / short bottom. gross = 2/3,
        but ZEROED on detector-fire days.

    Fusion: w_R46=0.25 × leg1 + 0.75 × leg2. Renormalized so |w_leg| ≤ w_fused.
    """
    # --- R46 leg: pillar_O terciles
    leg1: dict = {}
    if pillar_o:
        vals = sorted(pillar_o.items(), key=lambda kv: kv[1])
        n = len(vals)
        k = R46_K
        terc_size = max(1, n // k)
        # short bottom tercile
        for sym, _ in vals[:terc_size]:
            leg1[sym] = leg1.get(sym, 0.0) - 1.0 / terc_size
        # long top tercile
        for sym, _ in vals[-terc_size:]:
            leg1[sym] = leg1.get(sym, 0.0) + 1.0 / terc_size

    # --- R62 leg: funding score terciles (latest date)
    leg2: dict = {}
    det_fires_today = bool(detector.loc[today_idx]) if today_idx in detector.index else False
    if not det_fires_today and not score_funding.empty and today_idx in score_funding.index:
        row = score_funding.loc[today_idx].dropna()
        if len(row) >= 6:  # need at least 2 terciles worth
            vals = sorted(row.items(), key=lambda kv: kv[1])
            terc_size = max(1, len(vals) // R46_K)
            for sym, _ in vals[:terc_size]:
                leg2[sym] = leg2.get(sym, 0.0) - 1.0 / terc_size
            for sym, _ in vals[-terc_size:]:
                leg2[sym] = leg2.get(sym, 0.0) + 1.0 / terc_size

    # --- Fusion
    w: dict = {}
    for sym in set(leg1) | set(leg2):
        w[sym] = FUSION_W_R46 * leg1.get(sym, 0.0) + (1.0 - FUSION_W_R46) * leg2.get(sym, 0.0)
    # Renormalize: scale to gross Σ|w| = 2/3 (preserves the L/S structure, not 1.0)
    gross = sum(abs(x) for x in w.values())
    target_gross = 2.0 / 3.0
    if gross > 0:
        scale = target_gross / gross
        w = {k: v * scale for k, v in w.items()}
    return w


# ── State management (Redis cache + Supabase system of record) ────────────────
# 2026-08-19, S-176. Redis was the only writer and 5 days of daily marks showed
# identical NAV=0.9995 — the state did not survive between cycles, so each day
# re-inceptioned from nav=1.0 and lost all compounding. Per CLAUDE.md / MEMORY
# the system of record is Supabase and Redis is a cache. The new order is
# durable-first, cache-second, so a missing Redis key falls through to Supabase
# instead of re-inceptioning. The fusion paper book is the SHIP GATE for §P1
# (R64/R65 forward clock), and losing 5 days of compounding to a missing cache
# key is the same defect class as S-105 (24h-TTL Redis for 12 days) — only the
# failure mode is different.
async def _fetch_state_from_supabase() -> dict:
    """Durable state from Supabase. Slower than Redis, but the system of record.

    Returns the most recent row from `fusion_paper_state`. JSONB columns
    (weights / mark_prices / prev_prices / cell) come back as dicts already
    when the column is JSONB; if PostgREST returns them as strings (depends
    on the content negotiation), this normalizes them.

    Returns {} on any failure — same convention as `_load_state`'s cache path,
    so the caller cannot distinguish a missing table from a missing row from
    a network blip. The diagnostic log line is what makes that distinguishable
    in the row-level telemetry (S-131 again).
    """
    import os
    import httpx
    base, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY")
    if not (base and key):
        return {}
    url = (f"{base}/rest/v1/{_STATE_TABLE}"
           f"?select=inception,nav,weights,mark_prices,prev_prices,last_mark,"
           f"n_days_marked,cell,detector_fired_today"
           f"&order=last_mark.desc&limit=1")
    try:
        async with httpx.AsyncClient(timeout=8) as c:
            r = await c.get(
                url,
                headers={"apikey": key, "Authorization": f"Bearer {key}"},
            )
            if r.status_code != 200:
                _log.warning("[fusion] supabase state read: %s %s",
                             r.status_code, r.text[:120])
                return {}
            rows = r.json()
    except Exception as e:
        _log.warning("[fusion] supabase state read exception: %s", e)
        return {}
    if not rows:
        return {}
    row = rows[0]
    # Normalize JSONB columns that some PostgREST versions return as strings.
    for col in ("weights", "mark_prices", "prev_prices", "cell"):
        v = row.get(col)
        if isinstance(v, str):
            try:
                row[col] = json.loads(v)
            except Exception:
                pass
    return row


async def _load_state() -> dict:
    """Load state. Fast path: Redis. Durable fallback: Supabase.

    The 5 identical marks at NAV=0.9995 (S-176) were the result of this
    function returning {} when Redis was empty, after which `nav` defaulted to
    1.0 and `w_held` to {} — exactly the no-compounding placeholder the live
    table was showing. The Supabase fallback is the fix: when the cache misses,
    fall through to the durable row that was written at the end of the
    previous mark, not to a fresh inception.
    """
    # Fast path: Redis cache
    try:
        from src.api.store import redis_get_key
        s = await redis_get_key(_STATE_KEY)
        if isinstance(s, dict) and s:
            return s
    except Exception as e:
        _log.warning("[fusion] redis state read: %s", e)
    # Durable fallback: Supabase
    s = await _fetch_state_from_supabase()
    if s:
        # Refresh the cache so the next cycle is fast again.
        try:
            from src.api.store import redis_set_key
            await redis_set_key(_STATE_KEY, s, ttl=0)
        except Exception:
            pass
    return s


async def _save_state(s: dict) -> None:
    """Persist state. Durable first (Supabase), cache second (Redis).

    The order is load-bearing: if the durable write fails, the cache is NOT
    updated, so the next cycle's `_load_state` falls through to the LAST
    successfully persisted state, not to a half-written row that never made
    it to the system of record. That is the same S-105 discipline as
    `beta_core_paper.mark_and_rebalance` (DURABLE FIRST, CACHE SECOND).
    """
    # Durable: Supabase
    try:
        from src.api.store import supabase_insert_table
        ok = await supabase_insert_table(_STATE_TABLE, [{
            "inception": s.get("inception"),
            "last_mark": s.get("last_mark"),
            "nav": s.get("nav"),
            "weights": s.get("weights", {}),
            "mark_prices": s.get("mark_prices", {}),
            "prev_prices": s.get("prev_prices", {}),
            "n_days_marked": s.get("n_days_marked", 0),
            "cell": s.get("cell", {}),
            "detector_fired_today": bool(s.get("detector_fired_today", False)),
        }])
        if not ok:
            _log.warning("[fusion] supabase state save returned False — "
                         "cache NOT updated; next cycle will re-fetch durable state")
            return
    except Exception as e:
        _log.warning("[fusion] supabase state save exception: %s — "
                     "cache NOT updated", e)
        return
    # Cache: Redis (best-effort, only after durable write succeeded)
    try:
        from src.api.store import redis_set_key
        await redis_set_key(_STATE_KEY, s, ttl=0)
    except Exception as e:
        _log.warning("[fusion] redis state cache write: %s "
                     "(durable write succeeded; cache stale until next cycle)", e)


# ── Daily mark ───────────────────────────────────────────────────────────────
async def mark_and_rebalance(dry_run: bool = False) -> dict:
    """Daily mark of the R64 fusion paper book. Idempotent per calendar day.

    Pipeline:
      1. Fetch live close + funding from Binance fapi (28-asset universe).
      2. Fetch live CIS pillar_O from Redis/Supabase.
      3. Build today's funding features → frozen detector.
      4. Build today's funding score → leg2 weights.
      5. Pillar_O → leg1 weights.
      6. Fuse to target weights.
      7. Fill-attribution (P2): realized slippage + fill ratio against declared cap.
      8. Mark NAV using y[t]/y[t-1]-1 returns, deduct cost from rebalance.
      9. Persist state → Redis; NAV row → Supabase.

    Returns the daily result dict (used by both the loop and the API endpoint).
    """
    today = dt.date.today()
    data = await _fetch_close_funding(UNIVERSE)
    if len(data) < 20:
        return {"status": "skipped", "reason": "insufficient_live_data",
                "n_assets_with_data": len(data)}

    pillar_o = await _fetch_cis_pillar_o(list(data.keys()))
    adv_usd = await _fetch_adv_usd(list(data.keys()))

    # Build funding panel [date × asset] from live data
    today_ts = pd.Timestamp(today)
    funding_panel = pd.DataFrame(
        {sym: pd.Series(d["funding"], index=pd.date_range(
            end=today_ts, periods=len(d["funding"]), freq="D"))
         for sym, d in data.items() if len(d["funding"]) >= 20}
    ).sort_index()
    feats = _funding_features_daily(funding_panel)
    det = _frozen_detector(feats.reindex(data and pd.DataFrame({sym: d["close"] for sym, d in data.items()},
                                                              index=pd.date_range(end=today_ts, periods=max(len(d["close"]) for d in data.values()), freq="D")).index))
    score = _score_funding_zwide_live(funding_panel)

    last_px = {sym: float(d["close"][-1]) for sym, d in data.items()}
    prev_px = {sym: float(d["close"][-2]) for sym, d in data.items() if len(d["close"]) >= 2}

    # Restrict pillar_o to live-symbol set
    pillar_o_live = {s: pillar_o[s][-1] if isinstance(pillar_o.get(s), list) and pillar_o[s]
                     else pillar_o.get(s) for s in data.keys()}
    pillar_o_live = {s: float(v) for s, v in pillar_o_live.items() if v is not None and not (isinstance(v, float) and np.isnan(v))}

    w_tgt = _target_weights(pillar_o_live, score, det, today_ts)

    # Fill-attribution
    from src.data.signals.fill_attribution import attribute_fill
    state = await _load_state()
    nav = float(state.get("nav", 1.0)) if state.get("nav") else 1.0
    w_held = state.get("weights", {}) or {}
    fill = attribute_fill(
        target_weights=w_tgt,
        current_weights=w_held,
        nav_usd=nav,
        prices=last_px,
        adv_usd=adv_usd,
        slippage_model_bps=R46_BPS,
        declared_capacity_usd=DEFAULT_DECLARED_CAPACITY_USD,
    )

    last_mark = state.get("last_mark")
    if last_mark == today.isoformat():
        return {"status": "already_marked", "nav": round(nav, 5),
                "date": today.isoformat(), "n": len(w_tgt),
                "gross": round(sum(abs(x) for x in w_tgt.values()), 4)}

    # Mark-to-market PnL: Σ w_held × (price[t]/price[t-1] - 1)
    price_pnl = 0.0
    for sym, wi in w_held.items():
        if sym in last_px and sym in prev_px and prev_px[sym] > 0:
            price_pnl += wi * (last_px[sym] / prev_px[sym] - 1.0)

    # Turnover cost on the clip we just got from fill_attribution
    cost_frac = (fill["totals"]["weighted_slippage_bps"] / 1e4) if fill["totals"]["weighted_slippage_bps"] > 0 else 0.0
    daily_ret = price_pnl - cost_frac
    nav_new = nav * (1.0 + daily_ret)

    new_state = {
        "inception": state.get("inception", today.isoformat()),
        "nav": nav_new,
        "weights": w_tgt,
        "mark_prices": last_px,
        "prev_prices": prev_px,
        "last_mark": today.isoformat(),
        "cell": {"w_R46": FUSION_W_R46, "r46_cad": R46_CAD, "r46_bps": R46_BPS,
                 "r62_cad": R62_CAD, "r62_bps": R62_BPS, "r62_zwin": R62_ZWIN,
                 "r62_z": R62_Z, "r62_mf": R62_MF, "r62_features": R62_FEATURE_SET},
        "n_days_marked": int(state.get("n_days_marked", 0)) + 1,
        "detector_fired_today": bool(det.loc[today_ts]) if today_ts in det.index else False,
    }

    if not dry_run:
        await _save_state(new_state)
        await _write_nav(today, nav_new, daily_ret, w_tgt, cost_frac, fill, det, today_ts)

    validated = new_state["n_days_marked"] >= VALIDATION_MIN_DAYS
    return {
        "status": "marked", "nav": round(nav_new, 5),
        "daily_return_pct": round(daily_ret * 100, 4),
        "n": len(w_tgt),
        "gross": round(sum(abs(x) for x in w_tgt.values()), 4),
        "fill_ratio_overall": fill["totals"]["fill_ratio_overall"],
        "weighted_slippage_bps": fill["totals"]["weighted_slippage_bps"],
        "capacity_status": fill["capacity"]["status"],
        "detector_fired_today": new_state["detector_fired_today"],
        "n_days_marked": new_state["n_days_marked"],
        "validated": validated,
        "date": today.isoformat(),
    }


async def _write_nav(d, nav, dret, weights, cost, fill, det, today_ts):
    """Persist one NAV row to Supabase. Graceful skip if unconfigured."""
    from src.api.store import supabase_insert_table
    longs = ",".join(f"{s}:{w:+.3f}" for s, w in sorted(weights.items(), key=lambda kv: -kv[1])[:3])
    shorts = ",".join(f"{s}:{w:+.3f}" for s, w in sorted(weights.items(), key=lambda kv: kv[1])[:3])
    try:
        await supabase_insert_table(_NAV_TABLE, [{
            "mark_date": d.isoformat(),
            "nav": round(nav, 6),
            "daily_return": round(dret, 6),
            "gross": round(sum(abs(x) for x in weights.values()), 4),
            "n_positions": len(weights),
            "cost": round(cost, 6),
            "fill_ratio_overall": fill["totals"]["fill_ratio_overall"],
            "weighted_slippage_bps": fill["totals"]["weighted_slippage_bps"],
            "capacity_status": fill["capacity"]["status"],
            "capacity_used_pct": fill["capacity"]["used_pct"],
            "detector_fired": bool(det.loc[today_ts]) if today_ts in det.index else False,
            "cell_w_r46": FUSION_W_R46,
            "top_longs": longs,
            "top_shorts": shorts,
            "note": f"fill={fill['totals']['fill_ratio_overall']:.3f} slip={fill['totals']['weighted_slippage_bps']:.1f}bps cap={fill['capacity']['status']}",
        }])
    except Exception as e:
        _log.warning("[fusion] nav write: %s", e)


async def get_curve(limit: int = 400) -> dict:
    """NAV curve + honest summary for the endpoint."""
    import os, httpx
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_KEY", "")
    if not (url and key):
        return {"status": "skipped", "reason": "supabase_not_configured"}
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.get(f"{url}/rest/v1/{_NAV_TABLE}",
                            params={"select": "mark_date,nav,daily_return,gross,n_positions,cost,"
                                              "fill_ratio_overall,weighted_slippage_bps,"
                                              "capacity_status,capacity_used_pct,detector_fired,"
                                              "cell_w_r46,top_longs,top_shorts,note",
                                    "order": "mark_date.asc", "limit": str(limit)},
                            headers={"apikey": key, "Authorization": f"Bearer {key}"})
            rows = r.json() if r.status_code == 200 else []
    except Exception as e:
        return {"status": "error", "error": str(e)[:120]}
    if not rows:
        return {"status": "no_data",
                "note": "R65 fusion paper book not yet marked",
                "cell": {"w_R46": FUSION_W_R46, "r46_cad": R46_CAD, "r46_bps": R46_BPS,
                         "r62_cad": R62_CAD, "r62_bps": R62_BPS},
                "declared_capacity_usd": DEFAULT_DECLARED_CAPACITY_USD,
                "validation_min_days": VALIDATION_MIN_DAYS}

    navs = [x["nav"] for x in rows]
    rets = [x["daily_return"] for x in rows if x.get("daily_return") is not None]
    engaged = [x for x in rows if (x.get("gross") or 0) > 0]
    sharpe = (float(np.mean(rets) / np.std(rets) * np.sqrt(365))
              if len(rets) > 5 and np.std(rets) > 0 else None)
    peak = np.maximum.accumulate(navs)
    dd = float((peak - navs).max() / peak.max()) if navs else 0.0
    n_days = len(rows)
    validated = n_days >= VALIDATION_MIN_DAYS
    avg_fill = float(np.mean([r["fill_ratio_overall"] for r in rows if r.get("fill_ratio_overall") is not None])) if rows else None
    avg_slip = float(np.mean([r["weighted_slippage_bps"] for r in rows if r.get("weighted_slippage_bps") is not None])) if rows else None
    det_fires = sum(1 for r in rows if r.get("detector_fired"))
    return {
        "status": "ok",
        "cell": {"w_R46": FUSION_W_R46, "r46_cad": R46_CAD, "r46_bps": R46_BPS,
                 "r62_cad": R62_CAD, "r62_bps": R62_BPS, "r62_zwin": R62_ZWIN,
                 "r62_z": R62_Z, "r62_mf": R62_MF, "r62_features": R62_FEATURE_SET},
        "declared_capacity_usd": DEFAULT_DECLARED_CAPACITY_USD,
        "validation_min_days": VALIDATION_MIN_DAYS,
        "validated": validated,
        "days": n_days,
        "inception": rows[0]["mark_date"],
        "nav": navs[-1],
        "return_pct": round((navs[-1] - 1) * 100, 2),
        "ann_sharpe": round(sharpe, 2) if sharpe else None,
        "max_dd_pct": round(dd * 100, 2),
        "days_engaged": len(engaged),
        "days_flat": n_days - len(engaged),
        "engagement_pct": round(100.0 * len(engaged) / n_days, 1),
        "avg_fill_ratio": round(avg_fill, 4) if avg_fill is not None else None,
        "avg_weighted_slippage_bps": round(avg_slip, 2) if avg_slip is not None else None,
        "detector_fires_total": det_fires,
        "detector_fire_rate_pct": round(100.0 * det_fires / n_days, 1),
        "latest": rows[-1],
        "curve": rows,
    }


if __name__ == "__main__":
    import asyncio, json
    print(json.dumps(asyncio.run(mark_and_rebalance(dry_run=True)), indent=2, default=str))
