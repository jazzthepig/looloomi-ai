/**
 * portfolio.jsx — Standalone Portfolio page
 *
 * Two tabs:
 *   1. Portfolio Builder (PortfolioAllocation) — CIS-driven allocation engine
 *   2. My Portfolio     (MyPortfolio)          — watchlist + P&L tracker
 *
 * Fetches /api/v1/cis/universe once, passes data down to both tabs.
 * AuthContext provided here so MyPortfolio's useAuth works.
 */
import { createRoot } from "react-dom/client";
import { useState, useEffect, Suspense, lazy } from "react";
import { AuthProvider } from "./context/AuthContext.jsx";
import { T, FONTS } from "./tokens";

const PortfolioAllocation = lazy(() => import("./components/PortfolioAllocation"));
const MyPortfolio          = lazy(() => import("./components/MyPortfolio"));

const API_BASE = "/api/v1";

/* ── Shared nav ─────────────────────────────────────────────────────────── */
function PageNav({ activeTab, setActiveTab }) {
  return (
    <nav style={{
      position: "fixed", top: 0, left: 0, right: 0, zIndex: 1000,
      background: "rgba(6,15,27,0.90)", backdropFilter: "blur(18px)",
      WebkitBackdropFilter: "blur(18px)",
      borderBottom: `1px solid ${T.border}`,
      display: "flex", alignItems: "center",
      justifyContent: "space-between", padding: "0 48px", height: 56,
    }}>
      {/* Back + brand */}
      <div style={{ display: "flex", alignItems: "center", gap: 20 }}>
        <a href="/app.html" style={{
          display: "flex", alignItems: "center", gap: 7,
          fontFamily: FONTS.mono, fontSize: 11, color: T.muted,
          letterSpacing: "0.06em", textDecoration: "none",
          transition: "color .15s",
        }}
          onMouseEnter={e => e.currentTarget.style.color = T.t1}
          onMouseLeave={e => e.currentTarget.style.color = T.muted}
        >
          ← PLATFORM
        </a>
        <div style={{ width: 1, height: 16, background: T.border }} />
        <span style={{
          fontFamily: FONTS.brand, fontWeight: 700, fontSize: 16,
          letterSpacing: "-0.01em", color: T.t1,
        }}>
          Portfolio
        </span>
      </div>

      {/* Tab switcher */}
      <div style={{
        display: "flex", gap: 1,
        background: "rgba(255,255,255,0.04)", borderRadius: 8,
        padding: 3, border: `1px solid ${T.border}`,
      }}>
        {[
          { key: "builder", label: "Portfolio Builder" },
          { key: "myportfolio", label: "My Portfolio" },
        ].map(({ key, label }) => (
          <button
            key={key}
            onClick={() => setActiveTab(key)}
            style={{
              padding: "6px 16px", borderRadius: 5, fontSize: 11, fontWeight: 600,
              fontFamily: FONTS.display, cursor: "pointer", outline: "none",
              border: `1px solid ${activeTab === key ? "rgba(6,182,212,0.35)" : "transparent"}`,
              background: activeTab === key ? "rgba(6,182,212,0.10)" : "transparent",
              color: activeTab === key ? T.cyan : T.t3,
              transition: "all 0.18s ease", letterSpacing: "0.03em", whiteSpace: "nowrap",
            }}
          >
            {label}
          </button>
        ))}
      </div>

      {/* Right spacer — keeps tab bar centred */}
      <div style={{ width: 120 }} />
    </nav>
  );
}

/* ── Loading skeleton ───────────────────────────────────────────────────── */
function Loader() {
  return (
    <div style={{
      display: "flex", alignItems: "center", justifyContent: "center",
      minHeight: 280, color: "rgba(199,210,254,0.25)",
      fontFamily: FONTS.mono, fontSize: 11, letterSpacing: "0.12em",
    }}>
      LOADING…
    </div>
  );
}

/* ── Universe status banner ─────────────────────────────────────────────── */
function UniverseBanner({ count, loading }) {
  if (loading) return null;
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 8,
      fontFamily: FONTS.mono, fontSize: 10, color: T.muted,
      letterSpacing: "0.08em", marginBottom: 28,
    }}>
      <span style={{
        width: 6, height: 6, borderRadius: "50%",
        background: count > 0 ? T.green : T.amber,
        display: "inline-block", flexShrink: 0,
      }} />
      {count > 0
        ? `CIS Universe — ${count} assets loaded`
        : "CIS Universe unavailable — limited functionality"}
    </div>
  );
}

/* ── Root page ──────────────────────────────────────────────────────────── */
function PortfolioPage() {
  const [activeTab, setActiveTab]       = useState("builder");
  const [cisUniverse, setCisUniverse]   = useState([]);
  const [universeLoading, setLoading]   = useState(true);

  useEffect(() => {
    fetch(`${API_BASE}/cis/universe`)
      .then(r => r.json())
      .then(d => {
        const raw = d.assets || d.universe || d.data || d || [];
        const arr = Array.isArray(raw) ? raw : [];
        // Normalise field shapes (T1 / T2 can differ)
        setCisUniverse(arr.map(a => ({
          ...a,
          symbol:     (a.asset_id || a.symbol || "").toUpperCase(),
          cis_score:  a.total_score ?? a.cis_score ?? 0,
        })));
      })
      .catch(() => setCisUniverse([]))
      .finally(() => setLoading(false));
  }, []);

  return (
    <div style={{ background: T.deep, minHeight: "100vh", position: "relative" }}>
      {/* Ambient orbs */}
      <div style={{
        position: "fixed", top: 0, left: 0, right: 0, bottom: 0,
        pointerEvents: "none", zIndex: 0,
      }}>
        <div style={{
          position: "absolute", top: "15%", left: "8%",
          width: 500, height: 500, borderRadius: "50%",
          background: "radial-gradient(circle, rgba(6,182,212,0.05) 0%, transparent 70%)",
          filter: "blur(80px)",
          animation: "breathe 8s ease-in-out infinite",
        }} />
        <div style={{
          position: "absolute", bottom: "20%", right: "10%",
          width: 400, height: 400, borderRadius: "50%",
          background: "radial-gradient(circle, rgba(107,15,204,0.06) 0%, transparent 70%)",
          filter: "blur(60px)",
          animation: "breathe 11s ease-in-out infinite 2s",
        }} />
      </div>

      <PageNav activeTab={activeTab} setActiveTab={setActiveTab} />

      {/* Page content */}
      <main style={{ paddingTop: 80, position: "relative", zIndex: 1 }}>
        <div style={{ maxWidth: 1600, margin: "0 auto", padding: "40px 48px 80px" }}>

          {/* Page header */}
          <div style={{ marginBottom: 36 }}>
            <h1 style={{
              fontFamily: FONTS.brand, fontSize: 42, fontWeight: 700,
              color: T.t1, letterSpacing: "-0.03em", lineHeight: 1.05,
              marginBottom: 10,
            }}>
              {activeTab === "builder" ? "Portfolio Builder" : "My Portfolio"}
            </h1>
            <p style={{
              fontFamily: FONTS.body, fontSize: 14, color: T.secondary,
              maxWidth: 560, lineHeight: 1.65, margin: 0,
            }}>
              {activeTab === "builder"
                ? "CIS-driven allocation engine — build, weight, and analyse a portfolio across any asset class with regime-aware scoring."
                : "Watchlist, position tracker, and CIS grade alerts — wallet-synced and fully private."}
            </p>
          </div>

          <UniverseBanner count={cisUniverse.length} loading={universeLoading} />

          {/* Tab content */}
          <Suspense fallback={<Loader />}>
            {activeTab === "builder" && (
              <PortfolioAllocation universe={cisUniverse} />
            )}
            {activeTab === "myportfolio" && (
              <MyPortfolio cisUniverse={cisUniverse} />
            )}
          </Suspense>

        </div>
      </main>

      <style>{`
        @keyframes breathe {
          0%, 100% { opacity: 0.6; transform: scale(1); }
          50%       { opacity: 1;   transform: scale(1.05); }
        }
        body {
          background: ${T.deep};
          margin: 0; padding: 0;
          -webkit-font-smoothing: antialiased;
        }
        * { box-sizing: border-box; }
        ::-webkit-scrollbar { width: 3px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.08); border-radius: 2px; }
      `}</style>
    </div>
  );
}

createRoot(document.getElementById("root")).render(
  <AuthProvider>
    <PortfolioPage />
  </AuthProvider>
);
