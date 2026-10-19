-- T-133 (2026-10-19): Binance 公开历史档(data.binance.vision,U 本位永续 metrics)→ 每名每日一行的持仓结构特征。
-- 写入端:src/data/market/binance_vision.py(_binance_vision_loop 每小时一轮,按 deriv_metrics_plan 补)。
-- n_points = 0 的行 = 那天没有文件(未上市 / 下架),特征全空 —— 记下来不再重取;不是 0 值。
create table if not exists deriv_metrics_daily (
    symbol                   text        not null,
    d                        date        not null,
    oi_close                 double precision,
    oi_value_close           double precision,
    top_pos_ratio_close      double precision,
    top_pos_ratio_mean       double precision,
    top_acct_ratio_close     double precision,
    global_acct_ratio_close  double precision,
    taker_ratio_mean         double precision,
    taker_ratio_last4h       double precision,
    n_points                 integer     not null default 0,
    source                   text        not null default 'binance_vision_metrics',
    recorded_at              timestamptz not null default now(),
    primary key (symbol, d)
);
alter table deriv_metrics_daily enable row level security;

-- 回补计划:binance_hist 在册名字的目标起点(max(上市日, 2020-09-01))、最后一根日线,与已覆盖的区间。
create or replace view deriv_metrics_plan with (security_invoker = true) as
select o.symbol,
       greatest(o.first_d, date '2020-09-01') as target_start,
       o.last_d,
       c.min_d,
       c.max_d
from (select symbol, min(trade_date) as first_d, max(trade_date) as last_d
      from ohlcv_daily
      where source = 'binance_hist' and symbol not in ('USDC', 'BTCDOM', 'DEFI')
      group by symbol) o
left join (select symbol, min(d) as min_d, max(d) as max_d from deriv_metrics_daily group by symbol) c using (symbol);
