import { useState, useEffect, useCallback } from "react";
import {
  RefreshCw, ExternalLink, Zap, Building2,
  DollarSign, Globe, Activity, Users, Shield
} from "lucide-react";

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

const API_BASE = "/api/v1";

/* ─── CSS ────────────────────────────────────────────────────────────── */
const CSS = `
  @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600;700;800&family=Exo+2:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap');

  @keyframes breathe  { 0%,100%{opacity:.28;transform:scale(1) translateY(0)} 50%{opacity:.44;transform:scale(1.06) translateY(-12px)} }
  @keyframes breathe2 { 0%,100%{opacity:.16;transform:scale(1)} 50%{opacity:.30;transform:scale(1.08) translateX(10px)} }
  @keyframes fadeUp   { from{opacity:0;transform:translateY(14px)} to{opacity:1;transform:translateY(0)} }
  @keyframes slideIn  { from{opacity:0;transform:translateX(-8px)} to{opacity:1;transform:translateX(0)} }
  @keyframes pulse    { 0%,100%{opacity:1} 50%{opacity:.35} }
  @keyframes shimmer  { 0%{background-position:-400px 0} 100%{background-position:400px 0} }

  .fade-up  { animation: fadeUp  .4s cubic-bezier(.16,1,.3,1) forwards; }
  .slide-in { animation: slideIn .25s ease forwards; }

  .turrell-wrap { position:fixed;inset:0;pointer-events:none;z-index:0;overflow:hidden; }
  .t-orb { position:absolute;border-radius:50%;filter:blur(100px);mix-blend-mode:screen; }
  .t-orb-1 { width:720px;height:720px;background:radial-gradient(circle,rgba(107,15,204,.20) 0%,transparent 65%);top:-300px;left:-200px;animation:breathe 52s ease-in-out infinite; }
  .t-orb-2 { width:560px;height:560px;background:radial-gradient(circle,rgba(45,53,212,.15) 0%,transparent 65%);top:5%;right:-200px;animation:breathe2 64s ease-in-out infinite 9s; }
  .t-orb-3 { width:380px;height:380px;background:radial-gradient(circle,rgba(0,200,224,.09) 0%,transparent 65%);bottom:0;left:22%;animation:breathe 76s ease-in-out infinite 24s; }
  .t-orb-4 { width:280px;height:280px;background:radial-gradient(circle,rgba(255,16,96,.07) 0%,transparent 65%);bottom:12%;right:8%;animation:breathe2 60s ease-in-out infinite 38s; }

  .lm-card { background:rgba(10,9,24,.82);border:1px solid #1A173A;border-radius:10px;backdrop-filter:blur(20px);transition:border-color .2s ease; }
  .lm-card:hover { border-color:#28244C; }
  .lm-card-accent { border-left-width:2px !important; }

  .lm-row { transition:background .12s ease,transform .12s ease;cursor:pointer; }
  .lm-row:hover { background:rgba(68,114,255,.05) !important;transform:translateX(2px); }

  .lm-tab { padding:5px 14px;border-radius:5px;font-size:12px;font-weight:500;font-family:'Exo 2',sans-serif;cursor:pointer;outline:none;border:1px solid #1A173A;background:transparent;color:#8880BE;transition:all .18s ease;letter-spacing:.01em; }
  .lm-tab:hover { border-color:#28244C;color:#F0EEFF; }
  .lm-tab.active { border-color:rgba(68,114,255,.5);background:rgba(68,114,255,.10);color:#4472FF; }

  .filter-btn { padding:4px 10px;border-radius:4px;font-size:11px;font-weight:500;font-family:'Exo 2',sans-serif;cursor:pointer;outline:none;border:1px solid #1A173A;background:transparent;color:#3E3A6E;transition:all .15s ease; }
  .filter-btn:hover { border-color:#28244C;color:#8880BE; }
  .filter-btn.active { border-color:rgba(68,114,255,.4);background:rgba(68,114,255,.08);color:#4472FF; }

  .lm-action-btn { display:flex;align-items:center;gap:6px;padding:6px 12px;border-radius:6px;font-size:11px;font-weight:500;font-family:'Exo 2',sans-serif;cursor:pointer;outline:none;border:1px solid #1A173A;background:transparent;color:#8880BE;transition:all .18s ease; }
  .lm-action-btn:hover { border-color:#28244C;color:#F0EEFF; }

  .sk { background:linear-gradient(90deg,#100E22 30%,#16132E 50%,#100E22 70%);background-size:400px 100%;animation:shimmer 1.8s ease infinite;border-radius:4px;display:inline-block; }
  .pulse-dot { animation:pulse 2.2s ease-in-out infinite; }

  .iframe-wrap { position:relative;width:100%;height:calc(100vh - 88px);border-radius:10px;overflow:hidden;border:1px solid #1A173A; }
  .iframe-wrap iframe { width:100%;height:100%;border:none;background:white; }

  .lm-badge { display:inline-flex;align-items:center;padding:2px 7px;border-radius:3px;font-size:10px;font-weight:600;letter-spacing:.05em;text-transform:uppercase;font-family:'Exo 2',sans-serif; }

  /* Mobile responsive */
  @media (max-width: 768px) {
    .mobile-hidden { display: none !important; }
    .mobile-full { width: 100% !important; }
    .mobile-stack { flex-direction: column !important; }
    .mobile-pad { padding: 0 12px !important; }
    .mobile-stat-grid { grid-template-columns: 1fr 1fr !important; }
    .mobile-table-header { grid-template-columns: 1.8fr 1fr 1fr !important; }
    .mobile-table-row { grid-template-columns: 1.8fr 1fr 1fr !important; }
    .mobile-nav { flex-wrap: wrap !important; gap: 6px !important; }
    .mobile-nav-right { margin-top: 10px !important; width: 100% !important; justify-content: space-between !important; }
    .mobile-card-pad { padding: 12px 14px !important; }
    .mobile-header { padding: 12px 0 14px !important; }
    .mobile-footer { flex-direction: column !important; gap: 8px !important; text-align: center !important; }
    .mobile-howitworks-grid { grid-template-columns: 1fr 1fr !important; }
    .mobile-2col-grid { grid-template-columns: 1fr !important; }
    .mobile-hero { padding: 24px 20px !important; }
    .mobile-hero h1 { font-size: 28px !important; }
    .mobile-metrics { gap: 24px !important; }
    .mobile-pipeline-grid { grid-template-columns: 1fr !important; }
    .mobile-funds-scroll { flex-direction: column !important; }
  }
`;

/* ─── Helpers ────────────────────────────────────────────────────────── */
const fmt = {
  amount: (v) => {
    if (!v && v !== 0) return "—";
    if (v >= 1000) return `$${(v / 1000).toFixed(1)}B`;
    if (v >= 1)    return `$${v.toFixed(1)}M`;
    return `$${v.toFixed(2)}M`;
  },
  dateRelative: (ts) => {
    if (!ts) return "—";
    const now = Date.now() / 1000;
    const diff = now - ts;
    if (diff < 3600)    return `${Math.floor(diff / 60)}m ago`;
    if (diff < 86400)   return `${Math.floor(diff / 3600)}h ago`;
    if (diff < 604800)  return `${Math.floor(diff / 86400)}d ago`;
    if (diff < 2592000) return `${Math.floor(diff / 604800)}w ago`;
    const d = new Date(ts * 1000);
    return d.toLocaleDateString("en-US", { month: "short", year: "numeric" });
  },
};

/* ─── RWA Keywords ───────────────────────────────────────────────────── */
const RWA_KW = ["rwa", "real world asset", "tokeniz", "treasury", "bond", "credit",
  "lending", "ondo", "maple", "centrifuge", "goldfinch", "backed", "superstate",
  "securitize", "polymesh", "chainlink", "oracle"];

const isRWA = (item) => {
  const txt = `${item.name||""} ${item.sector||""} ${item.category||""} ${item.categoryGroup||""}`.toLowerCase();
  return RWA_KW.some(kw => txt.includes(kw));
};

/* ─── Category colors ────────────────────────────────────────────────── */
const CAT_C = {
  "RWA":            { bg: "rgba(232,160,0,.12)",  text: "#E8A000" },
  "DeFi":           { bg: "rgba(68,114,255,.12)", text: "#4472FF" },
  "AI":             { bg: "rgba(255,16,96,.10)",  text: "#FF1060" },
  "Infrastructure": { bg: "rgba(0,217,138,.10)",  text: "#00D98A" },
  "Layer 1":        { bg: "rgba(0,200,224,.08)",  text: "#00C8E0" },
  "Layer 2":        { bg: "rgba(107,15,204,.10)", text: "#9945FF" },
  "ZK":             { bg: "rgba(68,114,255,.08)", text: "#7B9FFF" },
};
const catStyle = (c) => CAT_C[c] || { bg: "rgba(255,255,255,.05)", text: "#8880BE" };

/* ─── Curated macro events (updated Mar 2026) ────────────────────────── */
const MACRO_EVENTS = [
  { id: "sol-eth", date: "Feb 2026", title: "Solana Establishes $500M ETH Ecosystem Fund", summary: "Solana Foundation commits major capital to bridge Ethereum L2 ecosystems, validating cross-chain infrastructure.", type: "institutional", impact: "high", source: "Solana Foundation" },
  { id: "ubs-rwa", date: "Jan 2026", title: "UBS Launches Tokenized Money Market Fund", summary: "Major Swiss bank enters RWA market with tokenized CHF and USD money market instruments.", type: "institutional", impact: "high", source: "UBS" },
  { id: "hsbc-token", date: "Dec 2025", title: "HSBC Tokenizes $2B Real Estate on Polygon", summary: "Largest tokenized real estate deployment by a traditional bank, signaling institutional adoption.", type: "institutional", impact: "high", source: "HSBC" },
  { id: "hk-eth", date: "Nov 2025", title: "Hong Kong Legalizes ETH as Recognized Asset", summary: "SFC ruling classifies ETH as property, enabling regulated ETH funds for retail investors.", type: "regulatory", impact: "high", source: "HK SFC" },
  { id: "us-senate", date: "Oct 2025", title: "US Senate Passes Stablecoin Regulation Act", summary: "Comprehensive stablecoin framework establishes clear rules for issuance and reserves.", type: "regulatory", impact: "high", source: "US Senate" },
  { id: "sec-eth", date: "Sep 2025", title: "SEC Approves Ethereum ETF Options Trading", summary: "Options on ETH ETFs cleared for trading, expanding institutional access to Ethereum.", type: "regulatory", impact: "high", source: "SEC" },
];

/* ─── Curated RWA Projects (Mar 2026) ────────────────────────────────── */
const RWA_PROJECTS = [
  // Tokenized Treasuries / RWA
  { id: "ondo", name: "Ondo Finance", category: "RWA - Treasuries", tvl: 2063553096, apy: 4.8, description: "Tokenized US Treasuries (OUSG, OMMF)", chain: "Multi-chain", investors: ["Founders Fund", "Coinbase Ventures"] },
  { id: "blackrock", name: "BlackRock BUIDL", category: "RWA - Treasuries", tvl: 2531565611, apy: 4.3, description: "Tokenized Money Market Fund", chain: "Multi-chain", investors: ["BlackRock"] },
  { id: "circle-usyc", name: "Circle USYC", category: "RWA - Treasuries", tvl: 1902157261, apy: 4.5, description: "US Treasury-backed yield", chain: "Multi-chain", investors: ["Circle", "Goldman Sachs"] },
  { id: "franklin", name: "Franklin Templeton", category: "RWA - Treasuries", tvl: 380000000, apy: 4.5, description: "BENJI - On-chain US Treasury Fund", chain: "Polygon", investors: ["Franklin Templeton"] },
  { id: "wisdomtree", name: "WisdomTree", category: "RWA - Treasuries", tvl: 741361216, apy: 4.2, description: "Tokenized treasury and commodities", chain: "Multi-chain", investors: ["WisdomTree"] },
  { id: "superstate", name: "Superstate", category: "RWA - Treasuries", tvl: 701873051, apy: 4.6, description: "USTB - US Treasury Short Fund", chain: "Ethereum", investors: ["Coinbase", "SIX Group"] },
  { id: "anemoy", name: "Anemoy Capital", category: "RWA - Treasuries", tvl: 568081855, apy: 5.2, description: "Treasury Bill protocol", chain: "Multi-chain", investors: ["a16z", "Dragonfly"] },

  // Stablecoins
  { id: "circle", name: "Circle (USDC)", category: "RWA - Stablecoin", tvl: 76000000000, apy: 0, description: "Regulated stablecoin", chain: "Multi-chain", investors: ["Goldman Sachs", "Accel", "IDG"] },
  { id: "tether", name: "Tether (USDT)", category: "RWA - Stablecoin", tvl: 142000000000, apy: 0, description: "Largest stablecoin by volume", chain: "Multi-chain", investors: ["Tether Holdings"] },
  { id: "paxos", name: "Paxos (USDP)", category: "RWA - Stablecoin", tvl: 1200000000, apy: 0, description: "Regulated stablecoin", chain: "Ethereum", investors: ["PayPal", "SEC"] },

  // Commodities (Gold)
  { id: "paxos-gold", name: "Paxos Gold (PAXG)", category: "RWA - Commodities", tvl: 2496506164, apy: 0, description: "Gold-backed token", chain: "Ethereum", investors: ["NYDFS", "Chainalysis"] },
  { id: "tether-gold", name: "Tether Gold (XAU₮)", category: "RWA - Commodities", tvl: 3633721936, apy: 0, description: "Gold-backed token", chain: "Multi-chain", investors: ["Tether"] },
  { id: "treasury-gold", name: "Trove Gold", category: "RWA - Commodities", tvl: 120000000, apy: 2.1, description: "Gold-backed tokens", chain: "Ethereum", investors: ["SIX Group"] },

  // Real Estate
  { id: "realty", name: "Realty DAO", category: "RWA - Real Estate", tvl: 85000000, apy: 12.5, description: "Fractional real estate ownership", chain: "Solana", investors: ["Republic", "Animoca Brands"] },
  { id: "tangible", name: "Tangible", category: "RWA - Real Estate", tvl: 42000000, apy: 8.2, description: "Tokenized real world assets", chain: "Ethereum", investors: ["SIX Group"] },
  { id: "implied", name: "Implied Finance", category: "RWA - Real Estate", tvl: 18000000, apy: 15.0, description: "Real estate debt protocol", chain: "Ethereum", investors: ["Dragonfly"] },
  { id: "hastra", name: "Hastra", category: "RWA - Real Estate", tvl: 330521150, apy: 8.5, description: "Real estate protocol", chain: "Solana", investors: ["Solana Ventures"] },

  // Private Credit
  { id: "maple", name: "Maple Finance", category: "RWA - Private Credit", tvl: 1970282076, apy: 12.0, description: "Unsecured lending for institutional", chain: "Multi-chain", investors: ["Polychain", "Galaxy", "Apple"] },
  { id: "centrifuge", name: "Centrifuge", category: "RWA - Private Credit", tvl: 1361042384, apy: 9.5, description: "Asset financing protocol", chain: "Multi-chain", investors: ["a16z", "Polychain"] },
  { id: "credix", name: "Credix", category: "RWA - Private Credit", tvl: 95000000, apy: 14.0, description: "Credit marketplace for EM", chain: "Solana", investors: ["Greylock", "Variant"] },
  { id: "aave-horizon", name: "Aave Horizon RWA", category: "RWA - Private Credit", tvl: 338389101, apy: 8.5, description: "Institutional lending", chain: "Ethereum", investors: ["Aave"] },

  // Derivatives
  { id: "dydx", name: "dYdX", category: "Derivatives", tvl: 1200000000, apy: 0, description: "Decentralized perpetual futures", chain: "Cosmos", investors: ["a16z", "Polychain", "Three Arrows"] },
  { id: "gmx", name: "GMX", category: "Derivatives", tvl: 680000000, apy: 0, description: "Decentralized perpetual trading", chain: "Arbitrum", investors: ["Framework", "GSR"] },
  { id: "drift", name: "Drift Protocol", category: "Derivatives", tvl: 338112171, apy: 0, description: "Solana perpetual DEX", chain: "Solana", investors: ["Paradigm", "Jump"] },
  { id: "hyperliquid", name: "Hyperliquid", category: "Derivatives", tvl: 4147634073, apy: 0, description: "High-performance perps", chain: "Hyperliquid", investors: ["a16z", "DTN"] },

  // Infrastructure / Oracle
  { id: "chainlink", name: "Chainlink", category: "Infrastructure", tvl: 0, apy: 0, description: "Cross-chain data infrastructure", chain: "Multi-chain", investors: ["a16z", "SoftBank", "Winklevoss"] },
  { id: "pyth", name: "Pyth", category: "Infrastructure", tvl: 0, apy: 0, description: "Oracle for financial data", chain: "Solana", investors: ["a16z", "Jump", "Deliver"] },
];

/* ─── Curated Active VCs (Mar 2026) ──────────────────────────────────── */
const ACTIVE_VCS = [
  { name: "a16z crypto", deals: 145, portfolio: ["Lido", "Arbitrum", "Coinbase", "Anthropic", "Base"], focus: "Infrastructure" },
  { name: "Paradigm", deals: 89, portfolio: ["Uniswap", "dYdX", "Flashbots", "Fantom", "Scroll"], focus: "DeFi" },
  { name: "Polychain", deals: 156, portfolio: ["Compound", "Maple", "Centrifuge", "EigenLayer", "Arbitrum"], focus: "DeFi/RWA" },
  { name: "Dragonfly", deals: 78, portfolio: ["MakerDAO", "Near", "Mystiko", "Celestia", "Eclipse"], focus: "Multi-chain" },
  { name: "Pantera", deals: 210, portfolio: ["Solana", "Circle", "Bitwise", "Avax", "Chainlink"], focus: "Infrastructure" },
  { name: "Coinbase Ventures", deals: 420, portfolio: ["OpenSea", "Ethereum", "Optimism", "Base", "Ondo"], focus: "Ecosystem" },
  { name: "Binance Labs", deals: 180, portfolio: ["Polygon", "Injective", "Celestia", "Sei", "Ton"], focus: "Infrastructure" },
  { name: "Solana Ventures", deals: 95, portfolio: ["Jupiter", "Marginfi", "Kamino", "Drift", "Meteora"], focus: "Solana" },
  { name: "Framework Ventures", deals: 85, portfolio: ["GMX", "Synthetix", "永续"], focus: "DeFi" },
  { name: "Hack VC", deals: 95, portfolio: ["EigenLayer", "Lido", "Ritual", "Hyperliquid"], focus: "Infrastructure" },
  { name: "Electric Capital", deals: 65, portfolio: ["Near", "Aptos", "Sui", "Circle"], focus: "Layer 1" },
  { name: "Variant Fund", deals: 45, portfolio: ["Uniswap", "Aave", "MakerDAO", "PoolTogether"], focus: "DeFi" },
];

const EV_TYPE = {
  institutional: { color: T.amber,  label: "Institutional",  Icon: Building2 },
  regulatory:    { color: T.blue,   label: "Regulatory",     Icon: Globe },
  protocol:      { color: T.green,  label: "Protocol",       Icon: Zap },
  infrastructure:{ color: "#9945FF",label: "Infrastructure", Icon: Activity },
};

const IMP_C = {
  high:   { bg: "rgba(255,45,85,.10)", text: "#FF2D55" },
  medium: { bg: "rgba(232,160,0,.10)", text: "#E8A000" },
  low:    { bg: "rgba(0,217,138,.08)", text: "#00D98A" },
};

/* ═══════════════════════════════════════════════════════════════════════
   INTELLIGENCE + QUANT GP PAGE
═══════════════════════════════════════════════════════════════════════ */
export default function IntelligencePage({ activeTab, setActiveTab }) {
  const [raises, setRaises]             = useState([]);
  const [rwaRaises, setRwaRaises]       = useState([]);
  const [loading, setLoading]           = useState(true);
  const [raisesFilter, setRaisesFilter] = useState("RWA");
  const [lastUpdate, setLastUpdate]     = useState(null);
  const [stats, setStats]               = useState(null);
  const [showUpdateDrawer, setShowUpdateDrawer] = useState(false);
  const [iframeError, setIframeError]   = useState(false);

  useEffect(() => {
    const id = "lm-intel-css";
    if (!document.getElementById(id)) {
      const s = document.createElement("style");
      s.id = id; s.textContent = CSS;
      document.head.appendChild(s);
    }
  }, []);

  const fetchRaises = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetch(`${API_BASE}/vc/funding-rounds?limit=100`);
      const json = await r.json();
      const raw = json.data || [];

      /* ── Normalize backend fields with comprehensive fallback ── */
      const all = raw.map(item => {
        // Backend returns amount in USD, convert to millions
        const amount = typeof item.amount === "number" ? item.amount / 1e6
          : parseFloat(item.amount_usd || 0) / 1e6;

        // Handle date - backend returns string "YYYY-MM-DD" or timestamp
        let date = null;
        if (item.date) {
          if (typeof item.date === "number") {
            date = item.date; // Already timestamp
          } else if (typeof item.date === "string") {
            // Try to parse string date, fallback to current time
            const parsed = Date.parse(item.date);
            date = isNaN(parsed) ? Date.now() / 1000 : Math.floor(parsed / 1000);
          }
        }

        return {
          name: item.project || item.name || item.protocol || "—",
          round: item.round_type || item.round || item.stage || "—",
          amount,
          date,
          leadInvestors: Array.isArray(item.investors) ? item.investors
            : Array.isArray(item.leadInvestors) ? item.leadInvestors
            : [],
          category: item.category || item.sector || "—",
          categoryGroup: item.categoryGroup || item.category || "—",
          sector: item.sector || item.category || "—",
          chains: item.chains || [],
        };
      });

      all.sort((a, b) => (b.date || 0) - (a.date || 0));

      // Broader filter: RWA + DeFi + Infrastructure
      const isSector = (item) => {
        const cat = (item.category || "").toLowerCase();
        return isRWA(item) || cat.includes("defi") || cat.includes("infrastructure") || cat.includes("l1") || cat.includes("l2");
      };
      const sector = all.filter(isSector);
      setRaises(all);
      setRwaRaises(sector);
      setLastUpdate(new Date());

      // Stats — 90d window
      const now90 = Date.now() / 1000 - 90 * 86400;
      const recent    = all.filter(r => r.date && r.date > now90);
      const recentRwa = sector.filter(r => r.date && r.date > now90);

      const vcMap = {};
      recent.forEach(r => {
        r.leadInvestors.forEach(v => { vcMap[v] = (vcMap[v] || 0) + 1; });
      });
      const topVC = Object.entries(vcMap).sort((a, b) => b[1] - a[1])[0];

      setStats({
        totalDeals:  recent.length,
        totalAmount: recent.reduce((s, r) => s + (r.amount || 0), 0),
        rwaAmount:   recentRwa.reduce((s, r) => s + (r.amount || 0), 0),
        rwaDeals:    recentRwa.length,
        topVC:       topVC ? topVC[0] : "—",
        topVCDeals:  topVC ? topVC[1] : 0,
      });
    } catch (e) {
      console.error("Raises fetch error:", e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchRaises(); }, []);

  const FILTERS = ["All", "RWA", "DeFi", "AI", "Infrastructure"];

  const filtered = raises.filter(r => {
    // Default: only show RWA/DeFi/Infrastructure with amount > $1M
    if (raisesFilter === "All") {
      return (isRWA(r) || (r.category || "").toLowerCase().includes("defi") || (r.category || "").toLowerCase().includes("infrastructure")) && r.amount >= 1;
    }
    if (raisesFilter === "RWA") return isRWA(r) && r.amount >= 1;
    return ((r.category || "").toLowerCase().includes(raisesFilter.toLowerCase()) || (r.categoryGroup || "").toLowerCase().includes(raisesFilter.toLowerCase())) && r.amount >= 1;
  });

  /* ── Shared nav ── */
  const NavBar = () => (
    <div style={{
      display: "flex", alignItems: "center", justifyContent: "space-between",
      padding: "18px 0 20px", borderBottom: `1px solid ${T.border}`,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
        <span style={{
          fontFamily: FONTS.display, fontWeight: 800, fontSize: 20,
          letterSpacing: "-0.03em",
          background: `linear-gradient(120deg,${T.pink} 0%,${T.violet} 45%,${T.blue} 100%)`,
          WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent",
        }}>
          LOOLOOMI
        </span>
        <div style={{ display: "flex", gap: 4 }}>
          {["Market", "Intelligence", "CIS", "Vault", "Protocol", "Quant GP"].map(tab => (
            <button key={tab} className={`lm-tab${activeTab === tab ? " active" : ""}`}
              onClick={() => setActiveTab(tab)}>
              {tab}
            </button>
          ))}
        </div>
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        {lastUpdate && (
          <span style={{ fontSize: 11, color: T.muted, fontFamily: FONTS.mono }}>
            {lastUpdate.toLocaleTimeString()}
          </span>
        )}
        <button className="lm-action-btn" onClick={fetchRaises}>
          <RefreshCw size={11} /> Refresh
        </button>
      </div>
    </div>
  );

  /* ── Section label ── */
  const Label = ({ Icon, children }) => (
    <div style={{
      fontSize: 10, color: T.muted, letterSpacing: "0.11em",
      textTransform: "uppercase", fontFamily: FONTS.body,
      display: "flex", alignItems: "center", gap: 7, marginBottom: 12,
    }}>
      {Icon && <Icon size={11} />}
      {children}
    </div>
  );

  return (
    <div style={{ position: "relative", minHeight: "100vh", background: T.void }}>
      <div className="turrell-wrap">
        <div className="t-orb t-orb-1" /><div className="t-orb t-orb-2" />
        <div className="t-orb t-orb-3" /><div className="t-orb t-orb-4" />
      </div>

      <div style={{ position: "relative", zIndex: 1, maxWidth: 1400, margin: "0 auto", padding: "0 28px 56px" }}>
        <NavBar />

        {/* ══ INTELLIGENCE TAB ══════════════════════════════════════════════ */}
        {activeTab === "Intelligence" && (
          <div>
            {/* Stat cards */}
            <div className="mobile-stat-grid" style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 10, margin: "20px 0" }}>
              {[
                { label: "90d Total Raised", value: stats ? fmt.amount(stats.totalAmount) : null, sub: `${stats?.totalDeals ?? "—"} deals`, color: T.blue },
                { label: "RWA Sector (90d)",  value: stats ? fmt.amount(stats.rwaAmount)  : null, sub: `${stats?.rwaDeals ?? "—"} RWA deals`, color: T.amber },
                { label: "Most Active VC",    value: stats?.topVC ?? null,                         sub: `${stats?.topVCDeals ?? "—"} deals`, color: T.green },
                { label: "Data Source",       value: "DeFiLlama",                                  sub: "Raises API · Live", color: T.pink },
              ].map((s, i) => (
                <div key={i} className="lm-card" style={{ padding: "18px 20px", animation: `fadeUp .3s ease ${i*.08}s both` }}>
                  <div style={{ fontSize: 10, color: T.muted, letterSpacing: "0.11em", textTransform: "uppercase", fontFamily: FONTS.body, marginBottom: 10 }}>
                    {s.label}
                  </div>
                  {s.value !== null
                    ? <div style={{ fontSize: 24, fontWeight: 600, color: s.color, fontFamily: FONTS.mono, lineHeight: 1, marginBottom: 6 }}>{s.value}</div>
                    : <div className="sk" style={{ height: 24, width: 90, marginBottom: 6 }} />
                  }
                  <div style={{ fontSize: 11, color: T.muted, fontFamily: FONTS.body }}>{s.sub}</div>
                </div>
              ))}
            </div>

            {/* RWA Projects Section */}
            <div style={{ marginBottom: 24 }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
                <Label Icon={Shield}>RWA Project Tracker</Label>
                <span style={{ fontSize: 10, color: T.muted, fontFamily: FONTS.mono }}>
                  {RWA_PROJECTS.length} protocols tracked
                </span>
              </div>
              <div className="lm-card" style={{ overflow: "hidden" }}>
                <div style={{
                  display: "grid", gridTemplateColumns: "1.5fr 1fr 1fr 1fr 1.5fr",
                  padding: "12px 20px", borderBottom: `1px solid ${T.border}`,
                  fontSize: 10, color: T.muted, letterSpacing: "0.1em", textTransform: "uppercase",
                  fontFamily: FONTS.body
                }}>
                  <div>Protocol</div>
                  <div>Category</div>
                  <div>TVL</div>
                  <div>APY</div>
                  <div>Chain</div>
                </div>
                {RWA_PROJECTS.slice(0, 12).map((p, idx) => (
                  <div key={p.id} className="lm-row" style={{
                    display: "grid", gridTemplateColumns: "1.5fr 1fr 1fr 1fr 1.5fr",
                    padding: "14px 20px", borderBottom: `1px solid ${T.border}`,
                    alignItems: "center",
                  }}>
                    <div>
                      <div style={{ fontFamily: FONTS.display, fontWeight: 600, color: T.primary, fontSize: 13 }}>
                        {p.name}
                      </div>
                      <div style={{ fontSize: 10, color: T.secondary, marginTop: 2 }}>
                        {p.description}
                      </div>
                    </div>
                    <div>
                      <span style={{
                        padding: "3px 8px", borderRadius: 4, fontSize: 10, fontWeight: 500,
                        background: catStyle(p.category).bg, color: catStyle(p.category).text,
                      }}>
                        {p.category}
                      </span>
                    </div>
                    <div style={{ fontFamily: FONTS.mono, fontSize: 13, color: T.green }}>
                      {p.tvl >= 1e9 ? `$${(p.tvl/1e9).toFixed(1)}B` : p.tvl >= 1e6 ? `$${(p.tvl/1e6).toFixed(0)}M` : `$${(p.tvl/1e3).toFixed(0)}K`}
                    </div>
                    <div style={{ fontFamily: FONTS.mono, fontSize: 13, color: p.apy > 0 ? T.green : T.muted }}>
                      {p.apy > 0 ? `${p.apy}%` : "—"}
                    </div>
                    <div style={{ fontSize: 11, color: T.secondary }}>
                      {p.chain}
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Main 2-col layout */}
            <div className="mobile-2col-grid" style={{ display: "grid", gridTemplateColumns: "1fr 360px", gap: 16 }}>

              {/* Left — VC Funding Table */}
              <div>
                {/* Update Drawer */}
                <div style={{ marginBottom: 12 }}>
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      <Label Icon={DollarSign}>VC Funding Rounds</Label>
                      {lastUpdate && (
                        <span style={{ fontSize: 10, color: T.muted, fontFamily: FONTS.mono }}>
                          Updated: {lastUpdate.toLocaleTimeString()}
                        </span>
                      )}
                    </div>
                    <button
                      className="lm-action-btn"
                      onClick={() => setShowUpdateDrawer(!showUpdateDrawer)}
                      style={{ fontSize: 10 }}
                    >
                      {showUpdateDrawer ? "▲" : "▼"} Data Source
                    </button>
                  </div>

                  {showUpdateDrawer && (
                    <div className="lm-card" style={{
                      padding: 14, borderLeft: `2px solid ${T.amber}`,
                      marginBottom: 12, animation: "fadeUp .2s ease"
                    }}>
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 10 }}>
                        <div>
                          <div style={{ fontSize: 11, fontWeight: 600, color: T.primary, fontFamily: FONTS.display, marginBottom: 4 }}>
                            Data Source Information
                          </div>
                          <div style={{ fontSize: 11, color: T.secondary, fontFamily: FONTS.body, lineHeight: 1.5 }}>
                            Source: DeFiLlama / CryptoRank API · Real-time funding round data
                          </div>
                          <div style={{ fontSize: 10, color: T.muted, fontFamily: FONTS.body, marginTop: 6 }}>
                            Coverage: Global crypto VC funding rounds · RWA/DeFi/Infrastructure focus
                          </div>
                        </div>
                        <button className="lm-action-btn" onClick={fetchRaises} style={{ borderColor: `${T.amber}40` }}>
                          <RefreshCw size={10} /> Refresh
                        </button>
                      </div>
                      <div style={{ fontSize: 10, color: T.muted, fontFamily: FONTS.body }}>
                        Default filter: RWA/DeFi/Infrastructure · Amount &gt; $1M · Sorted by date
                      </div>
                    </div>
                  )}
                </div>

                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
                  <div style={{ display: "flex", gap: 5 }}>
                    {FILTERS.map(f => (
                      <button key={f} className={`filter-btn${raisesFilter === f ? " active" : ""}`}
                        onClick={() => setRaisesFilter(f)}>
                        {f}
                      </button>
                    ))}
                  </div>
                </div>

                <div className="lm-card" style={{ overflow: "hidden" }}>
                  {/* Header */}
                  <div style={{
                    display: "grid", gridTemplateColumns: "2fr 90px 100px 130px 80px",
                    gap: 12, padding: "10px 18px", borderBottom: `1px solid ${T.border}`,
                    fontSize: 10, color: T.muted, letterSpacing: "0.11em",
                    textTransform: "uppercase", fontFamily: FONTS.body,
                  }}>
                    <span>Project</span>
                    <span>Round</span>
                    <span style={{ textAlign: "right" }}>Amount</span>
                    <span>Lead Investor</span>
                    <span style={{ textAlign: "right" }}>Date</span>
                  </div>

                  {/* Rows */}
                  <div style={{ maxHeight: 530, overflowY: "auto" }}>
                    {loading
                      ? Array(8).fill(0).map((_, i) => (
                          <div key={i} style={{
                            display: "grid", gridTemplateColumns: "2fr 90px 100px 130px 80px",
                            gap: 12, padding: "12px 18px", borderBottom: `1px solid ${T.border}`,
                            alignItems: "center",
                          }}>
                            {[120, 60, 60, 90, 55].map((w, j) => (
                              <div key={j} className="sk" style={{ height: 12, width: w }} />
                            ))}
                          </div>
                        ))
                      : filtered.slice(0, 60).map((r, i) => {
                          const cs = catStyle(r.category);
                          const lead = r.leadInvestors?.[0] || "—";
                          const rwaTag = isRWA(r);
                          return (
                            <div key={i} className="lm-row"
                              style={{
                                display: "grid",
                                gridTemplateColumns: "2fr 90px 100px 130px 80px",
                                gap: 12, padding: "12px 18px",
                                borderBottom: `1px solid ${T.border}`,
                                alignItems: "center",
                                background: rwaTag ? "rgba(232,160,0,.018)" : "transparent",
                                animation: `slideIn .2s ease ${Math.min(i*.02,.3)}s both`,
                              }}>

                              {/* Project */}
                              <div>
                                <div style={{ display: "flex", alignItems: "center", gap: 7, marginBottom: 2 }}>
                                  <span style={{ fontSize: 13, fontWeight: 600, color: T.primary, fontFamily: FONTS.display, letterSpacing: "-0.01em" }}>
                                    {r.name}
                                  </span>
                                  {rwaTag && (
                                    <span className="lm-badge" style={{ background: "rgba(232,160,0,.12)", color: T.amber }}>
                                      RWA
                                    </span>
                                  )}
                                </div>
                                <div style={{ fontSize: 10, color: T.muted, fontFamily: FONTS.body,
                                  maxWidth: 220, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                                  {r.sector !== "—" ? r.sector : r.category}
                                </div>
                              </div>

                              {/* Round */}
                              <div>
                                <span className="lm-badge" style={{ background: cs.bg, color: cs.text }}>
                                  {r.round || "—"}
                                </span>
                              </div>

                              {/* Amount */}
                              <div style={{ textAlign: "right" }}>
                                <span style={{ fontSize: 13, fontWeight: 600, fontFamily: FONTS.mono, color: r.amount ? T.green : T.muted }}>
                                  {r.amount ? fmt.amount(r.amount) : "Undisclosed"}
                                </span>
                              </div>

                              {/* Lead */}
                              <div style={{ fontSize: 11, color: T.secondary, fontFamily: FONTS.body,
                                overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                                {lead}
                              </div>

                              {/* Date */}
                              <div style={{ textAlign: "right", fontSize: 11, color: T.muted, fontFamily: FONTS.mono }}>
                                {fmt.dateRelative(r.date)}
                              </div>
                            </div>
                          );
                        })
                    }
                  </div>
                </div>
              </div>

              {/* Right sidebar — RWA Events */}
              <div>
                <Label Icon={Zap}>RWA Infrastructure Events</Label>
                <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>

                  {/* Live RWA raises from API */}
                  {!loading && rwaRaises.slice(0, 3).map((r, i) => (
                    <div key={i} className="lm-card" style={{
                      padding: 14, borderLeft: `2px solid ${T.amber}`,
                      animation: `fadeUp .3s ease ${i*.07}s both`,
                    }}>
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
                        <span className="lm-badge" style={{ background: "rgba(232,160,0,.12)", color: T.amber }}>RWA Funding</span>
                        <span style={{ fontSize: 10, color: T.muted, fontFamily: FONTS.mono }}>{fmt.dateRelative(r.date)}</span>
                      </div>
                      <div style={{ fontSize: 13, fontWeight: 600, color: T.primary, fontFamily: FONTS.display, letterSpacing: "-0.01em", marginBottom: 5 }}>
                        {r.name}
                        <span style={{ fontSize: 11, fontWeight: 400, color: T.muted, fontFamily: FONTS.body, marginLeft: 6 }}>
                          {r.round}
                        </span>
                      </div>
                      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <span style={{ fontSize: 15, fontWeight: 600, color: T.green, fontFamily: FONTS.mono }}>
                          {r.amount ? fmt.amount(r.amount) : "Undisclosed"}
                        </span>
                        {r.leadInvestors?.[0] && (
                          <span style={{ fontSize: 10, color: T.muted, fontFamily: FONTS.body }}>
                            led by {r.leadInvestors[0]}
                          </span>
                        )}
                      </div>
                    </div>
                  ))}

                  {/* Divider */}
                  <div style={{ fontSize: 10, color: T.muted, letterSpacing: "0.11em", textTransform: "uppercase",
                    fontFamily: FONTS.body, padding: "4px 0", display: "flex", alignItems: "center", gap: 7 }}>
                    <Globe size={10} /> Macro Events
                  </div>

                  {/* Divider */}
                  <div style={{ fontSize: 10, color: T.muted, letterSpacing: "0.11em", textTransform: "uppercase",
                    fontFamily: FONTS.body, padding: "4px 0", display: "flex", alignItems: "center", gap: 7, marginTop: 16 }}>
                    <Users size={10} /> Active VCs
                  </div>

                  {/* Curated Active VCs */}
                  {ACTIVE_VCS.slice(0, 6).map((vc, i) => (
                    <div key={vc.name} className="lm-card" style={{
                      padding: 12, marginBottom: 8, animation: `fadeUp .3s ease ${(i+5)*.07}s both`,
                    }}>
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
                        <span style={{ fontFamily: FONTS.display, fontWeight: 600, color: T.primary, fontSize: 12 }}>
                          {vc.name}
                        </span>
                        <span style={{ fontFamily: FONTS.mono, fontSize: 10, color: T.green }}>
                          {vc.deals} deals
                        </span>
                      </div>
                      <div style={{ fontSize: 10, color: T.amber, marginBottom: 4 }}>
                        Focus: {vc.focus}
                      </div>
                      <div style={{ fontSize: 10, color: T.secondary }}>
                        {vc.portfolio.slice(0, 4).join(", ")}
                      </div>
                    </div>
                  ))}

                  {/* Curated macro events */}
                  {MACRO_EVENTS.slice(0, 4).map((ev, i) => {
                    const cfg = EV_TYPE[ev.type] || EV_TYPE.protocol;
                    const imp = IMP_C[ev.impact] || IMP_C.medium;
                    return (
                      <div key={ev.id} className="lm-card" style={{
                        padding: 14, borderLeft: `2px solid ${cfg.color}`,
                        animation: `fadeUp .3s ease ${(i+3)*.07}s both`,
                      }}>
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 7 }}>
                          <span className="lm-badge" style={{ background: `${cfg.color}18`, color: cfg.color }}>
                            {cfg.label}
                          </span>
                          <span className="lm-badge" style={{ background: imp.bg, color: imp.text }}>
                            {ev.impact} impact
                          </span>
                        </div>
                        <div style={{ fontSize: 12, fontWeight: 600, color: T.primary, fontFamily: FONTS.display, letterSpacing: "-0.01em", marginBottom: 5, lineHeight: 1.4 }}>
                          {ev.title}
                        </div>
                        <div style={{ fontSize: 11, color: T.secondary, fontFamily: FONTS.body, lineHeight: 1.55 }}>
                          {ev.summary}
                        </div>
                        <div style={{ fontSize: 10, color: T.muted, fontFamily: FONTS.body, marginTop: 7 }}>
                          {ev.source} · {ev.date}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>

            {/* ══ TOKENIZED FUNDS & INDICES ══════════════════════════════════════ */}
            <div style={{ marginTop: 24, marginBottom: 24 }}>
              <div style={{ marginBottom: 14 }}>
                <Label Icon={Globe}>TOKENIZED FUNDS & INDICES</Label>
                <div style={{ fontSize: 11, color: T.secondary, fontFamily: FONTS.body }}>
                  Institutional-grade assets, live on-chain
                </div>
              </div>

              {/* Tokenized Funds Cards - Horizontal scroll on desktop */}
              <div className="mobile-funds-scroll" style={{
                display: "flex", gap: 12, overflowX: "auto", paddingBottom: 8,
              }}>
                {[
                  { name: "BUIDL", issuer: "BlackRock", aum: "$500M+", chain: "Ethereum", yield: "~5.0%", category: "Money Market", status: "LIVE" },
                  { name: "BENJI", issuer: "Franklin Templeton", aum: "$400M+", chain: "Polygon/Stellar", yield: "~4.8%", category: "Treasury", status: "LIVE" },
                  { name: "FOBXX", issuer: "WisdomTree", aum: "$45M", chain: "Stellar", yield: "~4.5%", category: "Treasury", status: "LIVE" },
                  { name: "USDY", issuer: "Ondo Finance", aum: "$300M+", chain: "Ethereum/Solana", yield: "~5.2%", category: "Money Market", status: "LIVE" },
                  { name: "OUSG", issuer: "Ondo Finance", aum: "$150M+", chain: "Ethereum", yield: "~4.7%", category: "Treasury", status: "LIVE" },
                  { name: "BMMF", issuer: "Backed Finance", aum: "$80M+", chain: "Base", yield: "~4.6%", category: "Money Market", status: "LIVE" },
                ].map((fund, i) => {
                  const catColors = {
                    "Money Market": { bg: "rgba(232,160,0,.10)", text: T.amber },
                    "Treasury": { bg: "rgba(0,200,224,.10)", text: T.cyan },
                    "Equity": { bg: "rgba(0,217,138,.10)", text: T.green },
                  };
                  const catColor = catColors[fund.category] || catColors["Money Market"];
                  return (
                    <div key={i} className="lm-card" style={{
                      minWidth: 200, flex: "0 0 auto", padding: 16,
                      borderTop: `2px solid ${catColor.text}`,
                      transition: "transform .2s ease, box-shadow .2s ease",
                      cursor: "pointer",
                    }}
                    onMouseEnter={(e) => { e.currentTarget.style.transform = "translateY(-3px)"; e.currentTarget.style.boxShadow = `0 4px 20px ${catColor.text}20`; }}
                    onMouseLeave={(e) => { e.currentTarget.style.transform = "translateY(0)"; e.currentTarget.style.boxShadow = "none"; }}
                    >
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 8 }}>
                        <div>
                          <div style={{ fontSize: 16, fontWeight: 700, color: T.primary, fontFamily: FONTS.display, letterSpacing: "-0.01em" }}>
                            {fund.name}
                          </div>
                          <div style={{ fontSize: 11, color: T.secondary, fontFamily: FONTS.body, marginTop: 2 }}>
                            {fund.issuer}
                          </div>
                        </div>
                        <span className="lm-badge" style={{ background: "rgba(0,217,138,.12)", color: T.green, fontSize: 9 }}>
                          {fund.status}
                        </span>
                      </div>
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end" }}>
                        <span className="lm-badge" style={{ background: catColor.bg, color: catColor.text, fontSize: 9 }}>
                          {fund.category}
                        </span>
                        <span style={{ fontSize: 13, fontWeight: 600, color: T.amber, fontFamily: FONTS.mono }}>
                          {fund.aum}
                        </span>
                      </div>
                      <div style={{ marginTop: 10, display: "flex", justifyContent: "space-between", fontSize: 10, color: T.muted, fontFamily: FONTS.body }}>
                        <span>{fund.chain}</span>
                        <span style={{ color: T.green }}>{fund.yield} APY</span>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* ══ ON-CHAIN LISTING PIPELINE ══════════════════════════════════════ */}
            <div style={{ marginBottom: 24 }}>
              <Label Icon={Zap}>ON-CHAIN LISTING PIPELINE</Label>

              <div className="mobile-pipeline-grid" style={{ display: "grid", gridTemplateColumns: "1fr 320px", gap: 12, marginTop: 12 }}>
                {/* Left - Timeline */}
                <div className="lm-card" style={{ background: "rgba(10,9,24,.92)", padding: 20 }}>
                  {[
                    { step: 1, title: "Asset Structuring", desc: "Legal wrapper, SPV design, regulatory alignment (SFC / MAS)", color: T.violet },
                    { step: 2, title: "Tokenization", desc: "Smart contract deployment, ERC-1400 / ERC-3643 compliance standards", color: T.indigo },
                    { step: 3, title: "Exchange Listing", desc: "CEX: OSL, HashKey · DEX: Uniswap V3, Orca (Solana)", color: T.blue },
                    { step: 4, title: "Liquidity & Reporting", desc: "Market maker onboarding, daily NAV on-chain, automated reporting", color: T.cyan },
                  ].map((item, i) => (
                    <div key={i} style={{ display: "flex", gap: 14, position: "relative", paddingBottom: i < 3 ? 20 : 0 }}>
                      {i < 3 && (
                        <div style={{
                          position: "absolute", left: 7, top: 24, bottom: 0,
                          width: 2, background: `linear-gradient(180deg,${item.color} 0%,${T.cyan} 100%)`,
                          opacity: 0.4,
                        }} />
                      )}
                      <div style={{
                        width: 16, height: 16, borderRadius: "50%",
                        background: item.color, flexShrink: 0,
                        display: "flex", alignItems: "center", justifyContent: "center",
                        fontSize: 9, fontWeight: 700, color: "#fff", fontFamily: FONTS.mono,
                      }}>
                        {item.step}
                      </div>
                      <div>
                        <div style={{ fontSize: 13, fontWeight: 600, color: T.primary, fontFamily: FONTS.display, letterSpacing: "-0.01em", marginBottom: 4 }}>
                          {item.title}
                        </div>
                        <div style={{ fontSize: 11, color: T.secondary, fontFamily: FONTS.body, lineHeight: 1.5 }}>
                          {item.desc}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>

                {/* Right - CTA Card */}
                <div className="lm-card" style={{
                  padding: 20, borderLeft: `2px solid ${T.amber}`,
                  display: "flex", flexDirection: "column", justifyContent: "center",
                }}>
                  <div style={{ fontSize: 15, fontWeight: 700, color: T.primary, fontFamily: FONTS.display, letterSpacing: "-0.01em", marginBottom: 8 }}>
                    List Your Fund On-Chain
                  </div>
                  <div style={{ fontSize: 12, color: T.secondary, fontFamily: FONTS.body, marginBottom: 16, lineHeight: 1.5 }}>
                    From structuring to first trade in 90 days
                  </div>
                  <div style={{ marginBottom: 18 }}>
                    {[
                      "SFC-compliant tokenization framework",
                      "Direct access to OSL & HashKey liquidity",
                      "AI-powered portfolio monitoring via Looloomi",
                    ].map((point, i) => (
                      <div key={i} style={{ display: "flex", alignItems: "flex-start", gap: 8, marginBottom: 8 }}>
                        <span style={{ color: T.green, fontSize: 12 }}>✦</span>
                        <span style={{ fontSize: 11, color: T.secondary, fontFamily: FONTS.body }}>{point}</span>
                      </div>
                    ))}
                  </div>
                  <button style={{
                    background: T.amber, color: "#000", border: "none",
                    padding: "10px 16px", borderRadius: 6,
                    fontSize: 12, fontWeight: 600, fontFamily: FONTS.display,
                    cursor: "pointer", width: "100%",
                    transition: "opacity .2s ease",
                  }}
                  onMouseEnter={(e) => e.currentTarget.style.opacity = 0.9}
                  onMouseLeave={(e) => e.currentTarget.style.opacity = 1}
                  >
                    Schedule a Consultation
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* ══ QUANT GP TAB ══════════════════════════════════════════════════ */}
        {activeTab === "Quant GP" && (
          <div style={{ marginTop: 20 }}>

            {/* Hero — CometCloud Vault */}
            <div style={{
              position: "relative", borderRadius: 12, overflow: "hidden",
              marginBottom: 18, padding: "44px 44px 40px",
              background: "linear-gradient(135deg, rgba(68,114,255,.10) 0%, rgba(107,15,204,.16) 50%, rgba(255,16,96,.07) 100%)",
              border: `1px solid ${T.borderHi}`,
            }}>
              {/* Subtle grid overlay */}
              <div style={{
                position: "absolute", inset: 0, opacity: 0.035,
                backgroundImage: `linear-gradient(${T.blue} 1px,transparent 1px),linear-gradient(90deg,${T.blue} 1px,transparent 1px)`,
                backgroundSize: "44px 44px",
              }} />
              {/* Edge glow */}
              <div style={{
                position: "absolute", inset: 0, opacity: 0.6,
                background: "linear-gradient(180deg,transparent 60%,rgba(107,15,204,.12) 100%)",
              }} />

              <div style={{ position: "relative", zIndex: 1 }}>
                {/* Badges */}
                <div style={{ display: "flex", gap: 7, marginBottom: 22, flexWrap: "wrap" }}>
                  {[
                    { text: "SOLANA NATIVE", color: T.green },
                    { text: "OSL STABLECOIN", color: T.amber },
                    { text: "AI-CURATED", color: T.blue },
                    { text: "0% MGMT FEE", color: T.pink },
                  ].map((b, i) => (
                    <span key={i} style={{
                      fontSize: 10, fontWeight: 700, letterSpacing: "0.10em",
                      padding: "4px 10px", borderRadius: 4,
                      background: `${b.color}16`, color: b.color,
                      border: `1px solid ${b.color}30`,
                      fontFamily: FONTS.mono,
                    }}>{b.text}</span>
                  ))}
                </div>

                {/* Headline */}
                <div style={{
                  fontSize: 42, fontWeight: 800, color: T.primary,
                  fontFamily: FONTS.display, letterSpacing: "-0.03em",
                  lineHeight: 1.08, marginBottom: 12,
                }}>
                  CometCloud Vault
                </div>
                <div style={{
                  fontSize: 16, fontWeight: 400, color: T.secondary,
                  fontFamily: FONTS.body, lineHeight: 1.6, maxWidth: 560,
                }}>
                  Asia's first AI-curated on-chain Fund-of-Funds,
                  built for human LPs and autonomous AI agents.
                </div>

                {/* Metrics */}
                <div style={{ display: "flex", gap: 48, marginTop: 30, flexWrap: "wrap" }}>
                  {[
                    { value: "$30M",  label: "Target AUM" },
                    { value: "5–8",   label: "Quant GPs" },
                    { value: "0 / 0", label: "Mgmt / Entry Fee" },
                    { value: "SOL",   label: "Native Chain" },
                  ].map((s, i) => (
                    <div key={i}>
                      <div style={{ fontSize: 30, fontWeight: 700, fontFamily: FONTS.mono, color: T.primary, lineHeight: 1 }}>{s.value}</div>
                      <div style={{ fontSize: 10, color: T.muted, fontFamily: FONTS.body, textTransform: "uppercase", letterSpacing: "0.10em", marginTop: 6 }}>{s.label}</div>
                    </div>
                  ))}
                </div>
              </div>
            </div>

            {/* How It Works */}
            <div style={{ marginBottom: 16 }}>
              <Label Icon={Zap}>How The Vault Works</Label>
              <div className="mobile-howitworks-grid" style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 10 }}>
                {[
                  { step:"01", title:"Deposit",      desc:"Subscribe with OSL stablecoin on Solana. Programmatic API available for AI agents.", color:T.blue,   icon:"↓" },
                  { step:"02", title:"AI Selection", desc:"Looloomi AI continuously scores and curates the GP universe using on-chain + quant signals.", color:T.violet, icon:"⚡" },
                  { step:"03", title:"GP Allocation",desc:"Capital allocated across 5–8 vetted quant GPs. Each GP runs independent strategies.", color:T.amber,  icon:"◎" },
                  { step:"04", title:"Performance",  desc:"Returns settled on-chain. Performance-only fee split with GP. Zero mgmt or entry cost.", color:T.green,  icon:"↑" },
                ].map((s, i) => (
                  <div key={i} className="lm-card" style={{
                    padding: 18, position: "relative", overflow: "hidden",
                    borderTop: `2px solid ${s.color}`,
                    animation: `fadeUp .3s ease ${i*.08}s both`,
                  }}>
                    <div style={{
                      fontSize: 36, fontWeight: 800, color: `${s.color}14`,
                      fontFamily: FONTS.display, position: "absolute",
                      top: 10, right: 14, lineHeight: 1, userSelect: "none",
                    }}>{s.step}</div>
                    <div style={{ fontSize: 20, marginBottom: 10 }}>{s.icon}</div>
                    <div style={{ fontSize: 14, fontWeight: 700, color: T.primary, fontFamily: FONTS.display, letterSpacing: "-0.01em", marginBottom: 8 }}>
                      {s.title}
                    </div>
                    <div style={{ fontSize: 12, color: T.secondary, fontFamily: FONTS.body, lineHeight: 1.65 }}>
                      {s.desc}
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* AI Agent + OSL */}
            <div className="mobile-2col-grid" style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10, marginBottom: 16 }}>
              <div className="lm-card" style={{ padding: 20, borderLeft: `2px solid ${T.blue}` }}>
                <div style={{ fontSize: 11, fontWeight: 700, color: T.blue, letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 10, fontFamily: FONTS.body }}>
                  ⚡ Built for AI Agents
                </div>
                <div style={{ fontSize: 13, color: T.secondary, fontFamily: FONTS.body, lineHeight: 1.75, marginBottom: 14 }}>
                  AI agents like OpenClaw can autonomously subscribe, monitor NAV, and redeem — all via on-chain calls. No human approval required.
                </div>
                <div style={{ padding: "11px 14px", borderRadius: 7, background: "rgba(68,114,255,.07)", border: `1px solid ${T.blue}20` }}>
                  <code style={{ fontSize: 11, color: T.cyan, fontFamily: FONTS.mono, lineHeight: 1.9 }}>
                    vault.deposit(amount, agent_wallet)<br />
                    vault.get_nav()<br />
                    vault.redeem(shares, recipient)
                  </code>
                </div>
              </div>

              <div className="lm-card" style={{ padding: 20, borderLeft: `2px solid ${T.amber}` }}>
                <div style={{ fontSize: 11, fontWeight: 700, color: T.amber, letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 10, fontFamily: FONTS.body }}>
                  🏦 OSL · Hong Kong Licensed
                </div>
                <div style={{ fontSize: 13, color: T.secondary, fontFamily: FONTS.body, lineHeight: 1.75, marginBottom: 14 }}>
                  Denominated in OSL's Solana stablecoin — Hong Kong's leading licensed digital asset platform. Institutional-grade entry with SFC-compliant infrastructure.
                </div>
                <div style={{ display: "flex", gap: 7, flexWrap: "wrap" }}>
                  {["SFC Framework", "HK Licensed", "Solana Native", "Institutional"].map((t, i) => (
                    <span key={i} style={{
                      fontSize: 10, padding: "3px 8px", borderRadius: 3,
                      background: "rgba(232,160,0,.08)", color: T.amber,
                      border: `1px solid ${T.amber}20`,
                      fontFamily: FONTS.body, fontWeight: 600,
                    }}>{t}</span>
                  ))}
                </div>
              </div>
            </div>

            {/* Status banner */}
            <div style={{
              display: "flex", alignItems: "center", justifyContent: "space-between",
              padding: "13px 20px", borderRadius: 8, marginBottom: 18,
              background: "rgba(0,217,138,.05)", border: `1px solid ${T.green}25`,
            }}>
              <div style={{ display: "flex", alignItems: "center", gap: 9 }}>
                <div className="pulse-dot" style={{ width: 7, height: 7, borderRadius: "50%", background: T.amber }} />
                <span style={{ fontSize: 13, color: T.amber, fontWeight: 600, fontFamily: FONTS.body }}>
                  Vault Contract: In Development · Solana Devnet Q2 2026
                </span>
              </div>
              <div style={{ fontSize: 11, color: T.muted, fontFamily: FONTS.mono }}>
                SPL Vault · Anchor / Rust
              </div>
            </div>

            {/* Core GP header */}
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
              <Label Icon={Users}>Core General Partner</Label>
              <div style={{ display: "flex", gap: 8 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 6, padding: "5px 12px", borderRadius: 6, border: `1px solid ${T.amber}40`, background: "rgba(232,160,0,.06)" }}>
                  <div className="pulse-dot" style={{ width: 5, height: 5, borderRadius: "50%", background: T.amber }} />
                  <span style={{ fontSize: 10, color: T.amber, fontFamily: FONTS.mono, fontWeight: 600 }}>VERIFIED GP</span>
                </div>
                <a href="https://est.cc" target="_blank" rel="noopener noreferrer"
                  style={{ display: "flex", alignItems: "center", gap: 6, padding: "5px 12px", borderRadius: 6, border: `1px solid ${T.border}`, background: "transparent", color: T.secondary, textDecoration: "none", fontSize: 11, fontFamily: FONTS.body }}>
                  <ExternalLink size={11} /> est.cc
                </a>
              </div>
            </div>

            {/* EST Alpha iframe */}
            <div className="iframe-wrap">
              {iframeError ? (
                <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100%", flexDirection: "column", gap: 12, color: T.muted }}>
                  <div style={{ fontSize: 14, fontFamily: FONTS.body }}>EST Alpha GP Dashboard</div>
                  <div style={{ fontSize: 12, color: T.secondary, fontFamily: FONTS.body }}>Coming Soon</div>
                </div>
              ) : (
                <iframe
                  src="https://est.cc"
                  title="EST Alpha — Quantitative GP"
                  allow="fullscreen"
                  onError={() => setIframeError(true)}
                  sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-popups-to-escape-sandbox"
                />
              )}
            </div>

            <div style={{ marginTop: 10, fontSize: 10, color: T.dim, textAlign: "center", fontFamily: FONTS.body }}>
              CometCloud Vault · Powered by Looloomi AI · Solana · OSL Stablecoin · Hong Kong
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
