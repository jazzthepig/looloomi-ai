-- S-496 / T-045 — 评估层 rr_matrix_daily:每本账 × 每个状态格子(6 类 regime + unknown)×(FOMC 窗口是 / 否)相对 ① 的超额分布。
-- 描述用;进 L3 的门槛仍是 l3-v2 的任意时刻下界。S-167 姿态:RLS 开、零 policy、只授 service_role。
-- AS APPLIED 2026-10-06(migration s496_rr_matrix_daily)。
create table if not exists rr_matrix_daily (
  d                date not null,
  strategy_id      text not null,
  cell             text not null,
  n_days           integer not null,
  excess_mean      double precision,
  ci_lo            double precision,
  ci_hi            double precision,
  p_pos            double precision,
  beta             double precision,
  rel_maxdd        double precision,
  turnover         double precision,
  n_variants_tried integer,
  code_ref         text,
  computed_at      timestamptz not null,
  primary key (d, strategy_id, cell)
);
alter table rr_matrix_daily enable row level security;
revoke all on rr_matrix_daily from anon, authenticated;
grant all on rr_matrix_daily to service_role;
