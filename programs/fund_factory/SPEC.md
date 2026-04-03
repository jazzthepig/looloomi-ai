# Fund Factory Program — SPEC.md
**Date:** 2026-03-24
**Version:** 1.0
**Phase:** Phase 1, Task 1.2
**Reference:** Fork of `fractal-protocol/solana-upshift-vault-programs`

---

## 1. Overview

**Program Name:** `fund_factory`
**Network:** Solana (Devnet → Testnet → Mainnet)
**Language:** Rust (Anchor framework 0.30+)
**Token Standard:** SPL Token-2022 (Fund Shares)

**Core Functionality:**
- GP (General Partner) creates on-chain tokenized funds
- Investors deposit USDC → receive fund share tokens (1 token = 1 share)
- GP manages fund NAV, distributes profits
- Investors redeem shares → receive USDC proportional to NAV

---

## 2. Architecture

### 2.1 Account Structure

```
Fund (PDA: [factory, fund_id])
├── fund_id: u32
├── name: String (max 32 chars)
├── symbol: String (max 8 chars)
├── fund_mint: Pubkey (Token-2022)
├── base_currency: Pubkey (USDC mint)
├── nav: u64 (current NAV in base_currency units × 1e6)
├── total_shares: u64 (outstanding fund tokens)
├── gp_authority: Pubkey
├── treasury: Pubkey (fee collection)
├── management_fee_bps: u16 (e.g., 200 = 2%)
├── performance_fee_bps: u16 (e.g., 2000 = 20%)
├── min_investment: u64 (lamports)
├── max_investment: u64
├── is_paused: bool
├── created_at: i64
└── bump: u8

FundVault (PDA: [fund, vault_seed])
├── fund: Pubkey
├── currency_vault: Pubkey (USDC ATA)
└── bump: u8

InvestorPosition (PDA: [fund, investor])
├── fund: Pubkey
├── investor: Pubkey
├── shares: u64
├── last_nav: u64 (nav at last interaction)
├── cumulative_fees: u64
└── bump: u8

Whitelist (PDA: [fund, investor])
├── fund: Pubkey
├── investor: Pubkey
├── kyc_level: u8 (0=none, 1=accredited, 2=institutional)
├── is_active: bool
├── added_at: i64
└── bump: u8
```

### 2.2 PDA Seeds

```rust
// Fund PDA
["factory", "fund", fund_id.to_le_bytes()] → Fund

// Fund Vault PDA
["factory", "fund", fund_id.to_le_bytes(), "vault"] → FundVault

// Investor Position PDA
["factory", "fund", fund_id.to_le_bytes(), "position", investor.as_ref()] → InvestorPosition

// Whitelist Entry PDA
["factory", "fund", fund_id.to_le_bytes(), "whitelist", investor.as_ref()] → Whitelist
```

---

## 3. Instructions

### 3.1 `create_fund`

**Authority:** GP (signer)
**Accounts:**
- factory (PDA)
- fund (PDA, mutable)
- fund_vault (PDA, mutable)
- fund_mint (Token-2022 mint, mutable)
- base_currency_mint (USDC)
- gp_authority (signer)
- treasury (fee recipient)
- rent_sysvar
- token_program
- associated_token_program
- system_program

**Params:**
```rust
struct CreateFundParams {
    fund_id: u32,
    name: String,       // max 32
    symbol: String,     // max 8
    management_fee_bps: u16,
    performance_fee_bps: u16,
    min_investment: u64,
    max_investment: u64,
}
```

**Logic:**
1. Validate fee parameters (0 ≤ fee ≤ 10000 bps)
2. Derive fund PDA, vault PDA, mint PDA
3. Create Token-2022 mint with:
   - Transfer fee extension (configurable)
   - Mint authority = fund_mint PDA
   - Freeze authority = None (or LOCAL hardware wallet)
4. Create fund vault ATA for USDC
5. Initialize fund account with params
6. Emit `FundCreated` event

### 3.2 `deposit`

**Authority:** Investor (signer)
**Pre-conditions:**
- Fund not paused
- Investor whitelisted (kyc_level ≥ 1)
- Within investment limits

**Accounts:**
- fund (PDA, immutable)
- fund_vault (PDA, mutable)
- investor_position (PDA, mutable)
- investor_whitelist (PDA, immutable)
- investor_base_currency_account (ATA)
- investor_fund_token_account (ATA)
- fund_mint (mutable)
- base_currency_mint
- investor (signer)
- rent_sysvar
- token_program
- associated_token_program
- system_program

**Params:**
```rust
struct DepositParams {
    base_currency_amount: u64,  // amount in lamports-like units
}
```

**Logic:**
1. Validate whitelist status
2. Calculate shares to mint: `amount / nav`
3. If first deposit, create investor_position
4. Transfer USDC from investor → fund_vault
5. Mint fund tokens to investor
6. Update investor_position.shares
7. Emit `Deposit` event

### 3.3 `redeem`

**Authority:** Investor (signer)
**Pre-conditions:**
- Fund not paused
- Investor has sufficient shares

**Accounts:** (same structure as deposit, reversed flow)

**Params:**
```rust
struct RedeemParams {
    share_amount: u64,
}
```

**Logic:**
1. Validate share balance
2. Calculate base_currency due: `shares × nav`
3. Burn investor's fund tokens
4. Transfer USDC from fund_vault → investor
5. Apply proportional management fee if due
6. Update investor_position
7. Emit `Redeem` event

### 3.4 `update_nav`

**Authority:** GP (signer)
**Pre-conditions:**
- GP authority verified
- NAV timestamp not in future (oracle protection)

**Params:**
```rust
struct UpdateNavParams {
    new_nav: u64,           // NAV × 1e6 precision
    timestamp: i64,
    signature: Vec<u8>,     // oracle price signature (optional)
}
```

**Logic:**
1. Validate GP authority
2. Update fund.nav
3. Calculate performance fees if new_nav > high_water_mark
4. Emit `NavUpdated` event

### 3.5 `set_whitelist`

**Authority:** GP (signer)

**Params:**
```rust
struct SetWhitelistParams {
    investor: Pubkey,
    kyc_level: u8,
    add: bool,  // true=add, false=remove
}
```

### 3.6 `pause` / `resume`

**Authority:** GP (signer)

**Logic:**
- Toggle `fund.is_paused`
- `pause` freezes deposits/redemptions
- Emit `FundPaused` / `FundResumed` event

---

## 4. Token-2022 Configuration

### 4.1 Transfer Fee Extension

```rust
// On every transfer, fee_amount = amount × (transfer_fee_bps / 10000)
// Fee goes to treasury
TransferFeeConfig {
    epoch: 0,
    transfer_fee_config_authority: fund_mint_pda,
    withheld_transfer_fee_authority: treasury_pda,
    maximum_fee: u64::MAX,
    mid: BaseOutsideLength::MID_LENGTH,
}
```

### 4.2 Transfer Hook (KYC)

Hook triggered on every `transfer` instruction:
1. Check sender + receiver in whitelist
2. Validate KYC levels
3. Revert if not approved

**Note:** Transfer hook requires separate Hook program deployed.

---

## 5. Security Model

### 5.1 Key Classification

| Key Type | Classification | Storage |
|----------|---------------|---------|
| Fund creation | LOCAL | Hardware wallet |
| Mint authority | LOCAL (initial), then PDA | Never single-sig after init |
| GP authority | HYBRID | Cloud prepared, LOCAL signed |
| Withdrawals | HYBRID | Cloud verified, LOCAL final |
| Treasury | MULTISIG (2-of-3) | Squads Protocol |

### 5.2 Validation Rules

1. All arithmetic uses checked math (no overflow)
2. NAV updates require GP signature + timestamp
3. Whitelist changes require GP signature
4. Pause/resume requires GP signature
5. Emergency withdrawal requires MULTISIG

---

## 6. Error Codes

```rust
#[error_code]
pub enum FundFactoryError {
    #[msg("Fund is paused")]
    FundPaused,
    #[msg("Investor not whitelisted")]
    NotWhitelisted,
    #[msg("KYC level insufficient")]
    InsufficientKycLevel,
    #[msg("Investment below minimum")]
    BelowMinInvestment,
    #[msg("Investment above maximum")]
    AboveMaxInvestment,
    #[msg("Insufficient shares")]
    InsufficientShares,
    #[msg("Invalid fee parameters")]
    InvalidFeeParams,
    #[msg("NAV timestamp in future")]
    NavTimestampInvalid,
    #[msg("Unauthorized GP operation")]
    UnauthorizedGp,
    #[msg("Invalid fund state")]
    InvalidFundState,
    #[msg("Arithmetic overflow")]
    Overflow,
}
```

---

## 7. Events

```rust
#[event]
struct FundCreated {
    fund: Pubkey,
    fund_id: u32,
    name: String,
    gp_authority: Pubkey,
    initial_nav: u64,
    timestamp: i64,
}

#[event]
struct Deposit {
    fund: Pubkey,
    investor: Pubkey,
    base_currency_amount: u64,
    shares_minted: u64,
    nav: u64,
    timestamp: i64,
}

#[event]
struct Redeem {
    fund: Pubkey,
    investor: Pubkey,
    shares_burned: u64,
    base_currency_amount: u64,
    fees_paid: u64,
    nav: u64,
    timestamp: i64,
}

#[event]
struct NavUpdated {
    fund: Pubkey,
    old_nav: u64,
    new_nav: u64,
    gp_authority: Pubkey,
    timestamp: i64,
}

#[event]
struct FundPaused {
    fund: Pubkey,
    timestamp: i64,
}
```

---

## 8. Integration with Backend

### 8.1 Railway API Endpoints (FastAPI)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/factory/funds` | GET | List all funds on-chain |
| `/api/v1/factory/fund/{id}` | GET | Get fund details |
| `/api/v1/factory/deploy` | POST | Create new fund (GP) |
| `/api/v1/factory/deposit` | POST | Deposit USDC |
| `/api/v1/factory/redeem` | POST | Redeem shares |
| `/api/v1/factory/nav` | POST | Update NAV (GP, internal) |
| `/api/v1/factory/whitelist` | POST | Manage whitelist |

### 8.2 IDL → TypeScript SDK

Anchor generates IDL at `target/idl/fund_factory.json`:
- Used by frontend to generate TypeScript client
- Enables `anchor.methods` calls from React

---

## 9. Testnet Deployment Plan

1. Deploy Fund Factory program to Devnet
2. Deploy KYC Transfer Hook to Devnet
3. Create test fund with 3 investors
4. Run deposit/redeem cycles
5. Verify Token-2022 transfer fees
6. Security audit + penetration testing
7. Deploy to Testnet

---

## 10. Reference Implementations

| Component | Source | Notes |
|-----------|--------|-------|
| Vault Factory | `fractal-protocol/upshift-vault` | Fork and adapt |
| PDA Pattern | `ironaddicteddog/anchor-escrow` | Educational reference |
| Token-2022 | `solana-program/token-2022-program` | Native support |
| KYC Hook | `Gitdigital-products/solana-kyc-compliance-sdk` | Adapt for fund |
| Multisig | `Squads-Protocol/squads-mpl` | Governance |

---

*Build things that feel alive.*
