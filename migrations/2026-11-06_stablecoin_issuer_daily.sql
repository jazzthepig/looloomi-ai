-- 2026-11-06 · stablecoin_issuer_daily: circulating supply by issuer (DeFiLlama), the mint / redeem flow per issuer.
create table if not exists public.stablecoin_issuer_daily (
  d date not null, coin text not null, circulating_usd double precision not null, source text,
  computed_at timestamptz not null default now(), primary key (d, coin)
);
alter table public.stablecoin_issuer_daily enable row level security;
grant select on public.stablecoin_issuer_daily to anon;
drop policy if exists lane_read on public.stablecoin_issuer_daily;
create policy lane_read on public.stablecoin_issuer_daily for select to anon using (true);
