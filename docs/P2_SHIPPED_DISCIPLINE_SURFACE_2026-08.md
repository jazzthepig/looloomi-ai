# §P2 — Shipped Discipline Surface — 2026-08-08

*Seth. Per OVERSIGHT_2026-08.md §3 P2 ("把资产讲对 — 把证伪装置做差异化主张"):
the LP-facing narrative (§6) MUST NOT invent claims. This document is the precise,
test-name-level inventory of what §P2 has actually been compiled into, so §6 can cite
without invention. All counts measured today by `bash scripts/preflight.sh`.*

> **P2 status (verbatim from OVERSIGHT §7.3, 2026-08-08):** 部分进行中 —
> 已在 CI 中(DSR/PBO + 可执行性 + neutralize() + 锚点判据 + 事件计数 + L0 身份守卫);
> 对外材料对齐等 LP-facing 文档更新待 Jazz 决策。

---

## 0. How to read this

§P2 的差异化主张只有一条: **"证伪装置本身是产品"**(ARCHITECTURE.md)。
要让 LP 接受这条主张,§6 narrative 必须能指向具体代码、具体测试、
具体运行中的 paper book。**这张表就是那些具体东西的总览。**

| Section | What it inventories | Why it matters for §P2 |
|---|---|---|
| §1 | The CI enforcement layer | Every "纪律编译进了 CI" 的具体断言 |
| §2 | The paper-book accruing record | "60 天前向" 门槛的当前进度 |
| §3 | The production contract surfaces | Mac↔Railway 不漂移、RLS、breaker 等 |
| §4 | The honest gap | §P2 还没覆盖什么(防 over-claim) |

---

## 1. CI enforcement layer

**全部 14 个 category,121+ 断言。** `bash scripts/preflight.sh` 在 push 前是 Hard Rule #5
强制闸门 —— 任何一条红都不会到 origin。

| # | Category | Test count | What it guards | Anchor |
|---|---|---:|---|---|
| 1 | py_compile all `src/**/*.py` | syntax | 语法层守门(但 import-time 不够 — 见 #2) | Hard Rule #5 |
| 2 | import + boot smoke (`scripts/smoke_test.py`) | runtime | **真生产闸门** — py_compile 通过但缺 `Response` 仍会 502(2026-07-13) | Hard Rule #5 |
| 3a | `test_strategy_discipline` | **13** | SHIP 必须有 cause / OOS / ≥60d paper / regime evidence / multiple-testing floor / executability floor | CLAUDE.md "CI not prose" |
| 3a-bis | `test_supabase_breaker` | **7** | 2026-07-29 P0: Supabase saturation → 33s 挂起 → 重试风暴同时 `/health` 撒谎"healthy"。Guard: 不重试 timeout / 熔断打开 / 失败快 / 冷却后恢复 / 4xx 不触发 / health 反映真态 | S-92 |
| 3a-bis-2 | `test_cis_universe_lock` | **7** | Universe 端点的 build-phase 锁(避免 stale 服务 + 超时返回 200 的双错) | S-95 |
| 3a-bis-3 | `test_t2_fanout_bounds` | **7** | 2026-08-07 S-104: 单条慢装饰分支(25 coin × 4 sem × 15s)拖死 9 条已成功分支。Guard: per-branch 超时 / 失败上报不吞 / negative-cache 不自我致残 | S-104 |
| 3a-ter | `test_cold_start_contract` | **6** | Amnesia path(AMNESIA_PROTOCOL.md): PROJECT_STATE.md 首段必须是 `## OPEN RISKS` / 每个 item 有 `VERIFY:` + `OWNER:` / ≤7 项 / MEMORY.md 不超 cap | Lesson #92 |
| 3a-quater | `test_no_undefined_names` | **2** | 服务路径上无未定义名(NameError 在冷分支只 log warning 时静默杀进程 —— 2026-08-06 T2 universe fallback 死亡案) | S-95 |
| 3a-quinquies | `test_neutralize` | **5** | 2026-08-07 S-103: `neutralize()` 在 71 个文件里被引用、0 处定义。Guard 双向:纯 β 必须中性到零 + 真 α 必须存活(避免一个把一切都剥掉的"中性器") | S-103 / Lesson #83 |
| 3a-sexies | `test_strategy_durability` | **4** | 2026-08-07 S-105: 研究 graveyard 的 24h-TTL Redis 备用路径跑了 12 天(因为 Postgres migration 写了但没 apply)。Guard: fallback **被计数**而非仅 log / 一次失败即 degraded | S-105 / Lesson #85 |
| 3a-septies | `test_data_architecture` | **4** | 2026-08-07 L0: `asset_class` 住在 observation 行上 = 实际记录的是数据源(>1% open gap Crypto 31.3% vs DeFi 83.5%)。Guard: 架构契约可验证 / L0 migration 已 check-in / 不再有 `where asset_class=...` 过滤观测 / observation 写时不带 asset_class | S-106 |
| 3a-octies-2 | `test_beta_core_book` | **8 + 18** | 2026-08-07 OVERSIGHT 复审: 五本 forward book 全 L/S、④ 层、产出 R76–R94 graveyard,而 ①层(产品本体 + 每本书基准)零 forward。Guard: long-only / 暴露 [0,1.3] / vol scalar 去杠杆自由但永不加杠杆 / 未测输入走中性不放大 / 基准腿是结构性的(超额是算术,不是事后挑的) / lost cache 不重置钟 / stalled clock 可被外部观测 | OVERSIGHT §3 P0 #1 |
| 3a-quater¹ | `test_venue_consolidation` | **18** | 2026-08-01 S-92: HYPE → Binance spot HYPERUSDT 错指 Hyperlane($0.0558 vs Hyperliquid $52.32,937×),全 completeness 检查都绿但 D/UNDERWEIGHT 标在 +256% 涨势上的资产。Guard: 错指 mapping 被拒 / 不臆造 / 注册表显式 | S-92 / Lesson #80 |
| 3a-quinquies¹ | `test_cis_drift_detector` | **11** | 2026-07-30 HYPE 案: 纯检测逻辑必须 regression-safe;live Supabase probe 在 cron 路径(offline-only) | S-92 |
| 3a-sexies¹ | `test_regime_override_enforcer` | **23** | 2026-08-06 ⓠ enforcer: 把研究侧 `assign_band_hysteresis` 包成生产 API, PIT-safe, 只允许 v1 caps {0.0, 0.5, 1.0, 1.3}, 拒绝 naked short | S-106 reframe |
| 3a-septies¹ | `test_fusion_paper_regime_track` | **16** | 2026-08-06 ⓠ paper track: 纯回测 / 聚合逻辑;live paper 在 `daily_runner.py` post-validation(60d forward paper) | S-106 reframe |
| 3a-octies¹ | `test_build_l1_observations_smoke` | **6** | 2026-08-07 Lesson #72 follow-up: `--diagnose` 验证 live Supabase key(2026-08-02 伪造 key 类)。Pin 脚本形状(imports / constants / `resolve_panel_source('none')` / `compute_panel_series` / `diagnose()` 契约)防止结构回归;网络 probe 在 cron | S-103 |
| 3b | contract schema echo | inline | cis_push `SCHEMA_VERSION=1.0` · vector schema v2 (27-dim) — 每次 preflight 必 echo,防 Mac push schema 改而 Railway 没跟(2026-07 漂移类) | §2.2 |

> **14 个 category,121 个具名断言 + 18 venue sub-checks + 语法/runtime/contract 三个外部闸门。**
> 任何"纪律被编译进 CI"的 LP-facing 表述都可以指向这张表里的具体行。

---

## 2. Paper-book accruing record

**5 本 active book + ①层 + §P3 平行 prototype = 7 个 forward-clock 在跑。**
但今天只有 **①层 beta_core_paper** 是"为 SHIP 累计"的产品本体(2026-10-初 满 60 天),
其余 6 个里 3 个是研究记录(demoted),2 个是非 L/S 候选,1 个是 prototype。

| Book | Days¹ | Inception | Construction | Status | Source of truth |
|---|---:|---|---|---|---|
| **① beta_core_paper_nav** | **1+** | 2026-08-08 | equal-weight · vol-target · ⓠ regime cap ∈ {0,0.5,1,1.3} · long-only · benchmark-nav 同行标记 | 🟢 **PRODUCT — forward-clock** | Supabase `beta_core_nav` |
| causal_paper_nav | **~26** | 2026-07-13 | L/S · gross ≈ 1.0 | 🟡 DEMOTED 2026-08-08(OVERSIGHT §3 P0 #2) — 循环继续,graveyard 是资产 | Supabase `causal_paper_nav` |
| combined_book_nav | ~24 | 2026-07-15 | L/S · 4-signal factory nucleus blend | 🟡 DEMOTED 2026-08-08 — 工厂核自我重校准验证用途 | Supabase `combined_book_nav` |
| scalable_book_nav | ~23 | 2026-07-16 | L/S · 3-sleeve FACTOR/TREND/CARRY | � DEMOTED 2026-08-08 — TREND 容量数据留给将来 DIRECTIONAL sleeve 复用 | Supabase `scalable_book_nav` |
| dingge_paper_nav | ~24 | 2026-07-15 | RWA volume-gated · 非 L/S | 🟢 **NOT touched**(per OVERSIGHT §7.2) | Supabase `dingge_paper_nav` |
| two_layer_paper_nav | ~17 | 2026-07-22 | 两层架构 · 非 L/S(§5b 设计) | 🟢 **NOT touched**(per OVERSIGHT §7.2) | Supabase `two_layer_paper_nav` |
| /src/research/paper_books/* | varies | 2026-07 | 60d forward paper prototype(vol_carry / regime_nowcast / macro_overlay) | � INDEPENDENT(独立 prototype,OVERSIGHT 不涉及) | Supabase `*_paper_nav` |

¹Days = 距 2026-08-08 的日历天数;具体值 Mac 侧 `select max(mark_date), count(*) from {book}` 探针为准。

> **§P2 LP-facing 可引用的数字:**
> · ①层 60 天前向 — 最早 **2026-10-初**(calendar-bound,不加速);
> · 当前 1 天 = "已开始,远未满 60 天" — 不能 claim "60 天前向曲线"。

---

## 3. Production contract surfaces

| Surface | Today's state | What guards it |
|---|---|---|
| cis_push contract | `SCHEMA_VERSION=1.0` | preflight 3b 每次必 echo;`src/api/contracts/cis_push.py` 是 canonical |
| Vector schema | v2 (`ASSET_DIMS_V2 = 27`) | preflight 3b 每次必 echo;Mac ↔ Railway 协议 |
| RLS | 7 张表已 RLS | S-92 事件后清理;4 条 `USING(true)` 隐藏路径已删 |
| `/internal/cis-scores` auth | `X-Internal-Token` header | preflight smoke + breaker test |
| Supabase breaker | open / half-open / closed / degraded 状态可观测 | `test_supabase_breaker` 7 项 |
| `/health` 端点 | **观测数据层**,503 而非绿勾(2026-07-29 后) | `test_breaker_fails_fast` + `test_health_reports_degraded_when_breaker_open` |
| 外部探测 | 3h 轮询(probe) | `scripts/external_probe.sh` |
| ⓠ caps | `{0.0, 0.5, 1.0, 1.3}` | `test_regime_override_rejects_cap_outside_allowed_set` + naked short disabled |
| ①层暴露 | long-only · gross ≤ 1.3 | `test_layer_one_is_equal_weight_and_long_only` + `test_exposure_caps_are_discrete_and_within_the_mandate` |

---

## 4. Honest gap — what §P2 has NOT yet shipped

OVERSIGHT §3 P2 是 "部分进行中" 不是 "已完成"。以下清单是
**§P2 不可对外 claim** 的边界,防止 LP-facing narrative 过度延伸:

| Gap | Why it matters | Why it's not shipped |
|---|---|---|
| `decisions` 0 行 · `entities` 1 行 | ARCHITECTURE.md 主张"最深对象是 Entity/Decision";数据层零体现 | COMPLETENESS §0 给了 F 评级;接上 or 降级是 Jazz 判断题 |
| `asset_embeddings_history` 0 行 · `risk_meter_history` 0 行 | ⓠ 层回测与决策链需要这两张表 | 任务 #253/#261 等 service_role key 解除(OPEN RISK #1) |
| LP-facing 文本措辞 | OVERSIGHT §6 那段 "我们做 AI 策展的加密 FoF" 等 | **Jazz-decision pending per OVERSIGHT §7.3** —— 这份文档是 source-of-truth,文案不动 |
| 0 / 8 策略通过 `oos_survival=True` | CLAUDE.md 自己的门槛 | R76–R94 graveyard + S-105 executability floor 是为什么 |
| ≥60 天 paper for any non-① book | 同上 | ①层是唯一 calendar-bound 已开始 |
| "强度而非方向"假说验证 | COMPLETENESS §1 P0-1 项,可能让 +7.99 消失 | event-counted 重算未完成 |
| UNDERWEIGHT 底部反转 | COMPLETENESS §1 P0-3 项 | 待解释(可能捕捉超跌反弹)或收窄到三档 |

---

## 5. Source-of-truth chain (so §6 can cite, not invent)

当 §6 LP-facing narrative 写下述任何一句,**精确指针**如下:

| Claim | Cite this |
|---|---|
| "我们把证伪装置编译进 CI" | §1 表 — 14 category · 121+ 具名断言 · preflight 是 Hard Rule #5 |
| "X 次被自己的测量推翻" | REFUTATION_LEDGER.md(R76–R94 + S-1→S-100+)· 完整可审计 |
| "60 天前向门槛" | test_strategy_discipline: `test_executability_floor_is_enforced` + `test_ship_records_carry_the_evidence_floor` |
| "中性化是单位换算" | S-103 + test_neutralize: `test_pure_beta_neutralises_to_zero` + `test_real_alpha_survives_neutralisation` |
| "执行性先于回报" | S-105 + test_strategy_durability: `test_a_single_failure_is_already_degraded` |
| "事件计数先于 t-stat" | COMPLETENESS §1 ⚠️ 框 + Lesson #81(从均值日加权 → 独立事件 gap>7d) |
| "产品本体 = ①层 hold-the-panel" | OVERSIGHT §0 + §3 + §7.1 + test_beta_core_book(8 项 + venue 18) |
| "calendar-bound,不能加速" | OVERSIGHT §3 P0 理由 + ①层 2026-10-初 满 60 天 |
| "L0 数据架构不再让 asset_class 住在观测行" | test_data_architecture(4 项)+ S-106 重构 |
| "Mac�Railway 不漂移" | cis_push `SCHEMA_VERSION=1.0` + vector v2 (27-dim) — preflight 每次 echo |

---

*本文档只写实测数字 + 实测测试名 + 实测 commit 引用。
下次重评前重跑 §1(preflight)+ §2(Mac 侧 paper NAV probe)+ §3(echo 数字),不要凭本文更新。*

---

**Last verified:** 2026-08-08 · bash scripts/preflight.sh → PREFLIGHT PASSED · 14 categories · 121+ named assertions · `b5f32b2` on origin
