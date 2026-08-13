// App.jsx — entry shell. After B2 split (2026-08-13, design audit) this file
// owns only: route shell + ambient bg + Sidebar/Topnav mounting + lazy section
// mounting + global <style> block (responsive + sidebar scrollbar). All
// section-content logic now lives under components/.
//
// Composition:
//   App           — entry, picks desktop vs mobile
//   DesktopApp    — sidebar + topnav fallback + content pane w/ per-route lazy mounts
//   StagingBanner — orange ribbon only on ?env=staging
//   useIsMobile   — matchMedia hook
//   QuantGPContent — wrapper that composes QuantMonitor + EstAlphaSection
//
// Extracted in B2 split (2026-08-13):
//   SectionLabel / CompactSectionLabel / SectionLoader  → SectionLabels.jsx
//   Sidebar / NAV_ITEMS / SECTIONS / TOOL_LINKS          → Sidebar.jsx
//   CrossAssetView / CA_COLORS / GRADE_COLORS_CA / CLASS_ORDER → CrossAssetView.jsx
//   EarningsCalendarWidget                              → EarningsCalendarWidget.jsx
//   CISContent                                         → CISContent.jsx

import { useState, useEffect, lazy, Suspense } from "react";
import { track } from "./main.jsx";
import IntelligencePage from "./components/IntelligencePage";
import WalletConnect from "./components/WalletConnect";
import SiteNav from "./components/SiteNav";
import { Sidebar, SECTIONS } from "./components/Sidebar";
import { SectionLabel, SectionLoader } from "./components/SectionLabels";
import { CISContent } from "./components/CISContent";
import { T, FONTS } from "./tokens";

/* ── Lazy-loaded views (below fold / conditional / heavy) ── */
const VaultPage             = lazy(() => import("./components/VaultPage"));
const ApiKeysPage           = lazy(() => import("./components/ApiKeysPage"));
const ProtocolIntelligence  = lazy(() => import("./components/ProtocolIntelligence"));
const MobileApp             = lazy(() => import("./components/MobileApp"));
const QuantMonitor          = lazy(() => import("./components/QuantMonitor"));
const EstAlphaSection       = lazy(() => import("./components/EstAlphaSection"));
const MyPortfolio           = lazy(() => import("./components/MyPortfolio"));
import DiagnoseHome from "./components/DiagnoseHome";
const RiskMeter             = lazy(() => import("./components/RiskMeter"));
const StrategiesPage        = lazy(() => import("./components/StrategiesPage"));
const MultiFactorStrategies = lazy(() => import("./components/MultiFactorStrategies"));
const CISAssetDetail        = lazy(() => import("./components/CISAssetDetail"));
const SignalFeed            = lazy(() => import("./components/SignalFeed"));

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

/* ── Content pane padding — base; responsive overrides live in DesktopApp <style> ── */
const contentPad = {
  padding: "44px 48px",
  minHeight: "calc(100vh - 88px)",
  position: "relative",
  zIndex: 1,
};

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

/* ─────────────────────────────────────────────────────────────────────────
   DesktopApp — sidebar + topnav fallback + content pane
──────────────────────────────────────────────────────────────────────── */
function DesktopApp() {
  // Deep-link via ?section=xxx — e.g. /app?section=api-keys from strategy page CTA.
  // Landing is CIS Engine (leaderboard) — the actual product. Diagnose was demoted
  // from front door on 2026-08-13: asking a stranger for their entire book at the
  // point of least trust (the first page they ever see) was the wrong commitment.
  // CIS shows scores immediately; the user decides if they want to feed a book.
  const _initSection = (() => {
    const p = new URLSearchParams(window.location.search).get("section");
    if (p) window.history.replaceState({}, "", window.location.pathname);
    return p || "cis.leaderboard";
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

/* ── App: mobile/desktop router ─────────────────────────────────────────── */
export default function App() {
  const isMobile = useIsMobile();
  return isMobile ? <Suspense fallback={<SectionLoader />}><MobileApp /></Suspense> : <DesktopApp />;
}
