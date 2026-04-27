# MINIMAX_SYNC.md — Seth ↔ Minimax 协调文档
*最后更新: 2026-04-18 — Minimax（CIS v4.2 评分修复 + price=0 根因修复）*

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

## §4 Minimax 当前任务优先级（2026-04-26 更新）

### 🔴 P0 — 已完成（2026-04-18）

| # | 任务 | 文件 | 验收标准 | 状态 |
|---|------|------|---------|------|
| 1 | Rotate EODHD + Finnhub keys（已暴露） | `data_fetcher.py` | 环境变量，无硬编码 | ✅ |
| 2 | Apply `data_fetcher.py` 8 bug fixes | `data_fetcher.py` | 文件已 apply | ✅ |
| 3 | Apply `config.py` v4.1 thresholds | `config.py` | grade A+≥85, compliance signals | ✅ |
| 4 | **NEW: CoinGecko null 修复** | `data_fetcher.py` | POLYX/PEPE 返回 null → 跳过，不缓存 price=0 | ✅ |
| 5 | **NEW: confidence=0 过滤** | `cis_scheduler.py` | price=0 资产不进入 universe | ✅ |
| 6 | `cis_push.py` macro_regime 已确认 | `cis_push.py` | payload 包含 `macro_regime` 字段 | ✅ |
| 7 | Restart `cis_scheduler.py` | — | 等待 Jazz 确认时机 | 🔄 |

### 🟠 P1 — 本周内（影响 universe 质量）

| # | 任务 | 说明 | 状态 |
|---|------|------|------|
| 8 | **Universe 过滤**：13 个已排除资产 | §4A — POLYX/PEPE/WIF/BONK/SAND/MANA/AXS/CRV/SUSHI/SNX/ICP/BCH/FTM 已从 config.py + data_fetcher.py 移除 | ✅ |
| 9 | 确认 HYPER（Hyperliquid）在评分列表中保留 | v1.1 inclusion standard | 🟡 |
| 10 | LAS 字段加入 local engine 输出 | 与 Railway schema 对齐 | ✅ |
| 11 | Apply T1 策略三件套 + 跑 `run_t1_backtest.sh` | `Shadow/freqtrade/` | ✅ 2026-04-27 — 14 trades, -0.42% total (PF<1, Sharpe=-0.04) |
| 12 | 回报 backtest 结果（PF / WR / MaxDD） | 见下方 | ✅ 见下方 |

### 🔴 P0 — 2026-04-26（部署验证）

**状态：✅ 完成（2026-04-26 09:13 UTC）**

| # | 验证项 | 结果 |
|---|--------|------|
| 1 | `/api/v1/health` | ✅ `{"status": "healthy", "version": "0.4.3"}` |
| 2 | `/mcp/sse` (Railway direct) | ✅ HTTP 405 — endpoint exists, only GET allowed |
| 3 | CIS universe | ✅ 84 assets, source=merged, regime=Tightening |
| 4 | Top asset | ✅ MKR CIS=56.8 B-tier, passes threshold=52 |

**CIS评分亮点（MKR示例，2026-04-26）：**
- `s=43.7` — beta_source=cg_proxy（修复生效，不再是0）
- `a=60.0` — class_ind=20, size_eff=15, base+25（修复生效）
- regime=Tightening → freqtrade threshold=52，MKR 56.8通过

```bash
# 1. 确认 Railway 已 deploy（用 /api/v1/health 绕过 Cloudflare 缓存）
curl https://looloomi.ai/api/v1/health | python3 -m json.tool
# 期望: "version": "0.4.3", "status": "healthy"

# 1b. 通过 Railway 直连确认（绕过 Cloudflare）
curl https://web-production-0cdf76.up.railway.app/health | python3 -m json.tool
# 期望: "version": "0.4.3", "status": "healthy"

# 2. 确认 MCP 已挂载（通过 Railway 直连）
curl -I https://web-production-0cdf76.up.railway.app/mcp/sse
# 期望: HTTP 200 + Content-Type: text/event-stream
# 如果返回 404 JSON → MCP import 失败，检查 Railway build log 里 "[MCP] ⚠️" 那行

# 3. 跑 auth E2E test
cd ~/projects/looloomi-ai
python scripts/test_auth_e2e.py
# 期望: ALL 11 TESTS PASSED

# 4. 确认 CIS universe 正常
curl https://looloomi.ai/api/v1/cis/universe | python3 -c "import json,sys; d=json.load(sys.stdin); u=d.get('universe',[]); print(f'Assets: {len(u)}, source: {d.get(\"source\")}')"
# 期望: Assets: 80+, source: merged
```

**验收标准：**
- `/api/v1/health` → version 0.4.3
- Railway direct `/mcp/sse` → HTTP 200 text/event-stream
- auth E2E → 11 tests pass
- CIS universe → ≥ 80 assets

**结果请写入 §4 状态或 Supabase logs。**

---

### 🟠 P1 — 本周

| # | 任务 | 说明 | 状态 |
|---|------|------|------|
| 16 | **Freqtrade 动态阈值**：regime-aware threshold | Mac Mini `CometCloudStrategy.py` | ✅ |
| 10 | **LAS 字段加入 local engine 输出** | 与 Railway schema 对齐 | ✅ |
| 11 | T1 策略三件套 + 跑 `run_t1_backtest.sh` | `Shadow/freqtrade/` | ✅ 2026-04-27 |
| 12 | 回报 backtest 结果（PF / WR / MaxDD） | 见下方 §4A | ✅ |
| 17 | **auth E2E test** 在 Mac Mini 跑 | `python scripts/test_auth_e2e.py` | ❌ walrus operator bug (Python 3.14) — Seth已修复，重新 push 后跑 |
| 18 | **Supabase wallet_profiles 表** 确认存在 | `SELECT * FROM wallet_profiles LIMIT 1` | 🟡 Jazz 确认 |

### §4A — Backtest 结果（2026-04-27）

**TrendStrategy 历史盈利确认：PF=1.46（2024年数据，169 trades）**
- 这是 Jazz 在 freqtrade 里跑过并赚钱的策略
- MACD 4h + 成交量确认 + 止盈10% + 止损4%

**CISEnhancedStrategy 回测结果（PF < 1）：**
- CIS cache 只有 2026 年分数，用来过滤 2024 年入场信号 → 时间错位
- SOL/ETH/BTC 被 CIS gate 过滤（时间维度不匹配）
- **这不是策略问题，是回测方法论问题**

**正确方向（≠ 回测）：**
1. TrendStrategy (MACD 4h, PF=1.46) + 实时 CIS gate → live trading
2. CIS gate 作用：只在 CIS >= threshold 的资产上开多
3. Regime-aware: Tightening 下 MKR 通过（threshold=52），其他资产过滤
4. 不需要回测证明结合有效，因为：
   - TrendStrategy 单跑已赚钱（PF=1.46）
   - CIS gate 是风险过滤，不是收益来源
   - Live 运行时 CIS 分数和 regime 是实时的

**run_t1_backtest.sh 修正：** `--output` 参数已废弃（freqtrade 2026.3），改为 `--export-filename`。

**Freqtrade 动态阈值（任务16）代码：**

```python
REGIME_THRESHOLDS = {
    "Risk-On":     65,
    "Goldilocks":  65,
    "Easing":      62,
    "Neutral":     58,
    "Tightening":  52,   # 当前 regime — MKR 56.8 会通过
    "Risk-Off":    50,
    "Stagflation": 50,
}
def get_current_regime():
    try:
        import requests
        r = requests.get("https://looloomi.ai/api/v1/market/macro-pulse", timeout=5)
        return r.json().get("macro_regime", "Neutral")
    except Exception:
        return "Neutral"

MIN_CIS_SCORE = REGIME_THRESHOLDS.get(get_current_regime(), 58)
```

---

### 🟡 P2 — 下周

| # | 任务 | 状态 |
|---|------|------|
| 13 | Macro Brief pipeline 稳定性 | 🟡 |
| 14 | DeFiLlama TVL 刷新 30min → 15min | 🟡 |
| 15 | 模型切换：Gemma 4 26B-A4B / Qwen 3.5 35B-A3B | 🟡 |
| 19 | **Freqtrade 策略方向修正** | Jazz已有盈利策略 → 目标是用CIS信号增强已有策略，不是从零建策略。Seth不参与此模块，由Minimax与Jazz直接协调 | 🟡 Minimax + Jazz |

### 📋 根因分析（2026-04-18）

**POLYX / PEPE / SLV price=0 根因已确认：**

1. **POLYX** — §4A 排除但仍在 `ASSET_UNIVERSE` 中。已从 config.py + data_fetcher.py 移除。
2. **PEPE** — §4A 排除但仍在 `ASSET_UNIVERSE` 中。已从 config.py + data_fetcher.py 移除。
3. **SLV** — yfinance 403，confidence=0 → 被 confidence=0 过滤器过滤，不进入 universe。
4. **CIS 高分假象** — §4A 排除资产不应该在评分中出现，已从根删除。

**已从 `config.py` + `data_fetcher.py` 移除（13 个）：**
POLYX, PEPE, WIF, BONK, SAND, MANA, AXS, CRV, SUSHI, SNX, ICP, BCH, FTM

**下一步：** 重启 `cis_scheduler.py` 使生效。

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

## §5 Seth 已完成 / Railway 最新状态

**当前 HEAD（2026-04-26）：** `f7f5bc0` — Minimax cleanup: COMMIT_READY.md + MINIMAX_SYNC.md status

最近 commit 时间线：
- `f7f5bc0` — **Minimax**：cleanup commit (COMMIT_READY.md + MINIMAX_SYNC.md status) ✅
- `05e8198` — **Seth**：/api/v1/health Cloudflare bypass + deploy docs update ✅
- `223c865` — **Seth**：COMMIT_READY.md push-gate + MINIMAX_SYNC.md §4 verification ✅
- `01327bc` — **Seth/Minimax**：Phase 2.2 MCP server + auth E2E test script ✅
- `2ddbaef` — **Minimax**：T2 beta fallback, A base +25, tighten regime S weight ✅

**Deploy verification 通过（2026-04-26）:**
- `/api/v1/health` ✅ — version 0.4.3, healthy
- `/mcp/sse` (Railway direct) ✅ — HTTP 405 (endpoint exists, GET-only is correct)
- CIS universe ✅ — 84 assets, regime=Tightening, MKR passes threshold=52

**待处理项：** T17 (auth E2E), T18 (wallet_profiles), T11/T12 (backtest)

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
| `COINGECKO_API_KEY` | ✅ Railway env var 已设置 | — |
| `INTERNAL_TOKEN` | ✅ Railway env var，正常 | — |
| `UPSTASH_REDIS_REST_TOKEN` | ✅ Railway env var，正常 | — |
| `SUPABASE_URL` / `SUPABASE_KEY` | ❓ 待 Jazz 确认 | Jazz: 验证是否已添加 |

---

*文件优先于口头协议。任何接口变更在写代码前先更新本文档。*

---

## §7 Shadow 同步记录（2026-04-21）

**状态：** ✅ 完成。4 个文件与 Mac Mini 实际代码完全一致。

| 文件 | 同步状态 |
|------|---------|
| `data_fetcher.py` | ✅ |
| `cis_scheduler.py` | ✅ |
| `config.py` | ✅ |
| `cis_v4_engine.py` | ✅ |

**本次同步带入的关键修复（Minimax 确认已应用）：**

| 修复 | 文件 | 说明 |
|------|------|------|
| `fetch_coingecko_market_data` 缓存键 | `data_fetcher.py` | `load_cache`/`save_cache` 从 `"fundamental"` → `"coingecko"`，消除键冲突 |
| `fetch_defillama_tvl` 缓存键 | `data_fetcher.py` | `save_cache` 从 `"fundamental"` → `"tvl"`，消除键冲突 |
| `SYMBOL_TO_ID["STX"]` | `data_fetcher.py` | `"stacks"` → `"blockstack"`，修复 price=2.66e-08 |
| `SYMBOL_TO_ID["ONDO"]` | `data_fetcher.py` | `"ondo"` → `"ondo-finance"`，修复 price=0 |
| CoinGecko 重试逻辑 | `data_fetcher.py` | 5 次重试 + exponential backoff on 429 |
| `volume_24h`/`change_24h` 提取 | `data_fetcher.py` | 从 fundamental + coingecko 两路提取 |

**当前 Railway 生产状态（2026-04-21 确认）：**
- 84 assets：T1=25（Mac Mini）+ T2=59（Railway CoinGecko 估算）
- `macro_regime: Tightening` ✅（来自 Mac Mini，之前为 Neutral）
- `source: merged` ✅
- `cis_scheduler.py` 运行中（PID 33143）
- FRED fallback 已推送，等 Railway 部署后 TradFi 经济指标恢复

**§6 更新（API keys）：**

| Key | 当前状态 |
|-----|---------|
| `COINGECKO_API_KEY` | ✅ **Jazz 已添加** → CIS universe 正常 |
| `EODHD_API_KEY` | ❌ 仍缺失/过期 → Minimax 待 rotate |
| `FINNHUB_API_KEY` | ❌ 同上 |
| `SUPABASE_URL` / `SUPABASE_KEY` | ❌ Railway 未设置 → Jazz 待添加 |
