import { useState, useEffect, useRef } from "react";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Legend,
} from "recharts";
import { T, FONTS } from "../tokens";

/* ─── Constants ──────────────────────────────────────────────────────────── */
const API = import.meta.env.VITE_API_BASE || "";

const GRADE_ORDER = ["A+", "A", "B+", "B", "C+", "C", "D", "F"];
const GRADE_COLOR = {
  "A+": "#00D98A", "A": "#2ecc71", "B+": "#06b6d4", "B": "#3b82f6",
  "C+": "#f59e0b", "C": "#f97316", "D": "#ef4444", "F": "#6b7280",
};
const CLASS_COLOR = {
  L1: "#00D98A", L2: "#06b6d4", DeFi: "#818cf8", Infrastructure: "#f59e0b",
  RWA: "#d4a843", Memecoin: "#EC4899", TradFi: "#c7d2fe", Commodity: "#a78bfa",
  Gaming: "#f97316", AI: "#22d3ee",
};

const SECTION = {
  background: T.surface,
  border: `1px solid ${T.border}`,
  borderRadius: 12,
  padding: "24px 28px",
  marginBottom: 20,
};

// Normalize asset fields across T1/T2 response shapes
function normalizeAsset(a) {
  return {
    symbol:      (a.symbol || a.asset_id || "").toUpperCase(),
    name:        a.name || a.symbol || "",
    score:       a.cis_score ?? a.score ?? 0,
    grade:       a.grade || gradeForRaw(a.cis_score ?? a.score ?? 0),
    signal:      a.signal || "",
    asset_class: a.asset_class || a.class || "Other",
    data_tier:   a.data_tier || 2,
  };
}

function gradeForRaw(s) { return gradeForScore(s); }
function gradeForScore(score) {
  if (score >= 85) return "A+";
  if (score >= 75) return "A";
  if (score >= 65) return "B+";
  if (score >= 55) return "B";
  if (score >= 45) return "C+";
  if (score >= 35) return "C";
  if (score >= 25) return "D";
  return "F";
}

/* ─── Grade Migration Heatmap ────────────────────────────────────────────── */
function GradeHeatmap({ assets, historyMap }) {
  // Build 7 date labels (today → -6d)
  const days = [];
  for (let i = 6; i >= 0; i--) {
    const d = new Date();
    d.setDate(d.getDate() - i);
    days.push(d.toLocaleDateString("en-US", { month: "short", day: "numeric" }));
  }

  const rows = assets.slice(0, 20);
  const cellW = 52, cellH = 28;

  if (!rows.length) return (
    <div style={{ color: T.t3, fontFamily: FONTS.body, fontSize: 13, padding: "32px 0", textAlign: "center" }}>
      No asset data yet. Scores populate once CIS push is active.
    </div>
  );

  return (
    <div style={{ overflowX: "auto" }}>
      <div style={{ display: "grid", gridTemplateColumns: `100px repeat(7, ${cellW}px)`, gap: 1, minWidth: 480 }}>
        {/* Header */}
        <div style={{ fontSize: 10, color: T.t4, fontFamily: FONTS.mono, padding: "6px 0" }} />
        {days.map(d => (
          <div key={d} style={{ fontSize: 9, color: T.t3, fontFamily: FONTS.mono, textAlign: "center", padding: "6px 2px" }}>{d}</div>
        ))}

        {/* Rows */}
        {rows.map(asset => {
          const hist = historyMap[asset.symbol] || [];
          // Bucket history into 7 day slots
          const now = Date.now();
          const slotGrades = days.map((_, idx) => {
            const dayStart = now - (6 - idx) * 86400000;
            const dayEnd   = dayStart + 86400000;
            const inSlot   = hist.filter(h => {
              const ts = new Date(h.recorded_at || h.ts || 0).getTime();
              return ts >= dayStart && ts < dayEnd;
            });
            if (!inSlot.length) return asset.grade || gradeForScore(asset.score || 0);
            const avg = inSlot.reduce((s, h) => s + (h.score || 0), 0) / inSlot.length;
            return gradeForScore(avg);
          });

          return [
            <div key={`sym-${asset.symbol}`} style={{
              fontSize: 11, color: T.t2, fontFamily: FONTS.mono,
              display: "flex", alignItems: "center", padding: "2px 0",
              overflow: "hidden", whiteSpace: "nowrap",
            }}>
              {asset.symbol}
            </div>,
            ...slotGrades.map((grade, di) => (
              <div key={`${asset.symbol}-${di}`} style={{
                height: cellH, display: "flex", alignItems: "center", justifyContent: "center",
                background: `${GRADE_COLOR[grade]}18`,
                border: `1px solid ${GRADE_COLOR[grade]}30`,
                borderRadius: 4,
              }}>
                <span style={{ fontSize: 10, fontFamily: FONTS.mono, color: GRADE_COLOR[grade], fontWeight: 600 }}>
                  {grade}
                </span>
              </div>
            )),
          ];
        })}
      </div>

      {/* Grade legend */}
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 16 }}>
        {GRADE_ORDER.map(g => (
          <div key={g} style={{ display: "flex", alignItems: "center", gap: 4 }}>
            <div style={{ width: 10, height: 10, borderRadius: 2, background: GRADE_COLOR[g] }} />
            <span style={{ fontSize: 10, color: T.t3, fontFamily: FONTS.mono }}>{g}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

/* ─── Sector Rotation Chart ──────────────────────────────────────────────── */
function SectorRotation({ assets, historyMap }) {
  // Group assets by class, compute average score per day per class
  const classes = [...new Set(assets.map(a => a.asset_class).filter(Boolean))];

  const days = [];
  for (let i = 6; i >= 0; i--) {
    const d = new Date();
    d.setDate(d.getDate() - i);
    days.push({
      label: d.toLocaleDateString("en-US", { month: "short", day: "numeric" }),
      start: d.setHours(0, 0, 0, 0),
      end:   d + 86400000,
    });
  }

  const chartData = days.map(({ label, start, end }) => {
    const row = { date: label };
    classes.forEach(cls => {
      const classAssets = assets.filter(a => a.asset_class === cls);
      const scores = [];
      classAssets.forEach(asset => {
        const hist = historyMap[asset.symbol] || [];
        const inSlot = hist.filter(h => {
          const ts = new Date(h.recorded_at || h.ts || 0).getTime();
          return ts >= start && ts < end;
        });
        if (inSlot.length) {
          const avg = inSlot.reduce((s, h) => s + (h.score || 0), 0) / inSlot.length;
          scores.push(avg);
        } else if (asset.score) {
          scores.push(asset.score); // fallback to current
        }
      });
      if (scores.length) {
        row[cls] = parseFloat((scores.reduce((a, b) => a + b, 0) / scores.length).toFixed(1));
      }
    });
    return row;
  });

  if (!classes.length) return (
    <div style={{ color: T.t3, fontFamily: FONTS.body, fontSize: 13, padding: "32px 0", textAlign: "center" }}>
      Score history builds over time as Mac Mini pushes CIS scores every 30 minutes.
    </div>
  );

  return (
    <ResponsiveContainer width="100%" height={240}>
      <LineChart data={chartData} margin={{ top: 8, right: 16, left: -20, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke={T.border} />
        <XAxis dataKey="date" tick={{ fill: T.t3, fontSize: 9, fontFamily: FONTS.mono }} />
        <YAxis domain={[30, 80]} tick={{ fill: T.t3, fontSize: 9, fontFamily: FONTS.mono }} />
        <Tooltip
          contentStyle={{ background: T.raised, border: `1px solid ${T.borderMd}`, borderRadius: 8 }}
          labelStyle={{ color: T.t2, fontSize: 11, fontFamily: FONTS.mono }}
          itemStyle={{ fontSize: 10, fontFamily: FONTS.mono }}
          formatter={(val, name) => [`${val}`, name]}
        />
        <Legend
          wrapperStyle={{ fontSize: 10, fontFamily: FONTS.mono, color: T.t3 }}
          formatter={(value) => <span style={{ color: CLASS_COLOR[value] || T.t2 }}>{value}</span>}
        />
        {classes.map(cls => (
          <Line
            key={cls}
            type="monotone"
            dataKey={cls}
            stroke={CLASS_COLOR[cls] || T.t2}
            strokeWidth={1.5}
            dot={false}
            activeDot={{ r: 3 }}
            connectNulls
          />
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
}

/* ─── Grade Distribution Bar ─────────────────────────────────────────────── */
function GradeDistribution({ assets }) {
  const counts = {};
  GRADE_ORDER.forEach(g => counts[g] = 0);
  assets.forEach(a => { if (a.grade && counts[a.grade] !== undefined) counts[a.grade]++; });
  const total = assets.length || 1;

  return (
    <div style={{ display: "flex", gap: 0, height: 32, borderRadius: 6, overflow: "hidden", background: T.raised }}>
      {GRADE_ORDER.map(g => {
        const pct = (counts[g] / total) * 100;
        if (pct < 1) return null;
        return (
          <div
            key={g}
            title={`${g}: ${counts[g]} assets`}
            style={{
              width: `${pct}%`, background: `${GRADE_COLOR[g]}bb`,
              display: "flex", alignItems: "center", justifyContent: "center",
              transition: "width 0.3s",
            }}
          >
            {pct > 6 && <span style={{ fontSize: 9, fontFamily: FONTS.mono, color: "#fff", fontWeight: 700 }}>{g}</span>}
          </div>
        );
      })}
    </div>
  );
}

/* ─── Main Component ─────────────────────────────────────────────────────── */
// universe prop: raw array from CISLeaderboard (already fetched by parent) — avoids double-fetch
export default function ScoreAnalytics({ universe: universeProp = [] }) {
  const [universe, setUniverse] = useState([]);
  const [historyMap, setHistoryMap] = useState({});
  const [loading, setLoading] = useState(true);
  const [histLoading, setHistLoading] = useState(false);
  const [activeTab, setActiveTab] = useState("heatmap"); // heatmap | rotation
  const fetchedRef = useRef(false);

  // 1. If parent already has universe, use it directly; otherwise fetch independently
  useEffect(() => {
    if (universeProp.length > 0) {
      const assets = universeProp.map(normalizeAsset);
      setUniverse(assets);
      setLoading(false);
      return;
    }
    if (fetchedRef.current) return;
    fetchedRef.current = true;
    fetch(`${API}/api/v1/cis/universe`)
      .then(r => r.json())
      .then(d => {
        const raw = d.universe || d.assets || [];
        const assets = raw.map(normalizeAsset);
        setUniverse(assets);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, [universeProp]);

  // 2. Batch fetch history whenever universe changes
  useEffect(() => {
    if (!universe.length) return;
    const top20 = universe.slice(0, 20).map(a => a.symbol).join(",");
    setHistLoading(true);
    fetch(`${API}/api/v1/cis/history/batch?symbols=${top20}&days=7`)
      .then(r => r.json())
      .then(hd => {
        setHistoryMap(hd.data || hd.history || {});
        setHistLoading(false);
      })
      .catch(() => setHistLoading(false));
  }, [universe]);

  const tabs = [
    { id: "heatmap",  label: "Grade Heatmap" },
    { id: "rotation", label: "Sector Rotation" },
  ];

  return (
    <div style={{ fontFamily: FONTS.body }}>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 20 }}>
        <div>
          <h2 style={{ fontSize: 18, fontFamily: FONTS.display, color: T.t1, fontWeight: 700, margin: 0 }}>
            Score Analytics
          </h2>
          <p style={{ fontSize: 12, color: T.t3, margin: "4px 0 0", fontFamily: FONTS.body }}>
            7-day grade migration & sector rotation — updates every 30 min
          </p>
        </div>
        {histLoading && (
          <div style={{ fontSize: 10, color: T.t4, fontFamily: FONTS.mono, display: "flex", alignItems: "center", gap: 6 }}>
            <div style={{ width: 6, height: 6, borderRadius: "50%", background: T.blue, animation: "pulse 1.5s infinite" }} />
            Loading history…
          </div>
        )}
      </div>

      {/* Grade Distribution overview */}
      {!loading && universe.length > 0 && (
        <div style={{ ...SECTION, padding: "16px 20px", marginBottom: 16 }}>
          <div style={{ fontSize: 10, color: T.t3, fontFamily: FONTS.mono, marginBottom: 8, letterSpacing: "0.08em" }}>
            CURRENT GRADE DISTRIBUTION · {universe.length} ASSETS
          </div>
          <GradeDistribution assets={universe} />
          <div style={{ display: "flex", gap: 16, marginTop: 10, flexWrap: "wrap" }}>
            {Object.entries(
              universe.reduce((acc, a) => { acc[a.asset_class] = (acc[a.asset_class] || 0) + 1; return acc; }, {})
            ).map(([cls, n]) => (
              <span key={cls} style={{ fontSize: 10, fontFamily: FONTS.mono, color: CLASS_COLOR[cls] || T.t3 }}>
                {cls} <span style={{ color: T.t4 }}>{n}</span>
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Tabs */}
      <div style={{ display: "flex", gap: 4, marginBottom: 16 }}>
        {tabs.map(tab => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            style={{
              padding: "6px 16px", borderRadius: 6, border: "none", cursor: "pointer",
              fontFamily: FONTS.mono, fontSize: 11, letterSpacing: "0.06em",
              background: activeTab === tab.id ? T.blue : T.raised,
              color:      activeTab === tab.id ? "#fff"  : T.t3,
              transition: "all 0.15s",
            }}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* Content */}
      <div style={SECTION}>
        {loading ? (
          <div style={{ color: T.t3, fontFamily: FONTS.mono, fontSize: 12, padding: "24px 0", textAlign: "center" }}>
            Loading CIS universe…
          </div>
        ) : activeTab === "heatmap" ? (
          <>
            <div style={{ fontSize: 11, color: T.t3, fontFamily: FONTS.body, marginBottom: 16 }}>
              Grade per asset per day — color intensity indicates conviction. Daily average from 30-min intervals.
            </div>
            <GradeHeatmap assets={universe} historyMap={historyMap} />
          </>
        ) : (
          <>
            <div style={{ fontSize: 11, color: T.t3, fontFamily: FONTS.body, marginBottom: 16 }}>
              Average CIS score per asset class over 7 days. Reveals capital rotation between sectors.
            </div>
            <SectorRotation assets={universe} historyMap={historyMap} />
          </>
        )}
      </div>

      {/* Empty state hint */}
      {!loading && universe.length === 0 && (
        <div style={{ ...SECTION, textAlign: "center", padding: "40px 20px" }}>
          <div style={{ fontSize: 14, color: T.t2, fontFamily: FONTS.body, marginBottom: 8 }}>
            No score data yet
          </div>
          <div style={{ fontSize: 12, color: T.t3, fontFamily: FONTS.body }}>
            History accumulates as the Mac Mini CIS engine pushes scores every 30 minutes.
            Connect Supabase (SUPABASE_URL + SUPABASE_KEY in Railway) to persist history.
          </div>
        </div>
      )}
    </div>
  );
}
