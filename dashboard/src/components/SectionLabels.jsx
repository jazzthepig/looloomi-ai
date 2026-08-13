// SectionLabels.jsx — section-header primitives shared across the platform.
// Extracted from App.jsx on 2026-08-13 (design audit, B2 split).
//
//   SectionLabel       — full section header (cyan vertical bar + label + sub + optional right-aligned stats)
//   CompactSectionLabel — nested subsection header (gold/cyan horizontal line + UPPERCASE small caps + meta)
//   SectionLoader      — Suspense fallback used by every lazy-loaded section

import { T, FONTS } from "../tokens";

/* ── SectionLabel — full section header ─────────────────────────────────── */
/* stats: [{ label, value, color }] — rendered inline right-aligned (Fortress pattern) */
export function SectionLabel({ label, sub, stats = null }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 20, paddingBottom: 14, borderBottom: "1px solid rgba(6,182,212,0.08)" }}>
      <div style={{ width: 2, height: 16, background: "rgba(6,182,212,0.65)", borderRadius: 1, flexShrink: 0 }} />
      <span style={{ fontFamily: FONTS.display, fontSize: 18, fontWeight: 600, color: T.t1, letterSpacing: "-0.01em" }}>
        {label}
      </span>
      {sub && (
        <span style={{ fontFamily: FONTS.mono, fontSize: 10, color: T.muted, letterSpacing: "0.1em", textTransform: "uppercase" }}>
          · {sub}
        </span>
      )}
      {stats && stats.length > 0 && (
        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 0 }}>
          {stats.map((s, i) => (
            <div key={i} style={{
              paddingLeft: 20, paddingRight: i < stats.length - 1 ? 20 : 0,
              borderLeft: `1px solid rgba(6,182,212,0.10)`,
              display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 1,
            }}>
              <div style={{ fontFamily: FONTS.mono, fontSize: 9, letterSpacing: "0.12em", color: T.muted, textTransform: "uppercase" }}>{s.label}</div>
              <div style={{ fontFamily: FONTS.mono, fontSize: 13, color: s.color || T.t2, letterSpacing: "-0.01em" }}>{s.value}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/* ── CompactSectionLabel — nested subsection header ────────────────────── */
/* accent: 'cyan' (default) | 'gold' (gold is the editorial / sub-section indicator) */
export function CompactSectionLabel({ label, meta, accent = "cyan" }) {
  const lineColor = accent === "gold" ? T.gold : T.cyan;
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 12, marginBottom: 16, paddingBottom: 14,
      borderBottom: `1px solid ${T.border}`,
    }}>
      <div aria-hidden="true" style={{ width: 14, height: 1, background: lineColor, opacity: 0.5 }} />
      <span style={{
        fontFamily: FONTS.display, fontSize: 11, fontWeight: 700,
        letterSpacing: "0.14em", color: T.t2, textTransform: "uppercase",
      }}>
        {label}
      </span>
      {meta && (
        <span style={{ fontSize: 9, color: T.t3, fontFamily: FONTS.mono, marginLeft: "auto", opacity: 0.65 }}>
          {meta}
        </span>
      )}
    </div>
  );
}

/* ── SectionLoader — Suspense fallback used by every lazy section ──────── */
export function SectionLoader({ label = "LOADING…" }) {
  return (
    <div style={{ padding: "48px 0", textAlign: "center" }}>
      <div style={{ color: "rgba(199,210,254,0.2)", fontFamily: FONTS.mono, fontSize: 11, letterSpacing: "0.1em" }}>
        {label}
      </div>
    </div>
  );
}
