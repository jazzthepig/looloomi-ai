use anchor_lang::prelude::*;

// ============================================================================
// Factory
// ============================================================================

impl Factory {
    pub const INIT_SPACE: usize = 1 + 4 + 32; // bump + total_funds + authority
}

#[account]
pub struct Factory {
    pub bump: u8,
    pub total_funds: u32,
    pub authority: Pubkey,
}

// ============================================================================
// Fund
// ============================================================================

impl Fund {
    pub const MAX_NAME_LEN: usize = 32;
    pub const MAX_SYMBOL_LEN: usize = 8;
    pub const INIT_SPACE: usize =
        1 + 4 + 4 + 32 + 8 + 32 + 32 + 8 + 8 + 32 + 32 + 2 + 2 + 8 + 8 + 1 + 8 + 8;

    pub fn validate_fees(&self) -> Result<()> {
        require!(
            self.management_fee_bps <= 10000 && self.performance_fee_bps <= 10000,
            crate::error::FundFactoryError::InvalidFeeParams
        );
        Ok(())
    }

    pub fn calculate_shares(&self, base_amount: u64) -> Result<u64> {
        if self.nav == 0 {
            Ok(base_amount)
        } else {
            base_amount
                .checked_mul(1_000_000)
                .ok_or(crate::error::FundFactoryError::Overflow)?
                .checked_div(self.nav)
                .ok_or(crate::error::FundFactoryError::Overflow)?
                .checked_div(1_000_000)
                .ok_or(crate::error::FundFactoryError::Overflow)
        }
    }

    pub fn calculate_redemption(&self, shares: u64) -> Result<u64> {
        shares
            .checked_mul(self.nav)
            .ok_or(crate::error::FundFactoryError::Overflow)?
            .checked_div(1_000_000)
            .ok_or(crate::error::FundFactoryError::Overflow)
    }
}

#[account]
pub struct Fund {
    pub bump: u8,
    pub fund_id: u32,
    pub name: String,
    pub symbol: String,
    pub fund_mint: Pubkey,
    pub base_currency: Pubkey,
    pub nav: u64,
    pub total_shares: u64,
    pub gp_authority: Pubkey,
    pub treasury: Pubkey,
    pub management_fee_bps: u16,
    pub performance_fee_bps: u16,
    pub min_investment: u64,
    pub max_investment: u64,
    pub is_paused: bool,
    pub high_water_mark: u64,
    pub created_at: i64,
}

// ============================================================================
// FundVault
// ============================================================================

impl FundVault {
    pub const INIT_SPACE: usize = 1 + 32 + 32;

    pub fn validate_fund(&self, fund_key: &Pubkey) -> Result<()> {
        require!(
            self.fund == *fund_key,
            crate::error::FundFactoryError::InvalidVault
        );
        Ok(())
    }
}

#[account]
pub struct FundVault {
    pub bump: u8,
    pub fund: Pubkey,
    pub currency_vault: Pubkey,
}

// ============================================================================
// InvestorPosition
// ============================================================================

impl InvestorPosition {
    pub const INIT_SPACE: usize = 1 + 32 + 32 + 8 + 8 + 8;

    pub fn new(fund: Pubkey, investor: Pubkey, bump: u8) -> Self {
        Self {
            bump,
            fund,
            investor,
            shares: 0,
            last_nav: 0,
            cumulative_fees: 0,
        }
    }
}

#[account]
pub struct InvestorPosition {
    pub bump: u8,
    pub fund: Pubkey,
    pub investor: Pubkey,
    pub shares: u64,
    pub last_nav: u64,
    pub cumulative_fees: u64,
}

// ============================================================================
// WhitelistEntry
// ============================================================================

impl WhitelistEntry {
    pub const KYC_NONE: u8 = 0;
    pub const KYC_ACCREDITED: u8 = 1;
    pub const KYC_INSTITUTIONAL: u8 = 2;
    pub const INIT_SPACE: usize = 1 + 32 + 32 + 1 + 1 + 8;
}

#[account]
pub struct WhitelistEntry {
    pub bump: u8,
    pub fund: Pubkey,
    pub investor: Pubkey,
    pub kyc_level: u8,
    pub is_active: bool,
    pub added_at: i64,
}
