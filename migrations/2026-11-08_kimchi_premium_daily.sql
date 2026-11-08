-- 2026-11-08 · 全市场韩国溢价(「泡菜溢价」):BTC 在 Upbit 的韩元价 ÷(Binance BTC/USDT × 当天的 USDKRW)。
-- 汇率 = macro_daily series = 'usdkrw'(EODHD USDKRW.FOREX 日收盘,korea_retail.py 每天补);周末 / 假日取最近一个已知收盘。
-- 已知的偏:分母用 USDT 当美元(2018-10 USDT 曾折价 2–4%,那几周溢价会被高估);Upbit 与 Binance 都按 UTC 切日,收盘对齐。
-- 用法:S-787(只报不判)—— 韩国散户在整个市场层面多付钱的时候,之后 30 / 90 天 BTC 与面板怎么走。只描述,不进 ③。
create or replace view public.kimchi_premium_daily with (security_invoker = true) as
select u.d,
       u.c                                   as btc_krw,
       g.close                               as btc_usdt,
       fx.value                              as usdkrw,
       fx.d                                  as fx_d,
       ln(u.c / (g.close * fx.value))        as prem
from public.upbit_daily u
join public.ohlcv_daily g on g.symbol = 'BTC' and g.source = 'binance_hist' and g.trade_date = u.d and g.close > 0
join lateral (
  select m.value, m.d from public.macro_daily m
  where m.series = 'usdkrw' and m.d <= u.d and m.d > u.d - 7 and m.value > 0
  order by m.d desc limit 1
) fx on true
where u.market = 'KRW-BTC' and u.c > 0;
grant select on public.kimchi_premium_daily to anon, authenticated, service_role;
