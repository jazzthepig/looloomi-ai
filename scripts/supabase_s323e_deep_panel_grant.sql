-- S-323e (2026-09-08) — applied to production as migration
-- `s323e_deep_panel_symbol_list_security_definer`.
--
-- THE ACTUAL CAUSE, after four rounds of fixing things that were not it.
--
-- `deep_panel_symbol_list()` was granted EXECUTE to anon/authenticated and was
-- SECURITY INVOKER. It wraps `ohlcv_symbol_coverage()`, which was granted to
-- postgres and service_role ONLY. A SECURITY INVOKER function runs its body as
-- the CALLER, so every app call raised:
--
--     42501  permission denied for function ohlcv_symbol_coverage
--
-- Measured 2026-09-08, before the fix:
--
--     anon           -> 42501 permission denied for ohlcv_symbol_coverage
--     authenticated  -> 42501 permission denied for ohlcv_symbol_coverage
--     service_role   -> OK, 262 rows
--
-- PostgREST rendered that as 403. `_supabase_request_with_retry` treats any
-- 4xx except 429 as a non-retryable client error, records SUCCESS on the
-- circuit breaker, and returns the response; `supabase_rpc` then sees a
-- non-200 and returns None. The caller printed:
--
--     "深盘符号表没读到 (RPC 不通/熔断)"
--
-- ── WHY THIS COST FIVE ROUNDS ───────────────────────────────────────────────
--
-- That message names three suspects — RPC, connectivity, breaker — and the
-- real one is a GRANT on a function whose name appears nowhere in it. The
-- error text was assembled from the *hypotheses available when it was
-- written*, not from the response. S-323/c/d each fixed one of the named
-- suspects (index, timeout, schema cache) and each left the loop red, because
-- a message that lists its author's guesses will keep sending you to those
-- guesses for as long as you trust it.
--
-- The breaker was never involved in any of the five rounds.
--
-- ── WHY SECURITY DEFINER AND NOT A GRANT ON THE CALLEE ──────────────────────
--
-- Granting `ohlcv_symbol_coverage()` to anon would also work, and is wrong:
-- that function is the full-table grouping (591 rows, the expensive one) and
-- the wrapper exists precisely to be the narrow surface (262 rows). Widening
-- the callee would expose the thing the wrapper was built to keep unexposed.
-- SECURITY DEFINER keeps exactly one door open and it is the narrow one.
-- `search_path` is pinned, which SECURITY DEFINER requires.
--
-- ── THE CLASS, NOT THE INSTANCE ─────────────────────────────────────────────
--
-- A SECURITY INVOKER function is only as reachable as its least-granted
-- dependency, and nothing in the grant model says so: `\df+` shows the wrapper
-- granted to anon and stops there. Scanned the whole schema for the shape
-- (functions reachable by anon/authenticated, not DEFINER, whose body calls a
-- function those roles cannot execute) — exactly one instance, this one.
-- The scan is worth keeping, and it is a CATALOG question, so it lives in the
-- catalog as `public.rpc_reachability_audit()` (migration
-- `s323e_rpc_reachability_audit`, service_role only per CLAUDE.md #8). It needs
-- no deploy and cannot go stale against the thing it audits, because it reads
-- that thing directly. preflight stays offline by contract (S-163), so this is
-- the online half:
--
--     select * from public.rpc_reachability_audit();   -- expect 0 rows
--
-- Verified to FIRE on the real defect, not on a fixture: the identical query
-- returned exactly one row (deep_panel_symbol_list -> ohlcv_symbol_coverage)
-- before this migration and zero after it.

create or replace function public.deep_panel_symbol_list()
returns table(symbol text, n_rows bigint, latest text)
language sql
stable
security definer
set search_path to 'public'
as $$
  select c.symbol, c.n, c.last_date
  from public.ohlcv_symbol_coverage() c
  where c.source = 'binance_hist'
  order by c.symbol
$$;

-- ⚠️ THE REVOKE IS THE NARROWING STEP, AND I LEFT IT OUT (S-323h).
-- preflight's `test_security_definer_functions_are_revoked_at_all` caught it.
-- Postgres grants EXECUTE to PUBLIC on creation and Supabase's ALTER DEFAULT
-- PRIVILEGES adds anon/authenticated/service_role on top, so a bare GRANT is
-- ADDITIVE to a default that is already open. Measured after the first version
-- of this script: deep_panel_symbol_list was SECURITY DEFINER **with EXECUTE to
-- PUBLIC**, and rpc_reachability_audit had picked up `authenticated` even though
-- I granted service_role only.
--
-- The header above claimed this "keeps exactly one door open and it is the
-- narrow one". That sentence was false the moment it was written: it described
-- what the GRANT intended while the DEFAULT left every door open. Writing down
-- the intended end state is not reaching it -- the same defect as the rest of
-- this chain, this time inside my own fix.
revoke all on function public.deep_panel_symbol_list() from public;
grant execute on function public.deep_panel_symbol_list() to anon, authenticated, service_role;

notify pgrst, 'reload schema';

-- ⚠️⚠️ S-323i — READ THIS BEFORE TREATING THE ABOVE AS "THE FIX".
--
-- Restoring this RPC restores a 262-symbol fan-out to Binance's FREE mirror,
-- which `src/data/market/source_policy.py` forbids and names as its FIRST
-- example. JAZZ has said this many times; S-296 applied it to hyperliquid and
-- left the Binance loop 40 lines away untouched.
--
-- **The 42501 this script "fixed" was the only thing enforcing that policy.**
-- Five rounds went into diagnosing the enforcement as a fault and repairing it.
--
-- Enforcement now lives in code (`assert_purpose_source` wired into
-- `collect_deep_panel`, S-323i), so the panel's real fix is OPEN RISK #0a --
-- the CG Pro symbol->coin_id mapping -- and not this RPC.

-- Verified after applying, all three roles:
--     anon           -> OK rows=262
--     authenticated  -> OK rows=262
--     service_role   -> OK rows=262
