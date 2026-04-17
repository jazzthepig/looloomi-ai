import { useState, useEffect, lazy, Suspense } from "react";
// MarketDashboard removed (Q5 — cut market tab, reduces infra cost)
// File can be deleted: dashboard/src/components/MarketDashboard.jsx
import IntelligencePage from "./components/IntelligencePage";
import CISLeaderboard from "./components/CISLeaderboard";
import WalletConnect from "./components/WalletConnect";
import SiteNav from "./components/SiteNav";
import { T, FONTS } from "./tokens";

/* ── Lazy-loaded secondary views (below fold / conditional) ── */
const VaultPage            = lazy(() => import("./components/VaultPage"));
const ProtocolIntelligence = lazy(() => import("./components/ProtocolIntelligence"));
const MobileApp            = lazy(() => import("./components/MobileApp"));
const AssetRadar           = lazy(() => import("./components/AssetRadar"));
const QuantMonitor         = lazy(() => import("./components/QuantMonitor"));
const MyPortfolio          = lazy(() => import("./components/MyPortfolio"));

/* ── Staging environment banner ─────────────────────────────────────────── */
function StagingBanner() {
  const [env, setEnv] = useState(null);
  useEffect(() => {
    fetch("/health").then(r => r.json()).then(d => setEnv(d.environment)).catch(() => {});
  }, []);
  if (env !== "staging") return null;
  return (
    <div style={{
      background: "linear-gradient(90deg, #FF6B00, #E8A000)",
      color: "#000", textAlign: "center", padding: "4px 0",
      fontFamily: FONTS.mono, fontSize: 10, letterSpacing: "0.15em",
      fontWeight: 700, position: "sticky", top: 0, zIndex: 9999,
    }}>
      ⚠ STAGING ENVIRONMENT — NOT PRODUCTION
    </div>
  );
}

/* ── Lazy-load fallback ──────────────────────────────────────────────────── */
// ── Editorial section label — consistent across all sections ──────────────
// stats: [{ label, value, color }] — rendered inline right-aligned (Fortress pattern)
function SectionLabel({ label, sub, stats = null }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 20, paddingBottom: 14, borderBottom: "1px solid rgba(6,182,212,0.08)" }}>
      <div style={{ width: 2, height: 16, background: "rgba(6,182,212,0.65)", borderRadius: 1, flexShrink: 0 }} />
      <span style={{ fontFamily: FONTS.display, fontSize: 18, fontWeight: 600, color: T.t1, letterSpacing: "-0.01em" }}>
        {label}
      </span>
      {sub && (
        <span style={{ fontFamily: FONTS.mono, fontSize: 10, color: T.muted, letterSpacing: "0.1em", textTransform: "uppercase" }}>
          · {sub}
        </span>
      )}
      {stats && stats.length > 0 && (
        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 0 }}>
          {stats.map((s, i) => (
            <div key={i} style={{
              paddingLeft: 20, paddingRight: i < stats.length - 1 ? 20 : 0,
              borderLeft: `1px solid rgba(6,182,212,0.10)`,
              display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 1,
            }}>
              <div style={{ fontFamily: FONTS.mono, fontSize: 7, letterSpacing: "0.16em", color: T.muted, textTransform: "uppercase" }}>{s.label}</div>
              <div style={{ fontFamily: FONTS.mono, fontSize: 13, color: s.color || T.t2, letterSpacing: "-0.01em" }}>{s.value}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function SectionLoader() {
  return (
    <div style={{ padding: "48px 0", textAlign: "center" }}>
      <div style={{ color: "rgba(199,210,254,0.2)", fontFamily: "monospace", fontSize: 11, letterSpacing: "0.1em" }}>
        LOADING…
      </div>
    </div>
  );
}

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
  "A+": T.green,  A: T.green,
  "B+": T.indigo, B: T.indigo,
  "C+": T.amber,  C: T.amber,
  D: T.red, F: T.dim,
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
          const clr      = CA_COLORS[cls] || { bg: "rgba(255,255,255,0.04)", text: "#6B7280" };

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
            <div key={cls} className="lm-card" style={{
              padding: "16px 18px",
              borderTop: `2px solid ${clr.text}40`,
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
                  { key: "A", color: T.green },
                  { key: "B", color: T.indigo },
                  { key: "C", color: T.amber },
                  { key: "D", color: T.red },
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

const NAV_ITEMS = [
  { id: "intelligence", label: "Intelligence", icon: "◈", sub: "Signals · Events · Macro" },
  { id: "cis",          label: "CIS Engine",   icon: "◆", sub: "Scoring · Leaderboard" },
  { id: "protocol",     label: "Protocols",    icon: "⬡", sub: "DeFi TVL · Selection" },
  { id: "vault",        label: "Vault",        icon: "◎", sub: "Fund of Funds" },
  { id: "quantgp",      label: "Quant GP",     icon: "∿", sub: "EST Alpha · Live" },
  { id: "portfolio",    label: "Portfolio",    icon: "⊡", sub: "My Holdings" },
];

// Used by mobile SiteNav
const SECTIONS = NAV_ITEMS.map(({ id, label }) => ({ id, label }));

const TOOL_LINKS = [
  { label: "Portfolio Builder", href: "/portfolio.html" },
  { label: "Score Analytics",  href: "/analytics.html" },
  { label: "Agent API",        href: "/agent.html" },
  { label: "Fund Strategy",    href: "/strategy.html" },
];

/* ── Sidebar ────────────────────────────────────────────────────────────── */
function Sidebar({ activeSection, onNavigate, bottomSlot }) {
  return (
    <div style={{
      width: 220, minWidth: 220,
      height: "100vh",
      position: "fixed", left: 0, top: 0,
      background: "rgba(1,5,14,0.97)",
      borderRight: "1px solid rgba(6,182,212,0.07)",
      display: "flex", flexDirection: "column",
      zIndex: 1000,
      backdropFilter: "blur(20px)",
      WebkitBackdropFilter: "blur(20px)",
    }}>

      {/* Brand */}
      <div style={{ padding: "22px 20px 18px", borderBottom: "1px solid rgba(6,182,212,0.07)" }}>
        <a href="/app.html" style={{ textDecoration: "none", display: "flex", alignItems: "center", gap: 7 }}>
          <span style={{ fontFamily: FONTS.brand, fontWeight: 800, fontSize: 13, color: T.t1, letterSpacing: "0.06em" }}>
            COMETCLOUD
          </span>
          <span style={{ fontFamily: FONTS.mono, fontSize: 8, color: T.indigo, letterSpacing: "0.1em" }}>AI</span>
        </a>
        <div style={{
          fontFamily: FONTS.mono, fontSize: 8, color: T.muted,
          letterSpacing: "0.12em", textTransform: "uppercase", marginTop: 6, opacity: 0.6,
        }}>
          Institutional Intelligence
        </div>
      </div>

      {/* Nav */}
      <nav style={{ flex: 1, padding: "10px 8px", overflowY: "auto", scrollbarWidth: "none" }}>

        {/* Platform group */}
        <div style={{ fontFamily: FONTS.mono, fontSize: 8, color: T.muted, letterSpacing: "0.16em", textTransform: "uppercase", padding: "6px 12px 8px", opacity: 0.55 }}>
          Platform
        </div>

        {NAV_ITEMS.map(item => {
          const active = activeSection === item.id;
          return (
            <button
              key={item.id}
              onClick={() => onNavigate(item.id)}
              style={{
                width: "100%", textAlign: "left",
                display: "flex", alignItems: "center", gap: 10,
                padding: "9px 10px 9px 12px", borderRadius: 6,
                cursor: "pointer", border: "none", marginBottom: 2,
                background: active ? "rgba(6,182,212,0.07)" : "transparent",
                color: active ? T.t1 : T.t3,
                transition: "all 0.14s",
              }}
              onMouseEnter={e => { if (!active) { e.currentTarget.style.background = "rgba(255,255,255,0.025)"; e.currentTarget.style.color = T.t2; } }}
              onMouseLeave={e => { if (!active) { e.currentTarget.style.background = "transparent"; e.currentTarget.style.color = T.t3; } }}
            >
              {/* Active pip */}
              <div style={{
                width: 2, height: 18, borderRadius: 1, flexShrink: 0,
                background: active ? T.cyan : "transparent",
                transition: "background 0.14s",
              }} />
              {/* Icon */}
              <span style={{ fontFamily: FONTS.mono, fontSize: 12, color: active ? T.cyan : T.t3, flexShrink: 0, lineHeight: 1, opacity: active ? 1 : 0.5 }}>
                {item.icon}
              </span>
              {/* Label + sub */}
              <div style={{ minWidth: 0 }}>
                <div style={{ fontFamily: FONTS.display, fontSize: 12, fontWeight: active ? 700 : 500, letterSpacing: "0.01em", whiteSpace: "nowrap" }}>
                  {item.label}
                </div>
                <div style={{ fontFamily: FONTS.mono, fontSize: 9, color: active ? T.t3 : T.muted, marginTop: 2, opacity: 0.65, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                  {item.sub}
                </div>
              </div>
            </button>
          );
        })}

        {/* Divider */}
        <div style={{ height: 1, background: "rgba(6,182,212,0.05)", margin: "10px 12px" }} />

        {/* Tools group */}
        <div style={{ fontFamily: FONTS.mono, fontSize: 8, color: T.muted, letterSpacing: "0.16em", textTransform: "uppercase", padding: "4px 12px 8px", opacity: 0.55 }}>
          Tools
        </div>

        {TOOL_LINKS.map(link => (
          <a key={link.href} href={link.href} style={{
            width: "100%", display: "flex", alignItems: "center", gap: 10,
            padding: "7px 10px 7px 14px", borderRadius: 6, marginBottom: 2,
            textDecoration: "none", color: T.muted,
            transition: "all 0.14s",
          }}
            onMouseEnter={e => { e.currentTarget.style.background = "rgba(255,255,255,0.025)"; e.currentTarget.style.color = T.t2; }}
            onMouseLeave={e => { e.currentTarget.style.background = "transparent"; e.currentTarget.style.color = T.muted; }}
          >
            <div style={{ fontFamily: FONTS.display, fontSize: 11, flex: 1, letterSpacing: "0.01em" }}>{link.label}</div>
            <span style={{ fontSize: 9, opacity: 0.35 }}>↗</span>
          </a>
        ))}
      </nav>

      {/* Bottom: wallet + version */}
      <div style={{ padding: "14px 16px 18px", borderTop: "1px solid rgba(6,182,212,0.07)" }}>
        {bottomSlot}
        <div style={{ fontFamily: FONTS.mono, fontSize: 8, color: T.muted, textAlign: "center", marginTop: 12, letterSpacing: "0.06em", opacity: 0.4 }}>
          CIS v4.1 · CometCloud © 2025
        </div>
      </div>
    </div>
  );
}

function DesktopApp() {
  const [activeSection, setActiveSection] = useState("intelligence");
  const [cisUniverse, setCisUniverse]     = useState([]);
  // Lazy-mount: track which sections have been visited — mount once, keep alive
  const [visited, setVisited] = useState(() => new Set(["intelligence"]));

  const navigate = (id) => {
    setActiveSection(id);
    setVisited(prev => { const next = new Set(prev); next.add(id); return next; });
    // Scroll content pane back to top on section switch
    const pane = document.getElementById("cc-content-pane");
    if (pane) pane.scrollTop = 0;
  };

  return (
    <div style={{ background: T.deep, minHeight: "100vh", display: "flex", position: "relative" }}>

      <StagingBanner />

      {/* Ambient background orbs (fixed, behind everything) */}
      <div className="bg">
        <div className="bg-base" />
        <div className="bg-left" />
        <div className="bg-right" />
        <div className="bg-grain" />
      </div>

      {/* ── Sidebar — desktop only ── */}
      <div className="cc-sidebar">
        <Sidebar
          activeSection={activeSection}
          onNavigate={navigate}
          bottomSlot={<WalletConnect />}
        />
      </div>

      {/* ── Top nav — mobile fallback ── */}
      <div className="cc-topnav">
        <SiteNav
          sections={SECTIONS}
          activeSection={activeSection}
          onSectionClick={navigate}
          rightSlot={<WalletConnect />}
        />
        {/* Desktop upsell — only visible on mobile, below nav */}
        <div className="cc-desktop-hint">
          <span style={{ opacity: 0.45, marginRight: 6 }}>⊞</span>
          Open on desktop for the full platform experience
        </div>
      </div>

      {/* ── Content pane ── */}
      <main
        id="cc-content-pane"
        className="cc-main"
        style={{ flex: 1, overflowY: "auto", height: "100vh", position: "relative", zIndex: 1 }}
      >
        {/* Intelligence */}
        <div style={{ display: activeSection === "intelligence" ? "block" : "none" }}>
          {visited.has("intelligence") && (
            <section style={contentPad}>
              <IntelligencePage isSection={true} />
            </section>
          )}
        </div>

        {/* CIS */}
        <div style={{ display: activeSection === "cis" ? "block" : "none" }}>
          {visited.has("cis") && (
            <section style={contentPad}>
              <CISContent onUniverseLoad={setCisUniverse} />
            </section>
          )}
        </div>

        {/* Protocol */}
        <div style={{ display: activeSection === "protocol" ? "block" : "none" }}>
          {visited.has("protocol") && (
            <section style={contentPad}>
              <div style={{ maxWidth: 1400, margin: "0 auto" }}>
                <Suspense fallback={<SectionLoader />}>
                  <ProtocolIntelligence />
                </Suspense>
              </div>
            </section>
          )}
        </div>

        {/* Vault */}
        <div style={{ display: activeSection === "vault" ? "block" : "none" }}>
          {visited.has("vault") && (
            <section style={contentPad}>
              <Suspense fallback={<SectionLoader />}>
                <VaultPage isSection={true} />
              </Suspense>
            </section>
          )}
        </div>

        {/* Quant GP */}
        <div style={{ display: activeSection === "quantgp" ? "block" : "none" }}>
          {visited.has("quantgp") && (
            <section style={contentPad}>
              <div style={{ maxWidth: 1400, margin: "0 auto" }}>
                <SectionLabel label="Quant GP" sub="GP Partner Network" />
                <QuantGPContent />
              </div>
            </section>
          )}
        </div>

        {/* Portfolio */}
        <div style={{ display: activeSection === "portfolio" ? "block" : "none" }}>
          {visited.has("portfolio") && (
            <section style={contentPad}>
              <Suspense fallback={<SectionLoader />}>
                <MyPortfolio cisUniverse={cisUniverse} />
              </Suspense>
            </section>
          )}
        </div>
      </main>

      <style>{`
        body { background: ${T.deep}; margin: 0; }

        /* Desktop: sidebar visible, top nav hidden */
        .cc-sidebar  { display: block; }
        .cc-topnav   { display: none; }
        .cc-main     { margin-left: 220px; }

        /* Mobile: sidebar hidden, top nav visible */
        @media (max-width: 900px) {
          .cc-sidebar  { display: none; }
          .cc-topnav   { display: block; }
          .cc-main     { margin-left: 0 !important; padding-top: 108px; height: auto !important; overflow-y: visible !important; }
        }

        /* Desktop upsell strip — mobile only */
        .cc-desktop-hint {
          display: none;
        }
        @media (max-width: 900px) {
          .cc-desktop-hint {
            display: flex;
            align-items: center;
            justify-content: center;
            position: fixed;
            top: 56px;
            left: 0; right: 0;
            height: 28px;
            background: rgba(6,182,212,0.06);
            border-bottom: 1px solid rgba(6,182,212,0.10);
            font-family: 'JetBrains Mono', monospace;
            font-size: 10px;
            letter-spacing: 0.06em;
            color: rgba(6,182,212,0.55);
            z-index: 999;
            pointer-events: none;
          }
        }

        /* Content padding — responsive */
        @media (max-width: 480px)  { section { padding: 24px 14px !important; } }
        @media (min-width: 481px) and (max-width: 768px) { section { padding: 36px 20px !important; } }
        @media (min-width: 769px) and (max-width: 1100px) { section { padding: 40px 32px !important; } }
        @media (min-width: 1400px) { section { padding: 56px 64px !important; } }
        @media (min-width: 1800px) { section { padding: 64px 80px !important; } }

        /* Tables */
        @media (max-width: 768px) {
          .tbl-wrap, .table-wrap { overflow-x: auto; -webkit-overflow-scrolling: touch; }
        }

        /* Touch targets */
        @media (max-width: 768px) {
          button, .filter-btn, .lm-tab, .lm-action-btn { min-height: 36px; }
          .lm-row { min-height: 44px; }
        }

        /* Tiny screens */
        @media (max-width: 380px) {
          .lm-card { border-radius: 6px !important; }
          section  { padding: 16px 8px !important; }
        }

        /* Sidebar scrollbar */
        .cc-sidebar nav::-webkit-scrollbar { display: none; }
      `}</style>
    </div>
  );
}

const contentPad = {
  padding: "44px 48px",   // base; responsive overrides in DesktopApp <style>
  minHeight: "calc(100vh - 88px)",
  position: "relative",
  zIndex: 1,
};

/* HeroContent removed — was dead code (Market tab cut, no longer rendered).
   Kept in vision.html and strategy.html as standalone investor entry points. */

function _HeroContent_REMOVED() {
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
          background: "linear-gradient(135deg, rgba(13,32,56,0.9) 0%, rgba(18,45,76,0.8) 100%)",
          border: `1px solid ${T.borderMd}`,
          boxShadow: "0 20px 60px rgba(0,0,0,0.4)",
          display: "flex", alignItems: "center", justifyContent: "center",
          position: "relative", overflow: "hidden",
        }}>
          {/* Inner decorative elements */}
          <div style={{
            position: "absolute", top: 20, left: 20, right: 20, bottom: 20,
            border: `1px solid ${T.border}`, borderRadius: 16,
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
   EARNINGS CALENDAR WIDGET
──────────────────────────────────────────────────────────────────────── */
function EarningsCalendarWidget() {
  const [data, setData]       = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    fetch("/api/v1/market/earnings-calendar?symbols=AAPL,NVDA,MSFT,AMZN,GOOGL&days_ahead=30")
      .then(r => r.ok ? r.json() : null)
      .catch(() => null)
      .then(json => { if (!cancelled) { setData(json); setLoading(false); } });
    return () => { cancelled = true; };
  }, []);

  // Hide entirely if no data or empty / unavailable
  if (!loading && (!data || !data.available || !data.events?.length)) return null;

  const fmtDate = (d) => {
    if (!d) return "—";
    const dt = new Date(d);
    return dt.toLocaleDateString([], { month: "short", day: "numeric" });
  };
  const daysUntil = (d) => {
    if (!d) return null;
    const diff = Math.round((new Date(d) - new Date()) / 86400000);
    return diff;
  };

  return (
    <div style={{ marginTop: 28 }}>
      {/* Header */}
      <div style={{
        display: "flex", alignItems: "center", gap: 10, marginBottom: 12,
      }}>
        <div style={{ width: 14, height: 1, background: T.gold, opacity: 0.5 }} />
        <span style={{
          fontFamily: FONTS.display, fontSize: 11, fontWeight: 700,
          letterSpacing: "0.12em", color: T.t2, textTransform: "uppercase",
        }}>
          Earnings Calendar
        </span>
        <span style={{
          fontFamily: FONTS.mono, fontSize: 8, color: T.t3, opacity: 0.5,
        }}>
          EODHD · next 30 days
        </span>
      </div>

      {loading ? (
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
          {[1,2,3,4].map(i => (
            <div key={i} className="sk" style={{ height: 54, width: 120, borderRadius: 8 }} />
          ))}
        </div>
      ) : (
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
          {(data.events || []).slice(0, 8).map((ev, i) => {
            const days = daysUntil(ev.date);
            const soon = days !== null && days <= 7;
            return (
              <div key={i} style={{
                background: soon ? "rgba(200,168,75,0.05)" : T.surface,
                border: `1px solid ${soon ? "rgba(200,168,75,0.3)" : T.border}`,
                borderRadius: 8, padding: "10px 14px", minWidth: 110,
              }}>
                <div style={{
                  fontFamily: FONTS.mono, fontSize: 13, fontWeight: 700,
                  color: T.t1, marginBottom: 3,
                }}>
                  {ev.symbol || ev.ticker}
                </div>
                <div style={{
                  fontFamily: FONTS.mono, fontSize: 10, color: T.t3, marginBottom: 4,
                }}>
                  {fmtDate(ev.date)}
                </div>
                {days !== null && (
                  <div style={{
                    fontFamily: FONTS.mono, fontSize: 8, fontWeight: 700,
                    letterSpacing: "0.06em",
                    color: soon ? T.gold : T.t3,
                  }}>
                    {days === 0 ? "TODAY" : days === 1 ? "TOMORROW" : `IN ${days}D`}
                  </div>
                )}
                {ev.eps_estimate != null && (
                  <div style={{
                    fontFamily: FONTS.mono, fontSize: 8, color: T.t3, opacity: 0.7, marginTop: 2,
                  }}>
                    EPS est. {ev.eps_estimate > 0 ? "+" : ""}{ev.eps_estimate?.toFixed(2)}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────────────
   CIS SECTION
   CISLeaderboard owns the single fetch; exposes raw universe via onDataLoad
   callback → CrossAssetView renders from the same data, zero extra requests
──────────────────────────────────────────────────────────────────────── */
function CISContent({ onUniverseLoad }) {
  const [cisUniverse, setCisUniverse] = useState([]);

  const handleDataLoad = (data) => {
    setCisUniverse(data);
    if (onUniverseLoad) onUniverseLoad(data);
  };

  // Derive live stats from loaded universe
  const cisStats = cisUniverse.length > 0 ? (() => {
    const scored = cisUniverse.filter(a => (a.cis_score ?? a.score ?? 0) > 0);
    const gradeA = cisUniverse.filter(a => a.grade === "A" || a.grade === "A+").length;
    const topScore = Math.max(...scored.map(a => a.cis_score ?? a.score ?? 0));
    return [
      { label: "ASSETS",  value: cisUniverse.length,               color: T.cyan  },
      { label: "GRADE A", value: gradeA,                            color: "#00D98A" },
      { label: "TOP CIS", value: scored.length ? topScore.toFixed(1) : "—", color: T.t2 },
    ];
  })() : null;

  return (
    <div style={{ maxWidth: 1400, margin: "0 auto" }}>
      {/* Section Header */}
      <SectionLabel label="CIS" sub="Intelligence Score" stats={cisStats} />

      {/* Leaderboard — owns the fetch, fires onDataLoad when done */}
      <div className="lm-card" style={{ overflow: "hidden" }}>
        <CISLeaderboard onDataLoad={handleDataLoad} />
      </div>

      {/* Cross-Asset Overview — zero additional fetches */}
      <CrossAssetView universe={cisUniverse} />

      {/* Earnings Calendar — upcoming events for US equities in CIS universe */}
      <EarningsCalendarWidget />

      {/* Links to standalone pages */}
      <div style={{
        marginTop: 32, display: "flex", gap: 12, flexWrap: "wrap",
      }}>
        <a href="/portfolio.html" style={{
          display: "inline-flex", alignItems: "center", gap: 8,
          padding: "10px 20px", borderRadius: 8, fontSize: 12, fontWeight: 600,
          fontFamily: FONTS.display, letterSpacing: "0.04em",
          background: "rgba(6,182,212,0.08)", border: `1px solid rgba(6,182,212,0.22)`,
          color: T.cyan, textDecoration: "none",
          transition: "all .18s ease",
        }}
          onMouseEnter={e => { e.currentTarget.style.background = "rgba(6,182,212,0.14)"; e.currentTarget.style.borderColor = "rgba(6,182,212,0.4)"; }}
          onMouseLeave={e => { e.currentTarget.style.background = "rgba(6,182,212,0.08)"; e.currentTarget.style.borderColor = "rgba(6,182,212,0.22)"; }}
        >
          Portfolio Builder ↗
        </a>
        <a href="/analytics.html" style={{
          display: "inline-flex", alignItems: "center", gap: 8,
          padding: "10px 20px", borderRadius: 8, fontSize: 12, fontWeight: 600,
          fontFamily: FONTS.display, letterSpacing: "0.04em",
          background: "rgba(107,15,204,0.08)", border: `1px solid rgba(107,15,204,0.22)`,
          color: "#9945FF", textDecoration: "none",
          transition: "all .18s ease",
        }}
          onMouseEnter={e => { e.currentTarget.style.background = "rgba(107,15,204,0.14)"; e.currentTarget.style.borderColor = "rgba(107,15,204,0.4)"; }}
          onMouseLeave={e => { e.currentTarget.style.background = "rgba(107,15,204,0.08)"; e.currentTarget.style.borderColor = "rgba(107,15,204,0.22)"; }}
        >
          Score Analytics ↗
        </a>
      </div>

      {/* Asset Radar — 30-asset deep-scan table with category filters, LAS, dev scores */}
      <div style={{ marginTop: 40 }}>
        <div style={{
          display: "flex", alignItems: "center", gap: 12, marginBottom: 16,
          paddingBottom: 14, borderBottom: `1px solid ${T.border}`,
        }}>
          <div style={{ width: 14, height: 1, background: T.cyan, opacity: 0.5 }} />
          <span style={{
            fontFamily: FONTS.display, fontSize: 11, fontWeight: 700,
            letterSpacing: "0.14em", color: T.t2, textTransform: "uppercase",
          }}>
            Asset Radar
          </span>
          <span style={{ fontSize: 9, color: T.t3, fontFamily: FONTS.mono, marginLeft: "auto" }}>
            30 assets · 10 categories · live CG Pro
          </span>
        </div>
        <Suspense fallback={<SectionLoader />}>
          <AssetRadar />
        </Suspense>
      </div>
    </div>
  );
}

/* ─────────────────────────────────────────────────────────────────────────
   QUANT GP SECTION — EST Alpha Partner
──────────────────────────────────────────────────────────────────────── */
function QuantGPContent() {
  return (
    <div>
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
          background: "linear-gradient(135deg, rgba(13,32,56,0.9) 0%, rgba(18,45,76,0.8) 100%)",
          border: "2px solid rgba(200,168,75,0.3)",
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
          <div key={i} className="lm-stat-card" style={{ padding: "16px 20px" }}>
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
      <div className="lm-card" style={{ padding: 24, marginBottom: 24 }}>
        <div style={{
          fontFamily: FONTS.display, fontSize: 12, fontWeight: 700,
          color: "#C8A84B", letterSpacing: "0.1em", marginBottom: 12,
          textTransform: "uppercase",
        }}>
          Strategy Overview
        </div>
        <div style={{
          fontFamily: FONTS.body, fontSize: 14, color: T.secondary,
          lineHeight: 1.7,
        }}>
          EST Alpha employs quantitative strategies across digital asset markets,
          with a focus on systematic signal extraction and risk-adjusted return generation.
          As CometCloud's inaugural GP partner, EST Alpha provides institutional-grade
          execution infrastructure for the Vault's fund-of-funds structure.
        </div>
      </div>

      {/* Section 4 — Live Strategy Performance (QuantMonitor) */}
      <div style={{ marginBottom: 24 }}>
        <div style={{
          display: "flex", alignItems: "center", gap: 10, marginBottom: 14,
        }}>
          <div style={{ width: 14, height: 1, background: T.gold, opacity: 0.6 }} />
          <span style={{
            fontFamily: FONTS.display, fontSize: 11, fontWeight: 700,
            letterSpacing: "0.12em", color: T.t2, textTransform: "uppercase",
          }}>
            Live Strategy Performance
          </span>
          <span style={{
            fontFamily: FONTS.mono, fontSize: 8, color: T.t3, opacity: 0.5,
          }}>
            CometCloud Trading Engine · Freqtrade Dry Run
          </span>
        </div>
        <Suspense fallback={<SectionLoader />}>
          <QuantMonitor />
        </Suspense>
      </div>

      {/* Section 5 — GP Shelf */}
      <div className="lm-card-inner" style={{ padding: 20 }}>
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
  return isMobile ? <Suspense fallback={<SectionLoader />}><MobileApp /></Suspense> : <DesktopApp />;
}
