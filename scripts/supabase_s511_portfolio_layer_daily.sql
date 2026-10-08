-- S-511 / T-070 — 组合层 0–1 风险敞口(可空仓;预注册见 src/data/signals/portfolio_layer.py)。
-- arm:pl_v2 = 前向(起点 2026-10-08)· pl_v2_replay = 2023 起回放 · pl_v1cash_replay = S-506 的对照(③ v1 状态 → 空仓)。
-- flags = 作用于 d 的敞口所依据的 d−1 旗标(null = 输入读不到,不举旗)。
-- S-167 姿态:RLS 开、零 policy、只授 service_role。AS APPLIED 2026-10-08(migration s511_portfolio_layer_daily)。
create table if not exists portfolio_layer_daily (
  d           date not null,
  arm         text not null,
  x           double precision not null,
  ret         double precision not null,
  nav         double precision not null,
  cost        double precision not null,
  score       integer,
  flags       jsonb,
  inception   date not null,
  code_ref    text,
  computed_at timestamptz not null,
  primary key (d, arm)
);
alter table portfolio_layer_daily enable row level security;
revoke all on portfolio_layer_daily from anon, authenticated;
grant all on portfolio_layer_daily to service_role;
