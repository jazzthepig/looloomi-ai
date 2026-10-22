-- world50_mcap_weekly.shares —— 当周市值用的那个股数(2026-10-23 UTC,Seth)
--
-- 为什么:CIS v2 的个股「供给纪律」与 CIS 页上公开的「股数 52 周变化」原来是 市值 ÷ ohlcv_daily(eodhd)收盘 推出来的。
-- 但 ohlcv_daily 的收盘是**总回报复权**(分红、分拆都往回改),市值是 股数 × 原始收盘 ——
-- 两者相除 = 股数 × 原始价 / 复权价,52 周变化 ≈ 真实股数变化 − 股息率 − 分拆价值。
-- 实测 10-21:125 家里 40 家 |变化| > 5%;CMCSA −14.8%(2026-01 Versant 分拆那一周台阶 −6%,其余是股息),
-- VZ / T / MO / BTI / PFE 都是 −6% 到 −9%(约等于各自的股息率)。
--
-- 股数是 build_mcap 里本来就有的那一列:今天的拆股口径;ADR 按每份 ADR 折算;本地上市按交易所申报的股数。
-- 只加列,不改已写的值;下一次 world50 周更(PART_VERSIONS mcap 21)整段重写时填上。
alter table public.world50_mcap_weekly add column if not exists shares double precision;

comment on column public.world50_mcap_weekly.shares is
  '当周市值用的股数(今天的拆股口径;ADR 按每份 ADR 折算)。mcap_usd ÷ shares = 当周原始收盘(换成美元)。'
  '不要用 mcap_usd ÷ ohlcv_daily.close 推股数 —— 那个收盘是总回报复权的(2026-10-23)。';
