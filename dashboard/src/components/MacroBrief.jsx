import { useState, useEffect } from "react";
import { T, FONTS } from "../tokens";

const API_BASE = "/api/v1";

function formatAge(seconds) {
  if (!seconds || seconds < 0) return null;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)}h ago`;
  return `${Math.round(seconds / 86400)}d ago`;
}

// ── Inline markdown renderer ─────────────────────────────────────────────────
// Handles: **bold**, *italic*, `code`, paragraph breaks, and # / ## headings.
// No external deps — pure JSX.

function renderInline(text) {
  // Split on bold, italic, code spans
  const parts = [];
  const re = /(\*\*(.+?)\*\*|\*(.+?)\*|`(.+?)`)/g;
  let last = 0, m;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) parts.push(text.slice(last, m.index));
    if (m[0].startsWith("**")) {
      parts.push(<strong key={m.index} style={{ color: T.t1, fontWeight: 700 }}>{m[2]}</strong>);
    } else if (m[0].startsWith("*")) {
      parts.push(<em key={m.index} style={{ fontStyle: "italic", color: T.t2 }}>{m[3]}</em>);
    } else {
      parts.push(
        <code key={m.index} style={{
          fontFamily: FONTS.mono, fontSize: 12, background: "rgba(6,182,212,0.08)",
          color: T.cyan, borderRadius: 3, padding: "1px 4px",
        }}>{m[4]}</code>
      );
    }
    last = re.lastIndex;
  }
  if (last < text.length) parts.push(text.slice(last));
  return parts;
}

function renderMarkdown(text) {
  if (!text) return null;
  const lines = text.split("\n");
  const nodes = [];
  let key = 0;

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];

    // h1
    if (/^# /.test(line)) {
      nodes.push(
        <div key={key++} style={{
          fontFamily: FONTS.ui || FONTS.body, fontSize: 15, fontWeight: 700,
          color: T.t1, marginBottom: 6, marginTop: nodes.length ? 14 : 0, letterSpacing: "0.01em",
        }}>
          {renderInline(line.replace(/^# /, ""))}
        </div>
      );
      continue;
    }

    // h2
    if (/^## /.test(line)) {
      nodes.push(
        <div key={key++} style={{
          fontFamily: FONTS.ui || FONTS.body, fontSize: 13, fontWeight: 700,
          color: T.cyan, marginBottom: 4, marginTop: nodes.length ? 10 : 0,
          textTransform: "uppercase", letterSpacing: "0.08em",
        }}>
          {renderInline(line.replace(/^## /, ""))}
        </div>
      );
      continue;
    }

    // horizontal rule
    if (/^---+$/.test(line.trim())) {
      nodes.push(<hr key={key++} style={{ border: "none", borderTop: `1px solid rgba(6,182,212,0.12)`, margin: "10px 0" }} />);
      continue;
    }

    // blank line → paragraph spacer
    if (line.trim() === "") {
      // only add space if there's content before it
      if (nodes.length && nodes[nodes.length - 1]?.type !== "div" || true) {
        nodes.push(<div key={key++} style={{ height: 8 }} />);
      }
      continue;
    }

    // normal paragraph line
    nodes.push(
      <div key={key++} style={{
        fontFamily: FONTS.body, fontSize: 14, lineHeight: 1.75,
        color: T.t1, opacity: 0.88,
      }}>
        {renderInline(line)}
      </div>
    );
  }

  return nodes;
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

  const briefText   = data.brief;
  const isLong      = briefText.length > 600;
  const displayText = expanded || !isLong ? briefText : briefText.slice(0, 600) + "…";
  const age         = formatAge(data.age_seconds);

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

        {/* Brief body — markdown rendered */}
        <div>
          {renderMarkdown(displayText)}
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
