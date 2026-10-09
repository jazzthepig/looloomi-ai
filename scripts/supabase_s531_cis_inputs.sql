-- S-531 / T-079 — CIS 统一标准:补缺的维度(docs/CIS_STANDARD.md §4)。
-- asset_mcap_daily.volume  CG market_chart 的 24 小时全市场成交额(d 当天),此前被丢掉
-- macro_daily              长表:恐惧贪婪(alternative.me)、VIX(EODHD)、全市场市值 / 成交(CG global)
-- protocol_tvl_daily       DeFi 协议 TVL 历史(DeFiLlama /protocol)
-- S-167 姿态:RLS 开、零 policy、只授 service_role。AS APPLIED 2026-10-09(migration s531_cis_inputs)。
alter table public.asset_mcap_daily add column if not exists volume double precision;

create table if not exists public.macro_daily (
  series      text not null,
  d           date not null,
  value       double precision not null,
  source      text not null,
  computed_at timestamptz not null default now(),
  primary key (series, d)
);
alter table public.macro_daily enable row level security;
revoke all on public.macro_daily from anon, authenticated;
grant select, insert, update, delete on public.macro_daily to service_role;

create table if not exists public.protocol_tvl_daily (
  protocol    text not null,
  d           date not null,
  symbol      text,
  gecko_id    text,
  tvl_usd     double precision not null,
  source      text not null,
  computed_at timestamptz not null default now(),
  primary key (protocol, d)
);
alter table public.protocol_tvl_daily enable row level security;
revoke all on public.protocol_tvl_daily from anon, authenticated;
grant select, insert, update, delete on public.protocol_tvl_daily to service_role;
