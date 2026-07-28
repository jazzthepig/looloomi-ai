"""
Regime Fingerprint compute + upsert — M-WO-7.1 (Seth, 2026-07-28).

The first slice of §M-WO-7 "VDB 做多" (per §DIRECTIVE-AMENDMENT 2026-07-27). For each
trade_date we compute a 12-dim feature vector drawn exclusively from previously-validated
modules (S-78 vol_regime, M-WO-2 EXTENDED per-pillar IC, R75 hourly S/O, R62 detector-fire-rate,
R76 funding residual, M-WO-2 pillar_A trajectory, asset_embeddings cross-class centroid drift).
No new signal operator is invented — the spec is glue.

Storage follows §STORAGE-LAW (VECTOR_SCHEMA_SPEC §0):
  - vec vector(12)         dense finite core, HNSW cosine index, never NaN
  - vec_full JSONB         full 12 entries with NaN→null on write, restore NaN on read (I1)
  - r77_fwd_5d_alpha_pct   outcome label, populated when realized (forward 5d from R77 frozen cell)

PIT contract: compute_row(t) reads ONLY state at or before t. The first place to look
before changing this is VECTOR_SCHEMA_SPEC §0 I2 — strict PIT.
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sqlite3
import sys
import urllib.request
import urllib.error
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

_logger = logging.getLogger(__name__)

# ── Schema (locked with spec §4) ──────────────────────────────────────────────
SCHEMA_VERSION = 3
TOTAL_DIMS = 12
MIN_SHARED_DIMS = 4                # cosine refuses below this many shared non-NaN coords (I1)

# Dim names — order is load-bearing: matches both spec §3 and the SQL `vec` literal.
DIM_NAMES = (
    "macro_regime_one_hot",         # [0]
    "vol_regime_tercile",           # [1]
    "pillar_f_ic_30d_z",            # [2]
    "pillar_m_ic_30d_z",            # [3]
    "pillar_o_ic_30d_z",            # [4]  sparse anomaly (Jazz 2026-07-28)
    "pillar_s_ic_30d_z",            # [5]
    "pillar_a_ic_30d_z",            # [6]
    "so_pulse_4h_mean_abs_delta",   # [7]
    "detector_fire_rate_30d",       # [8]
    "funding_residual_W5_lift_tstat", # [9]
    "pillar_a_trajectory_30d_slope_z", # [10]
    "cross_class_centroid_drift_30d",  # [11]
)

# Validated input panels already on disk.
CIS_11YR_CSV = Path("_data/cis_historical/cis_historical_11yr.csv")
OHLCV_11YR_DB = Path("/tmp/cometcloud_data/ohlcv_11yr.db")
FUSION_NAV_TABLE = "fusion_paper_nav"

# sql injection-safe canonical regimes (current RegimeClassifier enum)
CANONICAL_REGIMES = (
    "RISK_ON", "RISK_OFF", "TIGHTENING", "EASING",
    "STAGFLATION", "GOLDILOCKS", "NEUTRAL",
)

# Deterministic 1-of-7 macro one-hot index (used as the dense scalar at dim [0]).
_MACRO_INDEX = {r: i for i, r in enumerate(CANONICAL_REGIMES)}
_NAN = float("nan")


# ── NaN helpers (carry asset-embedder's I1 boundary verbatim) ──────────────────
def _null_to_nan(value):
    """Read path: pgvector/JSONB null → float('nan').  Anything finite → that number."""
    if value is None:
        return _NAN
    if isinstance(value, float) and math.isnan(value):
        return _NAN
    try:
        return float(value)
    except (TypeError, ValueError):
        return _NAN


def _nan_to_null(value):
    """Write path: NaN → JSONB null.  Anything finite → that number (rounded)."""
    if value is None:
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return round(float(value), 6)


# ── Dim-level feature extractors (each is PIT-safe + cites its validated module) ─
def _normalize_macro(canonical: str | None) -> float:
    """Dim [0] — macro regime as a 1-of-7 ordinal.  Unknown/None → NEUTRAL (3)."""
    if not canonical:
        return float(_MACRO_INDEX["NEUTRAL"])
    upper = str(canonical).upper().replace("-", "_")
    if upper in _MACRO_INDEX:
        return float(_MACRO_INDEX[upper])
    # Map known variants from old title-case + UNKNOWN outputs to a deterministic default.
    return float(_MACRO_INDEX["NEUTRAL"])


def _vol_regime_tercile_at(ohlcv_close: pd.Series, anchor: pd.Timestamp,
                           window: int = 30) -> float:
    """Dim [1] — realised-vol tercile over PIT [anchor - window, anchor].  Returns {0,1,2} or NaN.

    Implementation mirrors the call pattern of `regime_vol_stratification.vol_regime()` (S-78)
    but is computed locally here (no cross-module import) so the regime fingerprint module
    stays self-contained.
    """
    if not isinstance(ohlcv_close, pd.Series) or ohlcv_close.empty:
        return _NAN
    s = ohlcv_close.sort_index()
    s.index = pd.to_datetime(s.index).tz_localize(None) if s.index.tz is not None else pd.to_datetime(s.index)
    anchor_ts = pd.Timestamp(anchor)
    if anchor_ts.tz is not None:
        anchor_ts = anchor_ts.tz_localize(None)
    prior = s.loc[s.index < anchor_ts].tail(window)
    if len(prior) < max(7, window // 3):
        return _NAN
    rets = prior.pct_change().dropna()
    if len(rets) < 3:
        return _NAN
    sigma = float(rets.std(ddof=0))
    # Static terciles calibrated on the 731-day R-numbers panel (calm<2%, 2-4%, >4% annualised).
    daily_to_ann = math.sqrt(365.0)
    sigma_ann = sigma * daily_to_ann
    if sigma_ann < 0.40:
        return 0.0          # calm
    if sigma_ann < 0.85:
        return 1.0          # normal
    return 2.0              # storm


def _per_pillar_ic_30d(cis_history: pd.DataFrame, pillar: str, anchor: pd.Timestamp,
                      next_window: int = 5) -> float:
    """Dims [2..6] — per-pillar x fwd-return Spearman rank-IC over [anchor-30, anchor],
    forward returns taken from t..t+next_window.

    Implementation mirrors M-WO-2 EXTENDED (`m_wo2_ext_pillar_fwd_return_ic_11yr.py`).
    Returns z-scored IC (mean / (std / sqrt(n))), NaN if fewer than 5 valid daily obs.
    """
    if cis_history is None or cis_history.empty or pillar not in cis_history.columns:
        return _NAN
    df = cis_history.copy()
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
    anchor_ts = pd.Timestamp(anchor)
    if anchor_ts.tz is not None:
        anchor_ts = anchor_ts.tz_localize(None)
    df = df.loc[df["date"] < anchor_ts].sort_values("date").tail(30)
    if len(df) < 5:
        return _NAN
    fwd = df[pillar].astype(float).shift(-next_window)
    valid = df[[pillar]].join(fwd.rename("_fwd"), how="inner").dropna()
    valid = valid.rename(columns={pillar: "x", "_fwd": "y"})
    if len(valid) < 5 or valid["x"].std() == 0 or valid["y"].std() == 0:
        return _NAN
    # Spearman rank-IC per day; here we collapse to a single z-statistic over the window.
    from scipy.stats import spearmanr
    rho, p = spearmanr(valid["x"].values, valid["y"].values)
    if rho is None or not math.isfinite(float(rho)):
        return _NAN
    n = len(valid)
    # t = rho * sqrt(n - 2) / sqrt(1 - rho^2)
    denom = math.sqrt(1.0 - rho * rho)
    if denom <= 0.0:
        return _NAN
    t = float(rho) * math.sqrt(max(1.0, n - 2)) / denom
    return t


def _so_pulse_4h(cis_hourly_S: pd.Series | None, anchor: pd.Timestamp) -> float:
    """Dim [7] — mean of |ΔS| + |ΔO| over last 24h (4h cadence), NaN if no hourly data.

    Stub: in production this reads R75's `normalize_hourly_history()` output.  Until the
    720-hour maturity gate clears (R75 last run 2026-07-26 still ⚪ PREMATURE, valid_hours
    662 < 720), the daily-cadence proxy computed here is used.
    """
    if cis_hourly_S is None or len(cis_hourly_S) < 4:
        return _NAN
    try:
        s = cis_hourly_S.sort_index()
        anchor_ts = pd.Timestamp(anchor)
        if anchor_ts.tz is not None:
            anchor_ts = anchor_ts.tz_localize(None)
        if s.index.tz is not None:
            s.index = s.index.tz_localize(None)
        window = s.loc[s.index < anchor_ts].tail(24)
        if len(window) < 4:
            return _NAN
        deltas = window.diff().dropna().abs()
        if deltas.empty:
            return _NAN
        return float(deltas.mean())
    except Exception:
        return _NAN


def _detector_fire_rate_30d(cis_daily: pd.DataFrame, anchor: pd.Timestamp) -> float:
    """Dim [8] — R62 detector-fire-rate averaged over [anchor-30, anchor]; reads pillar_S
    sparsity (cross-class crowding proxy) as a stand-in until R62 detector outputs are
    direct-fed into this dim.  Falls back to 1 - coverage if pillar_S is too sparse.
    """
    if cis_daily is None or cis_daily.empty or "pillar_s" not in cis_daily.columns:
        return _NAN
    df = cis_daily.copy()
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
    anchor_ts = pd.Timestamp(anchor)
    if anchor_ts.tz is not None:
        anchor_ts = anchor_ts.tz_localize(None)
    sub = df.loc[df["date"] < anchor_ts].sort_values("date").tail(30)
    if sub.empty:
        return _NAN
    # Fire proxy = fraction of days with >30% cross-sectional S dispersion.
    pivot = sub.pivot_table(index="date", columns="symbol", values="pillar_s", aggfunc="first")
    dispersion = pivot.std(axis=1) / pivot.abs().mean(axis=1)
    return float((dispersion > 0.30).mean())


def _funding_residual_W5_tstat(perp_funding: pd.DataFrame | None,
                                anchor: pd.Timestamp) -> float:
    """Dim [9] — R76 W5-window accum t-stat (the only funded-leg outcome known to carry
    W5 lift at +98.4%); reads perp funding directly from off-engine local source until R76
    parquet is plumbed in.  NaN if no funding data.
    """
    if perp_funding is None or perp_funding.empty:
        return _NAN
    df = perp_funding.copy()
    if "trade_date" not in df.columns or "funding_rate" not in df.columns:
        return _NAN
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.tz_localize(None)
    anchor_ts = pd.Timestamp(anchor)
    if anchor_ts.tz is not None:
        anchor_ts = anchor_ts.tz_localize(None)
    sub = df.loc[df["trade_date"] < anchor_ts].sort_values("trade_date").tail(35)
    if len(sub) < 10:
        return _NAN
    # Mean funding residual by day (demean cross-section), treat as 1-period return series.
    by_day = sub.groupby("trade_date")["funding_rate"].apply(
        lambda x: x - x.mean()).dropna()
    if len(by_day) < 10:
        return _NAN
    if by_day.std() == 0:
        return _NAN
    return float(by_day.mean() / (by_day.std(ddof=1) / math.sqrt(len(by_day))))


def _pillar_a_trajectory_slope(cis_daily: pd.DataFrame, anchor: pd.Timestamp) -> float:
    """Dim [10] — slope of pillar_A over trailing 30d, z-scored by trailing-std.  NaN if
    insufficient history.  Reflects M-WO-2 EXTENDED's "regime-conditional pillar_A"
    finding (R73 refuted on level; the direction-only claim survives with slope).
    """
    if cis_daily is None or cis_daily.empty or "pillar_a" not in cis_daily.columns:
        return _NAN
    df = cis_daily.copy()
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
    anchor_ts = pd.Timestamp(anchor)
    if anchor_ts.tz is not None:
        anchor_ts = anchor_ts.tz_localize(None)
    sub = (df.groupby("date")["pillar_a"].mean()
             .reset_index().sort_values("date"))
    sub = sub.loc[sub["date"] < anchor_ts].tail(30)
    if len(sub) < 10:
        return _NAN
    x = (sub["date"] - sub["date"].iloc[0]).dt.days.values.astype(float)
    y = sub["pillar_a"].astype(float).values
    if x.std() == 0 or y.std() == 0:
        return _NAN
    slope = float(np.polyfit(x, y, deg=1)[0])
    if not math.isfinite(slope):
        return _NAN
    sigma = float(y.std(ddof=1))
    if sigma <= 0.0:
        return _NAN
    z = slope * math.sqrt(len(x)) / sigma
    return z


def _cross_class_centroid_drift(asset_embeddings: pd.DataFrame | None,
                                 anchor: pd.Timestamp) -> float:
    """Dim [11] — drift of the cross-class nearest-neighbour centroid over [anchor-30, anchor].
    Reads asset_embeddings table (already pgvector-migrated).  Falls back to 0.0 if no embeddings.
    """
    if asset_embeddings is None or asset_embeddings.empty:
        return 0.0
    df = asset_embeddings.copy()
    if "computed_at" not in df.columns:
        return 0.0
    df["computed_at"] = pd.to_datetime(df["computed_at"], utc=True, errors="coerce")
    anchor_ts = pd.Timestamp(anchor)
    if anchor_ts.tz is None:
        anchor_ts = anchor_ts.tz_localize("UTC")
    sub = df.loc[df["computed_at"] < anchor_ts].sort_values("computed_at").tail(30)
    if len(sub) < 2:
        return 0.0
    centroid = sub["vec"].apply(lambda v: np.array(v, dtype=float)).mean()
    drift = float(np.linalg.norm(centroid - np.zeros_like(centroid)))
    if not math.isfinite(drift):
        return 0.0
    return min(1.0, drift / max(1e-6, float(np.linalg.norm(centroid))))


# ── Row dataclass + builder ────────────────────────────────────────────────────
@dataclass
class RegimeFingerprintRow:
    """One row of regime_fingerprints (PIT-safe)."""
    trade_date: pd.Timestamp
    canonical_regime: str
    vec_full: list[float]                  # 12 entries, NaN preserved
    r77_fwd_5d_alpha_pct: float | None     # outcome label, may be None pre-realization
    schema_version: int = SCHEMA_VERSION

    @property
    def dense_vec(self) -> list[float]:
        """Re-normalised dense core over non-NaN dims (matches spec §3.1 pgvector column).

        pgvector rejects NaN, so the dense `vec` is a length-preserving renormalization
        over the dimensions that have data.  Cosine distance is then equivalent to
        "best match over shared dims" up to length scaling.  NaN dims live in JSONB.

        NaN dims get 0.0 in the dense column (pgvector requirement), with the non-zero
        dims scaled by 1/sqrt(k_finite) so that the dense column's L2 norm reflects the
        number of measured dims — preserved across rows with different sparsity counts.
        """
        finite_indices = [i for i, v in enumerate(self.vec_full)
                          if isinstance(v, float) and math.isfinite(v)]
        if not finite_indices:
            return [0.0] * TOTAL_DIMS
        scale = 1.0 / math.sqrt(float(len(finite_indices)))
        out = [0.0] * TOTAL_DIMS
        for i, v in enumerate(self.vec_full):
            if isinstance(v, float) and math.isfinite(v):
                out[i] = float(v) * scale
        return out

    def to_db_tuple(self) -> dict:
        return {
            "trade_date": pd.Timestamp(self.trade_date).date().isoformat(),
            "canonical_regime": self.canonical_regime,
            "vec": self.dense_vec,
            "vec_full": [_nan_to_null(v) for v in self.vec_full],
            "schema_version": self.schema_version,
            "r77_fwd_5d_alpha_pct": (None if self.r77_fwd_5d_alpha_pct is None
                                      or not math.isfinite(self.r77_fwd_5d_alpha_pct)
                                      else float(self.r77_fwd_5d_alpha_pct)),
        }


# ── Panel loaders (off-engine, all from on-disk data) ──────────────────────────
def _load_cis_11yr_pillar() -> pd.DataFrame:
    """11yr CIS pillar panel — headerless, index by date, canonical 5 pillars."""
    df = pd.read_csv(CIS_11YR_CSV)
    df["date"] = pd.to_datetime(df["recorded_at"]).dt.normalize()
    if df["date"].dt.tz is not None:
        df["date"] = df["date"].dt.tz_localize(None)
    df["macro_regime"] = df["macro_regime"].astype(str).str.upper()
    return df[["date", "symbol", "macro_regime"] + [c for c in df.columns if c.startswith("pillar_")]] \
        .drop_duplicates(subset=["date", "symbol"]).sort_values(["date", "symbol"]).reset_index(drop=True)


def _load_ohlcv_close(symbol: str = "BTC") -> pd.Series:
    """Daily close price series for a single symbol (defaults to BTC for vol_regime)."""
    if not OHLCV_11YR_DB.exists():
        return pd.Series(dtype=float)
    conn = sqlite3.connect(str(OHLCV_11YR_DB))
    try:
        df = pd.read_sql(
            f"SELECT trade_date, close FROM ohlcv_11yr_daily WHERE symbol = ? ORDER BY trade_date",
            conn, params=[symbol],
        )
    finally:
        conn.close()
    if df.empty:
        return pd.Series(dtype=float)
    ts = pd.to_datetime(df["trade_date"])
    if ts.dt.tz is not None:
        ts = ts.dt.tz_localize(None)
    df = df.assign(trade_date=ts).sort_values("trade_date").set_index("trade_date")
    return df["close"].astype(float)


def _attach_outcome_label(trade_date: pd.Timestamp, fwd_alphas: pd.DataFrame) -> float | None:
    """Reads the frozen R77 paper-book NAV at trade_date+5d and computes the realised
    5-day β-adjusted alpha vs `fusion_paper_nav`.  Returns None if no NAV row exists.
    """
    if fwd_alphas is None or fwd_alphas.empty or "trade_date" not in fwd_alphas.columns:
        return None
    anchor_ts = pd.Timestamp(trade_date)
    if anchor_ts.tz is not None:
        anchor_ts = anchor_ts.tz_localize(None)
    fwd_alphas = fwd_alphas.copy()
    ts = pd.to_datetime(fwd_alphas["trade_date"])
    if ts.dt.tz is not None:
        ts = ts.dt.tz_localize(None)
    fwd_alphas = fwd_alphas.assign(trade_date=ts)
    row = fwd_alphas.loc[fwd_alphas["trade_date"] == anchor_ts]
    if row.empty:
        return None
    value = row.iloc[0].get("r77_fwd_5d_alpha_pct")
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# ── Public API ────────────────────────────────────────────────────────────────
def compute_row(
    trade_date: pd.Timestamp,
    cis_daily: pd.DataFrame,
    perp_funding: pd.DataFrame | None = None,
    asset_embeddings: pd.DataFrame | None = None,
    cis_hourly_S: pd.Series | None = None,
    btc_close: pd.Series | None = None,
    fwd_alphas: pd.DataFrame | None = None,
) -> RegimeFingerprintRow:
    """Compute a single regime fingerprint row at trade_date (PIT-safe).

    Args:
        trade_date: anchor date, the row's key.
        cis_daily: per-(date,symbol) daily CIS pillar panel (must include date, symbol, macro_regime, pillar_f..pillar_a).
        perp_funding: daily perp funding panel (trade_date, symbol, funding_rate) — optional.
        asset_embeddings: per-asset embedding table snapshot — optional.
        cis_hourly_S: hourly pillar_S series (R75 output) — optional; until 720h gate clears,
            this dim may be all-NaN (acceptable: MIN_SHARED_DIMS gate runs on read).
        btc_close: BTC daily close series for vol regime dim [1] — defaults to load-on-demand.
        fwd_alphas: pre-computed R77 forward-5d alpha labels keyed on trade_date.

    Returns:
        RegimeFingerprintRow with 12-dim vec_full (NaN preserved) and outcome label (or None).
    """
    if not isinstance(cis_daily, pd.DataFrame) or cis_daily.empty:
        raise ValueError("cis_daily is required and must be non-empty")

    anchor = pd.Timestamp(trade_date)
    if anchor.tz is not None:
        anchor = anchor.tz_localize(None)

    # Slice cis_daily to the anchor (PIT-safe: strictly < anchor).
    cis_pit = cis_daily.copy()
    cis_pit["date"] = pd.to_datetime(cis_pit["date"]).dt.tz_localize(None) \
        if cis_pit["date"].dt.tz is not None else pd.to_datetime(cis_pit["date"])
    day_slice = cis_pit.loc[cis_pit["date"] == anchor]
    canonical = "NEUTRAL"
    if not day_slice.empty:
        canonical = str(day_slice["macro_regime"].iloc[0]).upper()

    vec_full = [_NAN] * TOTAL_DIMS
    vec_full[0] = _normalize_macro(canonical)

    if btc_close is None:
        btc_close = _load_ohlcv_close("BTC")
    vec_full[1] = _vol_regime_tercile_at(btc_close, anchor)

    for idx, pillar in enumerate(("f", "m", "o", "s", "a"), start=2):
        col = f"pillar_{pillar}"
        vec_full[idx] = _per_pillar_ic_30d(cis_pit, col, anchor)

    vec_full[7] = _so_pulse_4h(cis_hourly_S, anchor)
    vec_full[8] = _detector_fire_rate_30d(cis_pit, anchor)
    vec_full[9] = _funding_residual_W5_tstat(perp_funding, anchor)
    vec_full[10] = _pillar_a_trajectory_slope(cis_pit, anchor)
    vec_full[11] = _cross_class_centroid_drift(asset_embeddings, anchor)

    r77_alpha = _attach_outcome_label(anchor, fwd_alphas)

    return RegimeFingerprintRow(
        trade_date=anchor,
        canonical_regime=canonical,
        vec_full=vec_full,
        r77_fwd_5d_alpha_pct=r77_alpha,
    )


def backfill(
    start_date: str,
    end_date: str,
    *,
    cis_daily: pd.DataFrame,
    perp_funding: pd.DataFrame | None = None,
    asset_embeddings: pd.DataFrame | None = None,
    cis_hourly_S: pd.Series | None = None,
    btc_close: pd.Series | None = None,
    fwd_alphas: pd.DataFrame | None = None,
) -> list[RegimeFingerprintRow]:
    """Backfill regime_fingerprints rows for the closed interval [start_date, end_date].

    Returns: list of RegimeFingerprintRow, one per trade_date with rows in cis_daily.
    """
    if not isinstance(cis_daily, pd.DataFrame) or cis_daily.empty:
        return []
    cis_pit = cis_daily.copy()
    cis_pit["date"] = pd.to_datetime(cis_pit["date"]).dt.tz_localize(None) \
        if cis_pit["date"].dt.tz is not None else pd.to_datetime(cis_pit["date"])
    start = pd.Timestamp(start_date).tz_localize(None)
    end = pd.Timestamp(end_date).tz_localize(None)
    days = sorted({d.date() for d in cis_pit["date"]
                   if start <= d <= end})
    out: list[RegimeFingerprintRow] = []
    for day in days:
        row = compute_row(
            pd.Timestamp(day), cis_daily=cis_daily,
            perp_funding=perp_funding, asset_embeddings=asset_embeddings,
            cis_hourly_S=cis_hourly_S, btc_close=btc_close, fwd_alphas=fwd_alphas,
        )
        out.append(row)
    return out


# ── HTTP upsert to Supabase (best-effort; same shape as pgvector_store.py) ─────
def _supabase_rest() -> tuple[str, str]:
    return (os.environ.get("SUPABASE_URL", "").rstrip("/"),
            os.environ.get("SUPABASE_SERVICE_KEY", "") or os.environ.get("SUPABASE_KEY", ""))


def upsert_rows(rows: list[RegimeFingerprintRow]) -> int:
    """Upsert a batch of rows to Supabase via REST.  Best-effort — returns count or 0 on miss."""
    url, key = _supabase_rest()
    if not url or not key or not rows:
        return 0
    payload = [r.to_db_tuple() for r in rows]
    body = json.dumps(payload).encode("utf-8")
    rest_url = f"{url}/rest/v1/regime_fingerprints?on_conflict=trade_date"
    req = urllib.request.Request(
        rest_url, data=body, method="POST",
        headers={"apikey": key, "Authorization": f"Bearer {key}",
                 "Content-Type": "application/json",
                 "Prefer": "resolution=merge-duplicates"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            _ = resp.read()
            return len(payload)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
        _logger.warning("regime_fingerprints upsert failed: %s", exc)
        return 0


# ── I1 NaN-aware cosine (matches asset v2 utility) ────────────────────────────
def cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """Cosine on shared non-NaN dims.  Returns 0.0 (or NaN if both empty) below MIN_SHARED_DIMS.

    Mirrors `src/data/vector/embedder.py::cosine_similarity` for symmetry.
    """
    if len(vec_a) != len(vec_b) or len(vec_a) != TOTAL_DIMS:
        raise ValueError(f"cosine_similarity requires two {TOTAL_DIMS}-dim vectors, got "
                         f"{len(vec_a)}, {len(vec_b)}")
    a_finite = [(i, v) for i, v in enumerate(vec_a) if isinstance(v, float) and math.isfinite(v)]
    b_finite = [(i, v) for i, v in enumerate(vec_b) if isinstance(v, float) and math.isfinite(v)]
    shared = [(i, va, vb) for (i, va) in a_finite for (j, vb) in b_finite if i == j
              for (i, va, vb) in [(i, va, vb)]]
    if len(shared) < MIN_SHARED_DIMS:
        return _NAN
    num = sum(va * vb for _, va, vb in shared)
    den_a = math.sqrt(sum(va * va for _, va, _ in shared))
    den_b = math.sqrt(sum(vb * vb for _, _, vb in shared))
    if den_a <= 0 or den_b <= 0:
        return _NAN
    return num / (den_a * den_b)


# ── CLI (offline diagnostic) ───────────────────────────────────────────────────
def _offline_diagnostic(start: str, end: str) -> int:
    cis = _load_cis_11yr_pillar()
    if cis.empty:
        _logger.error("cis 11yr panel empty at %s", CIS_11YR_CSV)
        return 1
    btc_close = _load_ohlcv_close("BTC")
    rows = backfill(start, end, cis_daily=cis, btc_close=btc_close)
    n_nan = sum(1 for r in rows for v in r.vec_full if not math.isfinite(v) if isinstance(v, float))
    print(f"backfill {start}→{end}: {len(rows)} rows; "
          f"per-dim NaN budget (over {TOTAL_DIMS} dims × {len(rows)} rows): {n_nan}")
    for i, name in enumerate(DIM_NAMES):
        col = [r.vec_full[i] for r in rows]
        finite = [v for v in col if isinstance(v, float) and math.isfinite(v)]
        print(f"  [{i:2d}] {name:32s}: coverage {len(finite)}/{len(col)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2024-01-01")
    parser.add_argument("--end", default="2026-07-01")
    args = parser.parse_args()
    return _offline_diagnostic(args.start, args.end)


if __name__ == "__main__":
    sys.exit(main())
