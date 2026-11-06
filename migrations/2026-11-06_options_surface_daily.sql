-- 2026-11-06 · options_surface_daily: Deribit option surface features + the price of a hedge (forward-only; no free history).
create table if not exists public.options_surface_daily (
  d date not null, currency text not null, spot double precision,
  atm_iv_7d double precision, atm_iv_30d double precision, atm_iv_90d double precision, term_slope double precision,
  skew_30d double precision, pc_oi_ratio double precision, pc_vol_ratio double precision,
  put90_30d_cost_pct double precision, put_spread_90_80_30d_cost_pct double precision,
  total_oi_usd double precision, n_options integer, fetched_at timestamptz not null default now(),
  primary key (d, currency)
);
alter table public.options_surface_daily enable row level security;
grant select on public.options_surface_daily to anon;
drop policy if exists lane_read on public.options_surface_daily;
create policy lane_read on public.options_surface_daily for select to anon using (true);
