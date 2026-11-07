-- =============================================================================
-- T-295 · public.crowding_events(p_from, p_to, p_clean) —— 提案(本文件【不执行】DDL)
-- =============================================================================
-- 目的  :把 t242_crowding_setups.py 的 detect() 写成一个可在库里跑的内核,
--         逐事件复现 S-726 的 squeeze 218 + flush 20(2020 → 2026-11-04);
--         p_clean = true(默认)再按 S-777 的两条【日级】守卫剔掉伪事件
--         ⇒ 干净集 squeeze 185 + flush 16(与 S-777 复算逐条一致)。
-- 口径  :照抄 S-726 / S-768 预注册;一个常数都不扫。
-- 来源  :docs/research/t242_crowding_setups.py(已合并,detect() 在 207–255 行)
--         docs/research/T-295_crowding_sql.md(逐项对照表 + 边角清单)
-- 参照  :docs/research/t289_events.json(218 + 20 的事件清单)、t289_results.json
--
-- 用法(等 Seth 在库里 apply 之后):
--   -- 干净口径(S-777;前向表按这个建):
--   select kind, count(*) from public.crowding_events(date '2019-12-31', date '2026-11-04')
--    group by kind;                      -- 期望 squeeze 185 / flush 16
--   -- 旧口径(复现 S-726 / S-768 的 218 + 20,用来跟 t289_events.json 对账):
--   select kind, count(*) from public.crowding_events(date '2019-12-31', date '2026-11-04', false)
--    group by kind;                      -- 期望 squeeze 218 / flush 20
--   -- 逐事件对账(必须与 t289_events.json 的 (kind, symbol, d) 完全一致):
--   select kind, symbol, d, fund_pct, ret, atr_thr, qv_mult
--     from public.crowding_events(date '2019-12-31', date '2026-11-04', false)
--    order by kind, d, symbol;
--
-- ⚠ 口径陷阱(SQL 独有,python 里看不出来),先读报告 §边角:
--   E1 宇宙掩码必须是 653(含 4 个 kind 空 + dead_from 非空的币);2026-11-08 重跑
--      实测 653/888(缓存从 .json 变成 .csv.gz 后有变数,见报告 E1)。
--   E2 去重必须「距上一个【已计入】事件 ≥ 10 个日历日」;用 max(前一个候选日)
--      近似会少留事件(反例见报告 E4)。本文件用递归 CTE 实现。
--   E3 f7 为空时 python 给 pct=0.0(不是 NaN)⇒ 与「历史最低」不可区分 ——
--      这正是 S-777 点名的伪事件(33 条)。p_clean = true(默认)时本文件【加】
--      NULL 保护(f7 为空 ⇒ 不是事件);p_clean = false 才复现旧口径。
--   E4 【平局容差 1e-12】f7 的末位取决于求和结合顺序:参考实现用 pandas
--      rolling(7).mean()(增量 + 补偿),SQL 用 7 行显式求和(顺序累加)⇒ 个别行
--      差 1 ULP。严格判「相等」会把并列算成不等 ⇒ pct 差 0.5/j;实测全窗口
--      唯一受影响的一条是 HYPE 2026-01-27(阈值 0.10,两侧 0.10124 / 0.09917)。
--      本文件用容差 1e-12 判「相等」⇒ 与参考实现逐条一致(218/20 与 185/16)。
--   E5 【S-777 日级守卫】p_clean = true 时:① d 日 f7 为空 ⇒ 不是事件;
--      ② ATR14 ≤ 0 或 20 日均 qv ≤ 0 ⇒ 不是事件(零价差零成交的合约恒真命中)。
--      两条守卫把 218/20 变成 185/16(剔掉的 37 条:资金费起点之前的 TLM 25 +
--      ICP 8,以及 ATR/qv20 为 0 的合约)。
-- =============================================================================

create or replace function public.crowding_events(
    p_from date,
    p_to   date,
    p_clean boolean default true      -- true = S-777 干净口径(185/16);false = 旧口径(218/20)
)
returns table (
    kind       text,
    symbol     text,
    d          date,
    fund_pct   double precision,
    ret        double precision,
    atr_thr    double precision,
    qv_mult    double precision
)
language sql
stable
as $fn$
with
-- ── S1 · 宇宙(照 t242_crowding_setups.py main() 第 434–438 行)──────────────
--   python: kind=='coin' or (kind is None and dead_from is not None)
--   ⇒ SQL: kind='coin' 或 (kind 为空 且 dead_from 非空)
--   注意 'tradfi' 不进宇宙;kind 为空的 35 个里只有 4 个 dead_from 非空 → 653。
uni as (
    select distinct p.symbol
    from perp_bv_pairs p
    where p.kind = 'coin'
       or (coalesce(nullif(btrim(p.kind), ''), '') = '' and p.dead_from is not null)
),

-- ── S2 · 价格面板(照 load_pbv() + build_panels() 的摊平部分)──────────────
--   面板起点固定 2019-10-01(T-238 那次查询的 d=gte.2019-10-01 口径;
--   库里 perp_bv_daily 最早 2019-12-31,所以这条过滤目前不截断任何东西)。
--   bar0 = 0 基行号 = python 的面板列下标 j。
--   k    = 该合约的面板行数(python: len(sub);库里 o/h/l/c/qv 全非空,
--          所以「有限收盘数」与「行数」相等)。
px as (
    select
        b.symbol,
        b.d::date                                as d,
        b.o, b.h, b.l, b.c, b.qv,
        (row_number() over (partition by b.symbol order by b.d) - 1)::int as bar0,
        count(*) over (partition by b.symbol)     as k
    from perp_bv_daily b
    join uni u on u.symbol = b.symbol
    where b.d::date >= date '2019-10-01'
),

-- ── S3 · 资金费按 (symbol, d) 对齐(照 build_panels() 第 124–135 行)──────
--   python 用 MultiIndex reindex 到面板行上:面板里没有的日期丢弃,
--   面板里有而资金费没有的那天 ⇒ NaN。
--   ⚠ 若 v_funding_daily 出现重复 (symbol,d),python 会直接报错(reindex 重复轴),
--      max() 只是防呆;真出现重复时两者不等价 ⇒ 先查重再谈复现。
fdaily as (
    select f.symbol, f.d::date as d, max(f.funding_rate) as funding_rate
    from v_funding_daily f
    group by f.symbol, f.d::date
),
pxf as (
    select p.symbol, p.d, p.o, p.h, p.l, p.c, p.qv, p.bar0, p.k,
           fd.funding_rate
    from px p
    left join fdaily fd
           on fd.symbol = p.symbol and fd.d = p.d
),

-- ── S4 · 前一日收盘 + 真实波幅 TR(照 build_panels() 第 138–141 行)────────
--   python: tr = nanmax(H−L, |H−c_{j−1}|, |L−c_{j−1}|)
--   numpy.nanmax 忽略 NaN ⇒ Postgres GREATEST 同样忽略 NULL(全 NULL 才 NULL)
--   ⇒ 语义一致:首根 / 断档日退化成 H−L。
trc as (
    select
        x.*,
        lag(x.c) over w as c_prev
    from pxf x
    window w as (partition by x.symbol order by x.bar0)
),
tr as (
    select
        t.*,
        greatest(t.h - t.l,
                 greatest(abs(t.h - t.c_prev), abs(t.l - t.c_prev))) as tr
    from trc t
),

-- ── S5 · ATR14(照 build_panels() 第 143–148 行)──────────────────────────
--   python: rolling(14).mean().shift(1) ⇒ atr_j = mean(tr_{j−14..j−1})
--   pandas rolling 的 min_periods 默认 = 窗口宽 ⇒ 窗口内不足 14 个非空即 NaN。
--   SQL 的 avg() 忽略 NULL 会给出「非空个数不足也算」的平均值 ⇒ 必须用 count 卡住。
atr as (
    select
        t.*,
        case when count(t.tr) over wa = 14 then avg(t.tr) over wa end as atr
    from tr t
    window wa as (partition by t.symbol order by t.bar0
                  rows between 14 preceding and 1 preceding)
),

-- ── S6 · qv20:前 20 日均量(照 build_panels() 第 149–153 行)──────────────
--   python: rolling(20).mean().shift(1) ⇒ qv20_j = mean(qv_{j−20..j−1}),min_periods=20
qv20 as (
    select
        a.*,
        case when count(a.qv) over wq = 20 then avg(a.qv) over wq end as qv20
    from atr a
    window wq as (partition by a.symbol order by a.bar0
                  rows between 20 preceding and 1 preceding)
),

-- ── S7 · f7:前 7 日均资金费(年化)(照 build_panels() 第 155–164 行)────────
--   python: F.rolling(7).mean().shift(1) * (3*365)
--   ⇒ f7_j = mean(funding_{j−7..j−1}) × 1095;7 天缺一天 ⇒ NaN(min_periods=7)
--
--   ⚠ 两条容易漏的(python 第 157–160 行与第 162 行):
--   ① k_fund = 该合约面板里【有资金费观测】的天数。
--      k_fund < FUND_WIN+2 = 9 ⇒ python 整行 continue ⇒ f7 与 pct 全是 NaN
--      ⇒ 该合约【一个事件都不产生】(不是 pct=0!)。漏这条会凭空多出几千个
--        「拥挤空头」——实测漏掉它会把 squeeze 从 218 变成 5913。
--   ② f7 只在面板的【前 k_fund 行】上算(python: s = pd.Series(F[i, :k]))
--      —— 资金费有缺口时,这条截断切的是【尾部】,不是「最后 k_fund 个有资金费的日子」。
f7all as (
    select
        q.*,
        count(q.funding_rate) over (partition by q.symbol) as k_fund,
        case when count(q.funding_rate) over wf = 7
             then avg(q.funding_rate) over wf * 1095.0
        end as f7
    from qv20 q
    window wf as (partition by q.symbol order by q.bar0
                  rows between 7 preceding and 1 preceding)
),
f7 as (
    select * from f7all
    where k_fund >= 9
      and bar0 < k_fund
),

-- ── S8 · 扩张分位的【分母】:更早的行数(照 build_panels() 第 166–172 行)──
--   python: nprior = max(arange(1,k+1) − 1, 1) ⇒ 分母是「更早的行数」,
--   不是「更早的非空样本数」;f7 为空的行照样进分母、不进分子。
den as (
    select f.*, greatest(f.bar0, 1)::float as nprior
    from f7 f
),

-- ── S9 · 年龄门槛(照 detect() 第 211 行)─────────────────────────────────
--   python: ordmat − first_ord ≥ 180 天,first_ord = 面板内首根的日期。
--   ⚠ 参照系是【面板首根】,不是上市日(perp_bv_pairs.first_d 另有其值)。
--     库里最早 2019-12-31 ⇒ 老币的「年龄」从 2019-12-31 起算,不是从上市起算。
age as (
    select
        d.*,
        (d.d - min(d.d) over (partition by d.symbol))::int as age_days
    from den d
),

-- ── S10 · 便宜的门槛先过(照 detect() 第 231–242 行)──────────────────────
--   python 逐条 continue:
--     j ≥ 1 且 j ≤ k−2(最后一根不算,因为要留一根做前进收益)  → bar0
--     pct / qv20 / thr 必须有限 → qv20、atr 非空且 c_prev 非空非零
--     年龄 ≥ 180 天
--     ret 有限
--     qv ≥ 3 × qv20
--   剩下 pct ≤ 0.10 / ≥ 0.90 与 ret 的方向比较放到 S12。
pre as (
    select
        a.*,
        (a.c / a.c_prev - 1.0)                       as ret,
        (2.0 * a.atr / a.c_prev)                     as atr_thr,
        (a.qv / a.qv20)                              as qv_mult
    from age a
    where a.k >= 40                                   -- detect() 第 216 行:k < 40 直接跳过
      and a.bar0 >= 1
      and a.bar0 <= a.k - 2
      and a.age_days >= 180
      and a.qv20 is not null
      and a.atr   is not null
      and a.c is not null and a.c_prev is not null and a.c_prev <> 0
      and a.qv >= 3.0 * a.qv20
      -- S-777 日级守卫(p_clean = true 时生效;见报告 §3):
      --   ① d 日的 f7 为空 ⇒ 不是事件(python 给 pct=0.0,被当成「历史最低」)
      --   ② ATR14 ≤ 0 或 20 日均 qv ≤ 0 ⇒ 不是事件(零价差零成交的合约恒真命中)
      and (not p_clean
           or (a.f7 is not null and a.atr > 0 and a.qv20 > 0))
),

-- ── S11 · 扩张分位 pct(照 build_panels() 第 165–172 行)──────────────────
--   pct_j = ( #{i<j : f7_i < f7_j} + 0.5 × #{i<j : f7_i = f7_j} ) / nprior
--   · 只对过了便宜门槛的行算(数学上与全量算等价:分母/分子都只看更早的行)。
--   · f7 为空的更早行:比较结果为 NULL ⇒ 不进分子(与 numpy 的 NaN 比较一致),
--     但它们【进分母】(nprior 按行数算)——这一条最容易写错。
--   · f7_j 本身为空时:python 不做保护 ⇒ pct = 0/nprior = 0.0(S-777 的伪事件);
--     本文件在 p_clean = true 时已于 S10 把这些行剔掉 ⇒ 到这里 f7_j 必非空。
--   · 【平局容差 1e-12】(见文件头 E4):f7 的末位取决于求和结合顺序,严格判
--     「相等」会把并列算成不等 ⇒ pct 差 0.5/j,实测全窗口只有 HYPE 2026-01-27
--     一条被这一条规则翻面(0.10124 vs 0.09917,阈值 0.10)。用容差判「相等」
--     ⇒ SQL 与参考实现逐条一致(218/20 与 185/16 两种口径都对得上)。
--   · 代价:这是 O(候选数 × 该合约行数) 的范围连接。候选集被 S10 收得很窄,
--     实测不卡;生产上建议把 f7/atr/qv20 落成日频中间表(见报告 §落地)。
pct as (
    select
        p.symbol, p.bar0, p.d,
        p.f7, p.ret, p.atr_thr, p.qv_mult, p.nprior,
        ( count(*) filter (where e.f7 <  p.f7 - 1e-12)
        + 0.5 * count(*) filter (where abs(e.f7 - p.f7) <= 1e-12) )::float
          / p.nprior as fund_pct
    from pre p
    join f7 e
      on e.symbol = p.symbol and e.bar0 < p.bar0
    group by p.symbol, p.bar0, p.d, p.f7, p.ret, p.atr_thr, p.qv_mult, p.nprior
),

-- ── S12 · 事件判定 + 10 日去重(照 detect() 第 242–253 行)────────────────
--   flush  : pct ≥ 0.90 且 ret ≤ −thr
--   squeeze: pct ≤ 0.10 且 ret ≥ +thr
--   (python 是 if/elif,两者互斥,故 union all 安全)
--   去重  : 同一合约同一类,距上一个【已计入】事件 ≥ 10 个日历日才再计一次。
--           ⇒ 必须递归:「上一个已计入」不是「上一个候选」。
--             反例:候选 0/5/12 日 ⇒ python 留 {0,12};
--                   用 max(前一个候选日)=5 判 12 日 ⇒ 7 < 10 ⇒ 会误删 12 日。
cand as (
    select 'squeeze'::text as kind, p.symbol, p.d, p.fund_pct, p.ret,
           p.atr_thr, p.qv_mult,
           row_number() over (partition by p.symbol order by p.d) as rn
    from pct p
    where p.fund_pct <= 0.10 and p.ret >= p.atr_thr
    union all
    select 'flush'::text, p.symbol, p.d, p.fund_pct, p.ret,
           p.atr_thr, p.qv_mult,
           row_number() over (partition by p.symbol order by p.d)
    from pct p
    where p.fund_pct >= 0.90 and p.ret <= -p.atr_thr
),
walk as (
    select c.symbol, c.kind, c.rn, c.d, c.fund_pct, c.ret, c.atr_thr, c.qv_mult,
           c.d as last_kept, true as kept
    from cand c
    where c.rn = 1
    union all
    select c.symbol, c.kind, c.rn, c.d, c.fund_pct, c.ret, c.atr_thr, c.qv_mult,
           case when (c.d - w.last_kept) >= 10 then c.d else w.last_kept end,
           (c.d - w.last_kept) >= 10
    from walk w
    join cand c
      on c.symbol = w.symbol and c.kind = w.kind and c.rn = w.rn + 1
)
select
    w.kind::text        as kind,
    w.symbol::text      as symbol,
    w.d::date           as d,
    w.fund_pct::float   as fund_pct,
    w.ret::float        as ret,
    w.atr_thr::float    as atr_thr,
    w.qv_mult::float    as qv_mult
from walk w
where w.kept
  and w.d between p_from and p_to
order by w.kind, w.d, w.symbol;
$fn$;

-- =============================================================================
-- 只读等价体(apply 之前就能跑,用于对账;不是函数,是一段 CTE 查询)
-- =============================================================================
-- 下面这段与函数体逐字相同,只是把 p_from/p_to 换成字面量、去掉外层 select。
-- Seth 可以先在库里跑它、和 t289_events.json 对账,再决定要不要 apply 函数。
--
--   with ... (同上的 S1..S12,只是最后一段改成)
--   select w.kind, w.symbol, w.d, w.fund_pct, w.ret, w.atr_thr, w.qv_mult
--   from walk w
--   where w.kept and w.d between date '2019-12-31' and date '2026-11-04'
--   order by w.kind, w.d, w.symbol;
--
-- 期望(2026-11-08 在 python 侧实测,见 docs/research/t295_audit.json):
--   干净口径(S-777 守卫在):squeeze 185 条、flush 16 条;
--   把 S10 里那三行守卫去掉(= p_clean = false 的旧口径):squeeze 218 条、
--   flush 20 条,逐 (kind, symbol, d) 与 docs/research/t289_events.json 完全一致。
--   平局容差 1e-12 必须留在 S11 里(否则 HYPE 2026-01-27 会多出一条)。
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 索引建议(Seth apply 时一并建,否则 S11 的范围连接会全表扫)
-- -----------------------------------------------------------------------------
--   create index if not exists perp_bv_daily_symbol_d_idx
--       on perp_bv_daily (symbol, d);
--   create index if not exists v_funding_daily_symbol_d_idx
--       on v_funding_daily (symbol, d);
--   create index if not exists perp_bv_pairs_symbol_idx
--       on perp_bv_pairs (symbol);
