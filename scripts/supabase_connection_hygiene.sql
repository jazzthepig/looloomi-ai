-- ============================================================================
-- Connection hygiene — root-cause fix for the 2026-07-29 P0 (S-92)
-- ============================================================================
-- INCIDENT. Between 15:23:27 and 15:37:18 UTC the database stopped accepting
-- work. PostgREST stayed alive (unauthenticated /rest/v1/ answered 401 in 0.25s)
-- and Postgres itself stayed idle (checkpoints writing 0.0-0.6% of buffers, two
-- statement timeouts all day) — but every query needing a pooled connection
-- hung. Supavisor pool size on Nano compute is 15. Down 10.4 h before detection,
-- because /health returned a hardcoded "healthy".
--
-- MECHANISM. Our writers set CLIENT-side timeouts only:
--     urllib.request.urlopen(req, timeout=10)      # pgvector_store.upsert
-- A client timeout closes the socket. It does NOT cancel the server-side
-- statement. `asset_embeddings` carries an HNSW index, so upsert index
-- maintenance is expensive on a Nano instance's small maintenance_work_mem: the
-- client gives up at 10s while the server keeps running and keeps holding its
-- pooled connection. The Mac engine repeats the push roughly every 30 min, so
-- abandoned-but-live connections accumulate until the pool of 15 is gone and
-- everything hangs.
--
-- The missing piece is not any single slow query — it is that NOTHING on the
-- server side ever gives up. A client-side timeout without a matching
-- server-side timeout is not a timeout; it is a connection leak with a
-- reassuring log line. (Same defect class as a health check that cannot fail,
-- and as the S-90 freeze that had no recovery path: every cut-off needs a
-- bounded, enforced end.)
--
-- APPLY: Mac side, once the instance is reachable again (a project restart is
-- required first to clear the connections already stranded).
-- Verify with the queries in the last section.
-- ============================================================================

-- ── 1. Server-side statement timeout per role ────────────────────────────────
-- Any statement exceeding the budget is cancelled BY THE SERVER, so an abandoned
-- client can no longer pin a connection indefinitely.
--   anon / authenticated : serving path, must stay snappy
--   service_role         : writers (Mac push, embeddings upsert) need more room
--                          for HNSW index maintenance, but still bounded
ALTER ROLE anon          SET statement_timeout = '8s';
ALTER ROLE authenticated SET statement_timeout = '8s';
ALTER ROLE service_role  SET statement_timeout = '30s';

-- ── 2. Idle-in-transaction timeout (the actual leak stopper) ─────────────────
-- A transaction left open by a dead/abandoned client holds its connection and
-- its locks forever. This bounds that to 30s for every role.
ALTER ROLE anon          SET idle_in_transaction_session_timeout = '30s';
ALTER ROLE authenticated SET idle_in_transaction_session_timeout = '30s';
ALTER ROLE service_role  SET idle_in_transaction_session_timeout = '60s';

-- Also bound lock waiting: a writer blocked on a lock should fail, not queue.
ALTER ROLE service_role  SET lock_timeout = '10s';
ALTER ROLE anon          SET lock_timeout = '5s';
ALTER ROLE authenticated SET lock_timeout = '5s';

-- ── 3. Make the expensive path cheaper, not just bounded ────────────────────
-- HNSW insert cost scales with ef_construction/m. The index was created for
-- recall on a 72-row table; on Nano the maintenance cost dominates. Lower the
-- build parameters so upserts stop being the slowest write in the system.
-- NOTE: run this only after confirming the index name; kept explicit rather
-- than guessed. Uncomment once verified against §5 output.
--
-- DROP INDEX IF EXISTS asset_embeddings_vec_hnsw_idx;
-- CREATE INDEX asset_embeddings_vec_hnsw_idx
--     ON asset_embeddings USING hnsw (vec vector_cosine_ops)
--     WITH (m = 8, ef_construction = 32);

-- ── 4. Verification — run these and paste the output into the ledger ────────
-- 4a. Confirm the role settings actually landed.
--     SELECT rolname, rolconfig FROM pg_roles
--      WHERE rolname IN ('anon','authenticated','service_role');
--
-- 4b. Who is holding connections, and for how long? This is the query that was
--     unavailable during the incident precisely because the pool was gone —
--     capture a baseline NOW so the next occurrence is diagnosable in seconds.
--     SELECT state,
--            count(*),
--            max(now() - state_change)          AS longest_in_state,
--            max(now() - xact_start)            AS longest_xact
--       FROM pg_stat_activity
--      WHERE datname = current_database()
--      GROUP BY state ORDER BY 2 DESC;
--
-- 4c. Any transaction older than a minute is a bug, not a workload.
--     SELECT pid, usename, application_name, state,
--            now() - xact_start AS xact_age, left(query, 120) AS query
--       FROM pg_stat_activity
--      WHERE xact_start < now() - interval '1 minute'
--      ORDER BY xact_start;
--
-- 4d. Index inventory for §3 (get the real name before uncommenting).
--     SELECT indexname, indexdef FROM pg_indexes
--      WHERE tablename = 'asset_embeddings';

-- ── 5. Emergency runbook (kept with the fix, not in someone's memory) ───────
-- Symptom: /api/v1/cis/* slow or 503-degraded; /health reports
--          data_layer.supabase = circuit_open.
--   1. GET /health   → read data_layer.breaker (added 2026-07-29; it can now
--                      actually go red, which is the whole point).
--   2. Run 4b/4c above. Connections idle-in-transaction ⇒ this incident again.
--   3. Terminate the stranded backends (safe — they are abandoned):
--        SELECT pg_terminate_backend(pid) FROM pg_stat_activity
--         WHERE datname = current_database()
--           AND state = 'idle in transaction'
--           AND xact_start < now() - interval '5 minutes';
--   4. If even step 3 cannot connect, restart the project from the dashboard
--      (Settings → General → Restart project). That clears all connections.
--   5. Confirm recovery:
--        curl -sm10 -o /dev/null -w '%{http_code} %{time_total}\n' \
--          "$BASE/api/v1/cis/universe?limit=1"
