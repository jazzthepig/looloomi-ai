use anchor_lang::prelude::*;
use crate::state::*;

#[derive(Accounts)]
pub struct PauseFund<'info> {
    #[account(
        mut,
        seeds = [b"fund", &fund.fund_id.to_le_bytes()],
        bump = fund.bump,
        constraint = fund.gp_authority == gp_authority.key()
    )]
    pub fund: Account<'info, Fund>,

    #[account(mut)]
    pub gp_authority: Signer<'info>,
}

pub fn pause(ctx: Context<PauseFund>) -> Result<()> {
    let fund = &mut ctx.accounts.fund;
    require!(!fund.is_paused, crate::error::FundFactoryError::InvalidFundState);

    fund.is_paused = true;

    emit!(FundPaused {
        fund: fund.key(),
        timestamp: Clock::get()?.unix_timestamp,
    });

    Ok(())
}

#[derive(Accounts)]
pub struct ResumeFund<'info> {
    #[account(
        mut,
        seeds = [b"fund", &fund.fund_id.to_le_bytes()],
        bump = fund.bump,
        constraint = fund.gp_authority == gp_authority.key()
    )]
    pub fund: Account<'info, Fund>,

    #[account(mut)]
    pub gp_authority: Signer<'info>,
}

pub fn resume(ctx: Context<ResumeFund>) -> Result<()> {
    let fund = &mut ctx.accounts.fund;
    require!(fund.is_paused, crate::error::FundFactoryError::InvalidFundState);

    fund.is_paused = false;

    emit!(FundResumed {
        fund: fund.key(),
        timestamp: Clock::get()?.unix_timestamp,
    });

    Ok(())
}

#[event]
pub struct FundPaused {
    pub fund: Pubkey,
    pub timestamp: i64,
}

#[event]
pub struct FundResumed {
    pub fund: Pubkey,
    pub timestamp: i64,
}
