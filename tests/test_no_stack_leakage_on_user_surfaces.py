"""
Guard: CLAUDE.md hard rule #8 — no implementation on investor-facing surfaces (S-139).

The rule already existed. It was violated in TEN rendered strings, including two
the rule names directly:

  · strategy.html (StrategyPage) shipped "Execution → Freqtrade + CEX APIs" — the
    execution framework, on the page we send to allocators.
  · The PAID TIER list offered "Dedicated Mac Mini scoring lane" and "Historical
    score data (Supabase)". A pricing page describing our hardware tells a
    competitor exactly what to clone and tells an allocator something that makes
    a $500M target harder to believe, not easier.
  · Every asset detail footer read "Mac Mini local engine" / "Railway estimation".
  · An error toast read "Railway may be starting up."

WHY A PROSE RULE WAS NOT ENOUGH. #8 is one line in CLAUDE.md and these strings
were written months apart by people who had read it. A rule that lives only in
prose is re-broken by every author who did not have it in mind at that moment;
the same argument produced test_compliance_language for BUY/SELL. This is the
second half of that: compliance language governs what we CLAIM, this governs what
we REVEAL.

WHAT COUNTS AS A LEAK. Vendor and hardware names — the things that answer "how is
this built?" rather than "what does it do?". Replacements say the CAPABILITY
instead: "full-model score" rather than "Mac Mini local engine". That is not
obfuscation; the tier, its meaning and its freshness stay visible. What goes away
is the part only a competitor benefits from.

COMMENTS ARE EXEMPT and string literals are not. A comment explaining the rule
necessarily contains the words it forbids — the same defect that made three
earlier guards fire on their own documentation.

Run: python3 -m tests.test_no_stack_leakage_on_user_surfaces
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "dashboard" / "src"

_FAILURES: list[str] = []

# Vendor / hardware / framework names. Not a style list — each one answers
# "how is it built", which is the question rule #8 says we do not answer.
_BANNED = [
    "Mac Mini", "Freqtrade", "Railway", "Ollama", "LM Studio", "FastAPI",
    "Supabase", "SUPABASE_", "Upstash", "Redis", "PostgREST", "pgvector",
]

# Strings that are legitimately user-facing despite matching. Keep this SHORT and
# make every entry justify itself; an allowlist that grows without argument is how
# a guard becomes decorative.
_ALLOW = [
    "OSL",           # named in the offering itself — the stablecoin LPs subscribe with
    "hyperliquid",   # HYPE is an ASSET IN THE UNIVERSE, not our infrastructure. The
                     # first version of this list banned it and the guard fired on a
                     # coin we score. A leak list that cannot tell a vendor from a
                     # holding will be silenced by whoever it annoys next.
]

# Exempt only when the WHOLE string is this token — i.e. it is a data value being
# compared or defaulted, not prose being shown. `json.source || "railway"` is a
# discriminator the code branches on; the badge it drives now renders
# FULL MODEL / ESTIMATED. A vendor name inside a sentence is display text and
# stays banned; a vendor name alone in a literal is a value.
#
# This distinction is the difference between a guard people keep and one they
# delete: matching identifiers as though they were copy produces failures that are
# obviously wrong, and a guard that cries wolf gets an allowlist entry per
# complaint until it means nothing.
_ALLOW_EXACT = {"railway", "local_engine", "railway_snapshot", "railway_t2_hourly"}


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  ✓ {name}")
    else:
        print(f"  ✗ {name} :: {detail}")
        _FAILURES.append(name)


def _rendered_strings(src: str) -> list[tuple[int, str]]:
    """String literals only, with // and /* */ comments removed.

    A guard whose subject is user-visible TEXT must not read the comments that
    explain the guard — three earlier suites in this repo fired on their own
    documentation before this was understood."""
    out = []
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    for i, line in enumerate(src.splitlines(), 1):
        stripped = line.lstrip()
        if stripped.startswith("//") or stripped.startswith("*"):
            continue
        line = re.sub(r"(?<!:)//.*$", "", line)          # trailing // (not in URLs)
        for m in re.finditer(r'"([^"\n]{4,})"|\'([^\'\n]{4,})\'|`([^`\n]{4,})`', line):
            out.append((i, m.group(1) or m.group(2) or m.group(3)))
    return out


def test_no_vendor_or_hardware_names_in_rendered_strings() -> None:
    hits: list[str] = []
    for p in sorted(_SRC.rglob("*.jsx")) + sorted(_SRC.rglob("*.js")):
        for lineno, s in _rendered_strings(p.read_text(encoding="utf-8")):
            if any(a in s for a in _ALLOW) or s.strip().lower() in _ALLOW_EXACT:
                continue
            for bad in _BANNED:
                if bad.lower() in s.lower():
                    hits.append(f"{p.relative_to(_SRC)}:{lineno} “{s[:70]}” ({bad})")
    check("no implementation names in rendered strings", not hits,
          "\n      " + "\n      ".join(hits[:12]))


def test_the_paid_tier_list_does_not_describe_our_hardware() -> None:
    """The sharpest instance, and the one that cost the most if left. A pricing
    page saying "Dedicated Mac Mini scoring lane" tells a competitor what to clone
    and tells an allocator that a $500M target runs on a desktop."""
    src = (_SRC / "components/StrategyPage.jsx").read_text(encoding="utf-8")
    for bad in ("Mac Mini", "Freqtrade", "Supabase"):
        check(f"tier list is free of “{bad}”", bad not in src.split("/*")[0] or
              bad not in "".join(l for l in src.splitlines()
                                 if not l.lstrip().startswith(("//", "*"))),
              f"{bad} still appears in a rendered string on strategy.html")


def test_a_retired_label_is_retired_everywhere() -> None:
    """2026-08-12. The nav labels were fixed and the UI did not change, because the
    same label is written TWICE — once in NAV_ITEMS (the sidebar) and once in the
    page's own SectionLabel heading. Renaming the menu and not the page is not a
    partial fix; from the user's side it is no fix, because the heading is what
    they read after clicking.

    There is no single source for these strings. Until there is, the retired ones
    are listed here — a list is a worse mechanism than a shared constant, and it is
    a much better mechanism than remembering."""
    retired = {
        "Trading Engine": "Research Desk",          # also leaked the execution stack
        "Simons IC Loop": "Information-Coefficient Loop",
        "Events & VC": "VC Funding Flows",          # the label promised events, showed funding
    }
    hits: list[str] = []
    for p in sorted(_SRC.rglob("*.jsx")) + sorted(_SRC.rglob("*.js")):
        for lineno, s in _rendered_strings(p.read_text(encoding="utf-8")):
            for old, new in retired.items():
                if old in s:
                    hits.append(f"{p.relative_to(_SRC)}:{lineno} “{s[:60]}” → should be “{new}”")
    check("retired labels appear nowhere in rendered strings", not hits,
          "\n      " + "\n      ".join(hits[:10]))


def test_the_rule_is_stated_where_the_nav_is_defined() -> None:
    """The nav subtitle is where this last broke ("IC Loop · Freqtrade · Live"),
    so the reason lives next to it rather than only in CLAUDE.md — an author
    editing a label should not have to have read a different file that morning."""
    # FOLLOW THE NAV, do not hardcode the file (2026-08-13). This asserted the
    # citation was in App.jsx. A design-audit refactor then moved NAV_ITEMS into
    # Sidebar.jsx and correctly took the comment with it — so the code did the
    # right thing and the guard failed, because the guard named a location while
    # the rule is about ADJACENCY. A guard that points at where something used
    # to be reports a violation when the codebase improves.
    defining = [f for f in sorted(_SRC.rglob("*.jsx"))
                if "NAV_ITEMS = " in f.read_text(encoding="utf-8")]
    check("exactly one file defines NAV_ITEMS", len(defining) == 1,
          f"{[str(f.relative_to(_SRC)) for f in defining]} — two nav definitions "
          f"means two places a label can leak from")
    if defining:
        src = defining[0].read_text(encoding="utf-8")
        check(f"{defining[0].name} cites hard rule #8 beside the nav it defines",
              "hard rule #8" in src and "implementation" in src,
              "the reason must sit next to the thing it governs — an author "
              "editing a label should not have to have read CLAUDE.md that morning")


def test_tier_meaning_survived_the_rewrite() -> None:
    """The fix must remove the VENDOR, not the INFORMATION. A user still needs to
    know a score is a full-model score rather than a market estimate — that is a
    data-quality fact they are entitled to, and hiding it would trade one
    honesty problem for another."""
    src = (_SRC / "components/CISAssetDetail.jsx").read_text(encoding="utf-8")
    check("asset detail still distinguishes the two tiers",
          "Full-model score" in src and "Market estimate" in src,
          "tier distinction was removed instead of renamed")


if __name__ == "__main__":
    print("── implementation leakage on user surfaces (hard rule #8, S-139) ──")
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_")]:
        fn()
    if _FAILURES:
        print(f"\n🔴 {len(_FAILURES)} FAILED: {_FAILURES}")
        sys.exit(1)
    print("\n✅ no implementation names on investor-facing surfaces")
