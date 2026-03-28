import { useState, useEffect, useRef, useCallback } from "react";
import MacroPulse from "./MacroPulse";
import AssetRadar from "./AssetRadar";
import SignalFeed from "./SignalFeed";
import { T, FONTS } from "../tokens";

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
        {/* Section Header */}
        <div style={{ marginBottom: 24 }}>
          <h2 style={{
            fontFamily: FONTS.brand, fontSize: 42, fontWeight: 700,
            color: T.t1, marginBottom: 6, letterSpacing: "-0.03em",
            lineHeight: 1.05,
          }}>
            Asset Prices
          </h2>
          <p style={{
            fontFamily: FONTS.body, fontSize: 14, color: "rgba(136,128,190,0.9)",
            maxWidth: 500, lineHeight: 1.6, margin: 0,
          }}>
            Live market data across L1, L2, DeFi, RWA, and Infrastructure — 60s refresh via CoinGecko.
          </p>
        </div>

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
