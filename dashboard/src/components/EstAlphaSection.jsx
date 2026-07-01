/**
 * EstAlphaSection
 * Data-driven display of EST Alpha — CometCloud's strategic GP partner.
 * Pulls from /api/v1/vault/funds (filter id === "est-alpha").
 *
 * Compliance notes (per PRD v2.2 must-not-include):
 *   - AUM is intentionally NOT displayed (kept "Confidential" per partner disclosure)
 *   - No performance projections / expected return / Sharpe forward-looking language
 *   - Grade is computed from scores.total (83 ≥ 75 → A per CIS thresholds)
 *   - Track record shows only live or audited data; placeholders clearly disclosed
 */

import { useEffect, useState } from "react";
import { T, FONTS } from "../tokens";

const API_BASE = "/api/v1";

/* ─── Helpers ────────────────────────────────────────────────────────── */
const gradeColor = (grade) => {
  if (!grade || grade === "—") return T.muted;
  if (grade.startsWith("A")) return T.green;   // A, A+
  if (grade.startsWith("B")) return T.blue;    // B, B+
  if (grade.startsWith("C")) return T.amber;   // C, C+
  if (grade === "D" || grade === "F") return T.red;
  return T.muted;
};

const statusBadge = (status) => {
  const active = status === "active";
  return {
    bg: active ? "rgba(0,217,138,0.10)" : "rgba(245,158,11,0.10)",
    border: active ? "rgba(0,217,138,0.25)" : "rgba(245,158,11,0.25)",
    color: active ? T.green : T.amber,
    dot: active ? T.green : T.amber,
    label: active ? "ACTIVE" : (status || "PENDING").toUpperCase(),
  };
};

const fmtNum = (n, decimals = 1) => (typeof n === "number" ? n.toFixed(decimals) : null);
const fmtPct = (n) => (typeof n === "number" ? `${n >= 0 ? "+" : ""}${n.toFixed(1)}%` : null);

/* ─── Score Breakdown — 6-criterion bar (lifted from VaultPage) ──────── */
const SCORE_CRITERIA = [
  { key: "performance",   label: "Performance",   short: "Perf",   max: 25, color: "#4472FF" },
  { key: "strategy",      label: "Strategy",      short: "Strat",  max: 20, color: "#A78BFA" },
  { key: "team",          label: "Team",          short: "Team",   max: 20, color: "#00D98A" },
  { key: "risk",          label: "Risk Mgmt",     short: "Risk",   max: 15, color: "#F59E0B" },
  { key: "transparency",  label: "Transparency",  short: "Trans",  max: 10, color: "#00C8E0" },
  { key: "aumTrackRecord",label: "AUM & Track",   short: "AUM",    max: 10, color: "#C8A84B" },
];

function ScoreBreakdown({ scores }) {
  if (!scores) return null;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 5 }}>
      {SCORE_CRITERIA.map((c) => {
        const val = scores[c.key];
        const isPending = val == null;
        const pct = isPending ? 0 : (val / c.max) * 100;
        return (
          <div key={c.key} title={`${c.label}: ${isPending ? "—" : `${val} / ${c.max} pts`}`}
               style={{ display: "flex", alignItems: "center", gap: 8, cursor: "default" }}>
            <span style={{
              fontFamily: FONTS.mono, fontSize: 9, fontWeight: 600,
              color: c.color, opacity: 0.75, width: 38, flexShrink: 0,
              letterSpacing: "-0.01em",
            }}>{c.short}</span>
            <div style={{
              flex: 1, height: 4, background: "rgba(255,255,255,0.07)",
              borderRadius: 2, overflow: "hidden",
            }}>
              <div style={{
                width: `${pct}%`, height: "100%", background: c.color,
                borderRadius: 2, opacity: isPending ? 0.2 : 0.85,
                transition: "width .4s ease",
              }} />
            </div>
            <span style={{
              fontFamily: FONTS.mono, fontSize: 10, fontWeight: 600,
              color: isPending ? T.muted : "rgba(240,244,255,0.75)",
              width: 18, textAlign: "right", flexShrink: 0,
            }}>{isPending ? "—" : val}</span>
          </div>
        );
      })}
    </div>
  );
}

/* ─── Track Record — 4-col metric row (lifted from VaultPage) ───────── */
function TrackRecord({ performance }) {
  if (!performance) return null;
  const p = performance;
  const fmtYtd = fmtPct(p.ytd);
  const ytdColor = fmtYtd ? (p.ytd >= 0 ? T.green : T.red) : T.muted;
  const fmtAnnual = fmtPct(p.annualReturn);
  const fmtSharpe = fmtNum(p.sharpeRatio, 2);
  const fmtDD = fmtPct(p.maxDrawdown);
  const hasAny = fmtYtd || fmtAnnual || fmtSharpe || fmtDD;

  return (
    <div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 8, marginBottom: p._note ? 10 : 0 }}>
        <div>
          <div style={{ fontSize: 9, color: T.muted, letterSpacing: "0.10em", textTransform: "uppercase", marginBottom: 4, fontFamily: FONTS.mono }}>YTD</div>
          <div style={{ fontSize: 16, fontWeight: 700, color: ytdColor, fontFamily: FONTS.mono }}>
            {fmtYtd || <span style={{ color: T.muted, fontWeight: 400, fontSize: 11 }}>Live accumulating</span>}
          </div>
        </div>
        <div>
          <div style={{ fontSize: 9, color: T.muted, letterSpacing: "0.10em", textTransform: "uppercase", marginBottom: 4, fontFamily: FONTS.mono }}>Annual</div>
          <div style={{ fontSize: 16, fontWeight: 700, color: fmtAnnual ? T.primary : T.muted, fontFamily: FONTS.mono }}>
            {fmtAnnual || <span style={{ color: T.muted, fontWeight: 400, fontSize: 11 }}>Live accumulating</span>}
          </div>
        </div>
        <div>
          <div style={{ fontSize: 9, color: T.muted, letterSpacing: "0.10em", textTransform: "uppercase", marginBottom: 4, fontFamily: FONTS.mono }}>Sharpe</div>
          <div style={{ fontSize: 16, fontWeight: 700, color: fmtSharpe ? T.primary : T.muted, fontFamily: FONTS.mono }}>
            {fmtSharpe || <span style={{ color: T.muted, fontWeight: 400, fontSize: 11 }}>Live accumulating</span>}
          </div>
        </div>
        <div>
          <div style={{ fontSize: 9, color: T.muted, letterSpacing: "0.10em", textTransform: "uppercase", marginBottom: 4, fontFamily: FONTS.mono }}>Max DD</div>
          <div style={{ fontSize: 16, fontWeight: 700, color: fmtDD ? T.amber : T.muted, fontFamily: FONTS.mono }}>
            {fmtDD || <span style={{ color: T.muted, fontWeight: 400, fontSize: 11 }}>Live accumulating</span>}
          </div>
        </div>
      </div>
      {p._note && (
        <div style={{
          display: "flex", alignItems: "flex-start", gap: 8,
          padding: "8px 12px", marginTop: 4,
          background: "rgba(245,158,11,0.06)",
          border: "1px solid rgba(245,158,11,0.18)",
          borderRadius: 6,
        }}>
          <span style={{ color: T.amber, fontSize: 11, lineHeight: 1, marginTop: 1 }}>●</span>
          <span style={{ fontSize: 10, color: "rgba(245,158,11,0.85)", fontFamily: FONTS.body, lineHeight: 1.4 }}>
            <strong style={{ color: T.amber, fontFamily: FONTS.mono, letterSpacing: "0.06em", marginRight: 4 }}>DATA NOTE</strong>
            {p._note}
          </span>
        </div>
      )}
    </div>
  );
}

/* ─── Section Divider — gold accent ──────────────────────────────────── */
function GoldDivider({ label }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 14, marginBottom: 24 }}>
      <div style={{ flex: 1, height: 1, background: "rgba(212,168,67,0.18)" }} />
      <span style={{
        fontFamily: FONTS.mono, fontSize: 9, color: "rgba(212,168,67,0.65)",
        letterSpacing: "0.18em", textTransform: "uppercase",
      }}>{label}</span>
      <div style={{ flex: 1, height: 1, background: "rgba(212,168,67,0.18)" }} />
    </div>
  );
}

/* ─── Skeleton loader ───────────────────────────────────────────────── */
function SectionSkeleton() {
  return (
    <div>
      <GoldDivider label="EST ALPHA · STRATEGIC GP" />
      <div style={{
        background: "linear-gradient(135deg, rgba(212,168,67,0.04) 0%, transparent 100%)",
        border: "1px solid rgba(212,168,67,0.10)", borderRadius: 12, padding: 28,
        marginBottom: 16, minHeight: 100,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
          <div className="sk" style={{ width: 64, height: 64, borderRadius: "50%" }} />
          <div style={{ flex: 1 }}>
            <div className="sk" style={{ width: 140, height: 18, marginBottom: 8, borderRadius: 4 }} />
            <div className="sk" style={{ width: 220, height: 11, borderRadius: 4 }} />
          </div>
        </div>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12, marginBottom: 20 }}>
        {[0,1,2,3].map((i) => <div key={i} className="sk" style={{ height: 70, borderRadius: 8 }} />)}
      </div>
    </div>
  );
}

/* ─── Main component ─────────────────────────────────────────────────── */
export default function EstAlphaSection() {
  const [fund, setFund] = useState(null);
  const [loading, setLoading] = useState(true);
  const [errored, setErrored] = useState(false);

  useEffect(() => {
    let mounted = true;
    (async () => {
      try {
        const resp = await fetch(`${API_BASE}/vault/funds`);
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const json = await resp.json();
        const est = (json?.data || []).find((f) => f.id === "est-alpha");
        if (mounted) {
          setFund(est || null);
          setLoading(false);
        }
      } catch (e) {
        if (mounted) {
          setErrored(true);
          setLoading(false);
        }
      }
    })();
    return () => { mounted = false; };
  }, []);

  if (loading) return <SectionSkeleton />;
  if (errored || !fund) {
    return (
      <div>
        <GoldDivider label="EST ALPHA · STRATEGIC GP" />
        <div style={{
          padding: "16px 20px", borderRadius: 8,
          background: "rgba(245,158,11,0.06)",
          border: "1px solid rgba(245,158,11,0.18)",
          color: T.amber, fontSize: 11, fontFamily: FONTS.mono,
        }}>
          EST Alpha data temporarily unavailable.
        </div>
      </div>
    );
  }

  const badge = statusBadge(fund.status);
  const gColor = gradeColor(fund.grade);
  const gScore = fund.scores?.total;

  return (
    <div>
      <GoldDivider label="EST ALPHA · STRATEGIC GP" />

      {/* ── Partnership Banner ─────────────────────────────────────────── */}
      <div style={{
        background: "linear-gradient(135deg, rgba(212,168,67,0.10) 0%, rgba(212,168,67,0.02) 50%, transparent 100%)",
        border: "1px solid rgba(212,168,67,0.30)",
        borderRadius: 12, padding: "22px 28px", marginBottom: 16,
        display: "flex", alignItems: "center", justifyContent: "space-between",
        flexWrap: "wrap", gap: 20,
      }}>
        {/* Logo placeholder */}
        <div style={{
          width: 64, height: 64, borderRadius: "50%",
          background: "linear-gradient(135deg, rgba(13,32,56,0.9) 0%, rgba(18,45,76,0.8) 100%)",
          border: "2px solid rgba(212,168,67,0.32)",
          display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0,
        }}>
          <span style={{
            fontFamily: FONTS.display, fontSize: 24, fontWeight: 800,
            color: "#92722A", letterSpacing: "-0.02em",
          }}>E</span>
        </div>

        {/* Name + partner info + grade */}
        <div style={{ flex: 1, minWidth: 200 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 4 }}>
            <span style={{
              fontFamily: FONTS.display, fontSize: 24, fontWeight: 700,
              color: T.primary, letterSpacing: "-0.01em",
            }}>{fund.name}</span>
            {fund.grade && fund.grade !== "—" && (
              <div style={{
                width: 32, height: 32, borderRadius: 6,
                background: `${gColor}20`, border: `1px solid ${gColor}40`,
                display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0,
              }}>
                <span style={{
                  fontFamily: FONTS.mono, fontSize: 14, fontWeight: 700, color: gColor,
                }}>{fund.grade}</span>
              </div>
            )}
          </div>
          <div style={{ fontFamily: FONTS.body, fontSize: 13, color: T.secondary }}>
            CometCloud Strategic GP · Since {fund.yearFounded}
            {gScore != null && (
              <span style={{ marginLeft: 10, color: T.muted, fontFamily: FONTS.mono, fontSize: 11 }}>
                · Score {gScore}/100
              </span>
            )}
          </div>
        </div>

        {/* Status badge */}
        <div style={{
          background: badge.bg, border: `1px solid ${badge.border}`,
          borderRadius: 6, padding: "6px 14px",
          display: "flex", alignItems: "center", gap: 6, flexShrink: 0,
        }}>
          <span style={{
            width: 6, height: 6, borderRadius: "50%",
            background: badge.dot, boxShadow: `0 0 8px ${badge.dot}80`,
          }} />
          <span style={{
            fontFamily: FONTS.display, fontSize: 10, fontWeight: 700,
            color: badge.color, letterSpacing: "0.1em",
          }}>{badge.label}</span>
        </div>
      </div>

      {/* ── 4-Stat Key Facts ───────────────────────────────────────────── */}
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12, marginBottom: 20 }}>
        {[
          { label: "Partner Since", value: fund.yearFounded },
          { label: "Classification", value: fund.strategy || "Multi-Strategy" },
          { label: "Domicile", value: fund.location || "—" },
          { label: "Status", value: fund.verified ? "Verified · Active" : "Active" },
        ].map((stat, i) => (
          <div key={i} className="lm-stat-card" style={{ padding: "16px 20px" }}>
            <div style={{
              fontSize: 10, color: T.muted, letterSpacing: "0.10em",
              textTransform: "uppercase", marginBottom: 8, fontFamily: FONTS.body,
            }}>{stat.label}</div>
            <div style={{ fontFamily: FONTS.mono, fontSize: 18, fontWeight: 600, color: T.primary }}>
              {stat.value}
            </div>
          </div>
        ))}
      </div>

      {/* ── Track Record ───────────────────────────────────────────────── */}
      <div className="lm-card" style={{ padding: "20px 24px", marginBottom: 16 }}>
        <div style={{
          fontFamily: FONTS.display, fontSize: 12, fontWeight: 700,
          color: T.gold, letterSpacing: "0.12em", marginBottom: 14,
          textTransform: "uppercase",
        }}>
          Track Record
        </div>
        <TrackRecord performance={fund.performance} />
      </div>

      {/* ── Strategy + Score Breakdown ─────────────────────────────────── */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16, marginBottom: 8 }}>
        <div className="lm-card" style={{ padding: 24 }}>
          <div style={{
            fontFamily: FONTS.display, fontSize: 12, fontWeight: 700,
            color: T.gold, letterSpacing: "0.12em", marginBottom: 10,
            textTransform: "uppercase",
          }}>Strategy</div>
          <p style={{
            fontFamily: FONTS.body, fontSize: 13, color: T.secondary,
            lineHeight: 1.7, margin: 0, marginBottom: fund.advantage ? 14 : 0,
          }}>
            {fund.strategyDetail || fund.description || "—"}
          </p>
          {fund.team && (
            <div style={{ marginTop: 12, paddingTop: 12, borderTop: "1px solid rgba(212,168,67,0.10)" }}>
              <div style={{
                fontSize: 9, color: T.muted, letterSpacing: "0.10em",
                textTransform: "uppercase", marginBottom: 4, fontFamily: FONTS.mono,
              }}>Team</div>
              <div style={{ fontFamily: FONTS.body, fontSize: 12, color: T.primary, lineHeight: 1.5 }}>
                {fund.team}
              </div>
            </div>
          )}
          {fund.advantage && (
            <div style={{
              marginTop: 12, padding: "10px 14px",
              background: "rgba(212,168,67,0.05)",
              border: "1px solid rgba(212,168,67,0.18)",
              borderRadius: 6,
            }}>
              <div style={{
                fontSize: 9, color: T.gold, letterSpacing: "0.10em",
                textTransform: "uppercase", marginBottom: 4, fontFamily: FONTS.mono,
              }}>Key Advantage</div>
              <div style={{ fontSize: 11, color: T.primary, lineHeight: 1.5 }}>{fund.advantage}</div>
            </div>
          )}
        </div>

        <div className="lm-card-inner" style={{ padding: 24 }}>
          <div style={{
            display: "flex", alignItems: "baseline", justifyContent: "space-between",
            marginBottom: 14,
          }}>
            <div style={{
              fontFamily: FONTS.display, fontSize: 12, fontWeight: 700,
              color: T.muted, letterSpacing: "0.12em", textTransform: "uppercase",
            }}>Score Breakdown</div>
            {gScore != null && (
              <div style={{ fontFamily: FONTS.mono, fontSize: 11, color: T.muted }}>
                {gScore}<span style={{ color: T.t4 }}> / 100</span>
              </div>
            )}
          </div>
          <ScoreBreakdown scores={fund.scores} />
          {fund.note && (
            <div style={{
              marginTop: 14, paddingTop: 12,
              borderTop: "1px solid rgba(255,255,255,0.05)",
              fontSize: 10, color: T.muted, fontFamily: FONTS.body, lineHeight: 1.5,
            }}>
              {fund.note}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
