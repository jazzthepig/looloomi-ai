-- S-517 / T-072 — ① 的候选定义(拿掉单币上限、动量加权)对照 BTC 与随机权重。预注册见 src/data/signals/core_variants.py。
-- arm:cap_c40(现行 ①)· cap_uncapped · mom90 · mom90_x_cap · btc。
-- S-167 姿态:RLS 开、零 policy、只授 service_role。AS APPLIED 2026-10-08(migration s517_core_variants_daily)。
create table if not exists public.core_variants_daily (
  d           date not null,
  arm         text not null,
  ret         double precision not null,
  nav         double precision not null,
  inception   date not null,
  code_ref    text,
  computed_at timestamptz not null,
  primary key (d, arm)
);
alter table public.core_variants_daily enable row level security;
revoke all on public.core_variants_daily from anon, authenticated;
grant select, insert, update, delete on public.core_variants_daily to service_role;
