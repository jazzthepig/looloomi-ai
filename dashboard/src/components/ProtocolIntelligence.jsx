import { useState, useEffect, useCallback } from "react";
import { T, FONTS } from "../tokens";

/* ─── Constants ─────────────────────────────────────────────────────── */
const GRADE_COLORS = {
  "A+": T.green, "A": T.green,
  "B+": T.gold,  "B": T.gold,
  "C+": T.amber, "C": T.amber,
  "D":  T.red,   "F": T.red,
};

const SIGNAL_COLORS = {
  OUTPERFORM:   { color: T.green, bg: "rgba(0,232,122,0.10)", border: "rgba(0,232,122,0.25)" },
  "STRONG OUTPERFORM": { color: T.green, bg: "rgba(0,232,122,0.15)", border: "rgba(0,232,122,0.35)" },
  NEUTRAL:      { color: T.gold,  bg: "rgba(200,168,75,0.10)", border: "rgba(200,168,75,0.25)" },
  UNDERPERFORM: { color: T.amber, bg: "rgba(245,158,11,0.10)", border: "rgba(245,158,11,0.25)" },
  UNDERWEIGHT:  { color: T.red,   bg: "rgba(255,61,90,0.10)",  border: "rgba(255,61,90,0.25)" },
};

const RISK_COLORS = {
  LOW:    { color: T.green, bg: "rgba(0,232,122,0.06)" },
  MEDIUM: { color: T.gold,  bg: "rgba(200,168,75,0.06)" },
  HIGH:   { color: T.red,   bg: "rgba(255,61,90,0.06)" },
};

const DIR_ICON = { UP: "▲", DOWN: "▼", FLAT: "—" };
const DIR_COLOR = { UP: T.green, DOWN: T.red, FLAT: T.t3 };

const PILLAR_LABELS = ["F", "M", "O", "S", "A"];
const PILLAR_NAMES = { F: "Fundamental", M: "Momentum", O: "On-chain Risk", S: "Sentiment", A: "Alpha" };

const CATEGORIES = ["All", "RWA", "DeFi", "Derivatives", "Infrastructure"];

/* ─── Pillar Radar (mini horizontal bars) ──────────────────────────── */
const PillarMini = ({ pillars }) => {
  if (!pillars) return null;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 3, marginTop: 10 }}>
      {PILLAR_LABELS.map((p) => {
        const val = pillars[p] ?? 0;
        const color = val >= 70 ? T.green : val >= 40 ? T.gold : val >= 20 ? T.amber : T.red;
        return (
          <div key={p} style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <span style={{
              fontFamily: FONTS.mono, fontSize: 9, fontWeight: 700,
              color, width: 10, textAlign: "center",
            }}>{p}</span>
            <div style={{
              flex: 1, height: 4, borderRadius: 2,
              background: "rgba(255,255,255,0.06)",
              overflow: "hidden",
            }}>
              <div style={{
                height: "100%", width: `${val}%`,
                background: color, borderRadius: 2,
                transition: "width 0.5s ease",
              }} />
            </div>
            <span style={{
              fontFamily: FONTS.mono, fontSize: 8, color: T.t3,
              width: 20, textAlign: "right",
            }}>{val}</span>
          </div>
        );
      })}
    </div>
  );
};

/* ─── Expanded Protocol Detail ─────────────────────────────────────── */
const ProtocolDetail = ({ protocol }) => {
  const p = protocol;
  if (!p) return null;
  const sig = SIGNAL_COLORS[p.signal] || SIGNAL_COLORS.NEUTRAL;

  return (
    <div style={{
      padding: "16px 20px",
      borderTop: `1px solid ${T.border}`,
      background: "rgba(0,0,0,0.012)",
    }}>
      {/* Signal + Risk + Weight row */}
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginBottom: 14, alignItems: "center" }}>
        <span style={{
          fontFamily: FONTS.display, fontSize: 11, fontWeight: 700,
          letterSpacing: "0.08em", padding: "4px 12px", borderRadius: 4,
          background: sig.bg, color: sig.color, border: `1px solid ${sig.border}`,
        }}>
          {p.signal}
        </span>
        {p.risk_tier && (
          <span style={{
            fontFamily: FONTS.display, fontSize: 10, fontWeight: 600,
            letterSpacing: "0.07em", padding: "3px 9px", borderRadius: 4,
            background: RISK_COLORS[p.risk_tier]?.bg, color: RISK_COLORS[p.risk_tier]?.color,
            border: `1px solid ${RISK_COLORS[p.risk_tier]?.color}30`,
          }}>
            RISK: {p.risk_tier}
          </span>
        )}
        {p.recommended_weight_bps > 0 && (
          <span style={{
            fontFamily: FONTS.mono, fontSize: 10, color: T.t2,
            padding: "3px 8px", borderRadius: 4,
            background: "rgba(255,255,255,0.04)", border: `1px solid ${T.border}`,
          }}>
            Rec. Weight: {(p.recommended_weight_bps / 100).toFixed(1)}%
          </span>
        )}
        {p.live_data && (
          <span style={{
            fontFamily: FONTS.mono, fontSize: 8, color: T.green,
            padding: "2px 6px", borderRadius: 3,
            background: "rgba(0,232,122,0.08)", border: "1px solid rgba(0,232,122,0.2)",
          }}>
            LIVE
          </span>
        )}
      </div>

      {/* TVL stats row */}
      <div style={{ display: "flex", gap: 20, marginBottom: 14, flexWrap: "wrap" }}>
        {[
          { label: "TVL", value: p.tvl_formatted || "—", color: T.t1 },
          { label: "7D", value: `${p.tvl_change_7d > 0 ? "+" : ""}${p.tvl_change_7d?.toFixed(1) ?? 0}%`, color: p.tvl_change_7d > 0 ? T.green : p.tvl_change_7d < 0 ? T.red : T.t3 },
          { label: "30D", value: `${p.tvl_change_30d > 0 ? "+" : ""}${p.tvl_change_30d?.toFixed(1) ?? 0}%`, color: p.tvl_change_30d > 0 ? T.green : p.tvl_change_30d < 0 ? T.red : T.t3 },
          { label: "APY", value: p.apy > 0 ? `${p.apy}%` : "—", color: p.apy > 0 ? T.green : T.t3 },
          { label: "Audit", value: `${p.audit_score}/10`, color: p.audit_score >= 8 ? T.green : p.audit_score >= 6 ? T.gold : T.red },
          { label: "Age", value: `${p.age_months}mo`, color: T.t2 },
        ].map((s, i) => (
          <div key={i}>
            <div style={{ fontSize: 8, color: T.t3, fontFamily: FONTS.mono, letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 3 }}>
              {s.label}
            </div>
            <div style={{ fontSize: 13, fontWeight: 600, color: s.color, fontFamily: FONTS.mono }}>
              {s.value}
            </div>
          </div>
        ))}
      </div>

      {/* What it is */}
      {p.description && (
        <div style={{ marginBottom: 14 }}>
          <div style={{
            fontSize: 9, fontFamily: FONTS.mono, color: T.t3,
            letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 6,
          }}>
            What It Is
          </div>
          <div style={{
            fontSize: 12, color: T.t2, fontFamily: FONTS.body, lineHeight: 1.65,
          }}>
            {p.description}
          </div>
        </div>
      )}

      {/* Why CometCloud selected it */}
      {p.why_selected && (
        <div style={{
          marginBottom: 14, padding: "12px 14px", borderRadius: 6,
          background: "rgba(75,158,255,0.04)", border: "1px solid rgba(75,158,255,0.12)",
        }}>
          <div style={{
            fontSize: 9, fontFamily: FONTS.mono, color: "rgba(75,158,255,0.7)",
            letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 6,
          }}>
            Why CometCloud Holds This
          </div>
          <div style={{
            fontSize: 12, color: T.t1, fontFamily: FONTS.body, lineHeight: 1.65,
          }}>
            {p.why_selected}
          </div>
        </div>
      )}

      {/* Strengths */}
      {p.strengths && p.strengths.length > 0 && (
        <div style={{ marginBottom: 14 }}>
          <div style={{
            fontSize: 9, fontFamily: FONTS.mono, color: T.t3,
            letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 8,
          }}>
            What We Like
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
            {p.strengths.map((s, i) => (
              <div key={i} style={{ display: "flex", alignItems: "flex-start", gap: 8 }}>
                <span style={{
                  color: T.green, fontFamily: FONTS.mono, fontSize: 10,
                  marginTop: 1, flexShrink: 0, lineHeight: 1.6,
                }}>▸</span>
                <span style={{
                  fontSize: 12, color: T.t2, fontFamily: FONTS.body, lineHeight: 1.6,
                }}>
                  {s}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Pillar breakdown */}
      <div style={{ fontSize: 9, fontFamily: FONTS.mono, color: T.t3, letterSpacing: "0.08em", textTransform: "uppercase", marginBottom: 6 }}>
        CIS Pillar Breakdown
      </div>
      <PillarMini pillars={p.pillars} />
    </div>
  );
};

/* ─── Main Component ────────────────────────────────────────────────── */
export default function ProtocolIntelligence() {
  const [protocols, setProtocols]     = useState([]);
  const [agentPicks, setAgentPicks]   = useState([]);
  const [categories, setCategories]   = useState({});
  const [totalTvl, setTotalTvl]       = useState("—");
  const [loading, setLoading]         = useState(true);
  const [error, setError]             = useState(null);
  const [expandedId, setExpandedId]   = useState(null);
  const [activeCategory, setActiveCategory] = useState("All");
  const [sortBy, setSortBy]           = useState("score"); // score | tvl | change_7d

  const fetchProtocols = useCallback(async () => {
    try {
      const res = await fetch("/api/v1/protocols/universe");
      if (!res.ok) throw new Error(`API ${res.status}`);
      const data = await res.json();
      setProtocols(data.protocols || []);
      setAgentPicks(data.agent_picks || []);
      setCategories(data.categories || {});
      setTotalTvl(data.total_tvl || "—");
    } catch (e) {
      console.error("ProtocolIntelligence:", e);
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchProtocols(); }, [fetchProtocols]);
  useEffect(() => {
    const interval = setInterval(fetchProtocols, 600000); // 10min
    return () => clearInterval(interval);
  }, [fetchProtocols]);

  // Filter & sort
  const filtered = protocols
    .filter(p => activeCategory === "All" || p.category.toLowerCase().includes(activeCategory.toLowerCase()))
    .sort((a, b) => {
      if (sortBy === "tvl") return (b.tvl || 0) - (a.tvl || 0);
      if (sortBy === "change_7d") return (b.tvl_change_7d || 0) - (a.tvl_change_7d || 0);
      return (b.cis_score || 0) - (a.cis_score || 0);
    });

  return (
    <div style={{ marginBottom: 24 }}>
      {/* ── Header ─────────────────────────────────────────────────── */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 12 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{
            fontFamily: FONTS.display, fontSize: 15, fontWeight: 700,
            color: T.t1, letterSpacing: "0.04em",
          }}>
            Protocol Intelligence
          </span>
          <span style={{
            fontFamily: FONTS.mono, fontSize: 9, fontWeight: 500,
            letterSpacing: "0.08em", color: T.t3,
          }}>CIS v4.1</span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 11, fontFamily: FONTS.mono, color: T.t3 }}>
            {protocols.length} protocols · {totalTvl}
          </span>
          <span style={{
            fontFamily: FONTS.mono, fontSize: 9, color: T.green, padding: "2px 7px",
            borderRadius: 3, background: "rgba(0,232,122,0.06)", border: "1px solid rgba(0,232,122,0.15)",
          }}>LIVE</span>
        </div>
      </div>

      {/* ── Category Filters + Sort ────────────────────────────────── */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10, flexWrap: "wrap", gap: 8 }}>
        <div style={{ display: "flex", gap: 4 }}>
          {CATEGORIES.map(cat => {
            const active = activeCategory === cat;
            return (
              <button key={cat} onClick={() => setActiveCategory(cat)} style={{
                fontFamily: FONTS.display, fontSize: 11, fontWeight: 700,
                letterSpacing: "0.06em", padding: "5px 12px", borderRadius: 4,
                cursor: "pointer", transition: "all 0.15s", border: "none",
                background: active ? "rgba(75,158,255,0.10)" : "transparent",
                color: active ? T.blue : T.t3,
                outline: active ? `1px solid rgba(75,158,255,0.3)` : "1px solid transparent",
              }}>
                {cat}
              </button>
            );
          })}
        </div>
        <div style={{ display: "flex", gap: 4 }}>
          {[
            { key: "score", label: "CIS Score" },
            { key: "tvl", label: "TVL" },
            { key: "change_7d", label: "7D Flow" },
          ].map(s => (
            <button key={s.key} onClick={() => setSortBy(s.key)} style={{
              fontFamily: FONTS.mono, fontSize: 10, padding: "4px 10px", borderRadius: 3,
              cursor: "pointer", border: "none",
              background: sortBy === s.key ? "rgba(255,255,255,0.06)" : "transparent",
              color: sortBy === s.key ? T.t1 : T.t3,
              outline: sortBy === s.key ? `1px solid ${T.border}` : "none",
            }}>
              {s.label}
            </button>
          ))}
        </div>
      </div>

      {/* ── Protocol Table ─────────────────────────────────────────── */}
      <div className="lm-card" style={{ overflow: "hidden" }}>
        {/* Table header */}
        <div style={{
          display: "grid", gridTemplateColumns: "32px 1.6fr 0.8fr 0.8fr 0.6fr 0.5fr 0.5fr",
          padding: "11px 18px", borderBottom: `1px solid ${T.border}`,
          fontSize: 9, color: T.t3, letterSpacing: "0.1em", textTransform: "uppercase",
          fontFamily: FONTS.mono, background: "rgba(13,32,56,0.5)",
        }}>
          <div>#</div>
          <div>Protocol</div>
          <div style={{ textAlign: "right" }}>TVL</div>
          <div style={{ textAlign: "right" }}>7D Flow</div>
          <div style={{ textAlign: "center" }}>Grade</div>
          <div style={{ textAlign: "center" }}>Signal</div>
          <div style={{ textAlign: "center" }}>Risk</div>
        </div>

        {/* Rows */}
        <div style={{ maxHeight: 600, overflowY: "auto", scrollbarWidth: "thin", scrollbarColor: `${T.border} transparent` }}>
          {loading ? (
            Array(8).fill(0).map((_, i) => (
              <div key={i} style={{
                display: "grid", gridTemplateColumns: "32px 1.6fr 0.8fr 0.8fr 0.6fr 0.5fr 0.5fr",
                padding: "14px 18px", borderBottom: `1px solid ${T.border}`,
                gap: 10, alignItems: "center",
              }}>
                {[16, 120, 60, 50, 30, 50, 40].map((w, j) => (
                  <div key={j} className="sk" style={{ height: 12, width: w }} />
                ))}
              </div>
            ))
          ) : error ? (
            <div style={{ padding: 40, textAlign: "center", color: T.t3, fontSize: 11 }}>
              Protocol data loading... API warming up.
            </div>
          ) : filtered.map((p, idx) => {
            const isExpanded_ = expandedId === p.id;
            const isPick = agentPicks.includes(p.id);
            const gradeColor = GRADE_COLORS[p.grade] || T.t3;
            const sigCfg = SIGNAL_COLORS[p.signal] || SIGNAL_COLORS.HOLD;
            const riskCfg = RISK_COLORS[p.risk_tier] || RISK_COLORS.MEDIUM;
            const dirColor = DIR_COLOR[p.tvl_direction] || T.t3;
            const dirIcon = DIR_ICON[p.tvl_direction] || "—";

            return (
              <div key={p.id}>
                <div
                  className="transition-row"
                  style={{
                    display: "grid", gridTemplateColumns: "32px 1.6fr 0.8fr 0.8fr 0.6fr 0.5fr 0.5fr",
                    padding: "12px 18px", borderBottom: `1px solid ${T.border}`,
                    alignItems: "center", cursor: "pointer",
                    background: isExpanded_ ? "rgba(0,0,0,0.02)" : isPick ? "rgba(0,232,122,0.015)" : "transparent",
                  }}
                  onClick={() => setExpandedId(isExpanded_ ? null : p.id)}
                  onMouseEnter={(e) => {
                    if (!isExpanded_) {
                      e.currentTarget.style.background = "rgba(13,32,56,0.6)";
                      e.currentTarget.style.borderLeft = "2px solid rgba(99,102,241,0.35)";
                    }
                  }}
                  onMouseLeave={(e) => {
                    if (!isExpanded_) {
                      e.currentTarget.style.background = isPick ? "rgba(0,232,122,0.015)" : "transparent";
                      e.currentTarget.style.borderLeft = "none";
                    }
                  }}
                >
                  {/* Rank */}
                  <span style={{ fontFamily: FONTS.mono, fontSize: 11, color: T.t3, fontWeight: 600 }}>
                    {p.rank}
                  </span>

                  {/* Protocol name + category */}
                  <div>
                    <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                      <span style={{ fontFamily: FONTS.display, fontSize: 13, fontWeight: 700, color: T.t1 }}>
                        {p.name}
                      </span>
                      {isPick && (
                        <span style={{
                          fontSize: 8, fontFamily: FONTS.mono, fontWeight: 600,
                          letterSpacing: "0.08em", color: T.green, opacity: 0.75,
                        }}>★</span>
                      )}
                    </div>
                    <div style={{ fontSize: 10, color: T.t3, fontFamily: FONTS.body, marginTop: 2 }}>
                      {p.category} · {p.chain}
                    </div>
                  </div>

                  {/* TVL + direction */}
                  <div style={{ textAlign: "right" }}>
                    <span style={{ fontFamily: FONTS.mono, fontSize: 13, fontWeight: 500, color: T.t1 }}>
                      {p.tvl_formatted || "—"}
                    </span>
                    <span style={{ fontSize: 9, color: dirColor, marginLeft: 4 }}>{dirIcon}</span>
                  </div>

                  {/* 7D flow */}
                  <div style={{ textAlign: "right" }}>
                    <span style={{
                      fontFamily: FONTS.mono, fontSize: 12,
                      color: (p.tvl_change_7d || 0) > 0 ? T.green : (p.tvl_change_7d || 0) < 0 ? T.red : T.t3,
                    }}>
                      {(p.tvl_change_7d || 0) > 0 ? "+" : ""}{(p.tvl_change_7d || 0).toFixed(1)}%
                    </span>
                  </div>

                  {/* Grade */}
                  <div style={{ textAlign: "center" }}>
                    <span style={{
                      fontFamily: FONTS.mono, fontSize: 13, fontWeight: 800,
                      color: gradeColor,
                    }}>
                      {p.grade}
                    </span>
                    <div style={{ fontSize: 9, color: T.t3, fontFamily: FONTS.mono, marginTop: 1 }}>
                      {p.cis_score?.toFixed(0)}
                    </div>
                  </div>

                  {/* Signal */}
                  <div style={{ textAlign: "center" }}>
                    <span style={{
                      fontFamily: FONTS.display, fontSize: 9, fontWeight: 700,
                      letterSpacing: "0.05em", padding: "3px 6px", borderRadius: 3,
                      background: sigCfg.bg, color: sigCfg.color,
                      border: `1px solid ${sigCfg.border}`,
                    }}>
                      {p.signal}
                    </span>
                  </div>

                  {/* Risk */}
                  <div style={{ textAlign: "center" }}>
                    <span style={{
                      fontFamily: FONTS.mono, fontSize: 10, fontWeight: 600,
                      color: riskCfg.color,
                    }}>
                      {p.risk_tier}
                    </span>
                  </div>
                </div>

                {/* Expanded detail */}
                {isExpanded_ && <ProtocolDetail protocol={p} />}
              </div>
            );
          })}
        </div>

        {/* Footer */}
        <div style={{
          padding: "10px 18px", borderTop: `1px solid ${T.border}`,
          display: "flex", justifyContent: "space-between", alignItems: "center",
          fontSize: 9, color: T.t3, fontFamily: FONTS.mono,
        }}>
          <span>Source: DeFiLlama TVL · CIS Protocol Engine v1.0</span>
          <span>Click row to expand · Data refreshes every 10 min</span>
        </div>
      </div>
    </div>
  );
}
