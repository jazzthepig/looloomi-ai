"""Is the vector substrate still being written to? (S-216)

Jazz, 2026-08-24, defining the lane:「你要管好的是矢量数据库还有价值挖掘后,
系统工程打通风格平衡的 loop。」

So the object is not a table, it is a CURRENT. ARCHITECTURE.md: *the loop is
circulation, not a pipeline; the system is a metabolism; `loop_health` measures
whether the current still flows.* We built that instrument in July and then did
not point it at the VDB, which is how the following went unnoticed — measured
2026-08-24, by hand, because nothing was watching:

    asset_embeddings        72 rows      last written 2026-07-24   31 days stale
    market_state_vectors   582 rows      last written 2026-08-05   19 days stale
                                         regime_label populated on   0 of 582
    strategy_records          0 rows     never written
    experiment_runs          60 rows     dsr present on 2 of 60

Every one of those is my own completed build. Tasks "VDB 落库", "embedder v2",
"canonical strategy_embedder", "asset_edge_moments" all closed green. **I built
every stage of this loop and kept none of it flowing** — organs without a
metabolism, which is precisely the failure ARCHITECTURE.md names.

WHY STALENESS HERE IS INVISIBLE BY DEFAULT. `rebuild_asset_vectors`' own
docstring (S-144) says embeddings are written *as a side effect of the CIS cycle,
inside one broad `except Exception` that degrades to a log line*. A side effect
that fails silently inside a loop that otherwise succeeds produces exactly this:
green everywhere, a substrate frozen a month ago. The read path then returns rows
— just old ones — so no consumer errors either.

AND IT TAKES THE DECISION CHAIN WITH IT. MEMORY.md records the chain as
`market_state_vectors` → `similar_market_states()` → `strategy_response`. With
`regime_label` NULL on all 582 rows and the table 19 days behind, that chain
cannot run at all. Nothing reports an error, because nothing calls it.

This module answers one question per store — flowing / stale / empty — and never
collapses "empty" into "stale". A table that was never written is a build defect;
a table that stopped being written is an operational one, and they have different
owners and different fixes.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

#: Beyond this, the substrate is no longer describing the current market. Chosen
#: to be shorter than the shortest thing that consumes it: the daily CIS cycle.
STALE_AFTER_DAYS = 2

#: Per-store staleness budget. `experiment_runs` is event-driven — research lands
#: in bursts — so silence there is not the same signal as silence in a daily loop.
BUDGETS: dict[str, int] = {
    "asset_embeddings": 2,
    "market_state_vectors": 2,
    "strategy_records": 30,
    "experiment_runs": 14,
}

#: Columns that must be POPULATED, not merely present. A row whose distinguishing
#: field is NULL is the "score and grade fine, all five pillars NULL" shape (S-207)
#: one layer down: the row count looks healthy and the content is not there.
#:
#: Each entry is (column, minimum populated FRACTION). The fraction is not
#: decoration — the live probe's first run returned `experiment_runs: flowing,
#: dsr populated on 2/60`, and an exact-zero test passes that happily. 2 of 60 is
#: worse than 0 of 60: it looks like the field is in use. MEMORY.md states the
#: rule directly — 危害与可发现性成反比.
COMPLETENESS: dict[str, tuple[str, float]] = {
    "market_state_vectors": ("regime_label", 0.90),
    "experiment_runs": ("dsr", 0.50),
}


@dataclass(frozen=True)
class StoreHealth:
    store: str
    status: str          # "flowing" | "stale" | "empty" | "unknown"
    rows: int | None
    age_days: int | None
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return {"store": self.store, "status": self.status, "rows": self.rows,
                "age_days": self.age_days, "detail": self.detail}


def classify(store: str, rows: int | None, age_days: int | None,
             populated: int | None = None) -> StoreHealth:
    """Turn counts into a verdict. Pure — the SQL lives at the call site.

    `rows is None` means the query did not answer, which is NOT zero rows. That
    distinction has cost us four separate outages this month, so it is the first
    branch here rather than an afterthought.
    """
    if rows is None:
        return StoreHealth(store, "unknown", None, None,
                           "could not read — this is not the same as empty")
    if rows == 0:
        return StoreHealth(store, "empty", 0, None,
                           "never written — a build defect, not a stalled loop")

    budget = BUDGETS.get(store, STALE_AFTER_DAYS)
    if age_days is None:
        return StoreHealth(store, "unknown", rows, None,
                           "rows present but no timestamp column read")

    bits = [f"{rows} rows, {age_days}d old (budget {budget}d)"]
    status = "flowing" if age_days <= budget else "stale"

    spec = COMPLETENESS.get(store)
    if spec is not None and populated is not None:
        col, min_frac = spec
        frac = populated / rows if rows else 0.0
        bits.append(f"{col} populated on {populated}/{rows} ({frac:.0%}, need {min_frac:.0%})")
        if frac < min_frac:
            # Fresh rows with the distinguishing column mostly empty is worse than
            # stale rows: the loop looks alive AND the content consumers need is
            # absent. A handful of populated rows is the most dangerous case,
            # because it also defeats an is-it-ever-set check.
            status = "stale"
            bits.append(
                f"⚠ {col} is NULL on every row — anything keyed on it is dead"
                if populated == 0 else
                f"⚠ {col} is set on only {populated} rows — present enough to look "
                f"wired, sparse enough to be unusable")
    return StoreHealth(store, status, rows, age_days, "; ".join(bits))


async def vdb_health() -> dict[str, Any]:
    """Read every VDB store's freshness. Never raises."""
    from src.api.store import _SB_URL, _SB_KEY, _supabase_request_with_retry

    specs = [
        ("asset_embeddings", "computed_at", None),
        ("market_state_vectors", "d", "regime_label"),
        ("strategy_records", "created_at", None),
        ("experiment_runs", "ts", "dsr"),
    ]
    if not _SB_URL or not _SB_KEY:
        return {"ok": False, "reason": "no Supabase credentials",
                "stores": [classify(s, None, None).as_dict() for s, _, _ in specs]}

    import datetime as _dt
    today = _dt.datetime.now(_dt.timezone.utc).date()
    out: list[dict[str, Any]] = []

    for table, ts_col, comp_col in specs:
        sel = ts_col if comp_col is None else f"{ts_col},{comp_col}"
        url = (f"{_SB_URL}/rest/v1/{table}?select={sel}"
               f"&order={ts_col}.desc&limit=2000")
        try:
            r = await _supabase_request_with_retry(
                "GET", url, headers={"apikey": _SB_KEY,
                                     "Authorization": f"Bearer {_SB_KEY}"})
        except Exception:                                         # noqa: BLE001
            out.append(classify(table, None, None).as_dict())
            continue
        if r is None or r.status_code != 200:
            out.append(classify(table, None, None).as_dict())
            continue

        rows = r.json() if isinstance(r.json(), list) else []
        n = len(rows)
        age = None
        if rows:
            raw = str(rows[0].get(ts_col) or "")[:10]
            try:
                age = (today - _dt.date.fromisoformat(raw)).days
            except ValueError:
                age = None
        pop = (sum(1 for x in rows if x.get(comp_col) is not None)
               if comp_col else None)
        out.append(classify(table, n, age, pop).as_dict())

    worst = "flowing"
    for s in out:
        if s["status"] in ("empty", "unknown"):
            worst = "broken"
            break
        if s["status"] == "stale":
            worst = "stale"
    return {"ok": True, "overall": worst, "stores": out,
            "note": "empty ≠ stale ≠ unreadable; see module docstring"}
