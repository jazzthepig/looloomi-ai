-- 2026-11-07 · 散户投机热度(src/data/market/degen_activity.py):Meme 发射台 / Telegram 机器人 / 散户交易 App 的每日手续费(DeFiLlama)。
create table if not exists public.degen_fees_daily (
  slug         text not null,
  name         text,
  category     text not null,
  d            date not null,
  fees_usd     double precision not null,
  recorded_at  timestamptz not null default now(),
  primary key (slug, d)
);
create index if not exists degen_fees_daily_d on public.degen_fees_daily (d);
alter table public.degen_fees_daily enable row level security;
grant select on public.degen_fees_daily to anon;
drop policy if exists lane_read on public.degen_fees_daily;
create policy lane_read on public.degen_fees_daily for select to anon using (true);
