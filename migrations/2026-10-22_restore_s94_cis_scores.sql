-- 2026-10-22 · restore the S-94 invariant: anon must read ZERO rows from cis_scores (applied 2026-10-22 00:06 UTC).
--
-- What happened: 2026-10-20_lane_read_publishable(_resume).sql put cis_scores on the lane_read list (anon SELECT,
-- using (true)) on the assumption that the only live anon credential was the new publishable key held by the lanes
-- and the Mac. It is not: the LEGACY anon JWT is still accepted by the project, and it is public — hardcoded in
-- scripts/external_probe.sh (and in git history). Measured 10-21: with that key, GET /rest/v1/cis_scores returned
-- rows (HTTP 200), and RLS cannot tell the two keys apart (both arrive as role anon with claims {"role":"anon"}).
-- scripts/external_probe.sh caught it: "CRITICAL:anon-read-cis_scores" (revoked 2026-07-30, S-94, must stay revoked).
--
-- Fix here: drop the anon policy on cis_scores. GRANT SELECT stays, so with RLS on and no policy anon reads [] —
-- exactly the state the probe asserts. Lanes and the Mac read CIS through cis_official_daily / the API, not this table.
-- The other lane_read tables are still readable with the legacy anon key until the legacy JWT API keys are
-- disabled in the Supabase dashboard (Jazz's action; nothing in production uses them since the 10-20 rotation).
-- Edge logs 2026-10-20 00:10 → 10-22 00:10 UTC: every legacy-anon request came from our own probe (curl, SG);
-- no publishable-key caller reads cis_scores, so dropping the policy breaks no lane.

drop policy if exists lane_read on public.cis_scores;
grant select on public.cis_scores to anon;
