-- S-323 (2026-09-08) — applied to production as migration
-- `s323_ohlcv_source_index_and_panel_symbol_list`.
--
-- WHY. `ohlcv_daily` (~464k rows) had exactly two indexes: the pk on `id`, and
-- the unique key on (symbol, trade_date, source). Nothing led with `source`, so
-- every grouped read filtered on source was a parallel seq scan of the whole
-- table. Measured 2026-09-08, warm and idle:
--
--     deep_panel_symbol_list()      3476 ms
--     refresh_depth_divergence()    5518 ms
--
-- PostgREST runs anon/authenticated with `statement_timeout = 8s`
-- (service_role gets 30s). Warm and idle those two fit under 8s. Under
-- production I/O contention they do not — PostgREST answers 5xx, the client
-- retries three times, and `supabase_rpc_write` reports:
--
--     "no response from Supabase after retries"
--
-- That string describes the symptom (silence) and hides the cause (the query
-- was too slow to finish), which is why `_forward_record_loop` failed nine
-- consecutive rounds without anyone learning anything from the message.
--
-- After the index: 181 ms and 1367 ms. 19x and 4x.
--
-- The index is created CONCURRENTLY in production (done via a direct statement,
-- since CREATE INDEX CONCURRENTLY cannot run inside the migration transaction);
-- the IF NOT EXISTS form below is the idempotent record of it.
create index if not exists ohlcv_daily_source_symbol_date_idx
  on public.ohlcv_daily (source, symbol, trade_date);

-- ── The panel's symbol list ──────────────────────────────────────────────────
-- Deliberately a FILTERED WRAPPER over `ohlcv_symbol_coverage()` (S-276) and not
-- a second grouping of the same table. Two implementations of one quantity drift;
-- this session spent its length removing exactly that shape and then nearly added
-- one here.
--
-- The wrapper is also the narrower object: 262 rows instead of 591. That matters
-- because PostgREST silently caps responses at 1000 rows and returns 200, so a
-- 591-row read is not far from becoming a truncated one that never says so.
create or replace function public.deep_panel_symbol_list()
returns table(symbol text, n_rows bigint, latest text)
language sql stable set search_path to 'public' as $$
  select c.symbol, c.n, c.last_date
  from public.ohlcv_symbol_coverage() c
  where c.source = 'binance_hist'
  order by c.symbol
$$;
grant execute on function public.deep_panel_symbol_list() to anon, authenticated, service_role;

-- ── Exact forward-return coverage ────────────────────────────────────────────
-- `coverage_report()` used to pull rows with `limit=10000` and count them in
-- Python. PostgREST truncated that to 1000 of 1759 eligible rows and returned
-- 200, so `coverage_pct` — the number that gates whether an IC may be reported
-- at all — was a statistic computed on an arbitrary slice and presented as the
-- population figure. Numerator and denominator were rewritten by the same
-- truncation, so the ratio always looked plausible and no single number ever
-- looked wrong. True coverage that day: 92.0%.
create or replace function public.forward_return_coverage(p_horizon int default 7)
returns table(eligible_rows bigint, measured_rows bigint,
              measured_days bigint, unmeasured_symbols text[])
language sql stable set search_path to 'public' as $$
  select count(*)::bigint,
         count(realized_return_7d)::bigint,
         count(distinct case when realized_return_7d is not null
                             then entry_time::date end)::bigint,
         coalesce(array_agg(distinct symbol)
                  filter (where realized_return_7d is null), '{}')
  from trade_results
  where entry_time <= (now() at time zone 'utc')::date - (p_horizon || ' days')::interval
$$;
grant execute on function public.forward_return_coverage(int) to anon, authenticated, service_role;
