"""
System heartbeat — the observability loop.

Every failure this codebase hit (empty universe, stale Mac Mini push, contract
drift, NULL MacroBrief) was found *reactively*, by someone looking. This turns
that into proactive Telegram alerts: a scheduled check computes one health
verdict, and when the verdict changes (healthy↔broken) it pings the ops channel.

`compute_health_summary()` — one JSON verdict over cheap Redis reads (no heavy
recompute). Served at GET /internal/health-summary.
`heartbeat_tick()`   — compute + diff against last verdict in Redis + alert on
change; also a once-daily digest. Called by the scheduled loop in main.py.
"""
from __future__ import annotations

import os
import time
import logging
from datetime import datetime, timezone

_log = logging.getLogger("health")

_PUSH_STALE_S = 7200          # Mac Mini pushes ~every 4h; >2h with no fresh push = warn
_MIN_UNIVERSE = 40
_LAST_KEY = "health:last_verdict"
_DIGEST_KEY = "health:last_digest_date"


def _check(name: str, ok: bool, detail: str = "", warn: bool = False) -> dict:
    state = "ok" if ok else ("warn" if warn else "fail")
    return {"name": name, "state": state, "detail": detail}


async def compute_health_summary() -> dict:
    from src.api.store import redis_get, redis_get_key
    checks: list[dict] = []
    now = time.time()

    # 1–3. CIS push freshness, universe size, contract drift (from the hot cache)
    cache = None
    try:
        cache = await redis_get()
    except Exception:
        pass
    if cache and cache.get("universe"):
        age = now - float(cache.get("last_updated") or 0)
        checks.append(_check("mac_mini_push", age < _PUSH_STALE_S,
                             f"{int(age)}s ago", warn=age >= _PUSH_STALE_S))
        n = len(cache.get("universe") or [])
        checks.append(_check("universe", n >= _MIN_UNIVERSE, f"{n} assets",
                             warn=0 < n < _MIN_UNIVERSE))
        dw = len(cache.get("contract_warnings") or [])
        checks.append(_check("contract_drift", dw == 0, f"{dw} warning(s)", warn=dw > 0))
    else:
        # No fresh push — are we at least serving last-known-good?
        lkg = None
        try:
            lkg = await redis_get_key("cis:last_known_good")
        except Exception:
            pass
        checks.append(_check("mac_mini_push", False, "no fresh push in cache", warn=bool(lkg)))
        has = bool(lkg and lkg.get("universe"))
        checks.append(_check("universe", has,
                             "serving last-known-good" if has else "EMPTY", warn=has))

    # 4. MacroBrief present AND FRESH
    #
    # S-187 (2026-08-20). This used to check only that a brief EXISTED, so a
    # three-day-old brief reported "present" and /health stayed green.
    #
    # That gap became load-bearing when generation moved to a resident Mac loop
    # on a 5-minute tick. The loop carries its own MAX_BRIEF_AGE_S ceiling — it
    # regenerates after 30 minutes even on a flat tape, precisely so that a
    # frozen brief is impossible. But **that ceiling is enforced inside the loop,
    # so it cannot fire when the loop is what died.** A hung LM Studio call, a
    # crashed process, a launchd job that stopped being loaded: in every case the
    # ceiling goes with it, the last brief sits in Redis under a 12-hour TTL, and
    # the page looks fine until the brief vanishes entirely half a day later.
    #
    # A fail-safe inside the thing that fails is not a fail-safe. Detection has
    # to live on the other side of the wire — which is here. Same lesson as
    # S-175 (a forward record whose refresher had no caller) and S-185 (a
    # fail-closed guard whose outage emitted no signal).
    try:
        from src.api.contracts.macro_brief import MAX_BRIEF_AGE_S
        mb = await redis_get_key("macro:brief")
        if not (mb and mb.get("brief")):
            checks.append(_check("macro_brief", False, "missing", warn=True))
        else:
            age = int(time.time()) - int(mb.get("received_at") or 0)
            # Two ceilings of slack: one missed cycle is a blip, two is a
            # pattern. Anything past that and the generator is not running.
            limit = MAX_BRIEF_AGE_S * 2
            fresh = age <= limit
            checks.append(_check(
                "macro_brief", fresh,
                f"fresh ({age // 60}m)" if fresh else
                f"STALE {age // 60}m (limit {limit // 60}m) — the Mac generator "
                f"has stopped; its own 30-min ceiling cannot fire if the loop is dead",
                warn=True))
    except Exception as _e:
        checks.append(_check("macro_brief", False, f"unreadable: {_e}", warn=True))

    # Overall verdict = worst state present
    states = {c["state"] for c in checks}
    status = "down" if "fail" in states else ("degraded" if "warn" in states else "healthy")

    return {
        "status": status,
        "checks": checks,
        "deploy_sha": (os.environ.get("RAILWAY_GIT_COMMIT_SHA", "") or "")[:8] or None,
        "as_of": datetime.now(timezone.utc).isoformat(),
    }


def _format_alert(summary: dict) -> str:
    icon = {"healthy": "✅", "degraded": "⚠️", "down": "🔴"}.get(summary["status"], "•")
    lines = [f"{icon} CometCloud health: {summary['status'].upper()}"]
    for c in summary["checks"]:
        mark = {"ok": "✓", "warn": "!", "fail": "✗"}.get(c["state"], "?")
        lines.append(f"  {mark} {c['name']}: {c['detail']}")
    if summary.get("deploy_sha"):
        lines.append(f"  · deploy {summary['deploy_sha']}")
    return "\n".join(lines)


async def heartbeat_tick() -> dict:
    """
    Compute health, alert Telegram on a status transition, and send a once-daily
    digest. Returns the summary. Safe no-op if Telegram/Redis unconfigured.
    """
    from src.api.store import redis_get_key, redis_set_key
    from src.api.notify import notify_telegram

    summary = await compute_health_summary()
    status = summary["status"]

    prev, prev_sha = None, None
    try:
        prevd = await redis_get_key(_LAST_KEY)
        prev = (prevd or {}).get("status")
        prev_sha = (prevd or {}).get("sha")
    except Exception:
        pass

    sha = summary.get("deploy_sha")

    # Loop 3 — deploy auto-verify: a new sha means a fresh deploy went live.
    # Verify it (the summary IS the post-deploy health check) and report to Telegram.
    if sha and prev_sha and sha != prev_sha:
        verdict = "✅ healthy" if status == "healthy" else f"⚠️ {status}"
        await notify_telegram(f"🚀 Deploy live: {sha} — post-deploy check {verdict}\n"
                              + _format_alert(summary))

    # Alert on any health transition (healthy→down, or recovery down→healthy)
    if prev != status:
        await notify_telegram(_format_alert(summary)
                              + ("\n\n(recovered)" if prev and status == "healthy" else ""))

    if prev != status or sha != prev_sha:
        try:
            await redis_set_key(_LAST_KEY, {"status": status, "sha": sha}, ttl=7 * 86400)
        except Exception:
            pass

    # Once-daily digest regardless of state (the "everything's fine" heartbeat)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        last_digest = (await redis_get_key(_DIGEST_KEY) or {}).get("date")
        if last_digest != today:
            await notify_telegram("Daily health digest\n" + _format_alert(summary))
            await redis_set_key(_DIGEST_KEY, {"date": today}, ttl=2 * 86400)
    except Exception:
        pass

    return summary
