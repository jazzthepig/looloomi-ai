-- 2026-11-06 · joint_forecast_daily: S-741 (T-263 ✅, Ridge) forward record — daily expanding retrain with a 30-day embargo,
-- the frozen 59-feature set, z vs the previous 90 predictions. kind = backfill (history computed at go-live, NOT forward
-- evidence) | live (predicted on the day). Descriptive input to ③ only; moves no money.
create table if not exists public.joint_forecast_daily (
  d date not null,
  model text not null,
  kind text not null check (kind in ('backfill', 'live')),
  pred double precision not null,
  z double precision,
  n_train integer,
  n_hist integer,
  fwd_ret_30d double precision,
  features_hash text not null,
  code_ref text not null,
  computed_at timestamptz not null default now(),
  primary key (d, model)
);
alter table public.joint_forecast_daily enable row level security;
grant select on public.joint_forecast_daily to anon;
drop policy if exists lane_read on public.joint_forecast_daily;
create policy lane_read on public.joint_forecast_daily for select to anon using (true);
