/**
 * 顶格 Monitor — tokenized-RWA perp funding extremes.
 * Data: GET /api/v1/signals/dingge-board (src/data/signals/dingge_rwa.py).
 * Structural signal: RWA perps (MSTR/NVDA/gold/silver/...) trade 24/7 on-chain vs a
 * CLOSED underlying → weekend/after-hours funding pins the cap → old trend exhausts →
 * new trend forms, direction set by 量能 (volume). Candidate, not auto-traded.
 */
import { useState, useEffect } from "react";
import { T, FONTS as F } from "../tokens";

const SIDE_COLOR = { long_crowded: "#ef4444", short_crowded: "#10b981" };   // crowded longs=flush risk / shorts=squeeze
const LEAN_COLOR = { up_bias: "#10b981", down_bias: "#ef4444", neutral: T.muted };

function fmtSide(s) {
  return s === "long_crowded" ? "CROWDED LONG" : s === "short_crowded" ? "CROWDED SHORT" : "—";
}

export default function DinggeBoard() {
  const [data, setData] = useState(null);
  const [err, setErr] = useState(false);
  useEffect(() => {
    const load = () => fetch("/api/v1/signals/dingge-board")
      .then(r => (r.ok ? r.json() : Promise.reject()))
      .then(setData).catch(() => setErr(true));
    load();
    const iv = setInterval(load, 600_000);   // 10 min
    return () => clearInterval(iv);
  }, []);

  if (err) return null;
  const board = (data && data.board) || [];
  const active = board.filter(b => b.at_cap || (b.days_since_cap != null && b.days_since_cap <= 45));
  const shown = active.length ? active : board.slice(0, 6);

  return (
    <div style={{ marginTop: 28 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 4 }}>
        <div style={{ width: 2, height: 16, background: T.amber || "#f59e0b", borderRadius: 1 }} />
        <span style={{ fontFamily: F.display, fontSize: 16, fontWeight: 800, color: T.t1 }}>顶格 Monitor</span>
        <span style={{ fontFamily: F.mono, fontSize: 8, fontWeight: 700, padding: "3px 8px", borderRadius: 4, background: "rgba(245,158,11,0.10)", color: T.amber || "#f59e0b", letterSpacing: ".1em" }}>
          RWA FUNDING EXTREMES
        </span>
        {data && (
          <span style={{ fontFamily: F.mono, fontSize: 9, color: T.muted, marginLeft: "auto" }}>
            {data.active_or_recent || 0} active/recent · {board.length} tracked
          </span>
        )}
      </div>
      <p style={{ fontFamily: F.body, fontSize: 12, color: T.t2, lineHeight: 1.6, maxWidth: 640, margin: "0 0 14px", paddingLeft: 12 }}>
        Tokenized stock/commodity perps trade 24/7 on-chain while their underlying is closed — so a
        weekend move pins funding at the exchange cap. The old trend exhausts; a new one forms, its
        direction set by 量能 (volume). Watch, don't auto-trade.
      </p>

      {!data ? (
        <div style={{ fontFamily: F.mono, fontSize: 10, color: T.muted, paddingLeft: 12 }}>Loading…</div>
      ) : shown.length === 0 ? (
        <div style={{ fontFamily: F.mono, fontSize: 10, color: T.muted, paddingLeft: 12 }}>No 顶格 events in the recent window.</div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {shown.map(b => (
            <div key={b.symbol} style={{
              display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap",
              background: "rgba(255,255,255,0.02)", borderRadius: 8, padding: "11px 14px",
              borderLeft: `2px solid ${SIDE_COLOR[b.side] || T.muted}`,
              border: "1px solid rgba(255,255,255,0.05)",
            }}>
              <span style={{ fontFamily: F.mono, fontSize: 13, fontWeight: 700, color: T.t1, minWidth: 90 }}>
                {b.symbol.replace("USDT", "")}
              </span>
              <span style={{ fontFamily: F.mono, fontSize: 9, fontWeight: 700, color: SIDE_COLOR[b.side] || T.muted, minWidth: 110 }}>
                {b.at_cap ? "🔴 AT CAP · " : ""}{fmtSide(b.side)}
              </span>
              <span style={{ fontFamily: F.mono, fontSize: 10, color: T.t2 }}>
                {b.days_since_cap != null ? `${b.days_since_cap}d ago` : "—"}
              </span>
              {b.peak_abs_funding_annualized_pct != null && (
                <span style={{ fontFamily: F.mono, fontSize: 10, color: T.amber || "#f59e0b" }}>
                  {Math.round(b.peak_abs_funding_annualized_pct)}%/yr peak
                </span>
              )}
              {b.volume_ratio != null && (
                <span style={{ fontFamily: F.mono, fontSize: 10, color: b.volume_ratio > 1.1 ? "#10b981" : b.volume_ratio < 0.9 ? "#ef4444" : T.muted }}>
                  量能 {b.volume_ratio}×
                </span>
              )}
              <span style={{
                fontFamily: F.mono, fontSize: 9, fontWeight: 700, padding: "2px 8px", borderRadius: 4,
                marginLeft: "auto", color: LEAN_COLOR[b.lean] || T.muted,
                background: `${LEAN_COLOR[b.lean] || T.muted}14`,
              }}>
                {(b.lean || "neutral").replace("_", " ").toUpperCase()}
              </span>
            </div>
          ))}
        </div>
      )}
      <div style={{ fontFamily: F.mono, fontSize: 8, color: T.muted, opacity: 0.5, marginTop: 8, paddingLeft: 12 }}>
        Candidate signal · n=40 episodes · volume-conditional (experiment_runs: funding_dingge_reversal). Not live capital.
      </div>
    </div>
  );
}
