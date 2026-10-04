"""
A-408-5 strategy + paper_trading loops smoke test
==================================================

8 paper_trading + 1 strategy loop wired to `_record_loop_attempt`:

  Class A (`_mark_within_valuation_window` shape, 7 loops):
    - _causal_paper_loop     / _dingge_paper_loop  / _combined_book_loop
    - _scalable_book_loop    / _beta_core_loop     / _two_layer_paper_loop
    - _fusion_paper_loop
  Class B (`_classify(res)` direct, 1 loop):
    - _factor_tilt_loop
  Class C (independent S-292 shape, 1 loop):
    - _treasury_decisions_loop

Class A/B share `_mark_within_valuation_window`/`_classify` semantics
(_ok/_ref/_why). Class C is independent.

This test enforces the wire-up:
  T25: site counts — 9 loops × 2 sites each = 18 total
  T26: Class A outcome enum + name attribution in detail (nav/status)
  T27: Class A `_beta_core_loop` FoF benchmark fields (nav/benchmark_nav/
       excess_pct/regime) preserved
  T28: Class B `_factor_tilt_loop` uses `_classify(res)` not
       `_mark_within_valuation_window`
  T29: Class C `_treasury_decisions_loop` has NO refused path (S-292:
       failure is always a fault, never "by-rules refused")
  T30: REPLAY — cumulative loops count ≥ 19 (8 from A-408-5 + 11 from
       prior families). Confirms the wire-up doesn't overlap / clobber.

Pure Python, no DB / no network / no secrets.
"""
import sys
import re
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[4]


def _main_src():
    return (_ROOT / "src/api/main.py").read_text()


def _body(name):
    src = _main_src()
    m = re.search(
        rf'^async def ({re.escape(name)})\(\):',
        src, re.MULTILINE)
    if not m:
        return None
    s = m.start()
    e = src.find('\nasync def ', s+1)
    if e == -1:
        e = s + 5000
    return src[s:e]


# T25: site counts — 9 loops × 2 sites each
def test_t25_site_count_per_loop():
    LOOPS = [
        '_treasury_decisions_loop',
        '_causal_paper_loop',
        '_dingge_paper_loop',
        '_combined_book_loop',
        '_scalable_book_loop',
        '_beta_core_loop',
        '_two_layer_paper_loop',
        '_fusion_paper_loop',
        '_factor_tilt_loop',
    ]
    fails = []
    for name in LOOPS:
        body = _body(name)
        if body is None:
            fails.append(f"{name}: not found")
            continue
        n = len(re.findall(
            rf'_record_loop_attempt\(\s*[\"\']({re.escape(name)})[\"\']',
            body))
        if n != 2:
            fails.append(f"{name}: {n} sites (need exactly 2)")
        else:
            print(f"  - {name}: {n} sites")
    assert not fails, "site count failures: " + "; ".join(fails)
    print("✓ T25: 9 loops × 2 sites = 18 total wired")


# T26: Class A outcome enum + key detail field
def test_t26_class_a_outcome_and_detail():
    LOOPS_A = [
        '_causal_paper_loop',
        '_dingge_paper_loop',
        '_combined_book_loop',
        '_scalable_book_loop',
        '_beta_core_loop',
        '_two_layer_paper_loop',
        '_fusion_paper_loop',
    ]
    for name in LOOPS_A:
        body = _body(name)
        # The ternary must appear: "ok" if _ok else "refused" if _ref else "error"
        assert ('"ok" if _ok else "refused" if _ref else "error"'
                in body), (
            f"{name}: missing ok/refused/error ternary")
        # detail must include status + nav
        assert 'res.get("status")' in body, (
            f"{name}: detail missing status field")
        assert 'res.get("nav")' in body, (
            f"{name}: detail missing nav field")
        # writer field must match name
        assert f'writer="src.api.main.{name}"' in body, (
            f"{name}: writer field mismatch")
        # Exception path must also exist
        assert 'reason=f"{type(_e).__name__}: {str(_e)[:300]}"' in body, (
            f"{name}: exception path missing")
    print(f"✓ T26: Class A 7 loops outcome enum + detail fields + writer "
          f"all consistent")


# T27: _beta_core_loop FoF benchmark fields preserved
def test_t27_beta_core_loop_benchmark_fields():
    body = _body('_beta_core_loop')
    # Per the docstring + §5b: nav/benchmark_nav/excess_pct/regime/cap
    for field in ("nav", "benchmark_nav", "excess_pct",
                  "exposure_cap", "regime"):
        assert field in body, (
            f"_beta_core_loop: detail must capture '{field}' (FoF benchmark "
            f"audit needs actual NAV state, not just ok)")
    print("✓ T27: _beta_core_loop captures FoF benchmark fields "
          "(nav/benchmark_nav/excess_pct/exposure_cap/regime)")


# T28: Class B _factor_tilt_loop uses _classify(res) (not valuation window)
def test_t28_factor_tilt_loop_uses_classify():
    body = _body('_factor_tilt_loop')
    assert '_classify(res)' in body, (
        "_factor_tilt_loop must use _classify(res) directly (Class B)")
    assert '_mark_within_valuation_window' not in body, (
        "_factor_tilt_loop must NOT use _mark_within_valuation_window "
        "(Class B uses _classify only)")
    # Class A/B share ternary shape but Class B captures factor attribution
    for field in ("today_return", "factor_sharpe",
                  "max_single_factor_sharpe_share", "n_days_marked"):
        assert field in body, (
            f"_factor_tilt_loop: detail must capture '{field}' "
            f"(factor attribution audit)")
    print("✓ T28: _factor_tilt_loop uses _classify + factor attribution fields")


# T29: Class C _treasury_decisions_loop has NO refused outcome (S-292)
def test_t29_treasury_decisions_loop_no_refused():
    body = _body('_treasury_decisions_loop')
    # Per inline S-292: failure is always a fault, not by-rules refused.
    # Outcomes should only be "ok" / "error".
    outcomes = re.findall(r'"(ok|refused|error)"\s+if', body)
    assert 'refused' not in outcomes, (
        f"_treasury_decisions_loop has 'refused' outcome — S-292 design "
        f"intent forbids it (failure is always a fault). "
        f"Outcomes found: {outcomes}")
    # errors list captured (S-292: errors[] is the diagnostic surface)
    assert 'res.get("errors")' in body, (
        "_treasury_decisions_loop must capture errors[] list")
    print(f"✓ T29: _treasury_decisions_loop outcomes={outcomes} (S-292 enforced)")


# T30: REPLAY — cumulative loops count ≥ 19 (11 prior + 8 from this batch)
def test_t30_replay_cumulative_loops():
    src = _main_src()
    targets = [
        # A-408-2 / A-408-2b/c family (7)
        '_cg_panel_loop', '_hl_book_loop', '_tokenization_tilt_loop',
        '_allocation_loop', '_channels_loop', '_interpret_loop',
        '_style_header_loop',
        # A-408-4 family (4)
        '_forward_record_loop', '_deep_panel_loop',
        '_hyperliquid_loop', '_market_state_loop',
        # A-408-5 family (9 — including treasury)
        '_treasury_decisions_loop',
        '_causal_paper_loop', '_dingge_paper_loop',
        '_combined_book_loop', '_scalable_book_loop',
        '_beta_core_loop', '_two_layer_paper_loop',
        '_fusion_paper_loop', '_factor_tilt_loop',
    ]
    found = 0
    for name in targets:
        body = _body(name)
        if body is None:
            continue
        n = len(re.findall(
            rf'_record_loop_attempt\(\s*[\"\']({re.escape(name)})[\"\']',
            body))
        if n >= 2:
            found += 1
            print(f"  - {name}: {n} sites")
    assert found >= 19, (
        f"cumulative loops count {found} (need ≥ 19: 7+4+9 = 20 wired)")
    print(f"✓ T30: REPLAY — {found} loops cumulative wired")


if __name__ == "__main__":
    print("── A-408-5 / S-408-5 strategy + paper_trading loops smoke ──")
    tests = sorted(
        [(k, v) for k, v in globals().items()
         if k.startswith("test_t")],
        key=lambda kv: int(kv[0].split("_t")[1].split("_")[0]))
    fails = []
    for name, fn in tests:
        try:
            fn()
        except AssertionError as e:
            print(f"  ✗ {name} :: {e}")
            fails.append(name)
        except Exception as e:
            print(f"  ✗ {name} :: {type(e).__name__}: {e}")
            fails.append(name)
    if fails:
        print(f"\n🔴 {len(fails)} FAILED: {fails}")
        sys.exit(1)
    print(f"\n✅ {len(tests)} tests pass")