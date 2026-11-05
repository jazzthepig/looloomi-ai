-- 11-05(lane-b T-238 v2 发现):perp_bv_daily 缺 2026-10-28 整天。覆盖视图只看 min/max,中间的洞永远补不上;
-- 这个视图给采集器逐日行数(近 450 天),整天缺 / 行数塌一半的日子按月档或日档重取。已通过 Supabase MCP 施加(migration name: perp_bv_day_counts)。
create or replace view public.perp_bv_day_counts with (security_invoker = on) as
select d, count(*) as n from public.perp_bv_daily
where d >= (now() at time zone 'utc')::date - 450
group by d;
grant select on public.perp_bv_day_counts to anon, authenticated, service_role;
