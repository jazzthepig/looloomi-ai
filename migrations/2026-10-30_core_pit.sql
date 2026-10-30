-- 2026-10-30 · S-700:按时点的 ① 回放(逐月前 N 大市值、含死币),与 core_alpha_daily(alpha = 1)同一套权重公式,只换名单。
-- 成员:每月第一天,按上月最后一个有数的日子(月初前 10 天内最晚的一天)的市值取前 p_n;整月不变。
-- 权重:市值加权(前一日市值)、单币 ≤ p_cap、每日再平衡;当日没有连续两日价格的成员不计入当日,其余重归一。不扣成本。
-- 排除:稳定币、包裹 / 质押凭证、代币化真实世界债权(名单写死在这里;改名单 = 改 S-700 预注册);选成员那天 volume/mcap ≥ 1%。
create or replace function public.core_pit_excluded()
returns text[] language sql immutable as $$
  select array['USDT','USDC','BUSD','DAI','TUSD','PAX','USDP','UST','USTC','FDUSD','USDE','USDS','PYUSD','GUSD','HUSD','USDD','USDN',
               'FRAX','LUSD','EURS','EURC','EURT','USDJ','SUSD','MIM','USD1','USDY','USD0','RLUSD','BUIDL','USDTB','USD',
               'WBTC','STETH','WSTETH','WEETH','CBBTC','BTCB','RETH','CBETH','WETH','SOLVBTC','WBETH','LBTC','TBTC','EZETH',
               'RSETH','METH','SFRXETH','FRXETH','BNSOL','JITOSOL','MSOL','WHYPE','HBTC','RENBTC','SUSDE','SUSDS','SDAI',
               'STKAAVE','XAUT','PAXG','WTRX','WBNB','USDT0','SOLVBTC.BBN',
               -- 代币化的真实世界债权 / 证券(① 是加密 beta,不是代币化房贷;S-700 修订二)
               'FIGR_HELOC','OUSG','BENJI','WTGXX','TBILL','USYC','BUIDL','JTRSY','USTB','VBILL']
$$;

-- 流动性地板(S-700 修订二):选成员那天 volume / mcap ≥ 1%;成交额为空按不过
create or replace function public.core_pit_min_turnover()
returns double precision language sql immutable as $$ select 0.01::double precision $$;

create or replace function public.core_pit_members(p_start date, p_end date, p_n int default 24)
returns table(m date, symbol text, rnk int, mcap double precision, asof date)
language sql stable set search_path = public, pg_temp as $$
  with months as (
    select generate_series(date_trunc('month', p_start)::date, date_trunc('month', p_end)::date, interval '1 month')::date m),
  cand as (
    select mo.m, a.symbol, a.mcap, a.d,
           row_number() over (partition by mo.m, a.symbol order by a.d desc) rn
    from months mo
    join asset_mcap_daily a on a.d < mo.m and a.d >= mo.m - 10 and a.mcap > 0 and a.price > 0
         and a.volume is not null and a.volume / a.mcap >= core_pit_min_turnover()
    where a.symbol <> all (core_pit_excluded())),
  ranked as (
    select m, symbol, mcap, d, row_number() over (partition by m order by mcap desc) rnk
    from cand where rn = 1)
  select m, symbol, rnk::int, mcap, d from ranked where rnk <= p_n order by m, rnk
$$;

create or replace function public.core_pit_daily(p_start date, p_end date, p_n int default 24, p_cap double precision default 0.4)
returns table(d date, ret double precision, n int, top_symbol text, top_w double precision)
language sql stable set search_path = public, pg_temp as $$
  with mem as materialized (select m, symbol from core_pit_members(p_start, p_end, p_n)),
  syms as materialized (select distinct symbol from mem),
  p as materialized (
    select a.symbol, a.d, date_trunc('month', a.d)::date m, a.price, a.mcap,
           lag(a.price) over w pp, lag(a.mcap) over w pm, lag(a.d) over w pd
    from asset_mcap_daily a
    join syms s using (symbol)
    where a.d >= p_start - 10 and a.d <= p_end and a.price > 0
    window w as (partition by a.symbol order by a.d)),
  r as (
    select p.symbol, p.d, p.price / p.pp - 1 as ret, p.pm
    from p join mem on mem.symbol = p.symbol and mem.m = p.m
    where p.pd = p.d - 1 and p.pp > 0 and p.pm > 0 and p.price / p.pp - 1 between -0.95 and 5 and p.d >= p_start),
  cw as (select r.*, pm / sum(pm) over (partition by r.d) w0 from r),
  -- 单币上限:超出部分按比例分给上限以下的币(窗口函数,不自连接 —— 自连接在 8 年上要几分钟)
  cwx as (select cw.*, sum(greatest(w0 - p_cap, 0)) over (partition by cw.d) excess,
                       sum(case when w0 < p_cap then w0 else 0 end) over (partition by cw.d) rest from cw),
  cw2 as (
    select cwx.d, cwx.symbol, cwx.ret,
           case when w0 >= p_cap then p_cap else w0 * (1 + excess / nullif(rest, 0)) end w1
    from cwx),
  cw3 as (select cw2.*, row_number() over (partition by cw2.d order by w1 desc, symbol) rk from cw2)
  select cw3.d, sum(w1 * ret) ret, count(*)::int n, max(symbol) filter (where rk = 1) top_symbol, max(w1) top_w
  from cw3 group by cw3.d order by cw3.d
$$;
revoke all on function public.core_pit_members(date, date, int) from anon, authenticated;
revoke all on function public.core_pit_daily(date, date, int, double precision) from anon, authenticated;
