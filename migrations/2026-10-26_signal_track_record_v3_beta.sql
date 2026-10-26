-- 2026-10-26 · refresh_signal_track_record v3:β 调整层第一次上线(用户报告 10-26:「空头标签分不清做空币还是做空 β」)。
--
-- 为什么不是 v2:v2(scripts/supabase_refresh_signal_track_record_v2.sql,2026-07-26)写好了但从未应用,
-- 而且它读的是已退役的 signal_outcomes;它的 β 用「之前的每一行」—— 那些行的 30 天结果在当天还没出来(看了未来)。
-- v3 从 cis_standard_outcomes(正式日终序列,S-540)聚合:
--   · PIT β = 同一标的、信号日 ≤ d − 30 天(结果当天已知)的 30 天收益对基准的 OLS 斜率,≥ 20 个先验,
--     不足 ⇒ NULL(不当 1.0 用);标的就是基准(BTC / SPY)的行 β 为 NULL。
--   · 方向化 β 调整边 = OUTPERFORM 族 (a − β·b),UNDER* 族 −(a − β·b);NEUTRAL 不给方向边。
--   · 相邻日的观察高度重叠:另给 n_months(信号月数)与按月聚类的 t(alpha_t_month / edge_beta_adj_t_month)——
--     逐日的 t(edge_beta_adj_t)会把同一段行情数几十遍,只作对照。
--   · 分组(grp = crypto 对 BTC / tradfi 对 SPY);每组每个信号另有一行 grade = 'ALL'(该信号各档合计)。
--   · 对照 NEUTRAL(edge_vs_neutral_*):同组同月 NEUTRAL 的 β 残差 (a − β·b) 作基线,方向化后按月聚类。
--     10-26 实测:加密整体都跑输自己的 β×BTC(NEUTRAL 残差 −1.26%/30d)—— 不扣这一项,
--     UNDERPERFORM 的 +2.27% β 调整边看起来像标签的本事,其实大半是全宇宙共有的拖累(对 NEUTRAL 只剩 t −0.86)。
-- 单位:*_pct 都是百分数(×100),与 v1 的 avg_alpha_pct 一致。

alter table public.signal_track_record add column if not exists grp text;
alter table public.signal_track_record add column if not exists n_months integer;
alter table public.signal_track_record add column if not exists alpha_t_month real;
alter table public.signal_track_record add column if not exists edge_beta_adj_t_month real;
alter table public.signal_track_record add column if not exists edge_vs_neutral_pct real;
alter table public.signal_track_record add column if not exists edge_vs_neutral_t_month real;

create or replace function public.refresh_signal_track_record()
 returns integer
 language plpgsql
 security definer
 set search_path to 'public', 'pg_temp'
as $function$
declare n_rows int;
begin
  insert into signal_track_record (grp, signal, grade, n, avg_alpha_pct, alpha_win_pct, avg_abs_return_pct, lookback_days, basis,
                                   avg_edge_beta_adj_pct, edge_beta_adj_t, avg_beta_pit, n_beta_adj,
                                   n_months, alpha_t_month, edge_beta_adj_t_month, edge_vs_neutral_pct, edge_vs_neutral_t_month)
  with o as (
    select grp, symbol, bench, d, signal, grade, a_ret, b_ret, alpha
    from cis_standard_outcomes
    where alpha is not null and signal is not null and a_ret is not null and b_ret is not null
  ), p as (
    select o.*,
           count(*)         over w as n_prior,
           sum(a_ret)       over w as sa,
           sum(b_ret)       over w as sb,
           sum(a_ret*b_ret) over w as sab,
           sum(b_ret*b_ret) over w as sbb
    from o
    window w as (partition by symbol order by d range between unbounded preceding and interval '30 days' preceding)
  ), b as (
    select *, case when symbol <> coalesce(bench, '') and n_prior >= 20 and abs(sbb - sb*sb/n_prior) > 1e-12
                   then (sab - sa*sb/n_prior) / (sbb - sb*sb/n_prior) end as beta_pit
    from p
  ), e as (
    select grp, signal, grade, date_trunc('month', d) as m, alpha, a_ret, beta_pit, a_ret - beta_pit*b_ret as res,
           case when signal in ('STRONG OUTPERFORM', 'OUTPERFORM') then 1
                when signal in ('UNDERPERFORM', 'UNDERWEIGHT') then -1 end as dir,
           case when beta_pit is null then null
                when signal in ('STRONG OUTPERFORM', 'OUTPERFORM') then a_ret - beta_pit*b_ret
                when signal in ('UNDERPERFORM', 'UNDERWEIGHT') then -(a_ret - beta_pit*b_ret) end as edge
    from b
  ), lvl as (
    select grp, signal, grade, m, alpha, a_ret, beta_pit, edge, res, dir from e
    union all
    select grp, signal, 'ALL', m, alpha, a_ret, beta_pit, edge, res, dir from e
  ), neu as (
    select grp, m, avg(res) as nres from e where signal = 'NEUTRAL' group by 1, 2
  ), mo as (
    select l.grp, l.signal, l.grade, l.m, avg(l.alpha) as ma, avg(l.edge) as me,
           max(l.dir) * (avg(l.res) - max(neu.nres)) as mv
    from lvl l left join neu on neu.grp = l.grp and neu.m = l.m
    group by 1, 2, 3, 4
  ), mt as (
    select grp, signal, grade, count(ma) as n_months,
           avg(ma) / nullif(stddev_samp(ma), 0) * sqrt(count(ma)) as t_alpha,
           avg(me) / nullif(stddev_samp(me), 0) * sqrt(count(me)) as t_edge,
           avg(mv) as v, avg(mv) / nullif(stddev_samp(mv), 0) * sqrt(count(mv)) as t_v
    from mo group by 1, 2, 3
  ), agg as (
    select grp, signal, grade, count(*) as n, avg(alpha) as a, count(*) filter (where alpha > 0) as wins,
           avg(a_ret) as ar, count(edge) as nb, avg(beta_pit) as bp, avg(edge) as ed,
           avg(edge) / nullif(stddev_samp(edge), 0) * sqrt(count(edge)) as t_naive
    from lvl group by 1, 2, 3
  )
  select agg.grp, agg.signal, agg.grade, agg.n,
         round((agg.a * 100)::numeric, 2), round(100.0 * agg.wins / agg.n, 1), round((agg.ar * 100)::numeric, 2), 30,
         'official daily-close series (published + point-in-time reconstruction of the same standard); 30d vs BTC (crypto) / SPY (traditional); '
         || 'beta = PIT OLS on the same asset''s matured 30d outcomes (signal day <= d - 30), >= 20 priors, else NULL',
         round((agg.ed * 100)::numeric, 2), round(agg.t_naive::numeric, 2), round(agg.bp::numeric, 3), agg.nb,
         mt.n_months, round(mt.t_alpha::numeric, 2), round(mt.t_edge::numeric, 2),
         round((mt.v * 100)::numeric, 2), round(mt.t_v::numeric, 2)
  from agg join mt using (grp, signal, grade);
  get diagnostics n_rows = row_count;
  return n_rows;
end $function$;
