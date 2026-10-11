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

-- S-531 补(10-11,migration s531d_equity_fundamentals):美股单票每季 EPS / 营收与**可得日**(EPS 公布日,没有则报送日)。
-- 重建按可得日复原 PE(价格 / 近四季 EPS)与营收同比 —— 只用 d 当天已经公布的季度。
create table if not exists public.equity_fundamentals_q (
  symbol      text not null,
  period_end  date not null,
  available_d date not null,
  eps         double precision,
  revenue     double precision,
  source      text not null,
  computed_at timestamptz not null default now(),
  primary key (symbol, period_end)
);
alter table public.equity_fundamentals_q enable row level security;
revoke all on public.equity_fundamentals_q from anon, authenticated;
grant select, insert, update, delete on public.equity_fundamentals_q to service_role;

-- S-531 补(10-11,migration s531e_github_commits_weekly):GitHub 每周提交数(participation,只有最近 52 周;
-- 每天重取并累积,52 周以前的复原不了)。S 支柱的开发活跃项按 d 之前 4 个完整周求和。
create table if not exists public.github_commits_weekly (
  symbol      text not null,
  repo        text not null,
  week_start  date not null,
  commits     integer not null,
  source      text not null,
  computed_at timestamptz not null default now(),
  primary key (symbol, week_start)
);
alter table public.github_commits_weekly enable row level security;
revoke all on public.github_commits_weekly from anon, authenticated;
grant select, insert, update, delete on public.github_commits_weekly to service_role;
