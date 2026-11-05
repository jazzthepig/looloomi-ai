-- S-718(2026-11-05):binance_um_hist(永续日线存档,到 2026-08-08)用 perp_bv_daily(同一个 data.binance.vision um 日档)续写。
-- 只续 binance_um_hist 里已有的符号(= R-v2 验证过的宇宙);volume = qv / c,使 close × volume = 报价成交额(与存档口径一致,S-718 核:比值中位 1.003)。
-- 幂等:唯一键 (symbol, trade_date, source) 冲突即跳过;不改任何已有行。已通过 Supabase MCP 施加(migration name: um_bridge_fill);首跑插入 26,593 行(2026-08-09 → 11-03)。
create or replace function public.um_bridge_fill(p_to date default null)
returns jsonb
language plpgsql
set search_path to 'public'
as $$
declare
  v_to date := coalesce(p_to, (now() at time zone 'utc')::date - 1);
  v_from date;
  v_n int := 0;
begin
  select max(trade_date) into v_from from ohlcv_daily where source = 'binance_um_hist';
  if v_from is null then
    return jsonb_build_object('ok', false, 'reason', 'binance_um_hist is empty');
  end if;
  with sym as (
    select symbol, max(asset_id) asset_id from ohlcv_daily where source = 'binance_um_hist' group by symbol
  ), ins as (
    insert into ohlcv_daily (symbol, asset_class, trade_date, open, high, low, close, volume, source, recorded_at, asset_id)
    select p.symbol, 'Crypto', p.d, p.o, p.h, p.l, p.c, case when p.c > 0 then p.qv / p.c else null end, 'binance_um_hist', now(), s.asset_id
    from perp_bv_daily p join sym s on s.symbol = p.symbol
    where p.d > v_from - 30 and p.d <= v_to and p.c > 0 and p.qv is not null
    on conflict (symbol, trade_date, source) do nothing
    returning 1
  )
  select count(*) into v_n from ins;
  return jsonb_build_object('ok', true, 'from', v_from, 'to', v_to, 'inserted', v_n,
    'max_d', (select max(trade_date) from ohlcv_daily where source = 'binance_um_hist'),
    'symbols_last', (select count(*) from ohlcv_daily where source = 'binance_um_hist' and trade_date = v_to));
end
$$;
grant execute on function public.um_bridge_fill(date) to service_role;
revoke execute on function public.um_bridge_fill(date) from anon, authenticated, public;
