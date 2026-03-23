import { useState, useEffect, useMemo } from "react";
import { T, FONTS } from "../tokens";

/* ─── Asset Universe ────────────────────────────────────────────────── */
// "龙头标准" — top 3 per category by on-chain verifiable data.
// Each category cites its ranking criterion.
//
// ── CATEGORIES (10) ───────────────────────────────────────────────────
// L1 (3):    Top 3 by ecosystem TVL (DeFiLlama aggregate)
// L2 (3):    Top 3 by L2 TVL (DeFiLlama L2 ranking)
// DeFi (3):  Top 3 by protocol TVL (DeFiLlama)
// Infra (3): Top 3 by on-chain integration count / service revenue
// RWA (3):   Top 3 by tokenized asset AUM (RWA.xyz / DeFiLlama)
// Meme (3):  Top 3 by market cap (only verifiable metric for memes)
// Gaming (3): Top 3 by daily active users (DappRadar)
// AI (3):    Top 3 by market cap in AI/DePIN sector
// US Equity (3): Top 3 by market cap (S&P component)
// Commodity (3): Top 3 ETFs by AUM
//
// Total: 30 assets (10 categories × 3)

const ASSETS = [
  // L1 — top 3 by ecosystem TVL (DeFiLlama)
  { id: "bitcoin",    symbol: "BTC",  name: "Bitcoin",    category: "L1",    color: "#F7931A" },
  { id: "ethereum",   symbol: "ETH",  name: "Ethereum",   category: "L1",    color: "#627EEA" },
  { id: "solana",     symbol: "SOL",  name: "Solana",     category: "L1",    color: "#9945FF" },
  // L2 — top 3 by L2 TVL (DeFiLlama)
  { id: "arbitrum",   symbol: "ARB",  name: "Arbitrum",   category: "L2",    color: "#28A0F0" },
  { id: "optimism",   symbol: "OP",   name: "Optimism",   category: "L2",    color: "#FF0420" },
  { id: "polygon-ecosystem-token", symbol: "POL", name: "Polygon", category: "L2", color: "#8247E5" },
  // DeFi — top 3 by protocol TVL (DeFiLlama)
  { id: "lido-dao",   symbol: "LDO",  name: "Lido",       category: "DeFi",  color: "#00A3FF" },
  { id: "aave",       symbol: "AAVE", name: "Aave",       category: "DeFi",  color: "#2EBAC6" },
  { id: "uniswap",    symbol: "UNI",  name: "Uniswap",    category: "DeFi",  color: "#FF007A" },
  // Infra — top 3 by on-chain integration count / service revenue
  { id: "chainlink",  symbol: "LINK", name: "Chainlink",  category: "Infra", color: "#2A5ADA" },
  { id: "celestia",   symbol: "TIA",  name: "Celestia",   category: "Infra", color: "#7B2FBE" },
  { id: "ethena",     symbol: "ENA",  name: "Ethena",     category: "Infra", color: "#8B5CF6" },
  // RWA — top 3 by tokenized asset AUM (RWA.xyz)
  { id: "ondo-finance", symbol: "ONDO", name: "Ondo",     category: "RWA",   color: "#2B65EC" },
  { id: "maker",      symbol: "MKR",  name: "Maker",      category: "RWA",   color: "#1AAB9B", cisKey: "MKR" },
  { id: "polymesh",   symbol: "POLYX", name: "Polymesh",  category: "RWA",   color: "#1348E8", cisKey: "POLYX" },
  // Meme — top 3 by market cap
  { id: "dogecoin",   symbol: "DOGE", name: "Dogecoin",   category: "Meme",  color: "#C2A633" },
  { id: "pepe",       symbol: "PEPE", name: "Pepe",       category: "Meme",  color: "#479F53" },
  { id: "dogwifcoin", symbol: "WIF",  name: "dogwifhat",  category: "Meme",  color: "#C08A53" },
  // Gaming — top 3 by DAU (DappRadar)
  { id: "the-sandbox", symbol: "SAND", name: "Sandbox",   category: "Gaming", color: "#00ADEF" },
  { id: "decentraland", symbol: "MANA", name: "Decentraland", category: "Gaming", color: "#FF2D55" },
  { id: "axie-infinity", symbol: "AXS", name: "Axie",     category: "Gaming", color: "#0055D5" },
  // AI / DePIN — top 3 by market cap in sector
  { id: "near",       symbol: "NEAR", name: "NEAR",       category: "AI",    color: "#00C08B" },
  { id: "internet-computer", symbol: "ICP", name: "ICP",  category: "AI",    color: "#29ABE2", cisKey: "ICP" },
  { id: "virtual-protocol", symbol: "VIRTUAL", name: "Virtuals", category: "AI", color: "#7C3AED", cisKey: "VIRTUAL" },
  // US Equity — top 3 by market cap (S&P mega-cap)
  { id: "spy",        symbol: "SPY",  name: "S&P 500",    category: "TradFi", color: "#4CAF50", cisKey: "SPY" },
  { id: "aapl",       symbol: "AAPL", name: "Apple",      category: "TradFi", color: "#A2AAAD", cisKey: "AAPL" },
  { id: "nvda",       symbol: "NVDA", name: "NVIDIA",     category: "TradFi", color: "#76B900", cisKey: "NVDA" },
  // Commodity — top 3 ETFs by AUM
  { id: "gld",        symbol: "GLD",  name: "Gold",       category: "Commodity", color: "#FFD700", cisKey: "GLD" },
  { id: "slv",        symbol: "SLV",  name: "Silver",     category: "Commodity", color: "#C0C0C0", cisKey: "SLV" },
  { id: "uso",        symbol: "USO",  name: "Oil",        category: "Commodity", color: "#8B4513", cisKey: "USO" },
];

/* ─── Category Styles ─────────────────────────────────────────────── */
const CAT_STYLE = {
  L1:        { bg: "rgba(75,158,255,0.10)",  color: T.blue,    border: "rgba(75,158,255,0.22)" },
  L2:        { bg: "rgba(248,113,113,0.10)", color: "#F87171", border: "rgba(248,113,113,0.22)" },
  DeFi:      { bg: "rgba(0,232,122,0.08)",   color: T.green,   border: "rgba(0,232,122,0.18)" },
  Infra:     { bg: "rgba(245,158,11,0.10)",  color: T.amber,   border: "rgba(245,158,11,0.22)" },
  RWA:       { bg: "rgba(167,139,250,0.13)", color: T.purple,  border: "rgba(167,139,250,0.22)" },
  Meme:      { bg: "rgba(200,168,75,0.10)",  color: T.gold,    border: "rgba(200,168,75,0.22)" },
  Gaming:    { bg: "rgba(0,173,239,0.10)",   color: "#00ADEF", border: "rgba(0,173,239,0.22)" },
  AI:        { bg: "rgba(124,58,237,0.10)",  color: "#A78BFA", border: "rgba(124,58,237,0.22)" },
  TradFi:    { bg: "rgba(76,175,80,0.10)",   color: "#4CAF50", border: "rgba(76,175,80,0.22)" },
  Commodity: { bg: "rgba(255,215,0,0.10)",   color: "#FFD700", border: "rgba(255,215,0,0.22)" },
};
const catStyle = (cat) => CAT_STYLE[cat] || CAT_STYLE.L1;

/* ─── Signal Styles (CIS v4.1 — compliance-safe positioning signals) ── */
const SIG_STYLE = {
  "STRONG OUTPERFORM": { color: T.green, bg: "rgba(0,232,122,0.14)",  border: "rgba(0,232,122,0.3)" },
  OUTPERFORM:          { color: T.green, bg: "rgba(0,232,122,0.09)",  border: "rgba(0,232,122,0.2)" },
  NEUTRAL:             { color: T.gold,  bg: "rgba(200,168,75,0.09)", border: "rgba(200,168,75,0.2)" },
  UNDERPERFORM:        { color: T.red,   bg: "rgba(255,61,90,0.09)",  border: "rgba(255,61,90,0.2)" },
  UNDERWEIGHT:         { color: T.red,   bg: "rgba(255,61,90,0.14)",  border: "rgba(255,61,90,0.3)" },
  // Legacy compat (in case cached data still has old signals)
  "STRONG BUY": { color: T.green, bg: "rgba(0,232,122,0.14)",  border: "rgba(0,232,122,0.3)" },
  BUY:          { color: T.green, bg: "rgba(0,232,122,0.09)",  border: "rgba(0,232,122,0.2)" },
  HOLD:         { color: T.gold,  bg: "rgba(200,168,75,0.09)", border: "rgba(200,168,75,0.2)" },
  REDUCE:       { color: T.red,   bg: "rgba(255,61,90,0.09)",  border: "rgba(255,61,90,0.2)" },
  AVOID:        { color: T.red,   bg: "rgba(255,61,90,0.14)",  border: "rgba(255,61,90,0.3)" },
};
const sigStyle = (sig) => SIG_STYLE[sig] || SIG_STYLE.NEUTRAL;

/* ─── Grade Styles ────────────────────────────────────────────────── */
const GRADE_STYLE = {
  "A+": { bg: "rgba(0,232,122,0.18)", color: T.green,  border: "rgba(0,232,123,0.4)" },
  A:    { bg: "rgba(0,232,122,0.14)", color: T.green,  border: "rgba(0,232,123,0.3)" },
  "B+": { bg: "rgba(75,158,255,0.15)", color: T.blue,  border: "rgba(75,158,255,0.35)" },
  B:    { bg: "rgba(75,158,255,0.11)", color: T.blue,  border: "rgba(75,158,255,0.25)" },
  "C+": { bg: "rgba(245,158,11,0.15)", color: T.amber, border: "rgba(245,158,11,0.35)" },
  C:    { bg: "rgba(245,158,11,0.11)", color: T.amber, border: "rgba(245,158,11,0.22)" },
  D:    { bg: "rgba(255,61,90,0.10)",  color: T.red,   border: "rgba(255,61,90,0.22)" },
  F:    { bg: "rgba(136,136,136,0.10)", color: "#888",  border: "rgba(136,136,136,0.2)" },
};
const gradeStyle = (g) => GRADE_STYLE[g] || { bg: "rgba(255,255,255,0.04)", color: T.t3, border: T.border };

/* ─── Filters (match actual categories) ───────────────────────────── */
const FILTERS = [
  { id: "all",       label: "All" },
  { id: "L1",        label: "L1" },
  { id: "L2",        label: "L2" },
  { id: "DeFi",      label: "DeFi" },
  { id: "Infra",     label: "Infra" },
  { id: "RWA",       label: "RWA" },
  { id: "AI",        label: "AI" },
  { id: "Gaming",    label: "Gaming" },
  { id: "Meme",      label: "Meme" },
  { id: "TradFi",    label: "TradFi" },
  { id: "Commodity", label: "Cmdty" },
];

/* ─── Sort options ────────────────────────────────────────────────── */
const SORT_OPTS = [
  { id: "mcap",  label: "Mkt Cap" },
  { id: "24h",   label: "24H %" },
  { id: "7d",    label: "7D %" },
  { id: "cis",   label: "CIS" },
  { id: "las",   label: "LAS" },
  { id: "vol",   label: "Volume" },
];

/* ─── Sparkline ───────────────────────────────────────────────────── */
const Sparkline = ({ data, positive }) => {
  if (!data || data.length < 2) return null;
  const w = 70, h = 18;
  const min = Math.min(...data), max = Math.max(...data);
  const range = max - min || 1;
  const pts = data.map((v, i) =>
    `${(i / (data.length - 1)) * w},${h - ((v - min) / range) * h}`
  ).join(" ");
  const c = positive ? T.green : T.red;
  return (
    <svg width={w} height={h} style={{ display: "block" }}>
      <polyline points={pts} fill="none" stroke={c} strokeWidth="1.4"
        strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
};

/* ─── Format Helpers ──────────────────────────────────────────────── */
const fmtPrice = (p) => {
  if (!p) return "—";
  if (p >= 1000)  return "$" + p.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  if (p >= 1)     return "$" + p.toFixed(2);
  if (p >= 0.001) return "$" + p.toFixed(4);
  return "$" + p.toFixed(6);
};
const fmtPct = (v) => v == null ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(1)}%`;
const fmtVol = (v) => {
  if (!v) return "—";
  if (v >= 1e12) return `$${(v / 1e12).toFixed(1)}T`;
  if (v >= 1e9)  return `$${(v / 1e9).toFixed(1)}B`;
  if (v >= 1e6)  return `$${(v / 1e6).toFixed(1)}M`;
  return `$${(v / 1e3).toFixed(0)}K`;
};

/* ─── TH style (shared) ───────────────────────────────────────────── */
const thBase = {
  padding: "10px 14px",
  fontFamily: FONTS.display,
  fontSize: 11,
  fontWeight: 700,
  letterSpacing: "0.14em",
  color: T.t2,
  textTransform: "uppercase",
  borderBottom: `1px solid ${T.border}`,
  whiteSpace: "nowrap",
};

/* ─── Skeleton Row ────────────────────────────────────────────────── */
const SkeletonRow = () => (
  <tr>
    {[240, 80, 60, 80, 100, 90, 40, 70, 80, 70].map((w, i) => (
      <td key={i} style={{ padding: "10px 14px" }}>
        <div className="sk" style={{ height: 14, width: w === 240 ? 120 : w * 0.6, borderRadius: 4, marginLeft: i > 0 ? "auto" : 0 }} />
      </td>
    ))}
  </tr>
);

/* ═══════════════════════════════════════════════════════════════════
   MAIN COMPONENT
   ═══════════════════════════════════════════════════════════════════ */
export default function AssetRadar({ fngValue = 50, refreshTrigger = 0 }) {
  const [loading, setLoading]         = useState(true);
  const [marketData, setMarketData]   = useState({});      // keyed by symbol
  const [cisData, setCisData]         = useState({});       // keyed by symbol (cisKey where applicable)
  const [cisLoading, setCisLoading]   = useState(true);
  const [error, setError]             = useState(null);
  const [lastUpdate, setLastUpdate]   = useState(null);
  const [activeFilter, setActiveFilter] = useState("all");
  const [sortBy, setSortBy]           = useState("mcap");
  const [sortDir, setSortDir]         = useState(-1);       // -1 = desc

  /* ── Fetch CoinGecko market data (crypto only) ────────────────── */
  const NON_CG_CATS = new Set(["TradFi", "Commodity"]);
  const fetchMarkets = async () => {
    const cryptoAssets = ASSETS.filter(a => !NON_CG_CATS.has(a.category));
    const ids = cryptoAssets.map(a => a.id).join(",");
    const res = await fetch(`/api/v1/market/coingecko-markets?ids=${encodeURIComponent(ids)}`);
    if (!res.ok) throw new Error(`Markets API ${res.status}`);
    const json = await res.json();
    const map = {};
    (json.data || []).forEach(coin => {
      const asset = ASSETS.find(a => a.id === coin.id);
      if (asset) map[asset.symbol] = coin;
    });
    return map;
  };

  /* ── Fetch CIS universe (includes TradFi/Commodity price data) ─ */
  const fetchCIS = async () => {
    const res = await fetch("/api/v1/cis/universe");
    if (!res.ok) throw new Error(`CIS API ${res.status}`);
    const json = await res.json();
    const cisMap = {};
    const tradfiMap = {};  // Also extract market data for non-CG assets
    (json.universe || []).forEach(item => {
      cisMap[item.symbol] = {
        score:      item.cis_score ?? item.score ?? 0,
        grade:      item.grade || "—",
        signal:     item.signal || "NEUTRAL",
        percentile: item.percentile_rank ?? 0,
        dataTier:   item.data_tier ?? 2,
        las:        item.las ?? null,
        confidence: item.confidence ?? null,
      };
      // For TradFi/Commodity: CIS universe has price/market_cap/volume
      if (item.price) {
        tradfiMap[item.symbol] = {
          current_price: item.price,
          market_cap: item.market_cap || 0,
          total_volume: item.volume_24h || 0,
          price_change_percentage_24h: item.change_24h || 0,
          price_change_percentage_7d_in_currency: item.change_7d || 0,
        };
      }
    });
    return { cisMap, tradfiMap };
  };

  /* ── Load both concurrently, resolve independently ────────────── */
  const loadData = async () => {
    setError(null);
    const marketsP = fetchMarkets();
    const cisP     = fetchCIS();

    let mktMap = {};
    try {
      mktMap = await marketsP;
    } catch (e) {
      console.error("Markets fetch error:", e);
      setError(e.message);
    }

    try {
      const { cisMap, tradfiMap } = await cisP;
      setCisData(cisMap);
      // Merge TradFi/Commodity market data from CIS universe
      const merged = { ...mktMap };
      for (const [sym, data] of Object.entries(tradfiMap)) {
        if (!merged[sym]) merged[sym] = data;
      }
      setMarketData(merged);
      setLastUpdate(new Date());
    } catch (e) {
      console.warn("CIS fetch error:", e.message);
      setMarketData(mktMap);
      setLastUpdate(new Date());
    } finally {
      setLoading(false);
      setCisLoading(false);
    }
  };

  // Single useEffect — initial load + interval + refreshTrigger
  useEffect(() => {
    setLoading(true);
    setCisLoading(true);
    loadData();
    const iv = setInterval(loadData, 60_000);
    return () => clearInterval(iv);
  }, [refreshTrigger]);

  /* ── Merge & derive display data ──────────────────────────────── */
  const rows = useMemo(() => {
    return ASSETS.map(asset => {
      const cisKey = asset.cisKey || asset.symbol;
      const mkt    = marketData[asset.symbol] || {};
      const cis    = cisData[cisKey] || null;
      const ch24   = mkt.price_change_percentage_24h ?? null;
      const ch7d   = mkt.price_change_percentage_7d_in_currency ?? null;
      return { asset, mkt, cis, ch24, ch7d };
    });
  }, [marketData, cisData]);

  /* ── Filter ───────────────────────────────────────────────────── */
  const filtered = useMemo(() => {
    let list = activeFilter === "all"
      ? rows
      : rows.filter(r => r.asset.category === activeFilter);

    // Sort
    list = [...list].sort((a, b) => {
      let va = 0, vb = 0;
      switch (sortBy) {
        case "mcap": va = a.mkt.market_cap || 0; vb = b.mkt.market_cap || 0; break;
        case "24h":  va = a.ch24 || 0;           vb = b.ch24 || 0; break;
        case "7d":   va = a.ch7d || 0;           vb = b.ch7d || 0; break;
        case "cis":  va = a.cis?.score || 0;     vb = b.cis?.score || 0; break;
        case "las":  va = a.cis?.las || 0;       vb = b.cis?.las || 0; break;
        case "vol":  va = a.mkt.total_volume || 0; vb = b.mkt.total_volume || 0; break;
        default: break;
      }
      return (va - vb) * sortDir;
    });

    return list;
  }, [rows, activeFilter, sortBy, sortDir]);

  /* ── Toggle sort ──────────────────────────────────────────────── */
  const toggleSort = (id) => {
    if (sortBy === id) setSortDir(d => d * -1);
    else { setSortBy(id); setSortDir(-1); }
  };

  /* ── Error state ──────────────────────────────────────────────── */
  if (error && Object.keys(marketData).length === 0) {
    return (
      <div style={{ border: `1px solid ${T.border}`, borderRadius: 12, overflow: "hidden", background: T.surface }}>
        <Header count={ASSETS.length} />
        <div style={{ padding: 40, textAlign: "center", color: T.red, fontFamily: FONTS.mono, fontSize: 11 }}>
          Data unavailable · {lastUpdate ? `Last: ${lastUpdate.toLocaleTimeString()}` : "Refresh to retry"}
        </div>
      </div>
    );
  }

  return (
    <div>
      <div style={{ border: `1px solid ${T.border}`, borderRadius: 12, overflow: "hidden", background: T.surface }}>

        {/* ── Controls ──────────────────────────────────────────── */}
        <div style={{
          display: "flex", alignItems: "center", justifyContent: "space-between",
          padding: "12px 18px", borderBottom: `1px solid ${T.border}`,
          background: "rgba(255,255,255,0.018)", flexWrap: "wrap", gap: 10,
        }}>
          {/* Title */}
          <div style={{
            fontFamily: FONTS.display, fontSize: 13, fontWeight: 700,
            letterSpacing: "0.12em", color: T.t1, textTransform: "uppercase",
            display: "flex", alignItems: "center",
          }}>
            <span style={{ width: 16, height: 1, background: T.gold, marginRight: 10, opacity: 0.5 }} />
            Asset Radar
            <span style={{
              fontFamily: FONTS.mono, fontSize: 9, fontWeight: 500,
              color: T.t3, marginLeft: 10, letterSpacing: "0.06em",
            }}>
              {ASSETS.length} assets
            </span>
          </div>

          <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
            {/* Category filters */}
            <div style={{ display: "flex", gap: 4 }}>
              {FILTERS.map(f => (
                <button key={f.id} onClick={() => setActiveFilter(f.id)} style={{
                  fontFamily: FONTS.display, fontSize: 10, fontWeight: 600,
                  letterSpacing: "0.06em", padding: "4px 10px", borderRadius: 5,
                  border: `1px solid ${activeFilter === f.id ? "rgba(200,168,75,0.28)" : T.border}`,
                  color: activeFilter === f.id ? T.gold : T.t3,
                  background: activeFilter === f.id ? T.goldDim : "transparent",
                  cursor: "pointer", transition: "all 0.15s", textTransform: "uppercase",
                }}>
                  {f.label}
                </button>
              ))}
            </div>

            {/* Sort selector */}
            <div style={{ display: "flex", gap: 3, alignItems: "center" }}>
              <span style={{ fontFamily: FONTS.mono, fontSize: 8, color: T.t3, letterSpacing: "0.1em", marginRight: 4 }}>SORT</span>
              {SORT_OPTS.map(s => (
                <button key={s.id} onClick={() => toggleSort(s.id)} style={{
                  fontFamily: FONTS.mono, fontSize: 9, fontWeight: 500,
                  padding: "3px 8px", borderRadius: 4,
                  border: `1px solid ${sortBy === s.id ? "rgba(75,158,255,0.25)" : T.border}`,
                  color: sortBy === s.id ? T.blue : T.t3,
                  background: sortBy === s.id ? "rgba(75,158,255,0.06)" : "transparent",
                  cursor: "pointer", transition: "all 0.15s",
                }}>
                  {s.label}{sortBy === s.id ? (sortDir === -1 ? " ↓" : " ↑") : ""}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* ── Table ─────────────────────────────────────────────── */}
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", minWidth: 900 }}>
            <thead>
              <tr>
                <th style={{ ...thBase, textAlign: "left", width: 220 }}>Asset</th>
                <th style={{ ...thBase, textAlign: "right" }}>Price</th>
                <th style={{ ...thBase, textAlign: "right", cursor: "pointer" }} onClick={() => toggleSort("24h")}>24H</th>
                <th style={{ ...thBase, textAlign: "right", cursor: "pointer" }} onClick={() => toggleSort("7d")}>7D</th>
                <th style={{ ...thBase, textAlign: "right", cursor: "pointer" }} onClick={() => toggleSort("mcap")}>Mkt Cap</th>
                <th style={{ ...thBase, textAlign: "right", cursor: "pointer", color: T.blue }} onClick={() => toggleSort("cis")}>CIS</th>
                <th style={{ ...thBase, textAlign: "right", cursor: "pointer" }} onClick={() => toggleSort("las")}>LAS</th>
                <th style={{ ...thBase, textAlign: "center" }}>Signal</th>
                <th style={{ ...thBase, textAlign: "right", cursor: "pointer" }} onClick={() => toggleSort("vol")}>Volume</th>
                <th style={{ ...thBase, textAlign: "right", width: 80 }}>Trend</th>
              </tr>
            </thead>
            <tbody>
              {loading
                ? Array(8).fill(0).map((_, i) => <SkeletonRow key={i} />)
                : filtered.map(({ asset, mkt, cis, ch24, ch7d }) => {
                    const cs = catStyle(asset.category);
                    const signal = cis?.signal || "NEUTRAL";
                    const ss = sigStyle(signal);
                    const gs = cis ? gradeStyle(cis.grade) : null;

                    return (
                      <tr key={asset.symbol}
                        style={{ transition: "background 0.14s", cursor: "pointer" }}
                        onMouseEnter={(e) => e.currentTarget.style.background = "rgba(255,255,255,0.02)"}
                        onMouseLeave={(e) => e.currentTarget.style.background = "transparent"}
                      >
                        {/* Asset */}
                        <td style={{ padding: "9px 14px" }}>
                          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                            <div style={{
                              width: 32, height: 32, borderRadius: 8,
                              background: `${asset.color}22`, color: asset.color,
                              display: "flex", alignItems: "center", justifyContent: "center",
                              fontFamily: FONTS.display, fontSize: 10, fontWeight: 800,
                              flexShrink: 0,
                            }}>
                              {asset.symbol.slice(0, 3)}
                            </div>
                            <div>
                              <div style={{
                                fontFamily: FONTS.display, fontSize: 12, fontWeight: 600, color: T.t1,
                                display: "flex", alignItems: "center", gap: 6,
                              }}>
                                {asset.name}
                                <span style={{ fontFamily: FONTS.mono, fontSize: 10, color: T.t3, fontWeight: 400 }}>
                                  {asset.symbol}
                                </span>
                              </div>
                              <span style={{
                                fontFamily: FONTS.display, fontSize: 8, fontWeight: 700,
                                letterSpacing: "0.1em", padding: "1px 5px", borderRadius: 3,
                                background: cs.bg, color: cs.color, border: `1px solid ${cs.border}`,
                                textTransform: "uppercase",
                              }}>
                                {asset.category}
                              </span>
                            </div>
                          </div>
                        </td>

                        {/* Price */}
                        <td style={{ textAlign: "right", padding: "9px 14px" }}>
                          <div style={{ fontFamily: FONTS.mono, fontSize: 13, fontWeight: 500, color: T.t1 }}>
                            {fmtPrice(mkt.current_price)}
                          </div>
                        </td>

                        {/* 24H */}
                        <td style={{ textAlign: "right", padding: "9px 14px" }}>
                          <span style={{
                            fontFamily: FONTS.mono, fontSize: 12, fontWeight: 500,
                            color: ch24 > 0 ? T.green : ch24 < 0 ? T.red : T.t3,
                          }}>
                            {fmtPct(ch24)}
                          </span>
                        </td>

                        {/* 7D */}
                        <td style={{ textAlign: "right", padding: "9px 14px" }}>
                          <span style={{
                            fontFamily: FONTS.mono, fontSize: 12, fontWeight: 500,
                            color: ch7d > 0 ? T.green : ch7d < 0 ? T.red : T.t3,
                          }}>
                            {fmtPct(ch7d)}
                          </span>
                        </td>

                        {/* Mkt Cap */}
                        <td style={{ textAlign: "right", padding: "9px 14px" }}>
                          <span style={{ fontFamily: FONTS.mono, fontSize: 12, color: T.t2 }}>
                            {fmtVol(mkt.market_cap)}
                          </span>
                        </td>

                        {/* CIS (grade + score + tier badge) */}
                        <td style={{ textAlign: "right", padding: "9px 14px" }}>
                          {cis ? (
                            <div style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
                              {/* Confidence dot: green ≥0.7, amber 0.5-0.7, red <0.5 */}
                              {cis.confidence != null && (
                                <span title={`Confidence: ${(cis.confidence * 100).toFixed(0)}%`} style={{
                                  width: 5, height: 5, borderRadius: "50%", flexShrink: 0,
                                  background: cis.confidence >= 0.7 ? T.green : cis.confidence >= 0.5 ? T.amber : T.red,
                                  opacity: 0.7,
                                }} />
                              )}
                              <span style={{ fontFamily: FONTS.mono, fontSize: 11, color: T.t2 }}>
                                {cis.confidence != null && cis.confidence < 0.5 ? "~" : ""}{cis.score.toFixed(1)}
                              </span>
                              <span style={{
                                display: "inline-flex", alignItems: "center", justifyContent: "center",
                                width: 28, height: 22, borderRadius: 5,
                                background: gs.bg, color: gs.color, border: `1px solid ${gs.border}`,
                                fontFamily: FONTS.display, fontSize: 10, fontWeight: 800,
                              }}>
                                {cis.grade}
                              </span>
                              {/* T1/T2 tier badge */}
                              <span style={{
                                fontFamily: FONTS.mono, fontSize: 7, fontWeight: 600, letterSpacing: "0.05em",
                                padding: "1px 4px", borderRadius: 3,
                                color: cis.dataTier === 1 ? T.green : T.amber,
                                background: cis.dataTier === 1 ? "rgba(0,232,122,0.08)" : "rgba(245,158,11,0.08)",
                                border: `1px solid ${cis.dataTier === 1 ? "rgba(0,232,122,0.2)" : "rgba(245,158,11,0.2)"}`,
                              }}>
                                T{cis.dataTier || 2}
                              </span>
                            </div>
                          ) : cisLoading ? (
                            <div className="sk" style={{ width: 55, height: 22, borderRadius: 5, display: "inline-block" }} />
                          ) : (
                            <span style={{ fontFamily: FONTS.mono, fontSize: 11, color: T.t3 }}>—</span>
                          )}
                        </td>

                        {/* LAS (Liquidity-Adjusted Score) */}
                        <td style={{ textAlign: "right", padding: "9px 14px" }}>
                          {cis?.las != null ? (
                            <span style={{
                              fontFamily: FONTS.mono, fontSize: 11, fontWeight: 500,
                              color: cis.las >= 60 ? T.green : cis.las >= 40 ? T.t2 : T.red,
                            }}>
                              {cis.las.toFixed(1)}
                            </span>
                          ) : cisLoading ? (
                            <div className="sk" style={{ width: 35, height: 14, borderRadius: 4, display: "inline-block" }} />
                          ) : (
                            <span style={{ fontFamily: FONTS.mono, fontSize: 11, color: T.t3 }}>—</span>
                          )}
                        </td>

                        {/* Signal (from CIS, not calculated) */}
                        <td style={{ textAlign: "center", padding: "9px 14px" }}>
                          {cis ? (
                            <span style={{
                              fontFamily: FONTS.display, fontSize: 9, fontWeight: 700,
                              letterSpacing: "0.06em", padding: "3px 9px", borderRadius: 4,
                              background: ss.bg, color: ss.color, border: `1px solid ${ss.border}`,
                              textTransform: "uppercase", whiteSpace: "nowrap",
                            }}>
                              {signal}
                            </span>
                          ) : cisLoading ? (
                            <div className="sk" style={{ width: 56, height: 20, borderRadius: 4, display: "inline-block" }} />
                          ) : (
                            <span style={{ fontFamily: FONTS.mono, fontSize: 10, color: T.t3 }}>—</span>
                          )}
                        </td>

                        {/* Volume */}
                        <td style={{ textAlign: "right", padding: "9px 14px" }}>
                          <span style={{ fontFamily: FONTS.mono, fontSize: 12, color: T.t2 }}>
                            {fmtVol(mkt.total_volume)}
                          </span>
                        </td>

                        {/* 7D Sparkline */}
                        <td style={{ textAlign: "right", padding: "9px 14px", width: 80 }}>
                          <Sparkline data={mkt.sparkline_in_7d?.price} positive={(ch7d || 0) >= 0} />
                        </td>
                      </tr>
                    );
                  })
              }
            </tbody>
          </table>
        </div>
      </div>

      {/* ── Footer ──────────────────────────────────────────────── */}
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        marginTop: 16, paddingTop: 12, borderTop: `1px solid ${T.border}`,
        fontFamily: FONTS.mono, fontSize: 9, color: T.t3, letterSpacing: "0.06em",
      }}>
        <span>
          Data: <span style={{ color: T.t2 }}>CoinGecko Pro</span>
          {" · "}Signals: <span style={{ color: T.blue }}>CIS v4.1</span>
          {" · "}60s refresh
          {" · "}<span style={{ color: T.amber }}>T2</span> Market Est.
        </span>
        {lastUpdate && (
          <span>Updated {lastUpdate.toLocaleTimeString()}</span>
        )}
      </div>
    </div>
  );
}

/* ─── Header (extracted for error state) ──────────────────────────── */
function Header({ count }) {
  return (
    <div style={{
      display: "flex", alignItems: "center", justifyContent: "space-between",
      padding: "12px 18px", borderBottom: `1px solid ${T.border}`,
      background: "rgba(255,255,255,0.018)",
    }}>
      <div style={{
        fontFamily: FONTS.display, fontSize: 13, fontWeight: 700,
        letterSpacing: "0.12em", color: T.t1, textTransform: "uppercase",
        display: "flex", alignItems: "center",
      }}>
        <span style={{ width: 16, height: 1, background: T.gold, marginRight: 10, opacity: 0.5 }} />
        Asset Radar
        <span style={{ fontFamily: FONTS.mono, fontSize: 9, fontWeight: 500, color: T.t3, marginLeft: 10 }}>
          {count} assets
        </span>
      </div>
    </div>
  );
}
