-- 2026-11-07 · S-763 / S-758 ✅ 之后:Binance 现货上币 / USDT 永续上线的前向记录(src/data/signals/event_watch.py)。
-- 一个 (类别, 代号) 一行;cohort = forward(11-07 起的新公告,前向证据)/ backfill(之前,只作对照)。
create table if not exists public.binance_event_watch (
  kind          text not null check (kind in ('listing', 'perp_listing')),
  symbol        text not null,
  announced_at  timestamptz not null,
  d0            date not null,
  title         text,
  cohort        text not null check (cohort in ('forward', 'backfill')),
  excess_30d    double precision,
  excess_90d    double precision,
  price_source  text,
  code_ref      text not null,
  settled_at    timestamptz,
  created_at    timestamptz not null default now(),
  primary key (kind, symbol)
);
create index if not exists binance_event_watch_announced on public.binance_event_watch (announced_at desc);
alter table public.binance_event_watch enable row level security;
grant select on public.binance_event_watch to anon;
drop policy if exists lane_read on public.binance_event_watch;
create policy lane_read on public.binance_event_watch for select to anon using (true);
