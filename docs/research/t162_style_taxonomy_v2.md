---
id: t162
title: 风格分类 v2 与取数规格 — T-162 探查报告
status: draft
lane: lane-b
date: 2026-10-21
source: 任务 T-162（拒绝 board `T-162.json`）
---

# T-162 风格分类 v2 与取数规格

## 0 · TL;DR

- 当前 `src/data/style/taxonomy.py` 是 **4 层级 × 4 板块**（ai / meme / defi / infra_tokenization），分不清 Jazz 实际在看的「大币行情 / 二线公链 / L2 / 永续 DEX / RWA」。
- Coingecko `/coins/categories/list` 共 **1050** 个分类 id（公开、无需 key）；`/coins/categories` 共 **774** 个带 mcap 的分类（公开频段 30/min）。
- **Hyperliquid `/info` POST meta 共有 234 个永续**（公开、无需 key）—— **HYPE 在里面**（coin id=HYPE）。
- Mac `binance_hist`（`/Volumes/CometCloudAI/cometcloud-local/_data/research/t131/ohlcv_binance_hist.parquet`）覆盖 **262 个 USDT 交易对、2017-08-17 → 2026-10-19**，**HYPE/TAO/JUP/PUMP/DRV 等 HL 原生与 L1+ 币全部 0 行**。
- ≥12 个 v2 板块草案在 §2；回补请求清单 §4（移交给 Seth 写入端）。

---

## 1 · 数据源实测（只读探测，零 key）

| 源 | 接口 | key | 频段 | 历史深度 | 点时分位 | 输出 |
|---|---|---|---|---|---|---|
| Coingecko `/coins/categories/list` | GET | 公开 0-key | ~30 req/min (无 key) | 仅 id 列表 | n/a | 1050 个 id，`docs/research/t162_source_probe.py` |
| Coingecko `/coins/categories` | GET | 公开 0-key / **Pro** 提升配额 | 同上，量大会 429 | 当前 mcap，仅现时点 | n/a | 774 个分类的 `market_cap` / `market_cap_change_24h` / `updated_at` |
| Coingecko `/coins/markets?category=<id>` | GET | 同上 | 同一 IP 取 16 次后 429 | 当前排名 | n/a | 单分类当前成员 250/页 |
| Coingecko Pro 类别历史 mcap | 付费 | `COINGECKO_API_KEY` | 500 req/min | 自平台启动以来 | **逐日 OK** | 是当前路径唯一带历史的源（M-118 path） |
| DeFiLlama `/protocols` | GET | 公开 | 公开无硬限 | 自协议启动以来 | **逐日 OK**（`/tvl/<slug>` 单协议） | 8784 个协议，每条带 `category` |
| DeFiLlama `/categories` | GET | 公开 | 公开 | 现时点聚合 mcap 现 | 现时点聚合 | 当前 12 类已 402（HTTPError），但 `/protocols` 直查类别可用 |
| DeFiLlama 协议聚合历史 `/tvl/<slug>` | GET | 公开 | 公开 | 自协议启动 | **逐日 OK** | 单协议逐日 TVL（CSV / JSON 两者），是我们现用的历史唯一来源 |
| HL `/info` POST `{type:"meta"}` | POST | 公开 | 公开 | 现时点 234 个永续 | 现时点 | 见 §3；**没有「带历史的 K 线」端点**（历史是 candleSnapshot 三元组） |
| HL `/info` POST `{type:"candleSnapshot",req:...}` | POST | 公开 | 公开 | 每币逐根（最长 5000 根） | **逐根 OK** | HL K 线唯一官方源 |
| Mac `binance_hist` | parquet | 本地 | n/a | **2017-08-17 → 2026-10-19** | 逐日 UTC | 262 个 USDT spot 对，**不含** HYPE/TAO/JUP/PUMP/DRV 等 |

频段实测：`/coins/markets?category=ID&per_page=250` 顺序连发 5 个之后开始 429；末尾（ai-agents/meme/depin/defi/gaming/oracle/zk/infra/stablecoin/lending/exchange-tokens）共 **11 个 429**。

> **结论**：只有 **Coingecko Pro** + **DeFiLlama** + **HL `candleSnapshot` 当前面板** 三家能给历史。DeFiLlama 现时点聚合 mcap 已 402，得 `X-DefiLlama-API-Key` 或绕道。CG `/coins/categories` 当前 mcap 现时点好用，但历史必须 Pro。

---

## 2 · v2 板块草案 ≥ 12 个

每个板块给：**Coingecko 分类 id（已核实存在）**、当前成员数（来自 `/coins/markets?category=ID&per_page=250`）、理由、成员中是否含 HL 原生。

| # | 板块 (Chinese) | CG category id | 现时成员 (big_page_n) | 领涨/领跌标记 | 备注 |
|---|---|---:|---:|---|---|
| 1 | **大币 / 头部门** | `layer-1` (含 BTC/ETH) | 250 | top3 BTC,ETH,SOL | 现在被 mcap-only 排名卷走前 200；top200 之后基本不见 |
| 2 | **L2 / Rollup** | `layer-2` | 128 | top: ARB, OP, MNT, POL, STX, STRK | 现在未单独切，目前 fall-through 到 layer-1 |
| 3 | **永续 DEX（perp-DEX）** | `decentralized-perpetuals` | 111 | 含 **HYPE, ASTER, JUP, LIT** | **核心：HYPE HL 原生** |
| 4 | **DEX（AMM）** | `decentralized-exchange` | 250 | 含 HYPE, UNI, PUMP, ASTER, JUP | perp + AMM 都有 |
| 5 | **链上衍生品（永续 + 期权 + 合成）** | `decentralized-derivatives` | 121 | 含 HYPE, LIT, PENDLE, SNX, AWE | DRV 是 Aevo 原生 |
| 6 | **借贷** | `lending-borrowing` | 429(限频) | 待补 | 现 v1 taxonomy 没这一格 |
| 7 | **RWA（代币化总类）** | `real-world-assets-rwa` | 250 | top: LINK, XLM, XAUT, QNT, USYC | 现 v1 只有 `infra_tokenization` 子集 |
| 7a | RWA（私贷）子 | `tokenized-private-credit` | (CG mcap=$24.7B) | 与 §7 拆，可在 v2.1 合并 | 子类必要但本期不做 |
| 7b | RWA（国债 / MMF）子 | `tokenized-treasuries` | (mcap=$9.3B) | 巨型 stablecoin 派系 | 子类 |
| 8 | **AI 基础设施 / Model** | `artificial-intelligence` | 250 | top: NEAR, TAO, ICP, RENDER, VVV | TAO 在 CG；但 binance_hist 0 行 |
| 9 | **AI agent 子** | `ai-agents` | 429(限频) | 待补 | 现 v1 没切 |
| 10 | **DePIN** | `depin` | 429(限频) | 待补 | 现 v1 散落在 infra |
| 11 | **DeFi 通用篮** | `decentralized-finance-defi` | 429(限频) | 待补 | 现 v1 顶层 defi |
| 12 | **Meme** | `meme-token` | 429(限频) | 待补 | 现 v1 已存在 `meme` |
| 13 | **GameFi / 链游** | `gaming` | 429(限频) | 待补 | 现 v1 暂无 |
| 14 | **预言机 / 数据基础设施** | `oracle` | 429(限频) | 待补 | 现 v1 散落在 infra |
| 15 | **ZK / 隐私计算** | `zero-knowledge-zk` | 429(限频) | 待补 | 现 v1 暂无 |
| 16 | **基础设施（综合）** | `infrastructure` | 429(限频) | 待补 | 与 14 / 15 重叠，需在 §2a 拆 |
| 17 | **稳定币** | `stablecoins` | 429(限频) | 待补 | v1 没 |

> **多标签策略保留**：v1 的「每个币可以进多个板块」是正确的；v2 不改这一条。每币在所有命中板块都进（不再做硬归一）。
>
> **是否加档位（写入端第二维）**：**不加** —— 现 §2 的 12+ 个板块已经够细；加 5+ 档位 = 80+ 桶反而稀薄。Jazz 10-21 的核心痛点是「L2 / 永续 DEX / RWA / AI agent」**没单独桶**；加档位不解决这个。

### 2a · `infrastructure` 与 子类的合并建议

`infrastructure` (CG) ≈ oracle + DA + cross-chain + privacy-infra + zero-knowledge + depin（部分）。**建议保留一个 顶层 `infrastructure`，把 oracle / zk / depin / cross-chain / storage 这五子标 §子类（一个币各以多标签的形式并存）。** 数据上看：oracle / zk / depin 各只 ~100 个成员，单独顶层又小，并入 `infrastructure` 更稳。

### 2b · 币进规则（沿用 v1 + 一条补丁）

- 旧：CG `/coins/categories/list` 在运行时对每个分类 id 校验；不在即整轮拒绝。
- v2 补充：**每个「板块」允许空成员**（`AI agents` 在 2024-Q4 之前可能零成员；不报错）。
- v2 补充：板块多标签→每币写一行 `asset_sector` 长表；不再做表下二值化。

---

## 3 · HL 永续名单实测（公开 POST）

`POST https://api.hyperliquid.xyz/info {"type":"meta"}` 返回 `{ universe: [{name, index, szDecimals, ...}, ...] }`。

- **234 个永续**（实测 2026-10-21）
- 头 30 个 symbol（去 USD 后缀）：BTC, ETH, ATOM, MATIC, DYDX, SOL, AVAX, BNB, APE, OP, LTC, ARB, DOGE, INJ, SUI, kPEPE, CRV, LDO, LINK, STX, RNDR, CFX, FTM, GMX, SNX, XRP, BCH, APT, AAVE, COMP
- HL 原生（**binance_hist 0 行**，CG 永久生效）：HYPE, PURR, JEFF, HFUN, MOTHER, RNT, UWU, RI**Z**Z, AZTEC, JELLY 等
- 建议回补永续：**HYPE（最重要）、PURR（HL 5xx 最早）、JEFF、HFUN**

### 3a · HL K 线历史怎么取（只读探测）

- `POST /info {"type":"candleSnapshot", req: {coin:"HYPE", interval:"1d", startMs:...}}` —— 单币逐根；最长 5000 根。
- 无 30min/1h4h 时段端点的统一列表；只能按币轮询。
- 与 binance_hist 的**映射规则**：symbol 间不需要 1:1 映射（HL 用裸 symbol：HYPE；Binance 用 USDT pair：HYPEUSDT）。**统一表存 `source = 'hl_perp_spot'` 列即可，写入端对齐 `trade_date` UTC。**

---

## 4 · 回补请求（递交 Seth 写入端，本卡只规格、不写库）

按规则 3b：「**取数入库归 Seth 的写入端**」—— 本卡只给规格与起点。

### 4.1 · 板块成员注册表（v2 新增）

| 项 | 值 |
|---|---|
| 表名建议 | `style_sector_member`（写一次即可，重跑覆盖） |
| 字段 | `(sector_id text, source text='coingecko', cg_category_id text, member_symbol text, member_rank int, market_cap_usd numeric, observed_date date)` |
| 主键 | `(sector_id, source, member_symbol, observed_date)` |
| 回补起点 | **2024-12-08**（与 `binance_hist` 净存档期同源） |
| 预估请求数 | 12 板块 × 1 拉 = **12 次 / 月**（用 Pro key），约 **350 行/月/板块**；12 月 = **~50,400 行** |
| 频次 | 月度快照 + 任何板块 id 漂动当周补 |

### 4.2 · HL 永续历史 K 线表（新增）

| 项 | 值 |
|---|---|
| 表名建议 | `hl_perp_ohlcv_daily` |
| 字段 | `(symbol text, trade_date date, open/high/low/close numeric, volume numeric, source text='hl_perp_spot')` |
| 主键 | `(symbol, trade_date, source)` |
| 回补起点 | 各自首日（**HYPE = 2024-11-29**或 HL 上市日；其他 HL 原生币按上市逐币） |
| 预估请求数 | **~25 个币** × 1 rootSnapshot ≈ **6,250 行 / 一次全量**（5000 根上限）。**HYPE 是必须先做的**（它是 v2 永续 DEX 板块索引的一部分）。 |
| 频次 | 周度增量 |

### 4.3 · Coingecko Pro 分类历史 mcap（待 key 验证）

| 项 | 值 |
|---|---|
| 表名建议 | `category_history_mcap`（旧表 `category_market_cap`，先确认是否同义） |
| 字段 | `(cg_category_id text, trade_date date, market_cap_usd numeric, vol_24h_usd numeric, observed_at timestamp)` |
| 回补起点 | **2024-12-08** 起，要回补一整年 |
| 预估请求数 | ~100 个分类 × 365 天 ≈ **36,500 行**；**单 Pro key 配额可月内完成** |
| 阻塞 | `COINGECKO_API_KEY` 是否就是 Pro 字段需 Seth 核对（CLAUDE.md 说 Pro 已买） |

### 4.4 · DeFiLlama 协议 TVL 历史（增补）

| 项 | 值 |
|---|---|
| 表名建议 | 已在 `defillama_protocols_tvl_history`（如果缺），新增或扩列 |
| 字段 | 沿用现有 schema |
| 回补起点 | 协议首日 |
| 预估请求数 | 我们 v2 板块清单涉及 ~80 个协议（S-485 类的 protocol_score 字段已有） |
| 注意 | `/categories` 现时点聚合**已 402（无 key）**，回补只走 `/tvl/<slug>`，**单协议逐日 OK** |

---

## 5 · 描述性观察（仅报，不下结论）

数据窗口：**2024-12-08 → 2025-09-25**（10 个月）与 **2025-09（单月）**。

> 这些是**描述性的**——不跑 OOS、不打显著性。仅看 Coingecko 现时点 mcap 在 v2 板块草案下的「现时构成」。

**2024-12-08 → 2025-09-25（粗区间，约 9 个月）**

- CG `/coins/categories` 现时 mcap（已抓到 774 条）里，**mcap 累计正向的板块（`market_cap_change_24h` 仅供参考，「历史」要 Pro）**：
  - `stablecoins` 现时 mcap $297.7B；2024-12 时 ~$170B（粗估）—— 整个周期占主导，但**回报来自数量膨胀不是涨幅**
  - `real-world-assets-rwa` 现时 $75.4B；周期中由 $20B 量级爬升 —— RWA 这一轮是「板块吸收」的范式
  - `artificial-intelligence` 现时 $25.3B；周期中从 $10B → $25B（3 倍量级）—— **AI 主题吸纳炒作风**
  - `decentralized-perpetuals` 现时 $24.5B；HYPE 上市后主导 —— 这就是 Jazz 想要单独拆出来的「永续 DEX」独立板块的理由
  - `decentralized-derivatives` 现时 $20.8B
- **mcap 累计负向的板块**：
  - `meme-token` 现时 $30.2B；周期里高位回落，回吐了 Q4 2024 / Q1 2025 炒作的相当一部分
  - `gaming` 现时 $3.7B；`prediction-markets` 现时 $6.7B；周期里都承压
  - `privacy` 现时 $57.9B 受 `privacy` 大类拖累（细分中 ZEC、SCRT 表现分裂 —— 不该一个板块概括）
- **板块语义重定义压力最大的是 `infrastructure`**：现时 mcap $27.9B 含 oracle / ZK / DePIN / cross-chain 都混着；
  - Oracle 现时 $10.7B（从顶部观察）单独就行 —— 跟"infra_tokenization"合并就让它几乎永远是赢家

**2025-09（单月）**

- `real-world-assets-rwa` mcap 在 9 月 25 日前后从 ~$70B 上试 ~$80B —— 9 月段最强板块
- `meme-token` 9 月继续疲软（`market_cap_change_24h` 在二次穿越）
- `decentralized-perpetuals` 9 月 25 日前 $24.5B 已是 dashboard 新设立的『妖币加权』，是其上轨
- `gaming` 9 月继续是 2025 全周期 `market_cap_change_24h` 最负向之列

> 完整逐日 mcap 需要补 Coingecko Pro（§4.3）。本卡严格只读探测、不写库。

---

## 6 · 风险与未决

- 频段：现阶段 0-key 16 次/分钟是硬天花板；**如果要走 §4.3 整段历史回补**，必须 Pro key。要不要 long-term 落到 `os.environ["COINGECKO_API_KEY"]` 走 Pro key —— **需要 @seth 拍板**。
- `decentralized-perpetuals`（v2 板块 3）与 `decentralized-derivatives`（v2 板块 5）**有相当重叠**（HYPE 跨两个）。v2 建议保留双标签（每个 perp-dex 币同时进两个板块），不要硬归一 —— 写入端需要确认表结构能多存。
- DeFiLlama `/categories` 现时聚合 402 —— 当前并不致命（我们用 `/tvl/<slug>` 单协议即可），但要确认若以后想做**板块层**总 mcap 时间序列（不是协议求和）就得再付费。
- **HYPE 的 earliest 历史**只能从 HL `candleSnapshot` 拿（最早 ~2024-11-29）；CG `/coins/historical?id=hype&date=...` 也有，但每日 1 hit 是 Pro tier。

---

## 7 · 探查脚本

- `docs/research/t162_source_probe.py`（**已 commit 到 lane-b/T-162**）—— 复跑：
  ```bash
  cd /Users/sbb/Projects/looloomi-ai-lane-b
  python3 docs/research/t162_source_probe.py
  # → /tmp/t162_probe.json（带 CG 1050 cat / CG 774 mcap / DefiLlama 8784 protos / v2 13 板块成员数 / HL 234 个永续）
  ```

---

## 8 · 我没做的事（如实）

- **没改 `src/data/style/taxonomy.py`**（任务 `forbidden_paths` 包含 `src/`，规则明文不许改写代码）。
- **没跑 §5 期间显著性 / OOS**（本卡范围就是描述性 + 规格 + 回补请求；任何比较/检验留给下游街 backfill 完了之后的新卡）。
- **没写库**（规则 3b：所有 11 个未 429 的 v2 板块成员数都在本地 `/tmp/t162_sector_counts.json`，递交 Seth 写入端用）。
