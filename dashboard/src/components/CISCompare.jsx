/**
 * CISCompare — Side-by-side CIS pillar comparison for 2–6 assets
 *
 * Surfaces relative value: who wins on Fundamental vs Momentum vs Alpha?
 * Designed for portfolio managers doing pair trades or sector rotation decisions.
 *
 * Features:
 *   - Asset selector (search from CIS universe, up to 6 positions)
 *   - Pillar radar: each pillar shown as a horizontal bar with universe avg line
 *   - Winner badge per pillar (highest score in comparison set)
 *   - Grade + signal summary header per asset
 *   - Regime-aware context blurb (which pillars matter in current regime)
 *   - Export as tab-separated table (copy to Excel)
 */

import { useState, useEffect, useCallback, useMemo } from "react";
import { T, FONTS } from "../tokens";

const API_BASE = "/api/v1";

// ── Design constants ───────────────────────────────────────────────────────────
const PILLAR_META = [
  { key: "F", label: "Fundamental",   desc: "Revenue, TVL, adoption, fee generation" },
  { key: "M", label: "Momentum",      desc: "Price trend across 24h / 7d / 30d timeframes" },
  { key: "O", label: "On-Chain Risk", desc: "Liquidity depth, volatility regime, spread" },
  { key: "S", label: "Sentiment",     desc: "Volume surge, momentum structure, F&G composite" },
  { key: "A", label: "Alpha",         desc: "Return vs BTC/SPY benchmark, independence" },
];

const PILLAR_COLORS = {
  F: "#4472FF",
  M: "#00D98A",
  O: "#9945FF",
  S: "#F59E0B",
  A: "#EC4899",
};

const GRADE_COLOR = (g) => {
  if (!g || g === "—") return T.muted;
  if (g === "A+" || g === "A") return "#00D98A";
  if (g === "B+" || g === "B") return "#7FFFB2";
  if (g === "C+" || g === "C") return T.gold;
  if (g === "D") return T.amber;
  return T.red;
};

const SIG_COLOR = {
  "STRONG OUTPERFORM": "#00D98A",
  "OUTPERFORM":        "#4472FF",
  "NEUTRAL":           T.muted,
  "UNDERPERFORM":      T.amber,
  "UNDERWEIGHT":       T.red,
};

const REGIME_PILLAR_WEIGHTS = {
  RISK_ON:     { F: 1, M: 3, O: 1, S: 2, A: 3 },
  RISK_OFF:    { F: 3, M: 1, O: 3, S: 1, A: 2 },
  TIGHTENING:  { F: 3, M: 2, O: 2, S: 1, A: 2 },
  EASING:      { F: 2, M: 3, O: 1, S: 2, A: 2 },
  STAGFLATION: { F: 2, M: 1, O: 3, S: 2, A: 2 },
  GOLDILOCKS:  { F: 2, M: 2, O: 1, S: 2, A: 3 },
  UNKNOWN:     { F: 2, M: 2, O: 2, S: 2, A: 2 },
};

const REGIME_LABEL = {
  RISK_ON:     { text: "Risk On",     color: "#00D98A" },
  RISK_OFF:    { text: "Risk Off",    color: "#FF3D5A" },
  TIGHTENING:  { text: "Tightening", color: T.amber   },
  EASING:      { text: "Easing",     color: "#4472FF" },
  STAGFLATION: { text: "Stagflation",color: "#FF6B35" },
  GOLDILOCKS:  { text: "Goldilocks", color: T.gold    },
  UNKNOWN:     { text: "Unknown",    color: T.muted   },
};

const fmtScore = (v) => (v == null ? "—" : v.toFixed(1));
const fmtPct   = (v) => (v == null ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`);
const fmtPrice = (p) => {
  if (!p) return "—";
  if (p >= 1000) return `$${p.toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
  if (p >= 1)    return `$${p.toFixed(2)}`;
  return `$${p.toFixed(4)}`;
};

function PillarBar({ value, avg, color, winner }) {
  const pct    = Math.min(100, Math.max(0, value ?? 0));
  const avgPct = avg != null ? Math.min(100, Math.max(0, avg)) : null;

  return (
    <div style={{ position: "relative", height: 6, background: "rgba(255,255,255,0.06)", borderRadius: 3, overflow: "visible" }}>
      {/* Fill */}
      <div style={{
        position: "absolute", left: 0, top: 0, height: "100%",
        width: `${pct}%`,
        background: value == null
          ? "rgba(255,255,255,0.08)"
          : winner
            ? `linear-gradient(90deg, ${color}, ${color}dd)`
            : color,
        borderRadius: 3,
        opacity: value == null ? 0.3 : 1,
        transition: "width 0.5s cubic-bezier(.16,1,.3,1)",
        boxShadow: winner ? `0 0 8px ${color}66` : "none",
      }} />
      {/* Universe avg tick */}
      {avgPct != null && (
        <div style={{
          position: "absolute",
          left: `${avgPct}%`,
          top: -3,
          width: 2,
          height: 12,
          background: "rgba(255,255,255,0.35)",
          borderRadius: 1,
          transform: "translateX(-50%)",
        }} />
      )}
    </div>
  );
}

function AssetCard({ asset, pillarAvg, winners, regimeWeights, isFirst, onRemove }) {
  const regimeScore = useMemo(() => {
    if (!asset?.pillars) return null;
    let total = 0, wTotal = 0;
    for (const { key } of PILLAR_META) {
      const w = regimeWeights[key] || 1;
      const v = asset.pillars[key];
      if (v != null) { total += v * w; wTotal += w; }
    }
    return wTotal > 0 ? (total / wTotal).toFixed(1) : null;
  }, [asset, regimeWeights]);

  if (!asset) return null;

  return (
    <div style={{
      flex: "1 1 180px",
      minWidth: 160,
      background: T.surface,
      border: `1px solid ${T.borderMd}`,
      borderRadius: 10,
      padding: "16px 14px 14px",
      position: "relative",
    }}>
      {/* Remove button */}
      <button
        onClick={onRemove}
        style={{
          position: "absolute", top: 8, right: 8,
          background: "none", border: "none", cursor: "pointer",
          color: T.muted, fontSize: 16, lineHeight: 1, padding: 2,
        }}
        title="Remove"
      >×</button>

      {/* Header */}
      <div style={{ marginBottom: 10 }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 6, marginBottom: 3 }}>
          <span style={{ fontFamily: FONTS.brand, fontWeight: 700, fontSize: 16, color: T.t1 }}>
            {asset.symbol}
          </span>
          <span style={{ fontFamily: FONTS.mono, fontSize: 11, color: GRADE_COLOR(asset.grade), fontWeight: 600 }}>
            {asset.grade}
          </span>
        </div>
        <div style={{ fontSize: 11, color: T.t3, marginBottom: 6, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
          {asset.name}
        </div>

        {/* CIS score */}
        <div style={{ display: "flex", alignItems: "baseline", gap: 6, marginBottom: 4 }}>
          <span style={{ fontFamily: FONTS.mono, fontSize: 22, fontWeight: 600, color: T.t1 }}>
            {fmtScore(asset.cis_score)}
          </span>
          <span style={{ fontSize: 10, color: T.muted }}>CIS</span>
        </div>

        {/* Signal */}
        <div style={{
          display: "inline-block",
          fontSize: 9,
          fontFamily: FONTS.mono,
          fontWeight: 600,
          letterSpacing: "0.04em",
          padding: "2px 6px",
          borderRadius: 3,
          background: `${SIG_COLOR[asset.signal] || T.muted}1a`,
          color: SIG_COLOR[asset.signal] || T.muted,
          border: `1px solid ${SIG_COLOR[asset.signal] || T.muted}44`,
          marginBottom: 8,
        }}>
          {asset.signal || "NEUTRAL"}
        </div>

        {/* Price + 24h */}
        <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11 }}>
          <span style={{ fontFamily: FONTS.mono, color: T.t2 }}>{fmtPrice(asset.price)}</span>
          <span style={{
            fontFamily: FONTS.mono,
            color: asset.change_24h == null ? T.muted : asset.change_24h >= 0 ? "#00D98A" : T.red,
          }}>
            {fmtPct(asset.change_24h)}
          </span>
        </div>
      </div>

      {/* Pillar bars */}
      <div style={{ borderTop: `1px solid ${T.border}`, paddingTop: 10 }}>
        {PILLAR_META.map(({ key, label }) => {
          const val     = asset.pillars?.[key];
          const avg     = pillarAvg?.[key];
          const isWin   = winners[key] === asset.symbol;
          const regW    = regimeWeights[key] || 1;

          return (
            <div key={key} style={{ marginBottom: 8 }}>
              <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 3 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
                  <span style={{
                    fontSize: 9, fontFamily: FONTS.mono, fontWeight: 700,
                    color: isWin ? PILLAR_COLORS[key] : T.t3,
                  }}>{key}</span>
                  {regW === 3 && (
                    <span style={{ fontSize: 8, color: PILLAR_COLORS[key], opacity: 0.8 }}>●</span>
                  )}
                  {isWin && (
                    <span style={{ fontSize: 8, color: PILLAR_COLORS[key] }}>▲</span>
                  )}
                </div>
                <span style={{
                  fontFamily: FONTS.mono, fontSize: 10,
                  color: val == null ? T.dim : isWin ? PILLAR_COLORS[key] : T.t2,
                  fontWeight: isWin ? 600 : 400,
                }}>
                  {fmtScore(val)}
                </span>
              </div>
              <PillarBar value={val} avg={avg} color={PILLAR_COLORS[key]} winner={isWin} />
            </div>
          );
        })}
      </div>

      {/* Regime-weighted score */}
      {regimeScore != null && (
        <div style={{
          marginTop: 10,
          paddingTop: 8,
          borderTop: `1px solid ${T.border}`,
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
        }}>
          <span style={{ fontSize: 9, color: T.muted, fontFamily: FONTS.mono }}>REGIME SCORE</span>
          <span style={{ fontFamily: FONTS.mono, fontSize: 11, color: T.gold, fontWeight: 600 }}>
            {regimeScore}
          </span>
        </div>
      )}
    </div>
  );
}

// ── Main component ─────────────────────────────────────────────────────────────

export default function CISCompare({ cisUniverse = [], initialSymbols = [] }) {
  const [selected, setSelected] = useState(
    initialSymbols.length ? initialSymbols.slice(0, 6) : []
  );
  const [compareData, setCompareData]   = useState(null);
  const [loading, setLoading]           = useState(false);
  const [error, setError]               = useState(null);
  const [search, setSearch]             = useState("");
  const [searchOpen, setSearchOpen]     = useState(false);
  const [copied, setCopied]             = useState(false);

  // Derive available symbols from cisUniverse prop
  const universeList = useMemo(() => {
    if (!Array.isArray(cisUniverse)) return [];
    return cisUniverse.map(a => ({
      symbol: (a.asset_id || a.symbol || "").toUpperCase(),
      name:   a.name || a.symbol || a.asset_id || "",
      class:  a.asset_class || a.class || "—",
      score:  a.cis_score ?? a.score ?? 0,
    })).filter(a => a.symbol);
  }, [cisUniverse]);

  const filteredUniverse = useMemo(() => {
    if (!search.trim()) return universeList.slice(0, 30);
    const q = search.toUpperCase();
    return universeList
      .filter(a => a.symbol.includes(q) || a.name.toUpperCase().includes(q))
      .slice(0, 20);
  }, [universeList, search]);

  // Fetch compare data whenever selection changes
  const fetchCompare = useCallback(async (syms) => {
    if (syms.length < 1) { setCompareData(null); return; }
    setLoading(true); setError(null);
    try {
      const r = await fetch(`${API_BASE}/cis/compare?symbols=${syms.join(",")}`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const d = await r.json();
      setCompareData(d);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (selected.length > 0) fetchCompare(selected);
    else setCompareData(null);
  }, [selected, fetchCompare]);

  const addSymbol = (sym) => {
    if (!selected.includes(sym) && selected.length < 6) {
      setSelected(prev => [...prev, sym]);
    }
    setSearch(""); setSearchOpen(false);
  };

  const removeSymbol = (sym) => setSelected(prev => prev.filter(s => s !== sym));

  // Per-pillar winner (highest score in comparison set)
  const winners = useMemo(() => {
    if (!compareData?.assets?.length) return {};
    const w = {};
    for (const { key } of PILLAR_META) {
      let best = -1, bestSym = null;
      for (const a of compareData.assets) {
        const v = a.pillars?.[key] ?? -1;
        if (v > best) { best = v; bestSym = a.symbol; }
      }
      if (bestSym) w[key] = bestSym;
    }
    return w;
  }, [compareData]);

  const regime    = compareData?.macro_regime || "UNKNOWN";
  const regimeW   = REGIME_PILLAR_WEIGHTS[regime] || REGIME_PILLAR_WEIGHTS.UNKNOWN;
  const regimeMeta = REGIME_LABEL[regime] || REGIME_LABEL.UNKNOWN;

  // Export: copy TSV
  const exportTSV = () => {
    if (!compareData?.assets?.length) return;
    const headers = ["Symbol","Name","Class","CIS","Grade","Signal","F","M","O","S","A","Price","24h%"];
    const rows = compareData.assets.map(a => [
      a.symbol, a.name, a.asset_class, a.cis_score, a.grade, a.signal,
      a.pillars?.F ?? "", a.pillars?.M ?? "", a.pillars?.O ?? "",
      a.pillars?.S ?? "", a.pillars?.A ?? "",
      a.price ?? "", a.change_24h ?? "",
    ]);
    const tsv = [headers, ...rows].map(r => r.join("\t")).join("\n");
    navigator.clipboard.writeText(tsv).then(() => {
      setCopied(true); setTimeout(() => setCopied(false), 1800);
    });
  };

  // ── Render ─────────────────────────────────────────────────────────────────
  return (
    <div style={{ fontFamily: FONTS.body }}>

      {/* ── Header bar ── */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16, gap: 12, flexWrap: "wrap" }}>
        <div>
          <div style={{ fontFamily: FONTS.brand, fontWeight: 700, fontSize: 14, color: T.t1, letterSpacing: "0.04em" }}>
            ASSET COMPARE
          </div>
          <div style={{ fontSize: 11, color: T.t3, marginTop: 2 }}>
            Side-by-side CIS pillar breakdown · up to 6 assets
          </div>
        </div>

        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          {/* Regime badge */}
          <div style={{
            padding: "3px 10px",
            borderRadius: 4,
            border: `1px solid ${regimeMeta.color}44`,
            background: `${regimeMeta.color}11`,
            fontSize: 10,
            fontFamily: FONTS.mono,
            color: regimeMeta.color,
            fontWeight: 600,
            letterSpacing: "0.06em",
          }}>
            {regimeMeta.text.toUpperCase()}
          </div>

          {/* Export */}
          {compareData?.assets?.length > 0 && (
            <button
              onClick={exportTSV}
              style={{
                background: "none",
                border: `1px solid ${T.border}`,
                borderRadius: 6,
                padding: "4px 10px",
                fontSize: 11,
                color: copied ? T.green : T.t2,
                cursor: "pointer",
                fontFamily: FONTS.mono,
              }}
            >
              {copied ? "Copied ✓" : "Copy TSV"}
            </button>
          )}
        </div>
      </div>

      {/* ── Regime context strip ── */}
      {compareData && (
        <div style={{
          marginBottom: 14,
          padding: "8px 12px",
          background: T.raised,
          borderRadius: 6,
          border: `1px solid ${T.border}`,
          fontSize: 11,
          color: T.t3,
          lineHeight: 1.5,
        }}>
          <span style={{ color: regimeMeta.color, fontWeight: 600, fontFamily: FONTS.mono }}>
            {regimeMeta.text}:
          </span>
          {" "}
          {regime === "RISK_ON" && "Elevated weight on Momentum and Alpha. Favor assets breaking out vs BTC benchmark."}
          {regime === "RISK_OFF" && "Elevated weight on Fundamental and On-Chain Risk. Prefer high-liquidity, low-volatility assets."}
          {regime === "TIGHTENING" && "Fundamental quality dominates. Screen for positive cash flow proxies (fee/TVL ratios) and avoid over-leveraged protocols."}
          {regime === "EASING" && "Momentum leads recovery. Assets with strong 30d trend and improving sentiment score first."}
          {regime === "STAGFLATION" && "On-chain risk and Fundamental stability matter. Real-yield assets and RWA historically outperform."}
          {regime === "GOLDILOCKS" && "Alpha independence is key — look for assets with high uncorrelated return vs BTC. Growth and quality both rewarded."}
          {(regime === "UNKNOWN" || !regime) && "Regime unknown — equal weight across all 5 pillars. Interpret scores as raw CIS v4.1."}
          {" "}
          <span style={{ color: T.muted }}>
            ● dots on pillar labels indicate high-weight pillars in this regime.
          </span>
        </div>
      )}

      {/* ── Asset selector ── */}
      <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 16, flexWrap: "wrap" }}>
        {/* Selected chips */}
        {selected.map(sym => (
          <div key={sym} style={{
            display: "flex", alignItems: "center", gap: 4,
            padding: "3px 8px 3px 10px",
            background: T.raised,
            border: `1px solid ${T.borderMd}`,
            borderRadius: 20,
            fontSize: 11,
            color: T.t1,
            fontFamily: FONTS.mono,
            fontWeight: 600,
          }}>
            {sym}
            <span
              onClick={() => removeSymbol(sym)}
              style={{ cursor: "pointer", color: T.muted, fontSize: 14, lineHeight: 1, marginLeft: 2 }}
            >×</span>
          </div>
        ))}

        {/* Add button + search */}
        {selected.length < 6 && (
          <div style={{ position: "relative" }}>
            {searchOpen ? (
              <div>
                <input
                  autoFocus
                  value={search}
                  onChange={e => setSearch(e.target.value)}
                  onBlur={() => setTimeout(() => setSearchOpen(false), 200)}
                  placeholder="Search symbol or name…"
                  style={{
                    background: T.raised,
                    border: `1px solid ${T.borderHi}`,
                    borderRadius: 6,
                    padding: "5px 10px",
                    color: T.t1,
                    fontSize: 11,
                    fontFamily: FONTS.mono,
                    outline: "none",
                    width: 180,
                  }}
                />
                {filteredUniverse.length > 0 && (
                  <div style={{
                    position: "absolute",
                    top: "100%",
                    left: 0,
                    zIndex: 200,
                    background: T.surface,
                    border: `1px solid ${T.borderMd}`,
                    borderRadius: 8,
                    marginTop: 4,
                    width: 220,
                    maxHeight: 240,
                    overflowY: "auto",
                    boxShadow: "0 8px 32px rgba(0,0,0,0.5)",
                  }}>
                    {filteredUniverse.map(a => (
                      <div
                        key={a.symbol}
                        onMouseDown={() => addSymbol(a.symbol)}
                        style={{
                          padding: "7px 12px",
                          cursor: "pointer",
                          display: "flex",
                          justifyContent: "space-between",
                          alignItems: "center",
                          borderBottom: `1px solid ${T.border}`,
                          opacity: selected.includes(a.symbol) ? 0.4 : 1,
                        }}
                      >
                        <div>
                          <span style={{ fontFamily: FONTS.mono, fontWeight: 600, fontSize: 12, color: T.t1 }}>{a.symbol}</span>
                          <span style={{ fontSize: 10, color: T.t3, marginLeft: 6 }}>{a.name}</span>
                        </div>
                        <span style={{ fontSize: 10, color: T.muted, fontFamily: FONTS.mono }}>{a.score?.toFixed(0)}</span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ) : (
              <button
                onClick={() => setSearchOpen(true)}
                style={{
                  background: "none",
                  border: `1px dashed ${T.borderMd}`,
                  borderRadius: 20,
                  padding: "3px 12px",
                  color: T.t3,
                  fontSize: 11,
                  cursor: "pointer",
                  fontFamily: FONTS.body,
                }}
              >
                + Add asset
              </button>
            )}
          </div>
        )}

        {selected.length === 0 && (
          <span style={{ fontSize: 11, color: T.muted }}>
            Try: BTC, ETH, SOL — or any asset from the CIS universe
          </span>
        )}
      </div>

      {/* ── Empty state ── */}
      {selected.length === 0 && (
        <div style={{
          textAlign: "center",
          padding: "48px 24px",
          background: T.surface,
          border: `1px solid ${T.border}`,
          borderRadius: 12,
          color: T.muted,
          fontSize: 13,
        }}>
          Select assets above to compare pillar scores side-by-side.
          <div style={{ marginTop: 12, display: "flex", gap: 8, justifyContent: "center", flexWrap: "wrap" }}>
            {["BTC", "ETH", "SOL", "AAVE", "SPY", "GLD"].map(sym => (
              <button
                key={sym}
                onClick={() => addSymbol(sym)}
                disabled={!universeList.find(a => a.symbol === sym)}
                style={{
                  background: T.raised,
                  border: `1px solid ${T.border}`,
                  borderRadius: 6,
                  padding: "4px 10px",
                  color: T.t2,
                  fontSize: 11,
                  cursor: "pointer",
                  fontFamily: FONTS.mono,
                  opacity: universeList.find(a => a.symbol === sym) ? 1 : 0.3,
                }}
              >{sym}</button>
            ))}
          </div>
        </div>
      )}

      {/* ── Loading ── */}
      {loading && (
        <div style={{ textAlign: "center", padding: 32, color: T.muted, fontSize: 12, fontFamily: FONTS.mono }}>
          Fetching pillar data…
        </div>
      )}

      {/* ── Error ── */}
      {error && !loading && (
        <div style={{
          padding: "10px 14px",
          background: `${T.red}11`,
          border: `1px solid ${T.red}44`,
          borderRadius: 8,
          color: T.red,
          fontSize: 12,
          marginBottom: 12,
        }}>
          {error}
        </div>
      )}

      {/* ── Asset cards ── */}
      {compareData?.assets?.length > 0 && !loading && (
        <>
          <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginBottom: 20 }}>
            {compareData.assets.map((asset, i) => (
              <AssetCard
                key={asset.symbol}
                asset={asset}
                pillarAvg={compareData.pillar_universe_avg}
                winners={winners}
                regimeWeights={regimeW}
                isFirst={i === 0}
                onRemove={() => removeSymbol(asset.symbol)}
              />
            ))}
          </div>

          {/* ── Pillar winner summary ── */}
          <div style={{
            padding: "12px 16px",
            background: T.surface,
            border: `1px solid ${T.border}`,
            borderRadius: 8,
            marginBottom: 14,
          }}>
            <div style={{ fontSize: 10, color: T.muted, fontFamily: FONTS.mono, marginBottom: 8, letterSpacing: "0.08em" }}>
              PILLAR LEADERS
            </div>
            <div style={{ display: "flex", gap: 20, flexWrap: "wrap" }}>
              {PILLAR_META.map(({ key, label }) => {
                const winnerSym = winners[key];
                const regW      = regimeW[key] || 1;
                return (
                  <div key={key} style={{ minWidth: 80 }}>
                    <div style={{ display: "flex", gap: 4, alignItems: "center", marginBottom: 2 }}>
                      <span style={{ fontSize: 9, fontFamily: FONTS.mono, fontWeight: 700, color: PILLAR_COLORS[key] }}>{key}</span>
                      {regW === 3 && <span style={{ fontSize: 8, color: PILLAR_COLORS[key] }}>●</span>}
                      <span style={{ fontSize: 9, color: T.muted }}>{label}</span>
                    </div>
                    <div style={{
                      fontFamily: FONTS.mono,
                      fontWeight: 600,
                      fontSize: 13,
                      color: winnerSym ? PILLAR_COLORS[key] : T.muted,
                    }}>
                      {winnerSym || "—"}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* ── Universe avg note ── */}
          <div style={{ fontSize: 10, color: T.dim, fontFamily: FONTS.mono, paddingLeft: 2 }}>
            White tick on bars = universe average ({compareData.universe_size} assets) · ●dots = high-weight pillar in {regimeMeta.text} regime
          </div>
        </>
      )}

      {/* ── Not found notice ── */}
      {compareData?.not_found?.length > 0 && (
        <div style={{ marginTop: 8, fontSize: 11, color: T.amber, fontFamily: FONTS.mono }}>
          Not in universe: {compareData.not_found.join(", ")}
        </div>
      )}
    </div>
  );
}
