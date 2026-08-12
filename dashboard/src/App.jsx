import { useState, useEffect, lazy, Suspense } from "react";
import { track } from "./main.jsx";
import IntelligencePage from "./components/IntelligencePage";
import WalletConnect from "./components/WalletConnect";
import SiteNav from "./components/SiteNav";
import { T, FONTS } from "./tokens";

/* ── Lazy-loaded views (below fold / conditional / heavy) ── */
const CISLeaderboard         = lazy(() => import("./components/CISLeaderboard"));
const VaultPage              = lazy(() => import("./components/VaultPage"));
const ApiKeysPage            = lazy(() => import("./components/ApiKeysPage"));
const ProtocolIntelligence   = lazy(() => import("./components/ProtocolIntelligence"));
const MobileApp              = lazy(() => import("./components/MobileApp"));
const AssetRadar             = lazy(() => import("./components/AssetRadar"));
const QuantMonitor           = lazy(() => import("./components/QuantMonitor"));
const EstAlphaSection        = lazy(() => import("./components/EstAlphaSection"));
const MyPortfolio            = lazy(() => import("./components/MyPortfolio"));
import DiagnoseHome from "./components/DiagnoseHome";
const RiskMeter              = lazy(() => import("./components/RiskMeter"));
const SignalFeed             = lazy(() => import("./components/SignalFeed"));
const StrategiesPage         = lazy(() => import("./components/StrategiesPage"));
const MultiFactorStrategies  = lazy(() => import("./components/MultiFactorStrategies"));
const CISAssetDetail         = lazy(() => import("./components/CISAssetDetail"));

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
              <div style={{ fontFamily: FONTS.mono, fontSize: 9, letterSpacing: "0.12em", color: T.muted, textTransform: "uppercase" }}>{s.label}</div>
              <div style={{ fontFamily: FONTS.mono, fontSize: 13, color: s.color || T.t2, letterSpacing: "-0.01em" }}>{s.value}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function SectionLoader({ label = "LOADING…" }) {
  return (
    <div style={{ padding: "48px 0", textAlign: "center" }}>
      <div style={{ color: "rgba(199,210,254,0.2)", fontFamily: FONTS.mono, fontSize: 11, letterSpacing: "0.1em" }}>
        {label}
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

// NAV. Two LABEL fixes only (2026-08-11) — the ids and the render blocks are
// untouched on purpose, because renaming a route is a different, riskier change
// than renaming a word, and the full IA restructure is a product decision that
// belongs to Jazz (docs/UI_CRITIQUE_2026-08-11.md §5).
//
// 1. "Events & VC" → "VC Funding Flows". The tab promised events and delivered a
//    funding table. That is a naming bug, not a layout one: a visitor who clicks
//    a label and gets something else stops trusting the other labels too.
//
// 2. "Trading Engine · IC Loop · Freqtrade · Live" → no execution stack in the
//    subtitle. This one is not taste. CLAUDE.md hard rule #8 forbids naming our
//    implementation on investor-facing surfaces, and a third-party execution
//    framework is squarely inside it — it tells a competitor what to clone and an
//    allocator something they did not ask to know.
//
// STILL WRONG, deliberately left for a product decision:
//   · "Diagnose" is the landing page. It asks a stranger for their entire book at
//     the point of least trust — the largest commitment we can request, first.
//   · Nine peers, no hierarchy: every item claims equal importance, so none is
//     the point, so a first visitor cannot tell what we sell.
//   · "CIS Engine" / "Protocols" / "Vault" are our module names, published.
const NAV_ITEMS = [
  { id: "diagnose", label: "Diagnose", icon: "◉", sub: "Your book, read upstream of price" },
  { id: "intelligence", label: "Intelligence", icon: "◈", sub: "Signals · Macro · Funding",
    children: [
      { id: "intelligence.signals", label: "Signal Feed" },
      { id: "intelligence.macro",   label: "Macro" },
      { id: "intelligence.events",  label: "VC Funding Flows" },
    ]
  },
  { id: "cis", label: "CIS Engine", icon: "◆", sub: "Scoring · Leaderboard",
    children: [
      { id: "cis.leaderboard", label: "Leaderboard" },
      { id: "cis.radar",       label: "Asset Radar" },
    ]
  },
  { id: "strategies", label: "Strategies", icon: "▲", sub: "Autonomous · Multi-Factor" },
  { id: "protocol",  label: "Protocols", icon: "⬡", sub: "DeFi TVL · Selection" },
  { id: "vault",     label: "Vault",     icon: "◎", sub: "Fund of Funds" },
  { id: "quantgp",   label: "Research Desk", icon: "∿", sub: "Factor research · Paper books" },
  { id: "portfolio", label: "Portfolio", icon: "⊡", sub: "My Holdings" },
  { id: "api-keys",  label: "API Keys",  icon: "⌘", sub: "RaaS · Free · Pro" },
];

// Used by mobile SiteNav — top-level items only
const SECTIONS = NAV_ITEMS.map(({ id, label }) => ({ id, label }));

const TOOL_LINKS = [
  { label: "Portfolio Builder", href: "/portfolio.html" },
  { label: "Score Analytics",  href: "/analytics.html" },
  { label: "Agent API",        href: "/agent.html" },
  { label: "Fund Strategy",    href: "/strategy.html" },
  { label: "Privacy Policy",   href: "/privacy.html" },
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
          const isParentActive = activeSection === item.id || activeSection.startsWith(item.id + ".");
          const active = activeSection === item.id;
          return (
            <div key={item.id}>
              <button
                onClick={() => onNavigate(item.id)}
                style={{
                  width: "100%", textAlign: "left",
                  display: "flex", alignItems: "center", gap: 10,
                  padding: "9px 10px 9px 12px", borderRadius: 6,
                  cursor: "pointer", border: "none", marginBottom: 2,
                  background: isParentActive ? "rgba(6,182,212,0.07)" : "transparent",
                  color: isParentActive ? T.t1 : T.t3,
                  transition: "all 0.14s",
                }}
                onMouseEnter={e => { if (!isParentActive) { e.currentTarget.style.background = "rgba(255,255,255,0.025)"; e.currentTarget.style.color = T.t2; } }}
                onMouseLeave={e => { if (!isParentActive) { e.currentTarget.style.background = "transparent"; e.currentTarget.style.color = T.t3; } }}
              >
                {/* Active pip */}
                <div style={{
                  width: 2, height: 18, borderRadius: 1, flexShrink: 0,
                  background: active ? T.cyan : isParentActive ? "rgba(6,182,212,0.35)" : "transparent",
                  transition: "background 0.14s",
                }} />
                {/* Icon */}
                <span style={{ fontFamily: FONTS.mono, fontSize: 12, color: isParentActive ? T.cyan : T.t3, flexShrink: 0, lineHeight: 1, opacity: isParentActive ? 1 : 0.5 }}>
                  {item.icon}
                </span>
                {/* Label + sub */}
                <div style={{ minWidth: 0 }}>
                  <div style={{ fontFamily: FONTS.display, fontSize: 12, fontWeight: isParentActive ? 700 : 500, letterSpacing: "0.01em", whiteSpace: "nowrap" }}>
                    {item.label}
                  </div>
                  <div style={{ fontFamily: FONTS.mono, fontSize: 9, color: isParentActive ? T.t3 : T.muted, marginTop: 2, opacity: 0.65, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                    {item.sub}
                  </div>
                </div>
              </button>

              {/* Children — shown when parent is active */}
              {item.children && isParentActive && (
                <div style={{ marginLeft: 24, marginBottom: 4 }}>
                  {item.children.map(child => {
                    const childActive = activeSection === child.id;
                    return (
                      <button
                        key={child.id}
                        onClick={() => onNavigate(child.id)}
                        style={{
                          width: "100%", textAlign: "left",
                          display: "flex", alignItems: "center", gap: 8,
                          padding: "6px 10px 6px 10px", borderRadius: 5,
                          cursor: "pointer", border: "none", marginBottom: 1,
                          background: childActive ? "rgba(6,182,212,0.10)" : "transparent",
                          color: childActive ? T.cyan : "rgba(148,163,184,0.55)",
                          transition: "all 0.12s",
                        }}
                        onMouseEnter={e => { if (!childActive) { e.currentTarget.style.background = "rgba(255,255,255,0.03)"; e.currentTarget.style.color = T.t2; } }}
                        onMouseLeave={e => { if (!childActive) { e.currentTarget.style.background = "transparent"; e.currentTarget.style.color = "rgba(148,163,184,0.55)"; } }}
                      >
                        <div style={{
                          width: 1, height: 12, background: childActive ? T.cyan : "rgba(6,182,212,0.25)", borderRadius: 1, flexShrink: 0,
                        }} />
                        <span style={{ fontFamily: FONTS.display, fontSize: 11, fontWeight: childActive ? 600 : 400, letterSpacing: "0.01em", whiteSpace: "nowrap" }}>
                          {child.label}
                        </span>
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
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
          CIS v4.1 · CometCloud © 2026
        </div>
      </div>
    </div>
  );
}

function DesktopApp() {
  // Deep-link via ?section=xxx — e.g. /app?section=api-keys from strategy page CTA
  const _initSection = (() => {
    const p = new URLSearchParams(window.location.search).get("section");
    if (p) window.history.replaceState({}, "", window.location.pathname);
    return p || "diagnose";
  })();
  const [activeSection, setActiveSection] = useState(_initSection);
  const [cisUniverse, setCisUniverse]     = useState([]);
  const [assetDetailSym, setAssetDetailSym] = useState(null);
  // Lazy-mount: track which sections have been visited — mount once, keep alive
  // "cis.leaderboard" pre-seeded so clicking CIS Engine parent mounts it immediately
  const [visited, setVisited] = useState(() => new Set([_initSection]));

  const navigate = (id, extra) => {
    // "cis" parent redirects to cis.leaderboard (canonical sub-page — avoids double CISContent mount)
    const resolved = id === "cis" ? "cis.leaderboard" : id;
    // Asset deep dive: navigate("cis.asset", "BTC") — stores symbol in state, uses single slot
    if (resolved === "cis.asset" && extra) {
      setAssetDetailSym(extra.toUpperCase());
    }
    setActiveSection(resolved);
    setVisited(prev => { const next = new Set(prev); next.add(resolved); return next; });
    track("section_view", { section: resolved, symbol: extra || undefined });
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
        {/* Diagnose — the front door (iPod / Fusion #1). Your book, read upstream of price,
            with the out-of-circle fragility line. Everything else is depth behind this. */}
        <div style={{ display: activeSection === "diagnose" ? "block" : "none" }}>
          {visited.has("diagnose") && (
            <section style={contentPad}>
              <Suspense fallback={<SectionLoader label="READING YOUR BOOK…" />}>
                <DiagnoseHome embedded />
                <div style={{ height: 28 }} />
                <RiskMeter />
              </Suspense>
            </section>
          )}
        </div>

        {/* Intelligence */}
        <div style={{ display: activeSection === "intelligence" ? "block" : "none" }}>
          {visited.has("intelligence") && (
            <section style={contentPad}>
              <IntelligencePage isSection={true} />
            </section>
          )}
        </div>

        {/* Strategies */}
        <div style={{ display: activeSection === "strategies" ? "block" : "none" }}>
          {visited.has("strategies") && (
            <section style={contentPad}>
              <div style={{ maxWidth: 1400, margin: "0 auto" }}>
                {/* Multi-Factor Strategy Engine — factor weight profiles + live rescoring */}
                <div style={{ marginBottom: 32 }}>
                  <Suspense fallback={<SectionLoader label="LOADING STRATEGIES…" />}>
                    <MultiFactorStrategies />
                  </Suspense>
                </div>
                {/* Divider */}
                <div style={{
                  display: "flex", alignItems: "center", gap: 12, marginBottom: 28,
                  opacity: 0.35,
                }}>
                  <div style={{ flex: 1, height: 1, background: "rgba(255,255,255,0.08)" }} />
                  <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 9, color: "rgba(199,210,254,0.4)", letterSpacing: "0.14em" }}>
                    AUTONOMOUS EXECUTION
                  </span>
                  <div style={{ flex: 1, height: 1, background: "rgba(255,255,255,0.08)" }} />
                </div>
                {/* Autonomous strategies (fund channels) */}
                <Suspense fallback={<SectionLoader label="LOADING CHANNELS…" />}>
                  <StrategiesPage />
                </Suspense>
              </div>
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
                <SectionLabel label="Research Desk" sub="Factor research · Paper books" />
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
                <DiagnoseHome embedded />
                <div style={{ height: 28 }} />
                <RiskMeter />
                <div style={{ height: 36 }} />
                <MyPortfolio cisUniverse={cisUniverse} />
              </Suspense>
            </section>
          )}
        </div>

        {/* ── Intelligence sub-pages ─────────────────────────────────────── */}

        {/* intelligence.signals */}
        <div style={{ display: activeSection === "intelligence.signals" ? "block" : "none" }}>
          {visited.has("intelligence.signals") && (
            <section style={contentPad}>
              <div style={{ maxWidth: 1400, margin: "0 auto" }}>
                <SectionLabel label="Signal Feed" sub="Live intelligence signals" />
                <Suspense fallback={<SectionLoader />}>
                  <SignalFeed />
                </Suspense>
              </div>
            </section>
          )}
        </div>

        {/* intelligence.macro */}
        <div style={{ display: activeSection === "intelligence.macro" ? "block" : "none" }}>
          {visited.has("intelligence.macro") && (
            <section style={contentPad}>
              <IntelligencePage isSection={true} view="macro" />
            </section>
          )}
        </div>

        {/* intelligence.events */}
        <div style={{ display: activeSection === "intelligence.events" ? "block" : "none" }}>
          {visited.has("intelligence.events") && (
            <section style={contentPad}>
              <IntelligencePage isSection={true} view="events" />
            </section>
          )}
        </div>

        {/* ── CIS sub-pages ──────────────────────────────────────────────── */}

        {/* cis.leaderboard */}
        <div style={{ display: activeSection === "cis.leaderboard" ? "block" : "none" }}>
          {visited.has("cis.leaderboard") && (
            <section style={contentPad}>
              <CISContent onUniverseLoad={setCisUniverse} onNavigate={navigate} />
            </section>
          )}
        </div>

        {/* cis.radar */}
        <div style={{ display: activeSection === "cis.radar" ? "block" : "none" }}>
          {visited.has("cis.radar") && (
            <section style={contentPad}>
              <div style={{ maxWidth: 1400, margin: "0 auto" }}>
                <SectionLabel label="Asset Radar" sub="30-asset live scoring" />
                <Suspense fallback={<SectionLoader />}>
                  <AssetRadar onNavigate={navigate} />
                </Suspense>
              </div>
            </section>
          )}
        </div>

        {/* cis.asset — deep dive (single slot, symbol stored in state) */}
        <div style={{ display: activeSection === "cis.asset" ? "block" : "none" }}>
          {visited.has("cis.asset") && assetDetailSym && (
            <section style={contentPad}>
              <div style={{ maxWidth: 1400, margin: "0 auto" }}>
                <Suspense fallback={<SectionLoader />}>
                  <CISAssetDetail
                    symbol={assetDetailSym}
                    onBack={() => navigate("cis.leaderboard")}
                    onNavigate={navigate}
                  />
                </Suspense>
              </div>
            </section>
          )}
        </div>

        {/* api-keys */}
        <div style={{ display: activeSection === "api-keys" ? "block" : "none" }}>
          {visited.has("api-keys") && (
            <Suspense fallback={<SectionLoader />}>
              <ApiKeysPage />
            </Suspense>
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
function CISContent({ onUniverseLoad, onNavigate }) {
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

      {/* Leaderboard — lazy-loaded; owns the fetch, fires onDataLoad when done */}
      <div className="lm-card" style={{ overflow: "hidden" }}>
        <Suspense fallback={<SectionLoader label="LOADING LEADERBOARD…" />}>
          <CISLeaderboard
            onDataLoad={handleDataLoad}
            onAssetClick={onNavigate ? (sym) => onNavigate("cis.asset", sym) : null}
          />
        </Suspense>
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
      {/* Section 1 — Live Trading Engine (IC Loop + QuantMonitor) — FIRST */}
      <div style={{ marginBottom: 32 }}>
        <Suspense fallback={<SectionLoader />}>
          <QuantMonitor />
        </Suspense>
      </div>

      {/* Section 2 — EST Alpha Strategic GP (data-driven) */}
      <Suspense fallback={<SectionLoader />}>
        <EstAlphaSection />
      </Suspense>
    </div>
  );
}

/* ── App: mobile/desktop router ─────────────────────────────────────────── */
export default function App() {
  const isMobile = useIsMobile();
  return isMobile ? <Suspense fallback={<SectionLoader />}><MobileApp /></Suspense> : <DesktopApp />;
}
