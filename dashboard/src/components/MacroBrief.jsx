import { useState, useEffect } from "react";
import { Activity, Clock, Cpu } from "lucide-react";
import { T, FONTS } from "../tokens";

const API_BASE = "/api/v1";

function formatAge(seconds) {
  if (!seconds || seconds < 0) return "—";
  if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)}h ago`;
  return `${Math.round(seconds / 86400)}d ago`;
}

export default function MacroBrief() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    const fetchBrief = async () => {
      try {
        const res = await fetch(`${API_BASE}/macro/brief`);
        const json = await res.json();
        setData(json);
      } catch (e) {
        console.error("MacroBrief fetch error:", e);
      } finally {
        setLoading(false);
      }
    };
    fetchBrief();
    // Refresh every 10 minutes
    const interval = setInterval(fetchBrief, 600_000);
    return () => clearInterval(interval);
  }, []);

  // No brief yet — show placeholder
  if (loading) {
    return (
      <div style={{
        background: "#FFFFFF",
        border: `1px solid ${T.border}`,
        borderRadius: 10,
        padding: "20px 24px",
        backdropFilter: "blur(20px)",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
          <Activity size={14} color={T.cyan} />
          <span style={{ fontSize: 11, color: T.muted, fontFamily: FONTS.display, letterSpacing: ".08em", textTransform: "uppercase" }}>
            Macro Brief
          </span>
        </div>
        <div style={{ height: 16, width: 200, background: "linear-gradient(90deg,#F3F4F6 30%,#E5E7EB 50%,#F3F4F6 70%)", backgroundSize: "400px 100%", borderRadius: 4, animation: "shimmer 1.8s ease infinite" }} />
      </div>
    );
  }

  if (!data?.brief) {
    return (
      <div style={{
        background: "#FFFFFF",
        border: `1px solid ${T.border}`,
        borderRadius: 10,
        padding: "20px 24px",
        backdropFilter: "blur(20px)",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <Activity size={14} color={T.muted} />
          <span style={{ fontSize: 11, color: T.muted, fontFamily: FONTS.display, letterSpacing: ".08em", textTransform: "uppercase" }}>
            Macro Brief
          </span>
          <span style={{ fontSize: 10, color: T.muted, fontFamily: FONTS.mono, marginLeft: "auto" }}>
            Awaiting next scheduled run
          </span>
        </div>
      </div>
    );
  }

  // brief is plain text — NEVER use dangerouslySetInnerHTML (XSS prevention)
  const briefText = data.brief;
  const isLong = briefText.length > 600;
  const displayText = expanded || !isLong ? briefText : briefText.slice(0, 600) + "…";

  return (
    <div style={{
      background: "#FFFFFF",
      border: `1px solid ${T.border}`,
      borderLeft: `2px solid ${T.cyan}`,
      borderRadius: 10,
      padding: "20px 24px",
      backdropFilter: "blur(20px)",
      animation: "fadeUp .4s cubic-bezier(.16,1,.3,1) forwards",
    }}>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 14 }}>
        <Activity size={14} color={T.cyan} />
        <span style={{
          fontSize: 11,
          color: T.cyan,
          fontFamily: FONTS.display,
          fontWeight: 600,
          letterSpacing: ".08em",
          textTransform: "uppercase",
        }}>
          Macro Brief
        </span>

        {/* Source badge */}
        <span style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 4,
          padding: "2px 7px",
          borderRadius: 3,
          fontSize: 9,
          fontWeight: 600,
          letterSpacing: ".06em",
          textTransform: "uppercase",
          fontFamily: FONTS.display,
          background: "rgba(0,232,122,0.08)",
          color: T.green,
          border: "1px solid rgba(0,232,122,0.15)",
        }}>
          <Cpu size={9} />
          {data.model || "LOCAL AI"}
        </span>

        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 6 }}>
          <Clock size={10} color={T.muted} />
          <span style={{ fontSize: 10, color: data.stale ? T.amber : T.muted, fontFamily: FONTS.mono }}>
            {formatAge(data.age_seconds)}
          </span>
        </div>
      </div>

      {/* Brief body */}
      <div style={{
        fontSize: 13,
        lineHeight: 1.7,
        color: T.t1,
        fontFamily: FONTS.body,
        whiteSpace: "pre-wrap",
        opacity: 0.88,
      }}>
        {displayText}
      </div>

      {/* Expand toggle */}
      {isLong && (
        <button
          onClick={() => setExpanded(!expanded)}
          style={{
            marginTop: 10,
            padding: "4px 10px",
            borderRadius: 4,
            fontSize: 10,
            fontWeight: 500,
            fontFamily: FONTS.display,
            cursor: "pointer",
            outline: "none",
            border: `1px solid ${T.border}`,
            background: "transparent",
            color: T.secondary,
            transition: "all .15s ease",
          }}
        >
          {expanded ? "Collapse" : "Read full brief"}
        </button>
      )}
    </div>
  );
}
