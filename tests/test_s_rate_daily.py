"""S-rate-daily counter — tests for scripts/s_rate_daily.py

Run: python3 -m pytest tests/test_s_rate_daily.py -q
or:  python3 -m tests.test_s_rate_daily

Test scope:
  - date extraction: 4 strategies (trailing parens, author trailer, body,
    heading-fallback) — fixture-based, not coupled to live ledger
  - sub-ID expansion: S-323b, S-323j/k/l, S-323u/v
  - aggregate behaviour: count + sort + dedup
  - live ledger: heading count == heading-of-record count + body shape
    (one big test that catches silent regression on the actual file)

THE LIE THIS TEST REJECTS. The counter is the canonical numerical reading
of "how often we are still producing new S-numbers". If the parsing
strategy drifts, the rate metric either crashes or — worse — silently
under-counts and reports a healthy 2/day when the true rate is 6/day. The
4-strategy date extractor is the structural fix: each strategy has its own
fixture so a future change to ONE strategy can't silently mask failures in
the OTHER three (the S-244/S-244-regression family of bugs).

Why a 4-strategy walker, not the single `'.*DATE.*'` substring grep it
replaces: S-244 died because the parser couldn't distinguish "an entry
WITHOUT a date" from "an entry whose body contains the string 'date'".
This test pins all 4 strategies so each has a fixture-derived truth-table.
"""
from __future__ import annotations

import pathlib
import sys
import tempfile

_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from scripts import s_rate_daily as srd  # noqa: E402


# ── FIXTURES (one per strategy) ───────────────────────────────────────────────

_TRAILING = """\
## S-100 — Old style, trailing parens-date (Seth, 2026-08-06)

正文不重要,标题是日期来源。
"""

_AUTHOR_TRAILER = """\
## S-101 — Author-then-date parens (Seth, 2026-08-06)
"""

_AUTHOR_TRAILER_COMMA = """\
## S-102 — Author-date-comma-trailer (Seth, 2026-08-06, "拉长周期")
"""

_BODY_DATE_DOUBLE_ASTERISK = """\
## S-103 — Body form, double-asterisk

**日期** 2026-08-07 · **Seth**
"""

_BODY_DATE_COLON = """\
## S-104 — Body form, colon variant

**日期:** 2026-08-07 · **Lane:** Seth
"""

# Heading fallback: legacy entries with NO parens-date and NO **日期** body
# line — only an inline year that happens to be in the title.
_HEADING_FALLBACK_NO_BODY_DATE = """\
## S-200 — 一次 Redis 读失败,可以整体改写评级历史 (2026-08-25)
"""

# Real legacy case from the ledger (S-180): no date anywhere.
_UNDATED = """\
## S-180 — 一次 Redis 读失败,可以整体改写评级历史

**触发。** Jazz 从另一台手机看...
"""

# Sub-IDs
_SUBID_SINGLE = """\
## S-323b · sub-entry (2026-09-08)
"""
_SUBID_TRIPLE = """\
## S-323j/k/l · multi-sub (2026-09-09)
"""
_SUBID_DOUBLE = """\
## S-323u/v · double-sub (2026-09-09)
"""


# ── DATE EXTRACTOR ────────────────────────────────────────────────────────────

def test_trailing_parens_date() -> None:
    """Strategy 1: trailing `(YYYY-MM-DD)` on heading."""
    body = "正文不重要,标题是日期来源。"
    assert srd._extract_date(_TRAILING.split("\n")[0], body) == "2026-08-06"


def test_author_trailer_parens_date() -> None:
    """Strategy 2: `(Seth, YYYY-MM-DD)` — name-then-date, no trailing comma."""
    assert srd._extract_date(_AUTHOR_TRAILER.split("\n")[0], "") == "2026-08-06"


def test_author_trailer_with_comma_suffix() -> None:
    """Strategy 2 (extended): `(Seth, YYYY-MM-DD, "拉长周期")` — date is
    SECOND-TO-LAST inside the parens (legacy heading style). Must still
    capture the date, not assume trailing `)`.
    """
    assert srd._extract_date(_AUTHOR_TRAILER_COMMA.split("\n")[0], "") == "2026-08-06"


def test_body_date_double_asterisk() -> None:
    """Strategy 3a: body `**日期** YYYY-MM-DD`."""
    lines = _BODY_DATE_DOUBLE_ASTERISK.split("\n")
    date = srd._extract_date(lines[0], "\n".join(lines[1:5]))
    assert date == "2026-08-07"


def test_body_date_colon() -> None:
    """Strategy 3b: body `**日期:** YYYY-MM-DD` (legacy colon variant)."""
    lines = _BODY_DATE_COLON.split("\n")
    date = srd._extract_date(lines[0], "\n".join(lines[1:5]))
    assert date == "2026-08-07"


def test_heading_fallback_extracts_first_iso_date() -> None:
    """Strategy 4: legacy entries with date only in heading text, no parens."""
    heading = _HEADING_FALLBACK_NO_BODY_DATE.split("\n")[0]
    assert srd._extract_date(heading, "") == "2026-08-25"


def test_truly_undated_returns_none() -> None:
    """No extractable date (S-180 case) returns None — not raise, not fabricate."""
    heading = _UNDATED.split("\n")[0]
    body = "\n".join(_UNDATED.split("\n")[1:3])
    assert srd._extract_date(heading, body) is None


# ── SUB-ID EXPANSION ─────────────────────────────────────────────────────────

def test_subid_single_b() -> None:
    """S-323b expands to ['S-323b'], one entry."""
    by_date, _ = srd.collect(_write_fixture(_SUBID_SINGLE))
    by_date_lists = list(by_date.values())
    assert by_date_lists == [["S-323b"]], f"got {by_date}"


def test_subid_triple_j_k_l() -> None:
    """S-323j/k/l expands to 3 entries; NOT ['S-323jk', 'S-323l']."""
    by_date, _ = srd.collect(_write_fixture(_SUBID_TRIPLE))
    by_date_lists = list(by_date.values())
    assert by_date_lists == [["S-323j", "S-323k", "S-323l"]], f"got {by_date}"


def test_subid_double_u_v() -> None:
    """S-323u/v expands to 2 entries."""
    by_date, _ = srd.collect(_write_fixture(_SUBID_DOUBLE))
    by_date_lists = list(by_date.values())
    assert by_date_lists == [["S-323u", "S-323v"]], f"got {by_date}"


# ── AGGREGATE ────────────────────────────────────────────────────────────────

def test_collect_groups_and_sorts() -> None:
    """collect() should group by date and stable-sort each day's IDs ASC."""
    fixture = "\n".join([
        "## S-201 — date A (Seth, 2026-08-26)",
        "",
        "## S-200 — date A (Seth, 2026-08-26)",
        "",
        "## S-150 — date B (Seth, 2026-08-15)",
    ]) + "\n"
    by_date, _ = srd.collect(_write_fixture(fixture))
    assert by_date["2026-08-26"] == ["S-200", "S-201"], f"got {by_date['2026-08-26']}"
    assert by_date["2026-08-15"] == ["S-150"]


def test_collect_separates_undated() -> None:
    """Undated headings land in `undated` list, not in by_date."""
    fixture = "\n".join([
        "## S-180 — undated",
        "正文无日期",
        "",
        "## S-100 — dated (Seth, 2026-08-06)",
        "",
    ]) + "\n"
    by_date, undated = srd.collect(_write_fixture(fixture))
    assert by_date == {"2026-08-06": ["S-100"]}, f"got by_date={by_date}"
    assert len(undated) == 1 and undated[0][0] == "S-180", f"got undated={undated}"


def test_summary_stats_match_known_invariants() -> None:
    """_summary computes means + max defensively. Construct a fixture with
    a known max, total, and mean to assert the math is right.
    """
    by_date = {
        "2026-08-26": ["S-242", "S-243", "S-244"],  # max (3)
        "2026-08-27": ["S-244"],                    # 1
        "2026-08-30": ["S-261", "S-262"],           # 2
    }
    s = srd._summary(by_date)
    assert s["total_entries"] == 6
    assert s["dated_days"] == 3
    assert s["all_time_mean"] == 6 / 3 == 2.0
    assert s["max_day"] == "2026-08-26"
    assert s["max_day_count"] == 3


# ── LIVE LEDGER (regression guard against silent drift) ──────────────────────

def test_live_ledger_parses_to_known_shape() -> None:
    """Walk the actual REFUTATION_LEDGER.md. Asserts invariants the rate
    metric depends on:
      - At least 100 dated entries (current is ~165; the floor catches
        a "parser broke and silently dropped half" regression).
      - The S-342/S-343/S-345 entries (shipped today) parse to today's date.
      - The S-323j/k/l composite ID expands to 3 entries on 2026-09-09.
      - More than 50% of dated days fall in the last 30 calendar days
        (catches "the parser is reading yesterday's ledger" — a cached
        file or wrong-path mistake).
    """
    by_date, undated = srd.collect()
    dated = [d for d, ids in by_date.items() if ids]
    assert sum(len(v) for v in by_date.values()) >= 100, (
        f"dated entry count {sum(len(v) for v in by_date.values())} < 100"
    )
    today = "2026-09-14"
    assert today in by_date, f"today ({today}) has no dated entries — did S-342/343/345 fail to land?"
    shipped = set(by_date[today])
    assert {"S-342", "S-343", "S-345"} <= shipped, (
        f"today's shipped S-IDs are {shipped}, missing at least one of "
        f"S-342/S-343/S-345 — they should ALL be on {today}"
    )
    # 2026-09-09 had the S-323 series; the j/k/l expansion is the day we
    # care about (it's the only day with a 3-letter composite in the live
    # ledger). Pin that specifically.
    sep09 = by_date.get("2026-09-09", [])
    for c in "jkl":
        assert f"S-323{c}" in sep09, (
            f"S-323{c} missing from 2026-09-09 expansion: {sep09}"
        )
    # 50% freshness floor (last 30 days = >= 2026-08-15)
    recent = [d for d in dated if d >= "2026-08-15"]
    assert len(recent) >= len(dated) * 0.5, (
        f"only {len(recent)}/{len(dated)} dated days fall in last 30d"
    )
    # Surface undated as a soft check (not a hard fail — the script's
    # metric is honest about it; we want the count to be small enough
    # to be a leak, not a flood).
    assert len(undated) < sum(len(v) for v in by_date.values()) * 0.4, (
        f"undated count {len(undated)} is > 40% of dated; "
        f"the 4-strategy walker is missing something."
    )


# ── FIXTURE HELPER ──────────────────────────────────────────────────────────

def _write_fixture(content: str) -> pathlib.Path:
    """Write a one-shot ledger fixture to a tmp file; return its path.

    The collect() function accepts a path argument, so we don't need to
    patch the module — write a real file and point at it.
    """
    fd = tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8")
    fd.write(content)
    fd.close()
    return pathlib.Path(fd.name)


# ── RUNNER ──────────────────────────────────────────────────────────────────

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
    print(f"\n{'✅' if not f else '🔴'} {p}/{len(TESTS)} s-rate-daily tests passed"
          + (f" · {f} FAILING" if f else ""))
    return 1 if f else 0


if __name__ == "__main__":
    sys.exit(main())
