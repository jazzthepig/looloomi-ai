# CometCloud AI / Looloomi — 项目真实状态
**更新日期：2026-03-22**

---

## 能跑的

### 平台基础
- **Railway 部署正常**：`app.html` 是主入口，5 个 tab（Asset Prices / Intelligence / CIS / Protocol / Vault），vision landing page 独立
- **FastAPI 后端**：`main.py` 已拆分为 6 个 router（market / cis / intelligence / agent / backtest / internal），共约 1000+ 行，结构清晰
- **GitHub → Railway 自动部署**：push main 触发，通常 2 分钟内生效

### CIS 评分体系
- **CIS v4.0**：5 pillar（F/M/O/S/A），百分位制打分，letter grade（A+ → F），7 个信号（STRONG BUY → STRONG AVOID）
- **覆盖资产**：37 个 crypto + 3 类 TradFi（US Equity / Bond / Commodity），共 40 个资产
- **Railway fallback 引擎**：`cis_provider.py`，CoinGecko + DeFiLlama + Alternative.me，评分实时可用
- **Mac Mini 本地引擎**（Minimax 操作）：`cis_v4_engine.py`，8 个资产类别，6 个宏观 regime（RISK_ON/OFF/TIGHTENING/EASING/STAGFLATION/GOLDILOCKS），regime-aware pillar 权重，DeFiLlama 真实 TVL，推送到 Redis 每 ~30 分钟一次
- **Redis 桥**（Upstash）：Mac Mini 分数持久化到 `cis:local_scores`，2h TTL，Railway deploy 不丢数据。前端绿色 badge "CIS PRO · LOCAL ENGINE" vs 琥珀色 "CIS MARKET · ESTIMATED"
- **CIS Leaderboard**：top 20 展示 + "显示更多"，sparklines 7d 趋势，methodology banner，百分位说明
- **CIS Widget**（Intelligence 页嵌入）：同步 sparkline

### 数据架构
- **Redis L2 缓存层**（本 session 新增）：
  - `get_defi_protocols_curated`：1800s Redis（原 300s 内存）
  - `get_defi_overview`：300s Redis，新增 `defi_change_24h` / `l2_tvl` / `rwa_tvl` 字段
  - `get_top_yields`：600s Redis
  - `get_fear_greed`：3600s Redis
  - 所有上述函数：内存 L1 → Redis L2 → API 三层，Railway worker 间共享，deploy 不丢
- **MacroPulse 后端代理**（本 session 新增）：`/api/v1/market/macro-pulse`，并发拉 CG global + FNG + BTC price，300s Redis，浏览器不再直接调外部 API
- **CoinGecko Pro 代理**：`/api/v1/market/coingecko-markets`，server-side Pro key，AssetRadar 走后端避开浏览器 30 req/min 限制

### 前端页面
- **Asset Prices tab**（MarketDashboard）：MacroPulse regime banner + macro metrics，AssetRadar 资产价格列表，Signal Feed，MMI，Gas，VC Funding
- **Intelligence tab**（IntelligencePage）：MacroBrief，Protocol Intelligence，Sector Heatmap，Macro Events，VC Funding
- **CIS tab**：CISLeaderboard 完整功能
- **Protocol tab**（本 session）：已用 ProtocolIntelligence 替换原 ProtocolPage，CIS scored + DeFiLlama live TVL，按类别/排序筛选，row 展开 pillar 详情，30min Redis 缓存
- **视觉系统**：James Turrell × ONDO，void black `#020208`，ambient orbs，Space Grotesk / Exo 2 / JetBrains Mono，institutional grade

### AI 与 Agent 层
- **MacroBrief 流水线**：Mac Mini → LM Studio（Qwen3 32B）→ `generate_report.py` → POST `/api/v1/macro/brief` → Redis → 前端；cron 每天 08:00 / 20:00 运行，前端 auto-refresh 10min
- **Agent JSON API**：`/api/v1/agent/cis`，标准化 schema（s/g/sc/sg/f/m/r/ss/a/ch30d/ch7d/vol/mc/vol24h/tvl/conf）
- **WebSocket**：`/ws/cis`，Mac Mini push 时实时广播到所有订阅者
- **Signal Feed v2**：7 个并发信号源，compliance-safe 语言，未知 time_horizon 不再渲染乱码 badge

### 基础设施
- **Freqtrade**：安装完成，Signal API 4 端点跑通，`CometCloudStrategy` 路径已更新，start script 就位，CIS cache writer 准备好。dry run **未启动**（等 Minimax git pull）
- **Auth 加固**：CORS preflight，WebSocket leak 修复，token reject-by-default，`/internal/cis-scores` X-Internal-Token 验证
- **Mobile/H5**：响应式适配完成，底部导航，BottomSheet，touch targets

---

## 有问题的

### 核心问题

**CIS 评分区分度不足**
当前 Railway fallback 引擎打出来的分布严重集中在 B/B+，A+/A 为零。根本原因：pillar 权重是固定的，没有 regime 感知；CoinGecko 数据 30 req/min 在 Railway 侧也会触发限速，部分 pillar 拿到默认值。Mac Mini 本地引擎有 regime-aware 权重，理论上分布更合理，但需要验证。**没有区分度的评级 = 无意义**，这是最大的未解问题。

**Supabase 分数历史未接入**
代码写好了（`supabase_insert_batch` / `supabase_get_history`，含 exponential backoff），但 Jazz 没有提供 `SUPABASE_URL` + `SUPABASE_KEY` 到 Railway 环境变量，所有写入静默跳过。分数历史为零，sparkline 靠的是当前打点不是历史数据。

**CoinGecko 限速**
Railway 后端目前是 `pro-api.coingecko.com` 但 API key 是否配置未确认。如果 `COINGECKO_API_KEY` 为空，`get_cg_global()` 直接返回 `{"error": "not set"}`，MacroPulse 宏观数据 fallback 到 free tier，可能 429。

**回测无数据**
`/api/v1/backtest/*` 端点存在，但没有跑过系统性回测。没有任何历史证据表明 CIS 分数和资产表现之间存在相关性。对机构 LP 来说这是硬伤。

### 已知小问题

- **MacroBrief 空窗期**：cron 2次/天，非运行时间段前端显示 "Awaiting next scheduled run"，视觉上像 bug。手动触发：`cd /Volumes/CometCloudAI/freqtrade/macro_analysis && python3 generate_report.py`
- **ProtocolPage.jsx**：文件还在 codebase，已无挂载点，死代码
- **IntelligencePage sectorData**：`defi_change_24h` / `l2_tvl` 字段现在后端已有，但前端 fallback 硬编码数字（$95.7B 等）还没清掉，需要确认字段名对齐后删
- **Agent API `conf` 字段**：confidence score 是固定常量 0.83，不是真实计算
- **TradFi 资产 CIS**：US Equity / Bond / Commodity 评分逻辑里 Binance 数据被 Railway geo-block，S pillar 用 VIX 替代，A pillar 用 SPY divergence，但实际数据拉取路径未完全验证

---

## 还没做的

### 近期（Week 3，Mar 24+）
- **Nic demo 材料**：investor-facing CIS report（PDF 或 HTML），需要包含方法论 + 样本资产 + 信号解释。Nic 连接着机构关系，demo 质量直接影响第一批 LP
- **Freqtrade dry run 启动**：Minimax `git pull` + `bash scripts/start_dry_run.sh`。已准备好，没人按那个按钮
- **Supabase 接入**：Jazz 提供 URL + key 到 Railway env → 分数历史开始积累 → sparkline 有真实历史数据
- **CoinGecko Pro key 确认**：`COINGECKO_API_KEY` 写入 Railway env vars，解除 Railway 侧限速
- **Freqtrade 监控 widget**：Dashboard 里显示 dry run 持仓 / P&L / 信号命中率

### 中期（4–6 周）
- **CIS 回测验证**：用历史 Binance klines 验证 CIS grade 和 forward return 的相关性，哪怕只有 3 个月数据也够用
- **分数历史分析**：grade migration（B→A 的资产），sector rotation signal（哪个板块在加速），需要先有 Supabase 数据
- **Portfolio allocation engine v1**：基于 CIS score 和 `recommended_weight` 字段，生成组合建议
- **MCP Server**：让外部 AI agent 消费 CIS API，Agent Card `/.well-known/agent.json`
- **Event Intelligence System**：事件驱动情报（链上大额转账、协议升级、监管动态触发评分重算）

### 长期 / 未排期
- **NemoClaw / ClawHub Skill 发布**：具体形态还未定义
- **Telegram bot**：社区信号推送，订阅 CIS 变动
- **GitHub 开源 CIS 方法论 repo**：公开评分方法建立公信力，不开源引擎
- **CometCloudStrategy.py**：Freqtrade 消费 CIS 信号完整闭环，需要 dry run 数据先验证
- **Solana 链上 Fund-of-Funds**：OSL stablecoin 计价，链上 LP 模块

---

## 依赖项（当前 blockers）

| 事项 | Owner | 状态 |
|------|-------|------|
| Supabase URL + Key → Railway env | Jazz | ❌ 未做 |
| CoinGecko Pro API Key → Railway env | Jazz | ❓ 不确认 |
| Freqtrade dry run `git pull` + start | Minimax | ❌ 未做 |
| MacroBrief 手动触发（避免空窗） | Minimax | 按需 |

---

*不美化。能用的就是能用的，有问题的就是有问题的。*
