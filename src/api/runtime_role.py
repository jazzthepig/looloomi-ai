"""
Runtime role — who is allowed to write the FORWARD RECORD (S-149/S-150).

THE INCIDENT. Running the app locally produced a night of confusing errors, and
the investigation cost three rounds. The proximate causes were missing credentials.
The structural cause was that **a laptop and the production deployment are the same
program with the same defaults**, and one of those defaults was:

    _ENV = os.environ.get("ENVIRONMENT", "production")

An unset variable made any machine a production writer. The only thing preventing
the local run from writing to the live tables was that `SUPABASE_KEY` happened to be
empty. Safety by accident.

Concretely, what was one paste away: the local process starts 20+ background loops,
a dozen of which write Supabase and share Redis state keys with Railway. Both would
have marked `beta_core_nav` for the same day off different panels at different
times. The forward record — the one artefact of this company that cannot be
re-derived — would have become a function of which machine woke first.

THE BOUNDARY IS *WRITE*, NOT *CONNECT*. Reading production from a laptop is useful
and harmless; it is how you debug against real data. Writing is the part that must
have exactly one owner. So this module gates writes and leaves reads alone.

SCOPE, stated precisely because the first version of this docstring was not
(S-150). This gates writes to the FORWARD RECORD — the paper-book NAVs, cis_scores,
the outcome and snapshot tables, the strategy graveyard. It does NOT gate business
tables (leads, webhooks, auth, api_keys, api_usage): those have no single-owner
requirement, and claiming them would make the rule unbelievable and the list
unmaintainable.

The original claim — "the write side has one owner" — was broader than the
implementation: two functions were gated while five record writers went around
them, and the guard defending the claim passed because it checked only the two it
knew about. `test_every_record_writer_is_gated_including_ones_added_later` now
ENUMERATES, so a writer added next month fails the build rather than being
silently outside the fence.

  production  the single writer. EXPLICIT ONLY — never a default.
  replica     reads everything, writes nothing. The default for anything unset.
  dev         writes, but only to an isolated namespace (Phase 2 — see below).

FAIL CLOSED. Unset ⇒ `replica`. An unrecognised value ⇒ refuse to start rather than
guess: a typo'd role that silently degrades to "writer" is the failure this exists
to remove, and a typo'd role that silently degrades to "reader" would hide a real
production deploy behind a green boot.

WHAT THIS DOES NOT YET DO (stated so its absence is not mistaken for coverage).
Redis writes have six separate `_redis_set` definitions and no single choke point,
so `dev` cannot yet be given a private namespace. Until it can, `dev` is refused.
Phase 2 is: one Redis write helper, key-prefixed by role, plus a Supabase branch —
at which point local write-path development becomes possible instead of dangerous.
"""
from __future__ import annotations

import logging
import os

_log = logging.getLogger("runtime_role")

PRODUCTION = "production"
REPLICA = "replica"
DEV = "dev"

_VALID = (PRODUCTION, REPLICA, DEV)

# Legacy `ENVIRONMENT` values mapped onto roles. `production` here is deliberate
# and load-bearing: Railway sets ENVIRONMENT=production explicitly, so the mapping
# preserves the live deployment. Everything else — ci, staging, unset — reads.
_LEGACY_MAP = {
    "production": PRODUCTION,
    "staging": REPLICA,
    "ci": REPLICA,
    "test": REPLICA,
    "development": REPLICA,
    "local": REPLICA,
}


class RoleConfigurationError(RuntimeError):
    """Raised at import time for a role we cannot honour. Loud on purpose."""


def _resolve() -> str:
    explicit = (os.environ.get("APP_ROLE") or "").strip().lower()
    if explicit:
        if explicit not in _VALID:
            raise RoleConfigurationError(
                f"APP_ROLE={explicit!r} is not one of {_VALID}. Refusing to start: "
                f"guessing would mean choosing between silently writing to "
                f"production and silently hiding a real deployment, and both of "
                f"those are worse than not booting.")
        if explicit == DEV:
            raise RoleConfigurationError(
                "APP_ROLE=dev is not implemented yet. It requires a private Redis "
                "namespace and an isolated Supabase branch (Phase 2); until then a "
                "'dev' writer would share prod state keys, which is the exact "
                "hazard this module exists to remove. Use APP_ROLE=replica.")
        return explicit

    legacy = (os.environ.get("ENVIRONMENT") or "").strip().lower()
    if not legacy:
        # THE FIX. This used to default to production.
        return REPLICA
    return _LEGACY_MAP.get(legacy, REPLICA)


ROLE: str = _resolve()


def is_writer() -> bool:
    """May this process write to the shared system of record?"""
    return ROLE == PRODUCTION


def refuse_write(what: str) -> str | None:
    """None if the write may proceed, else a reason to log and return False on.

    Returns a reason rather than raising: a replica that CRASHES on a write attempt
    is a replica you cannot use to debug the write path. It should decline, say so
    once, and keep serving."""
    if is_writer():
        return None
    return (f"role={ROLE} may not write {what}. Reads are unrestricted; the write "
            f"side of the record has exactly one owner (APP_ROLE=production, set "
            f"only on the live deployment).")


_WARNED: set[str] = set()


def note_refusal(what: str, reason: str) -> None:
    """Log a refusal ONCE per target. A background loop refusing every five minutes
    would bury the boot banner that explains why."""
    if what in _WARNED:
        return
    _WARNED.add(what)
    _log.warning("[ROLE] %s", reason)


def describe() -> dict:
    """The boot banner's payload — role, capability, and credential presence.

    Credential VALUES never appear; only whether each is set, empty or absent. The
    three states matter: `SUPABASE_KEY=` (present but empty) reads as configured to
    every `os.environ.get` in the codebase and writes nothing, which is precisely
    how a night was lost."""
    def _state(name: str) -> str:
        if name not in os.environ:
            return "absent"
        return "set" if os.environ[name].strip() else "EMPTY"

    creds = {n: _state(n) for n in (
        "SUPABASE_URL", "SUPABASE_KEY", "SUPABASE_SERVICE_KEY",
        "UPSTASH_REDIS_REST_URL", "UPSTASH_REDIS_REST_TOKEN",
        "INTERNAL_TOKEN", "TELEGRAM_BOT_TOKEN", "TELEGRAM_ALERT_CHAT_ID",
        "GITHUB_TOKEN", "COINGECKO_API_KEY",
    )}
    return {
        "role": ROLE,
        "writes_shared_record": is_writer(),
        "credentials": creds,
        "degraded": [n for n, s in creds.items() if s != "set"],
    }


def banner() -> str:
    d = describe()
    lines = [
        "",
        "╭─ RUNTIME ROLE ────────────────────────────────────────────────",
        f"│  role                 : {d['role']}",
        f"│  writes shared record : {'YES — this is the live writer' if d['writes_shared_record'] else 'no (reads only)'}",
    ]
    for n, s in d["credentials"].items():
        mark = "✓" if s == "set" else ("∅" if s == "absent" else "⚠")
        lines.append(f"│  {mark} {n:<26} {s}")
    if d["degraded"]:
        lines.append("│")
        lines.append(f"│  {len(d['degraded'])} credential(s) not usable — features "
                     f"depending on them will")
        lines.append("│  degrade. This line exists because the alternative is finding")
        lines.append("│  out from a stack trace at 01:00.")
    lines.append("╰───────────────────────────────────────────────────────────────")
    return "\n".join(lines)
