"""
Which tables the code writes to — extracted from the source, not remembered (S-166).

THE BUG THIS CLASS KEEPS PRODUCING. Measured 2026-08-15 against the live DB:
ELEVEN tables that live code writes to did not exist.

    beta_core_nav_q, beta_core_nav_q_meta          C2 ⓠ sleeve
    beta_core_nav_size, beta_core_nav_size_meta    C3 size sleeve
    strategy_params                                S-151
    execution_intents, execution_outcomes          S-155
    fusion_paper_nav, fusion_paper_lifecycle
    crowd_clock_log

PROJECT_STATE's own header read "C2 ⓠ + C3 size + C5 episode-code complete;
79/79 smoke green" — green tests, and no table to write a single row into. The
sleeves had never persisted anything and never could.

AND WE ALREADY KNEW. OPEN RISK #3(a) has said since 2026-07-26: "A table that
was never created. scripts/supabase_strategy_records.sql ... was never applied.
`_pg_upsert()` POSTed to a nonexistent table, caught the exception, logged one
WARNING, returned False". That risk was written down, the lesson was recorded,
and it then happened eleven more times — because what got fixed was that one
table, not the fact that nothing compares the set of tables the code writes
against the set that exists.

WHY THE EXISTING GUARD MISSED IT, in its own words. tests/test_table_columns_
match_the_code.py: "That catches code-vs-declared drift. It does NOT catch
declared-vs-live drift — only the live catalog can, and preflight is offline by
contract. So ... scripts/verify_live_schema.sql is the online half."

The gap was known, documented, and handed to a .sql file somebody has to
remember to run. That file's own founding argument is that a rule nobody
enforces is a wish, applied here to its own escape hatch. Nobody ran it.

THE SPLIT, and why it is two halves rather than one check. preflight must stay
offline (S-163: credentials in the gate are what made it slow and
machine-dependent). So:

    offline, in preflight   — this manifest matches what the source actually does
    online, post-deploy     — the live catalog matches this manifest

Neither half can pass vacuously. A stale manifest fails the offline half; a
missing table fails the online half. Deleting the manifest fails both.

EXTRACTED, NOT DECLARED. A hand-maintained list is a list that drifts, and drift
is the thing being guarded. This walks the AST and the literals, so adding a
`supabase_insert_table("new_thing", ...)` puts new_thing in the manifest on the
next run whether or not the author thought about it.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]

# Call sites that mean "this string is a table we write to" vs "this string
# is an RPC function we call". The two are SEPARATE catalogs because they
# answer different drift questions:
#
#   write_tables  → "does this table exist in Postgres?"     (S-166 / S-286)
#   rpc_functions → "does this function exist in Postgres?"  (A-29)
#
# Conflating them was the S-342 bug S-342 itself could not see: the
# suffix `_with_detail` matches both `insert_with_detail` (writes a row) and
# `rpc_with_detail` (calls a Postgres function). Both landed in `write_tables`,
# so `panel_funding` / `panel_closes` / `deep_panel_symbol_list` /
# `refresh_depth_divergence` / `resolve_depth_divergence` were all marked as
# MISSING TABLES when the drift probe ran on 2026-09-14 — they are missing
# TABLES, but present as FUNCTIONS, and the offline walker could not tell
# which side of the suffix they were on.
#
# ⚠️ S-330:这张表本身是一个**手写枚举**,所以它会随着写入函数的演化而失明。
# 2026-09-11 实测:`beta_core._write()` 从 `supabase_insert_table` 改到
# `insert_with_detail`(为了把状态码和 PostgREST body 带回心跳,S-329),
# 于是扫描器**看不见 `beta_core_nav` 被写入了**,preflight 立刻报
# 「manifest lists nothing the source no longer writes」。
#
# 那条报警是对的,但它描述的是症状。真正的事实是:
# **一个「哪些函数算写入」的清单,和它所守护的代码是分开演化的** ——
# 换一个写入函数,覆盖面就静默地少一块,而少的那一块恰恰是新代码。
#
# 加新写入函数时必须同时加到这里。`test_every_written_table_exists` 两半
# (离线 manifest + 线上 schema-drift)都建立在这张表之上。
_TABLE_WRITE_EXACT = frozenset({
    # S-328/S-329 write path — same semantics as supabase_insert_table, returns
    # (ok, detail) so the failure reason reaches the heartbeat instead of a
    # log line nobody reads.
    "insert_with_detail",
    # S-342 catch-up: production callers exist at
    # factor_tilt_paper.py:493 + pod_aggregator_paper.py:411, but the prior
    # hand-maintained set did not list the writer. Table is reached via the
    # NAV_TABLE module constant, see _CONST_RX below.
    "write_nav_row",
})
_TABLE_WRITE_SUFFIX = (
    # Pattern A — table-as-args[0] (AST walker 直接摘 args[0]):
    "_insert_table",
    "_insert_batch",
    "_upsert_table",
    "_delete_table",
    # NOTE: `_rpc_write` is NOT here. Its first arg is a Postgres FUNCTION
    # name, not a table. The S-342 regex treated it as table-write — A-29
    # splits it into _RPC_SUFFIX below. See _is_table_write_name docstring.
)

# Functions whose first string arg is a Postgres FUNCTION name (not a table).
# The drift probe checks these against `pg_proc`, not `pg_class`.
_RPC_EXACT = frozenset({
    # S-323m read path — returns (rows, detail) so failure reason reaches
    # the heartbeat (S-323 family). Distinct from `_rpc_write` (writer).
    "rpc_with_detail",
})
_RPC_SUFFIX = (
    # Pattern B — write-RPC: same signature as supabase_rpc (function name +
    # payload), but role-gated and returns (ok, reason) tuple (S-169). It is
    # STILL an RPC call: the function name must exist in Postgres for the call
    # to land anywhere. Putting `_rpc_write` here, not in table-write, is the
    # A-29 split that fixes the S-342 conflation.
    "_rpc_write",
)


def _is_table_write_name(name: str | None) -> bool:
    """S-342 + A-29: classify a call name as a table write.

    A function is a table-write iff its name ENDS with a structural-suffix
    token (``_insert_table``, ``_insert_batch``, ``_upsert_table``,
    ``_delete_table``), OR equals ``insert_with_detail`` or
    ``write_nav_row``.

    End-anchoring prevents over-matching: ``def _validate_insert_table_safe(...)``
    does NOT count because its suffix is ``_safe``, not ``_insert_table``.

    The split from ``_is_rpc_call_name`` is the S-342 bugfix: ``_with_detail``
    is ambiguous between ``insert_with_detail`` (table) and ``rpc_with_detail``
    (function), and ``_rpc_write`` is a write-RPC (function name in args[0])
    rather than a table writer — both are RPC calls (the function must exist
    in Postgres), so each is listed EXACTLY on the side it belongs.
    """
    if not name:
        return False
    if name in _TABLE_WRITE_EXACT:
        return True
    if name in _RPC_EXACT or any(name.endswith(s) for s in _RPC_SUFFIX):
        return False
    return any(name.endswith(s) for s in _TABLE_WRITE_SUFFIX)


def _is_rpc_call_name(name: str | None) -> bool:
    """A-29: classify a call name as an RPC function call (not a table write).

    Two shape classes:
      - ``rpc_with_detail`` (read RPC, S-323m)
      - any function whose name ends with ``_rpc_write`` (write RPC, S-169)

    Both kinds take a Postgres function name as their first string arg,
    which is the same shape that makes the manifest's tables-in / rpcs-in
    walkers work without per-call metadata. Adding ``rpc_with_timeout`` or
    ``rpc_read_with_detail`` here is a one-line change at the call-site
    declaration, not a search-and-replace through the project.
    """
    if not name:
        return False
    if name in _RPC_EXACT:
        return True
    return any(name.endswith(s) for s in _RPC_SUFFIX)


# Backward-compat alias for tests that pin the canonical writer set. The
# S-330/S-342 evolution was: literal set (S-330, stale-by-design) → suffix
# predicate (S-342, drift-by-rename). A-29 splits the predicate into
# table-write vs rpc-call. The literal set stays as a SANITY CHECK that the
# predicate hasn't quietly grown past what the docs say (test_a_book_asks...
# uses this). If a real writer appears that's NOT in this set, that's a
# legitimate signal — and the predicate already caught it via the AST walk.
_WRITE_FUNCS = frozenset({
    "supabase_insert_table",
    "supabase_upsert_table",
    "supabase_delete_table",
    "insert_with_detail",
    "write_nav_row",
    "supabase_insert_batch",
    "supabase_rpc_write",
})

# `_TABLE = "foo"` / `_NAV_TABLE = "foo"` module constants.
#
# TABLE must be its own underscore-delimited word. The first version of this
# regex matched TABLE as a substring and picked up `NS_INVESTABLE = "investable_v1"`
# — INVES-TABLE — putting a namespace string into the list of tables that must
# exist in Postgres. Funny, and exactly the failure mode this file exists to
# stop: a check that reports something confidently because it pattern-matched
# rather than understood. A guard with false positives gets muted, and a muted
# guard is worse than no guard, because it also occupies the slot where a real
# one would have gone.
#
# Done in two steps rather than one clever regex. The first attempt at a fix
# over-corrected and stopped matching `_TABLE = "..."` itself — a guard that
# silently narrows is the same hazard as one that over-matches, just quieter.
# Capture the name, then decide with plain Python that can be read at a glance.
_CONST_RX = re.compile(r"^(_?[A-Z][A-Z0-9_]*)\s*=\s*[\"']([a-z0-9_]+)[\"']", re.M)


def _names_a_table(const_name: str) -> bool:
    """TABLE must be a whole underscore-delimited word, so INVESTABLE is out."""
    return "TABLE" in const_name.strip("_").split("_")

# Directories whose writes are real production writes. `src/research/**` is
# excluded ON PURPOSE: those are one-off study scripts, they are run by hand,
# and a study that fails loudly on a missing table costs one person one minute.
# Including them would flood the manifest with tables nobody deployed, and a
# noisy guard is a guard people learn to skip.
_PROD_DIRS = ("src/api", "src/data", "src/mcp", "src/research/validation")

# Not a table. Vendored dependencies, virtualenvs, caches.
_SKIP = ("__pycache__", "/.venv/", "site-packages", "/node_modules/")


def _is_prod(p: Path) -> bool:
    rel = str(p.relative_to(_ROOT)).replace("\\", "/")
    return rel.startswith(_PROD_DIRS) and not any(s in f"/{rel}" for s in _SKIP)


def _tables_in(path: Path) -> set[str]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return set()
    found: set[str] = set()

    # 1. Module constants.
    found.update(v for name, v in _CONST_RX.findall(text) if _names_a_table(name))

    # 2. Write-helper call sites. AST, not regex: a table name inside a comment
    #    or a docstring is documentation, not a write, and the whole point of
    #    this file is to stop confusing what is written down with what runs.
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return found
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = getattr(fn, "id", None) or getattr(fn, "attr", None)
        # S-342 + A-29: predicate splits table-write from rpc-call. Detection
        # by structural suffix (intent), not enumeration, so a renamed writer
        # automatically stays in the manifest's scan (S-330 shape: stop).
        if not _is_table_write_name(name) or not node.args:
            continue
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            found.add(first.value)
        # A non-literal first arg (a variable, an f-string) is invisible here.
        # That is a known blind spot, recorded rather than papered over: a
        # dynamic table name cannot be checked statically, and pretending
        # otherwise would make the manifest look more complete than it is.
    return found


def _rpcs_in(path: Path) -> set[str]:
    """RPC function names this file calls. Mirrors ``_tables_in`` shape (A-29)."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return set()
    found: set[str] = set()
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return found
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = getattr(fn, "id", None) or getattr(fn, "attr", None)
        if not _is_rpc_call_name(name) or not node.args:
            continue
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            found.add(first.value)
    return found


#: 注入式写入者自报的表 (S-304)。
#:
#: ⚠️ **`_tables_in` 看不见注入式写入。** 它找的是字面的
#: `supabase_upsert_table("t", ...)`,而为了可离线测试,本仓库的几个 writer
#: 把写入函数作为参数注入(`supabase_upsert(table, rows, on_conflict)`),
#: 于是表名在调用点是一个**参数**,AST 看不到它是哪张表。
#:
#: 2026-09-05 实测后果:`treasury_entities` / `treasury_decisions` /
#: `corporate_treasury_history` **三张每天都在写的表从 S-292 起就不在清单里**,
#: 而清单守卫一直是绿的。**我为了可测性用的注入,把清单守卫打瞎了。**
#:
#: 推断在这里靠不住,所以改成**声明**:注入式写入者在模块级写
#: `WRITES_TABLES = ("t1", "t2")`,这里读它。声明会漏(有人忘了写),
#: 但漏了是**沉默的已知缺口**,而推断漏了是**看起来完整的清单**——
#: 后者更糟,因为它会变成人们信任的东西。
_DECLARED = "WRITES_TABLES"


def _declared_tables_in(path: Path) -> set[str]:
    """模块级 `WRITES_TABLES = (...)` 里声明的表名。"""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError):
        return set()
    out: set[str] = set()
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        names = {getattr(t, "id", None) for t in node.targets}
        if _DECLARED not in names:
            continue
        for el in getattr(node.value, "elts", []):
            if isinstance(el, ast.Constant) and isinstance(el.value, str):
                out.add(el.value)
    return out


def write_tables() -> list[str]:
    """Every table name a production module writes to. Sorted, deduped.

    两条来源:AST 推断出的字面调用,加上注入式写入者的显式声明。

    ⚠️ **这个函数把两条来源合并,而合并会丢掉下游需要的区别** ——
    见 `write_tables_by_provenance()`。保留它是因为「清单」这个用途不关心来源。
    """
    out: set[str] = set()
    for p in sorted(_ROOT.rglob("*.py")):
        if _is_prod(p):
            out |= _tables_in(p)
            out |= _declared_tables_in(p)
    return sorted(t for t in out if t and not t.startswith("_"))


def write_tables_by_provenance() -> dict[str, list[str]]:
    """同一份清单,但**不在最后一步塌成一个集合**。

    `{"with_call_site": [...], "declared_only": [...]}`

    **为什么要分开(S-399):** `/internal/schema-drift` 的那句 consequence 写的是
    「N table(s) **the code writes to** do not exist. Every write to them returns
    False and is swallowed」。2026-09-22 它对 `nav_panel_daily` /
    `nav_panel_rebalances` 报了这句 —— 而 `src/` 里**没有任何调用点**写这两张表,
    它们只出现在 `c13_nav_panel_manifest.WRITES_TABLES` 的声明里。
    **于是那句话在描述一个不存在的吞掉的写入**,会把人送去找一批不存在的 False。

    这和 S-354 是同一处伤口的另一支:那次是 RPC 探针把「读不到」说成「缺失」,
    修法写在本文件上游 ——「**三值一路带到输出,绝不在最后一步塌成两值**」。
    **RPC 那一支修了,表这一支没修**,而两支在同一个表达式里。

    ⚠️ **`declared_only` 不等于「没有写入者」。** 显式声明这个机制存在的理由,
    正是 AST 走查跟不进 `cometcloud-local/`(规则 3)。所以它只说明
    **「从 `src/` 看不到调用点」** —— 写入者在不在,要去声明它的那条 lane 看。
    **读不到 ≠ 不存在**(I1)。
    """
    ast_seen: set[str] = set()
    declared: set[str] = set()
    for p in sorted(_ROOT.rglob("*.py")):
        if _is_prod(p):
            ast_seen |= _tables_in(p)
            declared |= _declared_tables_in(p)
    clean = lambda s: sorted(t for t in s if t and not t.startswith("_"))
    return {
        "with_call_site": clean(ast_seen),
        "declared_only": clean(declared - ast_seen),
    }


def rpc_functions() -> list[str]:
    """Every RPC function a production module calls. Sorted, deduped. A-29.

    Mirrors ``write_tables()`` in shape but the catalog is different: these
    are Postgres functions (RPC endpoints), not tables. ``/internal/schema-drift``
    checks this list against ``pg_proc`` via ``supabase_function_exists`` —
    a missing function is the same drift class as a missing table (the call
    returns False, the failure looks like "no data yet"), but the live probe
    must look in the right catalog.
    """
    out: set[str] = set()
    for p in sorted(_ROOT.rglob("*.py")):
        if _is_prod(p):
            out |= _rpcs_in(p)
    return sorted(t for t in out if t and not t.startswith("_"))


def _columns_in(path: Path) -> dict[str, set[str]]:
    """table -> column names this file passes to a write helper (S-286).

    Only literal `dict` payloads with literal string keys count. A payload built
    from a variable is invisible here, which is the same blind spot `_tables_in`
    records for dynamic table names — noted rather than papered over, because a
    manifest that looks more complete than it is becomes the thing people trust
    instead of the database.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError):
        return {}
    out: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
        # S-342 + A-29: see _tables_in — same predicate, same rationale. We
        # only collect columns for TABLE writes; RPC calls don't carry row
        # payloads in the same shape.
        if not _is_table_write_name(name) or len(node.args) < 2:
            continue
        first = node.args[0]
        if not (isinstance(first, ast.Constant) and isinstance(first.value, str)):
            continue
        for d in ast.walk(node.args[1]):
            if isinstance(d, ast.Dict):
                out.setdefault(first.value, set()).update(
                    k.value for k in d.keys
                    if isinstance(k, ast.Constant) and isinstance(k.value, str))
    return out


def write_columns_by_provenance() -> dict[str, dict[str, list[str]]]:
    """同 `write_tables_by_provenance()`,列这一半(S-399c)。

    `{"with_call_site": {table: [cols]}, "declared_only": {table: [cols]}}`

    **为什么两半都要**:2026-09-22 我把表按来源拆开修了措辞,**列没拆**,
    于是 `market_state_vectors` 那三列(`adv_screen_pass` / `adv_usd_20d` /
    `mcap_usd`,和那两张表同一个不存在的 Mac 侧写入端)继续让
    `schema_drift_check` 退出 1,**而 preflight 是 `|| exit 1`、handoff 是 `&&` 链,
    于是所有 push 被挡住** —— 挡住的理由是一批**没有任何人写**的列。

    **「修了一半」这次发生在我自己身上,而且是在同一批改动里。**
    """
    ast_cols: dict[str, set[str]] = {}
    dec_cols: dict[str, set[str]] = {}
    for p in sorted(_ROOT.rglob("*.py")):
        if not _is_prod(p):
            continue
        for t, cols in _columns_in(p).items():
            ast_cols.setdefault(t, set()).update(cols)
        for t, cols in _declared_columns_in(p).items():
            dec_cols.setdefault(t, set()).update(cols)
    out_ast = {t: sorted(c) for t, c in ast_cols.items() if c}
    out_dec = {t: sorted(c - ast_cols.get(t, set()))
               for t, c in dec_cols.items()}
    return {"with_call_site": out_ast,
            "declared_only": {t: c for t, c in out_dec.items() if c}}


def write_columns() -> dict[str, list[str]]:
    """Every column a production module writes, per table. Sorted, deduped.

    THE HALF THAT WAS MISSING. `write_tables()` answers "does the table exist",
    which is the S-166 question. On 2026-09-04 the ① book was taken down by a
    missing COLUMN on a table that existed — `interval_hours`, code deployed
    ahead of its migration — and every existing guard stayed green. The offline
    guard can only prove a migration FILE exists; only a live probe can prove it
    RAN. This is the contract half of that probe (see `/internal/schema-drift`).

    Two sources are merged: literal `dict` payloads in write helpers (the
    `_columns_in` walker) AND module-level `WRITES_COLUMNS = {table: (cols...)}`
    declarations for injected writers (C-13 P4) whose payload is built outside
    this repo and so cannot be inferred from a literal dict.
    """
    out: dict[str, set[str]] = {}
    for p in sorted(_ROOT.rglob("*.py")):
        if _is_prod(p):
            for t, cols in _columns_in(p).items():
                out.setdefault(t, set()).update(cols)
            for t, cols in _declared_columns_in(p).items():
                out.setdefault(t, set()).update(cols)
    return {t: sorted(c) for t, c in sorted(out.items()) if t and not t.startswith("_")}


#: C-13 P4 (2026-09-21): mirror of `_DECLARED` for columns. `WRITES_COLUMNS`
#: is `{table: (col, col, ...)}` at module level — same shape as `WRITES_TABLES`,
#: but per-column. Used by Seth-side declaration modules whose payload is built
#: in Mac-side writers the AST walker cannot see (Rule 3: `cometcloud-local/`
#: is not Seth's lane). The declaration is read here; the alternative is a
#: manifest that "looks complete" while missing the columns the production code
#: actually writes — the same hazard `_declared_tables_in` was added to prevent.
_DECLARED_COLUMNS = "WRITES_COLUMNS"


def _declared_columns_in(path: Path) -> dict[str, set[str]]:
    """模块级 `WRITES_COLUMNS = {"t": ("c", "c")}` 里声明的 table -> columns。

    Accepted forms for the value side: tuple, list, set, frozenset, or a
    `frozenset({...})` call (the common idiom for a frozen, hashable set).
    Anything else falls through silently — the same blind-spot doctrine as
    `_tables_in` for non-literal first args.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError):
        return {}
    out: dict[str, set[str]] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        names = {getattr(t, "id", None) for t in node.targets}
        if _DECLARED_COLUMNS not in names:
            continue
        if not isinstance(node.value, ast.Dict):
            continue
        for k_node, v_node in zip(node.value.keys, node.value.values):
            if not (isinstance(k_node, ast.Constant) and isinstance(k_node.value, str)):
                continue
            cols: set[str] = set()
            # Form A: literal ("c", "c") / ["c", "c"] / {"c", "c"}.
            if isinstance(v_node, (ast.Tuple, ast.List, ast.Set)):
                for el in v_node.elts:
                    if isinstance(el, ast.Constant) and isinstance(el.value, str):
                        cols.add(el.value)
            # Form B: frozenset({"c", "c"}) — common for frozen-set literals.
            elif isinstance(v_node, ast.Call) and getattr(v_node.func, "id", None) == "frozenset":
                for arg in v_node.args:
                    if isinstance(arg, ast.Set):
                        for el in arg.elts:
                            if isinstance(el, ast.Constant) and isinstance(el.value, str):
                                cols.add(el.value)
            if cols:
                out[k_node.value] = cols
    return out


def manifest_path() -> Path:
    return _ROOT / "src" / "api" / "schema_manifest.json"
