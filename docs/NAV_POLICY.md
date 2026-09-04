# NAV & Valuation Policy

**Owner:** Seth (valuation designee) · **Approver:** Jazz (governing body) · **Independent check:** Minimax
**Status:** v1 — 2026-09-04 · **Review cadence:** quarterly + on trigger events (§11)

---

## §0 摘要（中文）

我们把 NAV 当作**研究输出**在写，机构基金把 NAV 当作**受控生产流程**在写。差别不在算法，在于
控制点：估值时点、价源层级、独立复核、误差重要性阈值、更正程序、记录连续性。

`读数读不准`不是偶发 —— 它是一整类缺陷，基金行政（fund administration）这门手艺存在的
全部理由就是系统性地消灭它。行业数据里**定价错误是 NAV 重述的最大单一类别**，而其中最常见
的两个成因恰好就是我们已经踩过的：**过期价格**和**错误价源**。

本次审计发现 **3 个 P0**，其中第 3 个是新的、也是最严重的：

| # | 缺陷 | 后果 |
|---|---|---|
| P0-1 | `beta_core:state` Redis key 未按 inception 分版本 | v4 继承 v3 的 NAV 与过期价格；第一行 +20.19% 是 3 天压成 1 天 |
| P0-2 | `get_curve` 用 `last/first` 而非从单位 NAV 1.0 起算 | 发布的 −0.177% 不是 since-inception 回报；且恰好把污染的第一行排除在外 |
| **P0-3** | **没有固定估值时点（valuation point）** | **"日收益"的实际区间在 10.6h 到 35.9h 之间浮动，3.38 倍差距。日频 vol / Sharpe / maxDD 全部失真** |

P0-3 是本文档的核心。它不是 bug，是**缺失的控制**——而这正是 fund admin 的第一条纪律。

---

## §1 Why this document exists

The product is a **verifiable forward track record** (ARCHITECTURE.md). That makes NAV not a
reporting artifact but the deliverable itself. Every other number we publish — Sharpe, max
drawdown, excess vs the panel, the 60-day gate verdict — is a function of the NAV series. An
error in NAV does not misstate one field; it propagates into every claim built on top of it.

Institutional fund administration solved this class of problem decades ago, and the solution is
not better arithmetic. It is a set of **named controls applied in a fixed order, by someone who
did not produce the number**. This document adopts that control set and binds it to our code.

Three sources frame it:

- **Pricing / valuation policy** — SEC Rule 2a-5 (valuation designee, documented methodology,
  pricing-service oversight), AICPA digital-asset practice aid (Level 1, principal market,
  elected daily cut-off time for continuously-traded assets).
- **Error handling** — CSSF Circular 24/856 (in force 2025-01-01, repealing 02/77): materiality
  thresholds, remedial plans, notification windows.
- **Record continuity** — GIPS 2020 (composite construction, linking rules, no silent restatement).

We are not a UCITS and hold no third-party capital in these books today. We adopt the controls
anyway, for one reason: **the apparatus IS the product.** An allocator's operational due
diligence will ask for this document by name, and "we are still pre-launch" is not an answer to
"how do you strike NAV."

---

## §2 The control set — standard → our implementation → status

| # | Control | Source | Our implementation | Status |
|---|---|---|---|---|
| C1 | Written valuation policy, approved before positions are held | 2a-5 | this document | ✅ v1 |
| C2 | **Fixed valuation point** aligned to the dealing/mark cycle | AICPA | §3 — `_VALUATION_POINT_UTC` | 🔴 **P0-3** |
| C3 | Named pricing sources in a fixed hierarchy | AICPA / 2a-5 | §4 | 🟡 exists at use-site, not codified |
| C4 | Stale-price and coverage refusal | IPV stale check | `mark_coverage.weighted_mark`, ≥80% held weight | ✅ (① only — extend) |
| C5 | Independent price verification (second source + tolerance) | IPV | §5 | 🔴 absent |
| C6 | NAV error materiality threshold + correction procedure | CSSF 24/856 | §6 | 🔴 absent |
| C7 | Record continuity — no silent restatement or re-base | GIPS | `_INCEPTION_ID` + `void_reason` | 🟡 **P0-1** (Postgres side only) |
| C8 | Return measured from a fixed unit base | GIPS | §7 | 🔴 **P0-2** (① only) |
| C9 | Shadow / parallel NAV with variance reporting | ODD practice | §8 | 🔴 absent |
| C10 | Segregation: producer ≠ verifier | 2a-5 / ODD | §9 | 🟡 informal |
| C11 | Exceptions & override log | 2a-5 / ODD | §10 | 🔴 absent |
| C12 | Periodic policy review | 2a-5 | §11 | 🔴 absent |
| C13 | Durable write, checked | (ours) | `nav_persist.NavWrite` | ✅ |

C4 and C13 already exist and are good — S-194 and S-214 bought them at real cost. This document
does not re-litigate them; it names them as controls so they stop being incident scar tissue and
start being policy.

---

## §3 Valuation point (C2) — the P0

**Rule.** Every book marks at exactly one instant per calendar day: **00:05 UTC**, using the
price observed at **00:00 UTC**. A mark that cannot be struck within ±30 minutes of the
valuation point is **not marked late — it is refused**, and the refusal is recorded in
`nav_exceptions` (§10).

> **§3 CORRECTION, 2026-09-04 (same day as v1).** This rule first said the refusal should be
> recorded as a `beta_core_nav` row carrying a `void_reason`. That was wrong on two counts, and
> writing the code is what exposed it:
>
> 1. **A row in the NAV table asserts that a NAV was struck.** The entire content of a refusal is
>    that none was. Recording "no NAV" as a NAV row with an annotation is the same shape as
>    recording "no price" as 0.00% — the defect S-194 exists to prevent, one table over.
> 2. **The commonest reason to refuse is that the NAV write path itself is broken.** On
>    2026-09-04 the ① book went dark exactly this way, and a refusal record travelling the path
>    that had just failed would have been lost with it.
>
> Refusals therefore go to a **different table, reached by a different insert**. The policy was
> corrected rather than the code bent to match it — but note which way round that had to happen:
> **the document was wrong and the implementation found it.** A policy that is never implemented
> is never tested, which is the same failure as `_INCEPTION_REASON` describing a Hyperliquid
> price path that the code does not contain.

**Why.** Crypto trades continuously, so a valuation point is not given by a market close — it
must be *elected*, and the AICPA guidance says exactly that. We never elected one. The ① book's
marks land wherever the async loop happened to fire:

```
mark_date    mark_time(UTC)   interval    "daily" return
2026-08-25   03:33:33           18.2h        +2.116%
2026-08-26   15:28:10           35.9h        -6.879%   ← longest interval, largest move
2026-08-27   05:12:00           13.7h        +1.362%
2026-09-01   02:26:35           10.6h        +2.304%   ← shortest interval
2026-09-03   09:29:00           29.2h        +2.655%

interval:  min 10.6h   max 35.9h   ratio 3.38x   mean 23.8h
```

Each of those rows is labelled a daily return and is fed to `realized_vol_30d`, to the annualized
Sharpe, and to the vol-target scaler that sizes the book. **A return series whose sampling
interval varies by 3.4x is not a daily series.** The consequences, in order of severity:

1. **Realized vol is inflated** by the long intervals and understated by the short ones — and
   `realized_vol_30d` is the input to `vol_target_scalar`, which sets gross exposure. The
   sizing layer is being driven by a mis-measured quantity.
2. **Annualized Sharpe is meaningless.** `√365` scaling assumes daily observations.
3. **Cross-book comparison is invalid.** Books marking at different times are measuring
   different windows of the same market, so their excess-return differences are partly an
   artifact of when the loop fired.
4. **The benchmark inherits the same defect**, so `excess` is the only quantity that survives —
   book and benchmark are marked in the same row off the same snapshot. This is why §12 keeps
   `excess` as the headline and demotes standalone Sharpe until C2 is fixed.

**Note the interaction with mark-coverage (C4).** Refusing to mark (correct, per S-194) creates
a gap in the calendar. A gap is honest but it is *not* a free action: the next mark then spans
two days and is still labelled daily. So C2 and C4 must be resolved together — a refused mark
must produce an explicit `void_reason` row, and the following mark must carry
`interval_hours` so the series can be resampled or the row excluded. **Never silently absorb a
missed day into the next return.** That is precisely how the +20.19% row was born.

---

## §4 Pricing hierarchy (C3)

Every position resolves to exactly one tier. The tier used is recorded on the row.

| Tier | Applies to | Primary source | Fallback | Recorded as |
|---|---|---|---|---|
| **L1** | Deep, continuously-quoted crypto | Hyperliquid oracle (spot anchor; median basis to mark +0.088%, p90 +0.327% — S-197) | CoinGecko Pro composite | `px_tier="L1_HL"` |
| **L2** | Crypto without HL coverage | CoinGecko Pro composite | Supabase `ohlcv_daily` prior close, ≤1 day, flagged stale | `px_tier="L2_CG"` |
| **L3** | TradFi (equities, ETFs, commodities) | EODHD | yfinance | `px_tier="L3_EOD"` |
| **L4** | Anything else | **refuse to mark** | — | `void_reason="no_eligible_source"` |

**Venue eligibility is a written standard, not a per-position choice**: real depth, data
integrity, no wash-volume signature, and a documented basis study before a source enters the
table. Adding or reordering a source is a **code change plus a ledger entry**, never a config flip.

**Binance is not an eligible source** — geo-blocked from Railway US, which is what produced the
v3 failure (S-194/S-196). Retained here explicitly so the exclusion is a policy, not an accident.

**① holds spot.** Hyperliquid supplies a price *reference*, not an execution venue. A long
perpetual is a synthetic long that pays carry — the ① panel's own 24 names run +23.07%
equal-weight annualised funding, i.e. ~26.5%/yr at gross 1.15 (S-197). Pricing off a perp venue
must never be read as holding the perp.

---

## §5 Independent price verification (C5)

**Rule.** Every mark is verified against a **second, independent source** before the NAV row is
written. Tolerance by tier:

| Tier | Tolerance (vs secondary) | Breach action |
|---|---|---|
| L1 crypto | 50 bps | Flag, use primary, log exception |
| L2 crypto | 150 bps | Flag, use **lower** of the two, log exception |
| L3 TradFi | 25 bps | Flag, use primary, log exception |
| any | **> 3×tolerance** | **Refuse the mark for that name**; if refusal drops held weight below the C4 floor, refuse the whole row |

Two prices agreeing is not the point — the point is that a **single source failing silently
becomes visible**. v3 marked 0.00% for three days because one source went dark and nothing else
was looking. A second source would have caught it on day one, which is the entire argument for
IPV as an industry control.

**Do not average the two sources.** A composite hides the disagreement; the disagreement is the
signal.

---

## §6 NAV error materiality & correction (C6)

Adapted from CSSF 24/856. Our books are track-record books, not dealing NAVs, so the
compensation machinery does not apply — but the **classification and correction discipline** does,
and the threshold should be *tighter* than a dealing fund's, because the record's credibility is
the only thing being sold.

### Thresholds

| Book type | Significant if error ≥ | Rationale |
|---|---|---|
| ① beta_core (the FoF core & benchmark) | **0.25%** of NAV on any published row | It is the benchmark every sleeve is measured against; an error here propagates to all of them |
| All other paper books | **0.50%** of NAV on any published row | Equity-UCITS-grade; CSSF 24/856 sets 1% equity / 0.5% mixed |
| Shadow-NAV variance (§8) | **0.10%** | Investigation trigger, not an error classification |

### The qualitative override — this is the part percentage thresholds miss

An error is **significant regardless of magnitude** if it:

1. changes the **sign** of excess return, or of any published daily return;
2. changes a **gate or validation verdict** (60-day gate, `oos_survival`, SHIP/NO-SHIP);
3. arises from a **control failure** rather than a data revision — i.e. the number was wrong
   because a check did not run, not because the input changed;
4. would change what a reader **concludes**, even if the number moves by a basis point.

Reason: a 0.04% error that flips `excess` from −0.01% to +0.03% turns "③ contributed nothing"
into "③ added value." Materiality in percent alone is blind to that, and it is exactly the class
of failure this codebase keeps rediscovering.

### Correction procedure

1. **Classify** within 24h of discovery — significant or not, by threshold *and* by override.
2. **Do not overwrite.** Superseded rows are marked with `void_reason` and stay queryable.
   The graveyard is the asset; a NAV that can be quietly restated proves nothing.
3. **Significant → the segment is voided and re-incepted** (§7), with the reason, date, and
   attribution in `_INCEPTION_REASON` and a matching `REFUTATION_LEDGER` entry.
4. **Not significant → correct forward**, log the exception (§10), no re-inception.
5. **Disclose** on the reading surface: any endpoint serving a curve that contains a corrected
   segment returns `restatements: [...]` alongside the rows. CSSF gives funds 4–8 weeks to
   notify; our equivalent is **same-day**, because the reader is a machine and the endpoint is
   the notification channel.

### Standing classification of the three P0s

| Defect | Magnitude | Significant? |
|---|---|---|
| P0-1 inception inheritance | first row +20.19% on a NAV base that should be 1.0 | **Yes** — override (1), (3), (4) |
| P0-2 return basis | published −0.177% vs true since-inception | **Yes** — override (4) |
| P0-3 no valuation point | intervals 10.6h–35.9h | **Yes** — override (2) and (3); invalidates every annualized figure |

⇒ **the ① v4 segment is VOID.** See §7 for what replaces it.

---

## §7 Record continuity & re-inception (C7)

**Rule.** A NAV series is identified by `(book, inception_id)`. Every artifact that can carry
state across a re-inception must be scoped by `inception_id` — **Postgres rows, Redis keys,
in-process caches, and any file on disk.**

`beta_core` scoped its Postgres reads correctly and left the Redis key unscoped:

```python
_STATE_KEY = "beta_core:state"      # ← survives a re-inception, carries the old NAV
```

On 2026-08-23 `_INCEPTION_ID` moved v3 → v4. Redis still held v3's state dict, complete with
`weights` and `mark_prices` frozen at 08-20. The guard `if not state.get("weights")` therefore
passed, so neither the Postgres-recovery branch (correctly filtered to v4, would have returned
`None` → clean start at 1.0) nor the fresh-inception branch ran. v4's first mark compounded onto
v3's NAV of 1.047005 **and** differenced against v3's three-day-stale prices:

```
nav  1.258366 / 1.201872 = 1.047005   ← v3's NAV, inherited
bmk  1.200400 / 1.155286 = 1.039050
daily_return +20.19% ≈ 1.1103 × 0.9857 × 1.098   ← 08-21, 08-22, 08-23 compounded into one row
excess +4.66%                                     ← the only non-zero excess in 12 rows; an artifact, not alpha
```

**Both defects v4 was created to fix were baked into v4's first row.** The inception-identity
mechanism was sound; its scope was one key too narrow. This is the same lesson MEMORY.md already
records about the MEMORY.md cap — *a control with too narrow a scope redirects attention away
from what it misses.*

**Re-inception rules (GIPS-derived):**

- Re-inception costs a commit. Changing `_INCEPTION_ID` is a code change: reviewed, dated,
  attributed, permanently visible in `git log`. Never an env var, never a config flip.
- **Never splice.** A curve served to a reader contains exactly one `inception_id`.
- Superseded segments are retained with `void_reason`, queryable, and linked from the
  successor's `_INCEPTION_REASON`.
- The gate clock **resets**. 60 forward days means 60 days of the current incarnation.

---

## §8 Return basis (C8)

**Rule.** Cumulative return is always measured from **unit NAV 1.0**, never from the first
retained row.

Every book computes `(navs[-1] - 1) * 100`. `beta_core` alone computes:

```python
cum = last["nav"] / first["nav"] - 1.0        # beta_core_paper.py:1099
```

With a first row of 1.258366 this publishes a *12-day window* return and calls it the book's
return — and because the contaminated row is the first one, the headline silently **excludes**
the +20.19% it should have surfaced. Two defects that partially cancel, which is worse than
either alone: the reader sees a plausible small number and has no reason to look.

The ① book is the one where this matters most, because it is the benchmark.

---

## §9 Shadow NAV (C9)

**Rule.** A second implementation recomputes each book's NAV independently from the same stored
prices, daily, and the variance is published. Industry tolerance for shadow-NAV variance runs
0.05%–0.50% by strategy risk; ours is **0.10%**, breach → investigate before the row is served.

The two implementations must not share the marking code path. A shadow NAV that calls the same
function verifies nothing — it verifies that the function is deterministic, which was never in
doubt.

Minimax is the natural operator: a different lane, a different process, reading Supabase rather
than Redis. **A lane can only judge what it can see** (S-276) — so this requires giving Minimax
read access to the NAV tables, which is an interface change, not a discipline request.

---

## §10 Segregation & exceptions log (C10, C11)

| Role | Fund-admin analogue | Here |
|---|---|---|
| Governing body — approves policy, rules on exceptions | Board / valuation committee | **Jazz** |
| Valuation designee — applies the policy, strikes NAV | Adviser under 2a-5 | **Seth** (`src/`) |
| Independent verification — reperforms, reports variance | Administrator | **Minimax** (§9) |
| Audit trail | Auditor working papers | `REFUTATION_LEDGER.md`, `git log`, `void_reason` |

**Exceptions log.** Every override, stale-price acceptance, IPV breach, refused mark, and manual
adjustment gets a row in `nav_exceptions` with: date, book, symbol, control that fired, action
taken, actor, and reason. Empty is a fine state; **absent is not** — the log's job is to make
"we never had exceptions" distinguishable from "we never looked."

Manual price overrides must be **possible, rare, logged, and approved — never silent.**

---

## §11 Review cadence (C12)

| When | What |
|---|---|
| Daily | Control checklist §12 runs with the mark; failures surface on the endpoint, not in logs |
| Weekly | Shadow-NAV variance report; exceptions log review — folded into the Sunday strategy review |
| Quarterly | Policy review: sources, tolerances, thresholds, incidents |
| On trigger | Source outage, venue delisting/depeg, regime-classifier change, any significant error (§6), any re-inception |

---

## §12 Daily control checklist

Runs in order. Any 🔴 refuses the mark rather than degrading it.

1. 🔴 **Valuation point** — within ±30 min of 00:05 UTC, else refuse (§3)
2. 🔴 **Interval** — `interval_hours` recorded; >30h or <18h flags the row as non-daily
3. 🔴 **Source tier** — every held name resolves to L1–L3, else refuse (§4)
4. 🔴 **Coverage** — ≥80% of held weight priceable (`mark_coverage`), else refuse (C4)
5. 🟡 **IPV** — secondary source within tolerance, else flag + log (§5)
6. 🔴 **Inception scope** — state key matches current `_INCEPTION_ID`, else refuse (§7)
7. 🔴 **Durable write** — `NavWrite.ok`, else `nav_persisted: false` with reason (C13)
8. 🟡 **Shadow variance** — <0.10%, else flag (§9)
9. 🟡 **Return basis** — cumulative from 1.0 (§8)

**Until C2 is fixed, `excess` is the only headline.** Book and benchmark are marked in the same
row off the same snapshot, so excess survives an irregular interval; standalone Sharpe, vol, and
annualized figures do not. Endpoints should suppress them rather than publish them with a
footnote — a footnoted wrong number still gets quoted.

---

## §13 What CI enforces

Prose is not a control. `tests/test_nav_policy.py` enforces:

- every `_STATE_KEY` in a book carrying an `_INCEPTION_ID` embeds that id
- no book computes cumulative return as `last/first`
- every book declares a valuation point and every NAV row carries `interval_hours`
- `mark_coverage` is called on every marking path (no book accumulates from 0.0 unguarded)
- the pricing-hierarchy table in §4 matches the sources actually reachable in code
- materiality thresholds in §6 exist as constants, not as text

The caps in MEMORY.md are CI, not advice, for the same reason. **The test is the memory.**

---

## §14 Open items

| # | Item | Owner | Blocking |
|---|---|---|---|
| 1 | Fix P0-1/2/3; void ① v4, re-incept v5 from 1.0 | Seth | 60-day gate restarts |
| 2 | Extend `mark_coverage` to all books, not just ① | Seth | — |
| 3 | Build IPV secondary-source check (§5) | Seth | — |
| 4 | `nav_exceptions` table + writer (§10) | Seth | migration |
| 5 | Shadow NAV (§9) | Minimax | needs Supabase read grant — `MINIMAX_SYNC` |
| 6 | Decide dealing-NAV thresholds before any real LP capital | Jazz | pre-launch |

---

*Internal engineering & governance document. Contains no investor-facing performance claims.
Positioning language elsewhere in the system is restricted to
STRONG OUTPERFORM / OUTPERFORM / NEUTRAL / UNDERPERFORM / UNDERWEIGHT.*
