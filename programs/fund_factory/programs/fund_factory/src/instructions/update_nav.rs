use anchor_lang::prelude::*;
use crate::error::FundFactoryError;
use crate::state::*;

#[derive(Accounts)]
pub struct UpdateNav<'info> {
    #[account(
        mut,
        seeds = [b"fund", &fund.fund_id.to_le_bytes()],
        bump = fund.bump
    )]
    pub fund: Account<'info, Fund>,

    #[account(
        constraint = fund.gp_authority == gp_authority.key()
    )]
    pub gp_authority: Signer<'info>,
}

pub fn update_nav(ctx: Context<UpdateNav>, new_nav: u64, timestamp: i64) -> Result<()> {
    let current_time = Clock::get()?.unix_timestamp;

    // Prevent future NAV updates (oracle protection)
    require!(
        timestamp <= current_time + 60, // Allow 60s clock drift
        FundFactoryError::NavTimestampInvalid
    );

    let fund = &mut ctx.accounts.fund;
    let old_nav = fund.nav;

    // Update NAV
    fund.nav = new_nav;

    // Update high water mark if NAV is higher
    if new_nav > fund.high_water_mark {
        fund.high_water_mark = new_nav;
    }

    emit!(NavUpdated {
        fund: fund.key(),
        old_nav,
        new_nav,
        gp_authority: ctx.accounts.gp_authority.key(),
        timestamp,
    });

    Ok(())
}

#[event]
pub struct NavUpdated {
    pub fund: Pubkey,
    pub old_nav: u64,
    pub new_nav: u64,
    pub gp_authority: Pubkey,
    pub timestamp: i64,
}
