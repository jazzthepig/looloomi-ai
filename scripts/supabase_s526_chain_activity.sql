-- S-526 / T-076 — 链的景气读数:TVL、手续费、DEX 成交量(DeFiLlama,日度,UTC 日期)。
-- 用途:预期差 = 基本面动量 − 价格动量;价格从 asset_mcap_daily 按 gecko_id 对上(不在这里存价格)。
-- S-167 姿态:RLS 开、零 policy、只授 service_role。AS APPLIED 2026-10-08(migration s526_chain_activity)。
create table if not exists public.chain_activity_daily (
  chain          text not null,
  d              date not null,
  gecko_id       text not null,
  symbol         text,
  tvl_usd        double precision,
  fees_usd       double precision,
  dex_volume_usd double precision,
  source         text not null,
  computed_at    timestamptz not null default now(),
  primary key (chain, d)
);
create index if not exists chain_activity_daily_d on public.chain_activity_daily (d);
create index if not exists chain_activity_daily_gecko on public.chain_activity_daily (gecko_id, d);
alter table public.chain_activity_daily enable row level security;
revoke all on public.chain_activity_daily from anon, authenticated;
grant select, insert, update, delete on public.chain_activity_daily to service_role;
