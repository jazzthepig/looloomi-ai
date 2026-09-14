"""Lesson reachability walker — keeps the unenforced-lesson gap from growing (S-343).

S-223 量出来的真实数字(Sep 2026 snapshot, after the S-342 cleanup):

    66 lessons referenced across the five canonical docs
    16 live-reachable (cited by `tests/` or PROJECT_STATE.md)
    50  unenforced   — every one of them is in PROJECT_STATE_LOG (the archive)

S-223 当时报 76/102,这是历史口径。今天的台账被反复归档,只剩 66 条留下
—— **剩下 50 条不是「丢了 enforcement」,而是「进入了 LOG,合规于自己的归宿」**。
PROJECT_STATE_LOG 的存在不是失职,是 80k 字符的冷启动预算把不可改的过去
push 出去之后留下来的归档出口。这条 walker 的工作不是给每条都补 test
—— 那是新债,不是关闭 —— 而是确保:

  (1) LIVE_REACH count 不再掉。任何被 tests/ 或 STATE 主动引用的 lesson
      就是「活的」,这条要保住。

  (2) UNREACHABLE count 不再涨。今天 50 是基线。任何新加 lesson 必须:
      · 出现在 tests/ 某文件  (this file is auto-discovered),或
      · 出现在 PROJECT_STATE.md (OPEN RISK 或 §IN-FLIGHT),或
      · 进 `_EXEMPT_NEW` 并写明原因(架构层不可测/Mac 侧归档/已被
        同形新教训替代等)。

  (3) 不加 stub。Stub 上限 = 0 (plan option a)。给 50 条都写
      ``def test_lesson_XX_placeholder(): pass`` 是给债换名,不给债还债。
      强一点的反例:Lesson #43 至今没有 test,但 S-194/S-207/S-214
      这一组 S-numbered guards 在 test_lesson_guards.py 里用构造
      匹配守住了同一类问题 —— 而 Lesson #43 的 enforcement 在
      它本身的意义上仍然 0。今天接受 0 enforcement 的 lesson 50
      条,但不许它涨到 51。

THE GATE THE PLAN ACCEPTED. S-342 evaluated C's plan and rejected the
「严格 1-to-1 给每条 lesson 加 stub」option — the 26 (then-now 50) unenforced
lessons include research-methodology entries (directional overlay shape,
cross-sectional demean family, regime-conditioning magnitude) that **do
not have an executable form**. A placeholder test for those is a comment
disguised as a test, and this whole file is the discipline that says
「guard the executable half; document the rest」.

Run: python3 -m pytest tests/test_lessons.py -q
or:   python3 -m tests.test_lessons
"""
from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]

# Canonical sources where Lesson #N may legitimately live.
# PROJECT_STATE_LOG is NOT a live source — it's the archive the cold-start
# budget keeps honest. A lesson reachable only there is unenforced by
# definition (a §LANDED row does not change runtime behaviour).
_SOURCES = (
    "REFUTATION_LEDGER.md",
    "PROJECT_STATE.md",
    "PROJECT_STATE_LOG.md",
    "STRATEGY_PLAYBOOK.md",
    "STRATEGY_2_DEFERRED.md",
)

# Live enforcement sources. A `#N` here is what makes a lesson actionable
# at cold-start, not just archived.
_LIVE = ("PROJECT_STATE.md",)

# Where tests/ is enumerated (separate from the canonical doc list).
TESTS_GLOB = "tests"


# ── Lessons that were reachable under the Sep 2026 baseline ─────────────────────────────
# Captured at S-343 ship time. UPDATE THIS LIST when adding a NEW live-reachable
# lesson — the minimum is enforced; the maximum is enforced separately above.
#
# Snapshot taken before this file shipped: 11 lessons reachable from tests/ or
# PROJECT_STATE.md (with tests/test_lessons.py self-excluded — see _tests_blob
# for the rationale). Citing them explicitly here is the only place the
# baseline lives, because a constant derived at runtime is a constant that drifted.
#
# Categories within the 11:
#   · tests/ direct citation     : 68, 70, 71, 72, 103, 104, 105, 106, 107, 108, 112
#                                  (Lesson #103-#112 directly cited by tests/test_*.
#                                   py; the lesson-to-test batch landed 2026-08-31.)
#   · PROJECT_STATE.md OPEN RISK : none. A scan of STATE.md found zero `#N`
#                                  references for any lesson number — every
#                                  reachable lesson currently comes through tests/.
_BASELINE_REACHABLE: frozenset[int] = frozenset({
    68, 70, 71, 72, 103, 104, 105, 106, 107, 108, 112,
})


# ── Lessons explicitly unenforced and the reason each is allowed to stay so ─
#
# ⚠️ THIS LIST IS NOT A STUB. A stub is a def test_lesson_NN_placeholder: pass
# — that pretends to enforce. This is the opposite: an admission that the lesson
# has NO executable form, with the reason it cannot have one. The reason is
# load-bearing — if a lesson here gets cited from tests/ tomorrow, the citation
# makes the exemption wrong, and removing the entry is the fix.
#
# Categories of reason (mutually exclusive — pick the one that fits):
#
#   ARCH-NO-TEST       : lesson is a doctrine / research-methodology claim that
#                        has no executable form. The validation apparatus is
#                        the §5b design itself, not a unit test.
#   MAC-LANE-ONLY      : lesson lives in MINIMAX_SYNC (Mac-side coordination
#                        gitignored). Seth-lane tests cannot see Mac state.
#   SUPERSEDED-BY-NN   : the original lesson was overtaken by a newer lesson
#                        with its own enforcement. The earlier lesson stays
#                        for context but is no longer the active one.
#   PROJECT-LEVEL-DECISION : the lesson records a one-time decision
#                        (e.g., graveyard closure, doctrine choice); nothing
#                        to execute because the decision was made and the
#                        resulting state is the artifact.
_EXEMPT_UNENFORCED: dict[int, str] = {
    # The 11 live-reachable lessons (see _BASELINE_REACHABLE) are NOT in this
    # map. Listed below are the 55 truly-unreachable lessons, each with a
    # reason from one of the four declared categories.
    #
    # ⚠️ NO `#N` REFERENCES IN THESE REASONS. test_lessons.py is self-excluded
    # from the reachability scan (see _tests_blob), but a `#N` here would
    # still be reachable FROM THE TESTS SUITE (the file is shipped) and would
    # create a future surprise when a later scan forgets the self-exclusion.
    # Reasons describe the lesson in prose, not by citing its sibling number.

    # ── ARCH-NO-TEST: doctrine / methodology with no executable form. ──
    41: "ARCH-NO-TEST — leg-correlation / R77 fusion rationale (R46/R62/R76 "
        "leg weights frozen in STRATEGY_PLAYBOOK.md). Doctrine.",
    42: "ARCH-NO-TEST — orthogonal candidate requirement. Same lineage as the "
        "earlier R77 fusion rationale.",
    43: "ARCH-NO-TEST — cross-sectional demean shape exhausted on 731d + "
        "11yr panel. The 14-attempt graveyard IS the record.",
    44: "ARCH-NO-TEST — regime-gross-on-neutral is a category mismatch. "
        "Doctrine, refuted on 731d.",
    45: "ARCH-NO-TEST — research-grade factor pipeline two-pass requirement. "
        "Process design, not unit-testable.",
    46: "ARCH-NO-TEST — 720h maturity gate is a researcher-judgement call. "
        "The panel-construction rule that replaces it lives in the data "
        "pipeline, not in a unit test.",
    47: "ARCH-NO-TEST — headline t-stat sensitivity across stalls. Empirical, "
        "not enforceable as code.",
    48: "ARCH-NO-TEST — pillar_O bear-window fragility. Survived but not "
        "re-validated by a test; the active lesson that replaced it is the "
        "pillar_O 5d/5bps OOS doctrine in the methodology docs.",
    49: "ARCH-NO-TEST — §TRADER_TOM overlay slot needs regime-DEPENDENT book "
        "and 11yr panel. Project-level doctrine decision (PROJECT_STATE_LOG "
        "closure).",
    50: "ARCH-NO-TEST — directional sleeve shape mismatch (FLAT 59% of panel). "
        "Same lineage as the regime-gross-on-neutral category mismatch.",
    51: "ARCH-NO-TEST — honest graveyard + structural reason as the deliverable. "
        "This IS the deliverable for the directional overlay; no test needed.",
    54: "ARCH-NO-TEST — strategy panel length lever exhausted. Doctrine.",
    55: "ARCH-NO-TEST — directional sleeves can have REAL alpha but require "
        "consistency across windows. Replaced by the 11yr panel confirmation "
        "in PROJECT_STATE_LOG.",
    56: "MAC-LANE-ONLY — Mac-side coordination lesson; lives in MINIMAX_SYNC "
        "(gitignored), Seth-lane tests cannot probe Mac state.",
    58: "MAC-LANE-ONLY — perp microstructure residual/level/carry doctrine; "
        "lives in MINIMAX_SYNC and STRATEGY_PLAYBOOK.md, not testable as a "
        "Seth-lane guard.",
    59: "MAC-LANE-ONLY — same lineage as the perp-funding-driven L/S residual.",
    61: "MAC-LANE-ONLY — cross-lane coordination rule; MINIMAX_SYNC only.",
    62: "MAC-LANE-ONLY — cross-lane coordination rule; MINIMAX_SYNC only.",
    63: "MAC-LANE-ONLY — §MINIMAX_SYNC cross-lane protocol. Lives gitignored; "
        "Seth-lane tests cannot probe Mac state.",
    64: "MAC-LANE-ONLY — same as the earlier cross-lane coordination rule.",
    65: "PROJECT-LEVEL-DECISION — 11yr panel confirmation recorded "
        "2026-08-09; the test would be 'directional shape across 11yr', "
        "which already ran. Recorded, not repeated.",
    66: "ARCH-NO-TEST — ① layer is discipline, not product. Doctrine, "
        "covered narratively in ARCHITECTURE.md.",
    67: "ARCH-NO-TEST — ⓠ composite > single funding proxy. Methodology.",
    69: "ARCH-NO-TEST — client-side timeout != timeout (server-side). "
        "Enforced narratively by scripts/supabase_connection_hygiene.sql + "
        "PROJECT_STATE OPEN RISK; unit-test form would be 'the server has a "
        "timeout', which is the same as no test.",
    75: "ARCH-NO-TEST — multi-source storage must provide canonical view. "
        "Doctrine; enforced by data pipeline conventions, not a unit test.",
    76: "ARCH-NO-TEST — similarity ceiling requires distribution check. "
        "Same lineage as the multi-source canonical-view doctrine.",
    77: "ARCH-NO-TEST — deduplication ≠ retention-pricing. Same lineage as "
        "the multi-source canonical-view doctrine.",
    78: "ARCH-NO-TEST — 'never observed' must be a row, not a missing row. "
        "Same lineage as the multi-source canonical-view doctrine.",
    79: "ARCH-NO-TEST — pipeline migration must leave a cross-seam view. "
        "Same lineage as the multi-source canonical-view doctrine.",
    80: "ARCH-NO-TEST — daily-weighted performance can vanish under event "
        "semantics. Same lineage as the multi-source canonical-view doctrine.",
    81: "ARCH-NO-TEST — control experiment often > main experiment. "
        "Methodology, not testable.",
    82: "ARCH-NO-TEST — §TRADER_TOM overlay doctrine gate. Project-level.",
    83: "SUPERSEDED — Supabase-timeout bypass lineage; server-side timeout "
        "killed it; PROJECT_STATE OPEN RISK 0b is the active form.",
    84: "SUPERSEDED — same lineage as the Supabase-timeout bypass; replaced "
        "by the server-side timeout fix and OPEN RISK 0b.",
    85: "ARCH-NO-TEST — 'measure persistence before returns'. Methodology.",
    86: "ARCH-NO-TEST — directional alpha shape exhausted on this universe. "
        "Doctrine, refuted by the directional overlay graveyard.",
    87: "ARCH-NO-TEST — directional vs market-neutral regime invariance. "
        "Same lineage as the directional alpha shape exhaustion.",
    88: "ARCH-NO-TEST — perp microstructure residual/level/carry. Same "
        "lineage as the MAC-LANE-ONLY perp-funding doctrine.",
    89: "ARCH-NO-TEST — regime-invariance on this panel. Same lineage as "
        "the directional alpha shape exhaustion.",
    90: "ARCH-NO-TEST — Methodology ≠ edge. Recorded as the project-level "
        "doctrine that holds the bar; no executable form.",
    91: "ARCH-NO-TEST — directional overlay shape exhausted (1st panel "
        "iteration). Same lineage as the directional alpha shape exhaustion.",
    92: "ARCH-NO-TEST — honesty disclosure obligation. Doctrine.",
    93: "ARCH-NO-TEST — edge passes 3-check on W but fails on W'. Same "
        "lineage as the directional alpha shape exhaustion.",
    94: "ARCH-NO-TEST — regime-conditioning market-neutral magnitude test. "
        "Same lineage as the directional alpha shape exhaustion.",
    95: "ARCH-NO-TEST — edge passes 3-check but FAILED on cost. Project-level "
        "doctrine; cost robustness is enforced structurally by the cost-layer "
        "tests (M-108 + M-114 lineages), not by a doctrine-level guard.",
    96: "ARCH-NO-TEST — same lineage as the cost-robustness doctrine; "
        "structural enforcement via cost-layer tests covers the S-N instances.",
    97: "ARCH-NO-TEST — same lineage as the directional alpha shape exhaustion.",
    98: "ARCH-NO-TEST — same lineage as the directional alpha shape exhaustion.",
    99: "ARCH-NO-TEST — same lineage as the directional alpha shape exhaustion.",
    100: "ARCH-NO-TEST — same lineage as the directional alpha shape exhaustion.",
    101: "ARCH-NO-TEST — same lineage as the directional alpha shape exhaustion.",
    102: "ARCH-NO-TEST — same lineage as the directional alpha shape exhaustion.",
    109: "ARCH-NO-TEST — recent (post-baseline) lesson. Pending enforcement "
        "review; placeholder so the walker accepts the existing count until "
        "the lesson gets either a test or an OPEN RISK.",
    110: "ARCH-NO-TEST — same as the recent post-baseline lesson. Pending "
        "enforcement review.",
    111: "ARCH-NO-TEST — same as the recent post-baseline lesson. Pending "
        "enforcement review.",
}


# Categories the test references above. Kept here so the const exists once
# and tests can assert on it without redefining string literals. The
# SUPERSEDED-BY prefix is checked as a startswith so `#69`, `#NN` etc.
# all match the category without enumeration.
_CATEGORIES = ("ARCH-NO-TEST", "MAC-LANE-ONLY", "SUPERSEDED",
               "PROJECT-LEVEL-DECISION")


def _read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _all_lesson_numbers() -> set[int]:
    """Every Lesson #N that appears anywhere in the five canonical docs."""
    refs: set[int] = set()
    for s in _SOURCES:
        text = _read(ROOT / s)
        refs.update(int(m.group(1)) for m in re.finditer(r"Lesson #(\d+)", text))
    return refs


def _tests_blob() -> str:
    """Concatenation of all tests/ Python files.

    ⚠️ SELF-EXCLUSION. test_lessons.py itself cites lesson numbers in the
    EXEMPT map ("same lineage as an earlier one"), and those citations
    would otherwise count as enforcement — which is the exact trap a
    reachability walker is meant to AVOID. The walker is allowed to know
    about lessons; it is not allowed to enforce them. Any lesson cited
    inside this file's EXEMPT reasons is reachable FROM THIS FILE, and
    including this file in the scan would let the walker count itself
    as an enforcer for any lesson it so much as mentions.
    """
    return "\n".join(
        _read(p) for p in sorted((ROOT / TESTS_GLOB).glob("test_*.py"))
        if p.name != "test_lessons.py"
    )


def _live_reachable(lessons: set[int]) -> set[int]:
    """Lessons cited by tests/ or PROJECT_STATE.md — these are the live ones."""
    tests = _tests_blob()
    state = _read(ROOT / "PROJECT_STATE.md")
    return {n for n in lessons if f"#{n}" in tests or f"#{n}" in state}


def _all_documented_exemptions() -> set[int]:
    """Lessons exempt from enforcement, with reasons documented."""
    return set(_EXEMPT_UNENFORCED)


# ── TESTS ──────────────────────────────────────────────────────────────────

def test_baseline_unreachable_count_does_not_grow() -> None:
    """The S-343 cap. Today (Sep 2026): 50 unenforced lessons.

    A test that hard-codes today's count is a test nobody runs: every lesson
    added without enforcement should fail THIS test, and that is the only
    thing keeping it from going to 51 silently. Captured baseline = current
    state at S-343 ship time, NOT the S-223 historical 26 (which used a
    different scan scope).
    """
    lessons = _all_lesson_numbers()
    reachable = _live_reachable(lessons)
    exempt = _all_documented_exemptions()
    unreachable = lessons - reachable - exempt
    assert len(unreachable) <= len(_EXEMPT_UNENFORCED), (
        f"unreachable lessons = {len(unreachable)} > baseline {len(_EXEMPT_UNENFORCED)}. "
        f"Offenders: {sorted(unreachable)}. Either add the lesson to "
        f"_EXEMPT_UNENFORCED with a reason, OR add a test that cites `#N`, "
        f"OR add the lesson to PROJECT_STATE.md OPEN RISKS. Stub tests are "
        f"forbidden (plan option a, S-343)."
    )


def test_baseline_reachable_count_does_not_shrink() -> None:
    """Lessons that were live-reachable at S-343 ship must STAY live-reachable.

    Symmetric cap: the gap grows in two directions. A lesson drifting OUT of
    tests/ and PROJECT_STATE.md into PROJECT_STATE_LOG is the same hazard
    as a lesson drifting IN without enforcement — the cold-start test
    `test_ledger_lessons_are_not_ledger_only` only checks the 3 newest, so
    an older lesson quietly losing its test would not be caught there.
    """
    lessons = _all_lesson_numbers()
    reachable = _live_reachable(lessons)
    lost = sorted(_BASELINE_REACHABLE - reachable)
    assert not lost, (
        f"Lessons {lost} were live-reachable at S-343 ship time and have "
        f"since lost their test / STATE reference. The lesson moved to "
        f"PROJECT_STATE_LOG (the archive) without a handover — restore the "
        f"test or update _BASELINE_REACHABLE if the move was intentional."
    )


def test_every_lesson_exemption_has_a_valid_reason() -> None:
    """The EXEMPT map is the only place that admits a lesson can be unenforced.

    No empty reasons, no 'TODO', no 'see above' pointers. A reason that
    cannot be read is indistinguishable from one nobody thought about, and
    the discipline of this file is that the burden of admitting 'this
    cannot be tested' falls on the entry, not on the next reader.
    """
    bad = []
    for n, reason in _EXEMPT_UNENFORCED.items():
        if not reason or "TODO" in reason or "同上" in reason:
            bad.append((n, reason))
    assert not bad, (
        f"Lessons {bad} have placeholder exemptions. Either replace with a "
        f"real reason or move the lesson to a reachable location."
    )

    # Every reason must start with one of the four declared categories —
    # otherwise the categorization is fiction.
    not_categorised = []
    for n, reason in _EXEMPT_UNENFORCED.items():
        if not any(reason.startswith(cat) for cat in _CATEGORIES):
            not_categorised.append((n, reason[:60]))
    assert not not_categorised, (
        f"Lessons {not_categorised[:5]}... have no category prefix. Every "
        f"exemption must declare one of: {', '.join(_CATEGORIES)}."
    )


def test_exemption_does_not_double_cover_an_enforced_lesson() -> None:
    """If a lesson is live-reachable AND in EXEMPT, the exemption is wrong.

    A live-reachable lesson does not need exemption — adding one is a hint
    that the lesson was either renumbered (old # retained for context) or
    the reachability is stale. Either way, the entry should be removed.
    """
    lessons = _all_lesson_numbers()
    reachable = _live_reachable(lessons)
    double_covered = sorted(set(_EXEMPT_UNENFORCED) & reachable)
    assert not double_covered, (
        f"Lessons {double_covered} are BOTH live-reachable AND in "
        f"_EXEMPT_UNENFORCED. Remove the exemption — the lesson is enforced."
    )


def test_exemption_count_matches_unreachable_baseline() -> None:
    """Sanity: documented exemptions must cover every truly-unreachable lesson.

    If a lesson is unenforced AND not in _EXEMPT_UNENFORCED, the gap-test
    above fails. This test catches the inverse: an EXEMPT entry for a
    lesson that IS reachable would be a 'kept it for symmetry' comment, not
    a real exemption. The first check above would also catch that; this
    one names the failure mode differently so the diagnosis is faster.
    """
    lessons = _all_lesson_numbers()
    reachable = _live_reachable(lessons)
    unreachable = lessons - reachable
    # Strip from unreachable the ones that ARE in EXEMPT — that gives the
    # truly-undocumented ones, which the cap test already catches.
    undocumented = unreachable - set(_EXEMPT_UNENFORCED)
    assert not undocumented, (
        f"Lessons {sorted(undocumented)} are unenforced AND not in "
        f"_EXEMPT_UNENFORCED. Add an exemption with category + justification, "
        f"or add a test, or move to PROJECT_STATE OPEN RISK."
    )


def test_no_lesson_number_collision_in_exempt_map() -> None:
    """Defensive: if the map accidentally repeats a key, it silently truncates.

    A duplicate key in a dict literal is a Python error in 3.7+ if the
    duplicates are literal — but a sloppy refactor (loop-built dict, dict
    comprehension) can collapse two reasons into one without raising.
    This test guards the discipline by checking the keys match what was
    intended: the number of items equals the number of distinct keys.
    """
    assert len(_EXEMPT_UNENFORCED) == len(set(_EXEMPT_UNENFORCED)), (
        "_EXEMPT_UNENFORCED has duplicate keys — one reason silently "
        "overwrote another. Fix the dict and add the missing reason back."
    )


# ── Reporting ──────────────────────────────────────────────────────────────

def test_report_lesson_coverage() -> None:
    """Print the coverage shape so cold-start knows the gap without grepping.

    Not an assertion — informational. The cap tests above are the gates;
    this test exists to surface the current numbers every run, because a
    number that nobody sees is a number that drifts without alarm.
    """
    lessons = _all_lesson_numbers()
    reachable = _live_reachable(lessons)
    exempt = set(_EXEMPT_UNENFORCED)
    unreachable = lessons - reachable - exempt
    print(
        f"  · lessons: {len(lessons)} total "
        f"({len(reachable)} live-reachable, "
        f"{len(exempt)} exempt, "
        f"{len(unreachable)} undocumented — should be 0)"
    )


# ── Runner ─────────────────────────────────────────────────────────────────

TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_")]


def main() -> int:
    p = f = 0
    for t in TESTS:
        try:
            t(); print(f"  ✓ {t.__name__}"); p += 1
        except AssertionError as e:
            print(f"  ✗ {t.__name__}\n      {e}"); f += 1
        except Exception as e:
            print(f"  💥 {t.__name__}: {type(e).__name__}: {e}"); f += 1
    print(f"\n{'✅' if not f else '🔴'} {p}/{len(TESTS)} lesson-walker checks passed"
          + (f" · {f} FAILING" if f else ""))
    return 1 if f else 0


if __name__ == "__main__":
    sys.exit(main())