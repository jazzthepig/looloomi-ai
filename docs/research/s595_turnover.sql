-- S-595 换手(成交额 / 市值)会不会骗人 —— 每周截面 Spearman IC(按年分段跑,避开语句超时)。
-- 用法:把 :lo / :hi(宇宙日期)与 :base_lo / :base_hi(取数窗口 = :lo 往前 8 个月、:hi 往后 1 个月)换成具体日期,
-- 每年跑一次;输出一行 csv:d,n,ic_turn28,ic_jump,rho(turn28,质量合成),ic_turn28_高质量半,ic_turn28_低质量半。
-- 宇宙 = 每周五非 BTC 市值前 50,26 周年化波动 ≥ 15%,去稳定 / 包装 / 质押币(名单同 s587_mine_crypto.WRAPPED)。
-- turn28 = 过去 28 天日均成交额 / 当日市值;jump = turn28 ÷ 自己过去 26 周 turn28 的中位数(不含当周);之后 = 28 天价格收益。
-- 质量合成 = −秩(vol13) − 秩(supply13) + 秩(size)(S-587)。
with base as (
  select symbol, d, price, mcap, volume from asset_mcap_daily
  where source='coingecko_pro_market_chart' and d between :base_lo and :base_hi and price > 0
    and upper(symbol) not in ('BTC','WBTC','WETH','STETH','WSTETH','CBBTC','RETH','WEETH','EETH','TBTC','BTCB','CBETH','METH','EZETH','RSETH','LBTC','SOLVBTC','CLBTC','BUIDL','USDT','USDC','DAI','USDE','SUSDE','FDUSD','PYUSD','USDS','USD1','TUSD','USDD','FRAX','RLUSD','USDTB','USDF','USDG','BFUSD','XAUT','PAXG','JITOSOL','MSOL','BNSOL','JUPSOL','OUSG','USYC','BENJI','WBETH','SAVAX','OSETH','SFRXETH','FIGR_HELOC')
),
daily as (
  select symbol, d, price, mcap, avg(volume) over w28 as vol28, count(volume) over w28 as nvol28,
    lead(price, 28) over (partition by symbol order by d) as p_fwd28, lead(d, 28) over (partition by symbol order by d) as d_fwd28
  from base window w28 as (partition by symbol order by d rows between 27 preceding and current row)
),
wk as (
  select symbol, d, price, mcap, case when nvol28 >= 20 and mcap > 0 then vol28/mcap end as turn28,
    case when d_fwd28 = d + 28 then p_fwd28/price - 1 end as fwd28,
    ln(price / lag(price) over (partition by symbol order by d)) as lr,
    lag(case when mcap > 0 then mcap/price end, 13) over (partition by symbol order by d) as units13
  from daily where extract(isodow from d) = 5
),
wk2 as (
  select *, stddev_samp(lr) over (partition by symbol order by d rows between 25 preceding and current row)*sqrt(52) as v26,
    count(lr) over (partition by symbol order by d rows between 25 preceding and current row) as n26,
    stddev_samp(lr) over (partition by symbol order by d rows between 12 preceding and current row)*sqrt(52) as v13,
    case when mcap > 0 then (mcap/price)/nullif(units13,0) - 1 end as sup13, case when mcap > 0 then ln(mcap) end as size,
    array_agg(turn28) over (partition by symbol order by d rows between 26 preceding and 1 preceding) as past_turn
  from wk
),
uni as (select *, row_number() over (partition by d order by mcap desc) rk from wk2 where v26 >= 0.15 and n26 >= 20 and mcap > 0 and d between :lo and :hi),
u50 as (select u.*, u.turn28 / nullif((select percentile_cont(0.5) within group (order by x) from unnest(u.past_turn) x where x is not null), 0) as jump from uni u where rk <= 50),
ranked as (
  select d, rank() over (partition by d order by turn28) r_turn, rank() over (partition by d order by jump) r_jump, rank() over (partition by d order by fwd28) r_fwd,
    (- rank() over (partition by d order by v13) - rank() over (partition by d order by sup13) + rank() over (partition by d order by size)) as combo_raw
  from u50 where turn28 is not null and fwd28 is not null and jump is not null and v13 is not null and sup13 is not null
),
r2 as (select *, rank() over (partition by d order by combo_raw) r_combo, ntile(2) over (partition by d order by combo_raw) qhalf from ranked)
select string_agg(concat_ws(',', d, n, a, b, c, e, f), ';' order by d) csv from (
select d, count(*) n, round(corr(r_turn, r_fwd)::numeric,3) a, round(corr(r_jump, r_fwd)::numeric,3) b, round(corr(r_turn, r_combo)::numeric,3) c,
  round((corr(r_turn, r_fwd) filter (where qhalf=2))::numeric,3) e, round((corr(r_turn, r_fwd) filter (where qhalf=1))::numeric,3) f
from r2 group by d) x;
