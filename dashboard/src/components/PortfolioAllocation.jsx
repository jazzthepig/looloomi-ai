/**
 * PortfolioAllocation — CIS-driven portfolio builder
 *
 * Receives `universe` prop from CISContent (same fetch, zero extra requests).
 *
 * Strategies:
 *   1. CIS-Weighted  — weights proportional to score, concentration-capped
 *   2. Equal Weight  — 1/N across top-N by CIS
 *   3. Risk Parity   — inverse-volatility weights (|change_30d| proxy)
 *
 * Risk presets:
 *   Conservative  — min grade B+, max 10 assets, 20% cap, no Meme/Gaming
 *   Balanced      — min grade B,  max 15 assets, 25% cap
 *   Aggressive    — min grade C+, max 20 assets, 30% cap
 */

import { useState, useMemo, useCallback } from "react";
import { T, FONTS } from "../tokens";

const PA_CSS = `
  .pa-layout {
    display: grid;
    grid-template-columns: 300px 1fr;
    gap: 20px;
  }
  .pa-metrics {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(110px, 1fr));
    gap: 10px;
  }
  .pa-alloc-table {
    overflow-x: auto;
  }
  .pa-alloc-row {
    display: grid;
    grid-template-columns: 28px 1fr 70px 55px 50px 110px 90px;
    padding: 11px 16px;
    align-items: center;
    transition: background 0.1s;
    min-width: 0;
  }
  .pa-alloc-head {
    display: grid;
    grid-template-columns: 28px 1fr 70px 55px 50px 110px 90px;
    padding: 8px 16px;
  }
  @media (max-width: 900px) {
    .pa-layout {
      grid-template-columns: 1fr;
    }
  }
  @media (max-width: 700px) {
    .pa-metrics {
      grid-template-columns: repeat(2, 1fr);
    }
    .pa-alloc-row,
    .pa-alloc-head {
      grid-template-columns: 24px 1fr 55px 44px 90px;
    }
    .pa-col-class,
    .pa-col-signal-hide {
      display: none;
    }
  }
`;

// ── Grade ordering ────────────────────────────────────────────────────────────
const GRADE_ORDER = { "A+": 9, "A": 8, "B+": 7, "B": 6, "C+": 5, "C": 4, "D": 3, "F": 2 };
function gradeGte(a, b) { return (GRADE_ORDER[a] || 0) >= (GRADE_ORDER[b] || 0); }

// ── Signal colors ─────────────────────────────────────────────────────────────
const SIG_COLOR = {
  "STRONG OUTPERFORM": "#00D98A",
  "OUTPERFORM":        "#4472FF",
  "NEUTRAL":           "#E8A000",
  "UNDERPERFORM":      "#FF6B35",
  "UNDERWEIGHT":       "#FF2D55",
};

// ── Asset class colors ────────────────────────────────────────────────────────
const CLASS_COLORS = {
  L1: "#00C8E0", L2: "#9945FF", DeFi: "#4472FF", RWA: "#E8A000",
  Infrastructure: "#00D98A", Oracle: "#A78BFA", Memecoin: "#FF1060",
  AI: "#FF6B00", "US Equity": "#4B9EFF", "US Bond": "#F59E0B", Commodity: "#C8A84B",
};

// ── Risk presets ──────────────────────────────────────────────────────────────
const PRESETS = {
  Conservative: {
    minGrade: "B+", maxAssets: 10, cap: 0.20,
    excludeClasses: new Set(["Memecoin", "Gaming", "AI"]),
    label: "Conservative",
    desc: "B+ or above · Max 10 assets · 20% cap · No Meme/AI",
    color: "#00D98A",
  },
  Balanced: {
    minGrade: "B", maxAssets: 15, cap: 0.25,
    excludeClasses: new Set(["Memecoin"]),
    label: "Balanced",
    desc: "B or above · Max 15 assets · 25% cap",
    color: "#4472FF",
  },
  Aggressive: {
    minGrade: "C+", maxAssets: 20, cap: 0.30,
    excludeClasses: new Set(),
    label: "Aggressive",
    desc: "C+ or above · Max 20 assets · 30% cap",
    color: "#E8A000",
  },
};

// ── Pearson correlation (3-point: 24h / 7d / 30d return vector) ──────────────
function pearsonCorr(xs, ys) {
  const n = xs.length;
  if (n < 2) return 0;
  const mx = xs.reduce((a, b) => a + b, 0) / n;
  const my = ys.reduce((a, b) => a + b, 0) / n;
  const num = xs.reduce((s, x, i) => s + (x - mx) * (ys[i] - my), 0);
  const dx  = Math.sqrt(xs.reduce((s, x) => s + (x - mx) ** 2, 0));
  const dy  = Math.sqrt(ys.reduce((s, y) => s + (y - my) ** 2, 0));
  if (dx === 0 || dy === 0) return 0;
  return num / (dx * dy);
}

// ── Allocation algorithms ─────────────────────────────────────────────────────
function applyCap(weights, cap) {
  for (let i = 0; i < 5; i++) {
    let excess = 0, freeCount = 0;
    weights = weights.map(w => {
      if (w > cap) { excess += w - cap; return cap; }
      freeCount++;
      return w;
    });
    if (excess < 1e-6 || !freeCount) break;
    const boost = excess / freeCount;
    weights = weights.map(w => w < cap ? Math.min(cap, w + boost) : w);
  }
  return weights;
}

function allocateCISWeighted(assets, cap) {
  const totalScore = assets.reduce((s, a) => s + (a.cis_score || 0), 0);
  if (!totalScore) return allocateEqualWeight(assets);
  return applyCap(assets.map(a => (a.cis_score || 0) / totalScore), cap);
}

function allocateEqualWeight(assets) {
  return assets.map(() => 1 / assets.length);
}

function allocateRiskParity(assets, cap) {
  const vols = assets.map((a, i) => {
    const v = Math.abs(a.change_30d ?? 0);
    return v > 0.1 ? v : (10 + i); // fallback rank-based
  });
  const invVols = vols.map(v => 1 / v);
  const totalInv = invVols.reduce((s, v) => s + v, 0);
  return applyCap(invVols.map(v => v / totalInv), cap);
}

function allocateLASWeighted(assets, cap) {
  // Uses LAS (Liquidity-Adjusted Score) for T1 assets; falls back to CIS for T2
  const scores = assets.map(a => a.las_score || a.cis_score || 0);
  const total = scores.reduce((s, v) => s + v, 0);
  if (!total) return allocateEqualWeight(assets);
  return applyCap(scores.map(v => v / total), cap);
}

function allocateMomentum(assets, cap) {
  // CIS × momentum modifier using 7d return: positive trend amplifies, negative dampens
  // Momentum contribution clamped to [-0.3, +0.5] to avoid runaway winners
  const scores = assets.map(a => {
    const cis   = a.cis_score || 0;
    const mom7d = a.change_7d ?? 0;
    const factor = mom7d > 0
      ? Math.min(mom7d / 40, 0.5)    // +20% 7d → +0.5 amplifier
      : Math.max(mom7d / 67, -0.3);  // −20% 7d → −0.3 dampener
    return cis * (1 + factor);
  });
  const total = scores.reduce((s, v) => s + v, 0);
  if (!total) return allocateEqualWeight(assets);
  return applyCap(scores.map(v => v / total), cap);
}

// Iteratively redistribute weight from overcapped sectors to others
function applySectorCap(allocs, weights, maxSectorPct) {
  if (!maxSectorPct) return weights;
  for (let iter = 0; iter < 10; iter++) {
    const sectorW = {};
    allocs.forEach((a, i) => {
      const cls = a.asset_class || "Other";
      sectorW[cls] = (sectorW[cls] || 0) + weights[i];
    });
    const overcap = new Set(
      Object.entries(sectorW).filter(([, w]) => w > maxSectorPct).map(([c]) => c)
    );
    if (!overcap.size) break;
    let totalExcess = 0;
    weights = weights.map((w, i) => {
      const cls = allocs[i].asset_class || "Other";
      if (overcap.has(cls)) {
        const scaled = w * (maxSectorPct / sectorW[cls]);
        totalExcess += w - scaled;
        return scaled;
      }
      return w;
    });
    const freeTotal = weights.reduce((s, w, i) =>
      s + (overcap.has(allocs[i].asset_class || "Other") ? 0 : w), 0);
    if (freeTotal > 0) {
      weights = weights.map((w, i) =>
        overcap.has(allocs[i].asset_class || "Other")
          ? w
          : w + (w / freeTotal) * totalExcess
      );
    }
  }
  const total = weights.reduce((s, w) => s + w, 0);
  return total > 0 ? weights.map(w => w / total) : weights;
}

// ── Regime palette ─────────────────────────────────────────────────────────────
const REGIME_COLOR = {
  RISK_ON:     "#00D98A",
  GOLDILOCKS:  "#4472FF",
  EASING:      "#9945FF",
  TIGHTENING:  "#E8A000",
  RISK_OFF:    "#FF2D55",
  STAGFLATION: "#FF6B35",
};

// ── Main component ────────────────────────────────────────────────────────────
export default function PortfolioAllocation({ universe = [] }) {
  const [preset, setPreset]           = useState("Balanced");
  const [strategy, setStrategy]       = useState("CIS-Weighted");
  const [customSize, setCustomSize]   = useState(null);
  const [selectedClasses, setSelectedClasses] = useState(null);
  const [sectorCap, setSectorCap]     = useState(null);

  const cfg = PRESETS[preset];

  // Detect current macro regime from T1 assets (global, not per-asset)
  const macroRegime = useMemo(() => {
    for (const a of universe) { if (a.macro_regime) return a.macro_regime; }
    return null;
  }, [universe]);

  const availableClasses = useMemo(
    () => [...new Set(universe.map(a => a.asset_class).filter(Boolean))].sort(),
    [universe]
  );

  const activeClasses = selectedClasses ?? new Set(availableClasses);

  const { allocations, metrics, corrWarning } = useMemo(() => {
    if (!universe.length) return { allocations: [], metrics: null, corrWarning: null };

    const maxAssets = customSize ?? cfg.maxAssets;
    const eligible = universe.filter(a =>
      a.grade &&
      gradeGte(a.grade, cfg.minGrade) &&
      !cfg.excludeClasses.has(a.asset_class) &&
      activeClasses.has(a.asset_class) &&
      (a.cis_score ?? 0) > 0
    );

    const selected = [...eligible]
      .sort((a, b) => (b.cis_score || 0) - (a.cis_score || 0))
      .slice(0, maxAssets);

    if (!selected.length) return { allocations: [], metrics: null, corrWarning: null };

    let weights;
    if (strategy === "CIS-Weighted")      weights = allocateCISWeighted(selected, cfg.cap);
    else if (strategy === "LAS-Weighted") weights = allocateLASWeighted(selected, cfg.cap);
    else if (strategy === "Momentum+")    weights = allocateMomentum(selected, cfg.cap);
    else if (strategy === "Equal Weight") weights = allocateEqualWeight(selected);
    else                                  weights = allocateRiskParity(selected, cfg.cap);

    if (sectorCap) weights = applySectorCap(selected, weights, sectorCap);

    const total = weights.reduce((s, w) => s + w, 0);
    weights = weights.map(w => w / total);

    const allocs = selected.map((a, i) => ({ ...a, weight: weights[i] }))
      .sort((a, b) => b.weight - a.weight);

    const avgCIS     = allocs.reduce((s, a) => s + (a.cis_score || 0) * a.weight, 0);
    const classCount = new Set(allocs.map(a => a.asset_class)).size;
    const signalDist = {};
    for (const a of allocs) {
      const sig = a.signal || "NEUTRAL";
      signalDist[sig] = (signalDist[sig] || 0) + a.weight;
    }

    // ── Correlation cluster detection ────────────────────────────────────────
    // Use 3-point return vector [change_24h, change_7d, change_30d] as proxy.
    // Pearson ≥ 0.75 across all three windows = likely co-moving assets.
    const getReturns = (a) => [
      a.change_24h ?? 0,
      a.change_7d  ?? 0,
      a.change_30d ?? 0,
    ];
    const corrPairs = [];
    for (let i = 0; i < allocs.length; i++) {
      for (let j = i + 1; j < allocs.length; j++) {
        const r = pearsonCorr(getReturns(allocs[i]), getReturns(allocs[j]));
        if (r >= 0.75) {
          corrPairs.push({ a: allocs[i].symbol, b: allocs[j].symbol, corr: r });
        }
      }
    }
    corrPairs.sort((x, y) => y.corr - x.corr);
    let corrWarning = null;
    if (corrPairs.length > 0) {
      // Build cluster set from all flagged pairs
      const clusterSet = new Set();
      corrPairs.forEach(({ a, b }) => { clusterSet.add(a); clusterSet.add(b); });
      const combinedWeight = allocs
        .filter(a => clusterSet.has(a.symbol))
        .reduce((s, a) => s + a.weight, 0);
      corrWarning = {
        pairs: corrPairs.slice(0, 3),
        cluster: [...clusterSet].slice(0, 7),
        maxCorr: corrPairs[0].corr,
        combinedWeight,
      };
    }

    // ── Risk metrics ────────────────────────────────────────────────────────────
    // Effective N (inverse Herfindahl): 1/Σw² — 1 = single position, N = perfect equal weight
    const hhi         = allocs.reduce((s, a) => s + a.weight ** 2, 0);
    const effectiveN  = hhi > 0 ? 1 / hhi : allocs.length;

    // Weighted portfolio volatility proxy (|change_30d| as σ surrogate)
    const weightedVol = allocs.reduce((s, a) => {
      const v30 = Math.abs(a.change_30d ?? a.change_7d ?? a.change_24h ?? 0);
      return s + a.weight * v30;
    }, 0);

    // Portfolio BTC beta proxy: weighted correlation of each asset's 30d return vs BTC 30d
    // We use cross-sectional Pearson of the 3-point return vectors vs any BTC entry in universe
    const btcEntry = universe.find(a => (a.asset_id || a.symbol || "").toUpperCase() === "BTC");
    let btcBeta = null;
    if (btcEntry) {
      const btcVec = getReturns(btcEntry);
      const betaSum = allocs.reduce((s, a) => {
        const rho = pearsonCorr(getReturns(a), btcVec);
        return s + a.weight * rho;
      }, 0);
      btcBeta = betaSum;  // weighted average correlation as beta proxy (−1 to 1)
    }

    return {
      allocations: allocs,
      metrics: { avgCIS, classCount, signalDist, count: allocs.length, effectiveN, weightedVol, btcBeta },
      corrWarning,
    };
  }, [universe, preset, strategy, customSize, activeClasses, sectorCap]);

  const toggleClass = (cls) => {
    const next = new Set(activeClasses);
    if (next.has(cls)) { if (next.size > 1) next.delete(cls); }
    else next.add(cls);
    setSelectedClasses(next);
  };

  const exportCSV = useCallback(() => {
    if (!allocations.length) return;
    const header = "Rank,Symbol,Name,Class,CIS Score,Grade,Signal,Weight (%)\n";
    const rows = allocations.map((a, i) =>
      [
        i + 1,
        a.symbol,
        `"${(a.name || "").replace(/"/g, "'")}"`,
        a.asset_class || "",
        (a.cis_score || 0).toFixed(1),
        a.grade || "",
        a.signal || "NEUTRAL",
        (a.weight * 100).toFixed(2),
      ].join(",")
    ).join("\n");
    const csv = header + rows;
    const blob = new Blob([csv], { type: "text/csv" });
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement("a");
    a.href     = url;
    a.download = `cometcloud-portfolio-${strategy.toLowerCase().replace(/ /g, "-")}-${PRESETS[preset].label.toLowerCase()}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }, [allocations, strategy, preset]);

  if (!universe.length) return null;

  return (
    <div style={{ marginTop: 40 }}>
      <style>{PA_CSS}</style>
      {/* Section header */}
      <div style={{
        display: "flex", alignItems: "center", gap: 12, marginBottom: 24,
        paddingBottom: 14, borderBottom: `1px solid ${T.border}`,
      }}>
        <div style={{ width: 14, height: 1, background: "#C8A84B", opacity: 0.5 }} />
        <span style={{
          fontFamily: FONTS.display, fontSize: 11, fontWeight: 700,
          letterSpacing: "0.14em", color: T.t2, textTransform: "uppercase",
        }}>
          Portfolio Builder
        </span>
        <span style={{ fontSize: 9, color: T.t3, fontFamily: FONTS.mono, marginLeft: "auto" }}>
          CIS-driven allocation · {universe.length} assets in universe
        </span>
      </div>

      <div className="pa-layout">

        {/* ── LEFT PANEL: Controls ── */}
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>

          {/* Risk preset */}
          <div style={{ background: T.surface, border: `1px solid ${T.border}`, borderRadius: 10, padding: "16px 18px" }}>
            <div style={labelStyle}>Risk Profile</div>
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {Object.entries(PRESETS).map(([key, p]) => (
                <button key={key}
                  onClick={() => { setPreset(key); setCustomSize(null); setSelectedClasses(null); }}
                  style={{
                    textAlign: "left", padding: "10px 12px", borderRadius: 7, cursor: "pointer",
                    border: `1px solid ${preset === key ? `${p.color}50` : T.border}`,
                    background: preset === key ? `${p.color}0E` : "transparent",
                    transition: "all 0.15s",
                  }}
                >
                  <div style={{ fontFamily: FONTS.display, fontWeight: 700, fontSize: 12, color: preset === key ? p.color : T.t2, marginBottom: 2 }}>
                    {p.label}
                  </div>
                  <div style={{ fontSize: 10, color: T.t3, fontFamily: FONTS.body }}>{p.desc}</div>
                </button>
              ))}
            </div>
          </div>

          {/* Strategy */}
          <div style={{ background: T.surface, border: `1px solid ${T.border}`, borderRadius: 10, padding: "16px 18px" }}>
            <div style={labelStyle}>Allocation Strategy</div>
            {[
              { id: "CIS-Weighted",  sub: "default" },
              { id: "LAS-Weighted",  sub: "liquidity-adjusted" },
              { id: "Momentum+",     sub: "CIS × 7d trend" },
              { id: "Equal Weight",  sub: null },
              { id: "Risk Parity",   sub: "inverse vol" },
            ].map(({ id, sub }) => (
              <button key={id} onClick={() => setStrategy(id)}
                style={{
                  display: "block", width: "100%", textAlign: "left",
                  padding: "7px 10px", borderRadius: 6, marginBottom: 4, cursor: "pointer",
                  border: `1px solid ${strategy === id ? "rgba(56,148,210,0.4)" : T.border}`,
                  background: strategy === id ? "rgba(56,148,210,0.08)" : "transparent",
                  color: strategy === id ? "#7AAEC8" : T.t3,
                  fontFamily: FONTS.display, fontWeight: 600, fontSize: 11,
                  transition: "all 0.15s",
                }}
              >
                {id}
                {sub && <span style={{ fontSize: 9, color: T.t3, marginLeft: 6, fontWeight: 400 }}>{sub}</span>}
              </button>
            ))}

            <div style={{ marginTop: 12, paddingTop: 12, borderTop: `1px solid ${T.border}` }}>
              <div style={labelStyle}>Portfolio Size</div>
              <div style={{ display: "flex", gap: 5 }}>
                {[null, 5, 10, 20].map(n => (
                  <button key={n ?? "auto"} onClick={() => setCustomSize(n)}
                    style={{
                      flex: 1, padding: "5px 0", borderRadius: 5, fontSize: 10,
                      fontFamily: FONTS.mono, fontWeight: 600, cursor: "pointer",
                      border: `1px solid ${customSize === n ? "rgba(56,148,210,0.5)" : T.border}`,
                      background: customSize === n ? "rgba(56,148,210,0.10)" : "transparent",
                      color: customSize === n ? "#7AAEC8" : T.t3,
                    }}
                  >
                    {n ?? "Auto"}
                  </button>
                ))}
              </div>
            </div>

            <div style={{ marginTop: 12, paddingTop: 12, borderTop: `1px solid ${T.border}` }}>
              <div style={labelStyle}>Sector Cap</div>
              <div style={{ display: "flex", gap: 5 }}>
                {[null, 0.35, 0.45].map(cap => (
                  <button key={cap ?? "off"} onClick={() => setSectorCap(cap)}
                    style={{
                      flex: 1, padding: "5px 0", borderRadius: 5, fontSize: 10,
                      fontFamily: FONTS.mono, fontWeight: 600, cursor: "pointer",
                      border: `1px solid ${sectorCap === cap ? "rgba(200,168,75,0.5)" : T.border}`,
                      background: sectorCap === cap ? "rgba(200,168,75,0.10)" : "transparent",
                      color: sectorCap === cap ? "#C8A84B" : T.t3,
                    }}
                  >
                    {cap == null ? "Off" : `${Math.round(cap * 100)}%`}
                  </button>
                ))}
              </div>
              <div style={{ fontSize: 9, color: T.t3, marginTop: 5, fontFamily: FONTS.body }}>
                Max weight per asset class
              </div>
            </div>
          </div>

          {/* Asset classes */}
          <div style={{ background: T.surface, border: `1px solid ${T.border}`, borderRadius: 10, padding: "16px 18px" }}>
            <div style={labelStyle}>Asset Classes</div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 5 }}>
              {availableClasses.map(cls => {
                const excluded = cfg.excludeClasses.has(cls);
                const active   = activeClasses.has(cls) && !excluded;
                const clr      = CLASS_COLORS[cls] || "#6B7280";
                return (
                  <button key={cls}
                    onClick={() => !excluded && toggleClass(cls)}
                    disabled={excluded}
                    style={{
                      padding: "3px 8px", borderRadius: 4, fontSize: 10, cursor: excluded ? "not-allowed" : "pointer",
                      fontFamily: FONTS.display, fontWeight: 700,
                      border: `1px solid ${active ? `${clr}50` : "rgba(255,255,255,0.06)"}`,
                      background: active ? `${clr}12` : "transparent",
                      color: excluded ? "rgba(255,255,255,0.15)" : (active ? clr : T.t3),
                      opacity: excluded ? 0.4 : 1, transition: "all 0.15s",
                    }}
                  >
                    {cls}
                  </button>
                );
              })}
            </div>
            <div style={{ fontSize: 9, color: T.t3, marginTop: 8, fontFamily: FONTS.body }}>
              Greyed = excluded by risk profile
            </div>
          </div>
        </div>

        {/* ── RIGHT PANEL: Output ── */}
        <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>

          {/* Regime banner */}
          {macroRegime && (
            <div style={{
              padding: "8px 14px", borderRadius: 7,
              background: `${REGIME_COLOR[macroRegime] || "#6B7280"}0A`,
              border: `1px solid ${REGIME_COLOR[macroRegime] || "#6B7280"}30`,
              display: "flex", alignItems: "center", gap: 10,
            }}>
              <div style={{
                width: 6, height: 6, borderRadius: "50%",
                background: REGIME_COLOR[macroRegime] || "#6B7280", flexShrink: 0,
              }} />
              <span style={{
                fontSize: 9, fontFamily: FONTS.display, fontWeight: 700,
                letterSpacing: "0.12em", textTransform: "uppercase",
                color: REGIME_COLOR[macroRegime] || "#6B7280",
              }}>
                Regime · {macroRegime.replace("_", " ")}
              </span>
              <span style={{ fontSize: 9, color: T.t3, fontFamily: FONTS.body, marginLeft: "auto" }}>
                {macroRegime === "TIGHTENING" && "Weights skewed toward quality. Min grade filter applies."}
                {macroRegime === "RISK_OFF"   && "Defensive posture. High correlation among alts expected."}
                {macroRegime === "RISK_ON"    && "Risk appetite elevated. Full allocation eligible."}
                {macroRegime === "GOLDILOCKS" && "Ideal conditions. Broad universe active."}
                {macroRegime === "EASING"     && "Liquidity expanding. Growth assets favoured."}
                {macroRegime === "STAGFLATION"&& "Mixed signals. RWA and commodities defensive."}
              </span>
            </div>
          )}

          {/* Metrics */}
          {metrics && (
            <div className="pa-metrics">
              {[
                { label: "Positions", value: metrics.count, mono: true },
                {
                  label: "Avg CIS", value: metrics.avgCIS.toFixed(1), mono: true,
                  color: metrics.avgCIS >= 60 ? T.green : metrics.avgCIS >= 45 ? T.blue : T.amber,
                },
                { label: "Classes", value: metrics.classCount, mono: true },
                {
                  label: "Top Signal",
                  value: Object.entries(metrics.signalDist).sort((a,b) => b[1]-a[1])[0]?.[0]
                    ?.replace("STRONG OUTPERFORM","STR OUT").replace("OUTPERFORM","OUTPERF")
                    .replace("UNDERPERFORM","UNDERPERF") || "—",
                  mono: false,
                  color: SIG_COLOR[Object.entries(metrics.signalDist).sort((a,b)=>b[1]-a[1])[0]?.[0]] || T.t1,
                },
                {
                  label: "Eff. N",
                  value: metrics.effectiveN?.toFixed(1) ?? "—",
                  mono: true,
                  color: metrics.effectiveN >= metrics.count * 0.8 ? T.green
                       : metrics.effectiveN >= metrics.count * 0.5 ? T.t1
                       : T.amber,
                  title: `Effective positions (inverse HHI). Lower than position count = concentration risk. Max = ${metrics.count}`,
                },
                {
                  label: "Vol Proxy",
                  value: metrics.weightedVol != null ? `${metrics.weightedVol.toFixed(1)}%` : "—",
                  mono: true,
                  color: metrics.weightedVol < 15 ? T.green : metrics.weightedVol < 35 ? T.amber : T.red,
                  title: "Weighted avg |30d change| across positions — directional volatility proxy, not annualised σ",
                },
                ...(metrics.btcBeta != null ? [{
                  label: "β BTC",
                  value: metrics.btcBeta.toFixed(2),
                  mono: true,
                  color: Math.abs(metrics.btcBeta) < 0.4 ? T.green
                       : Math.abs(metrics.btcBeta) < 0.7 ? T.t1
                       : T.amber,
                  title: "Weighted-avg return correlation vs BTC (3-point proxy). <0.4 = low BTC dependency.",
                }] : []),
              ].map((m, i) => (
                <div key={i} title={m.title || ""} style={{
                  background: T.surface, border: `1px solid ${T.border}`,
                  borderRadius: 8, padding: "12px 14px",
                  cursor: m.title ? "help" : "default",
                }}>
                  <div style={{ fontSize: 9, color: T.t3, textTransform: "uppercase", letterSpacing: "0.1em", fontFamily: FONTS.display, marginBottom: 6 }}>
                    {m.label}
                  </div>
                  <div style={{
                    fontSize: 20, lineHeight: 1,
                    fontFamily: m.mono ? FONTS.mono : FONTS.display,
                    fontWeight: m.mono ? 400 : 700,
                    color: m.color || T.t1,
                  }}>
                    {m.value}
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Signal distribution bar */}
          {metrics?.signalDist && (
            <div style={{
              background: T.surface, border: `1px solid ${T.border}`,
              borderRadius: 8, padding: "10px 14px",
              display: "flex", alignItems: "center", gap: 14,
            }}>
              <span style={{ fontSize: 9, color: T.t3, fontFamily: FONTS.display, textTransform: "uppercase", letterSpacing: "0.1em", flexShrink: 0 }}>
                Signal Mix
              </span>
              <div style={{ flex: 1, display: "flex", height: 5, borderRadius: 3, overflow: "hidden", gap: 1 }}>
                {Object.entries(metrics.signalDist)
                  .sort((a, b) => b[1] - a[1])
                  .map(([sig, w]) => (
                    <div key={sig} style={{
                      flex: w, background: SIG_COLOR[sig] || T.t3,
                      minWidth: 2, opacity: 0.8,
                    }} title={`${sig}: ${(w * 100).toFixed(0)}%`} />
                  ))}
              </div>
              <div style={{ display: "flex", gap: 10, flexShrink: 0 }}>
                {Object.entries(metrics.signalDist).sort((a, b) => b[1] - a[1]).map(([sig, w]) => (
                  <div key={sig} style={{ display: "flex", alignItems: "center", gap: 4 }}>
                    <div style={{ width: 6, height: 6, borderRadius: "50%", background: SIG_COLOR[sig] || T.t3, flexShrink: 0 }} />
                    <span style={{ fontSize: 9, color: T.t3, fontFamily: FONTS.mono }}>
                      {sig.replace("STRONG OUTPERFORM","STR OUT").replace("OUTPERFORM","OUT").replace("UNDERPERFORM","UND")}{" "}
                      {(w * 100).toFixed(0)}%
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Correlation Warning */}
          {corrWarning && (
            <div style={{
              background: "rgba(255,107,53,0.06)",
              border: "1px solid rgba(255,107,53,0.22)",
              borderRadius: 8, padding: "11px 14px",
              display: "flex", alignItems: "flex-start", gap: 10,
            }}>
              <span style={{ color: "#FF6B35", fontSize: 14, flexShrink: 0, marginTop: 1 }}>⚠</span>
              <div style={{ flex: 1 }}>
                <div style={{
                  fontFamily: FONTS.display, fontWeight: 700, fontSize: 10,
                  color: "#FF6B35", letterSpacing: "0.1em", textTransform: "uppercase",
                  marginBottom: 5,
                }}>
                  High Correlation Warning
                </div>
                <div style={{ fontSize: 11, color: T.t2, fontFamily: FONTS.body, lineHeight: 1.55 }}>
                  <span style={{ fontFamily: FONTS.mono, color: "#FF9F7A", fontWeight: 600 }}>
                    {corrWarning.cluster.join(" · ")}
                  </span>
                  {" "}move together (r ≈ {corrWarning.maxCorr.toFixed(2)}, combined {(corrWarning.combinedWeight * 100).toFixed(0)}% of portfolio).
                  Effective diversification may be lower than {corrWarning.cluster.length} positions suggest — consider reducing concentration or adding non-correlated classes.
                </div>
                {corrWarning.pairs.length > 1 && (
                  <div style={{ marginTop: 6, display: "flex", flexWrap: "wrap", gap: 5 }}>
                    {corrWarning.pairs.map(({ a, b, corr }) => (
                      <span key={`${a}-${b}`} style={{
                        fontSize: 9, fontFamily: FONTS.mono, color: "rgba(255,107,53,0.75)",
                        background: "rgba(255,107,53,0.08)", border: "1px solid rgba(255,107,53,0.15)",
                        borderRadius: 4, padding: "2px 6px",
                      }}>
                        {a}/{b} r={corr.toFixed(2)}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Allocation table */}
          {allocations.length === 0 ? (
            <div style={{
              background: T.surface, border: `1px solid ${T.border}`,
              borderRadius: 10, padding: "40px 20px", textAlign: "center",
              color: T.t3, fontFamily: FONTS.body, fontSize: 13,
            }}>
              No assets match the current filters — try a lower grade threshold or more asset classes.
            </div>
          ) : (
            <div style={{ background: T.surface, border: `1px solid ${T.border}`, borderRadius: 10, overflow: "hidden" }}>
              {/* Header */}
              <div className="pa-alloc-head" style={{
                borderBottom: `1px solid ${T.border}`,
                background: "rgba(0,0,0,0.14)",
              }}>
                {["#", "Asset", "Class", "CIS", "Grade", "Signal", "Weight"].map((h, i) => (
                  <span key={i}
                    className={i === 2 ? "pa-col-class" : i === 5 ? "pa-col-signal-hide" : ""}
                    style={{
                      fontSize: 9, color: T.t3, fontFamily: FONTS.display, fontWeight: 700,
                      letterSpacing: "0.1em", textTransform: "uppercase",
                      textAlign: i >= 3 ? "right" : "left",
                    }}>
                    {h}
                  </span>
                ))}
              </div>

              <div className="pa-alloc-table">
              {allocations.map((a, idx) => {
                const clr    = CLASS_COLORS[a.asset_class] || "#6B7280";
                const sigClr = SIG_COLOR[a.signal] || T.t3;
                return (
                  <div key={a.symbol}
                    className="pa-alloc-row"
                    style={{
                      borderBottom: idx < allocations.length - 1 ? `1px solid ${T.border}` : "none",
                    }}
                    onMouseEnter={e => e.currentTarget.style.background = "rgba(56,148,210,0.04)"}
                    onMouseLeave={e => e.currentTarget.style.background = "transparent"}
                  >
                    <span style={{ fontSize: 10, color: T.t3, fontFamily: FONTS.mono }}>{idx + 1}</span>

                    <div style={{ minWidth: 0 }}>
                      <div style={{ fontFamily: FONTS.display, fontWeight: 700, fontSize: 13, color: T.t1 }}>{a.symbol}</div>
                      <div style={{ fontSize: 10, color: T.t3, marginTop: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{a.name}</div>
                    </div>

                    <span className="pa-col-class" style={{
                      fontSize: 9, fontFamily: FONTS.display, fontWeight: 700,
                      color: clr, background: `${clr}12`,
                      padding: "2px 6px", borderRadius: 3, border: `1px solid ${clr}25`,
                      whiteSpace: "nowrap", overflow: "hidden",
                    }}>
                      {(a.asset_class || "")
                        .replace("Infrastructure", "Infra")
                        .replace("Commodity", "Cmdty")
                        .replace("US Equity", "Equity")
                        .replace("US Bond", "Bond")}
                    </span>

                    <span style={{
                      textAlign: "right", fontFamily: FONTS.mono, fontSize: 13,
                      color: (a.cis_score || 0) >= 65 ? T.green : (a.cis_score || 0) >= 50 ? T.blue : T.amber,
                    }}>
                      {(a.cis_score || 0).toFixed(1)}
                    </span>

                    <span style={{ textAlign: "right", fontFamily: FONTS.mono, fontWeight: 700, fontSize: 12, color: T.t1 }}>
                      {a.grade}
                    </span>

                    <span className="pa-col-signal-hide" style={{
                      textAlign: "right", fontSize: 9, fontFamily: FONTS.display,
                      fontWeight: 700, color: sigClr, letterSpacing: "0.04em",
                    }}>
                      {(a.signal || "")
                        .replace("STRONG OUTPERFORM", "STR OUTPERF")
                        .replace("OUTPERFORM", "OUTPERFORM")
                        .replace("UNDERPERFORM", "UNDERPERF")}
                    </span>

                    {/* Weight: bar + % */}
                    <div style={{ display: "flex", alignItems: "center", gap: 8, justifyContent: "flex-end" }}>
                      <div style={{ flex: 1, height: 4, background: "rgba(255,255,255,0.06)", borderRadius: 2, overflow: "hidden", maxWidth: 44 }}>
                        <div style={{
                          height: "100%", borderRadius: 2,
                          width: `${(a.weight / allocations[0].weight) * 100}%`,
                          background: `linear-gradient(90deg, ${clr}70, ${clr}bb)`,
                          transition: "width 0.4s ease",
                        }} />
                      </div>
                      <span style={{ fontFamily: FONTS.mono, fontWeight: 700, fontSize: 13, color: T.t1, flexShrink: 0 }}>
                        {(a.weight * 100).toFixed(1)}%
                      </span>
                    </div>
                  </div>
                );
              })}
              </div>

              {/* Footer */}
              <div style={{
                padding: "9px 16px", background: "rgba(0,0,0,0.14)",
                display: "flex", justifyContent: "space-between", alignItems: "center",
              }}>
                <span style={{ fontSize: 9, color: T.t3, fontFamily: FONTS.body }}>
                  {strategy} · {PRESETS[preset].label} · {allocations.length} positions
                </span>
                <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                  <span style={{ fontSize: 9, color: T.t3, fontFamily: FONTS.mono }}>
                    Σ {(allocations.reduce((s, a) => s + a.weight, 0) * 100).toFixed(1)}%
                  </span>
                  <button
                    onClick={exportCSV}
                    title="Export allocation as CSV"
                    style={{
                      padding: "3px 9px", borderRadius: 4, cursor: "pointer",
                      border: `1px solid rgba(200,168,75,0.25)`,
                      background: "rgba(200,168,75,0.06)",
                      color: "#C8A84B", fontSize: 9,
                      fontFamily: FONTS.display, fontWeight: 700,
                      letterSpacing: "0.06em", transition: "all 0.15s",
                    }}
                  >
                    ↓ CSV
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* Disclaimer */}
          <div style={{
            padding: "9px 12px", borderRadius: 6,
            background: "rgba(200,168,75,0.04)", border: "1px solid rgba(200,168,75,0.10)",
            fontSize: 10, color: T.t3, fontFamily: FONTS.body, lineHeight: 1.6,
          }}>
            ⚖ Algorithmic weights derived from CIS scores. Not investment advice.
            Signals use positioning language only (OUTPERFORM / NEUTRAL / UNDERPERFORM / UNDERWEIGHT).
          </div>
        </div>
      </div>
    </div>
  );
}

const labelStyle = {
  fontSize: 9, color: T.t3, fontFamily: FONTS.display,
  letterSpacing: "0.12em", textTransform: "uppercase", marginBottom: 10,
};
