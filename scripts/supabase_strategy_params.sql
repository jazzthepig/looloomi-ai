-- strategy_params — versioned, append-only sleeve parameters (S-151, 2026-08-12)
--
-- WHY. Two reasons, and the second is why this table has the shape it has.
--
-- 1. The mined edge must not ship inside the repo (Jazz, 2026-08-12).
--    C3's 5x5 conviction table and C2's q thresholds ARE the research output;
--    everything around them is plumbing. NOTE: the Python modules stay tracked.
--    src/api/main.py imports them and Railway deploys from git, so gitignoring
--    a module is a 500 on the endpoint. The edge leaves as a PARAMETER.
--
-- 2. Parameters in a table can change without a code review, and a forward
--    record cannot show what it cannot see. That is only acceptable because
--    (a) every NAV row carries param_version + param_source, and (b) a payload
--    that violates the sleeve's behavioural invariants CANNOT LOAD
--    (src/data/signals/strategy_params.py). Reason (b) is not hypothetical:
--    the C3 table in the repo was transposed on both axes, so the book took
--    MAXIMUM leverage at MAXIMUM regime unfamiliarity with the WEAKEST signal,
--    and returned 1.20x with no inputs at all.
--
-- APPEND-ONLY. Never UPDATE a row. A new parameter set is a new param_version;
-- activating it is an INSERT plus deactivating the prior version. The old row
-- stays forever, so "what were the thresholds on 2026-09-14" stays answerable —
-- which is the entire point of a 60-day forward commitment. A mutable config
-- row would let a sleeve silently become a different sleeve mid-clock while the
-- ledger still called it c3_size_v1.

create table if not exists strategy_params (
    id             bigint generated always as identity primary key,
    namespace      text        not null,          -- matches the sleeve inception_id
    param_version  integer     not null,
    payload        jsonb       not null,
    active         boolean     not null default false,
    -- Provenance. `source_ref` points at the ledger entry (M-##) that justifies
    -- these values; `notes` explains WHY, for the reader six months out who is
    -- asking why 0.85 and not 0.80.
    source_ref     text,
    notes          text,
    created_at     timestamptz not null default now(),
    created_by     text,
    unique (namespace, param_version)
);

create index if not exists idx_strategy_params_active
    on strategy_params (namespace, param_version desc) where active;

-- Only one active version per namespace. Enforced in the DATABASE, not in the
-- loader: a guarantee that lives in the caller holds until someone writes a
-- second caller. (Same argument that put GREATEST inside api_usage_upsert.)
create unique index if not exists uq_strategy_params_one_active
    on strategy_params (namespace) where active;

alter table strategy_params enable row level security;

-- Service-role only. These values ARE the edge; anon must not read them.
-- This is the whole point of taking them out of git.
drop policy if exists strategy_params_service_only on strategy_params;
create policy strategy_params_service_only on strategy_params
    for all to service_role using (true) with check (true);

comment on table strategy_params is
 'Append-only versioned sleeve parameters. Never UPDATE; insert a new '
 'param_version. Payloads are validated on load by '
 'src/data/signals/strategy_params.py — a set violating the sleeve''s '
 'behavioural invariants is refused and the sleeve falls back to neutral, '
 'recording param_source=db_rejected_fallback in the NAV row.';

comment on column strategy_params.active is
 'Exactly one active version per namespace (partial unique index). Rolling '
 'forward = insert new version + flip active in one transaction.';


-- ── Provenance columns on the C3 forward record ─────────────────────────────
-- A NAV row that cannot name the parameters that produced it is a NAV row you
-- cannot defend. Nullable: rows written before S-151 genuinely do not know,
-- and back-filling a guess would manufacture provenance that never existed.
alter table beta_core_nav_size
    add column if not exists param_namespace text,
    add column if not exists param_version   integer,
    add column if not exists param_source    text;

comment on column beta_core_nav_size.param_source is
 'db | code_fallback | db_rejected_fallback. Anything other than "db" means '
 'the sleeve ran degraded that day — the curve is still honest, but it is not '
 'the curve the parameters describe.';


-- ── Seeding is DELIBERATELY NOT DONE HERE ───────────────────────────────────
-- No INSERT of the C3 table in this file. Committing the calibrated values to
-- scripts/ would put the edge straight back into git, which is the thing this
-- migration exists to prevent. Seed from the Mac side, out of band.
--
-- The table currently in beta_core_size.py FAILS validation (12 violations).
-- Un-transposing it — reversing both axes — yields a set that passes with all
-- 25 original values intact, which is itself the evidence that the magnitudes
-- were designed correctly and only the assembly was wrong. Whoever seeds this
-- owns that call; the loader will refuse the inverted orientation either way.
