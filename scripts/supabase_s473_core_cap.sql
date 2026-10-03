-- S-473 — ① 持有市场:市值加权、单币 ≤ 40% 的核心持仓(Jazz 2026-10-03「use 1」)+ α=0.5 / α=0 两条对照臂。
-- S-167 姿态:RLS 开、零 policy、只授 service_role。AS APPLIED 2026-10-03(migration s473_core_cap_daily)。
create table if not exists core_cap_daily (
  d           date not null,
  arm         text not null,
  alpha       double precision not null,
  nav         double precision not null,
  ret         double precision not null,
  weights     jsonb not null,
  max_weight  double precision,
  rebalanced  boolean not null,
  turnover    double precision,
  n_quoted    integer,
  n_filled    integer,
  barred      jsonb,
  source      text,
  inception   date not null,
  code_ref    text,
  computed_at timestamptz not null,
  primary key (d, arm)
);
alter table core_cap_daily enable row level security;
revoke all on core_cap_daily from anon, authenticated;
grant all on core_cap_daily to service_role;
