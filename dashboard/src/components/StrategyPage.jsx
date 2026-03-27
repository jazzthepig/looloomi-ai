import { useState, useEffect } from "react";
import { T, FONTS } from "../tokens";

/* ═══════════════════════════════════════════════════════════════════════════
   CometCloud AI — Investor Strategy Page
   Complete product flow: Intelligence → Channels → Returns
   Live data from Railway API, projected numbers where real data pending.
   ═══════════════════════════════════════════════════════════════════════════ */

const F = FONTS;

/* ── Grade colors ────────────────────────────────────────────────────────── */
const GRADE_C = {
  "A+": T.green, A: T.green, "B+": T.gold, B: T.gold,
  "C+": T.amber, C: T.amber, D: T.red, F: T.red,
};

/* ── Section wrapper ─────────────────────────────────────────────────────── */
const Section = ({ children, id, style }) => (
  <section id={id} style={{
    maxWidth: 1120, margin: "0 auto", padding: "80px 32px", ...style,
  }}>
    {children}
  </section>
);

const Label = ({ children, color = T.t3 }) => (
  <div style={{
    fontFamily: F.mono, fontSize: 10, fontWeight: 500,
    letterSpacing: "0.18em", textTransform: "uppercase",
    color, marginBottom: 10,
  }}>
    {children}
  </div>
);

const Divider = () => (
  <div style={{ height: 1, background: T.border, margin: "0 auto", maxWidth: 1120 }} />
);

/* ── Stat pill ───────────────────────────────────────────────────────────── */
const Stat = ({ label, value, color = T.t1, sub }) => (
  <div style={{ textAlign: "center" }}>
    <div style={{
      fontFamily: F.mono, fontSize: 10, letterSpacing: "0.14em",
      textTransform: "uppercase", color: T.t3, marginBottom: 6,
    }}>{label}</div>
    <div style={{
      fontFamily: F.mono, fontSize: 26, fontWeight: 400,
      color, letterSpacing: "-0.02em", lineHeight: 1,
    }}>{value}</div>
    {sub && <div style={{ fontFamily: F.mono, fontSize: 10, color: T.t3, marginTop: 4 }}>{sub}</div>}
  </div>
);

/* ── Channel card ────────────────────────────────────────────────────────── */
const ChannelCard = ({ icon, title, subtitle, description, metrics, status, statusColor, children }) => (
  <div style={{
    flex: 1, minWidth: 300,
    background: "rgba(10,14,24,0.85)", border: `1px solid ${T.border}`,
    borderRadius: 12, padding: "28px 24px", backdropFilter: "blur(20px)",
    display: "flex", flexDirection: "column", gap: 16,
    transition: "border-color 0.2s",
  }}
    onMouseEnter={(e) => e.currentTarget.style.borderColor = "rgba(0,0,0,0.10)"}
    onMouseLeave={(e) => e.currentTarget.style.borderColor = T.border}
  >
    {/* Header */}
    <div>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
        <span style={{ fontSize: 22 }}>{icon}</span>
        <div>
          <div style={{ fontFamily: F.display, fontSize: 16, fontWeight: 700, color: T.t1, letterSpacing: "0.02em" }}>
            {title}
          </div>
          <div style={{ fontFamily: F.mono, fontSize: 10, color: T.t3, letterSpacing: "0.06em" }}>
            {subtitle}
          </div>
        </div>
      </div>
      <div style={{ fontFamily: F.body, fontSize: 13, color: T.t2, lineHeight: 1.65 }}>
        {description}
      </div>
    </div>

    {/* Metrics grid */}
    {metrics && (
      <div style={{
        display: "grid", gridTemplateColumns: "1fr 1fr",
        gap: "12px 16px", padding: "14px 0",
        borderTop: `1px solid ${T.border}`, borderBottom: `1px solid ${T.border}`,
      }}>
        {metrics.map((m, i) => (
          <div key={i}>
            <div style={{ fontFamily: F.mono, fontSize: 9, color: T.t3, letterSpacing: "0.12em", textTransform: "uppercase", marginBottom: 3 }}>
              {m.label}
            </div>
            <div style={{ fontFamily: F.mono, fontSize: 15, fontWeight: 500, color: m.color || T.t1 }}>
              {m.value}
            </div>
          </div>
        ))}
      </div>
    )}

    {/* Live content */}
    {children}

    {/* Status */}
    <div style={{ marginTop: "auto", display: "flex", alignItems: "center", gap: 6 }}>
      <span style={{
        width: 6, height: 6, borderRadius: "50%",
        background: statusColor || T.green,
        boxShadow: `0 0 8px ${statusColor || T.green}60`,
      }} />
      <span style={{ fontFamily: F.mono, fontSize: 10, color: statusColor || T.green, letterSpacing: "0.08em" }}>
        {status}
      </span>
    </div>
  </div>
);

/* ── Flow step ───────────────────────────────────────────────────────────── */
const FlowStep = ({ num, title, desc }) => (
  <div style={{ display: "flex", gap: 16, alignItems: "flex-start" }}>
    <div style={{
      width: 36, height: 36, borderRadius: "50%",
      border: `1px solid ${T.gold}40`, background: `${T.gold}08`,
      display: "flex", alignItems: "center", justifyContent: "center",
      fontFamily: F.mono, fontSize: 14, fontWeight: 600, color: T.gold,
      flexShrink: 0,
    }}>{num}</div>
    <div>
      <div style={{ fontFamily: F.display, fontSize: 14, fontWeight: 700, color: T.t1, marginBottom: 4 }}>
        {title}
      </div>
      <div style={{ fontFamily: F.body, fontSize: 12, color: T.t2, lineHeight: 1.6 }}>
        {desc}
      </div>
    </div>
  </div>
);

/* ═══════════════════════════════════════════════════════════════════════════
   MAIN
   ═══════════════════════════════════════════════════════════════════════════ */
export default function StrategyPage() {
  const [macro, setMacro]       = useState(null);
  const [cisData, setCisData]   = useState(null);
  const [protocols, setProtocols] = useState(null);

  useEffect(() => {
    // Fetch live data in parallel
    const load = async () => {
      const [macroRes, cisRes, protoRes] = await Promise.allSettled([
        fetch("/api/v1/market/macro-pulse").then(r => r.ok ? r.json() : null),
        fetch("/api/v1/cis/universe").then(r => r.ok ? r.json() : null),
        fetch("/api/v1/protocols/universe").then(r => r.ok ? r.json() : null),
      ]);
      if (macroRes.status === "fulfilled" && macroRes.value) setMacro(macroRes.value);
      if (cisRes.status === "fulfilled" && cisRes.value) setCisData(cisRes.value);
      if (protoRes.status === "fulfilled" && protoRes.value) setProtocols(protoRes.value);
    };
    load();
  }, []);

  // Derived
  const btcDom = macro?.data?.market_cap_percentage?.btc;
  const fngVal = macro?.fng?.value;
  const fngLabel = macro?.fng?.value_classification;
  const mcapChange = macro?.data?.market_cap_change_percentage_24h_usd;

  const regime = (() => {
    const btc7d = macro?.btc?.usd_7d_change || 0;
    const fng = parseInt(fngVal || 50);
    if (btc7d > 5 && fng > 50) return "RISK ON";
    if (btc7d < -10 || fng < 25) return "RISK OFF";
    return "NEUTRAL";
  })();
  const regimeColor = regime === "RISK ON" ? T.green : regime === "RISK OFF" ? T.red : T.gold;

  const topAssets = (cisData?.universe || cisData?.assets || cisData?.scores || [])
    .sort((a, b) => (b.cis_score ?? b.score ?? 0) - (a.cis_score ?? a.score ?? 0))
    .slice(0, 10);

  const topProtocols = (protocols?.protocols || [])
    .sort((a, b) => (b.cis_score || 0) - (a.cis_score || 0))
    .slice(0, 5);

  return (
    <div style={{ background: T.void, color: T.t1, minHeight: "100vh", position: "relative", overflow: "hidden" }}>
      {/* ── Turrell ambient — 8 layers, async breathing, void with light ── */}
      <div style={{ position: "fixed", inset: 0, pointerEvents: "none", zIndex: 0 }}>
        {/* Base: subtle depth gradient — the void isn't flat */}
        <div style={{ position: "absolute", inset: 0, background: "radial-gradient(ellipse 120% 100% at 50% 30%, #080c18 0%, #FAFBFC 55%, #020406 100%)" }} />
        {/* L1: Top-left emerald — CIS green echo */}
        <div className="al-orb" style={{ width: 1100, height: 700, top: -220, left: -180, background: "radial-gradient(ellipse, rgba(0,232,122,0.11) 0%, transparent 60%)", filter: "blur(90px)", animation: "alA 13s ease-in-out infinite" }} />
        {/* L2: Right gold — CometCloud accent */}
        <div className="al-orb" style={{ width: 900, height: 550, top: 180, right: -200, background: "radial-gradient(ellipse, rgba(200,168,75,0.10) 0%, transparent 58%)", filter: "blur(90px)", animation: "alB 19s ease-in-out infinite" }} />
        {/* L3: Bottom center blue — cold horizon */}
        <div className="al-orb" style={{ width: 1000, height: 450, bottom: -80, left: "20%", background: "radial-gradient(ellipse, rgba(75,158,255,0.09) 0%, transparent 60%)", filter: "blur(100px)", animation: "alC 23s ease-in-out infinite" }} />
        {/* L4: Left violet — Turrell signature */}
        <div className="al-orb" style={{ width: 600, height: 600, top: "30%", left: -120, background: "radial-gradient(ellipse, rgba(107,15,204,0.10) 0%, transparent 55%)", filter: "blur(90px)", animation: "alD 17s ease-in-out infinite" }} />
        {/* L5: Bottom-right warm red — subtle tension */}
        <div className="al-orb" style={{ width: 500, height: 350, bottom: "15%", right: "8%", background: "radial-gradient(ellipse, rgba(255,61,90,0.06) 0%, transparent 60%)", filter: "blur(80px)", animation: "alE 21s ease-in-out infinite" }} />
        {/* L6: Wide horizontal blue band — depth layer */}
        <div className="al-orb" style={{ width: 1400, height: 300, top: "55%", left: -100, background: "radial-gradient(ellipse, rgba(75,158,255,0.05) 0%, transparent 65%)", filter: "blur(100px)", animation: "alF 28s ease-in-out infinite" }} />
        {/* L7: Top-right green — secondary pulse */}
        <div className="al-orb" style={{ width: 400, height: 400, top: "8%", right: "15%", background: "radial-gradient(ellipse, rgba(0,232,122,0.07) 0%, transparent 60%)", filter: "blur(70px)", animation: "alG 15s ease-in-out infinite" }} />
        {/* L8: Bottom-right gold — warm anchor */}
        <div className="al-orb" style={{ width: 900, height: 700, bottom: -200, right: -200, background: "radial-gradient(ellipse, rgba(200,168,75,0.08) 0%, transparent 58%)", filter: "blur(100px)", animation: "alH 31s ease-in-out infinite" }} />
      </div>

      <div style={{ position: "relative", zIndex: 1 }}>

        {/* ══ NAV ═══════════════════════════════════════════════════════════ */}
        <nav style={{
          maxWidth: 1120, margin: "0 auto", padding: "24px 32px",
          display: "flex", alignItems: "center", justifyContent: "space-between",
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <span style={{ fontFamily: F.serif, fontSize: 22, fontWeight: 600, color: T.t1, letterSpacing: "-0.02em" }}>
              CometCloud
            </span>
            <span style={{
              fontFamily: F.mono, fontSize: 8, fontWeight: 600, padding: "2px 7px",
              borderRadius: 3, letterSpacing: "0.12em",
              background: "rgba(107,15,204,0.12)", color: T.purple,
              border: "1px solid rgba(107,15,204,0.25)",
            }}>AI</span>
          </div>
          <a href="app.html" style={{
            fontFamily: F.display, fontSize: 12, fontWeight: 600,
            color: T.t2, textDecoration: "none", letterSpacing: "0.04em",
            padding: "8px 18px", borderRadius: 6,
            border: `1px solid ${T.border}`,
            transition: "all 0.15s",
          }}
            onMouseEnter={(e) => { e.currentTarget.style.borderColor = "rgba(0,0,0,0.12)"; e.currentTarget.style.color = T.t1; }}
            onMouseLeave={(e) => { e.currentTarget.style.borderColor = T.border; e.currentTarget.style.color = T.t2; }}
          >
            Open Platform
          </a>
        </nav>

        {/* ══ SECTION 1: HERO ═══════════════════════════════════════════════ */}
        <Section style={{ paddingTop: 100, paddingBottom: 60, textAlign: "center" }}>
          <Label color={T.gold}>Investment Strategy</Label>
          <h1 style={{
            fontFamily: F.serif, fontSize: 52, fontWeight: 400,
            lineHeight: 1.15, color: T.t1, margin: "0 0 20px",
            letterSpacing: "-0.02em",
          }}>
            AI-Curated Crypto<br />Investment Intelligence
          </h1>
          <p style={{
            fontFamily: F.body, fontSize: 16, color: T.t2,
            lineHeight: 1.7, maxWidth: 640, margin: "0 auto 48px",
          }}>
            Proprietary CIS scoring engine analyzes digital assets across 5 dimensions.
            Three distinct investment channels — algorithmic trading, DeFi protocol yield,
            and fund-of-funds allocation — all driven by real-time intelligence.
          </p>

          {/* Key metrics strip */}
          <div style={{
            display: "flex", justifyContent: "center", gap: 48, flexWrap: "wrap",
            padding: "28px 0", borderTop: `1px solid ${T.border}`, borderBottom: `1px solid ${T.border}`,
          }}>
            <Stat label="Assets Scored" value={`${topAssets.length || 14}+`} sub="Crypto + TradFi" />
            <Stat label="Investment Channels" value="3" sub="Algo · Protocol · FoF" />
            <Stat label="Target AUM" value="$30M" sub="Phase 1" />
            <Stat label="Management Fee" value="0%" sub="Performance only" color={T.green} />
          </div>
        </Section>

        <Divider />

        {/* ══ SECTION 2: LIVE MARKET INTELLIGENCE ═══════════════════════════ */}
        <Section>
          <Label>Live Market Intelligence</Label>
          <h2 style={{
            fontFamily: F.display, fontSize: 28, fontWeight: 800,
            color: T.t1, margin: "0 0 8px", letterSpacing: "0.01em",
          }}>
            Current Market Regime:{" "}
            <span style={{ color: regimeColor }}>{macro ? regime : "Loading..."}</span>
          </h2>
          <p style={{
            fontFamily: F.body, fontSize: 13, color: T.t2, lineHeight: 1.65,
            maxWidth: 600, marginBottom: 32,
          }}>
            Our AI continuously monitors macro conditions, on-chain flows, and market sentiment
            to dynamically adjust allocation weights across all three investment channels.
          </p>

          <div style={{
            display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(180px, 1fr))",
            gap: 16,
          }}>
            {[
              { label: "BTC Dominance", value: btcDom ? `${btcDom.toFixed(1)}%` : "—", color: T.t1 },
              { label: "Fear & Greed", value: fngVal || "—", sub: fngLabel || "", color: fngVal ? (parseInt(fngVal) > 65 ? T.green : parseInt(fngVal) < 35 ? T.red : T.gold) : T.t3 },
              { label: "Total MCap 24h", value: mcapChange != null ? `${mcapChange >= 0 ? "+" : ""}${mcapChange.toFixed(1)}%` : "—", color: mcapChange >= 0 ? T.green : T.red },
              { label: "BTC 7D", value: macro?.btc?.usd_7d_change != null ? `${macro.btc.usd_7d_change >= 0 ? "+" : ""}${macro.btc.usd_7d_change.toFixed(1)}%` : "—", color: (macro?.btc?.usd_7d_change || 0) >= 0 ? T.green : T.red },
            ].map((m, i) => (
              <div key={i} style={{
                background: "rgba(10,14,24,0.7)", border: `1px solid ${T.border}`,
                borderRadius: 10, padding: "20px 18px", textAlign: "center",
              }}>
                <div style={{ fontFamily: F.mono, fontSize: 9, color: T.t3, letterSpacing: "0.14em", textTransform: "uppercase", marginBottom: 8 }}>
                  {m.label}
                </div>
                <div style={{ fontFamily: F.mono, fontSize: 24, fontWeight: 400, color: m.color, letterSpacing: "-0.02em" }}>
                  {m.value}
                </div>
                {m.sub && <div style={{ fontFamily: F.mono, fontSize: 10, color: T.t3, marginTop: 4 }}>{m.sub}</div>}
              </div>
            ))}
          </div>
        </Section>

        <Divider />

        {/* ══ SECTION 3: CIS ENGINE ═════════════════════════════════════════ */}
        <Section>
          <Label>Proprietary Scoring</Label>
          <h2 style={{
            fontFamily: F.display, fontSize: 28, fontWeight: 800,
            color: T.t1, margin: "0 0 8px",
          }}>
            CometCloud Intelligence Score
          </h2>
          <p style={{
            fontFamily: F.body, fontSize: 13, color: T.t2, lineHeight: 1.65,
            maxWidth: 640, marginBottom: 32,
          }}>
            Every asset is scored across five dimensions using real-time market data,
            on-chain analytics, and sentiment indicators. Scores update every 30 minutes
            from our local AI infrastructure.
          </p>

          {/* 5 Pillars */}
          <div style={{
            display: "grid", gridTemplateColumns: "repeat(5, 1fr)",
            gap: 12, marginBottom: 36,
          }}>
            {[
              { key: "F", name: "Fundamental", desc: "TVL, Market Cap, FDV ratio, Protocol revenue" },
              { key: "M", name: "Momentum", desc: "Price trend, 7D/30D change, Volume acceleration" },
              { key: "O", name: "On-chain Risk", desc: "Active addresses, Whale flows, Network health" },
              { key: "S", name: "Sentiment", desc: "Fear & Greed, VIX cross-reference, Social signals" },
              { key: "A", name: "Alpha", desc: "BTC divergence, Sector rotation, Regime sensitivity" },
            ].map((p) => (
              <div key={p.key} style={{
                background: "rgba(10,14,24,0.7)", border: `1px solid ${T.border}`,
                borderRadius: 10, padding: "18px 14px", textAlign: "center",
              }}>
                <div style={{
                  fontFamily: F.mono, fontSize: 22, fontWeight: 700,
                  color: T.gold, marginBottom: 6,
                }}>{p.key}</div>
                <div style={{ fontFamily: F.display, fontSize: 12, fontWeight: 700, color: T.t1, marginBottom: 6 }}>
                  {p.name}
                </div>
                <div style={{ fontFamily: F.body, fontSize: 10, color: T.t3, lineHeight: 1.5 }}>
                  {p.desc}
                </div>
              </div>
            ))}
          </div>

          {/* CIS Top 10 leaderboard */}
          <div style={{
            background: "rgba(10,14,24,0.7)", border: `1px solid ${T.border}`,
            borderRadius: 10, overflow: "hidden",
          }}>
            <div style={{
              display: "grid", gridTemplateColumns: "40px 1.5fr 0.8fr 0.7fr 0.6fr 0.7fr",
              padding: "12px 20px", borderBottom: `1px solid ${T.border}`,
              fontFamily: F.mono, fontSize: 9, color: T.t3,
              letterSpacing: "0.12em", textTransform: "uppercase",
            }}>
              <div>#</div>
              <div>Asset</div>
              <div style={{ textAlign: "right" }}>Score</div>
              <div style={{ textAlign: "center" }}>Grade</div>
              <div style={{ textAlign: "center" }}>Signal</div>
              <div style={{ textAlign: "right" }}>7D</div>
            </div>

            {topAssets.length === 0 ? (
              <div style={{ padding: 40, textAlign: "center", color: T.t3, fontFamily: F.mono, fontSize: 11 }}>
                Loading CIS scores...
              </div>
            ) : topAssets.map((a, i) => {
              const score = a.cis_score ?? a.score ?? 0;
              const grade = a.grade || "—";
              const signal = a.signal || "NEUTRAL";
              const ch7d = a.price_change_7d ?? a.change_7d ?? a.ch7d ?? 0;
              const sym = a.symbol || a.s || "—";
              return (
                <div key={i} style={{
                  display: "grid", gridTemplateColumns: "40px 1.5fr 0.8fr 0.7fr 0.6fr 0.7fr",
                  padding: "13px 20px", borderBottom: `1px solid ${T.border}`,
                  alignItems: "center",
                }}>
                  <span style={{ fontFamily: F.mono, fontSize: 11, color: T.t3 }}>{i + 1}</span>
                  <span style={{ fontFamily: F.display, fontSize: 13, fontWeight: 700, color: T.t1 }}>
                    {sym}
                  </span>
                  <span style={{ fontFamily: F.mono, fontSize: 13, textAlign: "right", color: T.t1 }}>
                    {score.toFixed(1)}
                  </span>
                  <span style={{
                    fontFamily: F.mono, fontSize: 13, fontWeight: 800, textAlign: "center",
                    color: GRADE_C[grade] || T.t3,
                  }}>
                    {grade}
                  </span>
                  <span style={{
                    fontFamily: F.display, fontSize: 9, fontWeight: 700,
                    textAlign: "center", letterSpacing: "0.04em",
                    color: signal.includes("OUTPERFORM") ? T.green : signal.includes("UNDER") ? T.red : T.gold,
                  }}>
                    {signal}
                  </span>
                  <span style={{
                    fontFamily: F.mono, fontSize: 12, textAlign: "right",
                    color: ch7d > 0 ? T.green : ch7d < 0 ? T.red : T.t3,
                  }}>
                    {ch7d > 0 ? "+" : ""}{ch7d.toFixed(1)}%
                  </span>
                </div>
              );
            })}

            <div style={{
              padding: "10px 20px", fontFamily: F.mono, fontSize: 9,
              color: T.t3, display: "flex", justifyContent: "space-between",
            }}>
              <span>Source: CIS v4.1 · CoinGecko Pro + DeFiLlama + Alternative.me</span>
              <span>Updated every 30 min via local AI engine</span>
            </div>
          </div>
        </Section>

        <Divider />

        {/* ══ SECTION 4: THREE INVESTMENT CHANNELS ══════════════════════════ */}
        <Section>
          <Label>Investment Channels</Label>
          <h2 style={{
            fontFamily: F.display, fontSize: 28, fontWeight: 800,
            color: T.t1, margin: "0 0 8px",
          }}>
            Three Ways to Invest
          </h2>
          <p style={{
            fontFamily: F.body, fontSize: 13, color: T.t2, lineHeight: 1.65,
            maxWidth: 640, marginBottom: 36,
          }}>
            CIS intelligence feeds directly into three distinct channels.
            Each channel is optimized for a different risk/return profile and investment horizon.
          </p>

          <div style={{ display: "flex", gap: 18, flexWrap: "wrap" }}>

            {/* Channel A: Trading Agent */}
            <ChannelCard
              icon="⚡"
              title="CIS Trading Strategy"
              subtitle="SYSTEMATIC · ALGO · CIS-POWERED"
              description="AI-powered systematic trading engine that converts CIS signals into position sizing and execution. Regime-aware allocation adjusts exposure between risk-on and risk-off environments."
              metrics={[
                { label: "Strategy", value: "Long/Short Crypto", color: T.t1 },
                { label: "Target Return", value: "15-25% Ann.", color: T.green },
                { label: "Max Drawdown", value: "< 15%", color: T.amber },
                { label: "Rebalance", value: "Every 30min", color: T.t1 },
              ]}
              status="DRY RUN IN DEPLOYMENT"
              statusColor={T.amber}
            >
              <div style={{ fontFamily: F.body, fontSize: 11, color: T.t3, lineHeight: 1.5 }}>
                <div style={{ marginBottom: 6, fontFamily: F.mono, fontSize: 9, color: T.t3, letterSpacing: "0.1em" }}>
                  SIGNAL FLOW
                </div>
                {["CIS Score Change → Signal Generation (OUTPERFORM/NEUTRAL/UNDERWEIGHT)",
                  "Macro Regime → Position Size Multiplier",
                  "Risk Limits → Max Allocation per Asset 8%",
                  "Execution → Freqtrade + CEX APIs"].map((s, i) => (
                  <div key={i} style={{ padding: "4px 0", borderBottom: i < 3 ? `1px solid ${T.border}` : "none", color: T.t2, fontSize: 11 }}>
                    {s}
                  </div>
                ))}
              </div>
            </ChannelCard>

            {/* Channel B: Protocol Yield */}
            <ChannelCard
              icon="🏦"
              title="Protocol Yield"
              subtitle="DEFI · CIS-CURATED · YIELD"
              description="CIS-rated DeFi protocol allocation. Capital is deployed to the highest-scoring protocols with verified security audits, sustainable yield sources, and sufficient TVL depth."
              metrics={[
                { label: "Protocols Rated", value: `${(protocols?.protocols || protocols?.data || []).length || 30}+`, color: T.t1 },
                { label: "Target APY", value: "8-18%", color: T.green },
                { label: "Min Audit Score", value: "7/10", color: T.t1 },
                { label: "Min TVL", value: "> $100M", color: T.t1 },
              ]}
              status="LIVE · DEFILLAMA DATA"
              statusColor={T.green}
            >
              {topProtocols.length > 0 ? (
                <div>
                  <div style={{ fontFamily: F.mono, fontSize: 9, color: T.t3, letterSpacing: "0.1em", marginBottom: 8 }}>
                    TOP CIS-RATED PROTOCOLS
                  </div>
                  {topProtocols.map((p, i) => (
                    <div key={i} style={{
                      display: "flex", justifyContent: "space-between", alignItems: "center",
                      padding: "6px 0", borderBottom: i < topProtocols.length - 1 ? `1px solid ${T.border}` : "none",
                    }}>
                      <span style={{ fontFamily: F.display, fontSize: 12, fontWeight: 600, color: T.t1 }}>
                        {p.name}
                      </span>
                      <div style={{ display: "flex", gap: 12, alignItems: "center" }}>
                        <span style={{ fontFamily: F.mono, fontSize: 11, color: T.t2 }}>
                          {p.tvl_formatted || "—"}
                        </span>
                        <span style={{
                          fontFamily: F.mono, fontSize: 11, fontWeight: 700,
                          color: GRADE_C[p.grade] || T.t3,
                        }}>
                          {p.grade || "—"}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div style={{ fontFamily: F.mono, fontSize: 10, color: T.t3 }}>Loading protocols...</div>
              )}
            </ChannelCard>

            {/* Channel C: Fund of Funds */}
            <ChannelCard
              icon="🗂"
              title="Fund of Funds"
              subtitle="INSTITUTIONAL · MULTI-GP · ON-CHAIN"
              description="Solana-based fund-of-funds allocating across CIS-scored GP partners. Zero management fee, performance-only structure aligned with LP interests. Denominated in OSL stablecoin."
              metrics={[
                { label: "Structure", value: "On-chain FoF", color: T.t1 },
                { label: "Target AUM", value: "$30M", color: T.t1 },
                { label: "Management Fee", value: "0%", color: T.green },
                { label: "Base", value: "Hong Kong", color: T.t1 },
              ]}
              status="GP ONBOARDING · Q2 2026"
              statusColor={T.amber}
            >
              <div>
                <div style={{ fontFamily: F.mono, fontSize: 9, color: T.t3, letterSpacing: "0.1em", marginBottom: 8 }}>
                  CONFIRMED GP PARTNERS
                </div>
                <div style={{
                  display: "flex", justifyContent: "space-between", alignItems: "center",
                  padding: "8px 0", borderBottom: `1px solid ${T.border}`,
                }}>
                  <div>
                    <div style={{ fontFamily: F.display, fontSize: 12, fontWeight: 600, color: T.t1 }}>EST Alpha</div>
                    <div style={{ fontFamily: F.mono, fontSize: 10, color: T.t3 }}>Multi-Strategy · Singapore</div>
                  </div>
                  <span style={{
                    fontFamily: F.mono, fontSize: 9, fontWeight: 700, padding: "2px 8px",
                    borderRadius: 3, background: "rgba(0,232,122,0.08)", color: T.green,
                    border: "1px solid rgba(0,232,122,0.2)",
                  }}>CONFIRMED</span>
                </div>
                <div style={{
                  display: "flex", justifyContent: "space-between", alignItems: "center",
                  padding: "8px 0",
                }}>
                  <div>
                    <div style={{ fontFamily: F.display, fontSize: 12, fontWeight: 600, color: T.t3 }}>Additional GPs</div>
                    <div style={{ fontFamily: F.mono, fontSize: 10, color: T.t3 }}>Onboarding Q2 2026</div>
                  </div>
                  <span style={{
                    fontFamily: F.mono, fontSize: 9, fontWeight: 700, padding: "2px 8px",
                    borderRadius: 3, background: "rgba(200,168,75,0.08)", color: T.gold,
                    border: "1px solid rgba(200,168,75,0.2)",
                  }}>PIPELINE</span>
                </div>
              </div>
            </ChannelCard>

          </div>
        </Section>

        <Divider />

        {/* ══ SECTION 5: HOW IT WORKS ═══════════════════════════════════════ */}
        <Section>
          <Label>Architecture</Label>
          <h2 style={{
            fontFamily: F.display, fontSize: 28, fontWeight: 800,
            color: T.t1, margin: "0 0 32px",
          }}>
            How It Works
          </h2>

          <div style={{
            display: "grid", gridTemplateColumns: "1fr 1fr",
            gap: 28,
          }}>
            <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
              <FlowStep num="1" title="Multi-Source Data Ingestion"
                desc="Real-time feeds from CoinGecko Pro, DeFiLlama, Alternative.me, and Binance. On-chain analytics, TVL flows, sentiment indices, and macro indicators aggregated every 30 minutes." />
              <FlowStep num="2" title="CIS Scoring Engine"
                desc="Dedicated local AI infrastructure scores each asset across 5 pillars. Regime-aware weight adjustments ensure scores reflect the current macro environment — not static rankings." />
              <FlowStep num="3" title="Signal Generation"
                desc="Scores are converted to positioning signals: STRONG OUTPERFORM, OUTPERFORM, NEUTRAL, UNDERPERFORM, UNDERWEIGHT. Confidence levels and recommended portfolio weights are computed per asset." />
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
              <FlowStep num="4" title="Channel Allocation"
                desc="Signals feed into three channels simultaneously. The Trading Agent executes positions, Protocol Yield rebalances DeFi allocations, and the Fund-of-Funds adjusts GP weights." />
              <FlowStep num="5" title="Risk Management"
                desc="Maximum per-asset allocation 8%, sector concentration limits, drawdown triggers, and automatic regime-based derisking. All positions monitored in real-time." />
              <FlowStep num="6" title="Investor Dashboard"
                desc="Full transparency: live CIS scores, channel performance, allocation breakdown, and risk metrics. Real-time updates via WebSocket. All data accessible on-platform." />
            </div>
          </div>
        </Section>

        <Divider />

        {/* ══ SECTION 6: RISK & STRUCTURE ═══════════════════════════════════ */}
        <Section>
          <Label>Risk & Structure</Label>
          <h2 style={{
            fontFamily: F.display, fontSize: 28, fontWeight: 800,
            color: T.t1, margin: "0 0 32px",
          }}>
            Institutional Grade Infrastructure
          </h2>

          <div style={{
            display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))",
            gap: 16,
          }}>
            {[
              { title: "Regulatory Framework", desc: "Hong Kong incorporated entity. Structured for institutional LP participation with proper fund documentation and compliance.", icon: "🏛" },
              { title: "Technology Stack", desc: "Cloud-native architecture with real-time data pipelines, local AI scoring infrastructure, persistent caching, and WebSocket live updates.", icon: "⚙" },
              { title: "Fee Structure", desc: "Zero management fee. Performance-only fee alignment ensures our interests are fully aligned with LP returns.", icon: "💎" },
              { title: "On-Chain Settlement", desc: "Solana-based fund operations. OSL stablecoin denominated. Designed for both human LPs and autonomous AI agent participation.", icon: "⛓" },
              { title: "Risk Controls", desc: "Max 8% single-asset allocation. Regime-based derisking. Drawdown triggers. 6 macro regime detection for dynamic weight adjustment.", icon: "🛡" },
              { title: "Transparency", desc: "Full CIS methodology published. Real-time scoring visible on dashboard. Score history and grade migration tracking for all assets.", icon: "📊" },
            ].map((card, i) => (
              <div key={i} style={{
                background: "rgba(10,14,24,0.7)", border: `1px solid ${T.border}`,
                borderRadius: 10, padding: "22px 18px",
              }}>
                <div style={{ fontSize: 20, marginBottom: 10 }}>{card.icon}</div>
                <div style={{ fontFamily: F.display, fontSize: 14, fontWeight: 700, color: T.t1, marginBottom: 8 }}>
                  {card.title}
                </div>
                <div style={{ fontFamily: F.body, fontSize: 12, color: T.t2, lineHeight: 1.6 }}>
                  {card.desc}
                </div>
              </div>
            ))}
          </div>
        </Section>

        <Divider />

        {/* ══ SECTION 7: CTA ════════════════════════════════════════════════ */}
        <Section style={{ textAlign: "center", paddingBottom: 120 }}>
          <h2 style={{
            fontFamily: F.serif, fontSize: 38, fontWeight: 400,
            color: T.t1, margin: "0 0 16px", letterSpacing: "-0.02em",
          }}>
            Ready to See the Full Platform?
          </h2>
          <p style={{
            fontFamily: F.body, fontSize: 14, color: T.t2,
            maxWidth: 480, margin: "0 auto 36px", lineHeight: 1.65,
          }}>
            Schedule a walkthrough of the CIS scoring engine, live market intelligence,
            and investment channel allocation. Available for qualified institutional investors
            and family offices.
          </p>
          <div style={{ display: "flex", gap: 16, justifyContent: "center" }}>
            <a href="app.html" style={{
              fontFamily: F.display, fontSize: 14, fontWeight: 700,
              color: "#fff", textDecoration: "none", letterSpacing: "0.04em",
              padding: "14px 32px", borderRadius: 8,
              background: "linear-gradient(135deg, rgba(107,15,204,0.6), rgba(45,53,212,0.6))",
              border: "1px solid rgba(107,15,204,0.3)",
              transition: "all 0.2s",
            }}
              onMouseEnter={(e) => e.currentTarget.style.transform = "translateY(-1px)"}
              onMouseLeave={(e) => e.currentTarget.style.transform = "translateY(0)"}
            >
              Open Platform
            </a>
            <a href="mailto:jazz@cometcloud.ai" style={{
              fontFamily: F.display, fontSize: 14, fontWeight: 700,
              color: T.t2, textDecoration: "none", letterSpacing: "0.04em",
              padding: "14px 32px", borderRadius: 8,
              border: `1px solid ${T.border}`,
              transition: "all 0.2s",
            }}
              onMouseEnter={(e) => { e.currentTarget.style.borderColor = "rgba(0,0,0,0.12)"; e.currentTarget.style.color = T.t1; }}
              onMouseLeave={(e) => { e.currentTarget.style.borderColor = T.border; e.currentTarget.style.color = T.t2; }}
            >
              Contact Us
            </a>
          </div>
        </Section>

        {/* ══ FOOTER ════════════════════════════════════════════════════════ */}
        <footer style={{
          maxWidth: 1120, margin: "0 auto", padding: "24px 32px 40px",
          borderTop: `1px solid ${T.border}`,
          display: "flex", justifyContent: "space-between", alignItems: "center",
        }}>
          <span style={{ fontFamily: F.serif, fontSize: 14, color: T.t3, letterSpacing: "-0.01em" }}>
            CometCloud AI
          </span>
          <span style={{ fontFamily: F.mono, fontSize: 9, color: T.t3, letterSpacing: "0.08em" }}>
            HONG KONG · {new Date().getFullYear()}
          </span>
        </footer>
      </div>

      <style>{`
        * { margin: 0; padding: 0; box-sizing: border-box; }
        html { scroll-behavior: smooth; }
        body { background: ${T.void}; }
        ::selection { background: rgba(107,15,204,0.3); }
        a { cursor: pointer; }

        .al-orb {
          position: absolute;
          border-radius: 50%;
          mix-blend-mode: screen;
        }

        /* 8 async ambient animations — each orb breathes independently */
        @keyframes alA { 0%,100% { opacity:.7; transform:scale(1) translate(0,0); } 50% { opacity:1; transform:scale(1.18) translate(28px,18px); } }
        @keyframes alB { 0%,100% { opacity:.5; transform:scale(1) translate(0,0); } 50% { opacity:.9; transform:scale(1.22) translate(-22px,28px); } }
        @keyframes alC { 0%,100% { opacity:.6; transform:scale(1); } 60% { opacity:1; transform:scale(1.3) translateX(30px); } }
        @keyframes alD { 0%,100% { opacity:.4; transform:scale(1); } 50% { opacity:.8; transform:scale(1.25) translate(15px,-20px); } }
        @keyframes alE { 0%,100% { opacity:.3; transform:scale(1); } 50% { opacity:.7; transform:scale(1.2) translate(-10px,10px); } }
        @keyframes alF { 0%,100% { opacity:.5; transform:scaleX(1); } 50% { opacity:.9; transform:scaleX(1.1); } }
        @keyframes alG { 0%,100% { opacity:.4; transform:scale(1); } 50% { opacity:.7; transform:scale(1.3); } }
        @keyframes alH { 0%,100% { opacity:.3; transform:scale(1); } 50% { opacity:.6; transform:scale(1.15); } }
      `}</style>
    </div>
  );
}
