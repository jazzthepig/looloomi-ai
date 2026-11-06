-- 2026-11-06 · the point-in-time coin universe read by token_holders / cg_supply was cg_coin_mcap_daily alone — which has
-- no bitcoin / ethereum / solana (lane-a / lane-b found 21 majors at 0 rows; that table holds the new-coin / wrapped universe).
-- asset_mcap_daily (same CoinGecko upstream) holds the majors; the two are mostly disjoint (413 of 486 coin_ids only there).
-- Union both ⇒ 826 → 1,216 coins. 2.3 s to compute ⇒ materialized, refreshed by refresh_feature_matrix() (hourly).
drop view if exists public.cg_coin_mcap_coins;
create materialized view if not exists public.cg_coin_mcap_coins as
with u as (
  select coin_id, d, mcap from public.cg_coin_mcap_daily where mcap > 0
  union all
  select coin_id, d, mcap from public.asset_mcap_daily where mcap > 0 and coin_id is not null
)
select coin_id, min(d) first_d, max(d) last_d, (array_agg(mcap order by d desc))[1] last_mcap from u group by coin_id;
create unique index if not exists cg_coin_mcap_coins_uq on public.cg_coin_mcap_coins (coin_id);
grant select on public.cg_coin_mcap_coins to anon, authenticated, service_role;

create or replace function public.refresh_feature_matrix() returns integer
language plpgsql security definer set search_path = public, pg_temp as $$
begin
  refresh materialized view concurrently public.feature_matrix_daily;
  refresh materialized view concurrently public.cg_coin_mcap_coins;
  return (select count(*) from public.feature_matrix_daily);
end $$;
revoke all on function public.refresh_feature_matrix() from public, anon, authenticated;
grant execute on function public.refresh_feature_matrix() to service_role;
