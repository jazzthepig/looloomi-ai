-- S-704 · CIS v2 加密切换条件的前向核对(S-668 ① ②)。11-09 满 20 天时原样再跑。只读。
-- ① 覆盖(宽 = 有分;严 = missing 为空)
with u as (select d, count(*) n, count(*) filter (where score is not null and n_dims >= 2) scored,
                  count(*) filter (where score is not null and coalesce(array_length(missing, 1), 0) = 0) complete
           from cis_v2_daily where grp = 'crypto' group by d)
select 'coverage' part, d::text, n, scored, complete,
       (scored >= ceil(0.95 * 25))::int ok_wide, (complete >= ceil(0.95 * 25))::int ok_strict
from u order by d;
-- ② 换档:每名字每 30 天(两边同一批名字、同一段日子)
with v2 as (select symbol, d, signal from cis_v2_daily where grp = 'crypto'),
v1 as (select o.symbol, o.d, o.signal from cis_official_daily o join (select distinct symbol from v2) s using (symbol)
       where o.d between (select min(d) from v2) and (select max(d) from v2)),
ch as (select 'v2' k, symbol, d, signal, lag(signal) over (partition by symbol order by d) prev from v2
       union all select 'v1', symbol, d, signal, lag(signal) over (partition by symbol order by d) from v1)
select 'tier_changes' part, k, count(distinct symbol) names, count(distinct d) days,
       count(*) filter (where prev is not null and signal is distinct from prev) changes,
       round((count(*) filter (where prev is not null and signal is distinct from prev))::numeric
             / nullif(count(distinct symbol), 0) / nullif(count(distinct d) - 1, 0) * 30, 3) per_name_per_30d
from ch group by k order by k;
-- 描述:v1 / v2 名次相关(每天),最新一天名次差最大的 5 个
with j as (select v.d, v.symbol, v.score s2, o.cis_score s1 from cis_v2_daily v
           join cis_official_daily o on o.symbol = v.symbol and o.d = v.d where v.grp = 'crypto'),
r as (select d, symbol, rank() over (partition by d order by s1 desc) r1, rank() over (partition by d order by s2 desc) r2 from j)
select 'rank_corr' part, d::text, round(corr(r1, r2)::numeric, 3) spearman, count(*) n from r group by d order by d;
with j as (select v.d, v.symbol, v.score s2, o.cis_score s1, v.signal g2, o.signal g1 from cis_v2_daily v
           join cis_official_daily o on o.symbol = v.symbol and o.d = v.d
           where v.grp = 'crypto' and v.d = (select max(d) from cis_v2_daily where grp = 'crypto'))
select 'disagree' part, symbol, rank() over (order by s1 desc) r_v1, rank() over (order by s2 desc) r_v2, g1, g2
from j order by abs(rank() over (order by s1 desc) - rank() over (order by s2 desc)) desc limit 5;
