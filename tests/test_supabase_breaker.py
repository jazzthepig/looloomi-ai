"""
Supabase circuit breaker — the 2026-07-29 P0 incident compiled into tests.
==========================================================================

INCIDENT. Supabase (free tier) reported "exhausting multiple resources". Every
/api/v1/cis/* request then burned timeout(10) x 3 attempts + backoff(1+2) = up to
33s before giving up, so endpoints HUNG instead of erroring — and each request
tripled the load on an already-saturated database. Our own retry policy was a
retry storm. Meanwhile /health returned a hardcoded "healthy".

These tests exist so the incident cannot silently return:
  · timeouts must NOT be retried          (retrying is what caused the outage)
  · the breaker must OPEN and fail fast   (bounded latency, no queueing)
  · it must RECOVER after cooldown        (S-90 lesson: never lock permanently)
  · 4xx must NOT trip the breaker         (healthy backend, bad request)
  · health must REFLECT breaker state     (a check that can't fail isn't a check)

Run: python3 -m tests.test_supabase_breaker
"""
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import httpx  # noqa: E402

from src.api import store  # noqa: E402


def _reset(threshold=5, cooldown=30.0):
    store._cb_consecutive_failures = 0
    store._cb_open_until = 0.0
    store._CB_FAIL_THRESHOLD = threshold
    store._CB_COOLDOWN_S = cooldown


class _FakeClient:
    """Stands in for the httpx client. Records call count so we can prove that
    an open breaker issues ZERO network calls (the load-shedding property)."""

    def __init__(self, behaviour):
        self.behaviour = behaviour
        self.calls = 0

    async def request(self, method, url, **kw):
        self.calls += 1
        b = self.behaviour
        if b == "timeout":
            raise httpx.ReadTimeout("simulated saturation")
        if b == "500":
            return httpx.Response(500, text="boom")
        if b == "404":
            return httpx.Response(404, text="no such row")
        return httpx.Response(200, json={"ok": True})


def _run(behaviour, n=1):
    fake = _FakeClient(behaviour)
    store._get_supabase_client = lambda: fake  # type: ignore[assignment]
    outs = [asyncio.run(store._supabase_request_with_retry("GET", "http://x")) for _ in range(n)]
    return fake, outs


def test_timeout_is_not_retried():
    """The core fix. One timeout ⇒ one call, immediate None. Retrying a saturated
    backend is what converted a slowdown into an outage."""
    _reset()
    fake, outs = _run("timeout")
    assert fake.calls == 1, f"timeout must not be retried, got {fake.calls} calls"
    assert outs[0] is None
    assert store._cb_consecutive_failures == 1


def test_breaker_opens_and_stops_issuing_calls():
    """After threshold failures the breaker opens and issues ZERO further calls —
    this is what takes load OFF the database so it can recover."""
    _reset(threshold=3)
    fake, _ = _run("timeout", n=3)
    assert fake.calls == 3
    assert store.supabase_breaker_state()["open"], "breaker must be open at threshold"

    calls_before = fake.calls
    out = asyncio.run(store._supabase_request_with_retry("GET", "http://x"))
    assert out is None, "open breaker must fail fast with None"
    assert fake.calls == calls_before, "open breaker must issue NO network calls"


def test_breaker_fails_fast():
    """Bounded latency while open — the user-visible symptom was a 33s hang."""
    _reset(threshold=1)
    _run("timeout", n=1)
    assert store.supabase_breaker_state()["open"]
    t0 = time.time()
    asyncio.run(store._supabase_request_with_retry("GET", "http://x"))
    assert time.time() - t0 < 0.1, "open breaker must return immediately"


def test_breaker_recovers_after_cooldown():
    """S-90 lesson (the drawdown-ladder freeze that never unfroze): any control
    that cuts something off MUST have a proven path back. Permanent lock-out is
    the same bug in a different costume."""
    _reset(threshold=1, cooldown=0.05)
    _run("timeout", n=1)
    assert store.supabase_breaker_state()["open"]
    time.sleep(0.08)
    assert not store.supabase_breaker_state()["open"], "breaker must close after cooldown"
    fake, outs = _run("ok", n=1)
    assert outs[0] is not None and fake.calls == 1, "must resume real calls after recovery"
    assert store._cb_consecutive_failures == 0, "success must reset the failure count"


def test_4xx_does_not_trip_breaker():
    """A 404 means the backend is HEALTHY and the request was wrong. Counting it
    would open the breaker on perfectly good infrastructure."""
    _reset(threshold=2)
    fake, outs = _run("404", n=5)
    assert fake.calls == 5, "4xx must not be retried but must still be issued"
    assert outs[0] is not None and outs[0].status_code == 404
    assert not store.supabase_breaker_state()["open"], "4xx must never open the breaker"


def test_5xx_still_retries_then_trips():
    """5xx is a genuinely transient fault ⇒ backoff retry is still correct there.
    We only removed retry for timeouts."""
    _reset(threshold=1)
    store._SB_BASE_DELAY = 0.001
    fake, outs = _run("500", n=1)
    assert fake.calls == store._SB_MAX_RETRIES, f"5xx should retry, got {fake.calls}"
    assert outs[0] is None
    assert store.supabase_breaker_state()["open"]


def test_health_reports_degraded_when_breaker_open():
    """/health returned a hardcoded 'healthy' through the whole outage. A health
    check that cannot fail is not a check."""
    _reset(threshold=1)
    _run("timeout", n=1)
    from src.api.main import _health_with_data_layer
    h = _health_with_data_layer()
    assert h["status"] == "degraded", "health must go degraded when the data layer is down"
    assert h["data_layer"]["supabase"] == "circuit_open"

    _reset()
    h2 = _health_with_data_layer()
    assert h2["status"] == "healthy" and h2["data_layer"]["supabase"] == "ok"


TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_")]

if __name__ == "__main__":
    p = 0
    for t in TESTS:
        t(); print(f"  ✓ {t.__name__}"); p += 1
    print(f"\n✅ {p}/{len(TESTS)} supabase breaker checks passed")
