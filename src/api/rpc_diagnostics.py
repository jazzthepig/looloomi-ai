"""What the RPC call ACTUALLY did — not what we guessed it did (S-323m).

WHY THIS EXISTS. Measured across S-323 → S-323l, five consecutive rounds of
diagnosis, every one of them wrong, all misled by the same sentence:

    "深盘符号表**没读到**(RPC 不通/熔断/超时)"

That string is emitted by `main.py` when `deep_panel_symbols()` returns None.
It names three suspects — RPC, breaker, timeout — and the real cause across
those five rounds was, in order: a missing index, a cold PostgREST schema
cache, a 4xx recorded as breaker SUCCESS, a GRANT on a function whose name
appears nowhere in it, and finally a loop that was simply ASLEEP.

**The message was assembled from the hypotheses its author had at the time,
not from the response.** So it kept returning every reader — me, five times —
to that author's guesses. A message that enumerates guesses costs more than no
message at all: no message sends you to look at the response, that one
persuades you that you already have.

The real evidence existed the whole time. `store.py` logs status code and body
at WARNING and then throws them away:

    _logger.warning(f"[SUPABASE] rpc {fn} error {resp.status_code}: {resp.text[:120]}")

Nothing carries them to `_beat(error=...)`, so `/internal/data-freshness` — the
surface anyone actually reads — shows the guess and never the fact.

THE RULE THIS ENCODES. **A diagnostic field must carry an observation, never a
hypothesis.** If we do not know why something failed, the honest rendering is
the status code and the body, however unhelpful they look. A guess dressed as a
diagnosis is worse than "unknown", because "unknown" makes you go and measure.

Credit: Minimax-A reached this independently on 2026-09-09 while auditing the
whole project, and located it more precisely than I had — I had recorded the
symptom in the ledger four times without once fixing the layer that produced it.
"""
from __future__ import annotations

import time
from typing import Any

__all__ = ["rpc_with_detail", "render_detail"]


async def rpc_with_detail(fn_name: str,
                          payload: dict | None = None) -> tuple[Any, dict]:
    """Call a PostgREST RPC and return `(data_or_None, detail)`.

    `detail` always says which of the mutually-exclusive outcomes happened, so
    a caller can render a fact instead of a list of suspects:

        not_configured  SUPABASE_URL / SUPABASE_KEY missing on this process
        breaker_open    short-circuited before any network call
        no_response     timeout, or all retries exhausted (None from the layer)
        http_error      the backend answered, and this is the code and the body
        not_json        HTTP 200 whose body would not parse
        ok              data returned

    These have DIFFERENT fixes — set a variable, wait for cooldown, look at the
    query plan, fix a grant, fix the payload — which is exactly why collapsing
    them into one None (and then into one sentence) cost five rounds.
    """
    from src.api import store

    detail: dict[str, Any] = {
        "fn": fn_name, "outcome": None, "status": None,
        "body": None, "elapsed_ms": None,
        # Breaker state at call time. Recorded because "the breaker did it" was
        # asserted repeatedly and was false every time; now it is observed.
        "breaker_open": None, "breaker_consecutive_failures": None,
        "breaker_lifetime_trips": None,
    }

    if not store._SB_URL or not store._SB_KEY:
        detail["outcome"] = "not_configured"
        return None, detail

    detail["breaker_open"] = bool(time.time() < store._cb_open_until)
    detail["breaker_consecutive_failures"] = store._cb_consecutive_failures
    detail["breaker_lifetime_trips"] = store._cb_trips

    url = f"{store._SB_URL}/rest/v1/rpc/{fn_name}"
    headers = {"apikey": store._SB_KEY,
               "Authorization": f"Bearer {store._SB_KEY}",
               "Content-Type": "application/json"}

    t0 = time.time()
    try:
        resp = await store._supabase_request_with_retry(
            "POST", url, json=(payload or {}), headers=headers)
    except Exception as e:                                      # noqa: BLE001
        detail["outcome"] = "exception"
        detail["body"] = f"{type(e).__name__}: {str(e)[:200]}"
        detail["elapsed_ms"] = int((time.time() - t0) * 1000)
        return None, detail
    detail["elapsed_ms"] = int((time.time() - t0) * 1000)

    if resp is None:
        # The layer already folds breaker-open / timeout / retries-exhausted
        # into one None. We cannot un-fold it from here, so we say which one it
        # WAS NOT: the breaker state was captured before the call.
        detail["outcome"] = "breaker_open" if detail["breaker_open"] else "no_response"
        return None, detail

    detail["status"] = resp.status_code
    if resp.status_code in (200, 204):
        try:
            data = resp.json()
        except Exception:                                       # noqa: BLE001
            detail["outcome"] = "not_json"
            detail["body"] = (resp.text or "")[:200]
            return None, detail
        detail["outcome"] = "ok"
        if isinstance(data, list):
            detail["n_rows"] = len(data)
        return data, detail

    # THE BODY IS THE POINT. PostgREST puts our own schema's message here —
    # "permission denied for function ohlcv_symbol_coverage" is the sentence
    # that would have ended this in round one.
    detail["outcome"] = "http_error"
    detail["body"] = (resp.text or "")[:300]
    return None, detail


def render_detail(detail: dict, *, prefix: str = "") -> str:
    """One line, observation only. **Never append a suspected cause.**"""
    o = detail.get("outcome")
    fn = detail.get("fn", "?")
    ms = detail.get("elapsed_ms")
    took = f" [{ms}ms]" if ms is not None else ""
    cb = (f" breaker(open={detail.get('breaker_open')},"
          f"fails={detail.get('breaker_consecutive_failures')},"
          f"trips={detail.get('breaker_lifetime_trips')})")

    if o == "ok":
        return f"{prefix}{fn}: ok, {detail.get('n_rows', '?')} rows{took}"
    if o == "not_configured":
        return f"{prefix}{fn}: SUPABASE_URL/KEY not set on this process"
    if o == "breaker_open":
        return f"{prefix}{fn}: circuit breaker OPEN — no request was sent.{cb}"
    if o == "no_response":
        return (f"{prefix}{fn}: no response (timeout or retries exhausted)"
                f"{took}.{cb}")
    if o == "http_error":
        return (f"{prefix}{fn}: HTTP {detail.get('status')}{took} — "
                f"{detail.get('body')}")
    if o == "not_json":
        return (f"{prefix}{fn}: HTTP {detail.get('status')} but body is not JSON"
                f"{took} — {detail.get('body')}")
    if o == "exception":
        return f"{prefix}{fn}: {detail.get('body')}{took}"
    return f"{prefix}{fn}: outcome={o!r} (unrecognised — this is not success)"
