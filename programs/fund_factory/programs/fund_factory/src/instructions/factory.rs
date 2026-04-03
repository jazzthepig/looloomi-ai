use anchor_lang::prelude::*;
use crate::state::*;

#[derive(Accounts)]
pub struct InitializeFactory<'info> {
    #[account(
        init,
        payer = authority,
        space = 8 + Factory::INIT_SPACE,
        seeds = [b"factory"],
        bump
    )]
    pub factory: Account<'info, Factory>,

    #[account(mut)]
    pub authority: Signer<'info>,

    pub system_program: Program<'info, System>,
}

pub fn initialize_factory(ctx: Context<InitializeFactory>) -> Result<()> {
    let factory = &mut ctx.accounts.factory;
    factory.bump = ctx.bumps.factory;
    factory.total_funds = 0;
    factory.authority = ctx.accounts.authority.key();

    emit!(FactoryInitialized {
        authority: factory.authority,
        timestamp: Clock::get()?.unix_timestamp,
    });

    Ok(())
}

#[event]
pub struct FactoryInitialized {
    pub authority: Pubkey,
    pub timestamp: i64,
}
