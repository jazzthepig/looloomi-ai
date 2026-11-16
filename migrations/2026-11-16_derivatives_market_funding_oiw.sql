-- 2026-11-16 · derivatives_market_daily:加 OI 加权资金费的分子分母两列(给 positioning 读库用)。
--
-- WHY. `src/data/cis/positioning.py` 每 30 分钟直接打 CoinGecko 的**公开**端点 `/derivatives`;
-- 而这张表的写入端(`src/data/market/derivatives_market.py`,Analyst 档,每 6 小时一轮)打的是
-- **同一个端点的同一份数据**。同一个数据、同一个端点,分了两个额度池:公开端点每分钟只有十几次
-- (而且 Pro key 在公开 host 上会被忽略),429 是家常便饭;Analyst 档每分钟 500 次却几乎没被这条路径用上。
-- 「路径直接走了调用,而不是先走我们的数据库」的一个具体实例。
--
-- WHAT. 两列,刻意存**原始量和分母**,不存算好的比例:
--   funding_oiw_sum = Σ(funding_rate × open_interest)  —— 只统计带 funding_rate 的永续
--   oi_funding_usd  = Σ open_interest                   —— 同一批行(加权平均资金费的分母)
-- 两者相除 = OI 加权平均资金费。存分子分母而不是存比例,是因为 positioning 的口径是
-- 「OI 加权平均」,而这张表的 `top_funding_raw` 是「持仓最大的那个场所的资金费」—— 两个不同的量,
-- 不能互相顶替;读者自己除一次,口径就永远不会和 API 路径悄悄分叉。
--
-- WHO READS IT. `src/data/cis/positioning.py::refresh_positioning()`:先读这张表(最新一天),
-- 读不到或读旧了(>12 小时)才回落 CoinGecko **Pro** 端点。口径两条路完全一致。
--
-- 迁移没跑之前会怎样:写入端报 PGRST204(列不存在),`derivatives_market.run_once` 会**退回旧列集重试**
-- (不丢这一轮数据,只是没有资金费两列);positioning 读列失败 → 自动走 API 回落。两条路都不会静默出错。
--
-- LIVENESS: select max(d), max(fetched_at), count(*) from derivatives_market_daily;

alter table public.derivatives_market_daily
  add column if not exists funding_oiw_sum double precision,
  add column if not exists oi_funding_usd double precision;
comment on column public.derivatives_market_daily.funding_oiw_sum is 'Σ(funding_rate × open_interest) over perpetual rows carrying a funding_rate — numerator of the OI-weighted funding';
comment on column public.derivatives_market_daily.oi_funding_usd is 'Σ open_interest over the same rows — denominator of the OI-weighted funding';
notify pgrst, 'reload schema';
