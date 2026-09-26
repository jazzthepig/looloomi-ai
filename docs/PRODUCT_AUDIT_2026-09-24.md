# 产品面审计(T-014)—— 进行中

*Seth,2026-09-24 起。方法:内置浏览器走 Jazz 的网络逐页看;每条发现最终转成任务卡。*
*判据三条:① 页面显示的内容与现在的真实数据一致;② 合规用语(规则 1);③ 不向投资人暴露实现细节(规则 8)。*

## 已看

### 1. 开屏页 `looloomi.ai`(进入前的动画页)

- 🔴 **规则 8:页面 DOM 里嵌着「Discipline Surface」面板**,默认不展开,但源码公开可读。内容包括
  内部文件路径(`docs/LP_FACING_2026-08-08.md`、`tests/test_*.py`、`REFUTATION_LEDGER.md`)、
  commit 哈希、「修改措辞请联系 Jazz 论点,修改源真链请联系 Seth」、「MCP on deprecated HTTP+SSE transport」、
  「decisions 0 行, entities 1 行」。
- 🟡 **内容过期**:版本 2026-08-08;写着「①层已上线 1 天」「asset_embeddings_history 0 行 · risk_meter_history 0 行」
  —— 现在 ① 已 47 天,两张表都有数据。
- 🟡 「第一条方法论干净的前向曲线将于 2026 年 10 月初满 60 天」—— 与 ① 的实际起点(08-08)一致,10-07 左右满 60 天,是一个可以兑现的承诺,要确保届时页面能展示。

### 2. 落地页(点击进入后)

- 🟡 **过度承诺**:「CometCloud Protocol lets institutional capital restake … Transparent on-chain allocation — every position traceable
  to a CIS signal」「Vault infrastructure」—— vault 相关表全部 0 行,没有任何链上仓位。
- 🟡 **需要 Jazz 确认**:点名「Harvest Fund network and EST Alpha as founding institutional relationships」。
- 🟡 **无出处的数字**:「76% INSTITUTIONAL INVESTORS INCREASING CRYPTO EXPOSURE — 2025 survey data」
  「5% CONFIDENT IN BLOCKCHAIN RISK ASSESSMENT」。$30T(渣打 2034 预测)有出处。
- 🟡 「Not for traders chasing momentum」—— 与我们现在的交易主干(趋势规则)措辞上冲突,可改为强调纪律而非否定动量。
- ✅ 未见买卖类用语。页脚「© 2025」应更新。

### 3. 平台 `app.html` → CIS 排行榜

- ✅ 数据能加载(走 Jazz 网络;沙箱 IP 被限流,见 T-013),约 14 秒出数。API 全 200。
- 🟡 **首屏 14 秒的加载时间**,期间只有 「LOADING LEADERBOARD…」。
- 待核:徽章显示 **ESTIMATED**(T2);T1 已于 09-24 恢复但只覆盖 24 个加密标的(T-001)。
  回测条「30d realized returns by grade · Binance klines · 64 assets:A +4.09% / B +1.83% / C −1.28%」—— 数据源写的是 Binance,
  而 Binance 从 Railway 被地区封锁(NAV_POLICY),要查这条回测是什么时候、用什么数据算的。

### 4. 移动端 `app.html`(窄屏首屏:Pulse)

- 🔴 **宏观简报写「市场平静」,当天总市值 24h −6.4%** → 已修,T-017 / S-422。两条路都读错 24h 键;
  「距上份简报」的几分钟增量被当成市场状态。
- 🔴 **规则 1:Railway 兜底模板带仓位建议**(Accumulation zones / contrarian entry / Allocate / Reduce risk / positioning favoured),
  从不过 `validate_brief` → 已修,T-017。
- 🟡 RECENT SIGNALS:一行没有标的、四行全是 NEUTRAL —— feed 条目 direction 为 null,前端把缺失显示成 NEUTRAL,
  与上方 UNI 的 OUTPERFORM 冲突 → 已修,T-017(只在有值时显示方向,行标题改显示 headline)。
- 🟡 卡片文案「positions to outperform on **strong momentum**」旁边是 −7.45% / −8.98%。两者时间跨度不同(百分比是 24h),
  但读者看到的是矛盾。建议:卡片上的百分比标出跨度(24h),或叙事避免「strong momentum」这类与短期价格同屏会冲突的词。待开卡。
- 待核:顶栏「CIS LIVE · 58 assets」—— T1 只覆盖 24 个加密标的(T-001 未完),其余是 T2 估算。「LIVE」是否该拆成 T1/T2 计数。

## 路由审计(2026-09-26,本轮补充)

**SPA 入口只有一个:`/app.html`(2424 字节,加载 `assets/app-iOwRc3Gh.js`)。** Sidebar/SiteNav 全部 onNavigate 切 section,无独立 HTML。

### 死链(6 个静态 URL)

| URL | 状态 | 内容 |
|---|---|---|
| `/market.html` | 200 / 41121 | 落地页 |
| `/cis.html` | 200 / 41121 | 落地页 |
| `/vault.html` | 200 / 41121 | 落地页 |
| `/protocol.html` | 200 / 41121 | 落地页 |
| `/intelligence.html` | 200 / 41121 | 落地页 |
| `/quant-gp.html` | 200 / 41121 | 落地页 |

→ 全部转 T-021:删 OR 301→/app.html OR 410。

### 死 API(4 个 404,SPA 不调用)

| 路径 | SPA 是否调用 |
|---|---|
| `/api/v1/intelligence/signals` | ❌(SPA 用 `/api/v1/signals/feed`) |
| `/api/v1/vault/positions` | ❌(SPA 用 `/api/v1/trading/positions`) |
| `/api/v1/protocol/metrics` | ❌(SPA 用 `/api/v1/protocols/universe`) |
| `/api/v1/quant/gp-status` | ❌(QuantMonitor 用 `/api/v1/trading/metrics` + `/trading/positions` + `/trading/order`) |

→ 全部转 T-021:删 OR doc。

### SPA 实际调用的 API(全部 200,2026-09-26 验证)

```
/api/v1/cis/universe                       → 58 universe(data_source=null,见 T-023)
/api/v1/macro/brief                        → mb-3 内容(已修,T-017)
/api/v1/market/crowd-clock                 → CrowdClock widget
/api/v1/market/earnings-calendar           → EarningsCalendarWidget
/api/v1/signals/dingge-board               → DinggeBoard
/api/v1/signals/feed                       → SignalFeed
/api/v1/protocols/universe                 → ProtocolIntelligence
/api/v1/trading/metrics                    → QuantMonitor
/api/v1/trading/positions                  → QuantMonitor
/api/v1/trading/order                      → QuantMonitor
/api/v1/defi/overview                      → ProtocolIntelligence(TVL)
/api/v1/intelligence/macro-events          → IntelligencePage(VC Funding Flows)
/api/v1/market/economic-indicators         → MacroBrief 周边
```

### Section 路由(Sidebar.jsx,8 个)

`cis` / `intelligence` / `strategies` / `protocol` / `vault` / `quantgp` / `portfolio` / `api-keys` —— 全部由 SPA 客户端 onNavigate 切换。

## 6 页结论(走 SPA 路径)

### 1. CIS Engine(`/app.html` 默认)

- ✅ 数据加载(CIS universe 58,合规用语 OK)。
- 🟡 徽章颜色:全 ESTIMATED 灰;**T1/T2 不染色**(data_source=null)→ T-023。

### 2. Intelligence

- ✅ Macro brief 24h 变化对、零仓位建议(mb-3 验收已过)。
- ✅ Signal Feed 接 `/api/v1/signals/feed`,合规用语通过。
- 🟡 移动端 RECENT SIGNALS 卡片文案/百分比跨度冲突 → T-022。

### 3. Strategies / Research Desk(QuantGP)

- ✅ QuantMonitor 接 trading/positions/metrics/order,PAPER 仓位可见(2026-09-26 拉 POL/SOL 两条,unrealized +16.86% / +6.75%)。
- ✅ EstAlphaSection:内容已就位。

### 4. Protocols

- ✅ ProtocolIntelligence 接 `/api/v1/protocols/universe` + `/defi/overview`,DeFi TVL 正常。

### 5. Vault(`/app.html` + section `vault`)

- 🔴 **VaultInProgress 占位**(2026-08-19 Jazz:「内容下,放着进度页」)。
- 待 Jazz:是否解除(Vault 表全部 0 行,链上无仓位)。

### 6. Portfolio / API Keys

- 待核(本轮未走完)。

## 已转任务卡

- T-021:死链与遗留路由
- T-022:移动端 RECENT SIGNALS 卡片
- T-023:CIS universe Tier 标签

## 剩余未看

- Portfolio · API Keys · Portfolio Builder(`/portfolio.html`)· Score Analytics(`/analytics.html`)· Agent API(`/agent.html`)· Fund Strategy(`/strategy.html`)· 移动端 Rankings/Signal 屏
