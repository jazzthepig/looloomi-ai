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
CREATE POLICY "api_keys_insert" ON api_keys FOR INSERT WITH CHECK (true);
CREATE POLICY "api_keys_select" ON api_keys FOR SELECT USING (true);
CREATE POLICY "api_keys_update" ON api_keys FOR UPDATE USING (true);


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
CREATE POLICY "analytics_insert" ON analytics_events FOR INSERT WITH CHECK (true);
CREATE POLICY "analytics_select" ON analytics_events FOR SELECT USING (true);


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
CREATE POLICY "webhook_subs_insert" ON webhook_subscriptions FOR INSERT WITH CHECK (true);
CREATE POLICY "webhook_subs_select" ON webhook_subscriptions FOR SELECT USING (true);
CREATE POLICY "webhook_subs_update" ON webhook_subscriptions FOR UPDATE USING (true);
CREATE POLICY "webhook_subs_delete" ON webhook_subscriptions FOR DELETE USING (true);


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
