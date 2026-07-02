-- CometCloud signal track record — computed ENTIRELY from our own DB (no external fetch,
-- no "wait 30 days"). Joins cis_scores (historical signals) × ohlcv_daily (prices we kept)
-- to measure the 30-day BENCHMARK-RELATIVE outcome (alpha vs BTC for crypto / SPY for TradFi)
-- of every matured OUTPERFORM/STRONG-OUTPERFORM call.
--
-- Key finding (2026-07-01, ~100-day sample, 1,609 resolved):
--   plain OUTPERFORM (B/B+)      → negative alpha (~-0.2 to -0.6%), ~38% win  → NOT an edge
--   STRONG OUTPERFORM (A / A+)   → +3.3% / +3.7% alpha, ~49% / 67% win        → the real edge
-- Implication: the tradeable signal is the narrow top-conviction slice, not the broad tier.
--
-- Usage: run against Supabase (psql or MCP). Change the GROUP BY / filters to slice by
-- regime, asset_class, or time window. The `<= current_date - 30` gate = matured only.

with sig as (            -- one signal per (symbol, day): dedup the 30-min pushes
  select distinct on (symbol, recorded_at::date)
    symbol, asset_class, recorded_at::date as d, grade, signal, macro_regime
  from cis_scores
  where signal ilike '%OUTPERFORM%' and recorded_at::date <= current_date - 30
  order by symbol, recorded_at::date, recorded_at
),
priced as (              -- asset entry (≈signal day) + exit (≈ +30d) from our OHLCV
  select s.*,
    case when s.asset_class in ('US Equity','US Bond','Commodity','TradFi','EM Equity','DM Equity')
         then 'SPY' else 'BTC' end as bench,
    (select close from ohlcv_daily o where o.symbol=s.symbol and o.trade_date between s.d-2 and s.d+2
       order by abs(o.trade_date-s.d) limit 1) a_entry,
    (select close from ohlcv_daily o where o.symbol=s.symbol and o.trade_date between s.d+28 and s.d+34
       order by abs(o.trade_date-(s.d+30)) limit 1) a_exit
  from sig s
),
benched as (             -- benchmark entry/exit over the same window
  select p.*,
    (select close from ohlcv_daily o where o.symbol=p.bench and o.trade_date between p.d-2 and p.d+2
       order by abs(o.trade_date-p.d) limit 1) b_entry,
    (select close from ohlcv_daily o where o.symbol=p.bench and o.trade_date between p.d+28 and p.d+34
       order by abs(o.trade_date-(p.d+30)) limit 1) b_exit
  from priced p
  where p.a_entry>0 and p.a_exit>0
)
select signal, grade, count(*) n,
  round(avg(((a_exit/a_entry-1)-(b_exit/b_entry-1))*100)::numeric,2)                     avg_alpha_pct,
  round(100.0*count(*) filter (where (a_exit/a_entry) > (b_exit/b_entry))/count(*),1)    alpha_win_pct,
  round(avg((a_exit/a_entry-1)*100)::numeric,2)                                          avg_abs_return_pct
from benched
where b_entry>0 and b_exit>0
group by signal, grade
order by signal, grade;
