-- 2026-10-22 · 协议收入 / 持币人收入的每日快照(DeFiLlama 概览,两次请求覆盖全部协议)—— 台账 S-661。
--
-- S-661:持币人收入 ÷ 协议收入(价值捕获比)在留出段 2024–26 IC +0.086、t 3.45、三分位差每月 +10.7%;
-- 30 / 60 / 90 天窗口结果几乎一样,所以只存概览自带的 24h / 30d / 前 30 天三段。每天一行 / 母协议。
-- 公开数据,lane 可读(publishable key = anon,只读);写入只走 Railway 的 secret key。

create table if not exists public.protocol_revenue_daily (
  slug             text not null,
  d                date not null,
  gecko_id         text,
  name             text,
  category         text,
  revenue_24h      double precision not null default 0,
  revenue_30d      double precision not null default 0,
  revenue_60to30d  double precision not null default 0,
  holders_24h      double precision not null default 0,
  holders_30d      double precision not null default 0,
  holders_60to30d  double precision not null default 0,
  recorded_at      timestamptz not null default now(),
  primary key (slug, d)
);
create index if not exists protocol_revenue_daily_d_idx on public.protocol_revenue_daily (d, gecko_id);
alter table public.protocol_revenue_daily enable row level security;
grant select on public.protocol_revenue_daily to anon;
drop policy if exists lane_read on public.protocol_revenue_daily;
create policy lane_read on public.protocol_revenue_daily for select to anon using (true);
