-- ============================================================================
-- refresh_signal_track_record() v2 — β-adjusted investor track record
-- Seth, 2026-07-26. MINIMAX_SYNC §BETA-METRIC-AGG (spec 2026-07-22).
--
-- WHY: the live investor surface (/api/v1/signals/track-record) was publishing
-- `alpha = a_ret − b_ret` — only alpha when β=1. Ours is 1.4–2.4. R62 overturned
-- R61 (the misleading "broad OUTPERFORM tier did not deliver" finding) but the
-- INV published story was NOT updated. This RPC rebuilds daily and emits BOTH
-- raw (what an UNHEDGED holder experiences) and β-ADJ (HEDGED excess, requires
-- shorting the bench) per spec.
--
-- WHAT THIS DOES (in one DB-side transaction, idempotent, re-runnable):
--   1. Deletes today's snapshot of signal_track_record (keeps history).
--   2. For every (signal, grade) bucket over signal_outcomes:
--        - Filters: symbol <> bench, alpha-priors sufficient (≥20 priors in window).
--        - Raw columns:  n, avg_alpha_pct, alpha_win_pct, avg_abs_return_pct.
--        - β columns:    avg_edge_beta_adj_pct, edge_beta_adj_t,
--                        avg_beta_pit, n_beta_adj.
--   3. Extends the scan beyond OUTPERFORM (the original spec-ilike filter
--      excluded UNDERPERFORM/UNDERWEIGHT; the v2 includes every directional
--      signal so the UNDERWEIGHT defect (t = -3.79 in R62) becomes visible to
--      the investor surface, not just our internal scorecard).
--
-- SEMANTIC INVARIANTS (mirroring src/data/market/beta_adjust.py EXACTLY):
--   - PIT expanding-window OLS over strictly-prior (symbol, d, id) order
--   - min 20 priors
--   - non-degenerate bench variance (var > 1e-12)
--   - NEVER default β to 1.0 (insufficient history → NULL — the row is
--     honestly excluded from n_beta_adj, not silently substituted)
--   - NEUTRAL makes no directional claim → its columns are NULL
--
-- SHIP GATE: this RPC runs unconditionally in the daily Railway loop
-- (src/api/main.py::_track_record_loop). The PUBLISH gate lives in
-- src/api/store.py::supabase_get_latest_track_record AND in
-- src/api/routers/signals.py::get_signal_track_record — both check
-- ohlcv_daily.last_trade_date and suppress the β-ADJ headline when
-- the price feed is stale. If we publish on stale data, we'd be
-- publishing β-correct-but-stale numbers, which is worse than the
-- current pre-R62 surface.
-- ============================================================================

create or replace function refresh_signal_track_record()
returns int
language plpgsql
security definer
as $$
declare
  n_rows    int;
  bench_str text := case
    when current_setting('app.bench_default', true) is not null
      and current_setting('app.bench_default', true) <> ''
    then current_setting('app.bench_default', true)
    else 'BTC'
  end;
begin
  -- 1. Drop today's snapshot (preserve history for time-series audit).
  delete from signal_track_record
   where computed_at::date = current_date;

  -- 2. Aggregate per (signal, grade), computing both RAW and β-ADJ columns
  --    in one pass via a CTE. Same row-set feeds both.
  with base as (
    select
      o.signal,
      o.grade,
      o.symbol,
      o.d,
      o.bench,         -- column on signal_outcomes; mirrors the original
                       -- track_record.sql CASE (SPY for TradFi, BTC else).
                       -- §BETA-METRIC-BACKFILL notes 259 self-rows exist
                       -- (BTC with bench=BTC, SPY with bench=SPY).
      o.a_ret,
      o.b_ret
    from signal_outcomes o
    where o.signal <> 'NEUTRAL'
  ),
  -- Drop symbol = bench rows. An asset has no alpha vs itself.
  ex_self as (
    select * from base where symbol <> bench
  ),
  -- For each (symbol, d), rank priors. Strictly-prior = ROWS BEFORE current.
  -- rows between unbounded preceding and 1 preceding = window over PRIOR only.
  with_priors as (
    select
      signal, grade, symbol, d, a_ret, b_ret,
      count(*)  over w as n_prior,
      sum(a_ret) over w as sa,
      sum(b_ret) over w as sb,
      sum(a_ret * b_ret) over w as sab,
      sum(b_ret * b_ret) over w as sbb
    from ex_self
    window w as (
      partition by symbol
      order by d, symbol       -- secondary key for deterministic tiebreak
      rows between unbounded preceding and 1 preceding
    )
  ),
  beta_calc as (
    select
      signal, grade, d, a_ret, b_ret,
      case
        when n_prior >= 20
         and abs(sbb - sb * sb / n_prior) > 1e-12
        then (sab - sa * sb / n_prior) / (sbb - sb * sb / n_prior)
      end as beta_pit
    from with_priors
  ),
  -- Direction-aware edge: OUTPERFORM-family wants positive alpha; UNDER*-family
  -- wants negative alpha (i.e. a "correct" call is -alpha > 0). Mirrors
  -- beta_adjust.directional_edge exactly.
  edges as (
    select
      signal, grade, beta_pit, a_ret, b_ret,
      case
        when beta_pit is null then null
        else case
          when signal in ('STRONG OUTPERFORM','OUTPERFORM') then (a_ret - beta_pit * b_ret)
          when signal in ('UNDERPERFORM','UNDERWEIGHT')   then -(a_ret - beta_pit * b_ret)
        end
      end as edge_beta_adj,
      (a_ret - b_ret) as raw_alpha
    from beta_calc
  ),
  agg as (
    select
      signal,
      grade,
      -- RAW columns (always populated when a_ret, b_ret exist):
      count(*)                                                                as n,
      round(avg(raw_alpha)::numeric, 2)                                       as avg_alpha_pct,
      round(100.0 * count(*) filter (where raw_alpha > 0) / count(*), 1)      as alpha_win_pct,
      round(avg(a_ret)::numeric, 2)                                           as avg_abs_return_pct,
      -- β columns (NULL when insufficient priors on this bucket):
      count(edge_beta_adj)                                                    as n_beta_adj,
      round(avg(beta_pit)::numeric, 3)                                        as avg_beta_pit,
      round(avg(edge_beta_adj)::numeric, 4)                                   as avg_edge_beta_adj_pct,
      round(
        (avg(edge_beta_adj) / nullif(stddev_samp(edge_beta_adj), 0)
         * sqrt(count(edge_beta_adj)))::numeric, 2
      )                                                                       as edge_beta_adj_t
    from edges
    group by signal, grade
  )
  insert into signal_track_record (
    signal, grade, n,
    avg_alpha_pct, alpha_win_pct, avg_abs_return_pct,
    avg_edge_beta_adj_pct, edge_beta_adj_t, avg_beta_pit, n_beta_adj,
    computed_at
  )
  select
    signal, grade, n,
    avg_alpha_pct, alpha_win_pct, avg_abs_return_pct,
    avg_edge_beta_adj_pct, edge_beta_adj_t, avg_beta_pit, n_beta_adj,
    now() as computed_at
  from agg;

  get diagnostics n_rows = row_count;
  return n_rows;
end;
$$;

-- The original migrate was `select refresh_signal_track_record();` — both work.
-- Lock down so the publishing app and the migration share one definition.
revoke all on function refresh_signal_track_record() from public;
grant execute on function refresh_signal_track_record() to service_role;

comment on function refresh_signal_track_record() is
  'v2 (2026-07-26): emits both RAW (avg_alpha_pct) and β-ADJ '
  '(avg_edge_beta_adj_pct, edge_beta_adj_t, avg_beta_pit, n_beta_adj) columns. '
  'PIT expanding-window OLS mirroring src/data/market/beta_adjust.py: ≥20 priors '
  'required, NEVER default β=1.0 (insufficient → NULL → excluded from n_beta_adj), '
  'symbol=bench filtered out. Scan extends beyond OUTPERFORM so the UNDERWEIGHT '
  'defect (t < 0 in R62) is visible on the investor surface, not just internal. '
  'The daily Railway loop (src/api/main.py::_track_record_loop) calls this '
  'unconditionally; the SUPPRESS gate lives in the endpoint layer when '
  'ohlcv_daily.last_trade_date > 1 day stale.';
