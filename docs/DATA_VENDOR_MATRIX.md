# Data Vendor Matrix — Funding / On-Chain / Fundamentals

**Last updated:** 2026-07-29
**Owner:** Seth (research lane)
**Scope:** Vendor comparison + bootstrap path for the 3 known data gaps: funding rate history, on-chain active addresses, protocol revenue/fees.
**Cadence:** Re-validate pricing every 6 months; vendor landscape shifts faster than our needs.

---

## Honest framing first

| Gap | Real gap shape | Why not just buy everything |
|---|---|---|
| **Funding rate 2021-2023 + pre-2021** | 2021+ partial via free archives; pre-2021 structurally thin (many perps didn't exist) | Pre-2021 is a **structural** gap, not an API problem. No vendor can sell you data that never existed. |
| **Pillar_O 11yr (active addresses)** | Most altcoins simply don't have address history pre-2024 | Per [[pillar-fm-tilt-doctrine]], pillar_O doesn't need 11yr backfill — eligibility filter covers it. Don't buy on-chain vendor until doctrine flips. |
| **Pillar_F 2018-2019 revenue gap** | DeFiLlama fees coverage starts ~2020 for most protocols | ②-F+M sleeve starts **2020-01-01** (DeFiLlama full coverage), not 2017. Acceptable. |

**Conclusion:** ~70% of perceived data gaps are not gaps. 30% are 2018-2019 corner cases. **Phase-0 bootstrap is $0.** Only Tardis.dev ($50-150/mo) is genuinely worth paying for at our current AUM scale.

---

## Vendor Matrix

### Gap #1 — Funding rate history

| Tier | Vendor | Coverage | Pricing | Quality |
|---|---|---|---|---|
| **FREE** | [Coinalyze](https://coinalyze.com) | 2021+ major pairs (Binance / Bybit / OKX / dYdX / BitMEX) | $0 | 🟢 |
| **FREE** | Exchange APIs ([Binance `/fapi/v1/fundingRate`](https://developers.binance.com/), [OKX](https://www.okx.com/docs-v5/en/), [Bybit](https://bybit-exchange.github.io/docs/v5/market/history-fund-rate)) | Per exchange, since perp launch | $0 + pagination engineering | 🟢 |
| **FREE** | Dune community dashboards | Per template | $0 (query credits) | 🟡 |
| **Cheap** | **[Tardis.dev](https://tardis.dev/pricing)** | 2019+, tick-level, 50+ exchanges | **from $50/mo** | 🟢 Industry standard |
| **Paid** | [CoinGlass Pro](https://www.coinglass.com/pricing) | 8+ exchanges full history | **$699/mo** / $8,388/yr | 🟢 OHLC + raw |
| **Paid** | [Laevitas](https://www.laevitas.ch) | 15+ exchanges + options flow | Custom (~$200-500/mo) | 🟢 Derivatives specialist |
| **Enterprise** | Kaiko / Amberdata | All exchanges + L2/L3 order book | $5k+/mo | 🟢 Overkill at our scale |

### Gap #2 — On-chain active addresses (doctrine-deprioritized, but path is ready)

| Tier | Vendor | Coverage | Pricing | Quality |
|---|---|---|---|---|
| **FREE** | [Blockchain.com](https://www.blockchain.com/explorer/api) | BTC full history | $0 | 🟢 |
| **FREE** | [Etherscan API](https://docs.etherscan.io/resources/rate-limits) | ETH full history | 3 calls/sec · 100k/day · 1k records/req (post-Jul 2026) | 🟢 Pagination cost |
| **FREE** | [CryptoDataDownload](https://www.cryptodatadownload.com/) | BTC 2009+ / ETH 2015+ on-chain CSV | $0, no signup | 🟢 |
| **FREE** | [DIA Free Crypto API](https://www.diadata.org/free-crypto-api/) | Prices + partial on-chain | $0, no signup | 🟡 |
| **Paid** | **[Glassnode Studio](https://studio.glassnode.com/pricing)** | 50+ chains full history | Free / **$49/mo (Advanced)** / **$999/mo (Professional, annual)** | 🟢 Industry standard |
| **Paid** | **[Artemis](https://about.artemis.ai/pricing)** | Cross-chain + stablecoins + RWA | Lite Free / **$300/mo monthly** / **$250/mo annual ($3k/yr)** / Enterprise custom | 🟢 Strong on chain revenue |
| **Enterprise** | Nansen / Allium / Coin Metrics | Smart-money / institutional | $5k+/mo | 🟢 Not needed unless smart-money alpha |

### Gap #3 — Protocol revenue / fees history (Pillar_F evidence)

| Tier | Vendor | Coverage | Pricing | Quality |
|---|---|---|---|---|
| **FREE** | **[DeFiLlama Fees API](https://api-docs.defillama.com/)** | 100s protocols × 10+ chains | $0 | 🟢 **Strongest free source we have** |
| **FREE** | [CryptoFees.info](https://cryptofees.info) | Top chains aggregated | $0 | 🟢 |
| **Paid** | [Token Terminal](https://tokenterminal.com/pricing) | Protocol P&L + L2 / restaking breakdown | Enterprise custom ($20-50k/yr) | 🟢 Industry standard |
| **Paid** | [Messari Pro](https://messari.io/) | Standardized fundamentals + quarterly reports + API | $10-30k/yr institutional | 🟢 Governance + historical financials |
| **Enterprise** | Coin Metrics | Institution full suite | $5k+/mo | 🟢 Overkill |

---

## Bootstrap Path (4 stages)

### Stage 0 — NOW (pre-AUM, validate ②-F+M hypothesis)
**Monthly cost: $0**

| Gap | Source |
|---|---|
| Pillar_F (TVL) | DeFiLlama `/historicalChainTvl` |
| Pillar_F (revenue most) | DeFiLlama Fees API |
| Pillar_F (2018-2019 gap) | **Accepted gap. Sleeve starts 2020-01-01.** |
| Pillar_M | Our 11yr OHLCV panel (`/tmp/cometcloud_data/ohlcv_11yr.db`) |
| Funding rate verification | Coinalyze free + exchange APIs |

**What it unlocks:** ②-F+M sleeve empirical work, starting 2020-01-01. ~7.5 years of data — well past the ≥5 cycles gate.

### Stage 1 — Strategy 1+2 validation + R77 re-verification
**Monthly cost: <$200**

Add **[Tardis.dev](https://tardis.dev/pricing) at $50-150/mo** — gets 2019+ funding rate full archive. R77 frozen cell can be re-verified on post-2019 window instead of post-2023.

Add **[Glassnode Advanced](https://studio.glassnode.com/pricing) at $49/mo** (optional, hedge) — only if pillar_O doctrine flips or we want to spot-check on-chain.

**What it unlocks:** R77 wider-window verification + ②-F+M on post-2020 panel + on-chain pathway ready.

### Stage 2 — AUM $50M+ go-live
**Monthly cost: $300-800/mo**

Add **[Artemis Pro](https://about.artemis.ai/pricing) at $250/mo (annual)** — institutional-grade on-chain + stablecoins + RWA. Survives LP IC Q&A.

Add **[CoinGlass Pro](https://www.coinglass.com/pricing) at $699/mo** — only for verified-essential funding/derivatives metrics.

**What it unlocks:** Pre-LP due diligence data backbone + R77/R62/R76 full-spectrum verification + cross-derivatives audit trail.

### Stage 3 — $200M+ AUM + LP-mandated disclosures
**Monthly cost: $2-5k/mo**

Add **[Token Terminal Enterprise](https://tokenterminal.com/pricing)** — only when LP IC requires protocol-level P&L history + L2/restaking breakdown.

Add **[Messari Pro](https://messari.io/)** — quarterly reports + governance + standardized financials, LP documentation default.

**Note:** This stage is LP-driven, not research-driven. **Don't buy until LP asks.**

---

## Decision principles (when in doubt)

1. **Don't buy on-chain vendors unless pillar_O doctrine flips.** Eligibility filter already covers the structural risk.
2. **Don't buy Token Terminal / Messari until LP IC demands protocol-level P&L.** Our empirical work uses DeFiLlama + OHLCV — sufficient for internal validation.
3. **Tardis.dev is the only currently-justified paid vendor.** $50-150/mo buys 5+ extra years of funding history for R77 verification. Cheapest cost-per-evidence-year of any vendor.
4. **All vendor pricing above is web-search-sourced, ~Jan-Jul 2026.** Re-validate before any buy order; vendor landscape shifts 10-20% annually.
5. **CoinGlass Pro is Stage-2+ only.** At $699/mo it's the single most expensive "nice-to-have" — only buy when funding rate is on the critical path for a verifiable edge.

---

## Sources

- [CoinGlass Pricing](https://www.coinglass.com/pricing)
- [Tardis.dev Pricing](https://tardis.dev/pricing)
- [Artemis Pricing](https://about.artemis.ai/pricing)
- [Glassnode Studio Pricing](https://studio.glassnode.com/pricing)
- [Token Terminal Pricing](https://tokenterminal.com/pricing)
- [Messari Pro](https://messari.io/)
- [Laevitas](https://www.laevitas.ch/)
- [Etherscan API Rate Limits](https://docs.etherscan.io/resources/rate-limits)
- [DeFiLlama Fees API Docs](https://api-docs.defillama.com/)
- [CryptoDataDownload](https://www.cryptodatadownload.com/)
- [DIA Free Crypto API](https://www.diadata.org/free-crypto-api/)
- [Coinalyze](https://coinalyze.com)
- [Blockchain.com Explorer API](https://www.blockchain.com/explorer/api)
- [CryptoFees.info](https://cryptofees.info)
