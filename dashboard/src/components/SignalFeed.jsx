import { useState, useEffect } from "react";

/* ─── Design Tokens ──────────────────────────────────────────────────── */
const T = {
  void:      "#020208",
  deep:      "#06050F",
  surface:   "#0A0918",
  raised:    "#100E22",
  border:    "#1A173A",
  borderHi:  "#28244C",
  primary:   "#F0EEFF",
  secondary: "#8880BE",
  muted:     "#3E3A6E",
  green:     "#00D98A",
  red:       "#FF2D55",
  amber:     "#E8A000",
  gold:      "#D4AF37",
};

const FONTS = {
  display: "'Space Grotesk', sans-serif",
  body:    "'Exo 2', sans-serif",
  mono:    "'JetBrains Mono', monospace",
};

/* ─── TypeScript Interface ────────────────────────────────────────────── */
/*
interface Signal {
  id: string;
  timestamp: number;           // Unix timestamp in ms
  type: 'WHALE' | 'FUNDING' | 'FLOW' | 'MACRO' | 'RISK';
  description: string;          // Max 60 chars
  assets: string[];            // 1-3 token symbols
  importance: 'HIGH' | 'MED' | 'LOW';
}
*/

const SIGNAL_TYPES = {
  WHALE:   { label: "WHALE",   color: "#9945FF", desc: "大额转账/持仓变动" },
  FUNDING: { label: "FUNDING", color: "#00C8E0", desc: "资金费率变化" },
  FLOW:    { label: "FLOW",    color: "#00D98A", desc: "资金流入/流出" },
  MACRO:   { label: "MACRO",   color: "#F7931A", desc: "宏观事件" },
  RISK:    { label: "RISK",    color: "#FF2D55", desc: "风险信号" },
};

const IMPORTANCE_STYLES = {
  HIGH: { color: T.red, bg: "rgba(255,45,85,0.15)", border: "rgba(255,45,85,0.3)" },
  MED:  { color: T.primary, bg: "rgba(240,238,255,0.08)", border: "rgba(240,238,255,0.15)" },
  LOW:  { color: T.muted, bg: "rgba(62,58,110,0.3)", border: "rgba(62,58,110,0.5)" },
};

/* ─── Mock Signals (TODO: Replace with real API endpoint) ──────────────── */
const MOCK_SIGNALS = [
  {
    id: "s1",
    timestamp: Date.now() - 2 * 60 * 60 * 1000, // 2h ago
    type: "WHALE",
    description: "BTC单笔转入Coinbase 1,240 BTC（约$84M），交易所净流入信号",
    assets: ["BTC"],
    importance: "HIGH",
  },
  {
    id: "s2",
    timestamp: Date.now() - 4 * 60 * 60 * 1000, // 4h ago
    type: "FUNDING",
    description: "ETH永续合约资金费率转负（-0.02%），空头情绪积累",
    assets: ["ETH"],
    importance: "MED",
  },
  {
    id: "s3",
    timestamp: Date.now() - 6 * 60 * 60 * 1000, // 6h ago
    type: "MACRO",
    description: "美联储发言暗示维持高利率，风险资产短期承压",
    assets: ["BTC", "ETH"],
    importance: "HIGH",
  },
  {
    id: "s4",
    timestamp: Date.now() - 8 * 60 * 60 * 1000, // 8h ago
    type: "FLOW",
    description: "Solana链上DEX净流入$128M，创月度新高",
    assets: ["SOL"],
    importance: "MED",
  },
  {
    id: "s5",
    timestamp: Date.now() - 12 * 60 * 60 * 1000, // 12h ago
    type: "RISK",
    description: "USDC溢价扩大至-0.3%，亚洲需求疲软",
    assets: ["USDC"],
    importance: "LOW",
  },
  {
    id: "s6",
    timestamp: Date.now() - 18 * 60 * 60 * 1000, // 18h ago
    type: "WHALE",
    description: "未知地址向Binance转入4,500 ETH，减持信号",
    assets: ["ETH"],
    importance: "MED",
  },
  {
    id: "s7",
    timestamp: Date.now() - 24 * 60 * 60 * 1000, // 24h ago
    type: "FUNDING",
    description: "BTC资金费率连续3日转正，多头平仓压力增加",
    assets: ["BTC"],
    importance: "HIGH",
  },
];

/* ─── Helper Functions ───────────────────────────────────────────────── */
const formatRelativeTime = (timestamp) => {
  const diff = Date.now() - timestamp;
  const hours = Math.floor(diff / (1000 * 60 * 60));
  const minutes = Math.floor(diff / (1000 * 60));

  if (hours >= 24) {
    const days = Math.floor(hours / 24);
    return `${days}d ago`;
  }
  if (hours >= 1) {
    return `${hours}h ago`;
  }
  return `${minutes}m ago`;
};

/* ─── Signal Row Component ─────────────────────────────────────────────── */
const SignalRow = ({ signal, onClick }) => {
  const typeConfig = SIGNAL_TYPES[signal.type];
  const impStyle = IMPORTANCE_STYLES[signal.importance];

  return (
    <div
      onClick={() => onClick?.(signal)}
      style={{
        display: "flex",
        alignItems: "flex-start",
        gap: 16,
        padding: "14px 16px",
        borderRadius: 6,
        cursor: "pointer",
        transition: "background 0.15s ease",
        position: "relative",
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.background = "rgba(240,238,255,0.04)";
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.background = "transparent";
      }}
    >
      {/* Timeline Dot */}
      <div style={{
        position: "relative",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        width: 12,
      }}>
        <div style={{
          width: 8,
          height: 8,
          borderRadius: "50%",
          background: typeConfig.color,
          boxShadow: `0 0 8px ${typeConfig.color}`,
          flexShrink: 0,
        }} />
        {/* Vertical line */}
        <div style={{
          position: "absolute",
          top: 12,
          width: 1,
          height: "calc(100% - 4px)",
          background: "rgba(255,255,255,0.15)",
        }} />
      </div>

      {/* Time */}
      <div style={{
        fontSize: 11,
        fontFamily: FONTS.mono,
        color: T.muted,
        minWidth: 55,
        flexShrink: 0,
        paddingTop: 2,
      }}>
        {formatRelativeTime(signal.timestamp)}
      </div>

      {/* Content */}
      <div style={{ flex: 1, minWidth: 0 }}>
        {/* Type Tag */}
        <span style={{
          display: "inline-block",
          fontSize: 9,
          fontFamily: FONTS.mono,
          fontWeight: 600,
          color: typeConfig.color,
          border: `1px solid ${typeConfig.color}`,
          borderRadius: 3,
          padding: "2px 5px",
          marginRight: 8,
          letterSpacing: "0.05em",
        }}>
          {typeConfig.label}
        </span>

        {/* Description */}
        <span style={{
          fontSize: 12,
          fontFamily: FONTS.body,
          color: T.primary,
          lineHeight: 1.5,
        }}>
          {signal.description}
        </span>

        {/* Asset Tags */}
        <div style={{ marginTop: 8, display: "flex", gap: 6, flexWrap: "wrap" }}>
          {signal.assets.map((asset) => (
            <span key={asset} style={{
              fontSize: 10,
              fontFamily: FONTS.mono,
              fontWeight: 500,
              color: T.secondary,
              background: "rgba(136,128,190,0.15)",
              borderRadius: 4,
              padding: "2px 6px",
            }}>
              {asset}
            </span>
          ))}
        </div>
      </div>

      {/* Importance Tag */}
      <div style={{
        fontSize: 9,
        fontFamily: FONTS.mono,
        fontWeight: 600,
        color: impStyle.color,
        background: impStyle.bg,
        border: `1px solid ${impStyle.border}`,
        borderRadius: 4,
        padding: "4px 8px",
        flexShrink: 0,
        alignSelf: "flex-start",
      }}>
        {signal.importance}
      </div>
    </div>
  );
};

/* ─── Skeleton Row ───────────────────────────────────────────────────── */
const SkeletonRow = () => (
  <div style={{
    display: "flex",
    alignItems: "flex-start",
    gap: 16,
    padding: "14px 16px",
  }}>
    <div style={{ width: 8, height: 8, borderRadius: "50%", background: T.muted, flexShrink: 0 }} />
    <div className="sk" style={{ height: 12, width: 50, marginTop: 2 }} />
    <div style={{ flex: 1 }}>
      <div className="sk" style={{ height: 14, width: "80%", marginBottom: 8 }} />
      <div className="sk" style={{ height: 20, width: 120 }} />
    </div>
    <div className="sk" style={{ height: 20, width: 40 }} />
  </div>
);

/* ─── Main Component ─────────────────────────────────────────────────── */
export default function SignalFeed({ onSignalClick, refreshTrigger = 0 }) {
  const [loading, setLoading] = useState(true);
  const [signals, setSignals] = useState([]);
  const [error, setError] = useState(null);
  const [lastUpdate, setLastUpdate] = useState(null);

  const fetchSignals = async () => {
    setError(null);
    try {
      // TODO: Replace with real API endpoint
      // const res = await fetch('/api/v1/signals/today');
      // const data = await res.json();
      // setSignals(data);

      // Simulate API call with mock data
      await new Promise(resolve => setTimeout(resolve, 300));
      setSignals(MOCK_SIGNALS);
      setLastUpdate(new Date());
    } catch (err) {
      console.error("SignalFeed fetch error:", err);
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    setLoading(true);
    fetchSignals();
  }, [refreshTrigger]);

  useEffect(() => {
    const interval = setInterval(fetchSignals, 30 * 1000); // 30s refresh for future real API
    return () => clearInterval(interval);
  }, []);

  // Error state
  if (error && signals.length === 0) {
    return (
      <div>
        <div style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          marginBottom: 14,
        }}>
          <h2 style={{
            fontSize: 14,
            fontWeight: 600,
            fontFamily: FONTS.display,
            color: T.primary,
          }}>
            Signal Feed
          </h2>
        </div>
        <div style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          height: 200,
          background: "rgba(10,9,24,0.6)",
          border: "1px solid rgba(255,45,85,0.3)",
          borderRadius: 8,
          color: T.red,
          fontSize: 12,
          fontFamily: FONTS.body,
        }}>
          数据加载失败 · {lastUpdate ? `上次更新: ${lastUpdate.toLocaleTimeString()}` : "请刷新"}
        </div>
      </div>
    );
  }

  return (
    <div>
      {/* Section Title */}
      <div style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        marginBottom: 14,
      }}>
        <h2 style={{
          fontSize: 14,
          fontWeight: 600,
          fontFamily: FONTS.display,
          color: T.primary,
          letterSpacing: "-0.01em",
        }}>
          Signal Feed
        </h2>
        <span style={{
          fontSize: 10,
          color: T.muted,
          fontFamily: FONTS.mono,
        }}>
          Real-time · Today
        </span>
      </div>

      {/* Signal Timeline */}
      <div style={{
        background: "rgba(10,9,24,0.6)",
        border: "1px solid rgba(255,255,255,0.08)",
        borderRadius: 8,
        overflow: "hidden",
      }}>
        {loading
          ? Array(5).fill(0).map((_, i) => <SkeletonRow key={i} />)
          : signals.map((signal, idx) => (
              <div key={signal.id} style={{ position: "relative" }}>
                <SignalRow
                  signal={signal}
                  onClick={onSignalClick}
                />
                {/* Hide line on last item */}
                {idx < signals.length - 1 && (
                  <div style={{
                    position: "absolute",
                    left: 27,
                    top: 22,
                    width: 1,
                    height: "calc(100% - 8px)",
                    background: "rgba(255,255,255,0.08)",
                  }} />
                )}
              </div>
            ))}
      </div>

      {/* Legend */}
      <div style={{
        display: "flex",
        gap: 16,
        marginTop: 12,
        paddingLeft: 4,
      }}>
        {Object.entries(SIGNAL_TYPES).map(([key, val]) => (
          <div key={key} style={{
            display: "flex",
            alignItems: "center",
            gap: 6,
          }}>
            <div style={{
              width: 6,
              height: 6,
              borderRadius: "50%",
              background: val.color,
            }} />
            <span style={{
              fontSize: 9,
              fontFamily: FONTS.mono,
              color: T.muted,
            }}>
              {val.label}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
