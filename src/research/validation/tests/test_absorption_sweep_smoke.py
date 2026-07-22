"""
Smoke tests for absorption_sweep — §ABSORPTION-SWEEP runner (Seth, 2026-07-18).
================================================================================
Sandbox-safe: pure numpy, no nautilus / httpx / Mac data. Confirms the runner:
  1. imports cleanly from `src.research.validation.absorption_sweep`
  2. flags a synthetic absorbed sleeve as ABSORBED (no independent survivor)
  3. flags a synthetic orthogonal sleeve as ★ SURVIVOR
  4. honors the ≥60-obs cutoff (returns "INSUFFICIENT DATA")
  5. auto-detects `f_*` factor columns vs sleeve columns
  6. applies the stepwise peer-correction (alpha-vs-peers is computed, not just alpha-vs-factors)
  7. renders the table without crashing
  8. uses compliance-safe language (no buy/sell/avoid/reduce) in any user-facing string

Pattern mirrors `tests/test_vol_sleeve_v2_smoke.py` — regression-resistant assertions on
behavioral shape, not exact numbers.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# Allow `python tests/test_*.py` from repo root without PYTHONPATH gymnastics.
# Test file: src/research/validation/tests/test_absorption_sweep_smoke.py
# parents: [0]=tests, [1]=validation, [2]=research, [3]=src, [4]=REPO_ROOT (looloomi-ai)
_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import numpy as np
import pytest

from src.research.validation.absorption_sweep import (
    FACTOR_PREFIX,
    format_table,
    run_from_csv,
    sweep,
)


# ── fixtures ──────────────────────────────────────────────────────────────────
def _synthetic_panel(n: int = 800, seed: int = 7) -> dict:
    """Build a deterministic factor panel + 2 sleeves (1 absorbed, 1 orthogonal)."""
    rng = np.random.default_rng(seed)
    mkt = rng.normal(0.001, 0.03, n)
    mom = np.sign(np.convolve(mkt, np.ones(30), "same")) * mkt
    quality = rng.normal(0.0003, 0.01, n)
    absorbed = 0.6 * mkt + 0.4 * mom + rng.normal(0, 0.005, n)         # pure beta
    orthogonal = 0.0009 + 0.1 * mkt + rng.normal(0, 0.01, n)            # real α
    return {
        "absorbed_sleeve": absorbed,
        "orthogonal_sleeve": orthogonal,
        "f_market": mkt, "f_momentum": mom, "f_cis_quality": quality,
    }


# ── 1. imports cleanly ────────────────────────────────────────────────────────
def test_imports_sandbox_safe():
    """No nautilus / httpx / live data in the runner — sandbox-runnable."""
    src = (_REPO_ROOT / "src/research/validation/absorption_sweep.py").read_text()
    assert "import nautilus" not in src, "runner must not pull in nautilus"
    assert "import httpx" not in src, "runner must not pull in httpx"
    assert "from src.research.cis_regime_studies" not in src, "wrong layer"
    # runner may use csv stdlib for run_from_csv; that's fine.
    assert "FACTOR_PREFIX" in src


# ── 2. absorbed sleeve is filtered ────────────────────────────────────────────
def test_known_absorbed_sleeve_filtered():
    """A sleeve that's pure beta (market + momentum) must NOT be flagged as a survivor."""
    rows = sweep(_synthetic_panel())
    absorbed = next(r for r in rows if r["sleeve"] == "absorbed_sleeve")
    assert absorbed["independent_survivor"] is False, (
        f"absorbed sleeve wrongly flagged: {absorbed}"
    )
    # verdict either "NOT SIGNIFICANT raw" or "ABSORBED — raw edge is explained..."
    assert ("NOT SIGNIFICANT" in absorbed["verdict"]) or ("ABSORBED" in absorbed["verdict"]), (
        f"absorbed sleeve should be filtered, got: {absorbed['verdict']}"
    )


# ── 3. orthogonal sleeve survives ─────────────────────────────────────────────
def test_known_orthogonal_sleeve_survives():
    """A sleeve with real α independent of factors + peers must be flagged ★ SURVIVOR."""
    rows = sweep(_synthetic_panel())
    orth = next(r for r in rows if r["sleeve"] == "orthogonal_sleeve")
    assert orth["independent_survivor"] is True, (
        f"orthogonal sleeve should survive, got: {orth}"
    )
    # The runner exposes this as `residual_alpha` (the friendlier name)
    assert orth["residual_alpha"] is True
    assert orth["alpha_t_vs_peers"] is not None, "peer-correction step not run"
    assert abs(orth["alpha_t_vs_peers"]) > 1.96


# ── 4. minimum-obs cutoff ─────────────────────────────────────────────────────
def test_minimum_obs_cutoff():
    """< 60 obs returns INSUFFICIENT DATA, not a misleading verdict."""
    panel = _synthetic_panel(n=50)  # below cutoff
    rows = sweep(panel)
    assert all("INSUFFICIENT" in r["verdict"] for r in rows), (
        f"expected INSUFFICIENT verdict, got: {[r['verdict'] for r in rows]}"
    )


# ── 5. f_ prefix auto-detects factors vs sleeves ──────────────────────────────
def test_factor_prefix_auto_detection():
    """Columns prefixed `f_` are factors; everything else is a sleeve."""
    data = _synthetic_panel()
    rows = sweep(data)  # no explicit factor_cols / sleeve_cols → auto-detect
    sleeve_names = [r["sleeve"] for r in rows]
    assert "absorbed_sleeve" in sleeve_names
    assert "orthogonal_sleeve" in sleeve_names
    assert "f_market" not in sleeve_names
    assert "f_momentum" not in sleeve_names
    # explicit override still works
    rows2 = sweep(data, sleeve_cols=["orthogonal_sleeve"], factor_cols=["f_market"])
    assert [r["sleeve"] for r in rows2] == ["orthogonal_sleeve"]


# ── 6. stepwise peer-correction actually changes the picture ─────────────────
def test_peer_correction_is_computed():
    """When a sibling sleeve is added, the alpha_t value should reflect it.
    With one sleeve in the universe, peer-correction has nothing to add — but
    `alpha_t_vs_peers` must still be present (the runner should not silently skip)."""
    rows = sweep(_synthetic_panel())
    for r in rows:
        assert "alpha_t_vs_peers" in r, f"peer-correction field missing on {r['sleeve']}"
        # With ≥1 other sleeve, peer-correction is attempted.
        # It may equal alpha_t (no peer overlap) or differ (peer absorbs some α).
        assert r["alpha_t_vs_peers"] is not None, (
            f"peer-correction should be attempted, got None for {r['sleeve']}"
        )


# ── 7. table renders without crashing ────────────────────────────────────────
def test_format_table_renders():
    rows = sweep(_synthetic_panel())
    table = format_table(rows)
    assert isinstance(table, str) and len(table) > 0
    # key header columns present
    for col in ("rawAnn", "rawT", "αAnn", "αT", "αT|peers", "verdict"):
        assert col in table, f"missing column header: {col}"
    # survivor line at bottom
    assert "INDEPENDENT SURVIVORS" in table
    assert "orthogonal_sleeve" in table  # the only survivor in our synth set


# ── 8. compliance language ────────────────────────────────────────────────────
def test_compliance_language():
    """No buy/sell/avoid/reduce in any string the runner produces — positioning language only."""
    rows = sweep(_synthetic_panel())
    table = format_table(rows)
    blob = table.lower() + " " + (_REPO_ROOT / "src/research/validation/absorption_sweep.py").read_text().lower()
    forbidden = ["buy", "sell", "avoid", "reduce", "accumulate", "long-short"]
    for word in forbidden:
        # word-boundary check to avoid flagging "accumulation" of alpha_t
        if re.search(rf"\b{word}\b", blob):
            pytest.fail(f"compliance violation: forbidden word '{word}' in runner output or source")


# ── 9. CSV contract honored by run_from_csv ──────────────────────────────────
def test_run_from_csv(tmp_path):
    """The CSV contract documented in absorption_sweep.py header must round-trip."""
    data = _synthetic_panel(n=200)
    dates = [f"2025-{(i // 30) + 1:02d}-{(i % 30) + 1:02d}" for i in range(200)]
    csv_path = tmp_path / "sleeves.csv"
    cols = list(data.keys())
    with open(csv_path, "w") as fh:
        fh.write("date," + ",".join(cols) + "\n")
        for i, d in enumerate(dates):
            fh.write(d + "," + ",".join(f"{data[c][i]:.6f}" for c in cols) + "\n")
    rows = run_from_csv(str(csv_path))
    assert isinstance(rows, list) and len(rows) == 2  # both sleeves, factors auto-filtered


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))