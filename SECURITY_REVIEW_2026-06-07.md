# Stability & Security Review — 2026-06-07

Live deploy: `c2944016`. Method: live probes + Supabase security advisors + repo scan.

## Stability — ✅ healthy

- Mac Mini push **fresh** (28 min ago, not stale), **43 T1 assets**, **drift = 0**
  (contract fully aligned — engine now sends clean schema_version/provenance).
- Universe: `merged`, 58 assets, regime Tightening, `status: success`. No errors.
- App health 200, uptime ~3.4h. Internal write endpoints reject without token (401).
- The TradFi D-grade fix + never-empty floor are holding.

## Security — findings (severity-ranked)

### 🔴 HIGH — Supabase RLS write policies are wide open to `anon`
Many tables have RLS policies with `WITH CHECK (true)` / `USING (true)` for
INSERT/UPDATE/DELETE, and the **anon key is committed** in `run_reconstruction.command`
(anon keys are public-by-design, so assume it's known). Net effect: anyone can
write to these tables directly via `…supabase.co/rest/v1/…`:

- **`api_keys`** — anon INSERT *and* UPDATE → forge/escalate RaaS API keys. Worst one.
- **`signal_journal`** — anon INSERT/UPDATE → fabricate or alter the signal track
  record. The track record is the BP; a forgeable one is a due-diligence red flag.
- **`cis_scores`, `macro_briefs`** — anon INSERT → poison displayed intelligence.
- **`wallet_profiles`** — anon INSERT/UPDATE.
- **`webhook_subscriptions`** — anon INSERT/UPDATE/DELETE → add/remove alert sinks.
- **`trade_results`, `analytics_events`, `agent_call_log`, `cis_backtest_results`** — anon INSERT (data poisoning).

**Why the fix is safe:** the backend writes with the **service_role** key, which
bypasses RLS entirely — and the frontend does **not** talk to Supabase directly
(no `supabase.co` in the shipped bundle). So these anon write policies are pure
attack surface; dropping them changes nothing for the app.

### 🟠 MEDIUM
- **3 SECURITY DEFINER views** (`regime_transitions`, `cis_score_history_7d`,
  `cis_score_latest`) — linter ERROR; run with creator privileges, bypass RLS.
  → recreate as `SECURITY INVOKER`.
- **2 SECURITY DEFINER functions callable by anon** (`increment_api_key_usage`,
  `increment_webhook_delivery`) via `/rest/v1/rpc/…` → revoke anon EXECUTE.
- **Committed anon key** in `run_reconstruction.command` → remove from repo.

### 🟡 LOW / hardening
- `function_search_path_mutable` on the 2 functions → set `search_path`.
- `/internal/build-state` + `/internal/health-summary` are public (no token) —
  they expose deploy sha / push freshness / drift. Not secrets, but recon info;
  consider token-guarding or trimming provenance from the public response.
- `leads`, `vault_deposit_intents`: RLS on, no policy → **deny by default (safe)**.

## Remediation plan (proposed migration — needs your green light)
1. Drop the permissive anon INSERT/UPDATE/DELETE policies on the tables above
   (backend keeps working via service_role).
2. Recreate the 3 views as SECURITY INVOKER.
3. `REVOKE EXECUTE … FROM anon, authenticated` on the 2 RPC functions; set search_path.
4. Remove the anon key from `run_reconstruction.command` (use env var).

Items 1–3 are Supabase DDL (I can apply via migration once you approve — it's
safe given service_role backend). Item 4 is a repo edit + commit.
