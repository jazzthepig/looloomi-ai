# 产品落地与开发建议
**日期：** 2026-03-30
**状态：** 已验证 Railway CIS 数据恢复（T2, 70 assets）

---

## 当前真实状态

### 已可用
- Railway CIS 数据（T2 Railway，70 assets，真实数据）
- Strategy.html（静态展示 + 真实回测）
- Signal Feed（实时信号）
- Freqtrade dry run（Mac Mini 上周跑起来了）
- Lead capture + wallet auth 后端（build 完成，Supabase 未接通）
- ScoreAnalytics（build 完成，未开箱验证）

### 在修/未接通
- Supabase env vars（Wallet auth + Lead capture 数据没有落地）
- Mac Mini T1 push（v4.1 代码已 apply，但正常推送需要验证）

### 未启动（机构可投资前提）
- Vault 合约审计（Certik）
- 独立基金审计（Armanino/Cohen）
- SFC 合规状态明确
- 机构托管结构

---

## 实用 vs 理想对比

| 功能 | 实用状态（现在能跑） | 理想状态（机构可投资） |
|------|---------------------|----------------------|
| CIS 数据 | T2 Railway 已够展示用 | T1 Mac Mini push 才算完整 |
| Vault | 没有真实合约 | Certik 审计后才有效 |
| 净值记录 | 无 | 需要 12 个月实盘 + 第三方审计 |
| KYC/AML | 无 | 需要持牌机构处理 |
| 托管 | 无 | 需要机构级托管行 |

**核心结论：实用状态和理想状态之间，不是"还有多少功能要做"，而是"需要多少时间积累信任"。**

---

## 实用状态建议（本周可完成）

### 产品侧

| 行动 | 收益 | 负责方 |
|------|------|-------|
| 接通 Supabase env vars | Wallet auth + Lead capture 数据落地，email 功能可用 | Jazz |
| ScoreAnalytics 开箱验证 | 评分迁移热力图真实运行，证明系统在记录历史 | Seth |
| CIS Leaderboard 截图 + 导出 | Nic 带去见家办的人有真实数据 | Seth |
| Lead capture 落地页加 CTA | "获取完整报告" → email capture | Seth |
| Strategy.html 加上"T2 数据说明" | 机构看到数据来源，消除疑虑 | Seth |

### 渠道侧

| 行动 | 收益 | 负责方 |
|------|------|-------|
| DD 报告精缩成一页 exec summary | Nic 可以发给潜在 LP，30 秒说明我们在做什么 | Seth |
| Nic 用现有材料约 1-2 个真实接触 | 收集真实反馈，不是闭门造车 | Nic |

---

## 理想状态建议（机构 LP 最低要求）

| 要求 | 当前状态 | 距离开工 | 实际瓶颈 |
|------|---------|---------|---------|
| 12 个月可验证净值 | 0 | 需要实时跑 12 个月 | Freqtrade dry run 上周才开始 |
| Vault 合约审计 | 无 | Certik 询价中 | Jazz 需要主动推进 |
| 独立基金审计 | 无 | 需要找 Armanino/Cohen | Jazz 需要主动推进 |
| SFC 合规状态 | 未明确 | 咨询合规顾问 | Jazz 需要决策时间线 |
| 托管结构 | 无 | 需要确定托管行 | Jazz + Nic 需要建立关系 |

---

## 渠道策略建议

### 优先目标：HNW 个体（不是机构 FO/FOF）

**为什么 HNW > 机构 FO：**
- HNW 个体可以接受私募结构（不需要 SFC 牌照）
- 投资决策周期短（2-4 个月 vs 9-18 个月）
- 资金规模 $50-500K，对托管要求低
- 更容易成为第一批真实用户，为后续机构背书

**Nic 需要回答的问题：**
1. 他的网络里，有没有 2-3 个有 crypto 配置意愿的 HNW 个体？
2. 他们每个人能投多少？
3. 他们的决策速度通常多快？

### 战略调整

把"机构 LP"的目标，从"说服他们投资"降级为"收集他们的拒绝理由"。

三级尽调报告的价值，不在于告诉我们该做什么，而在于告诉我们**哪些事情在没有 12 个月业绩的情况下做不了**。Nic 收集的每一个拒绝理由，都是下一版产品迭代的输入。

---

## 本周行动清单

### Jazz 优先

| 优先级 | 行动 | 时间 |
|--------|------|------|
| 🔴 最高 | 接通 Supabase env vars | 10min |
| 🔴 最高 | 联系 Certik 询价 Vault 审计 | 30min |
| 🟡 其次 | 确认 SFC 合规状态 memo | 2h |

### Seth 本周

| 优先级 | 行动 |
|--------|------|
| 🔴 最高 | ScoreAnalytics 开箱验证 |
| 🔴 最高 | DD 报告精缩成一页 exec summary |
| 🟡 其次 | Strategy.html T2 数据说明 |
| 🟡 其次 | Lead capture CTA 优化 |

### Nic 本周

| 优先级 | 行动 |
|--------|------|
| 🔴 最高 | 用真实材料约 1-2 个接触 |
| 🟡 其次 | 收集反馈，整理拒绝理由 |

---

## A2A 合作可能性（CEX）

CEX 合作比直接打机构更可行：

| 合作类型 | 条件 | 收益 |
|---------|------|------|
| 用户导流 | LP 通过 CEX 出入金，手续费返佣 | 增量用户 |
| 资产端合作 | Vault 配置 OSL，CEX 提供流动性 | TVL 贡献 |
| 技术对接 | API 延迟测试 + 合约审计 | 建立信任 |

**前提：Vault 合约通过 Certik 审计（目前是阻断项）**

---

*供 Jazz + Claude Cowork 内部参考*
