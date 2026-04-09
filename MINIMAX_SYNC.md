# MINIMAX_SYNC.md — Seth ↔ Minimax 协调文档
*最后更新: 2026-04-10 — Seth（优先级已更新，Railway push 完成）*

---

## §1 文件所有权

Mac Mini `/Volumes/CometCloudAI/` 下有三个独立目录，各自有用途：

| 实际路径 | Shadow 镜像 | 所有者 | 用途 |
|---------|------------|--------|------|
| `/Volumes/CometCloudAI/cometcloud-local/` | `Shadow/cometcloud-local/` | **Minimax** | 本地后端：CIS 引擎 (`cis_v4_engine.py`)、scheduler、data fetcher、Ollama/Qwen3 推理 |
| `/Volumes/CometCloudAI/freqtrade/` | `Shadow/freqtrade/` | **Minimax** | 策略研究 + 计算实验室：strategies、backtesting、dry run |
| `/Volumes/CometCloudAI/data/` | `Shadow/data/` | **Minimax** | 数据存储 |
| `~/projects/looloomi-ai/src/` | — | **Seth** | Railway 后端，git 管理，auto-deploy |
| `~/projects/looloomi-ai/dashboard/` | — | **Seth** | React 前端，git 管理，auto-deploy |
| `~/projects/looloomi-ai/programs/` | — | **Seth/Jazz** | Solana 链上合约（Anchor），活跃开发 |

**Shadow/ 是只读参考镜像** — Seth 在 Shadow/ 里写参考代码，Minimax 手动 apply 到对应的实际路径。Shadow/ 永远不 commit 进 git。

**规则：Seth 不碰 cometcloud-local 或 freqtrade。Minimax 不碰 src/ 或 dashboard/。**

---

## §2 接口合约 — `/internal/cis-scores` POST Schema

Railway 端接收格式（`src/api/routers/cis.py`），当前版本 v4.1：

```json
{
  "assets": [
    {
      "asset_id": "BTC",
      "symbol": "BTC",
      "name": "Bitcoin",
      "asset_class": "L1",
      "cis_score": 72.4,
      "grade": "B+",
      "signal": "OUTPERFORM",
      "las": 68.1,
      "confidence": 0.85,
      "pillars": { "F": 75, "M": 68, "O": 71, "S": 65, "A": 80 },
      "recommended_weight": 0.10,
      "class_rank": 1,
      "global_rank": 3
    }
  ],
  "macro_regime": "RISK_ON",
  "engine_version": "4.1",
  "push_timestamp": 1712000000000
}
```

**合规要求（绝对禁止）：**
- `signal` 字段只允许：`STRONG OUTPERFORM` / `OUTPERFORM` / `NEUTRAL` / `UNDERPERFORM` / `UNDERWEIGHT`
- 禁止使用：`BUY` / `SELL` / `ACCUMULATE` / `AVOID` / `OVERWEIGHT`

**Grade 阈值 v4.1（绝对分）：**

| Grade | 分数范围 | Signal |
|-------|---------|--------|
| A+    | ≥ 85    | STRONG OUTPERFORM |
| A     | ≥ 75    | STRONG OUTPERFORM |
| B+    | ≥ 65    | OUTPERFORM |
| B     | ≥ 55    | OUTPERFORM |
| C+    | ≥ 45    | NEUTRAL |
| C     | ≥ 35    | UNDERPERFORM |
| D     | ≥ 25    | UNDERWEIGHT |
| F     | < 25    | UNDERWEIGHT |

*已在 `Shadow/cometcloud-local/config.py` 更新。请 Minimax 确认 `cis_v4_engine.py` 使用相同阈值。*

---

## §3 待 Minimax Apply 的 Shadow 变更

以下所有文件均已在 Shadow/ 更新。Minimax 需要手动 apply 到 Mac Mini 实际路径。

### 🔴 P0 — 影响 CIS 数据质量（当前 Railway CIS universe 为空）

#### `data_fetcher.py`
**Shadow 路径:** `Shadow/cometcloud-local/data_fetcher.py`
**目标路径:** `/Volumes/CometCloudAI/cometcloud-local/data_fetcher.py`

8 个 bug 修复（上个 session）：

| # | 问题 | 修复 |
|---|------|------|
| 1 | EODHD 日期格式传 Unix timestamp，API 要 `YYYY-MM-DD` | 改用 `datetime.strftime("%Y-%m-%d")` |
| 2 | Finnhub API key 硬编码在代码里（git history 暴露） | 改为 `""` 默认值，通过环境变量读取 |
| 3 | EODHD API key 同上暴露 | 同上 |
| 4 | `SYMBOL_TO_ID.get(symbol.lower())` 查不到（dict 是大写 key） | 改为 `.upper()` |
| 5 | `requests.exceptions.RateLimitError` 不存在，静默失败 | 改为 `HTTPError` + `e.response.status_code == 429` |
| 6 | `fetch_yf_price()` 内仍调用 `ticker.info`（IP 封禁会 hang） | 删除 `ticker.info`，`market_cap` 返回 0 |
| 7 | 重复 `import threading`（line 24 和 line 30） | 删除 line 30 |
| 8 | ⚠️ 轮换 EODHD + Finnhub key（已暴露在 git history） | **Minimax 需要重新申请或 rotate key** |

#### `config.py`
**Shadow 路径:** `Shadow/cometcloud-local/config.py`
**目标路径:** `/Volumes/CometCloudAI/cometcloud-local/config.py`

Grade thresholds 改为 v4.1 + compliance 信号：
- 旧：A+≥90, A≥80，信号用 `STRONG OVERWEIGHT`/`AVOID`（**合规违规**）
- 新：A+≥85, A≥75, B+≥65...，信号用 `STRONG OUTPERFORM`/`UNDERWEIGHT`

**apply 后需要重启 `cis_scheduler.py`。**

---

### 🟡 P1 — Freqtrade T1 策略验证（dry run 前置条件）

#### `CometCloudT1Strategy.py`（新建）
**Shadow 路径:** `Shadow/freqtrade/user_data/strategies/CometCloudT1Strategy.py`
**目标路径:** `/Volumes/CometCloudAI/freqtrade/user_data/strategies/CometCloudT1Strategy.py`

autoresearch 最优参数的 Freqtrade 原生实现：
- RSI(14) ≤ 30 入场，ADX(14) ≥ 18 趋势过滤，SL=-3%，RSI ≥ 55 出场
- 纯技术，无外部依赖（无 CIS/EODHD/API）
- 无 pandas_ta 依赖，用内置函数

#### `config_backtest_t1.json`（新建）
**Shadow 路径:** `Shadow/freqtrade/config_backtest_t1.json`
**目标路径:** `/Volumes/CometCloudAI/freqtrade/config_backtest_t1.json`

backtest 专用 config：fee=0.001（0.1%/side），max_open_trades=1

#### `scripts/run_t1_backtest.sh`（新建）
**Shadow 路径:** `Shadow/freqtrade/scripts/run_t1_backtest.sh`
**目标路径:** `/Volumes/CometCloudAI/freqtrade/scripts/run_t1_backtest.sh`

一键 backtest 脚本：下载数据 + 跑回测 + 输出决策标准

**决策标准：PF ≥ 1.25 with fees → 启动 dry run。PF < 1.10 → 返回 research。**

详见 `Shadow/freqtrade/research/T1_BACKTEST_VALIDATION.md`。

---

## §4 Minimax 当前任务优先级（2026-04-10 更新）

### 🔴 P0 — 必须先做（阻塞 CIS 数据）

| # | 任务 | 命令/文件 | 验收标准 | 状态 |
|---|------|----------|---------|------|
| 1 | Rotate EODHD + Finnhub keys（已暴露） | 重新申请，设置环境变量 | 代码中无硬编码 key | 🔴 |
| 2 | Apply `data_fetcher.py` 8 bug fixes | `cp Shadow/cometcloud-local/data_fetcher.py /Volumes/CometCloudAI/cometcloud-local/` | 文件 MD5 一致 | 🔴 |
| 3 | Apply `config.py` v4.1 thresholds + compliance signals | `cp Shadow/cometcloud-local/config.py /Volumes/CometCloudAI/cometcloud-local/` | grade A+≥85, 信号无 BUY/SELL | 🔴 |
| 4 | Restart `cis_scheduler.py` | `pkill -f cis_scheduler && python cis_scheduler.py &` | `cis:local_scores` key 在 Redis 有数据 | 🔴 |
| 5 | 验证 CIS push 成功 | `curl -H "X-Internal-Token: $INTERNAL_TOKEN" https://looloomi.up.railway.app/api/v1/cis/universe \| jq '.data_tier'` | 返回 `"T1_LOCAL"` 而不是 `"railway"` | 🔴 |
| 6 | 通知 Jazz：T1 badge 变绿 | — | — | 🔴 |

### 🟠 P1 — 本周内（影响 universe 质量）

| # | 任务 | 说明 | 状态 |
|---|------|------|------|
| 7 | **Universe 过滤**：从 cis_v4_engine.py 的资产列表中移除 14 个已排除资产 | 见下方 §4A 排除列表 | 🟡 |
| 8 | 确认 HYPER（Hyperliquid）在评分列表中保留 | v1.1 inclusion standard 已重新纳入 | 🟡 |
| 9 | LAS 字段加入 local engine 输出 | `"las": cis_score * liquidity_multiplier * confidence` — 与 Railway schema 对齐 | 🟡 |
| 10 | Apply T1 策略三件套 + 跑 `run_t1_backtest.sh` | `Shadow/freqtrade/` 目录，决策标准：PF ≥ 1.25 → dry run | 🟡 |
| 11 | 回报 backtest 结果（PF / WR / MaxDD） | 发给 Jazz | 🟡 |

### 🟡 P2 — 下周

| # | 任务 | 状态 |
|---|------|------|
| 12 | Macro Brief pipeline 稳定性 — LM Studio crash recovery（Gemma 4 26B-A4B 替代 Qwen3-35B 做 narrative generation） | 🟡 |
| 13 | DeFiLlama TVL 刷新 30min → 15min | 🟡 |
| 14 | 模型切换：Narrative generation → **Gemma 4 26B-A4B**；Event classification → **Qwen 3.5 35B-A3B**（见 PRD_V2_2.md §5） | 🟡 |

### ⚠️ 已完成 / 被阻塞

| # | 任务 | 说明 |
|---|------|------|
| — | Seth Railway push | ✅ commit `a2008f1` 已推送，包含 P0 文件 |
| — | Redis `cis:local_scores` 数据存在 | 等待 P0 #1-#3 apply 后 Mac Mini 重新 push |

---

## §4A Universe 过滤 — 从评分列表删除这 14 个资产

以下资产已在 EXCLUSION_LIST.md v1.1 中确认排除。请从 `cis_v4_engine.py` 的 `ASSETS` 列表（或等效配置）中移除：

```
BONK   — Criterion 3+7 (anonymous team, no custody)
PEPE   — Criterion 3+7 (anonymous team, no custody)
WIF    — Criterion 3+6+7 (anonymous team, no custody, history)
MANA   — Criterion 1+2 (volume <$5M, DAU <1K)
SAND   — Criterion 1 (volume declining below threshold)
AXS    — Criterion 7 ($625M Ronin exploit, unresolved)
CRV    — Criterion 7 (founder conflict of interest — personal loan positions)
SUSHI  — Criterion 7 (repeated treasury integrity incidents 2020-2024)
SNX    — Criterion 2 (data discontinuity from 3 product pivots)
ICP    — Criterion 5 (undisclosed 90% supply inflation at launch)
VIRTUAL— Criterion 3 (no institutional custodian support)
BCH    — Criterion 4 (Roger Ver DOJ indictment 2024)
FTM    — Criterion 5 (FTM→S rebrand breaks time-series; new asset <18mo)
POLYX  — Criterion 1 (30d volume ~$300K vs $5M minimum)
```

**保留（不要删除）：**
- `HYPER` (Hyperliquid) — 已在 v1.1 重新纳入，confidence multiplier 0.85× 直到 180 天历史
- `DOGE` — passes all 7 criteria，保留
- `RUNE` — borderline，暂时保留但加 `"remediation_flag": true` 字段，等 Jazz 最终决定
- `MKR` — 保留（SKY 不评分）

---

## §5 Seth 已完成 / 待推送到 Railway

**Railway 已推送（commit `a2008f1`）：** 2026-04-10 push 成功，包含全部 P0 文件 + dashboard 新页面 + dist build。Railway auto-deploy 已触发。

**所有待处理项已清空。** 无阻塞项。

| 文件 | 变更 | Session |
|------|------|---------|
| `src/mcp/cometcloud_mcp.py` | CIS universe key 修复；signal feed 字段修复；macro_pulse fallback；3 新工具（get_cis_exclusions, get_inclusion_standard, get_regime_context）；get_vc_funding → get_institutional_flows | Apr 2 + Apr 10 |
| `src/api/routers/cis.py` | 新增 `/api/v1/agent/cis-exclusions` + `/api/v1/agent/inclusion-standard` 两个端点；含完整静态排除数据 | Apr 10 |
| `src/api/routers/leads.py` | BumbleBee → HumbleBee Capital | Apr 10 |
| `src/api/routers/vault.py` | BumbleBee → HumbleBee Capital | Apr 10 |
| `src/data/market/data_layer.py` | `get_macro_pulse()` flat fields for MCP | Apr 2 |
| `dashboard/src/agent.jsx` | 全新 /agent.html 页面 — MCP API landing page + pricing + key request form | Apr 10 |
| `dashboard/src/analytics.jsx` | Standalone analytics page | Apr 9 |
| `dashboard/src/portfolio.jsx` | Standalone portfolio page | Apr 9 |
| `dashboard/src/components/VaultPage.jsx` | HumbleBee fix | Apr 10 |
| `dashboard/src/components/ShareCard.jsx` | HumbleBee fix + T.muted tokens | Apr 9 |
| `dashboard/src/lib/solanaVault.js` | HumbleBee fix | Apr 10 |
| `dashboard/vite.config.js` | portfolio + analytics + agent entries added | Apr 9-10 |
| `dashboard/dist/` | Built output for all above | Apr 10 |

---

## §6 API key 管理

| Key | 当前状态 | 行动 |
|-----|---------|------|
| `EODHD_API_KEY` | **已暴露在 git history**（`Shadow/cometcloud-local/data_fetcher.py`） | Minimax: rotate key，通过环境变量设置，不写入代码 |
| `FINNHUB_API_KEY` | **同上** | 同上 |
| `COINGECKO_API_KEY` | Railway env var 未设置（导致 CIS universe 为空） | Jazz: 在 Railway → Variables 中添加 |
| `INTERNAL_TOKEN` | Railway env var，正常 | — |
| `UPSTASH_REDIS_REST_TOKEN` | Railway env var，正常 | — |
| `SUPABASE_URL` / `SUPABASE_KEY` | **未在 Railway 设置** | Jazz: 添加到 Railway Variables |

---

*文件优先于口头协议。任何接口变更在写代码前先更新本文档。*
