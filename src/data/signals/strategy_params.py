"""
Strategy parameters — versioned, append-only, VALIDATED ON LOAD (S-151).

WHY THIS EXISTS, two reasons, and the second one is the load-bearing one.

REASON 1 (Jazz, 2026-08-12): the mined edge must not ship inside the repo.
`SIZE_TABLE_2D` (C3's 5×5 conviction table) and C2's ⓠ thresholds ARE the
research output — everything around them is plumbing. So the values move out
and the code keeps only a neutral fallback. Note what this does NOT mean:
the modules stay tracked. `src/api/main.py` imports them and Railway deploys
from git, so a gitignored module is a 500 on the endpoint and a silent stall
on the ⓠ clock. **The edge leaves as PARAMETERS, never as import targets.**

REASON 2 — the one that made this urgent. Moving parameters into a table means
they can change without a code review, and a forward record cannot show what
it cannot see. That would be an unacceptable trade on its own. It becomes
acceptable only if two things hold:

    (a) every row of the forward record carries the param version that
        produced it, and
    (b) a parameter set that violates the sleeve's own stated invariants
        CANNOT LOAD.

(b) is not hypothetical. Measured 2026-08-12, before any of this existed:

    lookup_size(regime=5 out-of-distribution, signal=1 weakest)  = 1.30
    lookup_size(regime=1 in-distribution,     signal=5 strongest) = 0.10

both exactly inverted from the module's own docstring, on both axes. Centre
cell (3,3)=0.85 was correct — it is the fixed point of a transpose, which is
why spot-checking "the default baseline" passed. Worse, with BOTH inputs
missing the table returns **1.20**, and `beta_core_size_hook` documented that
number as the intended first-ship baseline, "slightly above 1.0". A defect
does not get more expensive than when it has been written down as the plan.

So the invariant that matters is not "the table equals these 25 numbers" — a
frozen-value check would have passed the day the table was transposed, because
it was transposed before it was frozen. The invariant is BEHAVIOURAL:

    no information must never produce leverage
    less familiar regime must never produce more size
    weaker signal must never produce more size

Those hold for any correctly-oriented table and fail for every inverted one,
including tables nobody has written yet. That is the difference between a
guard that protects you from the past and one that protects you from next
month.

FAIL CLOSED, AND SAY SO. A rejected payload does not raise — it falls back to
the in-code neutral values and returns `source="db_rejected_fallback"`, which
is stamped into the NAV row. A sleeve that crashes on a bad config is a sleeve
you cannot debug; a sleeve that silently swaps to fallback is the class of bug
this module exists to remove. It must degrade, record that it degraded, and
keep marking.

APPEND-ONLY. Rows are never UPDATEd. A new parameter set is a new
`param_version`; activating it is an INSERT of a higher version. The old row
stays, so "what were the thresholds on 2026-09-14" is answerable forever —
which is the whole point of a 60-day forward commitment.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Callable

_log = logging.getLogger("strategy_params")

# Namespaces. One per sleeve; the string is written into the NAV row, so it is
# part of the record's contract — renaming one orphans the history.
NS_C2_Q = "c2_q_v1"
NS_C3_SIZE = "c3_size_v1"
NS_INVESTABLE = "investable_v1"
NS_TRIPWIRE = "capacity_tripwire_v1"

_CODE_FALLBACK = "code_fallback"
_DB = "db"
_DB_REJECTED = "db_rejected_fallback"


class InvariantViolation(Exception):
    """A parameter payload that would misprice risk. Carries every failure,
    not just the first — a config author fixing them one round-trip at a time
    is a config author who will give up and paste the old values back."""

    def __init__(self, namespace: str, problems: list[str]):
        self.namespace = namespace
        self.problems = problems
        super().__init__(f"{namespace}: {len(problems)} invariant violation(s): "
                         + "; ".join(problems))


@dataclass(frozen=True)
class ParamSet:
    """Parameters plus their provenance. `version` and `source` are NOT
    diagnostics — they belong in the NAV row. A forward record that cannot say
    which parameters produced it is a forward record you cannot defend."""
    namespace: str
    values: dict[str, Any]
    version: int
    source: str                       # db | code_fallback | db_rejected_fallback
    problems: list[str] = field(default_factory=list)

    @property
    def is_degraded(self) -> bool:
        return self.source != _DB

    def stamp(self) -> dict[str, Any]:
        """The columns every NAV row written under these params must carry."""
        return {
            "param_namespace": self.namespace,
            "param_version": self.version,
            "param_source": self.source,
        }


# ── Invariants ───────────────────────────────────────────────────────────────
# A validator returns a list of problems (empty = valid). It must never raise:
# a validator that throws on malformed input turns "bad config" into "no book".

def _validate_c3_size(v: dict) -> list[str]:
    """C3 conviction-size table. Stated intent, from beta_core_size.py:

        regime band ↑ (less familiar)  → size ↓
        signal band ↑ (more conviction) → size ↑
        missing inputs                  → conservative

    Every one of these was violated by the table in the repo on 2026-08-12.
    """
    problems: list[str] = []
    table = v.get("size_table_2d")
    if not isinstance(table, (list, tuple)) or len(table) != 5:
        return ["size_table_2d must be 5 rows (regime bands 1..5)"]
    rows: list[list[float]] = []
    for i, row in enumerate(table, 1):
        if not isinstance(row, (list, tuple)) or len(row) != 5:
            return [f"size_table_2d row {i} must have 5 columns (signal bands 1..5)"]
        try:
            rows.append([float(x) for x in row])
        except (TypeError, ValueError):
            return [f"size_table_2d row {i} contains a non-numeric cell"]

    clip_max = float(v.get("size_clip_max", 1.3))

    # (1) signal ↑ → size ↑, along every regime row.
    for r, row in enumerate(rows, 1):
        for c in range(4):
            if row[c] > row[c + 1] + 1e-9:
                problems.append(
                    f"regime={r}: size falls as signal strengthens "
                    f"(signal {c+1}={row[c]:.2f} > signal {c+2}={row[c+1]:.2f}) — "
                    f"more conviction must never mean less size")
                break

    # (2) regime ↑ (less familiar) → size ↓, down every signal column.
    for c in range(5):
        col = [rows[r][c] for r in range(5)]
        for r in range(4):
            if col[r] < col[r + 1] - 1e-9:
                problems.append(
                    f"signal={c+1}: size RISES as the regime becomes less familiar "
                    f"(regime {r+1}={col[r]:.2f} < regime {r+2}={col[r+1]:.2f}) — "
                    f"this is the 2026-08-12 inversion: max leverage at max "
                    f"unfamiliarity")
                break

    # (3) THE ONE THAT COSTS MONEY. The cell reached when both inputs are
    # missing must not lever up. Bands are quantised elsewhere; the contract
    # here is that whatever cell the missing-data path lands on is ≤ 1.0.
    nan_r = int(v.get("nan_regime_band", 3))
    nan_s = int(v.get("nan_signal_band", 1))
    if 1 <= nan_r <= 5 and 1 <= nan_s <= 5:
        nan_cell = rows[nan_r - 1][nan_s - 1]
        if nan_cell > 1.0 + 1e-9:
            problems.append(
                f"missing-data cell (regime={nan_r}, signal={nan_s}) = {nan_cell:.2f} > 1.0 "
                f"— no information must never produce leverage. The repo table "
                f"returned 1.20 here and the hook documented it as the baseline")

    # (4) Corners follow from (1)+(2) but are asserted directly: they are what
    # a human reads first, and the inverted table's corners were the tell.
    if rows[0][4] < rows[4][0] - 1e-9:
        problems.append(
            f"corner check: (in-distribution, strongest) = {rows[0][4]:.2f} is smaller "
            f"than (out-of-distribution, weakest) = {rows[4][0]:.2f} — the table is "
            f"transposed")

    if any(x > clip_max + 1e-9 for row in rows for x in row):
        problems.append(f"a cell exceeds size_clip_max={clip_max}")
    if any(x < 0 for row in rows for x in row):
        problems.append("negative size — this book is long-only (return hierarchy ①)")
    return problems


def _validate_c2_q(v: dict) -> list[str]:
    """C2 ⓠ overlay thresholds."""
    problems: list[str] = []
    try:
        enter = float(v["enter_q_zero_threshold"])
        exit_ = float(v["exit_q_zero_threshold"])
    except (KeyError, TypeError, ValueError):
        return ["enter_q_zero_threshold / exit_q_zero_threshold missing or non-numeric"]

    # Hysteresis: you must exit at a LOOSER level than you entered, or the
    # state machine chatters and turnover eats the sleeve.
    if exit_ >= enter:
        problems.append(
            f"exit ({exit_}) >= enter ({enter}) — with no hysteresis the state "
            f"flips daily and turnover cost decides the book, not the signal")
    gap = float(v.get("hysteresis_gap", 0.0))
    if gap > 0 and (enter - exit_) + 1e-9 < gap:
        problems.append(f"enter-exit gap {enter - exit_:.3f} < declared hysteresis_gap {gap}")

    dwell = int(v.get("dwell_days", 0))
    if dwell < 1:
        problems.append("dwell_days < 1 — a state with no minimum dwell is not a state")

    allowed = v.get("allowed_q") or []
    try:
        qs = [float(x) for x in allowed]
    except (TypeError, ValueError):
        return problems + ["allowed_q contains a non-numeric value"]
    if not qs:
        problems.append("allowed_q is empty")
    if any(q < 0 for q in qs):
        problems.append("allowed_q contains a negative exposure — long-only (①)")
    if any(q > 1.3 + 1e-9 for q in qs):
        problems.append("allowed_q exceeds 1.3 — the ① book's ceiling (S-137)")
    return problems


def _validate_investable(v: dict) -> list[str]:
    """Delegates to the universe module so the inclusion standard has ONE
    definition. A second copy here would drift, and the copy that drifts is
    always the one production uses."""
    from src.data.universe.investable import validate_investable
    return validate_investable(v)


_VALIDATORS: dict[str, Callable[[dict], list[str]]] = {
    NS_C3_SIZE: _validate_c3_size,
    NS_C2_Q: _validate_c2_q,
    NS_INVESTABLE: _validate_investable,
    NS_TRIPWIRE: lambda v: __import__(
        "src.data.universe.aum_tripwire", fromlist=["validate_tripwire"]
    ).validate_tripwire(v),
}


def validate(namespace: str, values: dict) -> list[str]:
    """Public entry — used by the loader AND by the preflight guard, so the
    rule that gates production is the same object the tests assert against."""
    fn = _VALIDATORS.get(namespace)
    if fn is None:
        return [f"no validator registered for namespace {namespace!r} — refusing to "
                f"trust an unvalidated parameter set"]
    try:
        return fn(values)
    except Exception as e:                      # a validator must never take the book down
        return [f"validator raised {type(e).__name__}: {e}"]


# ── Loading ──────────────────────────────────────────────────────────────────
def _fetch_active(namespace: str) -> tuple[dict, int] | None:
    """Highest active param_version for a namespace. None on any failure —
    unreachable config is a fallback, not an outage."""
    base = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not base or not key:
        return None
    try:
        import httpx
        url = (f"{base.rstrip('/')}/rest/v1/strategy_params"
               f"?select=param_version,payload&namespace=eq.{namespace}"
               f"&active=is.true&order=param_version.desc&limit=1")
        r = httpx.get(url, headers={"apikey": key, "Authorization": f"Bearer {key}"},
                      timeout=8.0)
        if r.status_code != 200:
            _log.warning("[params] %s fetch HTTP %s — using code fallback",
                         namespace, r.status_code)
            return None
        rows = r.json()
        if not rows:
            return None
        payload = rows[0].get("payload")
        if isinstance(payload, str):
            payload = json.loads(payload)
        if not isinstance(payload, dict):
            return None
        return payload, int(rows[0].get("param_version") or 0)
    except Exception as e:
        _log.warning("[params] %s fetch failed (%s) — using code fallback",
                     namespace, e)
        return None


_WARNED: set[str] = set()


def load(namespace: str, fallback: dict, fallback_version: int = 0) -> ParamSet:
    """Load the active parameter set, or the neutral in-code fallback.

    The fallback is deliberately NEUTRAL, not "the good values" — if the code
    carried the calibrated table, moving it to the database would have
    achieved nothing (reason 1), and a silent fallback would reproduce the
    edge without the record saying so (reason 2).
    """
    fetched = _fetch_active(namespace)

    if fetched is None:
        problems = validate(namespace, fallback)
        if problems and namespace not in _WARNED:
            _WARNED.add(namespace)
            _log.error("[params] %s: the IN-CODE FALLBACK itself violates its "
                       "invariants: %s", namespace, problems)
        return ParamSet(namespace, dict(fallback), fallback_version,
                        _CODE_FALLBACK, problems)

    payload, version = fetched
    problems = validate(namespace, payload)
    if problems:
        # Loud, every time — this is a config that would have mispriced risk.
        _log.error("[params] %s v%s REJECTED, falling back to code defaults. "
                   "Violations: %s", namespace, version, problems)
        return ParamSet(namespace, dict(fallback), fallback_version,
                        _DB_REJECTED, problems)

    return ParamSet(namespace, payload, version, _DB, [])
