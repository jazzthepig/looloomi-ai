# CometCloud AI — Investment Universe Inclusion Standard
**Version:** 1.1
**Effective date:** April 2026
**Status:** Calibrated — v1.1 loosens Criterion 6 and Criterion 7 per founder review
**Maintained by:** CometCloud AI Research
**Anchors:** Each criterion is directly linkable via `cometcloud.ai/methodology#criterion-N`

---

## Purpose

This document defines the complete criteria by which assets are admitted to the CometCloud AI Investable Universe. Admission is a prerequisite for CIS (CometCloud Intelligence Score) rating. Assets not in the universe are not rated, not signaled, and not eligible for fund allocation.

The standard exists to answer a single institutional question: **"What has been filtered out, and why?"** Institutional allocators should be more interested in the exclusion logic than the scores within the universe — because the curation gate is where the risk screening actually happens.

**Design principle:** This is an alpha-preserving filter, not a risk-elimination filter. The goal is to screen out structurally broken or fraudulent assets — not to exclude high-conviction emerging assets because they are new or have navigated and fully recovered from past incidents. A standard so strict it excludes Hyperliquid is a standard that has miscalibrated its purpose.

The inclusion standard is reviewed monthly. Changes are versioned and logged in the changelog at the bottom of this document. Assets can be added or removed as their circumstances change. The exclusion list reflects the current state of rejections, with reasons.

---

## Criterion 1 — Liquidity Threshold {#criterion-1}

**Applies to:** All asset classes
**Gate type:** Hard pass/fail

### Thresholds

| Asset class | Metric | Minimum |
|-------------|--------|---------|
| Crypto assets (L1/L2/DeFi/etc.) | 30-day average daily traded volume (USD) | $5,000,000 |
| Crypto assets | Exchange count (tier-1 or tier-2 exchanges) | ≥ 3 |
| Crypto assets | Bid-ask spread (spot, major pair) | < 1.50% |
| TradFi ETFs / equities | 30-day average daily traded volume (USD) | $50,000,000 |
| TradFi ETFs / equities | Exchange listing | NYSE or NASDAQ primary listing |

**Rationale:** Institutional portfolio construction requires the ability to enter and exit positions of size without material market impact. Assets below the liquidity threshold may score attractively on other pillars but cannot be allocated to safely. This criterion eliminates speculative micro-caps, illiquid DeFi tokens, and assets experiencing terminal volume decline regardless of their historical significance.

**Data source:** CoinGecko Pro (crypto), Bloomberg (TradFi). 30-day rolling average recalculated weekly.

**Example rejection:** POLYX (Polymesh) — 30-day average daily volume ~$280,000 against the $5M minimum. Excluded on Criterion 1 alone.

---

## Criterion 2 — Data Completeness {#criterion-2}

**Applies to:** All asset classes
**Gate type:** Hard pass/fail

### Thresholds

| Asset class | Requirement |
|-------------|-------------|
| Crypto assets | On-chain data available from at least one of: Dune Analytics, DeFiLlama, Glassnode, Nansen. Minimum 90 days of complete OHLCV history on a tier-1 exchange. |
| DeFi protocols | TVL data available via DeFiLlama API with <24h latency. Minimum 90 days of TVL history. |
| TradFi ETFs | Audited NAV history for minimum 2 full calendar years. Underlying index methodology published. |
| US equities | 3 years of audited financial statements. Quarterly earnings reporting. |

**Rationale:** The CIS scoring engine requires complete data across all 5 pillars. Assets that cannot be scored reliably produce noise, not signal. Incomplete data is treated as a disqualifying condition rather than a scoring penalty — a partial score from insufficient data is worse than no score at all from an exclusion standpoint.

**Data source:** DeFiLlama (TVL), CoinGecko Pro (OHLCV), Glassnode (on-chain), SEC EDGAR (TradFi).

---

## Criterion 3 — Institutional Custody Eligibility {#criterion-3}

**Applies to:** All asset classes
**Gate type:** Hard pass/fail

### Requirement

The asset must be supported in custody by at least **one** of the following institutional-grade custodians:

- Coinbase Prime / Coinbase Custody
- BitGo Trust
- Fireblocks (institutional network)
- Anchorage Digital Bank
- Fidelity Digital Assets
- Komainu (for Asia-Pacific allocators)
- Standard Chartered Zodia Custody

For TradFi assets, DTCC eligibility is sufficient.

**Rationale:** An asset that cannot be held by an institutional custodian cannot be allocated to by pension funds, family offices, or regulated funds. Custody eligibility is a proxy for regulatory acceptance and infrastructure maturity. Assets that appear on all major on-chain analytics platforms but cannot be held in institutional custody are not investable by CometCloud's target clients.

**Data source:** Published asset coverage lists from each custodian above, reviewed monthly.

**Example rejection:** VIRTUAL (Virtuals Protocol) — as of April 2026, not supported by any of the listed institutional custodians. Excluded on Criterion 3.

---

## Criterion 4 — Regulatory Status {#criterion-4}

**Applies to:** All asset classes
**Gate type:** Hard pass/fail

### Requirements

1. The asset must not be classified as an unregistered security by a regulatory body in CometCloud's primary jurisdictions (Hong Kong SFC, US SEC, EU MiCA).
2. No active enforcement action or charges naming the issuing entity or primary development team.
3. For crypto assets: the token's primary distribution mechanism must not have been through an unregistered public offering (ICO/IEO) that has subsequently been found unlawful.
4. No OFAC sanctions designation on the issuing entity or protocol treasury.

**Rationale:** Allocating to assets under active regulatory action exposes the fund and its LPs to legal and reputational risk. This criterion is the most dynamic of the seven — regulatory status can change rapidly, and the universe is reviewed monthly in part for this reason.

**Data source:** SFC Hong Kong regulatory announcements, SEC enforcement actions database, OFAC SDN list, EU MiCA registry.

**Example rejection:** BCH (Bitcoin Cash) — primary contributor Roger Ver subject to federal tax evasion and fraud charges (2024 DOJ indictment). While the protocol itself is not charged, the association and potential exchange delisting risk constitute an active regulatory concern. Excluded on Criterion 4.

---

## Criterion 5 — Token Mechanics (Crypto only) {#criterion-5}

**Applies to:** Crypto assets only (L1, L2, DeFi, Infrastructure, RWA, Memecoin, Gaming, AI)
**Gate type:** Hard pass/fail

### Thresholds

| Metric | Minimum / Requirement |
|--------|----------------------|
| Circulating supply / Total supply ratio | ≥ 0.30 |
| Vesting schedule publication | Full vesting schedule publicly available and verifiable on-chain or via auditable contract |
| Emission rate (annualized) | < 25% of current circulating supply per annum |
| Active emission exploits | Zero — any unresolved exploit that mints supply beyond the stated schedule disqualifies |
| Inflation event history | No undisclosed inflation event in the token's history. Any historical inflation event must have full public disclosure and documented remediation. |

**Rationale:** Token mechanics determine whether score-based positioning has any operational meaning. An asset that can inflate its supply by 50% in a quarter renders momentum and fundamental scoring irrelevant. Vesting transparency is required so that institutional LPs can model dilution. The circulating/total supply ratio screens out assets where insiders hold the overwhelming majority of supply — a concentration risk that TradFi equivalent disclosure requirements would surface.

**Data source:** Token unlocks data from TokenUnlocks.app and Messari; on-chain supply audits via Etherscan/Solscan.

**Example rejection:** ICP (Internet Computer) — experienced >90% supply inflation in the first 8 months post-launch (May–December 2021) through neuron reward emissions that were not clearly disclosed in the initial tokenomics documentation. Historical undisclosed inflation event. Excluded on Criterion 5.

---

## Criterion 6 — Trading History {#criterion-6}

**Applies to:** All asset classes
**Gate type:** Soft pass/fail with fast-track pathway

### Thresholds

**Standard track:** Minimum **90 days** of continuous trading history on at least one tier-1 exchange (Binance, Coinbase, Kraken, OKX, Bybit for crypto; NYSE/NASDAQ for TradFi).

**Fast-track eligibility (qualifies at 45+ days):** Assets may qualify earlier if ALL of the following are true:
- Institutional custody supported by at least one listed custodian from Criterion 3 at launch
- Full tokenomics published with on-chain verifiable vesting schedule pre-launch
- Minimum $10M in audited VC or institutional funding (verifiable on-chain or via reputable disclosure)
- No supply anomalies in the first 45 days of trading

**Rationale (v1.1 recalibration):** The prior 180-day minimum was calibrated for conservative institutional fund requirements. CometCloud's universe includes both the institutional-grade assets those allocators need AND the high-conviction emerging assets that generate alpha. A 90-day window covers one full calendar quarter of data — sufficient for meaningful momentum scoring (M pillar) and initial on-chain risk profiling (O pillar). Assets with strong pre-launch institutional backing and transparent tokenomics from day one carry lower data uncertainty than the 180-day rule implied. Requiring 180 days would have excluded Hyperliquid — one of the highest-conviction emerging L1/DeFi hybrid protocols of 2024-2025 — on a technicality rather than a substantive quality concern.

**Data source:** Exchange listing date from CoinGecko (crypto), Bloomberg IPO date (TradFi). VC funding verification via Messari, Crunchbase, on-chain disclosure.

**Scoring confidence note:** Assets between 45–90 days receive a reduced confidence score (0.6× multiplier) reflected in the LAS (Liquidity-Adjusted Score). This is not an exclusion — it is a transparent representation of the data maturity limitation. The confidence score recovers to 1.0× at 180 days of history.

---

## Criterion 7 — Team and Protocol Integrity {#criterion-7}

**Applies to:** All asset classes
**Gate type:** Hard pass/fail; judgment required

### Disqualifying conditions

1. **Documented rug-pull history:** Any project where the founding team or controlling parties withdrew liquidity, drained treasury, or abandoned the project without warning and without resolution.

2. **Anonymous team with no institutional accountability:** For a team to qualify as anonymous-but-acceptable, all of the following must be true: (a) the protocol has undergone a complete code audit by a reputable firm, (b) a legal entity with known registration exists, and (c) the protocol has operated without incident for at least 2 years. The bar is high — anonymous teams without institutional accountability are disqualified.

3. **Unresolved material exploit:** Any exploit that resulted in loss of user funds greater than $1,000,000 where (a) the root cause has not been published, (b) affected users have not been made whole, or (c) the vulnerability class remains unpatched.

4. **Documented treasury misuse:** Any documented case where protocol treasury funds were used for personal enrichment of team members without governance approval, including undisclosed compensation, unauthorized token sales from team wallets, or personal loan collateralization against protocol treasury without community consent.

5. **Active leadership in personal regulatory proceedings:** Where a founding or controlling team member faces active legal proceedings for financial crimes (not unrelated personal matters), the asset is subject to heightened review and may be excluded.

**Remediation pathway (v1.1 addition):** A protocol that previously triggered a disqualifying condition under this criterion may re-qualify if ALL of the following are demonstrated:
- Full public post-mortem published within 30 days of the incident
- Affected users made whole (≥80% of lost funds recovered or compensated)
- Independent security audit completed and published after the incident
- Clean operating record for **12+ consecutive months** since the incident
- No repeat of the same vulnerability class

This pathway allows protocols that have genuinely fixed their problems and demonstrated sustained recovery to re-enter the universe. It prevents the criterion from becoming a permanent blacklist that ignores rehabilitation evidence. Assets on the remediation pathway carry a "remediated" tag in the leaderboard for transparency.

**Rationale (v1.1):** Institutional LPs require a defensible answer to "why did you allocate here?" A team integrity failure at the time of allocation is indefensible. A well-documented and fully remediated historical incident, with clean operation since, is not. The original v1.0 version was too binary — it treated a 2021 exploit the same as an ongoing or unresolved one. The recalibrated criterion targets structurally broken or actively fraudulent assets, not assets that failed, learned, and rebuilt.

**Data source:** Public incident databases (Rekt.news, DeFiLlama hacks), SEC enforcement, Messari governance research, CryptoLeaks, on-chain wallet analysis.

**Example rejections:**
- AXS (Axie Infinity) — Ronin bridge hack March 2022, $625M in user funds drained. Root cause published and network relaunched, but scale and security failure are disqualifying. The exploit represents the largest single DeFi security failure in history. Excluded on Criterion 7.
- SUSHI (SushiSwap) — multiple documented treasury incidents: anonymous core developer "Chef Nomi" exit in September 2020 (later partially returned), subsequent leadership disputes, allegations of treasury fund misuse in 2023–2024. Excluded on Criterion 7.
- CRV (Curve Finance) — founder Michael Egorov's personal positions (totaling ~$168M in loans collateralized against CRV in mid-2023) created systemic liquidation risk to the protocol's largest liquidity pools. While not a direct treasury violation, the founder's personal use of the asset as collateral at scale created a conflict of interest that endangered the broader DeFi ecosystem. Excluded on Criterion 7.
- RUNE (Thorchain) — two material exploits in 2021: June 2021 ($5M) and July 2021 ($8M). While both were disclosed and partially compensated, the July 2021 exploit occurred after the June exploit had not fully been remediated, indicating inadequate security process. Excluded on Criterion 7.

---

## How criteria are applied

All 7 criteria are evaluated independently. **Failure on any single criterion results in exclusion.** There is no compensating mechanism — an asset that scores A+ on all other criteria but fails Criterion 1 (liquidity) is excluded.

The criteria are applied in order for efficiency: Criterion 1 (liquidity) typically eliminates the most candidates with the least analytical effort. Criteria 5 and 7 require the most judgment and are reviewed last.

The universe review cycle is monthly. Between review cycles, emergency exclusions can be triggered by:
- An enforcement action naming the issuing team
- A material exploit (>$1M user funds at risk)
- A liquidity event that drops a previously qualifying asset below threshold for 7 consecutive days

Emergency exclusions are published within 24 hours of the triggering event.

---

## Grade distribution note

After applying this inclusion standard, the surviving universe is expected to show a **B-centered grade distribution** under CIS v4.1 scoring. This is correct and expected behavior. The inclusion standard already screens out the worst performers — the bottom of the grade curve among excluded assets is much worse than F. What remains after curation is a set of genuinely investable assets for which the scoring engine can produce meaningful differentiation.

A universe where every asset is A+ would indicate the inclusion standard is too permissive. A universe where every asset is F would indicate the scoring engine is broken. A B-centered distribution after curation is the calibration signature of a working rating system over a quality universe.

---

## Changelog

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | April 2026 | Initial draft |
| 1.1 | April 2026 | Criterion 6: 180-day minimum → 90-day standard + 45-day fast-track. Criterion 7: added remediation pathway for protocols with documented recovery. Design principle added: alpha-preserving filter, not risk-elimination filter. |

---

*For questions about specific asset exclusions, see the Exclusion List. For the scoring methodology applied to included assets, see CIS_METHODOLOGY.md.*
