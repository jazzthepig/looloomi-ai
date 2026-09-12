-- S-336 · applied to production 2026-09-12 · record copy, not a to-run file.
--
-- WHY. fusion_paper_nav held 26 marks (08-15..09-09) with ONE distinct value in
-- every record-bearing column: nav 0.9995, daily_return exactly -cost, gross
-- 0.6667, n_positions 18, and NAV never compounding. The cause was not a bug in
-- the P&L maths — `fusion_paper_state` HAD NEVER EXISTED, so every _save_state
-- returned False and every _load_state returned {}, resetting nav to 1.0 and
-- w_held to {} each cycle. The loop over an empty dict never ran and the empty
-- accumulation was written as a flat day (S-194).
--
-- S-176 diagnosed the same symptom at 5 marks and added a Supabase fallback for
-- the state read — a fallback to a table that did not exist. A remedy that
-- lowers a failure's probability without changing what the system reports when
-- it happens buys time, not information.
--
-- Swept all 37 tables in schema_manifest.write_tables() against the live catalog
-- on 2026-09-12: fusion_paper_state was the ONLY missing one.

-- 1/2 the table that never existed. Columns come from the writer's payload and
-- the reader's select list. RLS posture mirrors fusion_paper_nav (enabled, zero
-- policies) so a state read can never succeed where a NAV read would fail.
create table if not exists public.fusion_paper_state (
    id                   bigserial primary key,
    inception            text,
    last_mark            text,
    nav                  double precision,
    weights              jsonb   not null default '{}'::jsonb,
    mark_prices          jsonb   not null default '{}'::jsonb,
    prev_prices          jsonb   not null default '{}'::jsonb,
    n_days_marked        integer not null default 0,
    cell                 jsonb   not null default '{}'::jsonb,
    detector_fired_today boolean not null default false,
    created_at           timestamptz not null default now()
);
create index if not exists fusion_paper_state_last_mark_desc
    on public.fusion_paper_state (last_mark desc);
alter table public.fusion_paper_state enable row level security;
grant select on public.fusion_paper_state to anon;
grant select, insert, update, delete on public.fusion_paper_state to authenticated;
grant select, insert, update, delete on public.fusion_paper_state to service_role;

-- 2/2 void the fabricated segment. VOIDED, NOT DELETED and not corrected: the
-- book never knew what it held, so the true NAVs cannot be reconstructed. Same
-- mechanism as beta_core's v4 void, for the same reason — a curve must never be
-- assembled across a voided segment and a live one.
alter table public.fusion_paper_nav
    add column if not exists inception_id text,
    add column if not exists void_reason  text;
update public.fusion_paper_nav
   set inception_id = coalesce(inception_id, 'v1'),
       void_reason  = coalesce(void_reason,
           'S-336 2026-09-12: fabricated segment. fusion_paper_state never '
           'existed, so state reset every cycle and an empty position book was '
           'recorded as a flat day. 26 marks, one distinct NAV, market P&L '
           'identically zero. Not an observation; cannot be reconstructed.')
 where inception_id is null or void_reason is null;
create index if not exists fusion_paper_nav_inception_live
    on public.fusion_paper_nav (inception_id, mark_date)
 where void_reason is null;
