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

## 待看

Intelligence · Strategies · Protocols · Vault · Research Desk · Portfolio · API Keys · Portfolio Builder ·
投资策略页 · MCP / agent 卡片 · 移动端其余两屏(Rankings / Signals)
