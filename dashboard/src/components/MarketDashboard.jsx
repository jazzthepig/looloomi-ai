import { useState, useEffect, useRef, useCallback } from "react";
import {
  TrendingUp, TrendingDown, Activity, RefreshCw,
  ExternalLink, Wifi, WifiOff, BarChart2, Globe,
  ArrowUpRight, ArrowDownRight, Minus, Layers, Link2
} from "lucide-react";
import {
  AreaChart, Area, XAxis, YAxis,
  Tooltip, ResponsiveContainer, BarChart, Bar
} from "recharts";

/* ─── Design Tokens ─────────────────────────────────────────────────── */
const T = {
  void:      "#07060F",
  deep:      "#0C0B1A",
  surface:   "#12112B",
  raised:    "#1A1940",
  border:    "#2A2850",
  borderHi:  "#3D3A70",
  primary:   "#F0EDFF",
  secondary: "#9893C4",
  muted:     "#5C5888",
  blue:      "#4F6EF7",
  green:     "#2DD4A0",
  red:       "#F5476A",
  amber:     "#D4AF37",
  turrellPink:   "#FF2D78",
  turrellViolet: "#6F02AC",
  turrellIndigo: "#3F44C7",
};

/* ─── RWA + Infrastructure Token Universe ───────────────────────────── */
const TOKEN_UNIVERSE = [
  // RWA Core
  { symbol: "ONDO",  name: "Ondo Finance",    category: "RWA",    color: "#4F6EF7" },
  { symbol: "POLYX", name: "Polymesh",        category: "RWA",    color: "#9B59B6" },
  { symbol: "SYRUP", name: "Maple Finance",   category: "RWA",    color: "#E67E22" },
  { symbol: "OPEN",  name: "OpenTrade",       category: "RWA",    color: "#2DD4A0" },
  { symbol: "ACX",   name: "Across Protocol", category: "RWA",    color: "#6FCF97" },
  // Oracle / Data Infrastructure
  { symbol: "LINK",  name: "Chainlink",       category: "Oracle", color: "#2A5ADA" },
  { symbol: "PYTH",  name: "Pyth Network",    category: "Oracle", color: "#E6007A" },
  // L1 Backbone
  { symbol: "BTC",   name: "Bitcoin",         category: "L1",     color: "#F7931A" },
  { symbol: "ETH",   name: "Ethereum",        category: "L1",     color: "#627EEA" },
  { symbol: "SOL",   name: "Solana",          category: "L1",     color: "#9945FF" },
  { symbol: "AVAX",  name: "Avalanche",       category: "L1",     color: "#E84142" },
  // L2 Scaling
  { symbol: "ARB",   name: "Arbitrum",        category: "L2",     color: "#28A0F0" },
  { symbol: "OP",    name: "Optimism",        category: "L2",     color: "#FF0420" },
  // DeFi Infrastructure
  { symbol: "AAVE",  name: "Aave",            category: "DeFi",   color: "#B6509E" },
  { symbol: "UNI",   name: "Uniswap",         category: "DeFi",   color: "#FF007A" },
  { symbol: "MKR",   name: "Maker",           category: "DeFi",   color: "#1AAB9B" },
];

const CATEGORIES = ["All", "RWA", "Oracle", "L1", "L2", "DeFi"];

const API_BASE = "/api/v1";
const REFRESH_INTERVAL = 30000; // 30s

/* ─── CSS Injection ─────────────────────────────────────────────────── */
const CSS = `
  @import url('https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=DM+Sans:wght@300;400;500&family=JetBrains+Mono:wght@400;500&display=swap');

  * { box-sizing: border-box; margin: 0; padding: 0; }

  body {
    background: #07060F;
    color: #F0EDFF;
    font-family: 'DM Sans', sans-serif;
    min-height: 100vh;
  }

  ::-webkit-scrollbar { width: 4px; }
  ::-webkit-scrollbar-track { background: #0C0B1A; }
  ::-webkit-scrollbar-thumb { background: #2A2850; border-radius: 2px; }

  @keyframes breathe {
    0%, 100% { opacity: 0.35; transform: scale(1); }
    50% { opacity: 0.55; transform: scale(1.08); }
  }
  @keyframes fadeUp {
    from { opacity: 0; transform: translateY(12px); }
    to   { opacity: 1; transform: translateY(0); }
  }
  @keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.4; }
  }
  @keyframes shimmer {
    0% { background-position: -200% center; }
    100% { background-position: 200% center; }
  }
  @keyframes slideIn {
    from { opacity: 0; transform: translateX(-8px); }
    to   { opacity: 1; transform: translateX(0); }
  }

  .fade-up { animation: fadeUp 0.4s ease forwards; }
  .pulse-dot { animation: pulse 2s infinite; }

  .token-row {
    transition: background 0.15s ease, transform 0.15s ease;
    cursor: pointer;
  }
  .token-row:hover {
    background: rgba(79, 110, 247, 0.06) !important;
    transform: translateX(2px);
  }

  .category-btn {
    transition: all 0.2s ease;
    cursor: pointer;
    border: none;
    outline: none;
  }
  .category-btn:hover { opacity: 0.85; }

  .card {
    background: rgba(18, 17, 43, 0.85);
    border: 1px solid #2A2850;
    border-radius: 12px;
    backdrop-filter: blur(16px);
    transition: border-color 0.2s ease;
  }
  .card:hover { border-color: #3D3A70; }

  .skeleton {
    background: linear-gradient(90deg, #1A1940 25%, #2A2850 50%, #1A1940 75%);
    background-size: 200% 100%;
    animation: shimmer 1.5s infinite;
    border-radius: 4px;
  }

  .change-up   { color: #2DD4A0; }
  .change-down { color: #F5476A; }
  .change-flat { color: #9893C4; }

  .turrell-ambient {
    position: fixed; inset: 0; pointer-events: none; z-index: 0;
    overflow: hidden;
  }
  .orb {
    position: absolute; border-radius: 50%;
    filter: blur(80px);
  }
  .orb-1 {
    width: 600px; height: 600px;
    background: radial-gradient(circle, rgba(111,2,172,0.18) 0%, transparent 70%);
    top: -200px; left: -100px;
    animation: breathe 45s ease-in-out infinite;
  }
  .orb-2 {
    width: 500px; height: 500px;
    background: radial-gradient(circle, rgba(63,68,199,0.14) 0%, transparent 70%);
    top: 10%; right: -150px;
    animation: breathe 55s ease-in-out infinite 12s;
  }
  .orb-3 {
    width: 400px; height: 400px;
    background: radial-gradient(circle, rgba(255,45,120,0.08) 0%, transparent 70%);
    bottom: 0; left: 30%;
    animation: breathe 65s ease-in-out infinite 25s;
  }
`;

/* ─── Helpers ───────────────────────────────────────────────────────── */
const fmt = {
  price: (v) => {
    if (!v && v !== 0) return "—";
    if (v >= 10000) return `$${v.toLocaleString("en", { maximumFractionDigits: 0 })}`;
    if (v >= 1)     return `$${v.toLocaleString("en", { minimumFractionDigits: 2, maximumFractionDigits: 4 })}`;
    return `$${v.toFixed(6)}`;
  },
  change: (v) => {
    if (v === null || v === undefined) return "—";
    return `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`;
  },
  volume: (v) => {
    if (!v) return "—";
    if (v >= 1e9) return `$${(v / 1e9).toFixed(2)}B`;
    if (v >= 1e6) return `$${(v / 1e6).toFixed(1)}M`;
    return `$${v.toLocaleString()}`;
  },
  tvl: (v) => {
    if (!v) return "—";
    if (v >= 1e9) return `$${(v / 1e9).toFixed(2)}B`;
    if (v >= 1e6) return `$${(v / 1e6).toFixed(1)}M`;
    return `$${v.toLocaleString()}`;
  },
};

const ChangeIcon = ({ v, size = 12 }) => {
  if (!v && v !== 0) return null;
  if (v > 0.05) return <ArrowUpRight size={size} />;
  if (v < -0.05) return <ArrowDownRight size={size} />;
  return <Minus size={size} />;
};

/* ─── Skeleton loaders ──────────────────────────────────────────────── */
const SkeletonRow = () => (
  <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr 1fr 1fr 1fr", gap: 12, padding: "14px 20px", borderBottom: `1px solid ${T.border}`, alignItems: "center" }}>
    {[140, 90, 80, 80, 90].map((w, i) => (
      <div key={i} className="skeleton" style={{ height: 14, width: w, maxWidth: "100%" }} />
    ))}
  </div>
);

/* ─── OHLCV Mini Chart ──────────────────────────────────────────────── */
const MiniChart = ({ data, color, positive }) => {
  if (!data?.length) return <div style={{ width: 80, height: 36, display: "flex", alignItems: "center", justifyContent: "center" }}><div className="skeleton" style={{ width: 80, height: 36 }} /></div>;
  const chartColor = positive ? T.green : T.red;
  return (
    <ResponsiveContainer width={80} height={36}>
      <AreaChart data={data} margin={{ top: 2, right: 0, left: 0, bottom: 2 }}>
        <defs>
          <linearGradient id={`g-${color}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={chartColor} stopOpacity={0.3} />
            <stop offset="100%" stopColor={chartColor} stopOpacity={0} />
          </linearGradient>
        </defs>
        <Area type="monotone" dataKey="close" stroke={chartColor} strokeWidth={1.5}
          fill={`url(#g-${color})`} dot={false} />
      </AreaChart>
    </ResponsiveContainer>
  );
};

/* ─── Category Badge ────────────────────────────────────────────────── */
const CategoryBadge = ({ cat }) => {
  const colors = {
    "RWA":    { bg: "rgba(212,175,55,0.12)",  text: T.amber },
    "Oracle": { bg: "rgba(79,110,247,0.12)",  text: T.blue },
    "L1":     { bg: "rgba(45,212,160,0.12)",  text: T.green },
    "L2":     { bg: "rgba(45,212,160,0.08)",  text: "#5EEDC9" },
    "DeFi":   { bg: "rgba(255,45,120,0.10)",  text: T.turrellPink },
  };
  const c = colors[cat] || { bg: "rgba(255,255,255,0.05)", text: T.secondary };
  return (
    <span style={{ fontSize: 10, fontWeight: 600, letterSpacing: "0.06em",
      padding: "2px 7px", borderRadius: 4, background: c.bg, color: c.text,
      fontFamily: "'DM Sans', sans-serif", textTransform: "uppercase" }}>
      {cat}
    </span>
  );
};

/* ─── Token Detail Panel ────────────────────────────────────────────── */
const TokenDetail = ({ token, priceData, ohlcv, onClose }) => {
  const p = priceData?.[token.symbol];
  const candles = ohlcv?.[token.symbol] || [];
  const positive = (p?.change_24h || 0) >= 0;

  return (
    <div className="card fade-up" style={{ padding: 24, marginBottom: 2 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 20 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <div style={{ width: 40, height: 40, borderRadius: "50%", background: `${token.color}22`,
            border: `1px solid ${token.color}44`, display: "flex", alignItems: "center",
            justifyContent: "center", fontSize: 13, fontWeight: 700, color: token.color,
            fontFamily: "'JetBrains Mono', monospace" }}>
            {token.symbol.slice(0, 2)}
          </div>
          <div>
            <div style={{ fontSize: 18, fontWeight: 700, fontFamily: "'Syne', sans-serif", color: T.primary }}>
              {token.name}
            </div>
            <div style={{ display: "flex", gap: 8, marginTop: 4 }}>
              <span style={{ fontSize: 12, color: T.secondary, fontFamily: "'JetBrains Mono', monospace" }}>
                {token.symbol}/USDT
              </span>
              <CategoryBadge cat={token.category} />
            </div>
          </div>
        </div>
        <button onClick={onClose} style={{ background: "none", border: "none", color: T.muted,
          cursor: "pointer", fontSize: 20, lineHeight: 1 }}>×</button>
      </div>

      {/* Price row */}
      <div style={{ display: "flex", gap: 32, marginBottom: 20, flexWrap: "wrap" }}>
        <div>
          <div style={{ fontSize: 11, color: T.muted, marginBottom: 4, textTransform: "uppercase", letterSpacing: "0.08em" }}>Price</div>
          <div style={{ fontSize: 28, fontWeight: 700, fontFamily: "'JetBrains Mono', monospace", color: T.primary }}>
            {p ? fmt.price(p.price) : <span className="skeleton" style={{ width: 120, height: 28, display: "inline-block" }} />}
          </div>
        </div>
        <div>
          <div style={{ fontSize: 11, color: T.muted, marginBottom: 4, textTransform: "uppercase", letterSpacing: "0.08em" }}>24h Change</div>
          <div style={{ fontSize: 22, fontWeight: 600, fontFamily: "'JetBrains Mono', monospace",
            color: positive ? T.green : T.red }}>
            {p ? fmt.change(p.change_24h) : "—"}
          </div>
        </div>
        <div>
          <div style={{ fontSize: 11, color: T.muted, marginBottom: 4, textTransform: "uppercase", letterSpacing: "0.08em" }}>24h Volume</div>
          <div style={{ fontSize: 16, fontWeight: 500, fontFamily: "'JetBrains Mono', monospace", color: T.secondary }}>
            {p ? fmt.volume(p.volume_24h_usdt) : "—"}
          </div>
        </div>
        <div>
          <div style={{ fontSize: 11, color: T.muted, marginBottom: 4, textTransform: "uppercase", letterSpacing: "0.08em" }}>24h High</div>
          <div style={{ fontSize: 16, fontWeight: 500, fontFamily: "'JetBrains Mono', monospace", color: T.secondary }}>
            {p ? fmt.price(p.high_24h) : "—"}
          </div>
        </div>
        <div>
          <div style={{ fontSize: 11, color: T.muted, marginBottom: 4, textTransform: "uppercase", letterSpacing: "0.08em" }}>24h Low</div>
          <div style={{ fontSize: 16, fontWeight: 500, fontFamily: "'JetBrains Mono', monospace", color: T.secondary }}>
            {p ? fmt.price(p.low_24h) : "—"}
          </div>
        </div>
      </div>

      {/* 24h Chart */}
      {candles.length > 0 && (
        <div>
          <div style={{ fontSize: 11, color: T.muted, marginBottom: 12, textTransform: "uppercase", letterSpacing: "0.08em" }}>
            24h Price Chart (1h candles)
          </div>
          <ResponsiveContainer width="100%" height={140}>
            <AreaChart data={candles} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
              <defs>
                <linearGradient id="detail-grad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={positive ? T.green : T.red} stopOpacity={0.25} />
                  <stop offset="100%" stopColor={positive ? T.green : T.red} stopOpacity={0} />
                </linearGradient>
              </defs>
              <XAxis dataKey="time" tick={{ fontSize: 9, fill: T.muted }} tickLine={false}
                tickFormatter={(t) => t.slice(11, 16)} interval={3} />
              <YAxis tick={{ fontSize: 9, fill: T.muted, fontFamily: "'JetBrains Mono', monospace" }}
                tickLine={false} axisLine={false}
                tickFormatter={(v) => v >= 1000 ? `${(v/1000).toFixed(1)}k` : v.toFixed(2)} />
              <Tooltip
                contentStyle={{ background: T.raised, border: `1px solid ${T.border}`, borderRadius: 8, fontSize: 11 }}
                labelStyle={{ color: T.muted }}
                formatter={(v) => [fmt.price(v), "Price"]}
                labelFormatter={(t) => t.slice(0, 16)} />
              <Area type="monotone" dataKey="close" stroke={positive ? T.green : T.red}
                strokeWidth={2} fill="url(#detail-grad)" dot={false} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
};

/* ═══════════════════════════════════════════════════════════════════════
   MAIN MARKET DASHBOARD
═══════════════════════════════════════════════════════════════════════ */
export default function MarketDashboard({ activeTab, setActiveTab }) {
  const [priceData, setPriceData]     = useState({});
  const [ohlcv, setOhlcv]             = useState({});
  const [fng, setFng]                 = useState(null);
  const [defi, setDefi]               = useState(null);
  const [movers, setMovers]           = useState(null);
  const [loading, setLoading]         = useState(true);
  const [lastUpdate, setLastUpdate]   = useState(null);
  const [live, setLive]               = useState(true);
  const [category, setCategory]       = useState("All");
  const [selectedToken, setSelected]  = useState(null);
  const [apiStatus, setApiStatus]     = useState("connecting");
  const intervalRef                   = useRef(null);

  // Inject CSS once
  useEffect(() => {
    const id = "looloomi-market-css";
    if (!document.getElementById(id)) {
      const s = document.createElement("style");
      s.id = id; s.textContent = CSS;
      document.head.appendChild(s);
    }
  }, []);

  // Fetch prices from backend
  const fetchPrices = useCallback(async () => {
    const symbols = TOKEN_UNIVERSE.map(t => t.symbol).join(",");
    try {
      const r = await fetch(`${API_BASE}/market/prices?symbols=${symbols}`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const json = await r.json();
      const map = {};
      for (const item of json.data || []) {
        if (item.symbol) map[item.symbol] = item;
      }
      setPriceData(map);
      setApiStatus("live");
      setLastUpdate(new Date());
    } catch (e) {
      setApiStatus("error");
      console.error("Price fetch error:", e);
    }
  }, []);

  // Fetch OHLCV for selected token
  const fetchOhlcv = useCallback(async (symbol) => {
    if (ohlcv[symbol]) return; // cached
    try {
      const r = await fetch(`${API_BASE}/market/ohlcv/${symbol}?interval=1h&limit=24`);
      const json = await r.json();
      setOhlcv(prev => ({ ...prev, [symbol]: json.data || [] }));
    } catch (e) {
      console.error("OHLCV error:", e);
    }
  }, [ohlcv]);

  // Fetch Fear & Greed + DeFi overview + movers
  const fetchSupplementary = useCallback(async () => {
    try {
      const [fngR, defiR, moversR] = await Promise.allSettled([
        fetch(`${API_BASE}/mmi/sentiment/fear-greed?limit=7`).then(r => r.json()),
        fetch(`${API_BASE}/defi/overview`).then(r => r.json()),
        fetch(`${API_BASE}/market/movers`).then(r => r.json()),
      ]);
      if (fngR.status === "fulfilled") setFng(fngR.value);
      if (defiR.status === "fulfilled") setDefi(defiR.value);
      if (moversR.status === "fulfilled") setMovers(moversR.value);
    } catch (e) {
      console.error("Supplementary fetch error:", e);
    }
  }, []);

  // Fetch OHLCV for all tokens in background (mini charts)
  const fetchAllOhlcv = useCallback(async () => {
    const symbols = TOKEN_UNIVERSE.map(t => t.symbol);
    for (let i = 0; i < symbols.length; i += 5) {
      const batch = symbols.slice(i, i + 5);
      await Promise.allSettled(batch.map(async (symbol) => {
        try {
          const r = await fetch(`${API_BASE}/market/ohlcv/${symbol}?interval=1h&limit=24`);
          const json = await r.json();
          if (json.data?.length) setOhlcv(prev => ({ ...prev, [symbol]: json.data }));
        } catch (e) {}
      }));
    }
  }, []);

  // Initial load
  useEffect(() => {
    const init = async () => {
      setLoading(true);
      await Promise.all([fetchPrices(), fetchSupplementary()]);
      setLoading(false);
      fetchAllOhlcv();
    };
    init();
  }, []);

  // Live polling
  useEffect(() => {
    if (live) {
      intervalRef.current = setInterval(fetchPrices, REFRESH_INTERVAL);
    } else {
      clearInterval(intervalRef.current);
    }
    return () => clearInterval(intervalRef.current);
  }, [live, fetchPrices]);

  // Fetch OHLCV when token selected
  useEffect(() => {
    if (selectedToken) fetchOhlcv(selectedToken.symbol);
  }, [selectedToken]);

  // Filtered tokens
  const filtered = TOKEN_UNIVERSE.filter(t =>
    category === "All" || t.category === category
  );

  // F&G gauge
  const fngCurrent = fng?.current || {};
  const fngValue = fngCurrent.value || 0;
  const fngColor = fngValue >= 60 ? T.green : fngValue >= 40 ? T.amber : T.red;
  const fngLabel = fngCurrent.label || "—";

  // Portfolio summary bar (top gainers from our universe)
  const sortedByChange = [...TOKEN_UNIVERSE]
    .map(t => ({ ...t, change: priceData[t.symbol]?.change_24h || 0 }))
    .sort((a, b) => b.change - a.change);

  return (
    <div style={{ position: "relative", minHeight: "100vh", background: T.void }}>
      {/* Turrell ambient */}
      <div className="turrell-ambient">
        <div className="orb orb-1" />
        <div className="orb orb-2" />
        <div className="orb orb-3" />
      </div>

      <div style={{ position: "relative", zIndex: 1, maxWidth: 1400, margin: "0 auto", padding: "0 24px 48px" }}>

        {/* ── Top Bar ──────────────────────────────────────────────── */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between",
          padding: "20px 0 24px", borderBottom: `1px solid ${T.border}` }}>
          <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
            <span style={{ fontFamily: "'Syne', sans-serif", fontWeight: 800, fontSize: 22,
              background: `linear-gradient(135deg, ${T.turrellPink}, ${T.turrellViolet}, ${T.blue})`,
              WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent" }}>
              LOOLOOMI
            </span>
            <div style={{ display: "flex", gap: 4 }}>
              {["Market", "Intelligence", "Quant GP"].map(tab => (
                <button key={tab}
                  onClick={() => setActiveTab(tab)}
                  style={{
                    padding: "6px 16px", borderRadius: 6, fontSize: 12,
                    fontFamily: "'DM Sans', sans-serif", fontWeight: 500,
                    background: activeTab === tab ? `${T.blue}22` : "transparent",
                    border: `1px solid ${activeTab === tab ? T.blue : T.border}`,
                    color: activeTab === tab ? T.blue : T.secondary,
                    cursor: "pointer", outline: "none", transition: "all 0.2s",
                  }}>
                  {tab}
                </button>
              ))}
            </div>
          </div>

          <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
            {/* API status */}
            <div style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 11,
              color: apiStatus === "live" ? T.green : apiStatus === "error" ? T.red : T.amber,
              fontFamily: "'JetBrains Mono', monospace" }}>
              <div className="pulse-dot" style={{ width: 6, height: 6, borderRadius: "50%",
                background: apiStatus === "live" ? T.green : apiStatus === "error" ? T.red : T.amber }} />
              {apiStatus === "live" ? "LIVE" : apiStatus === "error" ? "ERROR" : "CONNECTING"}
            </div>

            {/* Last update */}
            {lastUpdate && (
              <span style={{ fontSize: 11, color: T.muted, fontFamily: "'JetBrains Mono', monospace" }}>
                {lastUpdate.toLocaleTimeString()}
              </span>
            )}

            {/* Live toggle */}
            <button onClick={() => setLive(l => !l)}
              style={{ display: "flex", alignItems: "center", gap: 6, padding: "6px 12px",
                borderRadius: 6, border: `1px solid ${live ? T.blue : T.border}`,
                background: live ? `${T.blue}18` : "transparent",
                color: live ? T.blue : T.muted, cursor: "pointer", fontSize: 11,
                fontFamily: "'DM Sans', sans-serif", transition: "all 0.2s" }}>
              {live ? <Wifi size={12} /> : <WifiOff size={12} />}
              {live ? "LIVE" : "PAUSED"}
            </button>

            {/* Refresh */}
            <button onClick={() => { fetchPrices(); fetchSupplementary(); }}
              style={{ display: "flex", alignItems: "center", gap: 6, padding: "6px 12px",
                borderRadius: 6, border: `1px solid ${T.border}`,
                background: "transparent", color: T.secondary,
                cursor: "pointer", fontSize: 11, fontFamily: "'DM Sans', sans-serif" }}>
              <RefreshCw size={12} /> Refresh
            </button>
          </div>
        </div>

        {/* ── Summary Stats Row ─────────────────────────────────────── */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12, margin: "20px 0" }}>
          {/* Fear & Greed */}
          <div className="card" style={{ padding: 16 }}>
            <div style={{ fontSize: 10, color: T.muted, letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 8 }}>
              Fear & Greed
            </div>
            {fng ? (
              <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
                <span style={{ fontSize: 32, fontWeight: 700, fontFamily: "'JetBrains Mono', monospace", color: fngColor }}>
                  {fngValue}
                </span>
                <span style={{ fontSize: 12, color: fngColor, fontWeight: 500 }}>{fngLabel}</span>
              </div>
            ) : <div className="skeleton" style={{ height: 36, width: 100 }} />}
            <div style={{ fontSize: 10, color: T.muted, marginTop: 4 }}>Alternative.me · Daily</div>
          </div>

          {/* Total DeFi TVL */}
          <div className="card" style={{ padding: 16 }}>
            <div style={{ fontSize: 10, color: T.muted, letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 8 }}>
              DeFi TVL
            </div>
            {defi ? (
              <div style={{ fontSize: 32, fontWeight: 700, fontFamily: "'JetBrains Mono', monospace", color: T.primary }}>
                {defi.total_tvl_formatted}
              </div>
            ) : <div className="skeleton" style={{ height: 36, width: 90 }} />}
            <div style={{ fontSize: 10, color: T.muted, marginTop: 4 }}>DeFiLlama · All chains</div>
          </div>

          {/* Top gainer */}
          <div className="card" style={{ padding: 16 }}>
            <div style={{ fontSize: 10, color: T.muted, letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 8 }}>
              Top Gainer (24h)
            </div>
            {sortedByChange[0]?.change !== 0 ? (
              <div>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <span style={{ fontSize: 20, fontWeight: 700, fontFamily: "'Syne', sans-serif", color: T.primary }}>
                    {sortedByChange[0]?.symbol}
                  </span>
                  <span style={{ fontSize: 18, fontWeight: 600, fontFamily: "'JetBrains Mono', monospace", color: T.green }}>
                    {fmt.change(sortedByChange[0]?.change)}
                  </span>
                </div>
                <div style={{ fontSize: 10, color: T.muted, marginTop: 4 }}>{sortedByChange[0]?.name}</div>
              </div>
            ) : <div className="skeleton" style={{ height: 36, width: 110 }} />}
          </div>

          {/* Top loser */}
          <div className="card" style={{ padding: 16 }}>
            <div style={{ fontSize: 10, color: T.muted, letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 8 }}>
              Top Loser (24h)
            </div>
            {sortedByChange[sortedByChange.length - 1]?.change !== 0 ? (
              <div>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <span style={{ fontSize: 20, fontWeight: 700, fontFamily: "'Syne', sans-serif", color: T.primary }}>
                    {sortedByChange[sortedByChange.length - 1]?.symbol}
                  </span>
                  <span style={{ fontSize: 18, fontWeight: 600, fontFamily: "'JetBrains Mono', monospace", color: T.red }}>
                    {fmt.change(sortedByChange[sortedByChange.length - 1]?.change)}
                  </span>
                </div>
                <div style={{ fontSize: 10, color: T.muted, marginTop: 4 }}>{sortedByChange[sortedByChange.length - 1]?.name}</div>
              </div>
            ) : <div className="skeleton" style={{ height: 36, width: 110 }} />}
          </div>
        </div>

        {/* ── Category Filter ───────────────────────────────────────── */}
        <div style={{ display: "flex", gap: 8, marginBottom: 16 }}>
          {CATEGORIES.map(cat => (
            <button key={cat} className="category-btn"
              onClick={() => { setCategory(cat); setSelected(null); }}
              style={{
                padding: "6px 16px", borderRadius: 6, fontSize: 12,
                fontFamily: "'DM Sans', sans-serif", fontWeight: 500,
                background: category === cat ? `${T.blue}22` : "transparent",
                border: `1px solid ${category === cat ? T.blue : T.border}`,
                color: category === cat ? T.blue : T.secondary,
              }}>
              {cat}
            </button>
          ))}
          <div style={{ marginLeft: "auto", fontSize: 11, color: T.muted, alignSelf: "center",
            fontFamily: "'JetBrains Mono', monospace" }}>
            {filtered.length} assets · Binance
          </div>
        </div>

        {/* ── Token Table ───────────────────────────────────────────── */}
        <div className="card" style={{ overflow: "hidden" }}>
          {/* Header */}
          <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr 1fr 1fr 1fr",
            gap: 12, padding: "12px 20px", borderBottom: `1px solid ${T.border}`,
            fontSize: 10, color: T.muted, letterSpacing: "0.1em", textTransform: "uppercase" }}>
            <span>Asset</span>
            <span style={{ textAlign: "right" }}>Price</span>
            <span style={{ textAlign: "right" }}>24h Change</span>
            <span style={{ textAlign: "right" }}>Volume</span>
            <span style={{ textAlign: "right" }}>7d Chart</span>
          </div>

          {/* Rows */}
          {loading
            ? Array(8).fill(0).map((_, i) => <SkeletonRow key={i} />)
            : filtered.map((token, i) => {
                const p = priceData[token.symbol];
                const positive = (p?.change_24h || 0) >= 0;
                const isSelected = selectedToken?.symbol === token.symbol;

                return (
                  <div key={token.symbol}>
                    <div className="token-row"
                      onClick={() => setSelected(isSelected ? null : token)}
                      style={{
                        display: "grid", gridTemplateColumns: "2fr 1fr 1fr 1fr 1fr",
                        gap: 12, padding: "14px 20px",
                        borderBottom: `1px solid ${T.border}`,
                        background: isSelected ? `${T.blue}08` : "transparent",
                        animation: `fadeUp 0.3s ease ${i * 0.03}s both`,
                      }}>

                      {/* Name */}
                      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                        <div style={{ width: 32, height: 32, borderRadius: "50%",
                          background: `${token.color}18`,
                          border: `1px solid ${token.color}33`,
                          display: "flex", alignItems: "center", justifyContent: "center",
                          fontSize: 10, fontWeight: 700, color: token.color,
                          fontFamily: "'JetBrains Mono', monospace", flexShrink: 0 }}>
                          {token.symbol.slice(0, 2)}
                        </div>
                        <div>
                          <div style={{ fontSize: 14, fontWeight: 600, color: T.primary,
                            fontFamily: "'Syne', sans-serif", lineHeight: 1.2 }}>
                            {token.symbol}
                          </div>
                          <div style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 2 }}>
                            <span style={{ fontSize: 11, color: T.muted }}>{token.name}</span>
                            <CategoryBadge cat={token.category} />
                          </div>
                        </div>
                      </div>

                      {/* Price */}
                      <div style={{ textAlign: "right", display: "flex", alignItems: "center", justifyContent: "flex-end" }}>
                        {p ? (
                          <span style={{ fontSize: 14, fontWeight: 500, color: T.primary,
                            fontFamily: "'JetBrains Mono', monospace" }}>
                            {fmt.price(p.price)}
                          </span>
                        ) : <div className="skeleton" style={{ height: 14, width: 70 }} />}
                      </div>

                      {/* 24h Change */}
                      <div style={{ textAlign: "right", display: "flex", alignItems: "center",
                        justifyContent: "flex-end", gap: 4 }}>
                        {p ? (
                          <span style={{ fontSize: 13, fontWeight: 500,
                            fontFamily: "'JetBrains Mono', monospace",
                            color: positive ? T.green : T.red }}>
                            <ChangeIcon v={p.change_24h} size={11} />
                            {Math.abs(p.change_24h).toFixed(2)}%
                          </span>
                        ) : <div className="skeleton" style={{ height: 14, width: 55 }} />}
                      </div>

                      {/* Volume */}
                      <div style={{ textAlign: "right", display: "flex", alignItems: "center", justifyContent: "flex-end" }}>
                        {p ? (
                          <span style={{ fontSize: 12, color: T.secondary,
                            fontFamily: "'JetBrains Mono', monospace" }}>
                            {fmt.volume(p.volume_24h_usdt)}
                          </span>
                        ) : <div className="skeleton" style={{ height: 14, width: 60 }} />}
                      </div>

                      {/* Mini chart */}
                      <div style={{ display: "flex", alignItems: "center", justifyContent: "flex-end" }}>
                        <MiniChart
                          data={ohlcv[token.symbol]}
                          color={token.color}
                          positive={positive}
                        />
                      </div>
                    </div>

                    {/* Expanded detail */}
                    {isSelected && (
                      <div style={{ padding: "0 12px 12px", background: `${T.blue}04` }}>
                        <TokenDetail
                          token={token}
                          priceData={priceData}
                          ohlcv={ohlcv}
                          onClose={() => setSelected(null)}
                        />
                      </div>
                    )}
                  </div>
                );
              })
          }
        </div>

        {/* ── DeFi Top Protocols ────────────────────────────────────── */}
        {defi?.top_protocols?.length > 0 && (
          <div style={{ marginTop: 24 }}>
            <div style={{ fontSize: 11, color: T.muted, letterSpacing: "0.1em",
              textTransform: "uppercase", marginBottom: 12, display: "flex",
              alignItems: "center", gap: 8 }}>
              <Layers size={12} /> DeFiLlama · Top Protocols by TVL
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: 10 }}>
              {defi.top_protocols.slice(0, 8).map((p, i) => (
                <div key={p.name} className="card" style={{ padding: "12px 14px",
                  animation: `fadeUp 0.3s ease ${i * 0.05}s both` }}>
                  <div style={{ fontSize: 13, fontWeight: 600, color: T.primary,
                    fontFamily: "'Syne', sans-serif", marginBottom: 4 }}>{p.name}</div>
                  <div style={{ fontSize: 16, fontWeight: 700, color: T.blue,
                    fontFamily: "'JetBrains Mono', monospace", marginBottom: 6 }}>
                    {fmt.tvl(p.tvl)}
                  </div>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <span style={{ fontSize: 10, color: T.muted }}>{p.category}</span>
                    {p.change_1d !== undefined && (
                      <span style={{ fontSize: 10, fontFamily: "'JetBrains Mono', monospace",
                        color: (p.change_1d || 0) >= 0 ? T.green : T.red }}>
                        {fmt.change(p.change_1d)}
                      </span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* ── Footer ───────────────────────────────────────────────── */}
        <div style={{ marginTop: 32, paddingTop: 16, borderTop: `1px solid ${T.border}`,
          display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div style={{ fontSize: 10, color: T.muted, fontFamily: "'JetBrains Mono', monospace" }}>
            Data: Binance · DeFiLlama · Alternative.me · 30s refresh
          </div>
          <div style={{ fontSize: 10, color: T.muted }}>
            CometCloud AI — Institutional RWA Intelligence
          </div>
        </div>

      </div>
    </div>
  );
}
