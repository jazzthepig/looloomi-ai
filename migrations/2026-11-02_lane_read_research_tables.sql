-- 2026-11-02 · lanes (publishable key, role anon) may read the 11-02 research tables (S-705).
--
-- Why: T-222 needs venue_depth_snapshots (HL ±2% depth → capacity); the liq-map replay card needs
-- hl_liq_map_hourly; lanes should see their own scored propositions (scenario_ledger / scenario_scores).
-- All four are aggregates or ex-ante statements — no addresses, no keys, no positions of ours.
-- overlay_daily / overlays stay private (they describe real-money deviations).

do $$
declare t text;
begin
  foreach t in array array['venue_depth_snapshots','hl_liq_map_hourly','scenario_ledger','scenario_scores']
  loop
    execute format('grant select on public.%I to anon', t);
    execute format('drop policy if exists lane_read on public.%I', t);
    execute format('create policy lane_read on public.%I for select to anon using (true)', t);
  end loop;
end $$;
