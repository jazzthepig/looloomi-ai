# CometCloud AI — UI/UX Review
*Reviewed: 2026-04-10 by Seth*

---

## Fixed This Review (already applied)

| # | Issue | Fix |
|---|-------|-----|
| 1 | `agent.jsx` LiveStats: "9,946+ assets filtered" — API returns 14 structured entries | Changed to "14 structured rejections" |
| 2 | `agent.jsx` LiveStats: "MCP tools: 6" — server has 19 | Changed to "19 available" |
| 3 | `agent.jsx` Pricing cards: no `flex-wrap`, collapses on mobile | Added `flexWrap: 'wrap'` + `minWidth: 240` to TierCard |
| 4 | `agent.jsx` Quickstart grid: `1fr 1fr` hard grid, no mobile stack | Added `agent-quickstart-grid` class + `@media (max-width:768px)` rule |
| 5 | `App.jsx` Nav: hardcoded `rgba(6,15,27,0.85)` — wrong void color | Changed to `rgba(1,8,18,0.88)` to match T.void + upgraded blur to 20px |
| 6 | `App.jsx` Section divider: off-token blue `rgba(56,148,210,...)` | Changed to `rgba(6,182,212,...)` = T.cyan values |
| 7 | `agent.jsx` Nav: added `data-agent` attr + `agent-nav-links` class for CSS targeting | Done |

---

## Needs Jazz Action (cannot touch from VM)

### P0 — Market tab still live (Q5 decision: CUT)

The market section is still rendered in `App.jsx`. Nav still shows "Market" tab. Per the Q5 decision this should reduce infra cost ~200 API calls/day.

**Mac Mini terminal:**
```bash
cd /Users/sbb/Projects/looloomi-ai
rm dashboard/src/components/MarketPage.jsx
rm dashboard/src/components/MarketDashboard.jsx
rm dashboard/src/market.jsx
rm dashboard/market.html
```

Then in `App.jsx`: remove `"market"` from SECTIONS array, remove `MarketDashboard` import and `<section id="market">` block.

In `vite.config.js`: remove `market: resolve(__dirname, 'market.html')` from rollupOptions.input.

---

## Needs Engineering (Seth/Austin)

### P1 — No shared Nav component

Every standalone page (agent.jsx, strategy.html, portfolio.jsx, analytics.jsx) has its own `<Nav>` function written from scratch. Result:

- `App.jsx` nav: "CometCloud" (mixed case, weight 600, size 18)
- `agent.jsx` nav: "COMETCLOUD AI" (all caps, weight 800, size 16)
- `strategy.html` nav: probably its own variant

Create `dashboard/src/components/SiteNav.jsx` — one component, props for `activePage` and `cta`. All pages import it. Without this, every branding or link change requires touching 5+ files.

---

### P2 — HeroContent is dead code in App.jsx

`HeroContent()` is defined (~line 618) but not rendered anywhere in the DesktopApp section layout (which goes: Market → Intelligence → CIS → Protocol → Vault → QuantGP). If it was intentionally removed from the layout, delete the function. If it should be the landing hero, add a section before "Market" or replace the market section with it (which also solves the Q5 removal cleanly).

Recommendation: with Market tab cut, slot `HeroContent` in as the first section, anchored to `#home`. This gives the platform a proper landing moment before diving into Intelligence.

---

### P2 — CISLeaderboard grade colors hardcoded

`CISLeaderboard.jsx` defines `GRADE_COLORS` with literal hex values (`#00D98A`, `#4472FF`, etc.) that duplicate `T.green` and `T.blue` from tokens.js. If tokens ever change, grades won't follow.

```js
// Replace with:
const GRADE_COLORS = {
  "A+": T.green,  A: T.green,
  "B+": T.indigo, B: T.indigo,
  "C+": T.amber,  C: T.amber,
  D:    T.red,    F: T.dim,
};
```

Note: `#4472FF` ≠ `T.indigo` (#6366f1) and ≠ `T.blue` (#2563eb) — it's a third blue that exists only in CISLeaderboard. Unify to T.indigo for B/B+ grades.

---

### P3 — Protocol / QuantGP section headers oversized on mid-range screens

The inline h2 at line ~423 uses `fontSize: 38` with `letterSpacing: "-0.03em"`. On 1024–1280px viewports this is visually heavier than the section content below it. Intelligence and CIS sections get their section headings from within their own component (more controlled). Suggest dropping Protocol/QuantGP section h2 to 28px to match agent.jsx's section heading pattern.

---

### P3 — App.jsx IntersectionObserver nav height compensation fragile

Line ~576:
```css
body > div > div:nth-child(3) { padding-top: 88px !important; }
```
This nth-child selector will silently break if the DOM gains or loses a sibling div. Replace with a `data-attr` or a classname on the sections container.

---

## Design Consistency Notes

### Typography
`tokens.js` uses Syne as `FONTS.brand` and `FONTS.display`. `CLAUDE.md` spec still says "Space Grotesk (headlines)". This divergence existed before this session — Syne is what's running in production (vision.html uses it). CLAUDE.md should be updated to reflect Syne as the current choice. No visual change needed.

### Color reference
| Usage | Current value | Should be |
|-------|--------------|-----------|
| App.jsx nav bg | ~~rgba(6,15,27,0.85)~~ → rgba(1,8,18,0.88) | T.void ✓ fixed |
| Section divider | ~~rgba(56,148,210,...)~~ → rgba(6,182,212,...) | T.cyan ✓ fixed |
| CIS B+ grade | #4472FF | T.indigo (#6366f1) — pending |

### Mobile hierarchy (Q8 compliance check)
- Intelligence page: `mobile-hidden` class used on lower-priority columns ✓
- CIS leaderboard: pillar columns have responsive hiding ✓
- Signal Feed: no explicit "show 3 max on mobile" — currently shows all signals. Q8 says max 3 with "load more". Not implemented.
- Portfolio mobile: no `useMediaQuery` limiting to top recommendation only. Q8 says "Holdings summary + top recommendation only." Not implemented.

Signal Feed and Portfolio mobile condensing are **P1 scope** — not included here since Portfolio is still being built and Signal Feed lives inside IntelligencePage.

---

## agent.jsx — Content Notes

The page is well-structured. A few copy-level issues:

1. **Methodology link in footer** → `/methodology.html` — this page doesn't exist yet. The link is fine to keep (placeholder), but add a `<!-- TODO -->` comment so it's not forgotten.

2. **"Platform" and "Intelligence" nav links both go to `/app.html`** — Intelligence should anchor to `#intelligence` section: `/app.html#intelligence` (hash routing will work if App.jsx's IntersectionObserver auto-scrolls, otherwise just the top is fine for now).

3. **Python SDK quickstart example** uses `tools=[]` with comment `# MCP injects cometcloud tools` — technically accurate for MCP-based injection but could confuse developers unfamiliar with MCP. Consider adding a one-line comment: `# Note: tools are injected automatically when MCP server is configured`.

---

*Build status: ✓ Clean (2.88s, 0 errors, 0 warnings)*
