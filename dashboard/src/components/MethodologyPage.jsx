/**
 * MethodologyPage — CIS v4.1 public methodology specification.
 * Investor-facing. No internal implementation details.
 * Tone: institutional. Transparent. Precise.
 */

import { useState } from "react";
import SiteNav from "./SiteNav";
import { T, FONTS } from "../tokens";

/* ─── design tokens ─────────────────────────────────────────────────── */
const C = {
  bg:       "#030f2a",
  surface:  "rgba(5,7,22,0.88)",
  border:   "rgba(37,99,235,0.16)",
  borderHi: "rgba(99,102,241,0.30)",
  cyan:     "#06b6d4",
  indigo:   "#6366f1",
  gold:     "#d4a843",
  green:    "#00D98A",
  red:      "#FF3D5A",
  t1:       "#f0f4ff",
  t2:       "#c7d2fe",
  t3:       "rgba(199,210,254,0.45)",
  t4:       "rgba(199,210,254,0.20)",
};

const mono  = FONTS.mono;
const brand = FONTS.brand;
const body  = FONTS.body;
const disp  = FONTS.display;

/* ─── helpers ───────────────────────────────────────────────────────── */
const Section = ({ id, children, noBorder }) => (
  <section id={id} style={{
    borderTop: noBorder ? "none" : `1px solid ${C.border}`,
    paddingTop: noBorder ? 0 : 64,
    marginTop: noBorder ? 0 : 64,
  }}>
    {children}
  </section>
);

const SectionTitle = ({ num, title, sub }) => (
  <div style={{ marginBottom: 40 }}>
    <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 8 }}>
      <span style={{
        fontFamily: mono, fontSize: 11, color: C.indigo, fontWeight: 700,
        letterSpacing: "0.12em",
      }}>§{num}</span>
      <div style={{ flex: 1, height: 1, background: `linear-gradient(90deg, ${C.indigo}60, transparent)` }} />
    </div>
    <h2 style={{
      fontFamily: brand, fontSize: 28, fontWeight: 800,
      color: C.t1, margin: 0, letterSpacing: "-0.01em",
    }}>{title}</h2>
    {sub && <p style={{ fontFamily: body, fontSize: 15, color: C.t3, margin: "8px 0 0", lineHeight: 1.6 }}>{sub}</p>}
  </div>
);

const Card = ({ children, style }) => (
  <div style={{
    background: C.surface, border: `1px solid ${C.border}`,
    borderRadius: 10, padding: 24, ...style,
  }}>
    {children}
  </div>
);

const Pill = ({ label, color }) => (
  <span style={{
    fontFamily: mono, fontSize: 9, fontWeight: 700, letterSpacing: "0.10em",
    padding: "3px 8px", borderRadius: 4,
    color, background: `${color}18`, border: `1px solid ${color}40`,
  }}>{label}</span>
);

const Table = ({ headers, rows, colWidths }) => (
  <div style={{ overflowX: "auto", marginTop: 16 }}>
    <table style={{ width: "100%", borderCollapse: "collapse", fontFamily: body, fontSize: 13 }}>
      <thead>
        <tr>
          {headers.map((h, i) => (
            <th key={i} style={{
              padding: "8px 14px", textAlign: "left", fontFamily: disp,
              fontSize: 10, fontWeight: 700, letterSpacing: "0.1em",
              color: C.t3, borderBottom: `1px solid ${C.border}`,
              width: colWidths?.[i],
            }}>{h}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((row, ri) => (
          <tr key={ri} style={{
            borderBottom: `1px solid ${C.border}`,
            background: ri % 2 === 0 ? "transparent" : "rgba(255,255,255,0.015)",
          }}>
            {row.map((cell, ci) => (
              <td key={ci} style={{
                padding: "10px 14px", color: C.t2, lineHeight: 1.5,
                fontFamily: typeof cell === "string" && cell.startsWith("`") ? mono : body,
                fontSize: 12,
              }}>
                {typeof cell === "string"
                  ? cell.replace(/`([^`]+)`/g, (_, s) => `<code style="font-family:${mono};background:rgba(6,182,212,0.10);padding:1px 5px;border-radius:3px;color:${C.cyan};font-size:11px">${s}</code>`)
                      .split(/(<code[^>]*>.*?<\/code>)/s)
                      .map((part, pi) => {
                        if (part.startsWith("<code")) {
                          const m = part.match(/>([^<]+)</);
                          return <code key={pi} style={{ fontFamily: mono, background: "rgba(6,182,212,0.10)", padding: "1px 5px", borderRadius: 3, color: C.cyan, fontSize: 11 }}>{m?.[1]}</code>;
                        }
                        return part;
                      })
                  : cell}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  </div>
);

const Formula = ({ label, expr, note }) => (
  <div style={{
    background: "rgba(6,182,212,0.04)", border: `1px solid rgba(6,182,212,0.16)`,
    borderRadius: 6, padding: "12px 16px", marginBottom: 10,
  }}>
    {label && <div style={{ fontFamily: disp, fontSize: 10, color: C.t3, fontWeight: 700,
      letterSpacing: "0.08em", marginBottom: 6 }}>{label}</div>}
    <div style={{ fontFamily: mono, fontSize: 13, color: C.cyan, letterSpacing: "0.01em" }}>
      {expr}
    </div>
    {note && <div style={{ fontFamily: body, fontSize: 11, color: C.t4, marginTop: 6, lineHeight: 1.5 }}>{note}</div>}
  </div>
);

const PillarCard = ({ letter, name, color, weight, desc, components }) => (
  <Card style={{ borderLeft: `3px solid ${color}` }}>
    <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 14 }}>
      <div style={{
        width: 36, height: 36, borderRadius: "50%", display: "flex",
        alignItems: "center", justifyContent: "center", flexShrink: 0,
        background: `${color}18`, border: `1px solid ${color}40`,
        fontFamily: mono, fontSize: 16, fontWeight: 700, color,
      }}>{letter}</div>
      <div>
        <div style={{ fontFamily: brand, fontSize: 15, fontWeight: 700, color: C.t1 }}>{name}</div>
        <div style={{ fontFamily: body, fontSize: 12, color: C.t3, marginTop: 2 }}>{desc}</div>
      </div>
      <div style={{ marginLeft: "auto", textAlign: "right" }}>
        <div style={{ fontFamily: mono, fontSize: 10, color: C.t4, letterSpacing: "0.06em" }}>BASE WEIGHT</div>
        <div style={{ fontFamily: mono, fontSize: 18, fontWeight: 700, color }}>{weight}</div>
      </div>
    </div>
    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
      {components.map(([component, formula, range], i) => (
        <div key={i} style={{
          display: "grid", gridTemplateColumns: "160px 1fr 70px",
          gap: 10, alignItems: "start", padding: "8px 0",
          borderBottom: i < components.length - 1 ? `1px solid ${C.border}` : "none",
        }}>
          <div style={{ fontFamily: body, fontSize: 12, color: C.t2 }}>{component}</div>
          <div style={{ fontFamily: mono, fontSize: 11, color: C.t3, lineHeight: 1.5 }}>{formula}</div>
          <div style={{ fontFamily: mono, fontSize: 11, color, textAlign: "right" }}>{range}</div>
        </div>
      ))}
    </div>
  </Card>
);

/* ─── anchor nav ─────────────────────────────────────────────────────── */
const ANCHORS = [
  ["§1", "Purpose",          "#purpose"],
  ["§2", "Architecture",     "#architecture"],
  ["§3", "Pillars",          "#pillars"],
  ["§4", "Weights",          "#weights"],
  ["§5", "Grading",          "#grading"],
  ["§6", "LAS",              "#las"],
  ["§7", "Compliance",       "#compliance"],
  ["§8", "Data Integrity",   "#integrity"],
];

/* ─── page ───────────────────────────────────────────────────────────── */
export default function MethodologyPage() {
  const [activeAnchor, setActiveAnchor] = useState("#purpose");

  const scrollTo = (hash) => {
    const el = document.querySelector(hash);
    if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
    setActiveAnchor(hash);
  };

  return (
    <div style={{ background: C.bg, minHeight: "100vh", position: "relative" }}>
      {/* Ambient background */}
      <div className="bg" aria-hidden="true">
        <div className="bg-base" />
        <div className="bg-left" />
        <div className="bg-right" />
        <div className="bg-grain" />
      </div>

      <SiteNav activePage="methodology" />

      <div style={{ display: "flex", paddingTop: 56, position: "relative", zIndex: 1 }}>

        {/* ── Left anchor nav ── */}
        <aside style={{
          width: 200, flexShrink: 0, position: "sticky", top: 56,
          height: "calc(100vh - 56px)", padding: "40px 0 40px 32px",
          borderRight: `1px solid ${C.border}`, overflowY: "auto",
        }} className="method-sidenav">
          <div style={{ fontFamily: disp, fontSize: 9, color: C.t4, fontWeight: 700,
            letterSpacing: "0.14em", marginBottom: 16 }}>
            CIS v4.1 SPEC
          </div>
          {ANCHORS.map(([num, label, hash]) => {
            const active = activeAnchor === hash;
            return (
              <button
                key={hash}
                onClick={() => scrollTo(hash)}
                style={{
                  display: "block", width: "100%", textAlign: "left",
                  background: "transparent", border: "none", cursor: "pointer",
                  padding: "7px 0", fontFamily: body, fontSize: 12,
                  color: active ? C.cyan : C.t3,
                  borderLeft: active ? `2px solid ${C.cyan}` : "2px solid transparent",
                  paddingLeft: 12, marginLeft: -12,
                  transition: "all 0.14s ease",
                }}>
                <span style={{ fontFamily: mono, fontSize: 9, color: active ? C.cyan : C.t4,
                  marginRight: 6 }}>{num}</span>
                {label}
              </button>
            );
          })}

          {/* Live CIS link */}
          <div style={{ marginTop: 32, paddingTop: 20, borderTop: `1px solid ${C.border}` }}>
            <a href="/app.html" style={{
              fontFamily: disp, fontSize: 10, fontWeight: 700, letterSpacing: "0.07em",
              textDecoration: "none", color: C.indigo, display: "block",
              padding: "8px 12px", borderRadius: 6,
              background: "rgba(99,102,241,0.08)", border: `1px solid rgba(99,102,241,0.24)`,
            }}>
              View Live Scores →
            </a>
          </div>
        </aside>

        {/* ── Main content ── */}
        <main style={{ flex: 1, padding: "48px 56px 120px", maxWidth: 860 }}>

          {/* Hero */}
          <div id="purpose" style={{ marginBottom: 0 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 20 }}>
              <Pill label="CIS" color={C.cyan} />
              <Pill label="v4.1" color={C.indigo} />
              <Pill label="2026-03-23" color={C.t4} />
              <div style={{ flex: 1, height: 1, background: C.border }} />
            </div>
            <h1 style={{
              fontFamily: brand, fontSize: 40, fontWeight: 800, color: C.t1,
              margin: "0 0 16px", letterSpacing: "-0.02em", lineHeight: 1.1,
            }}>
              CometCloud Intelligence Score
              <br />
              <span style={{ color: C.indigo, fontSize: 30 }}>Methodology Specification</span>
            </h1>
            <p style={{ fontFamily: body, fontSize: 16, color: C.t3, lineHeight: 1.7, maxWidth: 620, margin: 0 }}>
              CIS is a multi-pillar composite score for ranking digital and traditional
              assets. It is designed for two distinct consumers: institutional investors
              who need transparent, auditable methodology, and autonomous trading systems
              that require stable, continuous signals with liquidity awareness.
            </p>

            {/* Stats row */}
            <div style={{ display: "flex", gap: 24, marginTop: 36, flexWrap: "wrap" }}>
              {[
                ["84",    "Assets Scored",     C.cyan],
                ["5",     "Analytical Pillars", C.indigo],
                ["2",     "Data Tiers",         C.gold],
                ["6",     "Macro Regimes",      C.green],
                ["0–100", "Score Range",        C.t2],
              ].map(([val, label, color]) => (
                <div key={label} style={{
                  background: C.surface, border: `1px solid ${C.border}`,
                  borderRadius: 8, padding: "16px 20px", minWidth: 100,
                }}>
                  <div style={{ fontFamily: mono, fontSize: 22, fontWeight: 700, color, lineHeight: 1 }}>{val}</div>
                  <div style={{ fontFamily: body, fontSize: 11, color: C.t3, marginTop: 4 }}>{label}</div>
                </div>
              ))}
            </div>
          </div>

          {/* §1 Purpose */}
          <Section id="purpose" noBorder>
            <div style={{ marginTop: 64 }} />
            <SectionTitle num="1" title="Purpose" />
            <Card>
              <p style={{ fontFamily: body, fontSize: 14, color: C.t2, lineHeight: 1.75, margin: 0 }}>
                CIS provides a unified, continuously-updated quality signal across 84 assets
                spanning crypto-native and traditional financial instruments. The score is
                not a price forecast. It measures the <em>structural quality, momentum,
                risk profile, sentiment positioning, and independent alpha potential</em> of
                each asset at a given point in time.
              </p>
              <p style={{ fontFamily: body, fontSize: 14, color: C.t2, lineHeight: 1.75, margin: "16px 0 0" }}>
                Every score is derived from publicly observable data sources — market prices,
                on-chain metrics, protocol TVL, and macro indicators. No proprietary
                data, no black-box adjustments. The full methodology is specified here.
              </p>
            </Card>
          </Section>

          {/* §2 Architecture */}
          <Section id="architecture">
            <SectionTitle num="2" title="Architecture: Two Engines, One Methodology"
              sub="Scores originate from two independent engines that share identical scoring logic and grading thresholds." />

            <Table
              headers={["", "Tier 1 · Full Engine", "Tier 2 · Market Estimation"]}
              colWidths={["180px", "auto", "auto"]}
              rows={[
                ["Price Data",    "High-frequency OHLCV klines (1h, 30d+)", "CoinGecko spot + 24h/7d/30d Δ"],
                ["On-Chain",      "DeFiLlama TVL real-time",                 "DeFiLlama TVL cached 30min"],
                ["Macro",         "Fed funds, VIX, DXY, TNX",                "VIX, Fear & Greed Index"],
                ["Regime",        "6-state detection",                        "Risk-On / Risk-Off binary"],
                ["Risk Metrics",  "Sharpe, Sortino, rolling beta, max DD",   "ATH distance proxy, vol estimate"],
                ["Universe",      "40+ assets, 8 asset classes",              "84 assets, curated leaders"],
                ["Update Freq",   "~30 min push",                             "On-demand (60s refresh)"],
                ["Display Badge", "CIS PRO · T1 (green)",                    "CIS MKT · T2 (amber)"],
              ]}
            />

            <div style={{ marginTop: 24 }}>
              <Card>
                <div style={{ fontFamily: disp, fontSize: 11, color: C.t3, fontWeight: 700,
                  letterSpacing: "0.1em", marginBottom: 12 }}>OUTPUT SCHEMA — BOTH TIERS</div>
                <pre style={{
                  fontFamily: mono, fontSize: 12, color: C.t2, lineHeight: 1.7,
                  margin: 0, whiteSpace: "pre-wrap",
                }}>{`{
  "cis_score":   0–100,         // weighted composite
  "grade":       "A+" … "F",   // unified absolute thresholds
  "signal":      "STRONG OUTPERFORM" | "OUTPERFORM" |
                 "NEUTRAL" | "UNDERPERFORM" | "UNDERWEIGHT",
  "data_tier":   1 | 2,
  "confidence":  0.0–1.0,      // data completeness ratio
  "las":         0–100,        // Liquidity-Adjusted Score
  "pillars":     { F, M, O, S, A }
}`}</pre>
              </Card>
            </div>
          </Section>

          {/* §3 Pillars */}
          <Section id="pillars">
            <SectionTitle num="3" title="Pillar Scoring (0–100 each)"
              sub="All five pillars use continuous functions — no discrete tier step functions. Every input difference produces a proportional score difference." />

            <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>

              <PillarCard
                letter="F" name="Fundamental — Structural Quality"
                color={C.cyan} weight="25–35%"
                desc="Market capitalization scale, on-chain depth, token economic health"
                components={[
                  ["Market Cap Scale",  "min(50, 10 × log₁₀(mcap / $1M))",          "0–50"],
                  ["TVL Depth",         "min(20, 5 × log₁₀(tvl / $1M))  [DeFi/L2 only]", "0–20"],
                  ["FDV Fairness",      "max(0, 15 × (1 – fdv/mcap) / 4)",           "0–15"],
                  ["Supply Health",     "15 × (circ_supply / total_supply)",         "0–15"],
                ]}
              />

              <PillarCard
                letter="M" name="Momentum — Market Activity"
                color={C.indigo} weight="20–35%"
                desc="Trading volume, liquidity depth relative to market cap, price trajectory"
                components={[
                  ["Volume Scale",     "min(40, 8 × log₁₀(vol_24h / $100K))",        "0–40"],
                  ["Liquidity Ratio",  "min(25, vol_24h / mcap × 200)",              "0–25"],
                  ["Price Momentum",   "Linear: –50% → 0, 0% → 15, +50% → 30, +100% → 35", "0–35"],
                ]}
              />

              <PillarCard
                letter="O" name="On-Chain Health / Risk-Adjusted"
                color={C.gold} weight="10–25%"
                desc="Risk-adjusted returns, drawdown resilience, protocol stability"
                components={[
                  ["Sharpe Ratio (T1)", "min(35, max(0, sharpe × 15 + 15))",         "0–35"],
                  ["Max Drawdown",      "max(0, 35 × (1 – mdd / 80))",               "0–35"],
                  ["TVL Stability",     "7d TVL change: <–20%→0, stable→20, growth→30", "0–30"],
                  ["ATH Recovery (T2)", "min(35, max(0, 35 × (1 – ath_dist / 80)))", "0–35"],
                ]}
              />

              <PillarCard
                letter="S" name="Sentiment — Market Psychology"
                color={C.green} weight="15–25%"
                desc="Market-wide sentiment baseline plus per-asset divergence and volatility regime"
                components={[
                  ["Baseline (Crypto)",  "Fear & Greed Index × 0.4",                 "0–40"],
                  ["Baseline (TradFi)",  "VIX inverse: VIX=12→38pts, VIX=30→8pts",  "0–40"],
                  ["Asset Divergence",   "30d vs category median × 0.5 + 24h burst", "–20 to +40"],
                  ["Vol Regime Mod.",    "Breakout→+15, Capitulation→–10, Accum→+10", "–10 to +20"],
                ]}
              />

              <PillarCard
                letter="A" name="Alpha — Independent Return"
                color="#818cf8" weight="10–20%"
                desc="Asset-specific return independent of BTC/SPY benchmark; correlation discount applied"
                components={[
                  ["Benchmark Div.",   "30d return – benchmark × 0.8 (continuous)",  "–20 to +40"],
                  ["Class Independence","DeFi/RWA > L1/L2 > Meme premium",            "0–20"],
                  ["Size Efficiency",  "Small cap with strong score → alpha bonus",   "–5 to +20"],
                  ["Correlation Disc.", "High beta to BTC/SPY → penalty",             "–15 to 0"],
                ]}
              />
            </div>

            <Card style={{ marginTop: 24 }}>
              <div style={{ fontFamily: disp, fontSize: 11, color: C.t3, fontWeight: 700,
                letterSpacing: "0.1em", marginBottom: 12 }}>BENCHMARKS BY CLASS</div>
              <div style={{
                display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))",
                gap: 10,
              }}>
                {[
                  ["Crypto (excl. BTC)", "BTC 30d return"],
                  ["Bitcoin",            "SPY 30d return"],
                  ["US Equity",          "SPY"],
                  ["US Bond",            "–SPY (inverted)"],
                  ["Commodity",          "SPY"],
                ].map(([cls, bench]) => (
                  <div key={cls} style={{
                    background: "rgba(99,102,241,0.06)", borderRadius: 6,
                    padding: "10px 14px", border: `1px solid ${C.border}`,
                  }}>
                    <div style={{ fontFamily: disp, fontSize: 10, color: C.t4, marginBottom: 4 }}>{cls}</div>
                    <div style={{ fontFamily: mono, fontSize: 11, color: C.t2 }}>{bench}</div>
                  </div>
                ))}
              </div>
            </Card>
          </Section>

          {/* §4 Weights */}
          <Section id="weights">
            <SectionTitle num="4" title="Weighting"
              sub="Base weights vary by asset class to reflect structural differences. Tier 1 applies additional regime adjustments." />

            <Table
              headers={["Asset Class", "F", "M", "O", "S", "A"]}
              rows={[
                ["L1 Blockchain",      "30%", "25%", "20%", "15%", "10%"],
                ["L2 / Scaling",       "30%", "25%", "20%", "15%", "10%"],
                ["DeFi Protocol",      "25%", "25%", "25%", "15%", "10%"],
                ["RWA",                "35%", "20%", "20%", "15%", "10%"],
                ["Infrastructure",     "30%", "20%", "25%", "10%", "15%"],
                ["Memecoin",           "15%", "35%", "15%", "25%", "10%"],
                ["US Equity",          "30%", "25%", "10%", "20%", "15%"],
                ["US Bond",            "30%", "20%", "10%", "20%", "20%"],
                ["Commodity",          "25%", "25%", "10%", "20%", "20%"],
              ]}
            />

            <div style={{ marginTop: 24 }}>
              <Card>
                <div style={{ fontFamily: disp, fontSize: 11, color: C.gold, fontWeight: 700,
                  letterSpacing: "0.1em", marginBottom: 14 }}>
                  REGIME ADJUSTMENTS (TIER 1 ONLY)
                </div>
                <p style={{ fontFamily: body, fontSize: 13, color: C.t3, margin: "0 0 16px", lineHeight: 1.6 }}>
                  The Tier 1 engine detects the current macro regime from Fed policy, VIX,
                  DXY, and yield curve signals. Pillar weights are then adjusted to
                  reflect what matters most in each regime.
                </p>
                <Table
                  headers={["Regime", "F", "M", "O", "S", "A", "Interpretation"]}
                  rows={[
                    ["RISK_ON",     "+0%",  "+5%",  "–5%",  "+5%",  "+0%",  "Momentum + sentiment lead"],
                    ["RISK_OFF",    "+5%",  "–10%", "+10%", "+0%",  "–5%",  "Quality + risk control"],
                    ["TIGHTENING",  "+5%",  "–5%",  "+5%",  "–5%",  "+0%",  "Fundamentals dominate"],
                    ["EASING",      "–5%",  "+5%",  "–5%",  "+0%",  "+5%",  "Momentum + alpha expand"],
                    ["STAGFLATION", "+5%",  "–5%",  "+10%", "–5%",  "–5%",  "Defensive quality"],
                    ["GOLDILOCKS",  "+2%",  "+2%",  "+2%",  "+2%",  "+2%",  "Balanced — all pillars equal"],
                  ]}
                />
              </Card>
            </div>
          </Section>

          {/* §5 Grading */}
          <Section id="grading">
            <SectionTitle num="5" title="Grading — Absolute Thresholds"
              sub="Both engines use identical thresholds. Percentile rank is metadata only and does not override grades." />

            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(110px, 1fr))", gap: 12 }}>
              {[
                ["A+", "≥ 85", C.green,  "STRONG OUTPERFORM"],
                ["A",  "≥ 75", C.green,  "OUTPERFORM"],
                ["B+", "≥ 65", C.cyan,   "OUTPERFORM"],
                ["B",  "≥ 55", C.cyan,   "NEUTRAL"],
                ["C+", "≥ 45", C.gold,   "NEUTRAL"],
                ["C",  "≥ 35", C.gold,   "UNDERPERFORM"],
                ["D",  "≥ 25", C.red,    "UNDERWEIGHT"],
                ["F",  "< 25", C.red,    "UNDERWEIGHT"],
              ].map(([grade, range, color, signal]) => (
                <div key={grade} style={{
                  background: `${color}0e`, border: `1px solid ${color}30`,
                  borderRadius: 8, padding: "14px 12px", textAlign: "center",
                }}>
                  <div style={{ fontFamily: mono, fontSize: 22, fontWeight: 700, color, lineHeight: 1 }}>{grade}</div>
                  <div style={{ fontFamily: mono, fontSize: 10, color: C.t3, margin: "4px 0 8px" }}>{range}</div>
                  <div style={{ fontFamily: disp, fontSize: 8, fontWeight: 700, color, letterSpacing: "0.08em",
                    background: `${color}20`, padding: "2px 6px", borderRadius: 3 }}>
                    {signal}
                  </div>
                </div>
              ))}
            </div>

            <Card style={{ marginTop: 20 }}>
              <div style={{ fontFamily: disp, fontSize: 11, color: C.t3, fontWeight: 700,
                letterSpacing: "0.1em", marginBottom: 10 }}>SIGNAL VOCABULARY</div>
              <p style={{ fontFamily: body, fontSize: 13, color: C.t3, lineHeight: 1.7, margin: 0 }}>
                CIS signals use positioning language exclusively. CometCloud does not hold
                an investment advisory license and does not issue buy or sell recommendations.
                Signals indicate quantitative positioning relative to the scored universe —
                not forecasts of future price performance.
              </p>
            </Card>
          </Section>

          {/* §6 LAS */}
          <Section id="las">
            <SectionTitle num="6" title="Liquidity-Adjusted Score (LAS)"
              sub="Adjusts the raw CIS score for realistic position sizing given available market depth. Designed for agent and fund consumers." />

            <Formula
              label="FORMULA"
              expr="LAS = CIS × liquidity_multiplier × spread_penalty × confidence"
              note="Range: 0–100. A score of 0 means the asset cannot be traded at meaningful size regardless of its CIS grade."
            />

            <Table
              headers={["Factor", "Formula", "Range", "Purpose"]}
              rows={[
                ["Liquidity Mult.",  "min(1.0, daily_tradeable / target_position)\nFloor: 0.15", "0.15–1.0", "Position absorptability"],
                ["Spread Penalty",   "1.0 – max(0, (hl_range – 0.05) × 2), min 0.8", "0.80–1.0", "Bid/ask cost penalty"],
                ["Confidence",       "data_completeness / applicable_fields",              "0.0–1.0", "Data quality discount"],
                ["OI Penalty (T1)",  "max(0.7, 1.0 – (oi_mcap_ratio – 0.2) × 0.375)",     "0.70–1.0", "Leverage risk discount"],
              ]}
            />

            <Card style={{ marginTop: 16, background: "rgba(6,182,212,0.04)", border: `1px solid rgba(6,182,212,0.16)` }}>
              <p style={{ fontFamily: body, fontSize: 13, color: C.t2, lineHeight: 1.7, margin: 0 }}>
                <strong style={{ color: C.cyan }}>Confidence is asset-class aware.</strong> Traditional
                financial assets (equities, bonds, commodities) are not penalised for
                lacking crypto-native data fields (TVL, Fear & Greed Index, circulating supply).
                Confidence is computed from the subset of fields applicable to each class.
              </p>
            </Card>
          </Section>

          {/* §7 Compliance */}
          <Section id="compliance">
            <SectionTitle num="7" title="Compliance Framework"
              sub="CIS operates under strict signal language controls. Non-compliance triggers automatic pipeline rejection." />

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
              <Card style={{ borderLeft: `3px solid ${C.green}` }}>
                <div style={{ fontFamily: disp, fontSize: 10, color: C.green, fontWeight: 700,
                  letterSpacing: "0.1em", marginBottom: 12 }}>✓ PERMITTED SIGNALS</div>
                {["STRONG OUTPERFORM", "OUTPERFORM", "NEUTRAL", "UNDERPERFORM", "UNDERWEIGHT"].map(s => (
                  <div key={s} style={{ fontFamily: mono, fontSize: 12, color: C.t2,
                    padding: "5px 0", borderBottom: `1px solid ${C.border}` }}>{s}</div>
                ))}
              </Card>
              <Card style={{ borderLeft: `3px solid ${C.red}` }}>
                <div style={{ fontFamily: disp, fontSize: 10, color: C.red, fontWeight: 700,
                  letterSpacing: "0.1em", marginBottom: 12 }}>✗ PROHIBITED LANGUAGE</div>
                {["BUY", "SELL", "STRONG BUY", "STRONG SELL", "ACCUMULATE", "REDUCE", "AVOID"].map(s => (
                  <div key={s} style={{ fontFamily: mono, fontSize: 12, color: C.t4,
                    padding: "5px 0", borderBottom: `1px solid ${C.border}`, textDecoration: "line-through" }}>{s}</div>
                ))}
              </Card>
            </div>

            <Card style={{ marginTop: 16 }}>
              <p style={{ fontFamily: body, fontSize: 13, color: C.t3, lineHeight: 1.7, margin: 0 }}>
                CometCloud AI operates from Hong Kong and does not hold a Type 1 (Dealing
                in Securities) or Type 9 (Asset Management) license. CIS scores are
                quantitative positioning indicators derived from publicly observable data.
                They are not investment advice, recommendations, or solicitations.
                All consumers of the CIS API and signal feed acknowledge this distinction.
              </p>
            </Card>
          </Section>

          {/* §8 Data Integrity */}
          <Section id="integrity">
            <SectionTitle num="8" title="Data Integrity"
              sub="Each score carries explicit provenance. Stale or missing data is surfaced rather than silently omitted." />

            <Table
              headers={["Condition", "Score Behaviour", "Frontend Display"]}
              rows={[
                ["Confidence < 0.5",      "Score compresses toward 50 (less range)", "Warning dot indicator"],
                ["Volume data gap",        "LAS liq_mult floored at 0.15",           "LAS displayed in amber"],
                ["Full-model score unavailable", "System falls back to Tier 2 estimate", "Badge: CIS MKT · T2"],
                ["Market data unavail.",   "Asset excluded from universe",            "Not shown in leaderboard"],
                ["Regime transition",      "T1 flags + stores previous_regime",      "Regime badge updates live"],
              ]}
            />

            <Card style={{ marginTop: 20 }}>
              <div style={{ fontFamily: disp, fontSize: 11, color: C.t3, fontWeight: 700,
                letterSpacing: "0.1em", marginBottom: 12 }}>SCORE HISTORY</div>
              <p style={{ fontFamily: body, fontSize: 13, color: C.t2, lineHeight: 1.7, margin: 0 }}>
                Every CIS push is persisted to a time-series database. Institutions can
                request historical score data to audit score stability and model the
                relationship between CIS signals and subsequent price performance.
                The CIS API exposes a{" "}
                <code style={{ fontFamily: mono, background: "rgba(6,182,212,0.10)",
                  padding: "1px 5px", borderRadius: 3, color: C.cyan, fontSize: 11 }}>
                  /api/v1/cis/history/batch
                </code>{" "}
                endpoint returning scored data back to the index inception date.
              </p>
            </Card>
          </Section>

          {/* Footer CTA */}
          <div style={{
            marginTop: 80, padding: "40px 0", borderTop: `1px solid ${C.border}`,
            display: "flex", gap: 16, flexWrap: "wrap", alignItems: "center",
          }}>
            <a href="/app.html" style={{
              fontFamily: disp, fontSize: 11, fontWeight: 700, letterSpacing: "0.07em",
              textDecoration: "none", color: "#0a1020",
              background: `linear-gradient(135deg, ${C.indigo}, ${C.cyan})`,
              padding: "10px 22px", borderRadius: 8, border: "none",
            }}>
              View Live CIS Platform →
            </a>
            <a href="/strategy.html" style={{
              fontFamily: disp, fontSize: 11, fontWeight: 700, letterSpacing: "0.07em",
              textDecoration: "none", color: C.t2,
              border: `1px solid ${C.border}`, padding: "10px 22px", borderRadius: 8,
            }}>
              Investment Strategy
            </a>
            <span style={{ fontFamily: body, fontSize: 12, color: C.t4, marginLeft: "auto" }}>
              CIS v4.1 · Effective 2026-03-23
            </span>
          </div>
        </main>
      </div>

      {/* Mobile responsive */}
      <style>{`
        @media (max-width: 768px) {
          .method-sidenav { display: none; }
        }
      `}</style>
    </div>
  );
}
