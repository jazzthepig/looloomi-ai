import { useState, useEffect } from "react";
import {
  RefreshCw, TrendingUp, Shield, Users, DollarSign,
  Activity, ArrowUpRight, ArrowDownRight, Globe
} from "lucide-react";
import BottomSheet from "./ui/BottomSheet";
import { T, FONTS } from "../tokens";

/* ─── Sample Funds Data ──────────────────────────────────────────────── */
/* Data fetched from /api/v1/vault/funds API - real verified GPs only */
const SAMPLE_FUNDS = []; // Empty - data loaded from API

const FUND_TYPES = ["All", "DeFi Quant", "VC / Early Stage", "Market Neutral", "Trading / Momentum", "Long-Only / Research", "On-Chain Active", "LSD Focus", "Yield / Lending", "Options / Volatility", "Multi-Strategy"];
const LOCATIONS = ["All", "Singapore", "Hong Kong", "London", "Dubai", "New York", "Berlin"];

/* ─── CSS ────────────────────────────────────────────────────────────── */
const CSS = `
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

  .lm-tab { padding:5px 14px;border-radius:5px;font-size:12px;font-weight:500;font-family:'Syne',sans-serif;cursor:pointer;outline:none;border:1px solid #1A173A;background:transparent;color:#8880BE;transition:all .18s ease;letter-spacing:.01em; }
  .lm-tab:hover { border-color:#28244C;color:#F0EEFF; }
  .lm-tab.active { border-color:rgba(68,114,255,.5);background:rgba(68,114,255,.10);color:#4472FF; }

  .filter-btn { padding:4px 10px;border-radius:4px;font-size:11px;font-weight:500;font-family:'Syne',sans-serif;cursor:pointer;outline:none;border:1px solid #1A173A;background:transparent;color:#3E3A6E;transition:all .15s ease; }
  .filter-btn:hover { border-color:#28244C;color:#8880BE; }
  .filter-btn.active { border-color:rgba(68,114,255,.4);background:rgba(68,114,255,.08);color:#4472FF; }
`;

export default function VaultPage({ activeTab, setActiveTab, isSection = false }) {
  const [funds, setFunds] = useState(SAMPLE_FUNDS);
  const [loading, setLoading] = useState(true);
  const [filterType, setFilterType] = useState("All");
  const [filterLocation, setFilterLocation] = useState("All");
  const [sortBy, setSortBy] = useState("total");
  const [selectedFund, setSelectedFund] = useState(null);
  const [fetchError, setFetchError] = useState(null);

  // Fetch GP data from API
  useEffect(() => {
    const fetchFunds = async () => {
      try {
        const res = await fetch('/api/v1/vault/funds');
        if (!res.ok) throw new Error(`API error: ${res.status}`);
        const json = await res.json();
        if (json.data && json.data.length > 0) {
          // Map API data to match frontend structure
          const mapped = json.data.map((f, idx) => ({
            ...f,
            id: f.id || `gp-${idx}`,
            performance: f.performance || { ytd: 0, annualReturn: 0, sharpeRatio: 0, maxDrawdown: 0 },
            scores: f.scores || { performance: 0, strategy: 0, team: 0, risk: 0, transparency: 0, aumTrackRecord: 0, total: 0 },
            grade: f.grade || "B",
            description: f.description || "",
            team: f.team || "",
            strategyDetail: f.strategyDetail || "",
            advantage: f.advantage || "",
          }));
          setFunds(mapped);
        } else {
          // Empty data is not an error - just show empty state
          setFunds([]);
        }
      } catch (err) {
        console.warn('Vault API failed:', err);
        setFetchError(err.message || 'Failed to load GP data');
        setFunds([]);
      } finally {
        setLoading(false);
      }
    };
    fetchFunds();
  }, []);

  const filteredFunds = funds
    .filter(f => filterType === "All" || f.strategy === filterType)
    .filter(f => filterLocation === "All" || f.location === filterLocation)
    .sort((a, b) => b.scores[sortBy] - a.scores[sortBy]);

  const formatAUM = (val) => {
    if (typeof val === 'string') return val;
    if (!val || val === 0) return '—';
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

  const activeFunds = funds.filter(f => f.status === 'active');
  const scoredFunds = funds.filter(f => f.scores?.total > 0);

  const stats = {
    totalFunds: activeFunds.length,
    totalAUM: 'Confidential',
    avgScore: scoredFunds.length > 0 ? Math.round(scoredFunds.reduce((acc, f) => acc + f.scores.total, 0) / scoredFunds.length) : '—',
    gradeA: funds.filter(f => f.grade === "A").length,
  };

  return (
    <div style={{ position: "relative", minHeight: "100vh", background: T.void }}>
      <style>{CSS}</style>
      {/* Turrell ambient - only when not embedded in App.jsx */}
      {!isSection && (
      <div className="turrell-wrap">
        <div className="t-orb t-orb-1" /><div className="t-orb t-orb-2" />
        <div className="t-orb t-orb-3" /><div className="t-orb t-orb-4" />
      </div>
      )}

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

        {/* DATA NOTE */}
        <div style={{
          display: 'flex', alignItems: 'center', gap: '8px',
          padding: '10px 14px',
          background: 'rgba(245,158,11,0.08)',
          border: '1px solid rgba(245,158,11,0.2)',
          borderRadius: '6px', marginBottom: '14px'
        }}>
          <span style={{
            fontSize: '8px', fontWeight: '700', letterSpacing: '0.12em',
            color: '#F59E0B', fontFamily: FONTS.display
          }}>DATA NOTE</span>
          <span style={{
            fontSize: '10px', color: 'rgba(255,255,255,0.5)',
            fontFamily: FONTS.body
          }}>
            GP data sourced from Looloomi Database. Only verified partners are listed.
          </span>
        </div>

        {/* Error State */}
        {fetchError && (
          <div style={{
            display: 'flex', alignItems: 'center', gap: '8px',
            padding: '10px 14px',
            background: 'rgba(239,68,68,0.08)',
            border: '1px solid rgba(239,68,68,0.2)',
            borderRadius: '6px', marginBottom: '14px'
          }}>
            <span style={{
              fontSize: '8px', fontWeight: '700', letterSpacing: '0.12em',
              color: '#ef4444', fontFamily: FONTS.display
            }}>API ERROR</span>
            <span style={{
              fontSize: '10px', color: 'rgba(255,255,255,0.5)',
              fontFamily: FONTS.body
            }}>
              {fetchError} — GP data unavailable
            </span>
          </div>
        )}

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

          {loading ? (
            <div style={{ padding: "40px 20px", textAlign: "center", color: T.muted, fontFamily: FONTS.body, fontSize: 13 }}>
              Loading GP data...
            </div>
          ) : filteredFunds.length === 0 ? (
            <div style={{ padding: "40px 20px", textAlign: "center", color: T.muted, fontFamily: FONTS.body, fontSize: 13 }}>
              No GP data available{fetchError ? ` (${fetchError})` : ""}
            </div>
          ) : filteredFunds.map((fund, idx) => {
            const isPlaceholder = fund.isPlaceholder || fund.status === 'evaluating';
            return (
            <div key={fund.id} className="lm-row"
              style={{
                display: "grid", gridTemplateColumns: "2fr 1fr 1fr 1fr 80px 60px",
                padding: "16px 20px", borderBottom: `1px solid ${T.border}`,
                alignItems: "center",
                animation: "fadeUp 0.3s ease forwards",
                animationDelay: `${idx * 50}ms`,
                cursor: isPlaceholder ? "default" : "pointer",
                background: selectedFund?.id === fund.id ? "rgba(68,114,255,.08)" : undefined,
                opacity: isPlaceholder ? 0.5 : 1,
              }}
              onClick={() => !isPlaceholder && setSelectedFund(selectedFund?.id === fund.id ? null : fund)}
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
                  background: isPlaceholder ? `${T.muted}20` : `${getGradeColor(fund.grade)}20`,
                  color: isPlaceholder ? T.muted : getGradeColor(fund.grade),
                  fontFamily: FONTS.mono, fontWeight: 700, fontSize: 14,
                }}>
                  {isPlaceholder ? "—" : fund.grade}
                </div>
              </div>
            </div>
            );
          })}
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
