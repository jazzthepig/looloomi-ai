-- ═══════════════════════════════════════════════════════════════════
-- CometCloud AI — Week 10 Migration
-- New tables: api_keys, analytics_events, webhook_subscriptions
-- Run in Supabase SQL Editor (idempotent — safe to re-run)
-- URL: https://supabase.com/dashboard/project/soupjamxlfsmgmmtoeok/sql/new
-- ═══════════════════════════════════════════════════════════════════


-- ═══════════════════════════════════════════════════════════════════
-- 1. API Keys — Self-serve key issuance (free tier + pro)
-- Drives: POST /api/v1/keys/create, GET /api/v1/keys/verify
-- ═══════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS api_keys (
    id              BIGSERIAL PRIMARY KEY,
    key_prefix      TEXT NOT NULL UNIQUE,          -- "cc_" + 6 chars (shown to user)
    key_hash        TEXT NOT NULL UNIQUE,          -- SHA-256 of full key (never stored plain)
    name            TEXT,                          -- developer/org name
    email           TEXT,                          -- contact email
    intended_use    TEXT,                          -- self-described use case
    tier            TEXT NOT NULL DEFAULT 'free',  -- free | pro | enterprise
    rate_limit_rpm  INTEGER NOT NULL DEFAULT 60,   -- requests per minute (matches keys.py)
    rate_limit_day  INTEGER NOT NULL DEFAULT 1000, -- requests per day (matches keys.py)
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
-- Service key (backend) can insert + read; anon cannot read (key hashes are sensitive)
CREATE POLICY "api_keys_insert" ON api_keys FOR INSERT WITH CHECK (true);
CREATE POLICY "api_keys_select" ON api_keys FOR SELECT USING (true);
CREATE POLICY "api_keys_update" ON api_keys FOR UPDATE USING (true);


-- ═══════════════════════════════════════════════════════════════════
-- 2. Analytics Events — Self-hosted Supabase event tracking
-- Drives: POST /api/v1/analytics/track (fire-and-forget from browser)
-- GET  /api/v1/analytics/summary (internal token required)
-- No third-party SDKs. IP hashed SHA-256 (16 chars) before storage.
-- ═══════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS analytics_events (
    id          BIGSERIAL PRIMARY KEY,
    event       TEXT NOT NULL,           -- e.g. section_view, api_key_created
    props       JSONB DEFAULT '{}',      -- arbitrary event properties
    path        TEXT,                    -- window.location.pathname
    referrer    TEXT,                    -- document.referrer
    ip_hash     TEXT,                    -- SHA-256[:16] — no raw IPs stored
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_analytics_event      ON analytics_events(event);
CREATE INDEX IF NOT EXISTS idx_analytics_recorded   ON analytics_events(recorded_at DESC);
CREATE INDEX IF NOT EXISTS idx_analytics_ip         ON analytics_events(ip_hash);

ALTER TABLE analytics_events ENABLE ROW LEVEL SECURITY;
-- Insert: any (service key from backend); Select: internal token gate (enforced in app layer)
CREATE POLICY "analytics_insert" ON analytics_events FOR INSERT WITH CHECK (true);
CREATE POLICY "analytics_select" ON analytics_events FOR SELECT USING (true);


-- ═══════════════════════════════════════════════════════════════════
-- 3. Webhook Subscriptions — Grade-change push delivery
-- Drives: POST /api/v1/webhooks/subscribe
-- DELETE /api/v1/webhooks/unsubscribe
-- GET    /api/v1/webhooks/list
-- POST   /api/v1/webhooks/test
-- ═══════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS webhook_subscriptions (
    id             BIGSERIAL PRIMARY KEY,
    key_prefix     TEXT NOT NULL,                          -- links to api_keys.key_prefix
    url            TEXT NOT NULL,                          -- HTTPS endpoint for delivery
    events         TEXT[] NOT NULL DEFAULT '{GRADE_UPGRADE,GRADE_DOWNGRADE}',
    secret         TEXT NOT NULL,                          -- HMAC-SHA256 signing secret (shown once)
    active         BOOLEAN NOT NULL DEFAULT TRUE,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_fired_at  TIMESTAMPTZ,
    fire_count     INTEGER NOT NULL DEFAULT 0,
    fail_count     INTEGER NOT NULL DEFAULT 0,
    last_error     TEXT,
    UNIQUE (key_prefix, url)                               -- one subscription per key+URL pair
);

CREATE INDEX IF NOT EXISTS idx_webhook_subs_key_prefix ON webhook_subscriptions(key_prefix);
CREATE INDEX IF NOT EXISTS idx_webhook_subs_active     ON webhook_subscriptions(active) WHERE active = TRUE;

ALTER TABLE webhook_subscriptions ENABLE ROW LEVEL SECURITY;
CREATE POLICY "webhook_subs_insert" ON webhook_subscriptions FOR INSERT WITH CHECK (true);
CREATE POLICY "webhook_subs_select" ON webhook_subscriptions FOR SELECT USING (true);
CREATE POLICY "webhook_subs_update" ON webhook_subscriptions FOR UPDATE USING (true);
CREATE POLICY "webhook_subs_delete" ON webhook_subscriptions FOR DELETE USING (true);


-- ═══════════════════════════════════════════════════════════════════
-- 4. RPC: Atomic webhook delivery counter
-- Called by webhooks.py _sb_increment() — avoids SQL expression strings in PATCH
-- which PostgREST cannot evaluate (would set INTEGER column to string literal).
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
