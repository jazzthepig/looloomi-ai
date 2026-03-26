-- CometCloud: Wallet authentication profiles
-- Run this once in Supabase SQL Editor → https://supabase.com/dashboard/project/soupjamxlfsmgmmtoeok/sql/new

-- 1. Wallet profiles table
CREATE TABLE IF NOT EXISTS wallet_profiles (
  wallet_address  TEXT PRIMARY KEY,          -- Solana base58 pubkey
  display_name    TEXT,                      -- optional alias
  nonce           TEXT,                      -- current sign-in nonce
  created_at      TIMESTAMPTZ DEFAULT NOW(),
  last_seen       TIMESTAMPTZ DEFAULT NOW()
);

-- 2. Row Level Security
ALTER TABLE wallet_profiles ENABLE ROW LEVEL SECURITY;

-- 3. Policies (using anon key only — no Supabase Auth JWT required)
CREATE POLICY "wp_select" ON wallet_profiles
  FOR SELECT TO anon USING (true);

CREATE POLICY "wp_insert" ON wallet_profiles
  FOR INSERT TO anon WITH CHECK (true);

CREATE POLICY "wp_update" ON wallet_profiles
  FOR UPDATE TO anon USING (true);

-- Done. Table is live. Backend /api/v1/auth/* endpoints will now work.
