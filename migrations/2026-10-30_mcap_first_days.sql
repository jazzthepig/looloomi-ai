-- 2026-10-30 · S-700 数据补齐用:asset_mcap_daily 每个 (symbol, coin_id) 的第一天(一次聚合,代替分页读全表)。
create or replace function public.mcap_first_days()
returns table(symbol text, coin_id text, first_d date)
language sql stable set search_path = public, pg_temp as $$
  select symbol, coin_id, min(d) from asset_mcap_daily group by 1, 2
$$;
revoke all on function public.mcap_first_days() from anon, authenticated;
