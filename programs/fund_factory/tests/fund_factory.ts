import * as anchor from "@project-serum/anchor";
import { Program } from "@project-serum/anchor";
import { FundFactory } from "../target/types/fund_factory";
import { expect } from "chai";

describe("Fund Factory", () => {
  // Configure the client to use the local cluster.
  anchor.setProvider(anchor.AnchorProvider.env());

  const program = anchor.workspace.FundFactory as Program<FundFactory>;

  it("Initializes the factory", async () => {
    const factory = anchor.web3.Keypair.generate();

    await program.methods
      .initializeFactory()
      .accounts({
        factory: factory.publicKey,
        authority: (program.provider as anchor.AnchorProvider).wallet.publicKey,
        systemProgram: anchor.web3.SystemProgram.programId,
      })
      .signers([factory])
      .rpc();

    const factoryAccount = await program.account.factory.fetch(factory.publicKey);
    expect(factoryAccount.authority.toBase58()).to.equal(
      (program.provider as anchor.AnchorProvider).wallet.publicKey.toBase58()
    );
  });
});
