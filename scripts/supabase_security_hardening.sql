-- ============================================================================
-- Security hardening — 11 advisor ERRORs + the exploitable ones (2026-07-30)
-- ============================================================================
-- These are not lint opinions. Verified live with a bare `anon` key that anyone
-- can read out of a browser bundle:
--
--   GET  /rest/v1/cis_scores          -> real grades + signals   ← the product
--   GET  /rest/v1/signal_outcomes     -> full signal history + alpha
--   GET  /rest/v1/asset_embeddings    -> 27-dim vectors          ← core IP
--   POST /rest/v1/rpc/backfill_binance_ohlcv  -> HTTP 200        ← REMOTE WRITE
--
-- The last one is the severe one and it is mine (scripts/supabase_ohlcv_backfill.sql):
-- a SECURITY DEFINER function, callable by anonymous internet users, that runs
-- with owner privileges, makes outbound HTTP calls, and writes ohlcv_daily. It is
-- an anonymous remote write primitive, an outbound-request trigger, and a
-- plausible amplifier of the 2026-07-29 connection exhaustion (S-92) — a
-- long-running DEFINER function that anyone could invoke at will.
--
-- ── SAFETY: why enabling RLS will NOT break production ─────────────────────
-- Verified before writing this, not assumed:
--   1. `public.leads` has RLS enabled with ZERO policies, yet contains a row
--      written 2026-07-16. A write that lands through RLS-with-no-policy proves
--      the writer BYPASSES RLS ⇒ SUPABASE_KEY is the service_role key.
--   2. The dashboard never calls supabase.co directly — no VITE_SUPABASE env,
--      all traffic goes through /api/v1/*. So no browser client depends on anon
--      read access.
--   3. Nothing in src/ or dashboard/ calls backfill_binance_ohlcv, so revoking
--      it breaks no code path.
-- ⇒ service_role bypasses RLS; enabling it blocks only anonymous access.
--
-- APPLY: Mac side. Verify with §6.
-- ============================================================================

BEGIN;

-- ── 1. URGENT — close the anonymous remote-write primitive ──────────────────
-- Revoke from PUBLIC as well: PUBLIC grants are the reason anon/authenticated
-- had EXECUTE even though nobody granted it to them explicitly.
REVOKE ALL ON FUNCTION public.backfill_binance_ohlcv(text, text, bigint) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.backfill_binance_ohlcv(text, text, bigint) FROM anon;
REVOKE ALL ON FUNCTION public.backfill_binance_ohlcv(text, text, bigint) FROM authenticated;
GRANT  EXECUTE ON FUNCTION public.backfill_binance_ohlcv(text, text, bigint) TO service_role;

-- The maintenance refreshers are operator tools, not user-facing API.
REVOKE ALL ON FUNCTION public.refresh_signal_track_record() FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.refresh_signal_edge_map()     FROM PUBLIC, anon, authenticated;
GRANT  EXECUTE ON FUNCTION public.refresh_signal_track_record() TO service_role;
GRANT  EXECUTE ON FUNCTION public.refresh_signal_edge_map()     TO service_role;

-- ── 2. Pin search_path on every SECURITY DEFINER function ───────────────────
-- A DEFINER function with a mutable search_path can be hijacked: an attacker who
-- can create objects in an earlier schema shadows a function/table name and the
-- DEFINER body executes their code with owner privileges. Pinning is the fix.
-- Signatures read from pg_proc before writing this, not guessed. The first draft
-- had `decision_source_term(text)`; it is actually `(date, integer)` — that alone
-- would have aborted the whole transaction. Verified set:
--   backfill_binance_ohlcv(p_symbol text, p_asset_class text, p_start_ms bigint)  DEFINER
--   refresh_signal_edge_map()                                                     DEFINER
--   refresh_signal_track_record()                                                 DEFINER
--   decision_source_term(as_of date, lookback_days integer)                       invoker
--   match_asset_embeddings(target text, k integer, class_mode text)               invoker
ALTER FUNCTION public.refresh_signal_track_record()                    SET search_path = public, pg_temp;
ALTER FUNCTION public.refresh_signal_edge_map()                        SET search_path = public, pg_temp;
ALTER FUNCTION public.backfill_binance_ohlcv(text, text, bigint)       SET search_path = public, pg_temp;
ALTER FUNCTION public.decision_source_term(date, integer)              SET search_path = public, pg_temp;
ALTER FUNCTION public.match_asset_embeddings(text, integer, text)      SET search_path = public, pg_temp;

-- ── 3. SECURITY DEFINER views → SECURITY INVOKER ────────────────────────────
-- A DEFINER view enforces the CREATOR's permissions and RLS, so it silently
-- launders access around whatever RLS we add below. Postgres 15+ supports the
-- security_invoker option, which is what we want: the QUERYING role's rules apply.
ALTER VIEW public.signal_beta_scorecard SET (security_invoker = true);
ALTER VIEW public.asset_edge_moments    SET (security_invoker = true);

-- ── 4. Enable RLS on every PostgREST-exposed table (9 ERRORs) ───────────────
-- No policies are added: service_role bypasses RLS, so our API and the Mac push
-- keep working, while anon/authenticated get nothing. Default-deny is correct
-- here — every one of these is internal IP, none is meant to be public read.
ALTER TABLE public.narrative_snapshots      ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.dingge_paper_nav         ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.combined_book_nav        ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.scalable_book_nav        ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.conviction_watchlist_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.signal_outcomes          ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.asset_embeddings         ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.entities                 ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.decisions                ENABLE ROW LEVEL SECURITY;

-- ── 4b. The policies the advisor could NOT flag ─────────────────────────────
-- cis_scores/ohlcv_daily/signal_journal were absent from the ERROR list because
-- RLS *is* enabled on them — yet a bare anon key returned real rows. Queried
-- pg_policies to find out why, rather than guessing:
--
--   cis_scores    | "Allow anon read"    | SELECT | {public} | USING (true)
--   cis_scores    | cis_scores_select    | SELECT | {public} | USING (true)
--   ohlcv_daily   | od_select            | SELECT | {public} | USING (true)
--   signal_journal| sj_select            | SELECT | {public} | USING (true)
--
-- Four `USING (true)` SELECT policies granted to `public`. The advisor
-- deliberately excludes permissive SELECT policies (that pattern is often
-- intentional public read), so THE MOST IMPORTANT EXPOSURES WERE NOT IN THE
-- 11 ERRORS AT ALL. Reading the advisor list alone would have left the product
-- itself — live CIS grades and signals — world-readable.
--
-- Note cis_scores carries TWO overlapping always-true policies, i.e. this was
-- opened twice independently. RLS with `USING (true)` for `public` is RLS in
-- name only.
DROP POLICY IF EXISTS "Allow anon read"  ON public.cis_scores;
DROP POLICY IF EXISTS cis_scores_select  ON public.cis_scores;
DROP POLICY IF EXISTS od_select          ON public.ohlcv_daily;
DROP POLICY IF EXISTS sj_select          ON public.signal_journal;
-- Service_role bypasses RLS, so the API keeps full read access. If any public
-- surface genuinely needs one of these, expose it through /api/v1/* (where we
-- control shaping, compliance language, and rate limits) — never by opening the
-- table.

-- ── 5. Drop the "always true" INSERT policies (7 WARNs) ─────────────────────
-- WITH CHECK (true) for INSERT with role `-` means ANY caller can insert. Our
-- writers use service_role and bypass RLS, so these policies grant nothing we
-- need and everything we don't.
DROP POLICY IF EXISTS causal_paper_nav_insert       ON public.causal_paper_nav;
DROP POLICY IF EXISTS cause_outcomes_insert         ON public.cause_outcomes;
DROP POLICY IF EXISTS cause_snapshots_insert        ON public.cause_snapshots_daily;
DROP POLICY IF EXISTS conviction_verdicts_insert    ON public.conviction_verdicts_daily;
DROP POLICY IF EXISTS experiment_runs_insert        ON public.experiment_runs;
DROP POLICY IF EXISTS prediction_outcomes_insert    ON public.prediction_outcomes;
DROP POLICY IF EXISTS two_layer_paper_nav_insert    ON public.two_layer_paper_nav;

COMMIT;

-- ── DEFERRED, with the reason stated ───────────────────────────────────────
-- `extension_in_public` (vector): moving pgvector out of `public` rewrites the
-- type reference on asset_embeddings.vec and invalidates the HNSW index. It is a
-- hardening nicety, not an exploitable hole, and the cost of getting it wrong
-- right after a P0 outage exceeds the benefit. Do it as a planned migration with
-- the index rebuild in the same transaction — NOT bundled into a security fix.
--
-- HNSW right-sizing also stays separate (see supabase_connection_hygiene.sql §3):
-- index name confirmed as `asset_embeddings_vec_hnsw`, created with DEFAULT
-- m=16 / ef_construction=64 on a 72-row table — heavy over-provisioning, and the
-- source of the write cost behind S-92. Safe to apply now, but as its own change
-- so that a security rollback never drags an index rebuild with it.

-- ── 6. Verification — run and paste into the ledger ────────────────────────
-- 6a. The exploit must now fail. Expect 401/403, NOT 200:
--     curl -s -o /dev/null -w '%{http_code}\n' -X POST -H "apikey: $ANON" \
--       -H 'Content-Type: application/json' -d '{"p_symbol":"x","p_asset_class":"crypto","p_start_ms":1}' \
--       "$SB/rest/v1/rpc/backfill_binance_ohlcv"
--
-- 6b. Anonymous reads must return [] on every hardened table:
--     for t in cis_scores signal_outcomes asset_embeddings entities decisions; do
--       curl -s -H "apikey: $ANON" "$SB/rest/v1/$t?select=*&limit=1"; echo " <- $t"; done
--
-- 6c. Find the permissive policy that still exposes cis_scores:
--     SELECT tablename, policyname, cmd, roles, qual, with_check
--       FROM pg_policies WHERE schemaname='public' AND tablename='cis_scores';
--
-- 6d. Confirm the match_asset_embeddings signature if §2 errored:
--     SELECT p.proname, pg_get_function_identity_arguments(p.oid)
--       FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
--      WHERE n.nspname='public' AND p.proname='match_asset_embeddings';
--
-- 6e. Production must still work (service_role path unaffected):
--     curl -sm12 -o /dev/null -w '%{http_code} %{time_total}\n' \
--       "$BASE/api/v1/cis/universe?limit=2"
--     …and confirm the Mac push still lands: newest cis_scores row < 1h old.
