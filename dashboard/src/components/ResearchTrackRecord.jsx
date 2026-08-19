/**
 * Research Desk — held-out out-of-sample results (2026-08-19).
 *
 * SOURCE. R70 held-out OOS isolation, Minimax-C, 2026-07-22
 * (`_reports/absorb_input/r70_held_out_oos_2026-07-22_summary.json`). The file
 * carries its own discipline statement, quoted here because it is the reason
 * these numbers are worth showing at all:
 *
 *   "_oos_isolation_discipline": Forward β-adj SR computed ONLY on the held-out
 *   window. β estimated only on the in-sample period.
 *   "_honest_boundary": PIT-safe: pillar signal uses value as-of recorded date.
 *   Costs 5/10/20 bps round-trip. Weights forward-shifted.
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

/* The contiguous survivor region: pillar A, fast cadence, unsmoothed. */
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
          Held-out backtest · not a live record
        </span>
        <span style={{ fontFamily: FONTS.mono, fontSize: 11, color: T.t3 }}>
          OOS {OOS_WINDOW} · {OOS_DAYS} days · β-adjusted · PIT-safe
        </span>
      </div>

      <h2 style={{ fontFamily: FONTS.display, fontWeight: 700, fontSize: 30, letterSpacing: "-0.02em",
                   color: T.t1, margin: "0 0 6px" }}>
        Held-out out-of-sample
      </h2>
      <p style={{ fontFamily: FONTS.body, fontSize: 15, lineHeight: 1.6, color: T.t2,
                  margin: "0 0 24px", maxWidth: 660 }}>
        Seventy-two configurations were tested. Sharpe is <strong style={{ color: T.t1 }}>β-adjusted</strong> —
        it measures excess over market exposure, not the exposure itself — and it is
        computed only on a window the search never saw. Costs are re-run at each
        assumption rather than quoted gross.
      </p>

      <div style={{ display: "flex", gap: 32, flexWrap: "wrap", padding: "20px 0 22px",
                    borderTop: `1px solid ${T.border}`, borderBottom: `1px solid ${T.border}`,
                    marginBottom: 26 }}>
        <Stat label="OOS Sharpe" value="1.58" sub="β-adjusted · net of 5 bps" tone={pos(1)} />
        <Stat label="In-sample" value="1.89" sub="degradation −17%" />
        <Stat label="Net annualised" value="+14.5%" sub="after costs" tone={pos(1)} />
        <Stat label="Survived OOS" value={`${N_SURVIVED} / ${N_TESTED}`} sub="configurations" />
        <Stat label="Held-out days" value={String(OOS_DAYS)} sub="never searched" />
      </div>

      <div style={{ fontFamily: FONTS.mono, fontSize: 10, letterSpacing: "0.16em",
                    textTransform: "uppercase", color: T.t3, marginBottom: 12 }}>
        The survivors · in-sample vs held-out
      </div>
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
