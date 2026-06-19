```
COMETCLOUD HEALTH CHECK — 2026-04-08T00:00Z (scheduled)
══════════════════════════════════════════════════════════

MACRO PULSE    ✅ LIVE    — BTC $71,397 | FNG 11 (Extreme Fear) | Dom 56.8% | MCap $2,507B
CIS UNIVERSE   ⚠️ LIVE T2 — 70 assets scored | T2_MARKET (Railway fallback) | Risk-Off regime
SIGNAL FEED    ✅ ACTIVE  — 19 signals | compliance-safe language confirmed
TOP ASSETS     ✅ OK      — #1 BTC B/60.6 | #2 USO B/58.5 | #3 ETH B/56.4 | #4 NVDA C+/52.6 | #5 BNB C+/52.4

OVERALL: 🟡 DEGRADED — Mac Mini not pushing T1 scores

════════════════════════════════════════════════════════════

DETAIL
------

MACRO PULSE:
  BTC Price:       $71,397 ✅ (non-zero, data flowing)
  Fear & Greed:    11 — Extreme Fear ✅ (valid 0-100 range)
  BTC Dominance:   56.8% ✅ (valid 1-100 range)
  Total MCap:      $2,507.2B
  DeFi TVL:        $93.5B
  Regime:          UNKNOWN ⚠️ (should show RISK_OFF / EASING / etc.)

CIS UNIVERSE:
  Universe Size:   70 assets ✅ (≥50 threshold met)
  Data Tier:       T2_MARKET (Railway) ⚠️ — Mac Mini not pushing
  Macro Regime:    Risk-Off ✅ (valid regime from CIS engine)
  Scored Assets:   70/70 ✅ (all assets have CIS > 0)
  Badge:           "CIS MARKET · ESTIMATED" (amber)

SIGNAL FEED:
  Signal Count:    19 ✅ (≥5 threshold met)
  Sources:         CoinGecko (movers/trending), Alternative.me (FNG), DeFiLlama (TVL/yields)
  Compliance:      ✅ No BUY/SELL language detected
  Notable:         BETA -64%, VIB -63%, WTC -57% (crash alerts); CREAM +65%, JOE +61% (momentum)
  FNG Signal:      Extreme Fear 11/100 — historical extreme low

TOP ASSETS:
  #1  BTC   B   60.6  NEUTRAL  (F:91.5 M:62.7 O:50.3 S:21.0 A:19.5)
  #2  USO   B   58.5  NEUTRAL  (F:57.2 M:50.7 O:100  S:49.4 A:50.0)
  #3  ETH   B   56.4  NEUTRAL  (F:84.3 M:69.9 O:37.5 S:23.5 A:17.0)
  #4  NVDA  C+  52.6  NEUTRAL  (F:81.4 M:32.7 O:100  S:23.1 A:5.0)
  #5  BNB   C+  52.4  NEUTRAL  (F:79.3 M:49.6 O:47.1 S:12.4 A:22.0)
  All grades valid ✅

KNOWN ISSUES:
  1. Macro Pulse regime = "UNKNOWN" — flat field not populated (nested data shows Risk-Off)
  2. Data tier = T2 — Mac Mini local engine not pushing scores to Redis
  3. S pillar depressed across crypto (FNG 11) — expected given Extreme Fear
  4. TVL = 0 for all assets — DeFiLlama TVL not wired to CIS provider on Railway
  5. 7d/30d price changes = 0 for most crypto — CoinGecko historical data gap

ACTION NEEDED:
  - [Minimax] Check cis_scheduler.py + cis_push.py — Mac Mini not pushing T1 scores to Redis
  - [Jazz] Verify COINGECKO_API_KEY is set in Railway env vars (may explain missing historical data)
  - [Seth] Fix macro_pulse flat-field regime (currently returns "UNKNOWN" while nested data has "Risk-Off")
```
