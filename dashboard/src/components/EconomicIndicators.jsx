import { useState, useEffect } from "react";
import { T, FONTS } from "../tokens";

const API_BASE = "/api/v1";

/* ─── Country config ─────────────────────────────────────────────────── */
const COUNTRIES = [
  { key: "us", label: "United States", flag: "🇺🇸", currency: "USD" },
  { key: "hk", label: "Hong Kong",     flag: "🇭🇰", currency: "HKD" },
  { key: "cn", label: "China",         flag: "🇨🇳", currency: "CNY" },
];

const INDICATOR_LABELS = {
  cpi_yoy:       { label: "CPI YoY",    fmt: (v) => v != null ? `${v.toFixed(1)}%` : "—", good: (v) => v < 3 },
  gdp_growth:    { label: "GDP Growth", fmt: (v) => v != null ? `${v.toFixed(1)}%` : "—", good: (v) => v > 2 },
  interest_rate: { label: "Policy Rate",fmt: (v) => v != null ? `${v.toFixed(2)}%` : "—", good: (v) => v < 4 },
  unemployment:  { label: "Unemploy.",  fmt: (v) => v != null ? `${v.toFixed(1)}%` : "—", good: (v) => v < 5 },
  pmi:           { label: "PMI",        fmt: (v) => v != null ? v.toFixed(1) : "—",         good: (v) => v > 50 },
};

const REGIME_COLORS = {
  GOLDILOCKS:  { color: T.green,  bg: "rgba(0,232,122,0.12)", border: "rgba(0,232,122,0.25)" },
  RISK_ON:     { color: T.cyan,   bg: "rgba(0,200,224,0.10)", border: "rgba(0,200,224,0.2)"  },
  EASING:      { color: T.indigo, bg: "rgba(99,102,241,0.10)",border: "rgba(99,102,241,0.2)" },
  NEUTRAL:     { color: T.t3,     bg: "rgba(255,255,255,0.04)", border: T.border              },
  TIGHTENING:  { color: T.gold,   bg: "rgba(200,168,75,0.10)", border: "rgba(200,168,75,0.2)" },
  RISK_OFF:    { color: T.amber,  bg: "rgba(245,158,11,0.10)", border: "rgba(245,158,11,0.2)" },
  STAGFLATION: { color: T.red,    bg: "rgba(255,61,90,0.10)",  border: "rgba(255,61,90,0.2)"  },
  UNKNOWN:     { color: T.t3,     bg: "rgba(255,255,255,0.03)", border: T.border              },
};

/* ─── Trend arrow ────────────────────────────────────────────────────── */
const Trend = ({ trend }) => {
  if (!trend) return null;
  const up = trend === "up";
  return (
    <span style={{
      fontSize: 9, fontFamily: FONTS.mono, marginLeft: 3,
      color: up ? T.green : T.red, opacity: 0.8,
    }}>
      {up ? "↑" : "↓"}
    </span>
  );
};

/* ─── Country panel ──────────────────────────────────────────────────── */
const CountryPanel = ({ flag, label, data }) => {
  if (!data || data.error) {
    return (
      <div style={{
        flex: 1, minWidth: 160,
        border: `1px solid ${T.border}`, borderRadius: 10,
        padding: "14px 16px", background: T.surface,
      }}>
        <div style={{ fontSize: 13, marginBottom: 8 }}>{flag} <span style={{ fontFamily: FONTS.display, fontSize: 11, fontWeight: 700, color: T.t2 }}>{label}</span></div>
        <div style={{ fontFamily: FONTS.mono, fontSize: 10, color: T.t3, opacity: 0.5 }}>No data</div>
      </div>
    );
  }

  const indicators = data.indicators || {};
  const regime = data.derived_regime || "UNKNOWN";
  const rc = REGIME_COLORS[regime] || REGIME_COLORS.UNKNOWN;

  return (
    <div style={{
      flex: 1, minWidth: 160,
      border: `1px solid ${T.border}`, borderRadius: 10,
      background: T.surface, overflow: "hidden",
    }}>
      {/* Country header */}
      <div style={{
        padding: "10px 14px", borderBottom: `1px solid ${T.border}`,
        background: T.raised,
        display: "flex", alignItems: "center", justifyContent: "space-between",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
          <span style={{ fontSize: 14 }}>{flag}</span>
          <span style={{ fontFamily: FONTS.display, fontSize: 11, fontWeight: 700, color: T.t1, letterSpacing: "0.04em" }}>
            {label}
          </span>
        </div>
        <div style={{
          fontFamily: FONTS.mono, fontSize: 8, fontWeight: 700,
          letterSpacing: "0.08em", padding: "2px 7px", borderRadius: 3,
          background: rc.bg, color: rc.color, border: `1px solid ${rc.border}`,
        }}>
          {regime.replace("_", " ")}
        </div>
      </div>

      {/* Indicators */}
      <div style={{ padding: "10px 14px", display: "flex", flexDirection: "column", gap: 7 }}>
        {Object.entries(INDICATOR_LABELS).map(([key, cfg]) => {
          const ind = indicators[key];
          if (!ind) return null;
          const val = ind.value;
          const isGood = cfg.good(val);

          return (
            <div key={key} style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <span style={{
                fontFamily: FONTS.mono, fontSize: 9, color: T.t3,
                letterSpacing: "0.04em", textTransform: "uppercase",
              }}>
                {cfg.label}
              </span>
              <div style={{ display: "flex", alignItems: "center" }}>
                <span style={{
                  fontFamily: FONTS.mono, fontSize: 11, fontWeight: 700,
                  color: isGood ? T.green : T.amber,
                }}>
                  {cfg.fmt(val)}
                </span>
                <Trend trend={ind.trend} />
              </div>
            </div>
          );
        })}
      </div>

      {/* Date watermark */}
      {indicators.cpi_yoy?.date && (
        <div style={{
          padding: "4px 14px 8px", fontFamily: FONTS.mono,
          fontSize: 8, color: T.t3, opacity: 0.4,
        }}>
          Latest: {indicators.cpi_yoy.date}
        </div>
      )}
    </div>
  );
};

/* ─── Skeleton ───────────────────────────────────────────────────────── */
const SkeletonPanel = () => (
  <div style={{
    flex: 1, minWidth: 160, border: `1px solid ${T.border}`,
    borderRadius: 10, background: T.surface, padding: "14px 16px",
  }}>
    <div className="sk" style={{ height: 14, width: "60%", borderRadius: 4, marginBottom: 12 }} />
    {[80, 90, 70, 75, 65].map((w, i) => (
      <div key={i} style={{ display: "flex", justifyContent: "space-between", marginBottom: 8 }}>
        <div className="sk" style={{ height: 10, width: `${w * 0.4}%`, borderRadius: 2 }} />
        <div className="sk" style={{ height: 10, width: "18%", borderRadius: 2 }} />
      </div>
    ))}
  </div>
);

/* ─── Main component ─────────────────────────────────────────────────── */
export default function EconomicIndicators() {
  const [data, setData]       = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError]     = useState(null);
  const [lastFetch, setLastFetch] = useState(null);

  useEffect(() => {
    let cancelled = false;
    async function fetch_data() {
      try {
        const r = await fetch(`${API_BASE}/market/economic-indicators`);
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const json = await r.json();
        if (!cancelled) {
          setData(json);
          setLastFetch(new Date());
        }
      } catch (e) {
        if (!cancelled) setError(e.message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    fetch_data();
    // Refresh every 4 hours (matches backend TTL)
    const interval = setInterval(fetch_data, 4 * 3600 * 1000);
    return () => { cancelled = true; clearInterval(interval); };
  }, []);

  const usRegime = data?.us_regime;
  const rc = usRegime ? (REGIME_COLORS[usRegime] || REGIME_COLORS.UNKNOWN) : null;

  return (
    <div style={{ marginBottom: 28 }}>
      {/* Section header */}
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        marginBottom: 14, flexWrap: "wrap", gap: 8,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ width: 14, height: 1, background: T.indigo, opacity: 0.6 }} />
          <span style={{
            fontFamily: FONTS.display, fontSize: 11, fontWeight: 700,
            letterSpacing: "0.12em", color: T.t1, textTransform: "uppercase",
          }}>
            Economic Indicators
          </span>
          <span style={{
            fontFamily: FONTS.mono, fontSize: 8, color: T.t3,
            opacity: 0.5, fontWeight: 400,
          }}>
            EODHD · 4h cache
          </span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          {rc && usRegime && (
            <span style={{
              fontFamily: FONTS.mono, fontSize: 8, fontWeight: 700,
              letterSpacing: "0.08em", padding: "2px 8px", borderRadius: 3,
              background: rc.bg, color: rc.color, border: `1px solid ${rc.border}`,
            }}>
              US: {usRegime.replace("_", " ")}
            </span>
          )}
          {lastFetch && (
            <span style={{ fontFamily: FONTS.mono, fontSize: 9, color: T.t3 }}>
              {lastFetch.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
            </span>
          )}
        </div>
      </div>

      {/* Not available notice */}
      {!loading && data && !data.available && (
        <div style={{
          padding: "12px 16px", borderRadius: 8,
          background: "rgba(200,168,75,0.06)", border: "1px solid rgba(200,168,75,0.2)",
          fontFamily: FONTS.body, fontSize: 11, color: T.gold,
        }}>
          ⚡ EODHD key not configured — add <code style={{ fontFamily: FONTS.mono }}>EODHD_API_KEY</code> to Railway Variables.
        </div>
      )}

      {/* Error */}
      {!loading && error && (
        <div style={{
          padding: "12px 16px", borderRadius: 8,
          background: "rgba(255,61,90,0.06)", border: "1px solid rgba(255,61,90,0.2)",
          fontFamily: FONTS.mono, fontSize: 10, color: T.red,
        }}>
          Failed to load: {error}
        </div>
      )}

      {/* Panels */}
      {(loading || (data && data.available)) && (
        <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
          {loading ? (
            COUNTRIES.map(c => <SkeletonPanel key={c.key} />)
          ) : (
            COUNTRIES.map(c => (
              <CountryPanel
                key={c.key}
                flag={c.flag}
                label={c.label}
                data={data?.[c.key]}
              />
            ))
          )}
        </div>
      )}
    </div>
  );
}
