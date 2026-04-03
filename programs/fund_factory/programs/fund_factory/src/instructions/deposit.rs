use anchor_lang::prelude::*;
use anchor_spl::token_2022::{mint_to, transfer_checked, MintTo, Token2022, TransferChecked};
use anchor_spl::token::Mint;
use anchor_spl::associated_token::AssociatedToken;
use crate::error::FundFactoryError;
use crate::state::*;

#[derive(Accounts)]
pub struct Deposit<'info> {
    #[account(
        mut,
        seeds = [b"fund", &fund.fund_id.to_le_bytes()],
        bump = fund.bump
    )]
    pub fund: Account<'info, Fund>,

    #[account(
        seeds = [b"fund", &fund.fund_id.to_le_bytes(), b"vault"],
        bump = fund_vault.bump
    )]
    pub fund_vault: Account<'info, FundVault>,

    #[account(
        init_if_needed,
        payer = investor,
        space = 8 + InvestorPosition::INIT_SPACE,
        seeds = [
            b"fund",
            &fund.fund_id.to_le_bytes(),
            b"position",
            investor.key().as_ref()
        ],
        bump
    )]
    pub investor_position: Account<'info, InvestorPosition>,

    #[account(
        seeds = [
            b"fund",
            &fund.fund_id.to_le_bytes(),
            b"whitelist",
            investor.key().as_ref()
        ],
        bump = whitelist_entry.bump,
        constraint = whitelist_entry.is_active
    )]
    pub whitelist_entry: Account<'info, WhitelistEntry>,

    /// Base currency mint (USDC) — required for transfer_checked decimals
    #[account(constraint = base_currency_mint.key() == fund.base_currency)]
    pub base_currency_mint: Account<'info, Mint>,

    /// Fund share token mint — mint authority must be fund PDA
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

    /// CHECK: validated as ATA
    #[account(
        mut,
        associated_token::mint = fund.base_currency,
        associated_token::authority = fund_vault,
    )]
    pub fund_vault_currency_account: UncheckedAccount<'info>,

    #[account(mut)]
    pub investor: Signer<'info>,

    pub token_program: Program<'info, Token2022>,
    pub associated_token_program: Program<'info, AssociatedToken>,
    pub system_program: Program<'info, System>,
}

pub fn deposit(ctx: Context<Deposit>, base_currency_amount: u64) -> Result<()> {
    require!(!ctx.accounts.fund.is_paused, FundFactoryError::FundPaused);
    require!(base_currency_amount > 0, FundFactoryError::ZeroAmount);
    require!(
        base_currency_amount >= ctx.accounts.fund.min_investment,
        FundFactoryError::BelowMinInvestment
    );
    require!(
        base_currency_amount <= ctx.accounts.fund.max_investment,
        FundFactoryError::AboveMaxInvestment
    );

    // Use Fund::calculate_shares — handles first-deposit (total_shares==0) edge case
    let shares = ctx.accounts.fund.calculate_shares(base_currency_amount)?;
    require!(shares > 0, FundFactoryError::ZeroAmount);

    let decimals = ctx.accounts.base_currency_mint.decimals;
    let nav_snapshot = ctx.accounts.fund.nav;
    let fund_key = ctx.accounts.fund.key();

    // CPI 1: transfer base currency (USDC) from investor → vault
    let transfer_cpi = CpiContext::new(
        ctx.accounts.token_program.to_account_info(),
        TransferChecked {
            from:      ctx.accounts.investor_currency_account.to_account_info(),
            mint:      ctx.accounts.base_currency_mint.to_account_info(),
            to:        ctx.accounts.fund_vault_currency_account.to_account_info(),
            authority: ctx.accounts.investor.to_account_info(),
        },
    );
    transfer_checked(transfer_cpi, base_currency_amount, decimals)?;

    // CPI 2: mint fund share tokens to investor (fund PDA is mint authority)
    let fund_id_bytes = ctx.accounts.fund.fund_id.to_le_bytes();
    let bump = [ctx.accounts.fund.bump];
    let signer_seeds: &[&[u8]] = &[b"fund", &fund_id_bytes, &bump];
    let signer: &[&[&[u8]]] = &[signer_seeds];

    let mint_cpi = CpiContext::new_with_signer(
        ctx.accounts.token_program.to_account_info(),
        MintTo {
            mint:      ctx.accounts.fund_mint.to_account_info(),
            to:        ctx.accounts.investor_fund_token_account.to_account_info(),
            authority: ctx.accounts.fund.to_account_info(),
        },
        signer,
    );
    mint_to(mint_cpi, shares)?;

    // Update investor position
    let position = &mut ctx.accounts.investor_position;
    if position.shares == 0 {
        position.bump   = ctx.bumps.investor_position;
        position.fund   = fund_key;
        position.investor = ctx.accounts.investor.key();
        position.last_nav = nav_snapshot;
    }
    position.shares = position.shares
        .checked_add(shares)
        .ok_or(FundFactoryError::Overflow)?;

    // Update fund total shares
    let fund = &mut ctx.accounts.fund;
    fund.total_shares = fund.total_shares
        .checked_add(shares)
        .ok_or(FundFactoryError::Overflow)?;

    emit!(DepositEvent {
        fund: fund.key(),
        investor: ctx.accounts.investor.key(),
        base_currency_amount,
        shares_minted: shares,
        nav: fund.nav,
        timestamp: Clock::get()?.unix_timestamp,
    });

    Ok(())
}

#[event]
pub struct DepositEvent {
    pub fund: Pubkey,
    pub investor: Pubkey,
    pub base_currency_amount: u64,
    pub shares_minted: u64,
    pub nav: u64,
    pub timestamp: i64,
}
