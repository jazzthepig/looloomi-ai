import { useState, useEffect, useRef, useCallback } from "react";
import MacroPulse from "./MacroPulse";
import AssetRadar from "./AssetRadar";
import SignalFeed from "./SignalFeed";
import { T, FONTS } from "../tokens";

export default function MarketDashboard({ isSection = false }) {
  const [macroRefresh, setMacroRefresh] = useState(0);
  const [assetRefresh, setAssetRefresh] = useState(0);
  const [signalRefresh, setSignalRefresh] = useState(0);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    // Trigger entrance animations after mount
    const timer = setTimeout(() => setMounted(true), 50);
    return () => clearTimeout(timer);
  }, []);

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
      <div className="market-page" style={{
        opacity: mounted ? 1 : 0,
        transform: mounted ? "translateY(0)" : "translateY(12px)",
        transition: "opacity 0.4s ease, transform 0.4s cubic-bezier(.16,1,.3,1)",
      }}>
        {/* Section Header */}
        <div style={{ marginBottom: 24, animationDelay: "0ms" }}>
          <h2 style={{
            fontFamily: FONTS.brand, fontSize: 38, fontWeight: 700,
            color: T.t1, marginBottom: 6, letterSpacing: "-0.03em",
            lineHeight: 1.05,
          }}>
            Asset Prices
          </h2>
          <p style={{
            fontFamily: FONTS.body, fontSize: 14, color: T.muted,
            maxWidth: 500, lineHeight: 1.6, margin: 0,
          }}>
            Live market data across L1, L2, DeFi, RWA, and Infrastructure — 60s refresh via CoinGecko.
          </p>
        </div>

        {/* MacroPulse Banner */}
        <div style={{
          marginBottom: 16,
          opacity: mounted ? 1 : 0,
          transform: mounted ? "translateY(0)" : "translateY(8px)",
          transition: "opacity 0.35s ease 80ms, transform 0.35s ease 80ms",
        }}>
          <MacroPulse
            refreshTrigger={macroRefresh}
            onRefresh={handleRefresh}
          />
        </div>

        {/* Market Grid: Main Content + Signal Panel */}
        <div style={{
          display: "grid",
          gridTemplateColumns: "1fr 340px",
          gap: 16,
          alignItems: "start",
        }}>
          {/* Main Content */}
          <div
            className="market-main"
            style={{
              opacity: mounted ? 1 : 0,
              transform: mounted ? "translateY(0)" : "translateY(8px)",
              transition: "opacity 0.35s ease 160ms, transform 0.35s ease 160ms",
            }}
          >
            {/* Asset Radar */}
            <AssetRadar
              refreshTrigger={assetRefresh}
            />
          </div>

          {/* Signal Panel (Right Side) */}
          <div
            className="market-side"
            style={{
              position: "sticky",
              top: 20,
              opacity: mounted ? 1 : 0,
              transform: mounted ? "translateY(0)" : "translateY(8px)",
              transition: "opacity 0.35s ease 240ms, transform 0.35s ease 240ms",
            }}
          >
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
          opacity: mounted ? 1 : 0,
          transition: "opacity 0.3s ease 320ms",
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
