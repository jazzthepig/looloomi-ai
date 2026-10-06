-- S-490 (2026-10-06, migration s490_hl_book_s436_correction): hl_book_daily 09-25 ~ 09-28 的收益用了晚一天的
-- coingecko_pro_ohlc(S-436 修复前):记的是前一天的涨跌,09-28 的 −2.05%(等权)整天没进账。
-- 原则:**决策照旧,只改账。** decided / held / book / features / jev_raw 一个不动(那是当时真实做出的决定,
-- 包括 09-28 那次用晚一天价格做的决策);只把这 4 天的收益换成同一持仓在正确价格下的收益,之后的 NAV 顺延。
-- 原值留在新列 correction['S-490'](orig_ret / orig_nav / reason / at),不删。幂等:已有 correction 的行不再改。
alter table public.hl_book_daily add column if not exists correction jsonb;

with px as (
  select trade_date d, symbol, close / lag(close) over (partition by symbol order by trade_date) - 1 r
  from ohlcv_daily
  where source = 'coingecko_pro_ohlc' and symbol in ('BTC','ETH','SOL','HYPE')
    and trade_date between '2026-09-20' and '2026-10-06'),
arms as (
  select h.d, a.key arm, (h.ret ->> a.key)::float ret_rec, a.value held
  from hl_book_daily h, jsonb_each(h.held) a),
adj as (
  select arms.d, arms.arm, sum(w.value::text::float * (p1.r - p0.r)) / nullif(count(*), 0) adj
  from arms
  join lateral jsonb_each(arms.held) w on true
  join px p1 on p1.symbol = w.key and p1.d = arms.d
  join px p0 on p0.symbol = w.key and p0.d = arms.d - 1
  where arms.d between '2026-09-25' and '2026-09-28'
  group by 1, 2),
nw as (
  select arms.d, arms.arm, arms.ret_rec + coalesce(adj.adj, 0) ret_new
  from arms left join adj using (d, arm)),
ch as (
  select d, arm, ret_new, exp(sum(ln(1 + ret_new)) over (partition by arm order by d)) nav_new from nw),
agg as (
  select d, jsonb_object_agg(arm, round(ret_new::numeric, 8)) ret_j, jsonb_object_agg(arm, round(nav_new::numeric, 8)) nav_j
  from ch where d >= '2026-09-25' group by d)
update public.hl_book_daily h
set correction = jsonb_build_object('S-490', jsonb_build_object(
      'orig_ret', h.ret, 'orig_nav', h.nav, 'at', now(),
      'reason', '09-25~09-28 的收益用了晚一天的 coingecko_pro_ohlc(S-436 修复前);决策照旧,只改账;之后的 NAV 顺延')),
    ret = case when h.d <= '2026-09-28' then agg.ret_j else h.ret end,
    nav = agg.nav_j
from agg
where h.d = agg.d and h.correction is null;
