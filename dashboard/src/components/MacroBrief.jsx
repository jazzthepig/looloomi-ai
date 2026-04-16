import { useState, useEffect } from "react";
import { T, FONTS } from "../tokens";

const API_BASE = "/api/v1";

function formatAge(seconds) {
  if (!seconds || seconds < 0) return null;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)}h ago`;
  return `${Math.round(seconds / 86400)}d ago`;
}

export default function MacroBrief() {
  const [data, setData]       = useState(null);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    const fetchBrief = async () => {
      try {
        const res  = await fetch(`${API_BASE}/macro/brief`);
        const json = await res.json();
        setData(json);
      } catch (e) {
        console.error("MacroBrief fetch error:", e);
      } finally {
        setLoading(false);
      }
    };
    fetchBrief();
    const interval = setInterval(fetchBrief, 600_000);
    return () => clearInterval(interval);
  }, []);

  // Nothing to show — no box, no placeholder, just gone
  if (loading || !data?.brief) return null;

  const briefText  = data.brief;
  const isLong     = briefText.length > 600;
  const displayText = expanded || !isLong ? briefText : briefText.slice(0, 600) + "…";
  const age        = formatAge(data.age_seconds);

  return (
    <div style={{
      display: "flex", gap: 20, marginBottom: 28,
      paddingBottom: 24, borderBottom: `1px solid rgba(37,99,235,0.10)`,
      animation: "fadeUp .4s cubic-bezier(.16,1,.3,1) forwards",
    }}>
      {/* Left accent bar */}
      <div style={{
        width: 2, flexShrink: 0,
        background: "linear-gradient(180deg, rgba(6,182,212,0.70) 0%, rgba(6,182,212,0.10) 100%)",
        borderRadius: 1, marginTop: 3,
      }} />

      <div style={{ flex: 1, minWidth: 0 }}>
        {/* Meta line */}
        <div style={{
          display: "flex", alignItems: "center", gap: 10, marginBottom: 10,
        }}>
          <span style={{
            fontFamily: FONTS.mono, fontSize: 9, fontWeight: 700,
            letterSpacing: "0.12em", textTransform: "uppercase", color: T.cyan,
          }}>
            Macro Brief
          </span>
          {data.model && (
            <span style={{ fontFamily: FONTS.mono, fontSize: 8, color: T.t3, opacity: 0.5 }}>
              {data.model}
            </span>
          )}
          {age && (
            <span style={{ fontFamily: FONTS.mono, fontSize: 8, color: data.stale ? T.amber : T.t3, marginLeft: "auto", opacity: data.stale ? 1 : 0.5 }}>
              {data.stale ? "stale · " : ""}{age}
            </span>
          )}
        </div>

        {/* Brief body — plain prose */}
        <div style={{
          fontFamily: FONTS.body, fontSize: 14, lineHeight: 1.75,
          color: T.t1, opacity: 0.88, whiteSpace: "pre-wrap",
        }}>
          {displayText}
        </div>

        {/* Expand */}
        {isLong && (
          <button
            onClick={() => setExpanded(!expanded)}
            style={{
              marginTop: 8, padding: 0, background: "none", border: "none",
              cursor: "pointer", outline: "none",
              fontFamily: FONTS.mono, fontSize: 10, color: T.cyan, opacity: 0.6,
              letterSpacing: "0.04em",
              transition: "opacity .15s ease",
            }}
            onMouseEnter={e => e.currentTarget.style.opacity = 1}
            onMouseLeave={e => e.currentTarget.style.opacity = 0.6}
          >
            {expanded ? "↑ collapse" : "↓ read more"}
          </button>
        )}
      </div>
    </div>
  );
}
