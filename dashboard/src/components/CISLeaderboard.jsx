import { useState, useEffect, useCallback } from "react";
import { ChevronDown, ChevronUp, BarChart3 } from "lucide-react";
import { ChevronCw } from "lucide-react";
import BottomSheet from "./ui/BottomSheet";

const T = {
  void: "#020208",
  deep: "#06050F",
  surface: "#0A0918",
  raised: "#100E22",
  border: "#1A173A",
  borderHi: "#28244C",
  primary: "#F0EEFF",
  secondary: "#8880BE",
  muted: "#3E3A6E",
  violet: "#6B0FCC",
  indigo: "#2D35D4",
  cyan: "#00C8E0",
  pink: "#FF1060",
  amber: "#E8A000",
  green: "#00D98A",
  red: "#FF2D55",
  blue: "#4472FF",
};

const FONTS = {
  display: "'Space Grotesk', sans-serif",
  body: "'Exo 2', sans-serif",
  mono: "'JetBrains Mono', monospace",
};

const GRADE_COLORS = {
  A: "#00D98A",
  B: "#4472FF",
  C: "#E8A000",
  D: "#FF2D55",
  F: "#888888",
};

const GRADE_LABELS = {
  A: "优先配置",
  B: "合格",
  C: "观察",
  D: "回避",
  F: "淘汰",
};

const ASSET_CLASS_COLORS = {
  RWA: { bg: "rgba(232,160,0,.12)", text: "#E8A000" },
  DeFi: { bg: "rgba(68,114,255,.12)", text: "#4472FF" },
  L1: { bg: "rgba(0,200,224,.08)", text: "#00C8E0" },
  L2: { bg: "rgba(107,15,204,.10)", text: "#9945FF" },
  Infrastructure: { bg: "rgba(0,217,138,.10)", text: "#00D98A" },
  Memecoin: { bg: "rgba(255,16,96,.10)", text: "#FF1060" },
  AI: { bg: "rgba(255,16,96,.10)", text: "#FF1060" },
};

const API_BASE = "/api/v1";

// Sample data for demo (will be replaced by API)
const SAMPLE_CIS_DATA = [
  { rank: 1, asset_id: "buidl", asset_name: "BlackRock BUIDL", asset_class: "RWA", total_score: 88.8, grade: "A", pillars: { F: 95, M: 85, O: 90, S: 80, alpha: 85 } },
  { rank: 2, asset_id: "benji", asset_name: "Franklin Templeton BENJI", asset_class: "RWA", total_score: 86.1, grade: "A", pillars: { F: 92, M: 82, O: 88, S: 78, alpha: 82 } },
  { rank: 3, asset_id: "eth", asset_name: "Ethereum", asset_class: "L1", total_score: 85.0, grade: "A", pillars: { F: 92, M: 95, O: 90, S: 68, alpha: 55 } },
  { rank: 4, asset_id: "btc", asset_name: "Bitcoin", asset_class: "L1", total_score: 85.0, grade: "A", pillars: { F: 95, M: 98, O: 95, S: 60, alpha: 40 } },
  { rank: 5, asset_id: "usdy", asset_name: "Ondo USDY", asset_class: "RWA", total_score: 84.3, grade: "B", pillars: { F: 90, M: 80, O: 88, S: 75, alpha: 80 } },
  { rank: 6, asset_id: "ousg", asset_name: "Ondo OUSG", asset_class: "RWA", total_score: 82.0, grade: "B", pillars: { F: 88, M: 78, O: 85, S: 72, alpha: 78 } },
  { rank: 7, asset_id: "sol", asset_name: "Solana", asset_class: "L1", total_score: 81.8, grade: "B", pillars: { F: 80, M: 90, O: 88, S: 75, alpha: 65 } },
  { rank: 8, asset_id: "link", asset_name: "Chainlink", asset_class: "Infrastructure", total_score: 80.0, grade: "B", pillars: { F: 88, M: 78, O: 85, S: 70, alpha: 65 } },
  { rank: 9, asset_id: "ondo", asset_name: "Ondo Finance", asset_class: "RWA", total_score: 79.5, grade: "B", pillars: { F: 85, M: 78, O: 82, S: 70, alpha: 72 } },
  { rank: 10, asset_id: "uni", asset_name: "Uniswap", asset_class: "DeFi", total_score: 77.8, grade: "B", pillars: { F: 80, M: 85, O: 82, S: 62, alpha: 68 } },
  { rank: 11, asset_id: "aave", asset_name: "Aave", asset_class: "DeFi", total_score: 77.2, grade: "B", pillars: { F: 82, M: 75, O: 85, S: 65, alpha: 70 } },
  { rank: 12, asset_id: "maker", asset_name: "Maker", asset_class: "DeFi", total_score: 76.0, grade: "B", pillars: { F: 85, M: 72, O: 88, S: 58, alpha: 60 } },
  { rank: 13, asset_id: "base", asset_name: "Base", asset_class: "L2", total_score: 74.4, grade: "B", pillars: { F: 78, M: 72, O: 80, S: 70, alpha: 65 } },
  { rank: 14, asset_id: "ton", asset_name: "Toncoin", asset_class: "L1", total_score: 72.2, grade: "B", pillars: { F: 70, M: 75, O: 78, S: 72, alpha: 60 } },
  { rank: 15, asset_id: "comp", asset_name: "Compound", asset_class: "DeFi", total_score: 71.8, grade: "B", pillars: { F: 78, M: 70, O: 80, S: 55, alpha: 65 } },
  { rank: 16, asset_id: "arb", asset_name: "Arbitrum", asset_class: "L2", total_score: 70.8, grade: "B", pillars: { F: 75, M: 70, O: 78, S: 60, alpha: 62 } },
  { rank: 17, asset_id: "morpho", asset_name: "Morpho", asset_class: "DeFi", total_score: 69.5, grade: "C", pillars: { F: 72, M: 65, O: 78, S: 55, alpha: 75 } },
  { rank: 18, asset_id: "op", asset_name: "Optimism", asset_class: "L2", total_score: 68.6, grade: "C", pillars: { F: 73, M: 68, O: 75, S: 58, alpha: 60 } },
  { rank: 19, asset_id: "doge", asset_name: "Dogecoin", asset_class: "Memecoin", total_score: 58.5, grade: "C", pillars: { F: 25, M: 60, O: 45, S: 88, alpha: 35 } },
  { rank: 20, asset_id: "pepe", asset_name: "Pepe", asset_class: "Memecoin", total_score: 52.1, grade: "C", pillars: { F: 15, M: 55, O: 40, S: 82, alpha: 28 } },
];

export default function CISLeaderboard({ minimal = false }) {
  const [data, setData] = useState(SAMPLE_CIS_DATA);
  const [loading, setLoading] = useState(false);
  const [gradeFilter, setGradeFilter] = useState("All");
  const [classFilter, setClassFilter] = useState("All");
  const [expandedRow, setExpandedRow] = useState(null);
  const [sortBy, setSortBy] = useState("rank");

  const GRADE_TABS = ["All", "A", "B", "C", "D", "F"];
  const CLASS_TABS = ["All", "RWA", "L1", "L2", "DeFi", "Infrastructure", "Memecoin"];

  // Filter data
  const filtered = data.filter(item => {
    const gradeMatch = gradeFilter === "All" || item.grade === gradeFilter;
    const classMatch = classFilter === "All" || item.asset_class === classFilter;
    return gradeMatch && classMatch;
  });

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
          { key: "F", label: "基础", desc: "团队/产品/代币经济学" },
          { key: "M", label: "市场", desc: "流动性/交易量/价差" },
          { key: "O", label: "链上", desc: "真实活动/Holder行为" },
          { key: "S", label: "情绪", desc: "社交/KOL/社区" },
          { key: "alpha", label: "阿尔法", desc: "BTC独立性/因子暴露" },
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

  return (
    <div>
      {/* Filters */}
      {!minimal && (
        <div style={{ marginBottom: 16 }}>
          {/* Grade Tabs */}
          <div style={{ display: "flex", gap: 6, marginBottom: 12, flexWrap: "wrap" }}>
            {GRADE_TABS.map(g => (
              <button
                key={g}
                onClick={() => setGradeFilter(g)}
                style={{
                  padding: "4px 12px", borderRadius: 4, fontSize: 11, fontWeight: 500,
                  fontFamily: FONTS.body, cursor: "pointer", border: "1px solid",
                  borderColor: gradeFilter === g ? `${GRADE_COLORS[g] || T.border}60` : T.border,
                  background: gradeFilter === g ? `${GRADE_COLORS[g] || T.blue}15` : "transparent",
                  color: gradeFilter === g ? (GRADE_COLORS[g] || T.primary) : T.secondary,
                  transition: "all 0.15s ease"
                }}
              >
                {g === "All" ? "All" : `Grade ${g}`}
                {g !== "All" && (
                  <span style={{ marginLeft: 4, opacity: 0.7 }}>
                    ({data.filter(i => i.grade === g).length})
                  </span>
                )}
              </button>
            ))}
          </div>

          {/* Asset Class Tabs */}
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            {CLASS_TABS.map(c => {
              const cfg = ASSET_CLASS_COLORS[c] || {};
              const isActive = classFilter === c;
              return (
                <button
                  key={c}
                  onClick={() => setClassFilter(c)}
                  style={{
                    padding: "3px 10px", borderRadius: 3, fontSize: 10, fontWeight: 500,
                    fontFamily: FONTS.body, cursor: "pointer", border: "1px solid",
                    borderColor: isActive ? `${cfg.text || T.border}50` : T.border,
                    background: isActive ? cfg.bg : "transparent",
                    color: isActive ? cfg.text : T.muted,
                    transition: "all 0.15s ease"
                  }}
                >
                  {c}
                </button>
              );
            })}
          </div>
        </div>
      )}

      {/* Table Header */}
      <div style={{
        display: "grid",
        gridTemplateColumns: minimal ? "40px 1.5fr 70px 50px" : "45px 2fr 80px 55px 200px",
        gap: 12, padding: "8px 16px", borderBottom: `1px solid ${T.border}`,
        fontSize: 10, color: T.muted, letterSpacing: "0.1em",
        textTransform: "uppercase", fontFamily: FONTS.body
      }}>
        {!minimal && <span>#</span>}
        <span>Asset</span>
        <span style={{ textAlign: "right" }}>CIS</span>
        <span>Grade</span>
        {!minimal && <span style={{ paddingLeft: 8 }}>Pillars</span>}
      </div>

      {/* Table Body */}
      <div>
        {filtered.length === 0 ? (
          <div style={{ padding: 40, textAlign: "center", color: T.muted, fontFamily: FONTS.body }}>
            No assets match the selected filters
          </div>
        ) : (
          filtered.map((item, i) => (
            <div key={item.asset_id}>
              <div
                onClick={() => setExpandedRow(expandedRow?.asset_id === item.asset_id ? null : item)}
                style={{
                  display: "grid",
                  gridTemplateColumns: minimal ? "40px 1.5fr 70px 50px" : "45px 2fr 80px 55px 200px",
                  gap: 12, padding: "12px 16px", borderBottom: `1px solid ${T.border}`,
                  alignItems: "center", cursor: "pointer",
                  background: expandedRow?.asset_id === item.asset_id ? T.deep : "transparent",
                  transition: "background 0.15s ease"
                }}
                className="cis-row"
              >
                {/* Rank */}
                {!minimal && (
                  <span style={{
                    fontSize: 12, fontFamily: FONTS.mono, color: T.muted,
                    width: 24
                  }}>
                    {item.rank}
                  </span>
                )}

                {/* Asset Name */}
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <span style={{
                    fontSize: 13, fontWeight: 600, fontFamily: FONTS.display,
                    color: T.primary, letterSpacing: "-0.01em"
                  }}>
                    {item.asset_name}
                  </span>
                  <span style={{
                    fontSize: 9, padding: "2px 6px", borderRadius: 3,
                    background: ASSET_CLASS_COLORS[item.asset_class]?.bg || "transparent",
                    color: ASSET_CLASS_COLORS[item.asset_class]?.text || T.muted,
                    fontFamily: FONTS.body, fontWeight: 500
                  }}>
                    {item.asset_class}
                  </span>
                </div>

                {/* CIS Score */}
                <div style={{ textAlign: "right" }}>
                  <span style={{
                    fontSize: 16, fontWeight: 700, fontFamily: FONTS.mono,
                    color: GRADE_COLORS[item.grade]
                  }}>
                    {item.total_score.toFixed(1)}
                  </span>
                </div>

                {/* Grade */}
                <div style={{
                  display: "flex", alignItems: "center", gap: 6
                }}>
                  <span style={{
                    width: 24, height: 24, borderRadius: "50%", display: "flex",
                    alignItems: "center", justifyContent: "center",
                    background: `${GRADE_COLORS[item.grade]}20`,
                    fontSize: 12, fontWeight: 700, fontFamily: FONTS.mono,
                    color: GRADE_COLORS[item.grade], border: `1px solid ${GRADE_COLORS[item.grade]}40`
                  }}>
                    {item.grade}
                  </span>
                  {!minimal && (
                    expandedRow?.asset_id === item.asset_id ? <ChevronUp size={14} color={T.muted} /> : <ChevronDown size={14} color={T.muted} />
                  )}
                </div>

                {/* Pillars (minimal mode shows dots) */}
                {!minimal && (
                  <div style={{ display: "flex", gap: 3, paddingLeft: 8 }}>
                    {["F", "M", "O", "S", "alpha"].map(p => (
                      <div key={p} style={{
                        width: 32, height: 4, background: T.border, borderRadius: 2, overflow: "hidden"
                      }}>
                        <div style={{
                          width: `${item.pillars[p]}%`, height: "100%",
                          background: p === "alpha" ? T.pink : (p === "S" ? T.amber : T.blue),
                          borderRadius: 2
                        }} />
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Expanded Detail - moved to BottomSheet */}
              {/* {expandedRow?.asset_id === item.asset_id && !minimal && (
                <ExpandedDetail item={item} />
              )} */}
            </div>
          ))
        )}
      </div>

      {/* Stats Footer */}
      {!minimal && filtered.length > 0 && (
        <div style={{
          padding: "12px 16px", borderTop: `1px solid ${T.border}`,
          display: "flex", justifyContent: "space-between", alignItems: "center",
          fontSize: 11, color: T.muted, fontFamily: FONTS.body
        }}>
          <span>Showing {filtered.length} of {data.length} assets</span>
          <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <BarChart3 size={12} />
            CIS v1.0 · Composite Intelligence Score
          </span>
        </div>
      )}

      <style>{`
        .cis-row:hover { background: ${T.raised} !important; }
      `}</style>

      {/* CIS Detail - BottomSheet */}
      <BottomSheet isOpen={!!expandedRow && !minimal} onClose={() => setExpandedRow(null)}>
        {expandedRow && (
          <div>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 20 }}>
              <div>
                <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                  <h3 style={{ fontFamily: FONTS.display, fontSize: 18, fontWeight: 700, color: T.primary, margin: 0 }}>
                    {expandedRow.asset_name}
                  </h3>
                  <span style={{
                    padding: "4px 10px", borderRadius: 4, fontSize: 12, fontWeight: 600,
                    background: `${GRADE_COLORS[expandedRow.grade]}20`, color: GRADE_COLORS[expandedRow.grade],
                  }}>
                    Grade {expandedRow.grade}
                  </span>
                </div>
                <div style={{ fontSize: 12, color: T.secondary, marginTop: 6 }}>
                  {expandedRow.asset_class} · Rank #{expandedRow.rank}
                </div>
              </div>
              <div style={{ fontSize: 24, fontWeight: 700, color: T.cyan, fontFamily: FONTS.mono, userSelect: "none" }}>
                {expandedRow.total_score.toFixed(1)}
              </div>
            </div>

            <div style={{
              display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: 12,
              marginBottom: 20
            }}>
              {[
                { key: "F", label: "基础", desc: "团队/产品/代币经济学" },
                { key: "M", label: "市场", desc: "流动性/交易量/价差" },
                { key: "O", label: "链上", desc: "真实活动/Holder行为" },
                { key: "S", label: "情绪", desc: "社交/KOL/社区" },
                { key: "alpha", label: "阿尔法", desc: "BTC独立性/因子暴露" },
              ].map(p => (
                <div key={p.key} style={{ textAlign: "center" }}>
                  <div style={{ fontSize: 10, color: T.muted, marginBottom: 6, fontFamily: FONTS.body }}>
                    {p.label}
                  </div>
                  <div style={{
                    width: "100%", height: 8, background: T.border, borderRadius: 4,
                    overflow: "hidden", marginBottom: 6
                  }}>
                    <div style={{
                      width: `${expandedRow.pillars[p.key]}%`, height: "100%",
                      background: GRADE_COLORS[expandedRow.grade],
                      borderRadius: 4
                    }} />
                  </div>
                  <div style={{ fontSize: 18, fontWeight: 600, color: T.primary, fontFamily: FONTS.mono, userSelect: "none" }}>
                    {expandedRow.pillars[p.key]}
                  </div>
                  <div style={{ fontSize: 9, color: T.secondary, marginTop: 4, fontFamily: FONTS.body }}>
                    {p.desc}
                  </div>
                </div>
              ))}
            </div>

            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
              {Object.entries(expandedRow.pillars).map(([k, v]) => (
                <span key={k} style={{
                  fontSize: 11, fontFamily: FONTS.mono, color: T.secondary,
                  background: T.surface, padding: "4px 8px", borderRadius: 4
                }}>
                  {k}: <span style={{ color: T.primary, userSelect: "none" }}>{v}</span>
                </span>
              ))}
            </div>
          </div>
        )}
      </BottomSheet>
    </div>
  );
}
