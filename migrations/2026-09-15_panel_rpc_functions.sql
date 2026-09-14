-- ============================================================================
-- Panel RPCs — three read/write functions the code calls but Postgres
-- doesn't have (drift detected 2026-09-15 by A-29 + supabase_function_exists
-- probe in src/api/routers/research_intake.py).
--
--   panel_closes(p_symbols text[], p_days int)
--       → TABLE(symbol text, closes numeric[], source text)
--     Reads ohlcv_daily, picks ONE source per symbol from PAID_SOURCES,
--     returns close series ASCENDING by trade_date.
--
--   panel_funding(p_symbols text[], p_points int)
--       → TABLE(symbol text, rates double precision[])
--     Reads funding_history, returns the most-recent p_points rates per
--     symbol in CHRONOLOGICAL order (oldest→newest, ASCENDING by funding_time).
--
--   exec_backfill_forward_returns(horizon_days int DEFAULT 7)
--       → TABLE(filled_id bigint)
--     Fills trade_results.realized_return_<horizon_days> from ohlcv_daily_canonical.
--     SECURITY DEFINER + service_role role check (writer, NOT for anon).
--     SQL was already applied "via MCP" on 2026-08-23 per
--     scripts/supabase_forward_return_backfill.sql header, but the live probe
--     shows it missing — re-applying here brings .sql AND database into
--     agreement (S-203 / S-340 lesson: applied-without-recorded deepens drift).
--
-- WHY ALL THREE GO IN ONE MIGRATION. They were missing together; the live
-- probe flagged them together; applying them together closes the whole
-- "panel RPCs missing in Postgres" gate that the online schema-drift check
-- was returning red on.
--
-- SECURITY MODEL
--   panel_closes, panel_funding → SECURITY DEFINER (read paths through a
--     function that bypasses table-level RLS, since both ohlcv_daily and
--     funding_history have anon-revoke policies). GRANT EXECUTE to anon,
--     authenticated, service_role — callers use the publishable key.
--     `REVOKE ... FROM PUBLIC` is load-bearing: CREATE FUNCTION grants
--     EXECUTE to PUBLIC and anon only INHERITS it (see supabase_funding_history.sql
--     line 96 comment); revoke-from-anon-alone succeeds and changes nothing.
--   exec_backfill_forward_returns → SECURITY DEFINER + auth.role() check
--     INSIDE the function body. service_role only. Same pattern as
--     backfill_binance_funding (supabase_funding_history.sql:48-92) and as
--     exec_backfill_forward_returns itself.
--
-- Idempotent. CREATE OR REPLACE FUNCTION. Safe to re-run.
-- ============================================================================


-- ── 1. panel_closes — daily closes for the universe, one source per symbol ──
-- Replaces 8 paper books' per-symbol fapi.binance.com fan-out with one
-- RPC (S-323u, paid_close_loader.py:99-138).
--
-- One source per symbol — S-106 discipline: bar convention is a property of
-- the SOURCE, so splicing two sources into one close series makes the seam
-- look like a move. The tie-breaker is "most rows in window, then
-- alphabetical source" — deterministic, gives the longest series (best
-- coverage), and the alphabetical tiebreak makes the choice reproducible.
--
-- Caller (paid_close_loader.py:114-123) takes ONE row per symbol; if we
-- ever changed to multiple rows per symbol the caller would silently
-- overwrite, so the row_number=1 filter is the contract.
--
-- ⚠️  DROP-then-CREATE, NOT CREATE OR REPLACE. panel_closes / panel_funding
-- were previously applied via MCP with DIFFERENT OUT parameter signatures
-- (the MCP stub returned one shape; we need a different shape for the
-- paid_close_loader / pod_aggregator callers). Postgres cannot change an
-- existing function's return type via CREATE OR REPLACE — it errors
-- 42P13 "Row type defined by OUT parameters is different". DROP FUNCTION
-- first is the only safe path.
DROP FUNCTION IF EXISTS public.panel_closes(text[], int);
CREATE OR REPLACE FUNCTION public.panel_closes(
    p_symbols text[],
    p_days    int
)
RETURNS TABLE(symbol text, closes numeric[], source text)
LANGUAGE sql
SECURITY DEFINER
SET search_path = public
AS $$
    WITH ranked AS (
        SELECT
            symbol,
            source,
            array_agg(close ORDER BY trade_date ASC) AS closes,
            count(*)                                AS n_rows,
            row_number() OVER (
                PARTITION BY symbol
                ORDER BY count(*) DESC, source ASC
            )                                       AS rn
        FROM public.ohlcv_daily
        WHERE symbol    = ANY(p_symbols)
          AND source    IN ('eodhd', 'coingecko_pro_ohlc')  -- PAID_SOURCES, mirrored in paid_close_loader.py:54
          AND close     IS NOT NULL
          AND trade_date >= (CURRENT_DATE - GREATEST(p_days, 1))::date
        GROUP BY symbol, source
    )
    SELECT symbol, closes, source
    FROM ranked
    WHERE rn = 1
    ORDER BY symbol;
$$;

REVOKE ALL ON FUNCTION public.panel_closes(text[], int) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.panel_closes(text[], int) TO anon, authenticated, service_role;

COMMENT ON FUNCTION public.panel_closes(text[], int) IS
    'Daily closes for the panel universe (S-323u). One source per symbol '
    '(PAID_SOURCES ∈ {eodhd, coingecko_pro_ohlc}); tie-break is most-rows-in-'
    'window then alphabetical. Caller receives chronological close series '
    'plus the source that priced it. SECURITY DEFINER to bypass ohlcv_daily '
    'RLS for anon/authenticated callers; GRANT EXECUTE to those roles is '
    'load-bearing because the underlying table is anon-revoked.';


-- ── 2. panel_funding — funding carry, most-recent p_points per symbol ──────
-- Reads funding_history (the S-107 anchor series), returns rates in
-- CHRONOLOGICAL order (oldest→newest). Caller
-- (pod_aggregator_paper.py:124-132) iterates rates as-is; downstream can
-- compute `rates[-1] - rates[0]` for chronological change without
-- reversing.
--
-- Window is "most-recent p_points" — same shape the loader already uses
-- (60 points default for 60 days of 1/day funding, but funding_history
-- has 3x/day on binance_perp so 60 points = ~20 days at the actual venue
-- cadence; the caller picks p_points to match its horizon).
--
-- SECURITY DEFINER for the same reason as panel_closes: funding_history
-- has anon-revoked RLS (supabase_funding_history.sql:46). Function runs
-- as owner (postgres in Supabase) and reads the table; anon calls the
-- RPC and gets the result.
--
-- Same DROP-first note as panel_closes above (Postgres can't change OUT
-- parameters via CREATE OR REPLACE).
DROP FUNCTION IF EXISTS public.panel_funding(text[], int);
CREATE OR REPLACE FUNCTION public.panel_funding(
    p_symbols text[],
    p_points  int
)
RETURNS TABLE(symbol text, rates double precision[])
LANGUAGE sql
SECURITY DEFINER
SET search_path = public
AS $$
    WITH numbered AS (
        SELECT
            symbol,
            funding_rate,
            funding_time,
            row_number() OVER (
                PARTITION BY symbol
                ORDER BY funding_time DESC   -- rn=1 is NEWEST
            ) AS rn
        FROM public.funding_history
        WHERE symbol = ANY(p_symbols)
    ),
    recent AS (
        SELECT symbol, funding_rate, funding_time
        FROM numbered
        WHERE rn <= GREATEST(p_points, 1)
    )
    SELECT
        symbol,
        array_agg(funding_rate ORDER BY funding_time ASC) AS rates
    FROM recent
    GROUP BY symbol
    ORDER BY symbol;
$$;

REVOKE ALL ON FUNCTION public.panel_funding(text[], int) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.panel_funding(text[], int) TO anon, authenticated, service_role;

COMMENT ON FUNCTION public.panel_funding(text[], int) IS
    'Funding carry series for the universe (S-323v). Most-recent p_points '
    'per symbol, returned in chronological order (oldest→newest) so '
    'downstream `rates[-1] - rates[0]` reads as time-correct change. '
    'SECURITY DEFINER to bypass funding_history RLS; anon/authenticated '
    'get the result via GRANT EXECUTE.';


-- ── 3. exec_backfill_forward_returns — fill trade_results forward returns ──
-- From scripts/supabase_forward_return_backfill.sql. Re-applying here
-- because the live probe shows the function missing even though the
-- header says "Applied 2026-08-23 via MCP" — the apply-vs-record drift
-- this header is meant to prevent is exactly what happened, so re-recording
-- closes the loop.
--
-- SECURITY DEFINER + auth.role() check INSIDE the function body — the
-- 2026-07-30 anonymous-writable SECURITY INVOKER hole is the reason this
-- pattern exists at all (see supabase_forward_return_backfill.sql header).
--
-- DROP-first: same Postgres "cannot change OUT parameter type" rule
-- applies if an older signature exists in pg_proc from a prior MCP apply.
DROP FUNCTION IF EXISTS public.exec_backfill_forward_returns(INT);
CREATE OR REPLACE FUNCTION public.exec_backfill_forward_returns(
    horizon_days INT DEFAULT 7
)
RETURNS TABLE(filled_id BIGINT)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    IF auth.role() IS DISTINCT FROM 'service_role' THEN
        RAISE EXCEPTION 'exec_backfill_forward_returns requires service_role (got %)',
              coalesce(auth.role(), 'null');
    END IF;

    RETURN QUERY
    WITH px AS (
        SELECT symbol, trade_date, close, source
        FROM ohlcv_daily_canonical
        WHERE source IN ('binance_hist', 'hyperliquid', 'eodhd')
    ),
    calc AS (
        SELECT tr.id, (p7.close / p0.close - 1.0) AS ret
        FROM trade_results tr
        JOIN px p0 ON p0.symbol = tr.symbol
                  AND p0.trade_date = tr.entry_time::date
        JOIN px p7 ON p7.symbol = tr.symbol
                  AND p7.trade_date = tr.entry_time::date + horizon_days
        WHERE tr.realized_return_7d IS NULL
          AND tr.entry_time IS NOT NULL
          AND p0.source = p7.source              -- S-106: bar-convention seam reads as a move
          AND p0.close > 0
    ),
    upd AS (
        UPDATE trade_results t
        SET realized_return_7d = c.ret
        FROM calc c
        WHERE t.id = c.id
        RETURNING t.id
    )
    SELECT id FROM upd;
END;
$$;

REVOKE ALL ON FUNCTION public.exec_backfill_forward_returns(INT) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.exec_backfill_forward_returns(INT) TO service_role;

COMMENT ON FUNCTION public.exec_backfill_forward_returns(INT) IS
    'Fills trade_results.realized_return_7d from ohlcv_daily_canonical '
    '(S-203). SECURITY DEFINER + service_role gate inside the body. The '
    'p0.source = p7.source filter rejects cross-source splices (S-106); '
    'unfillable rows stay NULL rather than fabricated.';


-- ============================================================================
-- Verification
-- ============================================================================
SELECT
    'panel_closes'                       AS function_name,
    pg_get_function_identity_arguments(
        'public.panel_closes(text[],int)'::regprocedure
    )                                     AS args,
    r.routine_schema IS NOT NULL          AS present
FROM information_schema.routines r
WHERE r.routine_schema = 'public'
  AND r.routine_name   = 'panel_closes'
UNION ALL
SELECT
    'panel_funding',
    pg_get_function_identity_arguments(
        'public.panel_funding(text[],int)'::regprocedure
    ),
    r.routine_schema IS NOT NULL
FROM information_schema.routines r
WHERE r.routine_schema = 'public'
  AND r.routine_name   = 'panel_funding'
UNION ALL
SELECT
    'exec_backfill_forward_returns',
    pg_get_function_identity_arguments(
        'public.exec_backfill_forward_returns(int)'::regprocedure
    ),
    r.routine_schema IS NOT NULL
FROM information_schema.routines r
WHERE r.routine_schema = 'public'
  AND r.routine_name   = 'exec_backfill_forward_returns';
