import { useState, useEffect, useCallback, useRef } from "react";
import { T, FONTS } from "../tokens";

/* ─── Signal Types ───────────────────────────────────────────────────── */
const SIGNAL_TYPES = {
  MACRO:      { label: "MACRO",      color: T.gold,    bg: "rgba(200,168,75,0.12)",  border: "rgba(200,168,75,0.2)"  },
  WHALE:      { label: "WHALE",      color: T.purple,  bg: "rgba(167,139,250,0.12)", border: "rgba(167,139,250,0.2)" },
  FUNDING:    { label: "FUNDING",    color: T.blue,    bg: "rgba(75,158,255,0.10)",  border: "rgba(75,158,255,0.2)"  },
  FLOW:       { label: "FLOW",       color: T.green,   bg: "rgba(0,232,122,0.08)",   border: "rgba(0,232,122,0.2)"   },
  RISK:       { label: "RISK",       color: T.red,     bg: "rgba(255,61,90,0.10)",   border: "rgba(255,61,90,0.2)"   },
  MOMENTUM:   { label: "MOMENTUM",   color: T.cyan,    bg: "rgba(0,200,224,0.10)",   border: "rgba(0,200,224,0.2)"   },
  REGULATORY: { label: "REGULATORY", color: "#FF8C42", bg: "rgba(255,140,66,0.10)",  border: "rgba(255,140,66,0.2)"  },
  CIS:        { label: "CIS",        color: "#A78BFA", bg: "rgba(167,139,250,0.10)", border: "rgba(167,139,250,0.2)" },
};

const IMPORTANCE_STYLES = {
  HIGH: { color: T.red,  bg: "rgba(255,61,90,0.12)",   border: "rgba(255,61,90,0.25)" },
  MED:  { color: T.gold, bg: "rgba(200,168,75,0.10)",  border: "rgba(200,168,75,0.2)" },
  LOW:  { color: T.t3,   bg: "rgba(255,255,255,0.04)", border: T.border },
};

const DIRECTION_STYLES = {
  BULLISH:     { color: T.green,  bg: "rgba(0,232,122,0.10)",   border: "rgba(0,232,122,0.25)",   icon: "↑" },
  BEARISH:     { color: T.red,    bg: "rgba(255,61,90,0.10)",   border: "rgba(255,61,90,0.25)",   icon: "↓" },
  CONTRARIAN:  { color: "#A78BFA",bg: "rgba(167,139,250,0.10)", border: "rgba(167,139,250,0.25)", icon: "⟳" },
  MIXED:       { color: T.gold,   bg: "rgba(200,168,75,0.10)",  border: "rgba(200,168,75,0.2)",   icon: "↕" },
  NEUTRAL:     { color: T.t3,     bg: "rgba(255,255,255,0.04)", border: T.border,                 icon: "—" },
};

const HORIZON_STYLES = {
  "IMMEDIATE": { color: T.red,   bg: "rgba(255,61,90,0.08)",   border: "rgba(255,61,90,0.2)"   },
  "24H":       { color: T.cyan,  bg: "rgba(0,200,224,0.08)",   border: "rgba(0,200,224,0.2)"   },
  "7D":        { color: T.gold,  bg: "rgba(200,168,75,0.08)",  border: "rgba(200,168,75,0.2)"  },
  "30D":       { color: T.green, bg: "rgba(0,232,122,0.06)",   border: "rgba(0,232,122,0.18)"  },
};

const PILLAR_LABELS = ["F", "M", "O", "S", "A"];
const PILLAR_NAMES  = {
  F: "Fundamental",
  M: "Momentum",
  O: "On-chain",
  S: "Sentiment",
  A: "Alpha",
};

/* ─── Pillar Impact Bar ──────────────────────────────────────────────── */
const PillarBars = ({ pillar_impact }) => {
  if (!pillar_impact) return null;
  const maxAbs = 30; // design scale

  return (
    <div style={{ marginTop: 10 }}>
      <div style={{ fontSize: 9, fontFamily: FONTS.mono, color: T.t3, letterSpacing: "0.08em", marginBottom: 6, textTransform: "uppercase" }}>
        CIS Pillar Impact
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        {PILLAR_LABELS.map((p) => {
          const val = pillar_impact[p] ?? 0;
          const pct = Math.abs(val) / maxAbs * 100;
          const isPos = val > 0;
          const isNeg = val < 0;
          const barColor = isPos ? T.green : isNeg ? T.red : "rgba(0,0,0,0.10)";

          return (
            <div key={p} style={{ display: "flex", alignItems: "center", gap: 6 }}>
              {/* Pillar label */}
              <span style={{
                fontFamily: FONTS.mono, fontSize: 10, fontWeight: 700,
                color: isPos ? T.green : isNeg ? T.red : T.t3,
                width: 12, textAlign: "center", flexShrink: 0,
              }}>{p}</span>

              {/* Bar track — center anchored */}
              <div style={{
                flex: 1, height: 6, borderRadius: 3,
                background: "rgba(255,255,255,0.06)",
                position: "relative",
                overflow: "hidden",
              }}>
                {/* Center line */}
                <div style={{
                  position: "absolute", left: "50%", top: 0, bottom: 0,
                  width: 1, background: "rgba(0,0,0,0.10)", transform: "translateX(-50%)",
                }} />
                {/* Fill */}
                {val !== 0 && (
                  <div style={{
                    position: "absolute",
                    top: 0, bottom: 0,
                    width: `${pct / 2}%`,
                    left: isPos ? "50%" : undefined,
                    right: isNeg ? "50%" : undefined,
                    background: barColor,
                    opacity: 0.85,
                    borderRadius: isPos ? "0 3px 3px 0" : "3px 0 0 3px",
                    transition: "width 0.4s ease",
                  }} />
                )}
              </div>

              {/* Value */}
              <span style={{
                fontFamily: FONTS.mono, fontSize: 9,
                color: isPos ? T.green : isNeg ? T.red : T.t3,
                width: 28, textAlign: "right", flexShrink: 0,
              }}>
                {val > 0 ? `+${val}` : val === 0 ? "—" : val}
              </span>

              {/* Pillar name tooltip */}
              <span style={{
                fontFamily: FONTS.mono, fontSize: 8, color: T.t3, opacity: 0.5,
                width: 64, flexShrink: 0, whiteSpace: "nowrap", overflow: "hidden",
              }}>
                {PILLAR_NAMES[p]}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
};

/* ─── Strength Meter ─────────────────────────────────────────────────── */
const StrengthBar = ({ value }) => {
  if (value == null) return null;
  const color = value >= 70 ? T.red : value >= 40 ? T.gold : T.t3;
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 8 }}>
      <span style={{ fontFamily: FONTS.mono, fontSize: 9, color: T.t3, flexShrink: 0 }}>STRENGTH</span>
      <div style={{
        flex: 1, height: 3, borderRadius: 2,
        background: "rgba(255,255,255,0.06)", overflow: "hidden",
      }}>
        <div style={{
          height: "100%", width: `${value}%`,
          background: color, borderRadius: 2,
          transition: "width 0.5s ease",
        }} />
      </div>
      <span style={{ fontFamily: FONTS.mono, fontSize: 9, color, width: 24, textAlign: "right" }}>{value}</span>
    </div>
  );
};

/* ─── Helper ─────────────────────────────────────────────────────────── */
const formatRelativeTime = (isoTimestamp) => {
  const ts = new Date(isoTimestamp).getTime();
  const diff = Date.now() - ts;
  const hours = Math.floor(diff / 3600000);
  const minutes = Math.floor(diff / 60000);
  if (hours >= 24) return `${Math.floor(hours / 24)}d ago`;
  if (hours >= 1)  return `${hours}h ago`;
  return `${minutes}m ago`;
};

/* ─── Fetch ──────────────────────────────────────────────────────────── */
async function fetchSignalsFromAPI() {
  try {
    const response = await fetch("/api/v1/signals");
    if (!response.ok) throw new Error(`API ${response.status}`);
    const data = await response.json();
    return { signals: data.signals || [], count: data.count || 0, version: data.version || "?" };
  } catch (e) {
    console.error("SignalFeed fetch:", e);
    return { signals: [], count: 0, version: "?" };
  }
}

/* ─── Signal Row ─────────────────────────────────────────────────────── */
const SignalRow = ({ signal, isNew, isExpanded, onToggle }) => {
  const rowRef = useRef(null);

  useEffect(() => {
    if (isExpanded && rowRef.current) {
      rowRef.current.scrollIntoView({ block: "nearest", behavior: "smooth" });
    }
  }, [isExpanded]);

  const typeConfig = SIGNAL_TYPES[signal.type] || SIGNAL_TYPES.MACRO;
  const impStyle   = IMPORTANCE_STYLES[signal.importance] || IMPORTANCE_STYLES.LOW;
  const dirStyle   = signal.vector_direction ? (DIRECTION_STYLES[signal.vector_direction] || DIRECTION_STYLES.NEUTRAL) : null;
  // Strict match only — unknown time_horizon values (e.g. raw numbers) must not render
  const horizStyle = signal.time_horizon ? (HORIZON_STYLES[signal.time_horizon] || null) : null;

  const hasMeta = signal.pillar_impact || signal.logic;

  return (
    <div
      ref={rowRef}
      className={isNew ? "signal-row new" : "signal-row"}
      style={{
        padding: "16px 16px",
        borderBottom: `1px solid ${T.border}`,
        transition: "background 0.14s",
        cursor: hasMeta ? "pointer" : "default",
        background: isExpanded ? "#0D2038" : "transparent",
      }}
      onClick={hasMeta ? onToggle : undefined}
      onMouseEnter={(e) => { if (!isExpanded) e.currentTarget.style.background = "rgba(0,0,0,0.02)"; }}
      onMouseLeave={(e) => { if (!isExpanded) e.currentTarget.style.background = "transparent"; }}
    >
      {/* ── Top row: type label (text only) + direction icon + time ──── */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 6, gap: 4 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          {/* Type — text only, no box */}
          <span style={{
            fontFamily: FONTS.display, fontSize: 9, fontWeight: 700, letterSpacing: "0.12em",
            color: typeConfig.color, textTransform: "uppercase",
          }}>
            {typeConfig.label}
          </span>
          {/* Direction icon only — no label, no box */}
          {dirStyle && signal.vector_direction && signal.vector_direction !== "NEUTRAL" && (
            <span style={{ fontSize: 10, lineHeight: 1, color: dirStyle.color, opacity: 0.7 }}>
              {dirStyle.icon}
            </span>
          )}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span style={{ fontSize: 10, color: T.t3, fontFamily: FONTS.mono, whiteSpace: "nowrap" }}>
            {formatRelativeTime(signal.timestamp)}
          </span>
          {hasMeta && (
            <span style={{ fontSize: 10, color: T.t3, opacity: 0.5, transition: "transform 0.2s", display: "inline-block", transform: isExpanded ? "rotate(180deg)" : "rotate(0)" }}>
              ▾
            </span>
          )}
        </div>
      </div>

      {/* ── Description ───────────────────────────────────────────────── */}
      <div style={{
        fontFamily: FONTS.display, fontSize: 13, fontWeight: 600,
        color: T.t1, letterSpacing: "0.005em", lineHeight: 1.45,
        marginBottom: 7, wordBreak: "break-word", overflowWrap: "break-word",
      }}>
        {signal.description}
      </div>

      {/* ── Strength bar (always visible if present) ───────────────────── */}
      {signal.signal_strength != null && (
        <StrengthBar value={signal.signal_strength} />
      )}

      {/* ── Asset tags + source ───────────────────────────────────────── */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 4, marginTop: 8 }}>
        {signal.affected_assets?.length > 0 && (
          <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
            {signal.affected_assets.map((asset) => (
              <span key={asset} style={{
                fontSize: 9, fontFamily: FONTS.mono, color: T.t3,
                background: "rgba(255,255,255,0.04)", border: `1px solid ${T.border}`,
                padding: "2px 6px", borderRadius: 2,
              }}>
                {asset}
              </span>
            ))}
          </div>
        )}
        {signal.source && (
          <span style={{ fontSize: 8, color: T.t3, fontFamily: FONTS.mono, opacity: 0.5, marginLeft: "auto" }}>
            {signal.source}
          </span>
        )}
      </div>

      {/* ── Expanded: pillar bars + logic ────────────────────────────── */}
      {isExpanded && hasMeta && (
        <div style={{
          marginTop: 12, paddingTop: 12,
          borderTop: `1px solid ${T.border}`,
        }}>
          {/* Pillar bars */}
          {signal.pillar_impact && (
            <PillarBars pillar_impact={signal.pillar_impact} />
          )}

          {/* Logic text */}
          {signal.logic && (
            <div style={{ marginTop: 12 }}>
              <div style={{ fontSize: 9, fontFamily: FONTS.mono, color: T.t3, letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 6 }}>
                Signal Logic
              </div>
              <div style={{
                fontFamily: FONTS.body, fontSize: 12, color: T.t2,
                lineHeight: 1.65, letterSpacing: "0.01em",
                padding: "10px 12px",
                background: "rgba(13,32,56,0.6)",
                border: `1px solid ${T.border}`,
                borderRadius: 6,
              }}>
                {signal.logic}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

/* ─── Skeleton ───────────────────────────────────────────────────────── */
const SkeletonRow = () => (
  <div style={{ padding: "13px 16px", borderBottom: `1px solid ${T.border}` }}>
    <div style={{ display: "flex", gap: 6, marginBottom: 9 }}>
      <div className="sk" style={{ height: 20, width: 70, borderRadius: 3 }} />
      <div className="sk" style={{ height: 20, width: 45, borderRadius: 3 }} />
      <div className="sk" style={{ height: 20, width: 80, borderRadius: 3 }} />
    </div>
    <div className="sk" style={{ height: 14, width: "88%", marginBottom: 6 }} />
    <div className="sk" style={{ height: 3, width: "60%", marginBottom: 8 }} />
    <div style={{ display: "flex", gap: 4 }}>
      <div className="sk" style={{ height: 16, width: 36, borderRadius: 2 }} />
      <div className="sk" style={{ height: 16, width: 36, borderRadius: 2 }} />
    </div>
  </div>
);

/* ─── Filter Bar ─────────────────────────────────────────────────────── */
const TAB_LABELS = {
  MACRO: "Macro", WHALE: "Whale", FUNDING: "Fund", FLOW: "Flow",
  RISK: "Risk", MOMENTUM: "Mom", REGULATORY: "Reg",
};

const FilterBar = ({ activeType, onChange }) => (
  <div className="signal-filter-bar" style={{
    flexShrink: 0,
    display: "flex", flexWrap: "nowrap", gap: 4, padding: "8px 12px",
    borderBottom: `1px solid ${T.border}`,
    background: "rgba(0,0,0,0.01)",
    overflowX: "auto", scrollbarWidth: "none",
  }}>
    {[null, ...Object.keys(SIGNAL_TYPES)].map((type) => {
      const isActive = activeType === type;
      const cfg = type ? SIGNAL_TYPES[type] : null;
      const label = type ? (TAB_LABELS[type] || type) : "All";
      return (
        <button
          key={type ?? "ALL"}
          onClick={() => onChange(type)}
          style={{
            fontFamily: FONTS.display, fontSize: 9, fontWeight: 700,
            letterSpacing: "0.06em", padding: "3px 8px", borderRadius: 3,
            cursor: "pointer", transition: "all 0.15s", whiteSpace: "nowrap",
            background: isActive ? (cfg ? cfg.bg : "rgba(255,255,255,0.08)") : "transparent",
            color:      isActive ? (cfg ? cfg.color : T.t1) : T.t3,
            border:     isActive ? `1px solid ${cfg ? cfg.border : "rgba(0,0,0,0.15)"}` : "1px solid transparent",
          }}
        >
          {label}
        </button>
      );
    })}
  </div>
);

/* ─── Main Component ─────────────────────────────────────────────────── */
export default function SignalFeed({ onSignalClick, refreshTrigger = 0 }) {
  const [loading, setLoading]       = useState(true);
  const [signals, setSignals]       = useState([]);
  const [count, setCount]           = useState(0);
  const [error, setError]           = useState(null);
  const [lastUpdate, setLastUpdate] = useState(null);
  const [expandedId, setExpandedId] = useState(null);
  const [activeFilter, setActiveFilter] = useState(null);
  const [version, setVersion]       = useState(null);

  const fetchSignals = useCallback(async () => {
    setError(null);
    try {
      const { signals: raw, count: total, version: v } = await fetchSignalsFromAPI();
      const seen = new Set();
      const unique = raw.filter((s) => {
        const key = s.id || s.description?.trim().toLowerCase();
        if (!key || seen.has(key)) return false;
        seen.add(key);
        return true;
      });
      setSignals(unique);
      setCount(total || unique.length);
      setLastUpdate(new Date());
      if (v) setVersion(v);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    setLoading(true);
    fetchSignals();
  }, [refreshTrigger, fetchSignals]);

  useEffect(() => {
    const interval = setInterval(fetchSignals, 300000);
    return () => clearInterval(interval);
  }, [fetchSignals]);

  const filteredSignals = activeFilter
    ? signals.filter((s) => s.type === activeFilter)
    : signals;

  const handleToggle = (id) => setExpandedId((prev) => (prev === id ? null : id));

  return (
    <div className="signal-panel" style={{
      border: `1px solid ${T.border}`,
      borderRadius: 12,
      background: T.surface,
      position: "sticky",
      top: 20,
      maxHeight: "calc(100vh - 40px)",
      display: "flex",
      flexDirection: "column",
      overflow: "hidden",
    }}>
      {/* ── Header ─────────────────────────────────────────────────────── */}
      <div style={{
        flexShrink: 0,
        display: "flex", alignItems: "center", justifyContent: "space-between",
        padding: "13px 16px", borderBottom: `1px solid ${T.border}`,
        background: "#0D2038",
      }}>
        <div style={{
          fontFamily: FONTS.display, fontSize: 11, fontWeight: 700,
          letterSpacing: "0.12em", color: T.t1, textTransform: "uppercase",
          display: "flex", alignItems: "center", gap: 8,
        }}>
          <span style={{ width: 14, height: 1, background: T.gold, opacity: 0.5 }} />
          Signal Feed
          {count > 0 && (
            <span style={{
              fontSize: 9, fontWeight: 700, fontFamily: FONTS.mono,
              padding: "1px 6px", borderRadius: 10,
              background: "rgba(200,168,75,0.15)", color: T.gold,
              border: "1px solid rgba(200,168,75,0.25)",
            }}>{count}</span>
          )}
          {version && (
            <span style={{
              fontSize: 8, fontFamily: FONTS.mono, color: T.t3, opacity: 0.5,
              fontWeight: 400,
            }}>v{version}</span>
          )}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          {lastUpdate && (
            <span style={{ fontSize: 9, color: T.t3, fontFamily: FONTS.mono }}>
              {lastUpdate.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
            </span>
          )}
          <span style={{
            background: "rgba(245,158,11,0.1)", color: T.amber,
            border: "1px solid rgba(245,158,11,0.2)",
            fontSize: 8, fontWeight: 700, letterSpacing: "0.1em",
            padding: "2px 6px", borderRadius: 3, fontFamily: FONTS.display,
          }}>LIVE</span>
          <div style={{
            width: 5, height: 5, borderRadius: "50%",
            background: error ? T.red : T.green,
          }} />
        </div>
      </div>

      {/* ── Filter Bar ─────────────────────────────────────────────────── */}
      <FilterBar activeType={activeFilter} onChange={setActiveFilter} />

      {/* ── Signal List ────────────────────────────────────────────────── */}
      <div style={{
        flex: 1,
        overflowY: "auto",
        minHeight: 0,
        scrollbarWidth: "thin",
        scrollbarColor: `${T.border} transparent`,
      }}>
        {loading ? (
          Array(4).fill(0).map((_, i) => <SkeletonRow key={i} />)
        ) : error && filteredSignals.length === 0 ? (
          <div style={{
            display: "flex", alignItems: "center", justifyContent: "center",
            height: 200, color: T.t3, fontSize: 11, fontFamily: FONTS.mono,
            flexDirection: "column", gap: 6,
          }}>
            <span style={{ color: T.red }}>数据加载失败</span>
            <span>请稍后重试</span>
          </div>
        ) : filteredSignals.length === 0 ? (
          <div style={{
            display: "flex", alignItems: "center", justifyContent: "center",
            height: 200, color: T.t3, fontSize: 11, fontFamily: FONTS.mono,
          }}>
            暂无信号
          </div>
        ) : (
          filteredSignals.map((signal, idx) => {
            const id = signal.id || String(idx);
            return (
              <SignalRow
                key={id}
                signal={signal}
                isNew={idx === 0 && !activeFilter}
                isExpanded={expandedId === id}
                onToggle={() => {
                  handleToggle(id);
                  if (onSignalClick) onSignalClick(signal);
                }}
              />
            );
          })
        )}
      </div>

      {/* ── Legend / Footer ─────────────────────────────────────────────── */}
      <div style={{
        flexShrink: 0,
        display: "flex", gap: 8, padding: "10px 16px",
        borderTop: `1px solid ${T.border}`,
        flexWrap: "wrap", background: "#0D2038",
        alignItems: "center", justifyContent: "space-between",
      }}>
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
          {Object.entries(DIRECTION_STYLES).map(([key, val]) => (
            <div key={key} style={{ display: "flex", alignItems: "center", gap: 4 }}>
              <span style={{ fontSize: 11, color: val.color }}>{val.icon}</span>
              <span style={{ fontSize: 10, fontFamily: FONTS.mono, color: T.t3, opacity: 0.75 }}>{key}</span>
            </div>
          ))}
        </div>
        <span style={{ fontSize: 9, fontFamily: FONTS.mono, color: T.t3, opacity: 0.4 }}>
          tap to expand
        </span>
      </div>

      <style>{`
        @keyframes signal-in {
          from { opacity: 0; transform: translateY(-4px); }
          to   { opacity: 1; transform: translateY(0); }
        }
        .signal-row.new { animation: signal-in 0.3s ease; }
        .signal-panel ::-webkit-scrollbar { width: 3px; }
        .signal-panel ::-webkit-scrollbar-track { background: transparent; }
        .signal-panel ::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.08); border-radius: 2px; }
        .signal-filter-bar::-webkit-scrollbar { display: none; }
      `}</style>
    </div>
  );
}
