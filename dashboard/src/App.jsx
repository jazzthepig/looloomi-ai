import { useState } from "react";
import MarketDashboard from "./components/MarketDashboard";
import IntelligencePage from "./components/IntelligencePage";
import CISLeaderboard from "./components/CISLeaderboard";
import VaultPage from "./components/VaultPage";
import ProtocolPage from "./components/ProtocolPage";

const FONTS = {
  display: "'Space Grotesk', sans-serif",
  body: "'Exo 2', sans-serif",
  mono: "'JetBrains Mono', monospace",
};

const T = {
  void: "#020208",
  surface: "#0f0f1a",
  border: "rgba(255,255,255,0.06)",
  borderHi: "rgba(255,255,255,0.12)",
  primary: "#F0EEFF",
  secondary: "#94a3b8",
  muted: "#64748b",
  cyan: "#06b6d4",
  gold: "#f59e0b",
  violet: "#8b5cf6",
};

export default function App() {
  const [activeTab, setActiveTab] = useState("Home");

  return (
    <>
      {activeTab === "Home" && <HomePage activeTab={activeTab} setActiveTab={setActiveTab} />}
      {activeTab === "Market" && <MarketDashboard activeTab={activeTab} setActiveTab={setActiveTab} />}
      {(activeTab === "Intelligence" || activeTab === "Quant GP") && (
        <IntelligencePage activeTab={activeTab} setActiveTab={setActiveTab} />
      )}
      {activeTab === "CIS" && <CISPage activeTab={activeTab} setActiveTab={setActiveTab} />}
      {activeTab === "Vault" && <VaultPage activeTab={activeTab} setActiveTab={setActiveTab} />}
      {activeTab === "Protocol" && <ProtocolPage activeTab={activeTab} setActiveTab={setActiveTab} />}
    </>
  );
}

/* ─────────────────────────────────────────────────────────────────────────
   HOME PAGE — Hero Section
──────────────────────────────────────────────────────────────────────── */
function HomePage({ activeTab, setActiveTab }) {
  return (
    <div style={{ position: "relative", minHeight: "100vh", background: T.void, overflow: "hidden" }}>
      {/* Ambient orbs */}
      <div style={{
        position: "fixed", inset: 0, pointerEvents: "none", zIndex: 0,
        background: "radial-gradient(ellipse 80% 60% at 50% 0%, rgba(6,182,212,0.12) 0%, transparent 60%), radial-gradient(ellipse 60% 50% at 80% 80%, rgba(245,158,11,0.08) 0%, transparent 50%)",
      }} />

      {/* Navigation */}
      <nav style={{
        position: "relative", zIndex: 10, display: "flex", alignItems: "center", justifyContent: "space-between",
        padding: "24px 48px", borderBottom: `1px solid ${T.border}`,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 32 }}>
          <span style={{
            fontFamily: FONTS.display, fontWeight: 700, fontSize: 24,
            letterSpacing: "-0.02em", color: T.primary,
            textShadow: "0 0 40px rgba(6,182,212,0.4)",
          }}>
            CometCloud
          </span>
          <div style={{ display: "flex", gap: 4 }}>
            {["Home", "Market", "Intelligence", "CIS", "Vault", "Protocol", "Quant GP"].map(tab => (
              <button key={tab}
                onClick={() => setActiveTab(tab)}
                style={{
                  padding: "10px 18px", borderRadius: 6, fontSize: 14, fontWeight: 500,
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
      </nav>

      {/* Hero Content */}
      <div style={{
        position: "relative", zIndex: 1, maxWidth: 1200, margin: "0 auto", padding: "80px 48px",
        display: "grid", gridTemplateColumns: "1fr 1fr", gap: 80, alignItems: "center",
      }}>
        {/* Left: Text */}
        <div>
          <div style={{
            fontFamily: FONTS.display, fontSize: 56, fontWeight: 700, color: T.primary,
            lineHeight: 1.1, letterSpacing: "-0.03em", marginBottom: 24,
          }}>
            Navigation Infrastructure for the<br />
            <span style={{
              background: "linear-gradient(135deg, #06b6d4 0%, #f59e0b 100%)",
              WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent",
            }}>On-Chain World</span>
          </div>
          <p style={{
            fontFamily: FONTS.body, fontSize: 18, color: T.secondary,
            lineHeight: 1.7, marginBottom: 40, maxWidth: 500,
          }}>
            AI-powered intelligence platform combining on-chain analytics,
            institutional fund intelligence, and RWA market data — built for
            institutional investors and AI agents.
          </p>

          {/* Value Props */}
          <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
            {[
              { icon: "◆", title: "CIS Scoring", desc: "Open-source 5-pillar asset evaluation" },
              { icon: "◈", title: "Fund Intelligence", desc: "GP selection framework for crypto funds" },
              { icon: "◇", title: "RWA Analytics", desc: "Real-time tokenized asset market data" },
            ].map((item, i) => (
              <div key={i} style={{ display: "flex", alignItems: "center", gap: 16 }}>
                <div style={{
                  width: 40, height: 40, borderRadius: 8,
                  background: "rgba(6,182,212,0.1)", border: `1px solid ${T.borderHi}`,
                  display: "flex", alignItems: "center", justifyContent: "center",
                  color: T.cyan, fontSize: 16,
                }}>
                  {item.icon}
                </div>
                <div>
                  <div style={{ fontFamily: FONTS.display, fontWeight: 600, fontSize: 16, color: T.primary }}>
                    {item.title}
                  </div>
                  <div style={{ fontFamily: FONTS.body, fontSize: 13, color: T.muted }}>
                    {item.desc}
                  </div>
                </div>
              </div>
            ))}
          </div>

          {/* CTA Buttons */}
          <div style={{ display: "flex", gap: 12, marginTop: 40 }}>
            <button onClick={() => setActiveTab("Intelligence")}
              style={{
                padding: "14px 28px", borderRadius: 8, fontSize: 14, fontWeight: 600,
                fontFamily: FONTS.body, cursor: "pointer", border: "none",
                background: T.cyan, color: "#fff",
              }}>
              Explore Intelligence
            </button>
            <button onClick={() => setActiveTab("Vault")}
              style={{
                padding: "14px 28px", borderRadius: 8, fontSize: 14, fontWeight: 600,
                fontFamily: FONTS.body, cursor: "pointer", border: `1px solid ${T.borderHi}`,
                background: "transparent", color: T.primary,
              }}>
              Fund-of-Funds
            </button>
          </div>
        </div>

        {/* Right: Visual */}
        <div style={{
          position: "relative", height: 400,
        }}>
          {/* Abstract orb visualization */}
          <div style={{
            position: "absolute", inset: 0,
            background: "radial-gradient(circle at 30% 30%, rgba(6,182,212,0.3) 0%, transparent 50%), radial-gradient(circle at 70% 70%, rgba(245,158,11,0.2) 0%, transparent 50%)",
            filter: "blur(60px)",
            animation: "pulse 8s ease-in-out infinite",
          }} />
          {/* Grid lines */}
          <div style={{
            position: "absolute", inset: 0,
            backgroundImage: `linear-gradient(${T.border} 1px, transparent 1px), linear-gradient(90deg, ${T.border} 1px, transparent 1px)`,
            backgroundSize: "40px 40px", opacity: 0.5,
          }} />
        </div>
      </div>

      <style>{`
        @keyframes pulse { 0%,100%{opacity:0.8;transform:scale(1)} 50%{opacity:1;transform:scale(1.02)} }
      `}</style>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────────────
   CIS Page wrapper with navigation
──────────────────────────────────────────────────────────────────────── */
function CISPage({ activeTab, setActiveTab }) {
  return (
    <div style={{ position: "relative", minHeight: "100vh", background: T.void }}>
      <div className="turrell-wrap">
        <div className="t-orb t-orb-1" /><div className="t-orb t-orb-2" />
        <div className="t-orb t-orb-3" /><div className="t-orb t-orb-4" />
      </div>

      <div style={{ position: "relative", zIndex: 1, maxWidth: 1600, margin: "0 auto", padding: "0 28px 56px" }}>
        {/* Navigation */}
        <nav style={{
          display: "flex", alignItems: "center", justifyContent: "space-between",
          padding: "18px 0 20px", borderBottom: `1px solid ${T.border}`,
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 32 }}>
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
        </nav>

        {/* Header */}
        <div style={{ marginTop: 32, marginBottom: 24 }}>
          <h1 style={{
            fontFamily: FONTS.display, fontSize: 32, fontWeight: 700,
            color: T.primary, marginBottom: 8, letterSpacing: "-0.02em"
          }}>
            CIS Leaderboard
          </h1>
          <p style={{
            fontFamily: FONTS.body, fontSize: 14, color: T.secondary,
            maxWidth: 600, lineHeight: 1.6
          }}>
            CometCloud Intelligence Score — Multi-dimensional asset evaluation
            across Fundamental, Market Structure, On-Chain Health, Sentiment, and Alpha Independence.
          </p>
        </div>

        {/* Stats Summary - improved spacing */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 16, marginBottom: 32 }}>
          {[
            { label: "Total Assets", value: "20", color: "#4472FF" },
            { label: "Grade A", value: "4", color: "#00D98A" },
            { label: "Grade B", value: "12", color: "#4472FF" },
            { label: "Grade C", value: "4", color: "#E8A000" },
          ].map((s, i) => (
            <div key={i} style={{
              background: T.surface, border: `1px solid ${T.border}`,
              borderRadius: 10, padding: 24,
            }}>
              <div style={{ fontSize: 11, color: T.muted, letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 12, fontFamily: FONTS.body }}>
                {s.label}
              </div>
              <div style={{ fontSize: 32, fontWeight: 700, color: s.color, fontFamily: FONTS.mono }}>
                {s.value}
              </div>
            </div>
          ))}
        </div>

        {/* Leaderboard */}
        <div style={{ background: T.surface, border: `1px solid ${T.border}`, borderRadius: 10, overflow: "hidden" }}>
          <CISLeaderboard />
        </div>
      </div>

      <style>{`
        .turrell-wrap { position:fixed;inset:0;pointer-events:none;z-index:0;overflow:hidden; }
        .t-orb { position:absolute;border-radius:50%;filter:blur(100px);mix-blend-mode:screen; }
        .t-orb-1 { width:720px;height:720px;background:radial-gradient(circle,rgba(107,15,204,.20) 0%,transparent 65%);top:-300px;left:-200px;animation:breathe 52s ease-in-out infinite; }
        .t-orb-2 { width:560px;height:560px;background:radial-gradient(circle,rgba(45,53,212,.15) 0%,transparent 65%);top:5%;right:-200px;animation:breathe2 64s ease-in-out infinite 9s; }
        .t-orb-3 { width:380px;height:380px;background:radial-gradient(circle,rgba(0,200,224,.09) 0%,transparent 65%);bottom:0;left:22%;animation:breathe 76s ease-in-out infinite 24s; }
        .t-orb-4 { width:280px;height:280px;background:radial-gradient(circle,rgba(255,16,96,.07) 0%,transparent 65%);bottom:12%;right:8%;animation:breathe2 60s ease-in-out infinite 38s; }
        @keyframes breathe { 0%,100%{opacity:.28;transform:scale(1) translateY(0)} 50%{opacity:.44;transform:scale(1.06) translateY(-12px)} }
        @keyframes breathe2 { 0%,100%{opacity:.16;transform:scale(1)} 50%{opacity:.30;transform:scale(1.08) translateX(10px)} }
      `}</style>
    </div>
  );
}
