"""
Research intake — the write path for lanes that hold no service_role key (S-164).

    POST /internal/research-intake          submit a batch
    GET  /internal/research-intake/schema   echo the contract (no auth on the echo)

Measured 2026-08-15: strategy_records and asset_embeddings have RLS on and ZERO
policies; experiment_runs has a SELECT-only policy. Every key except service_role
is refused, correctly and silently-by-design. Minimax-C was asked to land 172
mined artefacts down a path that was closed, and discovered it by collision,
because nothing said it was closed.

The service_role key is deliberately not shared with the mining lanes, so the
fix is not a key — it is this: one credential boundary (Railway), reached the
same way the Mac Mini engine already reaches /internal/cis-scores. The lane on
the other end learns no new concept.

WHAT THIS ENDPOINT WILL NOT DO. It will not accept a SHIP verdict. See
contracts/research_intake.py rule 3: a lane may submit evidence of any strength
and may not submit the conclusion, because the conclusion is what the discipline
suite earns over the committed record. An intake that accepted a pre-declared
verdict would be a route around the only gate we have.

HONEST FAILURE. A batch that writes nothing returns ok=false with reasons, and a
batch that writes some rows returns the rejected list alongside the accepted
count. There is no response shape in which a partial write reads as a success —
that is the failure mode that produced 80 days of a dead signal_outcomes
pipeline, and it is not being rebuilt here.
"""
from __future__ import annotations

import logging
import os
from fastapi import APIRouter, Header, HTTPException

from src.api.contracts.research_intake import (
    NATURAL_KEY,
    SCHEMA_VERSION,
    canonical_schema,
    normalize_research_payload,
)

router = APIRouter(tags=["internal"])
_log = logging.getLogger("research_intake")


def _token() -> str:
    # Read at call time, not import time: Railway rotates it, and a module-level
    # snapshot would keep authenticating against a value nobody can see.
    return os.getenv("INTERNAL_TOKEN", "")


def _drift_consequence(msplit: dict, rpc_missing: list, missing: list,
                       rpc_unknown: list | None = None) -> str:
    """把 drift 的 consequence 拼成一句**自洽**的话。纯函数,判据可直接调用。

    三种缺失**修法不同**,不能共用一句措辞(S-399):
      · `with_call_site`:src/ 有调用点而表没了 ⇒ 写入真的在被吞,补迁移;
      · `declared_only` :只在 `WRITES_TABLES` 声明过 ⇒ **这边没人写**,去问声明它的 lane。
        ⚠️ **不等于「没有写入者」** —— 声明机制存在的理由正是 AST 走查跟不进
        `cometcloud-local/`(实测六张 declared_only 里四张是活的);
      · `rpc_missing`   :函数不存在。

    **S-399b:全清子句曾经挂在 `with_call_site or rpc_missing` 上**,于是
    declared_only 非空而另两者为空时,**同一句话既报缺失又说「全都存在」**。
    那正是这整条守卫反对的东西,而我在修它的时候把它搬了进去。全清只能在**三者皆空**时出现。

    抽成纯函数是为了让判据能**调用**它 —— 上一版守卫想用正则去源码里读措辞,
    第一次取错窗口,第二次匹配不上。**按文本匹配而不是按结构,是同一个毛病。**

    ⚠️ S-354 那条保留:`rpc_unknown` 是「问不出来」,不是「不存在」——
    一个建立在错误事实上的完整因果故事,比一个错误的计数危险得多。
    """
    parts: list[str] = []
    if msplit["with_call_site"]:
        parts.append(
            f"{len(msplit['with_call_site'])} table(s) with a live call site in "
            f"src/ do not exist — every write returns False and is swallowed, "
            f"indistinguishable from 'no data yet'. ")
    if msplit["declared_only"]:
        parts.append(
            f"{len(msplit['declared_only'])} table(s) are DECLARED "
            f"(WRITES_TABLES) but have no call site in src/ — "
            f"**nothing here writes to them yet**, so this is a registered "
            f"intention, not a swallowed write. Whether an out-of-lane "
            f"(Mac-side) writer exists is NOT observable from here: check the "
            f"lane that declared it. ")
    if rpc_missing:
        parts.append(
            f"{len(rpc_missing)} RPC function(s) the code calls do not exist. ")
    if msplit["with_call_site"] or rpc_missing:
        parts.append("The sleeves depending on those tables have no forward "
                     "record and cannot start one.")
    if not (missing or rpc_missing):
        parts.append("every table the code writes to and every RPC it calls exists")
    if rpc_unknown:
        parts.append(f" ⚠️ catalog unreadable for {len(rpc_unknown)} RPC(s) — "
                     f"**that is 'we could not ask', not 'they are missing'**.")
    return "".join(parts)


@router.get("/internal/research-intake/schema")
async def research_intake_schema():
    """Unauthenticated on purpose. The submitting lane does not have this repo
    checked out, and a contract you must hold a credential to READ is a contract
    that gets guessed at. It describes shape only — no data, no secrets."""
    return canonical_schema()


@router.get("/internal/schema-drift")
async def schema_drift(x_internal_token: str = Header(None, alias="X-Internal-Token")):
    """The ONLINE half of the schema guard (S-166 + A-29) — does every table
    the code writes to AND every RPC function the code calls actually exist?

    Measured 2026-08-15: ELEVEN tables did not, including both C2 and C3
    sleeve NAV tables, while PROJECT_STATE read "C2 ⓠ + C3 size complete;
    79/79 smoke green". Green tests, and nowhere to write a row. Measured
    2026-09-14 (A-29): the same drift probe flagged 7 RPC function names as
    MISSING TABLES, because the offline walker could not tell a function call
    from a table write. Both halves of the probe now exist.

    preflight cannot answer this — it is offline by contract (S-163), and that
    is the right trade. This process has the credentials, so this is where the
    question belongs. The deploy-verifier calls it after every push.

    Authenticated: the table list is architecture, and CLAUDE.md #8 keeps
    internals off surfaces a competitor reads.
    """
    tok = _token()
    if not tok or not x_internal_token or x_internal_token != tok:
        raise HTTPException(status_code=401, detail="Invalid token")

    import json
    from src.api.schema_manifest import manifest_path

    try:
        manifest = json.loads(manifest_path().read_text())
    except Exception as e:                            # noqa: BLE001
        return {"ok": False, "error": f"manifest unreadable: {type(e).__name__}: {e}",
                "note": "regenerate with tests/test_every_written_table_exists.py"}

    expected_tables = sorted(manifest.get("write_tables") or [])
    expected_rpcs = sorted(manifest.get("rpc_functions") or [])

    from src.api.rpc_diagnostics import rpc_with_detail
    from src.api.store import (
        supabase_function_exists, supabase_missing_columns, supabase_table_exists,
    )
    live, unknown = [], []
    for t in expected_tables:
        got = await supabase_table_exists(t)
        (live if got is True else unknown).append(t)

    missing = [t for t in unknown]

    # ── S-399:把「缺失」按来源拆开,**不在最后一步塌成一个数** ─────────────
    # 2026-09-22 这个端点对 nav_panel_daily / nav_panel_rebalances 报了
    # 「the code writes to ... Every write returns False and is swallowed」——
    # 而 src/ 里没有任何调用点写它们,它们只在
    # `c13_nav_panel_manifest.WRITES_TABLES` 的声明里。**那句话在描述一批
    # 不存在的吞掉的写入**,会把人送去找不存在的 False(实测:一条 lane
    # 因此被派去修一个不存在的 writer)。
    #
    # 与 S-354 同一处伤口的另一支:那次 RPC 探针把「读不到」说成「缺失」,
    # 修法就写在本文件 `rpc_check_unavailable` 上面 ——「三值一路带到输出,
    # 绝不在最后一步塌成两值」。**RPC 支修了,表支没修,而两支在同一个表达式里。**
    try:
        from src.api.schema_manifest import write_tables_by_provenance
        _prov = write_tables_by_provenance()
        _declared_only = set(_prov["declared_only"])
    except Exception:                                             # noqa: BLE001
        # 拿不到来源 ⇒ 不假装知道。全部按「有调用点」报(保守:那一支的措辞更严厉)。
        _declared_only = set()
    _msplit = {
        "with_call_site": [t for t in missing if t not in _declared_only],
        "declared_only": [t for t in missing if t in _declared_only],
    }

    # ── RPC FUNCTIONS (A-29, probe corrected S-354) ──────────────────────────
    # Same drift class as tables. But **existence is a CATALOG question, not a
    # call question** — and probing by calling produced the same false P0 three
    # separate times for the same three functions:
    #
    #   panel_closes / panel_funding / exec_backfill_forward_returns
    #
    # All three exist and return real data. PostgREST resolves RPCs by ARGUMENT
    # NAME, so POSTing `{}` to a function with a required parameter answers
    # PGRST202 — "no overload matches these argument names", NOT "no such
    # function". Measured 2026-09-15: **128 of this project's 148 functions have
    # a required argument**, so the call-probe would report 128 as missing.
    #
    # ⚠️ And the consequence text built on top of it was worse than the wrong
    # flag: "every write to them returns False and is swallowed — the sleeves
    # have no forward record and cannot start one." A complete causal story on a
    # false premise, pointing at rewriting functions that work.
    #
    # `catalog_inventory()` (S-350) reads pg_proc in one round trip. It was built
    # for exactly this and then left unwired — the report got fixed, the probe
    # did not.
    rpc_live, rpc_unknown, rpc_missing = [], [], []
    _cat, _cat_detail = await rpc_with_detail("catalog_inventory", {})
    if isinstance(_cat, list):
        _known = {r.get("name") for r in _cat
                  if isinstance(r, dict) and r.get("kind") == "function"}
        for fn in expected_rpcs:
            (rpc_live if fn in _known else rpc_missing).append(fn)
    else:
        # **Unreadable catalog is NOT "everything is missing".** Three values,
        # kept apart all the way to the output (S-350: `unknown` renamed to
        # `missing` two lines below its own docstring is how this started).
        rpc_unknown = list(expected_rpcs)

    # ── COLUMNS, not only tables (S-286) ────────────────────────────────────
    # This endpoint was built for S-166, where eleven TABLES were missing, and it
    # inherited that incident's scope. On 2026-09-04 the ① book went dark on a
    # missing COLUMN of a table that existed: `interval_hours`, code deployed
    # ahead of its migration. Every insert 400'd, `_write` returned False, the
    # book stopped, and this endpoint said ok — truthfully, about the wrong
    # question. **Coverage that answers a narrower question than the one you have
    # reads as coverage.**
    #
    # Only tables that exist are probed: asking which columns a missing table
    # lacks produces noise that buries the real finding.
    try:
        expected_cols = json.loads(manifest_path().read_text()).get("write_columns", {})
    except Exception:                                 # noqa: BLE001
        expected_cols = {}
    col_drift, col_unknown = {}, []
    for t in live:
        cols = expected_cols.get(t) or []
        if not cols:
            continue
        got = await supabase_missing_columns(t, cols)
        if got is None:
            col_unknown.append(t)                     # could not tell ≠ missing
        elif got:
            col_drift[t] = got


    # ── S-399c:列这一半也按来源拆 ──────────────────────────────────────
    # 表拆了、列没拆,于是 `market_state_vectors` 那三列(和那两张表同一个
    # 不存在的 Mac 侧写入端)继续让 `schema_drift_check` 退出 1 ——
    # 而 preflight 是 `|| exit 1`、handoff 是 `&&` 链,**所有 push 被挡住**,
    # 挡住的理由是一批没有任何人写的列。**「修了一半」这次发生在同一批改动里。**
    try:
        from src.api.schema_manifest import write_columns_by_provenance
        _cprov = write_columns_by_provenance()["declared_only"]
        _col_declared_only = {
            t: [c for c in cols if c in set(_cprov.get(t, []))]
            for t, cols in col_drift.items()
            if [c for c in cols if c in set(_cprov.get(t, []))]
        }
    except Exception:                                             # noqa: BLE001
        _col_declared_only = {}   # 拿不到来源 ⇒ 不假装知道,全部按「有调用点」
    return {
        # `rpc_unknown` 不参与 ok —— **读不到不是坏,但也不是好**,
        # 它单独出现在 rpc_check_unavailable 里让人看见。
        "ok": not missing and not col_drift and not rpc_missing,
        # WHICH CHECKS THIS BUILD RUNS. Without it, `column_drift: null` from a
        # deploy that predates the column check is indistinguishable from
        # `column_drift: {}` on a clean one — Jazz hit exactly this on 2026-09-04
        # and neither of us could tell "not deployed" from "nothing wrong" without
        # reading git. A response that cannot say what it checked forces the reader
        # to know the build, and that knowledge is exactly what an echo exists to
        # remove.
        "checks": ["tables", "rpc_functions", "columns"],
        "checked": len(expected_tables),
        "present": len(live),
        "missing": missing,
        "rpc_checked": len(expected_rpcs),
        "rpc_present": len(rpc_live),
        "rpc_missing": rpc_missing,
        # S-354:读不到目录 ≠ 全部缺失。三值一路带到输出,绝不在最后一步塌成两值。
        "rpc_check_unavailable": rpc_unknown,
        "column_drift": col_drift,
        # S-399c:列这一半也按来源拆 —— 表拆了列没拆,于是
        # `market_state_vectors` 那三列(同一个不存在的 Mac 侧写入端)
        # 继续让 `schema_drift_check` 退出 1,**挡住所有 push**。
        "column_drift_declared_only": _col_declared_only,
        "column_drift_with_call_site": {
            t: [c for c in cols if c not in set(_col_declared_only.get(t, []))]
            for t, cols in col_drift.items()
            if [c for c in cols if c not in set(_col_declared_only.get(t, []))]
        },
        "column_check_unavailable": col_unknown,
        "column_consequence": (
            "code writes column(s) the live table does not have. PostgREST answers "
            "400, the insert helper returns False, and the writer logs one line and "
            "stops — the table simply stops growing, which reads as 'no data yet'. "
            "Almost always a deploy that outran its migration."
            if col_drift else "every column the code writes exists"),
        # Naming the consequence, not just the count. "3 missing" reads like a
        # config nit; "these sleeves cannot persist anything" is the actual fact.
        # S-399:表这一支曾经和 RPC 那一支犯同一个错 —— 见下面 `_missing_split`。
        "missing_with_call_site": _msplit["with_call_site"],
        "missing_declared_only": _msplit["declared_only"],
        "consequence": _drift_consequence(
            _msplit, rpc_missing, missing, rpc_unknown),
    }


@router.post("/internal/research-intake")
async def receive_research_batch(
    payload: dict,
    x_internal_token: str = Header(None, alias="X-Internal-Token"),
):
    tok = _token()
    # Reject by default: a missing env var must fail closed, not open.
    if not tok or not x_internal_token or x_internal_token != tok:
        raise HTTPException(status_code=401, detail="Invalid token")

    report = normalize_research_payload(payload)

    if report["fatal"]:
        # 400, not 422: the envelope itself is wrong, and the lane needs to see
        # the schema. Point at it rather than describing it.
        raise HTTPException(status_code=400, detail={
            "fatal": report["fatal"],
            "schema": "GET /internal/research-intake/schema",
        })

    table = report["table"]
    rows = report["rows"]
    written = False

    if rows:
        from src.api.store import supabase_upsert_table
        written = await supabase_upsert_table(
            table, rows, on_conflict=NATURAL_KEY[table]
        )
        if not written:
            # The role gate or Supabase declined. Say which is possible, and do
            # NOT report accepted rows — nothing landed.
            _log.warning("[INTAKE] %s: %d normalized rows were NOT written",
                         table, len(rows))
            return {
                "ok": False,
                "schema_version": SCHEMA_VERSION,
                "table": table,
                "batch_id": report["batch_id"],
                "accepted": 0,
                "normalized_but_unwritten": len(rows),
                "rejected": report["rejected"],
                "warnings": report["warnings"],
                "diagnosis": (
                    "rows normalized cleanly but the write was declined. Either this "
                    "process is not APP_ROLE=production (replicas may not write the "
                    "shared record), or Supabase rejected the upsert. Check the "
                    "deployment log for [ROLE] or [SUPABASE]."),
            }

    for w in report["warnings"]:
        _log.info("[INTAKE] %s", w)
    for r in report["rejected"]:
        _log.warning("[INTAKE] rejected: %s", r)

    _log.info("[INTAKE] %s ← lane=%s batch=%s accepted=%d rejected=%d",
              table, report["source_lane"], report["batch_id"],
              len(rows), len(report["rejected"]))

    return {
        "ok": bool(rows),
        "schema_version": SCHEMA_VERSION,
        "table": table,
        "source_lane": report["source_lane"],
        "batch_id": report["batch_id"],
        "accepted": len(rows),
        "rejected": report["rejected"],
        "warnings": report["warnings"],
        "idempotent_on": NATURAL_KEY[table],
        "note": ("resubmitting this batch_id with the same row keys is safe and is "
                 "the intended retry behaviour"),
    }
