-- 上游通道(CoinGecko Analyst):分类发现 / 成员市值历史 / 通道日度序列。S-167 姿态。
create table if not exists public.channel_categories (
  category_id text not null, channel text not null, discovered_d date not null,
  recorded_at timestamptz not null default now(), primary key (category_id, discovered_d));
create table if not exists public.cg_coin_mcap_daily (
  coin_id text not null, d date not null, price double precision, mcap double precision,
  source text not null, recorded_at timestamptz not null default now(), primary key (coin_id, d));
create table if not exists public.channel_series_daily (
  d date not null, channel text not null, category_id text not null, mcap double precision,
  n_members integer, basis text, code_ref text, computed_at timestamptz not null default now(),
  primary key (d, channel, category_id));
alter table public.channel_categories enable row level security;
alter table public.cg_coin_mcap_daily enable row level security;
alter table public.channel_series_daily enable row level security;
revoke all on public.channel_categories, public.cg_coin_mcap_daily, public.channel_series_daily from anon, authenticated;
grant select, insert, update, delete on public.channel_categories, public.cg_coin_mcap_daily, public.channel_series_daily to service_role;
