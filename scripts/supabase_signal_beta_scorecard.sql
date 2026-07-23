-- ============================================================================
-- Beta-adjusted signal metric — backfill + canonical scorecard view
-- Seth, 2026-07-22. Build-order #1 (docs/VECTOR_SCHEMA_SPEC.md §4, historical half).
--
-- Applied live to Supabase (project soupjamxlfsmgmmtoeok) via MCP on 2026-07-22.
-- This file is the repo-visible provenance of that DB change — re-runnable & idempotent.
--
-- WHY: for a year the live metric was alpha = a_ret - b_ret, which is only alpha when
-- beta to the benchmark is 1.0. Our universe beta is ~1.49 avg (2.4 for STRONG OUTPERFORM),
-- so the published number was LEVERAGED BETA, inverting the sign of a working signal in a
-- bear window (R61 -> R62 overturns R61). Faithful in-SQL reproduction of
-- src/data/market/beta_adjust.py: PIT expanding-window OLS on strictly-prior same-symbol
-- rows, >=20 priors, non-degenerate benchmark variance. NEVER full-sample, NEVER default
-- beta=1.0 (insufficient history -> NULL).
--
-- The live signal_outcomes WRITER remains Minimax's (Mac-side); this covers history only.
-- Investor track-record RPC beta-wiring is spec'd separately (MINIMAX_SYNC §BETA-METRIC-AGG).
-- ============================================================================

-- ---------------------------------------------------------------------------
-- 1. BACKFILL: populate beta_pit / alpha_beta_adj / edge_beta_adj on signal_outcomes
--    (columns already existed; added by Seth 2026-07-21 per §BETA-METRIC).
--    Result 2026-07-22: 7044/7743 rows beta-filled (699 = PIT warmup, correct); avg beta 1.49.
-- ---------------------------------------------------------------------------
with base as (
  select id, symbol, signal, d, a_ret::double precision a, b_ret::double precision b
  from signal_outcomes
),
sums as (  -- expanding window over STRICTLY prior rows per symbol
  select id, symbol, signal, a, b,
    count(*) over w as n_prior, sum(a) over w sa, sum(b) over w sb,
    sum(a*b) over w sab, sum(b*b) over w sbb
  from base
  window w as (partition by symbol order by d, id rows between unbounded preceding and 1 preceding)
),
calc as (
  select id, signal, a, b,
    case when n_prior >= 20 and abs(sbb - sb*sb/n_prior) > 1e-12
         then (sab - sa*sb/n_prior) / (sbb - sb*sb/n_prior) end as beta_pit
  from sums
),
final as (
  select id, signal, beta_pit,
    case when beta_pit is not null then (a - beta_pit*b) end as alpha_adj
  from calc
)
update signal_outcomes s
set beta_pit       = round(f.beta_pit::numeric, 4),
    alpha_beta_adj = round(f.alpha_adj::numeric, 6),
    edge_beta_adj  = case when f.alpha_adj is null then null
                          when f.signal in ('STRONG OUTPERFORM','OUTPERFORM') then round(f.alpha_adj::numeric,6)
                          when f.signal in ('UNDERPERFORM','UNDERWEIGHT')     then round((-f.alpha_adj)::numeric,6)
                          else null end
from final f
where s.id = f.id;

-- ---------------------------------------------------------------------------
-- 2. VIEW: canonical beta-adjusted per-signal scorecard. Forward-safe (auto-updates as
--    fresh rows land). Excludes symbol=bench (an asset has no alpha vs itself). Publishes
--    raw AND beta-adj side by side — beta-adj is the HEDGED excess (requires shorting the
--    bench); an unhedged holder experiences the raw number. Investor surfaces publish BOTH.
--    Verified 2026-07-22 (reproduces R62):
--      STRONG OUTPERFORM +8.12 (t+5.41) | OUTPERFORM +2.53 (t+4.57) |
--      UNDERPERFORM +1.25 (t+5.65)      | UNDERWEIGHT -3.69 (t-3.56)  <- the one real defect
-- ---------------------------------------------------------------------------
create or replace view signal_beta_scorecard as
select
  signal,
  count(edge_beta_adj)                                                                  as n_beta_adj,
  round(avg(beta_pit)::numeric, 3)                                                      as avg_beta_pit,
  round(avg(edge_beta_adj)::numeric, 4)                                                 as avg_edge_beta_adj_pct,
  round((avg(edge_beta_adj) / nullif(stddev_samp(edge_beta_adj), 0)
         * sqrt(count(edge_beta_adj)))::numeric, 2)                                     as edge_beta_adj_t,
  round(avg(alpha)::numeric, 4)                                                         as avg_raw_alpha_pct,
  min(d)                                                                                as first_d,
  max(d)                                                                                as last_d
from signal_outcomes
where edge_beta_adj is not null and symbol <> bench
group by signal
order by edge_beta_adj_t desc nulls last;

comment on view signal_beta_scorecard is
  'Canonical beta-adjusted per-signal edge (PIT, ex-self) over signal_outcomes. Build-order #1, 2026-07-22. '
  'edge_beta_adj_t is a one-sample t of the directional beta-adjusted edge vs 0. UNDERWEIGHT is the one real defect (t<0). '
  'Raw alpha shown beside it (what an UNHEDGED holder experiences); beta-adj requires shorting the benchmark. '
  'Investor surfaces must publish BOTH, labelled. NOTE: underlying signal_outcomes is Mac-side-fed and may be stale — check max(last_d).';


-- ---------------------------------------------------------------------------
-- 3. VIEW: per-asset RISK MOMENTS of the beta-adjusted edge (build-order #4, I5, 2026-07-22).
--    Feeds asset embedder v2 dims [25..26] (edge_vol, edge_p10). I5: a mean-only schema is blind
--    to where money is lost — R63 showed high sentiment leaves the mean flat while widening vol
--    (15.89->17.17) and deepening the p10 tail (-13.93->-18.33). n>=20 for a stable std/percentile;
--    the embedder treats a missing symbol / low-n as NaN (I1), never 0. Verified 2026-07-22:
--    25 symbols, mean edge_vol 17.06, mean edge_p10 -20.54 (squarely in R63's range).
-- ---------------------------------------------------------------------------
create or replace view asset_edge_moments as
select
  symbol,
  count(edge_beta_adj)                                                                as n,
  round(avg(edge_beta_adj)::numeric, 4)                                               as edge_mean,
  round(stddev_samp(edge_beta_adj)::numeric, 4)                                       as edge_vol,
  round((percentile_cont(0.10) within group (order by edge_beta_adj))::numeric, 4)    as edge_p10,
  max(d)                                                                              as last_d
from signal_outcomes
where edge_beta_adj is not null and symbol <> bench
group by symbol
having count(edge_beta_adj) >= 20;

comment on view asset_edge_moments is
  'Per-asset risk moments of the beta-adjusted directional edge (build-order #4, 2026-07-22). '
  'edge_vol = stddev, edge_p10 = 10th-percentile left tail. I5: a mean-only schema is blind to where '
  'money is lost. Feeds the asset embedder v2 risk-moment dims [25..26]. n>=20; missing symbol => NaN, not 0. '
  'NOTE: signal_outcomes is Mac-side-fed and may be stale — check max(last_d).';
