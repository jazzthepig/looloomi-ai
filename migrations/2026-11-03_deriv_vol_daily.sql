-- 2026-11-03 · deriv_vol_daily: Deribit DVOL (30-day implied volatility index) daily OHLC for BTC / ETH since 2021-03.
-- Input to the ③ daily decision (level + 1y percentile) and the data for S-710 (DVOL as a reduce rule, replayed by lane-c).
create table if not exists public.deriv_vol_daily (
  d           date not null,
  currency    text not null,
  dvol_open   double precision,
  dvol_high   double precision,
  dvol_low    double precision,
  dvol_close  double precision not null,
  source      text not null default 'deribit',
  recorded_at timestamptz not null default now(),
  primary key (d, currency)
);
alter table public.deriv_vol_daily enable row level security;
grant select on public.deriv_vol_daily to anon;
drop policy if exists lane_read on public.deriv_vol_daily;
create policy lane_read on public.deriv_vol_daily for select to anon using (true);
