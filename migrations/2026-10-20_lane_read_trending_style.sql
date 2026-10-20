-- 2026-10-20 · lanes read trending_log and style_index_pit_daily (publishable key = anon, read-only).
--
-- Why: trending_log had RLS on and NO anon policy, so a lane reading it with the publishable key got 0 rows with
-- HTTP 200 — not an error. The S-626 narrative A/B froze its T arm (CoinGecko trending) for 2026-W43 with 0 names
-- while the table held 3,570 rows in the last 14 days. style_index_pit_daily (the majors 200-day gate that the
-- R-v2 tickets, ③ and ⓠ q_slow all read) had no anon grant at all. Both are market / research data; writes stay
-- with the secret keys.

do $$
declare t text;
begin
  foreach t in array array['trending_log','style_index_pit_daily']
  loop
    execute format('grant select on public.%I to anon', t);
    execute format('drop policy if exists lane_read on public.%I', t);
    execute format('create policy lane_read on public.%I for select to anon using (true)', t);
  end loop;
end $$;
