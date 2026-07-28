"""
Smoke tests for M-WO-7.1 Regime Fingerprint compute + upsert.

Pure-Python synthetic tests — no Supabase / Railway / external infra.  Mirrors the
asset-embedder smoke pattern (`test_strategy_embedder_honest_smoke.py`) for parity.
"""
from __future__ import annotations

import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from src.research.vector.regime_fingerprints import (
    CANONICAL_REGIMES,
    DIM_NAMES,
    MIN_SHARED_DIMS,
    RegimeFingerprintRow,
    SCHEMA_VERSION,
    TOTAL_DIMS,
    _nan_to_null,
    _null_to_nan,
    backfill,
    compute_row,
    cosine_similarity,
    upsert_rows,
)


# ── Helpers ───────────────────────────────────────────────────────────────────
def _synth_cis(start: str = "2024-01-01", n_days: int = 60, n_syms: int = 8,
                seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    base = pd.Timestamp(start)
    for d_offset in range(n_days):
        date = base + pd.Timedelta(days=d_offset)
        for s in range(n_syms):
            rows.append({
                "date": date,
                "symbol": f"SYM{s}",
                "macro_regime": "RISK_ON" if d_offset < n_days // 2 else "EASING",
                "pillar_f": 50 + rng.normal(0, 5),
                "pillar_m": 50 + rng.normal(0, 5),
                "pillar_o": 50 + rng.normal(0, 5) * 0.1,   # pillar_O = sparse (low variance)
                "pillar_s": 50 + rng.normal(0, 5),
                "pillar_a": 50 + rng.normal(0, 5),
            })
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None) \
        if pd.to_datetime(df["date"]).dt.tz is not None else pd.to_datetime(df["date"])
    return df


def _synth_btc_close(start: str = "2024-01-01", n_days: int = 60, seed: int = 11) -> pd.Series:
    rng = np.random.default_rng(seed)
    base = pd.Timestamp(start)
    rets = rng.normal(0, 0.02, size=n_days)
    prices = 30000.0 * np.exp(np.cumsum(rets))
    idx = pd.date_range(base, periods=n_days, freq="D")
    return pd.Series(prices, index=idx, name="close")


# ── I1 NaN-honesty ────────────────────────────────────────────────────────────
def test_i1_nan_honesty_round_trip():
    """NaN → JSONB null on write → NaN on read.  Anything finite round-trips lossless."""
    assert _null_to_nan(None) is math.nan or not math.isfinite(_null_to_nan(None))
    assert math.isfinite(_null_to_nan(0.5))
    assert _null_to_nan(0.5) == 0.5
    assert _nan_to_null(float("nan")) is None
    assert _nan_to_null(float("inf")) is None
    assert _nan_to_null(-1.2345678) == -1.234568


# ── PIT safety ────────────────────────────────────────────────────────────────
def test_pit_safety_compute_row():
    """compute_row(anchor) only reads cis_daily strictly < anchor."""
    cis = _synth_cis(n_days=10)
    anchor = pd.Timestamp("2024-01-05") + pd.Timedelta(days=4)  # 2024-01-09
    btc = _synth_btc_close(n_days=20)
    row = compute_row(trade_date=anchor, cis_daily=cis, btc_close=btc)
    assert isinstance(row, RegimeFingerprintRow)
    assert row.trade_date == anchor
    assert len(row.vec_full) == TOTAL_DIMS == 12
    assert len(DIM_NAMES) == 12


# ── Cosine on shared dims ─────────────────────────────────────────────────────
def test_cosine_shared_dims_skips_nan():
    """Two vectors with NaN on different dims use only the shared non-NaN subset."""
    a = [0.1, 0.2, float("nan"), 0.4, 0.5, float("nan"), 0.7, 0.8, 0.9, 1.0, 0.1, 0.2]
    b = [0.2, 0.1, 0.3, float("nan"), 0.5, 0.6, float("nan"), 0.9, 0.8, 1.1, 0.0, 0.1]
    sim = cosine_similarity(a, b)
    assert math.isfinite(sim)
    # Cosine of two nearly-parallel shared-dim vectors should be close to 1.
    assert sim > 0.95


# ── MIN_SHARED_DIMS gate ──────────────────────────────────────────────────────
def test_cosine_refuses_below_min_shared_dims():
    """Below MIN_SHARED_DIMS shared coords, cosine_similarity returns NaN."""
    a = [0.1, 0.2, float("nan"), float("nan"), float("nan"),
         float("nan"), float("nan"), float("nan"), float("nan"),
         float("nan"), float("nan"), 0.5]
    b = [0.2, 0.3, 0.4,    0.5,    0.6,
         0.7,    0.8,    0.9,
         1.0,    0.1,    0.2, float("nan")]
    sim = cosine_similarity(a, b)
    assert not math.isfinite(sim)
    assert MIN_SHARED_DIMS == 4


# ── Commutativity ─────────────────────────────────────────────────────────────
def test_cosine_commutativity():
    rng = np.random.default_rng(2026)
    a = [float("nan") if rng.random() < 0.3 else float(v)
         for v in rng.standard_normal(TOTAL_DIMS)]
    b = [float("nan") if rng.random() < 0.3 else float(v)
         for v in rng.standard_normal(TOTAL_DIMS)]
    s_ab = cosine_similarity(a, b)
    s_ba = cosine_similarity(b, a)
    if math.isfinite(s_ab):
        assert math.isclose(s_ab, s_ba, abs_tol=1e-12), f"{s_ab} != {s_ba}"
    else:
        assert not math.isfinite(s_ba)


# ── Schema version round-trip ─────────────────────────────────────────────────
def test_schema_version_round_trip():
    cis = _synth_cis(n_days=20)
    anchor = pd.Timestamp("2024-01-10") + pd.Timedelta(days=9)  # 2024-01-19
    btc = _synth_btc_close(n_days=30)
    row = compute_row(trade_date=anchor, cis_daily=cis, btc_close=btc)
    assert row.schema_version == SCHEMA_VERSION == 3
    payload = row.to_db_tuple()
    # JSON round-trip preserves finite dims, NaN → null.
    encoded = json.loads(json.dumps(payload["vec_full"]))
    for i, orig in enumerate(row.vec_full):
        enc = encoded[i]
        if isinstance(orig, float) and not math.isfinite(orig):
            assert enc is None
        else:
            assert enc == round(float(orig), 6)


# ── Idempotent backfill (deterministic, re-runnable) ─────────────────────────
def test_idempotent_backfill():
    cis = _synth_cis(n_days=20)
    btc = _synth_btc_close(n_days=30)
    rows1 = backfill("2024-01-01", "2024-01-20", cis_daily=cis, btc_close=btc)
    rows2 = backfill("2024-01-01", "2024-01-20", cis_daily=cis, btc_close=btc)
    assert len(rows1) == len(rows2)
    for r1, r2 in zip(rows1, rows2):
        if r1.trade_date != r2.trade_date:
            assert False, f"date mismatch {r1.trade_date} {r2.trade_date}"
        for v1, v2 in zip(r1.vec_full, r2.vec_full):
            if isinstance(v1, float) and math.isnan(v1):
                assert isinstance(v2, float) and math.isnan(v2)
            elif isinstance(v1, float) and math.isinf(v1):
                assert isinstance(v2, float) and math.isinf(v2)
            else:
                assert math.isclose(v1, v2, abs_tol=1e-9)


# ── Macro one-hot deterministic ──────────────────────────────────────────────
def test_macro_one_hot_deterministic_and_canonical():
    """Macro regime dim [0] uses a fixed 1-of-7 mapping; unknown → NEUTRAL."""
    cis = _synth_cis(n_days=15)
    anchor = pd.Timestamp("2024-01-05") + pd.Timedelta(days=4)
    # Drop macro column to force the default.
    no_macro = cis.drop(columns=["macro_regime"]).assign(macro_regime="RISK_ON")
    btc = _synth_btc_close(n_days=20)
    row = compute_row(trade_date=anchor, cis_daily=no_macro, btc_close=btc)
    macro_dim = row.vec_full[0]
    assert math.isfinite(macro_dim)
    assert macro_dim == float(CANONICAL_REGIMES.index("RISK_ON"))


# ── UPSERT batch (best-effort, no infrastructure test) ───────────────────────
def test_upsert_rows_no_supabase_returns_zero():
    """Without SUPABASE env, upsert_rows returns 0 (no exception)."""
    import os
    saved = {k: os.environ.pop(k, None) for k in ("SUPABASE_URL", "SUPABASE_SERVICE_KEY", "SUPABASE_KEY")}
    try:
        cis = _synth_cis(n_days=5)
        btc = _synth_btc_close(n_days=10)
        rows = backfill("2024-01-01", "2024-01-05", cis_daily=cis, btc_close=btc)
        n = upsert_rows(rows)
        assert n == 0
    finally:
        for k, v in saved.items():
            if v is not None:
                os.environ[k] = v


# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    failed = 0
    passed = 0
    test_funcs = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for t in test_funcs:
        try:
            t()
        except SystemExit:
            pass
        except Exception as e:
            failed += 1
            print(f"  ❌ {t.__name__}: {type(e).__name__}: {e}")
            continue
        passed += 1
        print(f"  ✓ {t.__name__}")
    print(f"\n{passed}/{len(test_funcs)} tests passed; {failed} failed")
    sys.exit(1 if failed else 0)
