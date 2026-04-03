# Fund Factory — Solana Tokenized Fund Infrastructure

**Status:** Phase 1, Task 1.2 — In Development
**Network:** Solana (Devnet → Testnet → Mainnet)
**Language:** Rust (Anchor framework 0.30+)

---

## Overview

Fund Factory enables Quant GPs to **one-click deploy tokenized funds on Solana**.

- GP creates an on-chain fund with configurable fee structures
- Investors deposit USDC → receive fund share tokens (Token-2022)
- GP updates NAV on-chain via oracle
- Investors redeem shares → receive USDC proportional to NAV

---

## Architecture

```
Investor                    Fund Factory Program
   │                               │
   ├──deposit(USDC)───────────────►│
   │                               ├──Mint fund shares
   │◄────fund_token_account─────────┤
   │                               │
   │redeem(fund_tokens)────────────►│
   │                               ├──Burn fund tokens
   │◄────USDC from vault───────────┤
```

---

## Program Structure

```
programs/
└── fund_factory/
    ├── src/
    │   ├── lib.rs              # Program entry point
    │   ├── state.rs            # Account types
    │   ├── error.rs            # Error codes
    │   └── instructions/
    │       ├── mod.rs
    │       ├── factory.rs      # initialize_factory
    │       ├── create_fund.rs  # create_fund
    │       ├── deposit.rs      # deposit
    │       ├── redeem.rs       # redeem
    │       ├── update_nav.rs   # update_nav
    │       ├── set_whitelist.rs # whitelist management
    │       └── pause.rs        # pause/resume
    └── tests/
        └── fund_factory.ts     # Integration tests
```

---

## Account PDAs

| Account | PDA Seed |
|---------|----------|
| Factory | `["factory"]` |
| Fund | `["fund", fund_id.to_le_bytes()]` |
| FundVault | `["fund", fund_id, "vault"]` |
| InvestorPosition | `["fund", fund_id, "position", investor]` |
| WhitelistEntry | `["fund", fund_id, "whitelist", investor]` |

---

## Instructions

| Instruction | Authority | Description |
|-------------|-----------|-------------|
| `initializeFactory` | deployer | Initialize factory singleton |
| `createFund` | GP | Create new fund with params |
| `deposit` | investor | Deposit USDC, receive shares |
| `redeem` | investor | Burn shares, receive USDC |
| `updateNav` | GP | Update fund NAV |
| `setWhitelist` | GP | Add/remove investor whitelist |
| `pause` | GP | Pause fund operations |
| `resume` | GP | Resume fund operations |

---

## Deployment

```bash
# Devnet
anchor build
anchor deploy --provider.cluster devnet

# Testnet (after audit)
anchor deploy --provider.cluster testnet

# Mainnet (after security audit)
# Hardware wallet required for mainnet deploy
```

---

## Reference Implementations

- Vault Factory: [fractal-protocol/upshift-vault](https://github.com/fractal-protocol/solana-upshift-vault-programs)
- Token-2022: [solana-program/token-2022-program](https://github.com/solana-program/token-2022-program)
- Escrow Pattern: [ironaddicteddog/anchor-escrow](https://github.com/ironaddicteddog/anchor-escrow)
- KYC Transfer Hook: [Gitdigital-products/solana-kyc-compliance-sdk](https://github.com/Gitdigital-products/solana-kyc-compliance-sdk)

---

## Security

| Component | Classification |
|-----------|---------------|
| Program deployment | LOCAL (hardware wallet) |
| Program upgrade | HYBRID (timelock multisig) |
| Mint authority | LOCAL → PDA (never single-sig after init) |
| GP privileged ops | LOCAL (hardware wallet) |
| Treasury | MULTISIG (Squads Protocol) |

---

*Build things that feel alive.*
