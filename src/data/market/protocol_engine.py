"""
Protocol Intelligence Engine v1.0
CIS-scored protocol universe with live DeFiLlama data.

Each protocol is scored across 5 CIS pillars:
  F (Fundamental): TVL scale + stability + audit + age
  M (Momentum):    TVL 7d/30d change + APY trend
  O (On-chain):    Concentration risk + depeg history + contract quality
  S (Sentiment):   Community + dev activity + trending
  A (Alpha):       Outperformance vs category peers

Output: CIS grade (A+ → F), signal (ACCUMULATE/HOLD/REDUCE/AVOID),
        recommended_weight, per-pillar breakdown, risk_tier.
"""

import time
import math
import httpx
import asyncio
from datetime import datetime, timezone

# ── TTL cache (shared with data_layer pattern) ─────────────────────────────
_pcache: dict = {}

def _cget(key: str, ttl: int = 300):
    if key in _pcache:
        val, ts = _pcache[key]
        if time.time() - ts < ttl:
            return val
    return None

def _cset(key: str, val):
    _pcache[key] = (val, time.time())
    return val


# ── Protocol Registry ───────────────────────────────────────────────────────
# slug = DeFiLlama protocol slug for live TVL lookup
PROTOCOL_REGISTRY = [
    # RWA — Treasuries
    {
        "id": "ondo", "name": "Ondo Finance", "slug": "ondo-finance",
        "category": "RWA - Treasuries", "chain": "Multi-chain",
        "base_apy": 4.8, "audit_score": 9, "age_months": 24,
        "desc": "Ondo Finance brings institutional-grade US Treasury exposure on-chain through its OUSG (BlackRock T-bill ETF) and OMMF (money market) tokens. Redemptions settle T+0 for qualified buyers, bridging the operational gap between TradFi yield and DeFi composability.",
        "why_selected": "Ondo is the clearest signal that institutional capital has accepted tokenized RWA as a structural asset class. Its partnership with BlackRock, $500M+ TVL trajectory, and cross-chain expansion across Ethereum, Solana, and Arbitrum make it the bellwether for the RWA narrative we are positioned around.",
        "strengths": ["BlackRock BUIDL integration — direct T-bill ETF backing", "T+0 settlement for qualified institutional buyers", "Cross-chain: Ethereum, Solana, Arbitrum, Mantle", "Highest institutional brand trust in the tokenized treasury space"],
    },
    {
        "id": "blackrock", "name": "BlackRock BUIDL", "slug": "blackrock-buidl",
        "category": "RWA - Treasuries", "chain": "Multi-chain",
        "base_apy": 4.3, "audit_score": 10, "age_months": 18,
        "desc": "BUIDL is BlackRock's tokenized money market fund — the world's largest asset manager issuing directly on-chain via Securitize. Investors hold tokenized shares of a fund that invests exclusively in US Treasury bills, overnight repos, and cash. BlackRock custody, Deloitte audit.",
        "why_selected": "This is the institutional credibility anchor for the entire tokenized treasury sector. When BlackRock tokenizes $500M+ on Ethereum, it de-risks the regulatory narrative for every fund allocating to RWA. We hold BUIDL as a benchmark, not just a position.",
        "strengths": ["Issued by world's largest asset manager ($10T AUM)", "Perfect audit score — Deloitte-audited, SEC-registered fund", "Accepted as collateral by major DeFi protocols (Ondo, Frax)", "Fastest-growing tokenized fund in history"],
    },
    {
        "id": "franklin", "name": "Franklin Templeton", "slug": "franklin-onchain-us-government-money-fund",
        "category": "RWA - Treasuries", "chain": "Polygon",
        "base_apy": 4.5, "audit_score": 10, "age_months": 20,
        "desc": "The Franklin OnChain US Government Money Fund (FOBXX) was the first US-registered mutual fund to use a public blockchain for transaction processing and record-keeping. The BENJI token on Polygon represents fund shares, accruing daily yield from T-bills and government repos.",
        "why_selected": "Franklin Templeton moved first — before BlackRock, before Fidelity. That first-mover institutional courage, combined with their $1.5T AUM and the regulatory clarity of a registered mutual fund structure, makes FOBXX a core allocation for any RWA sleeve.",
        "strengths": ["First US-regulated mutual fund on a public blockchain (2021)", "Daily yield accrual — interest compounds directly into token value", "SEC and FINRA compliant — no regulatory ambiguity", "Franklin's $1.5T AUM backstops institutional confidence"],
    },
    {
        "id": "superstate", "name": "Superstate", "slug": "superstate",
        "category": "RWA - Treasuries", "chain": "Ethereum",
        "base_apy": 4.6, "audit_score": 8, "age_months": 14,
        "desc": "Superstate issues USTB — a tokenized short-duration US Treasury fund built on Ethereum and designed specifically for DeFi composability. Founded by Robert Leshner (Compound founder), it targets DeFi treasuries and DAOs seeking compliant on-chain yield without custody risk.",
        "why_selected": "Superstate sits at the intersection of two of our highest-conviction themes: the RWA yield narrative and DeFi protocol treasury adoption. Leshner's track record building Compound — the protocol that defined algorithmic money markets — makes this team a tier-one bet on the institutional DeFi transition.",
        "strengths": ["Founded by Robert Leshner (Compound creator)", "Designed for DeFi protocol treasury integration", "Short-duration focus minimises interest rate risk", "Growing DAO/treasury client base provides sticky AUM"],
    },
    {
        "id": "anemoy", "name": "Anemoy Capital", "slug": "anemoy-capital",
        "category": "RWA - Treasuries", "chain": "Multi-chain",
        "base_apy": 5.2, "audit_score": 7, "age_months": 12,
        "desc": "Anemoy operates the Liquid Treasury Fund — a tokenized T-bill vehicle built on Centrifuge's infrastructure with cross-chain reach via Axelar. Its higher APY relative to peers reflects a slightly wider maturity ladder and tactical allocation to short-dated agency paper.",
        "why_selected": "Anemoy offers incremental yield pickup (50–90bps) over the BlackRock/Franklin tier with acceptable credit quality. For a fund-of-funds structure where blended yield matters, this kind of differentiated instrument is worth holding in a satellite position alongside the anchor names.",
        "strengths": ["Higher APY — blended T-bill + agency paper strategy", "Built on Centrifuge infrastructure — proven legal wrapper", "Cross-chain via Axelar — not locked to a single L1", "Fills a yield gap between pure T-bill funds and private credit"],
    },

    # RWA — Private Credit
    {
        "id": "maple", "name": "Maple Finance", "slug": "maple",
        "category": "RWA - Private Credit", "chain": "Multi-chain",
        "base_apy": 12.0, "audit_score": 8, "age_months": 36,
        "desc": "Maple Finance is an institutional undercollateralized lending marketplace where creditworthy borrowers — primarily crypto market makers, trading firms, and fintechs — access capital against verified reputation and balance sheet. Lenders earn yield by funding vetted pools managed by expert Pool Delegates.",
        "why_selected": "Maple survived the 2022 blowup (Orthogonal Trading default) and came back with a materially stronger risk framework: over-collateralized pools, KYC/KYB requirements, and institutional-only borrower onboarding. Protocols that improve after stress tests are exactly what we want in the private credit sleeve.",
        "strengths": ["Post-2022 rebuild: stricter underwriting, institutional borrowers only", "Pool Delegate model — credit experts own risk decisions", "12%+ APY with institutional-grade counterparties", "Expanding to real-world SME lending via Maple Direct"],
    },
    {
        "id": "centrifuge", "name": "Centrifuge", "slug": "centrifuge",
        "category": "RWA - Private Credit", "chain": "Multi-chain",
        "base_apy": 9.5, "audit_score": 9, "age_months": 48,
        "desc": "Centrifuge pioneered the legal infrastructure for bringing real-world assets on-chain. Its Tinlake pools and updated Centrifuge Chain allow originators — invoice financiers, trade credit providers, microfinance lenders — to tokenize receivables and access DeFi liquidity. MakerDAO has deployed $200M+ through Centrifuge pools.",
        "why_selected": "Centrifuge built the legal wrapper that the entire RWA sector later borrowed. Their SPV + DROP/TIN tranching model is the template. As the oldest and most institutionally integrated RWA infrastructure protocol, it sits at the foundation of our private credit thesis.",
        "strengths": ["MakerDAO integration — $200M+ deployed via Centrifuge vaults", "Dual-tranche (DROP/TIN) risk structuring for different risk appetites", "Widest originator diversity — invoices, trade finance, real estate", "4 years live: most battle-tested RWA infrastructure on-chain"],
    },
    {
        "id": "credix", "name": "Credix", "slug": "credix-finance",
        "category": "RWA - Private Credit", "chain": "Solana",
        "base_apy": 14.0, "audit_score": 7, "age_months": 24,
        "desc": "Credix connects institutional lenders with emerging market fintechs — primarily in Latin America and Southeast Asia — seeking USD liquidity. Borrowers are credit-assessed fintech companies with established loan books; lenders access high-yield EM credit exposure with downside protection from structural seniority.",
        "why_selected": "EM private credit is structurally underserved by traditional finance, and that inefficiency is exactly where on-chain capital can extract a durable premium. Credix's 14% APY reflects genuine credit complexity, not protocol risk — a distinction that matters for portfolio construction.",
        "strengths": ["14%+ APY — genuine EM credit premium, not inflated emissions", "Borrowers are regulated fintechs with audited loan books", "Solana-native — low transaction costs for frequent settlement", "Fills a white space TradFi banks systematically underserve"],
    },
    {
        "id": "goldfinch", "name": "Goldfinch", "slug": "goldfinch",
        "category": "RWA - Private Credit", "chain": "Ethereum",
        "base_apy": 8.0, "audit_score": 9, "age_months": 36,
        "desc": "Goldfinch extends credit to off-chain businesses without crypto collateral, using a network of on-chain auditors and backers to underwrite credit risk. Its senior/junior pool structure means stablecoin LPs to the senior pool are protected by backer capital absorbing first losses. Primary borrowers are fintech lenders across EM markets.",
        "why_selected": "Goldfinch's auditor model is genuinely novel — it decentralises the credit underwriting function rather than just the capital deployment. Three years of live performance with real borrowers across Africa, Southeast Asia, and LatAm gives it a track record that newer protocols cannot match.",
        "strengths": ["Decentralised underwriting via on-chain auditor/backer network", "Senior LP first-loss protection — structurally safer for scale capital", "36+ months live performance with real-world borrower repayments", "High audit score — Certik, Trace, and Trail of Bits reviewed"],
    },

    # DeFi — Lending
    {
        "id": "aave", "name": "Aave", "slug": "aave",
        "category": "DeFi - Lending", "chain": "Multi-chain",
        "base_apy": 3.5, "audit_score": 10, "age_months": 60,
        "desc": "Aave is the dominant DeFi money market — $10B+ in TVL across Ethereum, Arbitrum, Polygon, and Avalanche. It supports 30+ collateral types, flash loans, credit delegation, and a GHO native stablecoin. The protocol's risk parameters are battle-tested across three market cycles and multiple black swan events.",
        "why_selected": "If you run a crypto fund-of-funds and aren't watching Aave, you're not watching DeFi. It is the benchmark lending rate for on-chain capital — equivalent to LIBOR in TradFi. We track it as both an alpha source and a systemic risk indicator.",
        "strengths": ["$10B+ TVL across 7+ chains — largest DeFi lending protocol", "10/10 audit score: OpenZeppelin, Certik, SigmaPrime, Trail of Bits", "Flash loans, credit delegation, GHO stablecoin — full ecosystem", "5 years continuous operation through all major market cycles"],
    },
    {
        "id": "compound", "name": "Compound", "slug": "compound-finance",
        "category": "DeFi - Lending", "chain": "Multi-chain",
        "base_apy": 2.8, "audit_score": 10, "age_months": 60,
        "desc": "Compound invented algorithmic on-chain money markets in 2018. Its interest rate model — continuous, market-driven, reactive — became the template every subsequent lending protocol copied. Compound v3 (Comet) introduced single-asset borrowing markets with improved capital efficiency and reduced governance surface.",
        "why_selected": "Compound's institutional API and integrations with traditional broker-dealers make it a critical piece of the emerging TradFi-DeFi bridge. Its conservative approach — lower yields, tighter risk params — is exactly what institutional allocators need as a gateway product.",
        "strengths": ["Original DeFi money market — invented the model (2018)", "v3 Comet: cleaner architecture, better capital efficiency", "Institutional API used by broker-dealers and prime brokers", "Most governance-decentralised major lending protocol"],
    },
    {
        "id": "morpho", "name": "Morpho", "slug": "morpho",
        "category": "DeFi - Lending", "chain": "Ethereum",
        "base_apy": 5.5, "audit_score": 9, "age_months": 24,
        "desc": "Morpho is a peer-to-peer lending optimizer that sits on top of Aave and Compound, matching lenders and borrowers directly when possible to eliminate the spread that pool-based AMMs always clip. Unmatched liquidity falls back to the underlying protocol, so there is zero duration mismatch risk. Morpho Blue extends this to permissionless market creation.",
        "why_selected": "Morpho solves a structural inefficiency: pool-based lending always benefits from a spread that should belong to lenders and borrowers. Its $2B+ TVL growth from zero in 24 months, with no pool-based liquidity risk, is the strongest product-market fit signal in the lending category.",
        "strengths": ["P2P matching eliminates AMM spread — better rates for both sides", "Morpho Blue: permissionless market creation, no governance gatekeeping", "Zero duration mismatch — unmatched capital is always in Aave/Compound", "Fastest TVL growth in lending category: $0 → $2B in 24 months"],
    },

    # DeFi — DEX / Liquidity
    {
        "id": "uniswap", "name": "Uniswap", "slug": "uniswap",
        "category": "DeFi - DEX", "chain": "Multi-chain",
        "base_apy": 0, "audit_score": 10, "age_months": 72,
        "desc": "Uniswap is the most-used DEX in crypto — $1T+ cumulative volume, 12+ chains, and 6 years of continuous operation. Its concentrated liquidity model (v3) let LPs deploy capital within custom price ranges for higher fee capture. Uniswap v4 introduces hooks — arbitrary custom logic at the pool level — making it a programmable liquidity primitive.",
        "why_selected": "Uniswap is DeFi's price discovery layer. Every fund that touches crypto interacts with it, either directly or through aggregators that route through it. It is the rails — and we need exposure to the rails.",
        "strengths": ["$1T+ cumulative trading volume — dominant market share", "v4 hooks: programmable AMM logic unlocks infinite protocol design space", "10/10 audit score across 6 years of open-source scrutiny", "LP fee revenue is real, sustainable yield — not token emissions"],
    },
    {
        "id": "curve", "name": "Curve Finance", "slug": "curve-finance",
        "category": "DeFi - DEX", "chain": "Multi-chain",
        "base_apy": 2.0, "audit_score": 9, "age_months": 60,
        "desc": "Curve Finance runs the deepest stablecoin and pegged-asset liquidity in DeFi. Its StableSwap invariant minimises slippage on correlated assets — USDC/USDT, stETH/ETH, crvUSD — making it the backbone of stable liquidity across the ecosystem. The veToken governance model (vote-escrowed CRV) created Curve Wars, influencing emissions allocation across the entire DeFi sector.",
        "why_selected": "Curve is critical DeFi infrastructure. Every stablecoin yield strategy runs through it. Every RWA protocol that needs secondary market liquidity will need Curve pools. We track it as both a yield source and an ecosystem health indicator.",
        "strengths": ["Deepest stablecoin liquidity in DeFi — $3B+ TVL", "StableSwap: lowest slippage for pegged assets by design", "veToken model drives multi-protocol governance participation (Curve Wars)", "crvUSD: native over-collateralized stablecoin adds protocol revenue"],
    },
    {
        "id": "jupiter", "name": "Jupiter", "slug": "jupiter",
        "category": "DeFi - DEX", "chain": "Solana",
        "base_apy": 0, "audit_score": 8, "age_months": 24,
        "desc": "Jupiter is Solana's dominant DEX aggregator — routing trades across Orca, Raydium, Lifinity, and every other Solana AMM to find best execution. Its JLP (Jupiter Liquidity Pool) lets LPs earn fees from perp trading activity. Jupiter processes $1B+ monthly volume and is the primary interface for most Solana DeFi users.",
        "why_selected": "CometCloud's Solana-native architecture means Jupiter is native infrastructure for us. As Solana's liquidity aggregation layer, it compounds any volume growth on the chain directly into protocol revenue. Its perp product diversifies revenue beyond AMM fees.",
        "strengths": ["Solana's #1 DEX aggregator — dominant routing market share", "JLP vault: earn fees from leveraged perp trading, not just AMM swaps", "Best execution routing across all major Solana liquidity sources", "Core Solana ecosystem infrastructure — grows with the chain"],
    },

    # DeFi — Liquid Staking
    {
        "id": "lido", "name": "Lido", "slug": "lido",
        "category": "DeFi - Staking", "chain": "Multi-chain",
        "base_apy": 3.2, "audit_score": 10, "age_months": 48,
        "desc": "Lido issues stETH — liquid staking tokens representing staked ETH plus accrued rewards. With $20B+ in TVL, it stakes roughly 32% of all ETH in the network. stETH is accepted as collateral on Aave, Compound, Morpho, and used in dozens of DeFi strategies. Lido is actively decentralising its node operator set via DVT (Distributed Validator Technology).",
        "why_selected": "stETH is the most liquid, most deeply integrated yield-bearing asset in DeFi. Any strategy that runs through Ethereum-based DeFi either holds stETH or competes with strategies that do. It is the risk-free rate of the Ethereum ecosystem.",
        "strengths": ["$20B+ TVL — largest staking protocol by a factor of 5x", "stETH accepted as collateral across all major DeFi lending markets", "Real ETH staking yield — not token emissions", "DVT roadmap addresses validator concentration risk systematically"],
    },
    {
        "id": "rocketpool", "name": "Rocket Pool", "slug": "rocket-pool",
        "category": "DeFi - Staking", "chain": "Ethereum",
        "base_apy": 3.0, "audit_score": 9, "age_months": 36,
        "desc": "Rocket Pool runs a decentralised ETH staking network where node operators post 8 ETH + RPL collateral to create minipools, completing 32 ETH validator requirements by drawing from a rETH deposit pool. Its trust model is fundamentally more decentralised than Lido — no allowlisted operators, no multi-sig custody.",
        "why_selected": "For a fund positioning around long-term Ethereum health, rETH is the more philosophically aligned choice. Network decentralisation is a risk factor for Ethereum consensus — protocols that reduce validator concentration reduce systemic risk to the network we rely on.",
        "strengths": ["Truly permissionless node operator set — no KYC or allowlisting", "rETH value accrual model — token appreciates vs ETH, no rebasing", "RPL collateral requirement aligns node operator incentives with protocol health", "Lower counterparty risk than operator-allowlisted alternatives"],
    },
    {
        "id": "jito", "name": "Jito", "slug": "jito",
        "category": "DeFi - Staking", "chain": "Solana",
        "base_apy": 7.5, "audit_score": 8, "age_months": 18,
        "desc": "Jito operates Solana's dominant MEV-aware liquid staking protocol. JitoSOL holders earn both base staking rewards and a share of MEV (Maximum Extractable Value) tips collected by the Jito-client validator software, which now powers the majority of Solana's validator stake. The additional MEV yield creates a structural APY premium over vanilla SOL staking.",
        "why_selected": "Jito's MEV capture is unique — it redistributes value that would otherwise go to sophisticated searchers back to JitoSOL holders. On a chain processing $1B+ daily volume, MEV is material yield. For our Solana-native architecture, JitoSOL is the optimal base asset.",
        "strengths": ["MEV tip redistribution — structural yield premium over vanilla staking", "Jito-client powers majority of Solana validator stake — entrenched infrastructure", "7.5%+ APY: highest yield for non-speculative SOL exposure", "JitoSOL: deep liquidity as Solana's premier yield-bearing collateral asset"],
    },

    # Derivatives
    {
        "id": "hyperliquid", "name": "Hyperliquid", "slug": "hyperliquid",
        "category": "Derivatives", "chain": "Hyperliquid",
        "base_apy": 0, "audit_score": 7, "age_months": 18,
        "desc": "Hyperliquid is a vertically integrated L1 blockchain purpose-built for high-performance perpetual futures trading. Its on-chain order book processes 100,000+ orders per second with sub-second finality. The HLP (Hyperliquidity Provider) vault lets passive LPs earn fees by acting as a market maker across all perp markets.",
        "why_selected": "Hyperliquid broke the assumption that CEX-grade performance requires centralisation. $2B+ TVL with zero VC backing and organic growth is a signal that the market validated its architecture before anyone prompted it to. For derivatives exposure, this is the protocol with the strongest PMF.",
        "strengths": ["100k+ orders/second on-chain — CEX-grade performance, DEX ownership", "$2B+ TVL grown entirely organically — no VC pump, no airdrop farming", "HLP vault: passive LP access to market-making yield", "Owns its own L1 — no dependency on Ethereum gas or sequencer latency"],
    },
    {
        "id": "gmx", "name": "GMX", "slug": "gmx",
        "category": "Derivatives", "chain": "Arbitrum",
        "base_apy": 0, "audit_score": 9, "age_months": 30,
        "desc": "GMX runs a decentralised perpetual and spot trading platform where LPs fund a multi-asset liquidity pool (GLP) that acts as counterparty to traders. GLP earns 70% of platform fees and is itself a yield-bearing basket of BTC, ETH, and stablecoins. GMX v2 introduced isolated markets with better risk partitioning.",
        "why_selected": "GMX's GLP model proved that LPs can profit by acting as the house in a leveraged trading market. Its $400M+ GLP pool has generated consistent fee revenue through bull and bear cycles — a rare thing in DeFi. The v2 upgrade substantially improved capital efficiency and risk controls.",
        "strengths": ["GLP LPs earn 70% of all trading fees — real, consistent revenue", "Multi-asset pool (BTC/ETH/stables) — natural hedge against directional markets", "v2 isolated markets reduce systemic risk from single asset blowouts", "3-year track record of fee generation through multiple market regimes"],
    },
    {
        "id": "dydx", "name": "dYdX", "slug": "dydx",
        "category": "Derivatives", "chain": "Cosmos",
        "base_apy": 0, "audit_score": 9, "age_months": 48,
        "desc": "dYdX v4 operates as a sovereign Cosmos appchain, giving it full control over its order book, matching engine, and fee structure without dependency on Ethereum's throughput constraints. It is the oldest decentralised perps exchange and is optimised for professional and institutional trading workflows.",
        "why_selected": "dYdX took the bold move of launching its own chain to escape EVM throughput limits. That architectural bet positions it for institutional adoption — traditional trading firms require order book performance that no EVM chain can currently deliver. We track it as the institutional-grade perps benchmark.",
        "strengths": ["Cosmos appchain: full sovereignty over performance and fee parameters", "Order book model — familiar UX for professional and institutional traders", "4 years of continuous operation — oldest decentralised perps exchange", "Staking dYdX earns a share of protocol trading fees"],
    },

    # Infrastructure
    {
        "id": "eigenlayer", "name": "EigenLayer", "slug": "eigenlayer",
        "category": "Infrastructure", "chain": "Ethereum",
        "base_apy": 3.8, "audit_score": 8, "age_months": 18,
        "desc": "EigenLayer introduced restaking — the ability to use staked ETH as cryptoeconomic security for additional protocols (Actively Validated Services, or AVSs) simultaneously. Restakers can earn additional yield from AVS fees on top of base ETH staking rewards. It currently secures $10B+ in restaked ETH and is bootstrapping security for a new class of decentralised infrastructure services.",
        "why_selected": "EigenLayer is creating a new economic primitive: pooled cryptoeconomic security. Every new protocol that builds on AVS infrastructure rather than bootstrapping its own validator set makes EigenLayer more valuable. In 18 months it became the largest DeFi protocol by TVL — that velocity is signal.",
        "strengths": ["$10B+ TVL — largest DeFi protocol by TVL in 2024", "Restaking enables yield stacking on top of base ETH staking rewards", "AVS ecosystem: oracles, bridges, data availability layers all leverage it", "Enables new protocols to bootstrap security without dilutive token issuance"],
    },
    {
        "id": "ethena", "name": "Ethena", "slug": "ethena",
        "category": "Infrastructure", "chain": "Ethereum",
        "base_apy": 15.0, "audit_score": 7, "age_months": 12,
        "desc": "Ethena issues USDe — a synthetic dollar backed by ETH spot holdings hedged with short ETH perpetual futures positions, making it delta-neutral. The funding rate earned from the short perp position (typically positive when markets are bullish) is distributed to sUSDe stakers, generating 10–25% APY in bull markets. In bear markets, negative funding can compress yield.",
        "why_selected": "USDe is the most economically interesting stablecoin design since DAI. Its yield is derived from a real market mechanism — perp funding rates — not from token inflation or unsustainable subsidies. We hold it as a high-yield satellite position with clear risk parameters: yield goes negative when perp funding inverts.",
        "strengths": ["15%+ APY from structural perp funding rate — not emissions", "Delta-neutral design: ETH spot long + ETH perp short = price-neutral exposure", "Rapidly became top-5 stablecoin by market cap from launch", "Transparent risk: funding rate publicly observable, risk is understood"],
    },
    {
        "id": "pendle", "name": "Pendle", "slug": "pendle",
        "category": "DeFi - Yield", "chain": "Multi-chain",
        "base_apy": 8.0, "audit_score": 8, "age_months": 30,
        "desc": "Pendle splits yield-bearing tokens into Principal Tokens (PT) and Yield Tokens (YT), allowing users to trade future yield independently of principal. A trader who expects yields to rise buys YT; one who wants fixed-rate exposure locks in yield by holding PT to maturity. This creates a yield curve for DeFi — the first on-chain fixed-rate market with genuine depth.",
        "why_selected": "Pendle is building the DeFi yield curve — the infrastructure that fixed-income desks need to manage duration risk systematically. As RWA yield products multiply, the ability to trade and hedge yield duration becomes essential. Pendle is the only protocol with real TVL doing this.",
        "strengths": ["First DeFi protocol with a functioning yield curve (PT/YT split)", "$3B+ TVL across Ethereum, Arbitrum, BNB Chain, Mantle", "Fixed-rate locking on stETH, eETH, USDe — institutional demand use case", "Rapidly becoming the yield management layer for RWA products"],
    },
    {
        "id": "maker", "name": "Sky (MakerDAO)", "slug": "makerdao",
        "category": "DeFi - Stablecoin", "chain": "Ethereum",
        "base_apy": 5.0, "audit_score": 10, "age_months": 84,
        "desc": "MakerDAO (rebranding as Sky) is the oldest major DeFi protocol and issuer of DAI — the first decentralised stablecoin by scale. DAI is backed by a mix of ETH, WBTC, and real-world assets including USDC, US Treasuries via Centrifuge vaults, and T-bill ETFs. The DAI Savings Rate (DSR) provides baseline yield to all DAI holders.",
        "why_selected": "MakerDAO is the bedrock of DeFi. Seven years of continuous operation, $5B+ DAI supply, and deep integration across every major protocol means it functions as critical financial infrastructure. Its RWA allocation — $2B+ in T-bills and credit instruments — makes it a direct expression of our thesis.",
        "strengths": ["7 years live — longest-running major DeFi protocol", "10/10 audit score — most thoroughly audited codebase in DeFi", "$2B+ deployed in RWA (T-bills, Centrifuge vaults) — DeFi's largest RWA allocator", "DAI is accepted collateral in every major DeFi protocol on Ethereum"],
    },
]


# ── DeFiLlama TVL Fetcher ───────────────────────────────────────────────────

async def _fetch_defillama_tvl(slug: str) -> dict | None:
    """Fetch TVL + TVL changes from DeFiLlama for a single protocol."""
    cache_key = f"proto_tvl:{slug}"
    cached = _cget(cache_key, ttl=600)  # 10min cache
    if cached is not None:
        return cached

    try:
        async with httpx.AsyncClient(timeout=8) as client:
            r = await client.get(f"https://api.llama.fi/protocol/{slug}")
            if r.status_code != 200:
                return _cset(cache_key, None)
            data = r.json()
            tvl_now = data.get("currentChainTvls", {})
            total_tvl = sum(v for k, v in tvl_now.items()
                           if not k.endswith("-borrowed") and not k.endswith("-staking")
                           and isinstance(v, (int, float)))
            if total_tvl == 0:
                total_tvl = data.get("tvl", [{}])[-1].get("totalLiquidityUSD", 0) if data.get("tvl") else 0

            # TVL history for 7d/30d change
            tvl_history = data.get("tvl", [])
            tvl_7d_ago = None
            tvl_30d_ago = None
            now_ts = time.time()
            for point in reversed(tvl_history):
                ts = point.get("date", 0)
                age_days = (now_ts - ts) / 86400
                if tvl_7d_ago is None and age_days >= 6.5:
                    tvl_7d_ago = point.get("totalLiquidityUSD", 0)
                if tvl_30d_ago is None and age_days >= 29:
                    tvl_30d_ago = point.get("totalLiquidityUSD", 0)
                if tvl_7d_ago and tvl_30d_ago:
                    break

            change_7d = ((total_tvl - tvl_7d_ago) / tvl_7d_ago * 100) if tvl_7d_ago and tvl_7d_ago > 0 else 0
            change_30d = ((total_tvl - tvl_30d_ago) / tvl_30d_ago * 100) if tvl_30d_ago and tvl_30d_ago > 0 else 0

            result = {
                "tvl": total_tvl,
                "tvl_7d_ago": tvl_7d_ago,
                "tvl_30d_ago": tvl_30d_ago,
                "change_7d": round(change_7d, 2),
                "change_30d": round(change_30d, 2),
                "chains": list(tvl_now.keys())[:5],
                "mcap": data.get("mcap", 0),
                "category": data.get("category", ""),
            }
            return _cset(cache_key, result)
    except Exception:
        return _cset(cache_key, None)


async def fetch_all_protocol_tvls() -> dict:
    """Batch fetch TVL for all protocols. Returns {id: tvl_data}."""
    cache_key = "proto_tvl_all"
    cached = _cget(cache_key, ttl=300)
    if cached is not None:
        return cached

    tasks = []
    for p in PROTOCOL_REGISTRY:
        tasks.append(_fetch_defillama_tvl(p["slug"]))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    tvl_map = {}
    for p, result in zip(PROTOCOL_REGISTRY, results):
        if isinstance(result, dict) and result:
            tvl_map[p["id"]] = result
        else:
            tvl_map[p["id"]] = None

    return _cset(cache_key, tvl_map)


# ── CIS Scoring Engine for Protocols ────────────────────────────────────────

def _score_protocol(proto: dict, tvl_data: dict | None, category_stats: dict) -> dict:
    """
    Score a single protocol across F/M/O/S/A pillars.
    Returns full scored protocol object.
    """
    pid = proto["id"]
    cat = proto["category"]

    tvl = tvl_data["tvl"] if tvl_data else 0
    chg_7d = tvl_data["change_7d"] if tvl_data else 0
    chg_30d = tvl_data["change_30d"] if tvl_data else 0
    live_tvl = tvl_data is not None

    # ── F pillar (Fundamental): TVL scale + audit + age ──────────────────
    # TVL score: log scale, max 30 at $10B+
    if tvl > 0:
        tvl_pts = min(30, max(0, int(math.log10(max(tvl, 1)) * 4 - 12)))
    else:
        tvl_pts = 0

    # Audit quality (0-10 input → 0-15 points)
    audit_pts = int(proto.get("audit_score", 5) * 1.5)

    # Protocol age maturity (months → points, max 15)
    age = proto.get("age_months", 0)
    age_pts = min(15, int(age / 4))

    # APY contribution (yield-bearing protocols get F boost)
    apy = proto.get("base_apy", 0)
    apy_pts = min(10, int(apy * 0.8)) if apy > 0 else 0

    f_score = min(40, tvl_pts + audit_pts + age_pts + apy_pts)

    # ── M pillar (Momentum): TVL change direction ────────────────────────
    m_7d = min(15, max(-15, int(chg_7d * 0.5)))
    m_30d = min(10, max(-10, int(chg_30d * 0.2)))
    m_base = 10 if tvl > 1e9 else 5 if tvl > 1e8 else 0
    m_score = max(0, min(30, m_base + m_7d + m_30d))

    # ── O pillar (On-chain / Risk): audit + age + TVL stability ──────────
    audit_risk = proto.get("audit_score", 5) * 2  # 0-20
    # TVL stability: penalize large drawdowns
    stability = 10
    if chg_7d < -15:
        stability -= 5
    if chg_30d < -30:
        stability -= 5
    # Age maturity for risk
    age_risk = min(10, int(age / 6))
    o_score = min(30, max(0, audit_risk + stability + age_risk))

    # ── S pillar (Sentiment): TVL growth = positive market perception ────
    s_growth = 5 if chg_7d > 5 else 0
    s_scale = min(10, int(math.log10(max(tvl, 1)) * 1.5 - 5)) if tvl > 0 else 0
    s_category = 5 if "RWA" in cat else 3  # RWA narrative premium 2026
    s_score = max(0, min(20, s_growth + s_scale + s_category))

    # ── A pillar (Alpha): outperformance vs category average ─────────────
    cat_avg_chg = category_stats.get(cat, {}).get("avg_change_7d", 0)
    alpha_vs_peers = chg_7d - cat_avg_chg
    a_outperform = min(10, max(-10, int(alpha_vs_peers * 0.5)))
    # Small protocols with high momentum = alpha opportunity
    a_size_bonus = 5 if tvl < 5e8 and chg_7d > 10 else 0
    a_score = max(0, min(20, 5 + a_outperform + a_size_bonus))

    # ── Composite ────────────────────────────────────────────────────────
    total = f_score + m_score + o_score + s_score + a_score
    # Normalize to 0-100
    max_possible = 40 + 30 + 30 + 20 + 20  # = 140
    normalized = round(total / max_possible * 100, 1)

    # Grade (protocol-specific thresholds)
    if normalized >= 75:
        grade = "A+"
    elif normalized >= 65:
        grade = "A"
    elif normalized >= 55:
        grade = "B+"
    elif normalized >= 45:
        grade = "B"
    elif normalized >= 35:
        grade = "C+"
    elif normalized >= 25:
        grade = "C"
    elif normalized >= 15:
        grade = "D"
    else:
        grade = "F"

    # Signal — compliance-safe positioning language (no buy/sell)
    if normalized >= 65 and chg_7d > 0:
        signal = "OUTPERFORM"
    elif normalized >= 50:
        signal = "NEUTRAL"
    elif normalized >= 35:
        signal = "UNDERPERFORM"
    else:
        signal = "UNDERWEIGHT"

    # Recommended weight (basis points of portfolio)
    if signal == "OUTPERFORM":
        rec_weight = min(800, max(200, int(normalized * 8)))
    elif signal == "NEUTRAL":
        rec_weight = min(500, max(100, int(normalized * 4)))
    elif signal == "UNDERPERFORM":
        rec_weight = max(0, int(normalized * 2))
    else:
        rec_weight = 0

    # Risk tier
    if o_score >= 25 and f_score >= 25:
        risk_tier = "LOW"
    elif o_score >= 15:
        risk_tier = "MEDIUM"
    else:
        risk_tier = "HIGH"

    # Direction arrow
    if chg_7d > 3:
        tvl_direction = "UP"
    elif chg_7d < -3:
        tvl_direction = "DOWN"
    else:
        tvl_direction = "FLAT"

    return {
        "id": pid,
        "name": proto["name"],
        "category": cat,
        "chain": proto["chain"],
        "description": proto["desc"],
        "why_selected": proto.get("why_selected", ""),
        "strengths": proto.get("strengths", []),
        "live_data": live_tvl,
        "tvl": round(tvl, 0) if tvl else 0,
        "tvl_formatted": _fmt_usd(tvl),
        "tvl_change_7d": chg_7d,
        "tvl_change_30d": chg_30d,
        "tvl_direction": tvl_direction,
        "apy": apy,
        "cis_score": normalized,
        "grade": grade,
        "signal": signal,
        "risk_tier": risk_tier,
        "recommended_weight_bps": rec_weight,
        "pillars": {
            "F": round(f_score / 40 * 100),
            "M": round(m_score / 30 * 100),
            "O": round(o_score / 30 * 100),
            "S": round(s_score / 20 * 100),
            "A": round(a_score / 20 * 100),
        },
        "audit_score": proto.get("audit_score", 0),
        "age_months": proto.get("age_months", 0),
    }


def _fmt_usd(v: float) -> str:
    if not v:
        return "$0"
    if v >= 1e12:
        return f"${v/1e12:.1f}T"
    if v >= 1e9:
        return f"${v/1e9:.2f}B"
    if v >= 1e6:
        return f"${v/1e6:.1f}M"
    if v >= 1e3:
        return f"${v/1e3:.0f}K"
    return f"${v:.0f}"


def _compute_category_stats(protocols: list, tvl_map: dict) -> dict:
    """Compute category-level averages for alpha calculation."""
    cat_data: dict = {}
    for p in protocols:
        cat = p["category"]
        tvl_d = tvl_map.get(p["id"])
        if tvl_d:
            cat_data.setdefault(cat, []).append(tvl_d.get("change_7d", 0))
    return {
        cat: {"avg_change_7d": sum(vals) / len(vals) if vals else 0}
        for cat, vals in cat_data.items()
    }


# ── Main Entry Point ────────────────────────────────────────────────────────

async def get_protocol_universe(category: str | None = None,
                                 min_grade: str | None = None) -> dict:
    """
    Full protocol intelligence universe.
    Returns scored, ranked, categorized protocol list.
    """
    cache_key = f"proto_universe:{category or 'all'}:{min_grade or 'all'}"
    cached = _cget(cache_key, ttl=300)
    if cached is not None:
        return cached

    # 1. Fetch all TVLs
    tvl_map = await fetch_all_protocol_tvls()

    # 2. Category stats for alpha calculation
    cat_stats = _compute_category_stats(PROTOCOL_REGISTRY, tvl_map)

    # 3. Score each protocol
    scored = []
    for proto in PROTOCOL_REGISTRY:
        tvl_data = tvl_map.get(proto["id"])
        result = _score_protocol(proto, tvl_data, cat_stats)
        scored.append(result)

    # 4. Sort by CIS score descending
    scored.sort(key=lambda x: (-x["cis_score"],))

    # 5. Assign ranks
    for i, p in enumerate(scored):
        p["rank"] = i + 1

    # 6. Filter
    grade_order = ["A+", "A", "B+", "B", "C+", "C", "D", "F"]
    if min_grade and min_grade in grade_order:
        min_idx = grade_order.index(min_grade)
        scored = [p for p in scored if grade_order.index(p["grade"]) <= min_idx]

    if category:
        cat_lower = category.lower()
        scored = [p for p in scored
                  if cat_lower in p["category"].lower()]

    # 7. Category summary
    categories = {}
    for p in scored:
        cat = p["category"]
        if cat not in categories:
            categories[cat] = {"count": 0, "total_tvl": 0, "avg_score": 0, "scores": []}
        categories[cat]["count"] += 1
        categories[cat]["total_tvl"] += p["tvl"]
        categories[cat]["scores"].append(p["cis_score"])
    for cat, info in categories.items():
        info["avg_score"] = round(sum(info["scores"]) / len(info["scores"]), 1) if info["scores"] else 0
        info["total_tvl_formatted"] = _fmt_usd(info["total_tvl"])
        del info["scores"]

    # 8. Top picks (agent-recommended)
    top_picks = [p["id"] for p in scored if p["signal"] == "OUTPERFORM"][:5]

    result = {
        "status": "success",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": "1.0.0",
        "total_protocols": len(scored),
        "total_tvl": _fmt_usd(sum(p["tvl"] for p in scored)),
        "agent_picks": top_picks,
        "categories": categories,
        "protocols": scored,
    }
    return _cset(cache_key, result)
