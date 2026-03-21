import { useState, useEffect, useCallback, useRef } from "react";
import { T, FONTS } from "../tokens";

/* ─── Inline Sparkline SVG ───────────────────────────────────────────── */
const Sparkline = ({ scores, width = 72, height = 24 }) => {
  if (!scores || scores.length < 2) {
    return (
      <div style={{ width, height, display: "flex", alignItems: "center", justifyContent: "center" }}>
        <span style={{ fontSize: 9, color: "rgba(255,255,255,0.15)", fontFamily: "monospace" }}>—</span>
      </div>
    );
  }
  const min = Math.min(...scores);
  const max = Math.max(...scores);
  const range = max - min || 1;
  const pad = 2;
  const w = width - pad * 2;
  const h = height - pad * 2;
  const pts = scores.map((v, i) => {
    const x = pad + (i / (scores.length - 1)) * w;
    const y = pad + h - ((v - min) / range) * h;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");

  const last  = scores[scores.length - 1];
  const first = scores[0];
  const diff  = last - first;
  const color = diff > 1 ? "#00D98A" : diff < -1 ? "#FF2D55" : "rgba(255,255,255,0.25)";

  return (
    <svg width={width} height={height} style={{ display: "block", overflow: "visible" }}>
      <polyline points={pts} fill="none" stroke={color} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" opacity="0.85" />
      {/* Last point dot */}
      <circle
        cx={parseFloat(pts.split(" ").at(-1).split(",")[0])}
        cy={parseFloat(pts.split(" ").at(-1).split(",")[1])}
        r="2" fill={color} opacity="0.9"
      />
    </svg>
  );
};

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

const ASSET_CLASS_COLORS = {
  RWA: { bg: "rgba(232,160,0,.12)", text: "#E8A000" },
  DeFi: { bg: "rgba(68,114,255,.12)", text: "#4472FF" },
  L1: { bg: "rgba(0,200,224,.08)", text: "#00C8E0" },
  L2: { bg: "rgba(107,15,204,.10)", text: "#9945FF" },
  Infrastructure: { bg: "rgba(0,217,138,.10)", text: "#00D98A" },
  Oracle: { bg: "rgba(167,139,250,.10)", text: "#A78BFA" },
  Memecoin: { bg: "rgba(255,16,96,.10)", text: "#FF1060" },
  AI: { bg: "rgba(255,107,0,.10)", text: "#FF6B00" },
  "US Equity": { bg: "rgba(68,114,255,.10)", text: "#4B9EFF" },
  "US Bond":   { bg: "rgba(245,158,11,.10)", text: "#F59E0B" },
  Commodity:   { bg: "rgba(200,168,75,.12)", text: "#C8A84B" },
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

// Grade definitions — percentile-based (Option A)
const GRADE_DEFINITIONS = [
  { grade: "A", minScore: "Top 15%", label: "Institutional Quality", desc: "CIS rating: VERY HIGH. Meets institutional-grade standards across all five pillars. Strong composite signal supported by fundamental and momentum data.", borderColor: "#00D98A" },
  { grade: "B", minScore: "Top 50%", label: "Investment Grade",       desc: "CIS rating: HIGH. Solid fundamentals with selective risk factors. Scores above the universe median across the majority of pillars.", borderColor: "#4472FF" },
  { grade: "C", minScore: "Top 85%", label: "Watch List",             desc: "CIS rating: NEUTRAL. Elevated risk or compressing momentum. Pillar scores show mixed signals — monitor for directional change.", borderColor: "#F59E0B" },
  { grade: "D", minScore: "Bottom 15%", label: "Low Score",           desc: "CIS rating: LOW. Significant structural weakness across multiple pillars. Scores in the bottom quartile of the live universe.", borderColor: "#FF2D55" },
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
    .cis-table-header, .cis-table-row { grid-template-columns: 30px 1fr 60px 40px 0px !important; gap: 8px !important; padding: 10px 12px !important; }
    .cis-table-header span:last-child, .cis-table-row > div:last-child { display: none !important; }
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

export default function CISLeaderboard({ minimal = false, externalData = null, onDataLoad = null }) {
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [gradeFilter, setGradeFilter] = useState("All");
  const [classFilter, setClassFilter] = useState("All");
  const [selectedAsset, setSelectedAsset] = useState(null);
  const [sortBy, setSortBy] = useState("rank");
  const [dataSource, setDataSource] = useState("loading");
  const [engineSource, setEngineSource] = useState(null); // "local_engine" | "railway"
  const [updatedAt, setUpdatedAt] = useState(null);
  const [sparklines, setSparklines] = useState({});   // { [symbol]: number[] }
  const sparkFetchedRef = useRef(false);
  const [backtest, setBacktest] = useState(null);   // backtest summary from API

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
        percentile_rank: asset.percentile_rank ?? null,
        change_30d: asset.change_30d ?? null,
        description: "",
      }));
      setData(mapped);
      setSelectedAsset(mapped[0] || null);
      setDataSource("live");
      if (onDataLoad) onDataLoad(externalData.universe);
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
            percentile_rank: asset.percentile_rank ?? null,
            change_30d: asset.change_30d ?? null,
            description: "",
          }));
          setData(mapped);
          setSelectedAsset(mapped[0]);
          setDataSource(json.data_source || "coingecko+defillama");
          setEngineSource(json.source || "railway");
          setUpdatedAt(json.timestamp ? new Date(json.timestamp).toLocaleString() : null);
          if (onDataLoad) onDataLoad(json.universe);
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

  // Fetch sparkline history after data loads — single batch request
  // Reset ref whenever data changes so sparklines re-fetch on refresh
  useEffect(() => {
    sparkFetchedRef.current = false;
  }, [data]);

  useEffect(() => {
    if (!data.length || sparkFetchedRef.current) return;
    sparkFetchedRef.current = true;

    const fetchAll = async () => {
      const symbols = data
        .map(d => d.asset_id?.toUpperCase() || d.asset_name?.toUpperCase())
        .filter(Boolean);
      if (!symbols.length) return;

      try {
        const res = await fetch(`/api/v1/cis/history/batch?symbols=${symbols.join(",")}&days=7`);
        const json = await res.json();
        if (json.data) {
          const parsed = {};
          for (const [sym, rows] of Object.entries(json.data)) {
            if (Array.isArray(rows) && rows.length > 1) {
              const scores = rows.map(h => h.score).filter(s => s != null);
              if (scores.length > 1) parsed[sym] = scores;
            }
          }
          setSparklines(parsed);
        }
      } catch { /* silent — sparklines are non-critical */ }
    };

    fetchAll();
  }, [data]);

  // Fetch backtest validation summary once on mount
  useEffect(() => {
    fetch("/api/v1/cis/backtest")
      .then(r => r.json())
      .then(d => { if (d.status === "success") setBacktest(d); })
      .catch(() => {});
  }, []);

  const GRADE_TABS = ["All", "A", "B", "C", "D"];
  const CLASS_TABS = ["All", "L1", "L2", "DeFi", "RWA", "Infrastructure", "Oracle", "Memecoin", "US Equity", "US Bond", "Commodity"];

  // Filter data — match base grade bucket (A catches A and A+, etc.)
  const GRADE_BUCKET = {
    A: ["A", "A+"],
    B: ["B", "B+"],
    C: ["C", "C+"],
    D: ["D", "F"],
  };
  const filtered = data.filter(item => {
    const gradeMatch = gradeFilter === "All" || (GRADE_BUCKET[gradeFilter] || [gradeFilter]).includes(item.grade);
    const classMatch = classFilter === "All" || item.asset_class === classFilter;
    return gradeMatch && classMatch;
  });

  // Percentile-based CIS rating — derived from live universe ranking
  // Top 20% = Very High | Middle 60% = Neutral | Bottom 20% = Low
  const getPercentileSignal = (pct) => {
    if (pct == null) return null;
    if (pct >= 80) return { label: "Very High", color: "#00D98A", bg: "rgba(0,217,138,0.12)" };
    if (pct >= 20) return { label: "Neutral",   color: "#4472FF", bg: "rgba(68,114,255,0.10)" };
    return               { label: "Low",        color: "#FF2D55", bg: "rgba(255,45,85,0.12)" };
  };

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
  const PillarBar = ({ value, color = T.blue }) => {
    if (value === null || value === undefined) return null;
    return (
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
  };

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
              {p.label} · {item.pillars[p.key] !== null && item.pillars[p.key] !== undefined ? item.pillars[p.key] : "—"}
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
            {k}: {v !== null && v !== undefined ? v : "—"}
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
              <span style={{ fontSize: 16, fontWeight: 700, fontFamily: FONTS.mono, color: GRADE_COLORS[item.grade] }}>{(item.total_score ?? 0).toFixed(1)}</span>
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
      {/* Header: engine source + timestamp */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{
            fontSize: 10, padding: "3px 10px", borderRadius: 4, fontFamily: FONTS.display,
            fontWeight: 700, letterSpacing: "0.08em",
            background: engineSource === "local_engine" ? "rgba(0,217,138,0.15)" : "rgba(251,191,36,0.12)",
            color: engineSource === "local_engine" ? "#00D98A" : "#fbbf24",
            border: `1px solid ${engineSource === "local_engine" ? "rgba(0,217,138,0.3)" : "rgba(251,191,36,0.25)"}`,
          }}>
            {engineSource === "local_engine" ? "CIS PRO · LOCAL ENGINE" : "CIS MARKET · ESTIMATED"}
          </span>
          {engineSource !== "local_engine" && (
            <span style={{ fontSize: 9, color: T.muted, fontFamily: FONTS.body }}>
              Local engine offline — using market model
            </span>
          )}
        </div>
        <span style={{ fontSize: 10, color: T.muted, fontFamily: FONTS.mono }}>
          CIS v4.0 · {data.length} assets
          {updatedAt && <span style={{ marginLeft: 8, opacity: 0.5 }}>Updated: {updatedAt}</span>}
        </span>
      </div>

      {/* Objectives + Methodology Banner */}
      <div style={{
        marginBottom: 20, padding: "18px 20px",
        background: "rgba(68,114,255,0.04)", border: "1px solid rgba(68,114,255,0.14)",
        borderRadius: 10,
      }}>
        <div style={{
          fontFamily: FONTS.display, fontSize: 10, fontWeight: 700,
          color: "#4472FF", letterSpacing: "0.14em", textTransform: "uppercase", marginBottom: 10,
        }}>
          CometCloud Intelligence Score — CIS v4.0
        </div>
        <div style={{
          fontFamily: FONTS.body, fontSize: 12, color: T.secondary,
          lineHeight: 1.75, marginBottom: 14,
        }}>
          A quantitative multi-pillar scoring system providing institutional investors with a systematic,
          data-driven basis for allocation and position-sizing decisions across crypto and traditional assets —
          updated every 30 minutes, comparable on a unified 0–100 scale.
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 10 }}>
          {[
            {
              title: "Problem Solved",
              text: "Eliminates subjective analyst ratings. Algorithmic, reproducible scoring removes emotional bias from allocation decisions and provides a continuous signal — not quarterly reviews.",
            },
            {
              title: "Methodology",
              text: "5 independent pillars: F (Fundamental) · M (Market Structure) · O (On-Chain Health) · S (Sentiment) · A (Alpha Independence). Graded by relative percentile rank within the live universe — stays meaningful in any market regime.",
            },
            {
              title: "Institutional Application",
              text: "CIS grades provide a standardized, cross-asset scoring framework. Grade A/B reflect strong composite signals across multiple pillars. Grade C reflects mixed or deteriorating signals. Grade D/F reflect weak scores relative to the live universe. Applicable across crypto and TradFi on the same methodology.",
            },
          ].map(card => (
            <div key={card.title} style={{
              background: "rgba(255,255,255,0.018)", border: "1px solid rgba(255,255,255,0.06)",
              borderRadius: 8, padding: "12px 14px",
            }}>
              <div style={{
                fontFamily: FONTS.display, fontSize: 10, fontWeight: 700,
                color: T.primary, marginBottom: 6, letterSpacing: "0.04em",
              }}>{card.title}</div>
              <div style={{ fontFamily: FONTS.body, fontSize: 10, color: T.muted, lineHeight: 1.65 }}>
                {card.text}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Backtest Validation Strip */}
      {backtest && backtest.returns_by_grade && (
        <div style={{
          marginBottom: 18, padding: "14px 20px",
          background: "rgba(0,217,138,0.04)", border: "1px solid rgba(0,217,138,0.14)",
          borderRadius: 10, display: "flex", alignItems: "center", gap: 24, flexWrap: "wrap",
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexShrink: 0 }}>
            <span style={{
              fontSize: 9, padding: "2px 8px", borderRadius: 3,
              background: "rgba(0,217,138,0.12)", color: "#00D98A",
              border: "1px solid rgba(0,217,138,0.25)",
              fontFamily: FONTS.display, fontWeight: 700, letterSpacing: "0.1em",
            }}>BACKTEST</span>
            <span style={{ fontSize: 10, color: T.muted, fontFamily: FONTS.body }}>
              30d realized returns by grade · Binance klines · {backtest.assets || "—"} assets
            </span>
          </div>
          <div style={{ display: "flex", gap: 20, flexWrap: "wrap" }}>
            {Object.entries(backtest.returns_by_grade).map(([grade, ret]) => {
              // TradFi assets return 0.0 — Binance klines don't carry SPY/AAPL/GLD/TLT
              const noData = typeof ret !== "number" || ret === 0;
              const color = noData ? "rgba(255,255,255,0.25)" : ret > 3 ? "#00D98A" : ret > 0 ? "#4472FF" : "#FF2D55";
              return (
                <div key={grade} style={{ display: "flex", alignItems: "baseline", gap: 5 }}>
                  <span style={{
                    fontFamily: FONTS.display, fontSize: 11, fontWeight: 700,
                    color: grade.startsWith("A") ? "#00D98A" : grade.startsWith("B") ? "#4472FF" : "#E8A000",
                  }}>{grade}</span>
                  <span style={{ fontFamily: FONTS.mono, fontSize: 13, fontWeight: 400, color }}>
                    {noData ? "—" : `${ret > 0 ? "+" : ""}${ret.toFixed(2)}%`}
                  </span>
                </div>
              );
            })}
          </div>
          {backtest.alpha && (
            <div style={{ marginLeft: "auto", display: "flex", gap: 16, flexShrink: 0 }}>
              {backtest.alpha.A_vs_B !== undefined && (
                <div style={{ textAlign: "right" }}>
                  <div style={{ fontSize: 9, color: T.muted, fontFamily: FONTS.mono }}>A vs B alpha</div>
                  <div style={{ fontSize: 12, fontFamily: FONTS.mono, color: "#00D98A" }}>
                    +{backtest.alpha.A_vs_B.toFixed(2)}%
                  </div>
                </div>
              )}
              {backtest.alpha.A_vs_C !== undefined && (
                <div style={{ textAlign: "right" }}>
                  <div style={{ fontSize: 9, color: T.muted, fontFamily: FONTS.mono }}>A vs C alpha</div>
                  <div style={{ fontSize: 12, fontFamily: FONTS.mono, color: "#00D98A" }}>
                    +{backtest.alpha.A_vs_C.toFixed(2)}%
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* Grade Summary Cards */}
      <div className="cis-grade-summary" style={{
        display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 8, marginBottom: 18
      }}>
        {[
          { grade: "A", label: "Top 15% · A+ / A", color: T.green },
          { grade: "B", label: "Top 50% · B+ / B", color: T.blue },
          { grade: "C", label: "Top 85% · C+ / C", color: T.amber },
          { grade: "D", label: "Bottom 15% · D / F", color: T.red },
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
      <div className="cis-layout" style={{ display: "grid", gridTemplateColumns: "1fr minmax(300px, 340px)", gap: 16, alignItems: "start" }}>
        {/* Left: Table */}
        <div style={{ border: `1px solid ${T.border}`, borderRadius: 10, overflow: "hidden", background: T.surface }}>
          {/* Table Header */}
          <div className="cis-table-header" style={{
            display: "grid", gridTemplateColumns: "34px 1fr 80px 60px 80px",
            gap: 12, padding: "9px 18px", borderBottom: `1px solid ${T.border}`,
            fontSize: 9, color: "rgba(255,255,255,0.26)", letterSpacing: "0.14em",
            textTransform: "uppercase", fontFamily: FONTS.display, fontWeight: 600,
            background: "rgba(255,255,255,0.018)",
          }}>
            <span>#</span>
            <span>Asset</span>
            <span style={{ textAlign: "right" }}>CIS</span>
            <span style={{ textAlign: "center" }}>Grade</span>
            <span style={{ textAlign: "center" }}>7D</span>
          </div>

          {/* Table Body */}
          <div style={{ maxHeight: "calc(100vh - 380px)", minHeight: 300, overflowY: "auto" }}>
            {filtered.length === 0 ? (
              <div style={{ padding: 40, textAlign: "center", color: T.muted }}>No assets match</div>
            ) : filtered.map((item) => {
              const symKey = (item.asset_id || "").toUpperCase();
              const sparkData = sparklines[symKey] || null;
              return (
              <div key={item.asset_id} className="cis-table-row"
                onClick={() => handleSelectAsset(item)}
                style={{
                  display: "grid", gridTemplateColumns: "34px 1fr 80px 60px 80px",
                  gap: 12, padding: "13px 18px", borderBottom: `1px solid ${T.border}`,
                  alignItems: "center", cursor: "pointer",
                  background: selectedAsset?.asset_id === item.asset_id ? "rgba(68,114,255,0.06)" : "transparent",
                  transition: "background .14s",
                }}
                onMouseEnter={(e) => { e.currentTarget.style.background = "rgba(255,255,255,0.022)"; }}
                onMouseLeave={(e) => { e.currentTarget.style.background = selectedAsset?.asset_id === item.asset_id ? "rgba(68,114,255,0.06)" : "transparent"; }}
              >
                <span style={{ fontFamily: FONTS.mono, fontSize: 10, color: "rgba(255,255,255,0.26)", textAlign: "center" }}>{item.rank}</span>
                <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                    <span style={{ fontFamily: FONTS.display, fontSize: 12, fontWeight: 700, color: T.primary }}>{item.asset_name}</span>
                    <span style={{
                      fontSize: 8, padding: "2px 5px", borderRadius: 2,
                      background: ASSET_CLASS_COLORS[item.asset_class]?.bg || "transparent",
                      color: ASSET_CLASS_COLORS[item.asset_class]?.text || T.muted,
                      fontFamily: FONTS.display, fontWeight: 600, letterSpacing: "0.05em"
                    }}>{item.asset_class}</span>
                  </div>
                  {(() => {
                    const sig = getPercentileSignal(item.percentile_rank);
                    return sig ? (
                      <span style={{
                        fontSize: 8, fontFamily: FONTS.display, fontWeight: 700,
                        letterSpacing: "0.06em", color: sig.color, opacity: 0.8,
                      }}>{sig.label}</span>
                    ) : null;
                  })()}
                </div>
                <span style={{ fontFamily: FONTS.mono, fontSize: 15, fontWeight: 400, textAlign: "right",
                  color: (item.total_score ?? 0) >= 85 ? T.green : (item.total_score ?? 0) >= 70 ? T.blue : T.amber }}>
                  {(item.total_score ?? 0).toFixed(1)}
                </span>
                <span style={{
                  width: 28, height: 28, borderRadius: "50%", display: "flex",
                  alignItems: "center", justifyContent: "center", margin: "0 auto",
                  background: `${GRADE_COLORS[item.grade]}20`,
                  fontSize: 12, fontWeight: 700, fontFamily: FONTS.mono,
                  color: GRADE_COLORS[item.grade], border: `1px solid ${GRADE_COLORS[item.grade]}40`
                }}>{item.grade}</span>
                {/* 7D Sparkline */}
                <div style={{ display: "flex", alignItems: "center", justifyContent: "center" }}>
                  <Sparkline scores={sparkData} width={72} height={24} />
                </div>
              </div>
              );
            })}
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
                <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 3 }}>
                  <span style={{ fontSize: 9, color: "rgba(255,255,255,0.26)" }}>
                    {selectedAsset?.asset_class} · Rank #{selectedAsset?.rank}
                    {selectedAsset?.percentile_rank != null ? ` · P${Math.round(selectedAsset.percentile_rank)}` : ""}
                  </span>
                  {(() => {
                    const sig = getPercentileSignal(selectedAsset?.percentile_rank);
                    return sig ? (
                      <span style={{
                        fontSize: 8, fontFamily: FONTS.display, fontWeight: 700,
                        letterSpacing: "0.07em", padding: "2px 7px", borderRadius: 3,
                        background: sig.bg, color: sig.color, border: `1px solid ${sig.color}30`,
                      }}>{sig.label}</span>
                    ) : null;
                  })()}
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
                color: (selectedAsset?.total_score ?? 0) >= 85 ? T.green : (selectedAsset?.total_score ?? 0) >= 70 ? T.blue : T.amber
              }}>{(selectedAsset?.total_score ?? 0).toFixed(1)}</span>
              <span style={{ fontSize: 10, color: "rgba(255,255,255,0.26)" }}>/ 100</span>
            </div>
          </div>

          {/* Detail Body */}
          <div style={{ padding: "18px 20px" }}>
            {/* Description — only render if non-empty */}
            {selectedAsset?.description && (
              <div style={{ fontSize: 10, color: T.secondary, lineHeight: 1.6, marginBottom: 18, paddingBottom: 14, borderBottom: `1px solid ${T.border}` }}>
                {selectedAsset.description}
              </div>
            )}

            {/* Pillar Bars */}
            {PILLAR_DEFS.map(p => {
              const raw = selectedAsset?.pillars[p.key];
              const isNull = raw === null || raw === undefined;
              const scaled = isNull ? 0 : Math.round((raw / 100) * p.weight * 10) / 10;
              return (
                <div key={p.key} style={{ marginBottom: 14 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 5 }}>
                    <span style={{ fontSize: 9, letterSpacing: "0.12em", color: "rgba(255,255,255,0.26)", fontFamily: FONTS.display, fontWeight: 600, textTransform: "uppercase" }}>
                      {p.name}
                    </span>
                    <span style={{ fontFamily: FONTS.mono, fontSize: 12, fontWeight: 500, color: isNull ? "rgba(255,255,255,0.26)" : p.color }}>
                      {isNull ? "—" : raw} <span style={{ color: "rgba(255,255,255,0.26)", fontSize: 9 }}>{isNull ? "" : `(${scaled}pts)`}</span>
                    </span>
                  </div>
                  {!isNull && (
                    <div style={{ height: 4, background: "rgba(255,255,255,0.07)", borderRadius: 2, overflow: "hidden" }}>
                      <div style={{ width: `${raw}%`, height: "100%", background: p.color, borderRadius: 2, transition: "width .5s ease .1s" }} />
                    </div>
                  )}
                </div>
              );
            })}

            {/* Footer */}
            <div style={{ marginTop: 18, paddingTop: 14, borderTop: `1px solid ${T.border}`, fontSize: 9, color: "rgba(255,255,255,0.26)" }}>
              CIS v4.0 · Scored by Looloomi AI · {new Date().toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" })}
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
              CIS Methodology v4.0
            </div>
            <div style={{
              fontFamily: FONTS.body, fontSize: 12, color: T.secondary,
            }}>
              Quantitative scoring framework for institutional crypto and cross-asset evaluation
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
              CIS scores are recalculated every 30 minutes using live market, on-chain, and macro data.
              Grades are percentile-based within the current universe — not absolute thresholds — ensuring
              the scale remains meaningful across market regimes.
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
                <span style={{ fontFamily: FONTS.mono, fontSize: 10, color: T.muted }}>
                  {g.minScore}
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
