import { useState, useEffect } from "react";

/* ─── Design Tokens ──────────────────────────────────────────────────── */
const T = {
  void:      "#020208",
  deep:      "#06050F",
  surface:   "#0A0918",
  raised:    "#100E22",
  border:    "#1A173A",
  primary:   "#F0EEFF",
  secondary: "#8880BE",
  muted:     "#3E3A6E",
  green:     "#00D98A",
  red:       "#FF2D55",
  amber:     "#E8A000",
};

const FONTS = {
  display: "'Space Grotesk', sans-serif",
  body:    "'Exo 2', sans-serif",
  mono:    "'JetBrains Mono', monospace",
};

/* ─── Regime Calculation Logic ──────────────────────────────────────── */
// Updated logic per requirements:
// - RISK ON: btc7dChange > 5 且 fearGreed > 50
// - RISK OFF: btc7dChange < -10 或 fearGreed < 25
// - NEUTRAL: 其余情况
const calculateRegime = (btc7dChange, fngValue) => {
  // RISK ON: BTC 7d > 5% AND Fear & Greed > 50
  if (btc7dChange > 5 && fngValue > 50) {
    return "RISK ON";
  }
  // RISK OFF: BTC 7d < -10% OR Fear & Greed < 25
  if (btc7dChange < -10 || fngValue < 25) {
    return "RISK OFF";
  }
  // NEUTRAL: everything else
  return "NEUTRAL";
};

const getRegimeConfig = (regime) => {
  switch (regime) {
    case "RISK ON":
      return {
        color: T.green,
        glow: "rgba(0, 217, 138, 0.5)",
        label: "看涨",
        description: "机构持续加仓，BTC领涨，市场风险偏好上升"
      };
    case "RISK OFF":
      return {
        color: T.red,
        glow: "rgba(255, 45, 85, 0.5)",
        label: "防御",
        description: "机构减仓观望，避险情绪升温"
      };
    default:
      return {
        color: T.secondary,
        glow: "rgba(136, 128, 190, 0.5)",
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

  // Add some logic-based variation
  const descriptions = configs[regime] || configs["NEUTRAL"];

  // Simple hash to pick consistent description
  const index = Math.floor((btcDom + marketCapChange + fngValue) / 33) % descriptions.length;
  return descriptions[index];
};

/* ─── Loading Skeleton ─────────────────────────────────────────────── */
const SkeletonPulse = () => (
  <div style={{
    display: "flex",
    alignItems: "center",
    height: 120,
    padding: "0 32px",
    background: "rgba(10,9,24,0.82)",
    border: `1px solid ${T.border}`,
    borderRadius: 10,
    gap: 40,
  }}>
    {/* Regime skeleton */}
    <div style={{ display: "flex", flexDirection: "column", gap: 8, minWidth: 160 }}>
      <div className="sk" style={{ height: 14, width: 100 }} />
      <div className="sk" style={{ height: 48, width: 140 }} />
    </div>

    {/* Divider */}
    <div style={{ width: 1, height: 80, background: T.border }} />

    {/* Metrics skeletons */}
    {[1, 2, 3].map((i) => (
      <div key={i} style={{ display: "flex", flexDirection: "column", gap: 8, flex: 1 }}>
        <div className="sk" style={{ height: 12, width: 80 }} />
        <div className="sk" style={{ height: 32, width: 100 }} />
      </div>
    ))}
  </div>
);

/* ─── Main Component ───────────────────────────────────────────────── */
export default function MacroPulse({ refreshTrigger = 0 }) {
  const [loading, setLoading] = useState(true);
  const [data, setData] = useState(null);
  const [fngData, setFngData] = useState(null);
  const [btcData, setBtcData] = useState(null);
  const [error, setError] = useState(null);
  const [lastUpdate, setLastUpdate] = useState(null);

  const fetchData = async () => {
    setError(null);
    try {
      // Fetch all data in parallel
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
    const interval = setInterval(fetchData, 5 * 60 * 1000); // 5 min refresh
    return () => clearInterval(interval);
  }, []);

  // Calculate values
  const btcDominance = data?.market_cap_percentage?.btc || 0;
  const totalMarketCapChange = data?.market_cap_change_percentage_24h_usd || 0;
  const fngValue = fngData ? parseInt(fngData.value) : 50;
  const fngLabel = fngData?.value_classification || "Neutral";
  const btc7dChange = btcData?.usd_7d_change || 0;

  // Calculate regime using new logic
  const regime = calculateRegime(btc7dChange, fngValue);
  const regimeConfig = getRegimeConfig(regime);
  const statusDescription = generateStatusDescription(regime, btcDominance, totalMarketCapChange, fngValue);

  // Get FNG color
  const getFngColor = (val) => {
    if (val > 65) return T.green;
    if (val < 35) return T.red;
    return T.amber;
  };

  // Expose lastUpdate to parent via callback or just render
  if (loading && !data) {
    return <SkeletonPulse />;
  }

  if (error && !data) {
    return (
      <div style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        height: 120,
        padding: "0 32px",
        background: "rgba(10,9,24,0.82)",
        border: "1px solid rgba(255,45,85,0.3)",
        borderRadius: 10,
        marginBottom: 20,
        color: T.red,
        fontSize: 12,
        fontFamily: FONTS.body,
      }}>
        数据加载失败 · {lastUpdate ? `上次更新: ${lastUpdate.toLocaleTimeString()}` : "请刷新"}
      </div>
    );
  }

  return (
    <div style={{
      display: "flex",
      alignItems: "center",
      height: 120,
      padding: "0 32px",
      background: "rgba(10,9,24,0.82)",
      border: `1px solid ${T.border}`,
      borderRadius: 10,
      marginBottom: 20,
      position: "relative",
      overflow: "hidden",
    }}>
      {/* Ambient glow effect */}
      <div style={{
        position: "absolute",
        left: 32,
        top: "50%",
        transform: "translateY(-50%)",
        width: 4,
        height: 80,
        background: regimeConfig.color,
        borderRadius: 2,
        boxShadow: `0 0 20px ${regimeConfig.glow}, 0 0 40px ${regimeConfig.glow}`,
        opacity: 0.8,
      }} />

      {/* Market Regime */}
      <div style={{
        display: "flex",
        flexDirection: "column",
        gap: 4,
        minWidth: 180,
        paddingLeft: 20,
      }}>
        <div style={{
          fontSize: 10,
          color: T.muted,
          letterSpacing: "0.11em",
          textTransform: "uppercase",
          fontFamily: FONTS.body,
        }}>
          Market Regime
        </div>
        <div style={{
          fontSize: 36,
          fontWeight: 700,
          fontFamily: FONTS.display,
          color: regimeConfig.color,
          lineHeight: 1.1,
          textShadow: `0 0 30px ${regimeConfig.glow}`,
          letterSpacing: "-0.02em",
        }}>
          {regime}
        </div>
      </div>

      {/* Divider */}
      <div style={{
        width: 1,
        height: 80,
        background: T.border,
        margin: "0 32px",
      }} />

      {/* Metrics */}
      <div style={{
        display: "flex",
        alignItems: "center",
        flex: 1,
        gap: 32,
      }}>
        {/* BTC Dominance */}
        <div style={{ display: "flex", flexDirection: "column", gap: 4, flex: 1 }}>
          <div style={{
            fontSize: 10,
            color: T.muted,
            letterSpacing: "0.11em",
            textTransform: "uppercase",
            fontFamily: FONTS.body,
          }}>
            BTC Dominance
          </div>
          <div style={{
            fontSize: 28,
            fontWeight: 600,
            fontFamily: FONTS.mono,
            color: T.primary,
            lineHeight: 1,
          }}>
            {btcDominance.toFixed(1)}%
          </div>
        </div>

        {/* Divider */}
        <div style={{ width: 1, height: 60, background: T.border }} />

        {/* Fear & Greed */}
        <div style={{ display: "flex", flexDirection: "column", gap: 4, flex: 1 }}>
          <div style={{
            fontSize: 10,
            color: T.muted,
            letterSpacing: "0.11em",
            textTransform: "uppercase",
            fontFamily: FONTS.body,
          }}>
            Fear & Greed
          </div>
          <div style={{
            fontSize: 28,
            fontWeight: 600,
            fontFamily: FONTS.mono,
            color: getFngColor(fngValue),
            lineHeight: 1,
          }}>
            {fngValue}
            <span style={{
              fontSize: 12,
              fontWeight: 500,
              color: getFngColor(fngValue),
              marginLeft: 8,
              fontFamily: FONTS.body,
            }}>
              {fngLabel}
            </span>
          </div>
        </div>

        {/* Divider */}
        <div style={{ width: 1, height: 60, background: T.border }} />

        {/* Total Market Cap Change */}
        <div style={{ display: "flex", flexDirection: "column", gap: 4, flex: 1 }}>
          <div style={{
            fontSize: 10,
            color: T.muted,
            letterSpacing: "0.11em",
            textTransform: "uppercase",
            fontFamily: FONTS.body,
          }}>
            Total MCap 24h
          </div>
          <div style={{
            fontSize: 28,
            fontWeight: 600,
            fontFamily: FONTS.mono,
            color: totalMarketCapChange >= 0 ? T.green : T.red,
            lineHeight: 1,
          }}>
            {totalMarketCapChange >= 0 ? "+" : ""}{totalMarketCapChange.toFixed(1)}%
          </div>
        </div>
      </div>

      {/* AI Status Description */}
      <div style={{
        position: "absolute",
        bottom: 10,
        right: 32,
        fontSize: 11,
        color: T.secondary,
        fontFamily: FONTS.body,
        maxWidth: 280,
        textAlign: "right",
        lineHeight: 1.4,
      }}>
        {statusDescription}
      </div>
    </div>
  );
}
