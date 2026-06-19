# Supabase Setup — CometCloud AI
_Last updated: 2026-03-28_

## Project
- URL: `https://soupjamxlfsmgmmtoeok.supabase.co`
- Publishable key: `sb_publishable_wdExIZf7M5AXW6ss12vBBA_RPPwm8KF`

---

## Railway Environment Variables

| Key | Value | Notes |
|-----|-------|-------|
| `SUPABASE_URL` | `https://soupjamxlfsmgmmtoeok.supabase.co` | Already in `store.py` |
| `SUPABASE_KEY` | `<service_role_key>` | Use **service_role** key (not anon) — backend only |

> ⚠️ The backend uses the service_role key for upserts that bypass Row Level Security.
> Never expose the service_role key to the frontend.
> The anon key is returned by `/api/v1/auth/config` for frontend-direct queries (read-only RLS).

---

## Tables

### 1. `wallet_profiles`
Used by auth router: `/api/v1/auth/wallet-signin` upserts here on every sign-in.

```sql
CREATE TABLE public.wallet_profiles (
  id               uuid        DEFAULT gen_random_uuid() PRIMARY KEY,
  wallet_address   text        UNIQUE NOT NULL,
  created_at       timestamptz DEFAULT now() NOT NULL,
  last_seen        timestamptz DEFAULT now() NOT NULL,
  display_name     text,
  risk_profile     text        DEFAULT 'moderate',  -- conservative | moderate | aggressive
  total_allocated  numeric     DEFAULT 0,
  metadata         jsonb       DEFAULT '{}'::jsonb
);

-- Enable RLS
ALTER TABLE public.wallet_profiles ENABLE ROW LEVEL SECURITY;

-- Backend (service_role) can do everything
-- Frontend with anon key can only read their own row (future: Supabase Auth JWT)
CREATE POLICY "service_role_all" ON public.wallet_profiles
  USING (true) WITH CHECK (true);

-- Index for fast lookups by wallet address
CREATE INDEX idx_wallet_profiles_address ON public.wallet_profiles (wallet_address);
```

### 2. `cis_scores`
Already exists (from Week 2 setup). Used by `store.py` for score history.

```sql
-- Verify it exists:
SELECT table_name FROM information_schema.tables
WHERE table_schema = 'public' AND table_name = 'cis_scores';
```

If missing, create:
```sql
CREATE TABLE public.cis_scores (
  id           uuid        DEFAULT gen_random_uuid() PRIMARY KEY,
  symbol       text        NOT NULL,
  score        numeric,
  grade        text,
  signal       text,
  percentile   numeric,
  pillar_f     numeric,
  pillar_m     numeric,
  pillar_o     numeric,
  pillar_s     numeric,
  pillar_a     numeric,
  source       text        DEFAULT 'railway',  -- railway | local
  recorded_at  timestamptz DEFAULT now() NOT NULL
);

CREATE INDEX idx_cis_scores_symbol_time ON public.cis_scores (symbol, recorded_at DESC);
```

---

## Verification

After running the SQL above, verify from Railway logs:

```bash
# Should see on first wallet sign-in:
[AUTH] Supabase upsert OK for <address>

# On subsequent sign-ins:
[AUTH] Supabase upsert OK (merge-duplicates)
```

Or query directly:
```sql
SELECT wallet_address, created_at, last_seen FROM wallet_profiles ORDER BY created_at DESC LIMIT 10;
```

---

## Auth Flow Summary

```
Browser (Phantom)
  → GET /api/v1/auth/nonce/{address}    (nonce stored in Redis, 5min TTL)
  → signMessage(nonce)                  (Phantom popup)
  → POST /api/v1/auth/wallet-signin     (Ed25519 verify via PyNaCl)
       → upsert wallet_profiles          (Supabase REST, service_role key)
       → issue session_token             (Redis, 24h TTL)
  → AuthContext stores token + address in localStorage
  → All components read auth state via useAuth()
```

## Frontend Auth Config

`VITE_API_URL` must be set in `dashboard/.env.local` for local dev:
```
VITE_API_URL=http://localhost:8000
```

For Railway production, requests use same-origin (empty `VITE_API_URL`).
