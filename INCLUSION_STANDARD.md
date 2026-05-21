# CometCloud AI — Investment Universe Inclusion Standard
**Version:** 2.0
**Effective date:** May 2026
**Status:** Nasigor 100-Class Institutional Standard — replaces v1.1
**Maintained by:** CometCloud AI Research

---

## Purpose

This document defines the criteria by which assets are admitted to the CometCloud AI Investable Universe. Admission is a prerequisite for CIS (CometCloud Intelligence Score) rating. Assets not in the universe are not rated, not signaled, and not eligible for fund allocation.

The standard exists to answer a single institutional question: **"What has been filtered out, and why?"** Institutional allocators should be more interested in the exclusion logic than the scores within the universe — because the curation gate is where the risk screening actually happens.

**Design principle:** This is an alpha-preserving filter, not a risk-elimination filter. The goal is to screen out structurally broken or fraudulent assets — not to exclude high-conviction emerging assets because they are new or have navigated and fully recovered from past incidents. A standard so strict it excludes Hyperliquid is a standard that has miscalibrated its purpose.

The inclusion standard is reviewed monthly. Changes are versioned and logged in the changelog at the bottom of this document.

---

## Hard Gates — All Must Pass

All nine criteria are evaluated independently. **Failure on any single criterion results in exclusion.** There is no compensating mechanism. The criteria are applied in order for efficiency — liquidity (Criterion 1) typically eliminates the most candidates with the least analytical effort.

---

## Criterion 1 — Liquidity Threshold

**Applies to:** All asset classes
**Gate type:** Hard pass/fail

### Thresholds

| Asset class | Metric | Minimum |
|-------------|--------|---------|
| Crypto assets (L1/L2/DeFi/Infra/RWA/Gaming/AI) | 30-day average daily traded volume (USD) | **$10,000,000** |
| Crypto assets | Tier-1 exchange listings (Binance, Coinbase, Kraken, OKX, Bybit) | ≥ 3 |
| Crypto assets | Bid-ask spread (spot, major pair) | < 0.5% |
| TradFi ETFs / equities | 30-day average daily traded volume (USD) | $50,000,000 |
| TradFi ETFs / equities | Exchange listing | NYSE or NASDAQ primary listing |

**Rationale:** Institutional portfolio construction requires the ability to enter and exit positions of size without material market impact. The raised threshold ($10M, up from $5M in v1.1) reflects the larger size and liquidity of the current crypto market post-2024 bull cycle.

**Data source:** CoinGecko Pro (crypto volume), Bloomberg (TradFi). 30-day rolling average recalculated weekly.

---

## Criterion 2 — Market Capitalization Floor

**Applies to:** All asset classes
**Gate type:** Hard pass/fail

### Thresholds

| Asset class | Metric | Minimum |
|-------------|--------|---------|
| Crypto assets | Fully diluted market cap (FDV) | **$500,000,000** |
| US equities | Market cap | $10,000,000,000 |
| US ETFs | AUM | $1,000,000,000 |

**Rationale:** Assets below the FDV floor lack sufficient market confidence and institutional infrastructure to support reliable scoring. This criterion complements liquidity — a token with $50M in daily volume but only $80M FDV is structurally fragile.

**Data source:** CoinGecko (FDV, market cap), Bloomberg (equities/ETFs).

---

## Criterion 3 — Rank Floor

**Applies to:** Crypto assets only
**Gate type:** Hard pass/fail

### Thresholds

| Metric | Minimum |
|--------|---------|
| CoinGecko market cap rank | Top **150** |

**Rationale:** The CG rank floor is a composite signal that captures liquidity, market cap, volume, and institutional attention simultaneously. Assets outside the top 150 by market cap have insufficient market maturity for institutional allocation. This criterion is applied weekly.

**Data source:** CoinGecko `market_cap_rank` field.

**Note:** Fast-track assets (Criterion 10) entering the top 100 by mcap are auto-flagged for accelerated inclusion review.

---

## Criterion 4 — Data Completeness

**Applies to:** All asset classes
**Gate type:** Hard pass/fail

### Thresholds

| Asset class | Requirement |
|-------------|-------------|
| Crypto assets | Minimum 90 days of complete OHLCV history on a tier-1 exchange. On-chain data available from at least one of: Dune Analytics, DeFiLlama, Glassnode, Nansen. |
| DeFi protocols | TVL data available via DeFiLlama API with <24h latency. Minimum 90 days of TVL history. |
| TradFi ETFs | Audited NAV history for minimum 2 full calendar years. Underlying index methodology published. |
| US equities | 3 years of audited financial statements. Quarterly earnings reporting. |

**Rationale:** The CIS scoring engine requires complete data across all 5 pillars. Assets that cannot be scored reliably produce noise, not signal. Incomplete data is treated as a disqualifying condition rather than a scoring penalty — a partial score from insufficient data is worse than no score at all from an exclusion standpoint.

**Data source:** DeFiLlama (TVL), CoinGecko Pro (OHLCV), Glassnode (on-chain), SEC EDGAR (TradFi).

---

## Criterion 5 — Institutional Custody

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

**Rationale:** An asset that cannot be held by an institutional custodian cannot be allocated to by pension funds, family offices, or regulated funds. Custody eligibility is a proxy for regulatory acceptance and infrastructure maturity.

**Data source:** Published asset coverage lists from each custodian above, reviewed monthly.

---

## Criterion 6 — Regulatory Status

**Applies to:** All asset classes
**Gate type:** Hard pass/fail

### Requirements

1. The asset must not be classified as an unregistered security by a regulatory body in CometCloud's primary jurisdictions (Hong Kong SFC, US SEC, EU MiCA).
2. No active enforcement action or charges naming the issuing entity or primary development team.
3. For crypto assets: the token's primary distribution mechanism must not have been through an unregistered public offering (ICO/IEO) that has subsequently been found unlawful.
4. No OFAC sanctions designation on the issuing entity or protocol treasury.

**Rationale:** Allocating to assets under active regulatory action exposes the fund and its LPs to legal and reputational risk. Regulatory status can change rapidly — the universe is reviewed monthly in part for this reason.

**Data source:** SFC Hong Kong regulatory announcements, SEC enforcement actions database, OFAC SDN list, EU MiCA registry.

---

## Criterion 7 — Token Mechanics (Crypto only)

**Applies to:** Crypto assets only (L1, L2, DeFi, Infrastructure, RWA, Memecoin, Gaming, AI)
**Gate type:** Hard pass/fail

### Thresholds

| Metric | Requirement |
|--------|-------------|
| Circulating supply / Total supply ratio | **≥ 0.30** |
| Vesting schedule | Full schedule publicly available and on-chain verifiable or via auditable contract |
| Emission rate (annualized) | < **20%** of current circulating supply per annum |
| Active emission exploits | Zero — any unresolved exploit that mints supply beyond the stated schedule disqualifies |
| Inflation event history | No undisclosed inflation event in the token's history |

**Rationale:** Token mechanics determine whether score-based positioning has any operational meaning. An asset that can inflate its supply by 50% in a quarter renders momentum and fundamental scoring irrelevant. The circulating/total supply ratio screens out assets where insiders hold the overwhelming majority of supply.

**Data source:** TokenUnlocks.data and Messari for vesting schedules; Etherscan/Solscan for on-chain supply audits.

---

## Criterion 8 — Trading History

**Applies to:** All asset classes
**Gate type:** Hard pass/fail

### Thresholds

**Standard track:** Minimum **180 days** of continuous trading history on at least one tier-1 exchange (Binance, Coinbase, Kraken, OKX, Bybit for crypto; NYSE/NASDAQ for TradFi).

**Rationale (v2.0 recalibration):** The 180-day minimum is calibrated for institutional fund requirements. It covers two full calendar quarters of data — sufficient for meaningful momentum scoring (M pillar), initial on-chain risk profiling (O pillar), and regime-awareness across multiple market cycles. This is the Nasdaq 100's 1-year listing requirement applied to crypto.

**Data source:** Exchange listing date from CoinGecko (crypto), Bloomberg IPO date (TradFi).

---

## Criterion 9 — Protocol Integrity

**Applies to:** All asset classes
**Gate type:** Hard pass/fail; judgment required

### Disqualifying conditions

1. **Documented rug-pull history:** Any project where the founding team or controlling parties withdrew liquidity, drained treasury, or abandoned the project without warning and without resolution.

2. **Anonymous team with no institutional accountability:** For a team to qualify as anonymous-but-acceptable, all of the following must be true: (a) the protocol has undergone a complete code audit by a reputable firm, (b) a legal entity with known registration exists, and (c) the protocol has operated without incident for at least **2 years**.

3. **Unresolved material exploit:** Any exploit that resulted in loss of user funds greater than $1,000,000 where (a) the root cause has not been published, (b) affected users have not been made whole, or (c) the vulnerability class remains unpatched.

4. **Documented treasury misuse:** Any documented case where protocol treasury funds were used for personal enrichment of team members without governance approval.

5. **Active leadership in personal regulatory proceedings:** Where a founding or controlling team member faces active legal proceedings for financial crimes.

### Remediation pathway

A protocol that previously triggered a disqualifying condition may re-qualify if ALL of the following are demonstrated:
- Full public post-mortem published within 30 days of the incident
- Affected users made whole (≥80% of lost funds recovered or compensated)
- Independent security audit completed and published after the incident
- Clean operating record for **12+ consecutive months** since the incident
- No repeat of the same vulnerability class

**Data source:** Rekt.news, DeFiLlama hacks, SEC enforcement, Messari governance research, on-chain wallet analysis.

---

## Criterion 10 — Fast-Track Pathway (New in v2.0)

**Applies to:** All asset classes
**Gate type:** Fast-track (reduces Criterion 8 requirement)

### Eligibility

An asset qualifies for a 90-day minimum trading history (instead of 180) if ALL of the following are true:

1. FDV ≥ **$1,000,000,000** at time of review
2. Primary listing on at least one tier-1 exchange (Binance, Coinbase, Kraken, OKX, or Bybit)
3. Institutional custody support from at least one Criterion 5 custodian at launch
4. Full tokenomics published with on-chain verifiable vesting schedule pre-launch
5. Minimum $10M in verifiable VC or institutional funding

**Rationale:** A $1B+ FDV asset that launches with institutional custody and transparent tokenomics represents a fundamentally different risk profile than a micro-cap token seeking to accumulate a track record. The fast-track prevents the 180-day rule from excluding high-conviction assets on a technicality when all substantive quality indicators are present.

**Scoring confidence:** Fast-track assets receive a reduced confidence score (0.75× multiplier) reflected in the LAS, recovering to 1.0× at 180 days of history.

---

## Monthly Review Triggers

The universe is reviewed monthly. Between review cycles, emergency exclusions can be triggered by:

- An enforcement action naming the issuing team
- A material exploit (>$1M user funds at risk)
- A liquidity event that drops a previously qualifying asset below Criterion 1 threshold for 7 consecutive days
- Asset entering the top 100 by CoinGecko market cap (auto-flagged for inclusion review)

Emergency exclusions are published within 24 hours of the triggering event.

---

## Grade Distribution

After applying this inclusion standard, the surviving universe is expected to show a **B-centered grade distribution** under CIS v4.1 scoring. This is correct and expected behavior. The inclusion standard already screens out the worst performers — the bottom of the grade curve among excluded assets is much worse than F. What remains after curation is a set of genuinely investable assets for which the scoring engine can produce meaningful differentiation.

A universe where every asset is A+ would indicate the inclusion standard is too permissive. A B-centered distribution after curation is the calibration signature of a working rating system over a quality universe.

---

## Changelog

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | April 2026 | Initial draft |
| 1.1 | April 2026 | Criterion 6: 180-day → 90-day + 45-day fast-track. Criterion 7: remediation pathway added. |
| 2.0 | May 2026 | **Full recalibration** — 10 criteria (was 7). Raised liquidity to $10M (was $5M). Added market cap floor ($500M FDV), rank floor (CG top 150), tightened token mechanics (circ/total ≥0.30, inflation <20%/yr), restored 180-day standard (no 45-day fast-track; replaced with 90-day fast-track at $1B+ FDV + custody). Compliance with Nasdaq 100-class institutional standard. |

---

*For questions about specific asset exclusions, see the Exclusion List (CIS router, `/api/v1/agent/cis-exclusions`). For the scoring methodology applied to included assets, see CIS_METHODOLOGY.md.*