-- S-607 / T-026 (2026-10-19): fusion v3 could never write a row.
--
-- fusion_paper.py moved _INCEPTION_ID to "v3" on 2026-10-13 (S-561: v2 had marked 51 days of
-- cost-only returns). The CHECK added in 2026-09-15_s336_fusion_paper_state_recovery.sql only
-- allows ('v1', 'v2'), so every v3 NAV insert has been refused with SQLSTATE 23514 - first hidden
-- behind the Binance 451 outage (the book never got far enough to write), then visible on the
-- first mark after S-607: 2026-10-19 00:05-00:33 UTC, 14 attempts, all
-- "durable_write_failed :: fusion_paper_nav: HTTP 400 code 23514".
--
-- Idempotent: drop-if-exists, then add with the extended list.
ALTER TABLE fusion_paper_nav DROP CONSTRAINT IF EXISTS fusion_paper_nav_inception_chk;
ALTER TABLE fusion_paper_nav
    ADD CONSTRAINT fusion_paper_nav_inception_chk
    CHECK (inception_id IN ('v1', 'v2', 'v3'));
