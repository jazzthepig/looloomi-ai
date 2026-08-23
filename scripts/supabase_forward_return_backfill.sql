-- exec_backfill_forward_returns — fills trade_results.realized_return_7d (S-203)
-- Seth, 2026-08-23. Applied to production the same day via MCP; written here
-- because applying without recording deepens the .sql-vs-database drift measured
-- on 08-20 (asset_embeddings.superseded_reason and beta_core_nav.exposure_cap
-- exist live and in no CREATE TABLE, which made a schema guard emit three false
-- positives and zero true ones).
--
-- WHY IT EXISTS. 234 of 234 rows had this column NULL, and that one gap disabled
-- the whole IC-weighting mechanism: compute_fitness returned [], cis_regime_fitness
-- stayed at 0 rows, the IC multiplier could not load, and CIS scored every asset
-- on NEUTRAL weights for four months while the daily log read `ok=True rows=0`.
--
-- SECURITY DEFINER + an explicit role check INSIDE the function. The 2026-07-30
-- hole was an anonymous-writable SECURITY INVOKER RPC; the answer is not INVOKER
-- but DEFINER with the authorisation stated in one readable place rather than
-- inherited from whoever called.
--
-- p0.source = p7.source IS THE POINT. It rejects the 20 candidate rows spanning
-- binance_hist -> coingecko: a return computed across two bar conventions reads
-- the splice as a move (S-106). Unfillable rows stay NULL — this column feeds a
-- weighting decision, and a fabricated return is indistinguishable downstream
-- from a measured one.

CREATE OR REPLACE FUNCTION exec_backfill_forward_returns(horizon_days INT DEFAULT 7)
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
          AND p0.source = p7.source
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

REVOKE ALL ON FUNCTION exec_backfill_forward_returns(INT) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION exec_backfill_forward_returns(INT) TO service_role;
