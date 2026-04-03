use anchor_lang::prelude::*;
use anchor_spl::token_2022::{burn, transfer_checked, Burn, Token2022, TransferChecked};
use anchor_spl::token::Mint;
use anchor_spl::associated_token::AssociatedToken;
use crate::error::FundFactoryError;
use crate::state::*;

#[derive(Accounts)]
pub struct Redeem<'info> {
    #[account(
        mut,
        seeds = [b"fund", &fund.fund_id.to_le_bytes()],
        bump = fund.bump
    )]
    pub fund: Account<'info, Fund>,

    #[account(
        mut,
        seeds = [b"fund", &fund.fund_id.to_le_bytes(), b"vault"],
        bump = fund_vault.bump
    )]
    pub fund_vault: Account<'info, FundVault>,

    #[account(
        mut,
        seeds = [
            b"fund",
            &fund.fund_id.to_le_bytes(),
            b"position",
            investor.key().as_ref()
        ],
        bump = investor_position.bump,
        constraint = investor_position.shares >= share_amount
    )]
    pub investor_position: Account<'info, InvestorPosition>,

    /// Base currency mint (USDC) — required for transfer_checked decimals
    #[account(constraint = base_currency_mint.key() == fund.base_currency)]
    pub base_currency_mint: Account<'info, Mint>,

    /// Fund share token mint — required for burn CPI
    /// CHECK: validated via fund.fund_mint constraint
    #[account(
        mut,
        constraint = fund_mint.key() == fund.fund_mint
    )]
    pub fund_mint: UncheckedAccount<'info>,

    /// CHECK: validated as ATA
    #[account(
        mut,
        associated_token::mint = fund.base_currency,
        associated_token::authority = fund_vault,
    )]
    pub fund_vault_currency_account: UncheckedAccount<'info>,

    /// CHECK: validated as ATA
    #[account(
        mut,
        associated_token::mint = fund.base_currency,
        associated_token::authority = investor,
    )]
    pub investor_currency_account: UncheckedAccount<'info>,

    /// CHECK: validated as ATA
    #[account(
        mut,
        associated_token::mint = fund.fund_mint,
        associated_token::authority = investor,
    )]
    pub investor_fund_token_account: UncheckedAccount<'info>,

    #[account(mut)]
    pub investor: Signer<'info>,

    pub token_program: Program<'info, Token2022>,
    pub associated_token_program: Program<'info, AssociatedToken>,
    pub system_program: Program<'info, System>,
}

pub fn redeem(ctx: Context<Redeem>, share_amount: u64) -> Result<()> {
    require!(!ctx.accounts.fund.is_paused, FundFactoryError::FundPaused);
    require!(share_amount > 0, FundFactoryError::ZeroAmount);
    require!(
        ctx.accounts.investor_position.shares >= share_amount,
        FundFactoryError::InsufficientShares
    );

    let base_currency_amount = ctx.accounts.fund.calculate_redemption(share_amount)?;

    let management_fee = base_currency_amount
        .checked_mul(ctx.accounts.fund.management_fee_bps as u64)
        .ok_or(FundFactoryError::Overflow)?
        .checked_div(10000)
        .ok_or(FundFactoryError::Overflow)?;

    let net_amount = base_currency_amount
        .checked_sub(management_fee)
        .ok_or(FundFactoryError::Overflow)?;

    let decimals = ctx.accounts.base_currency_mint.decimals;

    // CPI 1: burn fund share tokens from investor (investor signs)
    let burn_cpi = CpiContext::new(
        ctx.accounts.token_program.to_account_info(),
        Burn {
            mint:      ctx.accounts.fund_mint.to_account_info(),
            from:      ctx.accounts.investor_fund_token_account.to_account_info(),
            authority: ctx.accounts.investor.to_account_info(),
        },
    );
    burn(burn_cpi, share_amount)?;

    // CPI 2: transfer net USDC from vault → investor (fund_vault PDA signs)
    let fund_id_bytes = ctx.accounts.fund.fund_id.to_le_bytes();
    let vault_bump = [ctx.accounts.fund_vault.bump];
    let vault_seeds: &[&[u8]] = &[b"fund", &fund_id_bytes, b"vault", &vault_bump];
    let vault_signer: &[&[&[u8]]] = &[vault_seeds];

    let transfer_cpi = CpiContext::new_with_signer(
        ctx.accounts.token_program.to_account_info(),
        TransferChecked {
            from:      ctx.accounts.fund_vault_currency_account.to_account_info(),
            mint:      ctx.accounts.base_currency_mint.to_account_info(),
            to:        ctx.accounts.investor_currency_account.to_account_info(),
            authority: ctx.accounts.fund_vault.to_account_info(),
        },
        vault_signer,
    );
    transfer_checked(transfer_cpi, net_amount, decimals)?;

    // Update investor position
    let position = &mut ctx.accounts.investor_position;
    position.shares = position.shares
        .checked_sub(share_amount)
        .ok_or(FundFactoryError::Overflow)?;
    position.cumulative_fees = position.cumulative_fees
        .checked_add(management_fee)
        .ok_or(FundFactoryError::Overflow)?;

    // Update fund total shares
    let fund = &mut ctx.accounts.fund;
    fund.total_shares = fund.total_shares
        .checked_sub(share_amount)
        .ok_or(FundFactoryError::Overflow)?;

    emit!(RedeemEvent {
        fund: fund.key(),
        investor: ctx.accounts.investor.key(),
        shares_burned: share_amount,
        base_currency_amount,
        fees_paid: management_fee,
        nav: fund.nav,
        timestamp: Clock::get()?.unix_timestamp,
    });

    Ok(())
}

#[event]
pub struct RedeemEvent {
    pub fund: Pubkey,
    pub investor: Pubkey,
    pub shares_burned: u64,
    pub base_currency_amount: u64,
    pub fees_paid: u64,
    pub nav: u64,
    pub timestamp: i64,
}
