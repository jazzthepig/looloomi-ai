-- 2026-11-06 · feature_matrix_daily: every daily state dimension we have, one row per day, in one place
-- (Jazz 11-06 "features and factors are not put together"). A view, not a writer: each source keeps its own
-- writer and liveness check; this only joins. Point-in-time as far as each source is (state_daily / cycle are
-- computed as of d; macro_daily d is the availability date; DVOL percentile uses only the 365 days up to d).
-- Missing = absent key, never 0. Forward-only sources (options surface, prediction markets) appear from 2026-11-06.
create or replace view public.feature_matrix_daily with (security_invoker = true) as
with st as (
  select d, jsonb_object_agg(feature, value) f from public.state_daily where entity = 'panel' and value is not null group by d
), mc as (
  select d, jsonb_object_agg('macro:' || series, value) f from public.macro_daily where value is not null group by d
), cy as (
  select d, jsonb_strip_nulls(jsonb_build_object('cycle:deterioration', deterioration, 'cycle:shift_pct', shift_pct,
         'cycle:turning', case when phase = 'turning' then 1 when phase = 'normal' then 0 end)) f
  from public.cycle_vector_daily
), dvp as (
  select a.d, jsonb_strip_nulls(jsonb_build_object('dvol:btc', a.dvol_close,
         'dvol:btc_pct_1y', (select avg(case when b.dvol_close <= a.dvol_close then 1.0 else 0.0 end)
                              from public.deriv_vol_daily b where b.currency = 'BTC' and b.d between a.d - 365 and a.d))) f
  from public.deriv_vol_daily a where a.currency = 'BTC'
), op as (
  select d, jsonb_strip_nulls(jsonb_build_object('opt:atm_iv_30d', atm_iv_30d, 'opt:term_slope', term_slope, 'opt:skew_30d', skew_30d,
         'opt:pc_oi', pc_oi_ratio, 'opt:pc_vol', pc_vol_ratio, 'opt:put90_30d_cost_pct', put90_30d_cost_pct,
         'opt:put_spread_90_80_cost_pct', put_spread_90_80_30d_cost_pct, 'opt:gex_net_usd_1pct', gex_net_usd_1pct,
         'opt:gamma_pin_dist', case when spot > 0 and gamma_pin_strike is not null then gamma_pin_strike / spot - 1 end)) f
  from public.options_surface_daily where currency = 'BTC'
), sc as (
  select a.d, jsonb_object_agg('stable:' || a.coin || '_30d', a.circulating_usd / b.circulating_usd - 1) f
  from public.stablecoin_issuer_daily a
  join public.stablecoin_issuer_daily b on b.coin = a.coin and b.d = a.d - 30
  where b.circulating_usd > 0
  group by a.d
), cx as (
  select d, jsonb_strip_nulls(jsonb_build_object(
           'cex:inflow_1w_pct', sum(inflow_1w_usd) / nullif(sum(clean_assets_usd), 0),
           'cex:inflow_1m_pct', sum(inflow_1m_usd) / nullif(sum(clean_assets_usd), 0),
           'cex:leverage', sum(oi_usd) / nullif(sum(clean_assets_usd), 0))) f
  from public.cex_reserves_daily group by d
), dm as (
  select x.d, jsonb_strip_nulls(jsonb_build_object(
           'deriv:oi_to_mcap', sum(x.oi_usd) / nullif(max(m.value), 0),
           'deriv:alt_oi_share', 1 - sum(x.oi_usd) filter (where x.symbol in ('BTC', 'ETH')) / nullif(sum(x.oi_usd), 0),
           'deriv:btc_basis_pct', max(x.basis_oiw_pct) filter (where x.symbol = 'BTC'))) f
  from public.derivatives_market_daily x
  left join public.macro_daily m on m.series = 'total_mcap' and m.d = x.d
  group by x.d
), pol as (
  select d, jsonb_object_agg('pol:' || topic, value) f from public.political_intensity_daily group by d
), px as (
  -- 跨资产相关(T-258 前三之二):BTC 与纳指(QQQ)/ 美元(UUP)日对数收益的 60 个共同交易日滚动相关;UUP 取 eodhd,缺的日子用 yfinance
  select q.trade_date d, q.close qc, b.close bc, u.close uc
  from public.ohlcv_daily q
  join public.ohlcv_daily b on b.trade_date = q.trade_date and b.symbol = 'BTC' and b.source = 'binance_hist'
  join (select distinct on (trade_date) trade_date, close from public.ohlcv_daily
        where symbol = 'UUP' and source in ('eodhd', 'yfinance') order by trade_date, (source = 'eodhd') desc) u on u.trade_date = q.trade_date
  where q.symbol = 'QQQ' and q.source = 'eodhd' and q.close > 0 and b.close > 0 and u.close > 0
), rx as (
  select d, ln(qc / lag(qc) over w) rq, ln(bc / lag(bc) over w) rb, ln(uc / lag(uc) over w) ru from px window w as (order by d)
), xc as (
  select d, jsonb_strip_nulls(jsonb_build_object(
           'xasset:btc_qqq_corr60', case when n >= 60 then cq end, 'xasset:btc_uup_corr60', case when n >= 60 then cu end)) f
  from (select d, corr(rb, rq) over w cq, corr(rb, ru) over w cu, count(rb) over w n from rx
        window w as (order by d rows between 59 preceding and current row)) z
), xf as (
  -- 周末 / 假日沿用最近交易日(gaps-and-islands,不逐行回查)
  select s.d, x.f, count(x.f) over (order by s.d) grp from (select distinct d from public.state_daily where entity = 'panel') s
  left join xc x on x.d = s.d
), xff as (
  select d, first_value(f) over (partition by grp order by d) f from xf
)
select st.d,
       st.f || coalesce(mc.f, '{}'::jsonb) || coalesce(cy.f, '{}'::jsonb) || coalesce(dvp.f, '{}'::jsonb) || coalesce(op.f, '{}'::jsonb) || coalesce(sc.f, '{}'::jsonb) || coalesce(xc.f, '{}'::jsonb) || coalesce(cx.f, '{}'::jsonb) || coalesce(pol.f, '{}'::jsonb) || coalesce(dm.f, '{}'::jsonb) f,
       jsonb_build_object('state', st.f is not null, 'macro', mc.f is not null, 'cycle', cy.f is not null,
                          'dvol', dvp.f is not null, 'options', op.f is not null, 'stable_issuers', sc.f is not null, 'xasset', xc.f is not null, 'cex', cx.f is not null, 'political', pol.f is not null, 'derivatives', dm.f is not null) has
from st
left join mc on mc.d = st.d
left join cy on cy.d = st.d
left join dvp on dvp.d = st.d
left join op on op.d = st.d
left join sc on sc.d = st.d
left join xff xc on xc.d = st.d
left join cx on cx.d = st.d
left join pol on pol.d = st.d
left join dm on dm.d = st.d;
grant select on public.feature_matrix_daily to anon;
