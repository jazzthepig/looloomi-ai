/**
 * CISAssetDetail — full-page deep dive for a single asset.
 *
 * Props:
 *   symbol      {string}   — ticker (BTC, SPY, MKR…)
 *   onBack      {fn}       — called when user clicks ← Back
 *   onNavigate  {fn}       — parent navigate fn (to jump to Compare etc.)
 */

import { useState, useEffect } from "react";
import { T, FONTS, sigStyle } from "../tokens";

const API = import.meta.env.VITE_API_URL || "";

/* ─── tiny helpers ─────────────────────────────────────────────────── */
const fmt = (v, d = 1) => (v == null || isNaN(v)) ? "—" : v.toFixed(d);
const fmtPct = (v) => v == null ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(1)}%`;
const fmtPrice = (p) => {
  if (!p) return "—";
  if (p >= 1000) return `$${p.toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
  if (p >= 1)    return `$${p.toFixed(2)}`;
  return `$${p.toFixed(4)}`;
};
const fmtCap = (v) => {
  if (!v || v === 0) return "—";
  if (v >= 1e12) return `$${(v / 1e12).toFixed(2)}T`;
  if (v >= 1e9)  return `$${(v / 1e9).toFixed(2)}B`;
  if (v >= 1e6)  return `$${(v / 1e6).toFixed(1)}M`;
  return `$${v.toLocaleString()}`;
};
const clr = (v) => v > 0 ? T.green : v < 0 ? T.red : T.t3;

const PILLAR_META = {
  F: { label: "Fundamental",            desc: "Revenue, TVL, protocol activity, market size" },
  M: { label: "Momentum",               desc: "Price velocity, trend, 7d/30d performance" },
  O: { label: "On-chain / Risk",        desc: "Liquidity depth, open interest, funding rate" },
  S: { label: "Sentiment",              desc: "Fear & Greed, social flow, volatility regime" },
  A: { label: "Alpha",                  desc: "BTC/SPY divergence, relative strength" },
};

const GRADE_COLOR = {
  "A+": T.green, "A": T.green, "B+": T.cyan, "B": T.cyan,
  "C+": T.gold,  "C": T.gold,  "D": T.red,   "F": T.red,
};

/* ─── sparkline ─────────────────────────────────────────────────────── */
const Spark = ({ scores, w = 120, h = 36 }) => {
  if (!scores || scores.length < 2) return null;
  const min = Math.min(...scores);
  const max = Math.max(...scores);
  const rng = max - min || 1;
  const pts = scores.map((v, i) => {
    const x = 4 + (i / (scores.length - 1)) * (w - 8);
    const y = 4 + (h - 8) - ((v - min) / rng) * (h - 8);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  const last = scores[scores.length - 1], first = scores[0];
  const col = last > first + 0.5 ? T.cyan : last < first - 0.5 ? "#FF3D5A" : T.t3;
  return (
    <svg width={w} height={h} style={{ display: "block" }}>
      <polyline points={pts} fill="none" stroke={col} strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
};

/* ─── pillar bar ─────────────────────────────────────────────────────── */
const PillarBar = ({ pillar, score, desc }) => {
  const { label } = PILLAR_META[pillar] || { label: pillar };
  const pct = Math.max(0, Math.min(100, score ?? 0));
  const barClr = pct >= 65 ? T.cyan : pct >= 45 ? T.gold : T.red;
  return (
    <div style={{ marginBottom: 16 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{
            fontFamily: FONTS.mono, fontSize: 10, fontWeight: 700, color: barClr,
            background: `${barClr}18`, border: `1px solid ${barClr}40`,
            borderRadius: 4, padding: "1px 6px",
          }}>{pillar}</span>
          <span style={{ fontFamily: FONTS.display, fontSize: 11, color: T.t2, fontWeight: 600 }}>{label}</span>
        </div>
        <span style={{ fontFamily: FONTS.mono, fontSize: 13, fontWeight: 700, color: barClr }}>
          {score != null ? score.toFixed(1) : "—"}
        </span>
      </div>
      <div style={{ height: 4, background: "rgba(255,255,255,0.06)", borderRadius: 2, overflow: "hidden" }}>
        <div style={{
          height: "100%", width: `${pct}%`,
          background: `linear-gradient(90deg, ${barClr}99, ${barClr})`,
          borderRadius: 2, transition: "width 0.6s ease",
        }} />
      </div>
      {desc && (
        <p style={{ fontFamily: FONTS.body, fontSize: 10, color: T.t4, marginTop: 4, marginBottom: 0 }}>{desc}</p>
      )}
    </div>
  );
};

/* ─── stat card ─────────────────────────────────────────────────────── */
const Stat = ({ label, value, sub, color }) => (
  <div style={{
    background: "rgba(5,7,22,0.85)", border: `1px solid ${T.border}`,
    borderRadius: 8, padding: "12px 16px",
  }}>
    <div style={{ fontFamily: FONTS.display, fontSize: 10, color: T.t3, fontWeight: 600,
      letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 4 }}>{label}</div>
    <div style={{ fontFamily: FONTS.mono, fontSize: 18, fontWeight: 700,
      color: color || T.t1, letterSpacing: "-0.01em" }}>{value}</div>
    {sub && <div style={{ fontFamily: FONTS.mono, fontSize: 10, color: T.t3, marginTop: 2 }}>{sub}</div>}
  </div>
);

/* ─── main component ─────────────────────────────────────────────────── */
export default function CISAssetDetail({ symbol, onBack, onNavigate }) {
  const [asset, setAsset]       = useState(null);
  const [history, setHistory]   = useState([]);
  const [loading, setLoading]   = useState(true);
  const [error, setError]       = useState(null);

  useEffect(() => {
    if (!symbol) return;
    setLoading(true); setError(null);

    Promise.all([
      fetch(`${API}/api/v1/cis/asset/${symbol}`).then(r => r.json()),
      fetch(`${API}/api/v1/cis/history/batch?symbols=${symbol}&days=30`)
        .then(r => r.json()).catch(() => ({})),
    ]).then(([assetData, histData]) => {
      if (assetData.error) throw new Error(assetData.error);
      setAsset(assetData);
      // Extract score history for sparkline
      const hist = histData[symbol] || histData[symbol?.toLowerCase()] || [];
      setHistory(hist.map(h => h.score || h.cis_score || 0).filter(Boolean));
    }).catch(e => setError(e.message))
      .finally(() => setLoading(false));
  }, [symbol]);

  if (loading) return (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: 400 }}>
      <span style={{ fontFamily: FONTS.mono, fontSize: 12, color: T.t3 }}>Loading {symbol}…</span>
    </div>
  );

  if (error || !asset) return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 16, padding: 64 }}>
      <span style={{ fontFamily: FONTS.mono, fontSize: 12, color: T.red }}>
        {error || "Asset not found"}
      </span>
      <button onClick={onBack} style={backBtnStyle}>← Back</button>
    </div>
  );

  /* ── normalise fields (T1 / T2 shape) ── */
  const sym     = asset.symbol || asset.asset_id || symbol;
  const name    = asset.name || sym;
  const cls     = asset.asset_class || "—";
  const score   = asset.cis_score ?? asset.score ?? 0;
  const rawScore= asset.raw_cis_score ?? score;
  const grade   = asset.grade || "—";
  const signal  = asset.signal || "NEUTRAL";
  const tier    = asset.data_tier ?? 2;
  const regime  = asset.macro_regime || "—";
  const conf    = asset.confidence ?? 0;
  const las     = asset.las ?? 0;

  const pillars = asset.pillars || {
    F: asset.f ?? asset.pillar_f,
    M: asset.m ?? asset.pillar_m,
    O: asset.o ?? asset.pillar_o,
    S: asset.s ?? asset.pillar_s,
    A: asset.a ?? asset.pillar_a,
  };

  const price   = asset.price || 0;
  const ch24    = asset.change_24h ?? null;
  const ch7d    = asset.change_7d  ?? null;
  const ch30d   = asset.change_30d ?? null;
  const mcap    = asset.market_cap || 0;
  const vol     = asset.volume_24h || 0;

  const sig = sigStyle(signal);
  const gradeClr = GRADE_COLOR[grade] || T.t3;

  return (
    <div style={{ maxWidth: 920, margin: "0 auto" }}>

      {/* ── Back + header ── */}
      <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 28 }}>
        <button onClick={onBack} style={backBtnStyle}>← Back</button>
        <div style={{
          width: 1, height: 24, background: T.border,
        }} />
        <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
          <span style={{ fontFamily: FONTS.brand, fontSize: 24, fontWeight: 800,
            color: T.t1, letterSpacing: "0.02em" }}>{sym}</span>
          <span style={{ fontFamily: FONTS.body, fontSize: 14, color: T.t3 }}>{name}</span>
        </div>

        <div style={{ marginLeft: "auto", display: "flex", gap: 8, alignItems: "center" }}>
          {/* Tier badge */}
          <span style={{
            fontFamily: FONTS.mono, fontSize: 9, fontWeight: 700, letterSpacing: "0.08em",
            padding: "3px 8px", borderRadius: 4,
            ...(tier === 1
              ? { color: T.cyan,  background: "rgba(6,182,212,0.12)", border: "1px solid rgba(6,182,212,0.28)" }
              : { color: T.gold,  background: "rgba(212,168,67,0.12)", border: "1px solid rgba(212,168,67,0.28)" }),
          }}>
            {tier === 1 ? "CIS PRO · T1" : "CIS MKT · T2"}
          </span>

          {/* Asset class */}
          <span style={{
            fontFamily: FONTS.mono, fontSize: 9, color: T.t3,
            background: "rgba(255,255,255,0.04)", border: `1px solid ${T.border}`,
            borderRadius: 4, padding: "3px 8px", letterSpacing: "0.08em",
          }}>{cls.toUpperCase()}</span>

          {/* Compare button */}
          {onNavigate && (
            <button
              onClick={() => onNavigate("cis.compare", sym)}
              style={{
                fontFamily: FONTS.display, fontSize: 10, fontWeight: 700,
                color: T.indigo, background: "rgba(99,102,241,0.10)",
                border: "1px solid rgba(99,102,241,0.30)",
                borderRadius: 6, padding: "5px 12px", cursor: "pointer",
                letterSpacing: "0.04em",
              }}>
              Compare →
            </button>
          )}
        </div>
      </div>

      {/* ── Hero row: CIS + Grade + Signal + LAS ── */}
      <div style={{
        display: "grid", gridTemplateColumns: "1fr 1fr 1fr 1fr",
        gap: 12, marginBottom: 24,
      }} className="asset-stat-grid">
        <Stat
          label="CIS Score"
          value={fmt(score)}
          sub={rawScore !== score ? `Raw ${fmt(rawScore)}` : `Regime-adj.`}
          color={gradeClr}
        />
        <Stat
          label="Grade"
          value={grade}
          sub={`${fmt(score, 1)} / 100`}
          color={gradeClr}
        />
        <Stat
          label="Signal"
          value={signal.replace("_", " ")}
          color={sig.color}
        />
        <Stat
          label="LAS"
          value={fmt(las, 1)}
          sub={`Confidence ${(conf * 100).toFixed(0)}%`}
          color={las >= 40 ? T.cyan : las >= 20 ? T.gold : T.red}
        />
      </div>

      {/* ── Price row ── */}
      <div style={{
        display: "grid", gridTemplateColumns: "repeat(5,1fr)",
        gap: 12, marginBottom: 28,
      }} className="asset-stat-grid">
        <Stat label="Price"     value={fmtPrice(price)} />
        <Stat label="24H"       value={fmtPct(ch24)} color={clr(ch24)} />
        <Stat label="7D"        value={fmtPct(ch7d)}  color={clr(ch7d)}  />
        <Stat label="30D"       value={fmtPct(ch30d)} color={clr(ch30d)} />
        <Stat label="Mkt Cap"   value={fmtCap(mcap)} />
      </div>

      {/* ── Body: Pillars + Sidebar ── */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 320px", gap: 24 }}
           className="asset-body-grid">

        {/* Left: Pillar breakdown */}
        <div style={{
          background: "rgba(5,7,22,0.85)", border: `1px solid ${T.border}`,
          borderRadius: 10, padding: 24,
        }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20 }}>
            <h3 style={{ fontFamily: FONTS.brand, fontSize: 14, fontWeight: 700,
              color: T.t1, margin: 0, letterSpacing: "0.04em" }}>PILLAR BREAKDOWN</h3>
            <span style={{ fontFamily: FONTS.mono, fontSize: 10, color: T.t3 }}>
              v4.1 · {tier === 1 ? "Full-model score" : "Market estimate"}
            </span>
          </div>

          {["F", "M", "O", "S", "A"].map(p => (
            <PillarBar
              key={p}
              pillar={p}
              score={pillars[p]}
              desc={PILLAR_META[p]?.desc}
            />
          ))}

          {/* LAS explanation */}
          <div style={{
            marginTop: 20, padding: "12px 14px",
            background: "rgba(6,182,212,0.05)", border: "1px solid rgba(6,182,212,0.14)",
            borderRadius: 6,
          }}>
            <div style={{ fontFamily: FONTS.display, fontSize: 10, color: T.cyan,
              fontWeight: 700, letterSpacing: "0.08em", marginBottom: 4 }}>
              LIQUIDITY-ADJUSTED SCORE (LAS)
            </div>
            <div style={{ fontFamily: FONTS.body, fontSize: 11, color: T.t3, lineHeight: 1.5 }}>
              LAS = CIS × liquidity multiplier × spread penalty × confidence.
              Adjusts the raw score for realistic position sizing given available market depth.
            </div>
            {asset.las_params && (
              <div style={{ marginTop: 8, display: "flex", gap: 16, flexWrap: "wrap" }}>
                {Object.entries({
                  "Liq. mult.":   asset.las_params.liquidity_multiplier?.toFixed(2),
                  "Spread pen.":  asset.las_params.spread_penalty?.toFixed(2),
                  "Tradeable/d":  fmtCap(asset.las_params.daily_tradeable_usd),
                }).map(([k, v]) => v != null && (
                  <div key={k} style={{ fontFamily: FONTS.mono, fontSize: 10, color: T.t3 }}>
                    <span style={{ color: T.t4 }}>{k} </span>{v}
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Right: Sidebar */}
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>

          {/* Score history sparkline */}
          {history.length >= 2 && (
            <div style={{
              background: "rgba(5,7,22,0.85)", border: `1px solid ${T.border}`,
              borderRadius: 10, padding: 20,
            }}>
              <div style={{ fontFamily: FONTS.display, fontSize: 10, color: T.t3,
                fontWeight: 700, letterSpacing: "0.08em", marginBottom: 12 }}>
                30D SCORE HISTORY
              </div>
              <Spark scores={history} w={280} h={60} />
              <div style={{ display: "flex", justifyContent: "space-between", marginTop: 6 }}>
                <span style={{ fontFamily: FONTS.mono, fontSize: 9, color: T.t4 }}>30d ago</span>
                <span style={{ fontFamily: FONTS.mono, fontSize: 9, color: T.t4 }}>Today</span>
              </div>
            </div>
          )}

          {/* Macro context */}
          <div style={{
            background: "rgba(5,7,22,0.85)", border: `1px solid ${T.border}`,
            borderRadius: 10, padding: 20,
          }}>
            <div style={{ fontFamily: FONTS.display, fontSize: 10, color: T.t3,
              fontWeight: 700, letterSpacing: "0.08em", marginBottom: 14 }}>
              CONTEXT
            </div>
            {[
              ["Macro Regime",   regime.replace(/_/g, " ")],
              ["Data Tier",      tier === 1 ? "T1 · Full Engine" : "T2 · Market Est."],
              ["Confidence",     `${(conf * 100).toFixed(0)}%`],
              ["Volume 24H",     fmtCap(vol)],
              ["Score ∆ 7D",     fmtPct(asset.score_change_7d)],
              ["Score ∆ 30D",    fmtPct(asset.score_change_30d)],
              ["Vol 30D",        asset.volatility_30d ? `${(asset.volatility_30d * 100).toFixed(1)}%` : "—"],
            ].map(([label, value]) => (
              <div key={label} style={{
                display: "flex", justifyContent: "space-between", alignItems: "center",
                padding: "7px 0", borderBottom: `1px solid ${T.border}`,
              }}>
                <span style={{ fontFamily: FONTS.body, fontSize: 11, color: T.t3 }}>{label}</span>
                <span style={{ fontFamily: FONTS.mono, fontSize: 11, color: T.t2 }}>{value}</span>
              </div>
            ))}
          </div>

          {/* Signal badge */}
          <div style={{
            background: `${sig.bg}`, border: `1px solid ${sig.border}`,
            borderRadius: 10, padding: 20, textAlign: "center",
          }}>
            <div style={{ fontFamily: FONTS.mono, fontSize: 9, color: sig.color,
              fontWeight: 700, letterSpacing: "0.1em", marginBottom: 6 }}>
              CIS POSITIONING SIGNAL
            </div>
            <div style={{ fontFamily: FONTS.brand, fontSize: 16, fontWeight: 800,
              color: sig.color, letterSpacing: "0.04em" }}>
              {signal.replace(/_/g, " ")}
            </div>
            <div style={{ fontFamily: FONTS.body, fontSize: 10, color: T.t4,
              marginTop: 8, lineHeight: 1.4 }}>
              Quantitative positioning indicator only.
              Not investment advice. CometCloud is not a licensed investment advisor.
            </div>
          </div>
        </div>
      </div>

      {/* ── Responsive styles ── */}
      <style>{`
        @media (max-width: 800px) {
          .asset-stat-grid { grid-template-columns: 1fr 1fr !important; }
          .asset-body-grid { grid-template-columns: 1fr !important; }
        }
        @media (max-width: 480px) {
          .asset-stat-grid { grid-template-columns: 1fr !important; }
        }
      `}</style>
    </div>
  );
}

const backBtnStyle = {
  fontFamily: FONTS.display, fontSize: 11, fontWeight: 700,
  color: T.t3, background: "transparent", border: `1px solid ${T.border}`,
  borderRadius: 6, padding: "6px 12px", cursor: "pointer",
  letterSpacing: "0.04em", flexShrink: 0,
};
