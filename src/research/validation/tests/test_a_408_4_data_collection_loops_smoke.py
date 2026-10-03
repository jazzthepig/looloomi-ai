"""
A-408-4 data-collection loops smoke test
=======================================

The 4 data-collection loops (`_forward_record_loop`, `_deep_panel_loop`,
`_hyperliquid_loop`, `_market_state_loop`) were the silent-failure root
cause of "82 tables 28 zero rows" (S-405). They had `_beat()` liveness
hashing but NO `_record_loop_attempt` per-iteration record — so a loop
that refused correctly and a loop that was dead looked identical on
the ops dashboard.

This test enforces the wire-up:
  T18:  _forward_record_loop has ≥ 2 _record_loop_attempt call sites
  T19:  _forward_record_loop outcome mapping (ok / refused=empty day /
        error=stalled books)
  T20:  _deep_panel_loop has ≥ 3 call sites (success + SourcePolicyError
        refused + general exception error — S-323i/l explicitly separates
        the source-policy refusal)
  T21:  _hyperliquid_loop has 2 call sites, NO refused path (per inline
        S-294: failure is always a fault, never "by-rules refused")
  T22:  _hyperliquid_loop preserves diagnosis/error/reason verbatim
        (S-324: producer uses `reason`, consumer reads `diagnosis`/`error`)
  T23:  _market_state_loop has 2 call sites; StoreResult ok/refused/error
        mapping
  T25:  REPLAY — all 4 loops structured so total per-day cycle count
        ≥ 4 (the structural floor)

Pure Python, no DB / no network / no secrets.
"""
import sys
import re
import asyncio
from pathlib import Path
from unittest.mock import patch, MagicMock


_ROOT = Path(__file__).resolve().parents[4]


def _main_src():
    return (_ROOT / "src/api/main.py").read_text()


# T18: _forward_record_loop has ≥ 2 _record_loop_attempt call sites
def test_t18_forward_record_loop_site_count():
    src = _main_src()
    # Pull the function body
    m = re.search(
        r'^async def _forward_record_loop\(\):.*?(?=^async def |\Z)',
        src, re.MULTILINE | re.DOTALL)
    assert m is not None, "_forward_record_loop not found in main.py"
    count = len(re.findall(
        r'_record_loop_attempt\(\s*[\"\'](_forward_record_loop)[\"\']',
        m.group(0)))
    assert count >= 2, (
        f"_forward_record_loop has {count} _record_loop_attempt sites "
        f"(need ≥ 2: ok/refused/error + exception)")
    print(f"✓ T18: _forward_record_loop has {count} sites (≥ 2 required)")


# T19: _forward_record_loop outcome enum (ok / refused=empty day / error)
def test_t19_forward_record_loop_outcome_enum():
    src = _main_src()
    m = re.search(
        r'^async def _forward_record_loop\(\):.*?(?=^async def |\Z)',
        src, re.MULTILINE | re.DOTALL)
    body = m.group(0)
    # ok branch: "_ok and _w > 0"
    assert '"ok" if _ok and _w > 0' in body, (
        "ok branch must be _ok=True AND _w>0 (legit non-empty day)")
    # refused branch: "_ok and _w == 0"
    assert '"refused" if _ok' in body, (
        "refused branch must be _ok=True alone (legit empty day)")
    # error branch
    assert '"error"' in body, "error branch must exist"
    # All 3 outcomes in the same ternary
    ok_idx = body.find('"ok" if')
    ref_idx = body.find('"refused" if')
    err_idx = body.find('"error"')
    assert ok_idx < ref_idx < err_idx, (
        f"outcomes not in expected order ok<{ok_idx} < refused<{ref_idx} "
        f"< error<{err_idx}>")
    # reason preserved (stalled + problems)
    assert 'stalled=' in body, "error reason must include stalled=[]"
    assert 'problems=' in body, "error reason must include problems="
    print("✓ T19: _forward_record_loop ok/refused/error outcome mapping "
          "with stalled+problem reason")


# T20: _deep_panel_loop has ≥ 3 call sites (success + SourcePolicyError
# refused + general exception error)
def test_t20_deep_panel_loop_site_count_and_source_policy():
    src = _main_src()
    m = re.search(
        r'^async def _deep_panel_loop\(\):.*?(?=^async def |\Z)',
        src, re.MULTILINE | re.DOTALL)
    assert m is not None, "_deep_panel_loop not found in main.py"
    body = m.group(0)
    count = len(re.findall(
        r'_record_loop_attempt\(\s*[\"\'](_deep_panel_loop)[\"\']',
        body))
    assert count >= 3, (
        f"_deep_panel_loop has {count} sites (need ≥ 3: success + "
        f"SourcePolicyError refused + general exception)")
    # SourcePolicyError branch wired with refused outcome
    assert 'except SourcePolicyError as _e:' in body, (
        "SourcePolicyError branch missing")
    assert 'SourcePolicyError:' in body or 'source_policy_refused' in body, (
        "SourcePolicyError refused reason must be preserved")
    print(f"✓ T20: _deep_panel_loop has {count} sites + SourcePolicyError "
          f"refused branch wired")


# T21: _hyperliquid_loop has 2 call sites, NO refused outcome (per inline
# S-294: failure is always a fault, not "by-rules refused")
def test_t21_hyperliquid_loop_site_count_and_no_refused():
    src = _main_src()
    m = re.search(
        r'^async def _hyperliquid_loop\(\):.*?(?=^async def |\Z)',
        src, re.MULTILINE | re.DOTALL)
    body = m.group(0)
    count = len(re.findall(
        r'_record_loop_attempt\(\s*[\"\'](_hyperliquid_loop)[\"\']',
        body))
    assert count >= 2, (
        f"_hyperliquid_loop has {count} sites (need ≥ 2: ok/error + exception)")
    # CRITICAL — must NOT have refused outcome (S-294 design intent)
    # The only "refused" string should be the inline-comment quote of S-294
    refused_in_outcome = re.findall(
        r'"(ok|refused|error)"\s+if', body)
    # Per S-294, only ok and error outcomes are valid here
    assert 'refused' not in refused_in_outcome, (
        f"_hyperliquid_loop has 'refused' outcome in ternary — S-294 says "
        f"failure is always a fault. Outcomes found: {refused_in_outcome}")
    # Inline comment MAY quote "拒绝" — but outcome enum must be clean
    print(f"✓ T21: _hyperliquid_loop has {count} sites, no refused "
          f"outcome (S-294 enforced): outcomes={refused_in_outcome}")


# T22: _hyperliquid_loop preserves diagnosis/error/reason verbatim (S-324)
def test_t22_hyperliquid_loop_diagnosis_reason_preservation():
    src = _main_src()
    m = re.search(
        r'^async def _hyperliquid_loop\(\):.*?(?=^async def |\Z)',
        src, re.MULTILINE | re.DOTALL)
    body = m.group(0)
    # The success-path detail must include diagnosis/error preservation
    # via the _why computation
    assert '_why' in body, "_why computation must exist for verdict bridge"
    assert 'r.get("diagnosis") or r.get("error") or r.get("reason")' in body, (
        "S-324: diagnosis/error/reason must be merged in detail — producer "
        "writes `reason`, consumer reads `diagnosis`/`error`")
    # And detail captures them
    detail_m = re.search(r'detail=\{([^}]+)\}', body)
    assert detail_m is not None, "detail={} dict must be present"
    detail_str = detail_m.group(1)
    assert 'ok' in detail_str and 'n_perps' in detail_str, (
        "detail must include ok + n_perps (S-310 family fields)")
    print("✓ T22: _hyperliquid_loop diagnosis/error/reason verbatim S-324 "
          "preservation")


# T23: _market_state_loop has 2 call sites, StoreResult-based outcome enum
def test_t23_market_state_loop_site_count():
    src = _main_src()
    m = re.search(
        r'^async def _market_state_loop\(\):.*?(?=^async def |\Z)',
        src, re.MULTILINE | re.DOTALL)
    body = m.group(0)
    count = len(re.findall(
        r'_record_loop_attempt\(\s*[\"\'](_market_state_loop)[\"\']',
        body))
    assert count >= 2, (
        f"_market_state_loop has {count} sites (need ≥ 2: ok/refused/error "
        f"+ exception)")
    # StoreResult fields (typed object, not dict)
    assert 'res.ok' in body, "StoreResult.ok attribute must be used"
    assert 'res.refused' in body, "StoreResult.refused attribute must be used"
    assert 'res.reason' in body, "StoreResult.reason attribute must be used"
    # Outcome enum
    assert '"ok" if res.ok else "refused" if res.refused else "error"' in body, (
        "StoreResult outcome enum must follow ok<|> refused<|> error< shape")
    print(f"✓ T23: _market_state_loop has {count} sites, StoreResult "
          f"outcome enum correct")


# T24: REPLAY — all 4 loops structured so total per-day cycle count ≥ 4
# (structural floor for ops visibility)
def test_t24_replay_total_loop_count():
    src = _main_src()
    targets = [
        '_forward_record_loop',
        '_deep_panel_loop',
        '_hyperliquid_loop',
        '_market_state_loop',
    ]
    total = 0
    for name in targets:
        m = re.search(
            rf'^async def {name}\(\):.*?(?=^async def |\Z)',
            src, re.MULTILINE | re.DOTALL)
        if m is None:
            print(f"  ⚠ {name}: not found")
            continue
        n = len(re.findall(
            rf'_record_loop_attempt\(\s*[\"\']({name})[\"\']',
            m.group(0)))
        total += n
        print(f"  {name}: {n} sites")
    assert total >= 9, (
        f"4 data-collection loops total {total} sites (need ≥ 9: 2+3+2+2)")
    print(f"✓ T24: REPLAY — 4 loops cumulative {total} sites wired")


if __name__ == "__main__":
    print("── A-408-4 / S-408-4 data-collection loops smoke ──")
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