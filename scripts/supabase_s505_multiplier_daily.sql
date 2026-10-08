-- S-505 / T-063 — ③ 推力:① 的持仓 × 状态决定的 0.7 / 1.0 / 1.3 倍敞口(预注册见 src/data/signals/multiplier.py)。
-- arm:mult_v1 = 前向(起点 2026-10-08)· mult_v1_replay = 2023 起回放 · core_replay = 同期 ① 回放。
-- S-167 姿态:RLS 开、零 policy、只授 service_role。AS APPLIED 2026-10-08(migration s505_multiplier_daily)。
create table if not exists multiplier_daily (
  d           date not null,
  arm         text not null,
  m           double precision not null,
  ret         double precision not null,
  nav         double precision not null,
  cost        double precision not null,
  dist_200    double precision,
  vol_pct_3y  double precision,
  inception   date not null,
  code_ref    text,
  computed_at timestamptz not null,
  primary key (d, arm)
);
alter table multiplier_daily enable row level security;
revoke all on multiplier_daily from anon, authenticated;
grant all on multiplier_daily to service_role;
