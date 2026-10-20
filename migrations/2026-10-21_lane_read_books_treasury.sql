-- 2026-10-21 · lanes read the paper-book tables and the corporate-treasury tables (publishable key = anon, read-only).
--
-- Why: tonight's cards need them — S-634 (T-148) rebuilds ① weights from cis_tilt_daily exactly like S-630; S-636 (T-150)
-- reads treasury_decisions / corporate_treasury_history; the R-v2 paper book (r_tickets_paper / r_tickets_state) is
-- what the convex-sleeve cards compare against. r_tickets_paper already had an anon grant but RLS on and no policy —
-- the same HTTP-200-and-0-rows trap trending_log had (2026-10-20). All are research / public-filing data; writes stay
-- with the secret keys.

do $$
declare t text;
begin
  foreach t in array array['cis_tilt_daily','core_cap_daily','core_variants_daily','r_tickets_paper','r_tickets_state',
                           'treasury_decisions','corporate_treasury_history']
  loop
    execute format('grant select on public.%I to anon', t);
    execute format('drop policy if exists lane_read on public.%I', t);
    execute format('create policy lane_read on public.%I for select to anon using (true)', t);
  end loop;
end $$;
