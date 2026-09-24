# Jev → Nautilus Trader Integration Plan

**Date:** 2026-09-21
**Author:** Seth (Austin) — Nautilus owner per JAZZ reframe
**Lane:** Seth (`docs/`)
**Source research:** community use cases survey (5 patterns, 4 trading projects, 195 total)
**Status:** design proposal — not yet wired

---

## TL;DR

Jev is a **decision kernel** (state-in / typed-probability-out, not text). It fits Nautilus's
actor/strategy model cleanly as a **gating layer above existing strategies**, not as a
replacement for them. Start with **Pattern A (pre-filter / regime gate)** because:

1. **Smallest blast radius** — Jev can say "no" without affecting the strategy's normal operation.
2. **Calibration is testable** — gate fires are rare events; measured hit rate vs base rate = honest Brier.
3. **Doesn't require trust in Jev's probabilities** — only trust in its binary "is this tradeable?" call.
4. **Composes with §5b doctrine** — Jev sits at ⓪ OVERRIDE layer, not inside ①②③④.

**Don't** start with Pattern B (sole decider) — that requires trusting Jev's probability
calibration, which is **unproven** (no published Brier / ECE).

---

## Architecture fit (Nautilus actor/strategy model)

```
NautilusTrader (existing)
├── DataActor: market data ingestion + bar aggregation
├── Strategy: signal generation + order management + sizing
└── RiskEngine: pre-trade risk checks + position limits

PROPOSED addition (Pattern A):
├── JevRegimeActor (new DataActor subclass)
│   on_bar(bar): build_state() → typesafe.evaluate(...) → publish JevRegimeDecision
└── Strategy (modified)
    subscribe to JevRegimeDecision
    if decision.regime_ok == False: skip this bar's signal generation
    else: existing strategy logic
```

**Key principle: risk gates / sizing / stops / doctrine stay OUTSIDE Jev.**
Seth-side risk logic stays in Python where it's testable. Jev is a yes/no oracle.

---

## 5 community patterns mapped to Nautilus

| Pattern | What Jev does | Nautilus shape | Risk | Ship priority |
|---|---|---|---|---|
| **A. Pre-filter / router** | "Is this regime tradeable?" binary | `JevRegimeActor` publishes `regime_ok` boolean; Strategy subscribes | Low | **🥇 Start here** |
| B. Decision kernel (jev-trader) | Sole decider: state→action | Replace Strategy internals | High (single point of failure) | After A validated |
| C. Post-verdict judge | Score another LLM/workflow output | New `JevJudgeActor` for thesis generation | Medium | When thesis layer exists |
| D. Multi-primitive batch | bool + score + choice per ticker | One `evaluate()` call across N tickers (radix cache) | Low (additive) | When scaling to portfolio |
| E. Open-source self-host (openjev-sglang) | Same as A/B but local | Substitute `typesafe.evaluate` with local inference | Medium (license OK, infra burden) | If prod needs offline |

---

## Concrete skeleton (Pattern A — recommended start)

```python
# src/trading/jev_regime_actor.py
from nautilus_trader.common.actor import DataActor
from nautilus_trader.model.data import Bar
from typesafe_ai import typesafe
from typesafe_ai.primitives import Choice, Score, Noul

class JevRegimeActor(DataActor):
    """Decision-kernel-as-gate. Jev says yes/no; Strategy decides what/how."""

    def __init__(self, config: JevRegimeConfig):
        super().__init__(config)
        self._state_buffer: dict[str, Any] = {}
        self._buffer_max_bars: int = config.buffer_max_bars

    def on_bar(self, bar: Bar) -> None:
        # 1. update state buffer (rolling features: vol, spread, returns, regime, etc.)
        self._update_state(bar)

        # 2. skip until buffer full
        if len(self._state_buffer) < self._buffer_max_bars:
            return

        # 3. ask Jev: is this regime tradeable?
        result = typesafe.experimental_evaluate(
            model="typesafe-ai/jev",
            state=self._build_state_payload(),
            questions={
                "regime_ok": Noul(
                    "Given current vol, spread, breadth, and macro regime, "
                    "is this a tradeable regime for our strategy?"
                ),
                "direction_bias": Choice(
                    criteria={
                        "long": "vol < 1.2x 20d, breadth > 0.5, regime EASING",
                        "short": "vol > 1.5x 20d OR regime TIGHTENING with breadth < 0.3",
                        "neutral": "otherwise",
                    }
                ),
                "confidence": Score(levels=["low", "med", "high"]),
            },
        )

        # 4. publish decision — Strategy subscribes
        self.publish_data(JevRegimeDecision(
            bar_ts=bar.ts_event,
            regime_ok=result["regime_ok"].probability > 0.5,
            direction_bias=result["direction_bias"].choice,
            confidence=result["confidence"].score,
            jev_input_tokens=result.usage.input_tokens,
            jev_latency_ms=result.latency_ms,
        ))
```

**Strategy side** (modify existing strategies, e.g. `BetaCorePaperStrategy`):

```python
def on_bar(self, bar: Bar) -> None:
    # NEW: skip if Jev says regime not tradeable
    if self._jev_decision and not self._jev_decision.regime_ok:
        return  # Jev gate closed; do nothing

    # ... existing strategy logic unchanged ...
```

**Critical: Jev is ONE input among many.** Strategy still has its own regime detector,
its own doctrine checks, its own position sizing. Jev's `regime_ok=False` is a single veto.

---

## 60-day validation protocol

Before Pattern A ships live, must pass these gates (per S-114 lag-discipline + M-145 sparse-guard):

### Gate 1: Calibration
- Run Jev on **60d paper track** (no live orders) with Jev's `regime_ok` decisions logged.
- Compute: **empirical Brier score** on `regime_ok` decisions vs realized 5d forward return (positive = tradeable).
- **Pass criterion:** Brier < 0.20 (better than naive "always yes" baseline of 0.25).
- **Fail action:** Don't ship. Diagnose with Platt scaling or isotonic regression on holdout.

### Gate 2: Hit rate
- Of bars where `regime_ok=True`, measure **strategy's hit rate** vs holdout where Jev says False.
- **Pass criterion:** hit rate (Jev=True) > hit rate (Jev=False) + 5pp.
- **Fail action:** Jev is anti-correlated with our strategy; investigate what regime it's catching.

### Gate 3: Frequency
- How often does `regime_ok=False`? (5-30% expected; <5% = Jev is doing nothing; >50% = blocking too much).
- **Pass criterion:** 5-30% veto rate on daily bars.
- **Fail action:** Tune schema prompt or threshold.

### Gate 4: Cost realism
- 60d Jev spend at proposed cadence: e.g. daily regime check across 50 assets = $0.01/day = $0.60/60d.
- Sub-bar cadence (5min): ~50 ticks/day × 50 assets × $0.0004/call = $1/day = $60/60d.
- **Pass criterion:** Jev cost < 1% of strategy gross alpha in paper track.

### Gate 5: Doctrine check
- Jev says `regime_ok=True` but Strategy says doctrine fail → Strategy wins (doctrine is authoritative).
- Jev says `regime_ok=False` but Strategy says go → Strategy skips (Jev veto honored).
- **Pass criterion:** no doctrine violations slip through Jev gate.

---

## Risks (from community research)

| Risk | Impact | Mitigation |
|---|---|---|
| **No published Brier/ECE** | Trust in Jev's probabilities = unproven | 60d empirical Brier Gate 1; never trust probability for sizing |
| **Calibration drifts** | First 60d may differ from next 60d | Recompute monthly; ship "Jev gate on/off" toggle |
| **No explanation per decision** | Hard to debug bad veto | Log state payload + result; spot-check 10 random vetoes/week |
| **Schema rigidity** | Forgetting "hold" option → Jev forces buy/sell | Schema MUST include "neutral" + "insufficient evidence" |
| **150ms latency** | Too slow for sub-100ms strategies | Gate at bar close only (≥1m bars); not for tick strategies |
| **255 cardinality cap** | High-cardinality state slows 2-stage | Keep state payload < 50 fields |
| **Closed-source SaaS** | Vendor dependency, key risk | Plan E (open-source clone openjev-sglang) ready if license becomes blocker |
| **$0.042/M tokens** | Sub-second cadence = $175/month | Cap Jev calls/day at daily-cadence regime check ($0.01/day) |

---

## Mapped to ARCHITECTURE §5b

| §5b layer | Jev integration point |
|---|---|
| ⓪ OVERRIDE (downside protection) | **Pattern A** — Jev gates "is regime tradeable?" before strategy fires |
| ① capture beta (long-only hold) | No Jev — passive hold doesn't need a decision kernel |
| ② beta+ (CIS tilt) | Future — Jev could score CIS confidence per asset (Pattern D batch) |
| ③ time exposure (gross 0.7-1.3) | Future — Jev could decide regime multiplier (Pattern C post-verdict) |
| ④ pure alpha | Future — Jev as sole decider for satellite sleeve (Pattern B, post 60d validation) |

**Start at ⓪ (Pattern A).** Graduate to ②③④ only after Pattern A passes all 5 gates above.

---

## Next steps (Seth lane)

1. **This week:** Wire Pattern A into a paper-track `BetaCorePaperStrategy` instance (no live orders).
2. **+60d:** Run 60d paper validation; compute Gate 1-5 metrics; emit §S-395 in MINIMAX_SYNC with verdict.
3. **If gates pass:** Promote Pattern A to live `BetaCorePaperStrategy` with Jev gate = ⓪ OVERRIDE.
4. **If gates fail:** Diagnose (Brier / schema / cadence); iterate or abandon Jev integration.
5. **After ⓪ ships:** Pattern D multi-primitive batch for CIS confidence scoring (⓪→② expansion).

**NOT Seth's lane:** Jev's evaluation methodology, Jev's calibration paper, Jev's vendor
relationship. Those belong to Min-C if A/C takes them.

---

## References

- TypeSafe launch: https://typesafe.ai/blog/introducing-system-one-models-and-jev
- Best independent critical writeup: https://anthonymaio.substack.com/p/jev-the-language-model-that-wont
- Best trading reference: https://github.com/jarrodwatts/jev-trader (MIT, live MON/USDC, 100ms loop)
- LangChain integration patterns: https://www.langchain.com/blog/building-a-harness-with-jev
- Community index (195 projects): https://madewithjev.com/github-repos
- LiteLLM Python SDK: https://docs.litellm.ai/docs/pass_through/typesafe
- NautilusTrader actors: https://nautilustrader.io/docs/latest/concepts/actors/
- Memory file: `~/.claude/projects/-Users-sbb/memory/jev-typesafe-community-research-2026-09-21.md`

**Status:** Design proposal. No code written. No key needed yet (paper track uses mock state until
60d validation framework ready).
