/**
 * CometCloud Design Tokens
 * Vision palette — midnight navy + royal blue + indigo + bloom
 * Matches vision.html exactly
 */

export const FONTS = {
  brand:   "'Syne', system-ui, sans-serif",          // display headings — Syne 700/800
  display: "'Syne', system-ui, sans-serif",           // UI labels, nav
  body:    "'Exo 2', system-ui, sans-serif",          // body copy, descriptions
  mono:    "'JetBrains Mono', monospace",             // numbers, scores, prices
  serif:   "'Syne', system-ui, sans-serif",
};

export const T = {
  // ── Backgrounds — midnight navy (vision.html exact) ──────────────────
  void:       "#020208",        // absolute void — page base
  deep:       "#020208",        // page background (Turrell × ONDO void-black)
  surface:    "#06091a",        // card / elevated surface
  raised:     "#0a1030",        // inner card raised
  card:       "#0d1438",        // deepest card
  cardHover:  "#101840",
  overlay:    "rgba(1,8,18,0.96)",

  // ── Borders — royal blue / indigo tint ───────────────────────────────
  border:     "rgba(37,99,235,0.14)",
  borderMd:   "rgba(37,99,235,0.22)",
  borderHi:   "rgba(99,102,241,0.32)",

  // ── Text hierarchy — vision palette ──────────────────────────────────
  // WCAG AA rationale (2026-08-13, design audit): body text (font-size ≤ 14px, non-bold)
  // requires 4.5:1 contrast on the deep navy base (#030f2a). 0.45 opacity on bloom
  // (rgba(199,210,254,0.45)) measured ~3.7:1 — below AA for body text. 0.65 measures
  // ~6.3:1, comfortably above AA. T.dim (0.20) stays — it is decorative-only.
  t1:         "#f0f4ff",        // primary — ice white (vision --white)
  t2:         "#c7d2fe",        // secondary — bloom lavender
  t3:         "rgba(199,210,254,0.65)", // muted (vision --muted, WCAG AA compliant)
  t4:         "rgba(199,210,254,0.20)", // dim — decorative only, do NOT use for body text

  // Semantic aliases
  primary:    "#f0f4ff",
  secondary:  "#c7d2fe",
  muted:      "rgba(199,210,254,0.65)",  // alias of t3 — WCAG AA compliant
  dim:        "rgba(199,210,254,0.20)",

  // ── Brand accents ────────────────────────────────────────────────────
  gold:       "#d4a843",        // vision --gold
  goldLt:     "#e8c060",
  goldDim:    "rgba(212,168,67,0.12)",
  goldGlow:   "rgba(212,168,67,0.05)",

  // ── Status colors ────────────────────────────────────────────────────
  green:      "#00D98A",
  greenDim:   "rgba(0,217,138,0.10)",
  red:        "#FF3D5A",
  redDim:     "rgba(255,61,90,0.10)",
  blue:       "#2563eb",        // vision --royal
  blueDim:    "rgba(37,99,235,0.10)",

  // ── UI accents — vision palette ──────────────────────────────────────
  indigo:     "#6366f1",        // vision --indigo
  lavender:   "#818cf8",        // vision --lavender
  bloom:      "#c7d2fe",        // vision --bloom
  cobalt:     "#1e3a8a",        // vision --cobalt
  royal:      "#2563eb",        // vision --royal
  amber:      "#f59e0b",        // vision --amber
  cyan:       "#06b6d4",        // vision --cyan
  cyanDim:    "rgba(6,182,212,0.08)",
  purple:     "#818cf8",
  pink:       "#EC4899",
  violet:     "#7C3AED",
};

/* ─── CIS Positioning Signal Styles — shared across all components ─────── */
export const SIG_STYLE = {
  "STRONG OUTPERFORM": { color: "#00D98A", bg: "rgba(0,217,138,0.14)", border: "rgba(0,217,138,0.30)" },
  OUTPERFORM:          { color: "#00D98A", bg: "rgba(0,217,138,0.09)", border: "rgba(0,217,138,0.18)" },
  NEUTRAL:             { color: "#d4a843", bg: "rgba(212,168,67,0.09)", border: "rgba(212,168,67,0.20)" },
  UNDERPERFORM:        { color: "#FF3D5A", bg: "rgba(255,61,90,0.09)", border: "rgba(255,61,90,0.18)" },
  UNDERWEIGHT:         { color: "#FF3D5A", bg: "rgba(255,61,90,0.14)", border: "rgba(255,61,90,0.28)" },
};
export const sigStyle = (sig) => SIG_STYLE[(sig || "").toUpperCase()] || SIG_STYLE.NEUTRAL;
