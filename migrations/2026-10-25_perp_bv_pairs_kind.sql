-- 2026-10-25 · S-683 修订:两条做空臂只做加密合约。perp_bv_pairs 记下每个合约是什么资产类别。
--
-- kind = 'coin'(加密)/ 'tradfi'(股票、港股、韩股、商品、外汇永续)/ null(还没分类 —— 臂里不用)。
-- 种子 = fapi exchangeInfo 快照(2026-10-25,underlyingType,在 Seth 的沙盒里取,存数据根 research/s681/);
-- 之后新上的合约由 perp_bv_daily.run_once 用 CoinGecko Pro 的 binance_futures 衍生品行情补:有 coin_id ⇒ coin。

alter table public.perp_bv_pairs add column if not exists underlying_type text;
alter table public.perp_bv_pairs add column if not exists kind text check (kind in ('coin', 'tradfi'));
alter table public.perp_bv_pairs add column if not exists classified_by text;
alter table public.perp_bv_pairs add column if not exists classified_at timestamptz;
