-- S-323d (2026-09-08) — applied to production directly.
--
-- TWO FIXES FOR `refresh_depth_divergence` (5238 ms → 106 ms, 49×).
--
-- ROOT CAUSE. The function scans `ohlcv_daily` (464k rows) four times with
-- `source NOT IN ('binance_hist','coingecko','yfinance')`. Only 6533 rows
-- (1.4%) match, but none of the three indexes lead with the negative filter,
-- so every scan is a parallel seq scan of the whole table. Warm and idle this
-- cost 5238 ms — under anon's 8 s statement_timeout it ran; under production
-- I/O it did not. PostgREST got a 500, retried, each retry also got killed,
-- all retries exhausted, `supabase_rpc_write` returned None, and the error
-- said "no response from Supabase after retries" — a sentence about silence,
-- not about duration, which sent investigation toward connectivity.
--
-- This is the SAME shape as the S-323 index fix on the source-equality path:
-- a query too slow to finish under the caller's timeout, reported as a
-- network fault. S-323 was equality (`source = 'binance_hist'`), this one is
-- negation (`source NOT IN ...`). Different operator, same consequence.
--
-- FIX 1: partial index. The 6533-row subset is stable (it is the non-deep,
-- non-CoinGecko, non-yfinance slice — the maintained venue feeds). A partial
-- index lets Postgres jump straight to it.
--
-- FIX 2: per-function statement_timeout. Even after the index (106 ms), a
-- future table growth or a new scan path could push it back above 8 s. The
-- function runs once per day and writes, so giving it 30 s is proportionate.
-- The override is per-function (ALTER FUNCTION ... SET), not per-role, so it
-- applies regardless of which key calls it.
--
-- ALSO: `NOTIFY pgrst, 'reload schema'` — the S-323 RPCs
-- (deep_panel_symbol_list, forward_return_coverage) existed in pg_proc but
-- PostgREST had not reloaded its schema cache after the migration. Calls
-- returned 404, and `_supabase_request_with_retry` treats 404 as a
-- "non-retryable client error" → records SUCCESS on the circuit breaker →
-- health showed "breaker closed, 0 failures" while every RPC silently failed.
-- Two states, one representation, again.

-- ── Partial index ───────────────────────────────────────────────────────────
create index if not exists ohlcv_daily_depth_divergence_idx
  on public.ohlcv_daily (trade_date, symbol, source)
  where source not in ('binance_hist','coingecko','yfinance')
    and asset_class in ('Crypto','L1','L2','DeFi','Infrastructure','RWA');

-- ── Per-function timeout ────────────────────────────────────────────────────
alter function public.refresh_depth_divergence(date) set statement_timeout = '30s';
alter function public.resolve_depth_divergence()     set statement_timeout = '30s';

-- ── Schema cache reload ─────────────────────────────────────────────────────
notify pgrst, 'reload schema';
