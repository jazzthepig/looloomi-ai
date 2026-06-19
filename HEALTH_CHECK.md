# COMETCLOUD HEALTH CHECK — 2026-05-29 15:05 UTC

```
MACRO PULSE    ✅ LIVE  — BTC $73,028 | FNG 23 (Extreme Fear) | Dom 57.6% | MCap $2.54T
CIS UNIVERSE   ⚠️ T2   — 58 assets | T1=0 T2=58 | regime: Risk-Off | top: NEAR B (59.9)
SIGNAL FEED    ✅ ACTIVE — 11 signals | compliance OK (no BUY/SELL language)
TOP ASSETS     ✅ OK    — NEAR B 59.9 | ETH B 55.7 | BTC C+ 54.8 | INJ C+ 54.4 | BNB C+ 54.0

OVERALL: 🟡 DEGRADED — Mac Mini not pushing T1 scores
```

## Details

### Macro Pulse
All data flowing. BTC price, Fear & Greed (23), dominance (57.6%), total market cap ($2.54T),
DeFi TVL ($79.2B) all returning valid values. Regime source: `fred_derived` from CPI 3.78%,
GDP growth 6.4%, policy rate 3.64% → RISK_ON.

### CIS Universe
58 scored assets, all data_tier=2 (Railway estimation). **Zero T1 assets** — Mac Mini local
engine is not pushing scores to Redis. Universe size dropped from expected ~70+ to 58.

Top 5: NEAR B (59.9), ETH B (55.7), BTC C+ (54.8), INJ C+ (54.4), BNB C+ (54.0).
No B+ or higher assets — consistent with Risk-Off regime suppressing S and A pillars.

### Regime Mismatch
- Macro Pulse endpoint: `RISK_ON` (fred_derived — based on macro indicators)
- CIS Universe endpoint: `Risk-Off` (CIS engine's market-derived regime)

These use different regime detection methods. The CIS engine's Risk-Off is market-sentiment
driven (Extreme Fear, alts underperforming). The macro-pulse RISK_ON is macro-indicator
driven (GDP growth 6.4%, easing policy rate). Not necessarily a bug, but worth noting
the divergence — the two signals tell different stories.

### Signal Feed
11 signals across WHALE, MOMENTUM, RISK, FLOW, REGULATORY, MACRO types. All use compliant
positioning language. Notable: ALLO +154% whale signal, DeFi TVL -1.5%, FNG at 23
(Extreme Fear).

### Compliance
No BUY/SELL/HOLD/ACCUMULATE/AVOID language detected in any signal output.

## ACTION NEEDED

1. **Mac Mini T1 push down** — `cis_scheduler.py` is not pushing scores (T1=0).
   Minimax should check: is `cis_scheduler.py` still running? Is Redis connection
   (`UPSTASH_REDIS_REST_URL`) reachable from Mac Mini? Check `cis_push.py` logs.

2. **Universe size 58 vs expected ~70+** — Likely because T2 Railway estimation covers
   fewer assets than T1 Mac Mini engine. Will resolve when T1 comes back online.

3. **Regime label inconsistency** — Consider normalizing regime labels between
   macro-pulse (`RISK_ON`) and CIS universe (`Risk-Off`) to avoid confusion in
   downstream consumers and agent APIs.

---
*Previous check: 2026-05-23 — MACRO PULSE was DOWN (API timeout). Now recovered.*
