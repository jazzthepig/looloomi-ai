-- 2026-10-26 · S-689:面板外 Binance 永续名字 → CoinGecko coin_id 的价格校验映射(待补清单 + 结果)。
--
-- 写入 ← src/data/market/perp_mcap_backfill.py(_perp_mcap_backfill_loop,每 10 分钟最多 3 次 CoinGecko 请求)。
-- 选中币的日线写进已有的 cg_coin_mcap_daily。对 Binance 零请求(隐含价 = deriv_metrics_daily 的 oi_value_close / oi_close)。
-- 公开数据,lane 可读(anon 只读);写入只走 Railway 的 secret key。

create table if not exists public.perp_cg_map (
  symbol        text primary key,            -- Binance U 本位合约的 base(如 1000SHIB、LUNA2)
  query_symbol  text,                        -- 在 CoinGecko 上找的 symbol(去 1000 前缀 / 特例)
  mult          integer not null default 1,  -- 合约价 = CG 价 × mult
  candidates    text[],                      -- /coins/list(active + inactive)里同 symbol 的全部 coin_id
  tried         text[],
  coin_id       text,                        -- 价格校验通过的那个
  verdict       text not null default 'pending' check (verdict in ('pending', 'resolved', 'unresolved', 'too_many')),
  med_err       double precision,            -- median |CG 价 × mult / 隐含价 − 1|
  n_overlap     integer,
  rows_written  integer,
  note          text,
  seeded_at     timestamptz not null default now(),
  checked_at    timestamptz
);

alter table public.perp_cg_map enable row level security;
grant select on public.perp_cg_map to anon;
drop policy if exists lane_read on public.perp_cg_map;
create policy lane_read on public.perp_cg_map for select to anon using (true);

-- 种子:deriv_metrics_daily 里 2023-01-01 起有 OI、asset_mcap_daily 里没有价格 / 市值的 43 个名字(2026-10-26 查得)。
insert into public.perp_cg_map (symbol) values
  ('1000LUNC'), ('1000SHIB'), ('1000WHY'), ('1000XEC'), ('42'), ('ALPACA'), ('ALPHA'), ('AMB'), ('ATA'), ('BADGER'),
  ('BEL'), ('BID'), ('BSW'), ('COS'), ('DAM'), ('DMC'), ('EPT'), ('FIS'), ('FXS'), ('HIGH'), ('IP'), ('KEY'), ('LEVER'),
  ('LINA'), ('LOOM'), ('LUNA2'), ('MEMEFI'), ('MILK'), ('NEIROETH'), ('NULS'), ('OMG'), ('PERP'), ('QUICK'), ('SLERF'),
  ('STPT'), ('SWELL'), ('TOKEN'), ('TROY'), ('TRU'), ('VANRY'), ('VIDT'), ('VINE'), ('VOXEL')
on conflict (symbol) do nothing;
