-- 2026-11-02 · lanes may read three ops logs (T-217: lane-a saw "0 rows" on loop_attempt and concluded nothing was
-- written; the table has 34k rows — RLS, not emptiness). loop_attempt (heartbeats + per-iteration reasons),
-- regime_band_log, crowd_clock_log: no keys, no positions of ours beyond what the public HL account already shows.
-- write_log / execution_intents / execution_outcomes / agent_call_log stay private.
do $$
declare t text;
begin
  foreach t in array array['loop_attempt','regime_band_log','crowd_clock_log']
  loop
    execute format('grant select on public.%I to anon', t);
    execute format('drop policy if exists lane_read on public.%I', t);
    execute format('create policy lane_read on public.%I for select to anon using (true)', t);
  end loop;
end $$;
