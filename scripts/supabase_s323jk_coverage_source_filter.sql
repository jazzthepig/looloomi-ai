-- S-323j + S-323k + VACUUM (2026-09-09) — applied to production as migrations
-- `s323j_push_source_filter_into_coverage` and
-- `s323k_make_the_source_filter_sargable`.
--
-- MEASURED FIRST, twice, because the first attempt made it worse:
--
--     baseline (S-323e wrapper)                 1720 ms   7904 buffers
--     S-323j  `where p_source is null or ...`   3187 ms   7900 buffers  <- WORSE
--     S-323k  branch + quote_literal            2027 ms   7935 buffers
--     + VACUUM (ANALYZE) ohlcv_daily            1315 ms   2406 buffers
--
-- WHAT I GOT WRONG, IN ORDER.
--
-- 1. S-323e's header called this wrapper "the narrow surface (262 rows)".
--    Narrow OUTPUT is not cheap EXECUTION. ohlcv_symbol_coverage() is an
--    unfiltered `group by symbol, source` over the whole table; the wrapper
--    discarded every source but binance_hist AFTER paying for all of them.
--    Row count describes the response. Buffers describe the cost. I checked
--    the first and wrote a claim about the second.
--
-- 2. S-323j pushed the predicate into the query text and I assumed that made
--    it a predicate the INDEX could serve. `p_source is null or source =
--    p_source` is not sargable. **Buffers did not move** — that number, not
--    the timing, is what said the plan had not changed at all.
--
-- 3. S-323k made it sargable with a literal. Buffers STILL did not move, which
--    finally forced the question I should have asked first:
--
--        binance_hist = 386,257 rows = 71.3% of ohlcv_daily
--
--    A predicate selecting 71% of a table cannot be served by an index; the
--    seq scan was the CORRECT plan the whole time. Three migrations chasing an
--    index that was never going to be chosen, because I never measured the
--    selectivity of the filter I was adding.
--
-- 4. What actually helped was maintenance, not planning. `Heap Fetches:
--    386257` on an "Index Only Scan" means the visibility map was cold, so
--    every row still touched the heap. VACUUM (ANALYZE) cut buffers 7904 ->
--    2406 (3.3x).
--
-- STILL ~1.3 s, AND THAT IS NOT THE LOOP'S BLOCKER. The circuit breaker reads
-- `open=false, consecutive_failures=0, lifetime_trips=0` — a timeout would
-- have incremented failures, so the app was never timing out here. Confirmed
-- independently: anon and publishable keys both return HTTP 200 / 262 rows.
-- The panel loop was not failing, it was ASLEEP (see S-323l) — the heartbeat
-- has no last-failure timestamp, so "failed 9h ago and waiting" and "failing
-- now" are the same record, and I nearly optimised a cause I had not confirmed
-- for the sixth time in this chain.
--
-- The S-323 no-drift property is preserved: the aggregation formula still
-- appears exactly once (in v_base); only the predicate varies.

drop function if exists public.ohlcv_symbol_coverage();

create or replace function public.ohlcv_symbol_coverage(p_source text default null)
returns table(symbol text, source text, n bigint, first_date text, last_date text)
language plpgsql
stable
set search_path to 'public'
as $$
declare
  v_base constant text :=
    'select symbol::text, source::text, count(*)::bigint,
            min(trade_date)::text, max(trade_date)::text
     from public.ohlcv_daily';
  v_tail constant text := ' group by symbol, source';
begin
  if p_source is null then
    return query execute v_base || v_tail;
  else
    return query execute
      v_base || ' where source = ' || quote_literal(p_source) || v_tail;
  end if;
end $$;

revoke all on function public.ohlcv_symbol_coverage(text) from public;
grant execute on function public.ohlcv_symbol_coverage(text) to service_role;

create or replace function public.deep_panel_symbol_list()
returns table(symbol text, n_rows bigint, latest text)
language sql
stable
security definer
set search_path to 'public'
as $$
  select c.symbol, c.n, c.last_date
  from public.ohlcv_symbol_coverage('binance_hist') c
  order by c.symbol
$$;

revoke all on function public.deep_panel_symbol_list() from public;
grant execute on function public.deep_panel_symbol_list() to anon, authenticated, service_role;

notify pgrst, 'reload schema';

-- ⚠️ ohlcv_daily needs periodic VACUUM for the visibility map, or the index-only
-- scan degrades back to full heap fetches. Supabase autovacuum should cover it;
-- if this function creeps back above ~2 s, check `Heap Fetches` in EXPLAIN
-- before touching the query — that number, not the timing, names the cause.
