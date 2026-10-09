-- S-531 / T-079 — CIS 按时点重建(统一标准 v1,docs/CIS_STANDARD.md)。
-- cis_rebuild_daily   每个名字每个 UTC 日一行;与实盘 T2 同一个函数,只喂 d 收盘时已知的输入;不写 cis_scores
-- v_funding_daily     binance_perp 资金费率按 UTC 日取平均(重建按日读,避免每轮翻 8 小时一期的原始行)
-- S-167 姿态:RLS 开、零 policy、只授 service_role。AS APPLIED 2026-10-09(migration s531b_cis_rebuild)。
create table if not exists public.cis_rebuild_daily (
  symbol      text not null,
  d           date not null,
  code_ref    text not null,
  asset_class text,
  pillar_f    double precision,
  pillar_m    double precision,
  pillar_o    double precision,
  pillar_s    double precision,
  pillar_a    double precision,
  raw_score   double precision,
  score       double precision,
  grade       text,
  signal_raw  text,
  signal      text,
  watch       text,
  regime      text,
  inputs      jsonb,
  missing     text[],
  computed_at timestamptz not null,
  primary key (symbol, d, code_ref)
);
create index if not exists cis_rebuild_daily_d on public.cis_rebuild_daily (d);
alter table public.cis_rebuild_daily enable row level security;
revoke all on public.cis_rebuild_daily from anon, authenticated;
grant select, insert, update, delete on public.cis_rebuild_daily to service_role;

create or replace view public.v_funding_daily with (security_invoker = true) as
select symbol, (funding_time at time zone 'UTC')::date as d, avg(funding_rate) as funding_rate, count(*) as n
from public.funding_history
where venue = 'binance_perp'
group by 1, 2;
revoke all on public.v_funding_daily from anon, authenticated;
grant select on public.v_funding_daily to service_role;
