-- 11-05:lane 研究要日频资金费(T-242 / T-243);底表 funding_history 已对 anon 开读,视图按调用者权限执行,不多开任何东西。
-- 已通过 Supabase MCP 施加(migration name: lane_read_v_funding_daily)。
alter view public.v_funding_daily set (security_invoker = on);
grant select on public.v_funding_daily to anon;
