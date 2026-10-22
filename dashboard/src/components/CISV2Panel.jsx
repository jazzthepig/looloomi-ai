// CISV2Panel.jsx — CIS v2 (shadow) on the CIS page: slow-dimension score for tokens, facts + state for companies.
//
// S-668 / S-669, Jazz 10-22:
//   - the score keeps only slow, hard-to-fake dimensions (size, stability, supply discipline; F / O for tokens);
//   - momentum, sentiment and crowding are STATE — a description of now, never a forecast;
//   - companies are shown with facts and state only, with NO signal level (their composite ran opposite to
//     later returns, so a band word would mislead);
//   - the official CIS stays v1 until the crypto group finishes its 20-day shadow.
// One fetch: GET /api/v1/cis/v2. The basis sentence comes from the API (contracts/disclosure.py), not from here.

import { useEffect, useMemo, useState } from "react";
import { T, FONTS, sigStyle } from "../tokens";
import { CompactSectionLabel } from "./SectionLabels";

const TREND = {
  up:    { text: "Uptrend",   color: T.green },
  down:  { text: "Downtrend", color: T.red },
  range: { text: "Range",     color: T.t3 },
};
const MOOD = {
  greed: "Greed", fear: "Fear", neutral: "Neutral", stress: "Stress", calm: "Calm", normal: "Normal",
};

const pct = (x, digits = 1) => (x === null || x === undefined ? "—" : `${x >= 0 ? "+" : ""}${(x * 100).toFixed(digits)}%`);
const usd = (x) => {
  if (!x) return "—";
  if (x >= 1e12) return `$${(x / 1e12).toFixed(2)}T`;
  if (x >= 1e9) return `$${(x / 1e9).toFixed(0)}B`;
  return `$${(x / 1e6).toFixed(0)}M`;
};

function TrendCell({ state }) {
  const tr = state?.trend;
  if (!tr || !tr.label) return <span style={{ color: T.t4 }}>—</span>;
  const s = TREND[tr.label] || TREND.range;
  return (
    <span style={{ color: s.color, fontFamily: FONTS.body, fontSize: 12 }}>
      {s.text}
      {tr.basis === "short_history" && <span style={{ color: T.t3, fontSize: 10 }}> · short history</span>}
    </span>
  );
}

const th = { textAlign: "left", padding: "8px 10px", fontFamily: FONTS.display, fontSize: 10, letterSpacing: "0.08em",
             color: T.t3, fontWeight: 600, borderBottom: `1px solid ${T.border}`, whiteSpace: "nowrap" };
const td = { padding: "8px 10px", fontFamily: FONTS.mono, fontSize: 12, color: T.t1, borderBottom: `1px solid ${T.border}`,
             whiteSpace: "nowrap" };

function CryptoTable({ rows }) {
  return (
    <table style={{ width: "100%", borderCollapse: "collapse" }}>
      <thead>
        <tr>
          <th style={th}>ASSET</th><th style={th}>V2 SCORE</th><th style={th}>LEVEL (SHADOW)</th>
          <th style={th}>TREND</th><th style={th}>30D</th><th style={th}>FUNDING 7D (APR)</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => {
          const sg = r.signal ? sigStyle(r.signal) : null;
          return (
            <tr key={r.symbol}>
              <td style={{ ...td, fontFamily: FONTS.display, fontWeight: 700 }}>{r.symbol}</td>
              <td style={td}>{r.score === null || r.score === undefined ? "—" : r.score.toFixed(1)}</td>
              <td style={td}>
                {sg ? (
                  <span style={{ color: sg.color, background: sg.bg, border: `1px solid ${sg.border}`, borderRadius: 4,
                                 padding: "2px 6px", fontSize: 10, fontFamily: FONTS.display, letterSpacing: "0.04em" }}>
                    {r.signal}{r.watch ? " · watch" : ""}
                  </span>
                ) : <span style={{ color: T.t4 }}>—</span>}
              </td>
              <td style={td}><TrendCell state={r.state} /></td>
              <td style={td}>{pct(r.state?.momentum_30d)}</td>
              <td style={td}>{pct(r.state?.funding_7d?.apr)}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function CompanyTable({ rows }) {
  return (
    <table style={{ width: "100%", borderCollapse: "collapse" }}>
      <thead>
        <tr>
          <th style={th}>COMPANY</th><th style={th}>MARKET CAP</th><th style={th}>VOLATILITY (26W, WEEKLY)</th>
          <th style={th}>SHARE COUNT 52W</th><th style={th}>TREND</th><th style={th}>30D</th>
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.symbol}>
            <td style={{ ...td, fontFamily: FONTS.display, fontWeight: 700 }}>{r.symbol}</td>
            <td style={td}>{usd(r.facts?.market_cap_usd)}</td>
            <td style={td}>{r.facts?.volatility_26w_weekly == null ? "—" : `${(r.facts.volatility_26w_weekly * 100).toFixed(1)}%`}</td>
            <td style={{ ...td, color: r.facts?.share_count_change_52w > 0.02 ? T.amber : T.t1 }}>
              {pct(r.facts?.share_count_change_52w)}
            </td>
            <td style={td}><TrendCell state={r.state} /></td>
            <td style={td}>{pct(r.state?.momentum_30d)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function CISV2Panel() {
  const [data, setData] = useState(null);
  const [failed, setFailed] = useState(false);
  const [tab, setTab] = useState("crypto");

  useEffect(() => {
    const ctrl = new AbortController();
    fetch("/api/v1/cis/v2", { signal: ctrl.signal })
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then(setData)
      .catch((e) => { if (e?.name !== "AbortError") setFailed(true); });
    return () => ctrl.abort();
  }, []);

  const mood = useMemo(() => {
    const c = data?.crypto?.find((r) => r.state?.market)?.state?.market;
    const e = data?.companies?.find((r) => r.state?.market)?.state?.market;
    return { c, e };
  }, [data]);

  if (failed) return null;
  if (!data) {
    return <div className="lm-card" style={{ marginTop: 32, padding: 24, color: T.t3, fontFamily: FONTS.body }}>Loading CIS v2…</div>;
  }
  const sh = data.shadow || {};
  const rows = tab === "crypto" ? data.crypto || [] : data.companies || [];

  return (
    <div style={{ marginTop: 40 }}>
      <CompactSectionLabel
        label="CIS v2 · Shadow"
        meta={`${data.d || "—"} · crypto shadow day ${sh.crypto_consecutive_days ?? 0} of ${sh.switch_after_days ?? 20} · official CIS is still v1`}
        accent="gold"
      />
      <p style={{ color: T.t3, fontFamily: FONTS.body, fontSize: 12, lineHeight: 1.6, margin: "0 0 14px", maxWidth: 980 }}>
        {data.basis}
      </p>
      <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 12, flexWrap: "wrap" }}>
        {[["crypto", `Tokens (${(data.crypto || []).length})`], ["companies", `Companies (${(data.companies || []).length})`]].map(([k, label]) => (
          <button key={k} onClick={() => setTab(k)} style={{
            padding: "6px 14px", borderRadius: 6, fontSize: 11, fontFamily: FONTS.display, letterSpacing: "0.04em",
            cursor: "pointer", background: tab === k ? T.cyanDim : "transparent",
            border: `1px solid ${tab === k ? "rgba(6,182,212,0.4)" : T.border}`, color: tab === k ? T.cyan : T.t3,
          }}>{label}</button>
        ))}
        <span style={{ marginLeft: "auto", color: T.t3, fontFamily: FONTS.body, fontSize: 11 }}>
          {tab === "crypto" && mood.c?.label ? `Market mood: ${MOOD[mood.c.label]} (Fear & Greed ${mood.c.value})` : null}
          {tab === "companies" && mood.e?.label ? `Market mood: ${MOOD[mood.e.label]} (VIX ${mood.e.value})` : null}
        </span>
      </div>
      <div className="lm-card" style={{ overflowX: "auto" }}>
        {tab === "crypto" ? <CryptoTable rows={rows} /> : <CompanyTable rows={rows} />}
      </div>
      <p style={{ color: T.t3, fontFamily: FONTS.body, fontSize: 11, marginTop: 10 }}>
        Trend, 30-day change, funding and market mood describe the present; they are not forecasts.
        {tab === "companies" ? " Companies carry no signal level." : ""}
      </p>
    </div>
  );
}
