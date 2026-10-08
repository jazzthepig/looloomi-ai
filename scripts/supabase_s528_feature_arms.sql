-- S-528 / T-077 — 特征臂:把 CIS 当特征放进组合(cis_ew / cis_follow / cis_contra),前向对照。
-- v_cis_signal_daily:每个名字每个 UTC 日的最后一条 CIS 信号(账本按 d−1 读,避免每轮翻 15 万行原始记录)。
-- S-167 姿态:RLS 开、零 policy、只授 service_role。AS APPLIED 2026-10-08(migration s528_feature_arms)。
create table if not exists public.feature_arms_daily (
  d           date not null,
  arm         text not null,
  ret         double precision not null,
  nav         double precision not null,
  inception   date not null,
  code_ref    text,
  computed_at timestamptz not null,
  primary key (d, arm)
);
alter table public.feature_arms_daily enable row level security;
revoke all on public.feature_arms_daily from anon, authenticated;
grant select, insert, update, delete on public.feature_arms_daily to service_role;

create or replace view public.v_cis_signal_daily with (security_invoker = true) as
select distinct on (symbol, (recorded_at at time zone 'UTC')::date)
       symbol, asset_class, (recorded_at at time zone 'UTC')::date as d, signal, score
from public.cis_scores
order by symbol, (recorded_at at time zone 'UTC')::date, recorded_at desc;
revoke all on public.v_cis_signal_daily from anon, authenticated;
grant select on public.v_cis_signal_daily to service_role;
