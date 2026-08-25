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


#: ⚠️ THE PROBE MUST QUERY THE WAY THE CONSUMER QUERIES (S-225, 2026-08-24).
#:
#: `asset_embeddings` held 72 rows and this module cheerfully reported "72 rows,
#: 31d old". The read path in `pgvector_store` filters
#: `schema_version=eq.3 & superseded_reason=is.null`, and every stored row is
#: `schema_version = 2` — written before the v3 bump on 2026-08-09 and never
#: rewritten. **Readable rows: zero.** The vector layer has been fully dark for
#: two weeks while the freshness probe reported a merely stale table.
#:
#: A count over a SUPERSET of what consumers can see is not a health metric; it
#: is the same false comfort as a NAV that is flat because nothing was priceable.
#: So each store carries the consumer's own filter, and the probe reports
#: `readable_rows` next to `rows` — when they differ, that gap IS the finding.
READ_FILTERS: dict[str, str] = {
    "asset_embeddings": "&schema_version=eq.{schema_version}&superseded_reason=is.null",
}


def _embedder_contract() -> tuple[int, int]:
    """(SCHEMA_VERSION, 该版本承诺的维度)。一个版本号是一个关于形状的承诺。"""
    from src.data.vector.embedder import SCHEMA_VERSION, ASSET_DIMS_V2
    return SCHEMA_VERSION, ASSET_DIMS_V2


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
        h = classify(table, n, age, pop).as_dict()

        # How many of those rows can a CONSUMER actually see? See READ_FILTERS.
        filt = READ_FILTERS.get(table)
        if filt and n:
            try:
                SCHEMA_VERSION, _ = _embedder_contract()
                rurl = (f"{_SB_URL}/rest/v1/{table}?select={ts_col}"
                        + filt.format(schema_version=SCHEMA_VERSION) + "&limit=2000")
                rr = await _supabase_request_with_retry(
                    "GET", rurl, headers={"apikey": _SB_KEY,
                                          "Authorization": f"Bearer {_SB_KEY}"})
                readable = len(rr.json()) if (rr is not None and rr.status_code == 200
                                              and isinstance(rr.json(), list)) else None
            except Exception:                                     # noqa: BLE001
                readable = None
            h["readable_rows"] = readable

            # 形状分布,不是聚合 (S-226/S-227)。今天 13:30 写入的 58 行里,
            # 35 行是 dims=18 而 schema_version=3 —— 而 v3 的含义是 27 维。
            # 18 维和 27 维不是同一个向量空间,把它们混在一张被相似度检索读的表里
            # 没有意义,而【任何单一聚合都看不见这件事】:行数一样、版本一样、
            # 新鲜度一样。S-144 当初隔离的理由原话就是"dims 18 和 27 同时存在于
            # version 2 之下" —— 同一件事正在 version 3 下重演。
            try:
                surl = (f"{_SB_URL}/rest/v1/{table}?select=dims,schema_version&limit=2000")
                sr = await _supabase_request_with_retry(
                    "GET", surl, headers={"apikey": _SB_KEY,
                                          "Authorization": f"Bearer {_SB_KEY}"})
                if sr is not None and sr.status_code == 200:
                    shape: dict[str, int] = {}
                    for x in sr.json():
                        k = f"v{x.get('schema_version')}/{x.get('dims')}d"
                        shape[k] = shape.get(k, 0) + 1
                    h["shape_distribution"] = shape
                    if len(shape) > 1:
                        h["detail"] += f"; MIXED SHAPES {shape} — one table, several vector spaces"

                    # ⚠️ 均匀且错误,比混合更隐蔽 (S-229)。上一版只查「形状是否混合」——
                    # 那是我刚看见的那个病例,不是要守的性质。部署后实测:58 行全部
                    # `v3/18d` 统一,`len(shape) > 1` 为假,于是【什么都不报】,而 v3
                    # 的含义是 27 维。**缺的 9 维正是 v3 存在的理由**(deltas 5 +
                    # stability 2 + risk moments 2)。
                    #
                    # 一个版本号是一个关于形状的承诺。承诺必须对着它承诺的东西查,
                    # 不是对着"上次出问题的样子"查。
                    # 两个名字都在函数顶部导入(见 _embedder_contract),不在这里 ——
                    # 上一版把 SCHEMA_VERSION 的导入放在另一个 try 里,若那个 try
                    # 先失败,这里就是 NameError,而它会被本块的 except 吞掉:
                    # 一个静默失效的守卫,和没有守卫读起来一模一样。
                    SCHEMA_VERSION, ASSET_DIMS_V2 = _embedder_contract()
                    wrong = {k: v for k, v in shape.items()
                             if k.startswith(f"v{SCHEMA_VERSION}/")
                             and k != f"v{SCHEMA_VERSION}/{ASSET_DIMS_V2}d"}
                    if wrong:
                        h["expected_shape"] = f"v{SCHEMA_VERSION}/{ASSET_DIMS_V2}d"
                        h["wrong_shape_rows"] = sum(wrong.values())
                        h["status"] = "stale"
                        h["detail"] += (
                            f"; ⚠ {sum(wrong.values())} rows stamped v{SCHEMA_VERSION} "
                            f"carry {sorted(wrong)} but v{SCHEMA_VERSION} means "
                            f"{ASSET_DIMS_V2}d — the v2 inputs (prior_pillars / "
                            f"pillar_history / edge_moments) are not reaching the "
                            f"embedder, so every vector is missing the dimensions "
                            f"this version exists for")
            except Exception:                                     # noqa: BLE001
                pass

            if readable == 0:
                # Rows present, none visible to the consumer. Strictly worse than
                # stale: stale data still answers a query.
                h["status"] = "unreadable"
                h["detail"] = (f"{n} rows stored but 0 pass the consumer's filter "
                               f"({filt.strip('&')}) — the layer is DARK, not merely "
                               f"stale; a count over a superset is not a health metric")
            elif readable is not None and readable < n:
                h["detail"] += f"; readable {readable}/{n}"
        out.append(h)

    # ⚠️ RLS RETURNS 200 AND AN EMPTY LIST, NOT AN ERROR (S-220 follow-up).
    # All four tables have RLS on with ZERO policies, so a non-service key reads
    # every one of them as empty. `rows == 0` therefore cannot, on its own,
    # distinguish "never written" from "not visible to this credential" — and
    # this probe would confidently report four independent build defects.
    #
    # One table empty is a build defect. FOUR empty at once is one credential.
    # The joint pattern carries information no single reading does, which is why
    # the cross-check lives here and not in classify().
    if out and all(s["status"] == "empty" for s in out):
        for s in out:
            s["status"] = "unknown"
            s["detail"] = ("all four stores read empty at once — RLS is on with 0 "
                           "policies on each, so this is one credential problem, "
                           "not four build defects")
        return {"ok": True, "overall": "unknown", "stores": out,
                "note": "every store empty ⇒ suspect the key, not the writers"}

    worst = "flowing"
    for s in out:
        if s["status"] in ("empty", "unknown", "unreadable"):
            worst = "broken"
            break
        if s["status"] == "stale":
            worst = "stale"
    return {"ok": True, "overall": worst, "stores": out,
            "note": "empty ≠ stale ≠ unreadable; see module docstring"}
