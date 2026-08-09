# 全项目 Code Check — 2026-08-09

*Seth。全部数字实测于本日。修的已修,没修的写清楚为什么。*

---

## 0. 一句话

**基础设施是这个项目最强的部分,但今天找到的三个问题都属于同一类:
「写下来的规矩」和「真实生效的东西」之间存在无声的落差。**

三处都不是「忘了做」,而是**做了、返回成功、什么都没发生**。

---

## 1. 🔴 P0-1 安全:匿名角色可以调用 4 个 SECURITY DEFINER 函数

### 事实

```
backfill_binance_hourly(text, bigint, int)     ← anon 可调用
backfill_binance_funding(text, bigint, int)    ← anon 可调用
backfill_daily_for_asset(text, int)            ← anon 可调用
ingest_binance_universe()                      ← anon 可调用
```

`SECURITY DEFINER` = 以属主权限执行,**绕过 RLS**。而 `anon` 按设计就是公开的
(打包进前端,另外还硬编码在 `scripts/external_probe.sh` 里)。所以任何人都可以:

```
POST /rest/v1/rpc/backfill_binance_hourly
{"p_symbol": "<任一 monitor_hourly 资产>", "p_max_batches": 999999}
```

`p_max_batches` 由调用方控制,循环只在它或 now() 处退出 ⇒
**一次未认证调用即可驱动无上限的对外 http_get 和无上限的 INSERT**,
打向一个上周还在 90% 容量的存储层。

**不是**数据泄露(RLS 仍拦读),**不是**删除(anon 无 DELETE;TRUNCATE 虽有 grant
但 PostgREST 不暴露)。**是**干净的未认证资源耗尽路径。

### 根因 —— 值得记住的部分

脚本里**一直写着** revoke,从写下的那天起:

```sql
revoke all on function backfill_binance_hourly(text, bigint, int)
  from anon, authenticated;      -- supabase_ohlcv_hourly.sql:103
```

**但这个权限从来不属于 `anon`。** `CREATE FUNCTION` 默认把 EXECUTE 授给 `PUBLIC`,
`anon` 只是**继承**。从一个从未被直接授权的角色手里 revoke,
**是一次成功的空操作** —— 无报错、无警告、无行数,而脚本读起来像是门锁上了。

ACL 才是真相:

```
锁住的   {postgres=X/postgres, service_role=X/postgres}
没锁的   {=X/postgres,  postgres=X/postgres, service_role=X/postgres}
          ↑ 空 grantee 就是 PUBLIC
```

**正确写法本仓库里已经有一处** —— `supabase_refresh_signal_track_record_v2.sql`
写的是 `from public`,而那个函数**恰恰是唯一真正锁住的**。同一个作者、同一周、
两种写法并存,而文本上看不出任何区别。

### 已做

- `scripts/supabase_revoke_public_execute.sql`(**待 Jazz 在 Supabase 控制台执行**)
- 3 个脚本的 revoke 改为 `from public, anon, authenticated`
- 另外 4 个 SECURITY DEFINER 函数(线上已手工锁住,但**脚本里没有**⇒ 重建即漏)补上 revoke
- `tests/test_sql_privilege_idiom.py` 4/4 进 preflight

### 守卫的边界(明说)

**它读脚本,所以只能证明写法对,永远不能证明数据库对。**
线上校验写在 SQL 头部,属于定时探针,不属于离线门禁。**脚本不是授权。**

---

## 2. 🔴 P0-2 合规:9 处用户可见的交易性措辞(hard rule #1)

无 SFC Type 4/9 牌照 ⇒ 用户可见面只能用**定位语言**。此前**没有任何东西在检查这条**。

| 文件 | 原文 |
|---|---|
| `macro.py` | "Avoid high-beta altcoins." |
| `cis.py` | "Avoid over-leveraged protocols." |
| `signals.py` | "avoid shorts" · "not a buy list" ×2 · "trim gross long" · "reduce conviction sizing" |
| `market.py` | "Avoid chasing parabolic moves" · "Avoid FOMO entry" · "Avoid chasing" · "Avoid catching falling knives" · "Signal: trim position" |
| `portfolio_diagnosis.py` | `"action": "trim"` · `"bucket": "trim"` · "Trim {sym}" |
| `CISCompare.jsx` | "avoid over-leveraged protocols" |

### 它们的共同点,才是真正的发现

**每一条都是「谨慎措辞」。** "Avoid chasing"、"not a buy list"、"trim position" ——
写的时候是想表达克制,**而这正是它们通过人工审阅的原因**。
**对同事表达审慎的词,和监管眼里构成建议的词,是同一批词。**
⇒ 这件事不能靠判断力,只能靠机器检查。

### 已做

全部替换为定位语言(`UNDERWEIGHT` / `disfavored` / `screens as`),
`tests/test_compliance_language.py` 3/3 进 preflight。
**方法论页仍可以把禁用词划掉展示** —— 分不清「使用」和「提及」的守卫,
会逼我们停止记录自己的政策。

---

## 3. 🟡 P0-3 门禁:preflight 在干净环境里跑到一半就中止

21 个测试文件用 stdlib 自运行,**3 个用 pytest**。`set -euo pipefail` ⇒
`test_venue_consolidation` 一 import 失败,**后面 5 个套件 + 契约回显全部没跑**,
而且没有任何迹象表明它们没跑。

**这是最危险的形状:门禁失效时看起来像门禁通过。**

已加 `[0/3] 依赖检查`:缺 pytest 就**在最前面明确失败并给出修复命令**,
而不是在中间含糊地中止。修好后全量跑通:**23 个套件全绿。**

---

## 4. 数据点(无需行动,但该知道)

| 指标 | 值 |
|---|---|
| 跟踪文件 | 901 |
| Python/JS LOC | ~148,600 |
| 最大文件 | `data_layer.py` 3,608 行 · `cis.py` 3,341 · `cometcloud_mcp.py` 2,909 |
| **从未被 import 的 src 模块** | **139 / 356(39%)** —— 绝大多数在 `src/research/`,属正常(研究脚本独立运行) |
| RLS 关闭的表 | 1(`risk_meter_history`)—— 已在迁移脚本中开启 |
| RLS 开启但无策略的表 | ~30 —— **这是正确的**,默认拒绝 |

**3,000+ 行的单文件是真实的技术债**,但今天不动:拆分风险高于收益,
且没有任何一个当前故障归因于文件长度。**记录,不行动。**

---

## 5. 今天的三个发现是同一个形状

| 场合 | 报告成功 | 实际发生 |
|---|---|---|
| S-105 | 策略落库写入 | 进了 24h TTL 的 Redis |
| S-116 | ③ 层映射 | 词表根本不匹配 |
| S-122 | 默认值填充 | 抹掉了自己的证据 |
| **今天 P0-1** | **revoke 执行成功** | **权限一点没变** |
| **今天 P0-2** | **代码审阅通过** | **审慎措辞 = 违规措辞** |
| **今天 P0-3** | **preflight 打印通过** | **一半的检查没跑** |

**Lesson #107 —— 「操作成功」和「状态改变」是两件独立的事,必须分别验证。**
判据:**不要检查你的动作是否执行,检查目标是否改变。**
`revoke` 返回成功 → 查 ACL;测试打印绿色 → 查跑了几个;写入返回 200 → 查表里有没有。

---

## 6. 未修,且我认为不该现在修

1. **`trading.py:1160`** `REGIME_FACTOR.get(..., 0.80)` —— S-122 同类,
   但兜底不在 dict 值位、0.80 不在中性值集合 ⇒ 扫描器形状够不着。**已在 task #30。**
2. **`external_probe.sh` 硬编码 anon key** —— anon 本就公开,RLS 收紧后风险可接受;
   但**它给了攻击者一个现成的 key,省去了扒前端包的一步**。建议改读环境变量。
3. **139 个孤儿模块** —— 研究代码本就该是孤儿。**不清理,清理会误删台账资产。**

---

*重评前重跑:`bash scripts/preflight.sh` 与本文 §1 的 `pg_proc.proacl` 查询。*
