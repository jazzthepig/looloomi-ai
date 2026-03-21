/**
 * MobileApp.jsx — CometCloud Mobile Experience
 * 化繁为简: Three questions, answered immediately.
 * 1. Is the market safe? (Macro regime)
 * 2. What's worth watching? (Top CIS signals)
 * 3. What's moving? (Prices + signal feed)
 *
 * Bottom nav: PULSE | RANKINGS | SIGNALS
 */
import { useState, useEffect, useCallback } from "react";
import { T, FONTS } from "../tokens";

/* ── Design constants ─────────────────────────────────────────────────────── */
const GRADE_COLOR = {
  "A+": "#00E87A", A:  "#00E87A",
  "B+": "#4B9EFF", B:  "#4B9EFF",
  "C+": "#E8A000", C:  "#E8A000",
  D:    "#FF3D5A", F:  "#888",
};

const SIGNAL_COLOR = {
  "STRONG BUY": "#00E87A",
  BUY:          "#4B9EFF",
  HOLD:         "rgba(255,255,255,0.4)",
  REDUCE:       "#E8A000",
  AVOID:        "#FF3D5A",
};

const REGIME_CONFIG = {
  RISK_ON:      { label: "RISK ON",      color: "#00E87A", bg: "rgba(0,232,122,0.08)",  desc: "Favorable conditions" },
  RISK_OFF:     { label: "RISK OFF",     color: "#FF3D5A", bg: "rgba(255,61,90,0.08)",  desc: "Defensive posture recommended" },
  TIGHTENING:   { label: "TIGHTENING",   color: "#E8A000", bg: "rgba(232,160,0,0.08)",  desc: "Monetary tightening" },
  EASING:       { label: "EASING",       color: "#4B9EFF", bg: "rgba(75,158,255,0.08)", desc: "Monetary easing" },
  STAGFLATION:  { label: "STAGFLATION",  color: "#FF8C42", bg: "rgba(255,140,66,0.08)", desc: "Stagflation regime" },
  GOLDILOCKS:   { label: "GOLDILOCKS",   color: "#C8A84B", bg: "rgba(200,168,75,0.08)", desc: "Goldilocks environment" },
};

const ASSET_CLASS_COLOR = {
  L1:             "#00C8E0",
  L2:             "#9945FF",
  DeFi:           "#4472FF",
  RWA:            "#E8A000",
  Infrastructure: "#00D98A",
  "US Equity":    "#4B9EFF",
  "US Bond":      "#F59E0B",
  Commodity:      "#C8A84B",
};

/* ── Skeleton shimmer ─────────────────────────────────────────────────────── */
function Shimmer({ width = "100%", height = 14, radius = 4 }) {
  return (
    <div style={{
      width, height,
      borderRadius: radius,
      background: "linear-gradient(90deg, #0e1424 25%, #16132e 50%, #0e1424 75%)",
      backgroundSize: "400px 100%",
      animation: "mobileShimmer 1.6s ease infinite",
    }} />
  );
}

/* ── Grade badge ──────────────────────────────────────────────────────────── */
function GradeBadge({ grade, size = 14 }) {
  const color = GRADE_COLOR[grade] || "#888";
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", justifyContent: "center",
      width: size + 12, height: size + 10,
      borderRadius: 4,
      background: `${color}18`,
      border: `1px solid ${color}40`,
      color,
      fontSize: size,
      fontWeight: 700,
      fontFamily: FONTS.mono,
      flexShrink: 0,
    }}>
      {grade}
    </span>
  );
}

/* ── Sparkline (inline SVG) ───────────────────────────────────────────────── */
function Sparkline({ data = [], color = "#4B9EFF", width = 52, height = 20 }) {
  if (!data || data.length < 2) return <div style={{ width, height }} />;
  const vals = data.map(d => (typeof d === "number" ? d : d?.close || 0));
  const min = Math.min(...vals);
  const max = Math.max(...vals);
  const range = max - min || 1;
  const pts = vals.map((v, i) =>
    `${(i / (vals.length - 1)) * width},${height - ((v - min) / range) * height}`
  ).join(" ");
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} style={{ display: "block", overflow: "visible" }}>
      <polyline
        points={pts}
        fill="none"
        stroke={color}
        strokeWidth="1.5"
        strokeLinejoin="round"
        strokeLinecap="round"
        opacity={0.8}
      />
    </svg>
  );
}

/* ── Format helpers ───────────────────────────────────────────────────────── */
function formatAge(seconds) {
  if (!seconds || seconds < 0) return "—";
  if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`;
  return `${Math.round(seconds / 3600)}h ago`;
}

function pct(v) {
  if (v == null || isNaN(v)) return "—";
  const sign = v >= 0 ? "+" : "";
  return `${sign}${v.toFixed(2)}%`;
}

/* ═══════════════════════════════════════════════════════════════════════════
   TAB 1: PULSE
   ═══════════════════════════════════════════════════════════════════════════ */
function MobilePulse({ universe, macro, signals, sparkData, loading }) {
  const regime = universe.find(a => a.macro_regime)?.macro_regime
    || universe[0]?.macro_regime
    || null;
  const regimeCfg = REGIME_CONFIG[regime] || null;

  /* Top signals: A+/A/B+ grade assets with BUY or STRONG BUY */
  const topSignals = [...universe]
    .sort((a, b) => {
      const gradeOrder = ["A+", "A", "B+", "B", "C+", "C", "D", "F"];
      return gradeOrder.indexOf(a.grade) - gradeOrder.indexOf(b.grade);
    })
    .slice(0, 6);

  /* Macro brief summary — first ~280 chars */
  const briefSnippet = macro?.brief
    ? macro.brief.slice(0, 280).replace(/\n/g, " ").trim() + (macro.brief.length > 280 ? "…" : "")
    : null;

  return (
    <div style={{ padding: "16px 16px 0" }}>

      {/* ── Regime Banner ──────────────────────────────────────────────────── */}
      {loading ? (
        <div style={{ marginBottom: 16 }}>
          <Shimmer height={56} radius={10} />
        </div>
      ) : regimeCfg ? (
        <div style={{
          background: regimeCfg.bg,
          border: `1px solid ${regimeCfg.color}30`,
          borderLeft: `3px solid ${regimeCfg.color}`,
          borderRadius: 10,
          padding: "14px 16px",
          marginBottom: 16,
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
        }}>
          <div>
            <div style={{
              fontFamily: FONTS.display,
              fontSize: 11,
              fontWeight: 700,
              letterSpacing: "0.14em",
              color: regimeCfg.color,
              textTransform: "uppercase",
              marginBottom: 2,
            }}>
              {regimeCfg.label}
            </div>
            <div style={{ fontFamily: FONTS.body, fontSize: 12, color: T.t2 }}>
              {regimeCfg.desc}
            </div>
          </div>
          <div style={{
            width: 36, height: 36, borderRadius: "50%",
            background: `${regimeCfg.color}15`,
            border: `1px solid ${regimeCfg.color}30`,
            display: "flex", alignItems: "center", justifyContent: "center",
          }}>
            <span style={{ fontSize: 16 }}>
              {regime === "RISK_ON" || regime === "GOLDILOCKS" ? "↑" :
               regime === "RISK_OFF" || regime === "STAGFLATION" ? "↓" : "→"}
            </span>
          </div>
        </div>
      ) : (
        <div style={{
          background: T.surface,
          border: `1px solid ${T.border}`,
          borderRadius: 10,
          padding: "14px 16px",
          marginBottom: 16,
        }}>
          <span style={{ fontFamily: FONTS.display, fontSize: 11, color: T.t3, letterSpacing: "0.1em" }}>
            REGIME · LOADING
          </span>
        </div>
      )}

      {/* ── Macro Brief ────────────────────────────────────────────────────── */}
      {macro?.brief && (
        <div style={{
          background: "rgba(10,9,24,0.8)",
          border: `1px solid ${T.border}`,
          borderLeft: `2px solid #06B6D4`,
          borderRadius: 10,
          padding: "12px 14px",
          marginBottom: 16,
        }}>
          <div style={{
            fontFamily: FONTS.display, fontSize: 9, fontWeight: 700,
            letterSpacing: "0.14em", color: "#06B6D4",
            textTransform: "uppercase", marginBottom: 8,
            display: "flex", alignItems: "center", gap: 6,
          }}>
            <span style={{
              width: 6, height: 6, borderRadius: "50%",
              background: "#06B6D4", display: "inline-block",
              animation: "mobileGlow 2s ease-in-out infinite",
            }} />
            MACRO BRIEF
            <span style={{ marginLeft: "auto", fontFamily: FONTS.mono, color: T.t3, fontSize: 9 }}>
              {formatAge(macro.age_seconds)}
            </span>
          </div>
          <div style={{
            fontFamily: FONTS.body, fontSize: 12, lineHeight: 1.65,
            color: T.t1, opacity: 0.85,
          }}>
            {briefSnippet}
          </div>
        </div>
      )}

      {/* ── Section label ──────────────────────────────────────────────────── */}
      <div style={{
        fontFamily: FONTS.display, fontSize: 9, fontWeight: 700,
        letterSpacing: "0.16em", color: T.t3, textTransform: "uppercase",
        marginBottom: 10,
        display: "flex", alignItems: "center", gap: 8,
      }}>
        <span>TOP SIGNALS</span>
        <div style={{ flex: 1, height: 1, background: T.border }} />
        <span style={{ fontFamily: FONTS.mono }}>{universe.length} assets</span>
      </div>

      {/* ── Top Signal Cards ───────────────────────────────────────────────── */}
      {loading ? (
        <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 16 }}>
          {[1, 2, 3, 4].map(i => (
            <Shimmer key={i} height={64} radius={10} />
          ))}
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 8, marginBottom: 20 }}>
          {topSignals.map((asset, idx) => {
            const gradeColor = GRADE_COLOR[asset.grade] || "#888";
            const sigColor = SIGNAL_COLOR[asset.signal] || T.t3;
            const classColor = ASSET_CLASS_COLOR[asset.asset_class] || T.t3;
            const spark = sparkData?.[asset.symbol] || sparkData?.[asset.asset] || null;
            const score = asset.cis_score ?? asset.total_score;
            const change = asset.price_change_24h ?? null;

            return (
              <div key={asset.symbol || asset.asset || idx} style={{
                background: T.surface,
                border: `1px solid ${T.border}`,
                borderRadius: 10,
                padding: "12px 14px",
                display: "flex",
                alignItems: "center",
                gap: 12,
                position: "relative",
                overflow: "hidden",
              }}>
                {/* Grade accent line */}
                <div style={{
                  position: "absolute", left: 0, top: 0, bottom: 0,
                  width: 3, borderRadius: "10px 0 0 10px",
                  background: gradeColor,
                  opacity: 0.7,
                }} />

                {/* Rank */}
                <div style={{
                  fontFamily: FONTS.mono, fontSize: 10, color: T.t3,
                  minWidth: 16, textAlign: "center",
                }}>
                  {idx + 1}
                </div>

                {/* Grade badge */}
                <GradeBadge grade={asset.grade} size={13} />

                {/* Name + class */}
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{
                    fontFamily: FONTS.display, fontSize: 14, fontWeight: 700,
                    color: T.t1, lineHeight: 1.2,
                    overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                  }}>
                    {asset.symbol || asset.asset}
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: 5, marginTop: 2 }}>
                    {asset.asset_class && (
                      <span style={{
                        fontFamily: FONTS.mono, fontSize: 8, fontWeight: 600,
                        letterSpacing: "0.06em", color: classColor,
                        textTransform: "uppercase",
                      }}>
                        {asset.asset_class}
                      </span>
                    )}
                    <span style={{
                      fontFamily: FONTS.mono, fontSize: 9,
                      color: sigColor, opacity: 0.85,
                    }}>
                      {asset.signal}
                    </span>
                  </div>
                </div>

                {/* Sparkline */}
                {spark?.length > 1 && (
                  <div style={{ flexShrink: 0 }}>
                    <Sparkline data={spark} color={gradeColor} width={44} height={18} />
                  </div>
                )}

                {/* Score + 24h */}
                <div style={{ textAlign: "right", flexShrink: 0 }}>
                  <div style={{
                    fontFamily: FONTS.mono, fontSize: 16, fontWeight: 400,
                    color: score >= 70 ? T.green : score >= 50 ? T.blue : T.amber,
                    lineHeight: 1,
                  }}>
                    {score != null ? (score).toFixed(0) : "—"}
                  </div>
                  {change != null && (
                    <div style={{
                      fontFamily: FONTS.mono, fontSize: 10,
                      color: change >= 0 ? T.green : T.red,
                      marginTop: 2,
                    }}>
                      {pct(change)}
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* ── Latest Signals ─────────────────────────────────────────────────── */}
      {signals.length > 0 && (
        <>
          <div style={{
            fontFamily: FONTS.display, fontSize: 9, fontWeight: 700,
            letterSpacing: "0.16em", color: T.t3, textTransform: "uppercase",
            marginBottom: 10,
            display: "flex", alignItems: "center", gap: 8,
          }}>
            <span>RECENT SIGNALS</span>
            <div style={{ flex: 1, height: 1, background: T.border }} />
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 6, marginBottom: 20 }}>
            {signals.slice(0, 4).map((sig, i) => {
              const typeColors = {
                MACRO:      { color: "#06B6D4", bg: "rgba(6,182,212,0.08)" },
                FUNDING:    { color: "#4B9EFF", bg: "rgba(75,158,255,0.08)" },
                REGULATORY: { color: "#FF8C42", bg: "rgba(255,140,66,0.08)" },
                TECHNICAL:  { color: "#A78BFA", bg: "rgba(167,139,250,0.08)" },
                ONCHAIN:    { color: "#00D98A", bg: "rgba(0,217,138,0.08)" },
                SOCIAL:     { color: "#E8A000", bg: "rgba(232,160,0,0.08)" },
              };
              const tc = typeColors[sig.type] || typeColors.MACRO;
              return (
                <div key={i} style={{
                  background: T.surface,
                  border: `1px solid ${T.border}`,
                  borderRadius: 8,
                  padding: "10px 12px",
                }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 4 }}>
                    <span style={{
                      fontFamily: FONTS.mono, fontSize: 8, fontWeight: 700,
                      letterSpacing: "0.08em", padding: "2px 6px",
                      borderRadius: 3, background: tc.bg, color: tc.color,
                      textTransform: "uppercase",
                    }}>
                      {sig.type}
                    </span>
                    {sig.importance === "HIGH" && (
                      <span style={{
                        fontFamily: FONTS.mono, fontSize: 8,
                        color: T.amber, letterSpacing: "0.06em",
                      }}>
                        HIGH
                      </span>
                    )}
                    <span style={{
                      fontFamily: FONTS.mono, fontSize: 9, color: T.t3, marginLeft: "auto",
                    }}>
                      {sig.source}
                    </span>
                  </div>
                  <div style={{
                    fontFamily: FONTS.body, fontSize: 12, lineHeight: 1.5,
                    color: T.t1, opacity: 0.85,
                  }}>
                    {sig.description}
                  </div>
                </div>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   TAB 2: RANKINGS
   ═══════════════════════════════════════════════════════════════════════════ */
function MobileRankings({ universe, loading }) {
  const [filter, setFilter] = useState("ALL");
  const [expanded, setExpanded] = useState(null);

  const filters = ["ALL", "Crypto", "TradFi"];
  const cryptoClasses = new Set(["L1","L2","DeFi","RWA","Infrastructure","Oracle","Memecoin","AI"]);

  const filtered = universe.filter(a => {
    if (filter === "ALL") return true;
    if (filter === "Crypto") return cryptoClasses.has(a.asset_class);
    if (filter === "TradFi") return !cryptoClasses.has(a.asset_class) && a.asset_class;
    return true;
  });

  return (
    <div style={{ padding: "16px 16px 0" }}>
      {/* Filter tabs */}
      <div style={{
        display: "flex", gap: 4,
        background: T.raised, borderRadius: 8, padding: 3,
        border: `1px solid ${T.border}`,
        marginBottom: 14,
      }}>
        {filters.map(f => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            style={{
              flex: 1, padding: "7px 0",
              borderRadius: 5, fontSize: 11, fontWeight: 700,
              fontFamily: FONTS.display, cursor: "pointer",
              outline: "none",
              border: "1px solid transparent",
              background: filter === f ? T.goldDim : "transparent",
              color: filter === f ? T.gold : T.t3,
              transition: "all 0.15s",
              letterSpacing: "0.06em",
            }}
          >
            {f}
          </button>
        ))}
      </div>

      {/* Stats row */}
      <div style={{
        display: "flex", gap: 12, marginBottom: 14,
        fontFamily: FONTS.mono, fontSize: 9, color: T.t3,
      }}>
        {["A","B","C","D"].map(g => {
          const count = filtered.filter(a => a.grade?.startsWith(g)).length;
          const color = { A: T.green, B: T.blue, C: T.amber, D: T.red }[g];
          if (!count) return null;
          return (
            <span key={g} style={{ color }}>
              {g}: {count}
            </span>
          );
        })}
        <span style={{ marginLeft: "auto" }}>{filtered.length} assets</span>
      </div>

      {/* Asset list */}
      {loading ? (
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {[1,2,3,4,5,6,7].map(i => <Shimmer key={i} height={54} radius={8} />)}
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
          {filtered.map((asset, idx) => {
            const score = asset.cis_score ?? asset.total_score;
            const gradeColor = GRADE_COLOR[asset.grade] || "#888";
            const classColor = ASSET_CLASS_COLOR[asset.asset_class] || T.t3;
            const isOpen = expanded === (asset.symbol || asset.asset);
            const pillars = asset.pillars || {};

            return (
              <div key={asset.symbol || asset.asset || idx}>
                <div
                  onClick={() => setExpanded(isOpen ? null : (asset.symbol || asset.asset))}
                  style={{
                    background: isOpen ? T.card : T.surface,
                    border: `1px solid ${isOpen ? gradeColor + "40" : T.border}`,
                    borderRadius: isOpen ? "8px 8px 0 0" : 8,
                    padding: "10px 12px",
                    display: "flex", alignItems: "center", gap: 10,
                    cursor: "pointer",
                    transition: "all 0.15s",
                  }}
                >
                  {/* Rank */}
                  <div style={{
                    fontFamily: FONTS.mono, fontSize: 9, color: T.t3,
                    minWidth: 20, textAlign: "right",
                  }}>
                    {idx + 1}
                  </div>

                  {/* Grade */}
                  <GradeBadge grade={asset.grade} size={12} />

                  {/* Name + class */}
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{
                      fontFamily: FONTS.display, fontSize: 13, fontWeight: 700,
                      color: T.t1, lineHeight: 1.2,
                    }}>
                      {asset.symbol || asset.asset}
                    </div>
                    {asset.asset_class && (
                      <div style={{
                        fontFamily: FONTS.mono, fontSize: 8,
                        color: classColor, marginTop: 1,
                        textTransform: "uppercase", letterSpacing: "0.06em",
                      }}>
                        {asset.asset_class}
                      </div>
                    )}
                  </div>

                  {/* Signal */}
                  <div style={{
                    fontFamily: FONTS.mono, fontSize: 9,
                    color: SIGNAL_COLOR[asset.signal] || T.t3,
                    textAlign: "right", flexShrink: 0,
                    maxWidth: 60,
                  }}>
                    {asset.signal}
                  </div>

                  {/* Score */}
                  <div style={{
                    fontFamily: FONTS.mono, fontSize: 16, fontWeight: 400,
                    color: score >= 70 ? T.green : score >= 50 ? T.blue : T.amber,
                    minWidth: 36, textAlign: "right", flexShrink: 0,
                  }}>
                    {score != null ? Number(score).toFixed(0) : "—"}
                  </div>

                  {/* Expand icon */}
                  <div style={{
                    fontSize: 10, color: T.t3, flexShrink: 0,
                    transform: isOpen ? "rotate(180deg)" : "none",
                    transition: "transform 0.2s",
                  }}>
                    ▾
                  </div>
                </div>

                {/* Expanded detail */}
                {isOpen && (
                  <div style={{
                    background: T.card,
                    border: `1px solid ${gradeColor}40`,
                    borderTop: "none",
                    borderRadius: "0 0 8px 8px",
                    padding: "12px 14px",
                  }}>
                    {/* Asset name */}
                    <div style={{
                      fontFamily: FONTS.body, fontSize: 11, color: T.t2,
                      marginBottom: 12,
                    }}>
                      {asset.name || asset.asset_name || (asset.symbol || asset.asset)}
                      {asset.asset_class && (
                        <span style={{ color: classColor, marginLeft: 8 }}>
                          {asset.asset_class}
                        </span>
                      )}
                    </div>

                    {/* Pillar bars */}
                    {Object.keys(pillars).length > 0 && (
                      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                        {[
                          { key: "fundamental", label: "F · Fundamental" },
                          { key: "momentum",    label: "M · Momentum" },
                          { key: "onchain",     label: "O · On-Chain" },
                          { key: "sentiment",   label: "S · Sentiment" },
                          { key: "alpha",       label: "A · Alpha" },
                        ].map(({ key, label }) => {
                          const val = pillars[key];
                          if (val == null) return null;
                          const pctW = Math.max(0, Math.min(100, val));
                          const barColor = val >= 70 ? T.green : val >= 50 ? T.blue : T.amber;
                          return (
                            <div key={key}>
                              <div style={{
                                display: "flex", justifyContent: "space-between",
                                marginBottom: 3,
                              }}>
                                <span style={{
                                  fontFamily: FONTS.mono, fontSize: 9, color: T.t3,
                                  letterSpacing: "0.04em",
                                }}>
                                  {label}
                                </span>
                                <span style={{
                                  fontFamily: FONTS.mono, fontSize: 9, color: barColor,
                                }}>
                                  {Number(val).toFixed(1)}
                                </span>
                              </div>
                              <div style={{
                                height: 3, background: "rgba(255,255,255,0.06)",
                                borderRadius: 2,
                              }}>
                                <div style={{
                                  width: `${pctW}%`, height: "100%",
                                  background: barColor, borderRadius: 2,
                                  opacity: 0.75,
                                }} />
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    )}

                    {/* Percentile + rank */}
                    {(asset.global_rank || asset.percentile_rank != null) && (
                      <div style={{
                        display: "flex", gap: 16, marginTop: 12,
                        fontFamily: FONTS.mono, fontSize: 9, color: T.t3,
                      }}>
                        {asset.global_rank && (
                          <span>Rank #{asset.global_rank}</span>
                        )}
                        {asset.percentile_rank != null && (
                          <span>Top {(100 - asset.percentile_rank).toFixed(0)}%</span>
                        )}
                      </div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      <div style={{ height: 16 }} />
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   TAB 3: SIGNALS
   ═══════════════════════════════════════════════════════════════════════════ */
function MobileSignals({ signals, loading }) {
  const TYPE_COLORS = {
    MACRO:      { color: "#06B6D4", bg: "rgba(6,182,212,0.08)",   border: "rgba(6,182,212,0.18)" },
    FUNDING:    { color: "#4B9EFF", bg: "rgba(75,158,255,0.08)",  border: "rgba(75,158,255,0.18)" },
    REGULATORY: { color: "#FF8C42", bg: "rgba(255,140,66,0.08)",  border: "rgba(255,140,66,0.18)" },
    TECHNICAL:  { color: "#A78BFA", bg: "rgba(167,139,250,0.08)", border: "rgba(167,139,250,0.18)" },
    ONCHAIN:    { color: "#00D98A", bg: "rgba(0,217,138,0.08)",   border: "rgba(0,217,138,0.18)" },
    SOCIAL:     { color: "#E8A000", bg: "rgba(232,160,0,0.08)",   border: "rgba(232,160,0,0.18)" },
  };

  return (
    <div style={{ padding: "16px 16px 0" }}>
      {loading ? (
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {[1,2,3,4,5].map(i => <Shimmer key={i} height={80} radius={10} />)}
        </div>
      ) : signals.length === 0 ? (
        <div style={{
          textAlign: "center", padding: "60px 20px",
          fontFamily: FONTS.body, fontSize: 13, color: T.t3,
        }}>
          No signals available
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {signals.map((sig, i) => {
            const tc = TYPE_COLORS[sig.type] || TYPE_COLORS.MACRO;
            const impHigh = sig.importance === "HIGH" || sig.importance === "CRITICAL";

            return (
              <div key={i} style={{
                background: T.surface,
                border: `1px solid ${impHigh ? tc.border : T.border}`,
                borderRadius: 10,
                padding: "12px 14px",
              }}>
                {/* Header */}
                <div style={{
                  display: "flex", alignItems: "center", gap: 6,
                  marginBottom: 8,
                  flexWrap: "wrap",
                }}>
                  <span style={{
                    fontFamily: FONTS.mono, fontSize: 8, fontWeight: 700,
                    letterSpacing: "0.1em", padding: "2px 7px",
                    borderRadius: 3, background: tc.bg,
                    color: tc.color, textTransform: "uppercase",
                    border: `1px solid ${tc.border}`,
                  }}>
                    {sig.type}
                  </span>
                  {impHigh && (
                    <span style={{
                      fontFamily: FONTS.mono, fontSize: 8, fontWeight: 700,
                      color: T.amber, letterSpacing: "0.08em",
                      background: "rgba(245,158,11,0.08)",
                      padding: "2px 6px", borderRadius: 3,
                      border: "1px solid rgba(245,158,11,0.2)",
                    }}>
                      {sig.importance}
                    </span>
                  )}
                  <span style={{
                    fontFamily: FONTS.mono, fontSize: 9, color: T.t3,
                    marginLeft: "auto",
                  }}>
                    {sig.source}
                  </span>
                </div>

                {/* Body */}
                <div style={{
                  fontFamily: FONTS.body, fontSize: 13, lineHeight: 1.6,
                  color: T.t1, opacity: 0.88,
                  marginBottom: sig.affected_assets?.length ? 8 : 0,
                }}>
                  {sig.description}
                </div>

                {/* Affected assets */}
                {sig.affected_assets?.length > 0 && (
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
                    {sig.affected_assets.slice(0, 6).map(a => (
                      <span key={a} style={{
                        fontFamily: FONTS.mono, fontSize: 9,
                        padding: "2px 6px", borderRadius: 3,
                        background: T.raised,
                        border: `1px solid ${T.border}`,
                        color: T.t2,
                      }}>
                        {a}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
      <div style={{ height: 16 }} />
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   ROOT: MobileApp
   ═══════════════════════════════════════════════════════════════════════════ */
export default function MobileApp() {
  const [tab, setTab] = useState("pulse");
  const [universe, setUniverse] = useState([]);
  const [macro, setMacro] = useState(null);
  const [signals, setSignals] = useState([]);
  const [sparkData, setSparkData] = useState({});
  const [loading, setLoading] = useState(true);

  /* ── Fetch all data in parallel ──────────────────────────────────────── */
  useEffect(() => {
    const controller = new AbortController();

    const fetchAll = async () => {
      try {
        const [cisRes, macroRes, sigRes] = await Promise.allSettled([
          fetch("/api/v1/cis/universe", { signal: controller.signal }),
          fetch("/api/v1/macro/brief",  { signal: controller.signal }),
          fetch("/api/v1/signals",      { signal: controller.signal }),
        ]);

        if (cisRes.status === "fulfilled" && cisRes.value.ok) {
          const json = await cisRes.value.json();
          const assets = json.universe || json.assets || json || [];
          setUniverse(assets);

          // Fetch sparklines for top 6 assets
          const top6 = [...assets]
            .sort((a, b) => {
              const go = ["A+","A","B+","B","C+","C","D","F"];
              return go.indexOf(a.grade) - go.indexOf(b.grade);
            })
            .slice(0, 6)
            .map(a => a.symbol || a.asset)
            .filter(Boolean);

          if (top6.length) {
            const sparkRes = await fetch(
              `/api/v1/cis/history/batch?symbols=${top6.join(",")}&days=7`,
              { signal: controller.signal }
            ).catch(() => null);
            if (sparkRes?.ok) {
              const sd = await sparkRes.json();
              setSparkData(sd || {});
            }
          }
        }

        if (macroRes.status === "fulfilled" && macroRes.value.ok) {
          const json = await macroRes.value.json();
          setMacro(json);
        }

        if (sigRes.status === "fulfilled" && sigRes.value.ok) {
          const json = await sigRes.value.json();
          setSignals(json.signals || []);
        }
      } finally {
        setLoading(false);
      }
    };

    fetchAll();

    // Refresh every 5 minutes
    const interval = setInterval(fetchAll, 300_000);
    return () => {
      controller.abort();
      clearInterval(interval);
    };
  }, []);

  const TABS = [
    { id: "pulse",    label: "PULSE",    icon: "◎" },
    { id: "rankings", label: "RANKINGS", icon: "≡" },
    { id: "signals",  label: "SIGNALS",  icon: "⚡" },
  ];

  return (
    <div style={{
      background: "#030508",
      minHeight: "100dvh",
      display: "flex",
      flexDirection: "column",
      position: "relative",
    }}>
      {/* Ambient glow — simplified for mobile */}
      <div style={{
        position: "fixed", inset: 0, zIndex: 0, pointerEvents: "none",
        background: "radial-gradient(ellipse 80% 40% at 50% 0%, rgba(0,232,122,0.05) 0%, transparent 60%)",
      }} />

      {/* Top header */}
      <div style={{
        position: "fixed", top: 0, left: 0, right: 0, zIndex: 100,
        background: "rgba(3,5,8,0.92)",
        backdropFilter: "blur(20px)",
        WebkitBackdropFilter: "blur(20px)",
        borderBottom: `1px solid ${T.border}`,
        padding: "12px 16px",
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
      }}>
        <span style={{
          fontFamily: FONTS.display, fontWeight: 700, fontSize: 16,
          letterSpacing: "0.12em", color: T.gold,
        }}>
          COMETCLOUD
        </span>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          {/* Engine source indicator */}
          {!loading && universe.length > 0 && (
            <span style={{
              fontFamily: FONTS.mono, fontSize: 8, fontWeight: 700,
              letterSpacing: "0.08em", padding: "2px 7px",
              borderRadius: 3,
              background: "rgba(0,232,122,0.08)",
              color: T.green,
              border: "1px solid rgba(0,232,122,0.15)",
            }}>
              CIS LIVE
            </span>
          )}
          <span style={{
            fontFamily: FONTS.mono, fontSize: 9, color: T.t3,
          }}>
            {universe.length > 0 ? `${universe.length} assets` : ""}
          </span>
        </div>
      </div>

      {/* Scrollable content area */}
      <div style={{
        flex: 1,
        overflowY: "auto",
        paddingTop: 52,  /* header height */
        paddingBottom: 68, /* bottom nav height */
        position: "relative",
        zIndex: 1,
        WebkitOverflowScrolling: "touch",
      }}>
        {tab === "pulse"    && <MobilePulse    universe={universe} macro={macro} signals={signals} sparkData={sparkData} loading={loading} />}
        {tab === "rankings" && <MobileRankings universe={universe} loading={loading} />}
        {tab === "signals"  && <MobileSignals  signals={signals} loading={loading} />}
      </div>

      {/* Bottom navigation */}
      <div style={{
        position: "fixed", bottom: 0, left: 0, right: 0, zIndex: 100,
        background: "rgba(3,5,8,0.95)",
        backdropFilter: "blur(20px)",
        WebkitBackdropFilter: "blur(20px)",
        borderTop: `1px solid ${T.border}`,
        display: "flex",
        paddingBottom: "env(safe-area-inset-bottom, 0px)",
      }}>
        {TABS.map(({ id, label, icon }) => {
          const active = tab === id;
          return (
            <button
              key={id}
              onClick={() => setTab(id)}
              style={{
                flex: 1,
                display: "flex",
                flexDirection: "column",
                alignItems: "center",
                justifyContent: "center",
                padding: "12px 0",
                gap: 3,
                background: "transparent",
                border: "none",
                cursor: "pointer",
                outline: "none",
                position: "relative",
              }}
            >
              {/* Active indicator */}
              {active && (
                <div style={{
                  position: "absolute", top: 0, left: "30%", right: "30%",
                  height: 2, borderRadius: "0 0 2px 2px",
                  background: T.gold,
                }} />
              )}
              <span style={{
                fontSize: 16, lineHeight: 1,
                color: active ? T.gold : T.t3,
                filter: active ? `drop-shadow(0 0 6px ${T.gold}60)` : "none",
              }}>
                {icon}
              </span>
              <span style={{
                fontFamily: FONTS.display,
                fontSize: 9,
                fontWeight: 700,
                letterSpacing: "0.1em",
                color: active ? T.gold : T.t3,
              }}>
                {label}
              </span>
            </button>
          );
        })}
      </div>

      {/* Global mobile styles */}
      <style>{`
        @keyframes mobileShimmer {
          0%   { background-position: -400px 0; }
          100% { background-position: 400px 0; }
        }
        @keyframes mobileGlow {
          0%, 100% { opacity: 1; }
          50%       { opacity: 0.4; }
        }
        * { -webkit-tap-highlight-color: transparent; box-sizing: border-box; }
        body { background: #030508; }
      `}</style>
    </div>
  );
}
