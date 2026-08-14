-- Tenancy + durable usage metering (2026-08-11, S-140)
--
-- WHY THIS EXISTS. Measured today: usage lives ONLY in Redis, under
-- `rl:rpd:{identity}` with a 24-hour TTL, and `api_keys.request_count` is
-- incremented by NOTHING — the column is displayed on the analytics page and has
-- read 0 since it was created.
--
-- So there is no substrate to bill from. Not "billing is unbuilt" — the usage
-- itself does not survive a day. This is S-105's shape (the strategy library spent
-- 12 days in a 24h-TTL Redis key because its Postgres migration was never applied)
-- applied to revenue, and it is worse here: research can be re-derived, a month of
-- metered usage cannot.
--
-- It is also S-131's shape (`cap_source` existed, was never written, so every row
-- read NULL). A column that is only ever zero is indistinguishable from a customer
-- who never called — which is exactly the discrimination an invoice depends on.
--
-- DESIGN — Redis stays the hot counter, Postgres becomes the record.
-- Writing a row per request would put Postgres on the request path, which is the
-- 2026-07-29 saturation P0 waiting to happen. Instead the rate-limit middleware
-- keeps INCRing Redis (unchanged, hot, cheap) and a background loop flushes the
-- day's counters into `api_usage` every few minutes.
--
-- THE FLUSH IS MONOTONE AND IDEMPOTENT, which is what makes it safe:
--     requests = GREATEST(api_usage.requests, EXCLUDED.requests)
-- A re-run cannot double-count, a missed flush is recovered by the next one, and a
-- Redis eviction mid-day leaves the last flushed high-water mark rather than zero.
-- We under-count on a lost Redis key, never over-count — the correct direction to
-- be wrong in when the number is going on an invoice.

-- ── organizations — the billable entity ──────────────────────────────────────
-- An API key is a CREDENTIAL, not a customer. A customer rotates keys, issues one
-- per environment, and expects one invoice. Modelling the customer as the key is
-- the mistake that makes rotation a billing event.
create table if not exists organizations (
    id              bigint generated always as identity primary key,
    slug            text        not null unique,
    name            text        not null,
    billing_email   text        not null,
    tier            text        not null default 'free',
    -- Seats/limits live on the ORG so a customer's second key does not double
    -- their allowance, which is what per-key limits silently do today.
    rate_limit_rpm  integer     not null default 60,
    rate_limit_day  integer     not null default 1000,
    active          boolean     not null default true,
    created_at      timestamptz not null default now(),
    notes           text
);

-- Nullable on purpose: existing keys have no org, and backfilling one invented per
-- key would manufacture a customer list out of credentials. NULL here means
-- "unattributed", which is a fact we can act on; a fabricated org is not.
alter table api_keys add column if not exists org_id bigint references organizations(id);
create index if not exists idx_api_keys_org on api_keys(org_id);

-- ── api_usage — the billing substrate ────────────────────────────────────────
create table if not exists api_usage (
    key_prefix   text        not null,
    usage_date   date        not null,
    requests     bigint      not null default 0,
    -- Recorded so a disputed invoice can be traced to a flush rather than argued
    -- from memory. `last_flush_at` moving while `requests` does not is the
    -- signature of a dead Redis counter, and it is only visible if both are kept.
    last_flush_at timestamptz not null default now(),
    org_id       bigint      references organizations(id),
    primary key (key_prefix, usage_date)
);
create index if not exists idx_api_usage_date on api_usage(usage_date desc);
create index if not exists idx_api_usage_org  on api_usage(org_id, usage_date desc);

-- ── audit_log — who changed what ─────────────────────────────────────────────
-- Institutional diligence asks for this and we have never had it. Append-only by
-- convention AND by grant: no UPDATE, no DELETE to anyone but the service role.
create table if not exists audit_log (
    id          bigint generated always as identity primary key,
    at          timestamptz not null default now(),
    actor       text        not null,           -- key_prefix, 'system', or an email
    action      text        not null,           -- key.issue, key.revoke, org.create …
    subject     text,                           -- what it acted on
    detail      jsonb,
    ip          inet
);
create index if not exists idx_audit_at      on audit_log(at desc);
create index if not exists idx_audit_actor   on audit_log(actor, at desc);
create index if not exists idx_audit_action  on audit_log(action, at desc);

-- ── RLS ──────────────────────────────────────────────────────────────────────
-- Same posture as api_keys: service role only. These tables carry the customer
-- list, the invoice basis and the audit trail; anon has no business in any of them.
alter table organizations enable row level security;
alter table api_usage     enable row level security;
alter table audit_log     enable row level security;

drop policy if exists organizations_service_only on organizations;
drop policy if exists api_usage_service_only     on api_usage;
drop policy if exists audit_log_service_only     on audit_log;

-- S-167: was `CREATE POLICY "organizations_service_only" ON organizations FOR ALL` granted to PUBLIC.

-- Removed. service_role bypasses RLS; nothing legitimate needed it.

DROP POLICY IF EXISTS "organizations_service_only" ON organizations;
-- S-167: was `CREATE POLICY "api_usage_service_only" ON api_usage FOR ALL` granted to PUBLIC.
-- Removed. service_role bypasses RLS; nothing legitimate needed it.
DROP POLICY IF EXISTS "api_usage_service_only" ON api_usage;
-- S-167: was `CREATE POLICY "audit_log_service_only" ON audit_log FOR ALL` granted to PUBLIC.
-- Removed. service_role bypasses RLS; nothing legitimate needed it.
DROP POLICY IF EXISTS "audit_log_service_only" ON audit_log;

-- `using (false)` blocks anon and authenticated; the service role bypasses RLS.
-- Stated explicitly because "RLS is enabled" and "RLS denies" are different facts,
-- and a table with RLS on and no policy is open to nobody INCLUDING us, which
-- looks like a permissions bug at 2am rather than a design choice.

revoke all on organizations, api_usage, audit_log from anon, authenticated;
grant  all on organizations, api_usage, audit_log to   service_role;

-- ── VERIFY ───────────────────────────────────────────────────────────────────
-- select table_name, row_security
--   from information_schema.tables t
--   join pg_class c on c.relname = t.table_name
--  where table_name in ('organizations','api_usage','audit_log');
--
-- After the flush loop has run once (it runs ~5 min after boot, then every 5 min):
-- select * from api_usage order by usage_date desc, requests desc limit 10;
-- expect one row per (key_prefix, day) with requests > 0 for any key in use.
--
-- If `last_flush_at` advances while `requests` stays flat, the Redis counter is
-- not being incremented — check the rate-limit middleware, not this table.


-- ─────────────────────────────────────────────────────────────────────────────
-- WRITE POLICIES CORRECTED 2026-08-15 (S-167). DO NOT RE-ADD PUBLIC WRITES.
--
-- This file granted INSERT/UPDATE/DELETE to PUBLIC (a `CREATE POLICY ... FOR
-- INSERT WITH CHECK (true)` with no `TO` clause is granted to PUBLIC, and the
-- anon key is public — it ships inside the browser bundle).
--
-- The LIVE database does not have these grants; the 2026-07-30 hardening
-- replaced them. So the drift was file-more-permissive-than-production, which
-- is the dangerous direction: these files are idempotent, they are meant to be
-- re-run, and on 2026-08-15 one of them WAS re-run. Anybody running this file
-- would have silently re-opened public writes on a hardened table.
--
-- Posture below matches live: RLS on, writes denied to PUBLIC. service_role
-- bypasses RLS, so the app is unaffected — production writes through
-- SUPABASE_KEY and never needed these policies at all.
-- ─────────────────────────────────────────────────────────────────────────────

DROP POLICY IF EXISTS "api_usage_no_public_write" ON api_usage;
DROP POLICY IF EXISTS "audit_log_no_public_write" ON audit_log;
DROP POLICY IF EXISTS "organizations_no_public_write" ON organizations;
