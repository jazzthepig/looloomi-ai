import { useState, useEffect, useRef, useCallback } from "react";
import MacroPulse from "./MacroPulse";
import AssetRadar from "./AssetRadar";
import SignalFeed from "./SignalFeed";

/* ─── Design Tokens ──────────────────────────────────────────────────── */
const T = {
  void:       "#030508",
  deep:       "#06080f",
  surface:    "#090d18",
  raised:     "#0e1424",
  card:       "#111929",
  cardHover:  "#141e2e",
  border:     "rgba(255,255,255,0.055)",
  borderMd:   "rgba(255,255,255,0.10)",
  borderHi:   "rgba(255,255,255,0.18)",
  t1:         "rgba(255,255,255,0.90)",
  t2:         "rgba(255,255,255,0.50)",
  t3:         "rgba(255,255,255,0.26)",
  t4:         "rgba(255,255,255,0.12)",
  gold:       "#C8A84B",
  goldLt:     "#E8C86A",
  goldDim:    "rgba(200,168,75,0.13)",
  goldGlow:   "rgba(200,168,75,0.06)",
  green:      "#00E87A",
  greenDim:   "rgba(0,232,122,0.10)",
  red:        "#FF3D5A",
  redDim:     "rgba(255,61,90,0.10)",
  blue:       "#4B9EFF",
  blueDim:    "rgba(75,158,255,0.10)",
  purple:     "#A78BFA",
  amber:      "#F59E0B",
};

const FONTS = {
  display: "'Syne', sans-serif",
  mono:    "'DM Mono', monospace",
  serif:   "'Cormorant Garamond', serif",
};

export default function MarketDashboard({ isSection = false }) {
  const [macroRefresh, setMacroRefresh] = useState(0);
  const [assetRefresh, setAssetRefresh] = useState(0);
  const [signalRefresh, setSignalRefresh] = useState(0);

  const handleRefresh = useCallback(() => {
    setMacroRefresh(n => n + 1);
    setAssetRefresh(n => n + 1);
    setSignalRefresh(n => n + 1);
  }, []);

  return (
    <div style={{
      maxWidth: 1440,
      margin: "0 auto",
      padding: isSection ? "0" : "80px 28px 80px",
      position: "relative",
      zIndex: 1,
    }}>
      <style>{`
        @keyframes fade-in {
          from { opacity: 0; transform: translateY(8px); }
          to { opacity: 1; transform: translateY(0); }
        }
        .market-page {
          animation: fade-in 0.25s ease forwards;
        }
      `}</style>

      <div className="market-page">
        {/* MacroPulse Banner */}
        <MacroPulse
          refreshTrigger={macroRefresh}
          onRefresh={handleRefresh}
        />

        {/* Market Grid: Main Content + Signal Panel */}
        <div style={{
          display: "grid",
          gridTemplateColumns: "1fr 340px",
          gap: 16,
          alignItems: "start",
        }}>
          {/* Main Content */}
          <div className="market-main">
            {/* Asset Radar */}
            <AssetRadar
              refreshTrigger={assetRefresh}
            />
          </div>

          {/* Signal Panel (Right Side) */}
          <div className="market-side" style={{ position: "sticky", top: 20 }}>
            <SignalFeed
              refreshTrigger={signalRefresh}
            />
          </div>
        </div>

        {/* Data Source Footer */}
        <div style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginTop: 20,
          paddingTop: 14,
          borderTop: `1px solid ${T.border}`,
          fontSize: 9,
          color: T.t3,
          letterSpacing: "0.07em",
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
            <span>Data: CoinGecko · Alternative.me</span>
          </div>
          <span style={{ fontFamily: FONTS.serif, fontStyle: "italic", fontSize: 12, color: T.t3 }}>
            CometCloud Intelligence
          </span>
        </div>
      </div>
    </div>
  );
}
