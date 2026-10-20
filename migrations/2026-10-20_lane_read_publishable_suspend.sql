-- 2026-10-20 · suspend the anon reads opened by 2026-10-20_lane_read_publishable.sql (applied).
--
-- Why: the project's publishable key has sat in the PUBLIC docs/SUPABASE_SETUP.md since 2026-06-19.
-- RLS cannot tell one publishable key from another (all map to role anon), so while that key is
-- alive, an anon read policy = the research tables are public. Re-apply lane_read_publishable after
-- Jazz creates a new publishable key for lanes and deletes the published one.
-- GRANT SELECT stays; with RLS on and no policy, anon reads zero rows.

do $$
declare t text;
begin
  foreach t in array array[
    'ohlcv_daily','ohlcv_hourly','funding_history','open_interest_history','deriv_metrics_daily',
    'asset_mcap_daily','cg_coin_mcap_daily','macro_daily','macro_briefs',
    'cis_scores','cis_official_daily','cis_rebuild_daily','state_daily','multiplier_daily','risk_meter_history',
    'asset_embeddings','market_state_vectors','signal_edge_map','signal_journal','prediction_outcomes',
    'strategy_params','strategy_records','experiment_runs','decisions','r77_forward_episodes',
    'beta_core_nav','beta_core_nav_q','beta_core_nav_q_meta']
  loop
    execute format('drop policy if exists lane_read on public.%I', t);
  end loop;
end $$;
