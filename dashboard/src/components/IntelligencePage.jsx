import { useState, useEffect, useCallback, useRef, lazy, Suspense } from "react";
import {
  RefreshCw, ExternalLink, Zap, Building2,
  DollarSign, Globe, Activity, Users, Shield
} from "lucide-react";
import BottomSheet from "./ui/BottomSheet";
import CISWidget from "./CISWidget";
import MacroBrief from "./MacroBrief";
import EconomicIndicators from "./EconomicIndicators";
import { T, FONTS } from "../tokens";

// Lazy — recharts + DeFiLlama logic (~80KB); only used on Protocol tab
const ProtocolIntelligence = lazy(() => import("./ProtocolIntelligence"));

const API_BASE = "/api/v1";

/* ─── CSS ────────────────────────────────────────────────────────────── */
const CSS = `
  @keyframes fadeUp   { from{opacity:0;transform:translateY(14px)} to{opacity:1;transform:translateY(0)} }
  @keyframes slideIn  { from{opacity:0;transform:translateX(-8px)} to{opacity:1;transform:translateX(0)} }
  @keyframes pulse    { 0%,100%{opacity:1} 50%{opacity:.35} }
  @keyframes shimmer  { 0%{background-position:-400px 0} 100%{background-position:400px 0} }

  .fade-up  { animation: fadeUp  .4s cubic-bezier(.16,1,.3,1) forwards; }
  .slide-in { animation: slideIn .25s ease forwards; }

  .iframe-wrap { position:relative;width:100%;height:calc(100vh - 88px);border-radius:10px;overflow:hidden;border:1px solid rgba(255,255,255,0.08); }
  .iframe-wrap iframe { width:100%;height:100%;border:none;background:white; }

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
    .vc-table-header, .vc-table-row { grid-template-columns: 1.5fr 70px 80px !important; }
    .vc-col-lead, .vc-col-date-header { display: none !important; }
    .filter-btn { padding: 6px 10px !important; font-size: 10px !important; min-height: 32px; }
    .lm-action-btn { min-height: 36px; padding: 8px 12px !important; }
  }
  @media (max-width: 480px) {
    .vc-table-header, .vc-table-row { grid-template-columns: 1fr 60px !important; }
    .vc-col-round, .vc-col-round-header { display: none !important; }
    .mobile-stat-grid { grid-template-columns: 1fr 1fr !important; gap: 6px !important; }
    .mobile-howitworks-grid { grid-template-columns: 1fr !important; }
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
const catStyle = (c) => CAT_C[c] || { bg: "rgba(255,255,255,0.04)", text: T.muted };

/* ─── Curated RWA Projects (Mar 2026) ────────────────────────────────── */
/* RWA_PROJECTS removed — replaced by ProtocolIntelligence (live CIS-scored data) */

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
export default function IntelligencePage({ activeTab, setActiveTab, isSection = false }) {
  const [raises, setRaises]             = useState([]);
  const [rwaRaises, setRwaRaises]       = useState([]);
  const [loading, setLoading]           = useState(true);
  const [raisesFilter, setRaisesFilter] = useState("All");
  const [lastUpdate, setLastUpdate]     = useState(null);
  const [stats, setStats]               = useState(null);
  const [showUpdateDrawer, setShowUpdateDrawer] = useState(false);
  const [iframeError, setIframeError]   = useState(false);
  // selectedRWA removed — replaced by ProtocolIntelligence component
  const [selectedVCRound, setSelectedVCRound] = useState(null);
  const [macroEvents, setMacroEvents]   = useState([]);
  const [sectorData, setSectorData]     = useState([]);
  const [heatmapLoading, setHeatmapLoading] = useState(true);
  const [vcPortfolios, setVcPortfolios] = useState([]);
  const [vcPortfoliosLoading, setVcPortfoliosLoading] = useState(true);
  const [mounted, setMounted] = useState(false);

  // Page entrance animation
  useEffect(() => {
    const timer = setTimeout(() => setMounted(true), 50);
    return () => clearTimeout(timer);
  }, []);

  // Heatmap color helper
  const getHeatmapStyle = (change) => {
    const val = parseFloat(change);
    if (val >= 3) return { bg: "rgba(0,232,122,0.16)", border: "rgba(0,232,122,0.25)", color: T.green }; // strong-up
    if (val >= 0.5) return { bg: "rgba(0,232,122,0.08)", border: "rgba(0,232,122,0.14)", color: T.green }; // up
    if (val > -0.5) return { bg: "rgba(14,30,56,0.5)", border: "rgba(56,148,210,0.08)", color: T.t3 }; // flat
    if (val > -3) return { bg: "rgba(255,61,90,0.08)", border: "rgba(255,61,90,0.14)", color: T.red }; // down
    return { bg: "rgba(255,61,90,0.16)", border: "rgba(255,61,90,0.25)", color: T.red }; // strong-down
  };

  // Fetch sector heatmap data
  useEffect(() => {
    const fetchHeatmap = async () => {
      try {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 6000);
        const res = await fetch(`${API_BASE}/defi/overview`, { signal: controller.signal });
        clearTimeout(timeoutId);
        const data = await res.json();
        // Map API data to sector format — live fields from get_defi_overview v2
        const fmtB = (v) => v ? `$${Math.round(v / 1e9)}B` : "—";
        const mapped = [
          { name: "DeFi", change: data.defi_change_24h ?? 0, tvl: fmtB(data.total_tvl) },
          { name: "L2", change: data.l2_change_24h ?? 0, tvl: fmtB(data.l2_tvl) },
          { name: "RWA", change: data.rwa_change_24h ?? 0, tvl: fmtB(data.rwa_tvl) },
          { name: "L1", change: 0, tvl: "—" },
          { name: "Staking", change: 0, tvl: "—" },
          { name: "Oracle", change: 0, tvl: "—" },
          { name: "GameFi", change: 0, tvl: "—" },
          { name: "CEX", change: 0, tvl: "—" },
        ];
        setSectorData(mapped);
      } catch (e) {
        console.error("Heatmap fetch error:", e);
        // Fallback — show sectors with no data rather than stale numbers
        setSectorData([
          { name: "DeFi", change: 0, tvl: "—" },
          { name: "L2", change: 0, tvl: "—" },
          { name: "RWA", change: 0, tvl: "—" },
          { name: "L1", change: 0, tvl: "—" },
          { name: "Staking", change: 0, tvl: "—" },
          { name: "Oracle", change: 0, tvl: "—" },
          { name: "GameFi", change: 0, tvl: "—" },
          { name: "CEX", change: 0, tvl: "—" },
        ]);
      } finally {
        setHeatmapLoading(false);
      }
    };
    fetchHeatmap();
  }, []);

  // Fetch VC portfolio performance from CoinGecko categories
  useEffect(() => {
    const fetchVCPortfolios = async () => {
      try {
        const r = await fetch(`${API_BASE}/vc/portfolios`);
        const json = await r.json();
        setVcPortfolios(json.data || []);
      } catch (e) {
        console.error("VC portfolios fetch error:", e);
        setVcPortfolios([]);
      } finally {
        setVcPortfoliosLoading(false);
      }
    };
    fetchVCPortfolios();
  }, []);

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
        // Backend returns amount in USD (already multiplied by 1e6), convert to millions
        let amount = 0;
        if (typeof item.amount === "number") {
          amount = item.amount / 1_000_000;
        } else if (typeof item.amount === "string") {
          amount = parseFloat(item.amount) / 1_000_000;
        }

        // Handle date - backend returns string "YYYY-MM-DD" or timestamp
        let date = null;
        let dateStr = null;
        if (item.date) {
          if (typeof item.date === "number") {
            // Already a timestamp
            date = item.date;
            dateStr = new Date(item.date * 1000).toISOString().split("T")[0];
          } else if (typeof item.date === "string") {
            // Parse string date "YYYY-MM-DD"
            dateStr = item.date;
            const parts = item.date.split("-");
            if (parts.length === 3) {
              date = Math.floor(new Date(parts[0], parts[1]-1, parts[2]).getTime() / 1000);
            } else {
              date = Math.floor(Date.parse(item.date) / 1000);
            }
          }
        }

        return {
          name: item.project || item.name || item.protocol || "—",
          round: item.round_type || item.round || item.stage || "—",
          amount,
          date,
          dateStr,
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

      // Filter: amount > 0 AND date within last 180 days
      const now180 = Date.now() / 1000 - 180 * 86400;
      const recent180 = all.filter(r => r.amount > 0 && r.date && r.date > now180);

      // Broader filter: RWA + DeFi + Infrastructure
      const isSector = (item) => {
        const cat = (item.category || "").toLowerCase();
        return isRWA(item) || cat.includes("defi") || cat.includes("infrastructure") || cat.includes("l1") || cat.includes("l2");
      };
      const sector = recent180.filter(isSector);
      setRaises(recent180);
      setRwaRaises(sector);
      setLastUpdate(new Date());

      // Stats — 180d window (matching filter)
      const recent = recent180;
      const recentRwa = sector;

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

  // Fetch macro events — fall back to curated static list if API empty/fails
  useEffect(() => {
    const fetchMacroEvents = async () => {
      try {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), 8000);
        const res = await fetch(`${API_BASE}/intelligence/macro-events`, { signal: controller.signal });
        clearTimeout(timeoutId);
        const json = await res.json();
        const events = json.events || [];
        // show all events; filter is too strict and leaves list empty
        setMacroEvents(events);
      } catch (e) {
        console.error("Macro events fetch error:", e);
        setMacroEvents([]);
      }
    };
    fetchMacroEvents();
  }, []);

  const FILTERS = ["All", "RWA", "DeFi", "AI", "Infrastructure"];

  const filtered = raises.filter(r => {
    // All: show everything with amount > 0
    if (raisesFilter === "All") {
      return r.amount > 0;
    }
    // RWA: show RWA-related projects
    if (raisesFilter === "RWA") return isRWA(r) && r.amount > 0;
    // Other filters: match category
    return ((r.category || "").toLowerCase().includes(raisesFilter.toLowerCase()) || (r.categoryGroup || "").toLowerCase().includes(raisesFilter.toLowerCase())) && r.amount > 0;
  });

  /* ── Shared nav ── */
  const NavBar = () => (
    <div style={{
      display: "flex", alignItems: "center", justifyContent: "space-between",
      padding: "18px 0 20px", borderBottom: `1px solid ${T.border}`,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
        <span onClick={() => setActiveTab("Home")}
          style={{
            fontFamily: FONTS.display, fontWeight: 700, fontSize: 20,
            letterSpacing: "-0.02em", color: T.primary, cursor: "pointer",
          }}>
          CometCloud
        </span>
        <div style={{ display: "flex", gap: 4 }}>
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
    <div style={{ position: "relative", minHeight: "100vh", background: "transparent" }}>
      {/* Only render ambient light when not embedded in App.jsx */}
      {!isSection && (
        <div className="turrell-wrap">
          <div className="t-orb t-orb-1" /><div className="t-orb t-orb-2" />
          <div className="t-orb t-orb-3" /><div className="t-orb t-orb-4" />
        </div>
      )}

      <div style={{ position: "relative", zIndex: 1, maxWidth: 1400, margin: "0 auto", padding: isSection ? "0 0 40px" : "0 28px 56px" }}>
        {!isSection && <NavBar />}

        {/* ══ INTELLIGENCE TAB ══════════════════════════════════════════════ */}
        {(activeTab === "Intelligence" || isSection) && (
          <div>
            {/* Section Header (when embedded in App.jsx scroll layout) */}
            {isSection && (
              <div style={{
                marginBottom: 20,
                display: "flex", alignItems: "center", gap: 10,
                paddingBottom: 14, borderBottom: "1px solid rgba(6,182,212,0.08)",
                opacity: mounted ? 1 : 0,
                transform: mounted ? "translateY(0)" : "translateY(8px)",
                transition: "opacity 0.35s ease, transform 0.35s ease",
              }}>
                <div style={{ width: 2, height: 16, background: "rgba(6,182,212,0.65)", borderRadius: 1, flexShrink: 0 }} />
                <span style={{ fontFamily: FONTS.display, fontSize: 18, fontWeight: 600, color: T.primary, letterSpacing: "-0.01em" }}>
                  Intelligence
                </span>
                <span style={{ fontFamily: FONTS.mono, fontSize: 10, color: T.muted, letterSpacing: "0.1em", textTransform: "uppercase" }}>
                  · AI Market Analysis
                </span>
              </div>
            )}

            {/* Macro Brief — AI-generated market analysis */}
            <div style={{
              marginBottom: 16, width: "100%", clear: "both",
              opacity: mounted ? 1 : 0,
              transform: mounted ? "translateY(0)" : "translateY(8px)",
              transition: "opacity 0.35s ease 80ms, transform 0.35s ease 80ms",
            }}>
              <MacroBrief />
            </div>

            {/* Economic Indicators — EODHD multi-country macro panel */}
            <div style={{
              marginBottom: 20, width: "100%", clear: "both",
              opacity: mounted ? 1 : 0,
              transform: mounted ? "translateY(0)" : "translateY(8px)",
              transition: "opacity 0.35s ease 120ms, transform 0.35s ease 120ms",
            }}>
              <EconomicIndicators />
            </div>

            {/* CIS Widget */}
            <div style={{
              marginBottom: 24, width: "100%", clear: "both",
              opacity: mounted ? 1 : 0,
              transform: mounted ? "translateY(0)" : "translateY(8px)",
              transition: "opacity 0.35s ease 160ms, transform 0.35s ease 160ms",
            }}>
              <CISWidget defaultLimit={20} />
            </div>

            {/* Stat strip — inline, no cards */}
            <div style={{
              display: "flex", gap: 0, margin: "20px 0",
              paddingBottom: 20, borderBottom: `1px solid rgba(37,99,235,0.08)`,
              opacity: mounted ? 1 : 0,
              transform: mounted ? "translateY(0)" : "translateY(8px)",
              transition: "opacity 0.35s ease 240ms, transform 0.35s ease 240ms",
              flexWrap: "wrap",
            }}>
              {[
                { label: "90d Total Raised", value: stats ? fmt.amount(stats.totalAmount) : null, sub: `${stats?.totalDeals ?? "—"} deals`, color: T.blue },
                { label: "RWA Sector",        value: stats ? fmt.amount(stats.rwaAmount)  : null, sub: `${stats?.rwaDeals ?? "—"} RWA deals`, color: T.amber },
                { label: "Most Active VC",    value: stats?.topVC ?? null,                         sub: `${stats?.topVCDeals ?? "—"} deals`, color: T.green },
                { label: "Source",            value: "DeFiLlama",                                  sub: "Raises API · Live", color: T.t3 },
              ].map((s, i, arr) => (
                <div key={i} style={{
                  paddingRight: 36, paddingLeft: i === 0 ? 0 : 0,
                  borderRight: i < arr.length - 1 ? `1px solid rgba(37,99,235,0.10)` : "none",
                  marginRight: i < arr.length - 1 ? 36 : 0,
                  paddingBottom: 4,
                }}>
                  <div style={{ fontFamily: FONTS.mono, fontSize: 7, letterSpacing: "0.20em", color: T.t3, textTransform: "uppercase", marginBottom: 8, opacity: 0.6 }}>
                    {s.label}
                  </div>
                  {s.value !== null
                    ? <div style={{ fontFamily: FONTS.mono, fontSize: 22, fontWeight: 400, color: s.color, letterSpacing: "-0.02em", lineHeight: 1, marginBottom: 5 }}>{s.value}</div>
                    : <div className="sk" style={{ height: 22, width: 80, marginBottom: 5 }} />
                  }
                  <div style={{ fontFamily: FONTS.mono, fontSize: 9, color: T.t3, opacity: 0.6 }}>{s.sub}</div>
                </div>
              ))}
            </div>

            {/* ══ Protocol Intelligence ════════════════════════════════════ */}
            <div style={{
              opacity: mounted ? 1 : 0,
              transform: mounted ? "translateY(0)" : "translateY(8px)",
              transition: "opacity 0.35s ease 320ms, transform 0.35s ease 320ms",
            }}>
              <Suspense fallback={<div style={{ height: 200, display: "flex", alignItems: "center", justifyContent: "center", color: "rgba(199,210,254,0.3)", fontFamily: "monospace", fontSize: 11 }}>Loading protocols…</div>}>
                <ProtocolIntelligence />
              </Suspense>
            </div>

            {/* Main 2-col layout: Sector Heatmap + Macro Events */}
            <div className="mobile-2col-grid" style={{
              display: "grid", gridTemplateColumns: isSection ? "1fr" : "1fr 1fr", gap: 16, marginBottom: 16,
              opacity: mounted ? 1 : 0,
              transform: mounted ? "translateY(0)" : "translateY(8px)",
              transition: "opacity 0.35s ease 400ms, transform 0.35s ease 400ms",
            }}>

              {/* Left — Sector Heatmap */}
              <div className="lm-card transition-lift" style={{ padding: 0, overflow: "hidden" }}>
                <div style={{ padding: "16px 18px 0", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                  <Label Icon={Activity}>Sector Heatmap · 24H</Label>
                  <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                    <span style={{
                      background: "rgba(75,158,255,0.1)", border: "1px solid rgba(75,158,255,0.2)",
                      color: "#4B9EFF", padding: "2px 7px", borderRadius: 3,
                      fontSize: 8, fontWeight: 700, letterSpacing: "0.1em",
                      fontFamily: FONTS.display
                    }}>LIVE</span>
                    <span style={{ fontSize: 9, color: T.muted }}>DefiLlama</span>
                  </div>
                </div>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: 8, padding: 12 }}>
                  {heatmapLoading ? (
                    Array(8).fill(0).map((_, i) => (
                      <div key={i} style={{
                        borderRadius: 8, padding: "14px 16px",
                        border: `1px solid ${T.border}`,
                        background: "rgba(0,0,0,0.02)",
                      }}>
                        <div className="sk" style={{ height: 12, width: 50, marginBottom: 8 }} />
                        <div className="sk" style={{ height: 20, width: 60 }} />
                      </div>
                    ))
                  ) : sectorData.map((sector, idx) => {
                    const style = getHeatmapStyle(sector.change);
                    return (
                      <div key={idx} style={{
                        borderRadius: 8, padding: "14px 16px",
                        border: `1px solid ${style.border}`,
                        background: style.bg,
                        transition: "transform .2s ease, box-shadow .2s ease, border-color .2s ease", cursor: "pointer",
                      }}
                      onMouseEnter={(e) => { e.currentTarget.style.transform = "translateY(-2px)"; e.currentTarget.style.boxShadow = "0 4px 16px rgba(0,0,0,0.25)"; }}
                      onMouseLeave={(e) => { e.currentTarget.style.transform = "translateY(0)"; e.currentTarget.style.boxShadow = "none"; }}
                      >
                        <div style={{ fontFamily: FONTS.display, fontSize: 11, fontWeight: 700, color: T.primary, letterSpacing: "0.04em", marginBottom: 4 }}>
                          {sector.name}
                        </div>
                        <div style={{ fontFamily: FONTS.mono, fontSize: 17, fontWeight: 400, letterSpacing: "-0.02em", color: style.color }}>
                          {sector.tvl === "—" && sector.change === 0
                            ? "—"
                            : `${sector.change > 0 ? "+" : ""}${Number(sector.change).toFixed(1)}%`}
                        </div>
                        <div style={{ fontSize: 9, color: "rgba(199,210,254,0.3)", marginTop: 4 }}>
                          {sector.tvl}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>

              {/* Right — Macro Events */}
              <div style={{ padding: "16px 0 0", overflow: "hidden", maxHeight: 380, overflowY: "auto" }}>
                <div style={{ paddingBottom: 12, marginBottom: 4 }}>
                  <Label Icon={Shield}>Macro Events</Label>
                </div>
                <div>
                  {macroEvents.length > 0 ? macroEvents.slice(0, 5).map((event, idx) => {
                    const isInstitutional = event.category === "INSTITUTIONAL";
                    const isHigh = event.impact === "HIGH";
                    const catColor = isInstitutional ? "#C8A84B" : "#4B9EFF";
                    const desc = event.description || "";
                    const truncated = desc.length > 100 ? desc.slice(0, 100) + "…" : desc;
                    return (
                    <div key={idx} style={{
                      padding: "12px 0", borderBottom: `1px solid rgba(37,99,235,0.07)`,
                      cursor: "pointer",
                    }}>
                      <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginBottom: 5 }}>
                        <span style={{ fontFamily: FONTS.mono, fontSize: 8, fontWeight: 700, letterSpacing: "0.10em", color: catColor, textTransform: "uppercase" }}>
                          {event.category}
                        </span>
                        {isHigh && (
                          <span style={{ fontFamily: FONTS.mono, fontSize: 8, color: "#FF3D5A", letterSpacing: "0.06em" }}>· HIGH</span>
                        )}
                      </div>
                      <div style={{ fontFamily: FONTS.display, fontSize: 12, fontWeight: 600, color: T.t1, lineHeight: 1.4, marginBottom: 4 }}>
                        {event.title}
                      </div>
                      {truncated && (
                        <div style={{ fontFamily: FONTS.body, fontSize: 10, color: T.t3, lineHeight: 1.55, marginBottom: 4 }}>
                          {truncated}
                        </div>
                      )}
                      <div style={{ fontFamily: FONTS.mono, fontSize: 9, color: T.t3, opacity: 0.55 }}>
                        {event.source}{event.date ? ` · ${event.date}` : ""}
                      </div>
                    </div>
                    );
                  }) : (
                    <div style={{ padding: "20px 0", color: T.muted, fontSize: 12, fontFamily: FONTS.body }}>
                      No macro events available
                    </div>
                  )}
                </div>
              </div>
            </div>

            {/* ── VC Portfolio Performance (CoinGecko) ───────────────────── */}
            {(vcPortfoliosLoading || vcPortfolios.length > 0) && (
              <div className="lm-card" style={{ overflow: "hidden", marginBottom: 16 }}>
                <div style={{ padding: "14px 18px 12px", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                  <Label Icon={Activity}>VC Portfolio Performance</Label>
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <span style={{ fontSize: 9, fontFamily: FONTS.mono, color: T.muted, letterSpacing: "0.06em" }}>
                      CoinGecko · 10min
                    </span>
                    <span style={{
                      fontSize: 8, fontWeight: 700, letterSpacing: "0.1em",
                      padding: "2px 6px", borderRadius: 3, fontFamily: FONTS.display,
                      background: "rgba(37,99,235,0.10)", color: T.bloom,
                      border: `1px solid rgba(37,99,235,0.20)`,
                    }}>LIVE</span>
                  </div>
                </div>

                {/* Column headers */}
                <div style={{
                  display: "grid", gridTemplateColumns: "1.6fr 1fr 0.9fr 1.2fr",
                  padding: "6px 18px", borderTop: `1px solid ${T.border}`,
                  borderBottom: `1px solid ${T.border}`,
                }}>
                  {["FIRM", "PORTFOLIO MCAP", "24H", "TOP HOLDINGS"].map(h => (
                    <span key={h} style={{ fontFamily: FONTS.display, fontSize: 9, fontWeight: 700,
                      letterSpacing: "0.1em", color: T.t4, textTransform: "uppercase" }}>{h}</span>
                  ))}
                </div>

                <div style={{ maxHeight: 320, overflowY: "auto" }}>
                  {vcPortfoliosLoading
                    ? Array(8).fill(0).map((_, i) => (
                        <div key={i} style={{ display: "grid", gridTemplateColumns: "1.6fr 1fr 0.9fr 1.2fr",
                          padding: "9px 18px", borderBottom: `1px solid ${T.border}`, gap: 8 }}>
                          <div className="sk" style={{ height: 12, width: "70%", borderRadius: 3 }} />
                          <div className="sk" style={{ height: 12, width: "60%", borderRadius: 3 }} />
                          <div className="sk" style={{ height: 12, width: "40%", borderRadius: 3 }} />
                          <div className="sk" style={{ height: 12, width: "80%", borderRadius: 3 }} />
                        </div>
                      ))
                    : vcPortfolios.map((vc, i) => {
                        const chg = vc.change_24h ?? 0;
                        const chgColor = chg > 0 ? T.green : chg < 0 ? T.red : T.t3;
                        const mcapB = vc.market_cap ? (vc.market_cap / 1e9).toFixed(1) : "—";
                        const volB  = vc.volume_24h ? (vc.volume_24h / 1e9).toFixed(2) : "—";
                        const isT1  = vc.tier === 1;
                        return (
                          <div key={vc.id} className="lm-row" style={{
                            display: "grid", gridTemplateColumns: "1.6fr 1fr 0.9fr 1.2fr",
                            padding: "9px 18px", borderBottom: `1px solid ${T.border}`,
                            alignItems: "center", background: "transparent",
                          }}>
                            {/* Firm */}
                            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                              {isT1 && (
                                <span style={{ width: 3, height: 16, borderRadius: 2, flexShrink: 0,
                                  background: `linear-gradient(180deg, ${T.indigo}, ${T.royal})` }} />
                              )}
                              <span style={{ fontFamily: FONTS.display, fontSize: 12, fontWeight: isT1 ? 600 : 400,
                                color: isT1 ? T.t1 : T.t2 }}>
                                {vc.name}
                              </span>
                            </div>
                            {/* Market cap */}
                            <div style={{ fontFamily: FONTS.mono, fontSize: 12, color: T.t1 }}>
                              ${mcapB}B
                              <span style={{ fontSize: 9, color: T.t4, marginLeft: 4 }}>vol ${volB}B</span>
                            </div>
                            {/* 24h change */}
                            <div style={{ fontFamily: FONTS.mono, fontSize: 13, fontWeight: 600, color: chgColor }}>
                              {chg > 0 ? "+" : ""}{chg.toFixed(2)}%
                            </div>
                            {/* Top coins */}
                            <div style={{ display: "flex", gap: 5, flexWrap: "wrap" }}>
                              {(vc.top_coins || []).slice(0, 3).map(coin => (
                                <span key={coin} style={{
                                  fontFamily: FONTS.mono, fontSize: 9, fontWeight: 600,
                                  color: T.bloom, background: "rgba(99,102,241,0.08)",
                                  border: `1px solid rgba(99,102,241,0.18)`,
                                  padding: "1px 6px", borderRadius: 3,
                                  textTransform: "uppercase",
                                }}>
                                  {coin.replace(/-/g, " ").split(" ")[0]}
                                </span>
                              ))}
                            </div>
                          </div>
                        );
                      })}
                </div>

                {/* Footer */}
                {!vcPortfoliosLoading && vcPortfolios.length > 0 && (
                  <div style={{ padding: "8px 18px", borderTop: `1px solid ${T.border}`,
                    display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                    <span style={{ fontSize: 9, fontFamily: FONTS.mono, color: T.t4 }}>
                      {vcPortfolios.length} firms · ranked by portfolio market cap · CoinGecko categories
                    </span>
                    <span style={{ fontSize: 9, fontFamily: FONTS.mono, color: T.indigo, opacity: 0.6 }}>
                      ▌ Tier 1 firms highlighted
                    </span>
                  </div>
                )}
              </div>
            )}

            {/* Full width — VC Funding Table (hidden when no data) */}
            {(loading || raises.length > 0) && <div className="lm-card" style={{ overflow: "hidden", marginBottom: 16 }}>
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

                  {/* Data Source Label */}
                  <div style={{
                    display: 'flex', alignItems: 'center', gap: '6px',
                    fontSize: '9px', color: T.muted
                  }}>
                    <span style={{
                      background: 'rgba(75,158,255,0.1)',
                      border: '1px solid rgba(75,158,255,0.2)',
                      color: '#4B9EFF', padding: '2px 7px', borderRadius: '3px',
                      fontSize: '8px', fontWeight: '700', letterSpacing: '0.1em',
                      fontFamily: FONTS.display
                    }}>LIVE</span>
                    <span>DefiLlama Raises API</span>
                    <span style={{color:'rgba(148,163,184,0.35)'}}>·</span>
                    <span id="vcUpdateTime">Updated {lastUpdate ? lastUpdate.toLocaleTimeString() : 'just now'}</span>
                  </div>
                </div>

                <div className="lm-card" style={{ overflow: "hidden" }}>
                  {/* Header - redesign style */}
                  <div className="vc-table-header" style={{
                    display: "grid", gridTemplateColumns: "1fr 80px 100px 130px 80px",
                    gap: 10, padding: "9px 18px", borderBottom: `1px solid ${T.border}`,
                    fontSize: 9, color: T.muted, letterSpacing: "0.14em",
                    textTransform: "uppercase", fontFamily: FONTS.display, fontWeight: 600,
                    background: T.raised,
                  }}>
                    <span>Project</span>
                    <span className="vc-col-round-header" style={{ textAlign: "center" }}>Round</span>
                    <span style={{ textAlign: "right" }}>Amount</span>
                    <span className="vc-col-lead" style={{}}>Lead Investor</span>
                    <span className="vc-col-date-header" style={{ textAlign: "right" }}>Date</span>
                  </div>

                  {/* Rows */}
                  <div style={{ maxHeight: 530, overflowY: "auto" }}>
                    {loading
                      ? Array(8).fill(0).map((_, i) => (
                          <div key={i} className="vc-table-row" style={{
                            display: "grid", gridTemplateColumns: "1fr 80px 100px 130px 80px",
                            gap: 10, padding: "12px 18px", borderBottom: `1px solid ${T.border}`,
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
                            <div key={i} className="lm-row vc-table-row"
                              style={{
                                display: "grid",
                                gridTemplateColumns: "1fr 80px 100px 130px 80px",
                                gap: 10, padding: "12px 18px",
                                borderBottom: `1px solid ${T.border}`,
                                alignItems: "center",
                                transition: "background .14s",
                                cursor: "pointer",
                                background: rwaTag ? "rgba(232,160,0,.018)" : "transparent",
                                animation: `slideIn .2s ease ${Math.min(i*.02,.3)}s both`,
                              }}
                              onClick={() => setSelectedVCRound(selectedVCRound?.name === r.name ? null : r)}
                              onMouseEnter={(e) => { e.currentTarget.style.background = "rgba(0,0,0,0.02)"; }}
                              onMouseLeave={(e) => { e.currentTarget.style.background = rwaTag ? "rgba(232,160,0,.018)" : "transparent"; }}
                            >

                              {/* Project */}
                              <div>
                                <div style={{ display: "flex", alignItems: "center", gap: 7, marginBottom: 2 }}>
                                  <span style={{ fontSize: 12, fontWeight: 700, color: T.primary, fontFamily: FONTS.display }}>
                                    {r.name}
                                  </span>
                                </div>
                                <div style={{ fontSize: 9, color: T.t3, fontFamily: FONTS.body, marginTop: 2 }}>
                                  {r.sector !== "—" ? r.sector : r.category}
                                </div>
                              </div>

                              {/* Round - redesign style */}
                              <div className="vc-col-round" style={{ textAlign: "center" }}>
                                <span style={{
                                  fontFamily: FONTS.display, fontSize: 8, fontWeight: 700, letterSpacing: "0.08em",
                                  padding: "3px 7px", borderRadius: 3, border: `1px solid ${T.borderMd}`,
                                  color: T.t2, textAlign: "center",
                                }}>
                                  {r.round || "—"}
                                </span>
                              </div>

                              {/* Amount */}
                              <div style={{ textAlign: "right" }}>
                                <span style={{ fontSize: 13, fontWeight: 500, fontFamily: FONTS.mono, color: r.amount ? T.green : T.muted }}>
                                  {r.amount ? fmt.amount(r.amount) : "—"}
                                </span>
                              </div>

                              {/* Lead */}
                              <div className="vc-col-lead" style={{ fontSize: 10, color: T.t2, fontFamily: FONTS.body,
                                overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                                {lead}
                              </div>

                              {/* Date - redesign style */}
                              <div className="vc-col-date-header" style={{ textAlign: "right", fontSize: 9, color: T.t3, fontFamily: FONTS.mono }}>
                                {fmt.dateRelative(r.date)}
                              </div>
                            </div>
                          );
                        })
                    }
                  </div>

                  {/* Data Disclaimer */}
                  <div style={{
                    padding: '10px 18px',
                    borderTop: '1px solid rgba(255,255,255,0.05)',
                    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                    fontSize: '9px', color: 'rgba(148,163,184,0.45)', letterSpacing: '0.06em'
                  }}>
                    <span>
                      Source: DefiLlama Raises API · CryptoRank ·
                      Deal amounts reflect reported figures and may be estimates.
                      CometCloud does not verify individual deal terms.
                    </span>
                    <span>Data refreshes every 30 minutes</span>
                  </div>
                </div>
            </div>}

            {/* ══ MACRO EVENTS ═════════════════════════════ */}
            <div style={{ marginTop: 24, marginBottom: 24 }}>
              <div style={{ display: "flex", alignItems: "baseline", gap: 12, marginBottom: 16, paddingBottom: 10, borderBottom: `1px solid rgba(37,99,235,0.10)` }}>
                <span style={{ fontFamily: FONTS.display, fontSize: 11, fontWeight: 700, letterSpacing: "0.12em", color: T.t2, textTransform: "uppercase" }}>
                  Macro Events
                </span>
                <span style={{ fontFamily: FONTS.mono, fontSize: 8, color: T.t3, opacity: 0.45 }}>
                  Institutional &amp; regulatory
                </span>
              </div>
              <div>
                {macroEvents.length === 0 ? null : macroEvents.map((ev, i) => {
                  const cfg = EV_TYPE[ev.type] || EV_TYPE.protocol;
                  const isHigh = ev.impact === "HIGH";
                  return (
                    <div key={ev.id} style={{
                      display: "flex", gap: 16, paddingTop: 14, paddingBottom: 14,
                      borderBottom: `1px solid rgba(37,99,235,0.07)`,
                      animation: `fadeUp .3s ease ${i*.05}s both`,
                    }}>
                      {/* Thin color accent left */}
                      <div style={{ width: 2, flexShrink: 0, background: cfg.color, borderRadius: 1, opacity: 0.55, alignSelf: "stretch" }} />
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ display: "flex", alignItems: "baseline", gap: 8, marginBottom: 5 }}>
                          <span style={{ fontFamily: FONTS.mono, fontSize: 8, fontWeight: 700, letterSpacing: "0.10em", color: cfg.color, textTransform: "uppercase" }}>
                            {cfg.label}
                          </span>
                          {isHigh && <span style={{ fontFamily: FONTS.mono, fontSize: 8, color: T.red, letterSpacing: "0.06em" }}>· HIGH</span>}
                          <span style={{ fontFamily: FONTS.mono, fontSize: 8, color: T.t3, opacity: 0.5, marginLeft: "auto" }}>
                            {ev.source} · {ev.date}
                          </span>
                        </div>
                        <div style={{ fontFamily: FONTS.display, fontSize: 13, fontWeight: 600, color: T.t1, letterSpacing: "-0.01em", lineHeight: 1.4, marginBottom: 5 }}>
                          {ev.title}
                        </div>
                        <div style={{ fontFamily: FONTS.body, fontSize: 11, color: T.t3, lineHeight: 1.55 }}>
                          {ev.description || ev.summary}
                        </div>
                      </div>
                    </div>
                  );
                })}
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
              <div style={{ display: "flex", alignItems: "baseline", gap: 12, marginBottom: 16, paddingBottom: 10, borderBottom: `1px solid rgba(37,99,235,0.10)` }}>
                <span style={{ fontFamily: FONTS.display, fontSize: 11, fontWeight: 700, letterSpacing: "0.12em", color: T.t2, textTransform: "uppercase" }}>
                  On-Chain Listing Pipeline
                </span>
                <span style={{ fontFamily: FONTS.mono, fontSize: 8, color: T.t3, opacity: 0.45 }}>
                  90 days structuring to trade
                </span>
              </div>

              <div className="mobile-pipeline-grid" style={{ display: "grid", gridTemplateColumns: isSection ? "1fr" : "1fr 320px", gap: 40, marginTop: 12 }}>
                {/* Left - Step list */}
                <div>
                  {[
                    { step: "01", title: "Asset Structuring", desc: "Legal wrapper, SPV design, regulatory alignment (SFC / MAS)", color: T.violet },
                    { step: "02", title: "Tokenization", desc: "Smart contract deployment, ERC-1400 / ERC-3643 compliance standards", color: T.indigo },
                    { step: "03", title: "Exchange Listing", desc: "CEX: OSL, HashKey · DEX: Uniswap V3, Orca (Solana)", color: T.blue },
                    { step: "04", title: "Liquidity & Reporting", desc: "Market maker onboarding, daily NAV on-chain, automated reporting", color: T.cyan },
                  ].map((item, i) => (
                    <div key={i} style={{ display: "flex", gap: 20, paddingBottom: i < 3 ? 20 : 0, paddingTop: i > 0 ? 4 : 0 }}>
                      <div style={{
                        fontFamily: FONTS.mono, fontSize: 11, fontWeight: 400,
                        color: item.color, opacity: 0.55, flexShrink: 0,
                        width: 24, paddingTop: 2,
                      }}>
                        {item.step}
                      </div>
                      <div style={{ borderLeft: `1px solid ${item.color}28`, paddingLeft: 16 }}>
                        <div style={{ fontFamily: FONTS.display, fontSize: 13, fontWeight: 600, color: T.t1, letterSpacing: "-0.01em", marginBottom: 5 }}>
                          {item.title}
                        </div>
                        <div style={{ fontFamily: FONTS.body, fontSize: 11, color: T.t3, lineHeight: 1.55 }}>
                          {item.desc}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>

                {/* Right - CTA */}
                <div style={{ borderLeft: `2px solid rgba(200,168,75,0.20)`, paddingLeft: 24 }}>
                  <div style={{ fontFamily: FONTS.display, fontSize: 15, fontWeight: 600, color: T.t1, letterSpacing: "-0.01em", marginBottom: 8 }}>
                    List Your Fund On-Chain
                  </div>
                  <div style={{ fontFamily: FONTS.body, fontSize: 12, color: T.t3, marginBottom: 18, lineHeight: 1.6 }}>
                    From structuring to first trade in 90 days
                  </div>
                  <div style={{ marginBottom: 20 }}>
                    {[
                      "SFC-compliant tokenization framework",
                      "Direct access to OSL & HashKey liquidity",
                      "AI-powered portfolio monitoring via Looloomi",
                    ].map((point, i) => (
                      <div key={i} style={{ display: "flex", alignItems: "flex-start", gap: 8, marginBottom: 9 }}>
                        <span style={{ fontFamily: FONTS.mono, fontSize: 9, color: T.green, paddingTop: 1 }}>›</span>
                        <span style={{ fontFamily: FONTS.body, fontSize: 11, color: T.t2, lineHeight: 1.5 }}>{point}</span>
                      </div>
                    ))}
                  </div>
                  <button style={{
                    background: "transparent",
                    color: T.amber,
                    border: `1px solid rgba(200,168,75,0.35)`,
                    padding: "8px 18px", borderRadius: 4,
                    fontSize: 11, fontWeight: 600, fontFamily: FONTS.mono,
                    cursor: "pointer", letterSpacing: "0.04em",
                    transition: "border-color .15s, color .15s",
                  }}
                  onMouseEnter={(e) => { e.currentTarget.style.borderColor = "rgba(200,168,75,0.70)"; e.currentTarget.style.color = "#E8C563"; }}
                  onMouseLeave={(e) => { e.currentTarget.style.borderColor = "rgba(200,168,75,0.35)"; e.currentTarget.style.color = T.amber; }}
                  >
                    Schedule a Consultation →
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

      {/* VC Funding Round Detail - BottomSheet */}
      <BottomSheet isOpen={!!selectedVCRound} onClose={() => setSelectedVCRound(null)}>
        {selectedVCRound && (
          <div>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 16 }}>
              <div>
                <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                  <h3 style={{ fontFamily: FONTS.display, fontSize: 18, fontWeight: 700, color: T.primary, margin: 0 }}>
                    {selectedVCRound.name}
                  </h3>
                  {isRWA(selectedVCRound) && (
                    <span style={{ padding: "4px 10px", borderRadius: 4, fontSize: 12, fontWeight: 600, background: "rgba(232,160,0,.12)", color: T.amber }}>
                      RWA
                    </span>
                  )}
                  <span style={{
                    padding: "4px 10px", borderRadius: 4, fontSize: 12, fontWeight: 600,
                    background: catStyle(selectedVCRound.category).bg, color: catStyle(selectedVCRound.category).text,
                  }}>
                    {selectedVCRound.round || "—"}
                  </span>
                </div>
                <div style={{ fontSize: 12, color: T.secondary, marginTop: 6 }}>
                  {selectedVCRound.sector !== "—" ? selectedVCRound.sector : selectedVCRound.category}
                </div>
              </div>
              <div style={{ textAlign: "right" }}>
                <div style={{ fontSize: 10, color: T.muted, marginBottom: 4 }}>Amount</div>
                <div style={{ fontSize: 20, fontWeight: 600, color: T.green, fontFamily: FONTS.mono, userSelect: "none" }}>
                  {selectedVCRound.amount ? fmt.amount(selectedVCRound.amount) : "Undisclosed"}
                </div>
              </div>
            </div>

            {selectedVCRound.chains?.length > 0 && (
              <div style={{ marginBottom: 16 }}>
                <div style={{ fontSize: 10, color: T.muted, letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 8 }}>
                  Chains
                </div>
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                  {selectedVCRound.chains.map((chain, i) => (
                    <span key={i} style={{ fontSize: 12, padding: "4px 8px", background: "rgba(68,114,255,.1)", borderRadius: 4, color: T.blue }}>
                      {chain}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {selectedVCRound.leadInvestors?.length > 0 && (
              <div style={{ marginBottom: 16, padding: 12, background: "rgba(68,114,255,.05)", borderRadius: 8, border: `1px solid ${T.blue}30` }}>
                <div style={{ fontSize: 10, color: T.blue, letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 8 }}>
                  Lead Investor{selectedVCRound.leadInvestors.length > 1 ? "s" : ""}
                </div>
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                  {selectedVCRound.leadInvestors.map((inv, i) => (
                    <span key={i} style={{ fontSize: 13, fontWeight: 600, color: T.primary }}>
                      {inv}
                    </span>
                  ))}
                </div>
              </div>
            )}

            <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", gap: 12, paddingTop: 16, borderTop: `1px solid ${T.border}` }}>
              <div>
                <div style={{ fontSize: 10, color: T.muted, marginBottom: 4 }}>Date</div>
                <div style={{ fontSize: 14, fontWeight: 600, color: T.primary, fontFamily: FONTS.mono }}>
                  {selectedVCRound.dateStr || fmt.dateRelative(selectedVCRound.date)}
                </div>
              </div>
              <div>
                <div style={{ fontSize: 10, color: T.muted, marginBottom: 4 }}>Category</div>
                <div style={{ fontSize: 14, fontWeight: 600, color: T.cyan, fontFamily: FONTS.mono }}>
                  {selectedVCRound.category}
                </div>
              </div>
            </div>
          </div>
        )}
      </BottomSheet>
    </div>
  );
}
