import { useState, useEffect, useRef } from "react";
import MarketDashboard from "./components/MarketDashboard";
import IntelligencePage from "./components/IntelligencePage";
import CISLeaderboard from "./components/CISLeaderboard";
import VaultPage from "./components/VaultPage";
import ProtocolPage from "./components/ProtocolPage";
import { T, FONTS } from "./tokens";

const SECTIONS = [
  { id: "market", label: "Asset Prices" },
  { id: "intelligence", label: "Intelligence" },
  { id: "cis", label: "CIS" },
  { id: "protocol", label: "Protocol" },
  { id: "vault", label: "Vault" },
  { id: "quantgp", label: "Quant GP" },
];

export default function App() {
  const [activeSection, setActiveSection] = useState("market");
  const sectionRefs = useRef({});

  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            setActiveSection(entry.target.id);
          }
        });
      },
      { rootMargin: "-20% 0px -60% 0px", threshold: 0 }
    );

    SECTIONS.forEach(({ id }) => {
      const el = document.getElementById(id);
      if (el) observer.observe(el);
    });

    return () => observer.disconnect();
  }, []);

  const scrollToSection = (id) => {
    const el = document.getElementById(id);
    if (el) {
      el.scrollIntoView({ behavior: "smooth" });
    }
  };

  return (
    <div style={{ background: "#030508", minHeight: "100vh", position: "relative" }}>
      {/* AMBIENT LIGHT SYSTEM - 8 layers */}
      <div className="turrell-canvas">
        <div className="turrell-void"></div>
        <div className="al1"></div>
        <div className="al2"></div>
        <div className="al3"></div>
        <div className="al4"></div>
        <div className="al5"></div>
        <div className="al6"></div>
        <div className="al7"></div>
        <div className="al8"></div>
      </div>

      {/* Fixed Navigation */}
      <nav style={{
        position: "fixed", top: 0, left: 0, right: 0, zIndex: 1000,
        background: "rgba(3,5,8,0.85)", backdropFilter: "blur(20px)",
        borderBottom: `1px solid ${T.border}`, display: "flex", alignItems: "center",
        justifyContent: "space-between", padding: "16px 48px",
      }}>
        <span
          onClick={() => scrollToSection("market")}
          style={{
            fontFamily: FONTS.display, fontWeight: 700, fontSize: 20,
            letterSpacing: "0.1em", color: T.primary, cursor: "pointer",
            textShadow: "0 0 40px rgba(200,168,75,0.3)",
          }}
        >
          COMETCLOUD
        </span>
        <div style={{ display: "flex", gap: 2, background: T.raised, borderRadius: 10, padding: 3, border: `1px solid ${T.border}` }}>
          {SECTIONS.map(({ id, label }) => (
            <button
              key={id}
              onClick={() => scrollToSection(id)}
              style={{
                padding: "7px 16px", borderRadius: 7, fontSize: 12, fontWeight: 700,
                fontFamily: FONTS.display, cursor: "pointer", outline: "none",
                border: "1px solid transparent",
                background: activeSection === id ? T.goldDim : "transparent",
                color: activeSection === id ? T.gold : "rgba(255,255,255,0.50)",
                transition: "all 0.2s ease",
                letterSpacing: "0.08em",
                textTransform: "uppercase",
              }}
            >
              {label}
            </button>
          ))}
        </div>
      </nav>

      {/* Sections Container - padding for fixed nav */}
      <div style={{ paddingTop: 64 }}>

        {/* Section 1: Market */}
        <section id="market" style={sectionStyle(0)}>
          <MarketDashboard isSection={true} />
        </section>

        {/* Section Separator */}
        <div className="section-divider" />

        {/* Section 2: Intelligence */}
        <section id="intelligence" style={sectionStyle(1)}>
          <IntelligencePage isSection={true} />
        </section>

        {/* Section Separator */}
        <div className="section-divider" />

        {/* Section 3: CIS */}
        <section id="cis" style={sectionStyle(0)}>
          <CISContent />
        </section>

        {/* Section Separator */}
        <div className="section-divider" />

        {/* Section 4: Protocol */}
        <section id="protocol" style={sectionStyle(1)}>
          <ProtocolPage isSection={true} />
        </section>

        {/* Section Separator */}
        <div className="section-divider" />

        {/* Section 5: Vault */}
        <section id="vault" style={sectionStyle(0)}>
          <VaultPage isSection={true} />
        </section>

        {/* Section Separator */}
        <div className="section-divider" />

        {/* Section 6: Quant GP */}
        <section id="quantgp" style={sectionStyle(1)}>
          <QuantGPContent />
        </section>

      </div>

      <style>{`
        * { scroll-behavior: smooth; }
        body { background: #030508; min-height: 100vh; }

        /* ── AMBIENT LIGHT SYSTEM — 8 layers, async breathing ── */
        .turrell-canvas {
          position: fixed;
          inset: 0;
          z-index: 0;
          pointer-events: none;
          overflow: hidden;
        }

        /* LAYER 1: Top-left green glow */
        .turrell-void {
          position: absolute;
          inset: 0;
          background: radial-gradient(ellipse 120% 100% at 50% 50%, #050810 0%, #030508 50%, #030508 100%);
        }

        .al1 {
          position: absolute;
          width: 900px;
          height: 500px;
          top: -180px;
          left: -120px;
          background: radial-gradient(ellipse, rgba(0, 232, 122, 0.028), transparent 65%);
          filter: blur(80px);
          animation: al1 13s ease-in-out infinite;
        }

        .al2 {
          position: absolute;
          width: 600px;
          height: 400px;
          top: 300px;
          right: -150px;
          background: radial-gradient(ellipse, rgba(200, 168, 75, 0.022), transparent 65%);
          filter: blur(80px);
          animation: al2 19s ease-in-out infinite;
        }

        .al3 {
          position: absolute;
          width: 700px;
          height: 300px;
          bottom: -100px;
          left: 30%;
          background: radial-gradient(ellipse, rgba(75, 158, 255, 0.018), transparent 65%);
          filter: blur(80px);
          animation: al3 23s ease-in-out infinite;
        }

        .al4 {
          position: absolute;
          width: 400px;
          height: 400px;
          top: 40%;
          left: -80px;
          background: radial-gradient(ellipse, rgba(167, 139, 250, 0.012), transparent 65%);
          filter: blur(80px);
          animation: al4 17s ease-in-out infinite;
        }

        .al5 {
          position: absolute;
          width: 500px;
          height: 250px;
          bottom: 20%;
          right: 10%;
          background: radial-gradient(ellipse, rgba(255, 61, 90, 0.014), transparent 65%);
          filter: blur(80px);
          animation: al5 21s ease-in-out infinite;
        }

        .al6 {
          position: absolute;
          width: 1100px;
          height: 200px;
          top: 60%;
          left: 0;
          background: radial-gradient(ellipse, rgba(75, 158, 255, 0.010), transparent 70%);
          filter: blur(80px);
          animation: al6 28s ease-in-out infinite;
        }

        .al7 {
          position: absolute;
          width: 300px;
          height: 300px;
          top: 10%;
          right: 20%;
          background: radial-gradient(ellipse, rgba(0, 232, 122, 0.010), transparent 65%);
          filter: blur(80px);
          animation: al7 15s ease-in-out infinite;
        }

        .al8 {
          position: absolute;
          width: 800px;
          height: 600px;
          bottom: -200px;
          right: -200px;
          background: radial-gradient(ellipse, rgba(200, 168, 75, 0.008), transparent 65%);
          filter: blur(80px);
          animation: al8 31s ease-in-out infinite;
        }

        @keyframes al1 {
          0%, 100% { opacity: 0.7; transform: scale(1) translate(0, 0); }
          50% { opacity: 1; transform: scale(1.18) translate(28px, 18px); }
        }
        @keyframes al2 {
          0%, 100% { opacity: 0.5; transform: scale(1) translate(0, 0); }
          50% { opacity: 0.9; transform: scale(1.22) translate(-22px, 28px); }
        }
        @keyframes al3 {
          0%, 100% { opacity: 0.6; transform: scale(1); }
          60% { opacity: 1; transform: scale(1.3) translateX(30px); }
        }
        @keyframes al4 {
          0%, 100% { opacity: 0.4; transform: scale(1); }
          50% { opacity: 0.8; transform: scale(1.25) translate(15px, -20px); }
        }
        @keyframes al5 {
          0%, 100% { opacity: 0.3; transform: scale(1); }
          50% { opacity: 0.7; transform: scale(1.2) translate(-10px, 10px); }
        }
        @keyframes al6 {
          0%, 100% { opacity: 0.5; transform: scaleX(1); }
          50% { opacity: 0.9; transform: scaleX(1.1); }
        }
        @keyframes al7 {
          0%, 100% { opacity: 0.4; transform: scale(1); }
          50% { opacity: 0.7; transform: scale(1.3); }
        }
        @keyframes al8 {
          0%, 100% { opacity: 0.3; transform: scale(1); }
          50% { opacity: 0.6; transform: scale(1.15); }
        }

        /* ── SECTION DIVIDERS ── */
        .section-divider {
          height: 1px;
          background: linear-gradient(90deg, transparent 0%, rgba(200,168,75,0.025) 20%, rgba(200,168,75,0.06) 50%, rgba(200,168,75,0.025) 80%, transparent 100%);
          position: relative;
        }
        .section-divider::after {
          content: '';
          position: absolute;
          top: -3px;
          left: 50%;
          transform: translateX(-50%);
          width: 35%;
          height: 6px;
          background: radial-gradient(ellipse, rgba(6,182,212,0.04) 0%, transparent 70%);
          filter: blur(4px);
        }

        /* ── NAVBAR GLASSMORPHISM ── */
        nav {
          background: rgba(3, 3, 10, 0.75) !important;
          backdrop-filter: blur(16px);
          -webkit-backdrop-filter: blur(16px);
          border-bottom: 1px solid rgba(255,255,255,0.04) !important;
        }

        /* ── RESPONSIVE: Nav tabs on small screens ── */
        @media (max-width: 900px) {
          nav {
            overflow-x: auto;
            padding: 10px 12px;
          }
          nav span[style*="fontFamily: FONTS.display"] {
            font-size: 16px !important;
          }
          nav button {
            padding: 6px 10px !important;
            font-size: 12px !important;
          }
        }

        /* ── RESPONSIVE: Tables scroll horizontally ── */
        @media (max-width: 768px) {
          .tbl-wrap, .table-wrap {
            overflow-x: auto;
          }
        }

        /* ── RESPONSIVE: Section padding for different viewports ── */
        @media (max-width: 480px) {
          section {
            padding: 24px 12px !important;
          }
        }
        @media (min-width: 481px) and (max-width: 768px) {
          section {
            padding: 40px 16px !important;
          }
        }
        @media (min-width: 769px) and (max-width: 1024px) {
          section {
            padding: 60px 32px !important;
          }
        }
        @media (min-width: 1400px) {
          section {
            padding: 80px 80px !important;
          }
        }
        @media (min-width: 1800px) {
          section {
            padding: 100px 100px !important;
          }
        }

        /* ── RESPONSIVE: Grid adjustments ── */
        @media (max-width: 640px) {
          .mobile-stat-grid {
            grid-template-columns: 1fr 1fr !important;
            gap: 8px !important;
          }
        }

        /* ── RESPONSIVE: Quant GP ── */
        @media (max-width: 768px) {
          #quantgp .mobile-stat-grid {
            grid-template-columns: 1fr 1fr !important;
          }
        }

        /* ── RESPONSIVE: Page headers ── */
        @media (max-width: 768px) {
          section h1 {
            font-size: 22px !important;
            margin-bottom: 12px !important;
          }
          section > div > div:first-child {
            margin-top: 16px !important;
            margin-bottom: 16px !important;
          }
        }

        /* ── CARD TRANSPARENCY ── */
        .lm-card, .card, [class*="card"] {
          background: rgba(255, 255, 255, 0.05) !important;
          border: 1px solid rgba(255, 255, 255, 0.10) !important;
          backdrop-filter: blur(8px);
        }
      `}</style>
    </div>
  );
}

const sectionStyle = (index) => ({
  minHeight: "auto",
  padding: "80px 64px",
  background: "transparent",
  borderTop: "1px solid rgba(255,255,255,0.04)",
  position: "relative",
  zIndex: 1,
});

/* ─────────────────────────────────────────────────────────────────────────
   HERO SECTION
──────────────────────────────────────────────────────────────────────── */
function HeroContent() {
  const scrollTo = (id) => {
    document.getElementById(id)?.scrollIntoView({ behavior: "smooth" });
  };

  return (
    <div style={{
      position: "relative", maxWidth: 1200, margin: "0 auto", paddingTop: 40,
      display: "grid", gridTemplateColumns: "1fr 1fr", gap: 80, alignItems: "center",
    }}>
      {/* Ambient orbs */}
      <div style={{
        position: "fixed", inset: 0, pointerEvents: "none", zIndex: 0,
        background: "radial-gradient(ellipse 80% 60% at 70% 40%, rgba(6,182,212,0.08) 0%, rgba(245,158,11,0.04) 40%, transparent 70%), #0a0a0f",
      }} />

      {/* Left: Text */}
      <div style={{ position: "relative", zIndex: 1 }}>
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
          <button onClick={() => scrollTo("intelligence")}
            style={{
              padding: "14px 28px", borderRadius: 8, fontSize: 14, fontWeight: 600,
              fontFamily: FONTS.body, cursor: "pointer", border: "none",
              background: T.cyan, color: "#fff",
            }}>
            Explore Intelligence
          </button>
          <button onClick={() => scrollTo("vault")}
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
      <div style={{ position: "relative", height: 400 }}>
        <div style={{
          position: "absolute", inset: 0,
          background: "radial-gradient(circle at 30% 30%, rgba(6,182,212,0.3) 0%, transparent 50%), radial-gradient(circle at 70% 70%, rgba(245,158,11,0.2) 0%, transparent 50%)",
          filter: "blur(60px)",
          animation: "pulse 8s ease-in-out infinite",
        }} />
      </div>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────────────
   CIS SECTION
──────────────────────────────────────────────────────────────────────── */
function CISContent() {
  return (
    <div style={{ maxWidth: 1600, margin: "0 auto" }}>
      {/* Section Header */}
      <div style={{ marginBottom: 32 }}>
        <h2 style={{
          fontFamily: FONTS.display, fontSize: 32, fontWeight: 700,
          color: T.primary, marginBottom: 8, letterSpacing: "-0.02em"
        }}>
          <span style={{ color: T.cyan, marginRight: 12 }}>//</span>
          CIS Leaderboard
        </h2>
        <p style={{
          fontFamily: FONTS.body, fontSize: 14, color: T.secondary,
          maxWidth: 600, lineHeight: 1.6
        }}>
          CometCloud Intelligence Score — Multi-dimensional asset evaluation
          across Fundamental, Market Structure, On-Chain Health, Sentiment, and Alpha Independence.
        </p>
      </div>

      {/* Leaderboard */}
      <div style={{ background: T.surface, border: `1px solid ${T.border}`, borderRadius: 10, overflow: "hidden" }}>
        <CISLeaderboard />
      </div>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────────────
   QUANT GP SECTION — EST Alpha Partner
──────────────────────────────────────────────────────────────────────── */
function QuantGPContent() {
  return (
    <div style={{ maxWidth: 1600, margin: "0 auto" }}>
      {/* Section 1 — Partnership Banner */}
      <div style={{
        background: "linear-gradient(135deg, rgba(200,168,75,0.08) 0%, rgba(200,168,75,0.02) 50%, transparent 100%)",
        border: "1px solid rgba(200,168,75,0.28)",
        borderRadius: 12, padding: "24px 32px", marginBottom: 24,
        display: "flex", alignItems: "center", justifyContent: "space-between",
        flexWrap: "wrap", gap: 20,
      }}>
        {/* Left: Logo placeholder */}
        <div style={{
          width: 64, height: 64, borderRadius: "50%",
          background: "linear-gradient(135deg, #1a1520 0%, #0d0a10 100%)",
          border: "2px solid rgba(200,168,75,0.4)",
          display: "flex", alignItems: "center", justifyContent: "center",
        }}>
          <span style={{
            fontFamily: FONTS.display, fontSize: 24, fontWeight: 800,
            color: "#C8A84B", letterSpacing: "-0.02em",
          }}>E</span>
        </div>

        {/* Center: Name + Partner info */}
        <div style={{ flex: 1, minWidth: 200 }}>
          <div style={{
            fontFamily: FONTS.display, fontSize: 24, fontWeight: 700,
            color: T.primary, letterSpacing: "-0.01em", marginBottom: 4,
          }}>
            EST Alpha
          </div>
          <div style={{
            fontFamily: FONTS.body, fontSize: 13, color: T.secondary,
          }}>
            CometCloud GP Partner · Since 2025
          </div>
        </div>

        {/* Right: Status badge */}
        <div style={{
          background: "rgba(0,232,122,0.10)", border: "1px solid rgba(0,232,122,0.25)",
          borderRadius: 6, padding: "6px 14px",
          display: "flex", alignItems: "center", gap: 6,
        }}>
          <span style={{
            width: 6, height: 6, borderRadius: "50%",
            background: "#00E87A", boxShadow: "0 0 8px rgba(0,232,122,0.5)",
          }} />
          <span style={{
            fontFamily: FONTS.display, fontSize: 10, fontWeight: 700,
            color: "#00E87A", letterSpacing: "0.1em",
          }}>ACTIVE</span>
        </div>
      </div>

      {/* Section 2 — Key Stats */}
      <div style={{
        display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12, marginBottom: 24,
      }}>
        {[
          { label: "Partner Since", value: "2025" },
          { label: "Classification", value: "Quant / Systematic" },
          { label: "Domicile", value: "Singapore" },
          { label: "Status", value: "Active · Onboarding" },
        ].map((stat, i) => (
          <div key={i} style={{
            background: T.surface, border: `1px solid ${T.border}`,
            borderRadius: 10, padding: "16px 20px",
          }}>
            <div style={{
              fontSize: 10, color: T.muted, letterSpacing: "0.1em",
              textTransform: "uppercase", marginBottom: 8, fontFamily: FONTS.body,
            }}>
              {stat.label}
            </div>
            <div style={{
              fontFamily: FONTS.mono, fontSize: 18, fontWeight: 600,
              color: T.primary,
            }}>
              {stat.value}
            </div>
          </div>
        ))}
      </div>

      {/* Section 3 — Strategy Overview */}
      <div style={{
        background: T.surface, border: `1px solid ${T.border}`,
        borderRadius: 12, padding: 24, marginBottom: 24,
      }}>
        <div style={{
          fontFamily: FONTS.display, fontSize: 12, fontWeight: 700,
          color: "#C8A84B", letterSpacing: "0.1em", marginBottom: 12,
          textTransform: "uppercase",
        }}>
          Strategy Overview
        </div>
        <div style={{
          fontFamily: FONTS.body, fontSize: 14, color: T.secondary,
          lineHeight: 1.7, marginBottom: 16,
        }}>
          EST Alpha employs quantitative strategies across digital asset markets,
          with a focus on systematic signal extraction and risk-adjusted return generation.
          As CometCloud's inaugural GP partner, EST Alpha provides institutional-grade
          execution infrastructure for the Vault's fund-of-funds structure.
        </div>
        <div style={{
          background: "rgba(200,168,75,0.08)", border: "1px solid rgba(200,168,75,0.15)",
          borderRadius: 6, padding: "10px 14px", display: "inline-block",
        }}>
          <span style={{
            fontFamily: FONTS.body, fontSize: 11, color: "#C8A84B",
          }}>
            CometCloud Intelligence Score integration: Pending
          </span>
        </div>
      </div>

      {/* Section 4 — CIS Integration Status */}
      <div style={{
        background: T.surface, border: `1px solid ${T.border}`,
        borderRadius: 12, padding: 24, marginBottom: 24,
      }}>
        <div style={{
          fontFamily: FONTS.display, fontSize: 12, fontWeight: 700,
          color: T.primary, letterSpacing: "0.1em", marginBottom: 20,
          textTransform: "uppercase",
        }}>
          CIS Integration Pipeline
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 0 }}>
          {[
            { step: 1, title: "Partnership Agreement", status: "completed", date: "2025" },
            { step: 2, title: "Onboarding", status: "in_progress", date: "Q1 2026" },
            { step: 3, title: "CIS Score Integration", status: "pending", date: "Q2 2026" },
            { step: 4, title: "Live Performance Reporting", status: "pending", date: "Q2 2026" },
          ].map((item, i) => (
            <div key={i} style={{
              display: "flex", alignItems: "center", gap: 16,
              padding: "14px 0", borderBottom: i < 3 ? `1px solid ${T.border}` : "none",
            }}>
              {/* Step indicator */}
              <div style={{
                width: 28, height: 28, borderRadius: "50%",
                background: item.status === "completed" ? "rgba(0,232,122,0.15)" :
                           item.status === "in_progress" ? "rgba(200,168,75,0.15)" : "rgba(255,255,255,0.05)",
                border: `1px solid ${item.status === "completed" ? "rgba(0,232,122,0.4)" :
                                  item.status === "in_progress" ? "rgba(200,168,75,0.4)" : "rgba(255,255,255,0.1)"}`,
                display: "flex", alignItems: "center", justifyContent: "center",
                flexShrink: 0,
              }}>
                {item.status === "completed" ? (
                  <span style={{ color: "#00E87A", fontSize: 12 }}>✓</span>
                ) : item.status === "in_progress" ? (
                  <span style={{ color: "#C8A84B", fontSize: 10 }}>◐</span>
                ) : (
                  <span style={{ color: T.muted, fontSize: 10 }}>○</span>
                )}
              </div>

              {/* Content */}
              <div style={{ flex: 1 }}>
                <div style={{
                  fontFamily: FONTS.display, fontSize: 13, fontWeight: 600,
                  color: T.primary, marginBottom: 2,
                }}>
                  {item.title}
                </div>
                <div style={{
                  fontFamily: FONTS.body, fontSize: 11, color: T.muted,
                }}>
                  {item.date}
                </div>
              </div>

              {/* Status label */}
              <div style={{
                fontFamily: FONTS.display, fontSize: 9, fontWeight: 700,
                letterSpacing: "0.1em", padding: "4px 10px", borderRadius: 4,
                background: item.status === "completed" ? "rgba(0,232,122,0.10)" :
                           item.status === "in_progress" ? "rgba(200,168,75,0.10)" : "rgba(255,255,255,0.05)",
                color: item.status === "completed" ? "#00E87A" :
                       item.status === "in_progress" ? "#C8A84B" : T.muted,
                border: `1px solid ${item.status === "completed" ? "rgba(0,232,122,0.2)" :
                                  item.status === "in_progress" ? "rgba(200,168,75,0.2)" : "rgba(255,255,255,0.1)"}`,
              }}>
                {item.status === "completed" ? "COMPLETED" :
                 item.status === "in_progress" ? "IN PROGRESS" : "PENDING"}
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Section 5 — GP Shelf说明 */}
      <div style={{
        background: "rgba(255,255,255,0.02)", border: `1px solid ${T.border}`,
        borderRadius: 10, padding: 20,
      }}>
        <div style={{
          fontFamily: FONTS.display, fontSize: 11, fontWeight: 700,
          color: T.muted, letterSpacing: "0.12em", marginBottom: 10,
          textTransform: "uppercase",
        }}>
          GP Shelf
        </div>
        <p style={{
          fontFamily: FONTS.body, fontSize: 13, color: T.secondary,
          lineHeight: 1.7, maxWidth: 800,
        }}>
          CometCloud Vault operates a GP Shelf model — a curated selection of
          institutional-grade fund managers evaluated through the CIS framework.
          EST Alpha is the founding GP. Additional GPs are evaluated through a
          rigorous selection process.
        </p>
      </div>
    </div>
  );
}
