# Solana 代币化基金基础设施研究
**Date:** 2026-03-23
**研究范围:** Solana 生态 Fund Tokenization 开源组件

---

## 1. 开源基金/DeFi 协议（可 Fork/参考）

### 最佳匹配: Share-Based Vault Factory

**`fractal-protocol/solana-upshift-vault-programs`**
- **功能**: Operator 管理的代币化 vault，用户存入 SPL tokens 获得代表份额的 share tokens
- **架构**: Role-based（用户存取、Operator 提存、管理费用）
- **关键特性**:
  - Vault factory pattern（单程序多 vault）
  - Share-based 记账 + 比例赎回
  - 可配置赎回费用（防 sandwich）
  - 紧急暂停功能
  - PDA-based treasury
- **语言**: TypeScript (74.8%), Rust (15.6%)
- **链接**: https://github.com/fractal-protocol/solana-upshift-vault-programs

**结论：最接近基金代币化 vault factory，可 Fork 改编。**

---

### UXD Protocol (Delta-Neutral Stablecoin)

**`UXDProtocol/uxd-program`** (Business Source License 1.1)
- **功能**: 去中心化稳定币协议，通过 delta-neutral DEX 仓位对冲
- **组件**:
  - `Controller` — 顶层协议状态
  - `Depositories` — Identity, Mercurial Vault, Credix LP
  - 公开指令: `mint`, `redeem`, `collect_profits_of_*`, `rebalance_*`
- **Mainnet**: `UXD8m9cvwk4RcSxnX2HZ9VudQCEeDH6fRnB4CAP57Dr`
- **参考价值**: Depository pattern, controller pattern, CPI examples
- **链接**: https://github.com/UXDProtocol/uxd-program

---

### Credix LP Depository Pattern
- **功能**: 半流动性借贷 depository
- **链接**: https://github.com/UXDProtocol/uxd-client

---

### Token Lending (Aave-like, Archived)

**`solana-labs/solana-program-library/token-lending`** (Archived March 2025)
- 超级抵押借贷程序
- **参考价值**: Reserve-based 借贷架构
- **Devnet**: `6TvznH3B2e3p2mbhufNBpgSrLx6UkgvxtVQvopEZ2kuH`
- **链接**: https://github.com/solana-labs/solana-program-library/tree/master/token-lending

---

### Royalty Tokenization (Music/Revenue Share)

**`vvizardev/spotify-loyalty-program-solana`** (35 stars)
- **功能**: 艺术家将未来版权收入代币化；粉丝购买代表比例收益的 tokens
- **架构**: Anchor (Rust) + Express backend + React frontend
- **关键模式**: `initialize_project`, `buy_tokens`, `distribute_royalties`, `claim_royalties`
- **Oracle 集成**: Spotify API 自动分发
- **参考价值**: 向 token 持有者分发收益，按比例计算
- **链接**: https://github.com/vvizardev/spotify-loyalty-program-solana

---

## 2. SPL Token-2022 实现

### Token-2022 核心仓库

**`solana-program/token-2022-program`** (183 stars)
- **位置**: https://github.com/solana-program/token-2022-program
- **包含**: Token-2022 on-chain program + JS/Rust clients
- **可用扩展**:
  - Transfer Fee（可配置转账手续费）
  - Transfer Hook（每次转账自定义验证）
  - Confidential Transfers（隐私转账）
  - Token Metadata
  - Token Groups
  - Mint/Account-Level Default Accounts

---

### Transfer Fee Extension
- 可配置 basis point 手续费，每次转账自动扣费
- 费用转入预设账户（如 protocol treasury）
- **Token-2022 原生支持**

---

### Transfer Hook Extension
- 自定义程序通过 CPI 验证每次转账
- 用于 KYC 检查、合规、转账限额
- **需要单独部署外部 hook 程序**
- **KYC 实现示例**: `mitgajera/Token2022-Hook-AMM` (HookSwap) - KYC-gated AMM
- **链接**: https://github.com/mitgajera/Token2022-Hook-AMM

---

### KYC/Compliance on Token-2022

**`Gitdigital-products/solana-kyc-compliance-sdk`** (3 stars)
- 开源 SDK，使用 Transfer Hook & Permanent Delegate 实现 KYC/AML
- 组件: Rust on-chain programs, TypeScript SDK, Compliance Registry
- **链接**: https://github.com/Gitdigital-products/solana-kyc-compliance-sdk

---

## 3. Anchor 框架示例

### Vault + Token Factory 参考

**`klaim-dev/solana-programs`** (1 star)
- Anchor programs 包括:
  - `vault` — 通过 PDA 存取 SOL "PDA signer, lamport transfer, events"
  - `token_factory` — 创建/管理 SPL tokens: "SPL Token, ATA, mint/transfer/burn/freeze"
  - `counter`, `todo`, `tip_jar`, `airdrop`
- **Devnet 已部署**
- **链接**: https://github.com/klaim-dev/solana-programs

---

### Escrow Pattern (最多 Stars)

**`ironaddicteddog/anchor-escrow`** (196 stars)
- 教育用 escrow 实现，使用 PDA
- 关键模式: Vault Authority PDA 直接创建 associated token accounts
- **链接**: https://github.com/ironaddicteddog/anchor-escrow

---

## 4. 投资者白名单/KYC On-Chain 模式

### Whitelist-Gated Token Sale

**`smartstache/doorman`** (59 stars) — 最多 stars 的 whitelist 程序
- Candy machine whitelist: 用户支付 SOL 购买 mint tokens
- 可配置: 上线日期、whitelist 地址、 SOL 费用、 treasury
- **限制**: ~300-1111 条目（账户大小限制）
- **链接**: https://github.com/smartstache/doorman

---

### Advanced Tokenomics with Whitelisting

**`yllvar/my-anchor-token`** (2 stars)
- 转让税、whitelisting、流动性池功能
- **链接**: https://github.com/yllvar/my-anchor-token

---

### KYC Compliance SDK (Token-2022 Transfer Hook)

**`Gitdigital-products/solana-kyc-compliance-sdk`** (3 stars)
- On-chain KYC/AML 通过 Token Extensions (Transfer Hook + Permanent Delegate)
- 每个用户和 mint 的转账限额
- **链接**: https://github.com/Gitdigital-products/solana-kyc-compliance-sdk

---

### HookSwap - KYC-Gated AMM

**`mitgajera/Token2022-Hook-AMM`** (0 stars)
- 使用 Token-2022 transfer hooks 进行 KYC 合规的 AMM
- 每次转账通过 hook 程序验证
- **链接**: https://github.com/mitgajera/Token2022-Hook-AMM

---

## 5. Custody/Vault/Multisig 模式

### Multisig Vault

**`imclint21/held-cash`** (0 stars)
- Multisig vault & escrow 程序
- 可配置 cosigners、必需签名数
- **链接**: https://github.com/imclint21/held-cash

---

### Recoverable Custody Authority

**`sebscholl/custody-authority-program`** (0 stars)
- 安全存储 tokens 的 vault，支持便捷签名/转移
- 智能账户和多签钱包实验
- **链接**: https://github.com/sebscholl/custody-authority-program

---

## 6. 可通过 API 集成 vs 必须自建

### 可作为托管 API/SDK

| 服务 | 用途 | 链接 |
|------|------|------|
| **StreamFlow** | Token vesting, streaming payments, airdrops | https://docs.streamflow.finance |
| **CoinGecko** | 价格数据（已在用） | 已集成 |
| **DeFiLlama** | TVL 数据（已在用） | 已集成 |

---

### 必须自建

| 组件 | 原因 |
|------|------|
| Fund vault factory | 无精确匹配开源实现。最佳参考: fractal-protocol/upshift-vault (fork and adapt) |
| Investor whitelist/KYC | Doorman 面向 NFT；KYC SDK 较新/最小实现。需用 Token-2022 transfer hooks 自建 |
| 向股东分发利润 | 无直接匹配。Spotify royalty pattern 最接近 - fork and adapt |
| Fund share token (Token-2022 + transfer fee) | Token-2022 扩展本身可用；费用分发自定义逻辑需构建 |
| On-chain 合规检查 | 使用 Token-2022 transfer hook 接口，但需实现自定义 hook 程序 |

---

## 7. 总结表

| 类别 | 存在（Fork/参考） | 需自建 | API 服务 |
|------|-------------------|--------|----------|
| Vault Factory | `fractal-protocol/upshift-vault` | 适配基金运营 | - |
| Share Token (可转让) | SPL Token-2022 | 添加 transfer fees | - |
| 投资者白名单 | `doorman`, `solana-kyc-compliance-sdk` | 适配 KYC | - |
| 利润分发 | `spotify-loyalty` (royalty pattern) | 适配基金分红 | - |
| Custody/Multisig | `held-cash`, `custody-authority` | 适配基金角色 | - |
| Token-2022 Transfer Fee | Token-2022 原生 | 按基金配置 | - |
| KYC on Transfers | `solana-kyc-compliance-sdk` | 实现 hook | - |
| Vesting/Streaming | - | - | StreamFlow SDK |
| 价格数据 | - | - | CoinGecko (在用) |
| TVL 数据 | - | - | DeFiLlama (在用) |

---

## 8. 关键推荐

1. **Fork `fractal-protocol/solana-upshift-vault-programs`** — 最完整的 vault factory 模式。将 operator role 改为 fund manager，添加利润分发逻辑。

2. **使用 Token-2022 作为 fund shares** — 原生 transfer fee extension + 自定义 transfer hook 用于 KYC/whitelist。**不要**自己实现 token 程序。

3. **合规层作为 Anchor transfer hook 构建** — 使用 `solana-kyc-compliance-sdk` 作为 hook 接口参考，实现自定义 KYC registry。

4. **改编 `spotify-loyalty-program-solana` 用于利润分发** — 向股东分发收益/利润与向艺术家分发版权费模式相同。

5. **使用 `ironaddicteddog/anchor-escrow`** 作为 PDA-based vault 逻辑参考，包含正确的账户验证。

---

## 参考链接汇总

| 项目 | 用途 | URL |
|------|------|-----|
| Fractal upshift vault | Vault factory 参考 | https://github.com/fractal-protocol/solana-upshift-vault-programs |
| UXD Protocol | Depository 参考 | https://github.com/UXDProtocol/uxd-program |
| Spotify loyalty | 收益分发参考 | https://github.com/vvizardev/spotify-loyalty-program-solana |
| Token-2022 | 代币标准 | https://github.com/solana-program/token-2022-program |
| KYC SDK | 合规参考 | https://github.com/Gitdigital-products/solana-kyc-compliance-sdk |
| HookSwap | KYC AMM 参考 | https://github.com/mitgajera/Token2022-Hook-AMM |
| Anchor escrow | PDA vault 参考 | https://github.com/ironaddicteddog/anchor-escrow |
| Doorman | Whitelist 参考 | https://github.com/smartstache/doorman |
| StreamFlow | Streaming API | https://docs.streamflow.finance |
| Squads multisig | 多签治理 | https://github.com/Squads-Protocol/squads-mpl |
