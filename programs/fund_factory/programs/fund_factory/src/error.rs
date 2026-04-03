use anchor_lang::prelude::*;

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

    #[msg("Invalid mint")]
    InvalidMint,

    #[msg("Invalid vault")]
    InvalidVault,

    #[msg("Zero amount")]
    ZeroAmount,

    #[msg("Factory already initialized")]
    FactoryAlreadyInitialized,

    #[msg("Invalid fund id")]
    InvalidFundId,
}
