import React, { useState, useEffect } from "react";
import { T, FONTS } from "../tokens";

/* Risk Meter — the judgment→behavior link made visible. Reads /api/v1/portfolio/risk-meter:
   the book's exposure-weighted out-of-circle fragility as a 0..1 needle, plus the
   holdings dragging it and how much each is trimmed below its raw CIS-grade weight.
   The point: two A-grade names are NOT equally safe — the crowded, out-of-circle one is
   trimmed. beta+ from being closer to the cause, not the reflection (CIS). */

const BAND = {
  low:      { c: "#00D98A", label: "IN-CIRCLE" },
  elevated: { c: "#f59e0b", label: "DIFFUSING" },
  high:     { c: "#FF3D5A", label: "OUT-OF-CIRCLE" },
};

function Needle({ reading, band }) {
  const c = (BAND[band] || BAND.low).c;
  const a = Math.PI * (1 - Math.max(0, Math.min(1, reading))); // 0→right, 1→left
  const cx = 110, cy = 104, r = 84;
  const x = cx + r * Math.cos(a), y = cy - r * Math.sin(a);
  const arc = (t0, t1, col, w) => {
    const p0 = [cx + r * Math.cos(Math.PI * (1 - t0)), cy - r * Math.sin(Math.PI * (1 - t0))];
    const p1 = [cx + r * Math.cos(Math.PI * (1 - t1)), cy - r * Math.sin(Math.PI * (1 - t1))];
    return <path d={`M ${p0[0]} ${p0[1]} A ${r} ${r} 0 0 1 ${p1[0]} ${p1[1]}`}
      stroke={col} strokeWidth={w} fill="none" strokeLinecap="round" />;
  };
  return (
    <svg viewBox="0 0 220 124" width="220" height="124">
      {arc(0, 0.33, "#00D98A", 7)}
      {arc(0.33, 0.60, "#f59e0b", 7)}
      {arc(0.60, 1, "#FF3D5A", 7)}
      <line x1={cx} y1={cy} x2={x} y2={y} stroke={c} strokeWidth="3" strokeLinecap="round" />
      <circle cx={cx} cy={cy} r="5" fill={c} />
      <text x={cx} y={cy - 22} textAnchor="middle" fill={c}
        style={{ font: `700 26px ${FONTS.mono}` }}>{(reading * 100).toFixed(0)}</text>
      <text x={cx} y={cy - 6} textAnchor="middle" fill={T.t3}
        style={{ font: `600 8px ${FONTS.mono}`, letterSpacing: "0.12em" }}>OUT-OF-CIRCLE</text>
    </svg>
  );
}

export default function RiskMeter() {
  const [d, setD] = useState(null);
  const [err, setErr] = useState(false);

  useEffect(() => {
    let on = true;
    fetch("/api/v1/portfolio/risk-meter")
      .then((r) => r.json())
      .then((j) => { if (on) (j && j.meter ? setD(j) : setErr(true)); })
      .catch(() => on && setErr(true));
    return () => { on = false; };
  }, []);

  if (err) return null;
  const card = {
    background: T.surface, border: `1px solid ${T.border}`, borderRadius: 14,
    padding: "20px 22px", fontFamily: FONTS.body,
  };
  if (!d) return <div style={{ ...card, color: T.t3, font: `500 12px ${FONTS.body}` }}>Reading the book…</div>;

  const m = d.meter, band = BAND[m.band] || BAND.low;
  const contributors = m.top_risk_contributors || [];

  return (
    <div style={card}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 4 }}>
        <div style={{ font: `600 14px ${FONTS.head}`, color: T.t1, letterSpacing: "0.02em" }}>Risk Meter</div>
        <div style={{ font: `600 10px ${FONTS.mono}`, color: T.t3, letterSpacing: "0.1em" }}>
          {d.regime} · {d.universe_size} assets
        </div>
      </div>
      <div style={{ font: `500 10.5px ${FONTS.body}`, color: T.t3, marginBottom: 12 }}>
        Book’s out-of-circle fragility — crowded consensus, trimmed.
      </div>

      <div style={{ display: "flex", gap: 20, alignItems: "center", flexWrap: "wrap" }}>
        <div style={{ textAlign: "center" }}>
          <Needle reading={m.reading} band={m.band} />
          <div style={{ font: `700 10px ${FONTS.mono}`, color: band.c, letterSpacing: "0.14em", marginTop: -6 }}>
            {band.label}
          </div>
        </div>
        <div style={{ flex: 1, minWidth: 220, font: `500 12px ${FONTS.body}`, color: T.t2, lineHeight: 1.5 }}>
          {m.interpretation}
        </div>
      </div>

      {contributors.length > 0 && (
        <div style={{ marginTop: 16 }}>
          <div style={{ font: `600 9.5px ${FONTS.mono}`, color: T.t3, letterSpacing: "0.12em", marginBottom: 8 }}>
            HOLDINGS DRAGGING THE METER
          </div>
          {contributors.map((c) => {
            const rc = c.risk_score >= 0.6 ? "#FF3D5A" : c.risk_score >= 0.33 ? "#f59e0b" : "#00D98A";
            return (
              <div key={c.symbol} style={{ display: "flex", alignItems: "center", gap: 10, padding: "5px 0",
                borderTop: `1px solid ${T.border}` }}>
                <div style={{ width: 56, font: `600 12px ${FONTS.mono}`, color: T.t1 }}>{c.symbol}</div>
                <div style={{ flex: 1, height: 6, background: "rgba(255,255,255,0.05)", borderRadius: 3, overflow: "hidden" }}>
                  <div style={{ width: `${Math.round(c.risk_score * 100)}%`, height: "100%", background: rc }} />
                </div>
                <div style={{ width: 44, textAlign: "right", font: `600 11px ${FONTS.mono}`, color: rc }}>
                  {(c.risk_score * 100).toFixed(0)}
                </div>
                <div style={{ width: 60, textAlign: "right", font: `500 11px ${FONTS.mono}`, color: T.t2 }}>
                  w {(c.weight * 100).toFixed(1)}%
                </div>
              </div>
            );
          })}
          <div style={{ font: `500 9.5px ${FONTS.body}`, color: T.t3, marginTop: 8, lineHeight: 1.5 }}>
            Score = out-of-circle risk (D4 attention + market proxy; D3 holders when live).
            High-risk longs are trimmed below their raw CIS-grade weight; the freed weight
            rotates to in-circle names.
          </div>
        </div>
      )}
    </div>
  );
}
