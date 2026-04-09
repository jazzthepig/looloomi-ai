# CometCloud AI — Asset Exclusion List
**Version:** 1.1
**Effective date:** April 2026
**Status:** Recalibrated — v1.1 reinstates HYPER, moves RUNE to borderline remediation review
**Last updated:** 2026-04-09
**Total excluded:** ~14 confirmed + 5 borderline (see §3)

This document lists assets that have been evaluated against the CometCloud AI Inclusion Standard and excluded from the investable universe. Each exclusion includes the specific criterion(ia) triggered and the specific reason.

For the full criteria definitions, see [INCLUSION_STANDARD.md](./INCLUSION_STANDARD.md).

---

## 1. Confirmed Exclusions

### Memecoin / Speculative Assets

---

**BONK (Bonk)**
- **Criterion violated:** 3 (Custody), 7 (Team Integrity)
- **Reason:** No institutional custodian support as of April 2026. Core team is anonymous with no registered legal entity. Protocol has no utility beyond speculative trading and community distribution. Passes liquidity threshold but fails institutional accountability requirements.
- **Excluded since:** Initial review, April 2026

---

**PEPE (Pepe)**
- **Criterion violated:** 3 (Custody), 7 (Team Integrity)
- **Reason:** Launched as an explicitly anonymous memecoin project in April 2023. No institutional custodian support. No registered legal entity. No protocol utility. Despite achieving significant market capitalization, the project structure explicitly lacks the institutional accountability framework required.
- **Excluded since:** Initial review, April 2026

---

**WIF (dogwifhat)**
- **Criterion violated:** 3 (Custody), 6 (Trading History), 7 (Team Integrity)
- **Reason:** Launched December 2023, reaching 180-day mark in June 2024 but without institutional custodian onboarding. Anonymous team. No protocol utility. No legal entity. The asset's rapid market cap appreciation reflects retail speculation, not institutional-grade fundamentals.
- **Excluded since:** Initial review, April 2026

---

### Gaming / Metaverse Assets

---

**AXS (Axie Infinity)**
- **Criterion violated:** 7 (Team/Protocol Integrity)
- **Reason:** Ronin bridge exploit, March 2022 — $625M in user funds drained by the Lazarus Group (North Korean state-sponsored hackers). Largest single DeFi hack in history. Root cause: validator key compromise due to inadequate key management practices. Sky Mavis (the issuing company) provided partial restitution over 2022–2023 but full user compensation was not achieved. The security failure represents a fundamental custody and operational risk that disqualifies the asset from institutional consideration regardless of subsequent remediation. The exploit also triggered OFAC sanctions designation on associated wallets.
- **Excluded since:** Initial review, April 2026
- **Note to Jazz:** Sky Mavis has rebuilt the Ronin bridge with more validators and improved key management. If CometCloud wants to reassess in 2027 after 3+ years of clean operation post-rebuild, this exclusion could be reviewed. Not recommended before then.

---

**MANA (Decentraland)**
- **Criterion violated:** 1 (Liquidity), 2 (Data Completeness)
- **Reason:** 30-day average daily volume has declined below the $5M threshold as of Q1 2026. Daily Active Users in Decentraland consistently below 1,000, making on-chain engagement data insufficient for reliable F pillar scoring. The metaverse narrative that drove 2021 peak volume has structurally reversed. Liquidity may temporarily recover during risk-on cycles but has shown a persistent downtrend since 2022.
- **Excluded since:** Initial review, April 2026

---

**SAND (The Sandbox)**
- **Criterion violated:** 1 (Liquidity)
- **Reason:** Similar to MANA — 30-day average daily volume has declined to approximately $8-12M, borderline against the threshold, but with a consistent downtrend that places it at risk of breaching the threshold during illiquid periods. The Sandbox has maintained marginally better liquidity than Decentraland due to partnerships (Atari, Adidas, Gucci virtual land sales), but these are marketing events, not evidence of sustainable protocol activity. Borderline exclusion — downgraded on liquidity trend basis.
- **Excluded since:** Initial review, April 2026
- **Note to Jazz:** SAND is the most debatable exclusion in this list. If the metaverse narrative recovers with AI-driven virtual environments, this exclusion should be the first one reviewed.

---

### DeFi Protocols

---

**CRV (Curve Finance)**
- **Criterion violated:** 7 (Team/Protocol Integrity)
- **Reason:** In mid-2023, founder Michael Egorov held approximately $168M in personal DeFi loans collateralized against CRV tokens. These positions created a systemic risk to Curve's own liquidity pools — a liquidation cascade would have damaged the primary pools that the protocol depends on for fee revenue and TVL. This represents a fundamental conflict of interest between the founder's personal financial positions and the protocol's health. The situation was resolved through OTC sales to multiple parties (DeFi whales including Justin Sun, Machi Big Brother, and others), but the structure of those OTC sales — at steep discounts to market price — itself raised governance concerns. The founder's ability to use his token allocation as personal leverage at scale is a disqualifying integrity condition.
- **Excluded since:** Initial review, April 2026

---

**SUSHI (SushiSwap)**
- **Criterion violated:** 7 (Team/Protocol Integrity)
- **Reason:** Multiple documented integrity incidents spanning 2020–2024. September 2020: pseudonymous founder "Chef Nomi" withdrew ~$14M from the developer fund without governance approval, subsequently returned under community pressure. 2021–2022: repeated leadership transitions including Maki, Jared Grey, with allegations of toxic governance culture. 2023: allegations of treasury mismanagement surfaced during internal audit. 2024: key contributor departures and continued governance fragmentation. The pattern of repeated integrity incidents across multiple leadership generations distinguishes SUSHI from a single-incident recovery case.
- **Excluded since:** Initial review, April 2026

---

**RUNE (Thorchain)**
- **Status:** Moved to §3 Borderline — remediation pathway review
- **Original criterion:** 7 (Team/Protocol Integrity) — dual exploit window in 2021
- **Recalibration note (v1.1):** Thorchain has operated cleanly for 3+ years post-2021. Both incidents were disclosed publicly, post-mortems published, and partial compensation was made. Under the v1.1 remediation pathway (12+ consecutive months clean operation + audit), RUNE may now qualify. See §3 for full borderline assessment.
- **Moved to §3 borderline:** April 2026

---

**SNX (Synthetix)**
- **Criterion violated:** 2 (Data Completeness — scoring confidence)
- **Reason:** SNX has undergone three major product pivots since 2021 — from synthetic asset issuance to perpetuals infrastructure to a partial deprecation of the V2 synthetic platform. The multiple pivots create discontinuity in the on-chain data time series that prevents reliable F pillar scoring (the TVL and protocol revenue data from V2 and V3 cannot be compared on a continuous basis). Additionally, as of Q1 2026, SNX TVL is approximately $150M — declining from ~$2B peak — with unclear product-market fit for V3. The data completeness issue is secondary to the more fundamental concern about the protocol's trajectory, but the criterion is cleanly triggered by the data discontinuity.
- **Excluded since:** Initial review, April 2026

---

### Infrastructure

---

**ICP (Internet Computer)**
- **Criterion violated:** 5 (Token Mechanics)
- **Reason:** The ICP token's supply mechanics at launch (May 2021) included a neuron reward system that resulted in undisclosed inflation of approximately 90%+ in the first 8 months. The initial tokenomics documentation published before launch did not clearly disclose the full emission schedule, particularly the magnitude of the neuron staking rewards and the speed of their issuance. Dfinity (the issuing foundation) published post-hoc analyses but has never issued a formal correction acknowledging the disclosure gap. This constitutes a historical undisclosed inflation event under Criterion 5. The ICP token also has ongoing NNS (Network Nervous System) governance reward emissions that are variable and not fully predictable, creating ongoing supply schedule uncertainty.
- **Excluded since:** Initial review, April 2026

---

**RUNE** — see DeFi section above.

---

**VIRTUAL (Virtuals Protocol)**
- **Criterion violated:** 3 (Custody)
- **Reason:** Launched Q4 2024. Under the recalibrated Criterion 6 (90-day standard), VIRTUAL now passes the trading history gate. However, no institutional custodian from the Criterion 3 list currently offers VIRTUAL custody as of April 2026. Coinbase has not yet listed VIRTUAL. The AI agent narrative is strong and the protocol has genuine on-chain activity, but custody availability is the hard gate. Reassess when Coinbase, BitGo, or Fireblocks adds coverage.
- **Excluded since:** Initial review, April 2026

---

### Legacy Crypto

---

**BCH (Bitcoin Cash)**
- **Criterion violated:** 4 (Regulatory Status)
- **Reason:** Roger Ver, the most prominent public advocate and early major holder of BCH, was indicted by the US Department of Justice in April 2024 on charges of tax evasion and wire fraud related to his cryptocurrency holdings. While Ver is not formally a "primary development team" member of the Bitcoin Cash protocol, his public association and holdings create a regulatory proximity concern for institutional allocators. Additionally, the Bitcoin Cash ecosystem has seen exchange delisting pressure. BCH itself is not under regulatory action, but this is the closest exclusion call in this list — excluded on a conservative reading of Criterion 4.
- **Excluded since:** Initial review, April 2026
- **Note to Jazz:** This is the most debatable exclusion. BCH itself is not charged. If you want to include BCH and accept the Roger Ver association risk, this is the one to argue for. The protocol is technically sound and has reasonable liquidity.

---

**FTM / SONIC (Fantom → Sonic)**
- **Criterion violated:** 5 (Token Mechanics)
- **Reason:** The Fantom Foundation completed a full rebrand to Sonic in January 2025, including a token migration from FTM to S (Sonic) at a 1:1 ratio. This creates an asset continuity question: the legacy FTM chain is being wound down, the Sonic chain is effectively a new asset, and the migration tokenomics include an airdrop of 190.5M S tokens to eligible participants. The supply mechanics of the rebranded asset are sufficiently different from the historical FTM record that continuous time-series scoring is not possible. Additionally, the mid-flight tokenomics change (new supply issuance through airdrop during the migration) triggers Criterion 5's emission schedule requirement.
- **Excluded since:** Initial review, April 2026 (applies to both FTM and S/SONIC)
- **Note to Jazz:** Once the Sonic chain establishes 12+ months of stable, post-migration tokenomics and achieves institutional custodian support for S (not FTM), it should be reviewed for fresh inclusion.

---

### RWA

---

**POLYX (Polymesh)**
- **Criterion violated:** 1 (Liquidity)
- **Reason:** POLYX 30-day average daily volume is approximately $250,000–$500,000 against the $5,000,000 minimum threshold. Polymesh is a purpose-built institutional blockchain for regulated assets (securities tokenization), and its tokenomics are structured for network staking rather than trading activity. The liquidity profile reflects a supply-constrained, staking-heavy asset that cannot be entered or exited at institutional size without significant market impact. The institutional thesis for Polymesh is sound, but the liquidity mechanics are fundamentally incompatible with portfolio inclusion until the broader ecosystem generates more secondary market activity.
- **Excluded since:** Initial review, April 2026
- **Note to Jazz:** If regulated securities tokenization takes off significantly in APAC in 2026–2027, POLYX liquidity could recover to threshold levels. One to watch.

---

## 2. Universe Size

**Starting pool evaluated:** 70 assets (current CIS engine coverage)
**Standard version:** v1.1 (Criterion 6 recalibrated to 90 days; Criterion 7 remediation pathway added)

| Asset class | Evaluated | Admitted | Excluded | Notes |
|-------------|-----------|----------|----------|-------|
| L1 | 17 | 16 | 1 (FTM) | HYPER reinstated under v1.1 Criterion 6 |
| L2 | 4 | 4 | 0 | |
| DeFi | 7 | 4 | 3 (CRV, SUSHI, SNX) | |
| Infrastructure | 9 | 8 | 1 (ICP) | RUNE moved to §3 borderline (remediation review) |
| Memecoin | 4 | 1† | 3 (BONK, PEPE, WIF) | |
| Gaming | 3 | 0 | 3 (AXS, MANA, SAND) | |
| AI | 1 | 0 | 1 (VIRTUAL) | Fails Criterion 3 custody only |
| RWA | 3 | 2 | 1 (POLYX) | |
| Crypto legacy | 2 | 1 | 1 (BCH) | |
| US Equity | 10 | 10 | 0 | |
| US Bond | 5 | 5 | 0 | |
| Commodity | 5 | 5 | 0 | |
| **Total** | **70** | **56†** | **14** | +5 borderline in §3 |

†DOGE: borderline, see §3

**Resulting investable universe: approximately 54–56 assets** (before borderline resolutions).

---

## 3. Borderline Cases — Jazz Decision Required

The following assets have a specific borderline condition or are under active remediation review. They are admitted into the universe on a provisional basis pending confirmation, or excluded pending a specific condition being resolved.

---

**DOGE (Dogecoin)**
- **Status:** Borderline pass
- **Issue:** DOGE passes all 7 criteria. It has 10+ years of trading history, is supported by Coinbase Custody and BitGo, has >$500M daily volume, has transparent supply mechanics (no cap, known inflation schedule), and its team is functionally the Bitcoin and Litecoin development community. The concern is narrative credibility: including DOGE in an institutional universe alongside BTC, ETH, and SOL requires a defensible rationale. The defensible rationale exists (it is the most widely held speculative crypto asset with genuine payment utility use cases), but it is a judgment call about institutional optics.
- **Recommendation:** Include. It passes the standard. Institutional optics concern is real but the standard exists to be applied consistently.

---

**HYPER (Hyperliquid)**
- **Status:** ✅ REINSTATED — admitted under v1.1 standard
- **Previous issue:** Criterion 6 (180-day trading history) under v1.0
- **Resolution:** Under v1.1's recalibrated 90-day standard plus fast-track eligibility: Coinbase custody confirmed (Criterion 3 ✓), full tokenomics published pre-launch (Criterion 5 ✓), institutional backing established (Criterion 6 fast-track ✓). Trading history now exceeds 90 days. HYPER passes all 7 criteria under v1.1.
- **Confidence note:** LAS confidence multiplier applied at 0.85× (>90 days, <180 days history) until May 2026, then full 1.0× confidence.
- **Reinstated:** April 2026 (v1.1 recalibration)

---

**RUNE (Thorchain)**
- **Status:** Borderline — remediation pathway review
- **Original exclusion:** Criterion 7 — dual exploit window June–July 2021 ($5M + $8M)
- **Remediation evidence:** Both incidents publicly disclosed with post-mortems. Partial user compensation. Independent Halborn security audit completed post-2021. **3+ consecutive years of clean operation** (July 2021 – April 2026). No repeat of the same vulnerability class.
- **Remediation pathway check:** Post-mortem ✓ | ≥80% user compensation — partial, unclear if fully met | Independent audit ✓ | 12+ months clean ✓ (36+ months) | No repeat vulnerability ✓
- **Recommendation:** Include under the remediation pathway with a "remediated" tag visible in the leaderboard. The compensation gap (partial vs full) is the only unresolved item — Jazz call on whether partial compensation + 3 years clean operation is sufficient.
- **Jazz decision required:** Include with "remediated" tag, or continue to exclude pending confirmation of user compensation amounts?

---

**MKR / SKY (MakerDAO → Sky Protocol)**
- **Status:** Borderline — Criterion 5 (Token Mechanics)
- **Issue:** MakerDAO rebranded to Sky Protocol in mid-2024, introducing the SKY governance token alongside MKR at a 24,000:1 conversion ratio. The rebrand created two co-existing tokens (MKR and SKY) with unclear deprecation timeline for MKR. The dual-token structure creates asset continuity questions similar to FTM/Sonic, but less severe — MKR remains fungible with SKY and the protocol treasury is unchanged. The question is whether to include MKR (established), SKY (new), or both.
- **Recommendation:** Include MKR only. MKR has 6+ years of history, institutional custody support, and a continuous data record. SKY is <18 months old and lacks the history. Exclude SKY until it accumulates 2+ years of operating history post-rebrand.

---

## 4. Assets NOT in Current Engine Scope

The following assets are candidates for future inclusion evaluation — they are not currently in the CIS engine but should be assessed in the next universe expansion review:

- **EIGEN (Eigenlayer)** — major restaking protocol with legitimate institutional interest
- **JUP (Jupiter)** — leading Solana DEX aggregator, high volume
- **W (Wormhole)** — major cross-chain bridge, institutional backing from Jump
- **PYTH (Pyth Network)** — oracle infrastructure with strong fundamentals
- **STRK (Starknet)** — major Ethereum L2 with significant developer activity
- **cbBTC / WBTC** — wrapped Bitcoin products for DeFi institutional users

These are not exclusions — they simply have not been evaluated yet. They should be the first candidates for the next universe expansion.

---

## 5. Maintenance

| Review type | Cadence | Trigger |
|-------------|---------|---------|
| Full universe review | Monthly | Calendar |
| Emergency exclusion | Within 24h | Exploit >$1M, enforcement action, liquidity breach 7 consecutive days |
| Borderline re-evaluation | At next monthly review | When the specific condition blocking inclusion resolves |
| New asset evaluation | Monthly | Candidates submitted via standard form or identified by research |

Changes to this document are version-controlled and logged in the INCLUSION_STANDARD.md changelog.

---

*The exclusion list is the other half of the rating product. Any asset on this list can be cited by an analyst, an LP, or an AI agent as evidence that CometCloud applies its standard rigorously. The list is not a blacklist — it is a traceable audit trail of exactly where the line was drawn and why.*
