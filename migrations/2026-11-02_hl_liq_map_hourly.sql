-- 2026-11-02 · T-221 强平地图(src/exec_host/liqmap.py 主机算、src/data/market/liq_map.py 收):头部账户持仓按强平价离现价的距离分档汇总,
-- 每小时一份;不含地址。读的时候配永续 ±2% 深度(venue_depth_snapshots)。
create table if not exists public.hl_liq_map_hourly (
  ts            timestamptz not null,
  coin          text not null,
  side          text not null check (side in ('long', 'short')),
  band          text not null,
  band_lo       double precision,
  band_hi       double precision,
  notional_usd  double precision not null,
  n_positions   integer not null default 0,
  mark          double precision,
  primary key (ts, coin, side, band)
);
alter table public.hl_liq_map_hourly enable row level security;
revoke all on public.hl_liq_map_hourly from anon, authenticated;
