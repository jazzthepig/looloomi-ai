import { useState, useEffect } from "react";
import {
  RefreshCw, TrendingUp, Shield, Users, DollarSign,
  Activity, ArrowUpRight, ArrowDownRight, Globe
} from "lucide-react";
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

/* ─── Sample Funds Data ──────────────────────────────────────────────── */
const SAMPLE_FUNDS = [
  {
    id: "gp-001",
    name: "ArkStream Capital",
    strategy: "DeFi Quant",
    aum: 450000000,
    yearFounded: 2021,
    location: "Singapore",
    performance: {
      ytd: 34.5,
      annualReturn: 28.2,
      sharpeRatio: 1.85,
      maxDrawdown: -12.4,
    },
    scores: {
      performance: 22,
      strategy: 17,
      team: 18,
      risk: 13,
      transparency: 9,
      aumTrackRecord: 9,
      total: 88,
    },
    grade: "A",
    description: "Institutional-grade DeFi quantitative trading fund specializing in yield optimization and arbitrage strategies.",
    team: "Ex-Citadel, Jane Street, Two Sigma",
    strategyDetail: "Multi-strategy DeFi: yield farming arbitrage, stablecoin spreads, LSD rebalancing",
    advantage: "Institutional-grade risk management with real-time delta-neutral positioning",
  },
  {
    id: "gp-002",
    name: "Nebula Ventures",
    strategy: "VC / Early Stage",
    aum: 280000000,
    yearFounded: 2022,
    location: "Hong Kong",
    performance: {
      ytd: 18.2,
      annualReturn: 45.8,
      sharpeRatio: 1.42,
      maxDrawdown: -22.1,
    },
    scores: {
      performance: 20,
      strategy: 16,
      team: 17,
      risk: 11,
      transparency: 8,
      aumTrackRecord: 7,
      total: 79,
    },
    grade: "B",
    description: "Venture capital focus on early-stage Web3 infrastructure and protocol investments.",
    team: "Ex-Sequoia Asia, Blockchain.com Ventures",
    strategyDetail: "Early-stage incubation: seed rounds, strategic tokens, ecosystem building",
    advantage: "Strong Asia network with direct access to regional launchpads",
  },
  {
    id: "gp-003",
    name: "Quantum Hedge",
    strategy: "Market Neutral",
    aum: 820000000,
    yearFounded: 2020,
    location: "London",
    performance: {
      ytd: 12.8,
      annualReturn: 15.4,
      sharpeRatio: 2.34,
      maxDrawdown: -5.2,
    },
    scores: {
      performance: 21,
      strategy: 18,
      team: 19,
      risk: 14,
      transparency: 10,
      aumTrackRecord: 10,
      total: 92,
    },
    grade: "A",
    description: "Market-neutral crypto hedge fund with proven track record and institutional infrastructure.",
    team: "Ex-Goldman Sachs, Citadel, Optiver",
    strategyDetail: "Market-neutral: statistical arbitrage, pairs trading, volatility surface",
    advantage: "Ultra-low latency infrastructure with institutional custody (Fireblocks, BitGo)",
  },
  {
    id: "gp-004",
    name: "Phoenix Digital",
    strategy: "Trading / Momentum",
    aum: 125000000,
    yearFounded: 2023,
    location: "Dubai",
    performance: {
      ytd: 42.1,
      annualReturn: 52.3,
      sharpeRatio: 1.28,
      maxDrawdown: -28.5,
    },
    scores: {
      performance: 18,
      strategy: 14,
      team: 12,
      risk: 8,
      transparency: 6,
      aumTrackRecord: 5,
      total: 63,
    },
    grade: "C",
    description: "High-conviction momentum trading strategy with elevated risk profile.",
    team: "Ex-Deribit, Bybit market makers",
    strategyDetail: "Momentum & trend following across perpetual futures, options skew",
    advantage: "High conviction, rapid capital deployment in emerging narratives",
  },
  {
    id: "gp-005",
    name: "Aurora Research",
    strategy: "Long-Only / Research",
    aum: 340000000,
    yearFounded: 2021,
    location: "New York",
    performance: {
      ytd: 22.4,
      annualReturn: 19.8,
      sharpeRatio: 1.65,
      maxDrawdown: -15.8,
    },
    scores: {
      performance: 19,
      strategy: 16,
      team: 17,
      risk: 12,
      transparency: 8,
      aumTrackRecord: 8,
      total: 80,
    },
    grade: "B",
    description: "Research-driven long-only fund focusing on fundamental value plays in crypto assets.",
    team: "Ex-Morgan Stanley, Bloomberg Research",
    strategyDetail: "Fundamental research: protocol tokenomics, governance analysis, on-chain metrics",
    advantage: "Deep fundamental research with proprietary valuation models",
  },
  // Additional On-chain / DeFi focused funds
  {
    id: "gp-006",
    name: "Ethos Capital",
    strategy: "On-Chain Active",
    aum: 520000000,
    yearFounded: 2021,
    location: "Singapore",
    performance: {
      ytd: 28.5,
      annualReturn: 32.1,
      sharpeRatio: 1.72,
      maxDrawdown: -14.2,
    },
    scores: {
      performance: 23,
      strategy: 18,
      team: 17,
      risk: 12,
      transparency: 9,
      aumTrackRecord: 9,
      total: 88,
    },
    grade: "A",
    description: "On-chain native fund using whale tracking, smart money flows, and protocol governance.",
    team: "Early Ethereum validators, Nansen analysts",
    strategyDetail: "Whale wallet tracking, governance voting strategies, MEV extraction",
    advantage: "Direct on-chain alpha from wallet tracking and validator infrastructure",
  },
  {
    id: "gp-007",
    name: "LSD Alpha",
    strategy: "LSD Focus",
    aum: 180000000,
    yearFounded: 2023,
    location: "Berlin",
    performance: {
      ytd: 24.2,
      annualReturn: 18.5,
      sharpeRatio: 1.95,
      maxDrawdown: -8.4,
    },
    scores: {
      performance: 20,
      strategy: 16,
      team: 15,
      risk: 14,
      transparency: 9,
      aumTrackRecord: 6,
      total: 80,
    },
    grade: "B",
    description: "Specialized liquid staking derivatives strategy with focus on restaking ecosystem.",
    team: "Ex-Ethereum Foundation, Lido contributors",
    strategyDetail: "LSD arbitrage, restaking tokens (EigenLayer), validator infrastructure",
    advantage: "Deep technical expertise in Ethereum consensus and LSD mechanisms",
  },
  {
    id: "gp-008",
    name: "DeFi Pulse",
    strategy: "Yield / Lending",
    aum: 290000000,
    yearFounded: 2022,
    location: "Hong Kong",
    performance: {
      ytd: 16.8,
      annualReturn: 14.2,
      sharpeRatio: 1.55,
      maxDrawdown: -10.5,
    },
    scores: {
      performance: 18,
      strategy: 17,
      team: 16,
      risk: 13,
      transparency: 8,
      aumTrackRecord: 7,
      total: 79,
    },
    grade: "B",
    description: "Active lending protocol selection and yield optimization across chains.",
    team: "Ex-Compound, Aave governance participants",
    strategyDetail: "Cross-chain yield optimization, supply/borrow rate arbitrage, collateral switching",
    advantage: "Multi-chain yield aggregation with automated rebalancing",
  },
  {
    id: "gp-009",
    name: "Vaulted",
    strategy: "Options / Volatility",
    aum: 150000000,
    yearFounded: 2023,
    location: "London",
    performance: {
      ytd: 32.5,
      annualReturn: 28.8,
      sharpeRatio: 1.68,
      maxDrawdown: -18.2,
    },
    scores: {
      performance: 21,
      strategy: 16,
      team: 14,
      risk: 11,
      transparency: 8,
      aumTrackRecord: 6,
      total: 76,
    },
    grade: "B",
    description: "Crypto-native options desk focused on volatility strategies and structured products.",
    team: "Ex-Wolverine, DV Chain option traders",
    strategyDetail: "Covered calls, protective puts, strangles, volatility arbitrage",
    advantage: "Institutional options pricing with greeks management",
  },
  {
    id: "gp-010",
    name: "Terra Nova",
    strategy: "Multi-Strategy",
    aum: 680000000,
    yearFounded: 2020,
    location: "New York",
    performance: {
      ytd: 21.2,
      annualReturn: 24.5,
      sharpeRatio: 1.88,
      maxDrawdown: -9.8,
    },
    scores: {
      performance: 22,
      strategy: 19,
      team: 18,
      risk: 13,
      transparency: 9,
      aumTrackRecord: 10,
      total: 91,
    },
    grade: "A",
    description: "Premier multi-strategy crypto fund with diversified approach across alpha sources.",
    team: "Ex-Citadel, Point72, jump Trading",
    strategyDetail: "Market making, quant strategies, venture, on-chain - balanced portfolio",
    advantage: "Full-spectrum crypto exposure with institutional risk controls",
  },
];
const FUND_TYPES = ["All", "DeFi Quant", "VC / Early Stage", "Market Neutral", "Trading / Momentum", "Long-Only / Research", "On-Chain Active", "LSD Focus", "Yield / Lending", "Options / Volatility", "Multi-Strategy"];
const LOCATIONS = ["All", "Singapore", "Hong Kong", "London", "Dubai", "New York", "Berlin"];

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
  .lm-row:hover { background:rgba(6,182,212,.06) !important; border-left: 2px solid rgba(6,182,212,0.4); }

  .lm-tab { padding:5px 14px;border-radius:5px;font-size:12px;font-weight:500;font-family:'Exo 2',sans-serif;cursor:pointer;outline:none;border:1px solid #1A173A;background:transparent;color:#8880BE;transition:all .18s ease;letter-spacing:.01em; }
  .lm-tab:hover { border-color:#28244C;color:#F0EEFF; }
  .lm-tab.active { border-color:rgba(68,114,255,.5);background:rgba(68,114,255,.10);color:#4472FF; }

  .filter-btn { padding:4px 10px;border-radius:4px;font-size:11px;font-weight:500;font-family:'Exo 2',sans-serif;cursor:pointer;outline:none;border:1px solid #1A173A;background:transparent;color:#3E3A6E;transition:all .15s ease; }
  .filter-btn:hover { border-color:#28244C;color:#8880BE; }
  .filter-btn.active { border-color:rgba(68,114,255,.4);background:rgba(68,114,255,.08);color:#4472FF; }
`;

export default function VaultPage({ activeTab, setActiveTab, isSection = false }) {
  const [funds, setFunds] = useState(SAMPLE_FUNDS);
  const [filterType, setFilterType] = useState("All");
  const [filterLocation, setFilterLocation] = useState("All");
  const [sortBy, setSortBy] = useState("total");
  const [selectedFund, setSelectedFund] = useState(null);

  const filteredFunds = funds
    .filter(f => filterType === "All" || f.strategy === filterType)
    .filter(f => filterLocation === "All" || f.location === filterLocation)
    .sort((a, b) => b.scores[sortBy] - a.scores[sortBy]);

  const formatAUM = (val) => {
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
    totalFunds: funds.length,
    totalAUM: funds.reduce((acc, f) => acc + f.aum, 0),
    avgScore: Math.round(funds.reduce((acc, f) => acc + f.scores.total, 0) / funds.length),
    gradeA: funds.filter(f => f.grade === "A").length,
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
        {/* Navigation - hide when rendered as section */}
        {!isSection && (
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
        </div>
        )}

        {/* Header */}
        <div style={{ marginTop: 24, marginBottom: 20 }}>
          <h1 style={{
            fontFamily: FONTS.display, fontSize: 28, fontWeight: 700,
            color: T.primary, marginBottom: 8, letterSpacing: "-0.02em"
          }}>
            Vault — Fund-of-Funds
          </h1>
          <p style={{
            fontFamily: FONTS.body, fontSize: 14, color: T.secondary,
            maxWidth: 600, lineHeight: 1.6
          }}>
            GP Selection Framework — Evaluate and select top-tier crypto fund managers
            across Performance, Strategy, Team, Risk, Transparency, and Track Record.
          </p>
        </div>

        {/* Stats Summary */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 10, marginBottom: 24 }}>
          {[
            { label: "Active GPs", value: stats.totalFunds, icon: Users, color: T.blue },
            { label: "Total AUM", value: formatAUM(stats.totalAUM), icon: DollarSign, color: T.green },
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
            <span style={{ fontSize: 11, color: T.muted, fontFamily: FONTS.body, alignSelf: "center" }}>Strategy:</span>
            {FUND_TYPES.map(type => (
              <button key={type} className={`filter-btn${filterType === type ? " active" : ""}`}
                onClick={() => setFilterType(type)}>
                {type}
              </button>
            ))}
          </div>
          <div style={{ display: "flex", gap: 6 }}>
            <span style={{ fontSize: 11, color: T.muted, fontFamily: FONTS.body, alignSelf: "center" }}>Location:</span>
            {LOCATIONS.map(loc => (
              <button key={loc} className={`filter-btn${filterLocation === loc ? " active" : ""}`}
                onClick={() => setFilterLocation(loc)}>
                {loc}
              </button>
            ))}
          </div>
          <div style={{ display: "flex", gap: 6, marginLeft: "auto" }}>
            <span style={{ fontSize: 11, color: T.muted, fontFamily: FONTS.body, alignSelf: "center" }}>Sort:</span>
            {["total", "performance", "team", "risk"].map(s => (
              <button key={s} className={`filter-btn${sortBy === s ? " active" : ""}`}
                onClick={() => setSortBy(s)}>
                {s.charAt(0).toUpperCase() + s.slice(1)}
              </button>
            ))}
          </div>
        </div>

        {/* Fund List */}
        <div className="lm-card" style={{ overflow: "hidden" }}>
          <div style={{
            display: "grid", gridTemplateColumns: "2fr 1fr 1fr 1fr 80px 60px",
            padding: "12px 20px", borderBottom: `1px solid ${T.border}`,
            fontSize: 10, color: T.muted, letterSpacing: "0.1em", textTransform: "uppercase",
            fontFamily: FONTS.body
          }}>
            <div>Fund / Strategy</div>
            <div>Performance</div>
            <div>Risk</div>
            <div>Score Breakdown</div>
            <div>Score</div>
            <div>Grade</div>
          </div>

          {filteredFunds.map((fund, idx) => (
            <div key={fund.id} className="lm-row"
              style={{
                display: "grid", gridTemplateColumns: "2fr 1fr 1fr 1fr 80px 60px",
                padding: "16px 20px", borderBottom: `1px solid ${T.border}`,
                alignItems: "center",
                animation: "fadeUp 0.3s ease forwards",
                animationDelay: `${idx * 50}ms`,
                cursor: "pointer",
                background: selectedFund?.id === fund.id ? "rgba(68,114,255,.08)" : undefined,
              }}
              onClick={() => setSelectedFund(selectedFund?.id === fund.id ? null : fund)}
            >
              {/* Fund Info */}
              <div>
                <div style={{ fontFamily: FONTS.display, fontWeight: 600, color: T.primary, fontSize: 14 }}>
                  {fund.name}
                </div>
                <div style={{ display: "flex", gap: 8, marginTop: 4, flexWrap: "wrap" }}>
                  <span style={{ fontSize: 11, color: T.cyan, fontFamily: FONTS.mono }}>{fund.strategy}</span>
                  <span style={{ fontSize: 11, color: T.muted }}>|</span>
                  <span style={{ fontSize: 11, color: T.secondary }}>{fund.location}</span>
                  <span style={{ fontSize: 11, color: T.muted }}>|</span>
                  <span style={{ fontSize: 11, color: T.secondary }}>{formatAUM(fund.aum)} AUM</span>
                </div>
                {fund.team && (
                  <div style={{ fontSize: 10, color: T.muted, marginTop: 4 }}>
                    {fund.team}
                  </div>
                )}
              </div>

              {/* Performance */}
              <div>
                <div style={{ display: "flex", alignItems: "center", gap: 4, color: fund.performance.ytd >= 0 ? T.green : T.red, fontFamily: FONTS.mono, fontSize: 13 }}>
                  {fund.performance.ytd >= 0 ? <ArrowUpRight size={12} /> : <ArrowDownRight size={12} />}
                  {fund.performance.ytd >= 0 ? "+" : ""}{fund.performance.ytd}%
                </div>
                <div style={{ fontSize: 10, color: T.muted, marginTop: 2 }}>
                  Sharpe: {fund.performance.sharpeRatio}
                </div>
              </div>

              {/* Risk */}
              <div>
                <div style={{ color: T.amber, fontFamily: FONTS.mono, fontSize: 13 }}>
                  {fund.performance.maxDrawdown}%
                </div>
                <div style={{ fontSize: 10, color: T.muted, marginTop: 2 }}>
                  Max DD
                </div>
              </div>

              {/* Score Breakdown */}
              <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
                {Object.entries(fund.scores).filter(([k]) => k !== "total").map(([key, val]) => (
                  <div key={key} style={{ textAlign: "center" }}>
                    <div style={{ fontSize: 9, color: T.muted, textTransform: "capitalize" }}>{key.slice(0,3)}</div>
                    <div style={{ fontSize: 11, color: T.secondary, fontFamily: FONTS.mono }}>{val}</div>
                  </div>
                ))}
              </div>

              {/* Total Score */}
              <div>
                <div style={{ fontSize: 18, fontWeight: 600, color: T.primary, fontFamily: FONTS.mono }}>
                  {fund.scores.total}
                </div>
              </div>

              {/* Grade */}
              <div>
                <div style={{
                  display: "inline-flex", alignItems: "center", justifyContent: "center",
                  width: 32, height: 32, borderRadius: 6,
                  background: `${getGradeColor(fund.grade)}20`,
                  color: getGradeColor(fund.grade),
                  fontFamily: FONTS.mono, fontWeight: 700, fontSize: 14,
                }}>
                  {fund.grade}
                </div>
              </div>
            </div>
          ))}
        </div>

        {/* Selected Fund Detail - BottomSheet */}
        <BottomSheet isOpen={!!selectedFund} onClose={() => setSelectedFund(null)}>
          {selectedFund && (
            <div style={{ borderLeft: `3px solid ${getGradeColor(selectedFund.grade)}`, paddingLeft: 10 }}>
              {/* Row 1: Name + Grade */}
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6, lineHeight: 1.2 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <h3 style={{ fontFamily: FONTS.display, fontSize: 15, fontWeight: 700, color: T.primary, margin: 0 }}>
                    {selectedFund.name}
                  </h3>
                  <span style={{
                    padding: "1px 6px", borderRadius: 2, fontSize: 10, fontWeight: 600,
                    background: `${getGradeColor(selectedFund.grade)}20`, color: getGradeColor(selectedFund.grade),
                  }}>
                    Grade {selectedFund.grade}
                  </span>
                </div>
                <div style={{ fontSize: 10, color: T.secondary }}>
                  {formatAUM(selectedFund.aum)} AUM
                </div>
              </div>

              {/* Row 2: Key metrics */}
              <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 4, marginBottom: 6, paddingBottom: 6, borderBottom: `1px solid ${T.border}` }}>
                <div><div style={{ fontSize: 9, color: T.muted }}>YTD</div><div style={{ fontSize: 13, fontWeight: 600, color: selectedFund.performance.ytd >= 0 ? T.green : T.red, fontFamily: FONTS.mono }}>{selectedFund.performance.ytd >= 0 ? "+" : ""}{selectedFund.performance.ytd}%</div></div>
                <div><div style={{ fontSize: 9, color: T.muted }}>Annual</div><div style={{ fontSize: 13, fontWeight: 600, color: T.primary, fontFamily: FONTS.mono }}>+{selectedFund.performance.annualReturn}%</div></div>
                <div><div style={{ fontSize: 9, color: T.muted }}>Sharpe</div><div style={{ fontSize: 13, fontWeight: 600, color: T.primary, fontFamily: FONTS.mono }}>{selectedFund.performance.sharpeRatio}</div></div>
                <div><div style={{ fontSize: 9, color: T.muted }}>Max DD</div><div style={{ fontSize: 13, fontWeight: 600, color: T.amber, fontFamily: FONTS.mono }}>{selectedFund.performance.maxDrawdown}%</div></div>
              </div>

              {/* Row 3: Details */}
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
                <div>
                  <div style={{ fontSize: 9, color: T.muted, textTransform: "uppercase", marginBottom: 2 }}>Team</div>
                  <div style={{ fontSize: 11, color: T.primary, lineHeight: 1.3 }}>{selectedFund.team || "—"}</div>
                </div>
                <div>
                  <div style={{ fontSize: 9, color: T.muted, textTransform: "uppercase", marginBottom: 2 }}>Strategy</div>
                  <div style={{ fontSize: 11, color: T.primary, lineHeight: 1.3 }}>{selectedFund.strategyDetail || selectedFund.description}</div>
                </div>
              </div>

              {selectedFund.advantage && (
                <div style={{ marginTop: 8, padding: 8, background: "rgba(68,114,255,.05)", borderRadius: 4, border: `1px solid ${T.blue}30` }}>
                  <div style={{ fontSize: 9, color: T.blue, textTransform: "uppercase", marginBottom: 3 }}>Key Advantage</div>
                  <div style={{ fontSize: 11, color: T.primary }}>
                    {selectedFund.advantage}
                  </div>
                </div>
              )}
            </div>
          )}
        </BottomSheet>

        {/* Score Breakdown Legend */}
        <div style={{ marginTop: 20, padding: 16, background: "rgba(10,9,24,.5)", borderRadius: 10, border: `1px solid ${T.border}` }}>
          <div style={{ fontSize: 11, color: T.muted, letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 12 }}>
            GP Selection Framework — Scoring Criteria
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(6, 1fr)", gap: 16 }}>
            {[
              { label: "Performance", score: 25, desc: "YTD, Annual Return, Sharpe" },
              { label: "Strategy", score: 20, desc: "Clarity, Differentiation" },
              { label: "Team", score: 20, desc: "Background, Experience" },
              { label: "Risk", score: 15, desc: "Management, Limits" },
              { label: "Transparency", score: 10, desc: "Reporting, Disclosure" },
              { label: "AUM & Track", score: 10, desc: "Scale, History" },
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
      </div>
    </div>
  );
}
