-- 2026-10-20 · R-v2 forward money curve, written once a day and frozen (S-638 → forward).
--
-- r_tickets_nav_paper(0.01, 10) recomputes the curve from r_tickets_paper on demand; a curve that only exists when
-- someone asks for it is not a forward record. The Railway loop that advances r_tickets_scan now also writes the
-- curve here through accounting/forward_lock.write_locked: rows with d <= today - 2 are never rewritten (S-560),
-- later rows chain from the last frozen nav. One row per UTC day from the book's first forward day (2026-10-19).

create table if not exists public.r_money_daily (
  d            date primary key,
  nav          double precision not null,
  ret          double precision not null,
  realized     double precision,
  unrealized   double precision,
  open_n       integer,
  gross        double precision,
  taken        integer,
  skipped      integer,
  closed       integer,
  f            double precision not null,
  cap          integer not null,
  inception    date not null,
  rule_version text not null,
  computed_at  timestamptz not null default now()
);
alter table public.r_money_daily enable row level security;
grant select on public.r_money_daily to anon;
drop policy if exists lane_read on public.r_money_daily;
create policy lane_read on public.r_money_daily for select to anon using (true);
