```
COMETCLOUD HEALTH CHECK — 2026-04-07 11:07 UTC
══════════════════════════════════════════════════

MACRO PULSE    ✅ LIVE    — BTC $68,228 | FNG 11 (Extreme Fear) | Dom 56.5% | MCap $2,417B
CIS UNIVERSE   ⚠️ LIVE T2 — 70 assets scored | T2_MARKET (Railway fallback) | Regime: Risk-Off
SIGNAL FEED    ✅ ACTIVE  — 22 signals | No compliance violations
TOP ASSETS     ✅ OK      — #1 BTC B/61.4 | #2 USO B/58.2 | #3 ETH B/57.4 | #4 BNB C+/53.7 | #5 NVDA C+/52.7

OVERALL: 🟡 DEGRADED — Mac Mini not pushing T1 scores

ACTION NEEDED:
- CIS running on T2 (Railway fallback) — Mac Mini local engine is NOT pushing scores to Redis
  → Minimax: verify cis_scheduler.py + cis_push.py are running, check Redis connectivity
- Macro regime = "Risk-Off" but shows as "UNKNOWN" via macro_pulse endpoint
  → Backend returns regime from Redis (Mac Mini source) — stale/missing because Mac Mini offline
- FNG at 11 (Extreme Fear) — market under significant stress, monitor for cascade signals
- 7d/30d momentum data showing 0% for most crypto assets — likely missing historical price cache
  → Check CoinGecko API key in Railway env vars (COINGECKO_API_KEY)
- TVL data missing for all assets (tvl: 0) — DeFiLlama TVL not wired into CIS scoring on Railway
  → F pillar scoring degraded without TVL component
```

## Detailed Notes

### Macro Pulse
- BTC: $68,228 (-2.2% 24h)
- Fear & Greed: 11 — Extreme Fear (historic low territory)
- BTC Dominance: 56.5%
- Total Crypto MCap: $2,416.9B
- DeFi TVL: $92.6B (stable, -1.3% 24h)
- Regime returned as "UNKNOWN" from macro_pulse but "Risk-Off" from CIS universe

### CIS Universe
- 70 assets scored (meets ≥50 threshold)
- Data tier: T2_MARKET (Railway CoinGecko-based fallback)
- All 70 assets have CIS scores > 0
- Regime: Risk-Off
- Grade distribution skewed low — top asset (BTC) at 61.4 (B grade)
- S pillar universally depressed due to FNG 11

### Signal Feed
- 22 signals generated from 4 sources: CoinGecko, DeFiLlama, Alternative.me
- Signal types: RISK (5), MOMENTUM (6), WHALE (2), FLOW (8), defi_tvl (1)
- Notable: BETA -64%, VIB -63%, WTC -57% (severe drawdowns)
- Notable: BRISE +113%, CREAM +65% (extreme pumps)
- Compliance: ✅ No BUY/SELL language detected — uses vector_direction + pillar impact format

### Top 5 Assets
| Rank | Symbol | Grade | CIS | Signal | Price | 24h |
|------|--------|-------|-----|--------|-------|-----|
| 1 | BTC | B | 61.4 | NEUTRAL | $68,186 | -2.2% |
| 2 | USO | B | 58.2 | NEUTRAL | $138.94 | +1.0% |
| 3 | ETH | B | 57.4 | NEUTRAL | $2,087 | -2.9% |
| 4 | BNB | C+ | 53.7 | NEUTRAL | $597.67 | -1.4% |
| 5 | NVDA | C+ | 52.7 | NEUTRAL | $177.64 | +0.3% |

### Persistent Issues (from previous checks)
- Commit `682fdbe` still pending push (blocked on Jazz)
- Supabase env vars not in Railway
- COINGECKO_API_KEY status unknown — scoring works but momentum data incomplete
- Mac Mini T1 engine offline — no T1 scores since last check
