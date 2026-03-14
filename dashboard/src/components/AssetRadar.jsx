import { useState, useEffect } from "react";
import { T, FONTS } from "../tokens";

/* ─── Asset Categories ────────────────────────────────────────────────── */
// Asset list matching CIS universe
const ASSETS = [
  // L1
  { id: "bitcoin", symbol: "BTC", name: "Bitcoin", category: "L1", color: "#F7931A" },
  { id: "ethereum", symbol: "ETH", name: "Ethereum", category: "Crypto", color: "#627EEA" },
  { id: "solana", symbol: "SOL", name: "Solana", category: "L1", color: "#9945FF" },
  { id: "binancecoin", symbol: "BNB", name: "BNB", category: "L1", color: "#F3BA2F" },
  { id: "cardano", symbol: "ADA", name: "Cardano", category: "L1", color: "#0033AD" },
  { id: "ripple", symbol: "XRP", name: "XRP", category: "L1", color: "#23292F" },
  { id: "dogecoin", symbol: "DOGE", name: "Dogecoin", category: "L1", color: "#C2A633" },
  { id: "the-open-network", symbol: "TON", name: "Toncoin", category: "L1", color: "#0098EA" },
  { id: "avalanche-2", symbol: "AVAX", name: "Avalanche", category: "L1", color: "#E84142" },
  { id: "polkadot", symbol: "DOT", name: "Polkadot", category: "L1", color: "#E6007A" },
  // L2
  { id: "arbitrum", symbol: "ARB", name: "Arbitrum", category: "L2", color: "#28A0F0" },
  { id: "optimism", symbol: "OP", name: "Optimism", category: "L2", color: "#FF0420" },
  { id: "matic-network", symbol: "MATIC", name: "Polygon", category: "L2", color: "#8247E5" },
  { id: "immutable-x", symbol: "IMX", name: "Immutable", category: "L2", color: "#00BFFF" },
  { id: "base", symbol: "BASE", name: "Base", category: "L2", color: "#0052FF" },
  { id: "mantle", symbol: "MANTLE", name: "Mantle", category: "L2", color: "#00A8E0" },
  // DeFi
  { id: "uniswap", symbol: "UNI", name: "Uniswap", category: "DeFi", color: "#FF007A" },
  { id: "aave", symbol: "AAVE", name: "Aave", category: "DeFi", color: "#2EBAC6" },
  { id: "maker", symbol: "MKR", name: "Maker", category: "DeFi", color: "#1AAB9B" },
  { id: "havven", symbol: "SNX", name: "Synthetix", category: "DeFi", color: "#00D1FF" },
  { id: "curve-dao-token", symbol: "CRV", name: "Curve", category: "DeFi", color: "#FF6B6B" },
  { id: "lido-dao", symbol: "LDO", name: "Lido", category: "DeFi", color: "#00A3FF" },
  { id: "rocket-pool", symbol: "RPL", name: "Rocket Pool", category: "DeFi", color: "#FFFFFF" },
  { id: "compound-governance-token", symbol: "COMP", name: "Compound", category: "DeFi", color: "#00D395" },
  { id: "sushi", symbol: "SUSHI", name: "SushiSwap", category: "DeFi", color: "#FA52A0" },
  // Infrastructure
  { id: "chainlink", symbol: "LINK", name: "Chainlink", category: "Infrastructure", color: "#2A5ADA" },
  { id: "stacks", symbol: "STX", name: "Stacks", category: "Infrastructure", color: "#5546D6" },
  { id: "thorchain", symbol: "RUNE", name: "THORChain", category: "Infrastructure", color: "#2ECC71" },
  { id: "injective-protocol", symbol: "INJ", name: "Injective", category: "Infrastructure", color: "#00F2FE" },
  // RWA
  { id: "ondo-finance", symbol: "ONDO", name: "Ondo", category: "RWA", color: "#2B65EC" },
  { id: "genius", symbol: "GENIUS", name: "Genius", category: "RWA", color: "#FFD700" },
  { id: "polymesh", symbol: "POLYX", name: "Polymesh", category: "#RWA", color: "#E6007A" },
  // Memecoin
  { id: "pepe", symbol: "PEPE", name: "Pepe", category: "Memecoin", color: "#00FF00" },
];

/* ─── CIS Data (fallback - rarely used) ──────────────────────────────────── */
// Empty - now using API data only
const CIS_DATA = {};

/* ─── Signal Calculation ─────────────────────────────────────────────── */
const calculateSignal = (change7d, fngValue) => {
  if (change7d > 20 && fngValue > 75) {
    return { label: "CAUTION", color: T.red, bg: "rgba(255,61,90,0.12)", border: "rgba(255,61,90,0.25)" };
  }
  if (change7d < -20 && fngValue < 25) {
    return { label: "ACCUMULATE", color: T.green, bg: "rgba(0,232,122,0.12)", border: "rgba(0,232,122,0.25)" };
  }
  return { label: "HOLD", color: T.blue, bg: "rgba(75,158,255,0.10)", border: "rgba(75,158,255,0.22)" };
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

/* ─── Grade Style ───────────────────────────────────────────────────── */
const getGradeStyle = (grade) => {
  const styles = {
    "A+": { bg: "rgba(0,232,122,0.18)", color: T.green, border: "rgba(0,232,123,0.4)" },
    A: { bg: "rgba(0,232,122,0.15)", color: T.green, border: "rgba(0,232,123,0.3)" },
    "B+": { bg: "rgba(75,158,255,0.15)", color: T.blue, border: "rgba(75,158,255,0.35)" },
    B: { bg: "rgba(75,158,255,0.12)", color: T.blue, border: "rgba(75,158,255,0.25)" },
    "C+": { bg: "rgba(245,158,11,0.15)", color: T.amber, border: "rgba(245,158,11,0.35)" },
    C: { bg: "rgba(245,158,11,0.12)", color: T.amber, border: "rgba(245,158,11,0.22)" },
    D: { bg: "rgba(255,61,90,0.10)", color: T.red, border: "rgba(255,61,90,0.2)" },
    F: { bg: "rgba(136,136,136,0.10)", color: "#888888", border: "rgba(136,136,136,0.2)" },
  };
  return styles[grade] || styles.B;
};

/* ─── Sparkline SVG ────────────────────────────────────────────────── */
const Sparkline = ({ data, positive }) => {
  if (!data || data.length < 2) return null;

  const width = 70;
  const height = 18;
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
      />
    </svg>
  );
};

/* ─── Filter Chips ─────────────────────────────────────────────────── */
const FILTERS = [
  { id: "all", label: "All" },
  { id: "rwa", label: "RWA" },
  { id: "oracle", label: "Oracle" },
  { id: "l1", label: "L1" },
  { id: "l2", label: "L2" },
  { id: "defi", label: "DeFi" },
];

/* ─── Table Row Component ───────────────────────────────────────────── */
const AssetRow = ({ asset, marketData, cisData, fngValue }) => {
  const cis = cisData?.[asset.symbol] || CIS_DATA[asset.symbol] || null;
  const change7d = marketData?.price_change_percentage_7d_in_currency || 0;
  const change24h = marketData?.price_change_percentage_24h || 0;
  const signal = calculateSignal(change7d, fngValue);
  const catStyle = getCategoryBadge(asset.category);
  const gradeStyle = cis ? getGradeStyle(cis.grade) : null;

  const formatPrice = (price) => {
    if (!price) return "—";
    if (price >= 1000) return "$" + price.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    if (price >= 1) return "$" + price.toFixed(2);
    return "$" + price.toFixed(4);
  };

  const formatChange = (change) => {
    if (!change) return "—";
    const prefix = change >= 0 ? "+" : "";
    return `${prefix}${change.toFixed(1)}%`;
  };

  const formatVol = (vol) => {
    if (!vol) return "—";
    if (vol >= 1e9) return `$${(vol / 1e9).toFixed(1)}B`;
    if (vol >= 1e6) return `$${(vol / 1e6).toFixed(1)}M`;
    return `$${(vol / 1e3).toFixed(0)}K`;
  };

  return (
    <tr style={{ transition: "background 0.14s", cursor: "pointer" }}
      onMouseEnter={(e) => e.currentTarget.style.background = "rgba(255,255,255,0.022)"}
      onMouseLeave={(e) => e.currentTarget.style.background = "transparent"}
    >
      {/* Asset */}
      <td style={{ width: 240 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div style={{
            width: 34, height: 34, borderRadius: 9,
            background: `${asset.color}22`, color: asset.color,
            display: "flex", alignItems: "center", justifyContent: "center",
            fontFamily: FONTS.display, fontSize: 10, fontWeight: 800,
          }}>
            {asset.symbol.slice(0, 2)}
          </div>
          <div>
            <div style={{ fontFamily: FONTS.display, fontSize: 12, fontWeight: 600, color: T.t1 }}>
              {asset.name}
            </div>
            <span style={{
              fontFamily: FONTS.display, fontSize: 8, fontWeight: 700,
              letterSpacing: "0.1em", padding: "2px 6px", borderRadius: 3,
              background: catStyle.bg, color: catStyle.color, border: `1px solid ${catStyle.border}`,
              textTransform: "uppercase",
            }}>
              {asset.category}
            </span>
          </div>
        </div>
      </td>

      {/* Price */}
      <td style={{ textAlign: "right" }}>
        <div style={{ fontFamily: FONTS.mono, fontSize: 13, fontWeight: 500, color: T.t1 }}>
          {formatPrice(marketData?.current_price)}
        </div>
      </td>

      {/* 24H */}
      <td style={{ textAlign: "right" }}>
        <div style={{
          fontFamily: FONTS.mono, fontSize: 13, fontWeight: 500,
          color: change24h >= 0 ? T.green : T.red,
        }}>
          {formatChange(change24h)}
        </div>
      </td>

      {/* TVL */}
      <td style={{ textAlign: "right" }}>
        <div style={{ fontFamily: FONTS.mono, fontSize: 13, fontWeight: 400, color: T.t2 }}>
          {formatVol(marketData?.total_volume)}
        </div>
      </td>

      {/* CIS */}
      <td style={{ textAlign: "right" }}>
        {cis && (
          <div style={{
            width: 28, height: 28, borderRadius: 6,
            background: gradeStyle.bg, color: gradeStyle.color,
            border: `1px solid ${gradeStyle.border}`,
            display: "inline-flex", alignItems: "center", justifyContent: "center",
            fontFamily: FONTS.display, fontSize: 11, fontWeight: 800,
          }}>
            {cis.grade}
          </div>
        )}
      </td>

      {/* Signal */}
      <td style={{ textAlign: "right" }}>
        <span style={{
          fontFamily: FONTS.display, fontSize: 9, fontWeight: 700,
          letterSpacing: "0.08em", padding: "4px 10px", borderRadius: 4,
          background: signal.bg, color: signal.color, border: `1px solid ${signal.border}`,
          textTransform: "uppercase",
        }}>
          {signal.label}
        </span>
      </td>

      {/* Vol */}
      <td style={{ textAlign: "right" }}>
        <div style={{ fontFamily: FONTS.mono, fontSize: 13, fontWeight: 400, color: T.t2 }}>
          {formatVol(marketData?.total_volume)}
        </div>
      </td>

      {/* 7D */}
      <td style={{ textAlign: "right", width: 80 }}>
        <Sparkline
          data={marketData?.sparkline_in_7d?.price}
          positive={change7d >= 0}
        />
      </td>
    </tr>
  );
};

/* ─── Skeleton Row ─────────────────────────────────────────────────── */
const SkeletonRow = () => (
  <tr>
    <td><div style={{ display: "flex", alignItems: "center", gap: 10 }}><div className="sk" style={{ width: 34, height: 34, borderRadius: 9 }} /><div><div className="sk" style={{ height: 14, width: 60, marginBottom: 6 }} /><div className="sk" style={{ height: 16, width: 40 }} /></div></div></td>
    <td><div className="sk" style={{ height: 14, width: 60, marginLeft: "auto" }} /></td>
    <td><div className="sk" style={{ height: 14, width: 50, marginLeft: "auto" }} /></td>
    <td><div className="sk" style={{ height: 14, width: 60, marginLeft: "auto" }} /></td>
    <td><div className="sk" style={{ height: 28, width: 28, borderRadius: 6, marginLeft: "auto" }} /></td>
    <td><div className="sk" style={{ height: 20, width: 70, marginLeft: "auto", borderRadius: 4 }} /></td>
    <td><div className="sk" style={{ height: 14, width: 50, marginLeft: "auto" }} /></td>
    <td><div className="sk" style={{ height: 18, width: 70, marginLeft: "auto" }} /></td>
  </tr>
);

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
        fetch('/api/v1/cis/universe').catch(() => null)
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
          if (cisJson.universe) {
            const cisMap = {};
            cisJson.universe.forEach(item => {
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
      <div className="asset-tbl-wrap" style={{
        border: `1px solid ${T.border}`,
        borderRadius: 12,
        overflow: "hidden",
        background: T.surface,
      }}>
        <div className="at-controls" style={{
          display: "flex", alignItems: "center", justifyContent: "space-between",
          padding: "14px 18px", borderBottom: `1px solid ${T.border}`,
          background: "rgba(255,255,255,0.018)",
        }}>
          <div className="section-label" style={{ margin: 0, fontFamily: FONTS.display, fontSize: 11, fontWeight: 700, letterSpacing: "0.18em", color: T.t2, textTransform: "uppercase" }}>Asset Radar</div>
        </div>
        <div style={{ padding: 40, textAlign: "center", color: T.red, fontSize: 12 }}>
          数据加载失败 · {lastUpdate ? `上次更新: ${lastUpdate.toLocaleTimeString()}` : "请刷新"}
        </div>
      </div>
    );
  }

  return (
    <div>
      {/* Table Wrapper */}
      <div className="asset-tbl-wrap" style={{
        border: `1px solid ${T.border}`,
        borderRadius: 12,
        overflow: "hidden",
        background: T.surface,
      }}>
        {/* Controls Header */}
        <div className="at-controls" style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          padding: "14px 18px",
          borderBottom: `1px solid ${T.border}`,
          background: "rgba(255,255,255,0.018)",
        }}>
          <div style={{
            fontFamily: FONTS.display,
            fontSize: 9,
            fontWeight: 700,
            letterSpacing: "0.22em",
            color: T.t3,
            textTransform: "uppercase",
            display: "flex",
            alignItems: "center",
          }}>
            <span style={{ width: 20, height: 1, background: T.t3, marginRight: 10 }} />
            Asset Radar
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            {/* Filter Chips */}
            <div style={{ display: "flex", gap: 5 }}>
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
            <span style={{ fontSize: 9, color: T.t3, marginLeft: 6 }}>
              {ASSETS.length} assets · CoinGecko
            </span>
          </div>
        </div>

        {/* Table */}
        <table className="data-table" style={{ width: "100%", borderCollapse: "collapse" }}>
          <thead>
            <tr>
              <th style={{ width: 240, textAlign: "left", padding: "10px 14px", fontFamily: FONTS.display, fontSize: 11, fontWeight: 700, letterSpacing: "0.15em", color: T.t2, textTransform: "uppercase", borderBottom: `1px solid ${T.border}` }}>Asset</th>
              <th style={{ textAlign: "right", padding: "10px 14px", fontFamily: FONTS.display, fontSize: 11, fontWeight: 700, letterSpacing: "0.15em", color: T.t2, textTransform: "uppercase", borderBottom: `1px solid ${T.border}` }}>Price</th>
              <th style={{ textAlign: "right", padding: "10px 14px", fontFamily: FONTS.display, fontSize: 11, fontWeight: 700, letterSpacing: "0.15em", color: T.t2, textTransform: "uppercase", borderBottom: `1px solid ${T.border}` }}>24H</th>
              <th style={{ textAlign: "right", padding: "10px 14px", fontFamily: FONTS.display, fontSize: 11, fontWeight: 700, letterSpacing: "0.15em", color: T.t2, textTransform: "uppercase", borderBottom: `1px solid ${T.border}` }}>TVL</th>
              <th style={{ textAlign: "right", padding: "10px 14px", fontFamily: FONTS.display, fontSize: 11, fontWeight: 700, letterSpacing: "0.15em", color: T.blue, textTransform: "uppercase", borderBottom: `1px solid ${T.border}` }}>CIS</th>
              <th style={{ textAlign: "right", padding: "10px 14px", fontFamily: FONTS.display, fontSize: 11, fontWeight: 700, letterSpacing: "0.15em", color: T.t2, textTransform: "uppercase", borderBottom: `1px solid ${T.border}` }}>Signal</th>
              <th style={{ textAlign: "right", padding: "10px 14px", fontFamily: FONTS.display, fontSize: 11, fontWeight: 700, letterSpacing: "0.15em", color: T.t2, textTransform: "uppercase", borderBottom: `1px solid ${T.border}` }}>Vol</th>
              <th style={{ textAlign: "right", width: 80, padding: "10px 14px", fontFamily: FONTS.display, fontSize: 11, fontWeight: 700, letterSpacing: "0.15em", color: T.t2, textTransform: "uppercase", borderBottom: `1px solid ${T.border}` }}>7D</th>
            </tr>
          </thead>
          <tbody>
            {loading
              ? Array(8).fill(0).map((_, i) => <SkeletonRow key={i} />)
              : filteredAssets.map(asset => (
                  <AssetRow
                    key={asset.symbol}
                    asset={asset}
                    marketData={marketData[asset.symbol]}
                    cisData={cisData}
                    fngValue={fngValue}
                  />
                ))
            }
          </tbody>
        </table>
      </div>

      {/* Footer */}
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
        <span>Data: <span style={{ color: T.t2 }}>CoinGecko</span> · 60s refresh</span>
        <span style={{ fontFamily: FONTS.serif, fontStyle: "italic", fontSize: 12, color: T.t3 }}>CometCloud Intelligence</span>
      </div>
    </div>
  );
}
