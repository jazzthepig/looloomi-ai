// CISContent.jsx — the CIS Engine section (cis.leaderboard route).
//
// Owns the section header + lazy-loaded leaderboard + the cross-asset
// overview + earnings calendar + Asset Radar. The leaderboard is the SOLE
// fetcher of the universe; cross-asset derives from the same array via
// onDataLoad, so the cross-asset view makes zero additional requests.
//
// Extracted from App.jsx on 2026-08-13 (design audit, B2 split).

import { useState, lazy, Suspense } from "react";
import { T } from "../tokens";
import { SectionLabel, CompactSectionLabel, SectionLoader } from "./SectionLabels";
import { CrossAssetView } from "./CrossAssetView";
import { EarningsCalendarWidget } from "./EarningsCalendarWidget";

const CISLeaderboard = lazy(() => import("./CISLeaderboard"));
const AssetRadar     = lazy(() => import("./AssetRadar"));

export function CISContent({ onUniverseLoad, onNavigate }) {
  const [cisUniverse, setCisUniverse] = useState([]);

  const handleDataLoad = (data) => {
    setCisUniverse(data);
    if (onUniverseLoad) onUniverseLoad(data);
  };

  // Derive live stats from loaded universe
  const cisStats = cisUniverse.length > 0 ? (() => {
    const scored = cisUniverse.filter(a => (a.cis_score ?? a.score ?? 0) > 0);
    const gradeA = cisUniverse.filter(a => a.grade === "A" || a.grade === "A+").length;
    const topScore = Math.max(...scored.map(a => a.cis_score ?? a.score ?? 0));
    return [
      { label: "ASSETS",  value: cisUniverse.length,               color: T.cyan  },
      { label: "GRADE A", value: gradeA,                            color: "#00D98A" },
      { label: "TOP CIS", value: scored.length ? topScore.toFixed(1) : "—", color: T.t2 },
    ];
  })() : null;

  return (
    <div style={{ maxWidth: 1400, margin: "0 auto" }}>
      {/* Section Header */}
      <SectionLabel label="CIS" sub="Intelligence Score" stats={cisStats} />

      {/* Leaderboard — lazy-loaded; owns the fetch, fires onDataLoad when done */}
      <div className="lm-card" style={{ overflow: "hidden" }}>
        <Suspense fallback={<SectionLoader label="LOADING LEADERBOARD…" />}>
          <CISLeaderboard
            onDataLoad={handleDataLoad}
            onAssetClick={onNavigate ? (sym) => onNavigate("cis.asset", sym) : null}
          />
        </Suspense>
      </div>

      {/* Cross-Asset Overview — zero additional fetches */}
      <CrossAssetView universe={cisUniverse} />

      {/* Earnings Calendar — upcoming events for US equities in CIS universe */}
      <EarningsCalendarWidget />

      {/* Links to standalone pages */}
      <div style={{
        marginTop: 32, display: "flex", gap: 12, flexWrap: "wrap",
      }}>
        <a href="/portfolio.html" style={{
          display: "inline-flex", alignItems: "center", gap: 8,
          padding: "10px 20px", borderRadius: 8, fontSize: 12, fontWeight: 600,
          fontFamily: "Syne, system-ui, sans-serif", letterSpacing: "0.04em",
          background: "rgba(6,182,212,0.08)", border: `1px solid rgba(6,182,212,0.22)`,
          color: T.cyan, textDecoration: "none",
          transition: "all .18s ease",
        }}
          onMouseEnter={e => { e.currentTarget.style.background = "rgba(6,182,212,0.14)"; e.currentTarget.style.borderColor = "rgba(6,182,212,0.4)"; }}
          onMouseLeave={e => { e.currentTarget.style.background = "rgba(6,182,212,0.08)"; e.currentTarget.style.borderColor = "rgba(6,182,212,0.22)"; }}
        >
          Portfolio Builder ↗
        </a>
        <a href="/analytics.html" style={{
          display: "inline-flex", alignItems: "center", gap: 8,
          padding: "10px 20px", borderRadius: 8, fontSize: 12, fontWeight: 600,
          fontFamily: "Syne, system-ui, sans-serif", letterSpacing: "0.04em",
          background: "rgba(107,15,204,0.08)", border: `1px solid rgba(107,15,204,0.22)`,
          color: "#9945FF", textDecoration: "none",
          transition: "all .18s ease",
        }}
          onMouseEnter={e => { e.currentTarget.style.background = "rgba(107,15,204,0.14)"; e.currentTarget.style.borderColor = "rgba(107,15,204,0.4)"; }}
          onMouseLeave={e => { e.currentTarget.style.background = "rgba(107,15,204,0.08)"; e.currentTarget.style.borderColor = "rgba(107,15,204,0.22)"; }}
        >
          Score Analytics ↗
        </a>
      </div>

      {/* Asset Radar — 30-asset deep-scan table with category filters, LAS, dev scores */}
      <div style={{ marginTop: 40 }}>
        <CompactSectionLabel
          label="Asset Radar"
          /* hardcoded "30 assets" removed 2026-08-19 — the live table renders 31.
             A count in a label that no longer tracks the thing it counts is
             worse than no count: it reads as authoritative. */
          meta="10 categories · live CG Pro"
          accent="cyan"
        />
        <Suspense fallback={<SectionLoader />}>
          <AssetRadar />
        </Suspense>
      </div>
    </div>
  );
}
