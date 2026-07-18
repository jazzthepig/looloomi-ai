import { useState, useEffect, useCallback } from "react";
import { T, FONTS } from "../tokens";

/*
 * Signal Feed v5 — a STRUCTURED, TIERED, NARRATIVE briefing (not a scoreboard).
 * Sections from /api/v1/signals/feed, each item a mini-story: headline + narrative (what's
 * happening + why it matters). Distinct from the CIS leaderboard: this is context, not scores.
 */

const TIER = {
  context:     { color: T.cyan,   label: "MARKET CONTEXT" },
  conviction:  { color: T.green,  label: "CONVICTION WATCH" },
  positioning: { color: T.gold,   label: "POSITIONING & FLOW" },
  cross_asset: { color: T.purple || "#a78bfa", label: "CROSS-ASSET SHIFTS" },
  calls:       { color: T.t3,     label: "OUR TRACKED CALLS" },
};

// Defensive: strip markdown emphasis so **x** / *x* never render as literal asterisks.
const clean = (s) => (typeof s === "string"
  ? s.replace(/\*\*(.+?)\*\*/g, "$1").replace(/\*(.+?)\*/g, "$1")
  : s);

function dirColor(d = "") {
  const s = d.toUpperCase();
  if (s.includes("OUTPERFORM") && !s.includes("UNDER")) return T.green;
  if (s.includes("UNDER")) return T.red;
  return T.t3;
}

async function fetchFeed() {
  try {
    const r = await fetch("/api/v1/signals/feed");
    if (!r.ok) throw new Error(`API ${r.status}`);
    return await r.json();
  } catch (e) {
    console.error("SignalFeed:", e);
    return { sections: [] };
  }
}

const DirBadge = ({ d }) => {
  if (!d) return null;
  const c = dirColor(d);
  const s = d.toUpperCase();
  const icon = s.includes("OUTPERFORM") && !s.includes("UNDER") ? "▲" : s.includes("UNDER") ? "▼" : "•";
  return (
    <span style={{ fontFamily: FONTS.mono, fontSize: 8.5, fontWeight: 700, letterSpacing: "0.05em",
      color: c, background: `${c}18`, border: `1px solid ${c}40`, padding: "2px 7px", borderRadius: 100, whiteSpace: "nowrap" }}>
      {icon} {s}
    </span>
  );
};

const Layers = ({ l }) => {
  if (!l) return null;
  const bars = [["moat", l.moat], ["cat", l.catalyst], ["fund", l.fundamentals], ["trend", l.trend]];
  return (
    <div style={{ display: "flex", gap: 8, marginTop: 8 }}>
      {bars.map(([k, v]) => (
        <div key={k} style={{ flex: 1 }}>
          <div style={{ height: 3, borderRadius: 2, background: "rgba(255,255,255,0.06)" }}>
            <div style={{ width: `${Math.min(100, (v || 0) * 100)}%`, height: "100%", borderRadius: 2, background: T.green, opacity: 0.85 }} />
          </div>
          <div style={{ fontFamily: FONTS.mono, fontSize: 7.5, color: T.t4, letterSpacing: "0.06em", marginTop: 2, textTransform: "uppercase" }}>{k}</div>
        </div>
      ))}
    </div>
  );
};

const Item = ({ it, tierColor }) => (
  <div style={{ padding: "12px 14px", borderBottom: "1px solid rgba(37,99,235,0.08)", borderLeft: `2px solid ${tierColor}` }}>
    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10, marginBottom: 5, flexWrap: "wrap" }}>
      <span style={{ fontFamily: FONTS.brand || FONTS.body, fontWeight: 700, fontSize: 13.5, color: T.t1 }}>{clean(it.headline)}</span>
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        {it.direction && <DirBadge d={it.direction} />}
        {typeof it.score === "number" && (
          <span style={{ fontFamily: FONTS.mono, fontSize: 10, color: T.green }}>{it.score.toFixed(2)}</span>
        )}
      </div>
    </div>
    {it.narrative && (
      <div style={{ fontFamily: FONTS.body, fontSize: 12.5, lineHeight: 1.6, color: T.t2, opacity: 0.92 }}>{clean(it.narrative)}</div>
    )}
    <Layers l={it.layers} />
    {(it.source || it.symbols) && (
      <div style={{ display: "flex", gap: 8, marginTop: 8, flexWrap: "wrap", alignItems: "center" }}>
        {it.symbols && it.symbols.map((s) => (
          <span key={s} style={{ fontFamily: FONTS.mono, fontSize: 9, color: T.t2, background: T.raised, border: `1px solid ${T.border}`, padding: "1px 6px", borderRadius: 3 }}>{s}</span>
        ))}
        {it.source && <span style={{ fontFamily: FONTS.mono, fontSize: 8.5, color: T.t4, marginLeft: "auto", letterSpacing: "0.06em" }}>{it.source}</span>}
      </div>
    )}
  </div>
);

const Skeleton = () => (
  <div style={{ padding: "14px" }}>
    {[1, 2, 3].map((i) => (
      <div key={i} style={{ marginBottom: 14 }}>
        <div style={{ height: 11, width: "50%", background: "rgba(255,255,255,0.05)", borderRadius: 4, marginBottom: 7 }} />
        <div style={{ height: 9, width: "85%", background: "rgba(255,255,255,0.03)", borderRadius: 4 }} />
      </div>
    ))}
  </div>
);

export default function SignalFeed({ onSignalClick, refreshTrigger = 0 }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [updated, setUpdated] = useState(null);

  const load = useCallback(async () => {
    const d = await fetchFeed();
    setData(d); setUpdated(new Date()); setLoading(false);
  }, []);
  useEffect(() => { load(); }, [refreshTrigger, load]);
  useEffect(() => { const i = setInterval(load, 180000); return () => clearInterval(i); }, [load]);

  const sections = data?.sections || [];
  const acc = data?.accuracy;

  return (
    <div style={{ background: T.surface, border: `1px solid ${T.border}`, borderRadius: 14, overflow: "hidden" }}>
      {/* header — the frame */}
      <div style={{ padding: "16px 16px 13px", borderBottom: `1px solid ${T.border}` }}>
        <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: 8, flexWrap: "wrap" }}>
          <span style={{ display: "flex", alignItems: "center", gap: 7 }}>
            <span style={{ fontFamily: FONTS.brand, fontWeight: 700, fontSize: 15, color: T.t1 }}>Intelligence Briefing</span>
            {data?.narrative_source === "ai" && (
              <span title={data?.narrative_model ? `AI analysis · ${data.narrative_model}` : "AI analysis"}
                style={{ fontFamily: FONTS.mono, fontSize: 8, fontWeight: 700, letterSpacing: "0.1em", color: T.green,
                  border: `1px solid ${T.green}55`, background: `${T.green}12`, padding: "1px 5px", borderRadius: 4 }}>
                AI
              </span>
            )}
          </span>
          {data?.regime && (
            <span style={{ fontFamily: FONTS.mono, fontSize: 9, letterSpacing: "0.08em", color: T.cyan, border: `1px solid ${T.cyan}40`, padding: "2px 8px", borderRadius: 100 }}>
              REGIME · {String(data.regime).toUpperCase()}
            </span>
          )}
        </div>
        {data?.headline && (
          <div style={{ fontFamily: FONTS.body, fontSize: 13, color: T.t2, marginTop: 8, lineHeight: 1.5 }}>{clean(data.headline)}</div>
        )}
        {acc && acc.resolved_30d_directional_pct != null && (
          <div style={{ fontFamily: FONTS.mono, fontSize: 10, color: T.t3, marginTop: 8 }}>
            our tracked calls: <span style={{ color: T.green }}>{acc.resolved_30d_directional_pct}%</span> 30d directional (n={acc.n})
          </div>
        )}
      </div>

      {/* tiered sections */}
      {loading ? <Skeleton /> : sections.length === 0 ? (
        <div style={{ padding: "28px 16px", textAlign: "center", fontFamily: FONTS.mono, fontSize: 11, color: T.t3 }}>
          Briefing warming up — intelligence composes on the next cycle.
        </div>
      ) : sections.map((sec) => {
        const tc = TIER[sec.tier] || { color: T.t3, label: (sec.title || "").toUpperCase() };
        return (
          <div key={sec.tier}>
            <div style={{ padding: "11px 16px 7px", display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{ width: 5, height: 5, borderRadius: "50%", background: tc.color }} />
              <span style={{ fontFamily: FONTS.mono, fontSize: 9.5, fontWeight: 700, letterSpacing: "0.12em", color: tc.color, textTransform: "uppercase" }}>{sec.title}</span>
            </div>
            {(sec.items || []).map((it, i) => <Item key={it.symbol ? `${it.symbol}-${i}` : i} it={it} tierColor={tc.color} />)}
          </div>
        );
      })}

      <div style={{ padding: "10px 16px", borderTop: `1px solid ${T.border}`, fontFamily: FONTS.mono, fontSize: 8.5, color: T.t4, letterSpacing: "0.03em" }}>
        {updated && <>updated {updated.toLocaleTimeString()} · </>}positioning language only · conviction items are discretionary candidates, not advice
      </div>
    </div>
  );
}
