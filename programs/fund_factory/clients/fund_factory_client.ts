/**
 * Fund Factory TypeScript Client
 *
 * Generated from Anchor IDL + manual wrappers
 * Usage:
 *   import { FundFactoryClient } from './clients/fund_factory_client';
 *   const client = new FundFactoryClient(connection, wallet);
 */

import {
  Connection,
  PublicKey,
  Transaction,
  SystemProgram,
} from "@solana/web3.js";
import {
  Program,
  Provider,
  BN,
  web3,
} from "@project-serum/anchor";
import { FundFactory } from "../../target/types/fund_factory";
import { getAssociatedTokenAddress, TOKEN_PROGRAM_ID } from "@solana/spl-token";

// ============================================================================
// Constants
// ============================================================================

export const FACTORY_PROGRAM_ID = new PublicKey(
  "FundFactory1111111111111111111111111111111"
);

export const USDC_MINT = new PublicKey(
  "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v" // Solana USDC
);

// ============================================================================
// Types
// ============================================================================

export interface CreateFundParams {
  fundId: number;
  name: string;
  symbol: string;
  managementFeeBps: number;
  performanceFeeBps: number;
  minInvestment: BN;
  maxInvestment: BN;
}

export interface FundAccount {
  bump: number;
  fundId: number;
  name: string;
  symbol: string;
  fundMint: PublicKey;
  baseCurrency: PublicKey;
  nav: BN;
  totalShares: BN;
  gpAuthority: PublicKey;
  treasury: PublicKey;
  managementFeeBps: number;
  performanceFeeBps: number;
  minInvestment: BN;
  maxInvestment: BN;
  isPaused: boolean;
  highWaterMark: BN;
  createdAt: BN;
}

export interface InvestorPosition {
  bump: number;
  fund: PublicKey;
  investor: PublicKey;
  shares: BN;
  lastNav: BN;
  cumulativeFees: BN;
}

export interface WhitelistEntry {
  bump: number;
  fund: PublicKey;
  investor: PublicKey;
  kycLevel: number;
  isActive: boolean;
  addedAt: BN;
}

// ============================================================================
// PDA Derivation
// ============================================================================

export function findFactoryAddress(): PublicKey {
  return PublicKey.findProgramAddressSync([Buffer.from("factory")], FACTORY_PROGRAM_ID)[0];
}

export function findFundAddress(fundId: number): PublicKey {
  return PublicKey.findProgramAddressSync(
    [Buffer.from("fund"), Buffer.from(fundId.toLeBytes())],
    FACTORY_PROGRAM_ID
  )[0];
}

export function findFundVaultAddress(fundId: number): PublicKey {
  return PublicKey.findProgramAddressSync(
    [Buffer.from("fund"), Buffer.from(fundId.toLeBytes()), Buffer.from("vault")],
    FACTORY_PROGRAM_ID
  )[0];
}

export function findInvestorPositionAddress(
  fundId: number,
  investor: PublicKey
): PublicKey {
  return PublicKey.findProgramAddressSync(
    [
      Buffer.from("fund"),
      Buffer.from(fundId.toLeBytes()),
      Buffer.from("position"),
      investor.toBuffer(),
    ],
    FACTORY_PROGRAM_ID
  )[0];
}

export function findWhitelistAddress(
  fundId: number,
  investor: PublicKey
): PublicKey {
  return PublicKey.findProgramAddressSync(
    [
      Buffer.from("fund"),
      Buffer.from(fundId.toLeBytes()),
      Buffer.from("whitelist"),
      investor.toBuffer(),
    ],
    FACTORY_PROGRAM_ID
  )[0];
}

// ============================================================================
// Client Class
// ============================================================================

export class FundFactoryClient {
  private program: Program<FundFactory>;
  private provider: Provider;

  constructor(connection: Connection, wallet: web3.Keypair | Provider) {
    this.provider = new Provider(
      connection,
      wallet as Provider,
      Provider.defaultOptions()
    );
    this.program = new Program<FundFactory>(
      require("../../target/idl/fund_factory.json"),
      FACTORY_PROGRAM_ID,
      this.provider
    );
  }

  // --------------------------------------------------------------------------
  // Factory Operations
  // --------------------------------------------------------------------------

  async initializeFactory(): Promise<Transaction> {
    const [factory] = findFactoryAddress();
    return this.program.methods
      .initializeFactory()
      .accounts({
        factory,
        authority: this.provider.wallet.publicKey,
        systemProgram: SystemProgram.programId,
      })
      .transaction();
  }

  // --------------------------------------------------------------------------
  // Fund Operations
  // --------------------------------------------------------------------------

  async createFund(params: CreateFundParams): Promise<Transaction> {
    const [factory] = findFactoryAddress();
    const [fund] = findFundAddress(params.fundId);
    const [fundVault] = findFundVaultAddress(params.fundId);

    return this.program.methods
      .createFund({
        fundId: params.fundId,
        name: params.name,
        symbol: params.symbol,
        managementFeeBps: params.managementFeeBps,
        performanceFeeBps: params.performanceFeeBps,
        minInvestment: params.minInvestment,
        maxInvestment: params.maxInvestment,
      })
      .accounts({
        factory,
        fund,
        fundVault,
        fundMint: web3.Keypair.generate().publicKey, // Will be created
        baseCurrencyMint: USDC_MINT,
        gpAuthority: this.provider.wallet.publicKey,
        treasury: this.provider.wallet.publicKey,
        tokenProgram: TOKEN_PROGRAM_ID,
        associatedTokenProgram: web3.AssociatedTokenProgram.programId,
        systemProgram: SystemProgram.programId,
        rent: web3.SYSVAR_RENT_PUBKEY,
      })
      .transaction();
  }

  async deposit(fundId: number, baseCurrencyAmount: BN): Promise<Transaction> {
    const [fund] = findFundAddress(fundId);
    const [fundVault] = findFundVaultAddress(fundId);
    const investor = this.provider.wallet.publicKey;

    const [investorPosition] = findInvestorPositionAddress(fundId, investor);
    const [whitelistEntry] = findWhitelistAddress(fundId, investor);

    const investorCurrencyAccount = await getAssociatedTokenAddress(
      USDC_MINT,
      investor
    );
    const investorFundTokenAccount = await getAssociatedTokenAddress(
      (await this.program.account.fund.fetch(fund)).fundMint,
      investor
    );

    return this.program.methods
      .deposit(baseCurrencyAmount)
      .accounts({
        fund,
        fundVault,
        investorPosition,
        whitelistEntry,
        investorCurrencyAccount,
        investorFundTokenAccount,
        fundVaultCurrencyAccount: await getAssociatedTokenAddress(
          USDC_MINT,
          fundVault
        ),
        fundMint: (await this.program.account.fund.fetch(fund)).fundMint,
        investor,
        tokenProgram: TOKEN_PROGRAM_ID,
        associatedTokenProgram: web3.AssociatedTokenProgram.programId,
        systemProgram: SystemProgram.programId,
      })
      .transaction();
  }

  async redeem(fundId: number, shareAmount: BN): Promise<Transaction> {
    const [fund] = findFundAddress(fundId);
    const [fundVault] = findFundVaultAddress(fundId);
    const investor = this.provider.wallet.publicKey;

    const [investorPosition] = findInvestorPositionAddress(fundId, investor);

    const fundData = await this.program.account.fund.fetch(fund);
    const investorFundTokenAccount = await getAssociatedTokenAddress(
      fundData.fundMint,
      investor
    );

    return this.program.methods
      .redeem(shareAmount)
      .accounts({
        fund,
        fundVault,
        investorPosition,
        fundVaultCurrencyAccount: await getAssociatedTokenAddress(
          USDC_MINT,
          fundVault
        ),
        investorCurrencyAccount: await getAssociatedTokenAddress(
          USDC_MINT,
          investor
        ),
        investorFundTokenAccount,
        fundMint: fundData.fundMint,
        investor,
        tokenProgram: TOKEN_PROGRAM_ID,
        associatedTokenProgram: web3.AssociatedTokenProgram.programId,
        systemProgram: SystemProgram.programId,
      })
      .transaction();
  }

  async updateNav(
    fundId: number,
    newNav: BN,
    timestamp: number
  ): Promise<Transaction> {
    const [fund] = findFundAddress(fundId);
    return this.program.methods
      .updateNav(newNav, new BN(timestamp))
      .accounts({
        fund,
        gpAuthority: this.provider.wallet.publicKey,
      })
      .transaction();
  }

  // --------------------------------------------------------------------------
  // Whitelist Operations
  // --------------------------------------------------------------------------

  async setWhitelist(
    fundId: number,
    investor: PublicKey,
    kycLevel: number,
    add: boolean
  ): Promise<Transaction> {
    const [fund] = findFundAddress(fundId);
    const [whitelistEntry] = findWhitelistAddress(fundId, investor);

    return this.program.methods
      .setWhitelist(investor, kycLevel, add)
      .accounts({
        fund,
        whitelistEntry,
        investor,
        gpAuthority: this.provider.wallet.publicKey,
        systemProgram: SystemProgram.programId,
      })
      .transaction();
  }

  // --------------------------------------------------------------------------
  // Pause/Resume
  // --------------------------------------------------------------------------

  async pause(fundId: number): Promise<Transaction> {
    const [fund] = findFundAddress(fundId);
    return this.program.methods
      .pause()
      .accounts({
        fund,
        gpAuthority: this.provider.wallet.publicKey,
      })
      .transaction();
  }

  async resume(fundId: number): Promise<Transaction> {
    const [fund] = findFundAddress(fundId);
    return this.program.methods
      .resume()
      .accounts({
        fund,
        gpAuthority: this.provider.wallet.publicKey,
      })
      .transaction();
  }

  // --------------------------------------------------------------------------
  // Account Fetchers
  // --------------------------------------------------------------------------

  async getFund(fundId: number): Promise<FundAccount | null> {
    try {
      const [fund] = findFundAddress(fundId);
      return await this.program.account.fund.fetch(fund);
    } catch {
      return null;
    }
  }

  async getInvestorPosition(
    fundId: number,
    investor: PublicKey
  ): Promise<InvestorPosition | null> {
    try {
      const [position] = findInvestorPositionAddress(fundId, investor);
      return await this.program.account.investorPosition.fetch(position);
    } catch {
      return null;
    }
  }

  async getWhitelistEntry(
    fundId: number,
    investor: PublicKey
  ): Promise<WhitelistEntry | null> {
    try {
      const [entry] = findWhitelistAddress(fundId, investor);
      return await this.program.account.whitelistEntry.fetch(entry);
    } catch {
      return null;
    }
  }
}

// ============================================================================
// Utility Functions
// ============================================================================

export function calculateShares(nav: BN, baseAmount: BN): BN {
  if (nav.isZero()) {
    return baseAmount;
  }
  return baseAmount.mul(new BN(1_000_000)).div(nav).div(new BN(1_000_000));
}

export function calculateRedemption(nav: BN, shares: BN): BN {
  return shares.mul(nav).div(new BN(1_000_000));
}

export { BN };
