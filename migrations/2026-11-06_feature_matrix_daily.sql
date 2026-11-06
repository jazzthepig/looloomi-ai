-- 2026-11-06 · feature_matrix_daily: every daily state dimension we have, one row per day, in one place
-- (Jazz 11-06 "features and factors are not put together"). A view, not a writer: each source keeps its own
-- writer and liveness check; this only joins. Point-in-time as far as each source is (state_daily / cycle are
-- computed as of d; macro_daily d is the availability date; DVOL percentile uses only the 365 days up to d).
-- Missing = absent key, never 0. Forward-only sources (options surface, prediction markets) appear from 2026-11-06.
create or replace view public.feature_matrix_daily_live with (security_invoker = true) as
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
), sl as (
  select a.d, a.style, a.weighting, ln(a.level / b.level) r30
  from public.style_index_pit_daily a
  join public.style_index_pit_daily b on b.style = a.style and b.weighting = a.weighting and b.dimension = a.dimension and b.d = a.d - 30
  where a.level > 0 and b.level > 0
), sty as (
  select a.d, jsonb_strip_nulls(coalesce(jsonb_object_agg('style:' || a.style || '_rel30', a.r30 - m.r30) filter (where a.weighting = 'cap' and a.style <> 'majors'), '{}'::jsonb)
         || jsonb_build_object('style:app_eq_minus_cap_30', max(a.r30) filter (where a.style = 'app' and a.weighting = 'equal')
                                                          - max(a.r30) filter (where a.style = 'app' and a.weighting = 'cap'))) f
  from sl a join sl m on m.d = a.d and m.style = 'majors' and m.weighting = 'cap'
  group by a.d
), ca as (
  select chain, d, sum(fees_usd) over w fee30, sum(dex_volume_usd) over w dex30, count(fees_usd) over w nf, count(dex_volume_usd) over w nd, tvl_usd
  from public.chain_activity_daily window w as (partition by chain order by d rows between 29 preceding and current row)
), cb as (
  select a.d, sum(a.fee30) filter (where a.nf = 30 and b.nf = 30) f1, sum(b.fee30) filter (where a.nf = 30 and b.nf = 30) f0,
         sum(a.dex30) filter (where a.nd = 30 and b.nd = 30) x1, sum(b.dex30) filter (where a.nd = 30 and b.nd = 30) x0,
         sum(a.tvl_usd) filter (where a.tvl_usd > 0 and b.tvl_usd > 0) t1, sum(b.tvl_usd) filter (where a.tvl_usd > 0 and b.tvl_usd > 0) t0,
         sum(a.dex30) filter (where a.nd = 30) / 30.0 dex_day
  from ca a join ca b on b.chain = a.chain and b.d = a.d - 30
  group by a.d
), chn as (
  select cb.d, jsonb_strip_nulls(jsonb_build_object('chain:fees_30v30', ln(f1 / nullif(f0, 0)), 'chain:dex_30v30', ln(x1 / nullif(x0, 0)),
         'chain:tvl_30d', ln(t1 / nullif(t0, 0)), 'chain:dex_to_total_vol', dex_day / nullif(m.value, 0))) f
  from cb left join public.macro_daily m on m.series = 'total_volume' and m.d = cb.d
  where f0 > 0 or x0 > 0 or t0 > 0
), pos as (
  select d, jsonb_strip_nulls(jsonb_build_object(
           'pos:btc_top_pos_ln', ln(max(top_pos_ratio_close) filter (where symbol = 'BTC' and top_pos_ratio_close > 0)),
           'pos:btc_crowd_ln', ln(max(global_acct_ratio_close) filter (where symbol = 'BTC' and global_acct_ratio_close > 0)),
           'pos:btc_smart_minus_crowd', ln(max(top_pos_ratio_close) filter (where symbol = 'BTC' and top_pos_ratio_close > 0))
                                      - ln(max(global_acct_ratio_close) filter (where symbol = 'BTC' and global_acct_ratio_close > 0)),
           'pos:alt_crowd_median_ln', percentile_cont(0.5) within group (order by ln(global_acct_ratio_close))
                                      filter (where symbol not in ('BTC', 'ETH') and global_acct_ratio_close > 0),
           'pos:alt_smart_minus_crowd_median', percentile_cont(0.5) within group (order by ln(top_pos_ratio_close) - ln(global_acct_ratio_close))
                                      filter (where symbol not in ('BTC', 'ETH') and global_acct_ratio_close > 0 and top_pos_ratio_close > 0),
           'pos:alt_taker_median_ln', percentile_cont(0.5) within group (order by ln(taker_ratio_mean))
                                      filter (where symbol not in ('BTC', 'ETH') and taker_ratio_mean > 0),
           'pos:n_symbols', count(*) filter (where global_acct_ratio_close > 0))) f
  from public.deriv_metrics_daily where source = 'binance_vision_metrics' group by d
), chl as (
  select a.d, jsonb_object_agg('channel:' || a.channel || '_30d', ln(a.mcap / b.mcap)) f
  from public.channel_series_daily a
  join public.channel_series_daily b on b.channel = a.channel and b.category_id = a.category_id and b.d = a.d - 30
  where a.category_id = '*' and a.channel in ('rwa', 'tokenized') and a.mcap > 0 and b.mcap > 0
  group by a.d
), evw as (
  select d, exchange, kind, sum(volume_btc) over w v30, count(*) over w n30
  from public.exchange_volume_daily window w as (partition by exchange order by d rows between 29 preceding and current row)
), ven as (
  select d, jsonb_strip_nulls(jsonb_build_object(
           'venue:coinbase_share_spot30', sum(v30) filter (where exchange = 'gdax') / nullif(sum(v30) filter (where kind = 'spot'), 0),
           'venue:korea_share_spot30', sum(v30) filter (where exchange in ('upbit', 'bithumb')) / nullif(sum(v30) filter (where kind = 'spot'), 0),
           'venue:deriv_to_spot30', sum(v30) filter (where kind = 'deriv') / nullif(sum(v30) filter (where kind = 'spot'), 0),
           'venue:onchain_perp_share30', sum(v30) filter (where exchange in ('hyperliquid', 'aster', 'lighter')) / nullif(sum(v30) filter (where kind = 'deriv'), 0),
           'venue:cme_share_deriv30', sum(v30) filter (where exchange = 'cme_futures') / nullif(sum(v30) filter (where kind = 'deriv'), 0))) f
  from evw where n30 = 30 group by d
), hb as (
  -- 持有人数广度(holders_chart 周一快照,2024-10 起):4 周增长为正的币占比、增长中位数;|ln| > 1 视为数据跳变丢掉;≥ 30 个币才出数
  select a.d, jsonb_build_object(
           'holders:breadth_4w', avg(case when a.holders > b.holders then 1.0 else 0.0 end),
           'holders:median_growth_4w', percentile_cont(0.5) within group (order by ln(a.holders::float / b.holders)),
           'holders:n_coins', count(*)) f
  from public.token_holders_daily a
  join public.token_holders_daily b on b.coin_id = a.coin_id and b.d = a.d - 28
  where extract(isodow from a.d) = 1 and b.holders > 0 and abs(ln(a.holders::float / b.holders)) <= 1
  group by a.d having count(*) >= 30
), hbf as (
  select s.d, h.f, h.d src_d, count(h.f) over (order by s.d) grp from (select distinct d from public.state_daily where entity = 'panel') s
  left join hb h on h.d = s.d
), hbff as (
  -- 周频沿用到下一个周一,最多 10 天(写入端停了就断,不无限延续旧值)
  select d, case when d - first_value(src_d) over w <= 10 then first_value(f) over w end f
  from hbf window w as (partition by grp order by d)
), fwd as (
  -- 11-06 起才有的前向维度(CoinGecko Analyst):锁仓占比中位数、7 天新币数、分类 24h 上涨占比
  select z.d, jsonb_strip_nulls(jsonb_build_object(
           'supply:locked_share_median', (select percentile_cont(0.5) within group (order by non_circulating_supply / total_supply)
                                          from public.coin_supply_daily c where c.d = z.d and c.total_supply > 0 and c.non_circulating_supply is not null),
           'listings:new_coins_7d', (select count(*) from public.cg_new_coins n
                                     where n.activated_at > (z.d - 7)::timestamptz and n.activated_at <= (z.d + 1)::timestamptz),
           'cat:share_up_24h', (select avg(case when mcap_change_24h_pct > 0 then 1.0 else 0.0 end) from public.cg_category_daily g where g.d = z.d))) f
  from (select distinct d from public.coin_supply_daily union select distinct d from public.cg_category_daily) z
), scc as (
  -- 稳定币按链 30 天增长(干火药放在哪:Tron ≈ 亚洲散户 USDT,Ethereum ≈ 机构 / DeFi,Solana / Base / Arbitrum ≈ 链上投机)
  select a.d, jsonb_object_agg('stablechain:' || lower(a.chain) || '_30d', a.circulating_usd / b.circulating_usd - 1) f
  from public.stablecoin_chain_daily a
  join public.stablecoin_chain_daily b on b.chain = a.chain and b.d = a.d - 30
  where b.circulating_usd > 0
  group by a.d
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
       st.f || coalesce(mc.f, '{}'::jsonb) || coalesce(cy.f, '{}'::jsonb) || coalesce(dvp.f, '{}'::jsonb) || coalesce(op.f, '{}'::jsonb) || coalesce(sc.f, '{}'::jsonb) || coalesce(xc.f, '{}'::jsonb) || coalesce(cx.f, '{}'::jsonb) || coalesce(pol.f, '{}'::jsonb) || coalesce(dm.f, '{}'::jsonb)
          || coalesce(sty.f, '{}'::jsonb) || coalesce(chn.f, '{}'::jsonb) || coalesce(pos.f, '{}'::jsonb) || coalesce(chl.f, '{}'::jsonb) || coalesce(ven.f, '{}'::jsonb)
          || coalesce(hbff.f, '{}'::jsonb) || coalesce(fwd.f, '{}'::jsonb) || coalesce(scc.f, '{}'::jsonb) f,
       jsonb_build_object('state', st.f is not null, 'macro', mc.f is not null, 'cycle', cy.f is not null,
                          'dvol', dvp.f is not null, 'options', op.f is not null, 'stable_issuers', sc.f is not null, 'xasset', xc.f is not null, 'cex', cx.f is not null, 'political', pol.f is not null, 'derivatives', dm.f is not null,
                          'style', sty.f is not null, 'chain', chn.f is not null, 'positioning', pos.f is not null, 'channel', chl.f is not null, 'venue', ven.f is not null,
                          'holders', hbff.f is not null, 'cg_forward', fwd.f is not null, 'stable_chains', scc.f is not null) has
from st
left join mc on mc.d = st.d
left join cy on cy.d = st.d
left join dvp on dvp.d = st.d
left join op on op.d = st.d
left join sc on sc.d = st.d
left join xff xc on xc.d = st.d
left join cx on cx.d = st.d
left join pol on pol.d = st.d
left join dm on dm.d = st.d
left join sty on sty.d = st.d
left join chn on chn.d = st.d
left join pos on pos.d = st.d
left join chl on chl.d = st.d
left join ven on ven.d = st.d
left join hbff on hbff.d = st.d
left join fwd on fwd.d = st.d
left join scc on scc.d = st.d;

-- 11-06 (second pass): fuse what we already had but never joined — PIT style indices since 2020
-- (style_index_pit_daily: sector/tier 30d log return minus majors, plus equal-minus-cap breadth),
-- chain activity (69 chains: fees / DEX volume 30d vs prior 30d over chains present in both windows,
-- TVL 30d, DEX ÷ total volume), Binance positioning (top-trader vs all-account long/short ratios, BTC and
-- alt medians, since 2020-09), channel mcaps (RWA / tokenized, current constituents backfilled ⇒
-- survivorship-biased, flagged here). The live view is ~3 s, so readers get a materialized copy,
-- refreshed by refresh_feature_matrix() (hourly loop + before the state map reads it).
grant select on public.feature_matrix_daily_live to service_role;
do $$ begin
  if exists (select 1 from pg_class c join pg_namespace n on n.oid = c.relnamespace
             where n.nspname = 'public' and c.relname = 'feature_matrix_daily' and c.relkind = 'v') then
    drop view public.feature_matrix_daily;
  end if;
end $$;
create materialized view if not exists public.feature_matrix_daily as select * from public.feature_matrix_daily_live;
create unique index if not exists feature_matrix_daily_d_uq on public.feature_matrix_daily (d);
grant select on public.feature_matrix_daily to anon, authenticated, service_role;

create or replace function public.refresh_feature_matrix() returns integer
language plpgsql security definer set search_path = public, pg_temp as $$
begin
  refresh materialized view concurrently public.feature_matrix_daily;
  return (select count(*) from public.feature_matrix_daily);
end $$;
revoke all on function public.refresh_feature_matrix() from public, anon, authenticated;
grant execute on function public.refresh_feature_matrix() to service_role;
