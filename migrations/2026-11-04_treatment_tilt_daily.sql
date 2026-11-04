-- 2026-11-04 · treatment_tilt_daily: ② forward book — minority-holder treatment tilt vs equal-weight panel (S-711).
-- Same shape as tokenization_tilt_daily; tilt_classes counts pays / keeps / none at the last rebalance.
create table if not exists public.treatment_tilt_daily (
  d             date not null,
  arm           text not null,
  nav           double precision not null,
  ret           double precision not null,
  weights       jsonb not null default '{}'::jsonb,
  tilt_classes  jsonb not null default '{}'::jsonb,
  rebalanced    boolean not null default false,
  turnover      double precision,
  n_quoted      integer,
  n_filled      integer,
  barred        jsonb not null default '[]'::jsonb,
  source        text,
  inception     date,
  code_ref      text,
  computed_at   timestamptz not null default now(),
  primary key (d, arm)
);
alter table public.treatment_tilt_daily enable row level security;
grant select on public.treatment_tilt_daily to anon;
drop policy if exists lane_read on public.treatment_tilt_daily;
create policy lane_read on public.treatment_tilt_daily for select to anon using (true);
