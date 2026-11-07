-- 2026-11-07 · 韩国散户数据(src/data/market/korea_retail.py):Upbit KRW 市场日线 + Upbit 自己的市场标签(每天记,当天见过就算)。
-- 公告写进已有的 events(source = 'upbit'),这里不建表。
create table if not exists public.upbit_daily (
  market       text not null,
  symbol       text not null,
  d            date not null,
  o            double precision,
  h            double precision,
  l            double precision,
  c            double precision,
  vol_base     double precision,
  vol_krw      double precision,
  recorded_at  timestamptz not null default now(),
  primary key (market, d)
);
create index if not exists upbit_daily_symbol_d on public.upbit_daily (symbol, d);
create index if not exists upbit_daily_d on public.upbit_daily (d);
alter table public.upbit_daily enable row level security;
grant select on public.upbit_daily to anon;
drop policy if exists lane_read on public.upbit_daily;
create policy lane_read on public.upbit_daily for select to anon using (true);

create table if not exists public.upbit_market_event_daily (
  d             date not null,
  market        text not null,
  symbol        text not null,
  warning       boolean not null default false,
  caution       jsonb not null default '{}'::jsonb,
  n_caution     int not null default 0,
  last_seen_at  timestamptz not null default now(),
  primary key (d, market)
);
create index if not exists upbit_market_event_symbol on public.upbit_market_event_daily (symbol, d);
alter table public.upbit_market_event_daily enable row level security;
grant select on public.upbit_market_event_daily to anon;
drop policy if exists lane_read on public.upbit_market_event_daily;
create policy lane_read on public.upbit_market_event_daily for select to anon using (true);
