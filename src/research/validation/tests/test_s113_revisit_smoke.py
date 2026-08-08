"""Smoke tests for s113_revisit_s108_s109_on_687asset (Seth, 2026-08-08).

Six pure-function pins (offline / no live Supabase):
  1. compute_neff() on synthetic returns — N_eff formula correct.
  2. count_s108_episodes() returns the expected shape on synthetic dying-name data.
  3. count_s109_episodes() returns the expected shape on synthetic EUPHORIA-proxy data.
  4. build_layered_report() emits three layer keys + verdict grammar.
  5. run() without supabase creds emits the blocked-stub report (the honest state).
  6. Source-text honesty: does NOT claim live verdict (only "framework-ready").

Each test runs standalone (no pytest) via main() at the bottom.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

import numpy as np
import pandas as pd

from src.research.validation import s113_revisit_s108_s109_on_687asset as r


# ── Test 1: compute_neff formula on synthetic data ───────────────────────────
def t_compute_neff_formula():
    """N_eff should decrease with higher ρ̄ for fixed N."""
    rng = np.random.RandomState(0)
    n_assets = 20
    n_days = 500
    # Low-correlation panel (ρ̄ ≈ 0)
    rets_low = pd.DataFrame(rng.randn(n_days, n_assets),
                            columns=[f"A{i}" for i in range(n_assets)])
    neff_low = r.compute_neff(rets_low)
    # High-correlation panel (ρ̄ ≈ 0.8)
    common = rng.randn(n_days, 1)
    rets_hi = pd.DataFrame(
        0.9 * np.tile(common, (1, n_assets)) + 0.1 * rng.randn(n_days, n_assets),
        columns=[f"A{i}" for i in range(n_assets)],
    )
    neff_hi = r.compute_neff(rets_hi)
    assert neff_low["n_assets"] == n_assets, "n_assets should equal input N"
    assert neff_hi["n_eff"] < neff_low["n_eff"], (
        f"high-ρ panel should have lower N_eff: low={neff_low['n_eff']:.2f}, "
        f"hi={neff_hi['n_eff']:.2f}"
    )
    assert neff_hi["n_eff"] < neff_low["n_eff"] / 3, (
        "high-ρ N_eff should be much smaller than low-ρ N_eff"
    )
    assert neff_hi["rho_bar"] > 0.5, "high-ρ panel should have ρ̄ > 0.5"
    print("  ✓ compute_neff: low-ρ has higher N_eff than high-ρ")


# ── Test 2: count_s108_episodes shape on synthetic dying names ───────────────
def t_count_s108_episodes_shape():
    """S-108 episode counter should return the documented field set."""
    rng = np.random.RandomState(1)
    n_days = 400
    rets = pd.DataFrame(rng.randn(n_days, 5) * 0.02,
                        index=pd.date_range("2024-01-01", periods=n_days, freq="D"),
                        columns=[f"A{i}" for i in range(5)])
    dead_mask = pd.Series({f"A{i}": (i == 0) for i in range(5)}, dtype=bool)
    result = r.count_s108_episodes(rets, dead_mask)
    required = {"n_episodes", "n_positive", "n_negative",
                "pooled_positive_t", "pooled_all_t", "proxy_disclosure"}
    missing = required - set(result.keys())
    assert not missing, f"S-108 result missing fields: {missing}"
    assert "ATS proxy" in result["proxy_disclosure"], \
        "S-108 result must disclose ATS proxy nature"
    print("  ✓ count_s108_episodes returns 6 fields + proxy_disclosure")


# ── Test 3: count_s109_episodes shape on synthetic EUPHORIA data ─────────────
def t_count_s109_episodes_shape():
    """S-109 episode counter should return the documented field set."""
    rng = np.random.RandomState(2)
    n_days = 400
    rets = pd.DataFrame(rng.randn(n_days, 5) * 0.02,
                        index=pd.date_range("2024-01-01", periods=n_days, freq="D"),
                        columns=[f"A{i}" for i in range(5)])
    dead_mask = pd.Series(dtype=bool)  # S-109 doesn't filter by dead
    result = r.count_s109_episodes(rets, dead_mask)
    required = {"n_episodes", "n_positive", "n_negative",
                "pooled_positive_t", "pooled_all_t", "proxy_disclosure"}
    missing = required - set(result.keys())
    assert not missing, f"S-109 result missing fields: {missing}"
    assert "EUPHORIA proxy" in result["proxy_disclosure"], \
        "S-109 result must disclose EUPHORIA proxy nature"
    print("  ✓ count_s109_episodes returns 6 fields + proxy_disclosure")


# ── Test 4: build_layered_report emits three layers + verdict grammar ────────
def t_build_layered_report_keys():
    """Layered report should always emit the three layer keys + verdict."""
    rng = np.random.RandomState(3)
    n_days = 400
    n_assets = 30
    rets = pd.DataFrame(rng.randn(n_days, n_assets) * 0.02,
                        index=pd.date_range("2024-01-01", periods=n_days, freq="D"),
                        columns=[f"A{i}" for i in range(n_assets)])
    panels = {
        "ohlcv_returns": rets,
        "assets": list(rets.columns),
        "is_dead": pd.Series(False, index=rets.columns),
        "coverage": {"earliest": "2024-01-01", "latest": "2025-02-03",
                     "n_obs": n_days, "n_assets": n_assets},
    }
    report = r.build_layered_report(panels)
    for layer_name in ("n_eff_687", "s108_episodes_687", "s109_episodes_687"):
        assert layer_name in report["layers"], f"layer {layer_name} missing"
    verdict = report["verdict"]
    assert "primary" in verdict, "verdict.primary missing"
    assert "breadth_verdict" in verdict, "verdict.breadth_verdict missing"
    assert "s108_verdict" in verdict, "verdict.s108_verdict missing"
    assert "s109_verdict" in verdict, "verdict.s109_verdict missing"
    # Grammar pins
    assert verdict["primary"] in (r.VERDICT_PREMATURE_PANEL,
                                   r.VERDICT_BREADTH_OK, "INCONSISTENT"), \
        f"primary {verdict['primary']} not in grammar"
    print("  ✓ build_layered_report emits 3 layers + verdict grammar")


# ── Test 5: run() without creds emits blocked-stub (the honest state) ────────
def t_run_blocked_stub():
    """Without supabase_url/key, run() must emit blocked-stub with framework_ready=True."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        out_dir = Path(tmp) / "test_s113"
        result = r.run(out_dir)
        assert result["status"] == "blocked", \
            f"expected blocked status, got {result['status']}"
        assert result["framework_ready"] is True, \
            "blocked-stub must mark framework_ready=True (Mac-side can run)"
        assert result["mac_side_runnable"] is True, \
            "blocked-stub must mark mac_side_runnable=True"
        assert "open_risk_blocker" in result, \
            "blocked-stub must disclose OPEN RISK #1 as the blocker"
        assert "service_role" in result["open_risk_blocker"], \
            "blocker must name service_role"
        # Should write verdict.json even on blocked path
        assert (out_dir / "verdict.json").exists(), \
            "blocked-stub must still write verdict.json"
    print("  ✓ run() without creds → blocked-stub + framework_ready=True")


# ── Test 6: source-text honesty — does NOT claim live verdict ────────────────
def t_source_text_honesty():
    """The module docstring must NOT claim a verdict on S-108 or S-109."""
    src = Path(r.__file__).read_text(encoding="utf-8")
    # The framework is honest about being offline / pure-compute
    assert "offline / pure compute" in src or "pure compute" in src, \
        "module must describe itself as offline / pure compute"
    # It must NOT claim a live verdict without data
    assert "primary verdict:" not in src.lower(), \
        "module must NOT prescribe a primary verdict (let data speak)"
    # The expected verdict (PREMATURE_PANEL) is mentioned as a PREDICTION, not a result
    assert "Prediction:" in src or "prediction_rationale" in src, \
        "module must frame PREMATURE_PANEL as prediction, not result"
    # The S-113 baseline numbers must be referenced
    assert "S-113 baseline" in src or "S113_BASELINE" in src, \
        "module must reference S-113 baseline"
    # Service_role blocker must be explicit
    assert "OPEN RISK #1" in src, "module must name OPEN RISK #1 as blocker"
    # The §OHLCV-EXTENSION lever must be named (the real unlock)
    assert "OHLCV-EXTENSION" in src, \
        "module must reference §OHLCV-EXTENSION as the real breadth lever"
    print("  ✓ source text: offline-only, prediction-not-result, names blockers")


# ── run all ──────────────────────────────────────────────────────────────────
_TEST_FUNCS = [
    t_compute_neff_formula,
    t_count_s108_episodes_shape,
    t_count_s109_episodes_shape,
    t_build_layered_report_keys,
    t_run_blocked_stub,
    t_source_text_honesty,
]


def main() -> int:
    failed = 0
    for fn in _TEST_FUNCS:
        try:
            fn()
        except AssertionError as exc:
            print(f"  ✗ {fn.__name__}: {exc}")
            failed += 1
        except Exception as exc:
            print(f"  ✗ {fn.__name__}: {type(exc).__name__}: {exc}")
            failed += 1
    total = len(_TEST_FUNCS)
    passed = total - failed
    print()
    print(f"  {passed}/{total} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
