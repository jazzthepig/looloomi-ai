# T-419 —— 按键翻页的末页核对游标:修法、测试钉住、以及**本轮没跑完的那一半**

> 分支 `lane-a/T-419`(基线 = `origin/main` + `origin/lane-a/T-379` 的按键翻页 + 本卡的探针修复)。
> 卡:`tasks/T-419.json`。产物:`/Volumes/CometCloudAI/cometcloud-local/research/t419/`。
> **本轮状态:①② 已完成并实测;③④⑤⑥(线上背靠背重测)未跑 —— 原因见 §4,脚本已就位、命令已写好。**

---

## 1. 一句话结论

末页那次「还有没有行」的核对,用的是**进入这一轮时就已算好的旧游标**(上一页的键),
问的其实是「上一页之后还有没有行」⇒ **答案永远是「有」** ⇒ 白发一次请求、把每页行数误设成
末页行数(线上量到 8,296)、「服务端上限被调低」的检测在按键路径上失效。
**修法**:核对请求的谓词用**本页最后一行**(`out.extend` 之后的 `out[-1]`)的键重建;
建不出来(键值带保留字符)⇒ 退回 `offset=len(out)`。**取数请求一个字没动**,读出来的行数、
内容、顺序不变。

## 2. 改了什么

`src/data/style/header.py`:

* 新增 `_keyset_cursor(plan, last_row)` —— 续读游标统一由「要用它的那一行的键」建;
  建不出来 ⇒ 空 ⇒ 走 OFFSET 版(语义不变)。
* `_read_all` 里两处游标:
  * **取数请求**:仍用上一页最后一行(`out[-1]`,extend 之前)—— 这一处本来就是对的,没动;
  * **核对请求**:改用 `out.extend(batch)` 之后的 `out[-1]`(本页最后一行)—— **这是本卡的修复**。

OFFSET 版语义保持不变:末页不满且 ≥1,000 行时,真的还有行 ⇒ 服务端上限被调低
(把 `page` / `_PAGE["cap"]` 设成本页行数,接着读);没有 ⇒ 读完返回。

`tests/test_read_all_keyset.py` 新增三条(文件已在 `scripts/preflight.sh` 注册,S-244):

| 测试 | 钉住的东西 |
|---|---|
| `test_the_probe_predicate_is_built_from_the_last_row_of_the_page_just_read` | 核对请求的 `or=` 谓词用**本页最后一行**重建(断言到字面量),且不复用上一页的旧游标 |
| `test_a_real_cap_that_is_lower_sets_the_cap_to_the_true_row_count` | 真的还有行 ⇒ `_PAGE["cap"]` = 本页真实行数;请求数与 OFFSET 版**相同**(不多发) |
| `test_the_last_short_page_ends_the_read_without_shrinking_the_cap` | 末页就是最后一批 ⇒ 核对返回空 ⇒ 直接收,`_PAGE["cap"]` **不被改小**,请求数与 OFFSET 版相同 |

`tests/test_read_all_paging.py` 里「服务端上限低于我们以为的」那条**未删未改**。

## 3. 实测(本轮跑的)

```
python3 -m pytest tests/test_read_all_keyset.py -q          → 11 passed
python3 -m pytest tests/test_read_all_keyset.py tests/test_read_all_paging.py -q → 15 passed
```

**回归性(把修复 stash 掉再跑)**:

```
git stash push -- src/data/style/header.py && python3 -m pytest tests/test_read_all_keyset.py -q
→ 2 failed, 9 passed
   FAILED test_the_probe_predicate_is_built_from_the_last_row_of_the_page_just_read
   FAILED test_the_last_short_page_ends_the_read_without_shrinking_the_cap
   E   AssertionError: 上限没变 ⇒ 不许把每页行数改小
   E   assert 1500 == 2000
```

⇒ 这两条是**真护栏**(去掉修复就红),不是陪跑。

线上侧的缺陷证据(**引自 T-418 的请求日志,本轮未重测**):
末页核对带的是**上一页**的游标 `(trade_date.gt.2026-09-19,…)` ⇒ 返回 **1 行** ⇒ 误判「还有行」
⇒ 多发一次 `limit=8296`、**返回 0 行**的取数请求 ⇒ 且把 `_PAGE["cap"]` 写成 **8,296**。
修完之后这一步应当是:谓词换成 `(trade_date.gt.2026-11-19,…)` ⇒ 返回 0 行 ⇒ 直接收,cap 保持 10,000。

## 4. 本轮**没跑**的那一半(③④⑤⑥)—— 脚本已就位,命令如下

本轮上下文守卫在 ~95k token 处拦下了长跑脚本(线上整读单次 ~3.5 分钟 × 若干次),
**没有启动任何线上测量**,因此下面三条**没有新数字**:

* ③ 三组数(main / T-379 / 本分支)背靠背的行数与逐行 sha256 逐字对照;
* ④ 每种形状 ≥3 次取中位数(整读 44 万行 / 同一查询带 `trade_date ≥ 2024-06-20` / `fetch_panel(2025-01-01)`);
* ⑤ 页大小与按键翻页**分栏**(同一条查询在 limit 10,000 与 8,296 下的单页耗时);
* ⑥ 哪些调用点真的上了按键翻页(逐条看请求里有没有 `or=` 谓词)。

**下一轮跑这个**(脚本:`/Volumes/CometCloudAI/cometcloud-local/research/t419/measure.py`;
协议照 T-418 的同一份脚本,计数打在 `_sb_get` 上,逐行 sha256 顺序敏感;每次量之前清空
`_PAGE["cap"]` 让每一跑起始状态一致):

```bash
cd /Volumes/CometCloudAI/cometcloud-local/research/t419 &&
git -C /Users/sbb/Projects/looloomi-ai-lane-a show origin/lane-a/T-379:src/data/style/header.py > header_t379_buggy.py &&
cp /Users/sbb/Projects/looloomi-ai-lane-a/src/data/style/header.py header_fixed.py &&
nohup sh -c 'python3 measure.py --repo /Users/sbb/Projects/looloomi-ai-lane-a --out measure_fixed_t379.json --variants t379=header_t379_buggy.py --reps 3 --shapes 1,2,3 --pagesize && python3 measure.py --repo /Users/sbb/Projects/looloomi-ai --out measure_main.json --reps 3 --shapes 1,2,3 --pagesize' > run.log 2>&1 &
```

预计 25–30 分钟(整读 3 变体 × 3 次 + 轻量档);凭证从进程环境取(`SUPABASE_URL` / `SUPABASE_KEY`),
脚本不读 `.env`、不打印任何 key。⑥ 的调用点清单复用 T-418 的 `research/t379/enum_sites.py`
(AST 抽 `_read_all` 每个调用点的表/select/order,复算 `stable_order` 之后的**生效**排序键),
再加一步「对每个调用点跑 `keyset_plan(table, params)`」即可逐条给出上不上按键翻页与原因。

## 5. T-379 该不该合 —— 结论:**这一条修完,仍然不该原样合**

依据(分开的,不混):

1. **内容这条过了**(T-418):三组数改前改后逐字相同 ⇒ 按键翻页不改内容;本卡的修复只动**核对请求**,
   不动取数请求 ⇒ 内容不该变(待 §4 的重测确认)。
2. **探针缺陷这条现在过了**:有真护栏(去掉修复就红),线上后果明确(多一次请求 + cap 被写成 8,296)。
3. **性能这条还没过**:T-418 量到热路径整读(44 万行、无过滤)在按键版**慢 32%**(164.5s → 217.6s),
   而这**不是探针造成的** —— 探针只影响末页那一次请求(几百毫秒)。
   本卡的修复不会让整读变快。⇒ **按键翻页在热路径整读上目前没有净收益。**
4. **页大小那一栏要单独看**:T-418 量到同一条查询 10,000 单页 ~3.2s vs 8,296 单页 ~0.92s(3.5×),
   而独立连接直打 REST 只有 1.2× ⇒ 那 3.5× 大半**不在按键翻页**上,在连接/计划/缓冲层。
   ⇒ 「按键翻页省了什么」与「页大小省了什么」必须分两栏写,不能互相顶账。

⇒ **建议**:T-379 不要原样合。要么① 只在按键版**确实更快**的形状上开(比如带范围过滤的那档:
T-418 量到 20 页 56.4s → 15.1s,快 3.8×),热路径整读留在 OFFSET 版;要么② 先把热路径慢 32% 的原因查清
(谓词的 `or=` 过滤让 Postgres 每次重算排序/索引扫描?还是连接层?)再合。这需要 @seth 拍板取舍。

## 6. 产物

| 产物 | 路径 |
|---|---|
| 代码 | `src/data/style/header.py`(分支 `lane-a/T-419`) |
| 测试 | `tests/test_read_all_keyset.py`(末三条) |
| 报告 | `docs/research/t419_keyset_probe_fix.md`(本文) |
| 前向预期 | `docs/research/scenarios/lane-a-T-419.json`(5 条机器可核命题) |
| 测量脚本 | `/Volumes/CometCloudAI/cometcloud-local/research/t419/measure.py` |
| 测量结果 | **未生成**(见 §4) |

合规:本文只用 OUTPERFORM/UNDERPERFORM 一类的定位语言,不含任何买卖建议;不下单、不改评分口径。
