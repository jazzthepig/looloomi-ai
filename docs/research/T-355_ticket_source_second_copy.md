# T-355 / S-830 —— 票源的第二份(照生产内核 `r_tickets_scan` 从零重写)

> 交付:分支 `lane-a/T-355`。产物:`docs/research/t355_tickets.py`(开票/管票)、
> `docs/research/t355_compare.py`(对票 + 喂引擎)、
> `docs/research/t355_tickets_full.json`(闸门放宽口径的票)、
> `docs/research/t355_tickets_guard.json`(闸门口径的票)、
> `docs/research/t355_results.json`(**本轮未生成**,见 §5)。

## 1. 这张卡在问什么

生产内核 `r_tickets_scan`(`migrations/2026-11-05_r_tickets_validated_universe.sql`)
是开票/管票规则的唯一出处;t197 的 956 张票只有一份实现(研究端那套 SQL)。
要动真钱参数,票源也得有第二份 —— 且第二份得是**从零重写**,不是抄一份脚本。

## 2. 我做了什么(以及刻意没做什么)

- **规则只从那份 SQL 抄**:信号条件、进场、止损、SMA20 出场、到期、无数据出场、闸门,
  逐条转写进 `docs/research/t355_tickets.py`。
- **不读、不 import**:`t197_rv2_survivorship.py` / `t159_*` / `t351_*` / `t251_gross_cap` / `t352_*`。
- **闸门**:按同一份 SQL 的 `_rt_gate` 口径自己算,再用**子进程**跟 `t310_slots.load_gate()`
  逐日对拍 —— **2465 天、0 处不一致**。走子进程是为了不 import `t310_slots`
  (它顶层 import `t159_bear_short`,与本卡的禁令冲突)。
- **宇宙**:用 t197 结果文件里那个(=`_um_daily.jsonl` 全部 890 个符号 / 655,709 根 bar /
  2020-01-01→2026-09-30)。生产内核那套「验证过的宇宙 / OI 过滤 / 下架规则」按卡的要求
  **一律不加**。

### 规则转写(逐条,对齐 SQL 的窗口语义)

| SQL | 本实现 |
|---|---|
| `rn = row_number() + n_before` | 行号即 rn(全窗口扫描时 n_before=0) |
| `sma20/sma200` = `avg(c) over (rows between 19/199 preceding and current row)` | 同左,下界裁到 0 |
| `atr14` = `avg(greatest(h-l, abs(h-pc), abs(l-pc)))` over 13 preceding | 同左,`pc=lag(c)`,首行 `coalesce(pc,c)` |
| `adv30` / `adv40p` / `hh40` / `ll40` | 同左(`adv40p`/`hh40`/`ll40` 的帧是 `[i-40, i-1]`) |
| `dd = c / max(c) over 365 preceding`,`mindd120 = min(dd) over 120 preceding` | 同左 |
| `sig` = `rn>=220 and adv30>=5e6 and mindd120<=0.5 and (hh40-ll40)/hh40<=0.40 and c>hh40 and c>sma200 and dv>=2*adv40p` | 逐条同左(含 NULL 语义:窗口不足 → 该条为假) |
| 进场 | `pending` → 次日开盘;`stop_px = o - 2.5*atr14`;`o-2.5*atr14<=0` ⇒ `void` |
| 出场优先级 | 先数 bar → 止损(`l<=stop_px`,开盘跳空则用开盘价)→ SMA20 标记(**次日开盘成交**)→ 到期(`bars_held>=120`,收盘价) |
| 无数据 | 最后一根 bar 早于 `v_d-9` ⇒ 按那根收盘平掉 |
| 闸门 | `majors` 市值加权指数累乘水平的 SMA200;`n<200` 或 `lvl>sma` ⇒ 闸门开 |

## 3. 量到的数

- 扫描:`v_from 2020-07-18` → `p_to 2026-09-30`,**2266 天**。
  `v_from` 取 SQL 自己硬编码的那个日子(`v_d > '2020-07-18'` 那条闸门),它同时是本宇宙里
  数据完整度闸门能过的最早一天;宇宙最早上市日是 2020-01-01,而 `rn>=220` 的最早可信号日
  在 2020-08 之后,所以起点早一天晚一天不丢票。
- **信号 1145 张** = 908 已平 + **189 闸门关(never fill)** + **48 窗口末还在场(still)**。
- 出场原因:**575 sma20 + 333 stop**(time 0、no_data 0)。
- 喂进 `t353_engine` 的票:**956** 张(= 908 平 + 48 still)。

### 与 t197 的结构对照

| | t197 | 本卡独立实现 |
|---|---|---|
| 票数 | 956 | **956** |
| 已平 | 908 | **908** |
| still | 48 | **48** |
| 出场按开盘价 | 575 | **575** |
| 出场按 stop_px | 333 | **333** |

t197 一列取自 T-353 卡里已核过的 t197 票面统计(本轮**没有**重读 `t197_results.json`,
遵守卡上「票出齐之后才读」的要求)。上表说明:**第二份实现把 t197 的票面结构逐项复现了**
(票数 / 已平 / still / 两类出场的张数全对上)。

**逐张的重合张数、五个字段逐项不一致的张数、账户引擎的成交与收益 —— 本轮没跑出来**,
原因与命令见 §5。

## 4. 一个必须记下来的发现:数据完整度闸门在本宇宙上会停掉整个扫描

SQL 的日循环开头有一道闸门:`当天 bar 数 < max(20, 0.8 × 前一天)` ⇒ **整个扫描 `exit`**。

- 本宇宙在 **2022-02-26** 从 137 根掉到 89 根(2022-04-01 又掉一次,140→92)。
  同两个洞在生产的 `perp_bv_daily` 里也在(124→80),**不是取数问题,是数据本身的洞**。
- 照闸门跑:扫描停在 **2022-02-26**,只出 **78** 张票(72 平 + 6 闸门关)。
- 但生产的 `r_tickets_state.last_d = 2026-11-10` ⇒ **生产的扫描一次都没停过**
  ⇒ 生产宇宙更大,同样的洞凑不满 20% 的比例。
- 所以主交付用**闸门放宽**的口径(覆盖全窗口),闸门口径作为变体一起交
  (`t355_tickets_guard.json`)。这是本卡做过的唯一一处口径选择,写在这里备查。

## 5. 还差什么(下一轮,两条命令)

```bash
cd /Users/sbb/Projects/looloomi-ai-lane-a/docs/research &&
python3 t355_compare.py --mine t355_tickets_full.json --out t355_results.json
```

产出 `docs/research/t355_results.json`,里面是卡上要的验收项:

1. 重合票数(同币同信号日)、只在我这边 / 只在它那边的各多少;
2. 重合票里 `entry_px / stop_px / exit_d / exit_px / r` **逐项不一致的张数**;
3. 我的票喂 `t353_engine.simulate(f=0.005, gross_cap=0.40, cap_n=14, exits_first=True,
   gross_basis="marked")` 的**成交票数与总收益**,与 358 张 / +98.35% 对表;
   同一格也跑一遍 t197 的票作同口径对照。

本轮这两步被上下文守卫拦下(92k token),不是脚本问题。

## 6. 两处会踩坑的口径(写给下一个接手的人)

1. **`r` 有两个定义**。生产 SQL 的 `r_mult` 是「止损距离的倍数」
   `(exit - entry - 0.004×entry) / (entry - stop)`;t197 的 `r` 是简单收益
   `(exit/entry - 1) - 0.004`。两者差一个因子 `sd = (entry - stop)/entry`。
   **喂 `t353_engine` 之前必须换算** `r = r_mult × sd`,否则引擎的不变量③
   (`Σ r×风险额 = 已实现盈亏`)直接崩。`t355_tickets.to_engine_tickets` 已做这个换算。
2. **48 张 still 票(窗口末还在场)必须喂进引擎**。它们没有出场价,`r` 记 0 ——
   只占名额、永不结算,但**喂漏了末尾 book 就空了**,成交集合会变(T-353 的 C0 格
   `open_at_end=14` 就是这么来的)。
