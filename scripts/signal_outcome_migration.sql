-- Signal Outcome Tracker: Add 30d outcome columns to signal_journal
-- Run this on Supabase SQL editor after ohlcv_collector is running (30d data needed)

ALTER TABLE signal_journal
  ADD COLUMN IF NOT EXISTS outcome_30d     TEXT,  -- WIN | LOSS | EXPIRED | PENDING
  ADD COLUMN IF NOT EXISTS return_pct_30d  REAL,  -- return from entry to 30d mark
  ADD COLUMN IF NOT EXISTS price_at_30d    REAL,  -- price at 30d mark (OHLCV close)
  ADD COLUMN IF NOT EXISTS mcap_at_30d     REAL,  -- market cap at 30d mark
  ADD COLUMN IF NOT EXISTS circ_supply_at_entry REAL;  -- circulating supply at signal entry

-- Index for outcome queries
CREATE INDEX IF NOT EXISTS idx_sj_outcome ON signal_journal(outcome_30d)
  WHERE outcome_30d IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_sj_30d_pending ON signal_journal(id)
  WHERE outcome_30d IS NULL AND exit_date IS NULL AND signal_date < NOW() - INTERVAL '30 days';