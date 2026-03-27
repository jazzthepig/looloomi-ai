import { useState, useEffect, useRef } from "react";
import MarketDashboard from "./components/MarketDashboard";
import IntelligencePage from "./components/IntelligencePage";
import CISLeaderboard from "./components/CISLeaderboard";
import VaultPage from "./components/VaultPage";
import ProtocolIntelligence from "./components/ProtocolIntelligence";
import MobileApp from "./components/MobileApp";
import WalletConnect from "./components/WalletConnect";
import { T, FONTS } from "./tokens";

/* ── Mobile detection ─────────────────────────────────────────────────────── */
function useIsMobile() {
  const [isMobile, setIsMobile] = useState(() => window.innerWidth < 768);
  useEffect(() => {
    const mq = window.matchMedia("(max-width: 767px)");
    const handler = (e) => setIsMobile(e.matches);
    mq.addEventListener("change", handler);
    return () => mq.removeEventListener("change", handler);
  }, []);
  return isMobile;
}

/* ── Cross-Asset Class Colors (mirrors CISLeaderboard) ─────────────────── */
const CA_COLORS = {
  L1:           { bg: "rgba(0,200,224,.08)",    text: "#00C8E0" },
  L2:           { bg: "rgba(107,15,204,.10)",   text: "#9945FF" },
  DeFi:         { bg: "rgba(68,114,255,.12)",   text: "#4472FF" },
  RWA:          { bg: "rgba(232,160,0,.12)",    text: "#E8A000" },
  Infrastructure:{ bg: "rgba(0,217,138,.10)",   text: "#00D98A" },
  Oracle:       { bg: "rgba(167,139,250,.10)",  text: "#A78BFA" },
  Memecoin:     { bg: "rgba(255,16,96,.10)",    text: "#FF1060" },
  AI:           { bg: "rgba(255,107,0,.10)",    text: "#FF6B00" },
  "US Equity":  { bg: "rgba(68,114,255,.10)",   text: "#4B9EFF" },
  "US Bond":    { bg: "rgba(245,158,11,.10)",   text: "#F59E0B" },
  Commodity:    { bg: "rgba(200,168,75,.12)",   text: "#C8A84B" },
};

const GRADE_COLORS_CA = {
  "A+": "#00D98A", A: "#00D98A",
  "B+": "#4472FF", B: "#4472FF",
  "C+": "#E8A000", C: "#E8A000",
  D: "#FF2D55", F: "#888",
};

const CLASS_ORDER = [
  "L1", "L2", "DeFi", "RWA", "Infrastructure", "Oracle",
  "US Equity", "US Bond", "Commodity", "Memecoin", "AI",
];

/* ── Cross-Asset View Component ─────────────────────────────────────────── */
/* Receives universe array from parent — no independent fetch */
function CrossAssetView({ universe = [] }) {
  if (!universe.length) return null;

  // Group by asset_class
  const classMap = {};
  for (const asset of universe) {
    const cls = asset.asset_class || "Other";
    if (!classMap[cls]) classMap[cls] = [];
    classMap[cls].push(asset);
  }

  const classes = CLASS_ORDER.filter(c => classMap[c]);

  return (
    <div style={{ marginTop: 40 }}>
      {/* Section header */}
      <div style={{
        display: "flex", alignItems: "center", gap: 12, marginBottom: 20,
        paddingBottom: 14, borderBottom: `1px solid ${T.border}`,
      }}>
        <div style={{ width: 14, height: 1, background: T.gold, opacity: 0.5 }} />
        <span style={{
          fontFamily: FONTS.display, fontSize: 11, fontWeight: 700,
          letterSpacing: "0.14em", color: T.t2, textTransform: "uppercase",
        }}>
          Cross-Asset Overview
        </span>
        <span style={{
          fontSize: 9, color: T.t3, fontFamily: FONTS.mono,
          marginLeft: "auto",
        }}>
          {classes.length} classes · {universe.length} assets
        </span>
      </div>

      {/* Class cards grid */}
      <div style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))",
        gap: 12,
      }}>
        {classes.map(cls => {
          const assets   = [...classMap[cls]].sort((a, b) => (b.cis_score || 0) - (a.cis_score || 0));
          const scores   = assets.map(a => a.cis_score).filter(v => v != null);
          const avgScore = scores.length ? scores.reduce((a, b) => a + b, 0) / scores.length : 0;
          const topAsset = assets[0];
          const clr      = CA_COLORS[cls] || { bg: "rgba(0,0,0,0.04)", text: "#6B7280" };

          // Grade distribution
          const gradeDist = { A: 0, B: 0, C: 0, D: 0 };
          for (const a of assets) {
            const g = a.grade || "F";
            if (g.startsWith("A"))      gradeDist.A++;
            else if (g.startsWith("B")) gradeDist.B++;
            else if (g.startsWith("C")) gradeDist.C++;
            else                         gradeDist.D++;
          }

          return (
            <div key={cls} style={{
              background: T.surface, border: `1px solid ${T.border}`,
              borderRadius: 10, padding: "16px 18px",
              borderTop: `2px solid ${clr.text}40`,
              transition: "border-color .15s",
            }}>
              {/* Class badge + count */}
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
                <span style={{
                  fontFamily: FONTS.display, fontSize: 9, fontWeight: 700,
                  letterSpacing: "0.1em", padding: "3px 8px", borderRadius: 3,
                  background: clr.bg, color: clr.text, border: `1px solid ${clr.text}30`,
                }}>
                  {cls.toUpperCase()}
                </span>
                <span style={{ fontSize: 9, color: T.t3, fontFamily: FONTS.mono }}>
                  {assets.length} asset{assets.length > 1 ? "s" : ""}
                </span>
              </div>

              {/* Avg score */}
              <div style={{ display: "flex", alignItems: "baseline", gap: 6, marginBottom: 10 }}>
                <span style={{
                  fontFamily: FONTS.mono, fontSize: 30, fontWeight: 400, lineHeight: 1,
                  color: avgScore >= 70 ? T.green : avgScore >= 50 ? T.blue : T.amber,
                }}>
                  {avgScore.toFixed(1)}
                </span>
                <span style={{ fontSize: 9, color: T.t3, fontFamily: FONTS.mono }}>avg CIS</span>
              </div>

              {/* Top asset */}
              {topAsset && (
                <div style={{
                  display: "flex", alignItems: "center", justifyContent: "space-between",
                  marginBottom: 12, paddingBottom: 10, borderBottom: `1px solid ${T.border}`,
                }}>
                  <div>
                    <div style={{ fontSize: 11, fontWeight: 700, fontFamily: FONTS.display, color: T.t1 }}>
                      {topAsset.name || topAsset.symbol}
                    </div>
                    <div style={{ fontSize: 9, color: T.t3, fontFamily: FONTS.mono, marginTop: 1 }}>
                      Top asset · {topAsset.cis_score?.toFixed(1)}
                    </div>
                  </div>
                  <span style={{
                    width: 26, height: 26, borderRadius: "50%", display: "flex",
                    alignItems: "center", justifyContent: "center",
                    background: `${GRADE_COLORS_CA[topAsset.grade] || "#888"}20`,
                    color: GRADE_COLORS_CA[topAsset.grade] || "#888",
                    border: `1px solid ${GRADE_COLORS_CA[topAsset.grade] || "#888"}40`,
                    fontSize: 11, fontWeight: 700, fontFamily: FONTS.mono,
                  }}>
                    {topAsset.grade}
                  </span>
                </div>
              )}

              {/* Grade distribution bar */}
              <div style={{ display: "flex", gap: 3 }}>
                {[
                  { key: "A", color: "#00D98A" },
                  { key: "B", color: "#4472FF" },
                  { key: "C", color: "#E8A000" },
                  { key: "D", color: "#FF2D55" },
                ].map(({ key, color }) => {
                  const count = gradeDist[key];
                  if (!count) return null;
                  return (
                    <div key={key} style={{
                      flex: count, height: 3, borderRadius: 2, background: color, opacity: 0.7,
                      minWidth: 4,
                    }} title={`${key}: ${count}`} />
                  );
                })}
              </div>
              <div style={{ display: "flex", gap: 10, marginTop: 6 }}>
                {Object.entries(gradeDist).filter(([, v]) => v > 0).map(([g, v]) => (
                  <span key={g} style={{ fontSize: 8, fontFamily: FONTS.mono, color: GRADE_COLORS_CA[g] || T.t3 }}>
                    {g}:{v}
                  </span>
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

const SECTIONS = [
  { id: "market", label: "Asset Prices" },
  { id: "intelligence", label: "Intelligence" },
  { id: "cis", label: "CIS" },
  { id: "protocol", label: "Protocol" },
  { id: "vault", label: "Vault" },
  { id: "quantgp", label: "Quant GP" },
];

function DesktopApp() {
  const [activeSection, setActiveSection] = useState("market");
  const sectionRefs = useRef({});
  const manualScrollRef = useRef(false);

  useEffect(() => {
    // Track which sections are visible and by how much
    const ratioMap = {};

    const observer = new IntersectionObserver(
      (entries) => {
        // Skip observer updates during manual scroll (click-to-nav)
        if (manualScrollRef.current) return;

        entries.forEach((entry) => {
          ratioMap[entry.target.id] = entry.isIntersecting ? entry.intersectionRatio : 0;
        });

        // Pick the section with the highest visible ratio
        let best = null;
        let bestRatio = 0;
        for (const [id, ratio] of Object.entries(ratioMap)) {
          if (ratio > bestRatio) {
            bestRatio = ratio;
            best = id;
          }
        }
        if (best) setActiveSection(best);
      },
      { rootMargin: "0px 0px -40% 0px", threshold: [0, 0.1, 0.25, 0.5, 0.75] }
    );

    SECTIONS.forEach(({ id }) => {
      const el = document.getElementById(id);
      if (el) observer.observe(el);
    });

    return () => observer.disconnect();
  }, []);

  const scrollToSection = (id) => {
    // Lock the active tab immediately on click, suppress observer for 1.2s
    setActiveSection(id);
    manualScrollRef.current = true;

    const el = document.getElementById(id);
    if (el) {
      el.scrollIntoView({ behavior: "smooth" });
    }

    // Re-enable observer after scroll finishes
    setTimeout(() => { manualScrollRef.current = false; }, 1200);
  };

  return (
    <div style={{ background: "#FAFBFC", minHeight: "100vh", position: "relative" }}>

      {/* Fixed Navigation — clean, light, Stripe-style */}
      <nav style={{
        position: "fixed", top: 0, left: 0, right: 0, zIndex: 1000,
        background: "rgba(255,255,255,0.92)", backdropFilter: "blur(12px)",
        borderBottom: "1px solid rgba(0,0,0,0.06)", display: "flex", alignItems: "center",
        justifyContent: "space-between", padding: "12px 48px",
      }}>
        <span
          onClick={() => scrollToSection("market")}
          style={{
            fontFamily: FONTS.display, fontWeight: 700, fontSize: 18,
            letterSpacing: "0.04em", color: "#111827", cursor: "pointer",
          }}
        >
          CometCloud
        </span>
        <div style={{ display: "flex", gap: 2, background: "#F3F4F6", borderRadius: 10, padding: 3, border: "1px solid rgba(0,0,0,0.06)" }}>
          {SECTIONS.map(({ id, label }) => (
            <button
              key={id}
              onClick={() => scrollToSection(id)}
              style={{
                padding: "7px 16px", borderRadius: 7, fontSize: 12, fontWeight: 600,
                fontFamily: FONTS.display, cursor: "pointer", outline: "none",
                border: "1px solid transparent",
                background: activeSection === id ? "#FFFFFF" : "transparent",
                color: activeSection === id ? "#111827" : "#9CA3AF",
                boxShadow: activeSection === id ? "0 1px 3px rgba(0,0,0,0.08)" : "none",
                transition: "all 0.2s ease",
                letterSpacing: "0.04em",
              }}
            >
              {label}
            </button>
          ))}
        </div>
        <WalletConnect />
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
          <ProtocolIntelligence />
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
        body { background: #FAFBFC; min-height: 100vh; }

        /* ── SECTION DIVIDERS — subtle light border ── */
        .section-divider {
          height: 1px;
          background: rgba(0,0,0,0.06);
          margin: 0 64px;
        }

        /* ── RESPONSIVE: Nav tabs on small screens ── */
        @media (max-width: 900px) {
          nav {
            flex-direction: column !important;
            gap: 8px !important;
            padding: 10px 12px !important;
            align-items: stretch !important;
          }
          nav > span {
            font-size: 16px !important;
            text-align: center;
          }
          nav > div {
            overflow-x: auto;
            -webkit-overflow-scrolling: touch;
            scrollbar-width: none;
            white-space: nowrap;
            justify-content: flex-start !important;
          }
          nav > div::-webkit-scrollbar { display: none; }
          nav button {
            padding: 8px 12px !important;
            font-size: 11px !important;
            min-width: max-content;
            min-height: 36px;
          }
        }
        @media (max-width: 480px) {
          nav {
            padding: 8px 8px !important;
          }
          nav > span {
            font-size: 14px !important;
          }
          nav button {
            padding: 7px 10px !important;
            font-size: 10px !important;
          }
        }

        /* ── RESPONSIVE: Tables scroll horizontally ── */
        @media (max-width: 768px) {
          .tbl-wrap, .table-wrap {
            overflow-x: auto;
            -webkit-overflow-scrolling: touch;
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

        /* ── RESPONSIVE: Nav height compensation ── */
        @media (max-width: 900px) {
          body > div > div:nth-child(3) {
            padding-top: 88px !important;
          }
        }

        /* ── RESPONSIVE: Touch targets ── */
        @media (max-width: 768px) {
          button, .filter-btn, .lm-tab, .lm-action-btn {
            min-height: 36px;
          }
          .lm-row {
            min-height: 44px;
          }
        }

        /* ── RESPONSIVE: Cards on tiny screens ── */
        @media (max-width: 380px) {
          .lm-card {
            border-radius: 6px !important;
          }
          section {
            padding: 16px 8px !important;
          }
        }

        /* ── CARDS — clean white with subtle shadow ── */
        .lm-card, .card {
          background: #FFFFFF !important;
          border: 1px solid rgba(0,0,0,0.06) !important;
          box-shadow: 0 1px 3px rgba(0,0,0,0.04), 0 1px 2px rgba(0,0,0,0.02) !important;
        }
      `}</style>
    </div>
  );
}

const sectionStyle = (index) => ({
  minHeight: "auto",
  padding: "80px 64px",
  background: index % 2 === 0 ? "#FAFBFC" : "#FFFFFF",
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
      {/* Subtle background accent */}
      <div style={{
        position: "absolute", top: -100, right: -200, width: 600, height: 600,
        background: "radial-gradient(circle, rgba(6,182,212,0.06) 0%, transparent 70%)",
        pointerEvents: "none", zIndex: 0, filter: "blur(80px)",
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

      {/* Right: Visual — abstract grid/mesh */}
      <div style={{ position: "relative", height: 400, display: "flex", alignItems: "center", justifyContent: "center" }}>
        <div style={{
          width: 320, height: 320, borderRadius: 24,
          background: "linear-gradient(135deg, #F3F4F6 0%, #FFFFFF 100%)",
          border: "1px solid rgba(0,0,0,0.08)",
          boxShadow: "0 20px 60px rgba(0,0,0,0.06), 0 1px 3px rgba(0,0,0,0.04)",
          display: "flex", alignItems: "center", justifyContent: "center",
          position: "relative", overflow: "hidden",
        }}>
          {/* Inner decorative elements */}
          <div style={{
            position: "absolute", top: 20, left: 20, right: 20, bottom: 20,
            border: "1px solid rgba(0,0,0,0.04)", borderRadius: 16,
          }} />
          <div style={{
            fontFamily: FONTS.display, fontSize: 64, fontWeight: 800,
            background: "linear-gradient(135deg, #06b6d4 0%, #92722A 100%)",
            WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent",
            letterSpacing: "-0.04em",
          }}>
            CC
          </div>
        </div>
      </div>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────────────
   CIS SECTION
   CISLeaderboard owns the single fetch; exposes raw universe via onDataLoad
   callback → CrossAssetView renders from the same data, zero extra requests
──────────────────────────────────────────────────────────────────────── */
function CISContent() {
  const [cisUniverse, setCisUniverse] = useState([]);

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

      {/* Leaderboard — owns the fetch, fires onDataLoad when done */}
      <div style={{ background: T.surface, border: `1px solid ${T.border}`, borderRadius: 10, overflow: "hidden" }}>
        <CISLeaderboard onDataLoad={setCisUniverse} />
      </div>

      {/* Cross-Asset Overview — zero additional fetches */}
      <CrossAssetView universe={cisUniverse} />
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
          background: "linear-gradient(135deg, #F9FAFB 0%, #F3F4F6 100%)",
          border: "2px solid rgba(146,114,42,0.3)",
          display: "flex", alignItems: "center", justifyContent: "center",
        }}>
          <span style={{
            fontFamily: FONTS.display, fontSize: 24, fontWeight: 800,
            color: "#92722A", letterSpacing: "-0.02em",
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
                           item.status === "in_progress" ? "rgba(200,168,75,0.15)" : "rgba(0,0,0,0.04)",
                border: `1px solid ${item.status === "completed" ? "rgba(0,232,122,0.4)" :
                                  item.status === "in_progress" ? "rgba(200,168,75,0.4)" : "rgba(0,0,0,0.08)"}`,
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
                           item.status === "in_progress" ? "rgba(200,168,75,0.10)" : "rgba(0,0,0,0.04)",
                color: item.status === "completed" ? "#00E87A" :
                       item.status === "in_progress" ? "#C8A84B" : T.muted,
                border: `1px solid ${item.status === "completed" ? "rgba(0,232,122,0.2)" :
                                  item.status === "in_progress" ? "rgba(200,168,75,0.2)" : "rgba(0,0,0,0.08)"}`,
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
        background: "rgba(0,0,0,0.02)", border: `1px solid ${T.border}`,
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

/* ── App: mobile/desktop router ─────────────────────────────────────────── */
export default function App() {
  const isMobile = useIsMobile();
  return isMobile ? <MobileApp /> : <DesktopApp />;
}
