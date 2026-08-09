-- SECURITY P0 — revoke PUBLIC EXECUTE on the SECURITY DEFINER backfill functions
-- 2026-08-09, found during the full code check.
--
-- WHAT WAS WRONG. Four SECURITY DEFINER functions were callable by `anon`:
--
--   backfill_binance_hourly(text, bigint, int)
--   backfill_binance_funding(text, bigint, int)
--   backfill_daily_for_asset(text, int)
--   ingest_binance_universe()
--
-- SECURITY DEFINER means they execute with the owner's rights and bypass RLS
-- entirely. `anon` is public by construction — it ships in the frontend bundle and
-- is additionally hardcoded as a default in scripts/external_probe.sh — so this was
-- reachable by anyone:
--
--   POST /rest/v1/rpc/backfill_binance_hourly
--   {"p_symbol": "<any monitor_hourly asset>", "p_max_batches": 999999}
--
-- `p_max_batches` is caller-controlled and the loop only exits on it or on reaching
-- now(), so a single unauthenticated call drives unbounded outbound http_get calls
-- from inside the database and unbounded INSERTs into ohlcv_hourly — against a
-- storage tier we were at 90% of last week. Not exfiltration (RLS still blocks
-- reads) and not deletion (anon holds no DELETE, and TRUNCATE is unreachable
-- through PostgREST), but a clean unauthenticated resource-exhaustion vector.
--
-- WHY THE EXISTING REVOKES DID NOTHING — the part worth remembering. The scripts
-- already contained, and have contained since they were written:
--
--   revoke all on function backfill_binance_hourly(text, bigint, int)
--     from anon, authenticated;      -- supabase_ohlcv_hourly.sql:103
--
-- The privilege was never held by `anon`. `CREATE FUNCTION` grants EXECUTE to
-- PUBLIC by default, and `anon` merely inherits it. Revoking from a role that was
-- never granted is a SUCCESSFUL NO-OP: no error, no warning, no rows, and the
-- script reads as though the door were locked. The ACL shows it plainly —
--
--   locked:   {postgres=X/postgres, service_role=X/postgres}
--   exposed:  {=X/postgres, postgres=X/postgres, service_role=X/postgres}
--                ^^ the empty grantee IS PUBLIC
--
-- The correct idiom already exists once in this repo, in
-- supabase_refresh_signal_track_record_v2.sql: `... from public`. That function is
-- the one that is actually locked down. Same author, same week, both idioms.
--
-- This is the house failure mode in a new costume: an operation that reports
-- success while changing nothing (cf. S-105's durable write, S-116's inert mapping,
-- S-122's defaults). The rule holds — verify against the artifact, not the script.

begin;

-- ── the fix: revoke from PUBLIC, which is where the grant actually lives ─────
revoke all on function public.backfill_binance_hourly(text, bigint, integer)  from public;
revoke all on function public.backfill_binance_funding(text, bigint, integer) from public;
revoke all on function public.backfill_daily_for_asset(text, integer)         from public;
revoke all on function public.ingest_binance_universe()                       from public;

-- belt and braces: the named roles too, in case a future re-create grants directly
revoke all on function public.backfill_binance_hourly(text, bigint, integer)  from anon, authenticated;
revoke all on function public.backfill_binance_funding(text, bigint, integer) from anon, authenticated;
revoke all on function public.backfill_daily_for_asset(text, integer)         from anon, authenticated;
revoke all on function public.ingest_binance_universe()                       from anon, authenticated;

-- service_role keeps EXECUTE — the Mac engine and the scheduled jobs are the
-- legitimate callers and they authenticate with it.
grant execute on function public.backfill_binance_hourly(text, bigint, integer)  to service_role;
grant execute on function public.backfill_binance_funding(text, bigint, integer) to service_role;
grant execute on function public.backfill_daily_for_asset(text, integer)         to service_role;
grant execute on function public.ingest_binance_universe()                       to service_role;

-- ── risk_meter_history: the only table in the schema with RLS switched off ───
-- anon holds SELECT on it, so with RLS off it is anonymously readable through
-- PostgREST. Every other table is RLS-on, and the 30-odd with no policy at all are
-- deny-by-default, which is correct.
alter table public.risk_meter_history enable row level security;
revoke all on public.risk_meter_history from anon;

commit;

-- ── VERIFY (run after; this is the check that matters, not the script above) ──
-- select p.proname, p.proacl::text,
--        has_function_privilege('anon', p.oid, 'EXECUTE') anon_can_call
--   from pg_proc p join pg_namespace n on n.oid = p.pronamespace
--  where n.nspname = 'public'
--    and p.proname in ('backfill_binance_hourly','backfill_binance_funding',
--                      'backfill_daily_for_asset','ingest_binance_universe');
-- expect anon_can_call = false on all four, and NO leading `=X/` in any acl.
--
-- select relname, relrowsecurity from pg_class
--  where relnamespace = 'public'::regnamespace and relkind = 'r' and not relrowsecurity;
-- expect zero rows.
--
-- NOTE FOR THE NEXT MIGRATION: `CREATE OR REPLACE FUNCTION` re-grants EXECUTE to
-- PUBLIC. Any script that re-creates one of these must re-run the revoke, or the
-- hole reopens silently on the next deploy.
