-- S-513 / T-066 — 状态层补流量维度。
-- stable_lending_daily   Aave v2 / v3 以太坊上 USDC、USDT 借贷池的日度 TVL 与存款 APY(DeFiLlama yields /chart)
--                        —— 稳定币**被借走去加杠杆**的需求;总量增长会骗人(S-508),借贷利率不会
-- v_taker_share_daily    BTC / ETH / SOL 小时线主动买量的日汇总(视图:状态层不必每轮读 15 万行小时线)
-- S-167 姿态:RLS 开、零 policy、只授 service_role。AS APPLIED 2026-10-08(migration s513_flow_state)。
create table if not exists public.stable_lending_daily (
  d           date not null,
  pool_id     text not null,
  project     text not null,
  chain       text not null,
  symbol      text not null,
  tvl_usd     double precision,
  apy_base    double precision,
  source      text not null,
  computed_at timestamptz not null default now(),
  primary key (d, pool_id)
);
alter table public.stable_lending_daily enable row level security;
revoke all on public.stable_lending_daily from anon, authenticated;
grant select, insert, update, delete on public.stable_lending_daily to service_role;

create or replace view public.v_taker_share_daily with (security_invoker = true) as
select (ts at time zone 'UTC')::date as d,
       sum(taker_buy_base * close) as taker_buy_quote,
       sum(volume * close)         as quote_volume,
       count(*)                    as n_bars
from public.ohlcv_hourly
where source = 'binance_hist' and symbol in ('BTC', 'ETH', 'SOL') and taker_buy_base is not null
group by 1;
revoke all on public.v_taker_share_daily from anon, authenticated;
grant select on public.v_taker_share_daily to service_role;
