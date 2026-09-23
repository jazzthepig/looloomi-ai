"""S-rate-daily counter — number of new S-number entries per UTC day.

Task #113: §S-RATE-DAILY. Tracks the daily rate of new S-number assignments
in `REFUTATION_LEDGER.md`. The 7-change Minimax-C structural plan's success
metric is **rate decline**:
  - Pre-plan: ~6 S/day (Pattern A discovery cadence)
  - Post-plan target: <2 S/day (Pattern A + D largely closed)
  - Window: 14 days from plan ship (2026-09-14 → 2026-09-28)

Reads the ledger, groups entries by date, prints a sorted table. Pure read-only;
writes to stdout only. Designed to be run weekly by hand from the Seth lane or
from a cron on the Mac; never modifies the ledger itself (rule: APPEND-ONLY at
EOF, claim heading before body).

Run:
    python3 scripts/s_rate_daily.py                # table, full history
    python3 scripts/s_rate_daily.py --since 14    # last 14 days only
    python3 scripts/s_rate_daily.py --md           # markdown for PROJECT_STATE

THE LIE THIS COUNTER PREVENTS. Two failure shapes both look like S-rate
"levels off":
  - **Stale agent reports "we're at 3/day"** based on the last 7 days, when
    the 7d window is dominated by a single big-day cluster (S-323 had 12+
    sub-entries on 2026-09-08) — clipping misses it.
  - **New S-numbers are added but never reach the table** (a fresh refutation
    stays in PROJECT_STATE.md until someone copies it into REFUTATION_LEDGER,
    and the counter shows the gap as a decline — false positive of success).

Both shapes ARE the same family of failure as S-323x/S-336 ("looks healthy,
actual stop"): a measurement instrument that mistakes its own blind spot for
a true signal. This script is the read-side discipline that closes it: it
**counts headings only, then groups by parsed date** so the metric is on the
same surface a reader counts on, and any future heading-format change has to
either keep this script honest or fail loud in CI.
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_LEDGER = _REPO_ROOT / "REFUTATION_LEDGER.md"

# Heading: `## S-NNN <separator> <title> [optional parens-trailer]`.
# Separators in the ledger include: ` — `, ` · `, `·`, `—`.
# Sub-IDs: S-323b/c/d and ranges like S-323j/k/l or S-323u/v — we extract
# the FULL prefix (digits + optional letter-range string) and post-process
# into a list of one entry (most) or N entries (slash-joined ranges).
_HEADING_RE = re.compile(r"^## S-(\d+(?:[a-z](?:/[a-z])*|[a-z]+)?)")

# Date form 1: trailing `(YYYY-MM-DD)` at end of heading line
_DATE_TRAILING_RE = re.compile(r"\((\d{4}-\d{2}-\d{2})\)\s*$")
# Date form 2: `(Seth, 2026-09-14)` / `(Name, YYYY-MM-DD)` — the name-then-date
# comma form. We require the date to be followed by EITHER `)` OR `,` (NOT
# a comma-separated trailing phrase like `(Seth, 2026-07-23, "拉长周期")`),
# because those entries DO want the date but it's the SECOND-TO-LAST item.
_DATE_AUTHOR_TRAILER_RE = re.compile(
    r"\([^()]*?(\d{4}-\d{2}-\d{2})(?:[,)]+[^)]*)?\)"
)
# Date form 3: body line `**日期** YYYY-MM-DD` OR `**日期:** YYYY-MM-DD`
# (the legacy colon variant — S-151/S-153/S-162 use this). `\*+` instead of
# `\*?` because `**日期:**` has TWO asterisks after the colon — the
# singular form fails on those entries.
_DATE_BODY_RE = re.compile(r"\*\*日期[:\*]+\s+(\d{4}-\d{2}-\d{2})")
# Date form 4: last-resort heading fallback — first `YYYY-MM-DD` anywhere in
# the heading line. Most ledger headings have only one date; entries that
# REFERENCE other S-numbers with dates don't appear in HEADINGS (only body).
# Used only when no other form matches.
_DATE_HEADING_ANY_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")

# Date form 5: first YYYY-MM-DD in body lines that are NOT inside a fenced
# code block (```). Catches ~48 entries that have an ISO date in narrative
# form but no `**日期**` marker — e.g. "**Jazz 的要求** ... 2026-07-08",
# "(2026-08-23)" inline, quoted message dates. The 2026-09-23 walker audit
# showed 75% of body-ISO-dates fall in the first 10% of body, so picking
# the FIRST one is almost always the entry date; mid-body fallbacks are
# rare (2/48 cases) and still better than None. Code-block skip prevents
# matching timestamps like "08-19 09:02" which aren't ISO dates anyway.
_FENCE_RE = re.compile(r"^\s*```")


def _first_iso_date_in_body(body_slice: str) -> str | None:
    """First YYYY-MM-DD outside fenced code blocks; None if not found."""
    in_code = False
    for line in body_slice.splitlines():
        if _FENCE_RE.match(line):
            in_code = not in_code
            continue
        if in_code:
            continue
        m = _DATE_HEADING_ANY_RE.search(line)
        if m:
            return m.group(1)
    return None


def _extract_date(heading_line: str, body_slice: str) -> str | None:
    """Return ISO date string for a `## S-NNN` heading, or None if unparseable.

    Strategies, in order:
      1. Trailing parens-date `(YYYY-MM-DD)` at end of heading.
      2. Author-then-date parens `(Name, YYYY-MM-DD[, ...])` anywhere in heading.
      3. Body line containing `**日期** ` or `**日期:**` with a YYYY-MM-DD
         (searched over a 20-line body window so legacy entries with 2
         leading blank lines still parse).
      4. First YYYY-MM-DD in body, outside fenced code blocks. Catches
         entries that have an ISO date in narrative form but no `**日期**`
         marker (48 entries as of 2026-09-23 audit).
      5. Last resort: first YYYY-MM-DD anywhere in the heading line.
         Used only when 1-4 fail. Body never falls back to this.
    Returns None (not raises) so the caller can decide whether to count or skip.
    """
    m = _DATE_TRAILING_RE.search(heading_line)
    if m:
        return m.group(1)
    m = _DATE_AUTHOR_TRAILER_RE.search(heading_line)
    if m:
        return m.group(1)
    m = _DATE_BODY_RE.search(body_slice)
    if m:
        return m.group(1)
    m = _first_iso_date_in_body(body_slice)
    if m:
        return m
    m = _DATE_HEADING_ANY_RE.search(heading_line)
    if m:
        return m.group(1)
    return None


def collect(ledger_path: Path = _LEDGER) -> tuple[dict[str, list[str]], list[tuple[str, str | None]]]:
    """Walk the ledger; return (by_date, undated_seq).

    by_date maps `YYYY-MM-DD -> [S-XXX, ...]` (one list per day). Each
    entry ID appears once. The list is ordered by ledger position so the
    table reads in commit order, not numerically (a 2-S day writes to the
    table in the order it was written to the ledger, which is what the rate
    metric actually measures — not "what s-number was the 87th entry",
    which is meaningless).

    Sub-IDs (S-323j/k/l) are expanded: `j`, `k`, `l` are each their own
    entry on that day. Composite IDs preserve order from the heading.

    undated_seq is the ordered list of (S-XXX, body_excerpt_or_None)
    for headings where NO date form matched. These are NOT counted in the
    rate (an honest "no date" beats a fabricated one). They are returned so
    the caller can surface them as drift.
    """
    text = ledger_path.read_text(encoding="utf-8")
    lines = text.splitlines()

    by_date: dict[str, list[str]] = defaultdict(list)
    undated: list[tuple[str, str | None]] = []

    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        m = _HEADING_RE.match(line)
        if not m:
            i += 1
            continue
        raw_id = m.group(1)  # e.g. "323" or "323b" or "323j/k/l"
        # Look at next 20 lines for body-form date — but break on any next
        # heading so we never silently swallow an entire neighbour's body.
        body_window: list[str] = []
        for j in range(i + 1, min(i + 21, n)):
            if _HEADING_RE.match(lines[j]):
                break
            body_window.append(lines[j])
        date = _extract_date(line, "\n".join(body_window))
        # Expand sub-IDs. "323" -> ["S-323"]; "323b" -> ["S-323b"];
        # "323j/k/l" -> ["S-323j", "S-323k", "S-323l"];
        # "323u/v" -> ["S-323u", "S-323v"].
        if "/" in raw_id:
            parts = raw_id.split("/")
            # parts[0] may include a digit prefix + first letter (e.g. "323j").
            # Split THAT on the trailing-letter boundary to recover head="323".
            first = parts[0]
            digits_end = 0
            while digits_end < len(first) and first[digits_end].isdigit():
                digits_end += 1
            head = first[:digits_end]
            first_letter = first[digits_end:]
            sub_letters = ([first_letter] if first_letter else []) + parts[1:]
            ids = [f"S-{head}{l}" for l in sub_letters]
        else:
            ids = [f"S-{raw_id}"]
        if date is None:
            for sid in ids:
                undated.append((sid, "\n".join(body_window)[:120] or None))
        else:
            by_date[date].extend(ids)
        i += 1
    # Stable-sort each day's list by entry id ASC for legibility.
    for d in by_date:
        by_date[d].sort()
    return dict(by_date), undated


def to_table(by_date: dict[str, list[str]], since_days: int | None = None) -> str:
    """Render the table. `since_days=None` prints full history; otherwise the
    table starts at `today - since_days`. (Caller passes in the cutoff date
    if it wants a window; we don't compute 'today' here to keep this pure.)
    """
    if not by_date:
        return "(no dated S-entries in ledger)"
    dates = sorted(by_date.keys())
    if since_days is not None:
        # `since_days` here is the date-string of the cutoff, e.g. "2026-09-01".
        # Named for the historical "--since N days" interface; we accept a date
        # string directly for testability.
        cutoff = since_days
        dates = [d for d in dates if d >= cutoff]
    width = max(len(d) for d in dates)
    out = [f"{'date':<{width}}  count  s-numbers"]
    out.append("-" * (width + 2 + 5 + 2 + 60))
    for d in dates:
        nums = by_date[d]
        nums_str = " ".join(nums)
        out.append(f"{d:<{width}}  {len(nums):>5}  {nums_str}")
    return "\n".join(out)


def to_markdown(by_date: dict[str, list[str]], since_days_date: str | None = None) -> str:
    """Markdown rendering for PROJECT_STATE.md snippet."""
    if not by_date:
        return "_(no dated S-entries)_"
    dates = sorted(by_date.keys())
    if since_days_date is not None:
        dates = [d for d in dates if d >= since_days_date]
    out = ["| date | count | s-numbers |", "|------|------:|-----------|"]
    for d in dates:
        nums = by_date[d]
        nums_str = ", ".join(nums)
        out.append(f"| {d} | {len(nums)} | {nums_str} |")
    return "\n".join(out)


def _summary(by_date: dict[str, list[str]]) -> dict[str, float]:
    """Compute headline summary stats.
    Returns dict with keys: total_entries, dated_days, undated_count,
    last_7d_mean, last_14d_mean, all_time_mean, max_day, max_day_count.
    """
    if not by_date:
        return {}
    dates = sorted(by_date.keys())
    counts = [len(by_date[d]) for d in dates]
    last7 = dates[-7:] if len(dates) >= 7 else dates
    last14 = dates[-14:] if len(dates) >= 14 else dates
    last7_counts = [len(by_date[d]) for d in last7]
    last14_counts = [len(by_date[d]) for d in last14]
    max_idx = counts.index(max(counts))
    return {
        "total_entries": sum(counts),
        "dated_days": len(dates),
        "last_7d_mean": sum(last7_counts) / max(len(last7_counts), 1),
        "last_14d_mean": sum(last14_counts) / max(len(last14_counts), 1),
        "all_time_mean": sum(counts) / max(len(counts), 1),
        "max_day": dates[max_idx],
        "max_day_count": counts[max_idx],
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    p.add_argument("--since", metavar="YYYY-MM-DD",
                   help="only show entries on/after this date")
    p.add_argument("--md", action="store_true", help="markdown output")
    p.add_argument("--summary", action="store_true", help="print headline summary stats")
    p.add_argument("--ledger", type=Path, default=_LEDGER,
                   help="override ledger path (for tests)")
    args = p.parse_args(argv)

    by_date, undated = collect(args.ledger)
    if args.md:
        print(to_markdown(by_date, since_days_date=args.since))
    else:
        print(to_table(by_date, since_days=args.since))
    if args.summary:
        s = _summary(by_date)
        if s:
            print()
            print(f"  total entries  : {s['total_entries']}")
            print(f"  dated days     : {s['dated_days']}")
            print(f"  last 7d mean   : {s['last_7d_mean']:.2f}")
            print(f"  last 14d mean  : {s['last_14d_mean']:.2f}")
            print(f"  all-time mean  : {s['all_time_mean']:.2f}")
            print(f"  max day        : {s['max_day']}  ({s['max_day_count']} entries)")
    if undated:
        print()
        print(f"⚠ {len(undated)} S-NNN headings without a parsable date:")
        for sid, body_excerpt in undated[:20]:
            print(f"   {sid}    {body_excerpt!r}")
        if len(undated) > 20:
            print(f"   ... and {len(undated) - 20} more")
        # Don't fail on undated — the metric is honest about it, but the
        # CI purpose is "rate accounting", not "ledger is perfectly dated".
        # Surfacing is enough.
    return 0


if __name__ == "__main__":
    sys.exit(main())
