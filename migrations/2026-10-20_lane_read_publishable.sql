-- 2026-10-20 · lanes read with the PUBLISHABLE key only (Jazz ruling after the service_role leak).
--
-- Why: lanes run on a third-party relay and had been reading the service_role key out of .env since 10-07;
-- one pushed it to a public branch. From now on a lane holds only the publishable key (Postgres role anon),
-- so a leaked lane credential is read-only on the tables below and nothing else.
-- The list is exactly what the Mac side GET-read in the 24h before the change (edge logs 10-19 03:10 →
-- 10-20 03:09), plus the research tables the mining families use. Market / research data only:
-- no wallet, lead, API-key, executor or user table is here. Writes stay with the secret keys
-- (Railway, Mac engine); write RPCs (backfill_binance_ohlcv, refresh_signal_edge_map) are NOT granted.

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

-- security_invoker views over the tables above
grant select on public.ohlcv_daily_canonical to anon;
grant select on public.deriv_metrics_plan to anon;

-- read-only diagnostics RPCs (STABLE, SECURITY INVOKER: they see only what anon sees)
grant execute on function public.producer_freshness() to anon;
grant execute on function public.watch_census() to anon;
grant execute on function public.ohlcv_symbol_coverage(text) to anon;
grant execute on function public.ohlcv_source_coverage(integer, integer, integer, integer) to anon;
