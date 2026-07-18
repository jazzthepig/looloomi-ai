# Trader Tom Doctrine — behavioral-edge foundations for CometCloud

*Seth, 2026-07-17. Study commissioned by Jazz: "further study trader tom's philosophy."*
*Source: Tom Hougaard, **Best Loser Wins: Why Normal Thinking Never Wins the Trading Game**.*

> **Why this doc exists.** Our Shadow local engine referenced "Trader Tom's Methodology" as
> an RSI/ADX/MACD confluence grid (`Shadow/cometcloud-local/tools/autoresearch.py`,
> `Shadow/freqtrade/tools/polymarket_signal.py`). **That is a misreading.** Hougaard's book is
> explicitly *not* about technical setups — it is about mind management and crowd behavior.
> This doc records the real philosophy and binds it to our architecture so we build on the
> durable part (behavioral edge), not the caricature (indicator fitting that decays).

## 1. Who / what

Tom Hougaard ("Trader Tom") — Danish high-stakes day trader, ex-broker-floor, famously
compounded £25k → £1M+ in a year. His edge claim is behavioral, not predictive: the tools of
trading have improved enormously (cheap data, tight spreads, instant execution) but human
psychology has not, so the majority still lose. The edge is being deliberately *abnormal*.

## 2. The real principles

1. **"Normal thinking never wins."** ~90% of participants lose because they are hardwired to
   do the wrong thing (book winners early, ride losers on hope). The edge is the *opposite* of
   the crowd, by construction.
2. **Best loser wins.** Survival ≠ best predictor. It is the trader who loses *small, fast, and
   cleanly*. Governing line: **"I want to be big when I'm right and small when I'm wrong."**
3. **Three commands.** (1) I assume I am wrong until proven otherwise. (2) I expect to be
   uncomfortable. (3) I add when the crowd subtracts (and subtract when it adds).
4. **Add to winners, never to losers.** Averaging *up* on a confirmed thesis reinforces correct
   behavior; averaging *down* on a broken thesis is the classic blow-up. Adding to winners is a
   deliberate act *against* human nature.
5. **Hope is the enemy.** An open loser keeps hope alive and remote-controls the mind. Cutting it
   frees both capital *and* attention — you are then trading the market, not your own emotions
   (cognitive dissonance).
6. **Mindset is trainable through experience, not theory** — like an athlete resetting instantly
   after a miss. Dump-and-forget the loser; focus on the next opportunity.

## 3. The central tension — and its resolution

Jazz's north star: *"capture a high percentage of wins, cyclical opportunity that repeats over
and over — not simple tech specs that trade like bots doomed to fail."*

Hougaard **directly challenges "high percentage of wins" at the trade level.** His broker-floor
observation: *losing* traders often have *high* hit rates (right more often than wrong) yet blow
up, because they cut winners early and hold losers. Great investors run **20–25% hit rates** and
still beat the market — few winners, made huge. High per-trade win-rate correlates with
**negative skew**: many small wins, one fatal loss. Optimizing for it is the amateur trap he names.

**Resolution — the goal is real, the level is wrong.** "We win most of the time" is achieved not
by a high per-*trade* hit rate but by **breadth**:

> Fundamental Law of Active Management: **IR = IC × √breadth.**

Run many *independent, repeatable* edges and the **book's** win rate across months/quarters is
high even though each individual edge is low-hit-rate / high-payoff. Same felt outcome Jazz wants
— the book is green most periods — opposite mechanism from the doomed high-win-rate bot. This is
also why "library beats hero" (the signal factory) is the correct structure, not a coincidence.

## 4. Why Trader Tom IS the foundation for "repeats over and over"

The cycle that repeats forever is **the crowd's emotional cycle**. Indicator fits decay because
microstructure changes; fear and greed do not — that mechanism has no half-life. Hougaard's whole
edge is harvesting hardwired crowd behavior. So the behavioral read is not a detour from the
"cyclical, repeatable" thesis — it is its most durable expression. Every recurring setup we keep
should ultimately trace to a *human* cause (leverage, hope, capitulation, FOMO), because that is
the cause that recurs without decaying.

## 5. Principle → CometCloud mechanism

| Trader Tom principle | Our mechanism (already built or on the roadmap) |
|---|---|
| Fade the crowd (normal thinking loses) | **Positioning-crowding layer** — fade crowded longs (flush risk), ride crowded-short squeezes |
| Be big when right, small when wrong (convexity) | **Conviction engine** sizing; **edge-map** tier × risk-band expected alpha |
| Add to winners, not losers | Add to **confirmed catalyst activation** (L2); never average down a broken thesis |
| Assume wrong until proven otherwise | **Refutation ledger** (R1–R21) — every claim guilty until OOS-proven; **DSR/PBO** gate |
| Best loser wins (loss discipline) | Hard exit rules; factory kills a strategy before it kills the book |
| High book win-rate via breadth, not per-trade | **Signal factory / combined book** — many independent edges → smooth equity |
| Crowd emotion is the non-decaying cycle | **Recurring-setup registry** — every kept setup traces to a human cause |

## 5b. Expectancy over hit-rate; ride the trend (Jazz, 2026-07-17)

The refinement that operationalizes §3. The objective is **expected outcome, not win
percentage**: `E = Σ(p · payoff)`, dominated by the right tail. We do **not** need a high
percentage of winning; we need high expectancy. This forces a two-layer book:

1. **Durable fundamental core — never sold on short-term volatility.** Conviction positions
   are held *through* the noise. Being shaken out by a wick is the amateur's tax; volatility is
   not information about the thesis. (Sell only when the *thesis* breaks — cause invalidated —
   not when the *price* wobbles.) **NB (Jazz, 2026-07-17): this is spot / major-trend ASSET
   HOLDING — a different instrument and a different risk game from leveraged index/futures
   trading. "Hold through noise" applies to the conviction spot position, NOT to a 3× futures
   sleeve, which has its own mechanics (margin, funding, liquidation, hard stops). Never apply
   one game's rules to the other.**
2. **Tactical trend-riding overlay — gross scales with regime.** Risk-OFF → **defend**: small,
   hedged, cut fast. Risk-ON **and a confirmed long-term trend** → **press**: double down, ride
   the beta. You must *ride* risk, not hide from it.

**The master skill is judgment of the major trend** — it is the switch between defend-mode and
press-mode. Get the regime/trend call right and the sizing rules do the rest.

**The asymmetry law (the strategic core):** *If you cannot win big when beta is positive, you
cannot win bigger when the market is tight and low on volume.* The confirmed up-trend is the
easy money. A fund that plays safe there — that can't press a winner when everything is in its
favor — is deluding itself about the hard, thin tape. **Capturing the up-trend aggressively is a
prerequisite competency, not a nice-to-have.** Our edge-map posture (`_BAND_POSTURE` scaling gross
by risk band) is the seed of this, but current gross tops out ~1.10 — **too timid** for this
doctrine. The risk-ON, trend-confirmed gross must express real convexity.

**Anti-rot discipline:** "double down on trend" = **add to a *confirmed* winner** — Hougaard's
add-to-winners — **never** average into hope on a position working against you. But the press is
**evidence-gated, not mechanical**: in a market like BTC full of false breakouts (诱多/诱空,
stop-hunts, liquidity grabs), "higher high → add" is naive. Trend confirmation is a **judgment call,
一事一议** — weigh volume, positioning, and liquidity structure to tell a real breakout from a trap.
What is invariant is the *direction* of the rule (add only to what's working, never to hope), NOT any
single mechanical trigger. Defense in risk-OFF is equally rule-bound: cut fast, reduce gross, do not hope.

## 5c. Why two layers — mean-reversion vs trend are opposite skews (the resolution)

A sleeve can *contradict* Hougaard trade-by-trade and still belong in the book. Case in point,
`CometCloudMultiFactorV2` (MVRV capitulation buyer): at the trade level it **violates** three of his
rules — no stop on longs (rides losers on hope), take-profit exits (clips winners), and a
77%-win / −63%-loss silhouette (his negative-skew death pattern). Yet its *cause* is pure Tom:
逆人性, buy when the crowd is fearful ("normal thinking never wins").

The clash is **structural, not a bug**: mean-reversion and trend-following are **opposite skews**.
Trend/convexity (Hougaard's native mode) = low win-rate, add-to-winners, fat right tail. Mean-reversion
(premium selling) = high win-rate, buy weakness, clip winners, fat LEFT tail. **You cannot force a
mean-reversion sleeve to "obey Tom" trade-by-trade without destroying its edge** — a tight stop converts
its rare big loss into frequent small losses and kills the win-rate that *was* the edge.

**Resolution — obey the doctrine at the BOOK level, not the sleeve level.** Run the mean-reversion sleeve
as the win-rate engine *and accept its negative skew*; run the convex trend sleeve beside it. The trend
sleeve's fat right tail is the **insurance** on the mean-reversion sleeve's fat left tail. The book obeys
Tom even though the sleeve does not. **This is the whole reason the book is two layers.**

**Non-negotiable — skew ≠ ruin.** Accepting negative skew does NOT mean accepting ruin. A −63% no-stop
loss at 3× leverage is *ruin*, not skew. Bound the tail — cap size, catastrophe-only stop, **no leverage
on the naked mean-reversion sleeve** — without trend-ifying it. If even a catastrophe stop kills the edge,
the answer is *less size / less leverage*, never a tighter stop.

## 5d. Invariant essence, variable factors — 以不变应万变 (Jazz, 2026-07-17)

**Anti-dogmatism clause — read this before treating anything above as a rule.** This doctrine fixes
the ESSENCE, not the tactics.

- **Invariant (以不变):** expectancy over win-rate; loss asymmetry (big when right, small when wrong);
  fade the crowd; every edge traces to a cause; skew ≠ ruin; hold conviction through noise, cut on
  cause-break. These do not change across markets.
- **Variable (应万变):** the FACTORS, thresholds, and triggers. **Different markets → different
  factors.** The right variables come from **concrete attribution analysis per market and per regime**,
  never from applying yesterday's factor set by rote. A false-breakout market needs different
  trend-confirmation than a clean trending index; a high-funding perp needs different sizing than a
  spot core; on-chain valuation (MVRV) is a factor in crypto, meaningless elsewhere.

Great traders **adapt** — they incorporate new variables as the market changes — while the core stays
fixed. So: hold the essence as law; treat every factor, threshold, and mechanical trigger as a
**hypothesis owned by per-market attribution + the refutation ledger**, subject to revision. **A rule
that survives one market is NOT presumed to survive the next — it must be re-attributed.** Dogmatism is
itself a way to lose.

## 6. What it means for the build

- **Recurring-setup registry** (next artifact): each setup a written hypothesis with a base rate
  measured over *every* historical instance, gated through DSR/PBO. Prioritize setups whose cause
  is behavioral (crowding flush/squeeze, quality-dispersion mean reversion, capitulation) — those
  are the ones that "repeat over and over."
- **Report the book's period win-rate**, not a per-trade hit rate, as the headline "% of wins" —
  and never let a marketing number tempt us toward negative-skew strategies.
- **Convex sizing is a system rule, not a vibe.** Size up confirmed conviction; keep unconfirmed
  small. Encode "big when right, small when wrong" into the sizing layer, not into discretion.

## 7. Honest cautions (anti-cargo-cult)

- Hougaard is a **discretionary, high-leverage, n=1** trader. His personal record carries heavy
  **survivorship bias** — we cannot cite it as evidence, only as hypothesis.
- His tactical habits (trading without hard stops, very large size) are **dangerous if copied
  literally**. We adopt the *structural* principles (crowd durability, loss asymmetry, convexity,
  add-to-winners, assume-wrong), never the persona or the leverage.
- Behavioral edges still require **mechanism + base rate + OOS survival** before they enter the
  book. "It's crowd psychology" is a hypothesis, not a pass. The ledger discipline stands.

---

*Extract the physics of crowd behavior, not the swagger of one trader. Build things that feel alive.*
