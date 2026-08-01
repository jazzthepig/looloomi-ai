# Universe Inclusion Decision Memo — HYPE (Hyperliquid)

**Asset:** Hyperliquid (HYPE)
**Native chain:** HyperBFT (Hyperliquid L1, non-EVM core + HyperEVM EVM-compatible extension)
**Decision target:** CometCloud Investable Universe — FoF core beta + CIS tilt sleeves
**Memo version:** v1 (2026-08-01, Seth draft)
**Decision verdict:** 🟡 **CONDITIONAL ELIGIBLE** — eligible after §3 management plans signed off; 30-day forward-paper required before any sleeve exposure
**Re-review cadence:** **Calendar-monthly** (1st of month, 09:00 HKT) + event-triggered (per §4.2)
**First scheduled re-review:** **2026-09-01** (T+30d)
**Decision authority required:** **Jazz** (fund head) for final INCLUDE / EXCLUDE ruling

> **How to read this doc.** §2 is the **template body** — every future universe-intake follows the same 7-criterion evaluation. §3 management plans are **asset-specific** to the partial shape. §4-§5 are the governance layer (re-review schedule + log) that applies across the universe, not just HYPE. Fill in for each new intake.

---

## 1. Executive verdict

| Bucket | Count | Criteria |
|---|---|---|
| ✅ PASS (clear) | 4 | #1 liquidity, #3 custody, #6 history, #7 integrity |
| 🟡 PARTIAL (managed) | 3 | #2 data (TVL fragmented), #4 regulatory (US geofence), #5 tokenomics (low float + vesting cliff) |
| ❌ HARD FAIL (gate) | 0 | — |

**Bottom line.** The earlier "HYPE blocked by custody (#3)" verdict from the 2025-Q1-style snapshot is **stale and wrong** as of 2026-08-01. BitGo (custody+staking, 2026 launch), Komainu (Nomura, 2025-12 launch), and Anchorage Digital Bank (HyperEVM-native) all custody HYPE — all three are on CometCloud's approved custodian list (§7). Fireblocks status: MPC infrastructure via HyperEVM (community integration request thread is informational; production integration works through HyperEVM). **#3 has flipped from ❌ → ✅.**

The 3 remaining partials are not gate failures — each has an explicit management plan (§3a/b/c) that constrains operational risk without requiring exclusion.

**Recommendation.** Conditional INCLUDE per §6 once Jazz signs off §3 plans. 30-day forward-paper at 3% weight cap before any sleeve allocation.

---

## 2. 7-criterion evaluation template

> **Template use.** Every row below is filled for HYPE. For a new intake, replace §2 with the asset under review but keep the same 7 rows + verdict columns.

| # | Criterion | Verdict | Evidence (2026-08-01) | Source / link | Re-check trigger | Owner |
|---|---|---|---|---|---|---|
| **1** | **Liquidity threshold** (30d avg quote_vol ≥$5M, ≥3 venues) | ✅ **PASS** | $386M trailing 30d volume; 61 active venues (Hyperliquid Perps + Spot, Binance perp mirror, OKX, Bybit, Gate.io, MEXC, KuCoin, Kraken, ...); typical spread ≤30bps on Hyperliquid Perps, ≤50bps on cross-venue | Hyperliquid stats / DefiLlama derivatives | Monthly; event-trigger if 30d vol drops ≥50% from peak | Seth |
| **2** | **Data completeness** (OHLCV history, TVL/fees, audited financials) | 🟡 **PARTIAL** | OHLCV: Hyperliquid native API (full history since perps launch 2023-08) + Binance perp mirror; TVL: **fragmented** across HLP, Spot, Perps, Bridge sub-protocols (DeFiLlama does not auto-aggregate); revenue/fees: HLP fees via DeFiLlama | `scripts/fetch_ohlcv_11yr_binance.py` `ALL_48` list + new `scripts/hype_tvl_aggregator.py` (TBD per §3a) | Monthly; event-trigger on any sub-protocol rebrand | Seth + Minimax |
| **3** | **Institutional custody** (Coinbase / BitGo / Fireblocks / Anchorage / Fidelity / Komainu / Zodia) | ✅ **PASS** *(was ❌ in stale 2025-Q1 snapshot)* | BitGo institutional custody+staking for HYPE — launched 2026; Komainu (Nomura) institutional custody+staking for HYPE — 2025-12-15; Anchorage Digital Bank custody for Hyperliquid native token HYPE via HyperEVM-native integration; FalconX custody+staking; Fireblocks MPC via HyperEVM (production); Hyperliquid Spot + Perps available through MPC wallet + qualified custodian split | BitGo PR; Komainu PR; Anchorage PR; Fireblocks HyperEVM docs | **Quarterly** (custody landscape shifts ~2-4×/yr); event-trigger on any custodian onboarding/offboarding | **Jazz** (sign-off on custodian selection per LP route) |
| **4** | **Regulatory status** (not under SEC/CFTC enforcement, not OFAC-sanctioned) | 🟡 **PARTIAL** | Non-US (HK / SG / EU / UK / BVI / Cayman): ✅ cleared; **US persons**: ❌ blocked via direct custody on Coinbase.US, Binance.US, Kraken US; Hyperliquid DEX access via US IPs restricted at the validator level (geofence consensus-side); no SEC enforcement action; Hyperliquid Foundation filed Cayman; HYPE not yet on Coinbase.US or any US-licensed venue | Hyperliquid Foundation public filings; US LP contract review | Quarterly; event-trigger on SEC/CFTC/SFC/HKMA action; SEC no-action letter | **Jazz** |
| **5** | **Token mechanics** (supply ratio, emission rate, vesting transparency — crypto only) | 🟡 **PARTIAL** | Circulating 22% of total (June 2026); team + insider + foundation 78% on rolling 4-year unlock (started 2024-11 mainnet); next major cliff ~T+90 days from memo (≈Nov 2026); emission schedule published; no rug-pull history | CoinGecko; Messari unlock schedule; Hyperliquid Foundation governance repo | Monthly; **event-trigger when days-to-next-cliff < 90** | Seth |
| **6** | **Trading history** (≥90d standard; 45d fast-track for institutionally-backed) | ✅ **PASS** | Hyperliquid Perps live since 2023-08 (>1,095 days trading); 609 days with trailing 30d vol ≥$5M (since ~2024-08); 100% survival through 2024-Q4 dump + 2025-Q1 chop + 2025-Q3 recovery + 2026-Q1 sell-off; HYPE token live since 2024-11 | Hyperliquid stats + internal 11yr panel `ohlcv_11yr.db` | Monthly; event-trigger if 90d <$5M | Seth |
| **7** | **Team / protocol integrity** (no unresolved exploit >$1M, no treasury misuse) | ✅ **PASS** | HyperBFT consensus = PoS variant with delegated validators, slashed-validator track record; no exploits >$1M (~$5M minor events all fully remediated); legal entity filed (Cayman foundation); BitGo custody = institutional key-management standard; team publicly known; HyperEVM audited by Spearbit + Trail of Bits (2025-08) | Hyperliquid Foundation; public audit reports; legal entity registry | Quarterly; event-trigger on any >$1M on-chain exploit | **Jazz** |

**Score: 4 ✅ + 3 🟡 + 0 ❌ → 🟡 CONDITIONAL ELIGIBLE.**

---

## 3. Management plans for the 3 partials

> **Each plan has a trigger / scope / owner / exit.** These run inside the sleeve — they do not require exclusion.

### 3a — TVL fragmented (#2)

| | |
|---|---|
| **Problem** | HYPE ecosystem has 4+ sub-protocols (Hyperliquid Perps, Spot, Bridge, HLP). DeFiLlama does not auto-aggregate; sleeve cannot use a single TVL scalar without disguising structure. |
| **Plan** | 1) Build `scripts/hype_tvl_aggregator.py` summing sub-protocols with `TVL_AGGREGATED` flag. 2) Sleeve uses `TVL_AGGREGATED` (transparent 4-tuple: perps TVL, spot TVL, bridge TVL, HLP NAV). 3) Quarterly recheck: drop manual aggregator if DeFiLlama auto-aggregates by then. |
| **Trigger to escalate** | any sub-protocol rebrand, merger, or new sub-protocol launch |
| **Exit** | DeFiLlama includes HYPE in main aggregate table; manual script becomes fallback only |
| **Owner** | Seth + Minimax (data plumbing) |

### 3b — US geofence (#4)

| | |
|---|---|
| **Problem** | HYPE cannot be custodied under a US-qualified custodian for US-resident LPs (Coinbase.US, Binance.US, Kraken US do not list HYPE; Fireblocks + BitGo KYC blocks US persons without explicit waiver). |
| **Plan** | 1) Segment LP contracts at intake — non-US LP fund gets HYPE sleeve exposure; US LP fund gets HYPE sleeve weight = 0. 2) Disclose in LP quarterly statements (US version: "HYPE exposure = 0 by regulatory carve-out"; non-US version: "HYPE exposure per sleeve rules"). 3) Quarterly regulatory landscape check. |
| **Trigger to escalate** | SEC/CFTC no-action letter, SFC clarification, HYPE listing on Coinbase.US, CFTC positions limits relaxation |
| **Exit** | HYPE listed on US-licensed qualified custodian + SEC clarity = US LP exposure opens |
| **Owner** | **Jazz** (LP-facing) |

### 3c — Low float + vesting cliff (#5)

| | |
|---|---|
| **Problem** | 22% float means 78% still unlocking over 4-year schedule. Cliff events cause empirical sell pressure. Vesting transparency is there but timing is the risk. |
| **Plan** | Time-to-next-cliff controls sleeve ceiling: (i) cliff > 90 days: baseline weight; (ii) cliff ≤ 90 days: cap at 50% of baseline; (iii) cliff ≤ 30 days: cap at 25% of baseline OR flat 0 (Jazz discretion). Drawdown check on insider wallets weekly. |
| **Trigger to escalate** | unexpected insider transfer ≥ 1% of supply in any 24h window (alert from Wallet Watcher) |
| **Exit** | float ≥ 50% (next milestone ~2026-Q4 onwards) = baseline cap restored without constraint |
| **Owner** | Seth (daily monitoring) |

---

## 4. Re-review schedule

### 4.1 Calendar-monthly (base cadence)

- **Cadence:** 1st of month, 09:00 HKT
- **Owner:** Seth drafts (≤2 hours); Jazz reviews and signs (≤30 min)
- **Scope:** §2 re-evaluated against latest data; §3 management plans reviewed; §4.2 trigger log scanned
- **Output:** dated entry in §5 re-review log; verdict per §4.3 ladder
- **Skip rule:** if no triggers fired AND no management-plan execution errors AND no policy changes, "REVIEW NORMAL NO CHANGE" entry is sufficient; defer full §2 audit to quarterly.

### 4.2 Event-triggered (out-of-cycle)

| Trigger | Detection source | Review window |
|---|---|---|
| **Custody landscape shift** | New custodian onboards or known custodian offboards HYPE | T+5d |
| **Regulatory shift** | SEC/CFTC/SFC/HKMA/Binance.US action on HYPE or perp-DEX peers | T+5d |
| **Vesting cliff proximity** | Time-to-next-cliff < 90 days | Pre-event 7d + post-event 7d |
| **Insider transfer shock** | ≥1% supply / 24h wallet move (Wallet Watcher) | T+1d |
| **Vol shock** | 30d trailing quote_vol drops ≥50% from peak | T+1d |
| **On-chain exploit** | >$1M loss on Hyperliquid core contracts | T+1d |
| **Macro shock** | >2σ move in BTC or total crypto market cap | Same-week |
| **Top-validator slashing** | Any of top-10 Hyperliquid validators slashed | T+1d |

### 4.3 Re-review verdict ladder

| Verdict | Trigger condition | Next decision |
|---|---|---|
| ⬆️ **UPGRADE** | All 3 partials cleared (e.g., float ≥50%, SEC clarity, DeFiLlama auto-aggregate) | Remove §3 management plans; full weight |
| ➡️ **CONFIRM** | Still conditional, no worsening | Stay conditional; management plans continue |
| ⬇️ **DOWNGRADE** | 2+ partials worsen OR 1 new partial appears | Watchlist only (eligible but not active sleeve) |
| 🔴 **DELIST** | 1+ criterion flips to ❌ HARD FAIL OR HYPE zero-volume 60 days straight | Remove from universe; freeze 90 days then re-evaluate from §1 |

### 4.4 Communication

- ⬆️ / ➡️ : internal note in §5 log + dashboard tag
- ⬇️ : internal note + LP-facing brief (US / non-US split)
- 🔴 : internal note + immediate LP communication (3-business-day window) + remove from anywhere HYPE is referenced in product surfaces

---

## 5. Re-review log (append-only)

> **Discipline.** Append-only. Use the same schema row each time. Each entry gets a unique sequential number per asset. Reverse-time entries allowed only with `[CORRECTION]` prefix and date suffix on the row, never by deletion.

| # | Date | Reviewer | Verdict | Trigger source | Net delta vs prior review |
|---|---|---|---|---|---|
| 1 | 2026-09-01 *(scheduled)* | TBD | TBD | Calendar-monthly (init.) | Initial baseline (§2 frozen at memo date) |
| … | … | … | … | … | … |

*(First entry will be filled on 2026-09-01. Each subsequent event-triggered review also gets a row.)*

---

## 6. Sign-off block

| | |
|---|---|
| **Drafter** | **Seth** @ 2026-08-01 |
| **Decision authority** | **Jazz** — required for INCLUDE / EXCLUDE final ruling |
| **Forward-paper commitment** | **30 days** from sign-off, weight cap = **3% of FoF core** (baseline; §3c ceilings may tighten) |
| **Lane discipline** | Seth owns this memo (`docs/`); Mac-side custodian selection owned by Jazz + Minimax (via `MINIMAX_SYNC.md` §CUSTODY §HYPE) |
| **Production deadline** | `<2026-09-15>` for first forward-paper run, `<2026-10-15>` for any sleeve exposure decision |

**Out of scope of this memo** (separate work, owned elsewhere):

- Mac-side write of `scripts/hype_tvl_aggregator.py` (§3a exit depends on this)
- `MINIMAX_SYNC.md` §CUSTODY §HYPE entry (Mac-side custodian vendor confirmations)
- `PROJECT_STATE.md` `[2026-08-01] HYPE inclusion memo v1` log entry
- `REFUTATION_LEDGER.md` does **not** apply — this is governance, not an empirical strategy claim
- `STRATEGY_PLAYBOOK.md` update — only after 30-day forward-paper produces a result

---

## 7. References

| | |
|---|---|
| Custody | [BitGo HYPE 2026 PR (PDF)](https://s21.q4cdn.com/773293151/files/doc_news/BitGo-Launches-Institutional-Staking-and-Expanded-Custody-Support-for-Hyperliquid-HYPE-2026.pdf); [Komainu HYPE 2025-12-15 PR](https://komainu.com/komainu-announces-institutional-grade-custody-and-staking-support-for-hyperliquid-hype/); [Anchorage Digital HYPE blog](https://www.anchorage.com/insights/anchorage-digital-bank-custody-hyperliquids-native-token-hype-institutional-grade-security-hyperevm); [Fireblocks HyperEVM discussion](https://community.fireblocks.com/t/integration-with-hyperliquid/806) |
| Data | [DeFiLlama fees API](https://api-docs.defillama.com/); `scripts/fetch_ohlcv_11yr_binance.py` (existing fetcher — HYPE line needs update at handover to Mac) |
| Docs | `docs/DATA_VENDOR_MATRIX.md` (vendor pricing); `docs/HIGH_DIM_ONTOLOGY.md` §5b (return hierarchy) |
| Memory | [[pillar-fm-tilt-doctrine]] (② layer = F+M only — relevant if HYPE enters ② tilt sleeve) |
| Governance | `MINIMAX_SYNC.md` §CUSTODY (cross-lane vault + custody ledger) |

---

## Appendix A — Template re-use

This doc's structure is the **canonical intake template** for the universe. To apply to a new asset (say `XXX`):

1. Copy §2 table → fill rows 1-7 with `XXX` evidence + verdict
2. Identify partials → for each, write §3-style management plan
3. Set first re-review date at T+30d from intake signature
4. File at `docs/UNIVERSE_DECISION_<TICKER>.md`
5. Add pointer to MEMORY.md and the universe-tracking index (todo: create `docs/UNIVERSE_INDEX.md` when intake volume justifies)

Future-proofing: when **N ≥ 5** intake memos exist, graduate to `docs/UNIVERSE_INTAKE_TEMPLATE.md` extraction and link from each memo.
