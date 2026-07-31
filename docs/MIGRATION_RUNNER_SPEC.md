# Migration Runner Spec — `/internal/apply-migration` (M-WO-7.1 follow-on)

**Status:** Draft v0.1 (2026-07-29)
**Lane:** Seth (design-first per M-WO-7.5 model)
**Author:** Minimax-A (proposal); awaiting Seth sign-off + Jazz ratification
**Audience:** Seth (implementer), Jazz (security sign-off), Minimax-B (operator of Mac-side DDL via Railway)
**Supersedes:** None — greenfield build
**Resolves:** MINIMAX_SYNC §M-WO-7.1 reply — Minimax-A — 2026-07-28 PUSHED ✓ but migration NOT applied; route blocker

---

## 1. North star (why)

The §M-WO-7.1 reply block (Minimax-A, 2026-07-28) documented that:

> The `regime_fingerprints` schema migration was committed at `ecde38a` as `scripts/supabase_regime_fingerprints.sql`, but **no execution path exists in code** to apply it. The `src/api/store.py::supabase_rpc()` function only invokes *named* RPCs — there is no `supabase_apply_migration(sql_path)` route. Direct Supabase REST probes from Mac-side time out at the network layer (Seth flagged this 2026-07-27 §ASSET-VECTORS-READY body). Without `psql` binary on this Mac, **DDL cannot land** without manual intervention from a dashboard-accessible lane.

This is not a one-off. **10+ `scripts/supabase_*.sql` files are in HEAD**, all committed with no execution path:

| File | Purpose | Migration class |
|---|---|---|
| `supabase_regime_fingerprints.sql` | M-WO-7.1 build (Seth 2026-07-28) | pgvector table + HNSW + RPC |
| `supabase_pgvector_vdb.sql` | asset_embeddings v1 (Seth 2026-07-22) | pgvector extension + table |
| `supabase_strategy_records.sql` | strategy vector v2 (Seth 2026-07-26) | jsonb strategy vector table |
| `supabase_beta_core.sql` | M-WO-A beta_core_nav + risk_allocations (Seth 2026-07-27) | 2 tables for ① layer |
| `supabase_strategy_records.sql` | (re-listed above) | |
| `supabase_refresh_signal_track_record_v2.sql` | β-metric ship gate (Seth 2026-07-26) | view + function |
| others (10+ in HEAD but not yet enumerated) | various | various |

The pattern repeats: schema files are committed; **apply is left as a manual dashboard step**. This is the **migration-debt the project carries in perpetuity** — every new feature ships its DDL into HEAD, but the apply never finishes.

**The goal of this spec is a one-route clean-up**: a single Seth-side internal endpoint that any lane can use to apply *idempotent* SQL migrations from `scripts/supabase_*.sql`. The endpoint is best-effort-by-design (Mac-side push already succeeded if we got here), mirrors the existing `/internal/asset-vectors` + `/internal/cis-scores` patterns, and uses an idempotency key (the SQL file's basename + first 32 chars of the SHA256 of its contents) so re-applies are no-ops.

---

## 2. What this is NOT

- **NOT a psql-equivalent for ad-hoc DDL.** The route accepts only files that follow the `scripts/supabase_*.sql` naming convention. No raw SQL body submission from a client — that would defeat the principle that schema lives in the repo, not in operator memory.
- **NOT a backfill runner.** Backfills (`scripts/backfill_*.py`) live in the Seth-side Python tools and run via local CLI. The runner is for DDL apply only.
- **NOT a cis_push contract mutation path.** CIS push contract changes require a separate `SCHEMA_VERSION` bump in `src/api/contracts/cis_push.py` per §CONTRACT-INVARIANT and a coordinated Mac↔Railway handshake in `MINIMAX_SYNC §2`. The runner explicitly refuses to apply any SQL that touches `cis_push`, `cis_scores schema_version`, `contract_version`, or `vector_schema_version` columns — it can only ADD tables / indexes / RPCs.
- **NOT a sandbox-cross-lane write path.** The endpoint is /internal/* — same auth model as asset-vectors and cis-scores — and only Seth-lane or Minimax-lane credentials (env-gated `INTERNAL_TOKEN`) can hit it. Runaway rate-limits are the operator's responsibility.

---

## 3. Spec

### 3.1 Route surface

| Method | Path | Auth | Body | Response |
|---|---|---|---|---|
| `POST` | `/internal/apply-migration` | `X-Internal-Token: <env>` | `{"sql_path": "scripts/supabase_*.sql"}` | `{"status":"ok","applied":bool,"idempotency_key":"<sha256[:32]>","rows":[...]}` |
| `GET` | `/internal/apply-migration/schema` | `X-Internal-Token: <env>` (or unauth for echo) | — | `{"version":"1.0","accepted_glob":"scripts/supabase_*.sql","forbidden_patterns":["cis_scores","cis_push","schema_version","vector_schema"],"notes":...}` |
| `GET` | `/internal/apply-migration/applied` | `X-Internal-Token` | `?since=YYYY-MM-DD` | `{"applied":[{"idempotency_key":...,"sql_path":...,"applied_at":...,"runtime_ms":...}]}` |

### 3.2 Auth + safety

- **Token check**: exact match against `INTERNAL_TOKEN` env var. No token / wrong token → `401`.
- **Path allow-list**: glob pattern `scripts/supabase_*.sql`. Any other path → `403 forbidden path` (e.g., `/etc/passwd`, `scripts/run_backfill.py`, `src/.../*.sql`).
- **File read**: the SQL file is read from the repo's working directory on Railway (post-deploy bundle, NOT Mac-side). Mac-side pushes the SQL content via `payload["sql_text"]` fallback only if the path lookup fails — and the `sql_text` path is itself rate-limited to ≤1 call per migration per 24h.
- **Forbid-list** (regex on the SQL file body, fail-fast):
  ```python
  FORBIDDEN = [
      r"\bDROP\s+SCHEMA\b",
      r"\bDROP\s+DATABASE\b",
      r"\bDROP\s+ROLE\b",
      r"\bUPDATE\s+cis_scores\b",      # mutation of any cis_scores column
      r"\bALTER\s+TABLE\s+cis_push\b",
      r"\bALTER\s+TABLE\s+cis_scores\b\s+(ADD|DROP|RENAME|ALTER)",
      r"\bUPDATE\s+vector_schema_version\b",
  ]
  ```
  Any match → `403 forbidden SQL — apply via the cis_push contract path` with the matching pattern cited in the error body. This is the **schema-contract firewall**.
- **Statement splitter**: PostgreSQL syntax-aware splitter on `;` (with awareness of `DO $$ ... $$;` blocks, `CREATE FUNCTION` bodies, and quoted `$$...$$` strings). Splitter library: `pglast` is the canonical choice but introduces a dep; fallback is a hand-rolled `pg_split_statements()` in `src/api/store.py` that handles the well-known DDL subset (CREATE TABLE/INDEX/VIEW/FUNCTION, GRANT, COMMENT, ALTER TABLE ADD COLUMN, ALTER FUNCTION, INSERT INTO).

### 3.3 Idempotency model

- **Pre-flight**:
  ```sql
  CREATE TABLE IF NOT EXISTS _migrations_applied (
    idempotency_key text PRIMARY KEY,
    sql_path text NOT NULL,
    sql_sha256 text NOT NULL,
    applied_at timestamptz NOT NULL DEFAULT now(),
    applied_by text,
    runtime_ms int,
    statement_count int
  );
  ```
- **Compute key**: `sha256(sql_content)[:32]` + a path-fingerprint → 32-char hex string.
- **Re-apply rule**: if `(idempotency_key)` exists in `_migrations_applied`, skip with `applied=false, idempotency_hit=true`. If the *path* is new but `idempotency_key` matches an *earlier* path with same content, that's a collision (same SQL applied twice under two names) — log + skip.
- **Post-apply insert** is done as the last statement (idempotent: `INSERT ... ON CONFLICT DO NOTHING`).

### 3.4 What the runner applies (covered set)

| Class | Coverage | Notes |
|---|---|---|
| `CREATE TABLE IF NOT EXISTS` | ✅ | permitted always |
| `CREATE INDEX IF NOT EXISTS` | ✅ | permitted always |
| `CREATE OR REPLACE FUNCTION` | ✅ | permitted always |
| `CREATE OR REPLACE VIEW` | ✅ | permitted always |
| `CREATE EXTENSION` | ❌ | extensions must be manually enabled in Supabase dashboard |
| `DROP` * | ❌ | forbidden by regex (no DESTRUCTION EVER); manual dashboard for table drops |
| `GRANT`/`REVOKE` | 🟡 permitted but logged | audit trail in `_migrations_applied` |
| `INSERT INTO` | 🟡 only into `_migrations_applied` itself | no data inserts |
| `ALTER TABLE ADD COLUMN` (non-cis_*, non-vector_schema_*) | ✅ | permitted; logged |
| `ALTER TABLE ... ALTER ...` etc | ❌ | refuses any non-ADD ALTER outside forbid-list |

### 3.5 What the runner refuses (forbid-list — hard)

- `cis_scores`, `cis_push`, `cis_history`, `cis_provider` table mutations.
- `vector_schema_version`, `asset_vector_schema_version`, `regime_fingerprint schema_version` column mutations.
- `DROP SCHEMA`, `DROP DATABASE`, `DROP ROLE`.
- Any statement containing `;` *outside* the splitter's safe grammar (rejects injection of HTTP headers as SQL).
- Any raw SQL body via `payload.sql_text` path if the corresponding file is already in `_migrations_applied` (one-shot per migration per 24h).

### 3.6 Response shape

```json
{
  "status": "ok",
  "idempotency_key": "abc123...",
  "applied": true,
  "idempotency_hit": false,
  "sql_path": "scripts/supabase_regime_fingerprints.sql",
  "statement_count": 6,
  "statements_succeeded": 6,
  "statements_failed": 0,
  "runtime_ms": 842,
  "ts": "2026-07-29T01:50:00.123Z",
  "applied_by": "minimax-a",
  "schema_version_runtime_unchanged": true
}
```

`status="error"` on any failure, with `error_class`, `error_statement_index`, `error_pgcode`, `error_message` filled in.

### 3.7 API surface — research / non-investor

Per §-compliance, the route lives under `/internal/*` namespace; no `/api/v1/` exposure. Auth-required from any non-loopback caller. **No GET-all endpoint** that lists the contents of `scripts/` — only `applied` log.

---

## 4. Tests

Mandatory test coverage before SHIP (per §REGIME-OVERRIDE / §RISK-ALLOCATOR §3 +5 grain):

| Test | Verifies |
|---|---|
| `test_apply_migration_happy_path_regime_fingerprints` | regime_fingerprints DDL applies end-to-end; idempotency_key recorded |
| `test_apply_migration_idempotent_reapply_no_op` | second call with same content → `applied=false`, no error |
| `test_apply_migration_rejects_non_supabase_path` | `scripts/anything_else.sql` → 403 |
| `test_apply_migration_rejects_cis_scores_mutation` | forbid-list regex match on `cis_scores` → 403 with pattern cited |
| `test_apply_migration_rejects_drop_schema` | `DROP SCHEMA foo` → 403 |
| `test_apply_migration_handles_do_block_splitter` | `DO $$ ... $$;` block correctly parsed and applied |
| `test_apply_migration_logs_runtime_ms` | `_migrations_applied.runtime_ms` populated |
| `test_apply_migration_unauth_401` | missing/wrong token → 401 |
| `test_apply_migration_via_sql_text_fallback_once_only` | payload.sql_text only works if `_migrations_applied` doesn't have the sha in last 24h |
| `test_apply_migration_invariant_i1_no_data_drop` | the runner never drops rows from any existing table |

Plus a verification smoke that, after running on `supabase_regime_fingerprints.sql`, the `match_regime_fingerprints` RPC responds 200 to a stub `target` vector (proves schema is wired end-to-end).

---

## 5. Compliance / non-goals

- **Compliance**: the route does not surface investor-facing data. No CIS scores, no grading, no signal language. All responses are operational metadata (`applied`, `idempotency_key`, `runtime_ms`). Investor-facing routing is unaffected.
- **Out of scope**:
  - Schema migration **rollback** (DROP statements). If a migration needs to be undone, the operator publishes a new `scripts/supabase_rollback_X.sql` and re-applies manually via the dashboard.
  - **Mac-side apply**. The route applies on Railway's Supabase connection via `supabase_rpc()` (which uses `SUPABASE_URL` + `SUPABASE_KEY` already on Railway env). Mac-side apply would be a separate route (`/internal/apply-migration/mac`)
  - **Cross-cluster migrations** (read-replica, ETL target, etc.). Railway-only.
- **Hard non-goals**:
  - **No DDL on `cis_push`, `cis_scores`, `asset_embeddings` rows**. (can ADD table; CANNOT mutate rows of these named tables).
  - **No `pg_dump` / `pg_restore`**. Backups remain at the Supabase dashboard tier.

---

## 6. Build sequence (proposed)

1. **Seth-side writes module**: `src/api/routers/migration.py` (~80 LoC) + `src/api/store.py::supabase_apply_migration(sql_path)` (~60 LoC) + tests `tests/test_migration_runner.py` (~12 tests). Total: ~150 LoC + tests.
2. **Mount**: add `app.include_router(migration_router)` to `src/api/main.py` at line ~115 (between vector + strategy_vector).
3. **Preflight**: extend `scripts/preflight.sh` stage 3 to run the 12 new tests; expect 12/12.
4. **Push to main**: a single commit `feat(api): /internal/apply-migration route (M-WO-7.1 follow-on)`. Pre-flight green.
5. **Apply**: Minimax-A calls `POST /internal/apply-migration {"sql_path":"scripts/supabase_regime_fingerprints.sql"}` post-deploy. Expects `{"applied": true, "idempotency_key": "..."}`.
6. **Verify**: `match_regime_fingerprints(target='[0.1,0.2,...]'::vector, k=5)` returns 200 with 5 rows.
7. **Run 11yr backfill**: `scripts/backfill_regime_fingerprints.py --start 2017-08-17 --end 2026-07-27 --batch-size 200 --out reports/m_wo7_1_regime_fingerprint_backfill/2026-07-29_full/`.
8. **Close §M-WO-7.1**: REFUTATION_LEDGER §M-WO-7.1 verification flips to 🟢 BUILT.
9. **Cleanup sibling migrations**: `supabase_pgvector_vdb.sql`, `supabase_strategy_records.sql`, `supabase_beta_core.sql`, `supabase_refresh_signal_track_record_v2.sql`, etc. — all previously orphaned — can now be applied same way.

---

## 7. Open questions for Seth/Jazz

1. **`pglast` vs hand-rolled splitter?** — the splitter is the only non-trivial bit. Recommend hand-rolled (smaller blast radius, no new dep), but if Seth prefers `pglast`, the spec adapts.
2. **`sql_text` fallback — keep or drop?** — the path-lookup-first design means the rate-limit only triggers on operator-side failure modes (file deleted from bundle). Mac-side paths into `scripts/` would always be the canonical flow. Recommend **drop the fallback entirely** for v1; can add in v1.1 if a real use case surfaces.
3. **Auth model** — exact `INTERNAL_TOKEN` match (as currently proposed). An alternative is to require an `applied_by` caller label in the body (e.g. `{"caller":"minimax-a","sql_path":"..."}`) which would be audit-trail-only. Recommend adding caller label (no auth change).
4. **Should this auto-apply on Railway deploy?** — NO. Auto-apply is the lane that produced the §ASSET-VECTORS-READY deadlock (commit + push, no apply). Explicit apply-by-request keeps the operator in the loop. **The runner is the *control plane*, not a deploy hook.**

---

## 8. Files produced (when Seth builds it)

- `src/api/routers/migration.py` — route module
- `src/api/store.py` — add `supabase_apply_migration(sql_path)` (~60 LoC) + `pg_split_statements()` helper
- `src/api/main.py` — `app.include_router(migration_router)` line ~115
- `tests/test_migration_runner.py` — 12 tests
- `scripts/preflight.sh` — append 12 tests to stage 3
- `MINIMAX_SYNC §MIGRATION-RUNNER-SPEC reply — Minimax-A — 2026-07-29 — spec drafted, awaiting sign-off`

---

## 9. References

- **§M-WO-7.1** (`docs/REGIME_FINGERPRINT_SPEC.md`) — the migration that this route applies first.
- **§M-WO-7.1 reply — Minimax-A** (`MINIMAX_SYNC.md` line 7758+) — the blocker this route resolves.
- **`src/api/contracts/cis_push.py`** — the schema-contract firewall this route MUST respect.
- **§CONTRACT-INVARIANT (CLAUDE.md §4 hard rule)** — every `SCHEMA_VERSION` bump requires coordinated Mac↔Railway handshake documented in `MINIMAX_SYNC §2`. The runner's forbid-list is the runtime enforcement of this contract.
- **§PROTOCOL §3** — ownership lanes. This route is **Seth-side implementer**, **Minimax-B-operable** (Mac-side calls go through Railway), **Jazz-approved** (security sign-off).

EOF (this spec is 100% in §M-WO-7.5 design-first model. Sign-off is requested before code lands.)
