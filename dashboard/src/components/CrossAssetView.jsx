// CrossAssetView.jsx — class-grouped summary of the CIS universe, rendered
// from the same data CISLeaderboard already loaded (zero additional fetches).
// Extracted from App.jsx on 2026-08-13 (design audit, B2 split).

import { T, FONTS } from "../tokens";
import { CompactSectionLabel } from "./SectionLabels";

/* ── Cross-Asset Class Colors (mirrors CISLeaderboard) ─────────────────── */
const CA_COLORS = {
  L1:           { bg: "rgba(0,200,224,.08)",    text: "#00C8E0" },
  L2:           { bg: "rgba(107,15,204,.10)",   text: "#9945FF" },
  DeFi:         { bg: "rgba(68,114,255,.12)",   text: "#4472FF" },
  RWA:          { bg: "rgba(232,160,0,.12)",    text: "#E8A000" },
  Infrastructure:{ bg: "rgba(0,217,138,.10)",   text: "#00D98A" },
  Oracle:       { bg: "rgba(167,139,250,.10)",  text: "#A78BFA" },
  Memecoin:     { bg: "rgba(255,16,96,.10)",    text: "#FF1060" },
  AI:           { bg: "rgba(255,107,0,.10)",    text: "#FF6B00" },
  "US Equity":  { bg: "rgba(68,114,255,.10)",   text: "#4B9EFF" },
  "US Bond":    { bg: "rgba(245,158,11,.10)",   text: "#F59E0B" },
  Commodity:    { bg: "rgba(200,168,75,.12)",   text: "#C8A84B" },
};

const GRADE_COLORS_CA = {
  "A+": T.green,  A: T.green,
  "B+": T.indigo, B: T.indigo,
  "C+": T.amber,  C: T.amber,
  D: T.red, F: T.dim,
};

const CLASS_ORDER = [
  "L1", "L2", "DeFi", "RWA", "Infrastructure", "Oracle",
  "US Equity", "US Bond", "Commodity", "Memecoin", "AI",
];

/* ── Cross-Asset View Component ─────────────────────────────────────────── */
/* Receives universe array from parent — no independent fetch */
export function CrossAssetView({ universe = [] }) {
  if (!universe.length) return null;

  // Group by asset_class
  const classMap = {};
  for (const asset of universe) {
    const cls = asset.asset_class || "Other";
    if (!classMap[cls]) classMap[cls] = [];
    classMap[cls].push(asset);
  }

  const classes = CLASS_ORDER.filter(c => classMap[c]);

  return (
    <div style={{ marginTop: 40 }}>
      <CompactSectionLabel
        label="Cross-Asset Overview"
        meta={`${classes.length} classes · ${universe.length} assets`}
        accent="gold"
      />

      {/* Class cards grid */}
      <div style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))",
        gap: 12,
      }}>
        {classes.map(cls => {
          const assets   = [...classMap[cls]].sort((a, b) => (b.cis_score || 0) - (a.cis_score || 0));
          const scores   = assets.map(a => a.cis_score).filter(v => v != null);
          const avgScore = scores.length ? scores.reduce((a, b) => a + b, 0) / scores.length : 0;
          const topAsset = assets[0];
          const clr      = CA_COLORS[cls] || { bg: "rgba(255,255,255,0.04)", text: "#6B7280" };

          // Grade distribution
          const gradeDist = { A: 0, B: 0, C: 0, D: 0 };
          for (const a of assets) {
            const g = a.grade || "F";
            if (g.startsWith("A"))      gradeDist.A++;
            else if (g.startsWith("B")) gradeDist.B++;
            else if (g.startsWith("C")) gradeDist.C++;
            else                         gradeDist.D++;
          }

          return (
            <div key={cls} className="lm-card" style={{
              padding: "16px 18px",
              borderTop: `2px solid ${clr.text}40`,
            }}>
              {/* Class badge + count */}
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
                <span style={{
                  fontFamily: FONTS.display, fontSize: 9, fontWeight: 700,
                  letterSpacing: "0.1em", padding: "3px 8px", borderRadius: 3,
                  background: clr.bg, color: clr.text, border: `1px solid ${clr.text}30`,
                }}>
                  {cls.toUpperCase()}
                </span>
                <span style={{ fontSize: 9, color: T.t3, fontFamily: FONTS.mono }}>
                  {assets.length} asset{assets.length > 1 ? "s" : ""}
                </span>
              </div>

              {/* Avg score */}
              <div style={{ display: "flex", alignItems: "baseline", gap: 6, marginBottom: 10 }}>
                <span style={{
                  fontFamily: FONTS.mono, fontSize: 30, fontWeight: 400, lineHeight: 1,
                  color: avgScore >= 70 ? T.green : avgScore >= 50 ? T.blue : T.amber,
                }}>
                  {avgScore.toFixed(1)}
                </span>
                <span style={{ fontSize: 9, color: T.t3, fontFamily: FONTS.mono }}>avg CIS</span>
              </div>

              {/* Top asset */}
              {topAsset && (
                <div style={{
                  display: "flex", alignItems: "center", justifyContent: "space-between",
                  marginBottom: 12, paddingBottom: 10, borderBottom: `1px solid ${T.border}`,
                }}>
                  <div>
                    <div style={{ fontSize: 11, fontWeight: 700, fontFamily: FONTS.display, color: T.t1 }}>
                      {topAsset.name || topAsset.symbol}
                    </div>
                    <div style={{ fontSize: 9, color: T.t3, fontFamily: FONTS.mono, marginTop: 1 }}>
                      Top asset · {topAsset.cis_score?.toFixed(1)}
                    </div>
                  </div>
                  <span style={{
                    width: 26, height: 26, borderRadius: "50%", display: "flex",
                    alignItems: "center", justifyContent: "center",
                    background: `${GRADE_COLORS_CA[topAsset.grade] || "#888"}20`,
                    color: GRADE_COLORS_CA[topAsset.grade] || "#888",
                    border: `1px solid ${GRADE_COLORS_CA[topAsset.grade] || "#888"}40`,
                    fontSize: 11, fontWeight: 700, fontFamily: FONTS.mono,
                  }}>
                    {topAsset.grade}
                  </span>
                </div>
              )}

              {/* Grade distribution bar */}
              <div style={{ display: "flex", gap: 3 }}>
                {[
                  { key: "A", color: T.green },
                  { key: "B", color: T.indigo },
                  { key: "C", color: T.amber },
                  { key: "D", color: T.red },
                ].map(({ key, color }) => {
                  const count = gradeDist[key];
                  if (!count) return null;
                  return (
                    <div key={key} style={{
                      flex: count, height: 3, borderRadius: 2, background: color, opacity: 0.7,
                      minWidth: 4,
                    }} title={`${key}: ${count}`} />
                  );
                })}
              </div>
              <div style={{ display: "flex", gap: 10, marginTop: 6 }}>
                {Object.entries(gradeDist).filter(([, v]) => v > 0).map(([g, v]) => (
                  <span key={g} style={{ fontSize: 8, fontFamily: FONTS.mono, color: GRADE_COLORS_CA[g] || T.t3 }}>
                    {g}:{v}
                  </span>
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
