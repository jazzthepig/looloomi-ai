import { useState, useEffect, useCallback } from "react";
import { T, FONTS } from "../tokens";

/*
 * Signal Feed v4 — loop-sourced.
 * Each card is a dated, directional call drawn from our own resolvable prediction stream
 * (/api/v1/signals/feed → signal_journal → the resolver scores it into a track record), NOT
 * hand-authored market commentary. It surfaces the CALL + an honest aggregate accuracy, and
 * hides the machine (no weights / nucleus / book). Positioning language only — not advice.
 */

/* ─── Direction (compliance-safe positioning language) ───────────────────── */
function dirStyle(direction = "") {
  const s = direction.toUpperCase();
  if (s.includes("OUTPERFORM") && !s.includes("UNDER"))
    return { color: T.green, bg: "rgba(0,232,122,0.10)", border: "rgba(0,232,122,0.28)", icon: "▲",
             label: s.includes("STRONG") ? "STRONG OUTPERFORM" : "OUTPERFORM" };
  if (s.includes("UNDERPERFORM") || s.includes("UNDERWEIGHT"))
    return { color: T.red, bg: "rgba(255,61,90,0.10)", border: "rgba(255,61,90,0.28)", icon: "▼",
             label: s.includes("UNDERWEIGHT") ? "UNDERWEIGHT" : "UNDERPERFORM" };
  return { color: T.t3, bg: "rgba(255,255,255,0.04)", border: T.border, icon: "—", label: "NEUTRAL" };
}

const GRADE_COLOR = { "A+": T.green, "A": T.green, "B+": T.cyan, "B": T.cyan,
                      "C+": T.gold, "C": T.gold, "D": T.amber, "F": T.red };

function timeAgo(iso) {
  if (!iso) return "";
  const d = new Date(iso.length <= 10 ? iso + "T00:00:00Z" : iso);
  const mins = Math.max(0, Math.floor((Date.now() - d.getTime()) / 60000));
  if (mins < 60) return `${mins}m`;
  if (mins < 1440) return `${Math.floor(mins / 60)}h`;
  return `${Math.floor(mins / 1440)}d`;
}

/* ─── Fetch ──────────────────────────────────────────────────────────────── */
async function fetchFeed() {
  try {
    const r = await fetch("/api/v1/signals/feed");
    if (!r.ok) throw new Error(`API ${r.status}`);
    const d = await r.json();
    return { signals: d.signals || [], accuracy: d.accuracy || null, version: d.version || "?" };
  } catch (e) {
    console.error("SignalFeed fetch:", e);
    return { signals: [], accuracy: null, version: "?" };
  }
}

/* ─── Card ───────────────────────────────────────────────────────────────── */
const SignalCard = ({ signal, onClick }) => {
  const d = dirStyle(signal.direction);
  const resolved = signal.status === "resolved" && signal.outcome;
  const gradeColor = GRADE_COLOR[signal.conviction_grade] || T.t3;
  return (
    <div
      onClick={() => onClick && onClick(signal)}
      style={{
        padding: "13px 14px", borderBottom: "1px solid rgba(37,99,235,0.10)",
        borderLeft: `3px solid ${d.color}`, background: "transparent",
        cursor: onClick ? "pointer" : "default", transition: "background 0.14s",
      }}
      onMouseEnter={(e) => (e.currentTarget.style.background = "rgba(255,255,255,0.02)")}
      onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
    >
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, minWidth: 0 }}>
          <span style={{ fontFamily: FONTS.brand, fontWeight: 700, fontSize: 15, color: T.t1 }}>
            {signal.symbol}
          </span>
          <span style={{
            fontFamily: FONTS.mono, fontSize: 9.5, fontWeight: 600, letterSpacing: "0.06em",
            color: d.color, background: d.bg, border: `1px solid ${d.border}`,
            padding: "2px 7px", borderRadius: 100, whiteSpace: "nowrap",
          }}>{d.icon} {d.label}</span>
          {signal.conviction_grade && (
            <span style={{ fontFamily: FONTS.mono, fontSize: 10, fontWeight: 700, color: gradeColor }}>
              {signal.conviction_grade}
            </span>
          )}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8, flexShrink: 0 }}>
          {/* status pill */}
          <span style={{
            fontFamily: FONTS.mono, fontSize: 8.5, letterSpacing: "0.10em",
            color: resolved ? T.t3 : T.cyan,
            border: `1px solid ${resolved ? T.border : "rgba(0,200,224,0.3)"}`,
            padding: "2px 6px", borderRadius: 3, textTransform: "uppercase",
          }}>{resolved ? "resolved" : "live"}</span>
          <span style={{ fontFamily: FONTS.mono, fontSize: 10, color: T.t4 }}>{timeAgo(signal.timestamp)}</span>
        </div>
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: 14, marginTop: 8, flexWrap: "wrap" }}>
        <Meta label="source" value={signal.source} />
        {signal.regime && <Meta label="regime" value={signal.regime} />}
        <Meta label="horizon" value={signal.horizon} />
        {resolved && (
          <span style={{
            fontFamily: FONTS.mono, fontSize: 11, fontWeight: 600,
            color: signal.outcome.hit ? T.green : T.red,
          }}>
            {signal.outcome.hit ? "✓ hit" : "✗ miss"} · 30d α {signal.outcome.alpha_30d_pct >= 0 ? "+" : ""}
            {signal.outcome.alpha_30d_pct}%
          </span>
        )}
      </div>
    </div>
  );
};

const Meta = ({ label, value }) => (
  <span style={{ display: "flex", alignItems: "center", gap: 5 }}>
    <span style={{ fontFamily: FONTS.mono, fontSize: 8.5, letterSpacing: "0.08em", color: T.t4, textTransform: "uppercase" }}>{label}</span>
    <span style={{ fontFamily: FONTS.mono, fontSize: 10.5, color: T.t2 }}>{value}</span>
  </span>
);

const SkeletonRow = () => (
  <div style={{ padding: "16px 14px", borderBottom: "1px solid rgba(37,99,235,0.08)" }}>
    <div style={{ height: 12, width: "40%", background: "rgba(255,255,255,0.05)", borderRadius: 4, marginBottom: 8 }} />
    <div style={{ height: 9, width: "65%", background: "rgba(255,255,255,0.03)", borderRadius: 4 }} />
  </div>
);

/* ─── Main ───────────────────────────────────────────────────────────────── */
const FILTERS = ["all", "live", "resolved"];

export default function SignalFeed({ onSignalClick, refreshTrigger = 0 }) {
  const [loading, setLoading] = useState(true);
  const [signals, setSignals] = useState([]);
  const [accuracy, setAccuracy] = useState(null);
  const [lastUpdate, setLastUpdate] = useState(null);
  const [filter, setFilter] = useState("all");

  const load = useCallback(async () => {
    const { signals: s, accuracy: a } = await fetchFeed();
    setSignals(s);
    setAccuracy(a);
    setLastUpdate(new Date());
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [refreshTrigger, load]);
  useEffect(() => { const i = setInterval(load, 120000); return () => clearInterval(i); }, [load]);

  const shown = signals.filter((s) => filter === "all" || s.status === filter);

  return (
    <div style={{ background: T.surface, border: `1px solid ${T.border}`, borderRadius: 14, overflow: "hidden" }}>
      {/* header */}
      <div style={{ padding: "16px 16px 12px", borderBottom: `1px solid ${T.border}` }}>
        <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: 10, flexWrap: "wrap" }}>
          <div style={{ fontFamily: FONTS.brand, fontWeight: 700, fontSize: 15, color: T.t1 }}>
            Signal Feed
          </div>
          {lastUpdate && (
            <span style={{ fontFamily: FONTS.mono, fontSize: 9.5, color: T.t4 }}>
              updated {lastUpdate.toLocaleTimeString()}
            </span>
          )}
        </div>

        {/* honest accuracy — the only performance we surface (a trust signal, not the machine) */}
        {accuracy && accuracy.resolved_30d_directional_pct != null && (
          <div style={{ marginTop: 10, display: "flex", alignItems: "center", gap: 16, flexWrap: "wrap" }}>
            <div>
              <span style={{ fontFamily: FONTS.mono, fontSize: 20, fontWeight: 500, color: T.green }}>
                {accuracy.resolved_30d_directional_pct}%
              </span>
              <span style={{ fontFamily: FONTS.mono, fontSize: 9, color: T.t3, marginLeft: 6, letterSpacing: "0.06em" }}>
                30D DIRECTIONAL · n={accuracy.n}
              </span>
            </div>
            {accuracy.avg_alpha_30d_pct != null && (
              <div style={{ fontFamily: FONTS.mono, fontSize: 11, color: T.t2 }}>
                avg 30d α <span style={{ color: accuracy.avg_alpha_30d_pct >= 0 ? T.green : T.red }}>
                  {accuracy.avg_alpha_30d_pct >= 0 ? "+" : ""}{accuracy.avg_alpha_30d_pct}%
                </span>
              </div>
            )}
          </div>
        )}

        {/* filters */}
        <div style={{ display: "flex", gap: 6, marginTop: 12 }}>
          {FILTERS.map((f) => (
            <button key={f} onClick={() => setFilter(f)} style={{
              fontFamily: FONTS.mono, fontSize: 9.5, letterSpacing: "0.08em", textTransform: "uppercase",
              padding: "4px 10px", borderRadius: 100, cursor: "pointer",
              color: filter === f ? T.void : T.t3,
              background: filter === f ? T.cyan : "transparent",
              border: `1px solid ${filter === f ? T.cyan : T.border}`,
            }}>{f}</button>
          ))}
        </div>
      </div>

      {/* list */}
      <div>
        {loading
          ? Array(4).fill(0).map((_, i) => <SkeletonRow key={i} />)
          : shown.length === 0
            ? <div style={{ padding: "28px 16px", textAlign: "center", fontFamily: FONTS.mono, fontSize: 11, color: T.t3 }}>
                No {filter === "all" ? "" : filter} signals in the stream.
              </div>
            : shown.map((s) => <SignalCard key={s.id ?? `${s.symbol}-${s.timestamp}`} signal={s} onClick={onSignalClick} />)}
      </div>

      {/* footer — honest, compliance */}
      <div style={{ padding: "10px 16px", borderTop: `1px solid ${T.border}`, fontFamily: FONTS.mono, fontSize: 8.5, color: T.t4, letterSpacing: "0.03em" }}>
        Positioning language only · benchmark-relative 30d outcomes on our own resolved calls · not investment advice
      </div>
    </div>
  );
}
