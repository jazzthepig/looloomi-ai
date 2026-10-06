-- S-493 / T-052 — ② CIS 倾斜:在 ① 的持仓内按 CIS 超配(T-051 预注册,K = 0.5,单币 ≤ 40%,周一再平衡,起点 2026-10-06)。
-- S-167 姿态:RLS 开、零 policy、只授 service_role。AS APPLIED 2026-10-06(migration s493_cis_tilt_daily)。
create table if not exists cis_tilt_daily (
  d           date not null,
  arm         text not null,
  k           double precision not null,
  nav         double precision not null,
  ret         double precision not null,
  weights     jsonb not null,
  z           jsonb,
  n_scored    integer,
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
alter table cis_tilt_daily enable row level security;
revoke all on cis_tilt_daily from anon, authenticated;
grant all on cis_tilt_daily to service_role;
