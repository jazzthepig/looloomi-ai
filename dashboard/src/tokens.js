/**
 * CometCloud Design Tokens
 * James Turrell × 原研哉 — void as foundation, light as data
 *
 * Turrell: light is not decoration — it is the subject.
 * Hara Kenya: emptiness is not absence — it is potential.
 *
 * From: midnight navy tech
 * To:   void gallery — information revealed through light
 */

export const FONTS = {
  brand:   "'Space Grotesk', system-ui, sans-serif",     // display headings
  display: "'Space Grotesk', system-ui, sans-serif",      // UI labels, nav
  body:    "'Exo 2', system-ui, sans-serif",              // body copy
  mono:    "'JetBrains Mono', monospace",                 // numbers, scores, prices
  serif:   "'Space Grotesk', system-ui, sans-serif",
};

export const T = {
  // ── Backgrounds — true void, no blue cast ────────────────────────────
  void:       "#010104",        // absolute void — the Turrell darkness
  deep:       "#020208",        // page background — one breath from void
  surface:    "#05060f",        // card surface — barely lifted, floating
  raised:     "#08091a",        // inner card — slightly more present
  card:       "#0b0c1e",        // deepest data card
  cardHover:  "#0f1028",
  overlay:    "rgba(1,1,6,0.97)",

  // ── Borders — light film, near invisible ─────────────────────────────
  border:     "rgba(255,255,255,0.045)",   // ghost edge
  borderMd:   "rgba(255,255,255,0.075)",
  borderHi:   "rgba(180,200,230,0.14)",

  // ── Text — cool neutral light temperature (Hara: precision, no excess)
  t1:         "#edf2f7",        // primary — clean white, no blue push
  t2:         "#8da5be",        // secondary — recedes, calm
  t3:         "rgba(140,165,190,0.45)",  // subdued — like text in shadow
  t4:         "rgba(140,165,190,0.22)",  // barely perceptible

  // Semantic aliases
  primary:    "#edf2f7",
  secondary:  "#8da5be",
  muted:      "rgba(140,165,190,0.45)",
  dim:        "rgba(140,165,190,0.22)",

  // ── Turrell light palette — warm amber field / cool ice field ────────
  gold:       "#c8a86a",        // warm amber light — sunset through skyspace
  goldLt:     "#d8ba7a",
  goldDim:    "rgba(200,168,106,0.10)",
  goldGlow:   "rgba(200,168,106,0.04)",

  // ── Status — light-field feel, not alarm colors ───────────────────────
  green:      "#4cc9a0",        // sage-jade — growth signal
  greenDim:   "rgba(76,201,160,0.10)",
  red:        "#e05a72",        // deep rose — reduction signal
  redDim:     "rgba(224,90,114,0.10)",
  blue:       "#4a8fcc",        // cornflower — desaturated, calm
  blueDim:    "rgba(74,143,204,0.10)",

  // ── UI accents — void palette ────────────────────────────────────────
  indigo:     "#7080cc",        // desaturated indigo — quiet focus
  lavender:   "#8898c0",        // muted steel
  bloom:      "#b0c0d8",        // pale cool — large text
  cobalt:     "#1e2e58",
  royal:      "#2a4a80",
  amber:      "#c8a86a",
  cyan:       "#4aa0b8",        // teal, desaturated — precision indicator
  cyanDim:    "rgba(74,160,184,0.07)",
  purple:     "#7870c8",
  pink:       "#c070a0",
  violet:     "#6850b8",
};

/* ─── CIS Positioning Signal Styles — light-field edition ──────────────── */
export const SIG_STYLE = {
  "STRONG OUTPERFORM": { color: "#4cc9a0", bg: "rgba(76,201,160,0.10)", border: "rgba(76,201,160,0.22)" },
  OUTPERFORM:          { color: "#4cc9a0", bg: "rgba(76,201,160,0.07)", border: "rgba(76,201,160,0.15)" },
  NEUTRAL:             { color: "#c8a86a", bg: "rgba(200,168,106,0.08)", border: "rgba(200,168,106,0.18)" },
  UNDERPERFORM:        { color: "#e05a72", bg: "rgba(224,90,114,0.08)", border: "rgba(224,90,114,0.16)" },
  UNDERWEIGHT:         { color: "#e05a72", bg: "rgba(224,90,114,0.12)", border: "rgba(224,90,114,0.24)" },
};
export const sigStyle = (sig) => SIG_STYLE[(sig || "").toUpperCase()] || SIG_STYLE.NEUTRAL;
