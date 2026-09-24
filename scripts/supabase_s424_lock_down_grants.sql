-- S-424 (2026-09-24/25) — net effect of migrations s424_lock_down_public_grants, s424b, s424c.
-- Posture is S-167's: RLS on + zero policies ⇒ only service_role (which bypasses RLS) reads.
-- s424 first added anon read policies to keep the three views readable after switching them to
-- security_invoker; the S-167 guard rejected that, correctly — every real reader is service_role.
-- Instead, anon SELECT on the views is REVOKED so an anon read fails loudly rather than returning 0 rows.
revoke truncate, trigger, references on all tables in schema public from anon, authenticated;
revoke insert, update, delete on all tables in schema public from authenticated;
alter default privileges for role postgres in schema public revoke truncate, trigger, references on tables from anon, authenticated;
alter default privileges for role postgres in schema public revoke insert, update, delete on tables from authenticated;
alter table public.cg_coin_map enable row level security;
revoke select on public.cg_coin_map from anon, authenticated;
alter view public.ohlcv_daily_canonical set (security_invoker = on);
alter view public.panel_ew_forward_returns set (security_invoker = on);
alter view public.signal_outcomes_unified set (security_invoker = on);
revoke select on public.ohlcv_daily_canonical, public.panel_ew_forward_returns, public.signal_outcomes_unified from anon, authenticated;
-- + every public function without a pinned search_path: set search_path = public, extensions, pg_temp
