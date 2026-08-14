"""
Cold-start contract — the amnesia path, compiled into CI (2026-07-30).
=====================================================================

Every agent starts every session with zero memory. The 2026-07-29 P0 (S-92) was
not caused by its bug; it was caused by an earlier bypass (S-83, "Supabase kept
timing out, so I pulled prices from Binance instead and moved on") SURVIVING
across sessions. Each new session cold-started, read MEMORY.md + PROJECT_STATE.md,
saw nothing about it, and carried on. The amnesia path is not background
condition — it is the transmission mechanism.

Measured on 2026-07-30, a cold agent following CLAUDE.md exactly could NOT reach:
  · S-92 / S-93 or lessons #68-#70  (they live in a 5,672-line append-only ledger)
  · the still-open anonymous remote-write RPC
…and PROJECT_STATE's header was dated 2026-07-28 — older than the incident it
was supposed to be navigating.

PRINCIPLE: do not transmit memory, transmit verification. A cold agent cannot
remember anything, but it can run a command. Facts rot; commands don't.

These checks enforce the parts of docs/AMNESIA_PROTOCOL.md that must not depend
on anyone having read docs/AMNESIA_PROTOCOL.md.

Run: python3 -m tests.test_cold_start_contract
"""
import os
import pathlib
import re
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

REPO = pathlib.Path(__file__).resolve().parent.parent

MEMORY = REPO / "MEMORY.md"
STATE = REPO / "PROJECT_STATE.md"
LEDGER = REPO / "REFUTATION_LEDGER.md"

# MEMORY.md's own stated cap in CLAUDE.md is 4KB. It was 7,659 bytes when this
# test was written — nearly double, because the rule was never executable. A rule
# nobody enforces is a wish.
#
# 2026-08-07 — METRIC CORRECTED, and the correction needs its justification stated
# because it happened right after a trim that failed to meet the old number, which is
# exactly when moving a goalpost is least trustworthy.
# The rule's own stated purpose is "read at session start, 30s". Reading time scales
# with CHARACTERS, not bytes. MEMORY.md is bilingual and CJK costs 3 bytes/char, so
# byte-counting was charging triple for the densest lines in the file — the 2026-08-07
# trim cut real content and the byte count barely moved (5,934 → 5,126 B) while the
# character count told the truth (3,151 chars ≈ a genuine 30s read).
# Bytes were only ever a proxy that happens to equal characters for pure ASCII.
# For an English file NOTHING changes (1 byte = 1 char); this only stops penalising
# information-dense CJK. The cap is set BELOW today's value so it still ratchets.
#
# 2026-08-08 — the SOFT TARGET was removed, and that is a tightening, not a relaxation.
# A 3000-char advisory sat alongside the 3400 hard cap and warned on every single run
# for a full day without ever blocking anything. This file's own docstring says a rule
# nobody enforces is a wish, and MEMORY.md itself now carries "an always-on warning
# carries no information" (S-105). Keeping a permanent warning next to a real limit
# trains everyone to read past both. One number, enforced, ratcheting down only.
MEMORY_HARD_CAP = 3400   # CHARACTERS. Was 6144 bytes -> 3400 chars. Lower it, never raise it.

# 2026-08-15 (S-165) — THE CAP WAS ON THE WRONG FILE, and that is why nobody
# noticed the budget being spent.
#
# Minimax-C reported "MEMORY.md is too big". Measured, it was 3,390/3,400 —
# inside its cap, and the ONLY governed file in the set. What he was feeling was
# cold-start cost, and he attributed it to the one file that had a name attached
# to a limit. The actual bill, same measurement:
#
#     MEMORY.md          3,390 chars  ≈  1k tokens   ← capped, enforced, fine
#     CLAUDE.md         10,663        ≈  3k
#     PROJECT_STATE.md 315,708        ≈ 99k tokens   ← "read this at session start"
#     MINIMAX_SYNC.md  150,491        ≈ 47k
#
# 84% of PROJECT_STATE was two sections whose own headings called them history
# ("LANDED — kept for the lessons, not for the status"; "Building log"), and
# MINIMAX_SYNC contained a §RECENT header reading "rolling window; older →
# ARCHIVE" above 131k characters that had never once been archived.
#
# BOTH FILES HAD ALREADY WRITTEN DOWN THEIR OWN RULE AND NEITHER ENFORCED IT.
# That is this file's founding observation, applied to this file's blind spot:
# a rule nobody enforces is a wish. Capping one file taught us to trust the cap
# and stop looking at the other three — a guard with too narrow a scope does not
# merely miss things, it actively redirects attention away from them.
#
# So the caps below are deliberately generous. They are not a diet; they are a
# tripwire that fires before a file gets back to six figures, and they name the
# split target in the failure message so the fix is obvious at 3am.
COLD_START_CAPS = {
    # file            cap      where the history goes
    "PROJECT_STATE.md": (80_000, "PROJECT_STATE_LOG.md"),
    "MINIMAX_SYNC.md":  (80_000, "MINIMAX_SYNC_ARCHIVE.md"),
    "CLAUDE.md":        (16_000, "a skill under .claude/skills/"),
}

# ≤7 is a design choice, not laziness: a 30-item risk list and no list are
# equivalent — neither gets read to the end.
OPEN_RISKS_MAX = 7


def _read(p: pathlib.Path) -> str:
    return p.read_text(encoding="utf-8") if p.exists() else ""


def test_memory_stays_within_cap():
    """MEMORY.md is the ONE file guaranteed to be read cold. Past a few KB it
    stops being an index and becomes another document that gets skimmed."""
    size = len(_read(MEMORY))          # CHARACTERS — see the note above the constants
    assert size <= MEMORY_HARD_CAP, (
        f"MEMORY.md is {size} chars > hard cap {MEMORY_HARD_CAP}. It is the only file "
        f"guaranteed read on cold start; if it bloats, cold start reads nothing. "
        f"Evict dated/expiring facts to PROJECT_STATE or the ledger — MEMORY holds "
        f"only never-expiring facts.")
    # Report headroom rather than warn: a number that is printed every run should be
    # information, not an alarm. When headroom gets thin, evict something with a guard —
    # if a test already catches a fact, the test is the memory.
    print(f"  · MEMORY.md {size}/{MEMORY_HARD_CAP} chars ({MEMORY_HARD_CAP - size} headroom)")


def test_the_whole_cold_start_read_stays_affordable():
    """MEMORY.md was capped and the other three were not, so the budget was spent
    where nobody was counting. Every file an agent is INSTRUCTED to read on start
    is governed here, or the cap just moves the bloat next door."""
    root = MEMORY.parent
    over = []
    for name, (cap, split_to) in sorted(COLD_START_CAPS.items()):
        f = root / name
        if not f.exists():          # MINIMAX_SYNC.md is gitignored — absent is fine
            print(f"  · {name} absent (not tracked here)")
            continue
        n = len(_read(f))
        print(f"  · {name} {n}/{cap} chars ({cap - n} headroom)")
        if n > cap:
            over.append(
                f"{name} is {n} chars > {cap}. Move settled content to {split_to} "
                f"and leave a pointer. Keep what is TRUE NOW; a section whose own "
                f"heading calls it history is not state.")
    assert not over, "cold-start budget exceeded:\n  " + "\n  ".join(over)


def test_history_was_split_out_and_not_deleted():
    """S-165 moved 266k characters out of PROJECT_STATE. This asserts the move
    was a MOVE. A split that quietly drops the lessons is worse than the bloat —
    the graveyard is the asset, and the build log is where the graveyard is."""
    root = MEMORY.parent
    log = root / "PROJECT_STATE_LOG.md"
    assert log.exists(), (
        "PROJECT_STATE_LOG.md is missing. PROJECT_STATE.md points at it for "
        "'## LANDED' and '## Building log'; a pointer to nothing is worse than "
        "the wall of text it replaced.")
    body = _read(log)
    for heading in ("## LANDED", "## Building log"):
        assert heading in body, f"{heading} did not survive the split into the log"
    state = _read(STATE)
    assert "PROJECT_STATE_LOG.md" in state, (
        "PROJECT_STATE.md must say where the history went — an agent looking for "
        "why a decision was made has to be able to follow the trail.")


def test_project_state_opens_with_open_risks():
    """A cold agent reads the top of PROJECT_STATE and nothing else is guaranteed.
    If the first screen is narrative, the agent starts on last week's priority —
    which is exactly what happened on 2026-07-30 (header dated 2026-07-28, i.e.
    older than the P0 it should have been pointing at)."""
    txt = _read(STATE)
    assert txt, "PROJECT_STATE.md missing"
    head = "\n".join(txt.splitlines()[:60])
    assert re.search(r"^##\s*OPEN RISKS", head, re.M), (
        "PROJECT_STATE.md must open with a '## OPEN RISKS' block within the first "
        "60 lines, BEFORE any narrative. See docs/AMNESIA_PROTOCOL.md §4a. Cold "
        "start reads the first screen; that screen must carry live danger, not prose.")


def test_every_open_risk_carries_a_verify_line():
    """The whole protocol in one assertion: a risk without a VERIFY command is not
    recorded, because the next amnesiac agent has no way to check whether it is
    still true — and will not take prose on faith (correctly)."""
    txt = _read(STATE)
    m = re.search(r"^##\s*OPEN RISKS.*?$(.*?)(?=^##\s)", txt, re.M | re.S)
    if not m:
        return  # covered by the previous test
    block = m.group(1)
    # TOP-LEVEL only — no leading whitespace. The `\s*` version counted numbered
    # sub-points inside a risk's own body as separate risks (7 real, 11 counted), so
    # the cap fired on a list that was within it. A guard that miscounts the thing it
    # caps teaches people to raise the cap, which is the opposite of its purpose.
    items = re.findall(r"^\d+\.\s+(.*?)(?=^\d+\.\s|\Z)", block, re.M | re.S)
    assert items, "OPEN RISKS block is empty — if truly zero risks, say so explicitly"
    assert len(items) <= OPEN_RISKS_MAX, (
        f"{len(items)} open risks > {OPEN_RISKS_MAX}. Converge or close some; a list "
        f"too long to read is equivalent to no list.")
    for i, it in enumerate(items, 1):
        assert "VERIFY:" in it, (
            f"OPEN RISK #{i} has no 'VERIFY:' line. Every risk must ship the one "
            f"command that re-establishes whether it is still open. If genuinely "
            f"unverifiable, write 'VERIFY: none — this is itself the gap' and treat "
            f"it as top priority (that is the alerting hole).")
        assert "OWNER:" in it, f"OPEN RISK #{i} has no 'OWNER:' — unowned risks rot"


def test_project_state_header_not_older_than_newest_ledger_entry():
    """Staleness must be mechanical, not a judgement call. If the ledger has an
    entry newer than PROJECT_STATE's header, the navigation layer is behind the
    evidence layer and a cold agent will be misrouted."""
    state, ledger = _read(STATE), _read(LEDGER)
    if not state or not ledger:
        return
    hm = re.search(r"\*\*Last updated:\*\*\s*(\d{4}-\d{2}-\d{2})", state)
    assert hm, "PROJECT_STATE.md must carry '**Last updated:** YYYY-MM-DD'"
    # Dates from ENTRY HEADINGS only. A first pass scanned the whole ledger body and
    # picked up 2027-05-13 — a projected OOS window quoted inside an entry, not an
    # entry date. A staleness check that fires on forward-looking dates in prose is
    # itself a false-positive generator, and a check that cries wolf gets muted,
    # which is the failure mode this whole file exists to prevent.
    headings = [l for l in ledger.splitlines() if l.startswith("## ")]
    dates = [d for h in headings for d in re.findall(r"\b(20\d{2}-\d{2}-\d{2})\b", h)]
    import datetime as _dt
    today = _dt.date.today().isoformat()
    dates = [d for d in dates if d <= today]        # never trust a future entry date
    if not dates:
        return
    newest = max(dates)
    assert hm.group(1) >= newest, (
        f"PROJECT_STATE header says {hm.group(1)} but the ledger has an entry dated "
        f"{newest}. The navigation layer is behind the evidence layer — a cold agent "
        f"will start on a stale priority. Update the header in the SAME turn work lands.")


def test_ledger_lessons_are_not_ledger_only():
    """A lesson that lives only in a 5,672-line append-only ledger does not change
    behaviour, because cold start never reads it. Each numbered lesson must also
    surface as an executable check or an OPEN RISK. This is the dividing line
    between an archive and a memory."""
    ledger, state = _read(LEDGER), _read(STATE)
    lessons = set(re.findall(r"\*\*Lesson #(\d+)", ledger))
    if not lessons:
        return
    recent = sorted(lessons, key=int)[-3:]          # the three newest
    tests_blob = "\n".join(
        _read(p) for p in (REPO / "tests").glob("test_*.py"))
    reachable = tests_blob + state
    missing = [n for n in recent if f"#{n}" not in reachable]
    assert not missing, (
        f"Lesson(s) {missing} exist only in the ledger. Ledger-only = archived, not "
        f"remembered: cold start does not read 5,000+ lines. Cite the lesson number "
        f"in the test that enforces it, or raise it as an OPEN RISK in PROJECT_STATE.")


def test_amnesia_protocol_document_exists():
    """The written walk-through of the cold-start path. Referenced by CLAUDE.md so
    the path itself is discoverable, not folklore."""
    doc = REPO / "docs" / "AMNESIA_PROTOCOL.md"
    assert doc.exists(), "docs/AMNESIA_PROTOCOL.md missing — the cold-start contract"
    t = _read(doc)
    for anchor in ("OPEN RISKS", "VERIFY:", "S-83"):
        assert anchor in t, f"AMNESIA_PROTOCOL.md lost its '{anchor}' section"


def test_every_test_file_actually_runs_the_tests_it_defines():
    """Lesson #105: a green test summary is not evidence the tests ran.

    Found the hard way (S-124). `TESTS = [v for k, v in globals() ...]` sat in the
    MIDDLE of test_beta_core_book.py, so four guards appended below it were collected
    by nothing — and the file still printed a confident "14/14 passed". A collector
    that runs before the things it collects fails silently and looks healthy, which
    is the worst combination available.

    Lesson #106, its companion: assert over the whole syntactic unit. The first cut of
    one of those four guards matched a multi-line query with a single-line regex, so
    it PASSED a query it had only read the first fragment of. Every new guard needs a
    negative control — put the defect back and confirm it goes red.

    This test is the structural fix for #105: the collector must come after the last
    test definition in every file."""
    import ast
    import pathlib as _pl
    repo = _pl.Path(__file__).resolve().parent.parent
    offenders = []
    for p in sorted((repo / "tests").glob("test_*.py")):
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:
            continue
        last_test = max((n.lineno for n in tree.body
                         if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                         and n.name.startswith("test_")), default=None)
        if last_test is None:
            continue
        collector = next((n.lineno for n in tree.body
                          if isinstance(n, ast.Assign)
                          and any(getattr(t, "id", None) == "TESTS" for t in n.targets)), None)
        if collector is not None and collector < last_test:
            skipped = sum(1 for n in tree.body
                          if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                          and n.name.startswith("test_") and n.lineno > collector)
            offenders.append(f"{p.name}: TESTS at line {collector} misses "
                             f"{skipped} test(s) defined below it")
    assert not offenders, (
        "test collector runs before the tests it collects — these pass silently and "
        "the file still reports green:\n  " + "\n  ".join(offenders))


TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_")]

if __name__ == "__main__":
    p = f = 0
    for t in TESTS:
        try:
            t(); print(f"  ✓ {t.__name__}"); p += 1
        except AssertionError as e:
            print(f"  ✗ {t.__name__}\n      {e}"); f += 1
    print(f"\n{'✅' if not f else '🔴'} {p}/{len(TESTS)} cold-start contract checks passed"
          + (f" · {f} FAILING" if f else ""))
    sys.exit(1 if f else 0)
