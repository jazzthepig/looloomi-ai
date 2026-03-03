import { useState, useEffect, useCallback } from "react";
import {
  RefreshCw, ExternalLink, Zap, Building2,
  DollarSign, Globe, Activity, Users
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

/* ─── Curated macro events ───────────────────────────────────────────── */
const MACRO_EVENTS = [
  { id: "buidl", date: "Mar 2024", title: "BlackRock Launches BUIDL on Ethereum", summary: "Tokenized money market fund reaches $500M+ AUM within weeks, validating institutional RWA demand.", type: "institutional", impact: "high", source: "BlackRock" },
  { id: "benji", date: "Oct 2023", title: "Franklin Templeton Expands BENJI to Polygon", summary: "On-chain money market fund brings tokenized US Treasuries to Polygon.", type: "institutional", impact: "high", source: "Franklin Templeton" },
  { id: "hk-sfc", date: "Nov 2023", title: "Hong Kong SFC Issues RWA Tokenization Guidance", summary: "Comprehensive framework for tokenized securities positions HK as Asia's RWA hub.", type: "regulatory", impact: "high", source: "HK SFC" },
  { id: "flux", date: "Jan 2024", title: "Ondo Finance Launches Flux Finance", summary: "DeFi lending protocol enables borrowing against tokenized US Treasury positions.", type: "protocol", impact: "medium", source: "Ondo Finance" },
  { id: "mas", date: "Jun 2023", title: "MAS Project Guardian — $100M Tokenized Bonds", summary: "Singapore MAS pilots institutional-grade tokenized bonds with DBS, JPMorgan, SBI.", type: "regulatory", impact: "high", source: "MAS Singapore" },
  { id: "ccip", date: "Aug 2023", title: "Chainlink CCIP — RWA Cross-Chain Bridge", summary: "Cross-Chain Interoperability Protocol enables RWA movement across blockchains.", type: "infrastructure", impact: "high", source: "Chainlink" },
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
  const [raisesFilter, setRaisesFilter] = useState("All");
  const [lastUpdate, setLastUpdate]     = useState(null);
  const [stats, setStats]               = useState(null);

  useEffect(() => {
    const id = "lm-intel-css";
    if (!document.getElementById(id)) {
      const s = document.createElement("style");
      s.id = id; s.textContent = CSS;
      document.head.appendChild(s);
    }
  }, []);

  const fetchRaises = useCallback(async () => {
    try {
      const r = await fetch(`${API_BASE}/vc/funding-rounds?limit=100`);
      const json = await r.json();
      const raw = json.data || [];

      /* ── Normalize backend fields ── */
      const all = raw.map(r => ({
        name:          r.project  || r.name  || "—",
        round:         r.round_type || r.round || "—",
        // backend sends raw dollars, convert to $M
        amount:        typeof r.amount === "number" ? r.amount / 1e6 : 0,
        // backend sends "2024-04-09" ISO string, convert to unix ts
        date:          r.date ? Math.floor(new Date(r.date).getTime() / 1000) : null,
        leadInvestors: Array.isArray(r.investors) ? r.investors
                     : Array.isArray(r.leadInvestors) ? r.leadInvestors : [],
        category:      r.category || r.sector || "—",
        categoryGroup: r.categoryGroup || r.category || "—",
        sector:        r.sector   || r.category || "—",
      }));

      all.sort((a, b) => (b.date || 0) - (a.date || 0));

      const rwa = all.filter(isRWA);
      setRaises(all);
      setRwaRaises(rwa);
      setLastUpdate(new Date());

      // Stats — 90d window
      const now90 = Date.now() / 1000 - 90 * 86400;
      const recent    = all.filter(r => r.date && r.date > now90);
      const recentRwa = rwa.filter(r => r.date && r.date > now90);

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
    if (raisesFilter === "All") return true;
    if (raisesFilter === "RWA") return isRWA(r);
    return (r.category || "").toLowerCase().includes(raisesFilter.toLowerCase())
        || (r.categoryGroup || "").toLowerCase().includes(raisesFilter.toLowerCase());
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
          {["Market", "Intelligence", "Quant GP"].map(tab => (
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

            {/* Main 2-col layout */}
            <div className="mobile-2col-grid" style={{ display: "grid", gridTemplateColumns: "1fr 360px", gap: 16 }}>

              {/* Left — VC Funding Table */}
              <div>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
                  <Label Icon={DollarSign}>VC Funding Rounds</Label>
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
              <iframe src="https://est.cc" title="EST Alpha — Quantitative GP" allow="fullscreen"
                sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-popups-to-escape-sandbox" />
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
