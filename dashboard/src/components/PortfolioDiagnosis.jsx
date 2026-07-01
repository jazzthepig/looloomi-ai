import React, { useState } from "react";
import { T, FONTS } from "../tokens";

/* One object (your book) + one action (Diagnose). The iPod: simple, honest,
   one job — drop your holdings, get a read and the few moves toward beta+. */

const GRADE_COLOR = {
  "A+": "#00D98A", "A": "#00D98A", "B+": "#00D98A",
  "B": "#f59e0b", "C+": "#f59e0b", "C": "#fb923c",
  "D": "#FF3D5A", "F": "#FF3D5A",
};
const gc = (g) => GRADE_COLOR[g] || T.t3;

function parseHoldings(text) {
  // "BTC 30, SPY 20, ONDO" → [{symbol, weight?}]
  return text
    .split(/[,\n]/)
    .map((s) => s.trim())
    .filter(Boolean)
    .map((tok) => {
      const m = tok.match(/^([A-Za-z]{1,6})\s*([\d.]+)?%?$/);
      if (!m) return null;
      return { symbol: m[1].toUpperCase(), weight: m[2] ? parseFloat(m[2]) : null };
    })
    .filter(Boolean);
}

function hashAng(s) {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) % 360;
  return h;
}

/* The generative shadow: your book projected into the conviction field.
   High quality pulls toward the institutional core; off-standard drifts to the
   bubble rim. Size = weight, colour = grade. The high-dim read, made legible. */
function BookField({ holdings }) {
  const CX = 290, CY = 178;
  const rings = [44, 92, 140, 188];
  const nodes = (holdings || []).map((h) => {
    const off = !h.grade;
    const cis = typeof h.cis === "number" ? h.cis : 25;
    const r = off
      ? 202 + (hashAng(h.symbol) % 18)
      : Math.max(38, Math.min(196, 44 + ((85 - cis) / 60) * 148));
    const ang = (hashAng(h.symbol) * Math.PI) / 180;
    return {
      h, col: off ? "#FF5577" : gc(h.grade),
      x: CX + Math.cos(ang) * r, y: CY + Math.sin(ang) * r,
      size: 6 + Math.sqrt(h.weight || 0.1) * 15,
    };
  });
  return (
    <svg viewBox="0 0 580 372" style={{ width: "100%", display: "block", margin: "8px 0 2px" }}>
      {rings.map((r, i) => (
        <circle key={r} cx={CX} cy={CY} r={r} fill="none" stroke={T.blue} strokeWidth="1" strokeOpacity={0.2 - i * 0.04} />
      ))}
      <circle cx={CX} cy={CY} r="5" fill={T.blue} />
      <text x={CX} y={CY - 12} textAnchor="middle" fontSize="9" fill={T.t3} fontFamily={FONTS.display} letterSpacing="0.08em">INSTITUTIONAL CORE</text>
      <circle cx={CX} cy={CY} r="214" fill="none" stroke={T.red} strokeWidth="1" strokeOpacity="0.2" strokeDasharray="4 5" />
      <text x={CX} y={CY - 222} textAnchor="middle" fontSize="9" fill={T.red} fillOpacity="0.6" fontFamily={FONTS.display}>off-standard rim</text>
      {nodes.map(({ h, x, y, col, size }, i) => (
        <g key={h.symbol + i}>
          <line x1={CX} y1={CY} x2={x} y2={y} stroke={col} strokeWidth="1" strokeOpacity="0.16" />
          <circle cx={x} cy={y} r={size + 5} fill={col} fillOpacity="0.12" />
          <circle cx={x} cy={y} r={size} fill={col} fillOpacity="0.9">
            <animate attributeName="fill-opacity" values="0.9;0.5;0.9" dur={`${2.4 + (h.weight || 0.1) * 2}s`} repeatCount="indefinite" />
          </circle>
          <text x={x} y={y - size - 4} textAnchor="middle" fontSize="10" fontWeight="600" fill={T.t1} fontFamily={FONTS.display}>{h.symbol}</text>
        </g>
      ))}
    </svg>
  );
}

export default function PortfolioDiagnosis() {
  const [text, setText] = useState("");
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState(null);

  const run = async () => {
    const holdings = parseHoldings(text);
    if (!holdings.length) { setErr("Type a few tickers — e.g. BTC 30, SPY 20, ONDO 15"); return; }
    setErr(null); setLoading(true); setData(null);
    try {
      const r = await fetch("/api/v1/portfolio/diagnose", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ holdings }),
      });
      setData(await r.json());
    } catch (e) {
      setErr("Couldn't reach the engine — try again in a moment.");
    } finally {
      setLoading(false);
    }
  };

  const b = data?.book;

  return (
    <div style={{ maxWidth: 720, margin: "0 auto", padding: "8px 0" }}>
      <div style={{ fontFamily: FONTS.brand, fontSize: 22, fontWeight: 700, color: T.t1 }}>
        Diagnose your book
      </div>
      <div style={{ fontFamily: FONTS.body, fontSize: 13, color: T.t3, marginTop: 4, marginBottom: 18 }}>
        Drop your holdings. The engine reads them and gives you the few moves that tighten toward beta+. No magic, no 500x — a good assistant.
      </div>

      <div style={{ display: "flex", gap: 8 }}>
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && run()}
          placeholder="BTC 30, SPY 20, ONDO 15, NVDA 10, DOGE 15…"
          style={{
            flex: 1, background: T.surface, border: `1px solid ${T.border}`,
            borderRadius: 10, padding: "12px 14px", color: T.t1,
            fontFamily: FONTS.mono, fontSize: 13, outline: "none",
          }}
        />
        <button onClick={run} disabled={loading}
          style={{
            background: loading ? T.surface : T.blue, color: loading ? T.t3 : "#fff",
            border: "none", borderRadius: 10, padding: "0 20px", fontFamily: FONTS.display,
            fontWeight: 600, fontSize: 13, cursor: loading ? "default" : "pointer",
          }}>
          {loading ? "Reading…" : "Diagnose"}
        </button>
      </div>
      {err && <div style={{ color: T.red, fontSize: 12, marginTop: 8 }}>{err}</div>}

      {data && !data.error && (
        <div style={{ marginTop: 22 }}>
          {/* Book line */}
          <div style={{
            display: "flex", gap: 18, flexWrap: "wrap", alignItems: "baseline",
            padding: "14px 16px", background: T.surface, border: `1px solid ${T.border}`,
            borderRadius: 12,
          }}>
            <Stat label="Book grade" value={b.grade} color={gc(b.grade)} mono />
            <Stat label="Avg CIS" value={b.avg_cis != null ? b.avg_cis.toFixed(1) : "—"} mono />
            <Stat label="Off-standard" value={`${b.off_standard_pct}%`}
                  color={b.off_standard_pct >= 40 ? T.red : b.off_standard_pct >= 15 ? T.amber : T.green} mono />
            <Stat label="Regime" value={data.as_of_regime} />
          </div>

          {/* The generative shadow — your book in the field */}
          <BookField holdings={data.holdings} />

          {/* Verdict */}
          <div style={{
            fontFamily: FONTS.body, fontSize: 14, color: T.t1, lineHeight: 1.65,
            margin: "16px 2px", borderLeft: `2px solid ${T.gold}`, paddingLeft: 12,
          }}>
            {data.verdict}
          </div>

          {/* The few moves */}
          {data.moves?.length > 0 && (
            <div style={{ marginTop: 8 }}>
              <div style={{ fontFamily: FONTS.display, fontSize: 10, letterSpacing: "0.1em",
                textTransform: "uppercase", color: T.t3, marginBottom: 8 }}>The moves</div>
              {data.moves.map((m, i) => (
                <div key={i} style={{
                  display: "flex", gap: 10, alignItems: "flex-start", padding: "9px 0",
                  borderBottom: i < data.moves.length - 1 ? `1px solid ${T.border}` : "none",
                }}>
                  <span style={{
                    fontFamily: FONTS.mono, fontSize: 9, fontWeight: 700, textTransform: "uppercase",
                    color: m.action === "rotate" ? T.blue : T.amber, marginTop: 2, minWidth: 46,
                  }}>{m.action}</span>
                  <span style={{ fontFamily: FONTS.body, fontSize: 13, color: T.t2, lineHeight: 1.5 }}>{m.detail}</span>
                </div>
              ))}
            </div>
          )}

          {/* Per-holding chips */}
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 18 }}>
            {data.holdings?.map((h) => (
              <span key={h.symbol} style={{
                fontFamily: FONTS.mono, fontSize: 11, padding: "4px 9px", borderRadius: 6,
                background: "rgba(255,255,255,0.03)", border: `1px solid ${gc(h.grade)}33`,
                color: T.t2,
              }}>
                {h.symbol} <span style={{ color: gc(h.grade), fontWeight: 700 }}>{h.grade || "—"}</span>
              </span>
            ))}
          </div>

          <div style={{ fontFamily: FONTS.body, fontSize: 10, color: T.t3, marginTop: 16 }}>
            {data.note}
          </div>
        </div>
      )}
    </div>
  );
}

function Stat({ label, value, color, mono }) {
  return (
    <div>
      <div style={{ fontFamily: FONTS.display, fontSize: 9, letterSpacing: "0.08em",
        textTransform: "uppercase", color: T.t3 }}>{label}</div>
      <div style={{ fontFamily: mono ? FONTS.mono : FONTS.display, fontSize: 16, fontWeight: 700,
        color: color || T.t1, marginTop: 2 }}>{value}</div>
    </div>
  );
}
