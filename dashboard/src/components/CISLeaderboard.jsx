import { useState, useEffect, useCallback } from "react";
import { T, FONTS } from "../tokens";

const GRADE_COLORS = {
  "A+": "#00D98A",
  A: "#00D98A",
  "B+": "#4472FF",
  B: "#4472FF",
  "C+": "#E8A000",
  C: "#E8A000",
  D: "#FF2D55",
  F: "#888888",
};

const GRADE_LABELS = {
  A: "Priority Allocation",
  B: "Qualified",
  C: "Watchlist",
  D: "Avoid",
  F: "Eliminated",
};

const ASSET_CLASS_COLORS = {
  RWA: { bg: "rgba(232,160,0,.12)", text: "#E8A000" },
  DeFi: { bg: "rgba(68,114,255,.12)", text: "#4472FF" },
  L1: { bg: "rgba(0,200,224,.08)", text: "#00C8E0" },
  L2: { bg: "rgba(107,15,204,.10)", text: "#9945FF" },
  Infrastructure: { bg: "rgba(0,217,138,.10)", text: "#00D98A" },
  Oracle: { bg: "rgba(167,139,250,.10)", text: "#A78BFA" },
  Memecoin: { bg: "rgba(255,16,96,.10)", text: "#FF1060" },
  AI: { bg: "rgba(255,16,96,.10)", text: "#FF1060" },
};

const API_BASE = "/api/v1";

// Pillar definitions with weights
const PILLAR_DEFS = [
  { key: "F", name: "Fundamental", color: "#4472FF", weight: 30, desc: "Token economics, protocol revenue, team credibility, audit status" },
  { key: "M", name: "Market Structure", color: "#A78BFA", weight: 25, desc: "Liquidity depth, price stability, derivatives market health" },
  { key: "O", name: "On-Chain Health", color: "#00D98A", weight: 20, desc: "Active addresses, transaction velocity, whale concentration" },
  { key: "S", name: "Sentiment", color: "#F59E0B", weight: 15, desc: "Developer activity, social momentum, VC flow, narrative strength" },
  { key: "alpha", name: "Alpha Independence", color: "#FF2D55", weight: 10, desc: "BTC correlation (β), genuine uncorrelated return potential" },
];

// Grade definitions
const GRADE_DEFINITIONS = [
  { grade: "A", minScore: 85, label: "Institutional Quality", desc: "Meets institutional allocation standards across all pillars", borderColor: "#00D98A" },
  { grade: "B", minScore: 70, label: "Investment Grade", desc: "Strong fundamentals with selective risk factors", borderColor: "#4472FF" },
  { grade: "C", minScore: 55, label: "Speculative", desc: "Elevated risk, requires position sizing discipline", borderColor: "#F59E0B" },
  { grade: "D", minScore: 0, label: "High Risk", desc: "Significant structural concerns, not recommended for institutional allocation", borderColor: "#FF2D55" },
];

// Responsive styles
const CIS_CSS = `
  @media (max-width: 1100px) {
    .cis-layout { grid-template-columns: 1fr !important; }
    .cis-grade-summary { grid-template-columns: repeat(2, 1fr) !important; }
    .cis-filters { flex-wrap: wrap !important; }
    .cis-pillar-legend-top { display: none !important; }
  }
  @media (max-width: 768px) {
    .cis-grade-summary { grid-template-columns: 1fr 1fr !important; gap: 6px !important; }
    .cis-grade-card { padding: 10px 12px !important; }
    .cis-grade-card .grade-letter { font-size: 18px !important; }
    .cis-grade-card .grade-count { font-size: 22px !important; }
    .cis-grade-card .grade-label { font-size: 8px !important; }
    .cis-filters { gap: 4px !important; }
    .cis-filter-btn { padding: 3px 8px !important; font-size: 8px !important; }
    .cis-filter-divider { display: none !important; }
    .cis-table-header, .cis-table-row { grid-template-columns: 30px 1fr 60px 40px !important; gap: 8px !important; padding: 10px 12px !important; }
    .cis-detail-panel { position: static !important; margin-top: 16px !important; }
    .cis-score { font-size: 32px !important; }
    .cis-pillar-legend-bottom { gap: 12px !important; }
    .cis-pillar-legend-bottom span { font-size: 8px !important; }
  }
  @media (max-width: 480px) {
    .cis-grade-summary { grid-template-columns: 1fr 1fr !important; }
    .cis-layout { gap: 12px !important; }
    .cis-grade-definitions { grid-template-columns: 1fr 1fr !important; }
  }
  @media (max-width: 1100px) {
    .cis-grade-definitions { grid-template-columns: repeat(2, 1fr) !important; }
  }
`;

export default function CISLeaderboard({ minimal = false, externalData = null }) {
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [gradeFilter, setGradeFilter] = useState("All");
  const [classFilter, setClassFilter] = useState("All");
  const [selectedAsset, setSelectedAsset] = useState(null);
  const [sortBy, setSortBy] = useState("rank");
  const [dataSource, setDataSource] = useState("loading");

  // Fetch data from API if not provided externally
  useEffect(() => {
    if (externalData && externalData.universe) {
      // Use external data (from parent component)
      const mapped = externalData.universe.map((asset, idx) => ({
        rank: idx + 1,
        asset_id: asset.symbol.toLowerCase(),
        asset_name: asset.name,
        asset_class: asset.asset_class,
        total_score: asset.cis_score,
        grade: asset.grade,
        pillars: { F: asset.f, M: asset.m, O: asset.r, S: asset.s, alpha: asset.a },
        description: "",
      }));
      setData(mapped);
      setSelectedAsset(mapped[0] || null);
      setDataSource("live");
      return;
    }

    // Fetch from API
    const fetchData = async () => {
      setLoading(true);
      setError(null);
      try {
        const response = await fetch("/api/v1/cis/universe");
        if (!response.ok) throw new Error(`API error: ${response.status}`);
        const json = await response.json();
        if (json.universe && json.universe.length > 0) {
          const mapped = json.universe.map((asset, idx) => ({
            rank: idx + 1,
            asset_id: asset.symbol.toLowerCase(),
            asset_name: asset.name,
            asset_class: asset.asset_class,
            total_score: asset.cis_score,
            grade: asset.grade,
            pillars: { F: asset.f, M: asset.m, O: asset.r, S: asset.s, alpha: asset.a },
            description: "",
          }));
          setData(mapped);
          setSelectedAsset(mapped[0]);
          setDataSource(json.data_source || "coingecko+defillama");
        } else {
          throw new Error("No data returned");
        }
      } catch (e) {
        console.error("CISLeaderboard fetch error:", e);
        setError(e.message);
        setData([]);
      } finally {
        setLoading(false);
      }
    };

    fetchData();
  }, [externalData]);

  // Inject responsive CSS
  useEffect(() => {
    const id = "cis-responsive-css";
    if (!document.getElementById(id)) {
      const s = document.createElement("style");
      s.id = id;
      s.textContent = CIS_CSS;
      document.head.appendChild(s);
    }
  }, []);

  const GRADE_TABS = ["All", "A", "B", "C", "D"];
  const CLASS_TABS = ["All", "RWA", "L1", "L2", "DeFi", "Infrastructure", "Oracle", "Memecoin"];

  // Filter data
  const filtered = data.filter(item => {
    const gradeMatch = gradeFilter === "All" || item.grade === gradeFilter;
    const classMatch = classFilter === "All" || item.asset_class === classFilter;
    return gradeMatch && classMatch;
  });

  // Grade summary — includes A+/B+/C+ variants
  const gradeSummary = {
    A: data.filter(i => i.grade === "A" || i.grade === "A+").length,
    B: data.filter(i => i.grade === "B" || i.grade === "B+").length,
    C: data.filter(i => i.grade === "C" || i.grade === "C+").length,
    D: data.filter(i => i.grade === "D" || i.grade === "F").length,
  };

  // Handle asset selection
  const handleSelectAsset = (asset) => {
    setSelectedAsset(asset);
  };

  // Pillar bar width
  const PillarBar = ({ value, color = T.blue }) => (
    <div style={{
      width: 60, height: 6, background: T.border, borderRadius: 3,
      overflow: "hidden", display: "inline-block", marginRight: 4
    }}>
      <div style={{
        width: `${value}%`, height: "100%", background: color,
        borderRadius: 3, transition: "width 0.3s ease"
      }} />
    </div>
  );

  // Expanded row details
  const ExpandedDetail = ({ item }) => (
    <div style={{
      padding: "16px 20px", background: T.deep, borderTop: `1px solid ${T.border}`,
      animation: "fadeUp .2s ease"
    }}>
      <div style={{
        display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: 16,
        marginBottom: 16
      }}>
        {[
          { key: "F", label: "Fundamental", desc: "Team/Product/Tokenomics" },
          { key: "M", label: "Market", desc: "Liquidity/Volume/Spread" },
          { key: "O", label: "On-Chain", desc: "Real Activity/Holder Behavior" },
          { key: "S", label: "Sentiment", desc: "Social/KOL/Community" },
          { key: "alpha", label: "Alpha", desc: "BTC Independence/Factor Exposure" },
        ].map(p => (
          <div key={p.key}>
            <div style={{ fontSize: 10, color: T.muted, marginBottom: 4, fontFamily: FONTS.body }}>
              {p.label} · {item.pillars[p.key]}
            </div>
            <PillarBar value={item.pillars[p.key]} color={GRADE_COLORS[item.grade]} />
            <div style={{ fontSize: 9, color: T.secondary, marginTop: 4, fontFamily: FONTS.body }}>
              {p.desc}
            </div>
          </div>
        ))}
      </div>
      <div style={{ display: "flex", gap: 8 }}>
        {Object.entries(item.pillars).map(([k, v]) => (
          <span key={k} style={{
            fontSize: 10, fontFamily: FONTS.mono, color: T.secondary,
            background: T.surface, padding: "2px 6px", borderRadius: 3
          }}>
            {k}: {v}
          </span>
        ))}
      </div>
    </div>
  );

  // Minimal mode: just table without filters
  if (minimal) {
    return (
      <div>
        <div style={{
          display: "grid", gridTemplateColumns: "40px 1.5fr 70px 50px",
          gap: 12, padding: "8px 16px", borderBottom: `1px solid ${T.border}`,
          fontSize: 10, color: T.muted, letterSpacing: "0.1em",
          textTransform: "uppercase", fontFamily: FONTS.body
        }}>
          <span>#</span>
          <span>Asset</span>
          <span style={{ textAlign: "right" }}>CIS</span>
          <span>Grade</span>
        </div>
        {filtered.map((item) => (
          <div key={item.asset_id}
            onClick={() => handleSelectAsset(item)}
            style={{
              display: "grid", gridTemplateColumns: "40px 1.5fr 70px 50px",
              gap: 12, padding: "12px 16px", borderBottom: `1px solid ${T.border}`,
              alignItems: "center", cursor: "pointer",
              background: selectedAsset?.asset_id === item.asset_id ? T.deep : "transparent",
              transition: "background 0.15s ease"
            }}
          >
            <span style={{ fontSize: 12, fontFamily: FONTS.mono, color: T.muted }}>{item.rank}</span>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{ fontSize: 13, fontWeight: 600, fontFamily: FONTS.display, color: T.primary }}>{item.asset_name}</span>
            </div>
            <div style={{ textAlign: "right" }}>
              <span style={{ fontSize: 16, fontWeight: 700, fontFamily: FONTS.mono, color: GRADE_COLORS[item.grade] }}>{item.total_score.toFixed(1)}</span>
            </div>
            <span style={{
              width: 24, height: 24, borderRadius: "50%", display: "flex",
              alignItems: "center", justifyContent: "center",
              background: `${GRADE_COLORS[item.grade]}20`,
              fontSize: 12, fontWeight: 700, fontFamily: FONTS.mono,
              color: GRADE_COLORS[item.grade], border: `1px solid ${GRADE_COLORS[item.grade]}40`
            }}>{item.grade}</span>
          </div>
        ))}
      </div>
    );
  }

  // Loading/Error state
  if (loading) {
    return (
      <div style={{ padding: 40, textAlign: "center", color: T.secondary }}>
        <div style={{ fontSize: 14 }}>Loading CIS data...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div style={{ padding: 20, textAlign: "center" }}>
        <div style={{ color: T.red, marginBottom: 12 }}>Failed to load: {error}</div>
        <button onClick={() => window.location.reload()} style={{
          padding: "8px 16px", background: "rgba(239,68,68,0.2)", border: "1px solid #ef4444",
          borderRadius: 4, color: "#ef4444", cursor: "pointer"
        }}>Retry</button>
      </div>
    );
  }

  if (!data.length) {
    return (
      <div style={{ padding: 40, textAlign: "center", color: T.secondary }}>
        No CIS data available
      </div>
    );
  }

  // Full mode with 2-column layout
  return (
    <div>
      {/* Data Source Badge */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
        <span style={{
          fontSize: 10, padding: "2px 8px", borderRadius: 4,
          background: dataSource === "live" ? "rgba(34,197,94,0.2)" : "rgba(251,191,36,0.2)",
          color: dataSource === "live" ? "#22c55e" : "#fbbf24"
        }}>
          {dataSource === "loading" ? "LOADING" : dataSource.toUpperCase()}
        </span>
        <span style={{ fontSize: 10, color: T.muted }}>
          CIS v4.0 · {data.length} assets
        </span>
      </div>
      {/* Grade Summary Cards */}
      <div className="cis-grade-summary" style={{
        display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 8, marginBottom: 18
      }}>
        {[
          { grade: "A", label: "CIS Score ≥ 85", color: T.green },
          { grade: "B", label: "CIS Score 70–84", color: T.blue },
          { grade: "C", label: "CIS Score 55–69", color: T.amber },
          { grade: "D", label: "CIS Score < 55", color: T.red },
        ].map(g => (
          <div key={g.grade} className="cis-grade-card" style={{
            border: `1px solid ${T.border}`, borderRadius: 10,
            padding: "14px 16px", background: T.surface,
            display: "flex", flexDirection: "column", gap: 3,
          }}>
            <div className="grade-letter" style={{ fontFamily: FONTS.display, fontSize: 22, fontWeight: 800, marginBottom: 2, color: g.color }}>
              {g.grade}
            </div>
            <div className="grade-count" style={{ fontFamily: FONTS.mono, fontSize: 28, fontWeight: 400, color: T.primary }}>
              {g.grade === "A" ? gradeSummary.A : g.grade === "B" ? gradeSummary.B : g.grade === "C" ? gradeSummary.C : gradeSummary.D}
            </div>
            <div className="grade-label" style={{ fontSize: 9, color: "rgba(255,255,255,0.26)", letterSpacing: "0.06em" }}>
              {g.label}
            </div>
          </div>
        ))}
      </div>

      {/* Filters Row */}
      <div className="cis-filters" style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12, flexWrap: "wrap", gap: 8 }}>
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
          {/* Grade Tabs */}
          {GRADE_TABS.map(g => (
            <button key={g} onClick={() => setGradeFilter(g)} className="cis-filter-btn"
              style={{
                padding: "4px 12px", borderRadius: 4, fontSize: 10, fontWeight: 700, letterSpacing: "0.08em",
                fontFamily: FONTS.display, cursor: "pointer", border: "1px solid",
                borderColor: gradeFilter === g ? `${GRADE_COLORS[g] || T.border}50` : T.border,
                background: gradeFilter === g ? `${GRADE_COLORS[g] || T.blue}15` : "transparent",
                color: gradeFilter === g ? (GRADE_COLORS[g] || T.primary) : T.muted,
                transition: "all 0.15s ease"
              }}>
              {g}
            </button>
          ))}
          <div className="cis-filter-divider" style={{ width: 1, background: T.border, margin: "0 8px" }} />
          {/* Asset Class Tabs */}
          {CLASS_TABS.map(c => {
            const cfg = ASSET_CLASS_COLORS[c] || {};
            const isActive = classFilter === c;
            return (
              <button key={c} onClick={() => setClassFilter(c)} className="cis-filter-btn"
                style={{
                  padding: "3px 10px", borderRadius: 3, fontSize: 9, fontWeight: 600,
                  fontFamily: FONTS.display, cursor: "pointer", border: "1px solid",
                  borderColor: isActive ? `${cfg.text || T.border}50` : T.border,
                  background: isActive ? cfg.bg : "transparent",
                  color: isActive ? cfg.text : T.muted,
                  transition: "all 0.15s ease"
                }}>
                {c}
              </button>
            );
          })}
        </div>
        {/* Pillar Legend - Top */}
        <div className="cis-pillar-legend-top" style={{ display: "flex", alignItems: "center", gap: 16, fontSize: 9, color: "rgba(255,255,255,0.26)" }}>
          {PILLAR_DEFS.map(p => (
            <span key={p.key} style={{ display: "flex", alignItems: "center", gap: 4 }}>
              <span style={{ width: 6, height: 6, borderRadius: "50%", background: p.color }} />
              {p.key}
            </span>
          ))}
        </div>
      </div>

      {/* 2-Column Layout: Table + Detail Panel */}
      <div className="cis-layout" style={{ display: "grid", gridTemplateColumns: "1fr 300px", gap: 16, alignItems: "start" }}>
        {/* Left: Table */}
        <div style={{ border: `1px solid ${T.border}`, borderRadius: 10, overflow: "hidden", background: T.surface }}>
          {/* Table Header */}
          <div className="cis-table-header" style={{
            display: "grid", gridTemplateColumns: "34px 1fr 80px 60px",
            gap: 12, padding: "9px 18px", borderBottom: `1px solid ${T.border}`,
            fontSize: 9, color: "rgba(255,255,255,0.26)", letterSpacing: "0.14em",
            textTransform: "uppercase", fontFamily: FONTS.display, fontWeight: 600,
            background: "rgba(255,255,255,0.018)",
          }}>
            <span>#</span>
            <span>Asset</span>
            <span style={{ textAlign: "right" }}>CIS</span>
            <span style={{ textAlign: "center" }}>Grade</span>
          </div>

          {/* Table Body */}
          <div style={{ maxHeight: 500, overflowY: "auto" }}>
            {filtered.length === 0 ? (
              <div style={{ padding: 40, textAlign: "center", color: T.muted }}>No assets match</div>
            ) : filtered.map((item) => (
              <div key={item.asset_id} className="cis-table-row"
                onClick={() => handleSelectAsset(item)}
                style={{
                  display: "grid", gridTemplateColumns: "34px 1fr 80px 60px",
                  gap: 12, padding: "13px 18px", borderBottom: `1px solid ${T.border}`,
                  alignItems: "center", cursor: "pointer",
                  background: selectedAsset?.asset_id === item.asset_id ? "rgba(68,114,255,0.06)" : "transparent",
                  transition: "background .14s",
                }}
                onMouseEnter={(e) => { e.currentTarget.style.background = "rgba(255,255,255,0.022)"; }}
                onMouseLeave={(e) => { e.currentTarget.style.background = selectedAsset?.asset_id === item.asset_id ? "rgba(68,114,255,0.06)" : "transparent"; }}
              >
                <span style={{ fontFamily: FONTS.mono, fontSize: 10, color: "rgba(255,255,255,0.26)", textAlign: "center" }}>{item.rank}</span>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <span style={{ fontFamily: FONTS.display, fontSize: 12, fontWeight: 700, color: T.primary }}>{item.asset_name}</span>
                  <span style={{
                    fontSize: 8, padding: "2px 5px", borderRadius: 2,
                    background: ASSET_CLASS_COLORS[item.asset_class]?.bg || "transparent",
                    color: ASSET_CLASS_COLORS[item.asset_class]?.text || T.muted,
                    fontFamily: FONTS.display, fontWeight: 600, letterSpacing: "0.05em"
                  }}>{item.asset_class}</span>
                </div>
                <span style={{ fontFamily: FONTS.mono, fontSize: 15, fontWeight: 400, textAlign: "right",
                  color: item.total_score >= 85 ? T.green : item.total_score >= 70 ? T.blue : T.amber }}>
                  {item.total_score.toFixed(1)}
                </span>
                <span style={{
                  width: 28, height: 28, borderRadius: "50%", display: "flex",
                  alignItems: "center", justifyContent: "center", margin: "0 auto",
                  background: `${GRADE_COLORS[item.grade]}20`,
                  fontSize: 12, fontWeight: 700, fontFamily: FONTS.mono,
                  color: GRADE_COLORS[item.grade], border: `1px solid ${GRADE_COLORS[item.grade]}40`
                }}>{item.grade}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Right: Detail Panel */}
        <div className="cis-detail-panel" style={{
          border: `1px solid ${T.border}`, borderRadius: 12, overflow: "hidden",
          background: T.surface, position: "sticky", top: 80,
        }}>
          {/* Detail Header */}
          <div style={{
            padding: "18px 20px", borderBottom: `1px solid ${T.border}`,
            background: "rgba(255,255,255,0.018)",
          }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
              <div>
                <div style={{ fontFamily: FONTS.display, fontSize: 16, fontWeight: 800, color: T.primary }}>
                  {selectedAsset?.asset_name}
                </div>
                <div style={{ fontSize: 9, color: "rgba(255,255,255,0.26)", marginTop: 3 }}>
                  {selectedAsset?.asset_class} · Rank #{selectedAsset?.rank}
                </div>
              </div>
              <div style={{
                width: 36, height: 36, borderRadius: "50%", display: "flex",
                alignItems: "center", justifyContent: "center",
                background: `${GRADE_COLORS[selectedAsset?.grade]}20`,
                fontSize: 14, fontWeight: 700, fontFamily: FONTS.mono,
                color: GRADE_COLORS[selectedAsset?.grade],
                border: `1px solid ${GRADE_COLORS[selectedAsset?.grade]}40`
              }}>{selectedAsset?.grade}</div>
            </div>
            <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
              <span className="cis-score" style={{
                fontFamily: FONTS.mono, fontSize: 42, fontWeight: 400, lineHeight: 1, letterSpacing: "-0.03em",
                color: selectedAsset?.total_score >= 85 ? T.green : selectedAsset?.total_score >= 70 ? T.blue : T.amber
              }}>{selectedAsset?.total_score.toFixed(1)}</span>
              <span style={{ fontSize: 10, color: "rgba(255,255,255,0.26)" }}>/ 100</span>
            </div>
          </div>

          {/* Detail Body */}
          <div style={{ padding: "18px 20px" }}>
            {/* Description */}
            <div style={{ fontSize: 10, color: T.secondary, lineHeight: 1.6, marginBottom: 18, paddingBottom: 14, borderBottom: `1px solid ${T.border}` }}>
              {selectedAsset?.description}
            </div>

            {/* Pillar Bars */}
            {PILLAR_DEFS.map(p => {
              const raw = selectedAsset?.pillars[p.key] || 0;
              const scaled = Math.round((raw / 100) * p.weight * 10) / 10;
              return (
                <div key={p.key} style={{ marginBottom: 14 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 5 }}>
                    <span style={{ fontSize: 9, letterSpacing: "0.12em", color: "rgba(255,255,255,0.26)", fontFamily: FONTS.display, fontWeight: 600, textTransform: "uppercase" }}>
                      {p.name}
                    </span>
                    <span style={{ fontFamily: FONTS.mono, fontSize: 12, fontWeight: 500, color: p.color }}>
                      {raw} <span style={{ color: "rgba(255,255,255,0.26)", fontSize: 9 }}>({scaled}pts)</span>
                    </span>
                  </div>
                  <div style={{ height: 4, background: "rgba(255,255,255,0.07)", borderRadius: 2, overflow: "hidden" }}>
                    <div style={{ width: `${raw}%`, height: "100%", background: p.color, borderRadius: 2, transition: "width .5s ease .1s" }} />
                  </div>
                </div>
              );
            })}

            {/* Footer */}
            <div style={{ marginTop: 18, paddingTop: 14, borderTop: `1px solid ${T.border}`, fontSize: 9, color: "rgba(255,255,255,0.26)" }}>
              CIS v3.1 · Scored by Looloomi AI · {new Date().toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" })}
            </div>
          </div>
        </div>
      </div>

      {/* Bottom Pillar Legend (for mobile/alternative) */}
      <div className="cis-pillar-legend-bottom" style={{
        marginTop: 16, paddingTop: 14, borderTop: `1px solid ${T.border}`,
        display: "flex", justifyContent: "center", gap: 24, flexWrap: "wrap",
        fontSize: 9, color: "rgba(255,255,255,0.35)"
      }}>
        {PILLAR_DEFS.map(p => (
          <span key={p.key} style={{ display: "flex", alignItems: "center", gap: 5 }}>
            <span style={{ width: 8, height: 8, borderRadius: "50%", background: p.color }} />
            <span style={{ fontWeight: 600 }}>{p.key}</span> = {p.name} ({p.weight}%)
          </span>
        ))}
      </div>

      {/* Methodolog Overview */}
      <div style={{ marginTop: 32 }}>
        <div style={{
          background: T.surface, border: `1px solid ${T.border}`,
          borderRadius: 12, overflow: "hidden",
        }}>
          {/* Header */}
          <div style={{
            padding: "20px 24px", borderBottom: `1px solid ${T.border}`,
            background: "rgba(255,255,255,0.018)",
          }}>
            <div style={{
              fontFamily: FONTS.display, fontSize: 14, fontWeight: 700,
              color: T.primary, letterSpacing: "-0.01em", marginBottom: 4,
            }}>
              CIS Methodology v3.1
            </div>
            <div style={{
              fontFamily: FONTS.body, fontSize: 12, color: T.secondary,
            }}>
              Open-source scoring framework for institutional digital asset evaluation
            </div>
          </div>

          {/* Pillar Table */}
          <div style={{ padding: "16px 24px" }}>
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead>
                <tr style={{ borderBottom: `1px solid ${T.border}` }}>
                  <th style={{ textAlign: "left", padding: "10px 8px", fontSize: 11, color: "rgba(255,255,255,0.50)", letterSpacing: "0.1em", textTransform: "uppercase", fontFamily: FONTS.display, fontWeight: 700 }}>Pillar</th>
                  <th style={{ textAlign: "center", padding: "10px 8px", fontSize: 11, color: "rgba(255,255,255,0.50)", letterSpacing: "0.1em", textTransform: "uppercase", fontFamily: FONTS.display, fontWeight: 700, width: 80 }}>Weight</th>
                  <th style={{ textAlign: "left", padding: "10px 8px", fontSize: 11, color: "rgba(255,255,255,0.50)", letterSpacing: "0.1em", textTransform: "uppercase", fontFamily: FONTS.display, fontWeight: 700 }}>What it measures</th>
                </tr>
              </thead>
              <tbody>
                {PILLAR_DEFS.map((p, i) => (
                  <tr key={p.key} style={{ borderBottom: i < 4 ? `1px solid ${T.border}` : "none" }}>
                    <td style={{ padding: "12px 8px" }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <span style={{ width: 8, height: 8, borderRadius: "50%", background: p.color }} />
                        <span style={{ fontFamily: FONTS.display, fontSize: 12, fontWeight: 700, color: p.color }}>{p.key}</span>
                        <span style={{ fontFamily: FONTS.display, fontSize: 12, fontWeight: 600, color: T.primary }}>{p.name}</span>
                      </div>
                    </td>
                    <td style={{ textAlign: "center", padding: "12px 8px" }}>
                      <span style={{ fontFamily: FONTS.mono, fontSize: 13, fontWeight: 600, color: T.primary }}>{p.weight}pts</span>
                    </td>
                    <td style={{ padding: "12px 8px" }}>
                      <span style={{ fontFamily: FONTS.body, fontSize: 11, color: T.secondary }}>{p.desc}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Footer note */}
          <div style={{
            padding: "14px 24px", borderTop: `1px solid ${T.border}`,
            background: "rgba(255,255,255,0.015)",
          }}>
            <div style={{ fontFamily: FONTS.body, fontSize: 10, color: T.muted, lineHeight: 1.6 }}>
              CIS scores are recalculated weekly using live on-chain and market data.
              Methodology published on GitHub.
              Scores do not constitute investment advice.
            </div>
          </div>
        </div>
      </div>

      {/* Grade Definitions */}
      <div style={{ marginTop: 24, marginBottom: 16 }}>
        <div style={{
          fontFamily: FONTS.display, fontSize: 12, fontWeight: 700,
          color: T.muted, letterSpacing: "0.1em", marginBottom: 12,
          textTransform: "uppercase",
        }}>
          Grade Definitions
        </div>
        <div className="cis-grade-definitions" style={{
          display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 10,
        }}>
          {GRADE_DEFINITIONS.map((g) => (
            <div key={g.grade} style={{
              background: T.surface, border: `1px solid ${g.borderColor}40`,
              borderRadius: 10, padding: "16px 18px",
              borderTop: `3px solid ${g.borderColor}`,
            }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
                <span style={{
                  fontFamily: FONTS.mono, fontSize: 20, fontWeight: 800,
                  color: g.borderColor,
                }}>{g.grade}</span>
                <span style={{ fontFamily: FONTS.mono, fontSize: 11, color: T.muted }}>
                  {g.minScore}{g.minScore > 0 ? "+" : ""}
                </span>
              </div>
              <div style={{
                fontFamily: FONTS.display, fontSize: 11, fontWeight: 700,
                color: T.primary, marginBottom: 6,
              }}>
                {g.label}
              </div>
              <div style={{
                fontFamily: FONTS.body, fontSize: 10, color: T.secondary,
                lineHeight: 1.5,
              }}>
                {g.desc}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
