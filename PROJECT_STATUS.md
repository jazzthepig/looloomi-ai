# CometCloud AI / Looloomi — 项目真实状态
**更新日期：2026-03-23**

---

## 能跑的

### 平台基础
- **Railway 部署正常**：`app.html` 是主入口，5 个 tab（Asset Prices / Intelligence / CIS / Protocol / Vault），vision landing page + strategy landing page 独立
- **FastAPI 后端**：`main.py` 已拆分为 6 个 router（market / cis / intelligence / agent / backtest / internal），无重复注册（今日修复）
- **GitHub → Railway 自动部署**：push main 触发，通常 2 分钟内生效

### CIS 评分体系
- **CIS v4.0**：5 pillar（F/M/O/S/A），百分位制打分，letter grade（A+ → F），7 个信号（STRONG BUY → STRONG AVOID）
- **覆盖资产**：crypto + TradFi（US Equity / Bond / Commodity）
- **Railway fallback 引擎**：`cis_provider.py`，CoinGecko + DeFiLlama + Alternative.me，评分实时可用
- **Mac Mini 本地引擎**（Minimax 操作）：`cis_v4_engine.py`，8 个资产类别，6 个宏观 regime，regime-aware pillar 权重，DeFiLlama 真实 TVL，推送到 Redis 每 ~30 分钟一次
- **Redis 桥**（Upstash）：Mac Mini 分数持久化到 `cis:local_scores`，2h TTL，Railway deploy 不丢数据。前端绿色 badge "CIS PRO · LOCAL ENGINE" vs 琥珀色 "CIS MARKET · ESTIMATED"
- **CIS Leaderboard**：top 20 展示 + "显示更多"，sparklines 7d 趋势，methodology banner，百分位说明
- **CIS Widget**（Intelligence 页嵌入）：同步 sparkline

### 数据架构
- **Redis L2 缓存层**：
  - `get_defi_protocols_curated`：1800s Redis
  - `get_defi_overview`：300s Redis，含 `defi_change_24h` / `l2_tvl` / `rwa_tvl` 字段
  - `get_top_yields`：600s Redis
  - `get_fear_greed`：3600s Redis
  - 内存 L1 → Redis L2 → API 三层，Railway worker 间共享，deploy 不丢
  - Redis 连接池修复（今日）：`_redis_get/_redis_set` 改为共享 `AsyncClient`，不再每次创建新连接
- **MacroPulse 后端代理**：`/api/v1/market/macro-pulse`，并发拉 CG global + FNG + BTC price，300s Redis，浏览器不再直接调外部 API
- **CoinGecko Pro 代理**：`/api/v1/market/coingecko-markets`，server-side Pro key，AssetRadar 走后端避开浏览器 30 req/min 限制

### 前端页面
- **Asset Prices tab**（MarketDashboard）：MacroPulse regime banner + macro metrics，AssetRadar，Signal Feed，MMI，Gas，VC Funding
- **Intelligence tab**（IntelligencePage）：MacroBrief，Protocol Intelligence，Sector Heatmap，Macro Events（今日：移除 hardcoded fallback，API 无数据时显示空状态）
- **CIS tab**：CISLeaderboard 完整功能
- **Protocol tab**：ProtocolIntelligence，CIS scored + DeFiLlama live TVL
- **Vault tab**：VaultPage，今日移除 EST_ALPHA_FALLBACK 和 PLACEHOLDER_GP mock data，API 失败时显示真实空状态
- **MacroPulse**：今日修复 FNG null 处理，FNG 不可用时显示 "—" 而不是默默 fallback 到 50
- **vision.html**：Landing page，含 Strategy 链接
- **strategy.html**：独立投资者 Demo 页面，7 个 section，live 数据（macro-pulse + CIS universe + protocols）

### Asset Radar（今日重写）
- **资产宇宙精简**：36 → 14 个，按"链上数据可验证的前三龙头"标准保留
  - L1: BTC / ETH / SOL（生态 TVL 前三）
  - L2: ARB / OP / POL（L2 TVL 前三）
  - DeFi: LDO / AAVE / UNI（协议 TVL 前三）
  - Infra: LINK / TIA / ENA（Oracle/DA/合成美元各类第一）
  - RWA: ONDO（代币化国债 AUM 第一）
  - Meme: DOGE（市值第一，Meme 无 TVL 标准，单条）
- **Signal 逻辑修复**：弃用 `change7d + FNG` 计算的 OVERBOUGHT/OVERSOLD/NEUTRAL，改为直接使用 CIS API 返回的真实信号（STRONG BUY / BUY / HOLD / REDUCE / AVOID）
- **Category filter 修复**：Filter 和实际 category 字段完全对齐（原 "Oracle" filter 匹配不到任何资产）
- **Sort 功能**：Mkt Cap / 24H / 7D / CIS / Volume 五维度排序，升降序切换
- **CIS 列**：score 数值 + grade badge 同时显示
- **Double useEffect 修复**：mount 时两个 useEffect 都调 `loadData()` 导致 double fetch，合并为单一 useEffect
- **ENA 加入 CIS backend**：`cis_provider.py` CRYPTO_ASSETS 补充 Ethena

### AI 与 Agent 层
- **MacroBrief 流水线**：Mac Mini → LM Studio（Qwen3 35B）→ `generate_report.py` → POST `/api/v1/macro/brief` → Redis → 前端；cron 每天 08:00 / 20:00 运行，前端 auto-refresh 10min
- **Agent JSON API**：`/api/v1/agent/cis`，标准化 schema
- **WebSocket**：`/ws/cis`，Mac Mini push 时实时广播
- **Signal Feed v2**：7 个并发信号源，compliance-safe 语言

### 基础设施
- **Freqtrade**：安装完成，Signal API 4 端点跑通，CometCloudStrategy 路径更新，start script 就位。dry run **未启动**
- **Auth 加固**：CORS preflight，WebSocket leak 修复，token reject-by-default
- **Mobile/H5**：响应式适配完成

---

## 有问题的

### 核心问题

**CIS 评分区分度不足**
Railway fallback 引擎打分严重集中在 B/B+，A+/A 基本为零。根因：pillar 权重固定，无 regime 感知；CoinGecko Railway 侧可能 429 导致 pillar 拿默认值。Mac Mini 本地引擎有 regime-aware 权重，分布理论上更合理，但未系统验证。**无区分度的评级 = 无意义**，是当前最大未解问题。

**Supabase 分数历史未接入**
代码写好了（`supabase_insert_batch` / `supabase_get_history`，含 retry），但 `SUPABASE_URL` + `SUPABASE_KEY` 未配置到 Railway 环境变量，所有写入静默跳过。分数历史为零，sparkline 靠当前打点，无历史趋势。

**CoinGecko Pro key 状态不明**
`COINGECKO_API_KEY` 是否写入 Railway env 未确认。为空则 Railway 走 free tier，可能 429，MacroPulse 宏观数据降级。

**回测无数据**
`/api/v1/backtest/*` 端点存在，但没有跑过系统性回测。无 CIS grade 与 forward return 相关性历史证据，对机构 LP 是硬伤。

### 已知小问题

- **MacroBrief 空窗期**：cron 2次/天，非运行时段前端显示 "Awaiting next scheduled run"。手动触发：`cd /Volumes/CometCloudAI/freqtrade/macro_analysis && python3 generate_report.py`
- **ProtocolPage.jsx**：文件还在 codebase，已无挂载点，死代码
- **MACRO_EVENTS 常量**：IntelligencePage.jsx 里的硬编码 events 常量还在文件中（dead code），Minimax next batch 清除
- **Agent API `conf` 字段**：confidence score 固定常量 0.83，非真实计算
- **TradFi 资产 CIS**：Binance 在 Railway geo-block，A pillar 走 SPY divergence，实际路径未完全验证

---

## 还没做的

### 近期（Week 3–4，Mar 24+）

**Minimax next batch（今日已交付的 next batch 指令）：**
- [ ] `cis_scheduler.py`：Binance 失败时 skip 资产，不用 `np.random.randn()`
- [ ] `cis_provider.py`：`time.sleep(0.2)` → `await asyncio.sleep(0.2)`
- [ ] `cis.py`：error `return dict` → `raise HTTPException(500)`
- [ ] `IntelligencePage.jsx`：删 MACRO_EVENTS 常量（dead code）

**Jazz action items：**
- [ ] Supabase URL + Key → Railway env vars + 发给 Minimax（他没有昨天的记忆）
- [ ] CoinGecko Pro key → 确认 `COINGECKO_API_KEY` 在 Railway env 中存在非空，同步给 Minimax

**Minimax blockers：**
- [ ] Freqtrade dry run：`git pull` + `bash scripts/start_dry_run.sh`

**Seth/Austin：**
- [ ] Nic demo review + polish（strategy.html 已就绪，走一遍内容完整性）
- [ ] CIS 评分区分度修复：Railway fallback 引擎的 regime-aware 权重，或至少扩大 percentile 分布范围
- [ ] Freqtrade P&L widget（dry run 启动后接入 dashboard）

### 中期（4–6 周）

- **用户认证 + 钱包连接**：Supabase Auth + Solana wallet adapter，约 3–4 天（等 Supabase 配好后启动）
- **CIS 回测验证**：历史 Binance klines 验证 CIS grade 与 forward return 相关性
- **分数历史分析**：grade migration，sector rotation signal（依赖 Supabase 先有数据）
- **Portfolio allocation engine v1**：基于 `cis_score` + `recommended_weight` 生成组合建议
- **MCP Server**：外部 AI agent 消费 CIS API，Agent Card `/.well-known/agent.json`
- **Event Intelligence System**：事件驱动情报，链上大额转账/协议升级/监管动态触发评分重算

### 长期 / 未排期

- Telegram bot：社区信号推送，订阅 CIS 变动
- GitHub 开源 CIS 方法论 repo：公信力建设
- CometCloudStrategy.py：Freqtrade 完整闭环，需 dry run 数据先验证
- Solana 链上 Fund-of-Funds：OSL stablecoin 计价，链上 LP 模块

---

## 依赖项（当前 blockers）

| 事项 | Owner | 状态 |
|------|-------|------|
| Supabase URL + Key → Railway env | Jazz | ❌ 未做 |
| Supabase credentials → 同步给 Minimax | Jazz | ❌ 未做（Minimax 无昨日上下文）|
| CoinGecko Pro API Key → 确认 Railway env | Jazz | ❓ 未确认 |
| Freqtrade dry run `git pull` + start | Minimax | ❌ 未做 |
| Minimax next batch（4 项小修）| Minimax | 🔄 进行中 |

---

*不美化。能用的就是能用的，有问题的就是有问题的。*
