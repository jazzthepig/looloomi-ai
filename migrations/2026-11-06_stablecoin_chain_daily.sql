-- 2026-11-06 · stablecoin_chain_daily: USD-pegged stablecoin supply per chain (DeFiLlama). One-time history backfill
-- (one chart per chain, 6 chains) + one all-chains snapshot request per round.
create table if not exists public.stablecoin_chain_daily (
  d date not null, chain text not null, circulating_usd double precision not null, source text not null,
  fetched_at timestamptz not null default now(), primary key (d, chain)
);
alter table public.stablecoin_chain_daily enable row level security;
grant select on public.stablecoin_chain_daily to anon;
drop policy if exists lane_read on public.stablecoin_chain_daily;
create policy lane_read on public.stablecoin_chain_daily for select to anon using (true);
