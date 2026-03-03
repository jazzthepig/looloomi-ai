import { useState, useEffect, useRef } from "react";
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
  deep: "#0a0a0f",
  surface: "#0f0f1a",
  altBg: "#0d0d18",
  border: "rgba(255,255,255,0.06)",
  borderHi: "rgba(255,255,255,0.12)",
  primary: "#F0EEFF",
  secondary: "#94a3b8",
  muted: "#64748b",
  cyan: "#06b6d4",
  gold: "#f59e0b",
  violet: "#8b5cf6",
};

const SECTIONS = [
  { id: "hero", label: "Home" },
  { id: "market", label: "Market" },
  { id: "intelligence", label: "Intelligence" },
  { id: "cis", label: "CIS" },
  { id: "protocol", label: "Protocol" },
  { id: "vault", label: "Vault" },
  { id: "quantgp", label: "Quant GP" },
];

export default function App() {
  const [activeSection, setActiveSection] = useState("hero");
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
    <div style={{ background: "transparent", minHeight: "100vh", position: "relative" }}>
      {/* TURRELL AMBIENT LIGHT CANVAS */}
      <div className="turrell-canvas">
        <div className="orb-primary"></div>
        <div className="orb-gold"></div>
        <div className="orb-violet"></div>
        <div className="orb-center"></div>
        <div className="noise-overlay"></div>
      </div>

      {/* Fixed Navigation */}
      <nav style={{
        position: "fixed", top: 0, left: 0, right: 0, zIndex: 1000,
        background: "rgba(10,10,15,0.85)", backdropFilter: "blur(20px)",
        borderBottom: `1px solid ${T.border}`, display: "flex", alignItems: "center",
        justifyContent: "space-between", padding: "16px 48px",
      }}>
        <span
          onClick={() => scrollToSection("hero")}
          style={{
            fontFamily: FONTS.display, fontWeight: 700, fontSize: 20,
            letterSpacing: "-0.02em", color: T.primary, cursor: "pointer",
            textShadow: "0 0 40px rgba(6,182,212,0.4)",
          }}
        >
          CometCloud
        </span>
        <div style={{ display: "flex", gap: 4 }}>
          {SECTIONS.map(({ id, label }) => (
            <button
              key={id}
              onClick={() => scrollToSection(id)}
              style={{
                padding: "8px 16px", borderRadius: 6, fontSize: 13, fontWeight: 500,
                fontFamily: FONTS.body, cursor: "pointer", outline: "none",
                border: "none",
                background: activeSection === id ? T.cyan : "transparent",
                color: activeSection === id ? "#fff" : T.secondary,
                transition: "all 0.2s ease",
              }}
            >
              {label}
            </button>
          ))}
        </div>
      </nav>

      {/* Sections Container - padding for fixed nav */}
      <div style={{ paddingTop: 64 }}>

        {/* Section 1: Hero */}
        <section id="hero" style={sectionStyle(0)}>
          <HeroContent />
        </section>

        {/* Section Separator */}
        <div className="section-divider" />

        {/* Section 2: Market */}
        <section id="market" style={sectionStyle(1)}>
          <MarketDashboard isSection={true} />
        </section>

        {/* Section Separator */}
        <div className="section-divider" />

        {/* Section 3: Intelligence */}
        <section id="intelligence" style={sectionStyle(0)}>
          <IntelligencePage isSection={true} />
        </section>

        {/* Section Separator */}
        <div className="section-divider" />

        {/* Section 4: CIS */}
        <section id="cis" style={sectionStyle(1)}>
          <CISContent />
        </section>

        {/* Section Separator */}
        <div className="section-divider" />

        {/* Section 5: Protocol */}
        <section id="protocol" style={sectionStyle(0)}>
          <ProtocolPage isSection={true} />
        </section>

        {/* Section Separator */}
        <div className="section-divider" />

        {/* Section 6: Vault */}
        <section id="vault" style={sectionStyle(1)}>
          <VaultPage isSection={true} />
        </section>

        {/* Section Separator */}
        <div className="section-divider" />

        {/* Section 7: Quant GP */}
        <section id="quantgp" style={sectionStyle(0)}>
          <QuantGPContent />
        </section>

      </div>

      <style>{`
        * { scroll-behavior: smooth; }

        /* ── TURRELL AMBIENT LIGHT SYSTEM ── */
        .turrell-canvas {
          position: fixed;
          inset: 0;
          z-index: 0;
          pointer-events: none;
          background: #03030a;
        }

        .orb-primary {
          position: absolute;
          width: 900px;
          height: 900px;
          left: -200px;
          top: 50%;
          transform: translateY(-50%);
          background: radial-gradient(ellipse, rgba(6, 182, 212, 0.12) 0%, rgba(6, 182, 212, 0.06) 30%, rgba(6, 182, 212, 0.02) 60%, transparent 75%);
          border-radius: 50%;
          animation: orb-breathe-primary 8s ease-in-out infinite;
          filter: blur(40px);
        }

        .orb-gold {
          position: absolute;
          width: 600px;
          height: 600px;
          right: -100px;
          top: -100px;
          background: radial-gradient(ellipse, rgba(245, 158, 11, 0.09) 0%, rgba(245, 158, 11, 0.04) 40%, transparent 70%);
          border-radius: 50%;
          animation: orb-breathe-gold 11s ease-in-out infinite;
          filter: blur(60px);
        }

        .orb-violet {
          position: absolute;
          width: 500px;
          height: 500px;
          right: 10%;
          bottom: -80px;
          background: radial-gradient(ellipse, rgba(124, 58, 237, 0.08) 0%, rgba(124, 58, 237, 0.03) 50%, transparent 70%);
          border-radius: 50%;
          animation: orb-breathe-violet 14s ease-in-out infinite;
          filter: blur(50px);
        }

        .orb-center {
          position: absolute;
          width: 1400px;
          height: 800px;
          left: 50%;
          top: 50%;
          transform: translate(-50%, -50%);
          background: radial-gradient(ellipse, rgba(6, 182, 212, 0.025) 0%, rgba(30, 10, 60, 0.03) 40%, transparent 70%);
          border-radius: 50%;
          filter: blur(80px);
        }

        .noise-overlay {
          position: absolute;
          inset: 0;
          opacity: 0.035;
          background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noise'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noise)'/%3E%3C/svg%3E");
          background-size: 200px 200px;
        }

        @keyframes orb-breathe-primary {
          0%, 100% { opacity: 1; transform: translateY(-50%) scale(1); }
          50% { opacity: 0.7; transform: translateY(-50%) scale(1.08); }
        }
        @keyframes orb-breathe-gold {
          0%, 100% { opacity: 1; transform: scale(1); }
          50% { opacity: 0.6; transform: scale(1.12); }
        }
        @keyframes orb-breathe-violet {
          0%, 100% { opacity: 1; transform: scale(1); }
          50% { opacity: 0.8; transform: scale(0.92); }
        }

        /* ── SECTION DIVIDERS ── */
        .section-divider {
          height: 1px;
          background: linear-gradient(90deg, transparent 0%, rgba(6,182,212,0.06) 20%, rgba(6,182,212,0.16) 50%, rgba(6,182,212,0.06) 80%, transparent 100%);
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
          background: radial-gradient(ellipse, rgba(6,182,212,0.1) 0%, transparent 70%);
          filter: blur(4px);
        }

        /* ── NAVBAR GLASSMORPHISM ── */
        nav {
          background: rgba(3, 3, 10, 0.75) !important;
          backdrop-filter: blur(16px);
          -webkit-backdrop-filter: blur(16px);
          border-bottom: 1px solid rgba(255,255,255,0.04) !important;
        }

        /* ── CARD TRANSPARENCY ── */
        .lm-card, .card, [class*="card"] {
          background: rgba(255, 255, 255, 0.02) !important;
          border: 1px solid rgba(255, 255, 255, 0.06) !important;
          backdrop-filter: blur(8px);
        }
      `}</style>
    </div>
  );
}

const sectionStyle = (index) => ({
  minHeight: "100vh",
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

      {/* Stats Summary */}
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
  );
}

/* ─────────────────────────────────────────────────────────────────────────
   QUANT GP SECTION (placeholder)
──────────────────────────────────────────────────────────────────────── */
function QuantGPContent() {
  return (
    <div style={{ maxWidth: 1600, margin: "0 auto" }}>
      <div style={{ marginBottom: 32 }}>
        <h2 style={{
          fontFamily: FONTS.display, fontSize: 32, fontWeight: 700,
          color: T.primary, marginBottom: 8, letterSpacing: "-0.02em"
        }}>
          <span style={{ color: T.cyan, marginRight: 12 }}>//</span>
          Quant GP Strategies
        </h2>
        <p style={{
          fontFamily: FONTS.body, fontSize: 14, color: T.secondary,
          maxWidth: 600, lineHeight: 1.6
        }}>
          AI-powered quantitative strategies for institutional-grade crypto fund management.
        </p>
      </div>

      <div style={{
        background: T.surface, border: `1px solid ${T.border}`,
        borderRadius: 10, padding: 48, textAlign: "center",
      }}>
        <p style={{ fontFamily: FONTS.body, fontSize: 16, color: T.secondary }}>
          Quant GP strategies coming soon...
        </p>
      </div>
    </div>
  );
}
