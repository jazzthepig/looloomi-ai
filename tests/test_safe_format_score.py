"""S-397 P1 (A5/C6) — `fmtScore()` must render "—" for missing values.

CIS is the product core. The old `item.total_score ?? 0` renderer in
CISLeaderboard.jsx collapsed "no score" to "0.0" — a stablecoin / parked
asset would render with the same `T.amber` color as a C-grade, and the user
had no way to tell the difference.

This test exercises the helper directly so that any future "simplification"
that drops the null-safe branch fails CI. The CSS-component side
(scoreTone) is exercised by grep below — the helper itself is the unit.

The `isMissing` predicate is also asserted, because `fmtScore` is just
`isMissing(v) ? "—" : v.toFixed(d)`, and if isMissing ever stops treating
0 as a real number the test should catch it before any renderer does.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


_REPO = Path(__file__).resolve().parents[1]


_JS = r"""
import('/Users/sbb/Projects/looloomi-ai/dashboard/src/lib/safeFormat.js')
  .then(async (m) => {
    const { fmtScore, isMissing } = m;
    const fails = [];

    // The load-bearing cases — missing MUST render "—" and MUST NOT render 0.0.
    const mustBeDash = [
      ["null",          fmtScore(null),          "—"],
      ["undefined",     fmtScore(undefined),     "—"],
      ["NaN",           fmtScore(NaN),           "—"],
      ["string null",   fmtScore("null"),        "—"],   // not a number
      ["object",        fmtScore({}),            "—"],
    ];
    for (const [label, got, want] of mustBeDash) {
      if (got !== want) fails.push(`fmtScore(${label}) = ${JSON.stringify(got)}, want ${JSON.stringify(want)}`);
    }

    // Real numbers — including 0 — must render their value, not "—".
    // This is the S-397 P1 lesson: legitimate 0.0 is data, not a missing signal.
    const mustBeNumber = [
      ["zero",          fmtScore(0),        "0.0"],
      ["zero int",      fmtScore(0.0),      "0.0"],
      ["small",         fmtScore(0.04),     "0.0"],   // rounds to 0.0 at default 1 digit
      ["grade B",       fmtScore(72.3),     "72.3"],
      ["grade A",       fmtScore(85.0),     "85.0"],
      ["near-perfect",  fmtScore(99.4),     "99.4"],
      ["digits=2",      fmtScore(72.349, 2), "72.35"],
      ["negative",      fmtScore(-3.2),     "-3.2"],   // S-262 family — 0 is not the only non-missing
    ];
    for (const [label, got, want] of mustBeNumber) {
      if (got !== want) fails.push(`fmtScore(${label}) = ${JSON.stringify(got)}, want ${JSON.stringify(want)}`);
    }

    // isMissing itself — the predicate that backs the whole family.
    // If 0 ever gets added to the "missing" set, every safeFormat caller
    // collapses and the failure mode is silent.
    const isMissingCases = [
      [null, true], [undefined, true], [NaN, true],
      [0, false], [0.0, false], [-0, false],
      [42, false], [-1.5, false],
    ];
    for (const [input, want] of isMissingCases) {
      const got = isMissing(input);
      if (got !== want) fails.push(`isMissing(${JSON.stringify(input)}) = ${got}, want ${want}`);
    }

    if (fails.length) {
      for (const f of fails) console.error("  ✗ " + f);
      process.exit(1);
    }
    console.log("  ✓ fmtScore renders — for missing (null/undef/NaN/non-number)");
    console.log("  ✓ fmtScore renders real numbers including 0 (no S-262 collapse)");
    console.log("  ✓ isMissing treats 0 as a real number, not as missing");
  })
  .catch((e) => { console.error("load failed:", e); process.exit(2); });
"""


def _run_node_assertion() -> None:
    proc = subprocess.run(
        ["node", "--input-type=module", "-e", _JS],
        cwd=_REPO, capture_output=True, text=True, timeout=30,
    )
    if proc.returncode != 0:
        print(proc.stdout, end="")
        print(proc.stderr, file=sys.stderr, end="")
        raise AssertionError(
            "fmtScore() failed the null-safety contract — see lines above. "
            "If the helper now collapses missing to a number, every renderer "
            "that imports it inherits the lie (S-262 family)."
        )


def test_fmt_score_renders_dash_for_missing() -> None:
    """Direct call. The contract is binary: missing → "—", real number → toFixed."""
    _run_node_assertion()


def test_cisleaderboard_no_total_score_double_question_zero() -> None:
    """Static guard — the file may not contain `total_score ?? 0` outside safeFormat.

    A regression test for A5/C6 must catch the literal pattern that caused the
    bug in the first place. `scoreTone` here returns the color, not 0, so
    the call site uses `scoreTone(item.total_score)` — never `?? 0`.
    """
    src = Path("dashboard/src/components/CISLeaderboard.jsx").read_text(encoding="utf-8")
    bad = []
    for i, line in enumerate(src.splitlines(), 1):
        # Strip comments — `|| ret === 0` is documented as the OLD behavior,
        # not a render-time `?? 0` collapse.
        stripped = line.split("//", 1)[0]
        if "total_score ?? 0" in stripped:
            bad.append(f"line {i}: {line.strip()!r}")
    assert not bad, (
        "CISLeaderboard.jsx still collapses total_score to 0 — S-397 P1 (A5/C6) "
        "regressed:\n  " + "\n  ".join(bad)
    )


if __name__ == "__main__":
    fails = 0
    for fn in (test_fmt_score_renders_dash_for_missing,
               test_cisleaderboard_no_total_score_double_question_zero):
        try:
            fn()
            print(f"  ✓ {fn.__name__}")
        except AssertionError as e:
            fails += 1
            print(f"  ✗ {fn.__name__}\n    {e}")
    print(f"\n{'✅' if not fails else '🔴'} safeFormat score — {fails} failing")
    sys.exit(1 if fails else 0)
