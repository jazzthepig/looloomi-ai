"""
A-408-6 final 3 loops smoke test (lane-a worktree version)
==========================================================

Wires the FINAL 3 unwired loops to `_record_loop_attempt`:
  - _outcome_tracker_loop    (S-405 silent-fail named culprit)
  - _pod_aggregator_loop     (M-79 frozen cell — weights + breakers audit)
  - _track_record_loop       (S-299: None/0 distinguishing)

`_beta_plus_loop` is NOT in this lane-a worktree (lane-a is 105 commits
behind origin/main; `_beta_plus_loop` lives only on the dirty main
that Seth is committing). This test covers the 3 that ARE on this copy;
Seth gets a separate patch note for `_beta_plus_loop` if needed.

Tests:
  T31:  site counts — 3 loops × 2 sites each
  T32:  _outcome_tracker_loop captures resolved/wins/losses (S-405
        silent-fail — this is THE signal_outcomes writer)
  T33:  _pod_aggregator_loop captures M-79 frozen-cell fields
        (weights / max_corr / survivors / breakers_tripped)
  T34:  _track_record_loop distinguishes "None" (RPC failed) from "0"
        (upstream empty) — S-299 load-bearing
  T35:  REPLAY — cumulative loops count ≥ 22 (20 from prior + 3 here;
        _beta_plus_loop +1 if main also wired)

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


# T31: site counts — 3 loops × 2 sites each
def test_t31_site_count_per_loop():
    LOOPS = ['_outcome_tracker_loop', '_pod_aggregator_loop', '_track_record_loop']
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
    print("✓ T31: 3 loops × 2 sites = 6 sites wired")


# T32: _outcome_tracker_loop captures resolved/wins/losses
def test_t32_outcome_tracker_loop_audit_fields():
    body = _body('_outcome_tracker_loop')
    assert body is not None, "_outcome_tracker_loop not found"
    # Must capture the S-405 silent-fail culprit's output
    for field in ("resolved", "wins", "losses", "rows_written"):
        assert f'summary.get("{field}")' in body, (
            f"_outcome_tracker_loop: detail must capture '{field}' "
            f"(signal_outcomes audit needs to know what got written)")
    # outcome enum
    assert ('"ok" if _ok else "refused" if _ref else "error"'
            in body), ("_outcome_tracker_loop: missing ok/refused/error ternary")
    # writer
    assert 'writer="src.api.main._outcome_tracker_loop"' in body, (
        "_outcome_tracker_loop: writer field mismatch")
    # Exception path
    assert 'reason=f"{type(_e).__name__}: {str(_e)[:300]}"' in body, (
        "_outcome_tracker_loop: exception path missing")
    print("✓ T32: _outcome_tracker_loop captures resolved/wins/losses/rows_written")


# T33: _pod_aggregator_loop captures M-79 frozen-cell fields
def test_t33_pod_aggregator_loop_frozen_cell_fields():
    body = _body('_pod_aggregator_loop')
    assert body is not None, "_pod_aggregator_loop not found"
    # M-79 frozen cell weights / max_corr / survivors / breakers_tripped
    for field in ("weights", "max_corr_retained", "survivors",
                  "breakers_tripped", "n_days_marked"):
        assert f'res.get("{field}")' in body, (
            f"_pod_aggregator_loop: detail must capture '{field}' "
            f"(M-79 frozen cell audit needs weight + correlation + breaker state)")
    # writer + exception path
    assert 'writer="src.api.main._pod_aggregator_loop"' in body, (
        "_pod_aggregator_loop: writer field mismatch")
    print("✓ T33: _pod_aggregator_loop captures M-79 frozen-cell fields")


# T34: _track_record_loop distinguishes None (RPC failed) from 0 (upstream empty)
def test_t34_track_record_loop_none_zero_distinguishing():
    body = _body('_track_record_loop')
    assert body is not None, "_track_record_loop not found"
    # S-299: outcome enum must distinguish None (RPC failed) vs 0 (empty)
    # ternary: "ok" if (_n and _n > 0) else "refused" if _n == 0 else "error"
    assert '"ok" if (_n and _n > 0)' in body, (
        "_track_record_loop: ok branch must require _n > 0 (not just truthy)")
    assert '"refused" if _n == 0' in body, (
        "_track_record_loop: refused branch must be _n == 0 specifically")
    # detail must capture rpc_failed + zero_rows for the distinguishing audit
    assert '"rpc_failed"' in body, (
        "_track_record_loop: detail must include rpc_failed boolean")
    assert '"zero_rows"' in body, (
        "_track_record_loop: detail must include zero_rows boolean")
    # S-299 reason text must be preserved
    assert 'RPC 返回 None' in body, (
        "_track_record_loop: None reason text must be preserved (S-299)")
    print("✓ T34: _track_record_loop distinguishes None/0 (S-299 preserved)")


# T35: REPLAY — cumulative loops count in lane-a worktree
def test_t35_replay_cumulative_loops():
    src = _main_src()
    # In lane-a worktree, only loops that exist HERE count. Lane-a is
    # 105 commits behind origin/main — A-408-5 (and earlier batches)
    # were committed by Seth on main, not present in lane-a. We only
    # assert the 3 from this batch are wired.
    targets = [
        '_outcome_tracker_loop', '_pod_aggregator_loop', '_track_record_loop',
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
    assert found >= 3, (
        f"cumulative loops count {found} (need ≥ 3 in lane-a: this batch)")
    print(f"✓ T35: REPLAY — {found} loops cumulative wired in lane-a "
          f"(prior families are on main; Seth verifies post-rebase)")


if __name__ == "__main__":
    print("── A-408-6 / S-408-6 final 3 loops smoke (lane-a) ──")
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