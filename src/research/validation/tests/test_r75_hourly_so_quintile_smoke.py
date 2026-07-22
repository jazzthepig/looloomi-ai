"""Sandbox-safe smoke tests for R75 genuine-hourly S/O research."""
from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

from src.research.validation.r75_hourly_so_quintile import (
    MIN_ASSETS,
    align_score_to_next_bar,
    build_hourly_pillar_panel,
    delta_score,
    hourly_ls,
    load_hourly_returns,
    maturity_status,
    normalize_hourly_history,
)


def _rows(start="2026-07-01T00:00:00Z", hours=4, symbol_offset=0):
    base = pd.Timestamp(start)
    out = []
    for i in range(hours):
        ts = base + pd.Timedelta(hours=i)
        out.append({
            "recorded_at": ts.isoformat(),
            "pillar_s": 40.0 + symbol_offset + i,
            "pillar_o": 60.0 + symbol_offset + 2 * i,
        })
    return out


def test_normalize_hourly_uses_latest_real_snapshot():
    rows = _rows(hours=2)
    rows += [{"recorded_at": "2026-07-01T00:55:00Z", "pillar_s": 99.0, "pillar_o": 88.0}]
    series, meta = normalize_hourly_history(rows, "S")
    assert len(series) == 2
    assert series.loc[pd.Timestamp("2026-07-01 00:00:00")] == 99.0
    assert meta["duplicate_rows"] == 1


def test_normalize_does_not_fabricate_missing_hours():
    rows = [_rows(hours=1)[0], _rows(start="2026-07-01T03:00:00Z", hours=1)[0]]
    series, _ = normalize_hourly_history(rows, "O")
    assert list(series.index) == [pd.Timestamp("2026-07-01 00:00:00"), pd.Timestamp("2026-07-01 03:00:00")]
    assert pd.Timestamp("2026-07-01 01:00:00") not in series.index


def test_null_pillars_stay_unmeasured():
    rows = [{"recorded_at": "2026-07-01T00:00:00Z", "pillar_s": None}]
    series, meta = normalize_hourly_history(rows, "S")
    assert series.empty
    assert meta["unique_hours"] == 0


def test_panel_shape_and_symbols():
    panel, _ = build_hourly_pillar_panel({"btc": _rows(), "ETH": _rows(symbol_offset=2)}, "O")
    assert panel.shape == (4, 2)
    assert list(panel.columns) == ["BTC", "ETH"]


def test_delta_requires_exact_hourly_predecessor():
    idx = pd.DatetimeIndex(["2026-07-01 00:00", "2026-07-01 01:00", "2026-07-01 03:00"])
    panel = pd.DataFrame({"BTC": [10.0, 12.0, 20.0]}, index=idx)
    positive = delta_score(panel, 1, "positive")
    assert positive.loc[idx[1], "BTC"] == 2.0
    assert np.isnan(positive.loc[idx[2], "BTC"]), "03:00 must not use the 01:00 row as a fake 1h predecessor"


def test_stability_score_prefers_small_absolute_delta():
    idx = pd.date_range("2026-07-01", periods=2, freq="h")
    panel = pd.DataFrame({"STABLE": [50.0, 50.5], "UNSTABLE": [50.0, 60.0]}, index=idx)
    stable = delta_score(panel, 1, "stable")
    assert stable.iloc[1]["STABLE"] > stable.iloc[1]["UNSTABLE"]


def test_next_bar_alignment_has_one_hour_lag():
    idx = pd.date_range("2026-07-01", periods=3, freq="h")
    score = pd.DataFrame({"BTC": [1.0, 2.0, 3.0]}, index=idx)
    aligned = align_score_to_next_bar(score, idx)
    assert np.isnan(aligned.iloc[0, 0])
    assert aligned.iloc[1, 0] == 1.0
    assert aligned.iloc[2, 0] == 2.0


def test_hourly_ls_stability_direction_and_inverse():
    idx = pd.date_range("2026-07-01", periods=12, freq="h")
    assets = [f"A{i:02d}" for i in range(MIN_ASSETS)]
    score = pd.DataFrame({a: [float(i)] * len(idx) for i, a in enumerate(assets)}, index=idx)
    returns = pd.DataFrame({a: [i / 10000.0] * len(idx) for i, a in enumerate(assets)}, index=idx)
    forward = hourly_ls(score, returns, min_assets=MIN_ASSETS, k=5)
    inverse = hourly_ls(-score, returns, min_assets=MIN_ASSETS, k=5)
    assert forward.iloc[1:].mean() > 0
    assert abs(forward.iloc[1:].mean() + inverse.iloc[1:].mean()) < 1e-12


def test_maturity_gate_is_frozen_at_30d_720h_12assets():
    assets = [f"A{i:02d}" for i in range(MIN_ASSETS)]
    short_idx = pd.date_range("2026-07-01", periods=240, freq="h")
    long_idx = pd.date_range("2026-06-01", periods=744, freq="h")
    short = pd.DataFrame(1.0, index=short_idx, columns=assets)
    long = pd.DataFrame(1.0, index=long_idx, columns=assets)
    assert not maturity_status({"S": short, "O": short})["mature"]
    assert maturity_status({"S": long, "O": long})["mature"]


def test_hourly_return_loader_uses_real_parquet_only():
    with tempfile.TemporaryDirectory() as td:
        path = Path(td) / "BTC.parquet"
        frame = pd.DataFrame({
            "timestamp": pd.date_range("2026-07-01", periods=4, freq="h", tz="UTC"),
            "close": [100.0, 101.0, 102.0, 104.0],
        })
        frame.to_parquet(path)
        rets = load_hourly_returns(["BTC"], Path(td))
        assert list(rets.columns) == ["BTC"]
        assert abs(rets.iloc[-1, 0] - (104.0 / 102.0 - 1.0)) < 1e-12


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for test in tests:
        test()
        print(f"  ✓ {test.__name__}")
    print(f"\n✅ {len(tests)}/{len(tests)} R75 smoke tests passed")
