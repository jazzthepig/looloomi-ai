---
name: design-system
description: CometCloud/Looloomi visual design system — James Turrell × ONDO Finance aesthetic. Use this skill when building or reviewing React components, CSS, color choices, typography, layout, animations, or any visual element. Triggers include "design", "color", "Turrell", "void black", "Space Grotesk", "ONDO", "component", "CSS", "animation", "card", "badge", "layout", "dark mode", "ambient", "typography". The void-black + ambient-cyan aesthetic is a product differentiator — maintain it strictly.
---

# CometCloud Design System — Turrell × ONDO

## Design philosophy

James Turrell's light installations: the viewer experiences pure light in a void.
ONDO Finance's UI: precision data in high-contrast dark space.

CometCloud is where these meet. The interface should feel like a scientific instrument
— every number readable at a glance, every ambient element breathing, nothing decorative
that does not serve data legibility.

**Three-word design brief: void, precision, pulse.**

---

## Color palette

### Foundation
```css
--bg-base:         #020208   /* void black — never grey-black (#111, #1a1a1a) */
--bg-surface:      rgba(5, 7, 22, 0.88)   /* card surfaces */
--bg-surface-alt:  rgba(8, 12, 35, 0.75)  /* secondary surfaces, inner cards */
--bg-overlay:      rgba(2, 2, 8, 0.95)    /* modals, drawers */
```

### Accent
```css
--cyan-primary:    #00e5ff   /* primary accent — data highlights, links */
--cyan-dim:        rgba(0, 229, 255, 0.15) /* subtle fills */
--cyan-border:     rgba(0, 229, 255, 0.12) /* card borders */
--cyan-glow:       rgba(0, 229, 255, 0.06) /* ambient glow backgrounds */
```

### Status colors
```css
--green-live:      #00ff9d   /* T1 badge, live data, positive Δ */
--amber-estimated: #f59e0b   /* T2 badge, estimated, warning */
--red-alert:       #ff4757   /* errors, negative Δ, risk */
--purple-neutral:  #a855f7   /* NEUTRAL signal, special states */
```

### Grade colors (CIS grades)
```css
--grade-aplus:  #00ff9d   /* A+ */
--grade-a:      #4ade80   /* A */
--grade-bplus:  #60a5fa   /* B+ */
--grade-b:      #818cf8   /* B */
--grade-cplus:  #f59e0b   /* C+ */
--grade-c:      #fb923c   /* C */
--grade-d:      #f87171   /* D */
--grade-f:      #ef4444   /* F */
```

### Text
```css
--text-primary:   rgba(255, 255, 255, 0.95)
--text-secondary: rgba(255, 255, 255, 0.6)
--text-tertiary:  rgba(255, 255, 255, 0.35)
--text-accent:    #00e5ff
```

---

## Typography

Three-font hierarchy — no substitutions:

| Role | Font | Weight | Usage |
|------|------|--------|-------|
| **Display / Headlines** | Space Grotesk | 600–700 | Page titles, card headers, metric values |
| **Body / Labels** | Exo 2 | 400–500 | Body text, descriptions, filter labels |
| **Data / Numbers** | JetBrains Mono | 400–600 | Scores, prices, percentages, hashes |

```css
/* Import (already in index.css) */
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=Exo+2:wght@300;400;500;600&family=JetBrains+Mono:wght@400;500;600&display=swap');

/* Usage */
.page-title    { font-family: 'Space Grotesk', sans-serif; font-weight: 700; }
.card-label    { font-family: 'Exo 2', sans-serif; font-weight: 400; }
.metric-value  { font-family: 'JetBrains Mono', monospace; font-weight: 500; }
```

### Font size scale
```css
--text-xs:  10px   /* badges, micro-labels */
--text-sm:  12px   /* secondary data, tooltips */
--text-base: 14px  /* primary body, table rows */
--text-md:  16px   /* card headers, nav items */
--text-lg:  20px   /* section headers */
--text-xl:  28px   /* page titles */
--text-2xl: 40px   /* hero metrics */
```

---

## Card system

Three card levels:

```css
/* Level 1 — outer container */
.lm-card {
  background: rgba(5, 7, 22, 0.88);
  border: 1px solid rgba(0, 229, 255, 0.12);
  border-radius: 12px;
  padding: 20px;
}

/* Level 2 — inner section within a card */
.lm-card-inner {
  background: rgba(8, 12, 35, 0.60);
  border: 1px solid rgba(0, 229, 255, 0.08);
  border-radius: 8px;
  padding: 12px 16px;
}

/* Level 3 — stat cell, metric tile */
.lm-stat-card {
  background: rgba(0, 229, 255, 0.03);
  border: 1px solid rgba(0, 229, 255, 0.10);
  border-radius: 8px;
  padding: 12px;
}
```

**Anti-pattern:** saturated navy overlays (`rgba(7, 26, 74, 0.55)`) — they look like the old theme. Use void-dark surfaces only.

---

## Turrell ambient orbs

The signature ambient light effect — floating colored orbs with `mix-blend-mode: screen`.

```jsx
/* Usage: place in the background layer of any page/section */
<div style={{
  position: 'absolute',
  width: 600,
  height: 600,
  borderRadius: '50%',
  background: 'radial-gradient(circle, rgba(0, 229, 255, 0.06) 0%, transparent 70%)',
  mixBlendMode: 'screen',
  animation: 'breathe 8s ease-in-out infinite',
  top: '10%',
  left: '60%',
  pointerEvents: 'none',
  zIndex: 0,
}} />

/* CSS animation */
@keyframes breathe {
  0%, 100% { opacity: 0.4; transform: scale(1); }
  50%       { opacity: 0.8; transform: scale(1.08); }
}
```

**Rules:**
- Orbs are always `position: absolute`, `zIndex: 0`, `pointerEvents: none`
- Maximum 2 orbs per page section
- Colors: cyan (`#00e5ff`), purple (`#a855f7`), or gold (`#f59e0b`) — at ≤8% opacity
- Breathe animation: 6–10s cycle, `ease-in-out`, never jarring

---

## Badges

```jsx
/* Data tier badges */
<span className="badge-t1">CIS PRO · LOCAL ENGINE</span>   /* green */
<span className="badge-t2">CIS MARKET · ESTIMATED</span>   /* amber */

/* Signal badges */
<span className="signal-strong-outperform">STRONG OUTPERFORM</span>  /* bright cyan */
<span className="signal-outperform">OUTPERFORM</span>                /* cyan */
<span className="signal-neutral">NEUTRAL</span>                      /* purple */
<span className="signal-underperform">UNDERPERFORM</span>           /* amber */
<span className="signal-underweight">UNDERWEIGHT</span>             /* red */
```

Badge rules:
- Text: 9–10px, Exo 2, letter-spacing: 0.08em, uppercase
- Border radius: 4px
- No filled backgrounds for data badges — use `border + color` only
- Signal badges: filled background at 15% opacity of their signal color

---

## Layout structure

```
┌─────────────────────────────────────────────────┐
│  Sidebar (60px collapsed / 220px expanded)      │
│  ─────  ───────────────────────────────────     │
│         ┌──────────── Main content ──────────┐  │
│         │  Header bar (40px, sticky)         │  │
│         │  ─────────────────────────────────  │  │
│         │  Content area (scrollable)          │  │
│         │    Page header                     │  │
│         │    Stats strip                     │  │
│         │    Primary card(s)                 │  │
│         └────────────────────────────────────┘  │
└─────────────────────────────────────────────────┘
```

- Sidebar: `#020208` background, `rgba(0, 229, 255, 0.1)` right border
- Content bg: `#020208` (same as void base — no visible background change)
- Max content width: none (fills remaining space)
- Gutter: 20–24px padding on content area

---

## Data tables

```jsx
/* Table conventions */
<table className="lm-table">
  {/* Headers: Exo 2, 10px, text-tertiary, uppercase, letter-spacing */}
  {/* Data cells: 12–13px, JetBrains Mono for numbers, Exo 2 for names */}
  {/* Row hover: rgba(0, 229, 255, 0.04) background */}
  {/* Borders: 1px solid rgba(255,255,255,0.05) between rows */}
</table>
```

Numbers always right-aligned. Labels/names always left-aligned. Grades center-aligned.

---

## Animation rules

- Use CSS transitions for hover states (100–150ms ease)
- Loading skeletons: `background: linear-gradient(90deg, rgba(0,229,255,0.04) 25%, rgba(0,229,255,0.08) 50%, rgba(0,229,255,0.04) 75%)` with shimmer animation
- No bounce animations — the platform should feel precise, not playful
- No page transitions longer than 200ms

---

## Anti-patterns (what NOT to do)

- ❌ Grey-black background (`#111`, `#1a1a1a`) — use `#020208`
- ❌ Saturated navy cards (`rgba(7,26,74,0.55)`) — use void-dark surfaces
- ❌ White backgrounds for any component
- ❌ Red/green for CIS signals (confuses with compliance traffic-light thinking)
- ❌ System font (`-apple-system`, `Arial`) — always load Space Grotesk + Exo 2
- ❌ Shadow/drop-shadow for depth — use border + background opacity instead
- ❌ Any emoji in UI (loading states, badges, status indicators)
- ❌ Rounded corners > 12px on cards (gets puffy)
- ❌ More than 2 Turrell orbs per section

---

## References

- `references/tokens.css` — full CSS custom property definitions
- `dashboard/src/index.css` — actual implementation (source of truth)
- `dashboard/src/components/CISLeaderboard.jsx` — canonical card + table pattern
