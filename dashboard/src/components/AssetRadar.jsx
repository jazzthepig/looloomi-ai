import { useState, useEffect } from "react";

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

/* ─── Asset Categories ────────────────────────────────────────────────── */
const ASSET_CATEGORIES = {
  RWA: ["ONDO", "POLYX", "SYRUP", "OPEN", "ACX"],
  ORACLE: ["LINK"],
  L1: ["BTC", "ETH", "SOL", "BNB", "AVAX", "TIA", "APT", "SUI", "INJ", "STX"],
  L2: ["ARB", "OP", "MATIC"],
  DEFI: ["UNI", "AAVE"],
};

const ASSETS = [
  { id: "bitcoin", symbol: "BTC", name: "Bitcoin", category: "L1" },
  { id: "ethereum", symbol: "ETH", name: "Ethereum", category: "L1" },
  { id: "solana", symbol: "SOL", name: "Solana", category: "L1" },
  { id: "binancecoin", symbol: "BNB", name: "BNB", category: "L1" },
  { id: "avalanche-2", symbol: "AVAX", name: "Avalanche", category: "L1" },
  { id: "chainlink", symbol: "LINK", name: "Chainlink", category: "ORACLE" },
  { id: "uniswap", symbol: "UNI", name: "Uniswap", category: "DEFI" },
  { id: "aave", symbol: "AAVE", name: "Aave", category: "DEFI" },
  { id: "optimism", symbol: "OP", name: "Optimism", category: "L2" },
  { id: "arbitrum", symbol: "ARB", name: "Arbitrum", category: "L2" },
  { id: "matic-network", symbol: "MATIC", name: "Polygon", category: "L2" },
  { id: "sui", symbol: "SUI", name: "Sui", category: "L1" },
  { id: "aptos", symbol: "APT", name: "Aptos", category: "L1" },
  { id: "injective-protocol", symbol: "INJ", name: "Injective", category: "L1" },
  { id: "celestia", symbol: "TIA", name: "Celestia", category: "L1" },
  { id: "blockstack", symbol: "STX", name: "Stacks", category: "L1" },
];

/* ─── CIS Data (fallback) ──────────────────────────────────────────── */
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
  if (change7d > 20 && fngValue > 75) {
    return { label: "Caution", color: T.red };
  }
  if (change7d < -20 && fngValue < 25) {
    return { label: "Accumulate", color: T.green };
  }
  return { label: "Hold", color: T.amber };
};

/* ─── Sparkline Component ────────────────────────────────────────────── */
const Sparkline = ({ data, positive }) => {
  if (!data || data.length < 2) return null;

  const width = 80;
  const height = 20;
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
    <svg width={width} height={height} style={{ display: "block" }}>
      <polyline
        points={points}
        fill="none"
        stroke={color}
        strokeWidth="1.4"
        strokeLinecap="round"
        strokeLinejoin="round"
        style={{ filter: `drop-shadow(0 0 3px ${color})` }}
      />
    </svg>
  );
};

/* ─── Category Badge ────────────────────────────────────────────────── */
const getCategoryBadge = (category) => {
  const styles = {
    RWA: { bg: "rgba(167,139,250,0.13)", color: T.purple, border: "rgba(167,139,250,0.22)" },
    L1: { bg: "rgba(75,158,255,0.10)", color: T.blue, border: "rgba(75,158,255,0.2)" },
    L2: { bg: "rgba(248,113,113,0.10)", color: "#F87171", border: "rgba(248,113,113,0.2)" },
    ORACLE: { bg: "rgba(245,158,11,0.10)", color: T.amber, border: "rgba(245,158,11,0.2)" },
    DEFI: { bg: "rgba(0,232,122,0.08)", color: T.green, border: "rgba(0,232,122,0.18)" },
  };

  return styles[category] || styles.L1;
};

/* ─── Grade Badge ───────────────────────────────────────────────────── */
const getGradeStyle = (grade) => {
  const styles = {
    A: { bg: "rgba(0,232,122,0.15)", color: T.green, border: "rgba(0,232,122,0.3)" },
    B: { bg: "rgba(75,158,255,0.12)", color: T.blue, border: "rgba(75,158,255,0.25)" },
    C: { bg: "rgba(245,158,11,0.12)", color: T.amber, border: "rgba(245,158,11,0.22)" },
    D: { bg: "rgba(255,61,90,0.10)", color: T.red, border: "rgba(255,61,90,0.2)" },
  };
  return styles[grade] || styles.B;
};

/* ─── Asset Card Component ──────────────────────────────────────────── */
const AssetCard = ({ asset, marketData, cisData, fngValue, onClick }) => {
  const cis = cisData?.[asset.symbol] || CIS_DATA[asset.symbol] || null;
  const change7d = marketData?.price_change_percentage_7d_in_currency || 0;
  const signal = calculateSignal(change7d, fngValue);
  const catStyle = getCategoryBadge(asset.category);
  const gradeStyle = cis ? getGradeStyle(cis.grade) : null;

  const formatPrice = (price) => {
    if (!price) return "—";
    if (price >= 1000) return price.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    if (price >= 1) return price.toFixed(2);
    return price.toFixed(4);
  };

  const formatChange = (change) => {
    if (!change) return "—";
    const prefix = change >= 0 ? "+" : "";
    return `${prefix}${change.toFixed(2)}%`;
  };

  return (
    <div
      onClick={onClick}
      style={{
        background: T.surface,
        border: `1px solid ${T.border}`,
        borderRadius: 12,
        padding: "14px 16px",
        cursor: "pointer",
        transition: "border-color 0.2s ease, transform 0.15s ease",
        position: "relative",
        display: "flex",
        flexDirection: "column",
        height: "100%",
        minHeight: 130,
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.borderColor = T.borderHi;
        e.currentTarget.style.transform = "translateY(-2px)";
        e.currentTarget.style.background = T.cardHover;
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.borderColor = T.border;
        e.currentTarget.style.transform = "translateY(0)";
        e.currentTarget.style.background = T.surface;
      }}
    >
      {/* Category Badge */}
      <div style={{
        position: "absolute",
        top: 8,
        right: 8,
        display: "flex",
        alignItems: "center",
        gap: 6,
      }}>
        {cis && (
          <div style={{
            width: 28,
            height: 28,
            borderRadius: 6,
            background: gradeStyle.bg,
            color: gradeStyle.color,
            border: `1px solid ${gradeStyle.border}`,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            fontFamily: FONTS.display,
            fontSize: 11,
            fontWeight: 800,
            letterSpacing: "0.05em",
          }}>
            {cis.grade}
          </div>
        )}
        <span style={{
          fontFamily: FONTS.display,
          fontSize: 8,
          fontWeight: 700,
          letterSpacing: "0.1em",
          padding: "2px 7px",
          borderRadius: 3,
          background: catStyle.bg,
          color: catStyle.color,
          border: `1px solid ${catStyle.border}`,
          textTransform: "uppercase",
        }}>
          {asset.category}
        </span>
      </div>

      {/* Asset Name */}
      <div style={{ marginBottom: 8 }}>
        <div style={{
          fontFamily: FONTS.display,
          fontSize: 14,
          fontWeight: 600,
          color: T.t1,
          letterSpacing: "-0.01em",
        }}>
          {asset.name}
        </div>
        <div style={{
          fontFamily: FONTS.mono,
          fontSize: 11,
          color: T.t3,
          marginTop: 2,
        }}>
          {asset.symbol}
        </div>
      </div>

      {/* Price & Change */}
      <div style={{ marginBottom: 4 }}>
        <div style={{
          fontFamily: FONTS.mono,
          fontSize: 18,
          fontWeight: 500,
          color: T.t1,
        }}>
          ${formatPrice(marketData?.current_price)}
        </div>
        <div style={{
          fontFamily: FONTS.mono,
          fontSize: 13,
          fontWeight: 500,
          color: (marketData?.price_change_percentage_24h || 0) >= 0 ? T.green : T.red,
        }}>
          {formatChange(marketData?.price_change_percentage_24h)}
        </div>
      </div>

      {/* Signal & Sparkline */}
      <div style={{
        position: "absolute",
        bottom: 12,
        left: 16,
        right: 16,
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
      }}>
        <div style={{
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
            fontFamily: FONTS.display,
            fontSize: 9,
            fontWeight: 600,
            color: signal.color,
            letterSpacing: "0.05em",
          }}>
            {signal.label}
          </span>
        </div>
        <Sparkline
          data={marketData?.sparkline_in_7d?.price}
          positive={(marketData?.price_change_percentage_7d_in_currency || 0) >= 0}
        />
      </div>
    </div>
  );
};

/* ─── Skeleton Card ─────────────────────────────────────────────────── */
const SkeletonCard = () => (
  <div style={{
    background: T.surface,
    border: `1px solid ${T.border}`,
    borderRadius: 12,
    padding: "14px 16px",
    height: "100%",
    minHeight: 130,
  }}>
    <div className="sk" style={{ height: 12, width: 60, marginBottom: 8 }} />
    <div className="sk" style={{ height: 8, width: 40, marginBottom: 16 }} />
    <div className="sk" style={{ height: 18, width: 80, marginBottom: 4 }} />
    <div className="sk" style={{ height: 12, width: 50 }} />
  </div>
);

/* ─── Filter Chips ─────────────────────────────────────────────────── */
const FILTERS = [
  { id: "all", label: "All" },
  { id: "rwa", label: "RWA" },
  { id: "oracle", label: "Oracle" },
  { id: "l1", label: "L1" },
  { id: "l2", label: "L2" },
  { id: "defi", label: "DeFi" },
];

/* ─── Main Component ────────────────────────────────────────────────── */
export default function AssetRadar({ fngValue = 50, refreshTrigger = 0 }) {
  const [loading, setLoading] = useState(true);
  const [marketData, setMarketData] = useState({});
  const [cisData, setCisData] = useState({});
  const [error, setError] = useState(null);
  const [lastUpdate, setLastUpdate] = useState(null);
  const [activeFilter, setActiveFilter] = useState("all");

  const fetchData = async () => {
    setError(null);
    try {
      const ids = ASSETS.map(a => a.id).join(",");

      const [marketsRes, cisRes] = await Promise.all([
        fetch(
          `https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&ids=${ids}&order=market_cap_desc&sparkline=true&price_change_percentage=7d`
        ),
        fetch('/api/v1/cis/scores').catch(() => null)
      ]);

      if (!marketsRes.ok) throw new Error("Markets API failed");
      const marketsData = await marketsRes.json();

      const dataMap = {};
      marketsData.forEach(coin => {
        const asset = ASSETS.find(a => a.id === coin.id);
        if (asset) {
          dataMap[asset.symbol] = coin;
        }
      });
      setMarketData(dataMap);

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
    const interval = setInterval(fetchData, 60 * 1000);
    return () => clearInterval(interval);
  }, []);

  // Filter assets
  const filteredAssets = ASSETS.filter(asset => {
    if (activeFilter === "all") return true;
    return asset.category.toLowerCase() === activeFilter;
  });

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
            fontFamily: FONTS.display,
            fontSize: 14,
            fontWeight: 600,
            color: T.t1,
          }}>
            Asset Radar
          </h2>
        </div>
        <div style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          height: 200,
          background: T.surface,
          border: "1px solid rgba(255,45,85,0.3)",
          borderRadius: 12,
          color: T.red,
          fontSize: 12,
          fontFamily: FONTS.mono,
        }}>
          数据加载失败 · {lastUpdate ? `上次更新: ${lastUpdate.toLocaleTimeString()}` : "请刷新"}
        </div>
      </div>
    );
  }

  // Grid layout
  const rows = [];
  for (let i = 0; i < filteredAssets.length; i += 4) {
    rows.push(filteredAssets.slice(i, i + 4));
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
          fontFamily: FONTS.display,
          fontSize: 14,
          fontWeight: 600,
          color: T.t1,
          letterSpacing: "-0.01em",
        }}>
          Asset Radar
        </h2>
        <span style={{
          fontFamily: FONTS.mono,
          fontSize: 10,
          color: T.t3,
        }}>
          {ASSETS.length} assets · CoinGecko
        </span>
      </div>

      {/* Filter Chips */}
      <div style={{
        display: "flex",
        gap: 5,
        flexWrap: "wrap",
        marginBottom: 14,
      }}>
        {FILTERS.map(filter => (
          <button
            key={filter.id}
            onClick={() => setActiveFilter(filter.id)}
            style={{
              fontFamily: FONTS.display,
              fontSize: 10,
              fontWeight: 600,
              letterSpacing: "0.07em",
              padding: "5px 12px",
              borderRadius: 5,
              border: `1px solid ${activeFilter === filter.id ? "rgba(200,168,75,0.28)" : T.border}`,
              color: activeFilter === filter.id ? T.gold : T.t3,
              background: activeFilter === filter.id ? T.goldDim : "none",
              cursor: "pointer",
              transition: "all 0.16s",
              textTransform: "uppercase",
            }}
          >
            {filter.label}
          </button>
        ))}
      </div>

      {/* Asset Grid */}
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
