-- 2026-10-22 · R-v2 每张票开票当时的基本面标签(S-665 的前向):90 日流通量增长(稀释)。
--
-- S-665:开在高稀释币上的 R-v2 票平均少赚约一半(低 − 高 +0.54R,年内打乱 p 0.022,两段同号;最高三分位
-- = 一个季度流通量涨 > 2.2%,平均 +0.28R vs 其余 +0.66R)。实盘还不跳过;先给每张新票打标签,前向按同一切法对比。
-- 流通量 = asset_mcap_daily 的 市值 ÷ 价格(CoinGecko),按 symbol 接(同 symbol 取当日市值最大的 coin_id)。

create table if not exists public.r_ticket_tags (
  ticket_id    text primary key,
  symbol       text not null,
  signal_d     date not null,
  coin_id      text,
  supply_t     double precision,
  supply_t90   double precision,
  dil90        double precision,
  why_missing  text,
  rule         text not null default 'S-665',
  computed_at  timestamptz not null default now()
);
create index if not exists r_ticket_tags_signal_idx on public.r_ticket_tags (signal_d);
alter table public.r_ticket_tags enable row level security;
grant select on public.r_ticket_tags to anon;
drop policy if exists lane_read on public.r_ticket_tags;
create policy lane_read on public.r_ticket_tags for select to anon using (true);
