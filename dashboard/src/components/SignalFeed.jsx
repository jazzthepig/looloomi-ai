import { useState, useEffect, useCallback } from "react";
import { T, FONTS } from "../tokens";

/* ─── Signal Types ───────────────────────────────────────────────────── */
const SIGNAL_TYPES = {
  MACRO:    { label: "MACRO",    color: T.gold,   bg: "rgba(200,168,75,0.12)", border: "rgba(200,168,75,0.2)" },
  WHALE:    { label: "WHALE",    color: T.purple, bg: "rgba(167,139,250,0.12)", border: "rgba(167,139,250,0.2)" },
  FUNDING:  { label: "FUNDING",  color: T.blue,   bg: "rgba(75,158,255,0.10)", border: "rgba(75,158,255,0.2)" },
  FLOW:     { label: "FLOW",     color: T.green,  bg: "rgba(0,232,122,0.08)", border: "rgba(0,232,122,0.2)" },
  RISK:     { label: "RISK",     color: T.red,    bg: "rgba(255,61,90,0.10)", border: "rgba(255,61,90,0.2)" },
  MOMENTUM: { label: "MOMENTUM", color: T.cyan,   bg: "rgba(0,200,224,0.10)", border: "rgba(0,200,224,0.2)" },
};

const IMPORTANCE_STYLES = {
  HIGH: { color: T.red, bg: "rgba(255,61,90,0.12)", border: "rgba(255,61,90,0.25)" },
  MED:  { color: T.gold, bg: "rgba(200,168,75,0.10)", border: "rgba(200,168,75,0.2)" },
  LOW:  { color: T.t3, bg: "rgba(255,255,255,0.04)", border: T.border },
};

/* ─── Helper Functions ───────────────────────────────────────────────── */
const formatRelativeTime = (isoTimestamp) => {
  const timestamp = new Date(isoTimestamp).getTime();
  const diff = Date.now() - timestamp;
  const hours = Math.floor(diff / (1000 * 60 * 60));
  const minutes = Math.floor(diff / (1000 * 60));

  if (hours >= 24) {
    const days = Math.floor(hours / 24);
    return `${days}d ago`;
  }
  if (hours >= 1) {
    return `${hours}h ago`;
  }
  return `${minutes}m ago`;
};

/* ─── Fetch Real Signals ───────────────────────────────────────────────── */
async function fetchSignalsFromAPI() {
  try {
    const response = await fetch("/api/v1/signals");
    if (!response.ok) throw new Error(`API error: ${response.status}`);
    const data = await response.json();
    return data.signals || [];
  } catch (e) {
    console.error("Failed to fetch signals:", e);
    return []; // Return empty array instead of mock data
  }
}

/* ─── Signal Row Component ─────────────────────────────────────────────── */
const SignalRow = ({ signal, isNew }) => {
  const typeConfig = SIGNAL_TYPES[signal.type] || SIGNAL_TYPES.MACRO;
  const impStyle = IMPORTANCE_STYLES[signal.importance] || IMPORTANCE_STYLES.LOW;

  return (
    <div
      className={isNew ? "signal-row new" : "signal-row"}
      style={{
        display: "grid",
        gridTemplateColumns: "auto 1fr auto",
        gap: 11,
        alignItems: "start",
        padding: "13px 16px",
        borderBottom: `1px solid ${T.border}`,
        transition: "background 0.14s",
        cursor: "pointer",
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.background = "rgba(255,255,255,0.02)";
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.background = "transparent";
      }}
    >
      {/* Type Badge */}
      <div className={`stype st-${signal.type.toLowerCase()}`} style={{
        fontFamily: FONTS.display,
        fontSize: 7,
        fontWeight: 700,
        letterSpacing: "0.12em",
        padding: "3px 6px",
        borderRadius: 3,
        background: typeConfig.bg,
        color: typeConfig.color,
        border: `1px solid ${typeConfig.border}`,
        textTransform: "uppercase",
        marginTop: 1,
        whiteSpace: "nowrap",
      }}>
        {typeConfig.label}
      </div>

      {/* Content */}
      <div className="sr-body" style={{ display: "flex", flexDirection: "column", gap: 3 }}>
        <div className="sr-title" style={{
          fontFamily: FONTS.display,
          fontSize: 11,
          fontWeight: 600,
          color: T.t1,
          letterSpacing: "0.01em",
          lineHeight: 1.35,
        }}>
          {signal.description}
        </div>
        {/* Asset Tags */}
        <div className="sr-assets" style={{ display: "flex", gap: 3, flexWrap: "wrap", marginTop: 2 }}>
          {signal.affected_assets?.map((asset) => (
            <span key={asset} className="sr-asset" style={{
              fontSize: 8,
              fontFamily: FONTS.mono,
              color: T.t3,
              background: "rgba(255,255,255,0.045)",
              border: `1px solid ${T.border}`,
              padding: "1px 5px",
              borderRadius: 2,
            }}>
              {asset}
            </span>
          ))}
        </div>
      </div>

      {/* Right: Time & Importance */}
      <div className="sr-right" style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 4, minWidth: 54 }}>
        <div className="sr-time" style={{
          fontSize: 8,
          color: T.t3,
          whiteSpace: "nowrap",
        }}>
          {formatRelativeTime(signal.timestamp)}
        </div>
        {signal.importance && (
          <div className={`impact imp-${signal.importance.toLowerCase()}`} style={{
            fontFamily: FONTS.display,
            fontSize: 8,
            fontWeight: 700,
            letterSpacing: "0.12em",
            padding: "2px 7px",
            borderRadius: 3,
            background: impStyle.bg,
            color: impStyle.color,
            border: `1px solid ${impStyle.border}`,
          }}>
            {signal.importance}
          </div>
        )}
      </div>
    </div>
  );
};

/* ─── Skeleton Row ───────────────────────────────────────────────────── */
const SkeletonRow = () => (
  <div style={{
    display: "grid",
    gridTemplateColumns: "auto 1fr auto",
    gap: 11,
    alignItems: "start",
    padding: "13px 16px",
    borderBottom: `1px solid ${T.border}`,
  }}>
    <div className="sk" style={{ height: 16, width: 50 }} />
    <div>
      <div className="sk" style={{ height: 14, width: "90%", marginBottom: 8 }} />
      <div className="sk" style={{ height: 16, width: 80 }} />
    </div>
    <div className="sk" style={{ height: 14, width: 40 }} />
  </div>
);

/* ─── Main Component ─────────────────────────────────────────────────── */
export default function SignalFeed({ onSignalClick, refreshTrigger = 0 }) {
  const [loading, setLoading] = useState(true);
  const [signals, setSignals] = useState([]);
  const [displayedSignals, setDisplayedSignals] = useState([]);
  const [error, setError] = useState(null);
  const [lastUpdate, setLastUpdate] = useState(null);
  const [currentIndex, setCurrentIndex] = useState(0);

  const fetchSignals = async () => {
    setError(null);
    try {
      const raw = await fetchSignalsFromAPI();
      // Deduplicate by description to avoid backend returning identical signals
      const seen = new Set();
      const unique = raw.filter(s => {
        const key = s.description?.trim().toLowerCase();
        if (!key || seen.has(key)) return false;
        seen.add(key);
        return true;
      });
      setSignals(unique);
      setDisplayedSignals(unique.slice(0, 5));
      setCurrentIndex(0);
      setLastUpdate(new Date());
    } catch (err) {
      console.error("SignalFeed fetch error:", err);
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    setLoading(true);
    fetchSignals();
  }, [refreshTrigger]);

  // Auto-rotate signals every 30 seconds
  useEffect(() => {
    if (signals.length === 0) return;

    const rotateSignals = () => {
      setCurrentIndex(prev => {
        const nextIndex = (prev + 1) % signals.length;
        // Circular slice — wraps around so we always show 5 entries
        const sliced = [];
        for (let i = 0; i < 5; i++) {
          sliced.push(signals[(nextIndex + i) % signals.length]);
        }
        setDisplayedSignals(sliced);
        return nextIndex;
      });
    };

    const interval = setInterval(rotateSignals, 30000); // 30s rotation
    return () => clearInterval(interval);
  }, [signals]);

  // Error state
  if (error && signals.length === 0) {
    return (
      <div className="signal-panel" style={{
        border: `1px solid ${T.border}`,
        borderRadius: 12,
        overflow: "hidden",
        background: T.surface,
      }}>
        <div className="sp-head" style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "13px 16px",
          borderBottom: `1px solid ${T.border}`,
          background: "rgba(255,255,255,0.018)",
        }}>
          <div className="sp-title" style={{
            fontFamily: FONTS.display,
            fontSize: 11,
            fontWeight: 700,
            letterSpacing: "0.18em",
            color: T.t2,
            textTransform: "uppercase",
            display: "flex",
            alignItems: "center",
            gap: 8,
          }}>
            <span style={{ width: 14, height: 1, background: T.t2 }} />
            Signal Feed
          </div>
        </div>
        <div style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          height: 200,
          color: T.red,
          fontSize: 12,
          fontFamily: FONTS.mono,
        }}>
          数据加载失败 · {lastUpdate ? `上次更新: ${lastUpdate.toLocaleTimeString()}` : "请刷新"}
        </div>
      </div>
    );
  }

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
      <div className="sp-head" style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        padding: "13px 16px",
        borderBottom: `1px solid ${T.border}`,
        background: "rgba(255,255,255,0.018)",
      }}>
        <div className="sp-title" style={{
          fontFamily: FONTS.display,
          fontSize: 9,
          fontWeight: 700,
          letterSpacing: "0.2em",
          color: T.t3,
          textTransform: "uppercase",
          display: "flex",
          alignItems: "center",
          gap: 8,
        }}>
          <span style={{ width: 14, height: 1, background: T.t3 }} />
          Signal Feed
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span style={{
            background: "rgba(245,158,11,0.1)",
            color: T.amber,
            border: "1px solid rgba(245,158,11,0.2)",
            fontSize: 7,
            fontWeight: 700,
            letterSpacing: "0.1em",
            padding: "2px 6px",
            borderRadius: 3,
            fontFamily: FONTS.display,
          }}>LIVE</span>
          <div style={{
            width: 4,
            height: 4,
            borderRadius: "50%",
            background: T.green,
          }} />
        </div>
      </div>

      {/* Signal List */}
      <div className="sp-body" style={{
        maxHeight: "calc(100vh - 300px)",
        overflowY: "auto",
        minHeight: 400,
      }}>
        {loading
          ? Array(5).fill(0).map((_, i) => <SkeletonRow key={i} />)
          : displayedSignals.map((signal, idx) => (
              <SignalRow
                key={signal.id}
                signal={signal}
                onClick={onSignalClick}
                isNew={idx === 0}
              />
            ))
        }
      </div>

      {/* Legend */}
      <div style={{
        display: "flex",
        gap: 12,
        padding: "12px 16px",
        borderTop: `1px solid ${T.border}`,
        flexWrap: "wrap",
      }}>
        {Object.entries(SIGNAL_TYPES).map(([key, val]) => (
          <div key={key} style={{
            display: "flex",
            alignItems: "center",
            gap: 4,
          }}>
            <div style={{
              width: 6,
              height: 6,
              borderRadius: "50%",
              background: val.color,
            }} />
            <span style={{
              fontSize: 8,
              fontFamily: FONTS.mono,
              color: T.t3,
            }}>
              {val.label}
            </span>
          </div>
        ))}
      </div>

      <style>{`
        @keyframes signal-in {
          from { opacity: 0; transform: translateY(-5px); }
          to { opacity: 1; transform: translateY(0); }
        }
        .signal-row.new {
          animation: signal-in 0.35s ease;
        }
      `}</style>
    </div>
  );
}
