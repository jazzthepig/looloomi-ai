/**
 * MultiFactorStrategies — Factor-weight visualization + live strategy universe
 *
 * Shows each strategy's pillar weight profile, regime fitness, and top qualifying
 * assets scored with that strategy's factor weights.
 *
 * Tabs: Strategy Cards → live factor bars + fitness
 *        Universe      → top qualifying assets for selected strategy
 *        Compare       → side-by-side weight chart for all strategies
 */
import { useState, useEffect, useCallback } from "react";
import { T, FONTS as F } from "../tokens";

const API_BASE = "/api/v1";

/* ── Color config ──────────────────────────────────────────────────────────── */
const PILLAR_COLORS = { F: "#10B981", M: "#06B6D4", O: "#8B5CF6", S: "#F59E0B", A: "#F43F5E" };
const PILLAR_LABELS = { F: "Fundamental", M: "Momentum", O: "On-Chain", S: "Sentiment", A: "Alpha" };
const GRADE_C = { "A+": "#10B981", A: "#10B981", "B+": "#6366f1", B: "#6366f1", "C+": "#F59E0B", C: "#F59E0B", D: "#F87171", F: "#EF4444" };
const SIG_C = {
  "STRONG OUTPERFORM": { color: "#10B981", bg: "rgba(16,185,129,0.08)", border: "rgba(16,185,129,0.2)" },
  "OUTPERFORM":        { color: "#00D98A", bg: "rgba(0,217,138,0.06)", border: "rgba(0,217,138,0.16)" },
  "NEUTRAL":           { color: "#F59E0B", bg: "rgba(245,158,11,0.06)", border: "rgba(245,158,11,0.16)" },
  "UNDERPERFORM":      { color: "#F87171", bg: "rgba(248,113,113,0.06)", border: "rgba(248,113,113,0.16)" },
  "UNDERWEIGHT":       { color: "#EF4444", bg: "rgba(239,68,68,0.06)", border: "rgba(239,68,68,0.16)" },
};

const FITNESS_COLOR = (v) => v >= 75 ? "#10B981" : v >= 55 ? "#F59E0B" : "#EF4444";
const FITNESS_LABEL = (v) => v >= 75 ? "HIGH FIT" : v >= 55 ? "MODERATE" : "LOW FIT";

/* ── Factor Weight Bar ─────────────────────────────────────────────────────── */
function PillarBar({ pillar, weight, score, showScore = false }) {
  const color = PILLAR_COLORS[pillar];
  const pct = Math.round(weight * 100);
  return (
    <div style={{ marginBottom: 6 }}>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 3, alignItems: "center" }}>
        <span style={{ fontFamily: F.mono, fontSize: 9, color, letterSpacing: "0.06em", fontWeight: 700 }}>
          {pillar} — {PILLAR_LABELS[pillar]}
        </span>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          {showScore && score != null && (
            <span style={{ fontFamily: F.mono, fontSize: 10, color: T.t2, fontWeight: 500 }}>
              {Math.round(score)}
            </span>
          )}
          <span style={{ fontFamily: F.mono, fontSize: 10, color, fontWeight: 700 }}>{pct}%</span>
        </div>
      </div>
      <div style={{ height: 4, background: "rgba(255,255,255,0.06)", borderRadius: 2, overflow: "hidden" }}>
        <div style={{
          height: "100%", width: `${pct}%`, background: color,
          borderRadius: 2, transition: "width 0.5s ease",
          boxShadow: `0 0 6px ${color}44`,
        }} />
      </div>
    </div>
  );
}

/* ── Strategy Fitness Meter ────────────────────────────────────────────────── */
function FitnessMeter({ fitness, regime }) {
  const color = FITNESS_COLOR(fitness);
  return (
    <div style={{ marginTop: 12 }}>
      <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4, alignItems: "center" }}>
        <span style={{ fontFamily: F.mono, fontSize: 9, color: T.t3, letterSpacing: "0.10em" }}>
          REGIME FITNESS · {regime?.toUpperCase() || "NEUTRAL"}
        </span>
        <span style={{ fontFamily: F.mono, fontSize: 9, fontWeight: 700, color, letterSpacing: "0.08em" }}>
          {FITNESS_LABEL(fitness)} {fitness}/100
        </span>
      </div>
      <div style={{ height: 3, background: "rgba(255,255,255,0.06)", borderRadius: 2, overflow: "hidden" }}>
        <div style={{
          height: "100%", width: `${fitness}%`, borderRadius: 2,
          background: `linear-gradient(90deg, ${color}88, ${color})`,
          transition: "width 0.6s ease",
        }} />
      </div>
    </div>
  );
}

/* ── Strategy Card ─────────────────────────────────────────────────────────── */
function StrategyCard({ s, selected, onSelect, regime }) {
  const isSelected = selected === s.id;
  const color = s.color || T.cyan;
  return (
    <div
      onClick={() => onSelect(s.id)}
      style={{
        background: isSelected
          ? `linear-gradient(135deg, rgba(5,7,22,0.96) 0%, ${color}08 100%)`
          : "rgba(5,7,22,0.88)",
        border: `1px solid ${isSelected ? color + "40" : "rgba(255,255,255,0.07)"}`,
        borderRadius: 10, padding: "18px 20px", cursor: "pointer",
        transition: "all 0.25s ease",
        boxShadow: isSelected ? `0 0 18px ${color}18` : "none",
        flex: "1 1 0", minWidth: 0,
      }}
    >
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 14 }}>
        <span style={{ fontSize: 18, lineHeight: 1 }}>{s.icon}</span>
        <div style={{ minWidth: 0 }}>
          <div style={{ fontFamily: F.display, fontSize: 15, fontWeight: 700, color: T.t1, lineHeight: 1.2 }}>
            {s.name}
          </div>
          <div style={{ fontFamily: F.mono, fontSize: 9, color, letterSpacing: "0.10em", marginTop: 2, textTransform: "uppercase" }}>
            {s.subtitle}
          </div>
        </div>
        {isSelected && (
          <span style={{ marginLeft: "auto", fontFamily: F.mono, fontSize: 9, color, fontWeight: 700,
            letterSpacing: "0.08em", background: `${color}14`, padding: "2px 8px", borderRadius: 3 }}>
            ACTIVE
          </span>
        )}
      </div>

      {/* Description */}
      <div style={{ fontFamily: F.body, fontSize: 12, color: T.t3, lineHeight: 1.6, marginBottom: 14 }}>
        {s.description}
      </div>

      {/* Pillar weights */}
      <div>
        {["F", "M", "O", "S", "A"].map(p => (
          <PillarBar key={p} pillar={p} weight={s.pillar_weights[p] || 0} />
        ))}
      </div>

      {/* Fitness */}
      <FitnessMeter fitness={s.strategy_fitness} regime={s.current_regime || regime} />

      {/* Meta */}
      <div style={{
        marginTop: 12, paddingTop: 10,
        borderTop: "1px solid rgba(255,255,255,0.05)",
        display: "flex", gap: 16, flexWrap: "wrap",
      }}>
        <div>
          <div style={{ fontFamily: F.mono, fontSize: 9, color: T.t3, letterSpacing: "0.08em" }}>RISK</div>
          <div style={{ fontFamily: F.mono, fontSize: 10, color: T.t2, marginTop: 2, fontWeight: 600, textTransform: "uppercase" }}>
            {s.risk_profile}
          </div>
        </div>
        <div>
          <div style={{ fontFamily: F.mono, fontSize: 9, color: T.t3, letterSpacing: "0.08em" }}>HOLD</div>
          <div style={{ fontFamily: F.mono, fontSize: 10, color: T.t2, marginTop: 2 }}>{s.target_hold_days}d</div>
        </div>
        <div style={{ marginLeft: "auto" }}>
          <div style={{ fontFamily: F.mono, fontSize: 9, color: T.t3, letterSpacing: "0.08em" }}>FREQTRADE</div>
          <div style={{ fontFamily: F.mono, fontSize: 9, color: color, marginTop: 2, opacity: 0.75 }}>
            {s.freqtrade_class}
          </div>
        </div>
      </div>
    </div>
  );
}

/* ── Universe Table Row ────────────────────────────────────────────────────── */
function AssetRow({ a, rank, strategyColor }) {
  const grade = a.strategy_grade || "C";
  const sig = a.strategy_signal || "NEUTRAL";
  const sc = SIG_C[sig] || SIG_C["NEUTRAL"];
  const gc = GRADE_C[grade] || T.t3;
  const qualifies = a.qualifies;
  const exposure = a.factor_exposure || {};
  const topFactor = Object.entries(exposure).sort(([,va], [,vb]) => vb - va)[0];

  return (
    <div style={{
      display: "grid",
      gridTemplateColumns: "28px 56px 1fr 60px 52px 52px 52px 70px",
      alignItems: "center", padding: "8px 12px",
      borderBottom: "1px solid rgba(255,255,255,0.03)",
      opacity: qualifies ? 1 : 0.5,
      transition: "opacity 0.2s",
    }}>
      <span style={{ fontFamily: F.mono, fontSize: 9, color: T.t3, textAlign: "center" }}>{rank}</span>

      {/* Symbol + tier */}
      <div>
        <div style={{ fontFamily: F.display, fontSize: 12, fontWeight: 700, color: T.t1 }}>{a.symbol}</div>
        {a.data_tier === 1 && (
          <span style={{ fontFamily: F.mono, fontSize: 8, color: "#00E87A", letterSpacing: "0.04em" }}>T1</span>
        )}
      </div>

      {/* Asset class + dominant factor */}
      <div>
        <div style={{ fontFamily: F.mono, fontSize: 9, color: T.t3, letterSpacing: "0.06em" }}>
          {a.asset_class}
        </div>
        {topFactor && (
          <div style={{ fontFamily: F.mono, fontSize: 9, color: PILLAR_COLORS[topFactor[0]], marginTop: 1 }}>
            ↑ {PILLAR_LABELS[topFactor[0]]} {topFactor[1].toFixed(0)}
          </div>
        )}
      </div>

      {/* Strategy CIS */}
      <div style={{ textAlign: "right" }}>
        <div style={{ fontFamily: F.mono, fontSize: 13, fontWeight: 600, color: gc }}>
          {a.strategy_cis?.toFixed(1)}
        </div>
        <div style={{ fontFamily: F.mono, fontSize: 9, color: gc, opacity: 0.7 }}>{grade}</div>
      </div>

      {/* Pillar scores F/M/O */}
      <div style={{ textAlign: "right" }}>
        <div style={{ fontFamily: F.mono, fontSize: 9, color: PILLAR_COLORS.F }}>{(a.pillar_scores?.F || 0).toFixed(0)}</div>
        <div style={{ fontFamily: F.mono, fontSize: 9, color: T.t3, opacity: 0.5, letterSpacing: ".06em" }}>F</div>
      </div>
      <div style={{ textAlign: "right" }}>
        <div style={{ fontFamily: F.mono, fontSize: 9, color: PILLAR_COLORS.M }}>{(a.pillar_scores?.M || 0).toFixed(0)}</div>
        <div style={{ fontFamily: F.mono, fontSize: 9, color: T.t3, opacity: 0.5, letterSpacing: ".06em" }}>M</div>
      </div>
      <div style={{ textAlign: "right" }}>
        <div style={{ fontFamily: F.mono, fontSize: 9, color: PILLAR_COLORS.S }}>{(a.pillar_scores?.S || 0).toFixed(0)}</div>
        <div style={{ fontFamily: F.mono, fontSize: 9, color: T.t3, opacity: 0.5, letterSpacing: ".06em" }}>S</div>
      </div>

      {/* Signal */}
      <div style={{ textAlign: "right" }}>
        <span style={{
          fontFamily: F.mono, fontSize: 9, fontWeight: 700, letterSpacing: "0.04em",
          color: sc.color, background: sc.bg, border: `1px solid ${sc.border}`,
          padding: "2px 5px", borderRadius: 3, display: "inline-block",
          whiteSpace: "nowrap",
        }}>
          {sig === "STRONG OUTPERFORM" ? "STR.OUTPERF" : sig}
        </span>
        {qualifies && (
          <div style={{ fontFamily: F.mono, fontSize: 8, color: strategyColor, marginTop: 2, opacity: 0.75 }}>
            ✓ ENTRY
          </div>
        )}
      </div>
    </div>
  );
}

/* ── Compare Bar Chart (SVG) ───────────────────────────────────────────────── */
function CompareChart({ strategies }) {
  const pillars = ["F", "M", "O", "S", "A"];
  const ids = Object.keys(strategies);
  const barW = 14, gap = 4, groupGap = 20;
  const groupW = ids.length * (barW + gap) - gap;
  const chartW = pillars.length * (groupW + groupGap) - groupGap + 60;
  const chartH = 140;
  const maxVal = 50; // max weight is 50%

  return (
    <div style={{ overflowX: "auto", paddingTop: 8 }}>
      <svg width={chartW} height={chartH + 40} style={{ display: "block", minWidth: chartW }}>
        {/* Y-axis gridlines */}
        {[10, 20, 30, 40, 50].map(v => {
          const y = chartH - (v / maxVal) * chartH;
          return (
            <g key={v}>
              <line x1={30} y1={y} x2={chartW - 10} y2={y}
                stroke="rgba(255,255,255,0.05)" strokeDasharray="3,4" />
              <text x={25} y={y + 4} textAnchor="end"
                style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 9, fill: "rgba(199,210,254,0.3)" }}>
                {v}%
              </text>
            </g>
          );
        })}

        {/* Bars */}
        {pillars.map((p, pi) => {
          const gx = 35 + pi * (groupW + groupGap);
          return (
            <g key={p}>
              {/* Pillar label */}
              <text x={gx + groupW / 2} y={chartH + 18} textAnchor="middle"
                style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 10, fill: PILLAR_COLORS[p], fontWeight: 700 }}>
                {p}
              </text>
              <text x={gx + groupW / 2} y={chartH + 30} textAnchor="middle"
                style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 8, fill: "rgba(199,210,254,0.3)" }}>
                {PILLAR_LABELS[p].slice(0, 6)}
              </text>

              {/* Strategy bars */}
              {ids.map((sid, si) => {
                const s = strategies[sid];
                const w = s.weights[p] || 0;
                const barH = (w / maxVal) * chartH;
                const x = gx + si * (barW + gap);
                const y = chartH - barH;
                return (
                  <g key={sid}>
                    <rect x={x} y={y} width={barW} height={barH}
                      fill={s.color} opacity={0.75} rx={2} />
                    {barH > 14 && (
                      <text x={x + barW / 2} y={y + 12} textAnchor="middle"
                        style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 8, fill: "rgba(255,255,255,0.7)" }}>
                        {Math.round(w * 100)}
                      </text>
                    )}
                  </g>
                );
              })}
            </g>
          );
        })}
      </svg>

      {/* Legend */}
      <div style={{ display: "flex", gap: 16, marginTop: 8, flexWrap: "wrap" }}>
        {ids.map(sid => (
          <div key={sid} style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <div style={{ width: 10, height: 10, borderRadius: 2, background: strategies[sid].color }} />
            <span style={{ fontFamily: F.mono, fontSize: 9, color: T.t2 }}>{strategies[sid].name}</span>
            <span style={{ fontFamily: F.mono, fontSize: 9, color: strategies[sid].color, opacity: 0.75 }}>
              {strategies[sid].fitness}/100
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ══════════════════════════════════════════════════════════════════════════════
   Main Component
   ══════════════════════════════════════════════════════════════════════════════ */
export default function MultiFactorStrategies() {
  const [strategies, setStrategies] = useState([]);
  const [selectedId, setSelectedId]  = useState("breakout");
  const [activeTab, setActiveTab]    = useState("cards"); // cards | universe | compare
  const [universe, setUniverse]      = useState(null);
  const [compare, setCompare]        = useState(null);
  const [loading, setLoading]        = useState(true);
  const [uniLoading, setUniLoading]  = useState(false);
  const [error, setError]            = useState(null);
  const [regime, setRegime]          = useState("Neutral");

  // Fetch strategy list
  useEffect(() => {
    setLoading(true);
    const ctrl = new AbortController();
    const timeout = setTimeout(() => ctrl.abort(), 20_000);
    fetch(`${API_BASE}/strategies`, { signal: ctrl.signal })
      .then(r => r.json())
      .then(d => {
        setStrategies(d.strategies || []);
        setRegime(d.current_regime || "Neutral");
        setError(null);
      })
      .catch(e => {
        if (e.name !== "AbortError") setError(e.message);
      })
      .finally(() => { clearTimeout(timeout); setLoading(false); });
    return () => { clearTimeout(timeout); ctrl.abort(); };
  }, []);

  // Fetch universe for selected strategy
  const fetchUniverse = useCallback((stratId) => {
    setUniLoading(true);
    const ctrl = new AbortController();
    const timeout = setTimeout(() => ctrl.abort(), 25_000);
    fetch(`${API_BASE}/strategies/${stratId}/universe?top_n=30`, { signal: ctrl.signal })
      .then(r => r.json())
      .then(d => setUniverse(d))
      .catch(() => {})
      .finally(() => { clearTimeout(timeout); setUniLoading(false); });
    return () => { clearTimeout(timeout); ctrl.abort(); };
  }, []);

  // Fetch compare
  const fetchCompare = useCallback(() => {
    fetch(`${API_BASE}/strategies/compare/pillar-weights`)
      .then(r => r.json())
      .then(d => {
        // Reshape for CompareChart: { id: { name, weights, color, fitness } }
        const out = {};
        for (const [sid, s] of Object.entries(d.strategies || {})) {
          out[sid] = { name: s.name, weights: s.weights, color: s.color, fitness: s.fitness };
        }
        setCompare(out);
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    if (activeTab === "universe") fetchUniverse(selectedId);
    if (activeTab === "compare" && !compare) fetchCompare();
  }, [activeTab, selectedId]);

  const selectedStrategy = strategies.find(s => s.id === selectedId);
  const strategyColor = selectedStrategy?.color || T.cyan;

  /* ── Render ─────────────────────────────────────────────────────────────── */
  return (
    <div style={{ fontFamily: F.body, color: T.t1 }}>
      {/* Header */}
      <div style={{
        display: "flex", alignItems: "center", gap: 12, marginBottom: 20,
        paddingBottom: 16, borderBottom: "1px solid rgba(255,255,255,0.06)",
      }}>
        <div style={{ width: 2, height: 18, background: T.cyan, borderRadius: 1 }} />
        <div>
          <div style={{ fontFamily: F.display, fontSize: 16, fontWeight: 700, color: T.t1 }}>
            Multi-Factor Strategies
          </div>
          <div style={{ fontFamily: F.mono, fontSize: 9, color: T.t3, letterSpacing: "0.12em", marginTop: 2 }}>
            FACTOR WEIGHTS · CIS RESCORING · REGIME FITNESS
          </div>
        </div>
        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 8 }}>
          <div style={{ fontFamily: F.mono, fontSize: 9, color: T.t3, letterSpacing: "0.10em" }}>REGIME</div>
          <div style={{
            fontFamily: F.mono, fontSize: 10, fontWeight: 700,
            color: T.amber, background: "rgba(245,158,11,0.10)",
            border: "1px solid rgba(245,158,11,0.2)",
            padding: "2px 10px", borderRadius: 3, letterSpacing: "0.08em",
          }}>
            {regime.toUpperCase()}
          </div>
        </div>
      </div>

      {/* Tab bar */}
      <div style={{ display: "flex", gap: 2, marginBottom: 20, borderBottom: "1px solid rgba(255,255,255,0.06)" }}>
        {[
          { id: "cards",    label: "Strategy Cards" },
          { id: "universe", label: "Live Universe" },
          { id: "compare",  label: "Factor Compare" },
        ].map(tab => (
          <button key={tab.id} onClick={() => setActiveTab(tab.id)} style={{
            fontFamily: F.mono, fontSize: 10, fontWeight: 600, letterSpacing: "0.08em",
            background: "none", border: "none", cursor: "pointer",
            padding: "8px 16px", borderRadius: "4px 4px 0 0",
            color: activeTab === tab.id ? strategyColor : T.t3,
            borderBottom: `2px solid ${activeTab === tab.id ? strategyColor : "transparent"}`,
            marginBottom: -1,
            transition: "color 0.2s, border-color 0.2s",
          }}>{tab.label}</button>
        ))}
      </div>

      {/* ── TAB: Strategy Cards ─────────────────────────────────────────────── */}
      {activeTab === "cards" && (
        <div>
          {loading ? (
            <div style={{ padding: 48, textAlign: "center", fontFamily: F.mono, fontSize: 11, color: T.t3, letterSpacing: "0.12em" }}>
              LOADING STRATEGIES…
            </div>
          ) : error ? (
            <div style={{ padding: 40, textAlign: "center", fontFamily: F.mono, fontSize: 11, color: T.red }}>
              {error}
            </div>
          ) : (
            <div style={{ display: "flex", gap: 14, flexWrap: "wrap" }}>
              {strategies.map(s => (
                <StrategyCard key={s.id} s={s} selected={selectedId}
                  onSelect={id => { setSelectedId(id); setActiveTab("universe"); }}
                  regime={regime} />
              ))}
            </div>
          )}

          {/* Legend */}
          <div style={{
            marginTop: 20, padding: "12px 16px",
            background: "rgba(5,7,22,0.60)", border: "1px solid rgba(255,255,255,0.05)",
            borderRadius: 8,
          }}>
            <div style={{ display: "flex", gap: 20, flexWrap: "wrap" }}>
              {["F", "M", "O", "S", "A"].map(p => (
                <div key={p} style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <div style={{ width: 8, height: 8, borderRadius: 1, background: PILLAR_COLORS[p] }} />
                  <span style={{ fontFamily: F.mono, fontSize: 9, color: T.t3 }}>
                    <span style={{ color: PILLAR_COLORS[p], fontWeight: 700 }}>{p}</span> — {PILLAR_LABELS[p]}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* ── TAB: Live Universe ───────────────────────────────────────────────── */}
      {activeTab === "universe" && (
        <div>
          {/* Strategy selector */}
          <div style={{ display: "flex", gap: 8, marginBottom: 16, flexWrap: "wrap" }}>
            {strategies.map(s => (
              <button key={s.id} onClick={() => setSelectedId(s.id)} style={{
                fontFamily: F.mono, fontSize: 9, fontWeight: 700, letterSpacing: "0.08em",
                padding: "5px 12px", borderRadius: 4,
                background: selectedId === s.id ? `${s.color}14` : "rgba(5,7,22,0.7)",
                border: `1px solid ${selectedId === s.id ? s.color + "40" : "rgba(255,255,255,0.08)"}`,
                color: selectedId === s.id ? s.color : T.t3, cursor: "pointer",
                transition: "all 0.2s",
              }}>
                {s.icon} {s.name}
              </button>
            ))}
          </div>

          {uniLoading ? (
            <div style={{ padding: 48, textAlign: "center", fontFamily: F.mono, fontSize: 11, color: T.t3, letterSpacing: "0.12em" }}>
              RESCORING UNIVERSE…
            </div>
          ) : universe ? (
            <div>
              {/* Stats bar */}
              <div style={{
                display: "flex", gap: 0, marginBottom: 16,
                background: "rgba(5,7,22,0.85)",
                border: "1px solid rgba(255,255,255,0.07)", borderRadius: 8, overflow: "hidden",
              }}>
                {[
                  { label: "QUALIFYING", value: universe.qualifying_count, color: strategyColor },
                  { label: "TOTAL ASSETS", value: universe.total_count, color: T.t2 },
                  { label: "REGIME FIT", value: `${universe.strategy_fitness}/100`, color: FITNESS_COLOR(universe.strategy_fitness || 55) },
                  { label: "REGIME", value: universe.current_regime, color: T.amber },
                ].map((s, i, arr) => (
                  <div key={s.label} style={{
                    flex: 1, padding: "12px 16px", textAlign: "center",
                    borderRight: i < arr.length - 1 ? "1px solid rgba(255,255,255,0.05)" : "none",
                  }}>
                    <div style={{ fontFamily: F.mono, fontSize: 9, color: T.t3, letterSpacing: "0.10em", marginBottom: 4 }}>
                      {s.label}
                    </div>
                    <div style={{ fontFamily: F.mono, fontSize: 16, fontWeight: 600, color: s.color, letterSpacing: "-0.01em" }}>
                      {s.value}
                    </div>
                  </div>
                ))}
              </div>

              {/* Weights bar for active strategy */}
              {selectedStrategy && (
                <div style={{
                  marginBottom: 16, padding: "12px 16px",
                  background: `linear-gradient(135deg, rgba(5,7,22,0.92) 0%, ${strategyColor}06 100%)`,
                  border: `1px solid ${strategyColor}20`, borderRadius: 8,
                }}>
                  <div style={{ fontFamily: F.mono, fontSize: 9, color: T.t3, letterSpacing: "0.10em", marginBottom: 10 }}>
                    ACTIVE FACTOR WEIGHTS — {selectedStrategy.name.toUpperCase()}
                  </div>
                  <div style={{ display: "flex", gap: 0 }}>
                    {["F", "M", "O", "S", "A"].map(p => {
                      const w = universe.pillar_weights?.[p] || 0;
                      return (
                        <div key={p} style={{
                          flex: Math.round(w * 100), minWidth: 0,
                          background: PILLAR_COLORS[p] + "22",
                          borderRight: "1px solid rgba(5,7,22,0.8)",
                          padding: "4px 8px", display: "flex", flexDirection: "column",
                          alignItems: "center",
                        }}>
                          <div style={{ fontFamily: F.mono, fontSize: 9, fontWeight: 700, color: PILLAR_COLORS[p] }}>{p}</div>
                          <div style={{ fontFamily: F.mono, fontSize: 10, color: T.t2 }}>{Math.round(w * 100)}%</div>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* Table header */}
              <div style={{
                display: "grid",
                gridTemplateColumns: "28px 56px 1fr 60px 52px 52px 52px 70px",
                padding: "6px 12px 8px",
                fontFamily: F.mono, fontSize: 9, color: T.t3, letterSpacing: "0.10em",
                borderBottom: "1px solid rgba(255,255,255,0.08)",
              }}>
                <span>#</span>
                <span>ASSET</span>
                <span>CLASS · FACTOR</span>
                <span style={{ textAlign: "right" }}>STRAT CIS</span>
                <span style={{ textAlign: "right" }}>F</span>
                <span style={{ textAlign: "right" }}>M</span>
                <span style={{ textAlign: "right" }}>S</span>
                <span style={{ textAlign: "right" }}>SIGNAL</span>
              </div>

              {/* Asset rows */}
              <div style={{ maxHeight: 520, overflowY: "auto", scrollbarWidth: "thin", scrollbarColor: `${T.border} transparent` }}>
                {universe.assets.map((a, i) => (
                  <AssetRow key={a.symbol} a={a} rank={i + 1} strategyColor={strategyColor} />
                ))}
              </div>

              <div style={{ marginTop: 10, fontFamily: F.mono, fontSize: 9, color: T.t3, opacity: 0.45, textAlign: "right" }}>
                CIS rescored with {selectedStrategy?.name || selectedId} weights · Not investment advice
              </div>
            </div>
          ) : (
            <div style={{ padding: 48, textAlign: "center", fontFamily: F.mono, fontSize: 11, color: T.t3 }}>
              Select a strategy above
            </div>
          )}
        </div>
      )}

      {/* ── TAB: Factor Compare ──────────────────────────────────────────────── */}
      {activeTab === "compare" && (
        <div>
          {compare ? (
            <div>
              <div style={{
                padding: "14px 18px", marginBottom: 16,
                background: "rgba(5,7,22,0.85)", border: "1px solid rgba(255,255,255,0.07)", borderRadius: 8,
              }}>
                <div style={{ fontFamily: F.mono, fontSize: 9, color: T.t3, letterSpacing: "0.10em", marginBottom: 12 }}>
                  PILLAR WEIGHT COMPARISON — ALL STRATEGIES · CURRENT REGIME: {regime.toUpperCase()}
                </div>
                <CompareChart strategies={compare} />
              </div>

              {/* Insight cards */}
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))", gap: 10 }}>
                {Object.entries(compare).map(([sid, s]) => (
                  <div key={sid} style={{
                    padding: "12px 14px",
                    background: `linear-gradient(135deg, rgba(5,7,22,0.9), ${s.color}08)`,
                    border: `1px solid ${s.color}20`, borderRadius: 8,
                  }}>
                    <div style={{ fontFamily: F.mono, fontSize: 10, color: s.color, fontWeight: 700, marginBottom: 8, letterSpacing: "0.06em" }}>
                      {s.name}
                    </div>
                    {["F","M","O","S","A"].map(p => (
                      <div key={p} style={{ display: "flex", justifyContent: "space-between", marginBottom: 3 }}>
                        <span style={{ fontFamily: F.mono, fontSize: 9, color: PILLAR_COLORS[p] }}>{PILLAR_LABELS[p]}</span>
                        <span style={{ fontFamily: F.mono, fontSize: 9, color: T.t2, fontWeight: 600 }}>
                          {Math.round((s.weights[p] || 0) * 100)}%
                        </span>
                      </div>
                    ))}
                    <div style={{
                      marginTop: 8, paddingTop: 8, borderTop: "1px solid rgba(255,255,255,0.05)",
                      fontFamily: F.mono, fontSize: 9,
                      color: FITNESS_COLOR(s.fitness), fontWeight: 700, letterSpacing: "0.06em",
                    }}>
                      {FITNESS_LABEL(s.fitness)} · {s.fitness}/100
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <div style={{ padding: 48, textAlign: "center", fontFamily: F.mono, fontSize: 11, color: T.t3, letterSpacing: "0.12em" }}>
              LOADING COMPARISON…
            </div>
          )}
        </div>
      )}
    </div>
  );
}
