"""T-071 — Strategy 4 (5 spec equal weight) daily series integrity tests.

The JSON lives at
  /Users/sbb/Projects/looloomi-ai-lane-c/research/series/strategy4_blend_daily.json
and is produced by `research/series/export_strategy4_daily.py`, which reuses
the M-208h sealed spec functions + 10bp turnover cost formula.

T-071 acceptance (per card):
  1. Dates are unique and strictly increasing.
  2. No NaN values in `ret`.
  3. 2025-01-01 → 2026-08-13 compound return within 0.5pp of the M-208h
     C2 reported value (+16.77%).
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

JSON_PATH = Path(__file__).resolve().parent.parent / "research" / "series" / "strategy4_blend_daily.json"
TARGET_OOS_CUM = 0.1677  # M-208h C2 reported, rounded
TOLERANCE_PP = 0.5       # 0.5 percentage points


def _load() -> dict:
    assert JSON_PATH.exists(), (
        f"missing {JSON_PATH} — run `python3 research/series/export_strategy4_daily.py` first"
    )
    with open(JSON_PATH) as f:
        return json.load(f)


def test_top_level_schema():
    d = _load()
    for key in ("rows", "specs", "weights", "cost_bps", "as_of", "script"):
        assert key in d, f"missing top-level key {key!r}"
    assert d["weights"] == "equal"
    assert isinstance(d["cost_bps"], (int, float))
    assert d["cost_bps"] > 0
    assert isinstance(d["rows"], list) and d["rows"], "rows must be non-empty"
    assert len(d["specs"]) == 5, f"expected 5 specs, got {len(d['specs'])}"


def test_specs_match_m208h():
    d = _load()
    expected = ["m86", "m87", "m88-base", "m113", "m115"]
    assert sorted(d["specs"]) == sorted(expected), (
        f"spec list {d['specs']!r} does not match M-208h 5-spec set {expected!r}"
    )


def test_dates_unique_and_increasing():
    d = _load()
    dates = [r["d"] for r in d["rows"]]
    assert len(dates) == len(set(dates)), f"duplicate dates: {len(dates)} vs {len(set(dates))} unique"
    assert dates == sorted(dates), "dates are not in non-decreasing order"
    # Strictly increasing (no duplicates AND no ties)
    for a, b in zip(dates, dates[1:]):
        assert a < b, f"dates are not strictly increasing: {a} >= {b}"


def test_no_nan_in_ret():
    d = _load()
    for i, r in enumerate(d["rows"]):
        v = r["ret"]
        assert isinstance(v, (int, float)), f"row {i} ret is not a number: {v!r}"
        assert not math.isnan(v), f"row {i} ({r['d']}) has NaN ret"
        assert math.isfinite(v), f"row {i} ({r['d']}) has non-finite ret: {v!r}"


def test_first_date_is_2023_01_02():
    d = _load()
    first = d["rows"][0]["d"]
    assert first >= "2023-01-02", f"first date {first} is before 2023-01-02"


def test_oos_compound_matches_m208h():
    """2025-01-01 → 2026-08-13 compound must be within 0.5pp of M-208h C2 +16.77%."""
    d = _load()
    oos = [r for r in d["rows"] if "2025-01-01" <= r["d"] <= "2026-08-13"]
    assert len(oos) > 100, f"OOS window too small: {len(oos)} days"

    nav = 1.0
    for r in oos:
        nav *= (1 + r["ret"])
    cum = nav - 1

    delta_pp = abs(cum - TARGET_OOS_CUM) * 100
    assert delta_pp < TOLERANCE_PP, (
        f"OOS compound {cum*100:.4f}% differs from M-208h C2 {TARGET_OOS_CUM*100:.2f}% "
        f"by {delta_pp:.4f}pp (tolerance {TOLERANCE_PP}pp)"
    )
