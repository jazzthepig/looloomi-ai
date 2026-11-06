-- 2026-11-06 · derivatives_market_daily: CoinGecko /derivatives aggregated per underlying (all ~100 venues): OI, volume, OI-weighted basis. Forward-only.
create table if not exists public.derivatives_market_daily (
  d date not null, symbol text not null, oi_usd double precision not null, volume_24h_usd double precision, n_markets integer,
  basis_oiw_pct double precision, top_market text, top_funding_raw double precision,
  fetched_at timestamptz not null default now(), primary key (d, symbol)
);
alter table public.derivatives_market_daily enable row level security;
grant select on public.derivatives_market_daily to anon;
drop policy if exists lane_read on public.derivatives_market_daily;
create policy lane_read on public.derivatives_market_daily for select to anon using (true);
