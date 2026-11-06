-- 2026-11-06 · cex_reserves_daily: DeFiLlama /cexs snapshot per exchange (reserves ex-own-token, net inflows, OI, leverage). Forward-only.
create table if not exists public.cex_reserves_daily (
  d date not null, exchange text not null, clean_assets_usd double precision not null, total_assets_usd double precision,
  inflow_24h_usd double precision, inflow_1w_usd double precision, inflow_1m_usd double precision, oi_usd double precision,
  leverage double precision, spot_volume_usd double precision, deriv_volume_usd double precision,
  fetched_at timestamptz not null default now(), primary key (d, exchange)
);
alter table public.cex_reserves_daily enable row level security;
grant select on public.cex_reserves_daily to anon;
drop policy if exists lane_read on public.cex_reserves_daily;
create policy lane_read on public.cex_reserves_daily for select to anon using (true);
