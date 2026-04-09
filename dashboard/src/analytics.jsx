/**
 * analytics.jsx — Standalone Score Analytics page
 *
 * Full-page ScoreAnalytics: grade migration heatmap, sector rotation chart,
 * grade distribution, and backtest return-by-grade table.
 *
 * Fetches /api/v1/cis/universe once, passes to ScoreAnalytics.
 */
import { createRoot } from "react-dom/client";
import { useState, useEffect, Suspense, lazy } from "react";
import { T, FONTS } from "./tokens";

const ScoreAnalytics = lazy(() => import("./components/ScoreAnalytics"));

const API_BASE = "/api/v1";

/* ── Nav ────────────────────────────────────────────────────────────────── */
function PageNav() {
  return (
    <nav style={{
      position: "fixed", top: 0, left: 0, right: 0, zIndex: 1000,
      background: "rgba(6,15,27,0.90)", backdropFilter: "blur(18px)",
      WebkitBackdropFilter: "blur(18px)",
      borderBottom: `1px solid ${T.border}`,
      display: "flex", alignItems: "center",
      justifyContent: "space-between", padding: "0 48px", height: 56,
    }}>
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
          Score Analytics
        </span>
      </div>

      {/* Right: live indicator */}
      <div style={{
        display: "flex", alignItems: "center", gap: 7,
        fontFamily: FONTS.mono, fontSize: 10, color: T.muted,
        letterSpacing: "0.08em",
      }}>
        <span style={{
          width: 6, height: 6, borderRadius: "50%",
          background: T.green, display: "inline-block",
          boxShadow: `0 0 6px ${T.green}60`,
        }} />
        CIS UNIVERSE · LIVE
      </div>
    </nav>
  );
}

/* ── Loading skeleton ───────────────────────────────────────────────────── */
function Loader() {
  return (
    <div style={{
      display: "flex", flexDirection: "column", alignItems: "center",
      justifyContent: "center", minHeight: 320, gap: 12,
    }}>
      <div style={{
        color: "rgba(199,210,254,0.25)", fontFamily: FONTS.mono,
        fontSize: 11, letterSpacing: "0.12em",
      }}>
        LOADING ANALYTICS…
      </div>
    </div>
  );
}

/* ── Root page ──────────────────────────────────────────────────────────── */
function AnalyticsPage() {
  const [cisUniverse, setCisUniverse] = useState([]);
  const [loading, setLoading]         = useState(true);
  const [error, setError]             = useState(null);

  useEffect(() => {
    fetch(`${API_BASE}/cis/universe`)
      .then(r => r.json())
      .then(d => {
        const raw = d.assets || d.universe || d.data || d || [];
        const arr = Array.isArray(raw) ? raw : [];
        setCisUniverse(arr.map(a => ({
          ...a,
          symbol:    (a.asset_id || a.symbol || "").toUpperCase(),
          cis_score: a.total_score ?? a.cis_score ?? 0,
        })));
      })
      .catch(e => setError(e.message))
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
          position: "absolute", top: "10%", right: "5%",
          width: 600, height: 600, borderRadius: "50%",
          background: "radial-gradient(circle, rgba(107,15,204,0.06) 0%, transparent 70%)",
          filter: "blur(100px)",
          animation: "breathe 10s ease-in-out infinite",
        }} />
        <div style={{
          position: "absolute", bottom: "25%", left: "12%",
          width: 400, height: 400, borderRadius: "50%",
          background: "radial-gradient(circle, rgba(6,182,212,0.04) 0%, transparent 70%)",
          filter: "blur(70px)",
          animation: "breathe 13s ease-in-out infinite 3s",
        }} />
      </div>

      <PageNav />

      <main style={{ paddingTop: 80, position: "relative", zIndex: 1 }}>
        <div style={{ maxWidth: 1600, margin: "0 auto", padding: "40px 48px 80px" }}>

          {/* Page header */}
          <div style={{ marginBottom: 36 }}>
            <h1 style={{
              fontFamily: FONTS.brand, fontSize: 42, fontWeight: 700,
              color: T.t1, letterSpacing: "-0.03em", lineHeight: 1.05,
              marginBottom: 10,
            }}>
              Score Analytics
            </h1>
            <p style={{
              fontFamily: FONTS.body, fontSize: 14, color: T.secondary,
              maxWidth: 560, lineHeight: 1.65, margin: 0,
            }}>
              Grade migration heatmap, sector rotation trends, score distribution,
              and backtest returns by CIS grade — updated with every universe refresh.
            </p>
          </div>

          {/* Universe status */}
          {!loading && (
            <div style={{
              display: "flex", alignItems: "center", gap: 8, marginBottom: 28,
              fontFamily: FONTS.mono, fontSize: 10, color: T.muted,
              letterSpacing: "0.08em",
            }}>
              <span style={{
                width: 6, height: 6, borderRadius: "50%",
                background: error ? T.red : cisUniverse.length > 0 ? T.green : T.amber,
                display: "inline-block", flexShrink: 0,
              }} />
              {error
                ? `Universe fetch error — ${error}`
                : cisUniverse.length > 0
                ? `CIS Universe — ${cisUniverse.length} assets loaded`
                : "CIS Universe unavailable — charts may be empty"}
            </div>
          )}

          {/* ScoreAnalytics — full width */}
          <Suspense fallback={<Loader />}>
            {loading
              ? <Loader />
              : <ScoreAnalytics universe={cisUniverse} />
            }
          </Suspense>

        </div>
      </main>

      <style>{`
        @keyframes breathe {
          0%, 100% { opacity: 0.6; transform: scale(1); }
          50%       { opacity: 1;   transform: scale(1.06); }
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

createRoot(document.getElementById("root")).render(<AnalyticsPage />);
