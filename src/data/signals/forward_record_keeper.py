"""
The forward records must keep marking, and must say so when they stop (S-175).

TWO JOBS, ONE CAUSE.

  1. WIND THE CLOCK. `refresh_depth_divergence()` and `resolve_depth_divergence()`
     were created 2026-08-18 (S-173) and had ZERO callers. Measured the next day:
     the only two mentions of the function name in the whole repo were a test
     docstring and a preflight comment — both describing it, neither running it.
     The two rows in `depth_divergence_log` were written by hand from a SQL
     console.

     That is the same defect S-173's own ledger entry was about, committed by its
     author, one day later. Worth stating plainly rather than quietly fixing: the
     failure mode is not ignorance of the rule. **Building the thing feels like
     finishing it, and a scheduler disagrees.**

  2. PAGE WHEN A BOOK STOPS. The ① book went 5 days without a mark
     (2026-08-12 → 08-17, production was read-only under an unset APP_ROLE) and
     nothing said anything. `/internal/beta-core-clock` reported it accurately
     the whole time — `marks: 0, started: false` — to nobody, because a status
     endpoint only speaks when asked.

     A 60-day forward commitment that silently skips 5 days is not a 55-day
     record with a gap; **it is a record whose gaps you now have to argue were
     accidental.** The whole value of the ① book is that an LP can check it, and
     an unexplained hole is exactly what they will check.

WHY BOTH LIVE IN ONE LOOP. They are the same guarantee seen from two sides:
something must write the record, and something must shout when the record stops
growing. Splitting them into two loops means the day the shouting loop dies, the
writing loop keeps looking healthy — one more monitor inside the failure domain
it monitors (S-92).

ALERTS ARE RATE-LIMITED, NOT DEDUPLICATED AWAY. A book that has been dead for a
week should not send 7 identical pages, but it must not go quiet either: after
the first alert the cadence drops to one per day, so the channel stays honest
without becoming noise. An always-on warning carries no information (S-105); so
does an alarm that fires once and gives up.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any

_log = logging.getLogger("forward_record")

# A book that has not marked in more than this many days is broken, not quiet.
# 1 = "yesterday's mark is missing". Deliberately tight: the ① book marks daily,
# so the first missed day IS the signal. Waiting for 3 would have turned the
# 5-day outage into a 3-day one, which is not a fix.
MAX_SILENT_DAYS = 1

# After the first page, at most one per 24h for the same book.
_ALERT_COOLDOWN_S = 24 * 3600
_last_alert: dict[str, float] = {}


async def _page(key: str, text: str) -> bool:
    """Send once, then at most daily for the same key."""
    import time
    now = time.time()
    last = _last_alert.get(key, 0.0)
    if now - last < _ALERT_COOLDOWN_S:
        _log.info("[FWD] %s still bad, page suppressed (cooldown)", key)
        return False
    _last_alert[key] = now
    try:
        from src.api.notify import notify_telegram
        ok = await notify_telegram(text)
    except Exception as e:                                   # noqa: BLE001
        _log.warning("[FWD] page failed to send: %s", e)
        ok = False
    # Log the alert text regardless. If Telegram is unconfigured the alert must
    # still exist somewhere — otherwise the alarm has the same failure mode as
    # the thing it watches.
    _log.warning("[FWD] ALERT%s: %s", "" if ok else " (not delivered)", text)
    return ok


async def refresh_depth_divergence_log() -> dict[str, Any]:
    """Job 1: write today's observations, then resolve anything 20 days due."""
    from src.api.store import supabase_rpc_write

    out: dict[str, Any] = {"written": None, "resolved": None, "problems": []}

    ok, res = await supabase_rpc_write("refresh_depth_divergence", {})
    if ok:
        out["written"] = res
    else:
        out["problems"].append(f"refresh: {res}")

    ok2, res2 = await supabase_rpc_write("resolve_depth_divergence", {})
    if ok2:
        out["resolved"] = res2
    else:
        out["problems"].append(f"resolve: {res2}")

    # Negative codes are REFUSALS, not row counts. The SQL side fails closed
    # rather than writing a day whose coverage has collapsed, because a forward
    # record containing 2-row days is one whose sample size nobody can state.
    # Measured 2026-08-19: the default target is the panel's max(trade_date),
    # and the asset classes update on different clocks — Crypto (262 symbols) was
    # 11 days behind five small classes, so "the latest day" had 2 symbols in it.
    w = out["written"]
    if w == -1:
        out["problems"].append(
            "refresh REFUSED: panel coverage for the latest date is under the 50% "
            "floor. The feed is stale, not the market quiet — check which asset "
            "class stopped collecting before overriding with an explicit date.")
    elif w == -2:
        out["problems"].append("refresh REFUSED: no panel data at all")
    elif w == 0:
        out["problems"].append(
            "refresh wrote 0 rows — the panel has no data for the target date")

    if out["problems"]:
        _log.warning("[FWD] depth_divergence: %s", "; ".join(out["problems"]))
    else:
        _log.info("[FWD] depth_divergence: %s written, %s resolved",
                  out["written"], out["resolved"])
    return out


async def check_book_continuity() -> list[dict[str, Any]]:
    """Job 2: page if any forward book has stopped marking.

    Reads the books' own tables rather than the clock endpoints. An endpoint can
    report healthily off a cached value; the table is where the record either
    exists or does not.
    """
    from src.api.store import supabase_rpc_write  # noqa: F401  (role gate parity)
    from src.api.store import _SB_URL, _SB_KEY    # noqa

    books = [
        ("beta_core_nav", "mark_date", "① beta-core book"),
        ("depth_divergence_log", "d", "depth-divergence forward record"),
    ]
    results: list[dict[str, Any]] = []

    for table, col, label in books:
        age = await _days_since(table, col)
        row = {"book": label, "table": table, "days_since_mark": age}
        if age is None:
            # THIRD STATE. "could not read" is not "healthy" and is not "dead".
            row["status"] = "unknown"
            _log.warning("[FWD] %s: could not read %s.%s — continuity UNKNOWN, "
                         "not assumed fine", label, table, col)
        elif age > MAX_SILENT_DAYS:
            row["status"] = "stalled"
            await _page(table,
                        f"🔴 {label} has not marked in {age} day(s).\n"
                        f"A 60-day forward commitment with an unexplained gap is "
                        f"not a shorter record — it is a record whose gaps have to "
                        f"be argued for. Check /health .writes first: production "
                        f"ran read-only for 5 days in August under an unset "
                        f"APP_ROLE and this exact silence was the symptom.")
        else:
            row["status"] = "ok"
        results.append(row)

    return results


async def _days_since(table: str, col: str) -> int | None:
    """Days since the newest row. None when unreadable — never 0, never a guess."""
    from src.api.store import _SB_URL, _SB_KEY, _supabase_request_with_retry
    if not _SB_URL or not _SB_KEY:
        return None
    url = f"{_SB_URL}/rest/v1/{table}?select={col}&order={col}.desc&limit=1"
    try:
        resp = await _supabase_request_with_retry(
            "GET", url, headers={"apikey": _SB_KEY,
                                 "Authorization": f"Bearer {_SB_KEY}"})
        if not resp or resp.status_code != 200:
            return None
        rows = resp.json()
        if not rows:
            return None
        raw = str(rows[0][col])[:10]
        return (date.today() - date.fromisoformat(raw)).days
    except Exception:                                        # noqa: BLE001
        return None


async def run_once() -> dict[str, Any]:
    """One full pass. Safe to call from a loop, a startup hook, or by hand."""
    started = datetime.now(timezone.utc).isoformat()
    log = await refresh_depth_divergence_log()
    books = await check_book_continuity()
    stalled = [b["book"] for b in books if b["status"] == "stalled"]
    unknown = [b["book"] for b in books if b["status"] == "unknown"]
    return {
        "ran_at": started,
        "depth_divergence": log,
        "books": books,
        "stalled": stalled,
        "unknown": unknown,
        "ok": not stalled and not unknown and not log["problems"],
    }
