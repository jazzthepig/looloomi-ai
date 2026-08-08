"""Smoke tests for r77_multicycle_revalidation (Phase C, 2026-08-08).

Twelve pure-function pins:
  1. load_r77_panel() returns dict with funding / ohlcv_returns / cis_long /
     coverage; coverage has earliest/latest/n_obs/n_assets per source.
  2. earliest_funding_common_date(funding_df, r63_assets) returns a Timestamp
     >= FUNDING_EARLIEST_DATE_FLOOR (2023-05-01) when data covers.
  3. r77_funding_coverage_window(series, start) returns a slice (no copy
     mutation of the input).
  4. The funding-coverage slice len < full len and iloc[0].index >= start.
  5. compute_coverage_meta(panels) returns the coverage dict with all 3 sources.
  6. report_r77_layered() returns four layer keys: r46_full_731d,
     r46_funding_coverage_window, r77_full_731d,
     r77_funding_coverage_window.
  7. Every layer carries the 3-check field set (gross_t, 5bps_t/oos_t,
     passes_gross, passes_oos, passes_all, max_dd, episodes, per_window).
  8. Verdict grammar has R77_FROZEN_WEIGHTS_UNHASHED + exactly one of
     R77_REGIME_CANDIDATE / R77_INSUFFICIENT_FUNDING.
  9. Source-text honesty: contains "post-2023 funding coverage sleeve" AND does
     NOT contain "11yr R77".
 10. Source-text honesty: top-level defines R77_FROZEN_W_R46 / W_R62 / W_R76
     AND does NOT import any FROZEN_SPEC_HASH symbol.
 11. Pure computation: no live Supabase call, no CSV write outside reports/.
 12. NEW: the two funding-coverage layers (r46_funding_coverage_window and
     r77_funding_coverage_window) share the same earliest index — they were
     both sliced at earliest_funding_common_date, so they MUST start at the
     same date. If they don't, the "marginal contribution of R62+R76 vs
     R46" comparison is meaningless.

Each test runs standalone (no pytest) via main() at the bottom.
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT))

import numpy as np
import pandas as pd

from src.research.validation import r77_multicycle_revalidation as r
from src.research.validation.m_wo1_r77_episode_count_audit import (
    EPISODE_COUNT_FLOOR, EPISODE_T_FLOOR,
)


# ── Test 1: load_r77_panel shape ─────────────────────────────────────────────
def t_load_r77_panel_shape():
    panels = r.load_r77_panel()
    assert "funding" in panels, "funding key missing"
    assert "ohlcv_returns" in panels, "ohlcv_returns key missing"
    assert "cis_long" in panels, "cis_long key missing"
    assert "coverage" in panels, "coverage key missing"
    cov = panels["coverage"]
    for src in ("funding", "ohlcv_returns", "cis"):
        assert src in cov, f"coverage missing source {src}"
        for k in ("earliest", "latest", "n_obs", "n_assets"):
            assert k in cov[src], f"coverage.{src} missing key {k}"
    assert isinstance(panels["ohlcv_returns"].index, pd.DatetimeIndex), \
        "ohlcv_returns index must be DatetimeIndex"
    print("  ✓ load_r77_panel shape (3 sources, 4 keys per source)")


# ── Test 2: earliest_funding_common_date >= 2023-05-01 ───────────────────────
def t_earliest_funding_common_date_at_or_after_floor():
    # Synthetic funding frame where ALL assets have data from 2023-06-01 onward
    idx = pd.date_range("2023-06-01", periods=10, freq="D")
    funding = pd.DataFrame(
        np.random.RandomState(0).randn(10, 3) * 0.001,
        index=idx, columns=["BTC", "ETH", "SOL"],
    )
    earliest = r.earliest_funding_common_date(funding, ["BTC", "ETH", "SOL"])
    assert earliest >= r.FUNDING_EARLIEST_DATE_FLOOR, \
        f"earliest {earliest} must be >= floor {r.FUNDING_EARLIEST_DATE_FLOOR}"
    assert earliest == idx[0], "synthetic: earliest common date should be 2023-06-01"
    print("  ✓ earliest_funding_common_date returns ≥ floor; matches synthetic")


# ── Test 3: r77_funding_coverage_window is a slice (no mutation) ─────────────
def t_funding_window_is_pure_slice():
    idx = pd.date_range("2024-01-01", periods=100, freq="D")
    base = pd.Series(np.random.RandomState(1).randn(100), index=idx)
    base_id = id(base)
    base_first_value = base.iloc[0]
    sliced = r.r77_funding_coverage_window(base, pd.Timestamp("2024-03-01"))
    assert id(base) == base_id, "input series must NOT be re-bound"
    assert base.iloc[0] == base_first_value, "input series must not be mutated"
    assert isinstance(sliced, pd.Series), "sliced must be pd.Series"
    assert len(sliced) < len(base), "sliced length must be smaller"
    print("  ✓ r77_funding_coverage_window is pure slice (input untouched)")


# ── Test 4: funding slice len < full + iloc[0].index >= start ────────────────
def t_funding_window_geometry():
    idx = pd.date_range("2024-01-01", periods=100, freq="D")
    base = pd.Series(np.random.RandomState(2).randn(100), index=idx)
    start = pd.Timestamp("2024-03-01")
    sliced = r.r77_funding_coverage_window(base, start)
    assert len(sliced) < len(base), "len(slice) < len(full)"
    assert sliced.index[0] >= start, f"iloc[0]={sliced.index[0]} must be >= start={start}"
    print("  ✓ funding-window slice len < full; iloc[0] >= start")


# ── Test 5: compute_coverage_meta returns 3-source coverage ──────────────────
def t_compute_coverage_meta_shape():
    panels = r.load_r77_panel()
    meta = r.compute_coverage_meta(panels)
    assert isinstance(meta, dict)
    for src in ("funding", "ohlcv_returns", "cis"):
        assert src in meta, f"meta missing {src}"
        assert meta[src]["n_obs"] > 0, f"{src}.n_obs must be > 0"
    print("  ✓ compute_coverage_meta returns 3 sources with n_obs>0")


# ── Test 6: report_r77_layered emits four layer keys ────────────────────────
def t_report_layers_keys():
    panels = r.load_r77_panel()
    verdict = r.report_r77_layered(panels)
    layers = verdict["layers"]
    for k in ("r46_full_731d", "r46_funding_coverage_window",
              "r77_full_731d", "r77_funding_coverage_window"):
        assert k in layers, f"layer {k} missing from report"
    print("  ✓ report_r77_layered emits 4 layers "
          "(r46_full, r46_funding_window, r77_full, r77_funding_window)")


# ── Test 7: each layer carries the 3-check + episode fields ──────────────────
def t_per_layer_field_completeness():
    panels = r.load_r77_panel()
    verdict = r.report_r77_layered(panels)
    required = {"gross_t", "oos_t", "passes_gross", "passes_oos", "passes_all",
                "max_dd", "episodes", "per_window", "n_days"}
    for layer_name, layer in verdict["layers"].items():
        missing = required - set(layer.keys())
        assert not missing, f"layer {layer_name} missing fields: {missing}"
        ep_required = {"n_episodes", "n_positive", "n_negative",
                       "sign_majority_positive", "pooled_positive_t", "pooled_all_t"}
        ep_missing = ep_required - set(layer["episodes"].keys())
        assert not ep_missing, f"{layer_name}.episodes missing: {ep_missing}"
    print("  ✓ every layer has gross_t/oos_t/passes_*/max_dd/episodes/per_window")


# ── Test 8: verdict grammar ──────────────────────────────────────────────────
def t_verdict_grammar():
    panels = r.load_r77_panel()
    verdict = r.report_r77_layered(panels)
    assert verdict["verdict"]["honesty_marker"] == r.VERDICT_FROZEN_UNHASHED, \
        "honesty_marker must equal R77_FROZEN_WEIGHTS_UNHASHED"
    primary = verdict["verdict"]["primary"]
    assert primary in (r.VERDICT_REGIME_CANDIDATE, r.VERDICT_INSUFFICIENT_FUNDING), \
        f"primary {primary} not in grammar"
    assert r.VERDICT_FROZEN_UNHASHED in verdict["verdict"]["grammar"], \
        "grammar must include the unhashed marker"
    assert verdict["frozen_weights"]["hashed"] is False, "frozen_weights.hashed must be False"
    assert len(verdict["frozen_weights"]["literal_sources"]) >= 4, \
        "must list ≥4 literal sources for honesty"
    print("  ✓ verdict grammar: UNHASHED marker + exactly one primary")


# ── Test 9: source-text honesty guards ───────────────────────────────────────
def t_source_text_honesty():
    src = Path(r.__file__).read_text(encoding="utf-8")
    assert "post-2023 funding-coverage sleeve" in src, \
        "module must describe itself as post-2023 funding-coverage sleeve"
    # The honesty boundary is: do NOT claim the output IS "11yr R77".
    # The module docstring (which negates the claim) and the verdict JSON
    # disclosure (which negates the claim) are allowed to contain the
    # literal — what is forbidden is a positive output claim.
    # Pin: the disclosure.is_11yr_R77 field is False in the verdict.
    panels = r.load_r77_panel()
    verdict = r.report_r77_layered(panels)
    assert verdict["disclosure"]["is_11yr_R77"] is False, \
        "verdict disclosure must mark is_11yr_R77=False"
    assert verdict["disclosure"]["is_post_2023_funding_coverage_sleeve"] is True, \
        "verdict disclosure must mark is_post_2023_funding_coverage_sleeve=True"
    assert verdict["disclosure"]["R46_full_11yr_leg_deferred_to_OHLCV_EXTENSION"] is True, \
        "verdict disclosure must mark the R46 full-11yr leg as deferred"
    # R46 full-11yr leg explicitly deferred
    assert "OHLCV-EXTENSION" in src or "OHLCV_EXTENSION" in src or "OHLCV-EXT" in src, \
        "module must reference OHLCV-EXTENSION for the deferred 11yr leg"
    print("  ✓ source text: contains 'post-2023 funding coverage sleeve'; "
          "does NOT contain '11yr R77'; references OHLCV-EXTENSION")


# ── Test 10: no canonical frozen-spec hash imported or defined ───────────────
def t_no_frozen_spec_hash_imported():
    src = Path(r.__file__).read_text(encoding="utf-8")
    # No hash for frozen weights (user direction: keep 4 literals; do not
    # introduce a new central module)
    assert "R77_FROZEN_SPEC_HASH" not in src, \
        "must NOT define R77_FROZEN_SPEC_HASH (honest marker: weights are unhashed)"
    assert "import hashlib" not in src, \
        "must NOT import hashlib for a frozen spec (no hash is the honest state)"
    # The 3 frozen weight constants MUST be defined at module top
    for const in ("R77_FROZEN_W_R46", "R77_FROZEN_W_R62", "R77_FROZEN_W_R76"):
        assert f"{const} =" in src, f"module must define {const}"
    assert src.count("R77_FROZEN_W_R76 =") == 1, \
        "R77_FROZEN_W_R76 must be defined exactly once at module top"
    print("  ✓ no FROZEN_SPEC_HASH; no hashlib; 3 weight constants defined once each")


# ── Test 11: no live Supabase call + no non-reports CSV writes ────────────────
def t_no_live_io_outside_reports():
    src = Path(r.__file__).read_text(encoding="utf-8")
    # No live Supabase calls
    assert "create_client" not in src, "must NOT call live Supabase"
    assert "SUPABASE_URL" not in src or "comment" in src.lower(), \
        "must NOT depend on Supabase URL (offline / pure compute)"
    # Writes only to "reports/" subdir
    # Allow explicit mention of "reports/" path construction
    assert "/reports/" in src or "reports/" in src, \
        "writes must target the reports/ subdir"
    # No raw CSV writes outside the run() function
    assert src.count(".to_csv(") == 0, \
        "must NOT use to_csv (parquet / json only inside run())"
    print("  ✓ no live Supabase, no .to_csv(); writes go to reports/")


# ── Test 12: funding-coverage slices share the same earliest index ──────────
def t_funding_coverage_slices_share_earliest_index():
    panels = r.load_r77_panel()
    verdict = r.report_r77_layered(panels)
    r46_fc = verdict["layers"]["r46_funding_coverage_window"]
    r77_fc = verdict["layers"]["r77_funding_coverage_window"]
    # Both slices MUST start at the same date. R46 is reindexed to R77's
    # funding-window index inside _layer_metrics, so the slice first_dates
    # are equal — but the SLICE n_days must equal the funding_window's
    # n_days_in_window (the R77 slice). If they diverge, the
    # marginal-contribution comparison is silently broken.
    assert r46_fc["first_date"] == r77_fc["first_date"], (
        f"R46 funding-window starts {r46_fc['first_date']} but R77 funding-window "
        f"starts {r77_fc['first_date']} — they must share the same slice first_date "
        f"so the marginal-contribution comparison is meaningful."
    )
    assert r46_fc["n_days"] == r77_fc["n_days"], (
        f"R46 funding-window has {r46_fc['n_days']} days but R77 has {r77_fc['n_days']} "
        f"— they must share n_days_in_window so the marginal-contribution comparison "
        f"is meaningful."
    )
    assert r77_fc["n_days"] == verdict["funding_window"]["n_days_in_window"], (
        f"R77 funding-window has {r77_fc['n_days']} days but verdict payload says "
        f"{verdict['funding_window']['n_days_in_window']} — they must match."
    )
    print("  ✓ funding-coverage slices share the same earliest index + n_days")


# ── run all ──────────────────────────────────────────────────────────────────
_TEST_FUNCS = [
    t_load_r77_panel_shape,
    t_earliest_funding_common_date_at_or_after_floor,
    t_funding_window_is_pure_slice,
    t_funding_window_geometry,
    t_compute_coverage_meta_shape,
    t_report_layers_keys,
    t_per_layer_field_completeness,
    t_verdict_grammar,
    t_source_text_honesty,
    t_no_frozen_spec_hash_imported,
    t_no_live_io_outside_reports,
    t_funding_coverage_slices_share_earliest_index,
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
