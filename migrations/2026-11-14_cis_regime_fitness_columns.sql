-- 2026-11-14 · cis_regime_fitness: the two columns its writer has been sending (S-863).
-- 已通过 Supabase MCP 施加:cis_regime_fitness_return_source_n_days。
--
-- WHY. _regime_fitness_loop computes, per macro regime and pillar, the correlation between the pillar score and the
-- realised 7-day return, and posts {regime, pillar, correlation, n_samples, return_source, window_days, computed_at}.
-- The table never had `return_source`, so every write was rejected with 400 (PGRST204). Nobody saw it for months
-- because until 10-30 there were fewer than 20 independent days and the function returned nothing to write; since
-- 10-30 it has had rows to write and has failed on every round. The table has 0 rows.
--
-- WHAT. `return_source` (trade_results | coingecko_price | score_proxy; score_proxy is the unvalidated fallback and
-- must stay distinguishable) and `n_days` (independent days: n_samples counts rows, and cis_scores holds many rows per
-- symbol-day, so n_samples overstates the sample by the number of intraday snapshots — S-202).
--
-- WHO READS IT. Nothing in the scoring path: the live IC multiplier reads the Redis key cis:factor_performance, the
-- official daily CIS is computed with ic_mult=None, and no engine-side code reads this table. It is a record.
--
-- EXPECTED FIRST ROWS (measured 11-14 before the fix): in the 90-day window only TIGHTENING clears the 20-day floor
-- with real returns (21 days, 139 symbol-days) — so about five rows, one per pillar, return_source = trade_results.
--
-- LIVENESS: select regime, pillar, correlation, n_samples, n_days, return_source, computed_at
--           from cis_regime_fitness order by computed_at desc limit 10;   -- a new batch each day

alter table public.cis_regime_fitness
  add column if not exists return_source text,
  add column if not exists n_days integer;
comment on column public.cis_regime_fitness.return_source is 'where the 7-day return came from: trade_results | coingecko_price | score_proxy (score_proxy = unvalidated)';
comment on column public.cis_regime_fitness.n_days is 'independent days behind this correlation; n_samples counts rows, and cis_scores has many rows per symbol-day';
notify pgrst, 'reload schema';
