-- S-408-2 (A-408-2) · loop_attempt — per-iteration record for every async loop
--
-- WHY. Of 43 in-process async loops in src/api/main.py, 18 call `_beat()`
-- (a Redis hash, last-write-wins, 3-day TTL) and 25 only print(). None
-- persists a per-iteration row. The audit gate (`select count(*) from
-- loop_attempt where loop_name='_cg_panel_loop' and at::date = current_date`
-- ≥ 100) is impossible today: a Redis hash cannot answer a COUNT.
--
-- `_beat()` answers "is the loop alive RIGHT NOW". `loop_attempt` answers
-- "how many rounds ran today, with what outcome". They overlap on failure
-- (both flag the last error) but NOT on success — a loop that ran cleanly
-- 200 times today and failed once shows `beat()=ok` and `loop_attempt` =
-- {ok:199, error:1}. The COUNT is the audit gate; beat() cannot answer it.
--
-- Outcome vocabulary (mirrors `_classify` / `_beat` but adds one loop-specific
-- value, 'panel_unavailable', for the cg_panel "deep_panel_symbols()=None"
-- branch — that branch is the live S-410 failure mode and deserves its own
-- row kind so the audit can separate "the panel is empty" from "the
-- dependency is down" from "this loop raised").
--
-- Different shape from write_log on purpose: write_log records writes to
-- *other tables* (table_name axis); loop_attempt records iterations of
-- *loops* (loop_name axis). Collapsing them into one table forces one row
-- schema onto both axes and loses the queries the other table is good for.

create table if not exists public.loop_attempt (
    id          bigserial primary key,
    at          timestamptz not null default now(),
    loop_name   text not null,
    outcome     text not null,             -- 'ok' | 'refused' | 'error' | 'panel_unavailable'
    reason      text,
    elapsed_ms  integer,
    detail      jsonb,
    writer      text,                      -- call-site label, e.g. 'src.api.main._cg_panel_loop'
    build       text                       -- loop_beat.build_sha()[:8] — S-322 fossil attribution
);
-- Three indexes that match the actual query shapes the audit / dashboard needs:
--   1. per-loop today (the audit gate)
--   2. failures across the fleet (panel layer)
--   3. last 24h by outcome (a generic "what's looping badly" probe)
create index if not exists loop_attempt_loop_at_desc
    on public.loop_attempt (loop_name, at desc);
create index if not exists loop_attempt_failures
    on public.loop_attempt (at desc) where outcome <> 'ok';
create index if not exists loop_attempt_outcome_at_desc
    on public.loop_attempt (outcome, at desc);
alter table public.loop_attempt enable row level security;
grant select on public.loop_attempt to anon;
grant select, insert on public.loop_attempt to authenticated;
grant select, insert, delete on public.loop_attempt to service_role;

-- Health probe: one round-trip per loop's last success / failure.
-- Mirrors write_health() so the dashboard can call both with the same shape.
create or replace function public.loop_attempt_health(p_loop_name text default null)
returns table (loop_name text, last_ok timestamptz, last_fail timestamptz,
               last_outcome text, last_reason text, n_ok_24h bigint, n_fail_24h bigint)
language sql stable security definer
set search_path = public, pg_catalog
as $$
    select a.loop_name,
           max(a.at) filter (where a.outcome =  'ok'),
           max(a.at) filter (where a.outcome <> 'ok'),
           (array_agg(a.outcome order by a.at desc))[1],
           (array_agg(a.reason  order by a.at desc))[1],
           count(*) filter (where a.outcome =  'ok' and a.at > now() - interval '24 hours'),
           count(*) filter (where a.outcome <> 'ok' and a.at > now() - interval '24 hours')
    from public.loop_attempt a
    where (p_loop_name is null or a.loop_name = p_loop_name)
    group by a.loop_name
    order by max(a.at) desc;
$$;
revoke all on function public.loop_attempt_health() from public;   -- S-323h
grant execute on function public.loop_attempt_health() to anon;
grant execute on function public.loop_attempt_health() to authenticated;
grant execute on function public.loop_attempt_health() to service_role;