"""
Durable usage metering — the substrate an invoice can stand on (S-140, 2026-08-11).

WHAT WAS BROKEN. Usage lived ONLY in Redis, under `rl:rpd:{identity}` with a
24-hour TTL, and `api_keys.request_count` was incremented by nothing at all — the
column is shown on the analytics page and had read 0 since it was created.

So there was no substrate to bill from. Not "billing is unbuilt": the usage itself
did not survive a day. That is S-105's shape (the strategy library spent 12 days in
a 24h-TTL Redis key because its Postgres migration was never applied) moved onto
revenue, and it is worse here — research can be re-derived, a month of metered
usage cannot.

WHY NOT JUST WRITE POSTGRES PER REQUEST. That puts the database on the request
path, which is precisely the 2026-07-29 P0 (Supabase saturation → 33s hangs →
retry storm, while /health reported "healthy"). Redis stays the hot counter; this
module flushes it.

THE FLUSH IS MONOTONE, and that single choice is what makes it safe:

    requests = GREATEST(existing, redis_count)

  · a re-run cannot double-count — so a retry after a timeout is free
  · a missed flush is recovered by the next one, since Redis holds the running
    total for the day rather than a delta
  · a Redis eviction mid-day leaves the last flushed high-water mark, not zero

We therefore UNDER-count when Redis is lost and never OVER-count. That is the
correct direction to be wrong in when the number goes on an invoice: a customer
disputing a bill we can defend is a conversation; a customer discovering we
over-billed is a refund and a reputation.

A delta-based design (flush = count-since-last-flush, then reset) is the obvious
alternative and it is wrong here: it makes every flush a destructive read, so ONE
failed write between the read and the reset loses that slice permanently, and
nothing downstream can tell it happened.
"""
from __future__ import annotations

import datetime as dt
import logging
import os
from typing import Any

import httpx

_log = logging.getLogger("metering")

FLUSH_INTERVAL_S = 300          # 5 min. Bounds the loss window if the process dies.
_SCAN_LIMIT = 5_000             # keys per flush; a runaway key count must not stall boot


def _sb() -> tuple[str, str] | None:
    base = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ.get("SUPABASE_KEY", "")
    return (base, key) if base and key else None


_UPSTASH_URL = os.environ.get("UPSTASH_REDIS_REST_URL", "")
_UPSTASH_TOKEN = os.environ.get("UPSTASH_REDIS_REST_TOKEN", "")


async def _upstash(*path: str) -> Any:
    """One Upstash REST call. Returns the raw `result`, or None.

    Written here rather than imported because data_layer exposes only
    `_redis_get`, which json.loads() the value — and the rate limiter's counters
    are bare integers written by INCR, not JSON. Calling `_redis_get` on them
    returns None on a JSONDecodeError, silently, which would have made every
    invoice zero while every log line stayed clean.

    (The first draft of this module imported `_redis_scan` and `_redis_get_raw`.
    Neither exists. That is the S-103 class — `neutralize()` was cited in 71 files
    and defined in none — and it is worth recording that it happened again, in a
    module written by the person who wrote the guard for it.)"""
    if not _UPSTASH_URL:
        return None
    try:
        async with httpx.AsyncClient(timeout=8) as c:
            r = await c.get(f"{_UPSTASH_URL}/{'/'.join(path)}",
                            headers={"Authorization": f"Bearer {_UPSTASH_TOKEN}"})
        return r.json().get("result") if r.status_code == 200 else None
    except Exception as e:
        _log.warning("[metering] upstash %s failed: %s", path[0], e)
        return None


async def _redis_daily_counters() -> dict[str, int]:
    """{key_prefix: requests_today} from the rate limiter's own counters.

    Reads the SAME keys the middleware writes (`rl:rpd:{identity}`) rather than
    keeping a parallel count. Two counters for one quantity is two numbers that
    will disagree, and the disagreement surfaces as a billing dispute.

    SCAN, not KEYS: KEYS blocks the server for the whole keyspace, and this runs
    against the same instance serving the request path."""
    out: dict[str, int] = {}
    cursor, seen = "0", 0
    while True:
        res = await _upstash("scan", cursor, "match", "rl:rpd:*", "count", "500")
        if not isinstance(res, list) or len(res) != 2:
            break
        cursor, keys = str(res[0]), (res[1] or [])
        for k in keys:
            ident = str(k).split("rl:rpd:", 1)[-1]
            # Only API-key identities are billable. The middleware also limits by
            # IP for anonymous callers; metering those would invent usage for
            # people who have no account — an invoice line with no customer.
            if not ident.startswith("cc_live_"):
                continue
            raw = await _upstash("get", str(k))
            try:
                n = int(raw)
            except (TypeError, ValueError):
                continue
            if n > 0:
                out[ident] = n
        seen += len(keys)
        if cursor == "0" or seen >= _SCAN_LIMIT:
            break
    return out


async def flush_usage(day: dt.date | None = None) -> dict[str, Any]:
    """Flush today's Redis counters into `api_usage`. Safe to call at any time."""
    conf = _sb()
    if not conf:
        return {"status": "unconfigured"}
    base, key = conf
    day = day or dt.date.today()

    counters = await _redis_daily_counters()
    if not counters:
        return {"status": "nothing_to_flush", "date": day.isoformat()}

    rows = [{"key_prefix": kp, "usage_date": day.isoformat(),
             "requests": n, "last_flush_at": _now()} for kp, n in counters.items()]

    # PostgREST upsert. `merge-duplicates` alone would OVERWRITE with the incoming
    # value, which is only correct because the incoming value is the running daily
    # total — but it would silently lower `requests` if Redis were reset mid-day.
    # The GREATEST guarantee therefore lives in a database function, not in a hope
    # about ordering; see `api_usage_upsert` below.
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(
                f"{base}/rest/v1/rpc/api_usage_upsert",
                json={"p_rows": rows},
                headers={"apikey": key, "Authorization": f"Bearer {key}",
                         "Content-Type": "application/json"},
            )
        if r.status_code not in (200, 201, 204):
            _log.error("[metering] flush REJECTED %s %s", r.status_code, r.text[:240])
            return {"status": "failed", "http": r.status_code,
                    "body": r.text[:240], "n": len(rows)}
    except Exception as e:
        _log.error("[metering] flush failed: %s", e)
        return {"status": "failed", "error": str(e)[:200], "n": len(rows)}

    _log.info("[metering] flushed %d key-days for %s", len(rows), day.isoformat())
    return {"status": "ok", "n": len(rows), "date": day.isoformat()}


async def write_audit(actor: str, action: str, subject: str | None = None,
                      detail: dict | None = None, ip: str | None = None) -> bool:
    """Append one audit row. Returns whether it LANDED.

    Returns the outcome rather than only logging it — Lesson #107/#108: "the
    function was called" and "the row exists" are separate facts, and an audit
    trail that silently fails to record is worse than none, because it is trusted."""
    conf = _sb()
    if not conf:
        return False
    base, key = conf
    payload: dict[str, Any] = {"actor": actor, "action": action}
    if subject:
        payload["subject"] = subject
    if detail:
        payload["detail"] = detail
    if ip:
        payload["ip"] = ip
    try:
        async with httpx.AsyncClient(timeout=8) as c:
            r = await c.post(f"{base}/rest/v1/audit_log", json=[payload],
                             headers={"apikey": key, "Authorization": f"Bearer {key}",
                                      "Content-Type": "application/json",
                                      "Prefer": "return=minimal"})
        ok = r.status_code in (200, 201, 204)
        if not ok:
            _log.error("[audit] REJECTED %s %s — action=%s actor=%s",
                       r.status_code, r.text[:200], action, actor)
        return ok
    except Exception as e:
        _log.error("[audit] failed: %s — action=%s actor=%s", e, action, actor)
        return False


def _now() -> str:
    return dt.datetime.now(tz=dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
