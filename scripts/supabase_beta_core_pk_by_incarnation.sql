-- beta_core_nav: the primary key must carry the incarnation — 2026-08-09
--
-- WHAT BROKE. The v2 inception could not be written:
--
--   [SUPABASE] Insert into beta_core_nav failed: 409
--     {"code":"23505","details":"Key (mark_date)=(2026-08-09) already exists.",
--      "message":"duplicate key value violates unique constraint"}
--   [beta_core] NAV WRITE REJECTED for 2026-08-09
--   [beta_core] INCEPTION NOT PERSISTED — refusing to cache state
--   [BETA-CORE] mark — status=inception_failed
--
-- The table was created with `PRIMARY KEY (mark_date)`. The re-inception design gave
-- a row a second identity dimension — which incarnation produced it — and kept the
-- voided v1 rows in place deliberately, because the graveyard is the asset. But the
-- key still said a row IS a date. So v1's voided 2026-08-09 row silently forbade
-- v2's 2026-08-09 row.
--
-- THE GENERALISABLE PART. When an entity gains a dimension of identity, the
-- uniqueness constraint has to gain it in the same change, or the OLD definition of
-- identity quietly vetoes the new one. Same family as the L0 defect where
-- `asset_class` lived on observation rows: an identity recorded at the wrong grain.
-- Here it was recorded at the right grain in the column and the wrong grain in the key.
--
-- Two incarnations are two independent series. Both may legitimately hold a row for
-- the same calendar day, and reading either one alone must still be unambiguous —
-- which is exactly what a composite key gives.
--
-- WHY THIS WAS VISIBLE AT ALL. The three log lines above exist because of the fix
-- made an hour earlier (capture the insert's return value, refuse to cache an
-- unpersisted mark). Before it, this 409 would have been swallowed and the book
-- would have cached a NAV with no row behind it. The refusal also means no corrupt
-- state accumulated while this was broken — the retry is clean.

begin;

-- every existing row already carries 'v1' from the re-inception migration; assert it
-- rather than assume, because a NULL would silently fall out of a composite key
update beta_core_nav set inception_id = 'v1' where inception_id is null;

alter table beta_core_nav alter column inception_id set not null;

alter table beta_core_nav drop constraint beta_core_nav_pkey;
alter table beta_core_nav add constraint beta_core_nav_pkey
    primary key (inception_id, mark_date);

commit;

-- ── VERIFY ───────────────────────────────────────────────────────────────────
-- select pg_get_constraintdef(con.oid)
--   from pg_constraint con join pg_class c on c.oid = con.conrelid
--  where c.relname = 'beta_core_nav' and con.contype = 'p';
-- expect: PRIMARY KEY (inception_id, mark_date)
--
-- ── THEN ─────────────────────────────────────────────────────────────────────
-- The loop sleeps 24h between marks, so the retry is bound to a process restart.
-- Redeploy on Railway, wait ~10 minutes for the warmup, then:
--
--   select mark_date, nav, exposure_cap, regime, cap_source, inception_id
--     from beta_core_nav where inception_id = 'v2';
--
-- expect ONE row: nav 1.0, exposure_cap 0.5, regime TIGHTENING.
-- The Redis key does not need deleting — the previous attempt refused to cache, so
-- there is no state asserting an inception that never happened.
