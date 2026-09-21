// safeFormat.js — front-end formatters that NEVER collapse null/undefined to 0.
//
// S-262 family discipline: "拿不到被渲染成合理数字" is the failure mode the
// system has hit 11+ times across 7 files (S-395/S-395b + S-396 audit 2026-09-21).
// The rule: when the upstream data is missing/null/undefined, render "—".
// When the upstream gives a real number — including 0 — render it as-is.
//
// Quick reference (most common mistake → fix):
//   `x || 0`            on a percentage  → DON'T. Use `fmtPct(x)` instead.
//   `x ?? 0`            on a percentage  → DON'T. Same reason.
//   `x === 0` as noData proxy            → DON'T. Real zero and missing are different.
//   `0.0` hardcoded    when data is unavailable → DON'T. Use null at the source.
//
// Each helper below returns the formatted string (never throws, never renders
// "NaN" — defensive by construction).

/** True for null, undefined, NaN. NOT true for 0 — 0 is a real number. */
export const isMissing = (v) =>
  v === null || v === undefined || (typeof v === "number" && Number.isNaN(v));

/** Signed percent with one decimal. null/undefined/NaN → "—". */
export const fmtPct = (v, digits = 1) => {
  if (isMissing(v)) return "—";
  if (typeof v !== "number") return "—";
  const sign = v > 0 ? "+" : (v < 0 ? "" : "");
  return `${sign}${v.toFixed(digits)}%`;
};

/** Plain number with K/M/B suffix. null → "—". */
export const fmtNum = (v) => {
  if (isMissing(v)) return "—";
  if (typeof v !== "number") return "—";
  const abs = Math.abs(v);
  if (abs >= 1e9) return `${(v / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `${(v / 1e6).toFixed(2)}M`;
  if (abs >= 1e3) return `${(v / 1e3).toFixed(1)}K`;
  return String(v);
};

/** Dollar-formatted big number ("$1.5B" / "$320M" / "$—"). null → "$—". */
export const fmtDollar = (v) => {
  if (isMissing(v)) return "—";
  if (typeof v !== "number") return "—";
  const abs = Math.abs(v);
  if (abs >= 1e9) return `$${(v / 1e9).toFixed(1)}B`;
  if (abs >= 1e6) return `$${(v / 1e6).toFixed(0)}M`;
  if (abs >= 1e3) return `$${(v / 1e3).toFixed(1)}K`;
  return `$${v.toFixed(0)}`;
};

/** Back-compat alias used by SectorHeatmap fmtB; same null-safe rules. */
export const fmtB = (v) => {
  if (isMissing(v)) return "—";
  if (typeof v !== "number") return "—";
  if (v > 1e7) return `$${(v / 1e9).toFixed(1)}B`;
  if (v > 0)   return `$${(v / 1e6).toFixed(0)}M`;
  return "—";  // explicit 0 also renders "—" — this category doesn't track size
};

/** Heatmap change formatter: same as fmtPct but explicit "—" for null. */
export const fmtChg = (v) => {
  if (isMissing(v)) return null;  // caller renders "—" or "No data" depending on TVL
  if (typeof v !== "number") return null;
  if (Object.is(v, -0)) return 0;
  if (Math.abs(v) < 0.05) return 0;
  return v;
};

/** Color guard for a percentage: returns "up"/"down"/undefined — never coerces null to 0. */
export const directionOf = (v) => {
  if (isMissing(v)) return undefined;
  if (v > 0)  return "up";
  if (v < 0)  return "down";
  return "flat";
};
