-- 2026-11-06 · political_intensity_daily: GDELT DOC news-volume intensity per political topic (availability-dated), 2017 →.
-- GPR (Caldara-Iacoviello) and EPU (FRED USEPUINDXD) go to macro_daily as series gpr / gpr_act / gpr_threat / epu.
create table if not exists public.political_intensity_daily (
  d date not null, topic text not null, value double precision not null, source text,
  computed_at timestamptz not null default now(), primary key (d, topic)
);
alter table public.political_intensity_daily enable row level security;
grant select on public.political_intensity_daily to anon;
drop policy if exists lane_read on public.political_intensity_daily;
create policy lane_read on public.political_intensity_daily for select to anon using (true);
