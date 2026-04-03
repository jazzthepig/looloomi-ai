use anchor_lang::prelude::*;
use crate::error::FundFactoryError;
use crate::state::*;

#[derive(Accounts)]
pub struct SetWhitelist<'info> {
    #[account(
        seeds = [b"fund", &fund.fund_id.to_le_bytes()],
        bump = fund.bump,
        constraint = fund.gp_authority == gp_authority.key()
    )]
    pub fund: Account<'info, Fund>,

    #[account(
        init_if_needed,
        payer = gp_authority,
        space = 8 + WhitelistEntry::INIT_SPACE,
        seeds = [
            b"fund",
            &fund.fund_id.to_le_bytes(),
            b"whitelist",
            investor.as_ref()
        ],
        bump
    )]
    pub whitelist_entry: Account<'info, WhitelistEntry>,

    pub investor: UncheckedAccount<'info>,

    #[account(mut)]
    pub gp_authority: Signer<'info>,

    pub system_program: Program<'info, System>,
}

pub fn set_whitelist(
    ctx: Context<SetWhitelist>,
    investor: Pubkey,
    kyc_level: u8,
    add: bool,
) -> Result<()> {
    let fund = &ctx.accounts.fund;

    // Validate KYC level
    require!(
        kyc_level <= WhitelistEntry::KYC_INSTITUTIONAL,
        FundFactoryError::InsufficientKycLevel
    );

    if add {
        let entry = &mut ctx.accounts.whitelist_entry;
        entry.bump = ctx.bumps.whitelist_entry;
        entry.fund = fund.key();
        entry.investor = investor;
        entry.kyc_level = kyc_level;
        entry.is_active = true;
        entry.added_at = Clock::get()?.unix_timestamp;

        emit!(WhitelistUpdated {
            fund: fund.key(),
            investor,
            kyc_level,
            is_active: true,
            timestamp: entry.added_at,
        });
    } else {
        // Remove from whitelist
        let entry = &mut ctx.accounts.whitelist_entry;
        entry.is_active = false;

        emit!(WhitelistUpdated {
            fund: fund.key(),
            investor,
            kyc_level: entry.kyc_level,
            is_active: false,
            timestamp: Clock::get()?.unix_timestamp,
        });
    }

    Ok(())
}

#[event]
pub struct WhitelistUpdated {
    pub fund: Pubkey,
    pub investor: Pubkey,
    pub kyc_level: u8,
    pub is_active: bool,
    pub timestamp: i64,
}
