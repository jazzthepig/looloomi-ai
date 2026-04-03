#!/usr/bin/env bash
# =============================================================================
# Fund Factory - Devnet Deployment Script
# =============================================================================
# Usage: ./scripts/deploy-devnet.sh
# =============================================================================

set -e

echo "🚀 Deploying Fund Factory to Devnet..."

# Check if anchor is installed
if ! command -v anchor &> /dev/null; then
    echo "❌ Anchor CLI not found. Installing..."
    cargo install anchor-cli
fi

# Check Solana CLI
if ! command -v solana &> /dev/null; then
    echo "❌ Solana CLI not found. Please install Solana toolchain."
    exit 1
fi

# Set cluster to devnet
echo "📡 Setting cluster to devnet..."
solana config set --cluster devnet

# Airdrop SOL if needed
echo "💰 Checking SOL balance..."
BALANCE=$(solana balance | awk '{print $1}')
if (( $(echo "$BALANCE < 2" | bc -l) )); then
    echo "Airdropping SOL..."
    solana airdrop 2
fi

# Build the program
echo "🔨 Building program..."
anchor build

# Deploy
echo "📤 Deploying to devnet..."
anchor deploy --provider.cluster devnet

# Get program ID
PROGRAM_ID=$(anchor idl show --provider.cluster devnet 2>/dev/null | grep "Address" | awk '{print $2}')
echo "✅ Deployed! Program ID: $PROGRAM_ID"

# Save to .env
echo "FACTORY_PROGRAM_ID=$PROGRAM_ID" >> .env

echo "🎉 Deployment complete!"
