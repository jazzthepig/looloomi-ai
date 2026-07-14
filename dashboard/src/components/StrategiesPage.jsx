import { useState, useEffect } from "react";
import { T, FONTS as F } from "../tokens";

/* ═══════════════════════════════════════════════════════════════════════════
   StrategiesPage — Three autonomous strategies users can adopt in a few clicks.

   Strategy 1: CIS Momentum Alpha
     Systematic. Follows top OUTPERFORM / STRONG OUTPERFORM assets by CIS score.
     Regime-aware: full exposure in RISK_ON / GOLDILOCKS, heavy cash in RISK_OFF.
     Rebalances every 30min on signal change. Min $1K USDC.

   Strategy 2: Protocol Yield Optimizer
     Allocates to top-3 CIS-rated DeFi protocols with TVL>$100M, live audit.
     Weekly rebalance. No leverage, no liquidation risk. Min $500 USDC.

   Strategy 3: Balanced AI Portfolio
     50% Momentum Alpha + 30% Protocol Yield + 20% USDC buffer.
     Regime-aware buffer expansion in TIGHTENING / RISK_OFF. Min $5K USDC.
   ═══════════════════════════════════════════════════════════════════════════ */

const RISK_COLORS = { LOW: T.green, MEDIUM: "#f59e0b", HIGH: T.red };
const SIG_COLORS  = {
  "STRONG OUTPERFORM": T.green, "OUTPERFORM": "#00D98A",
  NEUTRAL: "#f59e0b", UNDERPERFORM: "#f87171", UNDERWEIGHT: T.red,
};
const GRADE_C = {
  "A+": T.green, A: T.green, "B+": "#6366f1", B: "#6366f1",
  "C+": "#f59e0b", C: "#f59e0b", D: T.red, F: T.red,
};

/* ── Micro-components ─────────────────────────────────────────────────────── */
function Badge({ children, color = T.cyan, bg }) {
  return (
    <span style={{
      fontFamily: F.mono, fontSize: 8, fontWeight: 700, letterSpacing: "0.12em",
      textTransform: "uppercase", padding: "2px 7px", borderRadius: 3,
      color, background: bg || `${color}14`,
      border: `1px solid ${color}28`,
    }}>{children}</span>
  );
}

function MetricPill({ label, value, color = T.t2, size = 18 }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
      <div style={{ fontFamily: F.mono, fontSize: 8, color: T.muted, letterSpacing: "0.14em", textTransform: "uppercase" }}>
        {label}
      </div>
      <div style={{ fontFamily: F.mono, fontSize: size, fontWeight: 500, color, letterSpacing: "-0.01em", lineHeight: 1 }}>
        {value}
      </div>
    </div>
  );
}

/* ── Live positions mini-table ──────────────────────────────────────────── */
function PositionRow({ rank, symbol, signal, score, grade, weight, change7d }) {
  return (
    <div style={{
      display: "grid",
      gridTemplateColumns: "22px 60px 1fr 52px 38px 46px",
      alignItems: "center", padding: "7px 0",
      borderBottom: "1px solid rgba(255,255,255,0.04)",
    }}>
      <span style={{ fontFamily: F.mono, fontSize: 9, color: T.muted }}>{rank}</span>
      <span style={{ fontFamily: F.display, fontSize: 12, fontWeight: 700, color: T.t1 }}>{symbol}</span>
      <span style={{
        fontFamily: F.mono, fontSize: 9, fontWeight: 700, letterSpacing: "0.04em",
        color: SIG_COLORS[signal] || T.muted,
      }}>
        {signal === "STRONG OUTPERFORM" ? "STR.OUTPERF" : signal}
      </span>
      <span style={{ fontFamily: F.mono, fontSize: 11, color: T.t2, textAlign: "right" }}>{score?.toFixed(1)}</span>
      <span style={{ fontFamily: F.mono, fontSize: 11, fontWeight: 700, color: GRADE_C[grade] || T.muted, textAlign: "center" }}>{grade}</span>
      <span style={{
        fontFamily: F.mono, fontSize: 11, textAlign: "right",
        color: change7d >= 0 ? T.green : T.red,
      }}>
        {change7d != null ? `${change7d >= 0 ? "+" : ""}${change7d.toFixed(1)}%` : "—"}
      </span>
    </div>
  );
}

function PositionTable({ assets, maxRows = 5, emptyMsg = "Loading positions…" }) {
  if (!assets || assets.length === 0) {
    return (
      <div style={{
        padding: "20px 0", textAlign: "center",
        fontFamily: F.mono, fontSize: 10, color: T.muted,
      }}>
        {emptyMsg}
      </div>
    );
  }
  return (
    <div>
      {/* Header */}
      <div style={{
        display: "grid",
        gridTemplateColumns: "22px 60px 1fr 52px 38px 46px",
        padding: "4px 0 6px",
        fontFamily: F.mono, fontSize: 9, color: T.muted, letterSpacing: "0.10em",
        borderBottom: "1px solid rgba(255,255,255,0.07)",
        marginBottom: 2,
      }}>
        <span>#</span>
        <span>ASSET</span>
        <span>SIGNAL</span>
        <span style={{ textAlign: "right" }}>CIS</span>
        <span style={{ textAlign: "center" }}>GRD</span>
        <span style={{ textAlign: "right" }}>7D</span>
      </div>
      {assets.slice(0, maxRows).map((a, i) => (
        <PositionRow
          key={a.symbol || i}
          rank={i + 1}
          symbol={a.symbol || a.asset_id || "—"}
          signal={a.signal || "NEUTRAL"}
          score={a.cis_score ?? a.score}
          grade={a.grade}
          change7d={a.price_change_7d ?? a.change_7d ?? a.ch7d}
        />
      ))}
    </div>
  );
}

/* ── Activate modal ───────────────────────────────────────────────────────── */
function ActivateModal({ strategy, regime, onClose }) {
  const [step, setStep]     = useState(1); // 1=params, 2=subscribe, 3=done
  const [amount, setAmount] = useState("");
  const [email, setEmail]   = useState("");
  const [notify, setNotify] = useState(true);
  const [submitting, setSubmitting] = useState(false);

  const inputStyle = {
    width: "100%", boxSizing: "border-box",
    padding: "10px 13px", borderRadius: 7,
    background: "rgba(255,255,255,0.03)",
    border: "1px solid rgba(255,255,255,0.10)",
    color: T.t1, fontFamily: F.mono, fontSize: 13,
    outline: "none",
  };
  const labelStyle = {
    display: "block", fontFamily: F.mono, fontSize: 9,
    letterSpacing: "0.12em", textTransform: "uppercase",
    color: T.muted, marginBottom: 6,
  };

  const handleSubscribe = async () => {
    if (!email.trim()) return;
    setSubmitting(true);
    try {
      await fetch("/api/v1/leads/capture", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email,
          name: email.split("@")[0],
          message: `Strategy interest: ${strategy.name} · Allocation: ${amount || "not specified"} · Regime: ${regime}`,
          source_page: "strategies",
        }),
      });
    } catch (_) {}
    setSubmitting(false);
    setStep(3);
  };

  return (
    <div style={{
      position: "fixed", inset: 0, zIndex: 2000,
      background: "rgba(2,2,8,0.88)", backdropFilter: "blur(16px)",
      display: "flex", alignItems: "center", justifyContent: "center",
      padding: 24,
    }} onClick={e => { if (e.target === e.currentTarget) onClose(); }}>
      <div style={{
        width: "100%", maxWidth: 480,
        background: "rgba(8,12,28,0.98)", border: "1px solid rgba(6,182,212,0.15)",
        borderRadius: 14, padding: 32,
        boxShadow: "0 32px 80px rgba(0,0,0,0.6)",
      }}>

        {/* Header */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 24 }}>
          <div>
            <div style={{ fontFamily: F.mono, fontSize: 8, color: T.cyan, letterSpacing: "0.16em", marginBottom: 8 }}>
              ACTIVATE STRATEGY
            </div>
            <div style={{ fontFamily: F.display, fontSize: 20, fontWeight: 700, color: T.t1 }}>
              {strategy.name}
            </div>
          </div>
          <button onClick={onClose} style={{ background: "none", border: "none", color: T.muted, cursor: "pointer", fontSize: 18, lineHeight: 1 }}>
            ×
          </button>
        </div>

        {/* Step indicator */}
        <div style={{ display: "flex", gap: 6, marginBottom: 28 }}>
          {["Parameters", "Subscribe", "Done"].map((s, i) => (
            <div key={i} style={{
              flex: 1, height: 2, borderRadius: 1,
              background: step > i ? T.cyan : "rgba(255,255,255,0.08)",
              transition: "background 0.3s",
            }} />
          ))}
        </div>

        {/* Step 1: Parameters */}
        {step === 1 && (
          <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
            <div>
              <label style={labelStyle}>Target Allocation (USDC)</label>
              <input
                value={amount}
                onChange={e => setAmount(e.target.value)}
                placeholder={`Min. ${strategy.minEntry}`}
                style={inputStyle}
              />
            </div>

            <div style={{
              background: "rgba(6,182,212,0.04)", border: "1px solid rgba(6,182,212,0.10)",
              borderRadius: 8, padding: "14px 16px",
            }}>
              <div style={{ fontFamily: F.mono, fontSize: 9, color: T.cyan, letterSpacing: "0.12em", marginBottom: 10 }}>
                CURRENT REGIME: {regime || "—"}
              </div>
              <div style={{ fontFamily: F.body, fontSize: 12, color: T.t2, lineHeight: 1.6 }}>
                {strategy.regimeNote}
              </div>
            </div>

            {/* Risk summary */}
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 10 }}>
              {[
                { label: "Target Return", value: strategy.target },
                { label: "Max Drawdown", value: strategy.maxDD },
                { label: "Rebalance", value: strategy.rebalance },
              ].map((m, i) => (
                <div key={i} style={{
                  background: "rgba(255,255,255,0.02)", border: "1px solid rgba(255,255,255,0.05)",
                  borderRadius: 7, padding: "10px 12px",
                }}>
                  <div style={{ fontFamily: F.mono, fontSize: 8, color: T.muted, letterSpacing: "0.1em", marginBottom: 4 }}>{m.label}</div>
                  <div style={{ fontFamily: F.mono, fontSize: 13, color: T.t1 }}>{m.value}</div>
                </div>
              ))}
            </div>

            <button
              onClick={() => setStep(2)}
              style={{
                width: "100%", padding: "13px 0", borderRadius: 8, cursor: "pointer",
                fontFamily: F.display, fontSize: 13, fontWeight: 700, letterSpacing: "0.04em",
                color: "#fff",
                background: "linear-gradient(135deg, rgba(6,182,212,0.35), rgba(99,102,241,0.35))",
                border: "1px solid rgba(6,182,212,0.35)",
                transition: "all 0.2s",
              }}
            >
              Continue →
            </button>

            <div style={{ fontFamily: F.mono, fontSize: 8, color: T.muted, letterSpacing: "0.06em", lineHeight: 1.6 }}>
              For qualified investors only. Positioning language only — not investment advice.
              CometCloud AI does not hold a Type 9 investment advisory licence.
            </div>
          </div>
        )}

        {/* Step 2: Subscribe */}
        {step === 2 && (
          <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
            <div style={{ fontFamily: F.body, fontSize: 13, color: T.t2, lineHeight: 1.65 }}>
              Subscribe to receive live signal updates, grade-change alerts, and regime shift
              notifications for this strategy. You'll get a CIS intelligence briefing within 24 hours.
            </div>

            <div>
              <label style={labelStyle}>Email</label>
              <input
                type="email"
                value={email}
                onChange={e => setEmail(e.target.value)}
                placeholder="you@fund.com"
                style={inputStyle}
              />
            </div>

            <label style={{
              display: "flex", alignItems: "center", gap: 10, cursor: "pointer",
              fontFamily: F.body, fontSize: 12, color: T.t2,
            }}>
              <input
                type="checkbox"
                checked={notify}
                onChange={e => setNotify(e.target.checked)}
                style={{ accentColor: T.cyan }}
              />
              Notify me when this strategy's top positions change (webhook available on Pro)
            </label>

            <div style={{ display: "flex", gap: 10 }}>
              <button
                onClick={() => setStep(1)}
                style={{
                  flex: "0 0 auto", padding: "12px 20px", borderRadius: 8, cursor: "pointer",
                  fontFamily: F.display, fontSize: 12, fontWeight: 600,
                  color: T.t3, background: "transparent",
                  border: "1px solid rgba(255,255,255,0.08)",
                }}
              >
                Back
              </button>
              <button
                onClick={handleSubscribe}
                disabled={!email.trim() || submitting}
                style={{
                  flex: 1, padding: "12px 0", borderRadius: 8, cursor: "pointer",
                  fontFamily: F.display, fontSize: 13, fontWeight: 700,
                  color: "#fff",
                  background: "linear-gradient(135deg, rgba(6,182,212,0.35), rgba(99,102,241,0.35))",
                  border: "1px solid rgba(6,182,212,0.35)",
                  opacity: (!email.trim() || submitting) ? 0.5 : 1,
                }}
              >
                {submitting ? "Subscribing…" : "Subscribe to Strategy →"}
              </button>
            </div>
          </div>
        )}

        {/* Step 3: Done */}
        {step === 3 && (
          <div style={{ textAlign: "center", padding: "12px 0 8px" }}>
            <div style={{
              width: 52, height: 52, borderRadius: "50%", margin: "0 auto 20px",
              background: "rgba(0,217,138,0.08)", border: "1px solid rgba(0,217,138,0.20)",
              display: "flex", alignItems: "center", justifyContent: "center",
              fontSize: 22,
            }}>✦</div>
            <div style={{ fontFamily: F.display, fontSize: 20, fontWeight: 700, color: T.t1, marginBottom: 10 }}>
              You're subscribed.
            </div>
            <div style={{ fontFamily: F.body, fontSize: 13, color: T.t2, lineHeight: 1.65, marginBottom: 28 }}>
              Expect a CIS intelligence briefing within 24 hours. Live signal access
              and webhook configuration details will follow.
            </div>
            <div style={{ display: "flex", gap: 10, justifyContent: "center" }}>
              <button onClick={onClose} style={{
                padding: "10px 24px", borderRadius: 7, cursor: "pointer",
                fontFamily: F.display, fontSize: 12, fontWeight: 700,
                color: T.t1, background: "rgba(6,182,212,0.08)",
                border: "1px solid rgba(6,182,212,0.2)",
              }}>
                Close
              </button>
              <a href="/strategy.html" style={{
                padding: "10px 24px", borderRadius: 7, cursor: "pointer",
                fontFamily: F.display, fontSize: 12, fontWeight: 700,
                color: T.t1, background: "rgba(255,255,255,0.04)",
                border: "1px solid rgba(255,255,255,0.08)",
                textDecoration: "none",
              }}>
                Read Full Strategy →
              </a>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   Strategy Card
   ═══════════════════════════════════════════════════════════════════════════ */
function StrategyCard({ strategy, assets, protocols, regime, onActivate }) {
  const positions = strategy.buildPositions(assets, protocols);

  const riskColor = RISK_COLORS[strategy.risk] || T.t2;

  return (
    <div style={{
      background: "rgba(5,9,20,0.90)", border: "1px solid rgba(6,182,212,0.09)",
      borderRadius: 14, overflow: "hidden",
      transition: "border-color 0.2s",
    }}
      onMouseEnter={e => e.currentTarget.style.borderColor = "rgba(6,182,212,0.20)"}
      onMouseLeave={e => e.currentTarget.style.borderColor = "rgba(6,182,212,0.09)"}
    >
      {/* ── Header bar ── */}
      <div style={{
        display: "flex", alignItems: "flex-start", justifyContent: "space-between",
        padding: "22px 24px 18px",
        borderBottom: "1px solid rgba(255,255,255,0.04)",
      }}>
        <div style={{ flex: 1 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 6 }}>
            <span style={{ fontSize: 18, lineHeight: 1 }}>{strategy.icon}</span>
            <span style={{ fontFamily: F.display, fontSize: 18, fontWeight: 800, color: T.t1 }}>
              {strategy.name}
            </span>
            <Badge color={riskColor}>{strategy.risk} RISK</Badge>
            {strategy.live ? (
              <Badge color={T.green}>LIVE</Badge>
            ) : (
              <Badge color={T.amber}>{strategy.statusLabel}</Badge>
            )}
          </div>
          <div style={{ fontFamily: F.body, fontSize: 13, color: T.t2, lineHeight: 1.65, maxWidth: 560 }}>
            {strategy.description}
          </div>
        </div>

        {/* CTA */}
        <button
          onClick={() => onActivate(strategy)}
          style={{
            flexShrink: 0, marginLeft: 24,
            padding: "11px 22px", borderRadius: 8, cursor: "pointer",
            fontFamily: F.display, fontSize: 12, fontWeight: 700, letterSpacing: "0.04em",
            color: "#fff",
            background: "linear-gradient(135deg, rgba(6,182,212,0.30), rgba(99,102,241,0.30))",
            border: "1px solid rgba(6,182,212,0.35)",
            whiteSpace: "nowrap",
            transition: "all 0.15s",
          }}
          onMouseEnter={e => e.currentTarget.style.borderColor = "rgba(6,182,212,0.70)"}
          onMouseLeave={e => e.currentTarget.style.borderColor = "rgba(6,182,212,0.35)"}
        >
          Adopt Strategy →
        </button>
      </div>

      {/* ── Metrics row ── */}
      <div style={{
        display: "flex", gap: 0,
        padding: "16px 24px",
        borderBottom: "1px solid rgba(255,255,255,0.04)",
      }}>
        {strategy.metrics.map((m, i) => (
          <div key={i} style={{
            flex: 1, paddingRight: 20, marginRight: 20,
            borderRight: i < strategy.metrics.length - 1 ? "1px solid rgba(255,255,255,0.05)" : "none",
          }}>
            <MetricPill label={m.label} value={m.value} color={m.color || T.t1} size={16} />
          </div>
        ))}
      </div>

      {/* ── Live positions + composition ── */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 280px", gap: 0 }}>

        {/* Left: live positions */}
        <div style={{ padding: "18px 24px", borderRight: "1px solid rgba(255,255,255,0.04)" }}>
          <div style={{
            fontFamily: F.mono, fontSize: 8, color: T.cyan, letterSpacing: "0.16em",
            marginBottom: 12, display: "flex", alignItems: "center", gap: 8,
          }}>
            <span style={{
              width: 5, height: 5, borderRadius: "50%", background: T.cyan,
              boxShadow: `0 0 8px ${T.cyan}`, display: "inline-block",
            }} />
            CURRENT POSITIONS · LIVE CIS
          </div>
          <PositionTable assets={positions} maxRows={strategy.maxPositions || 5} />
        </div>

        {/* Right: composition + allocation */}
        <div style={{ padding: "18px 20px" }}>
          <div style={{ fontFamily: F.mono, fontSize: 8, color: T.muted, letterSpacing: "0.14em", marginBottom: 14 }}>
            ALLOCATION MODEL
          </div>

          {strategy.allocation.map((bucket, i) => (
            <div key={i} style={{ marginBottom: 12 }}>
              <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
                <span style={{ fontFamily: F.body, fontSize: 11, color: T.t2 }}>{bucket.label}</span>
                <span style={{ fontFamily: F.mono, fontSize: 11, color: bucket.color || T.t1, fontWeight: 700 }}>
                  {bucket.pct}%
                </span>
              </div>
              <div style={{
                height: 4, borderRadius: 2,
                background: "rgba(255,255,255,0.05)",
                overflow: "hidden",
              }}>
                <div style={{
                  height: "100%", width: `${bucket.pct}%`, borderRadius: 2,
                  background: bucket.color || T.cyan,
                  transition: "width 0.6s ease",
                }} />
              </div>
            </div>
          ))}

          {/* Regime note */}
          <div style={{
            marginTop: 16, padding: "10px 12px",
            background: "rgba(255,255,255,0.015)", borderRadius: 7,
            border: "1px solid rgba(255,255,255,0.05)",
          }}>
            <div style={{ fontFamily: F.mono, fontSize: 8, color: T.muted, letterSpacing: "0.1em", marginBottom: 4 }}>
              REGIME · {regime || "—"}
            </div>
            <div style={{ fontFamily: F.body, fontSize: 11, color: T.t3, lineHeight: 1.5 }}>
              {strategy.regimeShort}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════════════════
   Strategy Definitions
   ═══════════════════════════════════════════════════════════════════════════ */
const STRATEGIES = [
  {
    id: "momentum-alpha",
    icon: "⚡",
    name: "CIS Momentum Alpha",
    description:
      "Systematic signal-following strategy. Automatically positions into the highest-scoring OUTPERFORM and STRONG OUTPERFORM assets from the CIS universe. Regime-aware: full exposure in RISK ON / GOLDILOCKS, shifts to cash buffer in TIGHTENING and RISK OFF. Rebalances within 30 minutes of any grade or signal change.",
    risk: "MEDIUM",
    target: "15–25% ann.",
    maxDD: "< 15%",
    rebalance: "30 min",
    minEntry: "$1,000 USDC",
    live: true,
    statusLabel: "SIGNALS LIVE",
    maxPositions: 5,
    regimeNote:
      "In TIGHTENING / RISK OFF regimes, the strategy reduces net exposure to STRONG OUTPERFORM only and increases the stablecoin buffer. In RISK ON / GOLDILOCKS, full exposure to top OUTPERFORM assets across all classes.",
    regimeShort:
      "TIGHTENING: holds STRONG OUTPERFORM only, 30% USDC buffer.",
    metrics: [
      { label: "Target Return",   value: "15–25% ann.",   color: T.green },
      { label: "Max Drawdown",    value: "< 15%",         color: "#f59e0b" },
      { label: "Signal Latency",  value: "< 30 min",      color: T.cyan },
      { label: "Min Allocation",  value: "$1K USDC",      color: T.t2 },
      { label: "Universe",        value: "84 assets",     color: T.t2 },
    ],
    allocation: [
      { label: "STRONG OUTPERFORM (top-3)",  pct: 45, color: T.green },
      { label: "OUTPERFORM (top-5)",         pct: 25, color: "#00D98A" },
      { label: "Regime buffer (USDC)",       pct: 20, color: "#6366f1" },
      { label: "Tail hedge",                 pct: 10, color: "#f59e0b" },
    ],
    buildPositions(assets) {
      if (!assets || assets.length === 0) return [];
      return assets
        .filter(a => (a.signal || "").includes("OUTPERFORM"))
        .sort((a, b) => (b.cis_score ?? b.score ?? 0) - (a.cis_score ?? a.score ?? 0))
        .slice(0, 5);
    },
  },

  {
    id: "protocol-yield",
    icon: "🏦",
    name: "Protocol Yield Optimizer",
    description:
      "Allocates capital to the top-3 CIS-rated DeFi protocols with TVL > $100M and verified security audits. No leverage, no liquidation risk. Sources yield only from lending, staking, and liquidity provision — never from speculative positions. Rebalances weekly or on TVL drop > 20%.",
    risk: "LOW",
    target: "7–15% APY",
    maxDD: "< 5%",
    rebalance: "Weekly",
    minEntry: "$500 USDC",
    live: true,
    statusLabel: "PROTOCOLS LIVE",
    maxPositions: 3,
    regimeNote:
      "Yield is relatively regime-stable but the strategy shifts weight toward established lending protocols (Aave, Compound) in RISK OFF / TIGHTENING, and opens allocations to higher-APY structured products (Pendle, Ethena) in RISK ON.",
    regimeShort:
      "TIGHTENING: overweight Aave / Compound. Reduces Ethena exposure.",
    metrics: [
      { label: "Target APY",      value: "7–15%",         color: T.green },
      { label: "Max Drawdown",    value: "< 5%",          color: T.green },
      { label: "Rebalance",       value: "Weekly",        color: T.cyan },
      { label: "Min Allocation",  value: "$500 USDC",     color: T.t2 },
      { label: "Protocol Min TVL",value: "$100M",         color: T.t2 },
    ],
    allocation: [
      { label: "Top-1 protocol (Aave / MakerDAO)", pct: 50, color: T.green },
      { label: "Top-2 protocol (Compound / Pendle)",pct: 30, color: "#00D98A" },
      { label: "Top-3 protocol (Ethena / Spark)",   pct: 20, color: "#6366f1" },
    ],
    buildPositions(_, protocols) {
      if (!protocols || protocols.length === 0) return [];
      return protocols
        .filter(p => p.cis_score > 0)
        .sort((a, b) => (b.cis_score || 0) - (a.cis_score || 0))
        .slice(0, 3)
        .map(p => ({
          symbol: p.name?.split(" ")[0] || p.symbol || "—",
          signal: p.signal || "OUTPERFORM",
          cis_score: p.cis_score,
          grade: p.grade,
          price_change_7d: p.tvl_change_7d ?? null,
        }));
    },
  },

  {
    id: "balanced-ai",
    icon: "◎",
    name: "Balanced AI Portfolio",
    description:
      "Full-spectrum allocation combining both strategies into one. 50% systematic CIS momentum trading, 30% protocol yield, 20% USDC buffer. Regime-aware buffer expansion — shifts stablecoin weight to 40% in TIGHTENING / RISK OFF. Designed for investors who want broad CometCloud AI exposure with built-in downside protection.",
    risk: "MEDIUM",
    target: "12–20% ann.",
    maxDD: "< 10%",
    rebalance: "Weekly",
    minEntry: "$5,000 USDC",
    live: false,
    statusLabel: "Q2 2026",
    maxPositions: 5,
    regimeNote:
      "In neutral regimes, maintains 50/30/20 split. In RISK OFF or TIGHTENING, USDC buffer expands to 40%, momentum sleeve compresses to 30%. In RISK ON, yield sleeve can expand to 35% as higher-APY protocols activate.",
    regimeShort:
      "TIGHTENING: 30% momentum / 30% yield / 40% buffer.",
    metrics: [
      { label: "Target Return",   value: "12–20% ann.",   color: T.green },
      { label: "Max Drawdown",    value: "< 10%",         color: "#f59e0b" },
      { label: "Rebalance",       value: "Weekly",        color: T.cyan },
      { label: "Min Allocation",  value: "$5K USDC",      color: T.t2 },
      { label: "Fee",             value: "0% mgmt.",      color: T.green },
    ],
    allocation: [
      { label: "CIS Momentum Alpha",         pct: 50, color: T.cyan },
      { label: "Protocol Yield Optimizer",   pct: 30, color: T.green },
      { label: "USDC liquidity buffer",      pct: 20, color: "#6366f1" },
    ],
    buildPositions(assets) {
      if (!assets || assets.length === 0) return [];
      return assets
        .filter(a => (a.signal || "").includes("OUTPERFORM"))
        .sort((a, b) => (b.cis_score ?? b.score ?? 0) - (a.cis_score ?? a.score ?? 0))
        .slice(0, 5);
    },
  },
];

/* ═══════════════════════════════════════════════════════════════════════════
   MAIN
   ═══════════════════════════════════════════════════════════════════════════ */
// ── Open-source strategies (MIT) — earlier profitable/CIS-gated strategies, honestly labeled ──
function OpenSourceStrategies() {
  const [items, setItems] = useState([]);
  const [openId, setOpenId] = useState(null);
  const [code, setCode] = useState({});
  useEffect(() => {
    fetch("/api/v1/strategies/open-source")
      .then(r => (r.ok ? r.json() : null))
      .then(d => setItems((d && d.strategies) || []))
      .catch(() => {});
  }, []);
  const toggle = async (id) => {
    if (openId === id) { setOpenId(null); return; }
    setOpenId(id);
    if (!code[id]) {
      try {
        const r = await fetch(`/api/v1/strategies/open-source/${id}/code`);
        const d = await r.json();
        setCode(c => ({ ...c, [id]: d.code || "" }));
      } catch { /* leave loading */ }
    }
  };
  if (!items.length) return null;
  return (
    <div style={{ marginTop: 34 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 6 }}>
        <div style={{ width: 2, height: 16, background: T.muted, borderRadius: 1 }} />
        <span style={{ fontFamily: F.display, fontSize: 16, fontWeight: 800, color: T.t1 }}>Open Source</span>
        <span style={{ fontFamily: F.mono, fontSize: 8, fontWeight: 700, padding: "3px 8px", borderRadius: 4, background: "rgba(255,255,255,0.05)", color: T.t2, letterSpacing: ".1em" }}>MIT · FREQTRADE</span>
      </div>
      <p style={{ fontFamily: F.body, fontSize: 12, color: T.t2, lineHeight: 1.6, maxWidth: 620, margin: "0 0 16px", paddingLeft: 12 }}>
        Earlier profitable strategies, released under MIT. Directional / CIS-gated — genuinely tradeable, but
        not our edge (the causal + conviction layer stays proprietary). Numbers are honestly labeled
        in-sample vs reference; we never dress a backtest as a live track record.
      </p>
      <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
        {items.map(s => (
          <div key={s.id} style={{ background: "rgba(255,255,255,0.02)", border: `1px solid ${(s.color || T.cyan)}22`, borderRadius: 8, padding: "14px 16px" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 12, flexWrap: "wrap" }}>
              <div>
                <span style={{ fontFamily: F.display, fontSize: 15, fontWeight: 700, color: T.t1 }}>{s.icon} {s.name}</span>
                <span style={{ fontFamily: F.mono, fontSize: 9, color: T.muted, marginLeft: 8 }}>{s.subtitle} · {s.timeframe}</span>
              </div>
              <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
                {s.metrics_basis === "in_sample" && s.metrics && (
                  <span style={{ fontFamily: F.mono, fontSize: 10, color: T.green }}>Sharpe {s.metrics.sharpe} · {s.metrics.cagr_pct}% CAGR <span style={{ color: T.muted }}>(in-sample)</span></span>
                )}
                {s.metrics_basis === "reference" && (
                  <span style={{ fontFamily: F.mono, fontSize: 9, color: T.muted }}>reference impl</span>
                )}
                <button onClick={() => toggle(s.id)} style={{ fontFamily: F.mono, fontSize: 9, padding: "4px 10px", borderRadius: 4, border: `1px solid ${(s.color || T.cyan)}40`, background: "transparent", color: s.color || T.cyan, cursor: "pointer" }}>
                  {openId === s.id ? "Hide code" : "View code"}
                </button>
              </div>
            </div>
            <p style={{ fontFamily: F.body, fontSize: 11.5, color: T.t2, lineHeight: 1.55, margin: "8px 0 0" }}>{s.thesis}</p>
            <p style={{ fontFamily: F.mono, fontSize: 9, color: T.muted, margin: "6px 0 0", fontStyle: "italic" }}>{s.honest_note}</p>
            {openId === s.id && (
              <pre style={{ marginTop: 12, maxHeight: 340, overflow: "auto", background: "#05060f", border: "1px solid rgba(255,255,255,0.06)", borderRadius: 6, padding: 12, fontFamily: F.mono, fontSize: 10, color: "#c9d1d9", lineHeight: 1.5 }}>
                {code[s.id] || "Loading…"}
              </pre>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}


export default function StrategiesPage() {
  const [assets,    setAssets]    = useState([]);
  const [protocols, setProtocols] = useState([]);
  const [regime,    setRegime]    = useState(null);
  const [active,    setActive]    = useState(null); // currently open modal

  useEffect(() => {
    const load = async () => {
      const [cisRes, protoRes] = await Promise.allSettled([
        fetch("/api/v1/cis/universe").then(r => r.ok ? r.json() : null),
        fetch("/api/v1/protocols/universe").then(r => r.ok ? r.json() : null),
      ]);
      if (cisRes.status === "fulfilled" && cisRes.value) {
        const d = cisRes.value;
        const universe = d.universe || d.assets || d.scores || [];
        setAssets(universe.sort((a, b) => (b.cis_score ?? b.score ?? 0) - (a.cis_score ?? a.score ?? 0)));
        if (d.macro_regime && d.macro_regime !== "UNKNOWN") {
          const MAP = {
            RISK_ON: "RISK ON", GOLDILOCKS: "GOLDILOCKS", EASING: "EASING",
            RISK_OFF: "RISK OFF", TIGHTENING: "TIGHTENING", STAGFLATION: "STAGFLATION",
          };
          setRegime(MAP[d.macro_regime] || d.macro_regime.replace(/_/g, " "));
        }
      }
      if (protoRes.status === "fulfilled" && protoRes.value) {
        setProtocols(protoRes.value.protocols || []);
      }
    };
    load();
  }, []);

  const regimeColor = regime === "RISK ON" || regime === "GOLDILOCKS" ? T.green
    : regime === "RISK OFF" || regime === "STAGFLATION" ? T.red
    : regime === "TIGHTENING" ? "#f59e0b"
    : T.t2;

  return (
    <div>
      {/* ── Page header ── */}
      <div style={{ marginBottom: 28 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 6 }}>
          <div style={{ width: 2, height: 20, background: T.cyan, borderRadius: 1 }} />
          <span style={{ fontFamily: F.display, fontSize: 22, fontWeight: 800, color: T.t1 }}>
            Autonomous Strategies
          </span>
          {regime && (
            <span style={{
              fontFamily: F.mono, fontSize: 8, fontWeight: 700,
              padding: "3px 9px", borderRadius: 4, letterSpacing: "0.12em",
              background: `${regimeColor}14`, color: regimeColor,
              border: `1px solid ${regimeColor}30`,
            }}>
              REGIME: {regime}
            </span>
          )}
        </div>
        <p style={{ fontFamily: F.body, fontSize: 13, color: T.t2, lineHeight: 1.65, maxWidth: 640, margin: 0, paddingLeft: 14 }}>
          Three complete investment strategies powered by live CIS signals.
          Each strategy shows its current positions, target metrics, and allocation model.
          Subscribe in three clicks — signals delivered by email and webhook.
        </p>
      </div>

      {/* ── Strategy cards ── */}
      <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
        {STRATEGIES.map(s => (
          <StrategyCard
            key={s.id}
            strategy={s}
            assets={assets}
            protocols={protocols}
            regime={regime || "UNKNOWN"}
            onActivate={setActive}
          />
        ))}
      </div>

      {/* ── Open-source strategies ── */}
      <OpenSourceStrategies />

      {/* ── Compliance footer ── */}
      <div style={{
        marginTop: 28, padding: "14px 18px",
        background: "rgba(255,255,255,0.015)", borderRadius: 8,
        border: "1px solid rgba(255,255,255,0.05)",
        fontFamily: F.mono, fontSize: 8, color: T.muted,
        letterSpacing: "0.06em", lineHeight: 1.7,
      }}>
        All strategy outputs use positioning language only (STRONG OUTPERFORM / OUTPERFORM / NEUTRAL /
        UNDERPERFORM / UNDERWEIGHT). CometCloud AI does not hold an investment advisory (Type 9) licence.
        Information provided is for qualified investors only and does not constitute a solicitation or
        investment advice. Past performance of any model or strategy is not indicative of future results.
        Capital may be at risk. For compliance enquiries: jazz@cometcloud.ai
      </div>

      {/* ── Activate modal ── */}
      {active && (
        <ActivateModal
          strategy={active}
          regime={regime || "UNKNOWN"}
          onClose={() => setActive(null)}
        />
      )}
    </div>
  );
}
