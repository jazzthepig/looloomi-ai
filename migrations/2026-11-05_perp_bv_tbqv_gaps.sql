-- 11-05(T-243 发现):tbqv 列 11-05 才加,2025-12 → 今天的已有行全是 NULL(补的是缺的月份,已有的行没重取)。
-- 这个视图告诉采集器哪些 (合约, 月) 还缺 tbqv,按月档重取一遍(upsert 覆盖同值 + 补 tbqv)。已通过 Supabase MCP 施加(migration name: perp_bv_tbqv_gaps)。
-- 同日:perp_bv_daily 加 tbqv 列与 (symbol, d) 索引(migration name: perp_bv_daily_tbqv)。
alter table public.perp_bv_daily add column if not exists tbqv double precision;
create index if not exists perp_bv_daily_symbol_d on public.perp_bv_daily (symbol, d);
create or replace view public.perp_bv_tbqv_gaps with (security_invoker = on) as
select pair, to_char(d, 'YYYY-MM') as month, count(*) as n_null, min(d) as min_d, max(d) as max_d
from public.perp_bv_daily
where tbqv is null
group by pair, to_char(d, 'YYYY-MM');
grant select on public.perp_bv_tbqv_gaps to anon, authenticated, service_role;
