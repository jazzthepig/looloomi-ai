-- 2026-11-07 · S-774 R 臂 ✅ 的前向记录(src/data/state/asset_flow_forecast.py)+ Ridge 的充分统计量函数。
-- 每个周一一批 (币, 预测);到期补 x30。训练统计在库里算(23 万行不出库),解在 Python。
create table if not exists public.asset_flow_forecast_daily (
  d           date not null,
  symbol      text not null,
  model       text not null,
  pred        double precision not null,
  pct         double precision,
  n_train     integer,
  x30         double precision,
  code_ref    text not null,
  settled_at  timestamptz,
  created_at  timestamptz not null default now(),
  primary key (d, symbol, model)
);
alter table public.asset_flow_forecast_daily enable row level security;
grant select on public.asset_flow_forecast_daily to anon;
drop policy if exists lane_read on public.asset_flow_forecast_daily;
create policy lane_read on public.asset_flow_forecast_daily for select to anon using (true);
create or replace function public.asset_flow_ridge_stats(p_cut date) returns jsonb
language sql stable security invoker set search_path = public, pg_temp as $$
  with u as (
    select x30::float8 y, (vec::real[])[1]::float8 a1, (vec::real[])[2]::float8 a2, (vec::real[])[3]::float8 a3, (vec::real[])[4]::float8 a4, (vec::real[])[5]::float8 a5, (vec::real[])[6]::float8 a6, (vec::real[])[7]::float8 a7, (vec::real[])[8]::float8 a8, (vec::real[])[9]::float8 a9, (vec::real[])[10]::float8 a10, (vec::real[])[11]::float8 a11
    from public.asset_flow_daily where vec is not null and x30 is not null and d < p_cut
  )
  select jsonb_build_object('n', count(*), 'sy', sum(y), 'syy', sum(y*y),
    'sx', jsonb_build_array(sum(a1),sum(a2),sum(a3),sum(a4),sum(a5),sum(a6),sum(a7),sum(a8),sum(a9),sum(a10),sum(a11)),
    'sxy', jsonb_build_array(sum(a1*y),sum(a2*y),sum(a3*y),sum(a4*y),sum(a5*y),sum(a6*y),sum(a7*y),sum(a8*y),sum(a9*y),sum(a10*y),sum(a11*y)),
    'sxx_upper', jsonb_build_array(sum(a1*a1),sum(a1*a2),sum(a1*a3),sum(a1*a4),sum(a1*a5),sum(a1*a6),sum(a1*a7),sum(a1*a8),sum(a1*a9),sum(a1*a10),sum(a1*a11),sum(a2*a2),sum(a2*a3),sum(a2*a4),sum(a2*a5),sum(a2*a6),sum(a2*a7),sum(a2*a8),sum(a2*a9),sum(a2*a10),sum(a2*a11),sum(a3*a3),sum(a3*a4),sum(a3*a5),sum(a3*a6),sum(a3*a7),sum(a3*a8),sum(a3*a9),sum(a3*a10),sum(a3*a11),sum(a4*a4),sum(a4*a5),sum(a4*a6),sum(a4*a7),sum(a4*a8),sum(a4*a9),sum(a4*a10),sum(a4*a11),sum(a5*a5),sum(a5*a6),sum(a5*a7),sum(a5*a8),sum(a5*a9),sum(a5*a10),sum(a5*a11),sum(a6*a6),sum(a6*a7),sum(a6*a8),sum(a6*a9),sum(a6*a10),sum(a6*a11),sum(a7*a7),sum(a7*a8),sum(a7*a9),sum(a7*a10),sum(a7*a11),sum(a8*a8),sum(a8*a9),sum(a8*a10),sum(a8*a11),sum(a9*a9),sum(a9*a10),sum(a9*a11),sum(a10*a10),sum(a10*a11),sum(a11*a11)))
  from u
$$;
revoke all on function public.asset_flow_ridge_stats(date) from public;
grant execute on function public.asset_flow_ridge_stats(date) to anon, authenticated, service_role;
