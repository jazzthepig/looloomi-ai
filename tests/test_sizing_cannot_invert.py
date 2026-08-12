"""
Guard: a sizing table can never reward unfamiliarity or ignorance (S-151).

WHAT WAS MEASURED, by execution, 2026-08-12:

    lookup_size(regime=5 out-of-distribution, signal=1 weakest)  = 1.30
    lookup_size(regime=1 in-distribution,     signal=5 strongest) = 0.10
    compute_size(vdb_distance=None, signal_strength=None)         = 1.20

against `beta_core_size.py`'s own stated design:

    regime band UP  -> size DOWN      (VDB far = unfamiliar = cut exposure)
    signal band UP  -> size UP        (strong signal = lean in)
    (regime 5, signal 1) = 0.10 ; (regime 1, signal 5) = 1.30

Inverted on BOTH axes. The centre cell (3,3)=0.85 was correct — it is the fixed
point of a transpose — so checking "the default baseline" passed.

WHY IT SURVIVED REVIEW. Three artefacts described the sleeve and two of them
were wrong together:

  · the module docstring stated the correct intent
  · the table implemented the inverse
  · `test_beta_core_size_smoke.py` ASSERTED the inverse, in prose:
        _fail("regime=1, signal=5 (in-dist, strong) should be 0.10")
  · `beta_core_size_hook.py` documented the resulting 1.20 as the intended
    first-ship baseline, "slightly above 1.0"

Table, test and hook agreed, so every consistency check between them passed.
Only the stated intent dissented. **A defect is never more expensive than when
it has been written down as the specification** — after that, the next reader
trusts the document instead of measuring.

The tell was inside the module the whole time. `regime_band()` warns against
defaulting to band 1 because it "would look like a strong daily claim", and
`signal_band()` warns against band 5 because it "would look like a conviction".
Both warnings are coherent ONLY if band-1 regime and band-5 signal are the
LARGE-size ends. Under the shipped table they were the small ones. The band
functions were written against a correctly-oriented table; the table was not.

WHY THIS SUITE ASSERTS BEHAVIOUR, NOT VALUES. A frozen-value check ("the table
equals these 25 numbers") would have passed on day one, because the table was
transposed BEFORE it was frozen. Freezing the wrong thing preserves it. So the
invariants here are properties every correctly-oriented table has and every
inverted one lacks — including tables nobody has written yet, which is the only
kind of guard worth having once the values live in a database and can change
without a deploy.

Run: python3 -m tests.test_sizing_cannot_invert
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

_FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  ✓ {name}")
    else:
        print(f"  ✗ {name} :: {detail}")
        _FAILURES.append(name)


_BASE = {"size_clip_min": 0.0, "size_clip_max": 1.3,
         "nan_regime_band": 3, "nan_signal_band": 1}

# The exact table that was in the repo on 2026-08-12. Kept verbatim: this suite
# must fail if anyone ever re-introduces it, and a paraphrase would not.
_INVERTED = [[1.00, 0.80, 0.50, 0.30, 0.10],
             [1.10, 0.95, 0.70, 0.50, 0.20],
             [1.20, 1.00, 0.85, 0.65, 0.30],
             [1.25, 1.10, 0.95, 0.75, 0.40],
             [1.30, 1.20, 1.05, 0.85, 0.50]]

_CORRECTED = [list(reversed(r)) for r in reversed(_INVERTED)]


def test_the_exact_shipped_table_is_rejected() -> None:
    from src.data.signals.strategy_params import NS_C3_SIZE, validate
    problems = validate(NS_C3_SIZE, {**_BASE, "size_table_2d": _INVERTED})
    check("the 2026-08-12 table is refused", len(problems) > 0,
          "the inversion loads")
    joined = " ".join(problems).lower()
    check("the refusal names the unfamiliarity inversion",
          "unfamiliar" in joined, joined[:160])
    check("the refusal names the conviction inversion",
          "conviction" in joined, joined[:160])
    check("the refusal names the no-information leverage",
          "no information" in joined, joined[:160])


def test_un_transposing_it_passes_with_every_value_intact() -> None:
    """Reversing both axes yields a valid set from the SAME 25 numbers. That is
    the evidence the magnitudes were designed correctly and only the assembly
    was wrong — worth asserting, because it tells whoever seeds the parameter
    table that they are re-orienting a design, not inventing one."""
    from src.data.signals.strategy_params import NS_C3_SIZE, validate
    problems = validate(NS_C3_SIZE, {**_BASE, "size_table_2d": _CORRECTED})
    check("the un-transposed table loads clean", not problems, str(problems))
    check("no value was invented",
          sorted(x for r in _CORRECTED for x in r)
          == sorted(x for r in _INVERTED for x in r), "")


def test_no_information_never_produces_leverage() -> None:
    """THE one that costs money. Whatever cell the missing-data path lands on
    must be <= 1.0. This is asserted on the payload AND on the live default,
    because the two can drift apart and only one of them marks the book."""
    from src.data.signals.strategy_params import NS_C3_SIZE, validate
    lever = [[1.2] * 5 for _ in range(5)]
    check("a uniformly levered table is refused",
          any("no information" in p for p in
              validate(NS_C3_SIZE, {**_BASE, "size_table_2d": lever})),
          "a table that levers with no inputs was accepted")

    from src.data.signals.beta_core_size import compute_size
    st = compute_size("2026-08-12", vdb_distance=None, signal_strength=None,
                      q_override=1.0)
    check("live default: both inputs missing -> size <= 1.0",
          st.size_final <= 1.0 + 1e-9,
          f"size={st.size_final} with NO information — this returned 1.20 "
          f"before S-151 and the hook called it the baseline")


def test_the_fallback_is_neutral_not_the_edge() -> None:
    """If the in-code fallback carried the calibrated values, taking them out
    of git would have achieved nothing, and a silent fallback would reproduce
    the edge while the record said `code_fallback`."""
    from src.data.signals.beta_core_size import NEUTRAL_SIZE_TABLE
    flat = {x for row in NEUTRAL_SIZE_TABLE for x in row}
    check("the fallback table is uniform (C3 degenerates to the ① baseline)",
          flat == {1.0}, f"fallback carries {len(flat)} distinct values: {flat}")

    src = (_ROOT / "src/data/signals/beta_core_size.py").read_text(encoding="utf-8")
    code = "\n".join(l for l in src.splitlines() if not l.lstrip().startswith("#"))
    check("the calibrated table is no longer in the module",
          "0.95, 0.70" not in code and "1.25, 1.10" not in code,
          "the mined 5x5 is still in git")


def test_every_mark_carries_its_parameter_version() -> None:
    """Externalising parameters without provenance would make the sizing
    silently mutable. A forward record cannot show what it cannot see."""
    from src.data.signals.beta_core_size import compute_size
    st = compute_size("2026-08-12", vdb_distance=0.5, signal_strength=0.5,
                      q_override=1.0)
    check("Size2DState carries param_version", hasattr(st, "param_version"), "")
    check("Size2DState carries param_source",
          getattr(st, "param_source", None) in
          ("db", "code_fallback", "db_rejected_fallback"),
          str(getattr(st, "param_source", None)))

    hook = (_ROOT / "src/data/signals/beta_core_size_hook.py").read_text(encoding="utf-8")
    for col in ("param_namespace", "param_version", "param_source"):
        check(f"the NAV row writes {col}", f'"{col}"' in hook,
              "a row that cannot name its parameters cannot be defended")


def test_a_rejected_payload_degrades_it_does_not_crash() -> None:
    """A sleeve that crashes on bad config is a sleeve you cannot debug. It
    must decline, record that it declined, and keep marking."""
    from src.data.signals.strategy_params import load, NS_C3_SIZE
    from src.data.signals.beta_core_size import _FALLBACK_PARAMS
    ps = load(NS_C3_SIZE, _FALLBACK_PARAMS, fallback_version=0)
    check("load() returns a ParamSet rather than raising",
          hasattr(ps, "values") and hasattr(ps, "source"), str(type(ps)))
    check("the fallback itself satisfies the invariants", not ps.problems,
          f"the in-code fallback violates its own rules: {ps.problems}")


def test_the_validator_is_the_same_object_production_uses() -> None:
    """A guard that re-implements the rule tests its own copy of it."""
    import src.data.signals.strategy_params as sp
    check("validate() is exported and registry-backed",
          callable(sp.validate) and sp.NS_C3_SIZE in sp._VALIDATORS, "")
    check("an unregistered namespace is refused, not trusted",
          len(sp.validate("made_up_sleeve", {})) > 0,
          "an unknown namespace loaded without validation")


if __name__ == "__main__":
    print("── a sizing table cannot invert (S-151) ──")
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_")]:
        fn()
    if _FAILURES:
        print(f"\n🔴 {len(_FAILURES)} FAILED: {_FAILURES}")
        sys.exit(1)
    print("\n✅ unfamiliarity cannot buy leverage; ignorance cannot buy size")
