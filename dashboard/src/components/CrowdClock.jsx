import { useState, useEffect, useCallback } from "react";
import { T, FONTS } from "../tokens";

/*
 * Crowd Clock — the behavioral-phase dial (Trader Tom's durable edge, made visible).
 * Where the crowd sits on the eternal loop: capitulation → accumulation → markup →
 * euphoria → distribution. One clock every surface can read. Reads /api/v1/market/crowd-clock.
 * HONEST: a CANDIDATE — instrumented for validation, not yet outcome-proven. Positioning read only.
 */

const PHASES = [
  { key: "capitulation", label: "Capitulation", angle: 234, color: "#22d3ee" },
  { key: "accumulation", label: "Accumulation", angle: 162, color: "#10b981" },
  { key: "markup",       label: "Markup",       angle: 90,  color: "#a3e635" },
  { key: "euphoria",     label: "Euphoria",     angle: 18,  color: "#f59e0b" },
  { key: "distribution", label: "Distribution", angle: 306, color: "#ef4444" },
];
const BYKEY = Object.fromEntries(PHASES.map((p) => [p.key, p]));

// math degrees (0 = east, 90 = north) → SVG coords (y down)
const pt = (cx, cy, r, deg) => {
  const a = (deg * Math.PI) / 180;
  return [cx + r * Math.cos(a), cy - r * Math.sin(a)];
};

async function fetchClock() {
  try {
    const r = await fetch("/api/v1/market/crowd-clock");
    if (!r.ok) throw new Error(`API ${r.status}`);
    return await r.json();
  } catch (e) {
    console.error("CrowdClock:", e);
    return null;
  }
}

export default function CrowdClock() {
  const [d, setD] = useState(null);
  const [loading, setLoading] = useState(true);
  const load = useCallback(async () => { setD(await fetchClock()); setLoading(false); }, []);
  useEffect(() => { load(); const i = setInterval(load, 300000); return () => clearInterval(i); }, [load]);

  const active = d?.phase ? BYKEY[d.phase] : null;
  const cx = 130, cy = 130, R = 96;
  const needleTo = active ? pt(cx, cy, R - 20, active.angle) : [cx, cy];

  return (
    <div style={{ background: T.surface, border: `1px solid ${T.border}`, borderRadius: 14, padding: "18px 20px", marginBottom: 28 }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 8, flexWrap: "wrap", marginBottom: 4 }}>
        <span style={{ fontFamily: FONTS.brand, fontWeight: 700, fontSize: 15, color: T.t1 }}>Crowd Clock</span>
        <span style={{ fontFamily: FONTS.mono, fontSize: 8, fontWeight: 700, letterSpacing: "0.1em", color: T.gold,
          border: `1px solid ${T.gold}55`, background: `${T.gold}12`, padding: "1px 6px", borderRadius: 4 }}>CANDIDATE</span>
        <span style={{ fontFamily: FONTS.mono, fontSize: 9, color: T.t3, marginLeft: "auto" }}>behavioral phase · one clock</span>
      </div>
      <div style={{ fontFamily: FONTS.body, fontSize: 11.5, color: T.t3, marginBottom: 12, lineHeight: 1.5 }}>
        Where the crowd sits on the emotional cycle — the durable, non-decaying edge. Fear and greed recur forever.
      </div>

      {loading ? (
        <div style={{ height: 200, display: "flex", alignItems: "center", justifyContent: "center", fontFamily: FONTS.mono, fontSize: 11, color: T.t3 }}>reading the crowd…</div>
      ) : !d ? (
        <div style={{ height: 120, display: "flex", alignItems: "center", justifyContent: "center", fontFamily: FONTS.mono, fontSize: 11, color: T.t3 }}>Clock warming up.</div>
      ) : (
        <div style={{ display: "flex", gap: 22, flexWrap: "wrap", alignItems: "center" }}>
          {/* the dial */}
          <svg width="260" height="260" viewBox="0 0 260 260" style={{ flexShrink: 0 }}>
            <circle cx={cx} cy={cy} r={R} fill="none" stroke="rgba(255,255,255,0.06)" strokeWidth="1" />
            <circle cx={cx} cy={cy} r={R - 40} fill="none" stroke="rgba(255,255,255,0.04)" strokeWidth="1" />
            {/* phase ticks + labels */}
            {PHASES.map((p) => {
              const [tx, ty] = pt(cx, cy, R, p.angle);
              const [lx, ly] = pt(cx, cy, R + 18, p.angle);
              const on = active && active.key === p.key;
              return (
                <g key={p.key}>
                  <circle cx={tx} cy={ty} r={on ? 6 : 3.5} fill={p.color} opacity={on ? 1 : 0.5}
                    style={{ filter: on ? `drop-shadow(0 0 8px ${p.color})` : "none" }} />
                  <text x={lx} y={ly} fill={on ? p.color : T.t3} fontSize="9.5" fontWeight={on ? 700 : 400}
                    fontFamily={FONTS.mono} textAnchor={lx > cx + 4 ? "start" : lx < cx - 4 ? "end" : "middle"}
                    dominantBaseline="middle">{p.label}</text>
                </g>
              );
            })}
            {/* needle */}
            {active && (
              <>
                <line x1={cx} y1={cy} x2={needleTo[0]} y2={needleTo[1]} stroke={active.color} strokeWidth="2.5"
                  strokeLinecap="round" style={{ filter: `drop-shadow(0 0 6px ${active.color})` }} />
                <circle cx={cx} cy={cy} r="5" fill={active.color} />
              </>
            )}
            {/* center read */}
            <text x={cx} y={cy - 52} fill={active?.color || T.t2} fontSize="13" fontWeight="700"
              fontFamily={FONTS.brand} textAnchor="middle">{active?.label || "—"}</text>
          </svg>

          {/* the read */}
          <div style={{ flex: 1, minWidth: 220 }}>
            <div style={{ fontFamily: FONTS.body, fontSize: 12.5, color: T.t2, lineHeight: 1.6, marginBottom: 10 }}>{d.posture}</div>
            {d.confidence != null && (
              <div style={{ fontFamily: FONTS.mono, fontSize: 10, color: T.t3, marginBottom: 10 }}>
                phase conviction <span style={{ color: active?.color || T.t2 }}>{Math.round(d.confidence * 100)}%</span> (separation from the runner-up)
              </div>
            )}
            {Array.isArray(d.drivers) && d.drivers.length > 0 && (
              <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 12 }}>
                {d.drivers.map((dr, i) => (
                  <span key={i} style={{ fontFamily: FONTS.mono, fontSize: 9, color: T.t2, background: T.raised || "rgba(255,255,255,0.03)",
                    border: `1px solid ${T.border}`, padding: "2px 7px", borderRadius: 4 }}>{dr}</span>
                ))}
              </div>
            )}
            <div style={{ fontFamily: FONTS.mono, fontSize: 8.5, color: T.t4, lineHeight: 1.5, borderTop: `1px solid ${T.border}`, paddingTop: 8 }}>
              {d.disclaimer}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
