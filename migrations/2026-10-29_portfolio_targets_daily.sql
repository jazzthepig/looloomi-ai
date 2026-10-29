-- 2026-10-29 · 组合层目标表(SPINE 7b,docs/PORTFOLIO_LAYER_DESIGN.md,src/data/execution/portfolio_layer.py)。
-- Jazz 10-29:T25 真钱起始 600 USDC;黄金 XAUT;R-v2 名义合计 ≤ 净值 30%;21 交易日或偏离 > 5pp 再平衡。
-- 每天一份、写一次不改(前向记录)。执行器读的是同一个函数(/internal/executor/plan 的 `portfolio`)。
-- 只给 service_role:目标里有资本额,不对 publishable key 开放(规则 8)。
create table if not exists public.portfolio_targets_daily (
  d                date not null,
  book             text not null,               -- 't25_live'
  sleeve           text not null,               -- crypto_x1v / equity / gold / cash / rv2
  kind             text not null check (kind in ('weight', 'gross_cap')),
  target_w         double precision,            -- weight:占 T25 的比例;gross_cap:R-v2 名义 ÷ 账户净值的上限
  target_usd       double precision,            -- weight 腿的美元额度(gross_cap 为空)
  capital_usd      double precision not null,   -- 定额度用的 T25 资本
  instrument       text,
  venue            text,
  executable       boolean not null,            -- 现在有没有执行器在执行这条腿
  why              text,
  next_rebalance_d date,
  rule             text not null,
  written_at       timestamptz not null default now(),
  primary key (d, book, sleeve)
);
alter table public.portfolio_targets_daily enable row level security;
revoke all on public.portfolio_targets_daily from anon, authenticated;
