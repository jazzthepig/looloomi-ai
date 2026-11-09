-- 2026-11-09 · S-794 头部账户的完整持仓(src/exec_host/liqmap.positioning 主机算、src/data/market/liq_map.write_positioning 收):
-- Hyperliquid 30 天盈利前 200、净值 ≥ 100 万美元的账户(T-130 whales),每小时一份,每币多 / 空名义额与仓位数;不含地址。
-- 与 hl_liq_map_hourly 同一批快照;那张只收强平价 20% 以内的仓位(强平风险),这张不分距离(谁押了什么)。
create table if not exists public.hl_whale_positioning_hourly (
  ts                 timestamptz not null,
  coin               text not null,
  long_usd           double precision not null,
  short_usd          double precision not null,
  n_long             integer not null default 0,
  n_short            integer not null default 0,
  n_accounts         integer not null default 0,
  mark               double precision,
  snapshot_accounts  integer,
  created_at         timestamptz not null default now(),
  primary key (ts, coin)
);
create index if not exists hl_whale_positioning_hourly_coin_ts on public.hl_whale_positioning_hourly (coin, ts desc);
alter table public.hl_whale_positioning_hourly enable row level security;
revoke all on public.hl_whale_positioning_hourly from anon, authenticated;
