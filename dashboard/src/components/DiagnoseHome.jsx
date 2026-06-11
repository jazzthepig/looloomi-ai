import React, { useState, useEffect, useRef } from "react";
import { T, FONTS } from "../tokens";

/* The front door. Drop your book; see it projected into the conviction field;
   drag a holding toward the core to rotate it into a stronger same-class name —
   the engine recomputes your book's CIS live. The iPod: one lovable job.
   Live data from /api/v1/cis/universe. The terminal lives behind a link. */

const GC = { "A+": "#00D98A", "A": "#00D98A", "B+": "#00D98A", "B": "#f59e0b",
  "C+": "#f59e0b", "C": "#fb923c", "D": "#FF3D5A", "F": "#FF3D5A" };
const KEEP = { "A+": 1, "A": 1, "B+": 1 };
const CX = 300, CY = 210;

function hashAng(s) { let h = 0; for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) % 360; return h; }
function radius(h) { return !h.g ? 222 + (hashAng(h.s) % 18) : Math.max(40, Math.min(208, 46 + ((85 - h.cis) / 60) * 162)); }
function posOf(h) { const a = hashAng(h.s) * Math.PI / 180, r = radius(h); return [CX + Math.cos(a) * r, CY + Math.sin(a) * r]; }
function statsOf(b) { let wc = 0, ws = 0, off = 0; b.forEach(h => { if (h.g) { ws += h.cis * h.w; wc += h.w; if (!KEEP[h.g]) off += h.w; } else off += h.w; }); return { cis: wc ? ws / wc : 0, off: Math.round(off * 100) }; }

export default function DiagnoseHome({ onEnter, embedded = false }) {
  const [uni, setUni] = useState(null);
  const [text, setText] = useState("BTC 30, SPY 20, ONDO 15, NVDA 10, DOGE 15, PEPE 10");
  const [book, setBook] = useState(null);
  const [orig, setOrig] = useState(null);
  const [drag, setDrag] = useState(null);
  const svgRef = useRef(null);

  useEffect(() => {
    (async () => {
      try {
        const r = await fetch("/api/v1/cis/universe");
        const j = await r.json();
        const map = {};
        (j.universe || []).forEach(a => { if (a.symbol) map[a.symbol.toUpperCase()] = [a.grade, a.cis_score, a.asset_class]; });
        setUni({ map, regime: j.macro_regime || "—" });
      } catch (e) { setUni({ map: {}, regime: "—" }); }
    })();
  }, []);

  const mk = (s, w) => { const u = uni && uni.map[s]; return { s, w, g: u ? u[0] : null, cis: u ? u[1] : null, cl: u ? u[2] : "—" }; };

  const run = () => {
    if (!uni) return;
    let hs = text.split(/[,\n]/).map(t => t.trim()).filter(Boolean)
      .map(tok => { const m = tok.match(/^([A-Za-z]{1,6})\s*([\d.]+)?/); return m ? { s: m[1].toUpperCase(), w: m[2] ? parseFloat(m[2]) : null } : null; })
      .filter(Boolean);
    if (!hs.length) return;
    if (hs.every(h => h.w == null)) hs.forEach(h => h.w = 1 / hs.length);
    else { const tot = hs.reduce((a, h) => a + (h.w || 0), 0) || 1; hs.forEach(h => h.w = (h.w || 0) / tot); }
    const b = hs.map(h => mk(h.s, h.w));
    setBook(b); setOrig(statsOf(b)); setDrag(null);
  };

  const bestAlt = (h) => {
    if (!uni) return null;
    const held = book.map(x => x.s);
    const pool = Object.keys(uni.map).filter(k => held.indexOf(k) < 0 && KEEP[uni.map[k][0]]);
    const same = pool.filter(k => uni.map[k][2] === h.cl && uni.map[k][1] > (h.cis || 0));
    const cand = same.length ? same : pool;
    if (!cand.length) return null;
    cand.sort((a, b) => uni.map[b][1] - uni.map[a][1]);
    return cand[0];
  };

  const toSvg = (e) => {
    const p = svgRef.current.createSVGPoint(); p.x = e.clientX; p.y = e.clientY;
    const q = p.matrixTransform(svgRef.current.getScreenCTM().inverse()); return [q.x, q.y];
  };
  const onDown = (i) => (e) => { e.preventDefault(); setDrag({ i, alt: bestAlt(book[i]), pos: posOf(book[i]) }); svgRef.current.setPointerCapture(e.pointerId); };
  const onMove = (e) => { if (!drag) return; setDrag(d => ({ ...d, pos: toSvg(e) })); };
  const onUp = (e) => {
    if (!drag) { return; }
    const p = toSvg(e); const d = Math.hypot(p[0] - CX, p[1] - CY);
    if (d < 165 && drag.alt) { setBook(b => b.map((h, i) => i === drag.i ? mk(drag.alt, h.w) : h)); }
    setDrag(null);
  };

  const cur = book ? statsOf(book) : null;

  return (
    <div style={embedded ? { color: T.t2 } : { background: T.deep, minHeight: "100vh", color: T.t2 }}>
      {/* top bar — front-door only */}
      {!embedded && (
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "20px 28px" }}>
          <div style={{ fontFamily: FONTS.brand, fontWeight: 800, fontSize: 18, color: T.t1, letterSpacing: "0.04em" }}>
            COMETCLOUD <span style={{ fontFamily: FONTS.mono, fontSize: 9, color: T.blue }}>AI</span>
          </div>
          {onEnter && (
            <button onClick={onEnter} style={{ background: "transparent", border: `1px solid ${T.border}`, borderRadius: 9, padding: "8px 16px", color: T.t2, fontFamily: FONTS.display, fontSize: 12, cursor: "pointer" }}>
              Open the terminal →
            </button>
          )}
        </div>
      )}

      <div style={embedded ? { maxWidth: 760, margin: "0 auto", padding: "0" } : { maxWidth: 760, margin: "0 auto", padding: "10px 24px 60px" }}>
        <div style={{ fontFamily: FONTS.brand, fontSize: embedded ? 22 : 30, fontWeight: 700, color: T.t1, lineHeight: 1.1 }}>
          Diagnose your book.
        </div>
        <div style={{ fontFamily: FONTS.body, fontSize: 14, color: T.t3, marginTop: 8, marginBottom: 22, maxWidth: 540 }}>
          Drop your holdings. See them in the conviction field. Drag the weak ones toward the core — the engine shows the few moves toward beta+. No magic, no 500x. A good assistant.
        </div>

        <div style={{ display: "flex", gap: 8 }}>
          <input value={text} onChange={e => setText(e.target.value)} onKeyDown={e => e.key === "Enter" && run()}
            placeholder="BTC 30, SPY 20, ONDO 15, NVDA 10, DOGE 15…"
            style={{ flex: 1, background: T.surface, border: `1px solid ${T.border}`, borderRadius: 10, padding: "12px 14px", color: T.t1, fontFamily: FONTS.mono, fontSize: 13, outline: "none" }} />
          <button onClick={run} disabled={!uni}
            style={{ background: uni ? T.blue : T.surface, color: uni ? "#fff" : T.t3, border: "none", borderRadius: 10, padding: "0 22px", fontFamily: FONTS.display, fontWeight: 600, fontSize: 13, cursor: uni ? "pointer" : "default" }}>
            {uni ? "Diagnose" : "Loading…"}
          </button>
        </div>

        {book && (
          <div style={{ marginTop: 18 }}>
            <div style={{ fontSize: 13, color: T.t2, marginBottom: 4 }}>
              Book CIS <b style={{ color: T.t1 }}>{orig.cis.toFixed(1)}{Math.abs(orig.cis - cur.cis) > 0.05 && <span style={{ color: T.green }}> → {cur.cis.toFixed(1)}</span>}</b>
              {"  ·  "}off-standard <b style={{ color: T.t1 }}>{orig.off}%{orig.off !== cur.off && <span style={{ color: T.green }}> → {cur.off}%</span>}</b>
              {"  ·  "}regime {uni.regime}
            </div>

            <svg ref={svgRef} viewBox="0 0 600 432" onPointerMove={onMove} onPointerUp={onUp}
              style={{ width: "100%", display: "block", touchAction: "none" }}>
              {[48, 100, 152, 204].map((r, i) => <circle key={r} cx={CX} cy={CY} r={r} fill="none" stroke={T.blue} strokeWidth="1" strokeOpacity={0.2 - i * 0.04} />)}
              <circle cx={CX} cy={CY} r="5" fill={T.blue} />
              <text x={CX} y={CY - 12} textAnchor="middle" fontSize="9" fill={T.t3} fontFamily={FONTS.display} letterSpacing="0.08em">INSTITUTIONAL CORE</text>
              <circle cx={CX} cy={CY} r="246" fill="none" stroke={T.red} strokeWidth="1" strokeOpacity="0.18" strokeDasharray="4 5" />
              {book.map((h, i) => {
                const p = drag && drag.i === i ? drag.pos : posOf(h);
                const col = h.g ? (GC[h.g] || "#888") : "#FF5577";
                const size = 6 + Math.sqrt(h.w || 0.1) * 16;
                const alt = drag && drag.i === i && drag.alt;
                const ap = alt ? posOf(mk(drag.alt, h.w)) : null;
                return (
                  <g key={h.s + i}>
                    <line x1={CX} y1={CY} x2={p[0]} y2={p[1]} stroke={col} strokeWidth="1" strokeOpacity="0.16" />
                    {alt && <>
                      <circle cx={ap[0]} cy={ap[1]} r={size} fill="none" stroke={GC[uni.map[drag.alt][0]]} strokeWidth="1.5" strokeDasharray="3 3" strokeOpacity="0.85" />
                      <text x={ap[0]} y={ap[1] - size - 4} textAnchor="middle" fontSize="10" fontWeight="600" fill={GC[uni.map[drag.alt][0]]}>→ {drag.alt}</text>
                    </>}
                    <circle cx={p[0]} cy={p[1]} r={size + 5} fill={col} fillOpacity="0.12" />
                    <circle cx={p[0]} cy={p[1]} r={size} fill={col} fillOpacity="0.9" style={{ cursor: "grab" }} onPointerDown={onDown(i)}>
                      <animate attributeName="fill-opacity" values="0.9;0.55;0.9" dur={`${2.4 + (h.w || 0.1) * 2}s`} repeatCount="indefinite" />
                    </circle>
                    <text x={p[0]} y={p[1] - size - 4} textAnchor="middle" fontSize="10" fontWeight="600" fill={T.t1} fontFamily={FONTS.display} style={{ pointerEvents: "none" }}>{h.s}</text>
                  </g>
                );
              })}
            </svg>

            <div style={{ fontFamily: FONTS.body, fontSize: 14, color: T.t1, lineHeight: 1.6, margin: "10px 2px", borderLeft: `2px solid ${T.gold}`, paddingLeft: 12 }}>
              {cur.off >= 40 ? `Heavy off-standard exposure: ${cur.off}% of the book sits below the institutional bar. Drag those toward the core.`
                : cur.off >= 15 ? `Solid core, but ${cur.off}% is off-standard. A few rotations lift the whole book.`
                  : `Clean book — ${cur.off}% off-standard. Mostly hold.`}
            </div>
            <div style={{ fontFamily: FONTS.body, fontSize: 10, color: T.t3, marginTop: 6 }}>
              Positioning toward enhanced beta — not investment advice or a promise of returns.
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
