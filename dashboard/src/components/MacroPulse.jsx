import { useState, useEffect, useCallback } from "react";

/* ─── Design Tokens ──────────────────────────────────────────────────── */
const T = {
  void:       "#030508",
  deep:       "#06080f",
  surface:    "#090d18",
  raised:     "#0e1424",
  card:       "#111929",
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

/* ─── Regime Calculation Logic ──────────────────────────────────────── */
const calculateRegime = (btc7dChange, fngValue) => {
  if (btc7dChange > 5 && fngValue > 50) {
    return "RISK ON";
  }
  if (btc7dChange < -10 || fngValue < 25) {
    return "RISK OFF";
  }
  return "NEUTRAL";
};

const REGIMES = ["NEUTRAL", "RISK ON", "RISK OFF"];

const getRegimeConfig = (regime) => {
  switch (regime) {
    case "RISK ON":
      return {
        color: T.green,
        glow: "rgba(0,232,122,0.07)",
        borderColor: "rgba(0,232,122,0.28)",
        labelColor: T.green,
        textShadow: "0 0 28px rgba(0,232,122,0.45), 0 0 60px rgba(0,232,122,0.15)",
        label: "看涨",
        description: "机构持续加仓，BTC领涨，市场风险偏好上升"
      };
    case "RISK OFF":
      return {
        color: T.red,
        glow: "rgba(255,61,90,0.07)",
        borderColor: "rgba(255,61,90,0.28)",
        labelColor: T.red,
        textShadow: "0 0 28px rgba(255,61,90,0.45), 0 0 60px rgba(255,61,90,0.15)",
        label: "防御",
        description: "机构减仓观望，避险情绪升温"
      };
    default:
      return {
        color: T.gold,
        glow: "rgba(200,168,75,0.07)",
        borderColor: "rgba(200,168,75,0.28)",
        labelColor: T.gold,
        textShadow: "0 0 28px rgba(200,168,75,0.45), 0 0 60px rgba(200,168,75,0.15)",
        label: "中性",
        description: "市场横盘整理，等待方向明确"
      };
  }
};

/* ─── AI Status Description Generator ───────────────────────────────── */
const generateStatusDescription = (regime, btcDom, marketCapChange, fngValue) => {
  const configs = {
    "RISK ON": [
      "风险情绪升温，山寨币有望轮动上涨",
      "资金回流加密市场，牛市信号增强",
      "市场风险偏好上升，机构态度乐观",
    ],
    "RISK OFF": [
      "机构持续减仓，BTC主导率上升，市场防御模式",
      "恐慌情绪蔓延，主流币相对抗跌",
      "资金外流明显，市场处于观望状态",
    ],
    "NEUTRAL": [
      "多空力量均衡，市场等待突破信号",
      "BTC主导率稳定，市场情绪中性",
      "方向选择前，建议保持谨慎",
    ],
  };

  const descriptions = configs[regime] || configs["NEUTRAL"];
  const index = Math.floor((btcDom + marketCapChange + fngValue) / 33) % descriptions.length;
  return descriptions[index];
};

/* ─── Loading Skeleton ─────────────────────────────────────────────── */
const SkeletonPulse = () => (
  <div style={{
    borderRadius: 13,
    border: `1px solid ${T.border}`,
    background: "linear-gradient(135deg, rgba(10,14,24,.98), rgba(6,9,15,.98))",
    marginBottom: 18,
    overflow: "hidden",
    position: "relative",
    height: 120,
  }}>
    <div style={{ display: "grid", gridTemplateColumns: "220px 1px 1fr 1px 180px", alignItems: "center", padding: "20px 26px", gap: 0, height: "100%" }}>
      <div style={{ paddingRight: 26 }}>
        <div className="sk" style={{ height: 10, width: 80, marginBottom: 6 }} />
        <div className="sk" style={{ height: 36, width: 140 }} />
      </div>
      <div style={{ width: 1, height: 80, background: T.border }} />
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-around", padding: "0 30px" }}>
        {[1, 2, 3].map(i => (
          <div key={i} style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 4 }}>
            <div className="sk" style={{ height: 10, width: 60 }} />
            <div className="sk" style={{ height: 24, width: 80 }} />
          </div>
        ))}
      </div>
      <div style={{ width: 1, height: 80, background: T.border }} />
      <div style={{ paddingLeft: 24, display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 8 }}>
        <div className="sk" style={{ height: 14, width: 60 }} />
        <div className="sk" style={{ height: 10, width: 80 }} />
      </div>
    </div>
  </div>
);

/* ─── Main Component ───────────────────────────────────────────────── */
export default function MacroPulse({ refreshTrigger = 0, onRefresh }) {
  const [loading, setLoading] = useState(true);
  const [data, setData] = useState(null);
  const [fngData, setFngData] = useState(null);
  const [btcData, setBtcData] = useState(null);
  const [error, setError] = useState(null);
  const [lastUpdate, setLastUpdate] = useState(null);
  const [manualRegime, setManualRegime] = useState(null); // User override

  const fetchData = async () => {
    setError(null);
    try {
      const [globalRes, fngRes, btcRes] = await Promise.all([
        fetch("https://api.coingecko.com/api/v3/global"),
        fetch("https://api.alternative.me/fng/"),
        fetch("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd&include_24hr_change=true&include_7d_change=true")
      ]);

      if (!globalRes.ok) throw new Error("Global API failed");
      if (!fngRes.ok) throw new Error("FNG API failed");
      if (!btcRes.ok) throw new Error("BTC API failed");

      const globalJson = await globalRes.json();
      const fngJson = await fngRes.json();
      const btcJson = await btcRes.json();

      setData(globalJson.data);
      setFngData(fngJson.data[0]);
      setBtcData(btcJson.bitcoin);
      setLastUpdate(new Date());
    } catch (err) {
      console.error("MacroPulse fetch error:", err);
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    setLoading(true);
    fetchData();
  }, [refreshTrigger]);

  useEffect(() => {
    const interval = setInterval(fetchData, 5 * 60 * 1000);
    return () => clearInterval(interval);
  }, []);

  // Handle click to toggle regime
  const handleBannerClick = useCallback(() => {
    const currentRegime = manualRegime || calculateRegime(btcData?.usd_7d_change || 0, fngData ? parseInt(fngData.value) : 50);
    const currentIndex = REGIMES.indexOf(currentRegime);
    const nextIndex = (currentIndex + 1) % REGIMES.length;
    setManualRegime(REGIMES[nextIndex]);
  }, [manualRegime, btcData, fngData]);

  // Calculate values
  const btcDominance = data?.market_cap_percentage?.btc || 0;
  const totalMarketCapChange = data?.market_cap_change_percentage_24h_usd || 0;
  const fngValue = fngData ? parseInt(fngData.value) : 50;
  const fngLabel = fngData?.value_classification || "Neutral";
  const btc7dChange = btcData?.usd_7d_change || 0;

  // Calculate regime - use manual override if set
  const calculatedRegime = calculateRegime(btc7dChange, fngValue);
  const regime = manualRegime || calculatedRegime;
  const regimeConfig = getRegimeConfig(regime);
  const statusDescription = generateStatusDescription(regime, btcDominance, totalMarketCapChange, fngValue);

  const getFngColor = (val) => {
    if (val > 65) return T.green;
    if (val < 35) return T.red;
    return T.amber;
  };

  if (loading && !data) {
    return <SkeletonPulse />;
  }

  if (error && !data) {
    return (
      <div style={{
        borderRadius: 13,
        border: "1px solid rgba(255,61,90,0.3)",
        background: "linear-gradient(135deg, rgba(10,14,24,.98), rgba(6,9,15,.98))",
        marginBottom: 18,
        overflow: "hidden",
        height: 120,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        color: T.red,
        fontSize: 12,
        fontFamily: FONTS.mono,
      }}>
        数据加载失败 · {lastUpdate ? `上次更新: ${lastUpdate.toLocaleTimeString()}` : "请刷新"}
      </div>
    );
  }

  return (
    <div
      onClick={handleBannerClick}
      style={{
        borderRadius: 13,
        border: `1px solid ${regimeConfig.borderColor}`,
        background: "linear-gradient(135deg, rgba(10,14,24,.98), rgba(6,9,15,.98))",
        marginBottom: 18,
        overflow: "hidden",
        position: "relative",
        cursor: "pointer",
        transition: "border-color 0.6s ease",
      }}
    >
      {/* Ambient glow */}
      <div style={{
        position: "absolute",
        inset: 0,
        pointerEvents: "none",
        background: `radial-gradient(ellipse 70% 120% at 12% 50%, ${regimeConfig.glow}, transparent 60%)`,
        transition: "opacity 0.6s ease",
      }} />

      {/* Hint */}
      <div className="mb-hint" style={{
        position: "absolute",
        bottom: 8,
        right: 14,
        fontSize: 8,
        color: T.t3,
        letterSpacing: "0.08em",
        opacity: 0,
        transition: "opacity 0.2s",
      }}>
        点击切换状态
      </div>

      <div style={{
        display: "grid",
        gridTemplateColumns: "220px 1px 1fr 1px 180px",
        alignItems: "center",
        padding: "20px 26px",
        gap: 0,
      }}>
        {/* Market Regime */}
        <div style={{ paddingRight: 26 }}>
          <div style={{
            fontSize: 8,
            letterSpacing: "0.2em",
            color: T.t3,
            fontFamily: FONTS.display,
            fontWeight: 600,
            textTransform: "uppercase",
            marginBottom: 4,
          }}>
            Market Regime
          </div>
          <div style={{
            fontFamily: FONTS.display,
            fontSize: 28,
            fontWeight: 800,
            letterSpacing: "0.05em",
            lineHeight: 1,
            color: regimeConfig.labelColor,
            textShadow: regimeConfig.textShadow,
            transition: "color 0.6s, text-shadow 0.6s",
          }}>
            {regime}
          </div>
          <div style={{
            fontSize: 9,
            color: T.t3,
            marginTop: 6,
            letterSpacing: "0.05em",
          }}>
            {regimeConfig.label}
          </div>
        </div>

        {/* Divider */}
        <div style={{ width: 1, height: 80, background: T.border }} />

        {/* Metrics */}
        <div style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-around",
          padding: "0 30px",
          gap: 12,
        }}>
          {/* BTC Dominance */}
          <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 2 }}>
            <div style={{
              fontSize: 8,
              letterSpacing: "0.16em",
              color: T.t3,
              fontFamily: FONTS.display,
              fontWeight: 600,
              textTransform: "uppercase",
            }}>
              BTC Dominance
            </div>
            <div style={{
              fontFamily: FONTS.mono,
              fontSize: 19,
              fontWeight: 400,
              color: T.t1,
              letterSpacing: "-0.02em",
            }}>
              {btcDominance.toFixed(1)}%
            </div>
          </div>

          <div style={{ width: 1, height: 36, background: T.border }} />

          {/* Fear & Greed */}
          <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 2 }}>
            <div style={{
              fontSize: 8,
              letterSpacing: "0.16em",
              color: T.t3,
              fontFamily: FONTS.display,
              fontWeight: 600,
              textTransform: "uppercase",
            }}>
              Fear & Greed
            </div>
            <div style={{
              fontFamily: FONTS.mono,
              fontSize: 19,
              fontWeight: 400,
              color: getFngColor(fngValue),
              letterSpacing: "-0.02em",
            }}>
              {fngValue}
              <span style={{
                fontSize: 9,
                letterSpacing: "0.04em",
                color: T.t3,
                marginLeft: 8,
              }}>
                {fngLabel}
              </span>
            </div>
          </div>

          <div style={{ width: 1, height: 36, background: T.border }} />

          {/* Total Market Cap */}
          <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 2 }}>
            <div style={{
              fontSize: 8,
              letterSpacing: "0.16em",
              color: T.t3,
              fontFamily: FONTS.display,
              fontWeight: 600,
              textTransform: "uppercase",
            }}>
              Total MCap 24h
            </div>
            <div style={{
              fontFamily: FONTS.mono,
              fontSize: 19,
              fontWeight: 400,
              color: totalMarketCapChange >= 0 ? T.green : T.red,
              letterSpacing: "-0.02em",
            }}>
              {totalMarketCapChange >= 0 ? "+" : ""}{totalMarketCapChange.toFixed(1)}%
            </div>
          </div>
        </div>

        {/* Divider */}
        <div style={{ width: 1, height: 80, background: T.border }} />

        {/* Right side */}
        <div style={{ paddingLeft: 24, display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 5 }}>
          <div style={{
            display: "flex",
            alignItems: "center",
            gap: 5,
            fontSize: 9,
            color: T.green,
            letterSpacing: "0.1em",
            fontFamily: FONTS.display,
            fontWeight: 700,
          }}>
            <span style={{
              width: 5,
              height: 5,
              borderRadius: "50%",
              background: T.green,
              animation: "blink 2s ease-in-out infinite",
            }} />
            LIVE
          </div>
          <div style={{
            fontSize: 9,
            color: T.t3,
          }}>
            {lastUpdate ? lastUpdate.toLocaleTimeString() : "--:--"}
          </div>
          <div className="mb-refresh" style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
            fontSize: 8,
            color: T.t3,
          }}>
            <div style={{ width: 52, height: 2, background: "rgba(255,255,255,0.08)", borderRadius: 1, overflow: "hidden" }}>
              <div style={{
                height: "100%",
                background: T.gold,
                borderRadius: 1,
                animation: "prog 300s linear infinite",
              }} />
            </div>
            5 min
          </div>
        </div>
      </div>

      {/* AI Status Description */}
      <div style={{
        position: "absolute",
        bottom: 10,
        right: 26,
        fontSize: 11,
        color: T.t2,
        fontFamily: FONTS.serif,
        fontStyle: "italic",
        maxWidth: 280,
        textAlign: "right",
        lineHeight: 1.4,
      }}>
        {statusDescription}
      </div>

      <style>{`
        @keyframes blink {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.25; }
        }
        @keyframes prog {
          from { width: 0; }
          to { width: 100%; }
        }
        div:hover .mb-hint { opacity: 1 !important; }
      `}</style>
    </div>
  );
}
