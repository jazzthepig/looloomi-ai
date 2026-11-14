-- 2026-11-14 · funding_daily: the daily funding aggregate becomes a trigger-maintained table (S-860).
-- 已通过 Supabase MCP 施加,两步:funding_daily_table_and_sync_trigger → v_funding_daily_reads_funding_daily。
--
-- WHY. v_funding_daily was `GROUP BY symbol, UTC day` over all of funding_history (2.66M binance_perp rows), and every page of
-- every paginated read recomputed it. pg_stat_statements since 2026-09-24: 224,115 calls x 1.08 s mean = 241,160 s,
-- 42% of ALL database time. One page at offset 200,000 took 2,459 ms; a full read from 2022-11 is ~590 pages.
--
-- WHAT. The same aggregate lives in public.funding_daily, kept current by statement-level triggers on funding_history
-- (insert / update / delete, transition tables): only the (symbol, day) pairs a statement touched are recomputed.
-- v_funding_daily now selects from the table, so every reader (code, lanes, asset_flow_daily_live) is unchanged.
--
-- CHECKED BEFORE THE VIEW WAS REPOINTED (old view vs table): 590,570 rows each, none on one side only, n equal everywhere,
-- max |rate difference| 1.7e-18. Trigger exercised inside a rolled-back block: insert, upsert-update, a row moved to the
-- next day, delete — each left the daily row as expected; another venue's row was ignored. Same page after: 283 ms.
--
-- LIVENESS (should return 0). Both sides start at a UTC day boundary: the first version cut the history side at
-- `now() - 3 days` (mid-day) and compared that partial day with the table's whole day — 35 false mismatches on first use (S-862).
--   select count(*) from (
--     select symbol, (funding_time at time zone 'UTC')::date d, avg(funding_rate) fr, count(*) n
--     from funding_history where venue = 'binance_perp' and funding_time >= (now() - interval '3 days')::date group by 1, 2) a
--   full join (select * from funding_daily where d >= (now() - interval '3 days')::date) b using (symbol, d)
--   where a.n is distinct from b.n or abs(a.fr - b.funding_rate) > 1e-12;
-- A failing trigger makes the funding write itself fail (loud, visible in loop_attempt) rather than letting the table drift.

create table if not exists public.funding_daily (
  symbol       text             not null,
  d            date             not null,
  funding_rate double precision not null,
  n            bigint           not null,
  updated_at   timestamptz      not null default now(),
  primary key (symbol, d)
);
create index if not exists funding_daily_d_idx on public.funding_daily (d);

alter table public.funding_daily enable row level security;
drop policy if exists lane_read on public.funding_daily;
create policy lane_read on public.funding_daily for select to anon using (true);
grant select on public.funding_daily to anon, authenticated;
grant all on public.funding_daily to service_role;

create or replace function public.funding_daily_recompute(p_symbols text[], p_days date[])
returns void language sql security definer set search_path = public as $$
  with touched as (
    select distinct s as symbol, dd as d from unnest(p_symbols, p_days) as t(s, dd)
  ), agg as (
    select t.symbol, t.d, avg(f.funding_rate) as funding_rate, count(f.funding_rate) as n
    from touched t
    left join public.funding_history f
      on f.symbol = t.symbol and f.venue = 'binance_perp'
     and f.funding_time >= (t.d::timestamp at time zone 'UTC')
     and f.funding_time <  ((t.d + 1)::timestamp at time zone 'UTC')
    group by t.symbol, t.d
  ), gone as (
    delete from public.funding_daily fd using agg a
    where fd.symbol = a.symbol and fd.d = a.d and a.n = 0
    returning 1
  )
  insert into public.funding_daily (symbol, d, funding_rate, n, updated_at)
  select symbol, d, funding_rate, n, now() from agg where n > 0
  on conflict (symbol, d) do update
    set funding_rate = excluded.funding_rate, n = excluded.n, updated_at = now()
    where funding_daily.funding_rate is distinct from excluded.funding_rate or funding_daily.n is distinct from excluded.n;
$$;

create or replace function public.funding_daily_sync() returns trigger
language plpgsql security definer set search_path = public as $$
declare
  syms text[];
  days date[];
begin
  if tg_op = 'INSERT' then
    select array_agg(symbol), array_agg(d) into syms, days from (
      select distinct symbol, (funding_time at time zone 'UTC')::date as d from new_rows where venue = 'binance_perp') x;
  elsif tg_op = 'UPDATE' then
    select array_agg(symbol), array_agg(d) into syms, days from (
      select symbol, (funding_time at time zone 'UTC')::date as d from new_rows where venue = 'binance_perp'
      union
      select symbol, (funding_time at time zone 'UTC')::date as d from old_rows where venue = 'binance_perp') x;
  else
    select array_agg(symbol), array_agg(d) into syms, days from (
      select distinct symbol, (funding_time at time zone 'UTC')::date as d from old_rows where venue = 'binance_perp') x;
  end if;
  if syms is not null then
    perform public.funding_daily_recompute(syms, days);
  end if;
  return null;
end $$;

revoke all on function public.funding_daily_recompute(text[], date[]) from public, anon, authenticated;
revoke all on function public.funding_daily_sync() from public, anon, authenticated;

drop trigger if exists funding_daily_sync_ins on public.funding_history;
drop trigger if exists funding_daily_sync_upd on public.funding_history;
drop trigger if exists funding_daily_sync_del on public.funding_history;
create trigger funding_daily_sync_ins after insert on public.funding_history
  referencing new table as new_rows for each statement execute function public.funding_daily_sync();
create trigger funding_daily_sync_upd after update on public.funding_history
  referencing old table as old_rows new table as new_rows for each statement execute function public.funding_daily_sync();
create trigger funding_daily_sync_del after delete on public.funding_history
  referencing old table as old_rows for each statement execute function public.funding_daily_sync();

insert into public.funding_daily (symbol, d, funding_rate, n)
select symbol, (funding_time at time zone 'UTC')::date, avg(funding_rate), count(*)
from public.funding_history where venue = 'binance_perp'
group by symbol, (funding_time at time zone 'UTC')::date
on conflict (symbol, d) do update set funding_rate = excluded.funding_rate, n = excluded.n, updated_at = now();

-- step two, after the comparison above passed
create or replace view public.v_funding_daily with (security_invoker = on) as
  select symbol, d, funding_rate, n from public.funding_daily;
