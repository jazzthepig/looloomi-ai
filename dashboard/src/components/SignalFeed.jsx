import { useState, useEffect, useCallback } from "react";
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
    return { signals: data.signals || [], count: data.count || 0 };
  } catch (e) {
    console.error("SignalFeed fetch:", e);
    return { signals: [], count: 0 };
  }
}

/* ─── Signal Card ────────────────────────────────────────────────────── */
const SignalRow = ({ signal, isNew, onClick }) => {
  const typeConfig = SIGNAL_TYPES[signal.type] || SIGNAL_TYPES.MACRO;
  const impStyle   = IMPORTANCE_STYLES[signal.importance] || IMPORTANCE_STYLES.LOW;

  return (
    <div
      className={isNew ? "signal-row new" : "signal-row"}
      style={{
        padding: "14px 16px",
        borderBottom: `1px solid ${T.border}`,
        transition: "background 0.14s",
        cursor: "pointer",
      }}
      onClick={onClick ? () => onClick(signal) : undefined}
      onMouseEnter={(e) => { e.currentTarget.style.background = "rgba(255,255,255,0.025)"; }}
      onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}
    >
      {/* Top row: type badge + importance badge + time */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 7 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span style={{
            fontFamily: FONTS.display,
            fontSize: 9,
            fontWeight: 700,
            letterSpacing: "0.1em",
            padding: "3px 7px",
            borderRadius: 3,
            background: typeConfig.bg,
            color: typeConfig.color,
            border: `1px solid ${typeConfig.border}`,
            textTransform: "uppercase",
          }}>
            {typeConfig.label}
          </span>
          {signal.importance && (
            <span style={{
              fontFamily: FONTS.display,
              fontSize: 9,
              fontWeight: 700,
              letterSpacing: "0.1em",
              padding: "3px 7px",
              borderRadius: 3,
              background: impStyle.bg,
              color: impStyle.color,
              border: `1px solid ${impStyle.border}`,
            }}>
              {signal.importance}
            </span>
          )}
        </div>
        <span style={{ fontSize: 10, color: T.t3, fontFamily: FONTS.mono, whiteSpace: "nowrap" }}>
          {formatRelativeTime(signal.timestamp)}
        </span>
      </div>

      {/* Description */}
      <div style={{
        fontFamily: FONTS.display,
        fontSize: 13,
        fontWeight: 600,
        color: T.t1,
        letterSpacing: "0.005em",
        lineHeight: 1.45,
        marginBottom: signal.affected_assets?.length ? 8 : 0,
      }}>
        {signal.description}
      </div>

      {/* Asset Tags + Source */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", gap: 4 }}>
        {signal.affected_assets?.length > 0 && (
          <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
            {signal.affected_assets.map((asset) => (
              <span key={asset} style={{
                fontSize: 9, fontFamily: FONTS.mono, color: T.t3,
                background: "rgba(255,255,255,0.045)", border: `1px solid ${T.border}`,
                padding: "2px 6px", borderRadius: 2,
              }}>
                {asset}
              </span>
            ))}
          </div>
        )}
        {signal.source && (
          <span style={{ fontSize: 8, color: T.t3, fontFamily: FONTS.mono, opacity: 0.6, marginLeft: "auto" }}>
            {signal.source}
          </span>
        )}
      </div>
    </div>
  );
};

/* ─── Skeleton ───────────────────────────────────────────────────────── */
const SkeletonRow = () => (
  <div style={{ padding: "14px 16px", borderBottom: `1px solid ${T.border}` }}>
    <div style={{ display: "flex", gap: 6, marginBottom: 9 }}>
      <div className="sk" style={{ height: 20, width: 70, borderRadius: 3 }} />
      <div className="sk" style={{ height: 20, width: 45, borderRadius: 3 }} />
    </div>
    <div className="sk" style={{ height: 14, width: "88%", marginBottom: 6 }} />
    <div className="sk" style={{ height: 14, width: "60%" }} />
  </div>
);

/* ─── Main Component ─────────────────────────────────────────────────── */
export default function SignalFeed({ onSignalClick, refreshTrigger = 0 }) {
  const [loading, setLoading]   = useState(true);
  const [signals, setSignals]   = useState([]);
  const [count, setCount]       = useState(0);
  const [error, setError]       = useState(null);
  const [lastUpdate, setLastUpdate] = useState(null);

  const fetchSignals = useCallback(async () => {
    setError(null);
    try {
      const { signals: raw, count: total } = await fetchSignalsFromAPI();
      const seen = new Set();
      const unique = raw.filter(s => {
        const key = s.id || s.description?.trim().toLowerCase();
        if (!key || seen.has(key)) return false;
        seen.add(key);
        return true;
      });
      setSignals(unique);
      setCount(total || unique.length);
      setLastUpdate(new Date());
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

  // Auto-refresh every 5 minutes
  useEffect(() => {
    const interval = setInterval(fetchSignals, 300000);
    return () => clearInterval(interval);
  }, [fetchSignals]);

  return (
    <div className="signal-panel" style={{
      border: `1px solid ${T.border}`,
      borderRadius: 12,
      overflow: "hidden",
      background: T.surface,
      position: "sticky",
      top: 20,
    }}>
      {/* Header */}
      <div style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        padding: "13px 16px",
        borderBottom: `1px solid ${T.border}`,
        background: "rgba(255,255,255,0.018)",
      }}>
        <div style={{
          fontFamily: FONTS.display,
          fontSize: 11,
          fontWeight: 700,
          letterSpacing: "0.12em",
          color: T.t2,
          textTransform: "uppercase",
          display: "flex",
          alignItems: "center",
          gap: 8,
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
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          {lastUpdate && (
            <span style={{ fontSize: 9, color: T.t3, fontFamily: FONTS.mono }}>
              {lastUpdate.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
            </span>
          )}
          <span style={{
            background: "rgba(245,158,11,0.1)",
            color: T.amber,
            border: "1px solid rgba(245,158,11,0.2)",
            fontSize: 8,
            fontWeight: 700,
            letterSpacing: "0.1em",
            padding: "2px 6px",
            borderRadius: 3,
            fontFamily: FONTS.display,
          }}>LIVE</span>
          <div style={{
            width: 5, height: 5, borderRadius: "50%",
            background: error ? T.red : T.green,
          }} />
        </div>
      </div>

      {/* Signal List */}
      <div style={{
        maxHeight: "calc(100vh - 280px)",
        overflowY: "auto",
        minHeight: 320,
      }}>
        {loading ? (
          Array(4).fill(0).map((_, i) => <SkeletonRow key={i} />)
        ) : error && signals.length === 0 ? (
          <div style={{
            display: "flex", alignItems: "center", justifyContent: "center",
            height: 200, color: T.t3, fontSize: 11, fontFamily: FONTS.mono,
            flexDirection: "column", gap: 6,
          }}>
            <span style={{ color: T.red }}>数据加载失败</span>
            <span>请稍后重试</span>
          </div>
        ) : signals.length === 0 ? (
          <div style={{
            display: "flex", alignItems: "center", justifyContent: "center",
            height: 200, color: T.t3, fontSize: 11, fontFamily: FONTS.mono,
          }}>
            暂无信号
          </div>
        ) : (
          signals.map((signal, idx) => (
            <SignalRow
              key={signal.id || idx}
              signal={signal}
              onClick={onSignalClick}
              isNew={idx === 0}
            />
          ))
        )}
      </div>

      {/* Legend */}
      <div style={{
        display: "flex",
        gap: 10,
        padding: "10px 16px",
        borderTop: `1px solid ${T.border}`,
        flexWrap: "wrap",
        background: "rgba(255,255,255,0.01)",
      }}>
        {Object.entries(SIGNAL_TYPES).map(([key, val]) => (
          <div key={key} style={{ display: "flex", alignItems: "center", gap: 4 }}>
            <div style={{ width: 5, height: 5, borderRadius: "50%", background: val.color }} />
            <span style={{ fontSize: 9, fontFamily: FONTS.mono, color: T.t3 }}>
              {val.label}
            </span>
          </div>
        ))}
      </div>

      <style>{`
        @keyframes signal-in {
          from { opacity: 0; transform: translateY(-4px); }
          to   { opacity: 1; transform: translateY(0); }
        }
        .signal-row.new { animation: signal-in 0.3s ease; }
      `}</style>
    </div>
  );
}
