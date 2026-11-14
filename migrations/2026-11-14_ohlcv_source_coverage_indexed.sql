-- 2026-11-14 · ohlcv_source_coverage() reads through the (source, trade_date, symbol) index (S-862).
-- 已通过 Supabase MCP 施加:ohlcv_source_coverage_reads_by_index。
--
-- WHY. Second health function behind /internal/data-freshness (the ops console calls it on every refresh).
-- `last_seen` was `max(trade_date) GROUP BY source` over all of ohlcv_daily (1.5M rows / 589 MB), and the two
-- date-bounded parts had no index that starts with trade_date. pg_stat_statements: 21,521 calls, 14,480 s in total,
-- mean 0.5-2.3 s depending on the plan, max 9.5 s. One of the nine statement timeouts at 07:58-08:02 UTC on 11-14.
--
-- WHAT. Same signature, defaults, columns and order. The distinct sources come from a loose index scan (8 of them);
-- the latest bar per source is one backward probe; the recent and baseline windows are index-only ranges per source.
--
-- CHECKED BEFORE REPLACING (old function vs new query, one statement): 8 sources on both sides, none on one side
-- only, 0 differences in any column. After: 141 ms on a quiet database. (The old one was not timed in isolation
-- right before the swap; the "before" figures are the pg_stat_statements means above.)
--
-- The first definition was applied by hand and is not in the repository (2026-10-20_lane_read_publishable.sql only
-- grants on it; the SQL it was built from is COVERAGE_SQL in src/data/market/source_freshness.py). This file is the
-- first complete record of the function.
--
-- LIVENESS: select count(*) from ohlcv_source_coverage();   -- one row per source label in ohlcv_daily (8 on 11-14)

create or replace function public.ohlcv_source_coverage(recent_crypto integer default 3, recent_tradfi integer default 6, base_lo integer default 45, base_hi integer default 15)
 returns table(source text, last_bar text, age_days integer, symbols_recent_crypto_win bigint, symbols_recent_tradfi_win bigint, symbols_typical numeric)
 language sql
 stable
 set search_path to 'public', 'pg_temp'
as $function$
  with recursive src as (
      (select o.source from ohlcv_daily o order by o.source limit 1)
      union all
      select (select o.source from ohlcv_daily o where o.source > s.source order by o.source limit 1)
      from src s where s.source is not null),
  s as (select src.source from src where src.source is not null),
  recent as (
      select s.source,
             count(distinct o.symbol) filter (where o.trade_date >= current_date - recent_crypto) as n_crypto_win,
             count(distinct o.symbol) filter (where o.trade_date >= current_date - recent_tradfi) as n_tradfi_win
      from s join ohlcv_daily o on o.source = s.source and o.trade_date >= current_date - recent_tradfi
      group by s.source),
  baseline as (
      select x.source, round(avg(x.n)::numeric, 0) as n_typical
      from (select s.source, o.trade_date, count(distinct o.symbol) as n
            from s join ohlcv_daily o on o.source = s.source
                 and o.trade_date between current_date - base_lo and current_date - base_hi
            group by s.source, o.trade_date) x
      group by x.source),
  last_seen as (
      select s.source,
             (select o.trade_date from ohlcv_daily o where o.source = s.source order by o.trade_date desc limit 1) as last_bar
      from s)
  select l.source,
         l.last_bar::text,
         (current_date - l.last_bar)::int,
         coalesce(r.n_crypto_win, 0),
         coalesce(r.n_tradfi_win, 0),
         b.n_typical
  from last_seen l
  left join recent   r on r.source = l.source
  left join baseline b on b.source = l.source
  order by (current_date - l.last_bar) desc;
$function$;
