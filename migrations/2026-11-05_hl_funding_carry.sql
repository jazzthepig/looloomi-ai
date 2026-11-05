-- 2026-11-05 · S-733 ④ carry: HL realized hourly funding (fundingHistory) + the forward paper book.
-- hl_funding_hourly is NOT funding_history(venue=hyperliquid): that one is irregular metaAndAssetCtxs snapshots of the
-- predicted rate; this one is HL's settled hourly rate. Two series, two tables.
create table if not exists public.hl_funding_hourly (
  coin        text not null,
  t           timestamptz not null,
  rate        double precision not null,
  premium     double precision,
  fetched_at  timestamptz not null default now(),
  primary key (coin, t)
);
alter table public.hl_funding_hourly enable row level security;
grant select on public.hl_funding_hourly to anon;
drop policy if exists lane_read on public.hl_funding_hourly;
create policy lane_read on public.hl_funding_hourly for select to anon using (true);

create or replace view public.hl_funding_hourly_last with (security_invoker = true) as
  select coin, min(t) first_t, max(t) last_t, count(*) n from public.hl_funding_hourly group by coin;
create or replace view public.hl_funding_daily with (security_invoker = true) as
  select coin, (t at time zone 'utc')::date d, sum(rate) rate_sum, count(*) n_hours from public.hl_funding_hourly group by 1, 2;
grant select on public.hl_funding_hourly_last, public.hl_funding_daily to anon;

create table if not exists public.carry_hl_daily (
  d            date not null,
  arm          text not null,
  ret          double precision not null,
  nav          double precision not null,
  n_names      integer,
  n_on         integer,
  switches     integer,
  inception    date,
  code_ref     text,
  computed_at  timestamptz not null default now(),
  primary key (d, arm)
);
alter table public.carry_hl_daily enable row level security;
grant select on public.carry_hl_daily to anon;
drop policy if exists lane_read on public.carry_hl_daily;
create policy lane_read on public.carry_hl_daily for select to anon using (true);
