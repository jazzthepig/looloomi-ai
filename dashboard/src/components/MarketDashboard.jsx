import { useState, useEffect, useRef, useCallback } from "react";
import {
  RefreshCw, Wifi, WifiOff, ArrowUpRight, ArrowDownRight,
  Minus, Layers, TrendingUp
} from "lucide-react";
import {
  AreaChart, Area, XAxis, YAxis,
  Tooltip, ResponsiveContainer
} from "recharts";
import BottomSheet from "./ui/BottomSheet";

/* ─── Design Tokens ──────────────────────────────────────────────────── */
const T = {
  void:      "#020208",
  deep:      "#06050F",
  surface:   "#0A0918",
  raised:    "#100E22",
  overlay:   "#16132E",
  border:    "#1A173A",
  borderHi:  "#28244C",
  primary:   "#F0EEFF",
  secondary: "#8880BE",
  muted:     "#3E3A6E",
  dim:       "#252248",
  violet:    "#6B0FCC",
  indigo:    "#2D35D4",
  cyan:      "#00C8E0",
  pink:      "#FF1060",
  amber:     "#E8A000",
  green:     "#00D98A",
  red:       "#FF2D55",
  blue:      "#4472FF",
};

const FONTS = {
  display: "'Space Grotesk', sans-serif",
  body:    "'Exo 2', sans-serif",
  mono:    "'JetBrains Mono', monospace",
};

/* ─── Token Universe ─────────────────────────────────────────────────── */
const TOKEN_UNIVERSE = [
  { symbol: "ONDO",  name: "Ondo Finance",    category: "RWA",    color: "#4472FF" },
  { symbol: "POLYX", name: "Polymesh",        category: "RWA",    color: "#9B59B6" },
  { symbol: "SYRUP", name: "Maple Finance",   category: "RWA",    color: "#E8A000" },
  { symbol: "OPEN",  name: "OpenTrade",       category: "RWA",    color: "#00D98A" },
  { symbol: "ACX",   name: "Across Protocol", category: "RWA",    color: "#00C8E0" },
  { symbol: "LINK",  name: "Chainlink",       category: "Oracle", color: "#2A5ADA" },
  { symbol: "PYTH",  name: "Pyth Network",    category: "Oracle", color: "#FF1060" },
  { symbol: "BTC",   name: "Bitcoin",         category: "L1",     color: "#F7931A" },
  { symbol: "ETH",   name: "Ethereum",        category: "L1",     color: "#627EEA" },
  { symbol: "SOL",   name: "Solana",          category: "L1",     color: "#9945FF" },
  { symbol: "AVAX",  name: "Avalanche",       category: "L1",     color: "#E84142" },
  { symbol: "ARB",   name: "Arbitrum",        category: "L2",     color: "#28A0F0" },
  { symbol: "OP",    name: "Optimism",        category: "L2",     color: "#FF0420" },
  { symbol: "AAVE",  name: "Aave",            category: "DeFi",   color: "#B6509E" },
  { symbol: "UNI",   name: "Uniswap",         category: "DeFi",   color: "#FF007A" },
  { symbol: "MKR",   name: "Maker",           category: "DeFi",   color: "#1AAB9B" },
];

const CATEGORIES = ["All", "RWA", "Oracle", "L1", "L2", "DeFi"];
const API_BASE = "/api/v1";
const REFRESH_INTERVAL = 30000;

/* Global CSS */
const CSS = `
  @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600;700;800&family=Exo+2:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap');

  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  html { -webkit-font-smoothing: antialiased; }

  body {
    background: #020208;
    color: #F0EEFF;
    font-family: 'Exo 2', sans-serif;
    min-height: 100vh;
  }

  ::-webkit-scrollbar { width: 3px; height: 3px; }
  ::-webkit-scrollbar-track { background: transparent; }
  ::-webkit-scrollbar-thumb { background: #1A173A; border-radius: 2px; }

  @keyframes breathe {
    0%,100% { opacity:0.28; transform:scale(1) translateY(0); }
    50%      { opacity:0.44; transform:scale(1.06) translateY(-12px); }
  }
  @keyframes breathe2 {
    0%,100% { opacity:0.16; transform:scale(1); }
    50%      { opacity:0.30; transform:scale(1.08) translateX(10px); }
  }
  @keyframes fadeUp {
    from { opacity:0; transform:translateY(14px); }
    to   { opacity:1; transform:translateY(0); }
  }
  @keyframes slideIn {
    from { opacity:0; transform:translateX(-8px); }
    to   { opacity:1; transform:translateX(0); }
  }
  @keyframes pulse {
    0%,100% { opacity:1; }
    50%      { opacity:0.35; }
  }
  @keyframes shimmer {
    0%   { background-position:-400px 0; }
    100% { background-position: 400px 0; }
  }

  .fade-up  { animation: fadeUp 0.4s cubic-bezier(.16,1,.3,1) forwards; }
  .slide-in { animation: slideIn 0.25s ease forwards; }

  /* Turrell ambient orbs */
  .turrell-wrap {
    position:fixed; inset:0;
    pointer-events:none; z-index:0; overflow:hidden;
  }
  .t-orb {
    position:absolute; border-radius:50%;
    filter:blur(100px); mix-blend-mode:screen;
  }
  .t-orb-1 {
    width:720px; height:720px;
    background:radial-gradient(circle,rgba(107,15,204,.20) 0%,transparent 65%);
    top:-300px; left:-200px;
    animation:breathe 52s ease-in-out infinite;
  }
  .t-orb-2 {
    width:560px; height:560px;
    background:radial-gradient(circle,rgba(45,53,212,.15) 0%,transparent 65%);
    top:5%; right:-200px;
    animation:breathe2 64s ease-in-out infinite 9s;
  }
  .t-orb-3 {
    width:380px; height:380px;
    background:radial-gradient(circle,rgba(0,200,224,.09) 0%,transparent 65%);
    bottom:0; left:22%;
    animation:breathe 76s ease-in-out infinite 24s;
  }
  .t-orb-4 {
    width:280px; height:280px;
    background:radial-gradient(circle,rgba(255,16,96,.07) 0%,transparent 65%);
    bottom:12%; right:8%;
    animation:breathe2 60s ease-in-out infinite 38s;
  }

  /* Card */
  .lm-card {
    background:rgba(10,9,24,.82);
    border:1px solid #1A173A;
    border-radius:10px;
    backdrop-filter:blur(20px);
    transition:border-color .2s ease, box-shadow .2s ease;
  }
  .lm-card:hover { border-color:#28244C; }

  /* Interactive row */
  .lm-row {
    transition:background .12s ease, transform .12s ease;
    cursor:pointer;
  }
  .lm-row:hover {
    background:rgba(6,182,212,.06) !important;
    border-left: 2px solid rgba(6,182,212,0.4);
    transform:translateX(2px);
  }

  /* Tab button */
  .lm-tab {
    padding:5px 14px; border-radius:5px;
    font-size:12px; font-weight:500;
    font-family:'Exo 2',sans-serif;
    cursor:pointer; outline:none;
    border:1px solid #1A173A;
    background:transparent; color:#8880BE;
    transition:all .18s ease;
    letter-spacing:0.01em;
  }
  .lm-tab:hover { border-color:#28244C; color:#F0EEFF; }
  .lm-tab.active {
    border-color:rgba(68,114,255,.5);
    background:rgba(68,114,255,.10);
    color:#4472FF;
  }

  /* Category filter */
  .cat-btn {
    padding:5px 13px; border-radius:5px;
    font-size:11px; font-weight:500;
    font-family:'Exo 2',sans-serif;
    cursor:pointer; outline:none;
    border:1px solid #1A173A;
    background:transparent; color:#3E3A6E;
    transition:all .15s ease;
  }
  .cat-btn:hover { border-color:#28244C; color:#8880BE; }
  .cat-btn.active {
    border-color:rgba(68,114,255,.4);
    background:rgba(68,114,255,.08);
    color:#4472FF;
  }

  /* Skeleton */
  .sk {
    background:linear-gradient(90deg,#100E22 30%,#16132E 50%,#100E22 70%);
    background-size:400px 100%;
    animation:shimmer 1.8s ease infinite;
    border-radius:4px;
    display:inline-block;
  }

  .pulse-dot { animation:pulse 2.2s ease-in-out infinite; }

  /* Action button */
  .lm-action-btn {
    display:flex; align-items:center; gap:6px;
    padding:6px 12px; border-radius:6px;
    font-size:11px; font-weight:500;
    font-family:'Exo 2',sans-serif;
    cursor:pointer; outline:none;
    border:1px solid #1A173A;
    background:transparent; color:#8880BE;
    transition:all .18s ease;
  }
  .lm-action-btn:hover { border-color:#28244C; color:#F0EEFF; }
  .lm-action-btn.live-on {
    border-color:rgba(68,114,255,.4);
    background:rgba(68,114,255,.10);
    color:#4472FF;
  }

  /* Mobile responsive */
  @media (max-width: 768px) {
    .mobile-hidden { display: none !important; }
    .mobile-full { width: 100% !important; }
    .mobile-stack { flex-direction: column !important; }
    .mobile-pad { padding: 0 12px !important; }
    .mobile-stat-grid { grid-template-columns: 1fr 1fr !important; }
    .mobile-table-grid { grid-template-columns: 1.8fr 1fr 1fr !important; }
    .mobile-table-header { grid-template-columns: 1.8fr 1fr 1fr !important; }
    .mobile-nav { flex-wrap: wrap !important; gap: 6px !important; }
    .mobile-nav-right { margin-top: 10px !important; width: 100% !important; justify-content: space-between !important; }
    .mobile-7d-chart { display: none !important; }
    .mobile-card-pad { padding: 12px 14px !important; }
    .mobile-header { padding: 12px 0 14px !important; }
    .mobile-footer { flex-direction: column !important; gap: 8px !important; text-align: center !important; }
  }
`;

/* ─── Helpers ────────────────────────────────────────────────────────── */
const fmt = {
  price: (v) => {
    if (!v && v !== 0) return "—";
    if (v >= 10000) return `$${v.toLocaleString("en", { maximumFractionDigits: 0 })}`;
    if (v >= 1)     return `$${v.toLocaleString("en", { minimumFractionDigits: 2, maximumFractionDigits: 4 })}`;
    return `$${v.toFixed(6)}`;
  },
  pct: (v) => {
    if (v === null || v === undefined) return "—";
    return `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`;
  },
  vol: (v) => {
    if (!v) return "—";
    if (v >= 1e9) return `$${(v/1e9).toFixed(2)}B`;
    if (v >= 1e6) return `$${(v/1e6).toFixed(1)}M`;
    return `$${v.toLocaleString()}`;
  },
  tvl: (v) => {
    if (!v) return "—";
    if (v >= 1e9) return `$${(v/1e9).toFixed(2)}B`;
    if (v >= 1e6) return `$${(v/1e6).toFixed(1)}M`;
    return `$${v.toLocaleString()}`;
  },
};

/* ─── Category Badge ─────────────────────────────────────────────────── */
const CAT_STYLE = {
  "RWA":    { bg: "rgba(232,160,0,.12)",    text: "#E8A000" },
  "Oracle": { bg: "rgba(68,114,255,.12)",   text: "#4472FF" },
  "L1":     { bg: "rgba(0,217,138,.10)",    text: "#00D98A" },
  "L2":     { bg: "rgba(0,200,224,.08)",    text: "#00C8E0" },
  "DeFi":   { bg: "rgba(255,16,96,.10)",    text: "#FF1060" },
};

const CatBadge = ({ cat }) => {
  const s = CAT_STYLE[cat] || { bg: "rgba(255,255,255,.05)", text: "#8880BE" };
  return (
    <span style={{
      display: "inline-flex", alignItems: "center",
      padding: "2px 6px", borderRadius: 3,
      fontSize: 9, fontWeight: 700,
      letterSpacing: "0.07em", textTransform: "uppercase",
      fontFamily: FONTS.body,
      background: s.bg, color: s.text,
    }}>
      {cat}
    </span>
  );
};

/* ─── Mini Sparkline ─────────────────────────────────────────────────── */
const Spark = ({ data, positive }) => {
  if (!data?.length) return (
    <div className="sk" style={{ width: 72, height: 32 }} />
  );
  const c = positive ? T.green : T.red;
  return (
    <ResponsiveContainer width={72} height={32}>
      <AreaChart data={data} margin={{ top: 2, right: 0, left: 0, bottom: 2 }}>
        <defs>
          <linearGradient id={`sg-${positive}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={c} stopOpacity={0.28} />
            <stop offset="100%" stopColor={c} stopOpacity={0} />
          </linearGradient>
        </defs>
        <Area type="monotone" dataKey="close"
          stroke={c} strokeWidth={1.5}
          fill={`url(#sg-${positive})`} dot={false} />
      </AreaChart>
    </ResponsiveContainer>
  );
};

/* ─── Change indicator ───────────────────────────────────────────────── */
const ChangeCell = ({ v }) => {
  if (v === null || v === undefined) return <span style={{ color: T.muted }}>—</span>;
  const pos = v >= 0;
  const Icon = v > 0.05 ? ArrowUpRight : v < -0.05 ? ArrowDownRight : Minus;
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: 2,
      fontFamily: FONTS.mono, fontSize: 13, fontWeight: 500,
      color: pos ? T.green : T.red,
    }}>
      <Icon size={11} />
      {Math.abs(v).toFixed(2)}%
    </span>
  );
};

/* ─── Token Detail Panel ─────────────────────────────────────────────── */
const TokenDetail = ({ token, priceData, ohlcv, onClose }) => {
  const p = priceData?.[token.symbol];
  const candles = ohlcv?.[token.symbol] || [];
  const positive = (p?.change_24h || 0) >= 0;

  return (
    <div className="lm-card fade-up" style={{ padding: 22, marginBottom: 2 }}>
      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 18 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <div style={{
            width: 38, height: 38, borderRadius: "50%",
            background: `${token.color}18`, border: `1px solid ${token.color}40`,
            display: "flex", alignItems: "center", justifyContent: "center",
            fontSize: 11, fontWeight: 700, color: token.color, fontFamily: FONTS.mono,
          }}>
            {token.symbol.slice(0, 2)}
          </div>
          <div>
            <div style={{ fontSize: 17, fontWeight: 700, fontFamily: FONTS.display, color: T.primary, letterSpacing: "-0.01em" }}>
              {token.name}
            </div>
            <div style={{ display: "flex", gap: 7, marginTop: 4 }}>
              <span style={{ fontSize: 11, color: T.muted, fontFamily: FONTS.mono }}>{token.symbol}/USDT</span>
              <CatBadge cat={token.category} />
            </div>
          </div>
        </div>
        <button onClick={onClose} style={{
          background: "none", border: "none", color: T.muted,
          cursor: "pointer", fontSize: 18, lineHeight: 1, padding: "0 2px",
        }}>×</button>
      </div>

      {/* Stats row */}
      <div style={{ display: "flex", gap: 28, marginBottom: 18, flexWrap: "wrap" }}>
        {[
          { label: "Price", value: p ? fmt.price(p.price) : null, big: true },
          { label: "24h Change", value: p ? fmt.pct(p.change_24h) : null, color: positive ? T.green : T.red },
          { label: "24h Volume", value: p ? fmt.vol(p.volume_24h_usdt) : null },
          { label: "24h High", value: p ? fmt.price(p.high_24h) : null },
          { label: "24h Low", value: p ? fmt.price(p.low_24h) : null },
        ].map(({ label, value, big, color }) => (
          <div key={label}>
            <div style={{ fontSize: 10, color: T.muted, textTransform: "uppercase", letterSpacing: "0.10em", fontFamily: FONTS.body, marginBottom: 5 }}>
              {label}
            </div>
            {value ? (
              <div style={{
                fontSize: big ? 26 : 15, fontWeight: big ? 600 : 500,
                fontFamily: FONTS.mono, color: color || T.primary, lineHeight: 1.1,
                userSelect: "none",
              }}>
                {value}
              </div>
            ) : <div className="sk" style={{ height: big ? 26 : 15, width: 90 }} />}
          </div>
        ))}
      </div>

      {/* Chart */}
      {candles.length > 0 && (
        <>
          <div style={{ fontSize: 10, color: T.muted, textTransform: "uppercase", letterSpacing: "0.10em", fontFamily: FONTS.body, marginBottom: 10 }}>
            24h Price (1h candles)
          </div>
          <ResponsiveContainer width="100%" height={130}>
            <AreaChart data={candles} margin={{ top: 4, right: 4, left: -24, bottom: 0 }}>
              <defs>
                <linearGradient id="dg" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={positive ? T.green : T.red} stopOpacity={0.22} />
                  <stop offset="100%" stopColor={positive ? T.green : T.red} stopOpacity={0} />
                </linearGradient>
              </defs>
              <XAxis dataKey="time" tick={{ fontSize: 9, fill: T.muted }} tickLine={false}
                tickFormatter={(t) => t.slice(11, 16)} interval={3} />
              <YAxis tick={{ fontSize: 9, fill: T.muted, fontFamily: FONTS.mono }}
                tickLine={false} axisLine={false}
                tickFormatter={(v) => v >= 1000 ? `${(v/1000).toFixed(1)}k` : v.toFixed(2)} />
              <Tooltip
                contentStyle={{ background: T.overlay, border: `1px solid ${T.border}`, borderRadius: 8, fontSize: 11 }}
                labelStyle={{ color: T.muted }}
                formatter={(v) => [fmt.price(v), "Price"]}
                labelFormatter={(t) => t.slice(0, 16)} />
              <Area type="monotone" dataKey="close"
                stroke={positive ? T.green : T.red} strokeWidth={1.8}
                fill="url(#dg)" dot={false} />
            </AreaChart>
          </ResponsiveContainer>
        </>
      )}
    </div>
  );
};

/* ═══════════════════════════════════════════════════════════════════════
   MARKET DASHBOARD
═══════════════════════════════════════════════════════════════════════ */
export default function MarketDashboard({ activeTab, setActiveTab, isSection = false }) {
  const [priceData, setPriceData]     = useState({});
  const [ohlcv, setOhlcv]             = useState({});
  const [fng, setFng]                 = useState(null);
  const [defi, setDefi]               = useState(null);
  const [loading, setLoading]         = useState(true);
  const [lastUpdate, setLastUpdate]   = useState(null);
  const [live, setLive]               = useState(true);
  const [category, setCategory]       = useState("All");
  const [selectedToken, setSelected]  = useState(null);
  const [apiStatus, setApiStatus]     = useState("connecting");
  const intervalRef                   = useRef(null);

  useEffect(() => {
    const id = "lm-market-css";
    if (!document.getElementById(id)) {
      const s = document.createElement("style");
      s.id = id; s.textContent = CSS;
      document.head.appendChild(s);
    }
  }, []);

  const fetchPrices = useCallback(async () => {
    const symbols = TOKEN_UNIVERSE.map(t => t.symbol).join(",");
    try {
      const r = await fetch(`${API_BASE}/market/prices?symbols=${symbols}`);
      if (!r.ok) throw new Error();
      const json = await r.json();
      const map = {};
      for (const item of json.data || []) if (item.symbol) map[item.symbol] = item;
      setPriceData(map);
      setApiStatus("live");
      setLastUpdate(new Date());
    } catch { setApiStatus("error"); }
  }, []);

  const fetchOhlcv = useCallback(async (symbol) => {
    if (ohlcv[symbol]) return;
    try {
      const r = await fetch(`${API_BASE}/market/ohlcv/${symbol}?interval=1h&limit=24`);
      const json = await r.json();
      setOhlcv(prev => ({ ...prev, [symbol]: json.data || [] }));
    } catch {}
  }, [ohlcv]);

  const fetchSupplementary = useCallback(async () => {
    try {
      const [fR, dR] = await Promise.allSettled([
        fetch(`${API_BASE}/mmi/sentiment/fear-greed?limit=7`).then(r => r.json()),
        fetch(`${API_BASE}/defi/overview`).then(r => r.json()),
      ]);
      if (fR.status === "fulfilled") setFng(fR.value);
      if (dR.status === "fulfilled") setDefi(dR.value);
    } catch {}
  }, []);

  const fetchAllOhlcv = useCallback(async () => {
    const symbols = TOKEN_UNIVERSE.map(t => t.symbol);
    for (let i = 0; i < symbols.length; i += 5) {
      const batch = symbols.slice(i, i + 5);
      await Promise.allSettled(batch.map(async (sym) => {
        try {
          const r = await fetch(`${API_BASE}/market/ohlcv/${sym}?interval=1h&limit=24`);
          const json = await r.json();
          if (json.data?.length) setOhlcv(prev => ({ ...prev, [sym]: json.data }));
        } catch {}
      }));
      await new Promise(res => setTimeout(res, 300));
    }
  }, []);

  useEffect(() => {
    const init = async () => {
      setLoading(true);
      await Promise.all([fetchPrices(), fetchSupplementary()]);
      setLoading(false);
      fetchAllOhlcv();
    };
    init();
  }, []);

  useEffect(() => {
    if (live) intervalRef.current = setInterval(fetchPrices, REFRESH_INTERVAL);
    else clearInterval(intervalRef.current);
    return () => clearInterval(intervalRef.current);
  }, [live, fetchPrices]);

  useEffect(() => {
    if (selectedToken) fetchOhlcv(selectedToken.symbol);
  }, [selectedToken]);

  const filtered = TOKEN_UNIVERSE.filter(t => category === "All" || t.category === category);

  const fngVal   = fng?.current?.value ?? null;
  const fngLabel = fng?.current?.label ?? "—";
  const fngColor = fngVal === null ? T.muted : fngVal >= 60 ? T.green : fngVal >= 40 ? T.amber : T.red;

  // Sorted for gainer/loser — only use actual data, not zero-padded
  const withData = TOKEN_UNIVERSE
    .map(t => ({ ...t, chg: priceData[t.symbol]?.change_24h ?? null }))
    .filter(t => t.chg !== null)
    .sort((a, b) => b.chg - a.chg);

  const topGainer = withData[0];
  const topLoser  = withData[withData.length - 1];

  /* ── Shared nav bar ── */
  const NavBar = () => (
    <div className="mobile-header" style={{
      display: "flex", alignItems: "center", justifyContent: "space-between",
      padding: "18px 0 20px",
      borderBottom: `1px solid ${T.border}`,
      flexWrap: "wrap",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
        <span onClick={() => setActiveTab("Home")}
          style={{
            fontFamily: FONTS.display, fontWeight: 700, fontSize: 20,
            letterSpacing: "-0.02em", color: T.primary, cursor: "pointer",
          }}>
          CometCloud
        </span>
        <div className="mobile-nav" style={{ display: "flex", gap: 4 }}>
          {["Home", "Market", "Intelligence", "CIS", "Vault", "Protocol", "Quant GP"].map(tab => (
            <button key={tab}
              onClick={() => setActiveTab(tab)}
              style={{
                padding: "8px 16px", borderRadius: 6, fontSize: 14, fontWeight: 500,
                fontFamily: FONTS.body, cursor: "pointer", outline: "none",
                border: "none",
                background: activeTab === tab ? T.cyan : "transparent",
                color: activeTab === tab ? "#fff" : T.secondary,
                transition: "all 0.2s ease",
              }}
            >
              {tab}
            </button>
          ))}
        </div>
      </div>

      <div className="mobile-nav-right" style={{ display: "flex", alignItems: "center", gap: 12 }}>
        {/* API status */}
        <div style={{
          display: "flex", alignItems: "center", gap: 6,
          fontSize: 11, fontFamily: FONTS.mono,
          color: apiStatus === "live" ? T.green : apiStatus === "error" ? T.red : T.amber,
        }}>
          <div className="pulse-dot" style={{
            width: 5, height: 5, borderRadius: "50%",
            background: apiStatus === "live" ? T.green : apiStatus === "error" ? T.red : T.amber,
          }} />
          {apiStatus.toUpperCase()}
        </div>

        {lastUpdate && (
          <span style={{ fontSize: 11, color: T.muted, fontFamily: FONTS.mono }}>
            {lastUpdate.toLocaleTimeString()}
          </span>
        )}

        <button className={`lm-action-btn${live ? " live-on" : ""}`} onClick={() => setLive(l => !l)}>
          {live ? <Wifi size={11} /> : <WifiOff size={11} />}
          {live ? "LIVE" : "PAUSED"}
        </button>

        <button className="lm-action-btn" onClick={() => { fetchPrices(); fetchSupplementary(); }}>
          <RefreshCw size={11} /> Refresh
        </button>
      </div>
    </div>
  );

  return (
    <div style={{ position: "relative", minHeight: "100vh", background: T.void }}>
      {/* Turrell ambient */}
      <div className="turrell-wrap">
        <div className="t-orb t-orb-1" />
        <div className="t-orb t-orb-2" />
        <div className="t-orb t-orb-3" />
        <div className="t-orb t-orb-4" />
      </div>

      <div className="mobile-pad" style={{ position: "relative", zIndex: 1, maxWidth: 1400, margin: "0 auto", padding: "0 28px 56px" }}>
        {!isSection && <NavBar />}

        {/* ── Stat cards ── */}
        <div className="mobile-stat-grid" style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 10, margin: "20px 0" }}>

          {/* Fear & Greed */}
          <div className="lm-card" style={{ padding: "18px 20px" }}>
            <div style={{ fontSize: 10, color: T.muted, letterSpacing: "0.11em", textTransform: "uppercase", fontFamily: FONTS.body, marginBottom: 10 }}>
              Fear & Greed
            </div>
            {fngVal !== null ? (
              <>
                <div style={{ display: "flex", alignItems: "baseline", gap: 9 }}>
                  <span style={{ fontSize: 32, fontWeight: 600, fontFamily: FONTS.mono, color: fngColor, lineHeight: 1 }}>
                    {fngVal}
                  </span>
                  <span style={{ fontSize: 12, color: fngColor, fontFamily: FONTS.body, fontWeight: 500 }}>{fngLabel}</span>
                </div>
                <div style={{ fontSize: 10, color: T.muted, fontFamily: FONTS.body, marginTop: 6 }}>Alternative.me · Daily</div>
              </>
            ) : <div className="sk" style={{ height: 32, width: 100, marginTop: 4 }} />}
          </div>

          {/* DeFi TVL */}
          <div className="lm-card" style={{ padding: "18px 20px" }}>
            <div style={{ fontSize: 10, color: T.muted, letterSpacing: "0.11em", textTransform: "uppercase", fontFamily: FONTS.body, marginBottom: 10 }}>
              DeFi TVL
            </div>
            {defi ? (
              <>
                <div style={{ fontSize: 32, fontWeight: 600, fontFamily: FONTS.mono, color: T.primary, lineHeight: 1 }}>
                  {defi.total_tvl_formatted}
                </div>
                <div style={{ fontSize: 10, color: T.muted, fontFamily: FONTS.body, marginTop: 6 }}>DeFiLlama · All chains</div>
              </>
            ) : <div className="sk" style={{ height: 32, width: 90, marginTop: 4 }} />}
          </div>

          {/* Top Gainer */}
          <div className="lm-card" style={{ padding: "18px 20px" }}>
            <div style={{ fontSize: 10, color: T.muted, letterSpacing: "0.11em", textTransform: "uppercase", fontFamily: FONTS.body, marginBottom: 10 }}>
              Top Gainer (24h)
            </div>
            {topGainer ? (
              <>
                <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
                  <span style={{ fontSize: 20, fontWeight: 700, fontFamily: FONTS.display, color: T.primary, letterSpacing: "-0.01em" }}>
                    {topGainer.symbol}
                  </span>
                  <span style={{ fontSize: 17, fontWeight: 500, fontFamily: FONTS.mono, color: T.green }}>
                    +{topGainer.chg.toFixed(2)}%
                  </span>
                </div>
                <div style={{ fontSize: 10, color: T.muted, fontFamily: FONTS.body, marginTop: 6 }}>{topGainer.name}</div>
              </>
            ) : <div className="sk" style={{ height: 32, width: 110, marginTop: 4 }} />}
          </div>

          {/* Top Loser */}
          <div className="lm-card" style={{ padding: "18px 20px" }}>
            <div style={{ fontSize: 10, color: T.muted, letterSpacing: "0.11em", textTransform: "uppercase", fontFamily: FONTS.body, marginBottom: 10 }}>
              Top Loser (24h)
            </div>
            {topLoser && topLoser.chg < 0 ? (
              <>
                <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
                  <span style={{ fontSize: 20, fontWeight: 700, fontFamily: FONTS.display, color: T.primary, letterSpacing: "-0.01em" }}>
                    {topLoser.symbol}
                  </span>
                  <span style={{ fontSize: 17, fontWeight: 500, fontFamily: FONTS.mono, color: T.red }}>
                    {topLoser.chg.toFixed(2)}%
                  </span>
                </div>
                <div style={{ fontSize: 10, color: T.muted, fontFamily: FONTS.body, marginTop: 6 }}>{topLoser.name}</div>
              </>
            ) : <div className="sk" style={{ height: 32, width: 110, marginTop: 4 }} />}
          </div>
        </div>

        {/* ── Category filter ── */}
        <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 14 }}>
          {CATEGORIES.map(cat => (
            <button key={cat}
              className={`cat-btn${category === cat ? " active" : ""}`}
              onClick={() => { setCategory(cat); setSelected(null); }}>
              {cat}
            </button>
          ))}
          <div style={{ marginLeft: "auto", fontSize: 11, color: T.muted, fontFamily: FONTS.mono }}>
            {filtered.length} assets · Binance
          </div>
        </div>

        {/* ── Token Table ── */}
        <div className="lm-card" style={{ overflow: "hidden" }}>
          {/* Table header */}
          <div className="mobile-table-header" style={{
            display: "grid", gridTemplateColumns: "2.2fr 1fr 1fr 1fr 80px",
            gap: 12, padding: "11px 20px",
            borderBottom: `1px solid ${T.border}`,
            fontSize: 10, color: T.muted, letterSpacing: "0.11em",
            textTransform: "uppercase", fontFamily: FONTS.body,
          }}>
            <span>Asset</span>
            <span style={{ textAlign: "right" }}>Price</span>
            <span style={{ textAlign: "right" }}>24h Change</span>
            <span style={{ textAlign: "right" }} className="mobile-hidden">Volume</span>
            <span style={{ textAlign: "right" }} className="mobile-7d-chart">7d Chart</span>
          </div>

          {/* Rows */}
          {loading
            ? Array(8).fill(0).map((_, i) => (
                <div key={i} className="mobile-table-grid" style={{
                  display: "grid", gridTemplateColumns: "2.2fr 1fr 1fr 1fr 80px",
                  gap: 12, padding: "13px 20px", borderBottom: `1px solid ${T.border}`,
                  alignItems: "center",
                }}>
                  {[130, 80, 70, 70, 72].map((w, j) => (
                    <div key={j} className="sk" style={{ height: 13, width: w, maxWidth: "100%" }} />
                  ))}
                </div>
              ))
            : filtered.map((token, i) => {
                const p = priceData[token.symbol];
                const positive = (p?.change_24h || 0) >= 0;
                const isSelected = selectedToken?.symbol === token.symbol;

                return (
                  <div key={token.symbol}>
                    <div className="lm-row mobile-table-grid"
                      onClick={() => setSelected(isSelected ? null : token)}
                      style={{
                        display: "grid", gridTemplateColumns: "2.2fr 1fr 1fr 1fr 80px",
                        gap: 12, padding: "13px 20px",
                        borderBottom: `1px solid ${T.border}`,
                        background: isSelected ? `rgba(68,114,255,.04)` : "transparent",
                        animation: `fadeUp 0.35s ease ${i * 0.03}s both`,
                        cursor: "pointer",
                      }}>

                      {/* Asset */}
                      <div style={{ display: "flex", alignItems: "center", gap: 11 }}>
                        <div style={{
                          width: 30, height: 30, borderRadius: "50%", flexShrink: 0,
                          background: `${token.color}15`,
                          border: `1px solid ${token.color}35`,
                          display: "flex", alignItems: "center", justifyContent: "center",
                          fontSize: 9, fontWeight: 700, color: token.color, fontFamily: FONTS.mono,
                        }}>
                          {token.symbol.slice(0, 2)}
                        </div>
                        <div>
                          <div style={{
                            fontSize: 14, fontWeight: 600, color: T.primary,
                            fontFamily: FONTS.display, letterSpacing: "-0.01em", lineHeight: 1.2,
                          }}>
                            {token.symbol}
                          </div>
                          <div style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 3 }}>
                            <span style={{ fontSize: 11, color: T.muted, fontFamily: FONTS.body }}>{token.name}</span>
                            <CatBadge cat={token.category} />
                          </div>
                        </div>
                      </div>

                      {/* Price */}
                      <div style={{ textAlign: "right", display: "flex", alignItems: "center", justifyContent: "flex-end" }}>
                        {p
                          ? <span style={{ fontSize: 13, fontWeight: 500, fontFamily: FONTS.mono, color: T.primary }}>{fmt.price(p.price)}</span>
                          : <div className="sk" style={{ height: 13, width: 70 }} />}
                      </div>

                      {/* Change */}
                      <div style={{ textAlign: "right", display: "flex", alignItems: "center", justifyContent: "flex-end" }}>
                        {p ? <ChangeCell v={p.change_24h} /> : <div className="sk" style={{ height: 13, width: 55 }} />}
                      </div>

                      {/* Volume */}
                      <div className="mobile-hidden" style={{ textAlign: "right", display: "flex", alignItems: "center", justifyContent: "flex-end" }}>
                        {p
                          ? <span style={{ fontSize: 11, color: T.secondary, fontFamily: FONTS.mono }}>{fmt.vol(p.volume_24h_usdt)}</span>
                          : <div className="sk" style={{ height: 13, width: 60 }} />}
                      </div>

                      {/* Chart */}
                      <div className="mobile-7d-chart" style={{ display: "flex", alignItems: "center", justifyContent: "flex-end" }}>
                        <Spark data={ohlcv[token.symbol]} positive={positive} />
                      </div>
                    </div>

                  </div>
                );
              })
          }
        </div>

        {/* ── DeFi Top Protocols ── */}
        {defi?.top_protocols?.length > 0 && (
          <div style={{ marginTop: 22 }}>
            <div style={{
              fontSize: 10, color: T.muted, letterSpacing: "0.11em",
              textTransform: "uppercase", fontFamily: FONTS.body,
              marginBottom: 12, display: "flex", alignItems: "center", gap: 7,
            }}>
              <Layers size={11} /> DeFiLlama · Top Protocols by TVL
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(190px, 1fr))", gap: 8 }}>
              {defi.top_protocols.slice(0, 8).map((p, i) => (
                <div key={p.name} className="lm-card" style={{
                  padding: "13px 16px",
                  animation: `fadeUp 0.3s ease ${i * 0.05}s both`,
                }}>
                  <div style={{ fontSize: 13, fontWeight: 600, color: T.primary, fontFamily: FONTS.display, letterSpacing: "-0.01em", marginBottom: 6 }}>
                    {p.name}
                  </div>
                  <div style={{ fontSize: 17, fontWeight: 600, color: T.blue, fontFamily: FONTS.mono, marginBottom: 8 }}>
                    {fmt.tvl(p.tvl)}
                  </div>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                    <span style={{ fontSize: 10, color: T.muted, fontFamily: FONTS.body }}>{p.category}</span>
                    {p.change_1d !== undefined && (
                      <span style={{ fontSize: 10, fontFamily: FONTS.mono, color: (p.change_1d || 0) >= 0 ? T.green : T.red }}>
                        {fmt.pct(p.change_1d)}
                      </span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* ── Footer ── */}
        <div style={{
          marginTop: 36, paddingTop: 16, borderTop: `1px solid ${T.border}`,
          display: "flex", justifyContent: "space-between", alignItems: "center",
        }}>
          <div style={{ fontSize: 10, color: T.muted, fontFamily: FONTS.mono }}>
            Data: Binance · DeFiLlama · Alternative.me · 30s refresh
          </div>
          <div style={{ fontSize: 10, color: T.dim, fontFamily: FONTS.body }}>
            CometCloud AI — Institutional RWA Intelligence
          </div>
        </div>
      </div>

      {/* Token Detail - BottomSheet */}
      <BottomSheet isOpen={!!selectedToken} onClose={() => setSelected(null)}>
        {selectedToken && (
          <TokenDetail token={selectedToken} priceData={priceData} ohlcv={ohlcv} onClose={() => setSelected(null)} />
        )}
      </BottomSheet>
    </div>
  );
}
