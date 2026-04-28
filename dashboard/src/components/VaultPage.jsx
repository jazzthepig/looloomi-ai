import { useState, useEffect, useCallback } from "react";
import {
  RefreshCw, TrendingUp, Shield, Users, DollarSign,
  Activity, ArrowUpRight, ArrowDownRight, Globe, ExternalLink, Zap,
  CheckCircle, AlertCircle
} from "lucide-react";
import BottomSheet from "./ui/BottomSheet";
import { T, FONTS } from "../tokens";
import { useAuth, shortAddr } from "../context/AuthContext.jsx";
import { sendVaultDepositMemo } from "../lib/solanaVault.js";

/* ─── Sample Funds Data ──────────────────────────────────────────────── */
/* Data fetched from /api/v1/vault/funds API - real verified GPs only */
const SAMPLE_FUNDS = []; // Empty - data loaded from API

const FUND_TYPES = ["All", "DeFi Quant", "VC / Early Stage", "Market Neutral", "Trading / Momentum", "Long-Only / Research", "On-Chain Active", "LSD Focus", "Yield / Lending", "Options / Volatility", "Multi-Strategy"];
const LOCATIONS = ["All", "Singapore", "Hong Kong", "London", "Dubai", "New York", "Berlin"];

/* ─── Score Breakdown — segmented bar with tooltip labels ─────────────── */
const SCORE_CRITERIA = [
  { key: "performance",   label: "Performance",   short: "Perf",   max: 25, color: "#4472FF" },
  { key: "strategy",      label: "Strategy",      short: "Strat",  max: 20, color: "#A78BFA" },
  { key: "team",          label: "Team",          short: "Team",   max: 20, color: "#00D98A" },
  { key: "risk",          label: "Risk Mgmt",     short: "Risk",   max: 15, color: "#F59E0B" },
  { key: "transparency",  label: "Transparency",  short: "Trans",  max: 10, color: "#00C8E0" },
  { key: "aumTrackRecord",label: "AUM & Track",   short: "AUM",    max: 10, color: "#C8A84B" },
];

const ScoreBreakdown = ({ scores }) => {
  if (!scores) return null;
  // If all pillar scores are null, show pending state
  const allNull = SCORE_CRITERIA.every(c => scores[c.key] == null);
  if (allNull) {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
        <span style={{ fontSize: 9, color: "rgba(245,158,11,0.7)", fontFamily: FONTS.mono, letterSpacing: "0.06em" }}>
          ASSESSMENT
        </span>
        <span style={{ fontSize: 8, color: "rgba(62,102,128,0.9)", fontFamily: FONTS.body }}>
          In progress
        </span>
      </div>
    );
  }
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
      {SCORE_CRITERIA.map(c => {
        const val = scores[c.key] ?? 0;
        const pct = c.max > 0 ? (val / c.max) * 100 : 0;
        return (
          <div
            key={c.key}
            title={`${c.label}: ${val} / ${c.max} pts`}
            style={{ display: "flex", alignItems: "center", gap: 5, cursor: "default" }}
          >
            <span style={{
              fontFamily: FONTS.mono, fontSize: 8, fontWeight: 600,
              color: c.color, opacity: 0.7, width: 32, flexShrink: 0,
              letterSpacing: "-0.01em",
            }}>{c.short}</span>
            <div style={{
              flex: 1, height: 3, background: "rgba(255,255,255,0.07)",
              borderRadius: 2, overflow: "hidden",
            }}>
              <div style={{
                width: `${pct}%`, height: "100%", background: c.color,
                borderRadius: 2, opacity: 0.75, transition: "width .4s ease",
              }} />
            </div>
            <span style={{
              fontFamily: FONTS.mono, fontSize: 9,
              color: "rgba(199,210,254,0.5)", width: 14, textAlign: "right", flexShrink: 0,
            }}>{val}</span>
          </div>
        );
      })}
    </div>
  );
};

/* ─── CSS ────────────────────────────────────────────────────────────── */
const CSS = `
  @keyframes breathe  { 0%,100%{opacity:.28;transform:scale(1) translateY(0)} 50%{opacity:.44;transform:scale(1.06) translateY(-12px)} }
  @keyframes breathe2 { 0%,100%{opacity:.16;transform:scale(1)} 50%{opacity:.30;transform:scale(1.08) translateX(10px)} }
  @keyframes fadeUp   { from{opacity:0;transform:translateY(14px)} to{opacity:1;transform:translateY(0)} }
  @keyframes slideIn  { from{opacity:0;transform:translateX(-8px)} to{opacity:1;transform:translateX(0)} }
  @keyframes ambientGlow { 0%,100%{opacity:0.6} 50%{opacity:1} }
  @keyframes shimmerBtn { 0%{background-position:-200px 0} 100%{background-position:200px 0} }

  .cta-btn-hover {
    position: relative;
    overflow: hidden;
    transition: transform 0.2s ease, box-shadow 0.2s ease;
  }
  .cta-btn-hover::after {
    content: '';
    position: absolute;
    inset: 0;
    background: linear-gradient(90deg, transparent 0%, rgba(255,255,255,0.08) 50%, transparent 100%);
    background-size: 200px 100%;
    opacity: 0;
    transition: opacity 0.2s ease;
  }
  .cta-btn-hover:hover::after {
    opacity: 1;
    animation: shimmerBtn 1s ease infinite;
  }
  .cta-btn-hover:hover {
    transform: translateY(-1px);
    box-shadow: 0 4px 20px rgba(99,102,241,0.2);
  }

  .turrell-wrap { position:fixed;inset:0;pointer-events:none;z-index:0;overflow:hidden; }
  .t-orb { position:absolute;border-radius:50%;filter:blur(100px);mix-blend-mode:screen; }
  .t-orb-1 { width:720px;height:720px;background:radial-gradient(circle,rgba(107,15,204,.20) 0%,transparent 65%);top:-300px;left:-200px;animation:breathe 52s ease-in-out infinite; }
  .t-orb-2 { width:560px;height:560px;background:radial-gradient(circle,rgba(45,53,212,.15) 0%,transparent 65%);top:5%;right:-200px;animation:breathe2 64s ease-in-out infinite 9s; }
  .t-orb-3 { width:380px;height:380px;background:radial-gradient(circle,rgba(0,200,224,.09) 0%,transparent 65%);bottom:0;left:22%;animation:breathe 76s ease-in-out infinite 24s; }
  .t-orb-4 { width:280px;height:280px;background:radial-gradient(circle,rgba(255,16,96,.07) 0%,transparent 65%);bottom:12%;right:8%;animation:breathe2 60s ease-in-out infinite 38s; }

  /* lm-card/lm-row inherit from index.css global card system */

  .lm-tab { padding:5px 14px;border-radius:5px;font-size:12px;font-weight:500;font-family:'Syne',sans-serif;cursor:pointer;outline:none;border:1px solid rgba(255,255,255,0.08);background:transparent;color:#3E6680;transition:all .18s ease;letter-spacing:.01em; }
  .lm-tab:hover { border-color:rgba(56,148,210,0.25);color:#EFF8FF; }
  .lm-tab.active { border-color:rgba(68,114,255,.5);background:rgba(68,114,255,.10);color:#4472FF; }

  .filter-btn { padding:4px 10px;border-radius:4px;font-size:11px;font-weight:500;font-family:'Syne',sans-serif;cursor:pointer;outline:none;border:1px solid rgba(255,255,255,0.08);background:transparent;color:#3E6680;transition:all .15s ease; }
  .filter-btn:hover { border-color:rgba(56,148,210,0.25);color:#3E6680; }
  .filter-btn.active { border-color:rgba(68,114,255,.4);background:rgba(68,114,255,.08);color:#4472FF; }
`;

export default function VaultPage({ activeTab, setActiveTab, isSection = false }) {
  const { isConnected, address, connect } = useAuth();
  const [funds, setFunds] = useState(SAMPLE_FUNDS);
  const [loading, setLoading] = useState(true);
  const [filterType, setFilterType] = useState("All");
  const [filterLocation, setFilterLocation] = useState("All");
  const [sortBy, setSortBy] = useState("total");
  const [selectedFund, setSelectedFund] = useState(null);
  const [fetchError, setFetchError] = useState(null);
  const [partnerVaults, setPartnerVaults] = useState([]);
  const [vaultsLoading, setVaultsLoading] = useState(true);
  // Deposit intent modal state
  const [depositTarget, setDepositTarget] = useState(null); // { fund, vault? }
  const [depositAmount, setDepositAmount] = useState("");
  const [depositState, setDepositState] = useState("idle"); // idle | signing | confirming | success | error
  const [depositResult, setDepositResult] = useState(null); // { signature, explorerUrl }
  const [depositError, setDepositError] = useState(null);

  // Fetch GP data from API
  useEffect(() => {
    const fetchFunds = async () => {
      try {
        const res = await fetch('/api/v1/vault/funds');
        if (!res.ok) throw new Error(`API error: ${res.status}`);
        const json = await res.json();
        if (json.data && json.data.length > 0) {
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

  // Fetch partner vaults (Drift on-chain)
  useEffect(() => {
    const fetchPartnerVaults = async () => {
      try {
        const res = await fetch('/api/v1/vault/partner-vaults');
        if (!res.ok) throw new Error(`status ${res.status}`);
        const json = await res.json();
        setPartnerVaults(json.data || []);
      } catch (err) {
        console.warn('Partner vaults API failed:', err);
        setPartnerVaults([]);
      } finally {
        setVaultsLoading(false);
      }
    };
    fetchPartnerVaults();
  }, []);

  const filteredFunds = funds
    .filter(f => filterType === "All" || f.strategy === filterType)
    .filter(f => filterLocation === "All" || f.location === filterLocation)
    // null-safe sort: null scores sort to bottom
    .sort((a, b) => (b.scores?.[sortBy] ?? -1) - (a.scores?.[sortBy] ?? -1));

  // ── Deposit intent handler ──────────────────────────────────────────────────
  const handleDepositIntent = useCallback(async () => {
    if (!depositTarget || !depositAmount || isNaN(Number(depositAmount))) return;
    const amount = Number(depositAmount);
    if (amount <= 0) return;

    const vaultAddress = depositTarget.vault?.vaultAddress || depositTarget.fund?.driftVault;
    const partner      = depositTarget.vault?.partner || depositTarget.fund?.name;
    const vaultId      = depositTarget.vault?.id || depositTarget.fund?.id;

    if (!vaultAddress) {
      setDepositError("No on-chain vault address configured for this fund.");
      setDepositState("error");
      return;
    }

    try {
      setDepositState("signing");
      setDepositError(null);

      // 1. Send on-chain memo tx (attribution)
      const { signature, explorerUrl } = await sendVaultDepositMemo({
        walletAddress: address,
        vaultAddress,
        partner,
        amountUsdc: amount,
      });

      setDepositState("confirming");

      // 2. Record intent on backend
      try {
        await fetch("/api/v1/vault/deposit-intent", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            wallet_address: address,
            vault_id:       vaultId,
            vault_address:  vaultAddress,
            partner,
            amount_usdc:    amount,
            tx_signature:   signature,
            memo_data:      { source: "cometcloud", action: "vault_deposit_intent" },
          }),
        });
      } catch (e) {
        // Backend record failure is non-fatal — memo is on-chain regardless
        console.warn("Backend intent record failed:", e);
      }

      setDepositResult({ signature, explorerUrl, partner, amount });
      setDepositState("success");
    } catch (err) {
      console.error("Deposit memo failed:", err);
      setDepositError(err.message || "Transaction failed. Please try again.");
      setDepositState("error");
    }
  }, [depositTarget, depositAmount, address]);

  const openDepositModal = (fund, vault = null) => {
    setDepositTarget({ fund, vault });
    setDepositAmount("");
    setDepositState("idle");
    setDepositResult(null);
    setDepositError(null);
  };

  const closeDepositModal = () => {
    setDepositTarget(null);
    setDepositState("idle");
  };

  const formatAUM = (val) => {
    if (typeof val === 'string') return val;
    if (!val || val === 0) return '—';
    if (val >= 1e9) return `$${(val / 1e9).toFixed(1)}B`;
    if (val >= 1e6) return `$${(val / 1e6).toFixed(0)}M`;
    return `$${val}`;
  };

  const getGradeColor = (grade) => {
    if (!grade || grade === "—") return T.muted;
    if (grade.startsWith("A")) return T.green;   // A, A+
    if (grade.startsWith("B")) return T.blue;    // B, B+
    if (grade.startsWith("C")) return T.amber;   // C, C+
    if (grade === "D" || grade === "F") return T.red;
    return T.muted;
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

      <div style={{ position: "relative", zIndex: 1, maxWidth: 1400, margin: "0 auto", padding: isSection ? "0 0 40px" : "0 28px 56px" }}>
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

        {/* Header — title left, live stats right */}
        <div style={{
          marginTop: isSection ? 0 : 24, marginBottom: 20,
          display: "flex", alignItems: "center", gap: 10,
          paddingBottom: 14, borderBottom: "1px solid rgba(6,182,212,0.08)",
        }}>
          <div style={{ width: 2, height: 16, background: "rgba(6,182,212,0.65)", borderRadius: 1, flexShrink: 0 }} />
          <span style={{ fontFamily: FONTS.display, fontSize: 18, fontWeight: 600, color: T.primary, letterSpacing: "-0.01em" }}>
            Vault
          </span>
          <span style={{ fontFamily: FONTS.mono, fontSize: 10, color: T.muted, letterSpacing: "0.1em", textTransform: "uppercase" }}>
            · GP Selection
          </span>
          {/* Live stats inline — right-aligned */}
          <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 0 }}>
            {[
              { label: "ACTIVE GPs",  value: stats.totalFunds,          color: T.blue  },
              { label: "AVG SCORE",   value: stats.avgScore,             color: T.t2   },
              { label: "GRADE A",     value: stats.gradeA,               color: T.green },
            ].map((s, i, arr) => (
              <div key={i} style={{
                paddingLeft: 20, paddingRight: i < arr.length - 1 ? 20 : 0,
                borderLeft: `1px solid rgba(6,182,212,0.10)`,
                display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 1,
              }}>
                <div style={{ fontFamily: FONTS.mono, fontSize: 7, letterSpacing: "0.16em", color: T.muted, textTransform: "uppercase" }}>{s.label}</div>
                <div style={{ fontFamily: FONTS.mono, fontSize: 13, color: s.color, letterSpacing: "-0.01em" }}>{s.value}</div>
              </div>
            ))}
          </div>
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
            fontSize: '10px', color: '#3E6680',
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
              fontSize: '10px', color: '#3E6680',
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
                {fund.performance.ytd != null ? (
                  <>
                    <div style={{ display: "flex", alignItems: "center", gap: 4, color: fund.performance.ytd >= 0 ? T.green : T.red, fontFamily: FONTS.mono, fontSize: 13 }}>
                      {fund.performance.ytd >= 0 ? <ArrowUpRight size={12} /> : <ArrowDownRight size={12} />}
                      {fund.performance.ytd >= 0 ? "+" : ""}{fund.performance.ytd}%
                    </div>
                    <div style={{ fontSize: 10, color: T.muted, marginTop: 2 }}>
                      Sharpe: {fund.performance.sharpeRatio ?? "—"}
                    </div>
                  </>
                ) : (
                  <div style={{ fontFamily: FONTS.mono, fontSize: 10, color: T.muted }}>
                    On-chain NAV<br />
                    <span style={{ color: T.cyan, fontSize: 9 }}>↗ Drift</span>
                  </div>
                )}
              </div>

              {/* Risk */}
              <div>
                {fund.performance.maxDrawdown != null ? (
                  <>
                    <div style={{ color: T.amber, fontFamily: FONTS.mono, fontSize: 13 }}>
                      {fund.performance.maxDrawdown}%
                    </div>
                    <div style={{ fontSize: 10, color: T.muted, marginTop: 2 }}>Max DD</div>
                  </>
                ) : (
                  <div style={{ fontFamily: FONTS.mono, fontSize: 10, color: T.muted }}>—</div>
                )}
              </div>

              {/* Score Breakdown — segmented mini bars */}
              <ScoreBreakdown scores={fund.scores} />

              {/* Total Score */}
              <div>
                <div style={{ fontSize: 18, fontWeight: 600, color: T.primary, fontFamily: FONTS.mono }}>
                  {fund.scores?.total ?? "—"}
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
              {(() => {
                const p = selectedFund.performance || {};
                const fmtYtd = p.ytd != null ? `${p.ytd >= 0 ? "+" : ""}${p.ytd}%` : "—";
                const ytdColor = p.ytd != null ? (p.ytd >= 0 ? T.green : T.red) : T.muted;
                const fmtAnnual = p.annualReturn != null ? `+${p.annualReturn}%` : "—";
                const fmtSharpe = p.sharpeRatio != null ? String(p.sharpeRatio) : "—";
                const fmtDD = p.maxDrawdown != null ? `${p.maxDrawdown}%` : "—";
                return (
                  <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 4, marginBottom: 6, paddingBottom: 6, borderBottom: `1px solid ${T.border}` }}>
                    <div><div style={{ fontSize: 9, color: T.muted }}>YTD</div><div style={{ fontSize: 13, fontWeight: 600, color: ytdColor, fontFamily: FONTS.mono }}>{fmtYtd}</div></div>
                    <div><div style={{ fontSize: 9, color: T.muted }}>Annual</div><div style={{ fontSize: 13, fontWeight: 600, color: T.primary, fontFamily: FONTS.mono }}>{fmtAnnual}</div></div>
                    <div><div style={{ fontSize: 9, color: T.muted }}>Sharpe</div><div style={{ fontSize: 13, fontWeight: 600, color: T.primary, fontFamily: FONTS.mono }}>{fmtSharpe}</div></div>
                    <div><div style={{ fontSize: 9, color: T.muted }}>Max DD</div><div style={{ fontSize: 13, fontWeight: 600, color: T.amber, fontFamily: FONTS.mono }}>{fmtDD}</div></div>
                  </div>
                );
              })()}

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

              {/* ── Auth-gated Allocate CTA ── */}
              <div style={{ marginTop: 14, paddingTop: 12, borderTop: `1px solid ${T.border}` }}>
                {isConnected ? (
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                    <div style={{ fontSize: 10, color: T.muted }}>
                      Connected as <span style={{ color: "#C8A84B", fontFamily: "'JetBrains Mono', monospace" }}>{shortAddr(address)}</span>
                    </div>
                    <button
                      style={{
                        padding: "8px 20px", borderRadius: 6, fontSize: 12, fontWeight: 700,
                        fontFamily: "'Space Grotesk', sans-serif",
                        background: "linear-gradient(135deg, rgba(200,168,75,0.15) 0%, rgba(200,168,75,0.08) 100%)",
                        border: "1px solid rgba(200,168,75,0.4)", color: "#C8A84B",
                        cursor: "pointer", letterSpacing: "0.06em",
                        transition: "all 0.2s ease",
                      }}
                      onMouseEnter={e => { e.currentTarget.style.background = "rgba(200,168,75,0.2)"; e.currentTarget.style.borderColor = "rgba(200,168,75,0.6)"; }}
                      onMouseLeave={e => { e.currentTarget.style.background = "linear-gradient(135deg, rgba(200,168,75,0.15) 0%, rgba(200,168,75,0.08) 100%)"; e.currentTarget.style.borderColor = "rgba(200,168,75,0.4)"; }}
                      onClick={() => openDepositModal(selectedFund)}
                    >
                      Express Interest
                    </button>
                  </div>
                ) : (
                  <div style={{
                    display: "flex", alignItems: "center", justifyContent: "space-between",
                    padding: "10px 14px", borderRadius: 8,
                    background: "rgba(56,148,210,0.05)", border: "1px solid rgba(56,148,210,0.15)",
                  }}>
                    <span style={{ fontSize: 11, color: T.t2, fontFamily: "'Exo 2', sans-serif" }}>
                      Connect wallet to express interest
                    </span>
                    <button
                      onClick={connect}
                      style={{
                        padding: "6px 14px", borderRadius: 6, fontSize: 11, fontWeight: 700,
                        fontFamily: "'Space Grotesk', sans-serif",
                        background: "rgba(56,148,210,0.12)", border: "1px solid rgba(56,148,210,0.30)",
                        color: "#7AAEC8", cursor: "pointer", letterSpacing: "0.05em",
                      }}
                    >
                      Connect Wallet
                    </button>
                  </div>
                )}
              </div>
            </div>
          )}
        </BottomSheet>

        {/* ── Deposit Intent Modal ─────────────────────────────────────── */}
        {depositTarget && (
          <div style={{
            position: "fixed", inset: 0, zIndex: 100,
            background: "rgba(2,2,8,0.85)", backdropFilter: "blur(12px)",
            display: "flex", alignItems: "center", justifyContent: "center",
            padding: "20px",
          }}
            onClick={e => { if (e.target === e.currentTarget) closeDepositModal(); }}
          >
            <div style={{
              width: "100%", maxWidth: 440,
              background: "rgba(10,18,36,0.97)",
              border: "1px solid rgba(56,148,210,0.18)",
              borderRadius: 14, padding: "28px 28px 24px",
              boxShadow: "0 24px 80px rgba(0,0,0,0.6)",
            }}>
              {/* Header */}
              <div style={{ marginBottom: 20 }}>
                <div style={{ fontSize: 9, color: T.violet, fontFamily: FONTS.display, fontWeight: 700, letterSpacing: "0.12em", textTransform: "uppercase", marginBottom: 6 }}>
                  Deposit Intent · On-Chain Attribution
                </div>
                <div style={{ fontFamily: FONTS.display, fontWeight: 700, fontSize: 17, color: T.primary }}>
                  {depositTarget.vault?.partner || depositTarget.fund?.name}
                </div>
                <div style={{ fontSize: 11, color: T.muted, fontFamily: FONTS.mono, marginTop: 4 }}>
                  {(depositTarget.vault?.vaultAddress || depositTarget.fund?.driftVault || "").slice(0,12)}…
                </div>
              </div>

              {/* State: idle / signing / confirming */}
              {(depositState === "idle" || depositState === "error") && (
                <>
                  {/* How it works callout */}
                  <div style={{
                    padding: "10px 14px", borderRadius: 8, marginBottom: 18,
                    background: "rgba(139,92,246,0.06)", border: "1px solid rgba(139,92,246,0.18)",
                    fontSize: 11, color: T.muted, fontFamily: FONTS.body, lineHeight: 1.6,
                  }}>
                    <strong style={{ color: T.violet, fontSize: 10, fontWeight: 700 }}>How it works:</strong><br />
                    1. This signs a lightweight Solana Memo tx (~0.000005 SOL fee) tagging your wallet as a CometCloud depositor.<br />
                    2. You then complete the actual USDC deposit on Drift's vault page.<br />
                    3. HumbleBee can attribute your AUM contribution on-chain.
                  </div>

                  {/* Amount input */}
                  <div style={{ marginBottom: 16 }}>
                    <label style={{ fontSize: 10, color: T.muted, fontFamily: FONTS.display, fontWeight: 700, letterSpacing: "0.1em", textTransform: "uppercase", display: "block", marginBottom: 8 }}>
                      Intended Deposit (USDC)
                    </label>
                    <input
                      type="number"
                      min="1"
                      step="100"
                      placeholder="e.g. 10000"
                      value={depositAmount}
                      onChange={e => setDepositAmount(e.target.value)}
                      style={{
                        width: "100%", boxSizing: "border-box",
                        padding: "10px 14px", borderRadius: 8,
                        background: "rgba(255,255,255,0.04)",
                        border: "1px solid rgba(56,148,210,0.25)",
                        color: T.primary, fontFamily: FONTS.mono, fontSize: 16,
                        outline: "none",
                      }}
                    />
                    <div style={{ fontSize: 9, color: T.muted, fontFamily: FONTS.body, marginTop: 6 }}>
                      This amount is recorded in the memo — not a commitment.
                    </div>
                  </div>

                  {depositError && (
                    <div style={{
                      display: "flex", alignItems: "flex-start", gap: 8,
                      padding: "10px 12px", borderRadius: 7, marginBottom: 14,
                      background: "rgba(239,68,68,0.08)", border: "1px solid rgba(239,68,68,0.2)",
                    }}>
                      <AlertCircle size={13} color="#ef4444" style={{ flexShrink: 0, marginTop: 1 }} />
                      <span style={{ fontSize: 11, color: "#ef4444", fontFamily: FONTS.body }}>{depositError}</span>
                    </div>
                  )}

                  {/* Actions */}
                  <div style={{ display: "flex", gap: 10 }}>
                    <button onClick={closeDepositModal} style={{
                      flex: 1, padding: "10px 0", borderRadius: 8, cursor: "pointer",
                      border: `1px solid ${T.border}`, background: "transparent",
                      color: T.muted, fontFamily: FONTS.display, fontWeight: 600, fontSize: 12,
                    }}>
                      Cancel
                    </button>
                    <button
                      onClick={handleDepositIntent}
                      disabled={!depositAmount || Number(depositAmount) <= 0}
                      style={{
                        flex: 2, padding: "10px 0", borderRadius: 8, cursor: "pointer",
                        border: "1px solid rgba(200,168,75,0.5)",
                        background: "linear-gradient(135deg, rgba(200,168,75,0.18) 0%, rgba(200,168,75,0.08) 100%)",
                        color: "#C8A84B", fontFamily: FONTS.display, fontWeight: 700, fontSize: 13,
                        letterSpacing: "0.04em", opacity: (!depositAmount || Number(depositAmount) <= 0) ? 0.4 : 1,
                        transition: "all 0.15s",
                      }}
                    >
                      Sign & Record On-Chain
                    </button>
                  </div>
                </>
              )}

              {/* Signing / confirming */}
              {(depositState === "signing" || depositState === "confirming") && (
                <div style={{ textAlign: "center", padding: "28px 0" }}>
                  <div style={{
                    width: 44, height: 44, borderRadius: "50%",
                    border: `2px solid ${T.violet}30`,
                    borderTop: `2px solid ${T.violet}`,
                    animation: "spin 0.8s linear infinite",
                    margin: "0 auto 16px",
                  }} />
                  <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
                  <div style={{ fontFamily: FONTS.display, fontWeight: 700, fontSize: 14, color: T.primary, marginBottom: 6 }}>
                    {depositState === "signing" ? "Waiting for Phantom…" : "Confirming on Solana…"}
                  </div>
                  <div style={{ fontSize: 11, color: T.muted, fontFamily: FONTS.body }}>
                    {depositState === "signing" ? "Approve the memo transaction in your wallet." : "Transaction submitted — awaiting confirmation."}
                  </div>
                </div>
              )}

              {/* Success */}
              {depositState === "success" && depositResult && (
                <div style={{ textAlign: "center", padding: "12px 0" }}>
                  <CheckCircle size={40} color={T.green} style={{ margin: "0 auto 14px" }} />
                  <div style={{ fontFamily: FONTS.display, fontWeight: 700, fontSize: 15, color: T.primary, marginBottom: 6 }}>
                    Attribution Recorded
                  </div>
                  <div style={{ fontSize: 12, color: T.muted, fontFamily: FONTS.body, lineHeight: 1.6, marginBottom: 20 }}>
                    Your deposit intent for <strong style={{ color: T.primary }}>${depositResult.amount.toLocaleString()} USDC</strong> to <strong style={{ color: T.primary }}>{depositResult.partner}</strong> is now on-chain.
                    <br />Complete your deposit on Drift to finish.
                  </div>
                  <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                    <a
                      href={depositResult.explorerUrl}
                      target="_blank" rel="noopener noreferrer"
                      style={{
                        display: "block", padding: "10px 0", borderRadius: 8,
                        border: `1px solid ${T.violet}40`, background: `${T.violet}08`,
                        color: T.violet, fontFamily: FONTS.display, fontWeight: 700, fontSize: 12,
                        textDecoration: "none", letterSpacing: "0.04em",
                      }}
                    >
                      View on Solscan ↗
                    </a>
                    <a
                      href={`https://app.drift.trade/vaults/strategy-vaults/${depositTarget.vault?.vaultAddress || depositTarget.fund?.driftVault}`}
                      target="_blank" rel="noopener noreferrer"
                      style={{
                        display: "block", padding: "10px 0", borderRadius: 8,
                        border: "1px solid rgba(200,168,75,0.4)",
                        background: "rgba(200,168,75,0.08)",
                        color: "#C8A84B", fontFamily: FONTS.display, fontWeight: 700, fontSize: 12,
                        textDecoration: "none", letterSpacing: "0.04em",
                      }}
                    >
                      Deposit on Drift →
                    </a>
                    <button onClick={closeDepositModal} style={{
                      padding: "8px 0", borderRadius: 8, cursor: "pointer",
                      border: `1px solid ${T.border}`, background: "transparent",
                      color: T.muted, fontFamily: FONTS.display, fontSize: 11,
                    }}>
                      Close
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>
        )}

        {/* ── Partner Vaults — On-Chain ───────────────────────────────── */}
        <div style={{ marginTop: 28 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 14 }}>
            <Zap size={14} color={T.violet} />
            <span style={{ fontFamily: FONTS.display, fontSize: 14, fontWeight: 700, color: T.primary, letterSpacing: "-0.01em" }}>
              Partner Vaults — On-Chain
            </span>
            <span style={{
              fontSize: 9, fontWeight: 700, letterSpacing: "0.12em",
              color: T.violet, border: `1px solid ${T.violet}40`,
              padding: "2px 7px", borderRadius: 3,
            }}>DRIFT · SOLANA</span>
          </div>

          {vaultsLoading ? (
            <div style={{ fontSize: 12, color: T.muted, fontFamily: FONTS.body, padding: "12px 0" }}>
              Loading on-chain vaults…
            </div>
          ) : partnerVaults.length === 0 ? (
            <div style={{ fontSize: 12, color: T.muted, fontFamily: FONTS.body }}>No partner vaults available.</div>
          ) : (
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(340px, 1fr))", gap: 14 }}>
              {partnerVaults.map(vault => {
                const oc = vault.onChain || {};
                const isLive = oc.live === true;
                const formatUsd = (v) => {
                  if (!v) return "—";
                  const n = Number(v);
                  if (isNaN(n)) return "—";
                  if (n >= 1e6) return `$${(n / 1e6).toFixed(2)}M`;
                  if (n >= 1e3) return `$${(n / 1e3).toFixed(1)}K`;
                  return `$${n.toFixed(0)}`;
                };
                const fmtApy = (v) => {
                  if (!v) return "—";
                  const n = Number(v);
                  if (isNaN(n)) return "—";
                  return `${(n * 100).toFixed(2)}%`;
                };
                const fmtPct = (v) => {
                  if (!v) return "—";
                  const n = Number(v);
                  if (isNaN(n)) return "—";
                  if (n <= 1) return `${(n * 100).toFixed(1)}%`;
                  return `${n.toFixed(1)}%`;
                };
                const shortAddr = (a) => a ? `${a.slice(0,6)}…${a.slice(-4)}` : "—";

                return (
                  <div key={vault.id} className="lm-card transition-lift" style={{ padding: 18, position: "relative", overflow: "hidden" }}>
                    {/* Ambient glow */}
                    <div style={{
                      position: "absolute", top: -40, right: -40,
                      width: 120, height: 120, borderRadius: "50%",
                      background: "radial-gradient(circle, rgba(139,92,246,0.12) 0%, transparent 70%)",
                      pointerEvents: "none",
                      animation: "ambientGlow 4s ease-in-out infinite",
                    }} />

                    {/* Header row */}
                    <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", marginBottom: 12 }}>
                      <div>
                        <div style={{ fontFamily: FONTS.display, fontWeight: 700, fontSize: 15, color: T.primary }}>
                          {vault.partner}
                        </div>
                        <div style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 3 }}>
                          <span style={{ fontSize: 10, color: T.violet, fontFamily: FONTS.mono }}>{vault.protocol}</span>
                          <span style={{ fontSize: 10, color: T.muted }}>·</span>
                          <span style={{ fontSize: 10, color: T.muted, fontFamily: FONTS.mono }}>
                            {shortAddr(vault.vaultAddress)}
                          </span>
                        </div>
                      </div>
                      <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 4 }}>
                        <span style={{
                          fontSize: 9, fontWeight: 700, letterSpacing: "0.1em",
                          padding: "2px 7px", borderRadius: 3,
                          background: isLive ? "rgba(0,217,138,0.10)" : "rgba(245,158,11,0.10)",
                          color: isLive ? T.green : T.amber,
                          border: `1px solid ${isLive ? T.green : T.amber}40`,
                        }}>
                          {isLive ? "LIVE" : "PENDING"}
                        </span>
                        <span style={{ fontSize: 9, color: T.muted, fontFamily: FONTS.mono }}>{vault.platform}</span>
                      </div>
                    </div>

                    {/* Stats grid */}
                    <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 10, marginBottom: 14 }}>
                      {[
                        { label: "TVL", value: formatUsd(oc.tvlUsd) },
                        { label: "APY Est.", value: fmtApy(oc.apy) },
                        { label: "Depositors", value: oc.depositors ?? "—" },
                        { label: "Mgmt Fee", value: fmtPct(oc.managementFee) },
                        { label: "Perf Fee", value: fmtPct(oc.profitShare) },
                        { label: "Redeem", value: oc.redeemPeriod ? `${Math.round(oc.redeemPeriod / 86400)}d` : "—" },
                      ].map((item, i) => (
                        <div key={i}>
                          <div style={{ fontSize: 9, color: T.muted, textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 2 }}>
                            {item.label}
                          </div>
                          <div style={{ fontSize: 14, fontWeight: 600, color: T.primary, fontFamily: FONTS.mono }}>
                            {item.value}
                          </div>
                        </div>
                      ))}
                    </div>

                    {/* Footer */}
                    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", paddingTop: 10, borderTop: `1px solid ${T.border}` }}>
                      <div style={{ fontSize: 10, color: T.muted, fontFamily: FONTS.body }}>
                        On-chain · Permissionless · Solana
                      </div>
                      <div style={{ display: "flex", gap: 8 }}>
                        {isConnected && (
                          <button
                            onClick={() => openDepositModal(null, vault)}
                            className="cta-btn-hover"
                            style={{
                              display: "flex", alignItems: "center", gap: 5,
                              fontSize: 11, fontWeight: 700, color: "#C8A84B",
                              fontFamily: FONTS.display, letterSpacing: "0.04em",
                              padding: "5px 12px", borderRadius: 6, cursor: "pointer",
                              border: "1px solid rgba(200,168,75,0.4)",
                              background: "rgba(200,168,75,0.08)",
                            }}
                          >
                            Deposit Intent
                          </button>
                        )}
                        <a
                          href={vault.vaultUrl}
                          target="_blank"
                          rel="noopener noreferrer"
                          style={{
                            display: "flex", alignItems: "center", gap: 5,
                            fontSize: 11, fontWeight: 700, color: T.violet,
                            fontFamily: FONTS.display, letterSpacing: "0.04em",
                            textDecoration: "none",
                            padding: "5px 12px", borderRadius: 6,
                            border: `1px solid ${T.violet}40`,
                            background: `${T.violet}08`,
                            transition: "all 0.15s ease",
                          }}
                          onMouseEnter={e => { e.currentTarget.style.background = `${T.violet}18`; e.currentTarget.style.borderColor = `${T.violet}70`; }}
                          onMouseLeave={e => { e.currentTarget.style.background = `${T.violet}08`; e.currentTarget.style.borderColor = `${T.violet}40`; }}
                        >
                          View on Drift <ExternalLink size={10} />
                        </a>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Score Breakdown Legend */}
        <div style={{ marginTop: 20, padding: 16, background: "rgba(13,32,56,0.6)", borderRadius: 10, border: `1px solid ${T.border}` }}>
          <div style={{ fontSize: 11, color: T.muted, letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 12 }}>
            GP Selection Framework — Scoring Criteria
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(6, 1fr)", gap: 16 }}>
            {SCORE_CRITERIA.map((item, i) => (
              <div key={i}>
                <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 6 }}>
                  <span style={{ width: 8, height: 8, borderRadius: 2, background: item.color, flexShrink: 0 }} />
                  <span style={{ fontSize: 11, fontWeight: 600, color: T.primary, fontFamily: FONTS.display }}>{item.label}</span>
                  <span style={{ fontSize: 10, color: item.color, fontFamily: FONTS.mono, opacity: 0.8 }}>{item.max}pts</span>
                </div>
                <div style={{ height: 3, background: "rgba(255,255,255,0.07)", borderRadius: 2, marginBottom: 6 }}>
                  <div style={{ width: `${(item.max / 100) * 100}%`, height: "100%", background: item.color, borderRadius: 2, opacity: 0.6 }} />
                </div>
                <div style={{ fontSize: 10, color: T.muted, fontFamily: FONTS.body }}>
                  {item.key === "performance" ? "YTD, Annual Return, Sharpe" :
                   item.key === "strategy"    ? "Clarity, Differentiation" :
                   item.key === "team"        ? "Background, Experience" :
                   item.key === "risk"        ? "Management, Limits" :
                   item.key === "transparency"? "Reporting, Disclosure" :
                                               "Scale, History"}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
