import { useState, useEffect } from "react";
import { T, FONTS } from "../tokens";

const API_BASE = "/api/v1";

const COUNTRIES = [
  { key: "us", label: "United States", flag: "🇺🇸" },
  { key: "hk", label: "Hong Kong",     flag: "🇭🇰" },
  { key: "cn", label: "China",         flag: "🇨🇳" },
];

const COLS = [
  { key: "cpi_yoy",       label: "CPI",   fmt: v => v != null ? `${v.toFixed(1)}%` : "—", good: v => v < 3 },
  { key: "gdp_growth",    label: "GDP",   fmt: v => v != null ? `${v.toFixed(1)}%` : "—", good: v => v > 2 },
  { key: "interest_rate", label: "Rate",  fmt: v => v != null ? `${v.toFixed(2)}%` : "—", good: v => v < 4 },
  { key: "unemployment",  label: "U/E",   fmt: v => v != null ? `${v.toFixed(1)}%` : "—", good: v => v < 5 },
  { key: "pmi",           label: "PMI",   fmt: v => v != null ? v.toFixed(1) : "—",        good: v => v > 50 },
];

const REGIME_COLORS = {
  GOLDILOCKS:  { color: T.green  },
  RISK_ON:     { color: T.cyan   },
  EASING:      { color: T.indigo },
  NEUTRAL:     { color: T.t3     },
  TIGHTENING:  { color: T.gold   },
  RISK_OFF:    { color: T.amber  },
  STAGFLATION: { color: T.red    },
  UNKNOWN:     { color: T.t3     },
};

/* ─── Single skeleton row ────────────────────────────────────────────── */
const SkeletonRow = () => (
  <div style={{
    display: "grid",
    gridTemplateColumns: "140px repeat(5, 1fr) 90px",
    gap: 0,
    padding: "10px 0",
    borderBottom: `1px solid ${T.border}`,
    alignItems: "center",
  }}>
    <div className="sk" style={{ height: 10, width: "70%", borderRadius: 2 }} />
    {COLS.map((_, i) => (
      <div key={i} className="sk" style={{ height: 10, width: "50%", borderRadius: 2, justifySelf: "end" }} />
    ))}
    <div className="sk" style={{ height: 10, width: "60%", borderRadius: 2, justifySelf: "end" }} />
  </div>
);

/* ─── Main component ─────────────────────────────────────────────────── */
export default function EconomicIndicators() {
  const [data, setData]     = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError]   = useState(null);
  const [lastFetch, setLastFetch] = useState(null);

  useEffect(() => {
    let cancelled = false;
    async function fetch_data() {
      try {
        const r = await fetch(`${API_BASE}/market/economic-indicators`);
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const json = await r.json();
        if (!cancelled) { setData(json); setLastFetch(new Date()); }
      } catch (e) {
        if (!cancelled) setError(e.message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    fetch_data();
    const interval = setInterval(fetch_data, 4 * 3600 * 1000);
    return () => { cancelled = true; clearInterval(interval); };
  }, []);

  // Hide if unavailable / error
  if (!loading && (error || (data && !data.available))) return null;

  return (
    <div style={{ marginBottom: 32 }}>
      {/* Section header — thin rule, no badge box */}
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        marginBottom: 16, paddingBottom: 10,
        borderBottom: `1px solid rgba(37,99,235,0.10)`,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{
            fontFamily: FONTS.display, fontSize: 11, fontWeight: 700,
            letterSpacing: "0.12em", color: T.t2, textTransform: "uppercase",
          }}>
            Economic Indicators
          </span>
          <span style={{ fontFamily: FONTS.mono, fontSize: 8, color: T.t3, opacity: 0.4 }}>
            EODHD · 4h cache
          </span>
        </div>
        {lastFetch && (
          <span style={{ fontFamily: FONTS.mono, fontSize: 9, color: T.t3, opacity: 0.5 }}>
            {lastFetch.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
          </span>
        )}
      </div>

      {/* Table */}
      <div style={{ width: "100%", overflowX: "auto" }}>
        {/* Column headers */}
        <div style={{
          display: "grid",
          gridTemplateColumns: "140px repeat(5, 1fr) 90px",
          gap: 0,
          paddingBottom: 8,
          borderBottom: `1px solid rgba(37,99,235,0.14)`,
        }}>
          <span style={{ fontFamily: FONTS.mono, fontSize: 8, color: T.t3, opacity: 0.5, letterSpacing: "0.08em", textTransform: "uppercase" }}>
            Country
          </span>
          {COLS.map(c => (
            <span key={c.key} style={{
              fontFamily: FONTS.mono, fontSize: 8, color: T.t3, opacity: 0.5,
              letterSpacing: "0.08em", textTransform: "uppercase",
              textAlign: "right",
            }}>
              {c.label}
            </span>
          ))}
          <span style={{
            fontFamily: FONTS.mono, fontSize: 8, color: T.t3, opacity: 0.5,
            letterSpacing: "0.08em", textTransform: "uppercase", textAlign: "right",
          }}>
            Regime
          </span>
        </div>

        {/* Data rows */}
        {loading
          ? COUNTRIES.map(c => <SkeletonRow key={c.key} />)
          : COUNTRIES.map((country, idx) => {
              const d = data?.[country.key];
              const inds = d?.indicators || {};
              const regime = d?.derived_regime || "UNKNOWN";
              const rc = REGIME_COLORS[regime] || REGIME_COLORS.UNKNOWN;
              const isLast = idx === COUNTRIES.length - 1;

              return (
                <div key={country.key} style={{
                  display: "grid",
                  gridTemplateColumns: "140px repeat(5, 1fr) 90px",
                  gap: 0,
                  padding: "10px 0",
                  borderBottom: isLast ? "none" : `1px solid rgba(37,99,235,0.07)`,
                  alignItems: "center",
                  transition: "background .12s ease",
                }}
                  onMouseEnter={e => e.currentTarget.style.background = "rgba(37,99,235,0.04)"}
                  onMouseLeave={e => e.currentTarget.style.background = "transparent"}
                >
                  {/* Country */}
                  <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
                    <span style={{ fontSize: 13 }}>{country.flag}</span>
                    <span style={{ fontFamily: FONTS.display, fontSize: 12, fontWeight: 600, color: T.t1 }}>
                      {country.label}
                    </span>
                  </div>

                  {/* Indicators */}
                  {COLS.map(col => {
                    const ind = inds[col.key];
                    const val = ind?.value;
                    const isGood = val != null ? col.good(val) : null;
                    const trend = ind?.trend;
                    return (
                      <div key={col.key} style={{ textAlign: "right" }}>
                        <span style={{
                          fontFamily: FONTS.mono, fontSize: 12, fontWeight: 600,
                          color: isGood === null ? T.t3
                               : isGood ? T.green : T.amber,
                        }}>
                          {col.fmt(val)}
                        </span>
                        {trend && (
                          <span style={{
                            fontSize: 9, fontFamily: FONTS.mono, marginLeft: 2,
                            color: trend === "up" ? T.green : T.red, opacity: 0.8,
                          }}>
                            {trend === "up" ? "↑" : "↓"}
                          </span>
                        )}
                      </div>
                    );
                  })}

                  {/* Regime — plain text, no badge */}
                  <div style={{ textAlign: "right" }}>
                    <span style={{
                      fontFamily: FONTS.mono, fontSize: 10, fontWeight: 700,
                      letterSpacing: "0.06em", color: rc.color,
                    }}>
                      {regime.replace("_", " ")}
                    </span>
                  </div>
                </div>
              );
            })
        }
      </div>
    </div>
  );
}
