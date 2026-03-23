import { useState, useEffect, useMemo } from "react";
import { T, FONTS } from "../tokens";

/* ─── Asset Universe ────────────────────────────────────────────────── */
// id: CoinGecko coin ID
// symbol: ticker shown in UI + used to join CIS data
// cisKey: override when CIS backend uses a different key (e.g. MNT→MANTLE)
const ASSETS = [
  // L1
  { id: "bitcoin",            symbol: "BTC",   name: "Bitcoin",    category: "L1",   color: "#F7931A" },
  { id: "ethereum",           symbol: "ETH",   name: "Ethereum",   category: "L1",   color: "#627EEA" },
  { id: "solana",             symbol: "SOL",   name: "Solana",     category: "L1",   color: "#9945FF" },
  { id: "binancecoin",        symbol: "BNB",   name: "BNB",        category: "L1",   color: "#F3BA2F" },
  { id: "cardano",            symbol: "ADA",   name: "Cardano",    category: "L1",   color: "#0033AD" },
  { id: "ripple",             symbol: "XRP",   name: "XRP",        category: "L1",   color: "#23292F" },
  { id: "dogecoin",           symbol: "DOGE",  name: "Dogecoin",   category: "Meme", color: "#C2A633" },
  { id: "the-open-network",   symbol: "TON",   name: "Toncoin",    category: "L1",   color: "#0098EA" },
  { id: "avalanche-2",        symbol: "AVAX",  name: "Avalanche",  category: "L1",   color: "#E84142" },
  { id: "polkadot",           symbol: "DOT",   name: "Polkadot",   category: "L1",   color: "#E6007A" },
  { id: "sui",                symbol: "SUI",   name: "Sui",        category: "L1",   color: "#6FBCF0" },
  { id: "aptos",              symbol: "APT",   name: "Aptos",      category: "L1",   color: "#2DD8A3" },
  { id: "near",               symbol: "NEAR",  name: "NEAR",       category: "L1",   color: "#00C1DE" },
  { id: "injective-protocol", symbol: "INJ",   name: "Injective",  category: "L1",   color: "#00F2FE" },
  // L2
  { id: "arbitrum",           symbol: "ARB",   name: "Arbitrum",   category: "L2",   color: "#28A0F0" },
  { id: "optimism",           symbol: "OP",    name: "Optimism",   category: "L2",   color: "#FF0420" },
  { id: "polygon-ecosystem-token", symbol: "POL", name: "Polygon (POL)", category: "L2", color: "#8247E5" },
  { id: "mantle",             symbol: "MNT",   cisKey: "MANTLE",   name: "Mantle",   category: "L2",   color: "#00A8E0" },
  // DeFi
  { id: "uniswap",                    symbol: "UNI",   name: "Uniswap",    category: "DeFi", color: "#FF007A" },
  { id: "aave",                       symbol: "AAVE",  name: "Aave",       category: "DeFi", color: "#2EBAC6" },
  { id: "maker",                      symbol: "MKR",   name: "Maker",      category: "DeFi", color: "#1AAB9B" },
  { id: "havven",                     symbol: "SNX",   name: "Synthetix",  category: "DeFi", color: "#00D1FF" },
  { id: "curve-dao-token",            symbol: "CRV",   name: "Curve",      category: "DeFi", color: "#FF6B6B" },
  { id: "lido-dao",                   symbol: "LDO",   name: "Lido",       category: "DeFi", color: "#00A3FF" },
  { id: "compound-governance-token",  symbol: "COMP",  name: "Compound",   category: "DeFi", color: "#00D395" },
  { id: "sushi",                      symbol: "SUSHI", name: "SushiSwap",  category: "DeFi", color: "#FA52A0" },
  // Infra
  { id: "chainlink", symbol: "LINK", name: "Chainlink", category: "Infra", color: "#2A5ADA" },
  { id: "blockstack", symbol: "STX",  name: "Stacks",    category: "Infra", color: "#5546D6" },
  { id: "thorchain", symbol: "RUNE", name: "THORChain", category: "Infra", color: "#2ECC71" },
  { id: "filecoin",  symbol: "FIL",  name: "Filecoin",  category: "Infra", color: "#0090FF" },
  { id: "celestia",  symbol: "TIA",  name: "Celestia",  category: "Infra", color: "#7B2FBE" },
  // RWA
  { id: "ondo-finance", symbol: "ONDO",  name: "Ondo",      category: "RWA", color: "#2B65EC" },
  { id: "polymesh",     symbol: "POLYX", name: "Polymesh",  category: "RWA", color: "#E6007A" },
  // Meme
  { id: "pepe",       symbol: "PEPE", name: "Pepe", category: "Meme", color: "#00FF00" },
  { id: "dogwifcoin", symbol: "WIF",  name: "WIF",  category: "Meme", color: "#9945FF" },
];

/* ─── Category Styles ─────────────────────────────────────────────── */
const CAT_STYLE = {
  L1:    { bg: "rgba(75,158,255,0.10)",  color: T.blue,   border: "rgba(75,158,255,0.22)" },
  L2:    { bg: "rgba(248,113,113,0.10)", color: "#F87171", border: "rgba(248,113,113,0.22)" },
  DeFi:  { bg: "rgba(0,232,122,0.08)",   color: T.green,  border: "rgba(0,232,122,0.18)" },
  Infra: { bg: "rgba(245,158,11,0.10)",  color: T.amber,  border: "rgba(245,158,11,0.22)" },
  RWA:   { bg: "rgba(167,139,250,0.13)", color: T.purple, border: "rgba(167,139,250,0.22)" },
  Meme:  { bg: "rgba(200,168,75,0.10)",  color: T.gold,   border: "rgba(200,168,75,0.22)" },
};
const catStyle = (cat) => CAT_STYLE[cat] || CAT_STYLE.L1;

/* ─── Signal Styles (CIS signals) ─────────────────────────────────── */
const SIG_STYLE = {
  "STRONG BUY": { color: T.green, bg: "rgba(0,232,122,0.14)",  border: "rgba(0,232,122,0.3)" },
  BUY:          { color: T.green, bg: "rgba(0,232,122,0.09)",  border: "rgba(0,232,122,0.2)" },
  ACCUMULATE:   { color: T.green, bg: "rgba(0,232,122,0.09)",  border: "rgba(0,232,122,0.2)" },
  HOLD:         { color: T.gold,  bg: "rgba(200,168,75,0.09)", border: "rgba(200,168,75,0.2)" },
  REDUCE:       { color: T.red,   bg: "rgba(255,61,90,0.09)",  border: "rgba(255,61,90,0.2)" },
  AVOID:        { color: T.red,   bg: "rgba(255,61,90,0.14)",  border: "rgba(255,61,90,0.3)" },
};
const sigStyle = (sig) => SIG_STYLE[sig] || SIG_STYLE.HOLD;

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
  { id: "all",   label: "All" },
  { id: "L1",    label: "L1" },
  { id: "L2",    label: "L2" },
  { id: "DeFi",  label: "DeFi" },
  { id: "Infra", label: "Infra" },
  { id: "RWA",   label: "RWA" },
  { id: "Meme",  label: "Meme" },
];

/* ─── Sort options ────────────────────────────────────────────────── */
const SORT_OPTS = [
  { id: "mcap",  label: "Mkt Cap" },
  { id: "24h",   label: "24H %" },
  { id: "7d",    label: "7D %" },
  { id: "cis",   label: "CIS" },
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
    {[240, 80, 60, 80, 100, 80, 70, 80].map((w, i) => (
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

  /* ── Fetch CoinGecko market data via backend proxy ────────────── */
  const fetchMarkets = async () => {
    const ids = ASSETS.map(a => a.id).join(",");
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

  /* ── Fetch CIS universe ───────────────────────────────────────── */
  const fetchCIS = async () => {
    const res = await fetch("/api/v1/cis/universe");
    if (!res.ok) throw new Error(`CIS API ${res.status}`);
    const json = await res.json();
    const map = {};
    (json.universe || []).forEach(item => {
      map[item.symbol] = {
        score:      item.cis_score ?? item.score ?? 0,
        grade:      item.grade || "—",
        signal:     item.signal || "HOLD",
        percentile: item.percentile_rank ?? 0,
      };
    });
    return map;
  };

  /* ── Load both concurrently, resolve independently ────────────── */
  const loadData = async () => {
    setError(null);
    const marketsP = fetchMarkets();
    const cisP     = fetchCIS();

    try {
      const m = await marketsP;
      setMarketData(m);
      setLastUpdate(new Date());
    } catch (e) {
      console.error("Markets fetch error:", e);
      setError(e.message);
    } finally {
      setLoading(false);
    }

    try {
      const c = await cisP;
      setCisData(c);
    } catch (e) {
      console.warn("CIS fetch error:", e.message);
    } finally {
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
                    const signal = cis?.signal || "HOLD";
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

                        {/* CIS (grade + score) */}
                        <td style={{ textAlign: "right", padding: "9px 14px" }}>
                          {cis ? (
                            <div style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                              <span style={{ fontFamily: FONTS.mono, fontSize: 11, color: T.t2 }}>
                                {cis.score.toFixed(1)}
                              </span>
                              <span style={{
                                display: "inline-flex", alignItems: "center", justifyContent: "center",
                                width: 28, height: 22, borderRadius: 5,
                                background: gs.bg, color: gs.color, border: `1px solid ${gs.border}`,
                                fontFamily: FONTS.display, fontSize: 10, fontWeight: 800,
                              }}>
                                {cis.grade}
                              </span>
                            </div>
                          ) : cisLoading ? (
                            <div className="sk" style={{ width: 55, height: 22, borderRadius: 5, display: "inline-block" }} />
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
          {" · "}Signals: <span style={{ color: T.blue }}>CIS v4.0</span>
          {" · "}60s refresh
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
