"""The one place a paper book's NAV row gets written, and the write gets CHECKED (S-214).

WHY THIS EXISTS. `pod_aggregator_paper.py` and `factor_tilt_paper.py` each declared
`NAV_TABLE = "..."` and never wrote to it. Both constants had been in the code for
weeks; both tables held 0 rows; both books were marking NAV into their *state* row
and reporting `status: ok`. Minimax-A found it by reading the tables, not the code
— from inside the process everything looked healthy, because the only thing that
was missing was a call nobody had written.

A constant naming a table is a PROMISE. `pod_aggregator_nav` existed, was migrated,
was documented, and was never once written to. That is worse than not having the
table: an empty table reads as "the strategy produced nothing", which is a result,
and it was never a result — it was an absent line of code.

THE DECISION, since it was mine and I deferred it three times. Add the writers, do
not delete the constants. A book that marks is FALSIFIABLE — sixty days of rows can
condemn it. A book that does not mark is neither alive nor dead, and CLAUDE.md is
explicit that the graveyard is the asset. You cannot bury something that never had
a pulse.

AND THE WRITE IS CHECKED. `supabase_insert_table` returns a bool and five paper
books throw it away (task #33). A discarded False is how a book reports `status: ok`
while persisting nothing — the same miss-vs-error collapse as S-180, one layer up.
So this returns a result the caller must place in its payload, and the endpoint
shows `nav_persisted: false` with a reason rather than a cheerful `ok`.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Mapping

_log = logging.getLogger("nav_persist")


@dataclass(frozen=True)
class NavWrite:
    """Outcome of one NAV row write. Three-valued, like every other read this month."""

    ok: bool
    table: str
    reason: str = ""

    def as_payload(self) -> dict[str, Any]:
        """What the endpoint shows. `nav_persisted` is a fact, not an aspiration."""
        out: dict[str, Any] = {"nav_persisted": self.ok, "nav_table": self.table}
        if not self.ok:
            # A failure with no reason is indistinguishable from one nobody looked
            # at, so the reason travels with the flag rather than to a log file.
            out["nav_persist_error"] = self.reason or "unknown"
        return out


async def write_nav_row(table: str, row: Mapping[str, Any]) -> NavWrite:
    """Insert one NAV row. Never raises; the caller must surface the result.

    Deliberately NOT silent-on-failure and NOT fire-and-forget. The whole defect
    class this module closes is a write that did not happen and did not say so.
    """
    if not table:
        return NavWrite(False, table or "?", "no table configured")
    if not row or row.get("mark_date") is None:
        # A NAV row without its date cannot be deduplicated or ordered, so it is
        # not a mark — it is a number in a table.
        return NavWrite(False, table, "row has no mark_date")

    try:
        from src.api.store import supabase_insert_table
    except Exception as e:                                        # noqa: BLE001
        return NavWrite(False, table, f"store import failed: {type(e).__name__}")

    try:
        ok = await supabase_insert_table(table, [dict(row)])
    except Exception as e:                                        # noqa: BLE001
        _log.warning("[NAV] %s write raised: %s", table, e)
        return NavWrite(False, table, f"{type(e).__name__}: {str(e)[:120]}")

    if not ok:
        # supabase_insert_table returns False for a role refusal, missing
        # credentials, an empty payload AND a transport error. It does not say
        # which, so neither do we — inventing a cause here would be worse.
        _log.warning("[NAV] %s write returned False", table)
        return NavWrite(False, table, "insert returned False "
                                      "(role gate, credentials, or transport)")

    _log.info("[NAV] %s ← %s", table, row.get("mark_date"))
    return NavWrite(True, table)
