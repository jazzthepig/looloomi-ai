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

/* ─── Asset List ─────────────────────────────────────────────────────── */
const ASSETS = [
  { id: "bitcoin", symbol: "BTC", name: "Bitcoin" },
  { id: "ethereum", symbol: "ETH", name: "Ethereum" },
  { id: "solana", symbol: "SOL", name: "Solana" },
  { id: "binancecoin", symbol: "BNB", name: "BNB" },
  { id: "avalanche-2", symbol: "AVAX", name: "Avalanche" },
  { id: "chainlink", symbol: "LINK", name: "Chainlink" },
  { id: "uniswap", symbol: "UNI", name: "Uniswap" },
  { id: "aave", symbol: "AAVE", name: "Aave" },
  { id: "optimism", symbol: "OP", name: "Optimism" },
  { id: "arbitrum", symbol: "ARB", name: "Arbitrum" },
  { id: "matic-network", symbol: "MATIC", name: "Polygon" },
  { id: "sui", symbol: "SUI", name: "Sui" },
  { id: "aptos", symbol: "APT", name: "Aptos" },
  { id: "injective-protocol", symbol: "INJ", name: "Injective" },
  { id: "celestia", symbol: "TIA", name: "Celestia" },
  { id: "blockstack", symbol: "STX", name: "Stacks" },
];

/* ─── CIS Data (from MarketPage) ────────────────────────────────────── */
const CIS_DATA = {
  BTC:  { score: 85.0, grade: "A" },
  ETH:  { score: 85.0, grade: "A" },
  SOL:  { score: 81.8, grade: "B" },
  BNB:  { score: 78.0, grade: "B" },
  AVAX: { score: 78.5, grade: "B" },
  LINK: { score: 80.0, grade: "B" },
  UNI:  { score: 77.8, grade: "B" },
  AAVE: { score: 77.2, grade: "B" },
  OP:   { score: 68.6, grade: "C" },
  ARB:  { score: 70.8, grade: "B" },
  MATIC:{ score: 72.0, grade: "B" },
  SUI:  { score: 75.0, grade: "B" },
  APT:  { score: 70.0, grade: "B" },
  INJ:  { score: 73.0, grade: "B" },
  TIA:  { score: 68.0, grade: "C" },
  STX:  { score: 65.0, grade: "C" },
};

/* ─── Signal Calculation ─────────────────────────────────────────────── */
const calculateSignal = (change7d, fngValue) => {
  // Simple rules as specified
  if (change7d > 20 && fngValue > 75) {
    return { label: "Caution", color: T.red, dot: "🔴" };
  }
  if (change7d < -20 && fngValue < 25) {
    return { label: "Accumulate", color: T.green, dot: "🟢" };
  }
  return { label: "Hold", color: T.amber, dot: "🟡" };
};

/* ─── Sparkline Component ────────────────────────────────────────────── */
const Sparkline = ({ data, positive }) => {
  if (!data || data.length < 2) return null;

  const width = 120;
  const height = 24;
  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;

  const points = data.map((val, i) => {
    const x = (i / (data.length - 1)) * width;
    const y = height - ((val - min) / range) * height;
    return `${x},${y}`;
  }).join(" ");

  const color = positive ? T.green : T.red;

  return (
    <svg width={width} height={height} style={{ display: "block", marginTop: 8 }}>
      <polyline
        points={points}
        fill="none"
        stroke={color}
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
        style={{ filter: `drop-shadow(0 0 3px ${color})` }}
      />
    </svg>
  );
};

/* ─── Asset Card Component ──────────────────────────────────────────── */
const AssetCard = ({ asset, marketData, cisData, fngValue, onClick }) => {
  // Use API CIS data first, fallback to mock CIS_DATA, then show "—" if none
  const cis = cisData?.[asset.symbol] || CIS_DATA[asset.symbol] || null;
  const change7d = marketData?.price_change_percentage_7d_in_currency || 0;
  const signal = calculateSignal(change7d, fngValue);

  const formatPrice = (price) => {
    if (price >= 1000) return price.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    if (price >= 1) return price.toFixed(2);
    return price.toFixed(4);
  };

  const formatChange = (change) => {
    const prefix = change >= 0 ? "+" : "";
    return `${prefix}${change.toFixed(2)}%`;
  };

  return (
    <div
      onClick={onClick}
      style={{
        background: "rgba(10,9,24,0.6)",
        border: "1px solid rgba(255,255,255,0.08)",
        borderRadius: 8,
        padding: "14px 16px",
        cursor: "pointer",
        transition: "border-color 0.2s ease, transform 0.15s ease",
        position: "relative",
        display: "flex",
        flexDirection: "column",
        height: "100%",
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.borderColor = "rgba(255,255,255,0.2)";
        e.currentTarget.style.transform = "translateY(-2px)";
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.borderColor = "rgba(255,255,255,0.08)";
        e.currentTarget.style.transform = "translateY(0)";
      }}
    >
      {/* CIS Badge - Top Right */}
      {cis ? (
        <div style={{
          position: "absolute",
          top: 8,
          right: 8,
          background: `linear-gradient(135deg, ${T.gold} 0%, #B8962E 100%)`,
          color: "#000",
          fontSize: 10,
          fontWeight: 700,
          fontFamily: FONTS.mono,
          padding: "3px 6px",
          borderRadius: 4,
          letterSpacing: "0.05em",
        }}>
          {cis.grade} {cis.score?.toFixed(0)}
        </div>
      ) : (
        <div style={{
          position: "absolute",
          top: 8,
          right: 8,
          fontSize: 9,
          color: T.muted,
          fontFamily: FONTS.body,
        }}>
          Scoring...
        </div>
      )}

      {/* Asset Name & Symbol */}
      <div style={{ marginBottom: 8 }}>
        <div style={{
          fontSize: 14,
          fontWeight: 600,
          fontFamily: FONTS.display,
          color: T.primary,
          letterSpacing: "-0.01em",
        }}>
          {asset.name}
        </div>
        <div style={{
          fontSize: 11,
          color: T.muted,
          fontFamily: FONTS.mono,
          marginTop: 2,
        }}>
          {asset.symbol}
        </div>
      </div>

      {/* Price & Change */}
      <div style={{ marginBottom: 4 }}>
        <div style={{
          fontSize: 18,
          fontWeight: 600,
          fontFamily: FONTS.mono,
          color: T.primary,
        }}>
          ${formatPrice(marketData?.current_price)}
        </div>
        <div style={{
          fontSize: 13,
          fontWeight: 500,
          fontFamily: FONTS.mono,
          color: (marketData?.price_change_percentage_24h || 0) >= 0 ? T.green : T.red,
        }}>
          {formatChange(marketData?.price_change_percentage_24h || 0)}
        </div>
      </div>

      {/* Signal - Bottom Left */}
      <div style={{
        position: "absolute",
        bottom: 12,
        left: 16,
        display: "flex",
        alignItems: "center",
        gap: 6,
      }}>
        <div style={{
          width: 8,
          height: 8,
          borderRadius: "50%",
          background: signal.color,
          boxShadow: `0 0 8px ${signal.color}`,
        }} />
        <span style={{
          fontSize: 10,
          fontWeight: 500,
          fontFamily: FONTS.body,
          color: signal.color,
        }}>
          {signal.label}
        </span>
      </div>

      {/* Sparkline - Bottom */}
      <div style={{
        position: "absolute",
        bottom: 8,
        right: 12,
      }}>
        <Sparkline
          data={marketData?.sparkline_in_7d?.price}
          positive={(marketData?.price_change_percentage_7d_in_currency || 0) >= 0}
        />
      </div>
    </div>
  );
};

/* ─── Skeleton Card ──────────────────────────────────────────────────── */
const SkeletonCard = () => (
  <div style={{
    background: "rgba(10,9,24,0.6)",
    border: "1px solid rgba(255,255,255,0.08)",
    borderRadius: 8,
    padding: "14px 16px",
    height: "100%",
    minHeight: 140,
  }}>
    <div className="sk" style={{ height: 12, width: 60, marginBottom: 8 }} />
    <div className="sk" style={{ height: 8, width: 40, marginBottom: 16 }} />
    <div className="sk" style={{ height: 18, width: 80, marginBottom: 4 }} />
    <div className="sk" style={{ height: 12, width: 50 }} />
  </div>
);

/* ─── Main Component ────────────────────────────────────────────────── */
export default function AssetRadar({ fngValue = 50, refreshTrigger = 0 }) {
  const [loading, setLoading] = useState(true);
  const [marketData, setMarketData] = useState({});
  const [cisData, setCisData] = useState({});
  const [error, setError] = useState(null);
  const [lastUpdate, setLastUpdate] = useState(null);

  const fetchData = async () => {
    setError(null);
    try {
      const ids = ASSETS.map(a => a.id).join(",");

      // Fetch market data and CIS scores in parallel
      const [marketsRes, cisRes] = await Promise.all([
        fetch(
          `https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&ids=${ids}&order=market_cap_desc&sparkline=true&price_change_percentage=7d`
        ),
        fetch('/api/v1/cis/scores').catch(() => null) // Gracefully handle missing API
      ]);

      if (!marketsRes.ok) throw new Error("Markets API failed");
      const marketsData = await marketsRes.json();

      // Process market data
      const dataMap = {};
      marketsData.forEach(coin => {
        const asset = ASSETS.find(a => a.id === coin.id);
        if (asset) {
          dataMap[asset.symbol] = coin;
        }
      });
      setMarketData(dataMap);

      // Process CIS data if available
      if (cisRes && cisRes.ok) {
        try {
          const cisJson = await cisRes.json();
          if (cisJson.scores) {
            const cisMap = {};
            cisJson.scores.forEach(item => {
              cisMap[item.symbol] = { score: item.cis_score, grade: item.grade };
            });
            setCisData(cisMap);
          }
        } catch (e) {
          console.warn("CIS data parse error:", e);
        }
      }

      setLastUpdate(new Date());
    } catch (err) {
      console.error("AssetRadar fetch error:", err);
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

    fetchData();
    const interval = setInterval(fetchData, 60 * 1000); // 60s refresh
    return () => clearInterval(interval);
  }, []);

  // Error state
  if (error && Object.keys(marketData).length === 0) {
    return (
      <div style={{ marginBottom: 24 }}>
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
            Asset Radar
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

  // Arrange in 4x4 grid
  const rows = [];
  for (let i = 0; i < ASSETS.length; i += 4) {
    rows.push(ASSETS.slice(i, i + 4));
  }

  return (
    <div style={{ marginBottom: 24 }}>
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
          Asset Radar
        </h2>
        <span style={{
          fontSize: 10,
          color: T.muted,
          fontFamily: FONTS.mono,
        }}>
          {ASSETS.length} assets · CoinGecko
        </span>
      </div>

      {/* 4x4 Grid */}
      <div style={{
        display: "grid",
        gridTemplateColumns: "repeat(4, 1fr)",
        gap: 10,
      }}>
        {loading
          ? Array(16).fill(0).map((_, i) => <SkeletonCard key={i} />)
          : rows.flatMap((row, rowIdx) =>
              row.map((asset, colIdx) => (
                <AssetCard
                  key={asset.symbol}
                  asset={asset}
                  marketData={marketData[asset.symbol]}
                  cisData={cisData}
                  fngValue={fngValue}
                  onClick={() => {}}
                />
              ))
            )}
      </div>
    </div>
  );
}
