import { useState, useEffect } from "react";
import {
  RefreshCw, Shield, TrendingUp, DollarSign, Lock,
  Activity, Globe, Zap, ArrowUpRight, ArrowDownRight
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

/* ─── Sample Protocols Data ──────────────────────────────────────────── */
const SAMPLE_PROTOCOLS = [
  {
    id: "proto-001",
    name: "Aave",
    category: "Lending",
    chain: "Multi-chain",
    tvl: 32400000000,
    tvlChange30d: 8.5,
    apy: 4.2,
    apyChange30d: 0.3,
    scores: {
      tvlGrowth: 28,
      security: 24,
      liquidity: 18,
      team: 14,
      innovation: 9,
      total: 93,
    },
    grade: "A",
    auditStatus: "Audited",
    audits: ["Trail of Bits", "OpenZeppelin", "Certora"],
    description: "Leading decentralized lending protocol with multi-chain presence and institutional adoption.",
  },
  {
    id: "proto-002",
    name: "Uniswap",
    category: "DEX",
    chain: "Multi-chain",
    tvl: 18500000000,
    tvlChange30d: 12.3,
    apy: 2.8,
    apyChange30d: -0.1,
    scores: {
      tvlGrowth: 27,
      security: 23,
      liquidity: 19,
      team: 14,
      innovation: 10,
      total: 93,
    },
    grade: "A",
    auditStatus: "Audited",
    audits: ["Trail of Bits", "OpenZeppelin"],
    description: "Dominant AMM DEX with the highest trading volume and deepest liquidity across chains.",
  },
  {
    id: "proto-003",
    name: "MakerDAO",
    category: "Lending",
    chain: "Ethereum",
    tvl: 8200000000,
    tvlChange30d: -2.1,
    apy: 5.8,
    apyChange30d: 0.5,
    scores: {
      tvlGrowth: 20,
      security: 25,
      liquidity: 15,
      team: 15,
      innovation: 8,
      total: 83,
    },
    grade: "B",
    auditStatus: "Audited",
    audits: ["OpenZeppelin", "Runtime Verification"],
    description: "Oldest decentralized stablecoin protocol with proven track record and conservative risk management.",
  },
  {
    id: "proto-004",
    name: "Curve Finance",
    category: "DEX",
    chain: "Multi-chain",
    tvl: 4200000000,
    tvlChange30d: 15.8,
    apy: 3.5,
    apyChange30d: 0.2,
    scores: {
      tvlGrowth: 25,
      security: 22,
      liquidity: 17,
      team: 12,
      innovation: 7,
      total: 83,
    },
    grade: "B",
    auditStatus: "Audited",
    audits: ["Trail of Bits", "ChainSecurity"],
    description: "Specialized stablecoin AMM with concentrated liquidity for low-slippage trades.",
  },
  {
    id: "proto-005",
    name: "Compound",
    category: "Lending",
    chain: "Ethereum",
    tvl: 2800000000,
    tvlChange30d: 5.2,
    apy: 3.9,
    apyChange30d: 0.1,
    scores: {
      tvlGrowth: 22,
      security: 24,
      liquidity: 14,
      team: 14,
      innovation: 8,
      total: 82,
    },
    grade: "B",
    auditStatus: "Audited",
    audits: ["OpenZeppelin", "ChainSecurity"],
    description: "Pioneering algorithmic interest rate protocol with strong institutional trust.",
  },
  {
    id: "proto-006",
    name: "Lido",
    category: "Staking",
    chain: "Multi-chain",
    tvl: 31200000000,
    tvlChange30d: 18.4,
    apy: 4.8,
    apyChange30d: 0.2,
    scores: {
      tvlGrowth: 30,
      security: 21,
      liquidity: 16,
      team: 13,
      innovation: 7,
      total: 87,
    },
    grade: "A",
    auditStatus: "Audited",
    audits: ["MixBytes", "ChainSecurity"],
    description: "Liquid staking solution for ETH with the largest LSD market share.",
  },
  {
    id: "proto-007",
    name: "GMX",
    category: "DEX",
    chain: "Arbitrum",
    tvl: 680000000,
    tvlChange30d: -8.5,
    apy: 8.2,
    apyChange30d: -1.2,
    scores: {
      tvlGrowth: 15,
      security: 19,
      liquidity: 12,
      team: 12,
      innovation: 9,
      total: 67,
    },
    grade: "C",
    auditStatus: "Audited",
    audits: ["ChainSecurity", "Kudelski Security"],
    description: "Decentralized perpetual trading platform with high leverage and unique architecture.",
  },
  {
    id: "proto-008",
    name: "Yearn Finance",
    category: "Yield",
    chain: "Ethereum",
    tvl: 1200000000,
    tvlChange30d: 22.1,
    apy: 6.5,
    apyChange30d: 0.8,
    scores: {
      tvlGrowth: 24,
      security: 18,
      liquidity: 14,
      team: 12,
      innovation: 9,
      total: 77,
    },
    grade: "B",
    auditStatus: "Audited",
    audits: ["Trail of Bits", "OpenZeppelin"],
    description: "Automated yield optimization vault strategy aggregator.",
  },
];

const CATEGORIES = ["All", "Lending", "DEX", "Staking", "Yield"];
const CHAINS = ["All", "Ethereum", "Arbitrum", "Multi-chain"];

/* ─── CSS ────────────────────────────────────────────────────────────── */
const CSS = `
  @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600;700;800&family=Exo+2:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap');

  @keyframes breathe  { 0%,100%{opacity:.28;transform:scale(1) translateY(0)} 50%{opacity:.44;transform:scale(1.06) translateY(-12px)} }
  @keyframes breathe2 { 0%,100%{opacity:.16;transform:scale(1)} 50%{opacity:.30;transform:scale(1.08) translateX(10px)} }
  @keyframes fadeUp   { from{opacity:0;transform:translateY(14px)} to{opacity:1;transform:translateY(0)} }
  @keyframes slideIn  { from{opacity:0;transform:translateX(-8px)} to{opacity:1;transform:translateX(0)} }

  .turrell-wrap { position:fixed;inset:0;pointer-events:none;z-index:0;overflow:hidden; }
  .t-orb { position:absolute;border-radius:50%;filter:blur(100px);mix-blend-mode:screen; }
  .t-orb-1 { width:720px;height:720px;background:radial-gradient(circle,rgba(107,15,204,.20) 0%,transparent 65%);top:-300px;left:-200px;animation:breathe 52s ease-in-out infinite; }
  .t-orb-2 { width:560px;height:560px;background:radial-gradient(circle,rgba(45,53,212,.15) 0%,transparent 65%);top:5%;right:-200px;animation:breathe2 64s ease-in-out infinite 9s; }
  .t-orb-3 { width:380px;height:380px;background:radial-gradient(circle,rgba(0,200,224,.09) 0%,transparent 65%);bottom:0;left:22%;animation:breathe 76s ease-in-out infinite 24s; }
  .t-orb-4 { width:280px;height:280px;background:radial-gradient(circle,rgba(255,16,96,.07) 0%,transparent 65%);bottom:12%;right:8%;animation:breathe2 60s ease-in-out infinite 38s; }

  .lm-card { background:rgba(10,9,24,.82);border:1px solid #1A173A;border-radius:10px;backdrop-filter:blur(20px); }
  .lm-card:hover { border-color:#28244C; }
  .lm-row { transition:background .12s ease;cursor:pointer; }
  .lm-row:hover { background:rgba(68,114,255,.05) !important; }

  .lm-tab { padding:5px 14px;border-radius:5px;font-size:12px;font-weight:500;font-family:'Exo 2',sans-serif;cursor:pointer;outline:none;border:1px solid #1A173A;background:transparent;color:#8880BE;transition:all .18s ease;letter-spacing:.01em; }
  .lm-tab:hover { border-color:#28244C;color:#F0EEFF; }
  .lm-tab.active { border-color:rgba(68,114,255,.5);background:rgba(68,114,255,.10);color:#4472FF; }

  .filter-btn { padding:4px 10px;border-radius:4px;font-size:11px;font-weight:500;font-family:'Exo 2',sans-serif;cursor:pointer;outline:none;border:1px solid #1A173A;background:transparent;color:#3E3A6E;transition:all .15s ease; }
  .filter-btn:hover { border-color:#28244C;color:#8880BE; }
  .filter-btn.active { border-color:rgba(68,114,255,.4);background:rgba(68,114,255,.08);color:#4472FF; }
`;

export default function ProtocolPage({ activeTab, setActiveTab }) {
  const [protocols, setProtocols] = useState(SAMPLE_PROTOCOLS);
  const [filterCategory, setFilterCategory] = useState("All");
  const [filterChain, setFilterChain] = useState("All");
  const [sortBy, setSortBy] = useState("total");

  const filteredProtocols = protocols
    .filter(p => filterCategory === "All" || p.category === filterCategory)
    .filter(p => filterChain === "All" || p.chain === filterChain)
    .sort((a, b) => b.scores[sortBy] - a.scores[sortBy]);

  const formatTVL = (val) => {
    if (val >= 1e12) return `$${(val / 1e12).toFixed(2)}T`;
    if (val >= 1e9) return `$${(val / 1e9).toFixed(1)}B`;
    if (val >= 1e6) return `$${(val / 1e6).toFixed(0)}M`;
    return `$${val}`;
  };

  const getGradeColor = (grade) => {
    switch(grade) {
      case "A": return T.green;
      case "B": return T.blue;
      case "C": return T.amber;
      default: return T.muted;
    }
  };

  const stats = {
    totalProtocols: protocols.length,
    totalTVL: protocols.reduce((acc, p) => acc + p.tvl, 0),
    avgScore: Math.round(protocols.reduce((acc, p) => acc + p.scores.total, 0) / protocols.length),
    gradeA: protocols.filter(p => p.grade === "A").length,
  };

  return (
    <div style={{ position: "relative", minHeight: "100vh", background: T.void }}>
      <style>{CSS}</style>
      <div className="turrell-wrap">
        <div className="t-orb t-orb-1" /><div className="t-orb t-orb-2" />
        <div className="t-orb t-orb-3" /><div className="t-orb t-orb-4" />
      </div>

      <div style={{ position: "relative", zIndex: 1, maxWidth: 1400, margin: "0 auto", padding: "0 28px 56px" }}>
        {/* Navigation */}
        <div style={{
          display: "flex", alignItems: "center", justifyContent: "space-between",
          padding: "18px 0 20px", borderBottom: `1px solid ${T.border}`,
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
            <span style={{
              fontFamily: FONTS.display, fontWeight: 800, fontSize: 20,
              letterSpacing: "-0.03em",
              background: "linear-gradient(120deg,#FF1060 0%,#6B0FCC 45%,#4472FF 100%)",
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
        </div>

        {/* Header */}
        <div style={{ marginTop: 24, marginBottom: 20 }}>
          <h1 style={{
            fontFamily: FONTS.display, fontSize: 28, fontWeight: 700,
            color: T.primary, marginBottom: 8, letterSpacing: "-0.02em"
          }}>
            Protocol Library
          </h1>
          <p style={{
            fontFamily: FONTS.body, fontSize: 14, color: T.secondary,
            maxWidth: 600, lineHeight: 1.6
          }}>
            DeFi Protocol Analytics — Monitor TVL, yields, security, and risk across
            leading lending, DEX, staking, and yield optimization protocols.
          </p>
        </div>

        {/* Stats Summary */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 10, marginBottom: 24 }}>
          {[
            { label: "Protocols", value: stats.totalProtocols, icon: Activity, color: T.blue },
            { label: "Total TVL", value: formatTVL(stats.totalTVL), icon: DollarSign, color: T.green },
            { label: "Avg Score", value: stats.avgScore, icon: TrendingUp, color: T.violet },
            { label: "Grade A", value: stats.gradeA, icon: Shield, color: T.green },
          ].map((s, i) => (
            <div key={i} className="lm-card" style={{ padding: "16px 20px" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 8 }}>
                <s.icon size={14} color={s.color} />
                <div style={{ fontSize: 10, color: T.muted, letterSpacing: "0.1em", textTransform: "uppercase" }}>
                  {s.label}
                </div>
              </div>
              <div style={{ fontSize: 24, fontWeight: 600, color: s.color, fontFamily: FONTS.mono }}>
                {s.value}
              </div>
            </div>
          ))}
        </div>

        {/* Filters */}
        <div style={{ display: "flex", gap: 16, marginBottom: 20, flexWrap: "wrap", alignItems: "center" }}>
          <div style={{ display: "flex", gap: 6 }}>
            <span style={{ fontSize: 11, color: T.muted, fontFamily: FONTS.body, alignSelf: "center" }}>Category:</span>
            {CATEGORIES.map(cat => (
              <button key={cat} className={`filter-btn${filterCategory === cat ? " active" : ""}`}
                onClick={() => setFilterCategory(cat)}>
                {cat}
              </button>
            ))}
          </div>
          <div style={{ display: "flex", gap: 6 }}>
            <span style={{ fontSize: 11, color: T.muted, fontFamily: FONTS.body, alignSelf: "center" }}>Chain:</span>
            {CHAINS.map(chain => (
              <button key={chain} className={`filter-btn${filterChain === chain ? " active" : ""}`}
                onClick={() => setFilterChain(chain)}>
                {chain}
              </button>
            ))}
          </div>
          <div style={{ display: "flex", gap: 6, marginLeft: "auto" }}>
            <span style={{ fontSize: 11, color: T.muted, fontFamily: FONTS.body, alignSelf: "center" }}>Sort:</span>
            {["total", "tvlGrowth", "security", "liquidity"].map(s => (
              <button key={s} className={`filter-btn${sortBy === s ? " active" : ""}`}
                onClick={() => setSortBy(s)}>
                {s === "tvlGrowth" ? "TVL Growth" : s.charAt(0).toUpperCase() + s.slice(1)}
              </button>
            ))}
          </div>
        </div>

        {/* Protocol List */}
        <div className="lm-card" style={{ overflow: "hidden" }}>
          <div style={{
            display: "grid", gridTemplateColumns: "2fr 1fr 1fr 1fr 80px 60px",
            padding: "12px 20px", borderBottom: `1px solid ${T.border}`,
            fontSize: 10, color: T.muted, letterSpacing: "0.1em", textTransform: "uppercase",
            fontFamily: FONTS.body
          }}>
            <div>Protocol / Category</div>
            <div>TVL</div>
            <div>APY</div>
            <div>Score Breakdown</div>
            <div>Score</div>
            <div>Grade</div>
          </div>

          {filteredProtocols.map((proto, idx) => (
            <div key={proto.id} className="lm-row"
              style={{
                display: "grid", gridTemplateColumns: "2fr 1fr 1fr 1fr 80px 60px",
                padding: "16px 20px", borderBottom: `1px solid ${T.border}`,
                alignItems: "center",
                animation: "fadeUp 0.3s ease forwards",
                animationDelay: `${idx * 50}ms`,
              }}
            >
              {/* Protocol Info */}
              <div>
                <div style={{ fontFamily: FONTS.display, fontWeight: 600, color: T.primary, fontSize: 14 }}>
                  {proto.name}
                </div>
                <div style={{ display: "flex", gap: 8, marginTop: 4 }}>
                  <span style={{ fontSize: 11, color: T.cyan, fontFamily: FONTS.mono }}>{proto.category}</span>
                  <span style={{ fontSize: 11, color: T.muted }}>|</span>
                  <span style={{ fontSize: 11, color: T.secondary }}>{proto.chain}</span>
                  <span style={{ fontSize: 11, color: T.muted }}>|</span>
                  <span style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 10, color: T.green }}>
                    <Shield size={10} /> {proto.auditStatus}
                  </span>
                </div>
              </div>

              {/* TVL */}
              <div>
                <div style={{ fontFamily: FONTS.mono, fontSize: 13, color: T.primary }}>
                  {formatTVL(proto.tvl)}
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 10, marginTop: 2,
                  color: proto.tvlChange30d >= 0 ? T.green : T.red }}>
                  {proto.tvlChange30d >= 0 ? <ArrowUpRight size={10} /> : <ArrowDownRight size={10} />}
                  {proto.tvlChange30d >= 0 ? "+" : ""}{proto.tvlChange30d}% (30d)
                </div>
              </div>

              {/* APY */}
              <div>
                <div style={{ fontFamily: FONTS.mono, fontSize: 13, color: T.green }}>
                  {proto.apy}%
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 10, marginTop: 2,
                  color: proto.apyChange30d >= 0 ? T.green : T.red }}>
                  {proto.apyChange30d >= 0 ? <ArrowUpRight size={10} /> : <ArrowDownRight size={10} />}
                  {proto.apyChange30d >= 0 ? "+" : ""}{proto.apyChange30d}% (30d)
                </div>
              </div>

              {/* Score Breakdown */}
              <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
                {Object.entries(proto.scores).filter(([k]) => k !== "total").map(([key, val]) => (
                  <div key={key} style={{ textAlign: "center" }}>
                    <div style={{ fontSize: 9, color: T.muted, textTransform: "capitalize" }}>{key.slice(0,3)}</div>
                    <div style={{ fontSize: 11, color: T.secondary, fontFamily: FONTS.mono }}>{val}</div>
                  </div>
                ))}
              </div>

              {/* Total Score */}
              <div>
                <div style={{ fontSize: 18, fontWeight: 600, color: T.primary, fontFamily: FONTS.mono }}>
                  {proto.scores.total}
                </div>
              </div>

              {/* Grade */}
              <div>
                <div style={{
                  display: "inline-flex", alignItems: "center", justifyContent: "center",
                  width: 32, height: 32, borderRadius: 6,
                  background: `${getGradeColor(proto.grade)}20`,
                  color: getGradeColor(proto.grade),
                  fontFamily: FONTS.mono, fontWeight: 700, fontSize: 14,
                }}>
                  {proto.grade}
                </div>
              </div>
            </div>
          ))}
        </div>

        {/* Score Breakdown Legend */}
        <div style={{ marginTop: 20, padding: 16, background: "rgba(10,9,24,.5)", borderRadius: 10, border: `1px solid ${T.border}` }}>
          <div style={{ fontSize: 11, color: T.muted, letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 12 }}>
            Protocol Scoring — Evaluation Criteria
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: 16 }}>
            {[
              { label: "TVL & Growth", score: 30, desc: "TVL, Growth Rate" },
              { label: "Security", score: 25, desc: "Audits, Bug History" },
              { label: "Liquidity", score: 20, desc: "Depth, Slippage" },
              { label: "Team", score: 15, desc: "Background, Transparency" },
              { label: "Innovation", score: 10, desc: "Novelty, Differentiation" },
            ].map((item, i) => (
              <div key={i}>
                <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 4 }}>
                  <span style={{ fontSize: 12, fontWeight: 600, color: T.primary }}>{item.label}</span>
                  <span style={{ fontSize: 10, color: T.blue, fontFamily: FONTS.mono }}>{item.score}pts</span>
                </div>
                <div style={{ fontSize: 10, color: T.muted }}>{item.desc}</div>
              </div>
            ))}
          </div>
        </div>

        {/* Top Protocols by Category */}
        <div style={{ marginTop: 24 }}>
          <h2 style={{ fontFamily: FONTS.display, fontSize: 18, fontWeight: 600, color: T.primary, marginBottom: 16 }}>
            Top Protocols by Category
          </h2>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12 }}>
            {["Lending", "DEX", "Staking", "Yield"].map(cat => {
              const top = protocols.filter(p => p.category === cat).sort((a, b) => b.scores.total - a.scores.total)[0];
              if (!top) return null;
              return (
                <div key={cat} className="lm-card" style={{ padding: 16 }}>
                  <div style={{ fontSize: 10, color: T.muted, textTransform: "uppercase", letterSpacing: "0.1em", marginBottom: 8 }}>
                    {cat}
                  </div>
                  <div style={{ fontFamily: FONTS.display, fontWeight: 600, color: T.primary, fontSize: 16 }}>
                    {top.name}
                  </div>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: 8 }}>
                    <span style={{ fontFamily: FONTS.mono, fontSize: 13, color: T.green }}>{formatTVL(top.tvl)}</span>
                    <span style={{
                      display: "inline-flex", alignItems: "center", justifyContent: "center",
                      width: 28, height: 28, borderRadius: 6,
                      background: `${getGradeColor(top.grade)}20`,
                      color: getGradeColor(top.grade),
                      fontFamily: FONTS.mono, fontWeight: 700, fontSize: 12,
                    }}>
                      {top.grade}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
