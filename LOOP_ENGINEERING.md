# Loop Engineering — data flow, storage, and value mining (2026-07-10)

*Seth. Jazz's concern: is this a real AI engineering loop (stores its own decisions +
outcomes, mines them, feeds back) or open-loop compute that logs and forgets? Assessed
from the live code + live Railway state, not from the doc. Verdict: one real closed
arc exists (proven live); the rest is write-heavy / read-light — a durable LOG, not yet
a learning substrate. Companion to ARCHITECTURE.md.*

---

## Verified live 2026-07-10 (via `/internal/loop-health`)

`LOOP HEALTH — FLOWING`. Every stage green: CIS universe (58 assets), Mac Mini→Redis
push (fresh), **upstream causes (forward_supply + positioning on all 24 crypto assets —
real values, e.g. ONDO fs_risk=0.702, pos=−0.405)**, measure→feedback (conviction_factors
learned), narrative/NMA (differentiated). NOTE: an earlier "causes empty on Railway" flag
was a FALSE ALARM — it read a flat field when the data is nested under `forward_supply` /
`positioning`. The standing probe (`src/api/loop_health.py` + `GET /internal/loop-health`)
now guards against exactly that class of silent-orphan error.

## The loop, stage by stage (actual state)

```
INGEST → COMPUTE → STORE → SERVE → ACT → MEASURE → LEARN → FEED BACK ↺
```

| Stage | What runs | State |
|---|---|---|
| **Ingest** | CG (Pro), DeFiLlama, Binance funding/OHLCV, Moralis holders, CryptoPanic | ✅ real |
| **Compute** | CIS pillars, causes (fwd-supply/positioning), narrative (repaired today), signals, conviction, edge map | ✅ real |
| **Store — hot** | Upstash Redis (2h TTL): `cis:local_scores/forward_supply/positioning/holder_map/regime/embeddings/factor_*` | ⚠️ serve-cache; some keys empty on Railway (causes) |
| **Store — durable** | Supabase: cis_scores, signal_journal, cause_snapshots_daily, conviction_verdicts_daily, regime_band_log, trade_results, cis_backtest_results, macro_briefs, signal_track_record | ✅ writing (**88 inserts**) |
| **Serve** | 127 endpoints → frontend, agents, MCP, strategies | ✅ real |
| **Act** | paper sleeve, signals | 🟡 paper sleeve reverted/gated this session |
| **Measure** | `outcome_tracker.py`: signal → 30d benchmark-relative outcome → patched back | ✅ real |
| **Learn** | `refresh_signal_track_record` RPC; grade backtest; edge shrinkage; DSR (manual) | 🟡 partial / manual |
| **Feed back** | `conviction_from_track_record` → risk-meter weights | ✅ **one real closed arc** |

## The good news — one arc genuinely closes (proven live)

The system demonstrably learns from its own outcomes. Live right now:

```
conviction_factors = {STRONG OUTPERFORM: 1.265, OUTPERFORM: 0.739,
                      NEUTRAL: 0.35, UNDERPERFORM: 0.0, UNDERWEIGHT: 0.0}
```

That is not hand-set. The chain: our signals → `signal_journal` → `outcome_tracker`
resolves each at 30d vs benchmark → `refresh_signal_track_record` (scheduled) → 
`conviction_from_track_record` → risk-meter weights. The system **earned** a 1.265×
tilt for STRONG OUTPERFORM and **suppressed UNDERPERFORM/UNDERWEIGHT to 0** from its
own realized results. That is a real AI engineering loop — store decision, measure
outcome, feed back into the next decision. Not SOP mimicry.

## The concern — only ONE arc closes; the rest is a write-only log

The database is used as a **durable log awaiting a read-back that mostly never comes.**
Signature: **88 `insert` calls, ~1 automated decision read-back** (the track-record arc).
Everything else accumulates and is mined only manually or not at all:

1. **`cause_snapshots_daily` + `conviction_verdicts_daily`** — written daily, but their
   consumer (`cause_backtest.py`) is **BLOCKED**: `_load_ohlcv_panel()` raises
   `NotImplementedError`. So the causes' value-mining has never run. We store the raw
   material for the moat and never refine it.
2. **`regime_band_log`, `trade_results`** — written, read back only in ad-hoc research.
3. **Narrative (NMA + catalyst)** — computed (repaired today) but **not stored at all**,
   and `apply_narrative_to_s_pillar` is never called → it neither persists nor feeds back.
4. **Learning is manual.** The sharpest mining this session (DSR certification, OOS,
   correlation, the causal backtest) I ran by hand. A real loop runs them on a schedule
   and acts on the result.

So: the *skeleton* of a real loop exists and one arc is alive, but value-mining is
**deferred (blocked), manual, or missing** for everything except the signal→weight arc.
We store far more than we mine.

## The unlock that's already in hand

The single blocker on the causes' value-mining is `_load_ohlcv_panel()` — a daily OHLCV
panel. **The `causal_positioning.py` Binance loader built this session fetches exactly
that** (daily close/volume for the universe, no geo-block). Wiring it into
`cause_backtest._load_ohlcv_panel()` unblocks the cause value-mining *today* — turning
`cause_snapshots_daily` from a write-only log into a mined signal. That is the highest-
leverage single wire in the whole loop.

## Plan to close the loop (make the DB a learning substrate, not a log)

1. **Unblock cause mining now** — point `_load_ohlcv_panel` at the `causal_positioning`
   Binance loader; run `cause_backtest`; the causes get their first real read-back.
2. **A read-back per write** — every table we insert into gets a named consumer that
   turns it into a decision (weights, gates, sizing), or we stop writing it.
3. **Automate the learning** — schedule DSR + OOS + outcome→weight as loops, not manual
   research. Extend `conviction_from_track_record` from per-signal to per-cause /
   per-strategy (the causal sleeve, the swing lineage) once each has a track record.
4. **Fix the orphans** — persist narrative (nma + catalyst) to Supabase and wire the
   S-pillar injection; repair the cause Redis population on Railway so snapshots aren't
   zeros.
5. **Loop-health instrument** — one view: per stage, last-run time, is data flowing, is
   it being read back. So an orphan (like narrative was) can't hide for months again.

---

*Verdict for Jazz: it IS a real loop — the conviction_factors prove the system learns
from its own outcomes and re-weights accordingly. But it's a loop with one closed arc
and a lot of write-only logging around it. The database stores the raw material for the
moat (causes, verdicts, regimes) and barely mines it, mostly because the mining step is
blocked or manual. Closing it is concrete, not aspirational — and the first, highest-
leverage wire (OHLCV → cause backtest) is already built.*
