import React, { useState, useEffect, useRef } from "react";
import { T, FONTS } from "../tokens";

/* The front door. Drop your book; see it projected into the conviction field;
   drag a holding toward the core to rotate it into a stronger same-class name —
   the engine recomputes your book's CIS live. The iPod: one lovable job.
   Live data from /api/v1/cis/universe. The terminal lives behind a link. */

const GC = { "A+": "#00D98A", "A": "#00D98A", "B+": "#00D98A", "B": "#f59e0b",
  "C+": "#f59e0b", "C": "#fb923c", "D": "#FF3D5A", "F": "#FF3D5A" };
const KEEP = { "A+": 1, "A": 1, "B+": 1 };
const CX = 300, CY = 220;

const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
function hashAng(s) { let h = 0; for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) % 360; return h; }

/* Cause-proximity (0..1) — the SECOND axis. v1 transparent proxy from CIS pillars:
   idiosyncratic alpha (A) pulls upstream; a move that already ran (high M + high 30d)
   and euphoric sentiment (S) push downstream; risk-adjusted quality (O) lifts slightly.
   Roadmap: replace with traceable-decision proximity (earnings/flows/index events) for TradFi. */
function causeProx(P, c30) {
  if (!P) return 0.25;
  const A = P.A ?? 50, M = P.M ?? 50, O = P.O ?? 50, S = P.S ?? 50;
  const alphaEdge = A / 100;
  const late = clamp((M - 60) / 40, 0, 1) * clamp((c30 || 0) / 40, 0, 1);
  const crowd = clamp((S - 72) / 28, 0, 1);
  const qual = clamp((O - 50) / 50, -1, 1);
  return clamp(0.45 + 0.42 * alphaEdge - 0.34 * late - 0.22 * crowd + 0.12 * qual, 0.05, 0.95);
}

// Radius = quality (high CIS → core). Off-standard names sit at the rim.
function radius(h) { return !h.g ? 222 + (hashAng(h.s) % 16) : clamp(46 + ((85 - h.cis) / 60) * 150, 40, 196); }
// Position: distance = quality, vertical elevation = cause-proximity (up = upstream),
// horizontal side spread by hash so similar-proximity names fan out instead of stacking.
function posOf(h) {
  const r = radius(h);
  const side = (hashAng(h.s) % 2 === 0) ? 1 : -1;
  const c = !h.g ? 0.12 : (h.cause ?? 0.5);   // off-standard → downstream
  const elev = (c - 0.5) * Math.PI * 0.82;
  return [CX + side * Math.cos(elev) * r, CY - Math.sin(elev) * r];
}
function statsOf(b) { let wc = 0, ws = 0, off = 0; b.forEach(h => { if (h.g) { ws += h.cis * h.w; wc += h.w; if (!KEEP[h.g]) off += h.w; } else off += h.w; }); return { cis: wc ? ws / wc : 0, off: Math.round(off * 100) }; }

/* Seed the diagnosis from the user's real book (MyPortfolio localStorage).
   Position value (units × entry) becomes the weight; watchlist-only names get
   the average position value so they're represented. Returns null if empty. */
function seedFromBook() {
  try {
    const p = JSON.parse(localStorage.getItem("cc_portfolio") || "null");
    const wl = (p && p.watchlist) || [];
    if (!wl.length) return null;
    const pos = p.positions || {};
    const vals = wl.map(s => { const q = pos[s]; const v = q && q.units && q.entry ? q.units * q.entry : 0; return [s, v]; });
    const present = vals.filter(([, v]) => v > 0);
    if (!present.length) return wl.join(", ");           // no positions → equal weight
    const avg = present.reduce((a, [, v]) => a + v, 0) / present.length;
    return vals.map(([s, v]) => `${s} ${Math.round((v > 0 ? v : avg))}`).join(", ");
  } catch { return null; }
}

export default function DiagnoseHome({ onEnter, embedded = false }) {
  const [uni, setUni] = useState(null);
  const [text, setText] = useState(() => (embedded && seedFromBook()) || "BTC 30, SPY 20, ONDO 15, NVDA 10, DOGE 15, PEPE 10");
  const [book, setBook] = useState(null);
  const [orig, setOrig] = useState(null);
  const [drag, setDrag] = useState(null);
  const [fromBook, setFromBook] = useState(() => embedded && !!seedFromBook());
  const svgRef = useRef(null);
  const seededRef = useRef(false);

  useEffect(() => {
    (async () => {
      try {
        const r = await fetch("/api/v1/cis/universe");
        const j = await r.json();
        const map = {};
        (j.universe || []).forEach(a => { if (a.symbol) map[a.symbol.toUpperCase()] = { g: a.grade, cis: a.cis_score, cl: a.asset_class, P: a.pillars || null, c30: a.change_30d }; });
        setUni({ map, regime: j.macro_regime || "—" });
      } catch (e) { setUni({ map: {}, regime: "—" }); }
    })();
  }, []);

  const mk = (s, w) => { const u = uni && uni.map[s]; return { s, w, g: u ? u.g : null, cis: u ? u.cis : null, cl: u ? u.cl : "—", cause: u ? causeProx(u.P, u.c30) : null }; };

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
    const pool = Object.keys(uni.map).filter(k => held.indexOf(k) < 0 && KEEP[uni.map[k].g]);
    const same = pool.filter(k => uni.map[k].cl === h.cl && uni.map[k].cis > (h.cis || 0));
    const cand = same.length ? same : pool;
    if (!cand.length) return null;
    cand.sort((a, b) => uni.map[b].cis - uni.map[a].cis);
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

  // Embedded in Portfolio: auto-diagnose the user's real book once the universe loads.
  useEffect(() => {
    if (embedded && uni && fromBook && !seededRef.current) { seededRef.current = true; run(); }
  }, [uni]); // eslint-disable-line react-hooks/exhaustive-deps

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
        <div style={{ fontFamily: FONTS.body, fontSize: 14, color: T.t3, marginTop: 8, marginBottom: fromBook ? 10 : 22, maxWidth: 540 }}>
          {fromBook
            ? "Your watchlist, read into the conviction field. Drag the weak ones toward the core — the engine shows the few moves toward beta+."
            : "Drop your holdings. See them in the conviction field. Drag the weak ones toward the core — the engine shows the few moves toward beta+. No magic, no 500x. A good assistant."}
        </div>

        {fromBook && (
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 14 }}>
            <span style={{ fontFamily: FONTS.mono, fontSize: 10, color: T.green, background: "rgba(0,217,138,0.08)", border: `1px solid ${T.green}33`, borderRadius: 5, padding: "3px 8px" }}>
              ◎ Loaded from My Portfolio
            </span>
            <button onClick={() => { setFromBook(false); setText("BTC 30, SPY 20, ONDO 15, NVDA 10, DOGE 15, PEPE 10"); }}
              style={{ background: "transparent", border: "none", color: T.t3, fontFamily: FONTS.body, fontSize: 11, cursor: "pointer", textDecoration: "underline", padding: 0 }}>
              use a sample instead
            </button>
          </div>
        )}

        <div style={{ display: "flex", gap: 8 }}>
          <input value={text} onChange={e => { setText(e.target.value); if (fromBook) setFromBook(false); }} onKeyDown={e => e.key === "Enter" && run()}
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

            <svg ref={svgRef} viewBox="0 0 600 472" onPointerMove={onMove} onPointerUp={onUp}
              style={{ width: "100%", display: "block", touchAction: "none" }}>
              {/* vertical cause axis guide + labels */}
              <line x1={CX} y1="30" x2={CX} y2="412" stroke={T.t3} strokeWidth="1" strokeOpacity="0.10" strokeDasharray="2 6" />
              <text x={CX} y="22" textAnchor="middle" fontSize="9" fill={T.green} fontFamily={FONTS.display} letterSpacing="0.12em">▲ UPSTREAM · nearer the cause</text>
              <text x={CX} y="430" textAnchor="middle" fontSize="9" fill={T.red} fillOpacity="0.7" fontFamily={FONTS.display} letterSpacing="0.12em">▼ DOWNSTREAM · exposed, late</text>
              {/* quality rings */}
              {[48, 100, 152, 196].map((r, i) => <circle key={r} cx={CX} cy={CY} r={r} fill="none" stroke={T.blue} strokeWidth="1" strokeOpacity={0.2 - i * 0.04} />)}
              <circle cx={CX} cy={CY} r="5" fill={T.blue} />
              <text x={CX} y={CY - 12} textAnchor="middle" fontSize="9" fill={T.t3} fontFamily={FONTS.display} letterSpacing="0.08em">CORE · quality</text>
              <circle cx={CX} cy={CY} r="232" fill="none" stroke={T.red} strokeWidth="1" strokeOpacity="0.14" strokeDasharray="4 5" />
              {book.map((h, i) => {
                const p = drag && drag.i === i ? drag.pos : posOf(h);
                const col = h.g ? (GC[h.g] || "#888") : "#FF5577";
                const size = 6 + Math.sqrt(h.w || 0.1) * 16;
                const alt = drag && drag.i === i && drag.alt;
                const ap = alt ? posOf(mk(drag.alt, h.w)) : null;
                const altG = alt ? (uni.map[drag.alt].g) : null;
                return (
                  <g key={h.s + i}>
                    <line x1={CX} y1={CY} x2={p[0]} y2={p[1]} stroke={col} strokeWidth="1" strokeOpacity="0.16" />
                    {alt && <>
                      <circle cx={ap[0]} cy={ap[1]} r={size} fill="none" stroke={GC[altG]} strokeWidth="1.5" strokeDasharray="3 3" strokeOpacity="0.85" />
                      <text x={ap[0]} y={ap[1] - size - 4} textAnchor="middle" fontSize="10" fontWeight="600" fill={GC[altG]}>→ {drag.alt}</text>
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

            <div style={{ fontFamily: FONTS.mono, fontSize: 9.5, color: T.t3, marginTop: 2, display: "flex", gap: 14, flexWrap: "wrap" }}>
              <span>Radius = quality (CIS)</span>
              <span>Height = proximity to the cause</span>
              <span style={{ opacity: 0.7 }}>v1 positioning read · traceable-decision model next</span>
            </div>

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
