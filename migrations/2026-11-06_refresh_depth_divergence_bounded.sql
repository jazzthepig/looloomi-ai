-- 2026-11-06 · T-231 ①:refresh_depth_divergence 的 ranked CTE 扫 ohlcv_daily 全部历史(≤ v_d),
-- 实测均值 8.3 s、最大 29.35 s(statement_timeout 30 s),而调用方的 HTTP 客户端 10 s 就放弃并重试 ——
-- 每次重试再跑一遍 9 s 的函数;服务端其实写完了(depth_divergence_log 每天都有行),记录却报 error,
-- _forward_record_loop 10-31 16:04 之后 0 次 ok。
--
-- 改动只有一处:ranked 加 `trade_date > v_d - 200`(日历天)。窗口最远看 80 根(w80 / w80a)+ lag 21,
-- 200 天对日线留 ≥ 101 根余量。逐行比对(同一 p_date,旧 vs 新的 depth_z / px20 / hist / 有无值):
--   p_date = 2026-11-05:210 / 210 行,差异 0;耗时 9,154 ms → 816 ms
--   p_date = 2026-08-20:321 / 321 行,差异 0
-- 其余逐字不动(返回码 −1 / −3、口径、写法)。
create or replace function public.refresh_depth_divergence(p_date date default null::date)
 returns integer
 language plpgsql
 set statement_timeout to '30s'
 set search_path to 'public', 'extensions', 'pg_temp'
as $function$
declare v_d date; v_n int; v_baseline int; v_today int;
begin
  v_baseline := 262;

  if p_date is not null then
    v_d := p_date;
  else
    select max(trade_date) into v_d from (
      select trade_date, count(distinct symbol) c from ohlcv_daily
      where source not in ('binance_hist','coingecko','yfinance')
        and asset_class in ('Crypto','L1','L2','DeFi','Infrastructure','RWA')
        and trade_date >= current_date - 30
      group by 1
    ) s where v_baseline > 0 and c::numeric / v_baseline >= 0.50;
  end if;

  if v_d is null then
    raise warning 'refresh_depth_divergence: no day in the last 30 clears the 50 percent floor against the DECLARED baseline of % panel symbols (S-323f). The maintained feed does not reach the panel -- OPEN RISK #0a, not a quiet market. It will not clear by waiting.', v_baseline;
    return -1;
  end if;

  if p_date is null and v_d < current_date - 3 then
    raise warning 'refresh_depth_divergence: the newest day clearing the floor is % (% days old). Rewriting it would return a positive row count and advance nothing, which is how this stall stayed invisible for 16 days (S-323g). Refusing. Pass an explicit date to backfill deliberately.', v_d, (current_date - v_d);
    return -3;
  end if;

  select count(distinct symbol) into v_today from ohlcv_daily
   where source not in ('binance_hist','coingecko','yfinance')
     and asset_class in ('Crypto','L1','L2','DeFi','Infrastructure','RWA')
     and trade_date = v_d;

  with ranked as (
    select upper(symbol) as symbol, trade_date, close, volume, source,
           row_number() over (
             partition by upper(symbol), trade_date
             order by case source
                        when 'hyperliquid'        then 1
                        when 'eodhd'              then 2
                        when 'coingecko_pro_ohlc' then 3
                        else 9 end) as rn
    from ohlcv_daily
    where source not in ('binance_hist','coingecko','yfinance')
      and asset_class in ('Crypto','L1','L2','DeFi','Infrastructure','RWA')
      and trade_date <= v_d
      and trade_date > v_d - 200          -- T-231:窗口最远 80 根 + lag 21,200 个日历天足够;全历史扫描是 9 s 的来源
  ),
  base as (
    select symbol, trade_date, close, source,
           case when volume > 0 and close > 0 then volume::float8 * close end as dv
    from ranked where rn = 1
  ),
  feat as (
    select symbol, trade_date, close, source,
      avg(dv) over w20 as adv20, avg(dv) over w80 as advb,
      stddev_samp(dv) over w80 as advsd,
      lag(close,1) over ws as cp, lag(close,21) over ws as cl,
      count(*) over w80a as hist
    from base
    window ws   as (partition by symbol order by trade_date),
           w20  as (partition by symbol order by trade_date rows between 20 preceding and 1 preceding),
           w80  as (partition by symbol order by trade_date rows between 80 preceding and 21 preceding),
           w80a as (partition by symbol order by trade_date rows between 80 preceding and 1 preceding)
  ),
  today as (
    select symbol, adv20, hist, source,
      case when advsd > 0 then (adv20 - advb) / advsd end as depth_z,
      case when cl > 0 then cp / cl - 1 end as px20
    from feat where trade_date = v_d
  )
  insert into depth_divergence_log
    (d, symbol, rule_version, depth_z, px20, adv20_usd, cell, signal,
     is_measured, problems, n_symbols_day, n_symbols_p90, baseline_source)
  select v_d, t.symbol, 'depth_divergence_v2', t.depth_z, t.px20, t.adv20,
    case
      when t.depth_z is null or t.px20 is null then 'unmeasured'
      when t.depth_z >= 1.5 and abs(t.px20) < 0.10 then 'depth_up_price_flat'
      when t.depth_z >= 1.5 and t.px20 >= 0.10      then 'depth_up_price_up'
      when t.depth_z >= 1.5                         then 'depth_up_price_down'
      else 'depth_flat'
    end,
    case when t.depth_z >= 1.5 and abs(t.px20) < 0.10 then 'UNDERWEIGHT' else 'NEUTRAL' end,
    (t.depth_z is not null and t.px20 is not null),
    case
      when t.depth_z is null and t.source = 'coingecko_pro_ohlc'
        then 'no volume on coingecko_pro_ohlc: /ohlc/range does not return it, so depth_z is unmeasurable on this source (S-312)'
      when t.depth_z is null or t.px20 is null
        then 'insufficient history: needs >=80 prior bars (had ' || t.hist || ') on source ' || t.source
    end,
    v_today, v_baseline, 'declared_panel_262_s323f'
  from today t
  on conflict (d, symbol, rule_version) do update set
    depth_z = excluded.depth_z, px20 = excluded.px20, adv20_usd = excluded.adv20_usd,
    cell = excluded.cell, signal = excluded.signal,
    is_measured = excluded.is_measured, problems = excluded.problems,
    n_symbols_day = excluded.n_symbols_day, n_symbols_p90 = excluded.n_symbols_p90,
    baseline_source = excluded.baseline_source;

  get diagnostics v_n = row_count;
  return v_n;
end
$function$;

-- 顺手收口(应用时发现):函数 EXECUTE 原来开给 PUBLIC / authenticated(写表的调用者只该是 Railway 的 service_role)。
revoke all on function public.refresh_depth_divergence(date) from public, anon, authenticated;
grant execute on function public.refresh_depth_divergence(date) to service_role;
