use anchor_lang::prelude::*;
use instructions::*;

pub use instructions::*;

mod instructions;
mod error;
mod state;

declare_id!("4xqfDm5m6wiGrdBLqTK5D77dpD8NbD2ED7xGa7LWqeA");

#[program]
pub mod fund_factory {
    use super::*;

    /// Create a new fund
    pub fn create_fund(
        ctx: Context<CreateFund>,
        params: CreateFundParams,
    ) -> Result<()> {
        instructions::create_fund(ctx, params)
    }

    /// Deposit base currency (USDC) into fund, receive fund shares
    pub fn deposit(
        ctx: Context<Deposit>,
        base_currency_amount: u64,
    ) -> Result<()> {
        instructions::deposit(ctx, base_currency_amount)
    }

    /// Redeem fund shares for base currency
    pub fn redeem(
        ctx: Context<Redeem>,
        share_amount: u64,
    ) -> Result<()> {
        instructions::redeem(ctx, share_amount)
    }

    /// Update fund NAV (GP only)
    pub fn update_nav(
        ctx: Context<UpdateNav>,
        new_nav: u64,
        timestamp: i64,
    ) -> Result<()> {
        instructions::update_nav(ctx, new_nav, timestamp)
    }

    /// Add or remove investor from whitelist (GP only)
    pub fn set_whitelist(
        ctx: Context<SetWhitelist>,
        investor: Pubkey,
        kyc_level: u8,
        add: bool,
    ) -> Result<()> {
        instructions::set_whitelist(ctx, investor, kyc_level, add)
    }

    /// Pause fund operations (GP only)
    pub fn pause(ctx: Context<PauseFund>) -> Result<()> {
        instructions::pause(ctx)
    }

    /// Resume fund operations (GP only)
    pub fn resume(ctx: Context<ResumeFund>) -> Result<()> {
        instructions::resume(ctx)
    }

    /// Initialize factory (one-time)
    pub fn initialize_factory(ctx: Context<InitializeFactory>) -> Result<()> {
        instructions::initialize_factory(ctx)
    }
}
