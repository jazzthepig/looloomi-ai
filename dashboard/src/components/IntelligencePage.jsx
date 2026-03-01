import { useState, useEffect, useCallback, useRef } from "react";
import {
  TrendingUp, TrendingDown, Activity, RefreshCw,
  ExternalLink, Wifi, WifiOff, Zap, Building2,
  DollarSign, Globe, ChevronRight, Calendar,
  ArrowUpRight, Users, BarChart2, AlertCircle,
  Newspaper, Filter, ChevronDown
} from "lucide-react";

/* ─── Design Tokens (same as MarketDashboard) ────────────────────── */
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

const API_BASE = "/api/v1";

/* ─── CSS ────────────────────────────────────────────────────────── */
const CSS = `
  @import url('https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=DM+Sans:wght@300;400;500&family=JetBrains+Mono:wght@400;500&display=swap');

  .intel-card {
    background: rgba(18,17,43,0.85);
    border: 1px solid #2A2850;
    border-radius: 12px;
    backdrop-filter: blur(16px);
    transition: border-color 0.2s, transform 0.15s;
  }
  .intel-card:hover { border-color: #3D3A70; }

  .raise-row {
    transition: background 0.15s, transform 0.15s;
    cursor: pointer;
  }
  .raise-row:hover {
    background: rgba(79,110,247,0.06) !important;
    transform: translateX(2px);
  }

  .event-item {
    transition: background 0.15s;
    cursor: pointer;
  }
  .event-item:hover { background: rgba(79,110,247,0.04); }

  .nav-tab {
    cursor: pointer;
    transition: all 0.2s;
    border: none;
    outline: none;
    background: none;
  }

  @keyframes fadeUp {
    from { opacity: 0; transform: translateY(10px); }
    to   { opacity: 1; transform: translateY(0); }
  }
  @keyframes pulse { 0%,100% { opacity:1; } 50% { opacity:0.4; } }
  @keyframes slideIn {
    from { opacity:0; transform: translateX(-6px); }
    to   { opacity:1; transform: translateX(0); }
  }
  @keyframes breathe {
    0%,100% { opacity:0.35; transform:scale(1); }
    50% { opacity:0.5; transform:scale(1.06); }
  }

  .fade-up { animation: fadeUp 0.35s ease forwards; }
  .slide-in { animation: slideIn 0.25s ease forwards; }
  .pulse-dot { animation: pulse 2s infinite; }

  .turrell-ambient {
    position: fixed; inset: 0; pointer-events: none; z-index: 0; overflow: hidden;
  }
  .orb {
    position: absolute; border-radius: 50%; filter: blur(80px);
  }
  .orb-1 {
    width:600px; height:600px;
    background: radial-gradient(circle, rgba(111,2,172,0.15) 0%, transparent 70%);
    top:-200px; left:-100px;
    animation: breathe 45s ease-in-out infinite;
  }
  .orb-2 {
    width:500px; height:500px;
    background: radial-gradient(circle, rgba(63,68,199,0.12) 0%, transparent 70%);
    top:10%; right:-150px;
    animation: breathe 55s ease-in-out infinite 15s;
  }
  .orb-3 {
    width:350px; height:350px;
    background: radial-gradient(circle, rgba(255,45,120,0.07) 0%, transparent 70%);
    bottom:0; left:35%;
    animation: breathe 65s ease-in-out infinite 28s;
  }

  .skeleton {
    background: linear-gradient(90deg, #1A1940 25%, #2A2850 50%, #1A1940 75%);
    background-size: 200% 100%;
    animation: shimmer 1.5s infinite;
    border-radius: 4px;
  }
  @keyframes shimmer {
    0% { background-position: -200% center; }
    100% { background-position: 200% center; }
  }

  .badge {
    display: inline-flex; align-items: center;
    padding: 2px 8px; border-radius: 4px;
    font-size: 10px; font-weight: 600;
    letter-spacing: 0.05em; text-transform: uppercase;
    font-family: 'DM Sans', sans-serif;
  }

  .iframe-container {
    position: relative;
    width: 100%;
    height: calc(100vh - 80px);
    border-radius: 12px;
    overflow: hidden;
    border: 1px solid #2A2850;
  }
  .iframe-container iframe {
    width: 100%;
    height: 100%;
    border: none;
    background: white;
  }
`;

/* ─── Helpers ────────────────────────────────────────────────────── */
const fmt = {
  amount: (v) => {
    if (!v && v !== 0) return "—";
    if (v >= 1000) return `$${(v/1000).toFixed(1)}B`;
    if (v >= 1)    return `$${v.toFixed(1)}M`;
    return `$${v.toFixed(2)}M`;
  },
  date: (ts) => {
    if (!ts) return "—";
    const d = new Date(ts * 1000);
    return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
  },
  dateRelative: (ts) => {
    if (!ts) return "—";
    const now = Date.now() / 1000;
    const diff = now - ts;
    if (diff < 86400)   return `${Math.floor(diff / 3600)}h ago`;
    if (diff < 604800)  return `${Math.floor(diff / 86400)}d ago`;
    if (diff < 2592000) return `${Math.floor(diff / 604800)}w ago`;
    return fmt.date(ts);
  },
};

const CATEGORY_COLORS = {
  "RWA":        { bg: "rgba(212,175,55,0.12)",  text: "#D4AF37" },
  "DeFi":       { bg: "rgba(79,110,247,0.12)",  text: "#4F6EF7" },
  "AI":         { bg: "rgba(255,45,120,0.10)",  text: "#FF2D78" },
  "Infrastructure": { bg: "rgba(45,212,160,0.10)", text: "#2DD4A0" },
  "Centralized Exchange": { bg: "rgba(156,163,175,0.10)", text: "#9893C4" },
  "NFT":        { bg: "rgba(147,51,234,0.10)",  text: "#A855F7" },
  "Gaming":     { bg: "rgba(234,179,8,0.10)",   text: "#EAB308" },
};

const getCategoryColor = (cat) =>
  CATEGORY_COLORS[cat] || { bg: "rgba(255,255,255,0.06)", text: "#9893C4" };

/* ─── RWA News from multiple free sources ───────────────────────── */
// Curated RWA event feed using DeFiLlama raises filtered for RWA
const RWA_KEYWORDS = ["rwa", "real world asset", "tokeniz", "treasury", "bond", "credit",
  "lending", "ondo", "maple", "centrifuge", "goldfinch", "backed", "matrixdock",
  "superstate", "securitize", "polymesh", "chainlink", "oracle"];

const isRWARelated = (item) => {
  const text = `${item.name} ${item.sector} ${item.category}`.toLowerCase();
  return RWA_KEYWORDS.some(kw => text.includes(kw));
};

/* ─── RWA Key Events (curated static + dynamic) ─────────────────── */
const RWA_MACRO_EVENTS = [
  {
    id: "blackrock-buidl",
    date: "Mar 2024",
    title: "BlackRock Launches BUIDL on Ethereum",
    summary: "BlackRock's tokenized money market fund reaches $500M+ AUM within weeks, validating institutional RWA demand.",
    type: "institutional", impact: "high", source: "BlackRock"
  },
  {
    id: "franklin-benji",
    date: "Oct 2023",
    title: "Franklin Templeton Expands BENJI to Polygon",
    summary: "Franklin Templeton's on-chain money market fund expands to Polygon, bringing tokenized US Treasuries to new chain.",
    type: "institutional", impact: "high", source: "Franklin Templeton"
  },
  {
    id: "hk-rwa-framework",
    date: "Nov 2023",
    title: "Hong Kong SFC Issues RWA Tokenization Guidance",
    summary: "SFC releases comprehensive framework for tokenized securities, positioning HK as Asia's RWA hub.",
    type: "regulatory", impact: "high", source: "Hong Kong SFC"
  },
  {
    id: "ondo-flux",
    date: "Jan 2024",
    title: "Ondo Finance Launches Flux Finance",
    summary: "Ondo's DeFi lending protocol enables borrowing against tokenized US Treasury positions.",
    type: "protocol", impact: "medium", source: "Ondo Finance"
  },
  {
    id: "mas-project-guardian",
    date: "Jun 2023",
    title: "MAS Project Guardian — $100M Tokenized Bonds",
    summary: "Singapore MAS pilots institutional-grade tokenized bonds with DBS, JPMorgan, SBI in Project Guardian.",
    type: "regulatory", impact: "high", source: "MAS Singapore"
  },
  {
    id: "chainlink-ccip",
    date: "Aug 2023",
    title: "Chainlink CCIP Goes Live — RWA Cross-Chain Bridge",
    summary: "Chainlink's Cross-Chain Interoperability Protocol enables RWA movement across blockchains, critical infrastructure for institutional adoption.",
    type: "infrastructure", impact: "high", source: "Chainlink"
  },
];

const EVENT_TYPE_CONFIG = {
  institutional: { color: T.amber,     label: "Institutional", icon: Building2 },
  regulatory:    { color: T.blue,      label: "Regulatory",    icon: Globe },
  protocol:      { color: T.green,     label: "Protocol",      icon: Zap },
  infrastructure:{ color: "#9945FF",   label: "Infrastructure",icon: Activity },
  funding:       { color: T.turrellPink, label: "Funding",     icon: DollarSign },
};

const IMPACT_COLORS = {
  high:   { bg: "rgba(245,71,106,0.12)", text: T.red },
  medium: { bg: "rgba(212,175,55,0.10)", text: T.amber },
  low:    { bg: "rgba(45,212,160,0.08)", text: T.green },
};

/* ═══════════════════════════════════════════════════════════════════
   MAIN INTELLIGENCE PAGE
═══════════════════════════════════════════════════════════════════ */
export default function IntelligencePage({ activeTab, setActiveTab }) {
  const [raises, setRaises]           = useState([]);
  const [rwaRaises, setRwaRaises]     = useState([]);
  const [loading, setLoading]         = useState(true);
  const [raisesFilter, setRaisesFilter] = useState("All");
  const [lastUpdate, setLastUpdate]   = useState(null);
  const [stats, setStats]             = useState(null);

  /* ── CSS injection ── */
  useEffect(() => {
    const id = "looloomi-intel-css";
    if (!document.getElementById(id)) {
      const s = document.createElement("style");
      s.id = id; s.textContent = CSS;
      document.head.appendChild(s);
    }
  }, []);

  /* ── Fetch raises from backend ── */
  const fetchRaises = useCallback(async () => {
    try {
      const r = await fetch(`${API_BASE}/vc/funding-rounds?limit=100`);
      const json = await r.json();
      const all = json.data || [];

      // Sort by date desc
      all.sort((a, b) => (b.date || 0) - (a.date || 0));

      setRaises(all);
      setLastUpdate(new Date());

      // Filter RWA-related
      const rwa = all.filter(isRWARelated);
      setRwaRaises(rwa);

      // Compute stats
      const recentAll  = all.filter(r => r.date && (Date.now()/1000 - r.date) < 90 * 86400);
      const totalAmt   = recentAll.reduce((s, r) => s + (r.amount || 0), 0);
      const rwaAmt     = rwa.filter(r => r.date && (Date.now()/1000 - r.date) < 90 * 86400)
                            .reduce((s, r) => s + (r.amount || 0), 0);
      const topVCs     = {};
      recentAll.forEach(r => {
        [...(r.leadInvestors||[]), ...(r.otherInvestors||[])].forEach(v => {
          topVCs[v] = (topVCs[v] || 0) + 1;
        });
      });
      const topVC = Object.entries(topVCs).sort((a,b) => b[1]-a[1])[0];

      setStats({
        totalDeals:  recentAll.length,
        totalAmount: totalAmt,
        rwaAmount:   rwaAmt,
        rwaDeals:    rwa.filter(r => r.date && (Date.now()/1000 - r.date) < 90 * 86400).length,
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

  /* ── Filter options ── */
  const FILTERS = ["All", "RWA", "DeFi", "AI", "Infrastructure"];

  const filteredRaises = raises.filter(r => {
    if (raisesFilter === "All") return true;
    if (raisesFilter === "RWA") return isRWARelated(r);
    return (r.category || "").toLowerCase().includes(raisesFilter.toLowerCase()) ||
           (r.categoryGroup || "").toLowerCase().includes(raisesFilter.toLowerCase());
  });

  /* ── Render ── */
  return (
    <div style={{ position: "relative", minHeight: "100vh", background: T.void }}>
      <div className="turrell-ambient">
        <div className="orb orb-1" /><div className="orb orb-2" /><div className="orb orb-3" />
      </div>

      <div style={{ position: "relative", zIndex: 1, maxWidth: 1400, margin: "0 auto", padding: "0 24px 48px" }}>

        {/* ── Top Nav ── */}
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
                <button key={tab} className="nav-tab"
                  onClick={() => setActiveTab(tab)}
                  style={{
                    padding: "6px 16px", borderRadius: 6, fontSize: 12,
                    fontFamily: "'DM Sans', sans-serif", fontWeight: 500,
                    background: activeTab === tab ? `${T.blue}22` : "transparent",
                    border: `1px solid ${activeTab === tab ? T.blue : T.border}`,
                    color: activeTab === tab ? T.blue : T.secondary,
                  }}>
                  {tab}
                </button>
              ))}
            </div>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            {lastUpdate && (
              <span style={{ fontSize: 11, color: T.muted, fontFamily: "'JetBrains Mono', monospace" }}>
                {lastUpdate.toLocaleTimeString()}
              </span>
            )}
            <button onClick={fetchRaises}
              style={{ display: "flex", alignItems: "center", gap: 6, padding: "6px 12px",
                borderRadius: 6, border: `1px solid ${T.border}`,
                background: "transparent", color: T.secondary,
                cursor: "pointer", fontSize: 11, fontFamily: "'DM Sans', sans-serif" }}>
              <RefreshCw size={12} /> Refresh
            </button>
          </div>
        </div>

        {/* ══ INTELLIGENCE TAB ══════════════════════════════════════ */}
        {activeTab === "Intelligence" && (
          <div>
            {/* ── Stats Row ── */}
            <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12, margin: "20px 0" }}>
              {[
                { label: "90d Total Raised", value: stats ? fmt.amount(stats.totalAmount) : "—", sub: `${stats?.totalDeals || "—"} deals`, color: T.blue },
                { label: "RWA Sector (90d)", value: stats ? fmt.amount(stats.rwaAmount) : "—", sub: `${stats?.rwaDeals || "—"} RWA deals`, color: T.amber },
                { label: "Most Active VC", value: stats?.topVC || "—", sub: `${stats?.topVCDeals || "—"} deals`, color: T.green },
                { label: "Data Source", value: "DeFiLlama", sub: "Raises API · Live", color: T.turrellPink },
              ].map((s, i) => (
                <div key={i} className="intel-card" style={{ padding: 16,
                  animation: `fadeUp 0.3s ease ${i*0.08}s both` }}>
                  <div style={{ fontSize: 10, color: T.muted, letterSpacing: "0.1em",
                    textTransform: "uppercase", marginBottom: 8 }}>{s.label}</div>
                  <div style={{ fontSize: 22, fontWeight: 700, color: s.color,
                    fontFamily: "'JetBrains Mono', monospace", marginBottom: 4 }}>{s.value}</div>
                  <div style={{ fontSize: 11, color: T.muted }}>{s.sub}</div>
                </div>
              ))}
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "1fr 380px", gap: 16 }}>

              {/* ── VC Funding Rounds ── */}
              <div>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
                  <div style={{ fontSize: 11, color: T.muted, letterSpacing: "0.1em",
                    textTransform: "uppercase", display: "flex", alignItems: "center", gap: 8 }}>
                    <DollarSign size={12} /> VC Funding Rounds
                  </div>
                  <div style={{ display: "flex", gap: 6 }}>
                    {FILTERS.map(f => (
                      <button key={f}
                        onClick={() => setRaisesFilter(f)}
                        style={{
                          padding: "4px 10px", borderRadius: 4, fontSize: 11,
                          fontFamily: "'DM Sans', sans-serif", cursor: "pointer",
                          background: raisesFilter === f ? `${T.blue}20` : "transparent",
                          border: `1px solid ${raisesFilter === f ? T.blue : T.border}`,
                          color: raisesFilter === f ? T.blue : T.muted,
                        }}>
                        {f}
                      </button>
                    ))}
                  </div>
                </div>

                <div className="intel-card" style={{ overflow: "hidden" }}>
                  {/* Table header */}
                  <div style={{ display: "grid",
                    gridTemplateColumns: "2fr 90px 100px 120px 80px",
                    gap: 12, padding: "10px 16px", borderBottom: `1px solid ${T.border}`,
                    fontSize: 10, color: T.muted, letterSpacing: "0.1em", textTransform: "uppercase" }}>
                    <span>Project</span>
                    <span>Round</span>
                    <span style={{ textAlign: "right" }}>Amount</span>
                    <span>Lead Investor</span>
                    <span style={{ textAlign: "right" }}>Date</span>
                  </div>

                  {/* Rows */}
                  <div style={{ maxHeight: 520, overflowY: "auto" }}>
                    {loading ? (
                      Array(8).fill(0).map((_, i) => (
                        <div key={i} style={{ display: "grid",
                          gridTemplateColumns: "2fr 90px 100px 120px 80px",
                          gap: 12, padding: "12px 16px", borderBottom: `1px solid ${T.border}`,
                          alignItems: "center" }}>
                          {[120, 60, 60, 90, 60].map((w, j) => (
                            <div key={j} className="skeleton" style={{ height: 12, width: w }} />
                          ))}
                        </div>
                      ))
                    ) : filteredRaises.slice(0, 50).map((r, i) => {
                      const catColor = getCategoryColor(r.category);
                      const lead = r.leadInvestors?.[0] || r.otherInvestors?.[0] || "—";
                      const isRWA = isRWARelated(r);

                      return (
                        <div key={i} className="raise-row"
                          style={{ display: "grid",
                            gridTemplateColumns: "2fr 90px 100px 120px 80px",
                            gap: 12, padding: "12px 16px",
                            borderBottom: `1px solid ${T.border}`,
                            alignItems: "center",
                            background: isRWA ? "rgba(212,175,55,0.02)" : "transparent",
                            animation: `slideIn 0.2s ease ${Math.min(i*0.02, 0.3)}s both`,
                          }}>

                          {/* Project */}
                          <div>
                            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                              <span style={{ fontSize: 13, fontWeight: 600, color: T.primary,
                                fontFamily: "'Syne', sans-serif" }}>{r.name}</span>
                              {isRWA && (
                                <span className="badge"
                                  style={{ background: "rgba(212,175,55,0.12)", color: T.amber }}>
                                  RWA
                                </span>
                              )}
                            </div>
                            <div style={{ fontSize: 11, color: T.muted, marginTop: 2,
                              maxWidth: 240, overflow: "hidden", textOverflow: "ellipsis",
                              whiteSpace: "nowrap" }}>
                              {r.sector?.slice(0, 60) || r.category}
                            </div>
                          </div>

                          {/* Round */}
                          <div>
                            <span className="badge" style={{ background: catColor.bg, color: catColor.text }}>
                              {r.round || "—"}
                            </span>
                          </div>

                          {/* Amount */}
                          <div style={{ textAlign: "right" }}>
                            <span style={{ fontSize: 14, fontWeight: 600,
                              fontFamily: "'JetBrains Mono', monospace",
                              color: r.amount ? T.green : T.muted }}>
                              {r.amount ? fmt.amount(r.amount) : "Undisclosed"}
                            </span>
                          </div>

                          {/* Lead investor */}
                          <div style={{ fontSize: 11, color: T.secondary,
                            overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                            {lead}
                          </div>

                          {/* Date */}
                          <div style={{ textAlign: "right", fontSize: 11, color: T.muted,
                            fontFamily: "'JetBrains Mono', monospace" }}>
                            {fmt.dateRelative(r.date)}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              </div>

              {/* ── RWA Key Events Sidebar ── */}
              <div>
                <div style={{ fontSize: 11, color: T.muted, letterSpacing: "0.1em",
                  textTransform: "uppercase", marginBottom: 12,
                  display: "flex", alignItems: "center", gap: 8 }}>
                  <Zap size={12} /> RWA Infrastructure Events
                </div>

                <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                  {/* Live RWA raises */}
                  {rwaRaises.slice(0, 4).map((r, i) => (
                    <div key={i} className="intel-card event-item"
                      style={{ padding: 14, animation: `fadeUp 0.3s ease ${i*0.06}s both` }}>
                      <div style={{ display: "flex", justifyContent: "space-between",
                        alignItems: "flex-start", marginBottom: 8 }}>
                        <span className="badge"
                          style={{ background: "rgba(212,175,55,0.12)", color: T.amber }}>
                          RWA Funding
                        </span>
                        <span style={{ fontSize: 10, color: T.muted,
                          fontFamily: "'JetBrains Mono', monospace" }}>
                          {fmt.dateRelative(r.date)}
                        </span>
                      </div>
                      <div style={{ fontSize: 13, fontWeight: 600, color: T.primary,
                        fontFamily: "'Syne', sans-serif", marginBottom: 4 }}>
                        {r.name} — {r.round}
                      </div>
                      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <span style={{ fontSize: 15, fontWeight: 700, color: T.green,
                          fontFamily: "'JetBrains Mono', monospace" }}>
                          {r.amount ? fmt.amount(r.amount) : "Undisclosed"}
                        </span>
                        {r.leadInvestors?.[0] && (
                          <span style={{ fontSize: 10, color: T.muted }}>
                            led by {r.leadInvestors[0]}
                          </span>
                        )}
                      </div>
                    </div>
                  ))}

                  {/* Divider */}
                  <div style={{ fontSize: 10, color: T.muted, letterSpacing: "0.1em",
                    textTransform: "uppercase", padding: "4px 0",
                    display: "flex", alignItems: "center", gap: 8 }}>
                    <Globe size={10} /> Macro Events
                  </div>

                  {/* Curated macro events */}
                  {RWA_MACRO_EVENTS.slice(0, 4).map((ev, i) => {
                    const cfg = EVENT_TYPE_CONFIG[ev.type] || EVENT_TYPE_CONFIG.protocol;
                    const imp = IMPACT_COLORS[ev.impact] || IMPACT_COLORS.medium;
                    return (
                      <div key={ev.id} className="intel-card event-item"
                        style={{ padding: 14,
                          animation: `fadeUp 0.3s ease ${(i+4)*0.06}s both`,
                          borderLeft: `2px solid ${cfg.color}` }}>
                        <div style={{ display: "flex", justifyContent: "space-between",
                          alignItems: "center", marginBottom: 6 }}>
                          <span className="badge"
                            style={{ background: `${cfg.color}18`, color: cfg.color }}>
                            {cfg.label}
                          </span>
                          <span className="badge" style={{ background: imp.bg, color: imp.text }}>
                            {ev.impact} impact
                          </span>
                        </div>
                        <div style={{ fontSize: 12, fontWeight: 600, color: T.primary,
                          fontFamily: "'Syne', sans-serif", marginBottom: 4, lineHeight: 1.4 }}>
                          {ev.title}
                        </div>
                        <div style={{ fontSize: 11, color: T.secondary, lineHeight: 1.5 }}>
                          {ev.summary}
                        </div>
                        <div style={{ fontSize: 10, color: T.muted, marginTop: 6 }}>
                          {ev.source} · {ev.date}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>
          </div>
        )}

        {/* ══ EST GP TAB ════════════════════════════════════════════ */}
        {activeTab === "Quant GP" && (
          <div style={{ marginTop: 20 }}>
            {/* Header */}
            <div style={{ display: "flex", justifyContent: "space-between",
              alignItems: "center", marginBottom: 16 }}>
              <div>
                <div style={{ fontSize: 18, fontWeight: 700, color: T.primary,
                  fontFamily: "'Syne', sans-serif", marginBottom: 4 }}>
                  EST Alpha — Quantitative GP
                </div>
                <div style={{ fontSize: 12, color: T.muted }}>
                  Core General Partner · CometCloud AI Fund-of-Funds Strategy
                </div>
              </div>
              <div style={{ display: "flex", gap: 10 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 6, padding: "8px 14px",
                  borderRadius: 8, border: `1px solid ${T.amber}44`,
                  background: "rgba(212,175,55,0.06)" }}>
                  <div style={{ width: 6, height: 6, borderRadius: "50%", background: T.amber }}
                    className="pulse-dot" />
                  <span style={{ fontSize: 11, color: T.amber,
                    fontFamily: "'JetBrains Mono', monospace" }}>VERIFIED GP</span>
                </div>
                <a href="https://est.cc" target="_blank" rel="noopener noreferrer"
                  style={{ display: "flex", alignItems: "center", gap: 6, padding: "8px 14px",
                    borderRadius: 8, border: `1px solid ${T.border}`,
                    background: "transparent", color: T.secondary,
                    textDecoration: "none", fontSize: 11,
                    fontFamily: "'DM Sans', sans-serif" }}>
                  <ExternalLink size={12} /> Open in New Tab
                </a>
              </div>
            </div>

            {/* Key metrics bar */}
            <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)",
              gap: 10, marginBottom: 16 }}>
              {[
                { label: "Strategy",      value: "Quantitative FoF",    color: T.blue },
                { label: "Focus",         value: "Crypto & RWA",        color: T.amber },
                { label: "Role in FoF",   value: "Core GP",             color: T.green },
                { label: "HQ",            value: "Hong Kong",           color: T.turrellPink },
              ].map((m, i) => (
                <div key={i} className="intel-card" style={{ padding: "12px 16px" }}>
                  <div style={{ fontSize: 10, color: T.muted, letterSpacing: "0.1em",
                    textTransform: "uppercase", marginBottom: 6 }}>{m.label}</div>
                  <div style={{ fontSize: 14, fontWeight: 600, color: m.color,
                    fontFamily: "'Syne', sans-serif" }}>{m.value}</div>
                </div>
              ))}
            </div>

            {/* iframe */}
            <div className="iframe-container">
              <iframe
                src="https://est.cc"
                title="EST Alpha — Quantitative GP"
                allow="fullscreen"
                sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-popups-to-escape-sandbox"
              />
            </div>

            {/* Footer note */}
            <div style={{ marginTop: 12, fontSize: 11, color: T.muted, textAlign: "center" }}>
              EST Alpha is CometCloud AI's core quantitative General Partner.
              This page is for institutional LP due diligence purposes.
            </div>
          </div>
        )}

      </div>
    </div>
  );
}
