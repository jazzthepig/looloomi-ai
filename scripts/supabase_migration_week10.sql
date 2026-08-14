-- ═══════════════════════════════════════════════════════════════════
-- CometCloud AI — Week 10 Migration
-- New tables: api_keys, analytics_events, webhook_subscriptions
-- Run in Supabase SQL Editor (idempotent — safe to re-run)
-- URL: https://supabase.com/dashboard/project/soupjamxlfsmgmmtoeok/sql/new
-- ═══════════════════════════════════════════════════════════════════


-- ═══════════════════════════════════════════════════════════════════
-- 1. API Keys — Self-serve key issuance (free tier + pro)
-- ═══════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS api_keys (
    id              BIGSERIAL PRIMARY KEY,
    key_prefix      TEXT NOT NULL UNIQUE,
    key_hash        TEXT NOT NULL UNIQUE,
    name            TEXT,
    email           TEXT,
    intended_use    TEXT,
    tier            TEXT NOT NULL DEFAULT 'free',
    rate_limit_rpm  INTEGER NOT NULL DEFAULT 60,
    rate_limit_day  INTEGER NOT NULL DEFAULT 1000,
    active          BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_used_at    TIMESTAMPTZ,
    request_count   BIGINT NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_api_keys_prefix  ON api_keys(key_prefix);
CREATE INDEX IF NOT EXISTS idx_api_keys_hash    ON api_keys(key_hash);
CREATE INDEX IF NOT EXISTS idx_api_keys_email   ON api_keys(email);
CREATE INDEX IF NOT EXISTS idx_api_keys_active  ON api_keys(active) WHERE active = TRUE;

ALTER TABLE api_keys ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "api_keys_insert" ON api_keys;
DROP POLICY IF EXISTS "api_keys_select" ON api_keys;
DROP POLICY IF EXISTS "api_keys_update" ON api_keys;
-- S-167: was `CREATE POLICY "api_keys_insert" ON api_keys FOR INSERT` granted to PUBLIC.
-- Removed. service_role bypasses RLS; nothing legitimate needed it.
DROP POLICY IF EXISTS "api_keys_insert" ON api_keys;
-- S-167: was `CREATE POLICY "api_keys_select" ON api_keys FOR SELECT USING (true)`
-- granted to PUBLIC. Measured 2026-08-15: the anon key could read this.
-- Removed live and here. Nothing we ship reads through anon — the frontend
-- goes through /api/v1/* on FastAPI, which holds service_role.
DROP POLICY IF EXISTS "api_keys_select" ON api_keys;
-- S-167: was `CREATE POLICY "api_keys_update" ON api_keys FOR UPDATE` granted to PUBLIC.
-- Removed. service_role bypasses RLS; nothing legitimate needed it.
DROP POLICY IF EXISTS "api_keys_update" ON api_keys;


-- ═══════════════════════════════════════════════════════════════════
-- 2. Analytics Events — Self-hosted Supabase event tracking
-- ═══════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS analytics_events (
    id          BIGSERIAL PRIMARY KEY,
    event       TEXT NOT NULL,
    props       JSONB DEFAULT '{}',
    path        TEXT,
    referrer    TEXT,
    ip_hash     TEXT,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_analytics_event    ON analytics_events(event);
CREATE INDEX IF NOT EXISTS idx_analytics_recorded ON analytics_events(recorded_at DESC);
CREATE INDEX IF NOT EXISTS idx_analytics_ip       ON analytics_events(ip_hash);

ALTER TABLE analytics_events ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "analytics_insert" ON analytics_events;
DROP POLICY IF EXISTS "analytics_select" ON analytics_events;
-- S-167: was `CREATE POLICY "analytics_insert" ON analytics_events FOR INSERT` granted to PUBLIC.
-- Removed. service_role bypasses RLS; nothing legitimate needed it.
DROP POLICY IF EXISTS "analytics_insert" ON analytics_events;
-- S-167: was `CREATE POLICY "analytics_select" ON analytics_events FOR SELECT USING (true)`
-- granted to PUBLIC. Measured 2026-08-15: the anon key could read this.
-- Removed live and here. Nothing we ship reads through anon — the frontend
-- goes through /api/v1/* on FastAPI, which holds service_role.
DROP POLICY IF EXISTS "analytics_select" ON analytics_events;


-- ═══════════════════════════════════════════════════════════════════
-- 3. Webhook Subscriptions — Grade-change push delivery
-- ═══════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS webhook_subscriptions (
    id             BIGSERIAL PRIMARY KEY,
    key_prefix     TEXT NOT NULL,
    url            TEXT NOT NULL,
    events         TEXT[] NOT NULL DEFAULT '{GRADE_UPGRADE,GRADE_DOWNGRADE}',
    secret         TEXT NOT NULL,
    active         BOOLEAN NOT NULL DEFAULT TRUE,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_fired_at  TIMESTAMPTZ,
    fire_count     INTEGER NOT NULL DEFAULT 0,
    fail_count     INTEGER NOT NULL DEFAULT 0,
    last_error     TEXT,
    UNIQUE (key_prefix, url)
);

CREATE INDEX IF NOT EXISTS idx_webhook_subs_key_prefix ON webhook_subscriptions(key_prefix);
CREATE INDEX IF NOT EXISTS idx_webhook_subs_active     ON webhook_subscriptions(active) WHERE active = TRUE;

ALTER TABLE webhook_subscriptions ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "webhook_subs_insert" ON webhook_subscriptions;
DROP POLICY IF EXISTS "webhook_subs_select" ON webhook_subscriptions;
DROP POLICY IF EXISTS "webhook_subs_update" ON webhook_subscriptions;
DROP POLICY IF EXISTS "webhook_subs_delete" ON webhook_subscriptions;
-- S-167: was `CREATE POLICY "webhook_subs_insert" ON webhook_subscriptions FOR INSERT` granted to PUBLIC.
-- Removed. service_role bypasses RLS; nothing legitimate needed it.
DROP POLICY IF EXISTS "webhook_subs_insert" ON webhook_subscriptions;
-- S-167: was `CREATE POLICY "webhook_subs_select" ON webhook_subscriptions FOR SELECT USING (true)`
-- granted to PUBLIC. Measured 2026-08-15: the anon key could read this.
-- Removed live and here. Nothing we ship reads through anon — the frontend
-- goes through /api/v1/* on FastAPI, which holds service_role.
DROP POLICY IF EXISTS "webhook_subs_select" ON webhook_subscriptions;
-- S-167: was `CREATE POLICY "webhook_subs_update" ON webhook_subscriptions FOR UPDATE` granted to PUBLIC.
-- Removed. service_role bypasses RLS; nothing legitimate needed it.
DROP POLICY IF EXISTS "webhook_subs_update" ON webhook_subscriptions;
-- S-167: was `CREATE POLICY "webhook_subs_delete" ON webhook_subscriptions FOR DELETE` granted to PUBLIC.
-- Removed. service_role bypasses RLS; nothing legitimate needed it.
DROP POLICY IF EXISTS "webhook_subs_delete" ON webhook_subscriptions;


-- ═══════════════════════════════════════════════════════════════════
-- 4. RPC: Atomic API key usage counter
-- PostgREST PATCH cannot evaluate SQL expressions; "request_count + 1"
-- as a JSON string literal causes a type error on INTEGER columns.
-- ═══════════════════════════════════════════════════════════════════
CREATE OR REPLACE FUNCTION increment_api_key_usage(
    p_key_id BIGINT
) RETURNS VOID AS $$
BEGIN
    UPDATE api_keys
    SET request_count = request_count + 1
    WHERE id = p_key_id;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;


-- ═══════════════════════════════════════════════════════════════════
-- 5. RPC: Atomic webhook delivery counter
-- PostgREST PATCH cannot evaluate SQL expressions ("fire_count + 1"
-- would be treated as a string literal, causing a type error).
-- This function handles atomic increments cleanly.
-- ═══════════════════════════════════════════════════════════════════
CREATE OR REPLACE FUNCTION increment_webhook_delivery(
    p_key_prefix TEXT,
    p_url        TEXT,
    p_success    BOOLEAN
) RETURNS VOID AS $$
BEGIN
    IF p_success THEN
        UPDATE webhook_subscriptions
        SET fire_count = fire_count + 1
        WHERE key_prefix = p_key_prefix AND url = p_url;
    ELSE
        UPDATE webhook_subscriptions
        SET fail_count = fail_count + 1
        WHERE key_prefix = p_key_prefix AND url = p_url;
    END IF;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

-- SECURITY (2026-08-09): see supabase_revoke_public_execute.sql. These are
-- SECURITY DEFINER and were left on the default PUBLIC grant in this script; the
-- live database was locked by hand, so a rebuild from scripts would have reopened it.
revoke all on function increment_api_key_usage(bigint) from public, anon, authenticated;
revoke all on function increment_webhook_delivery(text, text, boolean) from public, anon, authenticated;
grant execute on function increment_api_key_usage(bigint) to service_role;
grant execute on function increment_webhook_delivery(text, text, boolean) to service_role;


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

DROP POLICY IF EXISTS "analytics_events_no_public_write" ON analytics_events;
DROP POLICY IF EXISTS "api_keys_no_public_write" ON api_keys;
DROP POLICY IF EXISTS "webhook_subscriptions_no_public_write" ON webhook_subscriptions;
