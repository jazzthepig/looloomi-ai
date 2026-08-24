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

# Legacy `ENVIRONMENT` values mapped onto roles. Everything not listed — ci,
# staging, unset — resolves to REPLICA, i.e. reads only.
#
# THIS COMMENT USED TO SAY: "`production` here is deliberate and load-bearing:
# Railway sets ENVIRONMENT=production explicitly, so the mapping preserves the
# live deployment."
#
# MEASURED FALSE, 2026-08-15 (S-168). Railway sets neither variable. The live
# service resolved to REPLICA the moment this gate shipped, and production could
# not write the system of record for three days: cis_scores, beta_core_nav and
# experiment_runs all stop on 2026-08-12. The Mac T1 engine kept pushing the
# whole time and every push was accepted, returned 200, and discarded.
#
# The sentence is kept here rather than deleted because of HOW it failed. It was
# emphatic — "deliberate and load-bearing" — and that emphasis is what stopped
# anyone checking. A confident claim about another system's configuration is
# still a claim about another system's configuration, and this file had no way
# to verify it. Prose cannot probe an environment variable.
#
# Railway now needs APP_ROLE=production set explicitly. That is louder than
# relying on a legacy value, and /health reports the consequence in words
# ("READ-ONLY — nothing is being persisted") rather than the role.
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

#: 每个目标被拒了多少次 (S-228, 2026-08-24)。
#:
#: WHY COUNT AND NOT JUST LOG. 原来只 log-once,理由是对的(每五分钟一条会淹没
#: boot banner)。但 log-once 的代价是:**一次拒绝和一万次拒绝在外面看起来一样,
#: 而且都只是 Railway 日志里的一行。**
#:
#: 今天这让两个完全不同的世界无法区分:
#:   (a) 线上是 primary,`strategy_records` 空是因为【没人调那个端点】
#:   (b) 线上是 replica,每一次写入都在被【静默拒绝】
#: 两者的修法毫不相干,而我在 S-221 里直接断言了 (a)。**我断言的时候没有能力知道。**
#:
#: 计数不写日志,所以不会淹没任何东西;它只是让"拒绝了多少次"变成可查的事实。
_REFUSALS: dict[str, int] = {}


def note_refusal(what: str, reason: str) -> None:
    """Count every refusal; log the first one per target.

    计数与日志分开:日志是给人看的,一次就够;计数是给探针看的,必须全量 ——
    「有没有发生过」和「发生了多少次」是两个问题,而只有后者能告诉你一个循环
    是不是每天都在撞同一堵墙。
    """
    _REFUSALS[what] = _REFUSALS.get(what, 0) + 1
    if what in _WARNED:
        return
    _WARNED.add(what)
    _log.warning("[ROLE] %s", reason)


def refusal_counts() -> dict[str, int]:
    """{目标: 被拒次数}。空字典 = 从未有过写入尝试被拒。

    ⚠️ 空字典**不等于**"写入都成功了" —— 它也可能是"根本没人尝试过写"。
    这两件事要靠调用方的写入计数去分,不要在这里合并。
    """
    return dict(_REFUSALS)


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
