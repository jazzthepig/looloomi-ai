# Fund Factory 安全架构研究
**Date:** 2026-03-23
**研究范围:** 链上基金发行平台的 LOCAL vs CLOUD 安全边界

---

## 核心理念

> **任何能掏空 vault 的组件必须要求硬件签名，永不让软件密钥接触网络。**

---

## 组件安全分类

### 1. 智能合约/程序部署

| 方面 | 分类 | 理由 |
|------|------|------|
| **程序构建 (CI/CD)** | CLOUD_OK | 构建是确定性的；`cargo build-bpf` 给定相同源码产生相同产物。构建产物部署前哈希验证。 |
| **程序部署 (create_program_address)** | LOCAL | **部署密钥**（fee payer + program authority）绝不接触联网机器。使用气隙硬件钱包或 HSM。 |
| **程序升级权限** | HYBRID | 程序 authority 密钥存储在 HSM/Ledger；升级需要物理 YubiKey 确认或 3-of-5 多签。Cloud agents 可准备升级 tx 但不能签名。 |
| **程序 authority 密钥存储** | LOCAL | 私钥必须在气隙硬件上。即使加密静态存储也不够（机器有网络访问）。 |

**密钥管理流程:**
```
Developer → GitHub (code)
         → CI/CD (build, produce artifact hash)
         → Artifact hash signed by release manager
         → Air-gapped machine pulls artifact, verifies hash
         → Hardware wallet signs deployment tx
         → Signed tx submitted from air-gapped env
```

---

### 2. 基金创建 (`create_fund` instruction)

| 方面 | 分类 | 理由 |
|------|------|------|
| **指令解析/验证** | CLOUD_OK | 公开指令数据可在任何地方验证。 |
| **基金配置创建 (name, rules, whitelist)** | CLOUD_OK | 数据准备可基于云端。 |
| **基金 vault 初始化 (create PDA + mint)** | LOCAL | 首次 vault 创建是托管事件。GP 必须用硬件密钥签名以建立基金的规范所有权。 |
| **基金 authority 分配** | HYBRID | Fund authority 可以是 on-chain 治理控制的多签 PDA，而非单个 EC 密钥。 |

---

### 3. 存款处理

| 方面 | 分类 | 理由 |
|------|------|------|
| **存款指令解码** | CLOUD_OK | 只读解析。 |
| **存款金额验证 (KYC check)** | CLOUD_OK | Cloud backend 验证投资者在白名单且通过 KYC/AML。 |
| **Vault 入账 (transfer USDC to fund vault)** | HYBRID | 使用预签名交易或 vault operator 多签。不能被单一 cloud bot 自动化。 |
| **Fund token minting (mint_to)** | LOCAL | Fund tokens 的 minting authority 必须是硬件控制。过度 minting 是主要掏空向量。 |

**流程:**
```
Investor → Frontend → Cloud API (validate KYC, check whitelist)
                              ↓
                       Prepare deposit tx
                              ↓
                       GP hardware sign (or scheduled multisig sweep)
                              ↓
                       USDC transferred to vault
                              ↓
                       Fund tokens minted (LOCAL key) → investor wallet
```

---

### 4. 赎回处理

| 方面 | 分类 | 理由 |
|------|------|------|
| **赎回请求解码** | CLOUD_OK | 只读。 |
| **KYC/AML 重新验证** | CLOUD_OK | 可基于云端+审计日志。 |
| **NAV 计算** | CLOUD_OK | 计算密集型，需要价格 oracle 数据。 |
| **赎回 tx 执行** | LOCAL | burn fund tokens + 从 vault 转 USDC。必须有硬件签名或 timelock 多签。 |
| **利润分发 (carry)** | LOCAL | GP carry 是财务敏感操作。必须有显式硬件签名，不能自动化。 |

**关键:** 赎回是主要掏空攻击面。即使其他都是 cloud，赎回执行密钥也必须 LOCAL/HSM。

---

### 5. NAV Oracle 更新

| 方面 | 分类 | 理由 |
|------|------|------|
| **价格馈送聚合 (DeFiLlama, CoinGecko)** | CLOUD_OK | 公开数据，无安全敏感性。 |
| **Oracle 更新交易签名** | HYBRID | Oracle 更新应使用**阈值多签**（如 2-of-3 oracles 不同来源）。单一 cloud oracle key 是操纵向量。 |
| **Program-derived oracle authority** | LOCAL | 如果程序本身签署 oracle 更新，oracle 签名密钥必须 LOCAL。 |

**攻击向量（如果 Cloud）:** 被破坏的 cloud oracle key 可能报告虚假 NAV，导致可提取超过基金实际持有的 USDC（"无限钱"攻击）。

---

### 6. GP 授权操作

| 方面 | 分类 | 理由 |
|------|------|------|
| **权限策略定义** | CLOUD_OK | 元数据；非敏感。 |
| **权限检查 (on-chain)** | CLOUD_OK | 智能合约强制执行；无需信任。 |
| **GP 特权操作 (pause fund, update fee)** | LOCAL | GP 的特权密钥绝不接触联网机器。这是可以冻结投资者资金的"上帝模式"操作。 |
| **时间锁定 GP 操作 (change whitelist)** | HYBRID | 可为 timelock 多签（如 24h 延迟 + 2-of-3 GP 密钥）。Cloud agent 发起 timelock；实际执行需 LOCAL 签名。 |

---

### 7. 投资者 KYC/AML

| 方面 | 分类 | 理由 |
|------|------|------|
| **KYC 文档收集** | CLOUD_OK | 标准 web app；数据应加密静态存储。 |
| **KYC 验证逻辑** | CLOUD_OK | 可使用第三方 KYC 提供商 (Jumio, Onfido)。 |
| **KYC 状态 on-chain (whitelist 写入)** | HYBRID | 白名单更新是特权写入。预授权白名单可由硬件签名；批量添加可用多签。 |
| **制裁筛查** | CLOUD_OK | 实时筛查 OFAC 列表可基于云端 (Morningstar, Chainalysis)。 |

**注意:** KYC 数据是 PII，通常受监管（GDPR、香港 PDPO）。Cloud 提供商必须对 HK/SG 机构情境适用。

---

### 8. Token Minting Authority

| 方面 | 分类 | 理由 |
|------|------|------|
| **Fund token mint** | LOCAL | Mint authority 密钥是系统中最危险的密钥。泄露 = 无限 fund tokens。 |
| **Mint freeze authority** | LOCAL | 冻结转账能力（监管要求）需要 LOCAL 硬件密钥。 |
| **Token metadata 更新** | CLOUD_OK | 非关键；可用标准多签。 |

---

### 9. Fund Assets 托管

| 方面 | 分类 | 理由 |
|------|------|------|
| **Vault 中 USDC custody (program-controlled)** | HYBRID | Vault 是 PDA，由 Anchor 程序控制。没有单个密钥能掏空——只有程序逻辑。这是最安全的架构。 |
| **中间账户中的 USDC custody** | LOCAL | 任何在 sweep 到 vault 前积累存款的 staging wallet 需要硬件密钥控制。 |
| **托管审计/日志** | CLOUD_OK | 所有托管事件应记录到不可变存储（只读 cloud）。 |

---

## Oracle/馈送签名密钥

| Oracle 类型 | 密钥位置 | 理由 |
|------------|---------|------|
| **价格 oracle (DeFiLlama, etc.)** | 数据聚合 CLOUD_OK；**签名 LOCAL** 如果 on-chain oracle | 价格数据是公开的；on-chain oracle 签名者 (Pyth, Switchboard) 必须安全。 |
| **Oracle 更新交易** | HYBRID (多签 oracles 2-of-3) | 单一 cloud oracle = 单点故障/操纵。 |
| **汇率馈送** | CLOUD_OK (仅数据) | 数据本身不敏感；on-chain 交付的签名才是安全边界。 |

---

## Cloud Agents 的多签处理

Cloud agents **可在严格条件下**处理多签：

```
可接受的 CLOUD 多签:
- n-of-n 多签，所有密钥都是硬件支持（cloud agent 仅编排，不签名）
- timelock 多签（cloud 发起，硬件密钥在延迟后确认）
- policy-gated 多签（cloud 提案，GP 硬件密钥批准）

不可接受:
- 单个 cloud 密钥拥有任何 vault 上的 admin 权限
- 可单方面更改基金参数的 cloud 密钥
- 可暂停/恢复基金而无需延迟的 cloud 密钥
```

---

## 风险矩阵

### 如果组件运行在 Cloud（违规）

| 组件 | Cloud-only 风险 | 严重性 |
|------|----------------|--------|
| **Mint authority on cloud** | 恶意员工或泄露 API key → 无限 token mint → 掏空 USDC vault | CRITICAL |
| **Withdrawal signing on cloud** | 攻击者入侵 cloud → 直接掏空投资者资金 | CRITICAL |
| **GP privileged keys on cloud** | 内部威胁 → 冻结基金、重定向费用、修改白名单 | CRITICAL |
| **Oracle signing key on cloud** | 价格操纵 → 虚假 NAV → 过度提取 | HIGH |
| **Deploy key on cloud** | 攻击者部署恶意升级 → 窃取所有 vault USDC | CRITICAL |
| **Program upgrade on cloud** | 同 deploy key — 完全 vault 妥协 | CRITICAL |
| **KYC data on cloud** | 数据泄露 → 监管违规 + 声誉损失 | HIGH |
| **Custody sweep key on cloud** | 中间账户被掏空 | HIGH |

### 如果组件是 LOCAL/HYBRID（安全）

| 组件 | 获得保护 |
|------|---------|
| **Vault as PDA** | 程序逻辑控制所有赎回；无单个密钥可提取 |
| **Hardware mint authority** | 物理密钥要求 token minting |
| **Timelock multisig** | 特权操作 24h 延迟；鲸鱼监控可干预 |
| **n-of-m GP multisig** | 无单点妥协 |

---

## 推荐安全模型

```
┌─────────────────────────────────────────────────────────────────────┐
│                        FRONTEND (Browser)                           │
│   Wallet connection: ALWAYS user-side (Phantom, Backpack, Ledger)  │
│   Fund Deploy Wizard: validates inputs, prepares txs               │
└─────────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     CLOUD / RAILWAY (Public)                        │
│                                                                      │
│  ✓ KYC/AML verification logic          ✓ Price feed aggregation    │
│  ✓ Investor whitelist management       ✓ NAV calculation          │
│  ✓ Deposit/withdrawal request queue   ✓ Oracle data ingestion     │
│  ✓ Transaction construction            ✓ Audit logging             │
│  ✓ Program state queries              ✓ Non-custodial UI           │
│                                                                      │
│  ✗ CANNOT: sign any transaction that moves funds                   │
│  ✗ CANNOT: mint fund tokens                                     │
│  ✗ CANNOT: execute withdrawals                                  │
│  ✗ CANNOT: upgrade programs                                     │
└─────────────────────────────────────────────────────────────────────┘
                                 │
                    ┌────────────┴────────────┐
                    ▼                         ▼
┌─────────────────────────────────┐  ┌─────────────────────────────────┐
│   LOCAL / AIR-GAPPED (GP)      │  │   ON-CHAIN PROGRAM (Vault)      │
│                                 │  │                                 │
│  Hardware Wallet / Ledger        │  │  Fund PDA (Program Authority)  │
│  - Mint authority key            │  │  - Only programmable logic      │
│  - GP privileged action keys    │  │    can move USDC               │
│  - Withdrawal execution keys    │  │  - No single key can drain     │
│  - Program upgrade keys         │  │  - All ops require sigs        │
│                                 │  │    from defined signers        │
│  Physical YubiKey for          │  │                                 │
│  multisig confirmation          │  │                                 │
└─────────────────────────────────┘  └─────────────────────────────────┘
                    │                         ▲
                    │                         │
                    ▼                         │
┌─────────────────────────────────┐            │
│   ORACLE / FEED LAYER           │            │
│                                   │            │
│  2-of-3 independent sources      │            │
│  (DeFiLlama + CoinGecko +        │────────────┘
│   Binance via CCXT)               │
│  Signing keys on HSM              │
└─────────────────────────────────┘
```

---

## 组件分类汇总表

| 组件 | LOCAL_REQUIRED | CLOUD_OK | HYBRID |
|------|:---:|:---:|:---:|
| Program build (CI/CD) | | ✓ | |
| Program deployment | ✓ | | |
| Program upgrade authority | | | ✓ (timelocked) |
| Fund creation instruction | ✓ (finalize) | ✓ (prepare) | |
| Deposit processing | ✓ (vault credit) | ✓ (KYC, queue) | |
| Withdrawal execution | ✓ | | |
| NAV oracle updates | | | ✓ (multisig oracles) |
| Profit distribution | ✓ | | |
| GP privileged ops | ✓ | | |
| Investor KYC/AML | | ✓ | |
| Token minting | ✓ | | |
| Token metadata | | | ✓ (multisig) |
| Custody sweep | ✓ | | |
| Oracle signing | | | ✓ (2-of-3 HSM) |
| Wallet connection | ✓ (user-side) | | |

---

## 关键安全原则

1. **Vault as Program (PDA)** — Vault 必须是 PDA，由 Anchor 程序逻辑独占控制。永远不应有 EC 密钥直接访问 USDC 资金。这完全消除了"热钱包"问题。

2. **Mint authority is sacred** — Fund token mint 密钥必须在硬件上（Ledger Stax 或等价物），存储在保险箱中。绝不放在有网络访问的机器上，即使加密也不行。

3. **GP keys never touch the internet** — GP 的特权签名密钥应仅连接用于基金操作的专用气隙笔记本电脑。不是用于 email/Slack 的同一台机器。

4. **Time-locks on all privileged operations** — GP 特权操作（暂停、白名单变更、费用更新）24h timelock + 监控告警。Cloud agents 可提案；硬件密钥必须等待延迟。

5. **Defense in depth** — 即使 cloud 被入侵，架构也应要求硬件密钥进行任何基金移动。Cloud 可准备、排队和监控——但永不执行。

6. **Oracle manipulation defense** — NAV oracle 应使用 3 个独立源的阈值多签，有偏差检查（如果价格在 5 分钟内移动 >2%，暂停赎回）。

7. **Fund recovery** — 使用 Shamir's Secret Sharing (SSS) 分割种子短语（3-of-5），分配给：GP (2)、法律顾问 (1)、独立董事 (1)、机构托管人 (1)。无单一实体可单独恢复。

---

## 可实现技术栈

- **Candy Machine** 风格 upgradeauthority + timelock
- **Locked minting** via `TokenInstructions::MintTo` + 硬件密钥
- **Vault PDA** 作为 USDC custody 端点
- **Pyth** 或 **Switchboard** 用于 oracle 馈送 + 多签中继
- **Squads** 或 **Realms** 治理用于 on-chain 多签
