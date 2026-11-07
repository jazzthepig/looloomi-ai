-- 2026-11-07 · S-751 ✅(lane-b T-272)落地:Binance 整币下架公告的观察名单 + 前向记录(src/data/signals/delisting_watch.py)。
-- 一个代币一行(第一次公告);kind = forward(2026-11-07 起,前向证据)/ backfill(之前,只作对照)。
create table if not exists public.delisting_watch (
  symbol        text primary key,
  announced_at  timestamptz not null,
  d0            date not null,
  title         text,
  kind          text not null check (kind in ('forward', 'backfill')),
  excess_7d     double precision,
  excess_30d    double precision,
  ret_30d       double precision,
  btc_30d       double precision,
  price_source  text,
  code_ref      text not null,
  settled_at    timestamptz,
  created_at    timestamptz not null default now()
);
create index if not exists delisting_watch_announced on public.delisting_watch (announced_at desc);
alter table public.delisting_watch enable row level security;
grant select on public.delisting_watch to anon;
drop policy if exists lane_read on public.delisting_watch;
create policy lane_read on public.delisting_watch for select to anon using (true);
