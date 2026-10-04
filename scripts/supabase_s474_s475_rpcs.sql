-- S-474 (2026-10-03, migration s474_cg_known_coin_map_index_path): cg_known_coin_map() 1,167 ms -> 58 ms.
-- The ohlcv_daily fallback compared upper(o.symbol) = m.symbol, which defeats the (symbol, trade_date, source) index and
-- scanned 640k rows per symbol; under load it crossed the 10 s client timeout, and since S-469 a timed-out map read
-- refuses the cg_panel round (6 of 11 rounds refused in 12 h). Every symbol in both tables is already upper-case
-- (checked: 0 lower-case rows in either), so o.symbol = m.symbol is the same predicate on the index path.
create or replace function public.cg_known_coin_map()
 returns table(symbol text, coin_id text, resolved_from text, verified_at timestamp with time zone, asset_class text)
 language sql stable
 set search_path to 'public', 'extensions', 'pg_temp'
as $function$
  select m.symbol, m.coin_id, m.resolved_from, m.verified_at,
         coalesce(
           (select a.class from assets a where upper(a.symbol)=m.symbol limit 1),
           (select o.asset_class from ohlcv_daily o
             where o.symbol=m.symbol and o.asset_class is not null limit 1),
           'Crypto') as asset_class
  from cg_coin_map m
$function$;

-- S-475 (2026-10-03, migration s475_refresh_regime_daily): regime_daily had no writer after the one-time S-349 backfill
-- (stale since 09-15). Same derivation as scripts/supabase_s349_regime_daily.sql, reproduced exactly on 09-10..09-14;
-- 09-15 differed only because S-349 ran mid-day. Writes completed UTC days only; keeps the meditation columns.
-- Applied once immediately: 16 rows 09-15..10-02 (09-19 and 09-20 have no cis_scores rows -> no regime row, a gap, not 0).
create or replace function public.refresh_regime_daily(p_since date)
returns integer
language sql
set search_path = public, pg_temp
as $$
  with x as (
    select (c.recorded_at at time zone 'UTC')::date as d,
           jsonb_strip_nulls(jsonb_build_object(
             'avg_cis', round(avg(c.score)::numeric,3),
             'pct_out', round((count(*) filter (where c.signal like '%OUTPERFORM%'))::numeric/nullif(count(*),0),4),
             'pct_under', round((count(*) filter (where c.signal like '%UNDER%'))::numeric/nullif(count(*),0),4),
             'avg_pillar_f', round(avg(c.pillar_f)::numeric,3),
             'avg_pillar_m', round(avg(c.pillar_m)::numeric,3),
             'avg_pillar_o', round(avg(c.pillar_o)::numeric,3),
             'avg_pillar_s', round(avg(c.pillar_s)::numeric,3),
             'avg_pillar_a', round(avg(c.pillar_a)::numeric,3),
             'avg_las', round(avg(c.las)::numeric,3),
             'avg_conf', round(avg(c.confidence)::numeric,3),
             'score_disp', round(stddev_samp(c.score)::numeric,3))) as features,
           mode() within group (order by c.macro_regime) as regime_db,
           count(distinct c.symbol)::int as n_universe
    from cis_scores c
    where c.recorded_at >= (p_since::timestamp at time zone 'UTC')
      and c.recorded_at <  ((now() at time zone 'UTC')::date::timestamp at time zone 'UTC')
    group by 1),
  up as (
    insert into regime_daily (d, features, regime_db, n_universe)
    select d, features, regime_db, n_universe from x
    on conflict (d) do update
      set features = excluded.features, regime_db = excluded.regime_db, n_universe = excluded.n_universe
    returning 1)
  select count(*)::int from up;
$$;
revoke all on function public.refresh_regime_daily(date) from public, anon, authenticated;
grant execute on function public.refresh_regime_daily(date) to service_role;
-- select public.refresh_regime_daily('2026-09-15');
