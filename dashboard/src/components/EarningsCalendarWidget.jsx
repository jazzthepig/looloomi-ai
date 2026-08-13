// EarningsCalendarWidget.jsx — upcoming earnings for US equities in the CIS
// universe, fetched from /api/v1/market/earnings-calendar (EODHD backed).
// Renders nothing if the endpoint is empty/unavailable (no fabricated state).
// Extracted from App.jsx on 2026-08-13 (design audit, B2 split).

import { useState, useEffect } from "react";
import { T, FONTS } from "../tokens";
import { CompactSectionLabel } from "./SectionLabels";

export function EarningsCalendarWidget() {
  const [data, setData]       = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    fetch("/api/v1/market/earnings-calendar?symbols=AAPL,NVDA,MSFT,AMZN,GOOGL&days_ahead=30")
      .then(r => r.ok ? r.json() : null)
      .catch(() => null)
      .then(json => { if (!cancelled) { setData(json); setLoading(false); } });
    return () => { cancelled = true; };
  }, []);

  // Hide entirely if no data or empty / unavailable
  if (!loading && (!data || !data.available || !data.events?.length)) return null;

  const fmtDate = (d) => {
    if (!d) return "—";
    const dt = new Date(d);
    return dt.toLocaleDateString([], { month: "short", day: "numeric" });
  };
  const daysUntil = (d) => {
    if (!d) return null;
    const diff = Math.round((new Date(d) - new Date()) / 86400000);
    return diff;
  };

  return (
    <div style={{ marginTop: 28 }}>
      <CompactSectionLabel
        label="Earnings Calendar"
        meta="EODHD · next 30 days"
        accent="gold"
      />

      {loading ? (
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
          {[1,2,3,4].map(i => (
            <div key={i} className="sk" style={{ height: 54, width: 120, borderRadius: 8 }} />
          ))}
        </div>
      ) : (
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
          {(data.events || []).slice(0, 8).map((ev, i) => {
            const days = daysUntil(ev.date);
            const soon = days !== null && days <= 7;
            return (
              <div key={i} style={{
                background: soon ? "rgba(200,168,75,0.05)" : T.surface,
                border: `1px solid ${soon ? "rgba(200,168,75,0.3)" : T.border}`,
                borderRadius: 8, padding: "10px 14px", minWidth: 110,
              }}>
                <div style={{
                  fontFamily: FONTS.mono, fontSize: 13, fontWeight: 700,
                  color: T.t1, marginBottom: 3,
                }}>
                  {ev.symbol || ev.ticker}
                </div>
                <div style={{
                  fontFamily: FONTS.mono, fontSize: 10, color: T.t3, marginBottom: 4,
                }}>
                  {fmtDate(ev.date)}
                </div>
                {days !== null && (
                  <div style={{
                    fontFamily: FONTS.mono, fontSize: 8, fontWeight: 700,
                    letterSpacing: "0.06em",
                    color: soon ? T.gold : T.t3,
                  }}>
                    {days === 0 ? "TODAY" : days === 1 ? "TOMORROW" : `IN ${days}D`}
                  </div>
                )}
                {ev.eps_estimate != null && (
                  <div style={{
                    fontFamily: FONTS.mono, fontSize: 8, color: T.t3, opacity: 0.7, marginTop: 2,
                  }}>
                    EPS est. {ev.eps_estimate > 0 ? "+" : ""}{ev.eps_estimate?.toFixed(2)}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
