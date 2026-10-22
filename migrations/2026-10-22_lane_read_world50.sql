-- 2026-10-22 · lanes read the World50 equity panel (CIS v2 / S-668: equities get the same "quality + supply discipline"
-- score as coins; lane-a runs the equity study on world50_mcap_weekly + world50_revenue + eodhd closes).
-- Public-company market data and SEC-filed revenue; the publishable key that maps to anon is held only by the lanes
-- and the Mac (legacy JWT keys disabled and the legacy JWT secret revoked 2026-10-22). Same policy as the other lane_read tables.

do $$
declare t text;
begin
  foreach t in array array['world50_mcap_weekly', 'world50_revenue']
  loop
    execute format('grant select on public.%I to anon', t);
    execute format('drop policy if exists lane_read on public.%I', t);
    execute format('create policy lane_read on public.%I for select to anon using (true)', t);
  end loop;
end $$;
