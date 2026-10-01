-- T-041 / M-196:解读层预注册检验的每次运行结果(只追加)。S-167 姿态。
create table if not exists public.interpretation_validation_runs (
  id bigserial primary key,
  run_at timestamptz not null default now(),
  prereg text not null,
  code_ref text,
  verdict text,
  result jsonb not null);
alter table public.interpretation_validation_runs enable row level security;
revoke all on public.interpretation_validation_runs from anon, authenticated;
grant select, insert, update, delete on public.interpretation_validation_runs to service_role;
grant usage, select on sequence public.interpretation_validation_runs_id_seq to service_role;
