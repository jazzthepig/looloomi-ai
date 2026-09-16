-- S-361 P0 · applied 2026-09-16 · canonical 视图停 39 天而无人知
--
-- ┌ 症状 ─────────────────────────────────────────────────────────────────┐
-- │  ohlcv_daily            基表   最新 2026-09-16   ← 今天有数据          │
-- │  ohlcv_daily_canonical  视图   最新 2026-08-08   ← 落后 39 天          │
-- └───────────────────────────────────────────────────────────────────────┘
--
-- 视图不会自己陈旧 —— 它在读取时计算。机制:近 7 天写入的 1,770 行
-- `asset_id` 全是 NULL,视图 `JOIN assets` 是 INNER JOIN,整批被丢掉。
-- 所有源在同一周停写:
--     binance_hist        最后一次带 asset_id  2026-08-08
--     coingecko           最后一次带 asset_id  2026-08-07
--     eodhd               最后一次带 asset_id  2026-08-06
--     coingecko_pro_ohlc  从来没写过           9,263 行
--     hyperliquid         从来没写过           2,655 行
--
-- 39 天里没有任何东西报错:视图照常返回 485,352 行,只是旧的。
-- 而后果被放大一层 —— **唯一「守规矩」读 canonical 的 `outcome_tracker`
-- 拿到 39 天前的世界,23 处直读基表的代码拿到今天的。规矩把守规矩的人害了。**
-- `docs/SPINE.md` 当时还建议把那 23 处迁到 canonical:一份方向基准
-- 把所有人指向了断掉的那一边。
--
-- 它被发现的唯一原因:Minimax-B 被要求「逐处判定」而不是「照着迁」,
-- 于是他在动 vault/tick.py 前停下来问覆盖。**任务形状决定了它会不会被发现。**
--
-- ── 三步,顺序不能反 ────────────────────────────────────────────────────
--
-- 1. 数据:按 symbol 从 assets 回填 asset_id。
--    安全性:assets.symbol 唯一;PK 是代理键 id;唯一键 (symbol,trade_date,source)
--    不含 asset_id;FK 由 symbol 匹配保证有效。
--        实测回填 18,310 / 18,460 行。canonical 立刻回到 2026-09-16,
--        近 7 天标的数 0 → 235。
--    剩 150 行 / 10 个 symbol 在 assets 里没条目(APEX CASHCAT KBONK KFLOKI
--    KLUNC KNEIRO KPEPE KSHIB MNT PURR —— Hyperliquid 系,K 前缀是 1000x)。
--    **是否给它们建 assets 条目属于准入,不该由一个 JOIN 顺手决定。**
--
-- 2. 结构:JOIN → LEFT JOIN,且 asset_class 取 coalesce(a.class, o.asset_class)。
--    ⚠️ 只改 LEFT JOIN 不够:行回来了但 asset_class 会变 NULL,而下游普遍写
--    `where asset_class='Crypto'` —— **丢失会从 join 移到 filter,同样静默**。
--    基表自己就有 asset_class,实测那 18,460 行上 100% 填着,所以连降级都不需要。
--    这是 I1:缺失要传播成可见的 NULL,不能让整行蒸发,也不能换个地方继续蒸发。
--
-- 3. 写入:触发器在写入处解析 asset_id。
--    实测 `src/` 里没有任何写入端设过 asset_id —— 修某一个没用,第六个还会忘。
--    这不是「填默认值」(MEMORY.md 警告的是发明数据),而是**解析**:
--    symbol 已在行里,assets.symbol 唯一,asset_id 是它的确定性函数。
--    解析不出来留 NULL,由第 2 步承接 —— **解析不出来的会出现,不会消失。**
--
-- ── 守卫 ────────────────────────────────────────────────────────────────
-- 上面三步都是**机制**,机制会被下一次重构删掉/绕过/被第六个写入端忽略。
-- `tests/test_canonical_keeps_up_with_base.py`(已接 preflight)查的是**后果**:
-- 视图落后基表 > 1 天即红,`asset_class` 出现 NULL 即红。
-- 无凭据时打印 NOT CHECKED 而不是静默变绿。

-- ── 步骤 1:回填(已执行,此处留档以便复现)──────────────────────────
-- update ohlcv_daily o set asset_id = a.asset_id
--   from assets a where o.asset_id is null and a.symbol = o.symbol;
-- -- 实测 UPDATE 18310

-- ── 步骤 2:视图 ────────────────────────────────────────────────────────
create or replace view public.ohlcv_daily_canonical as
select distinct on (o.symbol, o.trade_date)
    o.symbol,
    o.asset_id,
    o.trade_date,
    coalesce(a.class, o.asset_class) as asset_class,
    o.source,
    o.open, o.high, o.low, o.close, o.volume,
    case o.source
        when 'coingecko' then 'usd_notional'
        when 'eodhd'     then 'shares'
        when 'yfinance'  then 'shares'
        else 'base_units'
    end as volume_unit,
    case o.source
        when 'binance_hist' then 'continuous_utc'
        when 'hyperliquid'  then 'continuous_utc'
        when 'coingecko'    then 'vendor_snapshot'
        else 'session'
    end as bar_convention,
    o.source <> 'coingecko' as open_usable
from ohlcv_daily o
left join assets a on a.asset_id = o.asset_id
order by o.symbol, o.trade_date,
    case o.source
        when 'binance_hist' then 1
        when 'hyperliquid'  then 2
        when 'eodhd'        then 3
        when 'coingecko'    then 4
        when 'yfinance'     then 5
        else 9
    end;

-- ── 步骤 3:写入触发器 ──────────────────────────────────────────────────
create or replace function public.ohlcv_resolve_asset_id()
returns trigger language plpgsql as $$
begin
    if new.asset_id is null and new.symbol is not null then
        select a.asset_id into new.asset_id
        from public.assets a where a.symbol = new.symbol limit 1;
    end if;
    return new;
end;
$$;

drop trigger if exists trg_ohlcv_resolve_asset_id on public.ohlcv_daily;
create trigger trg_ohlcv_resolve_asset_id
    before insert or update of symbol, asset_id on public.ohlcv_daily
    for each row execute function public.ohlcv_resolve_asset_id();

-- ── 验收(2026-09-16 实测)──────────────────────────────────────────────
--   canonical 最新日                  2026-09-16   (修前 2026-08-08)
--   canonical 近 7 天标的数           235          (修前 0)
--   canonical.asset_class NULL 行     0
--   10 个孤儿 symbol 在视图里          150 行       (修前 0 —— 它们消失着)
--   去重仍在生效                      56,523 行跨源重复被去掉
--   触发器正例:插 BTC 无 asset_id     → 解析出 BTC
--   触发器反例:插 __NOSUCHSYM__      → 留 NULL,且**仍出现在 canonical**
--                                        asset_class=Crypto(来自基表)
