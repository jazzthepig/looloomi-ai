/**
 * SignalAttribution — every CIS signal change for one asset, attributed (T-078).
 *
 * Why it changed: which pillars moved the score (pillar change × class base weight) and how the
 * price had already moved vs the scored universe in the 30 days before.
 * What followed: 7d / 30d return of the asset, of the equal-weight scored universe, and the difference.
 * Next to it: how signals of the same kind have done historically.
 *
 * Signals describe where an asset sits on past and current data; outcomes are history, not forecasts.
 */
import { useState, useEffect } from "react";
import { T, FONTS, sigStyle } from "../tokens";

const API = import.meta.env.VITE_API_URL || "";

const CRYPTO = new Set(["Crypto", "DeFi", "Gaming", "Infrastructure", "L1", "L2", "Memecoin", "RWA"]);
const PILLAR_LABEL = { F: "Fundamental", M: "Momentum", O: "On-chain / Risk", S: "Sentiment", A: "Alpha" };

const pct = (v, d = 1) => (v == null || isNaN(v)) ? "—" : `${v >= 0 ? "+" : ""}${(v * 100).toFixed(d)}%`;
const pts = (v) => (v == null || isNaN(v)) ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(2)}`;
const tone = (v) => v == null ? T.t3 : v > 0 ? T.green : v < 0 ? T.red : T.t3;
const addDays = (iso, n) => {
  const d = new Date(`${iso}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
};

const card = {
  background: "rgba(5,7,22,0.85)", border: `1px solid ${T.border}`, borderRadius: 10, padding: 20,
};
const label = {
  fontFamily: FONTS.display, fontSize: 10, color: T.t3, fontWeight: 700, letterSpacing: "0.08em",
};

const Skeleton = () => (
  <div style={{ ...card, marginTop: 24 }}>
    <div style={label}>SIGNAL ATTRIBUTION</div>
    {[0, 1, 2].map(i => (
      <div key={i} style={{ height: 14, marginTop: 14, borderRadius: 4,
        background: "linear-gradient(90deg, rgba(255,255,255,0.03), rgba(255,255,255,0.07), rgba(255,255,255,0.03))" }} />
    ))}
  </div>
);

const ContribBar = ({ k, name, v, max }) => (
  <div style={{ display: "grid", gridTemplateColumns: "92px 1fr 56px", alignItems: "center", gap: 8, marginBottom: 6 }}>
    <span style={{ fontFamily: FONTS.body, fontSize: 11, color: T.t3 }}>
      <span style={{ fontFamily: FONTS.mono, color: T.t2 }}>{k}</span> {name}
    </span>
    <div style={{ position: "relative", height: 6, background: "rgba(255,255,255,0.05)", borderRadius: 3 }}>
      <div style={{ position: "absolute", left: "50%", top: -2, bottom: -2, width: 1, background: T.border }} />
      {v != null && (
        <div style={{
          position: "absolute", top: 0, height: "100%", borderRadius: 3, background: tone(v),
          left: v >= 0 ? "50%" : `${50 - (Math.abs(v) / max) * 50}%`, width: `${(Math.abs(v) / max) * 50}%`,
        }} />
      )}
    </div>
    <span style={{ fontFamily: FONTS.mono, fontSize: 11, color: tone(v), textAlign: "right" }}>{pts(v)}</span>
  </div>
);

const Contribution = ({ contrib, residual }) => {
  const rows = ["F", "M", "O", "S", "A"].map(p => [p, contrib?.[p]]);
  const max = Math.max(1, ...rows.map(([, v]) => Math.abs(v ?? 0)), Math.abs(residual ?? 0));
  return (
    <div>
      {rows.map(([p, v]) => <ContribBar key={p} k={p} name={PILLAR_LABEL[p]} v={v} max={max} />)}
      <ContribBar k="·" name="Unexplained" v={residual} max={max} />
    </div>
  );
};

const After = ({ title, h, row }) => {
  const a = row.after?.[`${h}d`] || {};
  if (!a.matured) {
    return (
      <div>
        <div style={label}>{title}</div>
        <div style={{ fontFamily: FONTS.mono, fontSize: 11, color: T.t3, marginTop: 8 }}>
          Matures {addDays(row.date, h)}
        </div>
      </div>
    );
  }
  return (
    <div>
      <div style={label}>{title}</div>
      {[["Asset", a.return], ["Scored universe", a.universe_return], ["Relative", a.relative_to_universe]]
        .map(([k, v]) => (
          <div key={k} style={{ display: "flex", justifyContent: "space-between", marginTop: 6 }}>
            <span style={{ fontFamily: FONTS.body, fontSize: 11, color: T.t3 }}>{k}</span>
            <span style={{ fontFamily: FONTS.mono, fontSize: 11, color: k === "Relative" ? tone(v) : T.t2,
              fontWeight: k === "Relative" ? 700 : 400 }}>{pct(v)}</span>
          </div>
        ))}
    </div>
  );
};

const Held = ({ h }) => {
  if (!h || h.days == null) return null;
  if (h.reverted_within_3d) {
    return (
      <span style={{ fontFamily: FONTS.mono, fontSize: 10, color: T.gold, border: `1px solid ${T.gold}55`,
        borderRadius: 4, padding: "1px 6px", whiteSpace: "nowrap" }}>
        flipped back in {h.days}d
      </span>
    );
  }
  return (
    <span style={{ fontFamily: FONTS.mono, fontSize: 10, color: T.t3 }}>
      {h.next_signal ? `held ${h.days}d` : `current · ${h.days}d so far`}
    </span>
  );
};

export default function SignalAttribution({ symbol, assetClass, currentSignal }) {
  // Keyed by symbol: a result for another symbol reads as "still loading", so the effect never has to
  // reset state synchronously.
  const [state, setState] = useState({ sym: null, data: null, failed: false });

  useEffect(() => {
    if (!symbol) return;
    let live = true;
    fetch(`${API}/api/v1/cis/attribution?symbol=${encodeURIComponent(symbol)}&limit=8`)
      .then(r => { if (!r.ok) throw new Error(String(r.status)); return r.json(); })
      .then(d => { if (live) setState({ sym: symbol, data: d, failed: false }); })
      .catch(() => { if (live) setState({ sym: symbol, data: null, failed: true }); });
    return () => { live = false; };
  }, [symbol]);

  const mine = state.sym === symbol;
  const data = mine ? state.data : null;
  if (mine && state.failed) {
    return (
      <div style={{ ...card, marginTop: 24 }}>
        <div style={label}>SIGNAL ATTRIBUTION</div>
        <div style={{ fontFamily: FONTS.mono, fontSize: 11, color: T.gold, marginTop: 10 }}>
          Attribution could not be read right now — this is a read failure, not an absence of signals.
        </div>
      </div>
    );
  }
  if (!data) return <Skeleton />;

  const rows = data.signals || [];
  const latest = rows[0];
  const major = CRYPTO.has(assetClass) ? "crypto" : "tradfi";
  const sigNow = currentSignal || latest?.signal;
  const tr = data.track_record?.[major]?.[sigNow];
  const s = sigStyle(sigNow || "NEUTRAL");

  return (
    <div style={{ ...card, marginTop: 24, padding: 24 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 12, flexWrap: "wrap" }}>
        <h3 style={{ fontFamily: FONTS.brand, fontSize: 14, fontWeight: 700, color: T.t1, margin: 0, letterSpacing: "0.04em" }}>
          SIGNAL ATTRIBUTION
        </h3>
        <span style={{ fontFamily: FONTS.mono, fontSize: 10, color: T.t3 }}>
          Why each signal changed · what followed · relative to the scored universe
        </span>
      </div>

      {latest ? (
        <>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 18, flexWrap: "wrap" }}>
            <span style={{ fontFamily: FONTS.mono, fontSize: 11, color: T.t3 }}>{latest.date}</span>
            <span style={{ fontFamily: FONTS.mono, fontSize: 11, color: T.t3 }}>{latest.previous_signal}</span>
            <span style={{ color: T.t4 }}>→</span>
            <span style={{ fontFamily: FONTS.mono, fontSize: 11, fontWeight: 700, color: sigStyle(latest.signal).color }}>
              {latest.signal}
            </span>
            <span style={{ fontFamily: FONTS.mono, fontSize: 11, color: T.t3 }}>
              score {latest.previous_score?.toFixed?.(1) ?? "—"} → {latest.score?.toFixed?.(1) ?? "—"}
            </span>
            {latest.why?.main_driver && (
              <span style={{ fontFamily: FONTS.body, fontSize: 11, color: T.t2 }}>
                · main driver: <strong>{PILLAR_LABEL[latest.why.main_driver] || latest.why.main_driver}</strong>
              </span>
            )}
            <Held h={latest.held} />
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "1.4fr 1fr 1fr 1fr", gap: 20, marginTop: 16 }}
               className="attr-grid">
            <div>
              <div style={{ ...label, marginBottom: 10 }}>WHY · SCORE CONTRIBUTION BY PILLAR</div>
              <Contribution contrib={latest.why?.pillar_contributions} residual={latest.why?.unexplained} />
            </div>
            <div>
              <div style={label}>BEFORE · 30D</div>
              {[["Asset", latest.why?.return_30d_before], ["Relative", latest.why?.relative_30d_before]].map(([k, v]) => (
                <div key={k} style={{ display: "flex", justifyContent: "space-between", marginTop: 6 }}>
                  <span style={{ fontFamily: FONTS.body, fontSize: 11, color: T.t3 }}>{k}</span>
                  <span style={{ fontFamily: FONTS.mono, fontSize: 11, color: tone(v) }}>{pct(v)}</span>
                </div>
              ))}
              <div style={{ fontFamily: FONTS.body, fontSize: 10, color: T.t4, marginTop: 8, lineHeight: 1.4 }}>
                What had already happened when the signal changed.
              </div>
            </div>
            <After title="AFTER · 7D" h={7} row={latest} />
            <After title="AFTER · 30D" h={30} row={latest} />
          </div>

          {rows.length > 1 && (
            <div style={{ marginTop: 22 }}>
              <div style={{ ...label, marginBottom: 8 }}>EARLIER SIGNAL CHANGES</div>
              <div style={{ display: "grid", gridTemplateColumns: "92px 1fr 110px 120px 80px 80px 80px", gap: 8,
                fontFamily: FONTS.mono, fontSize: 10, color: T.t4, paddingBottom: 6, borderBottom: `1px solid ${T.border}` }}>
                <span>DATE</span><span>CHANGE</span><span>MAIN DRIVER</span><span>HELD</span>
                <span style={{ textAlign: "right" }}>30D BEFORE</span>
                <span style={{ textAlign: "right" }}>7D AFTER</span>
                <span style={{ textAlign: "right" }}>30D AFTER</span>
              </div>
              {rows.slice(1).map(r => (
                <div key={r.date} style={{ display: "grid", gridTemplateColumns: "92px 1fr 110px 120px 80px 80px 80px", gap: 8,
                  fontFamily: FONTS.mono, fontSize: 11, padding: "6px 0", borderBottom: `1px solid ${T.border}` }}>
                  <span style={{ color: T.t3 }}>{r.date}</span>
                  <span style={{ color: T.t2 }}>{r.previous_signal} → <span style={{ color: sigStyle(r.signal).color }}>{r.signal}</span></span>
                  <span style={{ color: T.t3 }}>{PILLAR_LABEL[r.why?.main_driver] || "—"}</span>
                  <span><Held h={r.held} /></span>
                  <span style={{ textAlign: "right", color: tone(r.why?.relative_30d_before) }}>{pct(r.why?.relative_30d_before)}</span>
                  <span style={{ textAlign: "right", color: tone(r.after?.["7d"]?.relative_to_universe) }}>
                    {r.after?.["7d"]?.matured ? pct(r.after["7d"].relative_to_universe) : "pending"}</span>
                  <span style={{ textAlign: "right", color: tone(r.after?.["30d"]?.relative_to_universe) }}>
                    {r.after?.["30d"]?.matured ? pct(r.after["30d"].relative_to_universe) : "pending"}</span>
                </div>
              ))}
              <div style={{ fontFamily: FONTS.body, fontSize: 10, color: T.t4, marginTop: 6 }}>
                Before / after columns are relative to the equal-weight scored universe.
              </div>
            </div>
          )}
        </>
      ) : (
        <div style={{ fontFamily: FONTS.body, fontSize: 12, color: T.t3, marginTop: 14 }}>
          This asset's signal has not changed since May 2025, so there is no change to attribute yet.
        </div>
      )}

      {tr && (
        <div style={{ marginTop: 22, padding: "14px 16px", background: s.bg, border: `1px solid ${s.border}`, borderRadius: 8 }}>
          <div style={{ ...label, color: s.color }}>
            HISTORICAL RECORD · PAST {sigNow} SIGNALS ({major === "crypto" ? "CRYPTO" : "TRADITIONAL ASSETS"})
          </div>
          <div style={{ display: "flex", gap: 22, flexWrap: "wrap", marginTop: 10 }}>
            {[["Signals", tr["30d"]?.n, (v) => v ?? "—"],
              ["Avg 30d vs universe", tr["30d"]?.mean_rel_pct, (v) => v == null ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`],
              ["Median 30d vs universe", tr["30d"]?.median_rel_pct, (v) => v == null ? "—" : `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`],
              ["Ahead of universe", tr["30d"]?.share_rel_positive, (v) => v == null ? "—" : `${Math.round(v * 100)}%`],
            ].map(([k, v, f]) => (
              <div key={k}>
                <div style={{ fontFamily: FONTS.body, fontSize: 10, color: T.t3 }}>{k}</div>
                <div style={{ fontFamily: FONTS.mono, fontSize: 14, fontWeight: 700, color: T.t1, marginTop: 2 }}>{f(v)}</div>
              </div>
            ))}
          </div>
          {tr.reverted_within_3d_share != null && (
            <div style={{ fontFamily: FONTS.mono, fontSize: 10, color: T.t3, marginTop: 10 }}>
              {Math.round(tr.reverted_within_3d_share * 100)}% of {tr.changes} past changes into {sigNow} flipped back within 3 days
              (grade-boundary noise) and are left out of the figures above.
            </div>
          )}
          {major === "crypto" && tr.btc_below_ma50 && tr.btc_above_ma50 && (
            <div style={{ fontFamily: FONTS.mono, fontSize: 10, color: T.t3, marginTop: 10 }}>
              BTC below its 50-day mean: avg {tr.btc_below_ma50["30d"]?.mean_rel_pct ?? "—"}% (n {tr.btc_below_ma50["30d"]?.n ?? 0})
              {" · "}above: avg {tr.btc_above_ma50["30d"]?.mean_rel_pct ?? "—"}% (n {tr.btc_above_ma50["30d"]?.n ?? 0})
            </div>
          )}
        </div>
      )}

      <div style={{ fontFamily: FONTS.body, fontSize: 10, color: T.t4, marginTop: 16, lineHeight: 1.5 }}>
        {data.disclosure}
      </div>

      <style>{`
        @media (max-width: 800px) { .attr-grid { grid-template-columns: 1fr 1fr !important; } }
        @media (max-width: 480px) { .attr-grid { grid-template-columns: 1fr !important; } }
      `}</style>
    </div>
  );
}
