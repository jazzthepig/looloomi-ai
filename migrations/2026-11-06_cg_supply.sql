-- 2026-11-06 · coin_supply_daily (CoinGecko Analyst supply_breakdown: circulating vs locked, per coin per day, forward-only)
-- and cg_new_coins (/coins/list/new: when each coin was activated on CoinGecko; first_seen_at never overwritten).
create table if not exists public.coin_supply_daily (
  d date not null,
  coin_id text not null,
  total_supply double precision not null,
  circulating_supply double precision not null,
  non_circulating_supply double precision,
  n_wallets integer,
  anomaly boolean,
  cg_updated_at timestamptz,
  fetched_at timestamptz not null default now(),
  primary key (d, coin_id)
);
alter table public.coin_supply_daily enable row level security;
grant select on public.coin_supply_daily to anon;
drop policy if exists lane_read on public.coin_supply_daily;
create policy lane_read on public.coin_supply_daily for select to anon using (true);

create table if not exists public.cg_new_coins (
  coin_id text primary key,
  symbol text,
  name text,
  activated_at timestamptz not null,
  first_seen_at timestamptz not null default now()
);
create index if not exists cg_new_coins_activated on public.cg_new_coins (activated_at);
alter table public.cg_new_coins enable row level security;
grant select on public.cg_new_coins to anon;
drop policy if exists lane_read on public.cg_new_coins;
create policy lane_read on public.cg_new_coins for select to anon using (true);

-- cg_category_daily: /coins/categories once per round (~600 categories), forward-only narrative-layer history.
create table if not exists public.cg_category_daily (
  d date not null,
  category_id text not null,
  name text,
  market_cap double precision not null,
  volume_24h double precision,
  mcap_change_24h_pct double precision,
  top3 jsonb,
  fetched_at timestamptz not null default now(),
  primary key (d, category_id)
);
alter table public.cg_category_daily enable row level security;
grant select on public.cg_category_daily to anon;
drop policy if exists lane_read on public.cg_category_daily;
create policy lane_read on public.cg_category_daily for select to anon using (true);
