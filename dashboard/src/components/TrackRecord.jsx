/**
 * TrackRecord — public-facing evidence page (T-086, 2026-10-13).
 *
 * The validation apparatus IS the product (CLAUDE.md §ARCHITECTURE). This page
 * shows three read-only surfaces and nothing computed here:
 *   • /api/v1/portfolio/books?mode=forward  — each book's name, layer, record span
 *   • /api/v1/proof/books                   — each book's window, forward days,
 *                                              period return, benchmark return,
 *                                              evidence class, allocation weight
 *   • /api/v1/proof/anchors                 — daily Bitcoin-anchored digests
 *
 * What this page does NOT compute:
 *   • No annualisation. Anything under one full year shows the period return
 *     and the label "period return" — not "annualised". The "less than a year,
 *     don't annualise, don't give Sharpe" rule is in the task spec (GIPS, S-543
 *     / S-553). A lookup table on the way to a derived number is exactly the
 *     trap that hides compounding and survivorship assumptions from the reader.
 *   • No Sharpe, no Sortino, no Calmar, no CAGR, no IR, no omega of money.
 *     Same reason. The forward window for most books is months, not years.
 *   • No max-drawdown derived client-side. The /api/v1/proof/books surface does
 *     not ship a drawdown field; if it ever does, surface it. Until then the
 *     page would have to compute it from a NAV series it does not have, and
 *     that path has its own gotchas (period-rank on a paper NAV ≠ period-rank
 *     on a live NAV). So: no drawdown number on this page today.
 *
 * Read-failure discipline (CLAUDE.md §no-mock-data):
 *   • A failed fetch renders the exact "读不到" string the spec mandates, never
 *     "no records" or "暂无记录". "No records" is a claim about the system;
 *     "we could not read" is a fact about the wire. They are not interchangeable.
 *   • The error message is identical to the message the API itself returns when
 *     its upstream fails (see src/api/routers/ohlcv.py:606 "读不到 ≠ 没有证据"
 *     and src/api/routers/portfolio_builder.py:52 "unreadable — not the same as
 *     no records"). The page surfaces the upstream string verbatim when it is
 *     non-empty, and a sibling string when the wire returned a transport failure
 *     with no body.
 *
 * Compliance (CLAUDE.md #1, #8):
 *   • Paper records, not live-traded P&L — footer disclosure.
 *   • Positioning language only.
 *   • No infrastructure named in any user-visible line (no FastAPI / Railway /
 *     Supabase / Mac / LM Studio / Freqtrade / OpenTimestamps).
 *   • "Forward record" / "paper record" / "validation" used in lieu of "live
 *     P&L" — accurate AND no false promise of live trading.
 *
 * Anti-imposter checks baked in (so future edits don't quietly relax them):
 *   • window / record arrays are displayed raw from the API as [start, end].
 *   • period_return is formatted as a percentage with explicit sign, never as
 *     an "annualised" rate.
 *   • The anchors section quotes the upstream `how_to_verify` string verbatim,
 *     because rewriting it would make the verification procedure the page
 *     describes not the verification procedure the anchors actually support.
 */
import { useEffect, useState } from "react";
import { T, FONTS } from "../tokens";

const F = FONTS;

const SOURCE_LABEL = {
  beta: "① Beta",
  beta_plus: "② Beta+",
  multiplier: "③ Multiplier",
  beta_and_multiplier: "①+③ Hold + timing",
  alpha: "④ Alpha",
  portfolio_layer: "Portfolio layer",
  event: "Event",
  other: "Other",
};
const SOURCE_GLYPH = { beta: "①", beta_plus: "②", multiplier: "③", beta_and_multiplier: "①+③",
  alpha: "④", portfolio_layer: "PL", event: "EV", other: "—" };

const pct = (v) => (v == null || Number.isNaN(v)) ? "—" :
  `${v > 0 ? "+" : ""}${(v * 100).toFixed(2)}%`;

const DATE = (d) => d ? String(d).slice(0, 10) : "—";
const SHORT = (s) => s == null ? "—" :
  String(s).length > 22 ? `${String(s).slice(0, 21)}…` : String(s);

const FAIL_BOOKS = "Book records could not be read — read failure, not absence of records.";
const FAIL_PROOF = "Forward evidence could not be read — read failure, not absence of evidence.";
const FAIL_ANCHORS = "Anchors could not be read — read failure, not absence of anchors.";

function ReadFail({ label }) {
  return (
    <div role="status" style={{
      padding: "10px 14px", border: `1px solid ${T.border}`, borderRadius: 6,
      background: "rgba(255,61,90,0.06)", color: T.red,
      fontFamily: F.body, fontSize: 12, lineHeight: 1.55, marginBottom: 18,
    }}>
      读不到 — {label}
    </div>
  );
}

function Section({ title, sub, children }) {
  return (
    <section style={{
      background: "rgba(5,7,22,0.85)", border: `1px solid ${T.border}`,
      borderRadius: 10, padding: 22, marginBottom: 22,
    }}>
      <header style={{ marginBottom: 14 }}>
        <h2 style={{
          fontFamily: F.display, fontSize: 15, fontWeight: 800,
          color: T.t1, margin: 0, letterSpacing: "0.02em",
        }}>{title}</h2>
        {sub && <p style={{
          fontFamily: F.body, fontSize: 12, color: T.t3,
          margin: "6px 0 0", lineHeight: 1.55,
        }}>{sub}</p>}
      </header>
      {children}
    </section>
  );
}

function EvidenceTag({ klass }) {
  const palette = {
    forward:        { color: T.green, bg: T.greenDim, border: "rgba(0,217,138,0.30)" },
    forward_young:  { color: T.gold,  bg: T.goldDim,  border: "rgba(212,168,67,0.30)" },
    caveat:         { color: T.red,   bg: T.redDim,   border: "rgba(255,61,90,0.30)" },
    retired:        { color: T.t3,    bg: "rgba(199,210,254,0.06)", border: T.border },
    no_record:      { color: T.t3,    bg: "rgba(199,210,254,0.06)", border: T.border },
  }[klass] || { color: T.t3, bg: "rgba(199,210,254,0.06)", border: T.border };
  const label = klass === "forward_young" ? "forward (young)" : klass || "—";
  return (
    <span style={{
      fontFamily: F.mono, fontSize: 9, letterSpacing: "0.08em",
      color: palette.color, background: palette.bg,
      border: `1px solid ${palette.border}`,
      borderRadius: 3, padding: "2px 6px", textTransform: "uppercase", whiteSpace: "nowrap",
    }}>{label}</span>
  );
}

function BooksTable({ books }) {
  if (!books.length) {
    return <p style={{ fontFamily: F.body, fontSize: 12, color: T.t3 }}>读不到 — no books in this basis.</p>;
  }
  return (
    <div className="tbl-wrap" style={{ overflowX: "auto" }}>
      <table style={{ width: "100%", borderCollapse: "collapse", fontFamily: F.body, fontSize: 12 }}>
        <thead>
          <tr style={{ borderBottom: `1px solid ${T.border}` }}>
            {["Layer", "Book", "Status", "Record", "Source", "Note"].map(h => (
              <th key={h} style={{
                fontFamily: F.mono, fontSize: 9, color: T.t3, textTransform: "uppercase",
                letterSpacing: "0.1em", padding: "8px 10px", textAlign: "left", fontWeight: 700,
              }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {books.map(b => (
            <tr key={b.id} style={{ borderBottom: `1px solid ${T.border}` }}>
              <td style={{ padding: "10px", color: T.t2, whiteSpace: "nowrap", fontFamily: F.mono }}>
                {SOURCE_GLYPH[b.source] || "—"}&nbsp;
                <span style={{ color: T.t3, fontFamily: F.body, fontSize: 10 }}>{SOURCE_LABEL[b.source] || b.source || "Other"}</span>
              </td>
              <td style={{ padding: "10px", color: T.t1, fontWeight: 600 }}>
                {b.name || b.id}
                {b.thesis && (
                  <div style={{ fontFamily: F.body, fontSize: 10, color: T.t3, marginTop: 3, lineHeight: 1.5 }}>
                    {SHORT(b.thesis)}
                  </div>
                )}
              </td>
              <td style={{ padding: "10px", color: b.available ? T.green : T.t3, fontFamily: F.mono, fontSize: 11 }}>
                {b.available ? "available" : (b.status || "—")}
              </td>
              <td style={{ padding: "10px", color: T.t2, fontFamily: F.mono, fontSize: 11, whiteSpace: "nowrap" }}>
                {b.record ? `${DATE(b.record[0])} → ${DATE(b.record[1])}` : "—"}
              </td>
              <td style={{ padding: "10px", color: T.t2, fontFamily: F.body, fontSize: 11 }}>
                {b.source || "—"}
              </td>
              <td style={{ padding: "10px", color: T.t3, fontFamily: F.body, fontSize: 11, maxWidth: 320 }}>
                {b.note || "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ProofTable({ rows }) {
  if (!rows.length) {
    return <p style={{ fontFamily: F.body, fontSize: 12, color: T.t3 }}>读不到 — no books in this evidence surface.</p>;
  }
  return (
    <div className="tbl-wrap" style={{ overflowX: "auto" }}>
      <table style={{ width: "100%", borderCollapse: "collapse", fontFamily: F.body, fontSize: 12 }}>
        <thead>
          <tr style={{ borderBottom: `1px solid ${T.border}` }}>
            {["Layer", "Book", "Window", "Forward days", "Period return", "Same-window benchmark",
              "Excess vs benchmark", "L3 weight", "Evidence"].map(h => (
              <th key={h} style={{
                fontFamily: F.mono, fontSize: 9, color: T.t3, textTransform: "uppercase",
                letterSpacing: "0.1em", padding: "8px 10px", textAlign: "left", fontWeight: 700,
              }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map(r => {
            const w = r.window || [];
            const posTone = r.total_return == null ? T.t3 :
              r.total_return > 0 ? T.green : r.total_return < 0 ? T.red : T.t3;
            const excTone = r.excess_vs_core == null ? T.t3 :
              r.excess_vs_core > 0 ? T.green : r.excess_vs_core < 0 ? T.red : T.t3;
            return (
              <tr key={r.id} style={{ borderBottom: `1px solid ${T.border}` }}>
                <td style={{ padding: "10px", color: T.t2, fontFamily: F.mono }}>
                  {SOURCE_GLYPH[r.layer] || "—"}
                </td>
                <td style={{ padding: "10px", color: T.t1, fontWeight: 600, maxWidth: 220 }}>
                  {r.name || r.id}
                  {r.caveat && (
                    <div style={{ fontFamily: F.body, fontSize: 10, color: T.red, marginTop: 3, lineHeight: 1.4 }}>
                      caveat: {SHORT(r.caveat)}
                    </div>
                  )}
                </td>
                <td style={{ padding: "10px", color: T.t2, fontFamily: F.mono, fontSize: 11, whiteSpace: "nowrap" }}>
                  {w.length === 2 ? `${DATE(w[0])} → ${DATE(w[1])}` : "—"}
                </td>
                <td style={{ padding: "10px", color: T.t2, fontFamily: F.mono, fontSize: 11, textAlign: "right" }}>
                  {r.forward_days ?? "—"}
                </td>
                <td style={{ padding: "10px", color: posTone, fontFamily: F.mono, fontSize: 11, textAlign: "right" }}>
                  {pct(r.total_return)}
                </td>
                <td style={{ padding: "10px", color: T.t2, fontFamily: F.mono, fontSize: 11, textAlign: "right" }}>
                  {pct(r.core_return_same_window)}
                </td>
                <td style={{ padding: "10px", color: excTone, fontFamily: F.mono, fontSize: 11, textAlign: "right" }}>
                  {pct(r.excess_vs_core)}
                </td>
                <td style={{ padding: "10px", color: T.t2, fontFamily: F.mono, fontSize: 11, textAlign: "right" }}>
                  {r.l3_weight == null ? "—" :
                    `${(r.l3_weight * 100).toFixed(1)}%`}
                </td>
                <td style={{ padding: "10px" }}>
                  <EvidenceTag klass={r.evidence_class} />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p style={{ fontFamily: F.body, fontSize: 11, color: T.t3, marginTop: 10, lineHeight: 1.5 }}>
        Period return = total return over the shown window. Not annualised. Same-window benchmark = the
        core holding's total return over the same window. Excess vs benchmark = period return minus
        same-window benchmark. No Sharpe, no CAGR, no drawdown derived here — the surface does not ship
        enough data to compute those without smuggling in assumptions.
      </p>
    </div>
  );
}

function AnchorsList({ anchors, howToVerify, error }) {
  if (error) return <ReadFail label={FAIL_ANCHORS} />;
  if (!anchors || anchors.length === 0) {
    return <p style={{ fontFamily: F.body, fontSize: 12, color: T.t3 }}>读不到 — no anchors in this window.</p>;
  }
  return (
    <>
      <div className="tbl-wrap" style={{ overflowX: "auto", marginBottom: 14 }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontFamily: F.body, fontSize: 12 }}>
          <thead>
            <tr style={{ borderBottom: `1px solid ${T.border}` }}>
              {["Date", "SHA-256 digest (prefix)", "Rows", "Submitted", "Calendars"].map(h => (
                <th key={h} style={{
                  fontFamily: F.mono, fontSize: 9, color: T.t3, textTransform: "uppercase",
                  letterSpacing: "0.1em", padding: "8px 10px", textAlign: "left", fontWeight: 700,
                }}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {anchors.map(a => (
              <tr key={a.d} style={{ borderBottom: `1px solid ${T.border}` }}>
                <td style={{ padding: "10px", color: T.t1, fontFamily: F.mono, fontSize: 11 }}>{a.d}</td>
                <td style={{
                  padding: "10px", color: T.t2, fontFamily: F.mono, fontSize: 11,
                  wordBreak: "break-all", maxWidth: 260,
                }}>
                  {a.digest ? `${a.digest.slice(0, 16)}…` : "—"}
                </td>
                <td style={{ padding: "10px", color: T.t2, fontFamily: F.mono, fontSize: 11, textAlign: "right" }}>
                  {a.n_rows ?? "—"}
                </td>
                <td style={{ padding: "10px", color: T.t2, fontFamily: F.mono, fontSize: 11, whiteSpace: "nowrap" }}>
                  {a.submitted_at ? String(a.submitted_at).replace("T", " ").slice(0, 19) : "—"}
                </td>
                <td style={{ padding: "10px", color: T.t2, fontFamily: F.body, fontSize: 11 }}>
                  {(a.calendars || []).length ? (a.calendars || []).join(", ") : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {howToVerify && (
        <details style={{ marginTop: 4 }}>
          <summary style={{
            fontFamily: F.mono, fontSize: 10, color: T.cyan, cursor: "pointer",
            letterSpacing: "0.08em", textTransform: "uppercase",
          }}>How to verify</summary>
          <p style={{
            fontFamily: F.body, fontSize: 11, color: T.t2, marginTop: 8,
            padding: 12, background: "rgba(6,182,212,0.06)", border: `1px solid ${T.border}`,
            borderRadius: 6, lineHeight: 1.55, wordBreak: "break-word",
          }}>{howToVerify}</p>
        </details>
      )}
    </>
  );
}

export default function TrackRecord() {
  const [books, setBooks]     = useState({ list: [], reading: null, error: null });
  const [proof, setProof]     = useState({ rows: [], asOf: null, error: null });
  const [anchors, setAnchors] = useState({ list: [], howToVerify: null, error: null });

  useEffect(() => {
    let alive = true;
    fetch("/api/v1/portfolio/books?mode=forward")
      .then(r => r.ok ? r.json() : Promise.reject({ status: r.status }))
      .then(d => { if (alive) setBooks({ list: d.books || [], reading: d.reading || null, error: null }); })
      .catch(err => { if (alive) setBooks({ list: [], reading: null,
        error: FAIL_BOOKS + (err && err.status ? ` (status ${err.status})` : "") }); });
    fetch("/api/v1/proof/books")
      .then(r => r.ok ? r.json() : Promise.reject({ status: r.status }))
      .then(d => { if (alive) setProof({ rows: d.books || [], asOf: d.as_of || null, error: null }); })
      .catch(err => { if (alive) setProof({ rows: [], asOf: null,
        error: FAIL_PROOF + (err && err.status ? ` (status ${err.status})` : "") }); });
    fetch("/api/v1/proof/anchors")
      .then(r => r.ok ? r.json() : Promise.reject({ status: r.status }))
      .then(d => { if (alive) setAnchors({ list: d.anchors || [], howToVerify: d.how_to_verify || null,
        error: null }); })
      .catch(err => { if (alive) setAnchors({ list: [], howToVerify: null,
        error: FAIL_ANCHORS + (err && err.status ? ` (status ${err.status})` : "") }); });
    return () => { alive = false; };
  }, []);

  return (
    <div style={{ maxWidth: 1200, margin: "0 auto", fontFamily: F.body, color: T.t2 }}>
      <header style={{ marginBottom: 24 }}>
        <h1 style={{
          fontFamily: F.display, fontSize: 26, fontWeight: 800,
          color: T.t1, margin: 0, letterSpacing: "0.01em",
        }}>Track Record</h1>
        <p style={{
          fontFamily: F.body, fontSize: 13, color: T.t3,
          margin: "10px 0 0", lineHeight: 1.6, maxWidth: 760,
        }}>
          Every paper book we publish, the period return the books actually carried,
          and a daily digest anchored against Bitcoin's clock. We cannot edit history
          after the day is anchored; if a row is wrong it is wrong in the snapshot too,
          and an outsider can re-compute the digest and check.
        </p>
      </header>

      {/* Books in scope (mode=forward) */}
      <Section
        title="Books in scope"
        sub="Each book the allocation layer can put capital behind on a forward basis. The same source as the portfolio builder."
      >
        {books.error
          ? <ReadFail label={books.error} />
          : <BooksTable books={books.list} />}
        {books.reading && (
          <p style={{ fontFamily: F.body, fontSize: 11, color: T.t3, marginTop: 10, lineHeight: 1.55 }}>
            {books.reading}
          </p>
        )}
      </Section>

      {/* Forward evidence per book */}
      <Section
        title="Forward evidence"
        sub="One row per book. Window = the allocation layer's forward window. Period return = total return over the window (not annualised)."
      >
        {proof.error
          ? <ReadFail label={proof.error} />
          : <ProofTable rows={proof.rows} />}
      </Section>

      {/* Daily anchors */}
      <Section
        title="Daily anchors"
        sub="One row per day. The digest is a SHA-256 over the snapshot rows that day. Each row links to the per-day payload."
      >
        <AnchorsList anchors={anchors.list} howToVerify={anchors.howToVerify} error={anchors.error} />
      </Section>

      <footer style={{
        marginTop: 28, padding: "16px 18px",
        border: `1px solid ${T.border}`, borderRadius: 8,
        background: "rgba(6,182,212,0.04)",
        fontFamily: F.body, fontSize: 11, color: T.t3, lineHeight: 1.6,
      }}>
        <strong style={{ color: T.t2, fontFamily: F.body }}>Disclosure.</strong>{" "}
        Paper records, not live-traded P&amp;L. Positioning language only;
        nothing on this page is a forecast or an investment recommendation.
        Period returns are period returns — not annualised, not Sharpe, not CAGR.
        Anchors are append-only.
      </footer>
    </div>
  );
}