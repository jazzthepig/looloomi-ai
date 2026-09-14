-- ============================================================================
-- A-21 · Vault NAV per-minute infrastructure
-- docs/VAULT_NAV_SPEC.md (tbd) — CometCloud Layer II vault (ETH ERC-20,
-- NOT Drift/Solana).
--
-- Three tables:
--   vault_state      — one row per vault, durable state (share count, inception)
--   vault_positions  — many rows per vault, ERC-20 holdings at as_of
--   vault_nav_tick   — one row per tick (force-tick or scheduled), per-minute
--
-- Why per-minute but only on demand. We do NOT have a live ETH mainnet
-- integration yet (no alchemy/infura/web3). Positions are seeded into
-- vault_positions by ops; force-tick reads them + the panel's current
-- ERC-20 prices, computes NAV, writes the row. A scheduled tick is the
-- same code, just called every minute by a loop.
--
-- ⚠️  RUN THIS BEFORE PUSHING THE CODE.
--     `tick_vault_nav()` will refuse with 404 against a missing
--     vault_nav_tick table, but the endpoint still produces a clean
--     diagnostic instead of crashing. So the order is "nice to have",
--     not load-bearing — unlike beta_core_nav.interval_hours (S-283).
--
-- Idempotent. Safe to re-run.
-- ============================================================================

-- ── 1. vault_state — durable state per vault ────────────────────────────────
-- One row per vault_id. share_count grows with deposits, shrinks with
-- withdrawals; inception_ts/nav anchor the per-share series.
CREATE TABLE IF NOT EXISTS public.vault_state (
    vault_id        text PRIMARY KEY,
    share_count     numeric NOT NULL CHECK (share_count >= 0),
    inception_ts    timestamptz NOT NULL,
    inception_nav   numeric NOT NULL CHECK (inception_nav > 0),
    as_of           timestamptz NOT NULL DEFAULT now(),
    note            text
);

COMMENT ON TABLE public.vault_state IS
    'CometCloud Layer II vault durable state (one row per vault_id). '
    'ETH ERC-20 only — Drift/Solana vault_state lives elsewhere.';


-- ── 2. vault_positions — ERC-20 holdings at as_of ───────────────────────────
-- Multi-row per vault_id; latest (as_of) per (vault_id, symbol, side) is the
-- current position. We don't store token addresses — symbol is canonical
-- (USDC, USDT, WETH, WBTC, DAI, ...). For tokens not in the panel, the
-- price lookup BLOCKS (we don't fabricate, NAV_POLICY §3).
CREATE TABLE IF NOT EXISTS public.vault_positions (
    id              bigserial PRIMARY KEY,
    vault_id        text NOT NULL,
    symbol          text NOT NULL,
    qty             numeric NOT NULL,           -- positive number; side encodes direction
    side            text NOT NULL CHECK (side IN ('LONG', 'SHORT')),
    as_of           timestamptz NOT NULL DEFAULT now(),
    source          text NOT NULL DEFAULT 'seed',
    note            text
);

CREATE INDEX IF NOT EXISTS idx_vault_positions_lookup
    ON public.vault_positions (vault_id, symbol, side, as_of DESC);

COMMENT ON TABLE public.vault_positions IS
    'CometCloud Layer II vault ERC-20 positions. Latest (as_of) per '
    '(vault_id, symbol, side) is the current holding. Source="seed" = ops '
    'inserted; future source="on_chain" needs ETH mainnet integration '
    '(alchemy/infura) which we do NOT have as of 2026-09-14.';


-- ── 3. vault_nav_tick — per-minute mark-to-market snapshot ──────────────────
-- One row per tick. tick_ts is the snapshot time (NOT insertion time).
-- nav_usd = sum(qty * price * sign(side)). nav_per_share = nav_usd /
-- share_count (from vault_state at tick_ts).
--
-- The table GROWS at ~1 row/minute/vault — for a single vault this is
-- ~525,600 rows/year. Index on (vault_id, tick_ts DESC) is the only
-- read pattern (latest NAV + time-series). Don't add other indexes
-- without a query that uses them — silent bloat.
CREATE TABLE IF NOT EXISTS public.vault_nav_tick (
    vault_id        text NOT NULL,
    tick_ts         timestamptz NOT NULL,
    nav_usd         numeric NOT NULL,
    share_count     numeric NOT NULL CHECK (share_count > 0),
    nav_per_share   numeric NOT NULL,
    holdings        jsonb NOT NULL,             -- [{symbol, qty, side, price, value_usd}, ...]
    source          text NOT NULL CHECK (source IN ('manual', 'loop')),
    PRIMARY KEY (vault_id, tick_ts)
);

CREATE INDEX IF NOT EXISTS idx_vault_nav_tick_recent
    ON public.vault_nav_tick (vault_id, tick_ts DESC);

COMMENT ON TABLE public.vault_nav_tick IS
    'CometCloud Layer II vault NAV tick (per-minute mark-to-market). '
    'source="manual" = force-tick via /internal/vault-tick/{vault_id}; '
    'source="loop" = scheduled per-minute tick. ETH ERC-20 vault only.';


-- ── 4. RLS — same role gate as *_paper_nav (service_role writes, anon reads) ─
-- Match the existing pattern: service_role bypasses RLS, anon gets SELECT only.
-- If the role that writes is different, adjust here.
ALTER TABLE public.vault_state       ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.vault_positions   ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.vault_nav_tick    ENABLE ROW LEVEL SECURITY;

-- anon / authenticated: SELECT only on vault_nav_tick (the public-facing series)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname='public' AND tablename='vault_nav_tick'
          AND policyname='vault_nav_tick_anon_select'
    ) THEN
        CREATE POLICY vault_nav_tick_anon_select ON public.vault_nav_tick
            FOR SELECT TO anon, authenticated
            USING (true);
    END IF;
END$$;

-- service_role bypasses RLS by default; no explicit policy needed for write.
-- If we add a NON-service-role writer later, add a policy FOR INSERT TO that role.
