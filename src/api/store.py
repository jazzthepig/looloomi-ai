"""
Shared state and utilities for all routers.
- Upstash Redis (CIS hot cache)
- Supabase (CIS score history)
- WebSocket ConnectionManager
- sanitize_floats helper
- Persistent httpx client pools (avoids reconnect overhead per request)
"""
import logging

from src.api.rpc_diagnostics import log_write_attempt  # S-352
from src.api.runtime_role import note_refusal, refuse_write
from src.api.store_result import StoreResult
import os, json, math, time
from datetime import datetime, timezone, timedelta
import httpx
from fastapi import WebSocket
from fastapi.websockets import WebSocketState
from typing import Any, cast

_logger = logging.getLogger(__name__)

# ── Persistent HTTP clients (reused across all requests) ──────────────────────
# Initialized lazily on first use; kept alive for the process lifetime.
_redis_client: httpx.AsyncClient | None = None
_supabase_client: httpx.AsyncClient | None = None


def _get_redis_client() -> httpx.AsyncClient:
    global _redis_client
    if _redis_client is None or _redis_client.is_closed:
        _redis_client = httpx.AsyncClient(timeout=5, limits=httpx.Limits(max_connections=20))
    return _redis_client


def _get_supabase_client() -> httpx.AsyncClient:
    global _supabase_client
    if _supabase_client is None or _supabase_client.is_closed:
        _supabase_client = httpx.AsyncClient(timeout=10, limits=httpx.Limits(max_connections=20))
    return _supabase_client

# ── Upstash Redis ────────────────────────────────────────────────────────────
_UPSTASH_URL   = os.environ.get("UPSTASH_REDIS_REST_URL", "")
_UPSTASH_TOKEN = os.environ.get("UPSTASH_REDIS_REST_TOKEN", "")
_REDIS_KEY     = "cis:local_scores"
_REDIS_TTL     = 7200  # 2 hours


async def redis_set(data: dict[str, Any]) -> StoreResult[bool]:
    """Write CIS payload to Upstash with 2 h TTL.

    Returns `StoreResult[bool]` (S-341a). The envelope carries the failure
    reason in `why` so callers can distinguish "missing config" from
    "transport refused". Legacy `if await redis_set(...)` continues to work
    via `__bool__` during migration; new callers should read `.ok` /
    `.why` directly.
    """
    return await redis_set_key(_REDIS_KEY, data, ttl=_REDIS_TTL)


async def redis_get() -> dict[str, Any] | None:
    """Read the T1 CIS payload from Upstash. None on miss OR error.

    ⚠️ If you are deciding T1-vs-T2 tier, use `redis_get_status()` — the tier
    decision must not be made on a value that cannot tell an absent Mac push
    from an unreachable Redis. S-180.
    """
    return await redis_get_key(_REDIS_KEY)


async def redis_get_status() -> tuple[dict[str, Any] | None, str]:
    """The T1 CIS payload plus WHY it is empty. See `redis_get_key_status`."""
    return await redis_get_key_status(_REDIS_KEY)


# ── Generic key-based Redis helpers ──────────────────────────────────────────

async def redis_set_key(key: str, data: dict[str, Any], ttl: int = 7200) -> StoreResult[bool]:
    """Write any JSON payload to Upstash with TTL.

    Returns `StoreResult[bool]` (S-341a). Failure reasons a caller can read
    off `.why`:
      - "UPSTASH_REDIS_REST_URL is unset in this process"
      - "UPSTASH returned status=<code> for key=<key>"
      - "UPSTASH request raised: <ExceptionClass>: <message>"

    Legacy `if await redis_set_key(...)` continues to work via `__bool__`
    on the envelope. New callers should branch on `.ok` and log `.why`.
    """
    if not _UPSTASH_URL:
        return StoreResult[bool].fail("UPSTASH_REDIS_REST_URL is unset in this process")
    try:
        client = _get_redis_client()
        resp = await client.post(
            f"{_UPSTASH_URL}/set/{key}",
            content=json.dumps(data),
            headers={
                "Authorization": f"Bearer {_UPSTASH_TOKEN}",
                "Content-Type": "application/json",
            },
            params={"EX": ttl},
        )
        if resp.status_code == 200:
            return StoreResult.ok_(value=True)
        return StoreResult[bool].fail(
            f"UPSTASH returned status={resp.status_code} for key={key}"
        )
    except Exception as e:
        _logger.warning(f"[REDIS] SET {key} error: {e}")
        return StoreResult[bool].fail(f"UPSTASH request raised: {type(e).__name__}: {e}")


async def redis_get_key_status(key: str) -> tuple[dict[str, Any] | None, str]:
    """Read a JSON payload from Upstash, SAYING WHY when it comes back empty.

    Returns (payload, status) with status one of:
        "hit"        payload is present
        "miss"       Upstash answered, and the key genuinely is not there
        "error"      we could not ask — transport failure, non-200, bad JSON
        "unconfigured"  no Upstash URL in the environment

    WHY THIS EXISTS (S-180, 2026-08-20). `redis_get_key` documented its own bug
    in its docstring — "Returns None on miss/error" — and `_build_cis_universe`
    read that None as "the Mac engine has not pushed", demoting **the entire
    58-asset universe** from T1 to T2 in one step. A T1→T2 demotion is not a
    small precision change: it swaps the whole pillar set (measured on BTC,
    2026-08-19: F 50→80, O 27→59, S 59→20), moves the score ~10 points, and
    crosses both the grade boundary and the positioning boundary. The hourly
    snapshot loop then wrote those rows into `cis_scores` as the permanent
    record, because its guard is `tier_label == "T2"` and every asset now
    claimed to be T2.

    So a single Redis blip did not degrade the read — it rewrote history. And
    it was invisible, because a genuine Mac outage produces byte-identical
    rows. The system's way of failing looked exactly like its way of being
    correct, which is the third instance of this same collapse in one week
    (`supabase_table_exists` missing-vs-unreachable, S-166; the loop-health
    "flowing" report off one fresh row, S-179). Two-valued returns keep
    re-manufacturing it: the fix is not another `if` at the call site, it is
    making the read itself carry the distinction it always had and discarded.
    """
    if not _UPSTASH_URL:
        return None, "unconfigured"
    try:
        client = _get_redis_client()
        resp = await client.get(
            f"{_UPSTASH_URL}/get/{key}",
            headers={"Authorization": f"Bearer {_UPSTASH_TOKEN}"},
        )
        if resp.status_code != 200:
            # An HTTP error is NOT a miss. Upstash returns 200 with
            # result=null for an absent key; anything else means we failed to
            # ask, and callers must not read that as "the key is gone".
            _logger.warning("[REDIS] GET %s → HTTP %s (treated as ERROR, not miss)",
                            key, resp.status_code)
            return None, "error"
        raw = resp.json().get("result")
        if raw is None or raw == "":
            return None, "miss"
        return json.loads(raw), "hit"
    except Exception as e:                                       # noqa: BLE001
        _logger.warning("[REDIS] GET %s error: %s (treated as ERROR, not miss)", key, e)
        return None, "error"


async def redis_get_key(key: str) -> dict[str, Any] | None:
    """Read any JSON payload from Upstash. Returns None on miss OR error.

    Kept for the many callers where the distinction genuinely does not matter
    (decoration, enrichment, best-effort caches). If a caller's behaviour on
    None is a FALLBACK THAT WRITES — anything that persists a different value
    because the read came back empty — it must use `redis_get_key_status`
    instead. See that function for what this one cost.
    """
    payload, _status = await redis_get_key_status(key)
    return payload


# ── Supabase ──────────────────────────────────────────────────────────────────
_SB_URL   = os.environ.get("SUPABASE_URL", "").rstrip("/")
_SB_KEY   = os.environ.get("SUPABASE_KEY", "")
_SB_TABLE = "cis_scores"

# Retry config
_SB_MAX_RETRIES = 3
_SB_BASE_DELAY = 1.0  # seconds

# ── Circuit breaker (2026-07-29, P0 incident) ────────────────────────────────
# INCIDENT: Supabase hit "exhausting multiple resources" on the free tier. Every
# /api/v1/cis/* request then took timeout(10) × 3 attempts + backoff(1+2) = up to
# 33s before failing, so the endpoint appeared to HANG rather than error. Worse,
# retrying tripled the request load onto an already-saturated database — our own
# retry policy was a retry storm keeping the DB down.
#
# Exponential backoff is correct for TRANSIENT faults and actively harmful for a
# SATURATED backend. The breaker distinguishes them: after N consecutive failures
# we stop calling for a cooldown, fail fast (None), and let callers fall back to
# the Redis cache. Callers already handle None — before this they simply never
# reached that path in time.
_CB_FAIL_THRESHOLD = int(os.environ.get("SB_CB_FAIL_THRESHOLD", "5"))
_CB_COOLDOWN_S     = float(os.environ.get("SB_CB_COOLDOWN_S", "30"))
_cb_consecutive_failures = 0
_cb_open_until = 0.0
_cb_trips = 0            # lifetime count, surfaced by /health
# S-323 Phase A2 (2026-09-14): 4xx is a CALLER bug (bad path / bad key /
# missing permission), not a backend outage. Counting it as success hid
# dozens of failures behind `lifetime_trips=0` while the loops racked up
# 14+ consecutive failures. Track 4xx separately so the health endpoint
# surfaces "config is wrong" without conflating it with saturation.
_cb_lifetime_4xx = 0
_cb_consecutive_4xx = 0
_CB_4XX_ALERT_THRESHOLD = 20       # alert once we have 20 cumulative 4xx


def supabase_breaker_state() -> dict[str, Any]:
    """Observable breaker state — consumed by the health check so that health
    reflects the real data layer instead of asserting it (see I4 / discipline)."""
    now = time.time()
    return {
        "open": now < _cb_open_until,
        "consecutive_failures": _cb_consecutive_failures,
        "cooldown_remaining_s": max(0.0, round(_cb_open_until - now, 1)),
        "lifetime_trips": _cb_trips,
        "lifetime_4xx": _cb_lifetime_4xx,
        "consecutive_4xx": _cb_consecutive_4xx,
        "threshold": _CB_FAIL_THRESHOLD,
    }


def _cb_record_success() -> None:
    global _cb_consecutive_failures, _cb_open_until
    _cb_consecutive_failures = 0
    _cb_open_until = 0.0


def _cb_record_failure() -> None:
    global _cb_consecutive_failures, _cb_open_until, _cb_trips
    _cb_consecutive_failures += 1
    if _cb_consecutive_failures >= _CB_FAIL_THRESHOLD and time.time() >= _cb_open_until:
        _cb_open_until = time.time() + _CB_COOLDOWN_S
        _cb_trips += 1
        _logger.error(
            f"[SUPABASE] circuit OPEN after {_cb_consecutive_failures} consecutive "
            f"failures — failing fast for {_CB_COOLDOWN_S}s (trip #{_cb_trips})")


def _cb_record_caller_error(status_code: int, body_snippet: str) -> None:
    """S-323 Phase A2. 4xx means our request was wrong (path/key/permission),
    not that the backend is saturated. Track separately so the data layer's
    health card can say "config is wrong" instead of looking healthy while
    loops pile up silent failures.

    Does NOT trip the breaker — callers still get the response so the loop's
    `_beat(ok=False, error=...)` carries the real reason."""
    global _cb_lifetime_4xx, _cb_consecutive_4xx
    _cb_lifetime_4xx += 1
    _cb_consecutive_4xx += 1
    snippet = (body_snippet or "")[:200]
    _logger.warning(
        f"[SUPABASE] 4xx caller_error #{_cb_lifetime_4xx} "
        f"(consec={_cb_consecutive_4xx}): HTTP {status_code} — {snippet}")
    if _cb_consecutive_4xx >= _CB_4XX_ALERT_THRESHOLD:
        _logger.error(
            f"[SUPABASE] { _cb_consecutive_4xx } consecutive 4xx — "
            f"this is a CONFIG bug, not saturation. Check SUPABASE_KEY / "
            f"endpoint paths. (lifetime_4xx={_cb_lifetime_4xx})")


async def _supabase_request_with_retry(
    method: str,
    url: str,
    **kwargs: Any,
) -> httpx.Response | None:
    """Execute HTTP request with backoff retry, guarded by a circuit breaker.

    Returns None when the call fails or the breaker is open; every caller treats
    None as "no data" and falls back to Redis. Never raises.
    """
    import asyncio

    # Breaker open ⇒ fail immediately. This is the whole point: no queueing, no
    # extra load on a saturated backend, no 33s hang for the client.
    if time.time() < _cb_open_until:
        _logger.warning("[SUPABASE] circuit open — short-circuiting request")
        return None

    client = _get_supabase_client()
    last_error = None

    for attempt in range(_SB_MAX_RETRIES):
        try:
            resp = await client.request(method, url, **kwargs)
            if resp.status_code in (200, 201):
                _cb_record_success()
                global _cb_consecutive_4xx
                _cb_consecutive_4xx = 0          # a 2xx clears the 4xx streak
                return resp
            # Non-retryable error (4xx except 429) — the backend is healthy and
            # is telling us the request is wrong. S-323 Phase A2: do NOT record
            # this as success. Track as caller_error so the loop's heartbeat
            # surfaces the real failure mode instead of "熔断 open, no request sent".
            if 400 <= resp.status_code < 500 and resp.status_code != 429:
                _cb_record_caller_error(resp.status_code, resp.text or "")
                return resp
            last_error = f"HTTP {resp.status_code}"
        except httpx.TimeoutException as e:
            # A timeout under saturation must NOT be retried — retrying is what
            # turned this incident into an outage. Trip toward the breaker and
            # bail out of the retry loop immediately.
            _cb_record_failure()
            _logger.warning(f"[SUPABASE] timeout ({e!r}) — no retry, falling back")
            return None
        except Exception as e:
            last_error = str(e)

        if attempt < _SB_MAX_RETRIES - 1:
            delay = _SB_BASE_DELAY * (2 ** attempt)  # exponential backoff
            _logger.warning(f"[SUPABASE] Retry {attempt + 1}/{_SB_MAX_RETRIES} after {delay}s: {last_error}")
            await asyncio.sleep(delay)

    _cb_record_failure()
    _logger.warning(f"[SUPABASE] All retries exhausted: {last_error}")
    return None


async def supabase_insert_batch(rows: list[Any]) -> StoreResult[bool]:
    """Bulk-insert CIS score rows into Supabase REST API with retry.

    Returns `StoreResult[bool]` (S-341b). Failure reasons a caller can read
    off `.why`:
      - role-gate refusal text (env: railway / role: anon / etc.)
      - "caller passed 0 rows (not a config problem)"
      - "SUPABASE_URL is empty" / "SUPABASE_KEY is empty" / both
      - "HTTP <status>"
      - "<ExceptionClass>: <msg>"

    Legacy `if await supabase_insert_batch(...)` continues to work via
    `__bool__` on the envelope. New callers should branch on `.ok` and log
    `.why` — bare-bool swallowed failures were the root cause of S-329/S-334.
    """
    # ROLE GATE (2026-08-12, S-149). Enforced HERE, at the write function, and not
    # in the twenty-odd background loops that call it — because loops keep being
    # added and a gate you have to remember is a gate that will be forgotten. Same
    # argument as putting GREATEST inside api_usage_upsert rather than in the
    # caller: a guarantee in one place holds for every caller, forever.
    _refusal = refuse_write("cis_scores (batch)")
    if _refusal:
        note_refusal("cis_scores (batch)", _refusal)
        return StoreResult[bool].fail(f"role_gate: {_refusal}")

    # NAME WHICH ONE (2026-08-12, S-148). This said "missing config or empty rows"
    # — three different causes behind one sentence, so a reader could only tell
    # them apart if a NEIGHBOURING log line happened to print the row count. It did,
    # this time. That is luck, not observability, and the same defect as
    # "Key storage failed" (S-138): a message that names no cause funds plausible
    # wrong answers about which thing to go fix.
    if not rows:
        _logger.warning("[SUPABASE] Skipped: caller passed 0 rows (not a config problem)")
        return StoreResult[bool].fail("caller passed 0 rows (not a config problem)")
    if not _SB_URL or not _SB_KEY:
        missing = " and ".join(
            n for n, v in (("SUPABASE_URL", _SB_URL), ("SUPABASE_KEY", _SB_KEY)) if not v)
        _logger.warning(
            "[SUPABASE] Skipped %d row(s): %s empty IN THIS PROCESS. These are read "
            "at import time, so a scheduled run that does not load .env sees them "
            "blank while the main engine writes fine — which is exactly how one "
            "writer can be dark while another is green.", len(rows), missing)
        return StoreResult[bool].fail(f"{missing} empty IN THIS PROCESS")

    url = f"{_SB_URL}/rest/v1/{_SB_TABLE}"
    headers = {
        "apikey":        _SB_KEY,
        "Authorization": f"Bearer {_SB_KEY}",
        "Content-Type":  "application/json",
        "Prefer":        "return=minimal",
    }

    try:
        resp = await _supabase_request_with_retry(
            "POST",
            url,
            content=json.dumps(rows),
            headers=headers,
        )
        if resp and resp.status_code in (200, 201):
            _logger.info(f"[SUPABASE] Inserted {len(rows)} rows (attempt 1)")
            return StoreResult.ok_(value=True)
        if resp:
            _logger.warning(f"[SUPABASE] Insert failed after retries: {resp.status_code}")
            return StoreResult[bool].fail(f"HTTP {resp.status_code} after retries")
        return StoreResult[bool].fail("no response from Supabase after retries (breaker may be open)")
    except Exception as e:
        _logger.warning(f"[SUPABASE] Insert exception: {e}")
        return StoreResult[bool].fail(f"{type(e).__name__}: {e}")


@log_write_attempt
async def supabase_insert_table(table: str, rows: list[Any]) -> StoreResult[bool]:
    """Generic bulk-insert into any Supabase table (REST) with retry.

    Returns `StoreResult[bool]` (S-341b). Failure reasons include role-gate
    refusal, "0 rows" / empty table name, "SUPABASE_URL is empty" /
    "SUPABASE_KEY is empty", "HTTP <status>: <body snippet>", and the
    exception class+message. Callers can use `.ok` / `.why` for logging.
    """
    # ROLE GATE (2026-08-12, S-149). Enforced HERE, at the write function, and not
    # in the twenty-odd background loops that call it — because loops keep being
    # added and a gate you have to remember is a gate that will be forgotten. Same
    # argument as putting GREATEST inside api_usage_upsert rather than in the
    # caller: a guarantee in one place holds for every caller, forever.
    _refusal = refuse_write(table)
    if _refusal:
        note_refusal(table, _refusal)
        return StoreResult[bool].fail(f"role_gate: {_refusal}")


    if not _SB_URL or not _SB_KEY:
        missing = " and ".join(
            n for n, v in (("SUPABASE_URL", _SB_URL), ("SUPABASE_KEY", _SB_KEY)) if not v)
        return StoreResult[bool].fail(f"{missing} empty IN THIS PROCESS")
    if not rows:
        return StoreResult[bool].fail("caller passed 0 rows")
    if not table:
        return StoreResult[bool].fail("caller passed empty table name")
    url = f"{_SB_URL}/rest/v1/{table}"
    headers = {
        "apikey":        _SB_KEY,
        "Authorization": f"Bearer {_SB_KEY}",
        "Content-Type":  "application/json",
        "Prefer":        "return=minimal",
    }
    try:
        resp = await _supabase_request_with_retry("POST", url, content=json.dumps(rows), headers=headers)
        if resp and resp.status_code in (200, 201):
            _logger.info(f"[SUPABASE] Inserted {len(rows)} rows into {table}")
            return StoreResult.ok_(value=True)
        if resp:
            _logger.warning(f"[SUPABASE] Insert into {table} failed: {resp.status_code} {resp.text[:120]}")
            return StoreResult[bool].fail(
                f"HTTP {resp.status_code}: {(resp.text or '')[:120]}")
        return StoreResult[bool].fail("no response from Supabase after retries (breaker may be open)")
    except Exception as e:
        _logger.warning(f"[SUPABASE] Insert into {table} exception: {e}")
        return StoreResult[bool].fail(f"{type(e).__name__}: {e}")


async def supabase_table_exists(table: str) -> bool | None:
    """Does this table exist? True / False / None (could not tell) — S-166.

    THREE-VALUED ON PURPOSE. A boolean would collapse "the table is missing"
    into "I could not reach Supabase", and that collapse is the bug this whole
    check exists to catch: eleven missing tables hid for weeks behind writes
    that returned False for reasons nobody distinguished. A drift report that
    says "missing" when the network blipped trains everyone to ignore it.

    Reads only — safe on a replica, no role gate.
    """
    if not _SB_URL or not _SB_KEY or not table:
        return None
    url = f"{_SB_URL}/rest/v1/{table}?select=*&limit=0"
    headers = {"apikey": _SB_KEY, "Authorization": f"Bearer {_SB_KEY}"}
    try:
        resp = await _supabase_request_with_retry("GET", url, headers=headers)
        if resp is None:
            return None
        if resp.status_code in (200, 206):
            return True
        # PostgREST answers an unknown relation with 404 + PGRST205, and a
        # permission problem with 401/403. Only the first means "absent".
        if resp.status_code == 404 or "PGRST205" in (resp.text or ""):
            return False
        return None
    except Exception:                                  # noqa: BLE001
        return None


async def supabase_function_exists(fn_name: str) -> bool | None:
    """Does this Postgres function exist (in pg_proc, exposed via PostgREST)? S-342 + A-29.

    The TABLE side has a clean GET probe (limit=0 returns the column shape
    without reading rows). The FUNCTION side does NOT — RPC endpoints need
    POST, and the response to an empty payload is shaped by the function's
    own signature, not by PostgREST's introspection. So this looks noisier
    than `supabase_table_exists` but the three outcomes still separate
    cleanly:

      - 200, 204                 — function exists, no args required → True
      - 4xx with PGRST202/404    — function not in pg_proc cache     → False
      - 4xx other (e.g. argument error, missing arg) — function exists,
        payload is wrong                                         → True
      - 5xx, network, timeout    — could not tell                  → None

    Three-valued for the same reason as `supabase_table_exists`: a missing
    function and a network blip MUST NOT collapse, or the deploy guard
    trains everyone to ignore the real signal.

    Note on `accept-profile` not set: PostgREST's RPC endpoint accepts a
    single function name per URL segment. There's no way to ask "do you
    know about function X" without POSTing to it — there's no HEAD method
    in the spec, and the OpenAPI doc only describes POST.
    """
    if not _SB_URL or not _SB_KEY or not fn_name:
        return None
    url = f"{_SB_URL}/rest/v1/rpc/{fn_name}"
    headers = {"apikey": _SB_KEY, "Authorization": f"Bearer {_SB_KEY}",
               "Content-Type": "application/json"}
    try:
        resp = await _supabase_request_with_retry("POST", url, json={}, headers=headers)
        if resp is None:
            return None
        if resp.status_code in (200, 204):
            return True
        body = resp.text or ""
        # PGRST202 = PostgREST's "could not find function in schema cache".
        # PGRST205 is the table equivalent — different catalog, same shape.
        # 404 is what PostgREST returns when the function isn't exposed.
        if resp.status_code == 404 or "PGRST202" in body or "PGRST205" in body:
            return False
        # Anything else (argument errors, type mismatches, permission denied
        # on the underlying tables) means the function is known to the
        # schema cache — it just rejected our empty payload.
        return True
    except Exception:                                  # noqa: BLE001
        return None


async def supabase_missing_columns(table: str, columns: list[str]) -> list[str] | None:
    """Which of `columns` does the LIVE table not have? None = could not tell (S-286).

    THE GAP THIS CLOSES. `supabase_table_exists` was built for S-166, where eleven
    TABLES were missing. It inherited that incident's scope, and on 2026-09-04 the
    ① book was taken down by a missing COLUMN: `_INCEPTION_ID` moved to v5 and
    deployed while the migration adding `interval_hours` had not run. Every insert
    got a 400, `_write` returned False, the book stopped, and the curve answered
    `{"days": 0}`. The table existed the whole time, so the online guard stayed
    green — **a control whose scope is one notch too narrow reads as coverage.**

    Probes with `select=<cols>&limit=0`: PostgREST resolves the projection before
    it fetches anything, so an unknown column answers 42703 without reading a row.
    Cheap enough to run on every deploy, which is the point — the offline half can
    only prove a migration FILE exists, never that it RAN.

    Three-valued for the same reason as `supabase_table_exists`: "the column is
    missing" and "I could not reach Supabase" must not collapse, or the report
    that says missing on a network blip trains everyone to ignore it.
    """
    if not _SB_URL or not _SB_KEY or not table or not columns:
        return None
    headers = {"apikey": _SB_KEY, "Authorization": f"Bearer {_SB_KEY}"}
    # Ask for all of them at once; only narrow to per-column probes on failure,
    # so the common (healthy) case costs exactly one request per table.
    url = f"{_SB_URL}/rest/v1/{table}?select={','.join(columns)}&limit=0"
    try:
        resp = await _supabase_request_with_retry("GET", url, headers=headers)
        if resp is None:
            return None
        if resp.status_code in (200, 206):
            return []
        if resp.status_code != 400 and "42703" not in (resp.text or ""):
            return None                      # auth, missing relation, something else
    except Exception:                                  # noqa: BLE001
        return None

    missing = []
    for col in columns:
        try:
            r = await _supabase_request_with_retry(
                "GET", f"{_SB_URL}/rest/v1/{table}?select={col}&limit=0", headers=headers)
            if r is None:
                return None
            if r.status_code == 400 or "42703" in (r.text or ""):
                missing.append(col)
            elif r.status_code not in (200, 206):
                return None
        except Exception:                              # noqa: BLE001
            return None
    return missing


@log_write_attempt
async def supabase_upsert_table(table: str, rows: list[Any], on_conflict: str) -> StoreResult[bool]:
    """Bulk UPSERT into any Supabase table, resolving duplicates on `on_conflict`.

    Distinct from supabase_insert_table for exactly one reason: RETRIES (S-164).
    The research intake receives batches from mining lanes that will resubmit —
    on timeout, on a 502, on a rerun of the same script. An INSERT-only path
    turns a retry into duplicate rows, and duplicate rows in experiment_runs do
    not merely inflate a count, they corrupt every base rate computed from the
    table. "17/29 refuted" is a number we make decisions with; it must not be a
    function of how many times somebody ran a script.

    Returns `StoreResult[bool]` (S-341b). Same failure-shape contract as
    `supabase_insert_table` plus an `on_conflict` empty-string check.

    Same role gate as the insert path — enforced at the write function, never at
    the caller, because callers keep being added.
    """
    _refusal = refuse_write(f"{table} (upsert)")
    if _refusal:
        note_refusal(table, _refusal)
        return StoreResult[bool].fail(f"role_gate: {_refusal}")

    if not _SB_URL or not _SB_KEY:
        missing = " and ".join(
            n for n, v in (("SUPABASE_URL", _SB_URL), ("SUPABASE_KEY", _SB_KEY)) if not v)
        return StoreResult[bool].fail(f"{missing} empty IN THIS PROCESS")
    if not rows:
        return StoreResult[bool].fail("caller passed 0 rows")
    if not table:
        return StoreResult[bool].fail("caller passed empty table name")
    if not on_conflict:
        return StoreResult[bool].fail("caller passed empty on_conflict")
    url = f"{_SB_URL}/rest/v1/{table}?on_conflict={on_conflict}"
    headers = {
        "apikey":        _SB_KEY,
        "Authorization": f"Bearer {_SB_KEY}",
        "Content-Type":  "application/json",
        # merge-duplicates is what makes this an UPSERT rather than a conflict 409.
        "Prefer":        "resolution=merge-duplicates,return=minimal",
    }
    try:
        resp = await _supabase_request_with_retry("POST", url, content=json.dumps(rows), headers=headers)
        if resp and resp.status_code in (200, 201, 204):
            _logger.info(f"[SUPABASE] Upserted {len(rows)} rows into {table} on {on_conflict}")
            return StoreResult.ok_(value=True)
        if resp:
            _logger.warning(f"[SUPABASE] Upsert into {table} failed: {resp.status_code} {resp.text[:200]}")
            return StoreResult[bool].fail(
                f"HTTP {resp.status_code}: {(resp.text or '')[:200]}")
        return StoreResult[bool].fail("no response from Supabase after retries (breaker may be open)")
    except Exception as e:
        _logger.warning(f"[SUPABASE] Upsert into {table} exception: {e}")
        return StoreResult[bool].fail(f"{type(e).__name__}: {e}")


async def supabase_get_recent_scores(symbols: list[Any], n: int = 30) -> dict[str, Any]:
    """Bulk-fetch last N CIS score rows per symbol from Supabase.

    Returns dict keyed by symbol (uppercase) → list of rows ordered newest-first.
    Each row contains at minimum {"score": float, "recorded_at": str}.
    Used by /internal/cis-scores to compute score_delta and score_zscore on push.
    Returns empty dict if Supabase is unconfigured or unreachable.
    """
    if not _SB_URL or not _SB_KEY or not symbols:
        return {}

    symbols_upper = [s.upper() for s in symbols if s]
    # Supabase PostgREST: filter on list via in.(A,B,C)
    in_filter = "in.(" + ",".join(symbols_upper) + ")"
    url = f"{_SB_URL}/rest/v1/{_SB_TABLE}"
    params = {
        "symbol": in_filter,
        "order":  "recorded_at.desc",
        "limit":  str(n * len(symbols_upper)),
        "select": "symbol,score,grade,signal,macro_regime,recorded_at",
    }
    headers = {
        "apikey":        _SB_KEY,
        "Authorization": f"Bearer {_SB_KEY}",
    }

    try:
        resp = await _supabase_request_with_retry("GET", url, params=params, headers=headers)
        if resp and resp.status_code == 200:
            rows = resp.json()
            result: dict[str, Any] = {}
            for row in rows:
                sym_raw = row.get("symbol")
                # Supabase returns symbol=null when the column isn't in SELECT
                # scope (or table has it as computed). Coerce None/empty to ""
                # so .upper() never raises AttributeError, which the outer
                # try/except was silently swallowing.
                sym = (sym_raw or "").upper()
                if sym:
                    result.setdefault(sym, []).append(row)
            # Each symbol list is already ordered newest-first (Supabase returns in query order)
            return result
        if resp:
            _logger.warning(f"[SUPABASE] get_recent_scores error {resp.status_code}: {resp.text[:100]}")
        return {}
    except Exception as e:
        _logger.warning(f"[SUPABASE] get_recent_scores exception: {e}")
        return {}


async def supabase_get_history(symbol: str, days: int = 7) -> list[dict[str, Any]]:
    """Read CIS score history for one symbol from Supabase with retry."""
    if not _SB_URL or not _SB_KEY:
        _logger.warning("[SUPABASE] History read skipped: missing config")
        return []

    url = f"{_SB_URL}/rest/v1/{_SB_TABLE}"
    params = {
        "symbol":  f"eq.{symbol.upper()}",
        "order":   "recorded_at.desc",
        "limit":   str(days * 48),
        "select":  "score,raw_cis_score,grade,signal,pillar_f,pillar_m,pillar_o,pillar_s,pillar_a,score_delta,score_zscore,macro_regime,data_tier,las,confidence,asset_class,recorded_at",
    }
    headers = {
        "apikey":        _SB_KEY,
        "Authorization": f"Bearer {_SB_KEY}",
    }

    try:
        resp = await _supabase_request_with_retry("GET", url, params=params, headers=headers)
        if resp and resp.status_code == 200:
            data = resp.json()
            _logger.warning(f"[SUPABASE] History {symbol}: {len(data)} records (last 7d)")
            return cast("list[dict[str, Any]]", data)
        if resp:
            _logger.warning(f"[SUPABASE] History error {resp.status_code}: {resp.text[:100]}")
        return []
    except Exception as e:
        _logger.warning(f"[SUPABASE] History exception: {e}")
        return []


# ── Track record read — cached, for the self-tuning conviction tilt ────────────
_TRACKREC_CACHE: dict[str, Any] = {"rows": cast("list[dict[str, Any]] | None", None), "ts": 0.0}
_TRACKREC_TTL = 6 * 3600  # 6h — the refresh runs daily; this is fresh enough


_EDGEMAP_CACHE: dict[str, Any] = {"rows": cast("list[dict[str, Any]] | None", None), "ts": 0.0}
_EDGEMAP_TTL = 6 * 3600


async def supabase_get_latest_edge_map() -> list[dict[str, Any]]:
    """Latest signal_edge_map batch: [{signal,risk_band,n,avg_alpha_pct,alpha_win_pct,...}].
    Cached 6h; best-effort ([] on miss)."""
    now = time.time()
    if _EDGEMAP_CACHE["rows"] is not None and (now - _EDGEMAP_CACHE["ts"]) < _EDGEMAP_TTL:
        return cast("list[dict[str, Any]]", _EDGEMAP_CACHE["rows"])
    if not _SB_URL or not _SB_KEY:
        return []
    url = f"{_SB_URL}/rest/v1/signal_edge_map"
    params = {"order": "computed_at.desc", "limit": "60",
              "select": "signal,risk_band,n,avg_alpha_pct,alpha_win_pct,avg_abs_return_pct,computed_at"}
    headers = {"apikey": _SB_KEY, "Authorization": f"Bearer {_SB_KEY}"}
    try:
        resp = await _supabase_request_with_retry("GET", url, params=params, headers=headers)
        if resp and resp.status_code == 200:
            allrows = resp.json()
            latest = max((r.get("computed_at") for r in allrows), default=None)
            rows = [r for r in allrows if r.get("computed_at") == latest]
            _EDGEMAP_CACHE["rows"] = rows; _EDGEMAP_CACHE["ts"] = now
            return rows
        return []
    except Exception as e:
        _logger.warning(f"[SUPABASE] edge_map read exception: {e}")
        return []


async def supabase_rpc(fn_name: str, payload: dict[str, Any] | None = None) -> Any:
    """Call a Postgres function via PostgREST RPC (uses the configured service key).
    Returns the JSON result or None. Used by the daily track-record refresh.

    S-323 Phase A1 (2026-09-14): when the response is 4xx or `200 with a
    non-JSON body`, log the status AND body inline so the heartbeat can pick
    it up. The previous shape collapsed four different failure modes
    (`4xx real error`, `200 with empty body`, `network timeout`,
    `breaker open`) into a single `None`, which is what kept us guessing
    at the cause for 128 days. Caller contract unchanged — None still
    means "no data", but the reason is now in the log with status+body.
    """
    if not _SB_URL or not _SB_KEY:
        return None
    url = f"{_SB_URL}/rest/v1/rpc/{fn_name}"
    headers = {"apikey": _SB_KEY, "Authorization": f"Bearer {_SB_KEY}",
               "Content-Type": "application/json"}
    try:
        resp = await _supabase_request_with_retry("POST", url, json=(payload or {}), headers=headers)
        if resp and resp.status_code in (200, 204):
            try:
                return resp.json()
            except Exception:
                # 200 + non-JSON: this IS the bug class S-323 calls out — log
                # the raw body, don't return True (which loses the diagnostic).
                _logger.warning(
                    f"[SUPABASE] rpc {fn_name}: HTTP 200 but body not JSON: "
                    f"{(resp.text or '')[:200]}")
                return None
        if resp:
            # S-323 Phase A1: log the actual response body. Caller still gets
            # None (signature preserved) but the reason is now searchable.
            _logger.warning(
                f"[SUPABASE] rpc {fn_name}: HTTP {resp.status_code} — "
                f"{(resp.text or '')[:200]}")
        return None
    except Exception as e:
        _logger.warning(f"[SUPABASE] rpc {fn_name} exception: {e}")
        return None


async def supabase_rpc_write(fn_name: str, payload: dict[str, Any] | None = None) -> StoreResult[Any]:
    """RPC that WRITES — role-gated. Returns StoreResult with `value` carrying
    the JSON result on success (S-169 + S-341b).

    WHY A SECOND FUNCTION. `supabase_rpc` above has no role gate. It predates
    S-149 and is used for reads, so gating it would break replicas that
    legitimately read. But an ungated RPC is a hole straight through the write
    boundary: a replica calling `upsert_*` writes the shared record while
    `supabase_insert_table` right next to it refuses. One door locked, the door
    beside it not.

    Found while wiring the Mac lane's writes through Railway (S-169), which is
    the moment it would have mattered — those pushes are RPC calls, so routing
    them through an ungated helper would have moved the write out from behind
    the gate rather than behind it.

    MIGRATION (S-341b). Pre-341b shape was `(ok: bool, why_or_result)` — a
    tuple. The envelope upgrade is structural: callers that did `ok, result =
    await supabase_rpc_write(...)` MUST be updated to `r = await ...; r.ok,
    r.value, r.why`. Callers doing just `if await fn(...)` keep working via
    `__bool__`. Affected call sites are listed in the S-341b ledger entry.

    Failure reasons in `.why`:
      - role-gate refusal text (env: railway / role: anon / etc.)
      - "SUPABASE_URL / SUPABASE_KEY not configured on this process"
      - "no response from Supabase after retries"
      - "HTTP <status>: <body snippet>"  (PostgREST's own message passes through)
      - "<ExceptionClass>: <msg>"

    Success: `.ok=True`, `.why=""`, `.value` is the parsed JSON or None.
    """
    _refusal = refuse_write(f"rpc {fn_name}")
    if _refusal:
        note_refusal(f"rpc:{fn_name}", _refusal)
        return StoreResult.fail(f"role_gate: {_refusal}")
    if not _SB_URL or not _SB_KEY:
        return StoreResult.fail("SUPABASE_URL / SUPABASE_KEY not configured on this process")
    url = f"{_SB_URL}/rest/v1/rpc/{fn_name}"
    headers = {"apikey": _SB_KEY, "Authorization": f"Bearer {_SB_KEY}",
               "Content-Type": "application/json"}
    try:
        resp = await _supabase_request_with_retry("POST", url, json=(payload or {}), headers=headers)
        if resp is None:
            return StoreResult.fail("no response from Supabase after retries")
        if resp.status_code in (200, 201, 204):
            try:
                return StoreResult.ok_(value=resp.json())
            except Exception:
                return StoreResult.ok_(value=None)
        # PostgREST puts OUR schema's own message here. Pass it through: a
        # generic failure string does not merely fail to help, it funds wrong
        # answers (S-138, the api_keys intended_use column).
        return StoreResult.fail(f"HTTP {resp.status_code}: {(resp.text or '')[:300]}")
    except Exception as e:                                  # noqa: BLE001
        return StoreResult.fail(f"{type(e).__name__}: {e}")


async def supabase_get_latest_track_record() -> list[dict[str, Any]]:
    """Latest signal_track_record batch (list of {signal,grade,n,avg_alpha_pct,
    alpha_win_pct, avg_edge_beta_adj_pct, edge_beta_adj_t, avg_beta_pit,
    n_beta_adj, computed_at}). Cached 6h; best-effort ([] on any miss →
    conviction falls back to the hardcoded prior).

    v2 (2026-07-26, MINIMAX_SYNC §BETA-METRIC-AGG): also reads the four
    β-adjusted columns populated by refresh_signal_track_record v2.
    The PUBLISH gate (ohlcv_daily freshness) lives in the caller
    (src/api/routers/signals.py::get_signal_track_record) and in
    supabase_ohlcv_daily_freshness() — this function returns the rows
    unfiltered; the gate is the caller's responsibility. The split
    avoids dependency cycles between the store layer and the router.
    """
    now = time.time()
    if _TRACKREC_CACHE["rows"] is not None and (now - _TRACKREC_CACHE["ts"]) < _TRACKREC_TTL:
        return cast("list[dict[str, Any]]", _TRACKREC_CACHE["rows"])
    if not _SB_URL or not _SB_KEY:
        return []
    url = f"{_SB_URL}/rest/v1/signal_track_record"
    params = {
        "order": "computed_at.desc", "limit": "60",
        "select": ("signal,grade,n,avg_alpha_pct,alpha_win_pct,"
                   "avg_abs_return_pct,"
                   "avg_edge_beta_adj_pct,edge_beta_adj_t,"
                   "avg_beta_pit,n_beta_adj,computed_at"),
    }
    headers = {"apikey": _SB_KEY, "Authorization": f"Bearer {_SB_KEY}"}
    try:
        resp = await _supabase_request_with_retry("GET", url, params=params, headers=headers)
        if resp and resp.status_code == 200:
            allrows = resp.json()
            latest = max((r.get("computed_at") for r in allrows), default=None)
            rows = [r for r in allrows if r.get("computed_at") == latest]
            _TRACKREC_CACHE["rows"] = rows
            _TRACKREC_CACHE["ts"] = now
            return rows
        return []
    except Exception as e:
        _logger.warning(f"[SUPABASE] track_record read exception: {e}")
        return []


# ── ohlcv_daily freshness probe (gate input for §BETA-METRIC-AGG) ───────────
# We do NOT publish β-adjusted investor numbers when the underlying price
# feed is stale (MINIMAX_SYNC §BETA-METRIC-AGG spec line 6880). The simplest
# check is to probe ohlcv_daily.last_trade_date directly via Supabase REST.
# Cached 5 min — the freshness gate is loose enough that this is plenty.
_OHLCV_FRESH_CACHE: dict[str, Any] = {"ts": 0.0, "result": cast("dict[str, Any] | None", None)}
_OHLCV_FRESH_TTL = 300
# Thresholds (seconds). 1.5 day = the daily collector must have written at
# least one row in the last 36 h to be considered "fresh." The 24 h admin
# threshold (cis `freshness_s`) intentionally allows a 12 h buffer because
# daily collectors can land anywhere in the 24 h window.
_OHLCV_FRESH_OPEN_S = 36 * 3600       # gate opens if age < 36 h
_OHLCV_FRESH_RECENT_S = 7 * 24 * 3600  # "recent" warning band


async def supabase_ohlcv_daily_freshness() -> dict[str, Any]:
    """Return the price-feed freshness block used by §BETA-METRIC-AGG gate.

    Returns dict with: {gate_open: bool, age_seconds, last_trade_date,
    verdict: "fresh"|"warning"|"stale", error?}.
    Cached 5 min. Honest about failure: error surfaces, not silently "open."
    """
    now = time.time()
    if _OHLCV_FRESH_CACHE["result"] is not None and (now - _OHLCV_FRESH_CACHE["ts"]) < _OHLCV_FRESH_TTL:
        return cast("dict[str, Any]", _OHLCV_FRESH_CACHE["result"])
    if not _SB_URL or not _SB_KEY:
        return {"gate_open": False, "age_seconds": None, "last_trade_date": None,
                "verdict": "stale", "error": "supabase_not_configured"}
    url = f"{_SB_URL}/rest/v1/ohlcv_daily"
    params = {"select": "trade_date", "order": "trade_date.desc", "limit": "1"}
    headers = {"apikey": _SB_KEY, "Authorization": f"Bearer {_SB_KEY}"}
    out: dict[str, Any] = {"gate_open": False, "age_seconds": None,
                 "last_trade_date": None, "verdict": "stale"}
    try:
        resp = await _supabase_request_with_retry("GET", url, params=params, headers=headers)
        if resp and resp.status_code == 200:
            rows = resp.json()
            if rows:
                last = str(rows[0].get("trade_date"))
                out["last_trade_date"] = last
                # Parse and age. trade_date is a date string (YYYY-MM-DD); we
                # assume UTC midnight — adequate for a "how stale is the feed"
                # check; the actual close time would be more precise but adds
                # schema coupling.
                try:
                    dt = datetime.fromisoformat(last.replace("Z", ""))
                    dt = dt.replace(tzinfo=timezone.utc)
                    age = (datetime.now(timezone.utc) - dt).total_seconds()
                    out["age_seconds"] = round(age, 1)
                    if age <= _OHLCV_FRESH_OPEN_S:
                        out["gate_open"] = True
                        out["verdict"] = "fresh"
                    elif age <= _OHLCV_FRESH_RECENT_S:
                        out["gate_open"] = False
                        out["verdict"] = "warning"
                    else:
                        out["gate_open"] = False
                        out["verdict"] = "stale"
                except Exception as e:
                    out["error"] = f"parse_failed:{e}"
            else:
                out["error"] = "ohlcv_daily_empty"
        else:
            out["error"] = f"http_{resp.status_code if resp else 'no_response'}"
    except Exception as e:
        out["error"] = f"exception:{str(e)[:120]}"
    _OHLCV_FRESH_CACHE["result"] = out
    _OHLCV_FRESH_CACHE["ts"] = now
    return out


# ── S-180: T1 occupancy, so a T2 writer can refuse to overwrite a live T1 ─────
_T1_OCCUPANCY_CACHE: dict[str, Any] = {"syms": cast("set[str] | None", None), "ts": 0.0}
_T1_OCCUPANCY_TTL = 120.0


async def supabase_fresh_t1_symbols(max_age_minutes: int = 90) -> set[str] | None:
    """Symbols that already have a T1 row in `cis_scores` inside the window.

    Returns None when the question could not be ASKED (Supabase unreachable,
    breaker open). None is not an empty set: an empty set means "no T1 rows
    exist, T2 is genuinely the only source"; None means "we do not know", and a
    writer must not treat not-knowing as permission.

    WHY (S-180). The hourly T2 snapshot loop guards itself with
    `tier_label == "T2"`, which is correct only if the tier label is correct.
    On 2026-08-19 it was not: a Redis read failure demoted the whole universe,
    so every asset presented as T2 and the loop wrote all of them — six minutes
    after a T1 row for the same symbol, with a different pillar set and a
    grade one letter away. Whichever landed last is what an allocator saw.

    The builder-side fix (holding last-good T1 across a blip) removes the cause.
    This removes the CONSEQUENCE, and it does so without trusting the builder:
    a receiver that checks the table cannot be talked into a bad write by an
    upstream that is confidently wrong. Both halves, because the cause will
    recur in a form the first fix does not cover — it already has, three times.
    """
    now = time.time()
    if (_T1_OCCUPANCY_CACHE["syms"] is not None
            and now - _T1_OCCUPANCY_CACHE["ts"] < _T1_OCCUPANCY_TTL):
        return cast("set[str] | None", _T1_OCCUPANCY_CACHE["syms"])
    if not _SB_URL or not _SB_KEY:
        return None
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=max_age_minutes)
    # `recorded_at`, NOT `created_at`. cis_scores has no created_at column, and
    # PostgREST answers a 400 for an unknown filter column — which this function
    # correctly maps to None ("could not ask"), which the hourly T2 writer
    # correctly treats as "do not write". Correct all the way down, and the net
    # effect was that the hourly loop silently wrote nothing for two cycles.
    #
    # Shipped 2026-08-20 in the same session where the identical mistake had
    # already thrown `column "created_at" does not exist` in an ad-hoc query an
    # hour earlier. Knowing a fact and encoding it are different acts; only the
    # second one survives, which is why the column name is now pinned by
    # `test_occupancy_query_filters_on_a_column_that_exists`.
    url = (f"{_SB_URL}/rest/v1/{_SB_TABLE}"
           f"?select=symbol&data_tier=eq.T1"
           f"&recorded_at=gte.{cutoff.isoformat()}&limit=5000")
    try:
        r = await _supabase_request_with_retry(
            "GET", url, headers={"apikey": _SB_KEY,
                                 "Authorization": f"Bearer {_SB_KEY}"})
        if r is None or r.status_code != 200:
            return None
        syms = {row["symbol"].upper() for row in r.json() if row.get("symbol")}
        _T1_OCCUPANCY_CACHE["syms"] = syms
        _T1_OCCUPANCY_CACHE["ts"] = now
        return syms
    except Exception as e:                                       # noqa: BLE001
        _logger.warning("[T1-OCC] could not read T1 occupancy: %s", e)
        return None


# ── D4 attention (trending_log) read — cached, for cause-proximity ─────────────
_TRENDING_CACHE: dict[str, Any] = {"map": cast("dict[str, dict[str, Any]] | None", None), "ts": 0.0}
_TRENDING_TTL = 1800  # 30 min — trending only refreshes daily, this is plenty fresh


async def supabase_get_latest_trending() -> dict[str, Any]:
    """Latest D4 attention snapshot as {SYMBOL_UPPER: row}. Cached 30 min; best-effort
    (returns {} on any miss so cause-proximity falls back to its market_proxy floor)."""
    now = time.time()
    if _TRENDING_CACHE["map"] is not None and (now - _TRENDING_CACHE["ts"]) < _TRENDING_TTL:
        return cast("dict[str, dict[str, Any]]", _TRENDING_CACHE["map"])
    if not _SB_URL or not _SB_KEY:
        return {}
    url = f"{_SB_URL}/rest/v1/trending_log"
    params = {
        "order": "recorded_at.desc",
        "limit": "60",   # ~4 daily snapshots of 15 coins — newest wins per symbol
        "select": "symbol,attention_score,sentiment_up,watchlist_users,market_cap_rank,trending_rank,recorded_at",
    }
    headers = {"apikey": _SB_KEY, "Authorization": f"Bearer {_SB_KEY}"}
    try:
        resp = await _supabase_request_with_retry("GET", url, params=params, headers=headers)
        if resp and resp.status_code == 200:
            out: dict[str, Any] = {}
            for row in resp.json():            # newest-first → first seen per symbol wins
                sym = (row.get("symbol") or "").upper()
                if sym and sym not in out:
                    out[sym] = row
            _TRENDING_CACHE["map"] = out
            _TRENDING_CACHE["ts"] = now
            return out
        return {}
    except Exception as e:
        _logger.warning(f"[SUPABASE] trending read exception: {e}")
        return {}


# ── Float sanitizer ───────────────────────────────────────────────────────────
def sanitize_floats(obj: Any) -> Any:
    """Recursively replace NaN/Inf numpy floats with None for JSON compliance."""
    if isinstance(obj, float):
        return None if not math.isfinite(obj) else obj
    if hasattr(obj, 'item'):  # numpy scalar
        try:
            val = obj.item()
            return None if isinstance(val, float) and not math.isfinite(val) else val
        except Exception:
            return None
    if isinstance(obj, dict):
        return {k: sanitize_floats(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [sanitize_floats(i) for i in obj]
    return obj


# ── WebSocket connection manager ─────────────────────────────────────────────
class ConnectionManager:
    def __init__(self) -> None:
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        try:
            if websocket in self.active_connections:
                self.active_connections.remove(websocket)
        except (ValueError, RuntimeError) as e:
            _logger.warning(f"[WS] disconnect error: {e}")

    async def broadcast(self, message: dict[str, Any]) -> None:
        # Remove dead connections before broadcasting
        self.cleanup_dead()

        dead: list[WebSocket] = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                dead.append(connection)
        for conn in dead:
            self.disconnect(conn)

    def cleanup_dead(self) -> None:
        """Remove dead connections that raised errors during send."""
        self.active_connections = [c for c in self.active_connections if self._is_alive(c)]

    def _is_alive(self, websocket: WebSocket) -> bool:
        """Check if WebSocket is still connected."""
        try:
            return websocket.client_state == WebSocketState.CONNECTED
        except Exception:
            return False


# Singleton — shared across all routers
ws_manager = ConnectionManager()

# Last CIS broadcast payload — sent to new subscribers on connect
last_cis_broadcast: dict[str, Any] | None = None
