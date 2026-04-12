import React, { useState, useEffect, useMemo, Fragment } from "react";
import { T, FONTS } from "../tokens";

const API_BASE = "/api/v1";

/* ─── Constants ──────────────────────────────────────────────────────── */
const REGIME_COLORS = {
  "Risk-On": "#22c55e",
  "Risk-Off": "#ef4444",
  "Tightening": "#f59e0b",
  "Easing": "#3b82f6",
  "Stagflation": "#dc2626",
  "Goldilocks": "#a855f7",
};

const GRADE_COLORS = {
  "A+": "#22c55e",
  "A": "#4ade80",
  "B+": "#86efac",
  "B": "#fbbf24",
  "C+": "#fb923c",
  "C": "#f87171",
  "D": "#ef4444",
  "F": "#dc2626",
};

const SIGNAL_STYLES = {
  "STRONG OUTPERFORM": { bg: "rgba(34,197,94,0.15)",  color: "#22c55e", label: "VERY HIGH" },
  "OUTPERFORM":        { bg: "rgba(74,222,128,0.12)", color: "#4ade80", label: "HIGH"      },
  "NEUTRAL":           { bg: "rgba(251,191,36,0.10)", color: "#fbbf24", label: "NEUTRAL"   },
  "UNDERPERFORM":      { bg: "rgba(248,113,113,0.12)",color: "#f87171", label: "LOW"       },
  "UNDERWEIGHT":       { bg: "rgba(220,38,38,0.15)",  color: "#dc2626", label: "VERY LOW"  },
};

const ASSET_CLASSES = ["All", "Crypto", "L1", "L2", "DeFi", "Infrastructure", "US Equity", "US Bond", "Commodity"];

/* ─── Sparkline ──────────────────────────────────────────────────────── */

function MiniSparkline({ scores, width = 60, height = 20 }) {
  if (!scores || scores.length < 2) {
    return (
      <div style={{ width, height, display: "flex", alignItems: "center", justifyContent: "center" }}>
        <span style={{ fontSize: 9, color: "rgba(199,210,254,0.20)", fontFamily: "'JetBrains Mono', monospace" }}>—</span>
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

  const diff = scores[scores.length - 1] - scores[0];
  const color = diff > 1 ? "#22c55e" : diff < -1 ? "#ef4444" : "rgba(148,163,184,0.25)";

  return (
    <svg width={width} height={height} style={{ display: "block" }}>
      <polyline points={pts} fill="none" stroke={color} strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" opacity="0.8" />
      <circle
        cx={parseFloat(pts.split(" ").at(-1).split(",")[0])}
        cy={parseFloat(pts.split(" ").at(-1).split(",")[1])}
        r="1.5" fill={color} opacity="0.9"
      />
    </svg>
  );
}

/* ─── Helper Components ──────────────────────────────────────────────── */

function PillarBar({ value, label }) {
  const v = value ?? 0;
  const color = v >= 80 ? "#22c55e" : v >= 65 ? "#fbbf24" : v >= 50 ? "#fb923c" : "#ef4444";
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 5 }}>
      <span style={{ fontSize: 10, color: "#6b7280", minWidth: 96, fontFamily: FONTS.mono }}>{label}</span>
      <div style={{ flex: 1, height: 6, background: "rgba(255,255,255,0.04)", borderRadius: 3, overflow: "hidden" }}>
        <div style={{ width: `${v}%`, height: "100%", background: color, borderRadius: 3, transition: "width 0.5s ease" }} />
      </div>
      <span style={{ fontSize: 10, color: "#9ca3af", width: 26, textAlign: "right", fontFamily: FONTS.mono }}>
        {value != null ? value : "—"}
      </span>
    </div>
  );
}

function HeatCell({ value, onClick }) {
  const v = value ?? 0;
  const h = v >= 80 ? 142 : v >= 65 ? 48 + (v - 65) * 6 : v >= 50 ? 30 : 0;
  const s = v >= 50 ? 70 : 80;
  const l = 25 + (v / 100) * 25;
  return (
    <td
      onClick={onClick}
      style={{
        background: `hsl(${h}, ${s}%, ${l}%)`,
        color: "#fff",
        fontSize: 11,
        fontFamily: FONTS.mono,
        fontWeight: 600,
        textAlign: "center",
        padding: "6px 4px",
        borderRadius: 2,
        minWidth: 36,
        cursor: "pointer",
        transition: "transform 0.1s ease",
      }}
    >
      {value}
    </td>
  );
}

/* ─── Macro Regime Banner ───────────────────────────────────────────── */

export function CISMacroBanner({ macro }) {
  const regimeColor = REGIME_COLORS[macro?.regime] || "#888";
  const regime = macro?.regime || "Unknown";

  return (
    <div className="lm-card" style={{ padding: "16px 20px", display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 16 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
        <div>
          <div style={{ fontSize: 10, color: T.secondary, textTransform: "uppercase", letterSpacing: "0.1em", marginBottom: 2 }}>Macro Regime</div>
          <div style={{ fontSize: 18, fontWeight: 700, color: regimeColor, fontFamily: FONTS.display }}>{regime}</div>
        </div>
      </div>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
        {[
          { label: "Fed", value: macro?.fed_funds ? `${macro.fed_funds}%` : "—" },
          { label: "10Y", value: macro?.treasury_10y ? `${macro.treasury_10y}%` : "—" },
          { label: "VIX", value: macro?.vix ?? "—" },
          { label: "DXY", value: macro?.dxy ?? "—" },
          { label: "CPI", value: macro?.cpi_yoy ? `${macro.cpi_yoy}%` : "—" },
        ].map((m, i) => (
          <div key={i} style={{ textAlign: "center", padding: "6px 12px", background: "rgba(255,255,255,0.03)", borderRadius: 6, border: "1px solid rgba(255,255,255,0.06)" }}>
            <div style={{ fontSize: 9, color: T.secondary, textTransform: "uppercase" }}>{m.label}</div>
            <div style={{ fontSize: 13, fontWeight: 600, color: T.primary, fontFamily: FONTS.mono }}>{m.value}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ─── CIS Leaderboard Table (simplified table — not to be confused with CISLeaderboard.jsx) ── */

export function CISLeaderboardTable({ data, filter, setFilter, defaultLimit = 0 }) {
  const [expanded, setExpanded] = useState(null);
  const [showAll, setShowAll] = useState(false);
  const [sparklines, setSparklines] = useState({});
  const sparkFetchedRef = React.useRef(false);

  const filtered = useMemo(() => {
    const items = data?.universe || [];
    return filter === "All" ? items : items.filter(a => a.asset_class === filter);
  }, [data, filter]);

  // Fetch sparkline history (batch) when data changes
  useEffect(() => { sparkFetchedRef.current = false; }, [data]);
  useEffect(() => {
    const symbols = (data?.universe || []).map(a => a.symbol).filter(Boolean);
    if (!symbols.length || sparkFetchedRef.current) return;
    sparkFetchedRef.current = true;
    (async () => {
      try {
        const res = await fetch(`${API_BASE}/cis/history/batch?symbols=${symbols.join(",")}&days=7`);
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
      } catch { /* sparklines are non-critical */ }
    })();
  }, [data]);

  // Apply row limit: 0 = no limit, otherwise truncate
  const displayRows = (defaultLimit > 0 && !showAll) ? filtered.slice(0, defaultLimit) : filtered;
  const hasMore = defaultLimit > 0 && filtered.length > defaultLimit;

  const macro = data?.macro || {};

  return (
    <div>
      {/* Filters */}
      <div style={{ padding: "12px 0", display: "flex", gap: 4, flexWrap: "wrap" }}>
        {ASSET_CLASSES.map(ac => (
          <button
            key={ac}
            onClick={() => setFilter(ac)}
            className="filter-btn"
            style={{
              borderColor: filter === ac ? T.gold : T.border,
              background: filter === ac ? "rgba(218,165,32,0.12)" : "transparent",
              color: filter === ac ? T.gold : T.muted,
            }}
          >
            {ac}
          </button>
        ))}
      </div>

      {/* Pillar Legend */}
      <div style={{ display: "flex", gap: 16, padding: "6px 10px 10px", flexWrap: "wrap" }}>
        {[
          { key: "F", label: "Fundamental", color: "#22c55e" },
          { key: "M", label: "Market",      color: "#3b82f6" },
          { key: "O", label: "On-Chain",    color: "#f59e0b" },
          { key: "S", label: "Sentiment",   color: "#ec4899" },
          { key: "A", label: "Alpha",       color: "#8b5cf6" },
        ].map(p => (
          <div key={p.key} style={{ display: "flex", alignItems: "center", gap: 5 }}>
            <span style={{ fontFamily: FONTS.mono, fontSize: 10, fontWeight: 700, color: p.color }}>{p.key}</span>
            <span style={{ fontSize: 10, color: T.muted }}>{p.label}</span>
          </div>
        ))}
      </div>

      {/* Table */}
      <div style={{ overflowX: "auto", WebkitOverflowScrolling: "touch" }}>
        <table style={{ width: "100%", borderCollapse: "separate", borderSpacing: "0 2px", minWidth: 740 }}>
          <thead>
            <tr>
              {["#", "Asset", "Class", "CIS", "Grade", "Rating", "Pillars", "7D", "30d", "Pctl"].map((h, i) => (
                <th key={i} style={{ padding: "8px 10px", textAlign: i <= 1 ? "center" : "left", fontSize: 10, color: T.secondary, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.08em", borderBottom: `1px solid ${T.border}` }}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {displayRows.map((asset, idx) => {
              const isExpanded = expanded === asset.symbol;
              const sig = SIGNAL_STYLES[asset.signal] || SIGNAL_STYLES["NEUTRAL"];
              return (
                <React.Fragment key={asset.symbol}>
                  <tr
                    onClick={() => setExpanded(isExpanded ? null : asset.symbol)}
                    className="lm-row"
                    style={{
                      background: isExpanded ? "rgba(218,165,32,0.04)" : idx % 2 === 0 ? "rgba(13,32,56,0.3)" : "transparent",
                    }}
                  >
                    <td style={{ padding: "10px 8px", textAlign: "center", fontSize: 12, color: T.secondary, fontFamily: FONTS.mono, width: 36 }}>{idx + 1}</td>
                    <td style={{ padding: "10px 8px" }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <span style={{ fontSize: 14, fontWeight: 700, color: T.primary, fontFamily: FONTS.display }}>{asset.symbol}</span>
                        <span style={{ fontSize: 11, color: T.secondary }}>{asset.name}</span>
                      </div>
                    </td>
                    <td style={{ padding: "10px 8px", fontSize: 11, color: T.secondary }}>{asset.asset_class}</td>
                    <td style={{ padding: "10px 8px" }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <div style={{ width: 64, height: 5, background: "rgba(255,255,255,0.04)", borderRadius: 3, overflow: "hidden" }}>
                          <div style={{ width: `${asset.cis_score}%`, height: "100%", borderRadius: 3, background: `linear-gradient(90deg, ${GRADE_COLORS[asset.grade] || "#fbbf24"}, ${GRADE_COLORS[asset.grade] || "#fbbf24"}88)` }} />
                        </div>
                        <span style={{ fontSize: 13, fontWeight: 700, fontFamily: FONTS.mono, color: T.primary }}>{asset.cis_score.toFixed(1)}</span>
                      </div>
                    </td>
                    <td style={{ padding: "10px 8px" }}>
                      <span style={{ fontSize: 12, fontWeight: 700, color: GRADE_COLORS[asset.grade] || "#fbbf24", fontFamily: FONTS.mono }}>{asset.grade}</span>
                    </td>
                    <td style={{ padding: "10px 8px" }}>
                      <span style={{ fontSize: 10, fontWeight: 600, padding: "2px 8px", borderRadius: 4, background: sig.bg, color: sig.color }}>{sig.label}</span>
                    </td>
                    <td style={{ padding: "10px 4px", width: 140 }}>
                      <div style={{ display: "flex", gap: 2 }}>
                        {[asset.f, asset.m, asset.r, asset.s, asset.a].map((v, j) => {
                          const vv = v ?? 0;
                          const c = vv >= 80 ? "#22c55e" : vv >= 65 ? "#fbbf24" : vv >= 50 ? "#fb923c" : "#ef4444";
                          return (
                            <div key={j} style={{ flex: 1, height: 18, borderRadius: 2, background: `${c}20`, display: "flex", alignItems: "center", justifyContent: "center" }}>
                              <span style={{ fontSize: 8, fontWeight: 700, color: c, fontFamily: FONTS.mono }}>{v != null ? v : "—"}</span>
                            </div>
                          );
                        })}
                      </div>
                    </td>
                    <td style={{ padding: "10px 4px", width: 64 }}>
                      <MiniSparkline scores={sparklines[asset.symbol?.toUpperCase()]} width={60} height={20} />
                    </td>
                    <td style={{ padding: "10px 8px", fontSize: 12, fontWeight: 600, fontFamily: FONTS.mono, color: (asset.change_30d ?? 0) >= 0 ? T.green : T.red }}>
                      {asset.change_30d != null
                        ? `${asset.change_30d >= 0 ? "+" : ""}${asset.change_30d.toFixed(1)}`
                        : "—"}
                    </td>
                    <td style={{ padding: "10px 8px", fontSize: 11, color: T.secondary, fontFamily: FONTS.mono }}>
                      {asset.percentile != null ? `${asset.percentile}%` : "—"}
                    </td>
                  </tr>
                  {isExpanded && (
                    <tr>
                      <td colSpan={10} style={{ padding: "0 8px 16px 44px", background: "rgba(218,165,32,0.02)" }}>
                        <div style={{ display: "flex", gap: 24, padding: "12px 0", flexWrap: "wrap" }}>
                          <div style={{ flex: 1, minWidth: 200 }}>
                            <div style={{ fontSize: 11, color: T.gold, fontWeight: 600, marginBottom: 8, textTransform: "uppercase", letterSpacing: "0.08em" }}>Pillar Breakdown</div>
                            <PillarBar value={asset.f} label="Fundamental" />
                            <PillarBar value={asset.m} label="Market" />
                            <PillarBar value={asset.r} label="On-Chain" />
                            <PillarBar value={asset.s} label="Sentiment" />
                            <PillarBar value={asset.a} label="Alpha" />
                          </div>
                          <div style={{ flex: 1, minWidth: 200 }}>
                            <div style={{ fontSize: 11, color: T.gold, fontWeight: 600, marginBottom: 8, textTransform: "uppercase", letterSpacing: "0.08em" }}>Summary</div>
                            <div style={{ fontSize: 12, color: T.secondary, lineHeight: 1.8 }}>
                              <div>Cross-Asset Percentile: <strong style={{ color: T.primary }}>{asset.percentile != null ? `Top ${100 - asset.percentile}%` : "—"}</strong></div>
                              <div>CIS Grade: <strong style={{ color: GRADE_COLORS[asset.grade] }}>{asset.grade}</strong> ({asset.cis_score != null ? asset.cis_score.toFixed(1) : "—"}/100)</div>
                              <div>CIS Rating: <strong style={{ color: SIGNAL_STYLES[asset.signal]?.color }}>{SIGNAL_STYLES[asset.signal]?.label ?? "—"}</strong></div>
                            </div>
                          </div>
                        </div>
                      </td>
                    </tr>
                  )}
                </React.Fragment>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Show all / Collapse toggle */}
      {hasMore && (
        <div style={{ padding: "12px 0", textAlign: "center" }}>
          <button
            onClick={() => setShowAll(!showAll)}
            style={{
              padding: "8px 24px", borderRadius: 6, fontSize: 11, fontWeight: 600,
              fontFamily: FONTS.display, cursor: "pointer", outline: "none",
              border: `1px solid ${T.border}`, background: "rgba(0,0,0,0.02)",
              color: T.secondary, transition: "all .15s ease",
              letterSpacing: "0.06em",
            }}
          >
            {showAll ? `Collapse to top ${defaultLimit}` : `Show all ${filtered.length} assets`}
          </button>
        </div>
      )}
    </div>
  );
}

/* ─── Cross-Asset Heatmap ───────────────────────────────────────────── */

export function CISHeatmap({ data, filter, setFilter }) {
  const [expanded, setExpanded] = useState(null);

  const filtered = useMemo(() => {
    const items = data?.universe || [];
    return filter === "All" ? items : items.filter(a => a.asset_class === filter);
  }, [data, filter]);

  return (
    <div>
      {/* Filters */}
      <div style={{ padding: "12px 0", display: "flex", gap: 4, flexWrap: "wrap" }}>
        {ASSET_CLASSES.slice(0, 6).map(ac => (
          <button
            key={ac}
            onClick={() => setFilter(ac)}
            className="filter-btn"
            style={{
              borderColor: filter === ac ? T.gold : T.border,
              background: filter === ac ? "rgba(218,165,32,0.12)" : "transparent",
              color: filter === ac ? T.gold : T.muted,
            }}
          >
            {ac}
          </button>
        ))}
      </div>

      {/* Heatmap */}
      <div style={{ overflowX: "auto", WebkitOverflowScrolling: "touch" }}>
        <table style={{ width: "100%", borderSpacing: "2px", minWidth: 560 }}>
          <thead>
            <tr>
              <th style={{ padding: 8, textAlign: "left", fontSize: 10, color: T.secondary, fontWeight: 600 }}>Asset</th>
              <th style={{ padding: 8, textAlign: "left", fontSize: 10, color: T.secondary, fontWeight: 600 }}>Class</th>
              {["F", "M", "R", "S", "A"].map(p => (
                <th key={p} style={{ padding: 8, textAlign: "center", fontSize: 11, color: T.gold, fontWeight: 700, fontFamily: FONTS.display }}>{p}</th>
              ))}
              <th style={{ padding: 8, textAlign: "center", fontSize: 10, color: T.secondary, fontWeight: 600 }}>CIS</th>
              <th style={{ padding: 8, textAlign: "center", fontSize: 10, color: T.secondary, fontWeight: 600 }}>Grade</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((asset) => (
              <Fragment key={asset.symbol}>
                <tr onClick={() => setExpanded(expanded === asset.symbol ? null : asset.symbol)} style={{ cursor: "pointer" }}>
                  <td style={{ padding: "6px 8px", fontSize: 13, fontWeight: 700, color: T.primary, fontFamily: FONTS.display }}>{asset.symbol}</td>
                  <td style={{ padding: "6px 8px", fontSize: 10, color: T.secondary }}>{asset.asset_class}</td>
                  <HeatCell value={asset.f} />
                  <HeatCell value={asset.m} />
                  <HeatCell value={asset.r} />
                  <HeatCell value={asset.s} />
                  <HeatCell value={asset.a} />
                  <td style={{ padding: "6px 8px", textAlign: "center", fontSize: 13, fontWeight: 700, color: T.primary, fontFamily: FONTS.mono }}>{asset.cis_score != null ? asset.cis_score.toFixed(1) : "—"}</td>
                  <td style={{ padding: "6px 8px", textAlign: "center", fontSize: 12, fontWeight: 700, color: GRADE_COLORS[asset.grade], fontFamily: FONTS.mono }}>{asset.grade}</td>
                </tr>
                {expanded === asset.symbol && (
                  <tr>
                    <td colSpan={9} style={{ padding: "12px 8px 16px 44px", background: "rgba(218,165,32,0.02)" }}>
                      <div style={{ display: "flex", gap: 24, flexWrap: "wrap" }}>
                        <div style={{ flex: 1, minWidth: 200 }}>
                          <PillarBar value={asset.f} label="Fundamental" />
                          <PillarBar value={asset.m} label="Market" />
                          <PillarBar value={asset.r} label="On-Chain" />
                          <PillarBar value={asset.s} label="Sentiment" />
                          <PillarBar value={asset.a} label="Alpha" />
                        </div>
                      </div>
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* ─── Main CIS Component ───────────────────────────────────────────── */

/* ─── Weight Adjuster Component ────────────────────────────────────────── */
function WeightAdjuster({ weights, onChange, pillarLabels }) {
  const [isOpen, setIsOpen] = useState(false);
  const [localWeights, setLocalWeights] = useState(weights);

  const pillars = ["F", "M", "O", "S", "A"];
  const colors = {
    F: "#22c55e",
    M: "#3b82f6",
    O: "#f59e0b",
    S: "#ec4899",
    A: "#8b5cf6",
  };

  const handleSliderChange = (pillar, value) => {
    const newWeights = { ...localWeights, [pillar]: parseFloat(value) };
    setLocalWeights(newWeights);
  };

  const applyWeights = () => {
    onChange(localWeights);
    setIsOpen(false);
  };

  const resetWeights = () => {
    const defaultWeights = { F: 0.25, M: 0.25, O: 0.20, S: 0.15, A: 0.15 };
    setLocalWeights(defaultWeights);
  };

  return (
    <div style={{ position: "relative" }}>
      <button
        onClick={() => setIsOpen(!isOpen)}
        style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          padding: "6px 12px",
          background: "rgba(255,255,255,0.04)",
          border: `1px solid ${T.border}`,
          borderRadius: 6,
          color: T.secondary,
          fontSize: 10,
          fontFamily: FONTS.mono,
          cursor: "pointer",
          transition: "all 0.2s",
        }}
      >
        <span style={{ color: T.gold }}>⚖</span>
        WEIGHTS
      </button>

      {isOpen && (
        <div style={{
          position: "absolute",
          top: "100%",
          right: 0,
          marginTop: 8,
          padding: 16,
          background: T.deep,
          border: `1px solid ${T.border}`,
          borderRadius: 8,
          width: 280,
          zIndex: 100,
          boxShadow: "0 4px 24px rgba(0,0,0,0.12), 0 1px 6px rgba(255,255,255,0.06)",
        }}>
          <div style={{ fontSize: 11, fontWeight: 600, color: T.primary, marginBottom: 12, fontFamily: FONTS.display }}>
            Adjust Pillar Weights
          </div>

          {pillars.map(pillar => (
            <div key={pillar} style={{ marginBottom: 12 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
                <span style={{ fontSize: 10, color: colors[pillar], fontFamily: FONTS.mono, fontWeight: 600 }}>
                  {pillar}: {pillarLabels[pillar]}
                </span>
                <span style={{ fontSize: 10, color: T.primary, fontFamily: FONTS.mono }}>
                  {(localWeights[pillar] * 100).toFixed(0)}%
                </span>
              </div>
              <input
                type="range"
                min="0"
                max="0.5"
                step="0.05"
                value={localWeights[pillar]}
                onChange={(e) => handleSliderChange(pillar, e.target.value)}
                style={{
                  width: "100%",
                  height: 4,
                  appearance: "none",
                  background: T.border,
                  borderRadius: 2,
                  cursor: "pointer",
                }}
              />
            </div>
          ))}

          <div style={{ display: "flex", gap: 8, marginTop: 16 }}>
            <button
              onClick={resetWeights}
              style={{
                flex: 1,
                padding: "6px 12px",
                background: "transparent",
                border: `1px solid ${T.border}`,
                borderRadius: 4,
                color: T.secondary,
                fontSize: 10,
                cursor: "pointer",
              }}
            >
              RESET
            </button>
            <button
              onClick={applyWeights}
              style={{
                flex: 1,
                padding: "6px 12px",
                background: "rgba(200,168,75,0.15)",
                border: `1px solid ${T.gold}`,
                borderRadius: 4,
                color: T.gold,
                fontSize: 10,
                fontWeight: 600,
                cursor: "pointer",
              }}
            >
              APPLY
            </button>
          </div>

          <div style={{ fontSize: 9, color: T.muted, marginTop: 12, textAlign: "center" }}>
            Total: {(Object.values(localWeights).reduce((a, b) => a + b, 0) * 100).toFixed(0)}%
          </div>
        </div>
      )}
    </div>
  );
}

/* ─── Main CIS Component ───────────────────────────────────────────── */

export default function CISWidget({ refreshKey = 0, defaultLimit = 0 }) {
  const [data, setData] = useState(null);
  const [filter, setFilter] = useState("All");
  const [view, setView] = useState("leaderboard");
  const [loading, setLoading] = useState(false);
  const [dataSource, setDataSource] = useState("loading");
  const [customWeights, setCustomWeights] = useState(null);

  const pillarLabels = {
    F: "Fundamental",
    M: "Market",
    O: "On-Chain",
    S: "Sentiment",
    A: "Alpha",
  };

  const defaultWeights = { F: 0.25, M: 0.25, O: 0.20, S: 0.15, A: 0.15 };

  const [error, setError] = useState(null);

  const fetchData = async () => {
    setLoading(true);
    setError(null);
    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 45000);

      const response = await fetch(`${API_BASE}/cis/universe`, {
        signal: controller.signal
      });
      clearTimeout(timeoutId);

      if (response.ok) {
        const json = await response.json();
        setData(json);
        setDataSource(json.data_source || "coingecko+defillama");
      } else {
        throw new Error(`API error: ${response.status}`);
      }
    } catch (e) {
      console.error("CIS fetch error:", e.message);
      setError(e.message);
      setData(null);
    } finally {
      setLoading(false);
    }
  };

  // Auto-refresh every 5 minutes
  useEffect(() => {
    fetchData();

    const interval = setInterval(() => {
      fetchData();
    }, 5 * 60 * 1000);

    return () => clearInterval(interval);
  }, [refreshKey]);

  // Recalculate scores when custom weights change
  const processedData = useMemo(() => {
    if (!data) return null;
    const weights = customWeights || defaultWeights;

    const recalculated = data.universe.map(asset => {
      const newScore =
        weights.F * (asset.f ?? 0) +
        weights.M * (asset.m ?? 0) +
        weights.O * (asset.r ?? 0) +
        weights.S * (asset.s ?? 0) +
        weights.A * (asset.a ?? 0);

      let newGrade;
      if (newScore >= 85) newGrade = "A+";
      else if (newScore >= 75) newGrade = "A";
      else if (newScore >= 65) newGrade = "B+";
      else if (newScore >= 55) newGrade = "B";
      else if (newScore >= 45) newGrade = "C+";
      else if (newScore >= 35) newGrade = "C";
      else if (newScore >= 25) newGrade = "D";
      else newGrade = "F";

      let newSignal;
      if (newGrade === "A+" || newGrade === "A") newSignal = "STRONG OUTPERFORM";
      else if (newGrade === "B+" || newGrade === "B") newSignal = "OUTPERFORM";
      else if (newGrade === "C+" || newGrade === "C") newSignal = "NEUTRAL";
      else newSignal = "UNDERWEIGHT";

      return { ...asset, cis_score: newScore, grade: newGrade, signal: newSignal };
    });

    recalculated.sort((a, b) => b.cis_score - a.cis_score);
    return { ...data, universe: recalculated };
  }, [data, customWeights]);

  const handleWeightChange = (newWeights) => {
    setCustomWeights(newWeights);
  };

  return (
    <div className="fade-up" style={{ width: "100%", clear: "both" }}>
      {/* Header */}
      <div style={{ padding: "16px 0", borderBottom: `1px solid ${T.border}`, marginBottom: 16, display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: 16, width: "100%" }}>
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <h2 style={{ fontSize: 18, fontWeight: 700, color: T.primary, fontFamily: FONTS.display }}>CometCloud Intelligence Score</h2>
            <span style={{
              padding: "2px 8px",
              borderRadius: 4,
              fontSize: 10,
              fontWeight: 600,
              background: error ? "rgba(239,68,68,0.2)" : dataSource !== "loading" ? "rgba(34,197,94,0.2)" : "rgba(251,191,36,0.2)",
              color: error ? "#ef4444" : dataSource !== "loading" ? "#22c55e" : "#fbbf24"
            }}>
              {error ? "ERROR" : dataSource === "loading" ? "LOADING" : dataSource.toUpperCase()}
            </span>
          </div>
          <p style={{ fontSize: 11, color: T.secondary, marginTop: 4 }}>
            CIS v4.1 · Real-time API · {processedData?.universe?.length || 0} assets
            {customWeights && <span style={{ color: T.gold, marginLeft: 8 }}>Custom Weights</span>}
            {data?.timestamp && <span style={{ marginLeft: 8 }}>Updated: {new Date(data.timestamp).toLocaleString()}</span>}
          </p>
        </div>

        {/* Error Message */}
        {error && (
          <div style={{ width: "100%", padding: "12px 16px", background: "rgba(239,68,68,0.1)", border: "1px solid rgba(239,68,68,0.3)", borderRadius: 6, marginTop: 8 }}>
            <p style={{ fontSize: 12, color: "#ef4444", margin: 0 }}>
              <strong>Failed to load CIS data:</strong> {error}
            </p>
            <button
              onClick={fetchData}
              style={{
                marginTop: 8,
                padding: "6px 12px",
                background: "rgba(239,68,68,0.2)",
                border: "1px solid #ef4444",
                borderRadius: 4,
                color: "#ef4444",
                fontSize: 11,
                cursor: "pointer"
              }}
            >
              Retry
            </button>
          </div>
        )}

        {/* Controls */}
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <WeightAdjuster
            weights={customWeights || defaultWeights}
            onChange={handleWeightChange}
            pillarLabels={pillarLabels}
          />
          {[
            { id: "leaderboard", label: "Leaderboard" },
            { id: "heatmap", label: "Heatmap" },
          ].map(v => (
            <button
              key={v.id}
              onClick={() => setView(v.id)}
              className="lm-tab"
              style={{
                borderColor: view === v.id ? T.violet : T.border,
                background: view === v.id ? "rgba(107,15,204,0.12)" : "transparent",
                color: view === v.id ? "#c4b5fd" : T.secondary,
              }}
            >
              {v.label}
            </button>
          ))}
        </div>
      </div>

      {/* Macro Banner */}
      <CISMacroBanner macro={data?.macro} />

      {/* Loading */}
      {loading && (
        <div style={{ padding: 40, textAlign: "center", color: T.secondary }}>
          Loading CIS data...
        </div>
      )}

      {/* Content */}
      {!loading && (
        <>
          {view === "leaderboard" && (
            <CISLeaderboardTable data={processedData} filter={filter} setFilter={setFilter} defaultLimit={defaultLimit} />
          )}
          {view === "heatmap" && (
            <CISHeatmap data={processedData} filter={filter} setFilter={setFilter} />
          )}
        </>
      )}
    </div>
  );
}
