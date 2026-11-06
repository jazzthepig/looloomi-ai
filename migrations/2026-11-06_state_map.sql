-- 2026-11-06 · S-737 forward record: daily state label from the frozen T-257 k-means + paper tickets for S5 × (BTC + 30d 90% put).
create table if not exists public.state_map_daily (
  d date primary key, state integer not null, dist double precision, features jsonb not null default '{}'::jsonb,
  code_ref text, computed_at timestamptz not null default now()
);
create table if not exists public.protected_long_paper (
  ticket_id text primary key, state integer, entry_d date not null, entry_px double precision not null, strike double precision,
  put_cost_pct double precision not null, put_source text, expiry_d date not null, status text not null,
  exit_px double precision, ret_spot double precision, ret_protected double precision, code_ref text,
  computed_at timestamptz not null default now()
);
alter table public.state_map_daily enable row level security;
alter table public.protected_long_paper enable row level security;
grant select on public.state_map_daily, public.protected_long_paper to anon;
drop policy if exists lane_read on public.state_map_daily;
create policy lane_read on public.state_map_daily for select to anon using (true);
drop policy if exists lane_read on public.protected_long_paper;
create policy lane_read on public.protected_long_paper for select to anon using (true);
