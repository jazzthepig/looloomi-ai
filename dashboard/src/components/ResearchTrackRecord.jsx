/**
 * Research Desk — held-out out-of-sample results (2026-08-19).
 *
 * SOURCE. R70 held-out OOS isolation, Minimax-C, 2026-07-22
 * (`_reports/absorb_input/r70_held_out_oos_2026-07-22_summary.json`). The file
 * carries its own discipline statement, quoted here because it is the reason
 * these numbers are worth showing at all:
 *
 *   "_oos_isolation_discipline": Forward β-adj SR computed ONLY on the held-out
 *   window. β estimated only on the OOS portion (no look-back into IS).
 *   "_honest_boundary": PIT-safe: pillar signal uses value as-of recorded date.
 *   Costs 5/10/20 bps round-trip. Weights forward-shifted.
 *
 * ⚠️ AND THAT IS THE SENTENCE THIS PAGE FIRST GOT WRONG. The first version of
 * this file paraphrased it as "β estimated only on the IN-SAMPLE period" — the
 * opposite — and so published R70's 1.580 as a production figure without
 * questioning it. R71 (2026-07-23) tested exactly that: estimating β inside the
 * held-out window uses information a live book does not have at the moment it
 * acts. Same OOS net returns, four estimators:
 *
 *     β fixed from in-sample     1.083   R71: "the rigorous ship-gate test"
 *     β expanding, recursive     1.018   R71: "production-realistic"
 *     β = 0                      1.083   reference
 *     β rolling inside OOS       1.580   reference — what R70 published
 *
 * The headline is 1.08. R71 sat in _reports/ the whole time; R70 was read and
 * the next file was not — the same failure as never opening _reports/ at all,
 * one directory deeper.
 *
 * WHY THIS AND NOT A NICER CURVE. Three properties almost no published backtest
 * has, all three present here:
 *   1. β-ADJUSTED — the number is excess over market exposure. An unadjusted
 *      crypto Sharpe mostly measures having been long.
 *   2. HELD-OUT — 151 days the search never saw. In-sample and out-of-sample
 *      are shown side by side so the degradation is visible, not hidden.
 *   3. COST-LADDERED — re-run at 5/10/20 bps rather than quoted gross.
 *
 * AND THE FAILURES ARE ON THE PAGE. 17 of 72 configurations survived. Every
 * "smoothed" variant looks respectable in-sample and collapses out-of-sample —
 * that is the single most informative thing in the grid and it is the kind of
 * thing that normally never leaves an internal deck.
 *
 * WHAT IS NOT PUBLISHED: construction. No pillar definition, no signal formula,
 * no threshold. Jazz, 2026-08-12 — 挖掘的最终成果不可以免费暴露. Performance is
 * evidence an allocator can hold us to; the recipe is the asset.
 *
 * COMPLIANCE (CLAUDE.md #1, #8): no BUY/SELL/HOLD vocabulary, no forward
 * promise, no infrastructure named. Backtest labelled in the first line.
 */
import { T, FONTS } from "../tokens";

const OOS_WINDOW = "2026-01-08 → 2026-06-07";
const OOS_DAYS = 151;
const N_SURVIVED = 17;
const N_TESTED = 72;

/* S-189 (2026-08-20). Computed by `src/research/validation/deflated_sharpe.py`
   from R70's full 72-configuration grid. Bailey & López de Prado (2014).

   N is 216, not 72: R70's grid was the SURVIVOR SET of R69's 216 cells, and
   every configuration ever run against this data belongs in the trial count.
   Reporting 72 would have been the flattering choice and would still have
   failed — DSR 0.36 at N=72, 0.27 at N=216. Neither is close to 0.95.

   To pass at this dispersion the strategy would have needed an OOS Sharpe of
   roughly 4.2–4.6 annualised. That is not a near miss. */
const DSR = {
  value: "0.27",
  threshold: 0.95,
  observed: "1.58",           // the grid's own units (β estimated inside OOS)
  luckThreshold: "2.38",      // expected max under the null, N=216
  nTrialsFunnel: 216,
  gridMean: "−0.45",
};

/* The contiguous survivor region: pillar A, fast cadence, unsmoothed. */
/* R71 β-sensitivity, 2026-07-23. Same OOS net returns, four β estimators.
   R71's own words: Method 2 (IS-fixed) is "the rigorous ship-gate test";
   Method 3 (expanding) is "the production-realistic recursive estimate";
   Methods 1 and 4 are "reference / worst-case". R70 published Method 1. */
const BETA_METHODS = [
  { name: "β fixed from in-sample", sr: 1.083, role: "ship-gate test", headline: true },
  { name: "β expanding, recursive", sr: 1.018, role: "production-realistic" },
  { name: "β = 0 (unadjusted)",     sr: 1.083, role: "identical — β_IS was 0.00" },
  { name: "β rolling inside OOS",   sr: 1.580, role: "reference — uses OOS data" },
];

/* R71 method 2: `beta_value = 0.0`. The in-sample estimate came out at exactly
   zero, which is WHY methods 2 and 4 give the same number — not a coincidence,
   the same computation. It also means the β adjustment does no work at the
   headline: with β = 0 the adjusted Sharpe IS the raw Sharpe. That is a real
   property (the sleeve carried no market exposure in this window) and calling
   the figure "β-adjusted" without saying so implies an adjustment that did not
   happen. Minimax-C's INDEX row said it plainly — "β_IS=0 so M2≡M4" — and this
   page shipped before that line was absorbed. */

const SURVIVORS = [
  { cfg: "cadence 3",  bps: 5,  oos: 1.580, is: 1.894, ann: 14.47, turn: 69.7 },
  { cfg: "cadence 3",  bps: 10, oos: 1.493, is: 1.769, ann: 12.64, turn: 69.7 },
  { cfg: "cadence 3",  bps: 20, oos: 1.315, is: 1.519, ann: 8.98,  turn: 69.7 },
  { cfg: "cadence 5",  bps: 5,  oos: 1.160, is: 1.692, ann: 10.61, turn: 51.3 },
  { cfg: "cadence 5",  bps: 10, oos: 1.102, is: 1.599, ann: 9.42,  turn: 51.3 },
  { cfg: "cadence 5",  bps: 20, oos: 0.988, is: 1.413, ann: 7.05,  turn: 51.3 },
];

/* Configurations that looked fine in-sample and did not survive. Published on
   purpose — a grid with no failures is a grid that was not held out. */
const FAILURES = [
  { cfg: "cadence 10 (slower rebalance)", is: 1.965, oos: 0.101 },
  { cfg: "second pillar, cadence 5",      is: 1.477, oos: -0.365 },
  { cfg: "smoothed signal, cadence 3",    is: 0.703, oos: -1.059 },
  { cfg: "smoothed + majority, cadence 5", is: 0.280, oos: -1.231 },
];

const pos = (v) => (v >= 0 ? T.green || "#34d399" : T.red || "#f87171");

function Stat({ label, value, sub, tone }) {
  return (
    <div style={{ minWidth: 118 }}>
      <div style={{ fontFamily: FONTS.mono, fontSize: 9, letterSpacing: "0.14em",
                    textTransform: "uppercase", color: T.t3, marginBottom: 6 }}>{label}</div>
      <div style={{ fontFamily: FONTS.mono, fontSize: 24, color: tone || T.t1, lineHeight: 1 }}>{value}</div>
      {sub && <div style={{ fontFamily: FONTS.mono, fontSize: 10, color: T.t3, marginTop: 5 }}>{sub}</div>}
    </div>
  );
}

export default function ResearchTrackRecord() {
  return (
    <div style={{ maxWidth: 940 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 14, flexWrap: "wrap" }}>
        <span style={{ padding: "4px 10px", borderRadius: 5, border: `1px solid ${T.border}`,
                       fontFamily: FONTS.mono, fontSize: 10, letterSpacing: "0.14em",
                       textTransform: "uppercase", color: T.amber || T.t2 }}>
          Held-out backtest · fails the search discount · not a live record
        </span>
        <span style={{ fontFamily: FONTS.mono, fontSize: 11, color: T.t3 }}>
          OOS {OOS_WINDOW} · {OOS_DAYS} days · β-adjusted · PIT-safe
        </span>
      </div>

      <h2 style={{ fontFamily: FONTS.display, fontWeight: 700, fontSize: 30, letterSpacing: "-0.02em",
                   color: T.t1, margin: "0 0 6px" }}>
        A result that failed our own bar
      </h2>
      <p style={{ fontFamily: FONTS.body, fontSize: 15, lineHeight: 1.6, color: T.t2,
                  margin: "0 0 24px", maxWidth: 680 }}>
        This is the strongest backtest we own. It was run on a window the search
        never saw, with costs re-run at each assumption rather than quoted gross,
        and with β fixed from in-sample so the figure is one a live book could
        have produced. It still does not clear the multiple-testing discount, and
        we are showing it anyway — because what an allocator cannot get elsewhere
        is not another Sharpe ratio, it is a manager who publishes the arithmetic
        that kills one.
      </p>

      <div style={{ display: "flex", gap: 32, flexWrap: "wrap", padding: "20px 0 22px",
                    borderTop: `1px solid ${T.border}`, borderBottom: `1px solid ${T.border}`,
                    marginBottom: 26 }}>
        <Stat label="OOS Sharpe" value="1.08" sub="β_IS = 0.00 ⇒ unadjusted" tone={pos(1)} />
        <Stat label="Deflated Sharpe" value={DSR.value} sub={`fails · bar is ${DSR.threshold}`} tone={T.red || "#f87171"} />
        <Stat label="Configurations run" value={String(DSR.nTrialsFunnel)} sub="R69 grid → R70 survivors" />
        <Stat label="Survived OOS" value={`${N_SURVIVED} / ${N_TESTED}`} sub="configurations" />
        <Stat label="Held-out days" value={String(OOS_DAYS)} sub="never searched" />
      </div>

      {/* ── The finding. S-189, 2026-08-20. ─────────────────────────────────
          This page previously led with 1.08 and stopped there. The number was
          correct and the discipline behind it was real — β fixed from in-sample,
          PIT-safe, cost-laddered, failures published. It was still an
          unsupported claim, because nothing had discounted it for the SEARCH
          that produced it, and `experiment_runs.dsr` had never been populated
          once since the column was created.
          Publishing this rather than quietly removing the page: the arithmetic
          below is the thing an allocator cannot get elsewhere. */}
      <div style={{ padding: "18px 20px", borderRadius: 10, marginBottom: 28,
                    border: `1px solid ${T.red || "#f87171"}44`,
                    background: "rgba(248,113,113,0.05)", maxWidth: 720 }}>
        <div style={{ fontFamily: FONTS.mono, fontSize: 10, letterSpacing: "0.16em",
                      textTransform: "uppercase", color: T.red || "#f87171", marginBottom: 10 }}>
          This result does not clear our bar
        </div>
        <div style={{ fontFamily: FONTS.body, fontSize: 14, lineHeight: 1.65, color: T.t2 }}>
          Search {DSR.nTrialsFunnel} configurations against a market and the best
          one looks good even when none of them has any skill — you have selected
          the maximum of {DSR.nTrialsFunnel} noisy draws. The Deflated Sharpe
          Ratio prices that in. With this grid's dispersion, chance alone is
          expected to produce a best-of-set Sharpe of{" "}
          <strong style={{ color: T.t1 }}>{DSR.luckThreshold}</strong>.
          We observed <strong style={{ color: T.t1 }}>{DSR.observed}</strong>{" "}
          — <strong style={{ color: T.red || "#f87171" }}>below the level luck
          alone would be expected to reach</strong>. Deflated Sharpe comes out at{" "}
          <strong style={{ color: T.t1 }}>{DSR.value}</strong> against a
          conventional bar of {DSR.threshold}.
        </div>
        <div style={{ fontFamily: FONTS.body, fontSize: 13, lineHeight: 1.6,
                      color: T.t3, marginTop: 12 }}>
          There is a second problem the deflation cannot repair. The window below
          was genuinely held out — and then the configuration to publish was
          chosen by ranking on it. Selecting on held-out data spends the very
          property that made it held out. A clean read needs a further window
          that the choice never touched, and that window does not exist yet; it
          is being accumulated forward, dated, in public.
        </div>
        <div style={{ fontFamily: FONTS.mono, fontSize: 10, color: T.t3, marginTop: 12,
                      lineHeight: 1.7, borderTop: `1px solid ${T.border}`, paddingTop: 10 }}>
          mean Sharpe across the grid {DSR.gridMean} · {N_SURVIVED} of {N_TESTED} above zero ·
          normal moments assumed, which flatters the result — real crypto returns
          are negatively skewed and fat tailed, and both push this lower
        </div>
      </div>

      {/* R71 — the number depends on how beta is estimated, so all four are shown. */}
      <div style={{ fontFamily: FONTS.mono, fontSize: 10, letterSpacing: "0.16em",
                    textTransform: "uppercase", color: T.t3, marginBottom: 10 }}>
        How the headline moves with the β estimator
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(150px,1fr))",
                    gap: 8, marginBottom: 14 }}>
        {BETA_METHODS.map((m) => (
          <div key={m.name} style={{
            padding: "11px 10px", borderRadius: 6,
            border: `1px solid ${m.headline ? (T.cyan || T.border) : T.border}`,
            background: m.headline ? "rgba(34,211,238,0.05)" : "transparent",
          }}>
            <div style={{ fontFamily: FONTS.mono, fontSize: 17, color: pos(m.sr) }}>
              {m.sr.toFixed(2)}
            </div>
            <div style={{ fontFamily: FONTS.body, fontSize: 12, color: T.t2, marginTop: 4 }}>
              {m.name}
            </div>
            <div style={{ fontFamily: FONTS.mono, fontSize: 9, color: T.t3, marginTop: 3 }}>
              {m.role}
            </div>
          </div>
        ))}
      </div>
      <div style={{ padding: "14px 16px", borderRadius: 8, border: `1px solid ${T.border}`,
                    background: "rgba(255,255,255,0.015)", marginBottom: 30, maxWidth: 660 }}>
        <div style={{ fontFamily: FONTS.body, fontSize: 14, lineHeight: 1.6, color: T.t2 }}>
          <strong style={{ color: T.t1 }}>The headline is 1.08, not 1.58.</strong>{" "}
          The higher figure estimates β inside the held-out window, which a live
          book cannot do — at the moment it acts it knows only its own history.
          Fixing β from in-sample is what production would actually have, and it
          costs a third of the Sharpe. The spread across four estimators is shown
          because a result that moves this much with a methodological choice
          should be presented with the choice visible, not with the best number
          picked out of it.
        </div>
      </div>

      <div style={{ fontFamily: FONTS.mono, fontSize: 10, letterSpacing: "0.16em",
                    textTransform: "uppercase", color: T.t3, marginBottom: 12 }}>
        The survivors · in-sample vs held-out
      </div>
      <p style={{ fontFamily: FONTS.body, fontSize: 12, lineHeight: 1.55, color: T.t3,
                  margin: "0 0 12px", maxWidth: 660 }}>
        This table is the original grid — both its Sharpe AND its annualised
        column use β estimated inside the held-out window (the 1.58 method).
        R71 re-ran the Sharpe under four estimators but not the annualised
        figure, so no ship-gate version of that column exists to show. It is kept
        because the SHAPE is what this table is for — which settings survive and
        how they rank, unchanged by the estimator. For the level, read 1.08.
      </p>
      <div style={{ marginBottom: 12 }}>
        <div style={{ display: "flex", gap: 10, fontFamily: FONTS.mono, fontSize: 9,
                      color: T.t3, letterSpacing: "0.1em", textTransform: "uppercase",
                      paddingBottom: 7, borderBottom: `1px solid ${T.border}` }}>
          <div style={{ flex: 1 }}>Configuration</div>
          <div style={{ width: 62, textAlign: "right" }}>Cost</div>
          <div style={{ width: 68, textAlign: "right" }}>In-sample</div>
          <div style={{ width: 68, textAlign: "right" }}>Held-out</div>
          <div style={{ width: 74, textAlign: "right" }}>Net / yr</div>
        </div>
        {SURVIVORS.map((r, i) => (
          <div key={i} style={{ display: "flex", gap: 10, alignItems: "center",
                                padding: "9px 0", borderBottom: `1px solid ${T.border}`,
                                fontFamily: FONTS.mono, fontSize: 12 }}>
            <div style={{ flex: 1, color: T.t2 }}>{r.cfg}</div>
            <div style={{ width: 62, textAlign: "right", color: T.t3 }}>{r.bps} bps</div>
            <div style={{ width: 68, textAlign: "right", color: T.t3 }}>{r.is.toFixed(2)}</div>
            <div style={{ width: 68, textAlign: "right", color: pos(r.oos) }}>{r.oos.toFixed(2)}</div>
            <div style={{ width: 74, textAlign: "right", color: pos(r.ann) }}>+{r.ann.toFixed(1)}%</div>
          </div>
        ))}
      </div>
      <p style={{ fontFamily: FONTS.body, fontSize: 13, lineHeight: 1.6, color: T.t3,
                  margin: "0 0 30px", maxWidth: 660 }}>
        The survivors form one contiguous region of the grid rather than scattered
        winners. That is what an effect looks like; scattered winners are what a
        lucky draw looks like.
      </p>

      <div style={{ fontFamily: FONTS.mono, fontSize: 10, letterSpacing: "0.16em",
                    textTransform: "uppercase", color: T.t3, marginBottom: 12 }}>
        What did not survive
      </div>
      <div style={{ marginBottom: 14 }}>
        {FAILURES.map((r, i) => (
          <div key={i} style={{ display: "flex", gap: 10, alignItems: "center",
                                padding: "8px 0", borderBottom: `1px solid ${T.border}`,
                                fontFamily: FONTS.mono, fontSize: 12 }}>
            <div style={{ flex: 1, color: T.t3 }}>{r.cfg}</div>
            <div style={{ width: 84, textAlign: "right", color: T.t3 }}>IS {r.is.toFixed(2)}</div>
            <div style={{ width: 84, textAlign: "right", color: pos(r.oos) }}>
              OOS {r.oos.toFixed(2)}
            </div>
          </div>
        ))}
      </div>
      <div style={{ padding: "14px 16px", borderRadius: 8, border: `1px solid ${T.border}`,
                    background: "rgba(255,255,255,0.015)", marginBottom: 30, maxWidth: 660 }}>
        <div style={{ fontFamily: FONTS.body, fontSize: 14, lineHeight: 1.6, color: T.t2 }}>
          <strong style={{ color: T.t1 }}>Fifty-five of seventy-two configurations failed.</strong>{" "}
          Every smoothed variant looked respectable in-sample and went negative out
          of sample. We publish the failures because a grid with no failures is a
          grid that was not held out — and because which settings break tells an
          allocator more about the process than the one that worked.
        </div>
      </div>

      <div style={{ borderTop: `1px solid ${T.border}`, paddingTop: 20, maxWidth: 700 }}>
        <div style={{ fontFamily: FONTS.mono, fontSize: 10, letterSpacing: "0.16em",
                      textTransform: "uppercase", color: T.t3, marginBottom: 10 }}>
          What happens next
        </div>
        <p style={{ fontFamily: FONTS.body, fontSize: 14, lineHeight: 1.65, color: T.t2, margin: 0 }}>
          A held-out window is the strongest evidence a backtest can offer and it is
          still not a live record. The signal runs in a simulated book from here, and
          that record — including the days it is wrong — is what gets published next.
          A backtest tells you what a rule would have done; only a forward record
          tells you whether we can run it.
        </p>
      </div>

      <p style={{ fontFamily: FONTS.body, fontSize: 12, lineHeight: 1.6, color: T.t3,
                  margin: "26px 0 0", maxWidth: 700 }}>
        Backtested and hypothetical results carry no guarantee of future performance
        and benefit from hindsight in ways live trading does not. Signal construction —
        inputs, lookbacks and thresholds — is not disclosed. Nothing here is an offer,
        a solicitation, or a recommendation regarding any investment.
      </p>
    </div>
  );
}
