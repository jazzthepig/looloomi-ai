-- 2026-11-06 · exec_backfill_forward_returns 每次把 ohlcv_daily_canonical(DISTINCT ON 全表 150 万行)物化成 px,
-- 再拿 ~100 行待补的 trade_results 去连 —— 实测 605 次调用均值 8,135 ms、最大 28,543 ms;
-- 调用方的共享客户端 10 s 就放弃,于是 _forward_return_backfill_loop 24 小时 26 次 error(reason 还是空的)。
-- 这一列(realized_return_7d)是 CIS IC 乘数的输入(S-203)。
--
-- 改法:每个待补行用 LATERAL 直接按 (symbol, trade_date) 走 ohlcv_daily 的唯一索引,
-- 在可信源里按原优先级(binance_hist > hyperliquid > eodhd)取一条。与原式等价:canonical 的 DISTINCT ON
-- 优先级里这三个源排 1–3,任何别的源都排在它们后面 —— 所以「canonical 选中的那条在可信源里」⟺「有可信源的行,
-- 且选中的是其中优先级最高的」。比对(最近 400 个 trade_results,不看是否已补):旧 370 / 新 370 行,ret 差异 0;
-- 耗时 2,151 ms → 15 ms(子集);全表待补情形 3,423 ms → 19 ms。
--
-- 安全模型不变:SECURITY DEFINER + 函数体内 service_role 检查;search_path 固定。
create or replace function public.exec_backfill_forward_returns(horizon_days integer default 7)
 returns table(filled_id bigint)
 language plpgsql
 security definer
 set search_path to 'public'
as $function$
begin
    if auth.role() is distinct from 'service_role' then
        raise exception 'exec_backfill_forward_returns requires service_role (got %)',
              coalesce(auth.role(), 'null');
    end if;

    return query
    with calc as (
        select tr.id, (p7.close / p0.close - 1.0) as ret
        from trade_results tr
        join lateral (
            select o.close, o.source from ohlcv_daily o
             where o.symbol = tr.symbol and o.trade_date = tr.entry_time::date
               and o.source in ('binance_hist', 'hyperliquid', 'eodhd')
             order by case o.source when 'binance_hist' then 1 when 'hyperliquid' then 2 else 3 end
             limit 1) p0 on true
        join lateral (
            select o.close, o.source from ohlcv_daily o
             where o.symbol = tr.symbol and o.trade_date = tr.entry_time::date + horizon_days
               and o.source in ('binance_hist', 'hyperliquid', 'eodhd')
             order by case o.source when 'binance_hist' then 1 when 'hyperliquid' then 2 else 3 end
             limit 1) p7 on true
        where tr.realized_return_7d is null
          and tr.entry_time is not null
          and p0.source = p7.source              -- S-106: bar-convention seam reads as a move
          and p0.close > 0
    ),
    upd as (
        update trade_results t
        set realized_return_7d = c.ret
        from calc c
        where t.id = c.id
        returning t.id
    )
    select id from upd;
end;
$function$;
