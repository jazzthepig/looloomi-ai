-- 2026-10-20 · resume the anon research reads suspended by 2026-10-20_lane_read_publishable_suspend.sql (applied).
--
-- Jazz created a fresh publishable key for the lanes and deleted the one published in docs/SUPABASE_SETUP.md
-- (06-19 → 10-20). The only live publishable key now sits in ~/.cometcloud/lane.env and the two Mac .env files,
-- none of which is in git (scripts/secret_scan.py now flags real-length sb_publishable_ keys).
-- Same table list and policy as 2026-10-20_lane_read_publishable.sql.

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
    execute format('grant select on public.%I to anon', t);
    execute format('drop policy if exists lane_read on public.%I', t);
    execute format('create policy lane_read on public.%I for select to anon using (true)', t);
  end loop;
end $$;

-- + assets (applied separately as lane_read_assets): ohlcv_daily_canonical is security_invoker and joins assets;
-- the Mac preflight's S-361 stage reads the view with the publishable key now and got 401 without it.
grant select on public.assets to anon;
drop policy if exists lane_read on public.assets;
create policy lane_read on public.assets for select to anon using (true);
