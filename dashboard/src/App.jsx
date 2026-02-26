import { useState, useEffect, useRef, useCallback } from "react";
import {
  TrendingUp, TrendingDown, Activity, Search, RefreshCw,
  ExternalLink, Copy, CheckCircle, XCircle, Clock, Shield,
  ChevronDown, ChevronUp, Wifi, AlertTriangle, Zap,
  BarChart2, Wallet, Eye, ArrowUpRight, Minus
} from "lucide-react";
import {
  AreaChart, Area, LineChart, Line, XAxis, YAxis,
  CartesianGrid, Tooltip, ResponsiveContainer, BarChart, Bar
} from "recharts";

/* ─────────────────────────────────────────────────────────────────────────────
   DESIGN TOKENS — ONDO × a16z × Turrell
───────────────────────────────────────────────────────────────────────────── */
const T = {
  // Surface palette (ONDO-inspired)
  void:    "#07060F",
  deep:    "#0C0B1A",
  surface: "#12112B",
  raised:  "#1A1940",
  border:  "#2A2850",
  borderHi:"#3D3A70",

  // Text
  primary:  "#F0EDFF",  // Turrell moon-white (violet-tinged)
  secondary:"#9893C4",
  muted:    "#5C5888",
  ghost:    "#322F5C",

  // Functional (ONDO)
  blue:   "#4F6EF7",
  blueDim:"#2038B0",
  green:  "#2DD4A0",
  red:    "#F5476A",
  amber:  "#D4AF37",  // a16z gold
  amberDim:"#6B5618",

  // Turrell atmospheric palette
  turrellPink:   "#FF2D78",
  turrellViolet: "#6F02AC",
  turrellIndigo: "#3F44C7",
  turrellDeep:   "#2D1B69",
  turrellDusk:   "#C4A6D9",
};

/* ─────────────────────────────────────────────────────────────────────────────
   GLOBAL STYLES injected once
───────────────────────────────────────────────────────────────────────────── */
const GLOBAL_CSS = `
  @import url('https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=DM+Serif+Display:ital@0;1&family=JetBrains+Mono:wght@300;400;500&family=DM+Sans:wght@300;400;500;600&display=swap');

  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  :root {
    --void:    ${T.void};
    --deep:    ${T.deep};
    --surface: ${T.surface};
    --raised:  ${T.raised};
    --border:  ${T.border};
    --primary: ${T.primary};
    --secondary:${T.secondary};
    --muted:   ${T.muted};
    --blue:    ${T.blue};
    --green:   ${T.green};
    --red:     ${T.red};
    --amber:   ${T.amber};
    --turrell-pink:   ${T.turrellPink};
    --turrell-violet: ${T.turrellViolet};
    --turrell-indigo: ${T.turrellIndigo};
  }

  body { background: ${T.void}; color: ${T.primary}; }

  /* Turrell ambient background animation */
  @keyframes turrellBreathe {
    0%   { opacity: 0.4; }
    50%  { opacity: 0.65; }
    100% { opacity: 0.4; }
  }
  @keyframes turrellShift {
    0%   { transform: scale(1) rotate(0deg); }
    33%  { transform: scale(1.12) rotate(2deg); }
    66%  { transform: scale(0.96) rotate(-1deg); }
    100% { transform: scale(1) rotate(0deg); }
  }
  @keyframes turrellHue {
    0%   { filter: hue-rotate(0deg)   saturate(1.0); }
    25%  { filter: hue-rotate(18deg)  saturate(1.3); }
    50%  { filter: hue-rotate(-12deg) saturate(0.9); }
    75%  { filter: hue-rotate(8deg)   saturate(1.15); }
    100% { filter: hue-rotate(0deg)   saturate(1.0); }
  }
  @keyframes fadeUp {
    from { opacity: 0; transform: translateY(16px); }
    to   { opacity: 1; transform: translateY(0); }
  }
  @keyframes pulseDot {
    0%, 100% { opacity: 1; transform: scale(1); }
    50%       { opacity: 0.5; transform: scale(0.85); }
  }
  @keyframes shimmer {
    0%   { background-position: -200% center; }
    100% { background-position: 200% center; }
  }
  @keyframes scanline {
    0%   { transform: translateY(-100%); }
    100% { transform: translateY(100vh); }
  }
  @keyframes borderGlow {
    0%, 100% { border-color: rgba(79,110,247,0.3); box-shadow: 0 0 0px rgba(79,110,247,0); }
    50%       { border-color: rgba(79,110,247,0.7); box-shadow: 0 0 20px rgba(79,110,247,0.15); }
  }

  .fade-up { animation: fadeUp 0.5s ease forwards; }
  .fade-up-1 { animation: fadeUp 0.5s 0.1s ease both; }
  .fade-up-2 { animation: fadeUp 0.5s 0.2s ease both; }
  .fade-up-3 { animation: fadeUp 0.5s 0.3s ease both; }
  .fade-up-4 { animation: fadeUp 0.5s 0.4s ease both; }

  /* Scrollbar */
  ::-webkit-scrollbar { width: 4px; height: 4px; }
  ::-webkit-scrollbar-track { background: ${T.void}; }
  ::-webkit-scrollbar-thumb { background: ${T.ghost}; border-radius: 2px; }
  ::-webkit-scrollbar-thumb:hover { background: ${T.muted}; }

  /* Selection */
  ::selection { background: rgba(79,110,247,0.3); color: ${T.primary}; }
`;

/* ─────────────────────────────────────────────────────────────────────────────
   TURRELL AMBIENT CANVAS
───────────────────────────────────────────────────────────────────────────── */
function TurrellAmbient() {
  return (
    <div style={{
      position: "fixed", inset: 0, zIndex: 0,
      pointerEvents: "none", overflow: "hidden",
    }}>
      {/* Primary void gradient */}
      <div style={{
        position: "absolute", inset: 0,
        background: `radial-gradient(ellipse 120% 80% at 50% 0%, ${T.turrellDeep}55 0%, ${T.void} 60%)`,
      }} />
      {/* Turrell orb — left */}
      <div style={{
        position: "absolute", width: "700px", height: "700px",
        left: "-200px", top: "10%",
        background: `radial-gradient(ellipse, ${T.turrellViolet}22 0%, transparent 70%)`,
        animation: "turrellBreathe 45s ease-in-out infinite, turrellShift 90s ease-in-out infinite",
        animationDelay: "0s, 10s",
      }} />
      {/* Turrell orb — right */}
      <div style={{
        position: "absolute", width: "600px", height: "600px",
        right: "-150px", top: "30%",
        background: `radial-gradient(ellipse, ${T.turrellIndigo}1A 0%, transparent 70%)`,
        animation: "turrellBreathe 55s ease-in-out infinite, turrellHue 120s ease-in-out infinite",
        animationDelay: "15s, 0s",
      }} />
      {/* Turrell orb — bottom accent (Akhob pink) */}
      <div style={{
        position: "absolute", width: "400px", height: "400px",
        left: "30%", bottom: "-100px",
        background: `radial-gradient(ellipse, ${T.turrellPink}0F 0%, transparent 70%)`,
        animation: "turrellBreathe 65s ease-in-out infinite",
        animationDelay: "25s",
      }} />
      {/* Grain texture overlay */}
      <div style={{
        position: "absolute", inset: 0,
        backgroundImage: `url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noise'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noise)' opacity='1'/%3E%3C/svg%3E")`,
        opacity: 0.025,
        mixBlendMode: "overlay",
      }} />
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────────────────
   CARD — glassmorphic with Turrell depth
───────────────────────────────────────────────────────────────────────────── */
function Card({ children, style, glow = false, aiAccent = false, className = "" }) {
  return (
    <div className={className} style={{
      background: `rgba(18,17,43,0.75)`,
      backdropFilter: "blur(20px)",
      WebkitBackdropFilter: "blur(20px)",
      border: `1px solid ${aiAccent ? "rgba(111,2,172,0.4)" : T.border}`,
      borderRadius: "16px",
      position: "relative",
      overflow: "hidden",
      ...(glow && {
        boxShadow: `0 0 60px rgba(47,27,105,0.2), inset 0 1px 0 rgba(255,255,255,0.05)`,
      }),
      ...(aiAccent && {
        borderImage: `linear-gradient(180deg, ${T.turrellPink}, ${T.turrellViolet}, ${T.turrellIndigo}) 1`,
        borderStyle: "solid",
        borderWidth: "1px",
        background: `linear-gradient(135deg, rgba(111,2,172,0.08) 0%, rgba(18,17,43,0.8) 60%)`,
      }),
      ...style,
    }}>
      {aiAccent && (
        <div style={{
          position: "absolute", top: 0, left: 0, right: 0, height: "1px",
          background: `linear-gradient(90deg, transparent, ${T.turrellPink}, ${T.turrellViolet}, ${T.turrellIndigo}, transparent)`,
        }} />
      )}
      {children}
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────────────────
   LABEL — uppercase tracking  
───────────────────────────────────────────────────────────────────────────── */
function Label({ children, color = T.muted, style }) {
  return (
    <div style={{
      fontFamily: "'DM Sans', sans-serif",
      fontSize: "10px",
      fontWeight: 600,
      letterSpacing: "0.1em",
      textTransform: "uppercase",
      color,
      ...style,
    }}>{children}</div>
  );
}

/* ─────────────────────────────────────────────────────────────────────────────
   DATA VALUE — mono display
───────────────────────────────────────────────────────────────────────────── */
function DataValue({ children, size = 24, color = T.primary, style }) {
  return (
    <div style={{
      fontFamily: "'JetBrains Mono', monospace",
      fontSize: size,
      fontWeight: 400,
      color,
      lineHeight: 1.15,
      ...style,
    }}>{children}</div>
  );
}

/* ─────────────────────────────────────────────────────────────────────────────
   BADGE
───────────────────────────────────────────────────────────────────────────── */
function Badge({ children, color = T.blue, bg }) {
  return (
    <span style={{
      display: "inline-flex", alignItems: "center",
      padding: "2px 8px", borderRadius: "4px",
      background: bg || `${color}18`,
      border: `1px solid ${color}30`,
      color,
      fontFamily: "'DM Sans', sans-serif",
      fontSize: "10px", fontWeight: 600,
      letterSpacing: "0.06em", textTransform: "uppercase",
    }}>{children}</span>
  );
}

/* ─────────────────────────────────────────────────────────────────────────────
   CANDLESTICK CHART — SVG native
───────────────────────────────────────────────────────────────────────────── */
function CandlestickChart({ data, height = 260 }) {
  const [hovered, setHovered] = useState(null);
  if (!data || data.length === 0) return null;

  const PAD = { t: 16, r: 64, b: 32, l: 8 };
  const VW = 900, VH = height;
  const IW = VW - PAD.l - PAD.r;
  const IH = VH - PAD.t - PAD.b;

  const allPrices = data.flatMap(d => [d.high, d.low]);
  const minP = Math.min(...allPrices);
  const maxP = Math.max(...allPrices);
  const range = maxP - minP || 1;
  const pad5 = range * 0.05;

  const sy = v => PAD.t + IH - ((v - (minP - pad5)) / (range + pad5 * 2)) * IH;
  const sx = i => PAD.l + (i / (data.length - 1)) * IW;
  const cw = Math.max(3, (IW / data.length) * 0.55);

  const yTicks = 5;
  const tickVals = Array.from({ length: yTicks }, (_, i) =>
    (minP - pad5) + ((range + pad5 * 2) / (yTicks - 1)) * i
  );
  const showIdx = data.reduce((acc, _, i) => {
    if (i % Math.ceil(data.length / 7) === 0) acc.push(i);
    return acc;
  }, []);

  return (
    <div style={{ position: "relative" }}>
      <svg viewBox={`0 0 ${VW} ${VH}`} style={{ width: "100%", height, display: "block" }}
        preserveAspectRatio="none">
        <defs>
          <linearGradient id="volGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={T.blue} stopOpacity="0.5" />
            <stop offset="100%" stopColor={T.blue} stopOpacity="0" />
          </linearGradient>
        </defs>

        {/* Horizontal grid */}
        {tickVals.map((v, i) => (
          <g key={i}>
            <line x1={PAD.l} y1={sy(v)} x2={VW - PAD.r} y2={sy(v)}
              stroke={T.border} strokeWidth="0.5" strokeDasharray="3,6" />
            <text x={VW - PAD.r + 6} y={sy(v) + 3.5}
              fill={T.muted} fontSize="9" fontFamily="JetBrains Mono">
              {v >= 1000 ? (v / 1000).toFixed(1) + "k" : v.toFixed(1)}
            </text>
          </g>
        ))}

        {/* Candles */}
        {data.map((d, i) => {
          const x = sx(i);
          const oy = sy(d.open), cy2 = sy(d.close);
          const hy = sy(d.high), ly = sy(d.low);
          const bull = d.close >= d.open;
          const bodyTop = Math.min(oy, cy2);
          const bodyH = Math.max(1, Math.abs(cy2 - oy));
          const col = bull ? T.green : T.red;

          return (
            <g key={i}
              onMouseEnter={() => setHovered({ d, i })}
              onMouseLeave={() => setHovered(null)}
              style={{ cursor: "crosshair" }}>
              {/* Wick */}
              <line x1={x} y1={hy} x2={x} y2={ly} stroke={col} strokeWidth="1" opacity="0.8" />
              {/* Body */}
              <rect x={x - cw / 2} y={bodyTop} width={cw} height={bodyH}
                fill={bull ? col : "none"}
                stroke={col} strokeWidth={bull ? 0 : 1}
                rx="1" opacity={hovered?.i === i ? 1 : 0.85} />
            </g>
          );
        })}

        {/* Crosshair */}
        {hovered && (
          <line x1={sx(hovered.i)} y1={PAD.t} x2={sx(hovered.i)} y2={VH - PAD.b}
            stroke={T.muted} strokeWidth="0.5" strokeDasharray="3,4" />
        )}

        {/* X labels */}
        {showIdx.map(i => (
          <text key={i} x={sx(i)} y={VH - 8} textAnchor="middle"
            fill={T.muted} fontSize="9" fontFamily="JetBrains Mono">
            {data[i].time}
          </text>
        ))}
      </svg>

      {/* Tooltip */}
      {hovered && (
        <div style={{
          position: "absolute", top: 8, left: 12,
          background: `rgba(12,11,26,0.92)`,
          backdropFilter: "blur(12px)",
          border: `1px solid ${T.border}`,
          borderRadius: 8, padding: "8px 12px",
          fontFamily: "'JetBrains Mono', monospace",
          fontSize: 11, lineHeight: 1.8,
          pointerEvents: "none",
        }}>
          <div style={{ color: T.muted, fontSize: 9, letterSpacing: "0.08em", marginBottom: 3 }}>
            {hovered.d.time}
          </div>
          <div style={{ color: T.secondary }}>O <span style={{ color: T.primary }}>{hovered.d.open.toLocaleString()}</span></div>
          <div style={{ color: T.secondary }}>H <span style={{ color: T.green }}>{hovered.d.high.toLocaleString()}</span></div>
          <div style={{ color: T.secondary }}>L <span style={{ color: T.red }}>{hovered.d.low.toLocaleString()}</span></div>
          <div style={{ color: T.secondary }}>C <span style={{ color: T.primary }}>{hovered.d.close.toLocaleString()}</span></div>
        </div>
      )}
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────────────────
   MMI DIAL
───────────────────────────────────────────────────────────────────────────── */
function MMIDial({ value }) {
  const r = 52, cx = 72, cy = 72;
  const startAngle = -225;
  const sweep = 270;
  const angle = startAngle + (value / 100) * sweep;

  const arc = (a1, a2, r2 = r, col = T.border) => {
    const toRad = d => (d * Math.PI) / 180;
    const x1 = cx + r2 * Math.cos(toRad(a1));
    const y1 = cy + r2 * Math.sin(toRad(a1));
    const x2 = cx + r2 * Math.cos(toRad(a2));
    const y2 = cy + r2 * Math.sin(toRad(a2));
    const large = Math.abs(a2 - a1) > 180 ? 1 : 0;
    return `M ${x1} ${y1} A ${r2} ${r2} 0 ${large} 1 ${x2} ${y2}`;
  };

  const accentColor = value < 30 ? T.red : value < 45 ? "#FF9500" : value < 55 ? T.secondary : value < 70 ? T.blue : T.green;
  const label = value < 30 ? "Extreme Fear" : value < 45 ? "Fear" : value < 55 ? "Neutral" : value < 70 ? "Greed" : "Extreme Greed";

  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center" }}>
      <svg width={144} height={100} viewBox="0 0 144 100">
        <defs>
          <linearGradient id="dialGrad" x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%" stopColor={T.red} />
            <stop offset="30%" stopColor="#FF9500" />
            <stop offset="50%" stopColor={T.secondary} />
            <stop offset="70%" stopColor={T.blue} />
            <stop offset="100%" stopColor={T.green} />
          </linearGradient>
        </defs>
        {/* Track */}
        <path d={arc(startAngle, startAngle + sweep)} fill="none" stroke={T.border} strokeWidth="8" strokeLinecap="round" />
        {/* Active arc */}
        <path d={arc(startAngle, angle)} fill="none" stroke="url(#dialGrad)" strokeWidth="8" strokeLinecap="round" opacity="0.9" />
        {/* Needle */}
        <line
          x1={cx} y1={cy}
          x2={cx + (r - 10) * Math.cos((angle * Math.PI) / 180)}
          y2={cy + (r - 10) * Math.sin((angle * Math.PI) / 180)}
          stroke={T.primary} strokeWidth="1.5" strokeLinecap="round" opacity="0.8"
        />
        <circle cx={cx} cy={cy} r="3.5" fill={accentColor} />
        {/* Value */}
        <text x={cx} y={cy + 18} textAnchor="middle"
          fontFamily="JetBrains Mono" fontSize="18" fontWeight="400" fill={T.primary}>
          {Math.round(value)}
        </text>
      </svg>
      <div style={{
        fontFamily: "'DM Sans', sans-serif", fontSize: 11, fontWeight: 500,
        color: accentColor, letterSpacing: "0.06em", textTransform: "uppercase",
        marginTop: -4,
      }}>{label}</div>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────────────────
   ADDRESS ANALYZER
───────────────────────────────────────────────────────────────────────────── */
function AddressAnalyzer() {
  const [address, setAddress] = useState("");
  const [chain, setChain] = useState("ETH");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState(null);
  const [copied, setCopied] = useState(false);

  const CHAINS = [
    { id: "ETH", color: T.blue },
    { id: "BSC", color: "#F3BA2F" },
    { id: "ARB", color: "#96BEDC" },
    { id: "POLY", color: "#8247E5" },
    { id: "SOL", color: "#9945FF" },
  ];

  const analyze = useCallback(async () => {
    if (!address || address.length < 6) return;
    setLoading(true); setResult(null);
    await new Promise(r => setTimeout(r, 1800));

    // Replace this mock with real Etherscan/BSCScan API:
    // GET https://api.etherscan.io/api?module=account&action=txlist&address=${address}&apikey=${KEY}
    const riskScore = Math.floor(Math.random() * 85) + 10;
    setResult({
      address, chain,
      balance: (Math.random() * 420 + 0.5).toFixed(3) + " " + (chain === "BSC" ? "BNB" : chain === "SOL" ? "SOL" : "ETH"),
      usd: "$" + (Math.random() * 900000 + 5000).toFixed(0),
      txCount: Math.floor(Math.random() * 8000) + 80,
      firstSeen: `20${Math.floor(Math.random() * 3) + 21}-${String(Math.floor(Math.random() * 12) + 1).padStart(2, "0")}-${String(Math.floor(Math.random() * 28) + 1).padStart(2, "0")}`,
      lastActive: new Date(Date.now() - Math.random() * 14 * 86400000).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" }),
      riskScore,
      tags: ["Whale", "DeFi Power User", "LP Provider"].slice(0, Math.floor(Math.random() * 2) + 1),
      holdings: [
        { symbol: chain === "ETH" ? "ETH" : chain === "SOL" ? "SOL" : "BNB", pct: 45 + Math.random() * 20, value: "$" + (Math.random() * 400000).toFixed(0) },
        { symbol: "USDC", pct: 20 + Math.random() * 15, value: "$" + (Math.random() * 120000).toFixed(0) },
        { symbol: "ARB", pct: 8 + Math.random() * 10, value: "$" + (Math.random() * 50000).toFixed(0) },
        { symbol: "PEPE", pct: 2 + Math.random() * 8, value: "$" + (Math.random() * 20000).toFixed(0) },
      ],
      activity: Array.from({ length: 12 }, (_, i) => ({
        m: ["J","F","M","A","M","J","J","A","S","O","N","D"][i],
        v: Math.floor(Math.random() * 180 + 5),
      })),
      txs: [
        { hash: "0x" + Math.random().toString(16).slice(2, 14), type: "Swap", amount: "$" + (Math.random() * 15000).toFixed(0), age: "2h ago", ok: true },
        { hash: "0x" + Math.random().toString(16).slice(2, 14), type: "Add Liquidity", amount: "$" + (Math.random() * 80000).toFixed(0), age: "8h ago", ok: true },
        { hash: "0x" + Math.random().toString(16).slice(2, 14), type: "Transfer", amount: "$" + (Math.random() * 6000).toFixed(0), age: "1d ago", ok: true },
        { hash: "0x" + Math.random().toString(16).slice(2, 14), type: "Swap", amount: "$" + (Math.random() * 2000).toFixed(0), age: "2d ago", ok: false },
      ],
    });
    setLoading(false);
  }, [address, chain]);

  const riskColor = s => s < 30 ? T.green : s < 60 ? "#FF9500" : T.red;
  const riskLabel = s => s < 30 ? "LOW" : s < 60 ? "MEDIUM" : "HIGH";

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {/* Search row */}
      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <div style={{ display: "flex", gap: 4 }}>
          {CHAINS.map(c => (
            <button key={c.id} onClick={() => setChain(c.id)}
              style={{
                padding: "6px 12px", borderRadius: 6, cursor: "pointer",
                border: `1px solid ${chain === c.id ? c.color + "60" : T.border}`,
                background: chain === c.id ? c.color + "18" : "transparent",
                color: chain === c.id ? c.color : T.muted,
                fontFamily: "'DM Sans', sans-serif", fontSize: 11, fontWeight: 600,
                letterSpacing: "0.04em", transition: "all 0.2s",
              }}>{c.id}</button>
          ))}
        </div>
        <div style={{ flex: 1, position: "relative", minWidth: 200 }}>
          <Search size={12} style={{ position: "absolute", left: 12, top: "50%", transform: "translateY(-50%)", color: T.muted }} />
          <input value={address} onChange={e => setAddress(e.target.value)}
            onKeyDown={e => e.key === "Enter" && analyze()}
            placeholder="Wallet address or ENS name..."
            style={{
              width: "100%", background: `rgba(26,25,64,0.6)`, border: `1px solid ${T.border}`,
              borderRadius: 8, padding: "9px 12px 9px 34px",
              fontFamily: "'JetBrains Mono', monospace", fontSize: 12, color: T.primary,
              outline: "none", transition: "border-color 0.2s",
            }}
            onFocus={e => e.target.style.borderColor = T.blue + "80"}
            onBlur={e => e.target.style.borderColor = T.border}
          />
        </div>
        <button onClick={analyze} disabled={loading}
          style={{
            padding: "9px 20px", borderRadius: 8, cursor: loading ? "wait" : "pointer",
            background: loading ? T.raised : T.blue,
            border: "none", color: loading ? T.secondary : "#fff",
            fontFamily: "'DM Sans', sans-serif", fontSize: 12, fontWeight: 600,
            display: "flex", alignItems: "center", gap: 6,
            transition: "all 0.2s", opacity: loading ? 0.7 : 1,
          }}>
          {loading ? <RefreshCw size={12} style={{ animation: "pulseDot 1s infinite" }} /> : <Search size={12} />}
          {loading ? "Scanning..." : "Analyze"}
        </button>
      </div>

      {/* Loading */}
      {loading && (
        <div style={{
          padding: "40px 24px", textAlign: "center",
          background: `rgba(18,17,43,0.5)`, border: `1px dashed ${T.border}`, borderRadius: 12,
        }}>
          <div style={{ color: T.blue, fontFamily: "'DM Sans', sans-serif", fontSize: 13, marginBottom: 6 }}>
            Scanning {chain} blockchain...
          </div>
          <div style={{ color: T.muted, fontFamily: "'DM Mono', monospace", fontSize: 11 }}>
            Analyzing transaction patterns · Risk assessment · Portfolio breakdown
          </div>
        </div>
      )}

      {/* Results */}
      {result && !loading && (
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }} className="fade-up">
          {/* Header */}
          <Card style={{ padding: "20px 24px" }} glow>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 16, flexWrap: "wrap", gap: 12 }}>
              <div>
                <div style={{ display: "flex", gap: 6, marginBottom: 8, flexWrap: "wrap" }}>
                  {CHAINS.find(c => c.id === result.chain) && (
                    <Badge color={CHAINS.find(c => c.id === result.chain).color}>{result.chain}</Badge>
                  )}
                  {result.tags.map(t => <Badge key={t} color={T.turrellViolet}>{t}</Badge>)}
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 13, color: T.secondary }}>
                    {result.address.slice(0, 18)}...{result.address.slice(-6)}
                  </span>
                  <button onClick={() => { navigator.clipboard.writeText(result.address); setCopied(true); setTimeout(() => setCopied(false), 2000); }}
                    style={{ background: "none", border: "none", cursor: "pointer", color: copied ? T.green : T.muted, padding: 0 }}>
                    {copied ? <CheckCircle size={12} /> : <Copy size={12} />}
                  </button>
                  <ExternalLink size={11} style={{ color: T.muted, cursor: "pointer" }} />
                </div>
              </div>
              <div style={{ textAlign: "right" }}>
                <DataValue size={28}>{result.usd}</DataValue>
                <div style={{ color: T.muted, fontFamily: "'JetBrains Mono', monospace", fontSize: 11, marginTop: 2 }}>{result.balance}</div>
              </div>
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))", gap: 10 }}>
              {[
                { label: "Total Transactions", value: result.txCount.toLocaleString(), icon: Activity },
                { label: "First Seen", value: result.firstSeen, icon: Clock },
                { label: "Last Active", value: result.lastActive, icon: RefreshCw },
                { label: "Risk Score", value: result.riskScore, icon: Shield, special: true },
              ].map(({ label, value, icon: Icon, special }) => (
                <div key={label} style={{
                  background: `rgba(7,6,15,0.5)`, borderRadius: 10, padding: "12px 14px",
                  border: `1px solid ${T.border}`,
                }}>
                  <Label style={{ display: "flex", alignItems: "center", gap: 4, marginBottom: 6 }}>
                    <Icon size={10} />{label}
                  </Label>
                  {special ? (
                    <div>
                      <DataValue size={20} color={riskColor(value)}>{value}</DataValue>
                      <Badge color={riskColor(value)} style={{ marginTop: 4 }}>{riskLabel(value)} RISK</Badge>
                    </div>
                  ) : (
                    <DataValue size={14} color={T.primary}>{value}</DataValue>
                  )}
                </div>
              ))}
            </div>
          </Card>

          {/* Charts row */}
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
            <Card style={{ padding: "16px 20px" }}>
              <Label style={{ marginBottom: 12 }}>Transaction Activity (12M)</Label>
              <ResponsiveContainer width="100%" height={110}>
                <BarChart data={result.activity} barSize={12}>
                  <XAxis dataKey="m" tick={{ fill: T.muted, fontSize: 9, fontFamily: "JetBrains Mono" }} axisLine={false} tickLine={false} />
                  <Bar dataKey="v" fill={T.blue} opacity={0.75} radius={[2, 2, 0, 0]} />
                  <Tooltip contentStyle={{ background: T.deep, border: `1px solid ${T.border}`, borderRadius: 6, fontSize: 11, fontFamily: "JetBrains Mono" }} itemStyle={{ color: T.primary }} cursor={{ fill: "rgba(79,110,247,0.05)" }} />
                </BarChart>
              </ResponsiveContainer>
            </Card>
            <Card style={{ padding: "16px 20px" }}>
              <Label style={{ marginBottom: 12 }}>Portfolio Breakdown</Label>
              <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 4 }}>
                {result.holdings.map((h, i) => {
                  const colors = [T.blue, T.turrellViolet, "#8247E5", T.turrellPink];
                  const c = colors[i % colors.length];
                  return (
                    <div key={h.symbol} style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 10, color: T.secondary, width: 36 }}>{h.symbol}</div>
                      <div style={{ flex: 1, height: 4, background: T.raised, borderRadius: 2, overflow: "hidden" }}>
                        <div style={{ width: `${h.pct}%`, height: "100%", background: `linear-gradient(90deg, ${c}, ${c}88)`, borderRadius: 2, transition: "width 0.8s ease" }} />
                      </div>
                      <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 10, color: T.secondary, width: 56, textAlign: "right" }}>{h.value}</div>
                      <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 10, color: c, width: 32, textAlign: "right" }}>{h.pct.toFixed(0)}%</div>
                    </div>
                  );
                })}
              </div>
            </Card>
          </div>

          {/* Recent txs */}
          <Card style={{ padding: "16px 20px" }}>
            <Label style={{ marginBottom: 12 }}>Recent Transactions</Label>
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead>
                <tr>
                  {["Hash", "Type", "Amount", "Age", "Status"].map(h => (
                    <th key={h} style={{ textAlign: h === "Amount" || h === "Age" || h === "Status" ? "right" : "left", padding: "0 0 10px", fontFamily: "'DM Sans', sans-serif", fontSize: 10, fontWeight: 600, letterSpacing: "0.08em", color: T.muted, textTransform: "uppercase", borderBottom: `1px solid ${T.border}` }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {result.txs.map((tx, i) => (
                  <tr key={i} style={{ borderBottom: i < result.txs.length - 1 ? `1px solid ${T.border}40` : "none" }}>
                    <td style={{ padding: "10px 0", fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: T.blue, cursor: "pointer" }}>{tx.hash.slice(0, 16)}...</td>
                    <td style={{ padding: "10px 0", fontFamily: "'DM Sans', sans-serif", fontSize: 12, color: T.secondary }}>{tx.type}</td>
                    <td style={{ padding: "10px 0", textAlign: "right", fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: T.primary }}>{tx.amount}</td>
                    <td style={{ padding: "10px 0", textAlign: "right", fontFamily: "'JetBrains Mono', monospace", fontSize: 10, color: T.muted }}>{tx.age}</td>
                    <td style={{ padding: "10px 0", textAlign: "right" }}>
                      {tx.ok
                        ? <span style={{ color: T.green, display: "flex", alignItems: "center", justifyContent: "flex-end", gap: 3, fontSize: 10, fontFamily: "'DM Sans', sans-serif", fontWeight: 600 }}><CheckCircle size={10} />OK</span>
                        : <span style={{ color: T.red, display: "flex", alignItems: "center", justifyContent: "flex-end", gap: 3, fontSize: 10, fontFamily: "'DM Sans', sans-serif", fontWeight: 600 }}><XCircle size={10} />Failed</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        </div>
      )}

      {!result && !loading && (
        <div style={{
          padding: "48px 24px", textAlign: "center",
          border: `1px dashed ${T.border}`, borderRadius: 12,
        }}>
          <Search size={24} style={{ color: T.ghost, margin: "0 auto 12px" }} />
          <div style={{ fontFamily: "'DM Sans', sans-serif", fontSize: 13, color: T.muted }}>Enter a wallet address to begin analysis</div>
          <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 10, color: T.ghost, marginTop: 6 }}>ETH · BSC · ARB · POLY · SOL</div>
        </div>
      )}
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────────────────
   DATA GENERATORS
───────────────────────────────────────────────────────────────────────────── */
function genCandles(n = 52) {
  const data = []; let p = 44800 + Math.random() * 2000; const now = Date.now();
  for (let i = n; i >= 0; i--) {
    const o = p, c = +(o + (Math.random() - 0.485) * o * 0.016).toFixed(2);
    const h = +(Math.max(o, c) + Math.random() * o * 0.006).toFixed(2);
    const l = +(Math.min(o, c) - Math.random() * o * 0.006).toFixed(2);
    data.push({ time: new Date(now - i * 5 * 60000).toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" }), open: o, high: h, low: l, close: c, volume: ~~(800 + Math.random() * 3000) });
    p = c;
  }
  return data;
}
function genMMI() {
  return ["Fear & Greed", "On-Chain Flow", "Social Sentiment", "Volume Delta", "Price Momentum"].map(n => ({
    name: n, value: +(30 + Math.random() * 60).toFixed(1), prev: +(30 + Math.random() * 60).toFixed(1)
  }));
}

const WHALE_DATA = [
  { addr: "0x7fa9…4e92", action: "Bought BTC", amount: "+$284K", delta: "+2.1%", chain: "ETH", rate: 94, pnl: "+$2.14M", bull: true },
  { addr: "0x29b3…f7e1", action: "Staked ETH", amount: "+$520K", delta: "+0.8%", chain: "ETH", rate: 91, pnl: "+$4.82M", bull: true },
  { addr: "0xd3c8…9a82", action: "Added LP", amount: "+$102K", delta: "+0.3%", chain: "ARB", rate: 88, pnl: "+$890K", bull: true },
  { addr: "0x56e2…2b51", action: "Sold SOL", amount: "-$74K", delta: "-0.4%", chain: "SOL", rate: 79, pnl: "+$340K", bull: false },
  { addr: "0x1af4…7d23", action: "Bridge ETH→ARB", amount: "$310K", delta: "—", chain: "ETH", rate: 86, pnl: "+$1.2M", bull: true },
];
const TOKEN_DATA = [
  { name: "$PEPEAI", age: "12m", mc: "$342K", liq: "$78K", dev: 86, signal: "STRONG BUY", bull: true, tier: 0 },
  { name: "$MEMEFROG", age: "28m", mc: "$128K", liq: "$42K", dev: 72, signal: "WATCH", bull: null, tier: 1 },
  { name: "$WOJAK", age: "45m", mc: "$492K", liq: "$22K", dev: 32, signal: "AVOID", bull: false, tier: 2 },
  { name: "$AIDOG", age: "1h 12m", mc: "$204K", liq: "$68K", dev: 88, signal: "BUY", bull: true, tier: 0 },
];

/* ─────────────────────────────────────────────────────────────────────────────
   MAIN DASHBOARD
───────────────────────────────────────────────────────────────────────────── */
export default function LooloomiDashboard() {
  const [tab, setTab] = useState("market");
  const [candles, setCandles] = useState(() => genCandles());
  const [mmiData] = useState(() => genMMI());
  const [mmiScore, setMmiScore] = useState(63);
  const [price, setPrice] = useState(44821.34);
  const [priceDelta, setPriceDelta] = useState(+1.24);
  const [ticker, setTicker] = useState("BTC/USDT");
  const [live, setLive] = useState(true);
  const [ts, setTs] = useState(new Date());

  useEffect(() => {
    if (!live) return;
    const id = setInterval(() => {
      setPrice(p => {
        const d = (Math.random() - 0.49) * 85;
        setPriceDelta(+((d / p) * 100).toFixed(3));
        return +(p + d).toFixed(2);
      });
      setTs(new Date());
      setMmiScore(s => Math.max(10, Math.min(95, s + (Math.random() - 0.5) * 2.5)));
      if (Math.random() > 0.65) {
        setCandles(prev => {
          const last = prev[prev.length - 1];
          const nc = +(last.close + (Math.random() - 0.48) * last.close * 0.005).toFixed(2);
          return [...prev.slice(1), {
            time: new Date().toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" }),
            open: last.close, close: nc,
            high: +(Math.max(last.close, nc) + Math.random() * 55).toFixed(2),
            low: +(Math.min(last.close, nc) - Math.random() * 55).toFixed(2),
            volume: ~~(800 + Math.random() * 3000),
          }];
        });
      }
    }, 3000);
    return () => clearInterval(id);
  }, [live]);

  const TABS = [
    { id: "market",  label: "Market", icon: BarChart2 },
    { id: "whales",  label: "Whales", icon: Wallet },
    { id: "address", label: "Address", icon: Search },
    { id: "mmi",     label: "MMI Index", icon: Activity },
  ];

  const STATS = [
    { label: "Active Wallets 24h", val: "18,742", delta: "+24%", up: true },
    { label: "New Tokens 24h",     val: "283",    delta: "+12%", up: true },
    { label: "Pump Signals",       val: "42",     delta: "78% acc", up: null },
    { label: "Risk Alerts",        val: "18",     delta: "92% acc", up: null },
  ];

  const signalColor = tier => tier === 0 ? T.green : tier === 1 ? "#FF9500" : T.red;
  const chainColor  = c => ({ ETH: T.blue, BSC: "#F3BA2F", ARB: "#96BEDC", SOL: "#9945FF", POLY: "#8247E5" }[c] || T.secondary);

  return (
    <>
      <style>{GLOBAL_CSS}</style>
      <TurrellAmbient />

      <div style={{
        position: "relative", zIndex: 1,
        minHeight: "100vh",
        fontFamily: "'DM Sans', sans-serif",
      }}>

        {/* ── NAV ─────────────────────────────────────────────────────────── */}
        <nav style={{
          position: "sticky", top: 0, zIndex: 100,
          background: `rgba(7,6,15,0.85)`,
          backdropFilter: "blur(24px)",
          WebkitBackdropFilter: "blur(24px)",
          borderBottom: `1px solid ${T.border}`,
        }}>
          <div style={{ maxWidth: 1320, margin: "0 auto", padding: "0 32px", height: 56, display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            {/* Logo */}
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <div style={{
                fontFamily: "'Syne', sans-serif", fontSize: 20, fontWeight: 800,
                letterSpacing: "-0.02em",
                background: `linear-gradient(135deg, ${T.primary} 0%, ${T.turrellDusk} 100%)`,
                WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent",
              }}>LOOLOOMI</div>
              <span style={{
                fontFamily: "'DM Sans', sans-serif", fontSize: 9, fontWeight: 700,
                letterSpacing: "0.12em",
                padding: "2px 6px", borderRadius: 3,
                background: `${T.turrellViolet}20`,
                border: `1px solid ${T.turrellViolet}40`,
                color: T.turrellDusk,
              }}>AI PLATFORM</span>
            </div>

            {/* Tabs */}
            <div style={{ display: "flex", gap: 2 }}>
              {TABS.map(({ id, label, icon: Icon }) => (
                <button key={id} onClick={() => setTab(id)} style={{
                  display: "flex", alignItems: "center", gap: 6,
                  padding: "6px 16px", borderRadius: 8, cursor: "pointer",
                  border: `1px solid ${tab === id ? T.blue + "40" : "transparent"}`,
                  background: tab === id ? `${T.blue}12` : "transparent",
                  color: tab === id ? T.blue : T.muted,
                  fontFamily: "'DM Sans', sans-serif", fontSize: 12, fontWeight: 500,
                  transition: "all 0.2s",
                }}>
                  <Icon size={13} />{label}
                </button>
              ))}
            </div>

            {/* Live indicator */}
            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <div style={{
                  width: 6, height: 6, borderRadius: "50%",
                  background: live ? T.green : T.muted,
                  animation: live ? "pulseDot 2s infinite" : "none",
                }} />
                <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 10, color: live ? T.green : T.muted }}>
                  {live ? "LIVE" : "PAUSED"}
                </span>
              </div>
              <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 10, color: T.ghost }}>
                {ts.toLocaleTimeString()}
              </span>
              <button onClick={() => setLive(l => !l)} style={{
                padding: "5px 12px", borderRadius: 6, cursor: "pointer",
                background: "transparent", border: `1px solid ${T.border}`,
                color: T.secondary, fontFamily: "'DM Sans', sans-serif", fontSize: 11, fontWeight: 500,
                transition: "all 0.2s",
              }}>{live ? "Pause" : "Resume"}</button>
            </div>
          </div>
        </nav>

        {/* ── CONTENT ─────────────────────────────────────────────────────── */}
        <div style={{ maxWidth: 1320, margin: "0 auto", padding: "28px 32px 60px" }}>

          {/* Stats row */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12, marginBottom: 24 }}>
            {STATS.map(({ label, val, delta, up }, i) => (
              <Card key={label} style={{ padding: "18px 20px" }} className={`fade-up-${i + 1}`}>
                <Label style={{ marginBottom: 8 }}>{label}</Label>
                <DataValue size={26}>{val}</DataValue>
                <div style={{
                  display: "flex", alignItems: "center", gap: 4, marginTop: 6,
                  fontFamily: "'DM Sans', sans-serif", fontSize: 11, fontWeight: 500,
                  color: up === true ? T.green : up === false ? T.red : T.amber,
                }}>
                  {up === true ? <TrendingUp size={11} /> : up === false ? <TrendingDown size={11} /> : <Minus size={11} />}
                  {delta}
                </div>
              </Card>
            ))}
          </div>

          {/* ── MARKET TAB ─────────────────────────────────────────────────── */}
          {tab === "market" && (
            <div style={{ display: "flex", flexDirection: "column", gap: 16 }} className="fade-up">
              {/* Price + Chart */}
              <Card style={{ padding: "24px 28px" }} glow>
                {/* Price header */}
                <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", marginBottom: 20, flexWrap: "wrap", gap: 16 }}>
                  <div>
                    {/* Ticker selector */}
                    <div style={{ display: "flex", gap: 6, marginBottom: 12 }}>
                      {["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT"].map(t => (
                        <button key={t} onClick={() => setTicker(t)} style={{
                          padding: "4px 12px", borderRadius: 5, cursor: "pointer",
                          border: `1px solid ${ticker === t ? T.blue + "50" : T.border}`,
                          background: ticker === t ? `${T.blue}12` : "transparent",
                          color: ticker === t ? T.blue : T.muted,
                          fontFamily: "'JetBrains Mono', monospace", fontSize: 10,
                          transition: "all 0.2s",
                        }}>{t}</button>
                      ))}
                    </div>
                    {/* Price */}
                    <div style={{ display: "flex", alignItems: "baseline", gap: 12 }}>
                      <div style={{
                        fontFamily: "'JetBrains Mono', monospace", fontSize: 42, fontWeight: 300,
                        color: T.primary, lineHeight: 1, letterSpacing: "-0.02em",
                      }}>${price.toLocaleString()}</div>
                      <div style={{
                        display: "flex", alignItems: "center", gap: 4,
                        fontFamily: "'JetBrains Mono', monospace", fontSize: 14,
                        color: priceDelta >= 0 ? T.green : T.red,
                      }}>
                        {priceDelta >= 0 ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
                        {priceDelta >= 0 ? "+" : ""}{priceDelta.toFixed(3)}%
                      </div>
                    </div>
                  </div>

                  {/* Market stats */}
                  <div style={{ display: "flex", gap: 28 }}>
                    {[
                      { l: "24h High", v: "$" + (price * 1.028).toFixed(0) },
                      { l: "24h Low",  v: "$" + (price * 0.972).toFixed(0) },
                      { l: "Volume",   v: "$" + (48.2 + Math.random()).toFixed(1) + "B" },
                      { l: "Mkt Cap",  v: "$" + (856 + Math.random() * 8).toFixed(0) + "B" },
                    ].map(({ l, v }) => (
                      <div key={l}>
                        <Label style={{ marginBottom: 4 }}>{l}</Label>
                        <DataValue size={13} color={T.secondary}>{v}</DataValue>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Candlestick */}
                <div style={{
                  background: `rgba(7,6,15,0.6)`,
                  border: `1px solid ${T.border}`,
                  borderRadius: 10, padding: "12px 8px 4px",
                }}>
                  <div style={{ display: "flex", gap: 12, paddingLeft: 8, marginBottom: 8 }}>
                    <Label style={{ display: "flex", alignItems: "center", gap: 4 }}>
                      <span style={{ display: "inline-block", width: 8, height: 8, background: T.green, borderRadius: 1 }} />Bull
                    </Label>
                    <Label style={{ display: "flex", alignItems: "center", gap: 4 }}>
                      <span style={{ display: "inline-block", width: 8, height: 8, background: T.red, borderRadius: 1 }} />Bear
                    </Label>
                    <Label style={{ marginLeft: "auto", paddingRight: 60 }}>5-min · {candles.length} candles</Label>
                  </div>
                  <CandlestickChart data={candles} height={260} />
                  {/* Volume bars */}
                  <div style={{ marginTop: -4 }}>
                    <ResponsiveContainer width="100%" height={50}>
                      <BarChart data={candles} margin={{ top: 0, right: 64, left: 8, bottom: 0 }}>
                        <Bar dataKey="volume" fill={T.blueDim} opacity={0.6} radius={[1, 1, 0, 0]} />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                </div>
              </Card>

              {/* AI Insight card (Turrell accent) */}
              <Card aiAccent style={{ padding: "20px 24px" }}>
                <div style={{ display: "flex", gap: 12, alignItems: "flex-start" }}>
                  <div style={{
                    width: 32, height: 32, borderRadius: 8,
                    background: `linear-gradient(135deg, ${T.turrellPink}30, ${T.turrellIndigo}30)`,
                    border: `1px solid ${T.turrellViolet}40`,
                    display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0,
                  }}>
                    <Zap size={14} color={T.turrellDusk} />
                  </div>
                  <div>
                    <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
                      <span style={{ fontFamily: "'Syne', sans-serif", fontSize: 13, fontWeight: 700, color: T.turrellDusk, letterSpacing: "0.04em" }}>AI SIGNAL DETECTED</span>
                      <Badge color={T.turrellPink}>High Confidence</Badge>
                    </div>
                    {/* DM Serif Display for the insight narrative — editorial quality */}
                    <p style={{
                      fontFamily: "'DM Serif Display', serif", fontSize: 15,
                      color: T.secondary, lineHeight: 1.65, fontStyle: "italic",
                    }}>
                      Three whale wallets accumulated within the last 4 minutes, pattern matching {" "}
                      <span style={{ color: T.primary, fontStyle: "normal" }}>+840% avg returns</span>{" "}
                      in similar early-stage launches. On-chain LP provision signals experienced team.
                    </p>
                  </div>
                </div>
              </Card>

              {/* Token table */}
              <Card style={{ padding: "20px 24px" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
                  <div style={{ fontFamily: "'Syne', sans-serif", fontSize: 13, fontWeight: 700, color: T.primary, letterSpacing: "0.04em" }}>RECENTLY DETECTED</div>
                  <span style={{ color: T.blue, fontFamily: "'DM Sans', sans-serif", fontSize: 11, cursor: "pointer" }}>View all <ArrowUpRight size={10} style={{ display: "inline" }} /></span>
                </div>
                <table style={{ width: "100%", borderCollapse: "collapse" }}>
                  <thead>
                    <tr>
                      {["Token", "Age", "Market Cap", "Liquidity", "Dev Score", "Signal", "Action"].map((h, i) => (
                        <th key={h} style={{
                          padding: "0 0 12px", textAlign: i > 1 ? "right" : "left",
                          fontFamily: "'DM Sans', sans-serif", fontSize: 9, fontWeight: 600,
                          letterSpacing: "0.1em", color: T.muted, textTransform: "uppercase",
                          borderBottom: `1px solid ${T.border}`,
                        }}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {TOKEN_DATA.map((t, i) => {
                      const sc = signalColor(t.tier);
                      return (
                        <tr key={t.name} style={{ borderBottom: i < TOKEN_DATA.length - 1 ? `1px solid ${T.border}30` : "none" }}>
                          <td style={{ padding: "12px 0" }}>
                            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                              <div style={{ width: 6, height: 6, borderRadius: "50%", background: sc, flexShrink: 0 }} />
                              <span style={{ fontFamily: "'Syne', sans-serif", fontSize: 13, fontWeight: 700, color: T.primary }}>{t.name}</span>
                            </div>
                          </td>
                          <td style={{ padding: "12px 0", textAlign: "right" }}>
                            <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 10, color: T.muted }}>{t.age}</span>
                          </td>
                          <td style={{ padding: "12px 0", textAlign: "right" }}>
                            <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 12, color: T.secondary }}>{t.mc}</span>
                          </td>
                          <td style={{ padding: "12px 0", textAlign: "right" }}>
                            <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 12, color: T.secondary }}>{t.liq}</span>
                          </td>
                          <td style={{ padding: "12px 0", textAlign: "right" }}>
                            <Badge color={sc}>{t.dev}/100</Badge>
                          </td>
                          <td style={{ padding: "12px 0", textAlign: "right" }}>
                            <Badge color={sc}>{t.signal}</Badge>
                          </td>
                          <td style={{ padding: "12px 0", textAlign: "right" }}>
                            <button style={{
                              padding: "5px 14px", borderRadius: 6, cursor: "pointer",
                              background: t.tier === 0 ? T.green : "transparent",
                              border: `1px solid ${t.tier === 0 ? T.green : T.border}`,
                              color: t.tier === 0 ? T.void : T.muted,
                              fontFamily: "'DM Sans', sans-serif", fontSize: 11, fontWeight: 600,
                              transition: "all 0.2s",
                            }}>{t.tier === 0 ? "Trade" : "Track"}</button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </Card>
            </div>
          )}

          {/* ── WHALES TAB ─────────────────────────────────────────────────── */}
          {tab === "whales" && (
            <div className="fade-up">
              <Card style={{ padding: "24px 28px" }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20 }}>
                  <div style={{ fontFamily: "'Syne', sans-serif", fontSize: 13, fontWeight: 700, letterSpacing: "0.06em", color: T.primary }}>WHALE INTELLIGENCE</div>
                  <div style={{ display: "flex", alignItems: "center", gap: 6, fontFamily: "'JetBrains Mono', monospace", fontSize: 10, color: T.green }}>
                    <div style={{ width: 6, height: 6, borderRadius: "50%", background: T.green, animation: "pulseDot 2s infinite" }} />
                    LIVE UPDATES
                  </div>
                </div>
                <table style={{ width: "100%", borderCollapse: "collapse" }}>
                  <thead>
                    <tr>
                      {["Wallet", "Last Action", "Chain", "Amount", "Success Rate", "30d P/L", ""].map((h, i) => (
                        <th key={h + i} style={{
                          padding: "0 0 14px",
                          textAlign: i >= 3 ? "right" : "left",
                          fontFamily: "'DM Sans', sans-serif", fontSize: 9, fontWeight: 600,
                          letterSpacing: "0.1em", color: T.muted, textTransform: "uppercase",
                          borderBottom: `1px solid ${T.border}`,
                        }}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {WHALE_DATA.map((w, i) => (
                      <tr key={i} style={{ borderBottom: i < WHALE_DATA.length - 1 ? `1px solid ${T.border}30` : "none" }}>
                        <td style={{ padding: "14px 0" }}>
                          <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: T.blue }}>{w.addr}</span>
                        </td>
                        <td style={{ padding: "14px 0" }}>
                          <div style={{ fontFamily: "'DM Sans', sans-serif", fontSize: 12, color: T.secondary }}>{w.action}</div>
                          <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 9, color: T.muted, marginTop: 2 }}>{w.delta}</div>
                        </td>
                        <td style={{ padding: "14px 0" }}>
                          <Badge color={chainColor(w.chain)}>{w.chain}</Badge>
                        </td>
                        <td style={{ padding: "14px 0", textAlign: "right" }}>
                          <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 13, fontWeight: 500, color: w.bull ? T.green : T.red }}>{w.amount}</span>
                        </td>
                        <td style={{ padding: "14px 0", textAlign: "right" }}>
                          <div style={{ display: "flex", alignItems: "center", justifyContent: "flex-end", gap: 8 }}>
                            <div style={{ width: 72, height: 3, background: T.raised, borderRadius: 2, overflow: "hidden" }}>
                              <div style={{ width: `${w.rate}%`, height: "100%", background: w.rate > 85 ? T.green : w.rate > 70 ? "#FF9500" : T.red, borderRadius: 2 }} />
                            </div>
                            <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 11, color: T.secondary }}>{w.rate}%</span>
                          </div>
                        </td>
                        <td style={{ padding: "14px 0", textAlign: "right" }}>
                          <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 13, color: T.green }}>{w.pnl}</span>
                        </td>
                        <td style={{ padding: "14px 0", textAlign: "right" }}>
                          <button style={{
                            padding: "5px 14px", borderRadius: 6, cursor: "pointer",
                            background: `${T.turrellViolet}15`,
                            border: `1px solid ${T.turrellViolet}35`,
                            color: T.turrellDusk,
                            fontFamily: "'DM Sans', sans-serif", fontSize: 11, fontWeight: 600,
                            transition: "all 0.2s",
                          }}>Shadow</button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Card>
            </div>
          )}

          {/* ── ADDRESS TAB ────────────────────────────────────────────────── */}
          {tab === "address" && (
            <div className="fade-up">
              <Card style={{ padding: "24px 28px" }}>
                <div style={{ marginBottom: 20 }}>
                  <div style={{ fontFamily: "'Syne', sans-serif", fontSize: 13, fontWeight: 700, letterSpacing: "0.06em", color: T.primary, marginBottom: 4 }}>ON-CHAIN ADDRESS INTELLIGENCE</div>
                  <p style={{ fontFamily: "'DM Serif Display', serif", fontStyle: "italic", fontSize: 14, color: T.muted }}>
                    Deep wallet forensics across multiple chains — risk profiling, transaction archaeology, portfolio mapping.
                  </p>
                </div>
                <AddressAnalyzer />
              </Card>
            </div>
          )}

          {/* ── MMI TAB ────────────────────────────────────────────────────── */}
          {tab === "mmi" && (
            <div style={{ display: "flex", flexDirection: "column", gap: 16 }} className="fade-up">
              <div style={{ display: "grid", gridTemplateColumns: "280px 1fr", gap: 16 }}>
                {/* Dial */}
                <Card style={{ padding: "28px 20px", display: "flex", flexDirection: "column", alignItems: "center", gap: 16 }} glow>
                  <div style={{ fontFamily: "'Syne', sans-serif", fontSize: 12, fontWeight: 700, letterSpacing: "0.1em", color: T.muted }}>MMI SCORE</div>
                  <MMIDial value={Math.round(mmiScore)} />
                  {/* a16z gold — institutional marker */}
                  <div style={{
                    padding: "8px 16px", borderRadius: 6,
                    background: `${T.amberDim}40`,
                    border: `1px solid ${T.amberDim}80`,
                    textAlign: "center",
                  }}>
                    <Label color={T.amber} style={{ marginBottom: 3 }}>Proprietary Index</Label>
                    <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 10, color: T.amber }}>
                      Fear&Greed + On-Chain + Social
                    </div>
                  </div>
                  <div style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 9, color: T.ghost }}>
                    Updated {ts.toLocaleTimeString()}
                  </div>
                </Card>

                {/* Components */}
                <Card style={{ padding: "20px 24px" }}>
                  <Label style={{ marginBottom: 16 }}>Component Breakdown</Label>
                  <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
                    {mmiData.map(({ name, value, prev }) => {
                      const color = value > 65 ? T.green : value > 45 ? T.blue : value > 30 ? "#FF9500" : T.red;
                      const delta = value - prev;
                      return (
                        <div key={name}>
                          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 5 }}>
                            <Label>{name}</Label>
                            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                              <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 9, color: T.ghost }}>{prev.toFixed(0)} prev</span>
                              <span style={{ display: "flex", alignItems: "center", gap: 2, fontFamily: "'JetBrains Mono', monospace", fontSize: 9, color: delta >= 0 ? T.green : T.red }}>
                                {delta >= 0 ? <ChevronUp size={9} /> : <ChevronDown size={9} />}{Math.abs(delta).toFixed(1)}
                              </span>
                              <DataValue size={14} color={color}>{value.toFixed(0)}</DataValue>
                            </div>
                          </div>
                          <div style={{ height: 5, background: T.raised, borderRadius: 3, overflow: "hidden" }}>
                            <div style={{
                              width: `${value}%`, height: "100%", borderRadius: 3,
                              background: `linear-gradient(90deg, ${color}90, ${color})`,
                              transition: "width 1s cubic-bezier(0.4,0,0.2,1)",
                            }} />
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </Card>
              </div>

              {/* Historical area chart */}
              <Card style={{ padding: "20px 24px" }}>
                <Label style={{ marginBottom: 16 }}>MMI Historical (30D)</Label>
                <ResponsiveContainer width="100%" height={180}>
                  <AreaChart data={Array.from({ length: 30 }, (_, i) => ({
                    d: `D${30 - i}`,
                    v: +(30 + Math.random() * 60 + Math.sin(i / 4.5) * 14).toFixed(1),
                  }))}>
                    <defs>
                      <linearGradient id="mmiAreaGrad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor={T.turrellViolet} stopOpacity={0.35} />
                        <stop offset="50%" stopColor={T.turrellIndigo} stopOpacity={0.15} />
                        <stop offset="100%" stopColor={T.turrellIndigo} stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 8" stroke={T.border} strokeOpacity={0.5} />
                    <XAxis dataKey="d" tick={{ fill: T.muted, fontSize: 9, fontFamily: "JetBrains Mono" }} axisLine={false} tickLine={false} interval={4} />
                    <YAxis domain={[0, 100]} tick={{ fill: T.muted, fontSize: 9, fontFamily: "JetBrains Mono" }} axisLine={false} tickLine={false} />
                    <Tooltip
                      contentStyle={{ background: T.deep, border: `1px solid ${T.border}`, borderRadius: 8, fontSize: 11, fontFamily: "JetBrains Mono" }}
                      itemStyle={{ color: T.turrellDusk }}
                      labelStyle={{ color: T.muted }}
                    />
                    <Area type="monotone" dataKey="v"
                      stroke={T.turrellViolet} fill="url(#mmiAreaGrad)"
                      strokeWidth={1.5} dot={false} activeDot={{ r: 4, fill: T.turrellPink, strokeWidth: 0 }}
                    />
                  </AreaChart>
                </ResponsiveContainer>
              </Card>
            </div>
          )}
        </div>
      </div>
    </>
  );
}
