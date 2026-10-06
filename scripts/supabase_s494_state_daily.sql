-- S-494 / T-048 — L1 状态层 state_daily:长表 (d, entity, feature, value),加特征不改表结构(v0.2 §L1)。
-- lane A 的草稿用了 bigserial id、给 anon / authenticated 授了读、加了一个授给 anon 的 security definer 函数;
-- 合并时改回 S-167 姿态:RLS 开、零 policy、只授 service_role。AS APPLIED 2026-10-06(migration s494_state_daily)。
create table if not exists state_daily (
  d           date not null,
  entity      text not null,
  feature     text not null,
  value       double precision,          -- null = 缺数据,不是 0
  source      text not null,
  code_ref    text,
  computed_at timestamptz not null,
  primary key (d, entity, feature)
);
create index if not exists state_daily_feature_d on state_daily (feature, d desc);
alter table state_daily enable row level security;
revoke all on state_daily from anon, authenticated;
grant all on state_daily to service_role;
