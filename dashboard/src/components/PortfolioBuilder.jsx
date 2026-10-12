/**
 * PortfolioBuilder — pick strategies (paper books), set weights, see the combination's risk and where its
 * return comes from (S-543, Jazz 10-12: "we have many strategies; people should be able to combine them and
 * see the portfolio's risk and return sources").
 *
 * Data: GET /api/v1/portfolio/books?mode=…  and  GET /api/v1/portfolio/combine?books=a:0.6,b:0.4&mode=…
 * Two bases, never mixed: "forward" = each book's own paper record; "replay" = point-in-time replay (after the fact).
 */
import { useState, useEffect } from "react";
import { T, FONTS as F } from "../tokens";

const SOURCE_LABEL = {
  beta: "① Beta — hold the panel",
  beta_plus: "② Beta+ — tilts inside the panel",
  multiplier: "③ Multiplier — exposure timing",
  beta_and_multiplier: "①+③ Hold + timing",
  alpha: "④ Alpha — long/short",
  portfolio_layer: "Portfolio layer — 0–1 exposure",
  event: "Event-driven",
  other: "Other",
};
const SOURCE_TAG = { beta: "①", beta_plus: "②", multiplier: "③", beta_and_multiplier: "①+③", alpha: "④",
  portfolio_layer: "PL", event: "EV", other: "—" };
const pct = (v, d = 1) => (v == null || isNaN(v)) ? "—" : `${v >= 0 ? "+" : ""}${(v * 100).toFixed(d)}%`;
const num = (v, d = 2) => (v == null || isNaN(v)) ? "—" : v.toFixed(d);
const tone = (v) => v == null ? T.t3 : v > 0 ? T.green : v < 0 ? T.red : T.t3;

const card = { background: "rgba(5,7,22,0.85)", border: `1px solid ${T.border}`, borderRadius: 10, padding: 18 };
const label = { fontFamily: F.display, fontSize: 10, fontWeight: 700, color: T.t3, letterSpacing: "0.08em" };

function NavLine({ nav }) {
  if (!nav || nav.length < 2) return null;
  const W = 640, H = 120;
  const ys = nav.map(p => p.nav);
  const lo = Math.min(...ys), hi = Math.max(...ys);
  const pts = nav.map((p, i) => {
    const x = (i / (nav.length - 1)) * W;
    const y = H - ((p.nav - lo) / ((hi - lo) || 1)) * H;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: 120 }} preserveAspectRatio="none">
      <polyline points={pts} fill="none" stroke={T.cyan} strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

export default function PortfolioBuilder() {
  const [mode, setMode] = useState("forward");
  const [books, setBooks] = useState({ mode: null, list: [], error: null });
  const [weights, setWeights] = useState({});
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let alive = true;
    fetch(`/api/v1/portfolio/books?mode=${mode}`)
      .then(r => r.ok ? r.json() : Promise.reject(r.status))
      .then(d => { if (alive) setBooks({ mode, list: d.books || [], error: null }); })
      .catch(() => { if (alive) setBooks({ mode, list: [], error: "Book records could not be read — this is a read failure, not an absence of records." }); });
    return () => { alive = false; };
  }, [mode]);

  const available = (books.list || []).filter(b => b.available);
  const total = Object.values(weights).reduce((a, b) => a + (Number(b) || 0), 0);

  const run = () => {
    const spec = Object.entries(weights).filter(([, w]) => Number(w) > 0).map(([k, w]) => `${k}:${Number(w) / 100}`).join(",");
    if (!spec) return;
    setBusy(true);
    fetch(`/api/v1/portfolio/combine?mode=${mode}&books=${encodeURIComponent(spec)}`)
      .then(r => r.json().then(j => ({ ok: r.ok, j })))
      .then(({ ok, j }) => setResult(ok ? j : { ok: false, reason: typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail) }))
      .catch(() => setResult({ ok: false, reason: "The combination could not be computed right now." }))
      .finally(() => setBusy(false));
  };

  const switchMode = (m) => { setMode(m); setWeights({}); setResult(null); };

  return (
    <div style={{ ...card, marginTop: 28 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", flexWrap: "wrap", gap: 10 }}>
        <span style={{ fontFamily: F.display, fontSize: 16, fontWeight: 800, color: T.t1 }}>Build a combination</span>
        <div style={{ display: "flex", gap: 6 }}>
          {[["forward", "Paper records"], ["replay", "Point-in-time replay"]].map(([k, l]) => (
            <button key={k} onClick={() => switchMode(k)} style={{
              fontFamily: F.mono, fontSize: 9, padding: "4px 10px", borderRadius: 4, cursor: "pointer",
              background: "transparent", color: mode === k ? T.t1 : T.t3,
              border: `1px solid ${mode === k ? T.t3 : T.border}`,
            }}>{l}</button>
          ))}
        </div>
      </div>
      <p style={{ fontFamily: F.body, fontSize: 12, color: T.t2, margin: "8px 0 14px", lineHeight: 1.6 }}>
        Pick strategies and weights (the rest is cash). The result shows the combination's return, risk, and where
        the return came from — holding the panel, tilts, exposure timing, long/short — and how much each strategy adds to risk.
        {mode === "replay" ? " Replay = computed after the fact with point-in-time data; only some strategies have one." : " Paper records are short for most strategies; under 20 shared days figures are described, not annualised."}
      </p>

      {books.error && <div style={{ fontFamily: F.body, fontSize: 12, color: T.red }}>{books.error}</div>}

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))", gap: 8 }}>
        {(books.list || []).map(b => (
          <div key={b.id} style={{ display: "flex", alignItems: "center", gap: 8, padding: "6px 8px",
            border: `1px solid ${T.border}`, borderRadius: 6, opacity: b.available ? 1 : 0.45 }}
            title={b.available ? (b.thesis || "") : (b.note || "")}>
            <input type="number" min="0" max="100" step="5" disabled={!b.available}
              value={weights[b.id] ?? ""} placeholder="0"
              onChange={e => setWeights(w => ({ ...w, [b.id]: e.target.value }))}
              style={{ width: 52, background: "transparent", color: T.t1, border: `1px solid ${T.border}`,
                borderRadius: 4, fontFamily: F.mono, fontSize: 11, padding: "2px 4px" }} />
            <span style={{ fontFamily: F.mono, fontSize: 10, color: T.t3, width: 26 }}>{SOURCE_TAG[b.source] || "—"}</span>
            <span style={{ fontFamily: F.body, fontSize: 11, color: T.t2, flex: 1 }}>{b.name}</span>
          </div>
        ))}
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: 12, marginTop: 12 }}>
        <button onClick={run} disabled={busy || total <= 0 || total > 100 || !available.length} style={{
          fontFamily: F.display, fontSize: 11, fontWeight: 700, padding: "6px 14px", borderRadius: 5, cursor: "pointer",
          background: `${T.cyan}18`, color: T.cyan, border: `1px solid ${T.cyan}40`,
        }}>{busy ? "Computing…" : "Compute"}</button>
        <span style={{ fontFamily: F.mono, fontSize: 10, color: total > 100 ? T.red : T.t3 }}>
          Total {total.toFixed(0)}% · cash {Math.max(0, 100 - total).toFixed(0)}%
        </span>
      </div>

      {result && !result.ok && (
        <div style={{ fontFamily: F.body, fontSize: 12, color: T.amber, marginTop: 12 }}>{result.reason}</div>
      )}

      {result && result.ok && (
        <div style={{ marginTop: 16 }}>
          <div style={{ fontFamily: F.mono, fontSize: 10, color: T.t3 }}>
            {result.window?.[0]} → {result.window?.[1]} · {result.days} shared days
            {!result.estimable && " · too short to annualise"}
          </div>
          <div style={{ display: "flex", gap: 24, flexWrap: "wrap", marginTop: 10 }}>
            {[["Total return", pct(result.portfolio.total_return)], ["Annualised", pct(result.portfolio.ann_return)],
              ["Volatility (ann.)", pct(result.portfolio.ann_vol).replace("+", "")], ["Sharpe", num(result.portfolio.sharpe)],
              ["Max drawdown", pct(result.portfolio.max_drawdown)], ["Worst day", pct(result.portfolio.worst_day)]].map(([k, v]) => (
              <div key={k}>
                <div style={label}>{k.toUpperCase()}</div>
                <div style={{ fontFamily: F.mono, fontSize: 15, color: T.t1, marginTop: 3 }}>{v}</div>
              </div>
            ))}
          </div>

          <NavLine nav={result.nav} />

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 18, marginTop: 10 }} className="pb-grid">
            <div>
              <div style={{ ...label, marginBottom: 8 }}>WHERE THE RETURN CAME FROM</div>
              {Object.entries(result.return_sources_by_layer || {}).map(([k, v]) => (
                <div key={k} style={{ display: "flex", justifyContent: "space-between", fontFamily: F.mono, fontSize: 11, padding: "3px 0" }}>
                  <span style={{ color: T.t2 }}>{SOURCE_LABEL[k] || k}</span>
                  <span style={{ color: tone(v) }}>{pct(v, 2)}</span>
                </div>
              ))}
              {result.vs_core && (
                <div style={{ fontFamily: F.mono, fontSize: 10, color: T.t3, marginTop: 10, lineHeight: 1.6 }}>
                  Against holding the core: β {num(result.vs_core.beta)} × core {pct(result.vs_core.core_return)} = {pct(result.vs_core.beta_part, 2)} from beta;
                  residual {pct(result.vs_core.residual_part, 2)}{result.vs_core.alpha_ann != null ? ` (≈ ${pct(result.vs_core.alpha_ann)} a year)` : ""} · R² {num(result.vs_core.r2)}
                </div>
              )}
            </div>
            <div>
              <div style={{ ...label, marginBottom: 8 }}>EACH STRATEGY</div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 60px 70px 70px", gap: 4, fontFamily: F.mono, fontSize: 9, color: T.t4 }}>
                <span>STRATEGY</span><span style={{ textAlign: "right" }}>WEIGHT</span>
                <span style={{ textAlign: "right" }}>ADDS RETURN</span><span style={{ textAlign: "right" }}>SHARE OF RISK</span>
              </div>
              {(result.books || []).map(b => (
                <div key={b.book} style={{ display: "grid", gridTemplateColumns: "1fr 60px 70px 70px", gap: 4, fontFamily: F.mono, fontSize: 11, padding: "3px 0" }}>
                  <span style={{ color: T.t2 }}>{result.selected?.[b.book]?.name || b.book}</span>
                  <span style={{ textAlign: "right", color: T.t3 }}>{(b.weight * 100).toFixed(0)}%</span>
                  <span style={{ textAlign: "right", color: tone(b.return_contribution) }}>{pct(b.return_contribution, 2)}</span>
                  <span style={{ textAlign: "right", color: T.t2 }}>{b.risk_contribution == null ? "—" : `${(b.risk_contribution * 100).toFixed(0)}%`}</span>
                </div>
              ))}
            </div>
          </div>

          <div style={{ fontFamily: F.body, fontSize: 10, color: T.t4, marginTop: 14, lineHeight: 1.5 }}>{result.reading}</div>
        </div>
      )}
      <style>{`@media (max-width: 800px) { .pb-grid { grid-template-columns: 1fr !important; } }`}</style>
    </div>
  );
}
