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
# nobody enforces is a wish. Grace allows landing this test before the cleanup;
# lower it to 4096 once MEMORY.md is trimmed, and never raise it.
MEMORY_HARD_CAP = 6144   # lowered 8192→6144 after the 2026-08-06 trim; ratchet down only
MEMORY_TARGET = 4096

# ≤7 is a design choice, not laziness: a 30-item risk list and no list are
# equivalent — neither gets read to the end.
OPEN_RISKS_MAX = 7


def _read(p: pathlib.Path) -> str:
    return p.read_text(encoding="utf-8") if p.exists() else ""


def test_memory_stays_within_cap():
    """MEMORY.md is the ONE file guaranteed to be read cold. Past a few KB it
    stops being an index and becomes another document that gets skimmed."""
    size = MEMORY.stat().st_size
    assert size <= MEMORY_HARD_CAP, (
        f"MEMORY.md is {size}B > hard cap {MEMORY_HARD_CAP}B. It is the only file "
        f"guaranteed read on cold start; if it bloats, cold start reads nothing. "
        f"Evict dated/expiring facts to PROJECT_STATE or the ledger — MEMORY holds "
        f"only never-expiring facts.")
    if size > MEMORY_TARGET:
        print(f"  ⚠️  MEMORY.md {size}B is over its {MEMORY_TARGET}B target "
              f"(CLAUDE.md says ≤4KB) — trim, then lower MEMORY_HARD_CAP.")


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
    items = re.findall(r"^\s*\d+\.\s+(.*?)(?=^\s*\d+\.\s|\Z)", block, re.M | re.S)
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
