-- S-521 / T-075 — 类比元配置:按当下状态找历史相似日,看策略库里每个策略之后 14 天表现,每周重配。
-- 预注册见 src/data/signals/meta_allocator.py。weights = 当周的目标权重。
-- S-167 姿态:RLS 开、零 policy、只授 service_role。AS APPLIED 2026-10-08(migration s521_meta_allocator_daily)。
create table if not exists public.meta_allocator_daily (
  d           date not null,
  arm         text not null,
  ret         double precision not null,
  nav         double precision not null,
  weights     jsonb,
  inception   date not null,
  code_ref    text,
  computed_at timestamptz not null,
  primary key (d, arm)
);
alter table public.meta_allocator_daily enable row level security;
revoke all on public.meta_allocator_daily from anon, authenticated;
grant select, insert, update, delete on public.meta_allocator_daily to service_role;
