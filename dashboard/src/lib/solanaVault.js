/**
 * solanaVault.js — CometCloud × Drift Vault attribution layer
 *
 * Phase 1: Memo-based AUM attribution
 *   - Sends a lightweight Solana transaction with a Memo instruction
 *   - Memo tags the deposit intent as originating from CometCloud
 *   - BumbleBee Capital can filter all vault depositors by this memo on-chain
 *   - Actual USDC deposit is handled by Drift's own UI (app.drift.trade)
 *
 * Phase 2 (future): @drift-labs/sdk direct vault deposit
 *
 * @solana/web3.js is lazy-loaded on first call to avoid bloating the main bundle.
 */

// Solana mainnet-beta RPC — use Helius/Triton in prod for reliability
const RPC_ENDPOINT = "https://api.mainnet-beta.solana.com";
const MEMO_PROGRAM_ID_STR = "MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr";

/**
 * Build and send a Solana Memo transaction tagging a CometCloud vault deposit intent.
 * Lazy-loads @solana/web3.js on first invocation.
 *
 * @param {object} params
 * @param {string} params.walletAddress    - Connected Phantom wallet address
 * @param {string} params.vaultAddress     - Drift vault address
 * @param {string} params.partner          - GP partner name (e.g. "BumbleBee Capital")
 * @param {number} params.amountUsdc       - Intended deposit amount in USDC
 * @returns {Promise<{ signature: string, explorerUrl: string }>}
 */
export async function sendVaultDepositMemo({ walletAddress, vaultAddress, partner, amountUsdc }) {
  const provider = window.solana;
  if (!provider?.isPhantom) throw new Error("Phantom wallet not found");
  if (!provider.isConnected)  throw new Error("Wallet not connected");

  // Lazy-load @solana/web3.js — only downloaded when user triggers a deposit intent
  const {
    Connection,
    Transaction,
    TransactionInstruction,
    PublicKey,
  } = await import("@solana/web3.js");

  const connection = new Connection(RPC_ENDPOINT, "confirmed");
  const publicKey  = new PublicKey(walletAddress);
  const MEMO_PROGRAM_ID = new PublicKey(MEMO_PROGRAM_ID_STR);

  // Memo payload — on-chain forever, queryable by BumbleBee / CometCloud
  const memoData = JSON.stringify({
    source:      "cometcloud",
    action:      "vault_deposit_intent",
    partner,
    vault:       vaultAddress,
    amount_usdc: amountUsdc,
    ts:          Math.floor(Date.now() / 1000),
  });

  const memoInstruction = new TransactionInstruction({
    keys:      [{ pubkey: publicKey, isSigner: true, isWritable: false }],
    programId: MEMO_PROGRAM_ID,
    data:      Buffer.from(memoData, "utf-8"),
  });

  const { blockhash, lastValidBlockHeight } = await connection.getLatestBlockhash();

  const tx = new Transaction({ recentBlockhash: blockhash, feePayer: publicKey });
  tx.add(memoInstruction);

  // Sign via Phantom (no auto-approve — user sees the tx)
  const { signature } = await provider.signAndSendTransaction(tx);

  // Wait for confirmation (up to ~30s)
  await connection.confirmTransaction(
    { signature, blockhash, lastValidBlockHeight },
    "confirmed"
  );

  return {
    signature,
    explorerUrl: `https://solscan.io/tx/${signature}`,
  };
}

/**
 * Shorten a Solana address for display: Abc1…xyz9
 */
export function shortSolAddr(addr) {
  if (!addr) return "";
  return `${addr.slice(0, 4)}…${addr.slice(-4)}`;
}
