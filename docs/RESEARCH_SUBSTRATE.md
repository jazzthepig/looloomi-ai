# 研究数据底座 — 取数从这里开始(给 Minimax-C)

> **为什么有这份文件。** 2026-09-16 C 的 W5 报 `n=0 全 INSUFFICIENT`,理由是
> `cis_history.db` 0 字节、`_data/research/d{1,2,15}_out/` 不存在。
> 同一天下午,同样三本账的日收益我在 **Supabase 里几分钟就取到了** ——
> 51 天重叠、组合/单腿 0.696。
>
> **数据一直在,C 在翻本地空文件,而我的 brief 没说去哪儿取。**
> 一个手上没有可运行数据的研究员只能退回执行模式 —— 那不是他的问题,是我的。
>
> 下面每一条 SQL **都是 2026-09-16 实跑过的**,不是示意。
> 跑不通的判据等于没有判据(同日 `/internal/health` 那一课)。

---

## §1 一条规矩

**本地 `.db` / `_data/` / `/tmp` 里的东西一律当作缓存,不当作真相。**
真相在 Supabase。本地文件可以空、可以旧、可以不存在,**那不构成 BLOCKED** ——
先去库里查,查不到再报 BLOCKED,并说明查的是哪张表。

---

## §2 账本日收益(W5 的输入)

活账本与各自的行数、最新日,一条查完:

```sql
select 'causal' b, count(*) n, max(mark_date)::text newest from causal_paper_nav
union all select 'combined',  count(*), max(mark_date)::text from combined_book_nav
union all select 'scalable',  count(*), max(mark_date)::text from scalable_book_nav
union all select 'two_layer', count(*), max(mark_date)::text from two_layer_paper_nav
union all select 'beta_core', count(*), max(mark_date)::text from beta_core_nav
union all select 'fusion',    count(*), max(mark_date)::text from fusion_paper_nav
order by n desc;
```

**日收益列名不统一**(`dingge_paper_nav` 没有 `daily_return`,只有 realized/unrealized),
所以取数要显式列出来,不要 `select *`:

| 表 | 日收益列 | 注意 |
|---|---|---|
| `causal_paper_nav` / `combined_book_nav` / `scalable_book_nav` / `two_layer_paper_nav` | `daily_return` | — |
| `beta_core_nav` | `daily_return` | **必须 `where void_reason is null`** |
| `fusion_paper_nav` | `daily_return` | **必须 `where void_reason is null and inception_id='v2'`** |
| `dingge_paper_nav` | 无 | 只有 `realized_pnl`/`unrealized_pnl`,需自己推 |

### 两两相关 + 组合/单腿比(2026-09-16 实跑)

```sql
with r as (
  select 'causal' b, mark_date d, daily_return v from causal_paper_nav where daily_return is not null
  union all select 'combined', mark_date, daily_return from combined_book_nav where daily_return is not null
  union all select 'scalable', mark_date, daily_return from scalable_book_nav where daily_return is not null
),
wide as (select d, max(v) filter (where b='causal') c, max(v) filter (where b='combined') k,
                 max(v) filter (where b='scalable') s from r group by d),
ok as (select *, (c+k+s)/3.0 p from wide where c is not null and k is not null and s is not null)
select count(*) n,
       round(corr(c,k)::numeric,3) rho_ck, round(corr(c,s)::numeric,3) rho_cs,
       round(corr(k,s)::numeric,3) rho_ks,
       round((stddev(p)/nullif((stddev(c)+stddev(k)+stddev(s))/3.0,0))::numeric,3) as 组合_单腿
from ok;
```

实测结果(留作回归基线):`n=51`,`rho` = 0.456 / −0.014 / 0.218,**组合/单腿 = 0.696**。

---

## §3 面板收益(外生分段变量)

⚠️ **W5 的分段变量必须外生。** 按组合自身收益分段会 induce 负相关
(我 2026-09-16 踩过,差点把伪影当成支持 3.3x 的证据)。用面板:

```sql
with px as (select symbol, trade_date, close from ohlcv_daily
            where asset_class='Crypto' and close>0 and trade_date >= date '2026-06-01'),
pr as (select symbol, trade_date,
              close/nullif(lag(close) over (partition by symbol order by trade_date),0)-1 r from px)
select trade_date d, avg(r) mkt, count(*) n_sym
from pr where r is not null and abs(r) < 0.5
group by trade_date having count(*) >= 15 order by d;
```

⚠️ **读 `ohlcv_daily`(基表),不要读 `ohlcv_daily_canonical`** ——
视图停在 2026-08-08(`asset_id` 自 08-06 全 NULL,被 INNER JOIN 丢掉,见 SPINE §5.0)。
修好之前 canonical 会静默给你 39 天前的世界。

`abs(r) < 0.5` 是防拆分/坏 tick;`count(*) >= 15` 是防早期只有几个标的的日子。

---

## §4 相位(5a 宏观 / 5b 微观)

```sql
select d, features, regime_db, meditation_regime, n_universe
from regime_daily order by d desc limit 5;              -- 5b:11 维 CIS 态 + 78 天人工判读

select d, vec_full, measured_dims, regime_label
from market_state_vectors order by d desc limit 5;      -- 5a:15 实测维,⚠️ 停 42 天
```

**跨角度的相似度数值不可比**(维度数 15 vs 11)。合成只能在排名/一致性上做。

---

## §5 结果与判据

```sql
select era, count(*), min(d)::text, max(d)::text from signal_outcomes_unified group by era;
select * from signal_edge_map order by signal, risk_band;
select run_id, kind, verdict, sharpe, dsr, n_obs, window from experiment_runs order by ts desc limit 20;
```

**只读 `signal_outcomes_unified`,不要单读 `signal_outcomes` 或 `signal_journal`** ——
单读任一张静默丢一半历史。

---

## §6 已知的坑(全部实测,别再踩一遍)

| 坑 | 表现 | 怎么躲 |
|---|---|---|
| `risk_meter_history` 有一行 `d = 2099-12-31` | `max(d)` 永远答 2099,新鲜度判据永久失效 | 任何 freshness 查询加 `where d <= current_date` |
| `ohlcv_daily_canonical` 停 39 天 | 视图返回行,只是旧的,**不报错** | 用基表;修好前不迁 |
| 30 天窗口重叠 | 212 天 ≈ **7 个独立窗口**,t 值虚高 | 报 `n_independent = n/horizon`,n<30 标 INSUFFICIENT |
| 多重检验 | R41:8 个变体 PSR 0.84 / **DSR 0.00** | 任何扫参必带 DSR 校正并报 `n_trials` |
| 按结果分段 | 造出负相关伪影 | 分段变量必须外生(用 §3 的面板) |
| 幸存者偏差 | 25.1pp/年(S-111),最大效应的 8 倍 | 用 `assets.delisted_at`,别只取活着的 |

---

## §7 报 BLOCKED 的门槛

BLOCKED 是**有用的**输出 —— C 2026-09-16 对 W5 报 BLOCKED 是对的,
比编一个 n=3 的结论好得多。但一条 BLOCKED 必须带三样:

1. **我查了哪张表**(表名 + 实跑的 SQL)
2. **它返回了什么**(行数 / 最新日 / 报错原文)
3. **最小解封条件** —— 「需要 X 才能算」,而不是「没有数据」

「本地文件不存在」**不满足第 1 条**。
