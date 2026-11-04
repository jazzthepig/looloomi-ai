-- 2026-11-04 · cycle_vector_daily: the ⓪ liquidity-cycle vector (HIGH_DIM_ONTOLOGY §5b-bis). Nine point-in-time components,
-- expanding-window z-scores, a signed deterioration score, the distance moved from the 90→30-day centroid (shift) and a
-- turning / normal phase with hysteresis (S-713 rule, not traded). Recomputed in full daily; lanes read it.
create table if not exists public.cycle_vector_daily (
  d              date primary key,
  components     jsonb not null default '{}'::jsonb,
  z              jsonb not null default '{}'::jsonb,
  deterioration  double precision,
  shift          double precision,
  shift_pct      double precision,
  phase          text,
  n_components   integer,
  code_ref       text,
  recorded_at    timestamptz not null default now()
);
alter table public.cycle_vector_daily enable row level security;
grant select on public.cycle_vector_daily to anon;
drop policy if exists lane_read on public.cycle_vector_daily;
create policy lane_read on public.cycle_vector_daily for select to anon using (true);
