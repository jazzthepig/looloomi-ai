/**
 * CometCloud Design Tokens
 * James Turrell × Editorial Finance
 * Dark navy / cyan-tinted — serif display + mono data
 */

export const FONTS = {
  brand:   "'Syne', system-ui, sans-serif",          // display headings — Syne 700/800
  display: "'Syne', system-ui, sans-serif",           // UI labels, nav
  body:    "'Exo 2', system-ui, sans-serif",          // body copy, descriptions
  mono:    "'JetBrains Mono', monospace",             // numbers, scores, prices
  serif:   "'Syne', system-ui, sans-serif",
};

export const T = {
  // ── Backgrounds — deep navy with cyan undertone ──────────────────────
  void:       "#060F1B",        // absolute deepest
  deep:       "#091728",        // page background
  surface:    "#0D2038",        // elevated surface / section bg
  raised:     "#112540",        // card background
  card:       "#142D4C",        // inner card
  cardHover:  "#193452",        // card hover
  overlay:    "rgba(6,15,27,0.96)",

  // ── Borders — cyan-tinted glass ──────────────────────────────────────
  border:     "rgba(56,148,210,0.10)",
  borderMd:   "rgba(56,148,210,0.18)",
  borderHi:   "rgba(56,148,210,0.30)",

  // ── Text hierarchy — 4 levels ────────────────────────────────────────
  t1:         "#EFF8FF",        // primary — ice white
  t2:         "#7AAEC8",        // secondary — blue-gray
  t3:         "#3E6680",        // muted
  t4:         "#1E3A52",        // dim / placeholder

  // Semantic aliases
  primary:    "#EFF8FF",
  secondary:  "#7AAEC8",
  muted:      "#3E6680",
  dim:        "#1E3A52",

  // ── Brand accents ────────────────────────────────────────────────────
  gold:       "#C8A84B",
  goldLt:     "#E8C96A",
  goldDim:    "rgba(200,168,75,0.12)",
  goldGlow:   "rgba(200,168,75,0.05)",

  // ── Status colors ────────────────────────────────────────────────────
  green:      "#00D98A",
  greenDim:   "rgba(0,217,138,0.10)",
  red:        "#FF3D5A",
  redDim:     "rgba(255,61,90,0.10)",
  blue:       "#4B9EFF",
  blueDim:    "rgba(75,158,255,0.10)",

  // ── UI accents ───────────────────────────────────────────────────────
  purple:     "#A78BFA",
  amber:      "#F59E0B",
  violet:     "#7C3AED",
  cyan:       "#06B6D4",
  cyanDim:    "rgba(6,182,212,0.10)",
  indigo:     "#4F46E5",
  pink:       "#EC4899",
};
