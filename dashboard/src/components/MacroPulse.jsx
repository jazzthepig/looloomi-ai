import { useState, useEffect, useCallback } from "react";
import { T, FONTS } from "../tokens";

/* ─── Regime logic ───────────────────────────────────────────────────── */
const calculateRegime = (btc7dChange, fngValue) => {
  if (fngValue === null || fngValue === undefined) {
    if (btc7dChange > 5)   return "RISK ON";
    if (btc7dChange < -10) return "RISK OFF";
    return "NEUTRAL";
  }
  if (btc7dChange > 5 && fngValue > 50)   return "RISK ON";
  if (btc7dChange < -10 || fngValue < 25) return "RISK OFF";
  return "NEUTRAL";
};

const REGIMES = ["NEUTRAL", "RISK ON", "RISK OFF"];

const getRegimeConfig = (regime) => {
  switch (regime) {
    case "RISK ON":  return { color: T.green,  glow: "rgba(0,217,138,0.07)",  label: "看涨", desc: "机构持续加仓，BTC领涨，市场风险偏好上升" };
    case "RISK OFF": return { color: T.red,    glow: "rgba(255,61,90,0.06)",   label: "防御", desc: "机构减仓观望，避险情绪升温" };
    default:         return { color: T.gold,   glow: "rgba(200,168,75,0.05)",  label: "中性", desc: "市场横盘整理，等待方向明确" };
  }
};

const generateStatusDescription = (regime, btcDom, marketCapChange, fngValue) => {
  const configs = {
    "RISK ON":  ["风险情绪升温，山寨币有望轮动上涨", "资金回流加密市场，牛市信号增强", "市场风险偏好上升，机构态度乐观"],
    "RISK OFF": ["机构持续减仓，BTC主导率上升，市场防御模式", "恐慌情绪蔓延，主流币相对抗跌", "资金外流明显，市场处于观望状态"],
    "NEUTRAL":  ["多空力量均衡，市场等待突破信号", "BTC主导率稳定，市场情绪中性", "方向选择前，建议保持谨慎"],
  };
  const descriptions = configs[regime] || configs["NEUTRAL"];
  const fngComponent = (fngValue !== null && fngValue !== undefined) ? fngValue : 50;
  const index = Math.floor((btcDom + marketCapChange + fngComponent) / 33) % descriptions.length;
  return descriptions[Math.abs(index) % descriptions.length];
};

const getFngColor = (val) => {
  if (val === null || val === undefined) return T.muted;
  if (val > 65) return T.green;
  if (val < 35) return T.red;
  return T.amber;
};

/* ─── Loading skeleton — minimal, no card ───────────────────────────── */
const SkeletonPulse = () => (
  <div style={{ paddingBottom: 24, marginBottom: 28, borderBottom: `1px solid rgba(37,99,235,0.08)` }}>
    <div style={{ display: "flex", alignItems: "flex-end", gap: 48 }}>
      <div>
        <div className="sk" style={{ height: 8, width: 90, borderRadius: 2, marginBottom: 10 }} />
        <div className="sk" style={{ height: 40, width: 160, borderRadius: 3 }} />
      </div>
      {[100, 80, 64, 80].map((w, i) => (
        <div key={i}>
          <div className="sk" style={{ height: 7, width: 60, borderRadius: 2, marginBottom: 10 }} />
          <div className="sk" style={{ height: 28, width: w, borderRadius: 3 }} />
        </div>
      ))}
    </div>
  </div>
);

/* ─── Main ───────────────────────────────────────────────────────────── */
export default function MacroPulse({ refreshTrigger = 0 }) {
  const [loading, setLoading] = useState(true);
  const [data, setData]       = useState(null);
  const [fngData, setFngData] = useState(null);
  const [btcData, setBtcData] = useState(null);
  const [error, setError]     = useState(null);
  const [lastUpdate, setLastUpdate] = useState(null);
  const [manualRegime, setManualRegime] = useState(null);

  const fetchData = async () => {
    setError(null);
    try {
      const res  = await fetch("/api/v1/market/macro-pulse");
      if (!res.ok) throw new Error(`${res.status}`);
      const json = await res.json();
      if (json.error) throw new Error(json.error);
      setData(json.data);
      setFngData(json.fng);
      setBtcData(json.btc);
      setLastUpdate(new Date());
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { setLoading(true); fetchData(); }, [refreshTrigger]);
  useEffect(() => {
    const interval = setInterval(fetchData, 5 * 60 * 1000);
    return () => clearInterval(interval);
  }, []);

  const btcDominance        = data?.market_cap_percentage?.btc || 0;
  const totalMarketCapChange = data?.market_cap_change_percentage_24h_usd || 0;
  const fngValue            = fngData ? parseInt(fngData.value) : null;
  const fngLabel            = fngData?.value_classification || "N/A";
  const btc7dChange         = btcData?.usd_7d_change || 0;

  const calculatedRegime = calculateRegime(btc7dChange, fngValue);
  const regime           = manualRegime || calculatedRegime;
  const regimeConfig     = getRegimeConfig(regime);
  const statusDesc       = generateStatusDescription(regime, btcDominance, totalMarketCapChange, fngValue);

  const handleClick = useCallback(() => {
    const currentIndex = REGIMES.indexOf(regime);
    setManualRegime(REGIMES[(currentIndex + 1) % REGIMES.length]);
  }, [regime]);

  if (loading && !data) return <SkeletonPulse />;

  if (error && !data) return (
    <div style={{ paddingBottom: 24, marginBottom: 28, borderBottom: `1px solid rgba(37,99,235,0.08)` }}>
      <span style={{ fontFamily: FONTS.mono, fontSize: 10, color: T.red }}>数据加载失败 · {error}</span>
    </div>
  );

  return (
    <div
      onClick={handleClick}
      title="点击切换状态"
      style={{
        paddingBottom: 24,
        marginBottom: 28,
        borderBottom: `1px solid rgba(37,99,235,0.08)`,
        position: "relative",
        cursor: "pointer",
      }}
    >
      {/* Ambient glow — regime color, left-anchored */}
      <div style={{
        position: "absolute",
        top: -32, left: -48, width: "45%", bottom: -24,
        background: `radial-gradient(ellipse 80% 100% at 0% 50%, ${regimeConfig.glow}, transparent 75%)`,
        pointerEvents: "none",
      }} />

      <div style={{
        display: "flex",
        alignItems: "flex-end",
        gap: 0,
        flexWrap: "wrap",
        position: "relative",
      }}>

        {/* ── Regime — headline element ── */}
        <div style={{ paddingRight: 40, paddingBottom: 4 }}>
          <div style={{
            fontFamily: FONTS.mono, fontSize: 7, letterSpacing: "0.22em",
            color: T.t3, textTransform: "uppercase", marginBottom: 10, opacity: 0.6,
          }}>
            Market Regime
          </div>
          <div style={{
            fontFamily: FONTS.brand, fontSize: 42, fontWeight: 600,
            letterSpacing: "-0.025em", color: regimeConfig.color,
            lineHeight: 1, transition: "color 0.5s ease",
          }}>
            {regime}
          </div>
          <div style={{
            fontFamily: FONTS.mono, fontSize: 9, color: regimeConfig.color,
            opacity: 0.45, marginTop: 7, letterSpacing: "0.03em", maxWidth: 220,
            whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
          }}>
            {regimeConfig.label} · {statusDesc}
          </div>
        </div>

        {/* Divider */}
        <div style={{ width: 1, height: 52, background: "rgba(37,99,235,0.12)", marginRight: 40, marginBottom: 8, flexShrink: 0 }} />

        {/* ── BTC Price ── */}
        <div style={{ paddingRight: 36, paddingBottom: 4 }}>
          <div style={{ fontFamily: FONTS.mono, fontSize: 7, letterSpacing: "0.20em", color: T.t3, textTransform: "uppercase", marginBottom: 10, opacity: 0.6 }}>
            Bitcoin
          </div>
          <div style={{ fontFamily: FONTS.mono, fontSize: 34, fontWeight: 400, color: T.t1, letterSpacing: "-0.02em", lineHeight: 1 }}>
            {btcData?.usd != null
              ? "$" + btcData.usd.toLocaleString("en-US", { maximumFractionDigits: 0 })
              : "—"}
          </div>
          {btcData?.usd_24h_change != null && (
            <div style={{ fontFamily: FONTS.mono, fontSize: 9, marginTop: 7, color: btcData.usd_24h_change >= 0 ? T.green : T.red }}>
              {btcData.usd_24h_change >= 0 ? "+" : ""}{btcData.usd_24h_change.toFixed(1)}% 24h
            </div>
          )}
        </div>

        {/* ── BTC Dominance ── */}
        <div style={{ paddingRight: 36, paddingBottom: 4 }}>
          <div style={{ fontFamily: FONTS.mono, fontSize: 7, letterSpacing: "0.20em", color: T.t3, textTransform: "uppercase", marginBottom: 10, opacity: 0.6 }}>
            BTC Dom
          </div>
          <div style={{ fontFamily: FONTS.mono, fontSize: 28, fontWeight: 400, color: T.t1, letterSpacing: "-0.02em", lineHeight: 1 }}>
            {btcDominance.toFixed(1)}%
          </div>
          <div style={{ height: 9, marginTop: 7 }} />
        </div>

        {/* ── Fear & Greed ── */}
        <div style={{ paddingRight: 36, paddingBottom: 4 }}>
          <div style={{ fontFamily: FONTS.mono, fontSize: 7, letterSpacing: "0.20em", color: T.t3, textTransform: "uppercase", marginBottom: 10, opacity: 0.6 }}>
            Fear &amp; Greed
          </div>
          <div style={{ fontFamily: FONTS.mono, fontSize: 28, fontWeight: 400, color: getFngColor(fngValue), letterSpacing: "-0.02em", lineHeight: 1 }}>
            {fngValue !== null ? fngValue : "—"}
          </div>
          <div style={{ fontFamily: FONTS.mono, fontSize: 9, color: T.t3, marginTop: 7, letterSpacing: "0.02em", opacity: 0.7 }}>
            {fngLabel}
          </div>
        </div>

        {/* ── MCap 24h ── */}
        <div style={{ paddingRight: 36, paddingBottom: 4 }}>
          <div style={{ fontFamily: FONTS.mono, fontSize: 7, letterSpacing: "0.20em", color: T.t3, textTransform: "uppercase", marginBottom: 10, opacity: 0.6 }}>
            Total MCap 24h
          </div>
          <div style={{ fontFamily: FONTS.mono, fontSize: 28, fontWeight: 400, letterSpacing: "-0.02em", lineHeight: 1, color: totalMarketCapChange >= 0 ? T.green : T.red }}>
            {totalMarketCapChange >= 0 ? "+" : ""}{totalMarketCapChange.toFixed(2)}%
          </div>
          <div style={{ height: 9, marginTop: 7 }} />
        </div>

        {/* Live indicator — far right, minimal */}
        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 6, paddingBottom: 8, paddingLeft: 20, flexShrink: 0 }}>
          <span style={{
            width: 5, height: 5, borderRadius: "50%",
            background: T.green, flexShrink: 0,
            boxShadow: `0 0 6px ${T.green}`,
            animation: "blink 2.2s ease-in-out infinite",
          }} />
          <span style={{ fontFamily: FONTS.mono, fontSize: 8, color: T.t3, letterSpacing: "0.12em", opacity: 0.5 }}>
            {lastUpdate ? lastUpdate.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "LIVE"}
          </span>
        </div>

      </div>

      <style>{`
        @keyframes blink { 0%,100%{opacity:1} 50%{opacity:0.2} }
      `}</style>
    </div>
  );
}
