use anchor_lang::prelude::*;
use anchor_spl::token_2022::{Token2022, TokenAccount};
use anchor_spl::token::Mint;
use anchor_spl::associated_token::AssociatedToken;
use crate::error::FundFactoryError;
use crate::state::*;

#[derive(Accounts)]
#[instruction(params: CreateFundParams)]
pub struct CreateFund<'info> {
    #[account(
        mut,
        seeds = [b"factory"],
        bump = factory.bump
    )]
    pub factory: Account<'info, Factory>,

    #[account(
        init,
        payer = gp_authority,
        space = 8 + Fund::INIT_SPACE,
        seeds = [b"fund", &params.fund_id.to_le_bytes()],
        bump
    )]
    pub fund: Account<'info, Fund>,

    #[account(
        init,
        payer = gp_authority,
        space = 8 + FundVault::INIT_SPACE,
        seeds = [b"fund", &params.fund_id.to_le_bytes(), b"vault"],
        bump
    )]
    pub fund_vault: Account<'info, FundVault>,

    /// Vault's USDC token account — initialized here, owned by fund_vault PDA.
    /// Holds all LP deposits; redeemed via fund_vault PDA signer in redeem.rs.
    #[account(
        init,
        payer = gp_authority,
        associated_token::mint = base_currency_mint,
        associated_token::authority = fund_vault,
        associated_token::token_program = token_program,
    )]
    pub vault_currency_account: Account<'info, TokenAccount>,

    /// Fund share token mint (Token-2022).
    /// NOTE: This account must be pre-initialized as a Token-2022 mint
    /// with the fund PDA as mint authority before calling create_fund.
    /// Transfer fee config and KYC hook should be set at mint init time.
    /// CHECK: caller-initialized, stored by pubkey only
    pub fund_mint: UncheckedAccount<'info>,

    pub base_currency_mint: Account<'info, Mint>,

    #[account(mut)]
    pub gp_authority: Signer<'info>,

    /// CHECK: treasury for fee collection
    pub treasury: UncheckedAccount<'info>,

    pub token_program: Program<'info, Token2022>,
    pub associated_token_program: Program<'info, AssociatedToken>,
    pub system_program: Program<'info, System>,
    pub rent: Sysvar<'info, Rent>,
}

#[derive(AnchorSerialize, AnchorDeserialize)]
pub struct CreateFundParams {
    pub fund_id: u32,
    pub name: String,
    pub symbol: String,
    pub management_fee_bps: u16,
    pub performance_fee_bps: u16,
    pub min_investment: u64,
    pub max_investment: u64,
}

pub fn create_fund(ctx: Context<CreateFund>, params: CreateFundParams) -> Result<()> {
    require!(
        params.name.len() <= Fund::MAX_NAME_LEN,
        FundFactoryError::InvalidFundState
    );
    require!(
        params.symbol.len() <= Fund::MAX_SYMBOL_LEN,
        FundFactoryError::InvalidFundState
    );
    require!(
        params.management_fee_bps <= 10000 && params.performance_fee_bps <= 10000,
        FundFactoryError::InvalidFeeParams
    );

    let fund = &mut ctx.accounts.fund;
    fund.bump               = ctx.bumps.fund;
    fund.fund_id            = params.fund_id;
    fund.name               = params.name.clone();
    fund.symbol             = params.symbol;
    fund.fund_mint          = ctx.accounts.fund_mint.key();
    fund.base_currency      = ctx.accounts.base_currency_mint.key();
    fund.nav                = 1_000_000; // 1.0 with 6 decimals
    fund.total_shares       = 0;
    fund.gp_authority       = ctx.accounts.gp_authority.key();
    fund.treasury           = ctx.accounts.treasury.key();
    fund.management_fee_bps = params.management_fee_bps;
    fund.performance_fee_bps = params.performance_fee_bps;
    fund.min_investment     = params.min_investment;
    fund.max_investment     = params.max_investment;
    fund.is_paused          = false;
    fund.high_water_mark    = fund.nav;
    fund.created_at         = Clock::get()?.unix_timestamp;

    let fund_vault = &mut ctx.accounts.fund_vault;
    fund_vault.bump           = ctx.bumps.fund_vault;
    fund_vault.fund           = ctx.accounts.fund.key();
    fund_vault.currency_vault = ctx.accounts.vault_currency_account.key(); // ATA initialized above

    let factory = &mut ctx.accounts.factory;
    factory.total_funds = factory.total_funds
        .checked_add(1)
        .ok_or(FundFactoryError::Overflow)?;

    emit!(FundCreated {
        fund: ctx.accounts.fund.key(),
        fund_id: params.fund_id,
        name: params.name,
        gp_authority: ctx.accounts.gp_authority.key(),
        initial_nav: fund.nav,
        timestamp: fund.created_at,
    });

    Ok(())
}

#[event]
pub struct FundCreated {
    pub fund: Pubkey,
    pub fund_id: u32,
    pub name: String,
    pub gp_authority: Pubkey,
    pub initial_nav: u64,
    pub timestamp: i64,
}
