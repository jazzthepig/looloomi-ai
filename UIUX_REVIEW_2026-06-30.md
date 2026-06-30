# UI/UX Review — looloomi.ai — 2026-06-30

Live walkthrough (Chrome) of the app + investor page. Desktop verified directly;
mobile/H5 needs real-device testing (the dashboard didn't reflow at narrow width via
desktop emulation, and the H5 experience is a separate `MobileApp.jsx` path).

Surfaces checked: Intelligence, CIS Leaderboard, Portfolio, Trading Engine, Vault,
Protocol Intelligence (desktop) + `strategy.html` (investor).

---

## P0 — credibility / blocking (fix before any investor or agent sees it)

**1. Trading Engine shows a −94.61% blow-up publicly.**
`/app` → Trading Engine → Signal Performance displays MaxDD −94.61%, Portfolio
$5.4k from $100k base, Win Rate 0.0%, Profit Factor 0.00, cumulative −94.61% with a
chart that craters to near-zero. This is almost certainly a signal-return compounding
bug (it contradicts `/api/v1/trading/metrics` which shows ~−0.18% total). Regardless of
cause, a −94% chart on a live, investor/agent-facing tab is the single most damaging
thing on the site — it actively refutes the "track record is our proof" thesis.
→ Fix the computation OR gate the panel behind a "needs N resolved trades" state until
the number is real. Do not show a blow-up.

**2. `strategy.html` renders on a blinding white background (dark-theme text washed out).**
The investor landing has a bright/near-white ambient background with a harsh diagonal
light streak. Its text was authored for the void-black theme, so the section eyebrows
("INVESTMENT STRATEGY", "PROPRIETARY SCORING") and the regime/intro paragraphs are
near-invisible (light text on light bg). Same failure mode as the old H5 dark-bg bug.
→ Restore the void-black background (design system `#020208`); verify eyebrow + body
contrast ≥ WCAG AA.

**3. Macro Brief leaks raw/placeholder content into the UI.**
Intelligence → Macro Brief card literally starts:
`{'# CometCloud Macro Brief: Market Update 10/24/23 (Sample Date) (Note: Using current data provided) …`
— a Python dict wrapper `{'`, a stale "10/24/23 (Sample Date)" placeholder, and an
internal note, all user-facing. Looks broken and undermines the "live intelligence" claim.
→ Strip the dict wrapper + internal notes server-side; never show "(Sample Date)".

---

## P1 — important polish / consistency

**4. Portfolio tab is missing Diagnose + Risk Meter and shows a stuck loading state.**
The Portfolio tab renders only the (empty) watchlist with a persistent
"Loading CIS universe… Live prices will appear shortly." banner that never clears —
while simultaneously showing "Your watchlist is empty" (contradictory). The DiagnoseHome
conviction field and the new Risk Meter are absent: the served `dist/` is out of sync
with the source that mounts them (backend `/portfolio/risk-meter` is live, frontend isn't).
→ Clean `npm run build` + commit dist from latest source; clear the loading banner once
the universe resolves.

**5. Grade-distribution inconsistency across surfaces (same brand, contradictory story).**
- App CIS asset leaderboard: nearly every asset is **C/C+ + NEUTRAL** (RATING column is
  100% identical → dead weight, nothing to scan).
- Protocol Intelligence: nearly every protocol is **A+ / STRONG OUTPERFORM**.
- `strategy.html` leaderboard: TradFi (SPY/QQQ/XLF) at **B+ / OUTPERFORM**, while the app
  shows crypto at the top with C/NEUTRAL.
A user crossing these sees three different grading "personalities." Either the regime
compression is real (then explain it inline) or the scales need reconciling. At minimum,
when an entire RATING column is identical, collapse/annotate it instead of repeating it.

**6. Empty data panels render as zeros/dashes instead of hiding or labeling.**
- Intelligence VC strip: "0 deals (0 disclosed) · 0 RMA deals · 1800 TOTAL RAISED / 0 deals"
  — reads as broken, not empty. (Known: needs CryptoRank key.)
- Header stats: VC Rounds "—", US PMI "—".
- Vault: EST Alpha "Sharpe —" while showing +8.5%/−2.1%; HumbleBee partner card all "—".
→ Use explicit empty states ("No funding rounds in range") or hide the panel; don't show
"1800 raised / 0 deals" which is internally contradictory.

---

## P2 — minor / nice-to-have

7. Trading Engine "366 OUTCOMES: 12 resolved, 0% win rate" on tiny n — label small-sample
   stats as provisional so 0% doesn't read as a verdict.
8. Macro Brief "read more" truncation mid-word ("smart contract pr…").
9. Consider a subtle non-identical accent when a whole column is one value (RATING) so the
   eye isn't drawn to redundant repetition.

---

## What's working (keep)

- **Protocol Intelligence** — the strongest page: real grade spread (A+→B+), STRONG
  OUTPERFORM signals, LOW risk, TVL + 7D flow, clean table. This is the template.
- **Vault** — polished GP cards, score-breakdown bars, clear selection framework.
- **CIS Leaderboard** — dense but legible: pillars sparklines, 7D/30D, percentile,
  "Show all 58", tier badges.
- Consistent dark design language, typography hierarchy, and nav across the app (the
  investor page is the outlier that broke it).

---

## Top 3 to fix first
1. Kill the −94.61% blow-up on Trading Engine (P0 #1).
2. Restore void-black background on `strategy.html` (P0 #2).
3. Strip the Macro Brief raw-dict/sample-date leak (P0 #3).
