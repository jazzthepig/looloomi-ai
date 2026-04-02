# MINIMAX_SYNC.md — Seth ↔ Minimax 协调文档
*最后更新: 2026-04-02 — Seth*

---

## §1 文件所有权

| 路径 | 所有者 | 说明 |
|------|--------|------|
| `src/api/`, `src/data/`, `src/mcp/` | **Seth** | Railway 后端，git 管理 |
| `dashboard/` | **Seth** | React 前端，git 管理 |
| `/Volumes/CometCloudAI/cometcloud-local/` | **Minimax** | 本地引擎，不进 git |
| `/Volumes/CometCloudAI/freqtrade/` | **Minimax** | Freqtrade，不进 git |
| `Shadow/` | **只读参考** | Seth 写参考代码，Minimax 手动 apply 到实际路径 |

**规则：Seth 不碰 cometcloud-local。Minimax 不碰 src/ 或 dashboard/。**

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

## §4 Minimax 当前任务优先级

| 优先级 | 任务 | 依赖 |
|--------|------|------|
| P0 | Apply `config.py` v4.1 thresholds + compliance signals | — |
| P0 | Apply `data_fetcher.py` 8 bug fixes | Rotate EODHD/Finnhub keys first |
| P0 | Restart `cis_scheduler.py` → 确认 Redis key `cis:local_scores` 有数据 | 上两项完成 |
| P0 | 通知 Jazz：CIS scores 已进 Redis（T1 badge 应该变绿） | — |
| P1 | Apply T1 策略三件套 + 跑 `run_t1_backtest.sh` | Freqtrade venv 正常 |
| P1 | 回报 backtest 结果（PF / WR / MaxDD） | backtest 完成 |
| P1 | LAS 字段加入 local engine 输出（match Railway schema） | — |
| P2 | Macro Brief pipeline 稳定性（LM Studio crash recovery） | — |
| P2 | DeFiLlama TVL 刷新 30min → 15min | — |

---

## §5 Seth 已完成 / Railway 已部署

本 session 已提交到 git 的 src/ 变更（commit `682fdbe`）：

| 文件 | 变更 |
|------|------|
| `src/mcp/cometcloud_mcp.py` | CIS universe key 修复（`universe` not `assets`）；signal feed 字段修复；macro_pulse 嵌套结构 fallback 解析；CIS 超时 20s→60s |
| `src/data/market/data_layer.py` | `get_macro_pulse()` 新增 flat fields（`btc_price`, `btc_dominance`, `fear_greed_index` 等）供 MCP agent 直接读取 |

**⚠️ 等待 Jazz：**
- `rm -f .git/HEAD.lock && git push origin main`（推送 682fdbe 到 Railway）
- 重启 Claude Desktop（MCP server 加载修复后代码）

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
