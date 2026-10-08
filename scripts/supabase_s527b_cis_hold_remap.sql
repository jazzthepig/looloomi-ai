-- Compliance (CLAUDE.md rule 1): 2026-04-16 → 2026-06-05 the local engine wrote signal='HOLD' into cis_scores
-- before the push-boundary remap (_SIGNAL_REMAP in src/api/contracts/cis_push.py) existed. Remap the history
-- the same way the boundary does today; one audit row per change so the original label is recoverable.
-- AS APPLIED 2026-10-08 (migration s527b_cis_hold_remap): 330 rows audited and remapped; 0 non-compliant left.
create table if not exists public.cis_signal_remap_audit (
  cis_id      bigint not null,
  old_signal  text not null,
  new_signal  text not null,
  remapped_at timestamptz not null default now(),
  primary key (cis_id)
);
alter table public.cis_signal_remap_audit enable row level security;
revoke all on public.cis_signal_remap_audit from anon, authenticated;
grant select, insert, update, delete on public.cis_signal_remap_audit to service_role;
insert into public.cis_signal_remap_audit (cis_id, old_signal, new_signal)
  select id, signal, 'NEUTRAL' from public.cis_scores where signal = 'HOLD'
  on conflict (cis_id) do nothing;
update public.cis_scores set signal = 'NEUTRAL' where signal = 'HOLD';
