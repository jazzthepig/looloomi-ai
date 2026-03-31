/**
 * ShareCard — CometCloud AI marketing share card
 *
 * Generates a live-data poster card for WeChat / Telegram / social sharing.
 * Features:
 *   - Live CIS top 5 assets + grades from API
 *   - Current macro regime + FNG from API
 *   - Referral code input → personalised strategy.html link
 *   - "Copy Link" one-tap referral
 *   - Screenshot-optimised card (540×960 portrait)
 *   - Download as image (html2canvas)
 */

import { useState, useEffect, useRef } from "react";
import { T, FONTS } from "../tokens";

const F = FONTS;

const GRADE_COLOR = {
  "A+": "#00D98A", "A": "#00D98A",
  "B+": "#C8A84B", "B": "#C8A84B",
  "C+": "#4472FF", "C": "#4472FF",
  "D": "#FF6B35", "F": "#FF2D55",
};

const SIG_SHORT = {
  "STRONG OUTPERFORM": "STR ↑",
  "OUTPERFORM":        "↑",
  "NEUTRAL":           "—",
  "UNDERPERFORM":      "↓",
  "UNDERWEIGHT":       "↓↓",
};
const SIG_COLOR = {
  "STRONG OUTPERFORM": "#00D98A",
  "OUTPERFORM":        "#4472FF",
  "NEUTRAL":           "#E8A000",
  "UNDERPERFORM":      "#FF6B35",
  "UNDERWEIGHT":       "#FF2D55",
};

const REGIME_LABEL = {
  RISK_ON:     "Risk On",  RISK_OFF:    "Risk Off",
  TIGHTENING:  "Tightening", EASING:    "Easing",
  STAGFLATION: "Stagflation", GOLDILOCKS: "Goldilocks",
};
const REGIME_COLOR = {
  RISK_ON: "#00D98A", RISK_OFF: "#FF2D55",
  TIGHTENING: "#FF6B35", EASING: "#4472FF",
  STAGFLATION: "#E8A000", GOLDILOCKS: "#C8A84B",
};

export default function ShareCard() {
  const [topAssets, setTopAssets] = useState([]);
  const [macro, setMacro]         = useState(null);
  const [refCode, setRefCode]     = useState("");
  const [copied, setCopied]       = useState(false);
  const [loading, setLoading]     = useState(true);
  const cardRef = useRef(null);

  // Read ?ref= from URL on mount
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const r = params.get("ref");
    if (r) setRefCode(r);
  }, []);

  // Fetch live data
  useEffect(() => {
    const fetchData = async () => {
      try {
        const [cisRes, macroRes] = await Promise.all([
          fetch("/api/v1/cis/universe"),
          fetch("/api/v1/market/macro-pulse"),
        ]);
        const cisJson   = cisRes.ok   ? await cisRes.json()   : null;
        const macroJson = macroRes.ok ? await macroRes.json() : null;

        if (cisJson?.universe || cisJson?.data) {
          const sorted = [...(cisJson.universe || cisJson.data)]
            .filter(a => a.cis_score > 0 && a.grade)
            .sort((a, b) => (b.cis_score || 0) - (a.cis_score || 0))
            .slice(0, 5);
          setTopAssets(sorted);
        }
        if (macroJson) setMacro(macroJson);
      } catch (e) {
        console.warn("ShareCard data fetch failed:", e);
      } finally {
        setLoading(false);
      }
    };
    fetchData();
  }, []);

  const referralUrl = `https://looloomi.ai/strategy.html${refCode ? `?ref=${encodeURIComponent(refCode)}` : ""}`;

  const copyLink = async () => {
    try {
      await navigator.clipboard.writeText(referralUrl);
      setCopied(true);
      setTimeout(() => setCopied(false), 2500);
    } catch {
      // fallback: select input
    }
  };

  const today = new Date().toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" });
  const regime = macro?.regime || macro?.macro_regime;
  const fng    = macro?.fear_greed_index ?? macro?.fng;
  const btcDom = macro?.btc_dominance;
  const mcap   = macro?.total_market_cap;

  const fmtMcap = (v) => {
    if (!v) return "—";
    if (v >= 1e12) return `$${(v / 1e12).toFixed(2)}T`;
    if (v >= 1e9)  return `$${(v / 1e9).toFixed(0)}B`;
    return `$${v}`;
  };

  return (
    <div style={{
      minHeight: "100vh", background: "#08080F",
      display: "flex", flexDirection: "column",
      alignItems: "center", padding: "32px 20px 60px",
      fontFamily: F.body,
    }}>

      {/* Page title */}
      <div style={{ width: "100%", maxWidth: 540, marginBottom: 24 }}>
        <div style={{ fontFamily: F.display, fontSize: 13, fontWeight: 700, color: "#C8A84B", letterSpacing: "0.08em", marginBottom: 4 }}>
          CometCloud AI
        </div>
        <div style={{ fontFamily: F.display, fontSize: 22, fontWeight: 700, color: "#F1F5F9", letterSpacing: "-0.02em" }}>
          Marketing Share Card
        </div>
        <div style={{ fontFamily: F.body, fontSize: 12, color: "#3E6680", marginTop: 4 }}>
          Screenshot and share on WeChat / Telegram / social
        </div>
      </div>

      {/* ── THE CARD (screenshot target) ── */}
      <div ref={cardRef} id="share-card" style={{
        width: 540, minHeight: 880,
        background: "linear-gradient(160deg, #020208 0%, #0A1222 40%, #060A18 100%)",
        border: "1px solid rgba(56,148,210,0.15)",
        borderRadius: 20, overflow: "hidden", position: "relative",
        boxShadow: "0 32px 80px rgba(0,0,0,0.7)",
      }}>

        {/* Turrell ambient orbs */}
        <div style={{ position: "absolute", inset: 0, pointerEvents: "none", overflow: "hidden" }}>
          <div style={{ position: "absolute", width: 480, height: 480, borderRadius: "50%", top: -200, left: -150, background: "radial-gradient(circle, rgba(107,15,204,0.18) 0%, transparent 65%)", filter: "blur(60px)" }} />
          <div style={{ position: "absolute", width: 320, height: 320, borderRadius: "50%", bottom: -100, right: -80, background: "radial-gradient(circle, rgba(45,53,212,0.12) 0%, transparent 65%)", filter: "blur(60px)" }} />
          <div style={{ position: "absolute", width: 200, height: 200, borderRadius: "50%", top: "45%", right: -60, background: "radial-gradient(circle, rgba(0,200,224,0.07) 0%, transparent 65%)", filter: "blur(40px)" }} />
        </div>

        <div style={{ position: "relative", zIndex: 1, padding: "32px 32px 28px" }}>

          {/* Header */}
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 28 }}>
            <div>
              <div style={{ fontFamily: F.display, fontWeight: 800, fontSize: 18, color: "#F1F5F9", letterSpacing: "-0.02em", marginBottom: 3 }}>
                CometCloud AI
              </div>
              <div style={{ fontFamily: F.body, fontSize: 11, color: "#3E6680", letterSpacing: "0.05em" }}>
                AI Fund-of-Funds · Solana · HK
              </div>
            </div>
            <div style={{ textAlign: "right" }}>
              <div style={{ fontFamily: F.mono, fontSize: 9, color: "#3E6680", letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 3 }}>
                {today}
              </div>
              {regime && (
                <div style={{
                  display: "inline-flex", alignItems: "center", gap: 5,
                  padding: "4px 10px", borderRadius: 20,
                  background: `${REGIME_COLOR[regime] || "#4472FF"}14`,
                  border: `1px solid ${REGIME_COLOR[regime] || "#4472FF"}40`,
                }}>
                  <div style={{ width: 5, height: 5, borderRadius: "50%", background: REGIME_COLOR[regime] || "#4472FF" }} />
                  <span style={{ fontFamily: F.mono, fontSize: 9, fontWeight: 700, color: REGIME_COLOR[regime] || "#4472FF", letterSpacing: "0.08em" }}>
                    {REGIME_LABEL[regime] || regime}
                  </span>
                </div>
              )}
            </div>
          </div>

          {/* Macro strip */}
          {macro && (
            <div style={{
              display: "grid", gridTemplateColumns: "repeat(3, 1fr)",
              gap: 1, marginBottom: 28,
              background: "rgba(255,255,255,0.04)", borderRadius: 10,
              border: "1px solid rgba(255,255,255,0.06)", overflow: "hidden",
            }}>
              {[
                { label: "Market Cap", value: fmtMcap(mcap) },
                { label: "Fear & Greed", value: fng ? `${Math.round(fng)}` : "—", color: fng >= 60 ? "#00D98A" : fng >= 40 ? "#C8A84B" : "#FF2D55" },
                { label: "BTC Dom.", value: btcDom ? `${btcDom.toFixed(1)}%` : "—" },
              ].map((m, i) => (
                <div key={i} style={{ padding: "12px 14px", background: "rgba(0,0,0,0.2)" }}>
                  <div style={{ fontFamily: F.mono, fontSize: 8, color: "#3E6680", textTransform: "uppercase", letterSpacing: "0.1em", marginBottom: 5 }}>{m.label}</div>
                  <div style={{ fontFamily: F.mono, fontSize: 16, fontWeight: 500, color: m.color || "#E2E8F0" }}>{m.value}</div>
                </div>
              ))}
            </div>
          )}

          {/* CIS Top 5 */}
          <div style={{ marginBottom: 24 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 14 }}>
              <div style={{ fontFamily: F.display, fontSize: 10, fontWeight: 700, letterSpacing: "0.14em", textTransform: "uppercase", color: "#3E6680" }}>
                CIS Top Assets
              </div>
              <div style={{ flex: 1, height: 1, background: "rgba(255,255,255,0.05)" }} />
              <div style={{ fontFamily: F.mono, fontSize: 8, color: "#3E6680", letterSpacing: "0.06em" }}>
                LIVE · AI-SCORED
              </div>
            </div>

            {loading ? (
              <div style={{ padding: "24px 0", textAlign: "center", color: "#3E6680", fontFamily: F.body, fontSize: 12 }}>Loading…</div>
            ) : topAssets.length === 0 ? (
              <div style={{ padding: "24px 0", textAlign: "center", color: "#3E6680", fontFamily: F.body, fontSize: 12 }}>No data available</div>
            ) : topAssets.map((a, i) => {
              const gc = GRADE_COLOR[a.grade] || "#6B7280";
              const sc = SIG_COLOR[a.signal] || "#6B7280";
              return (
                <div key={a.symbol} style={{
                  display: "grid", gridTemplateColumns: "20px 1fr auto auto auto",
                  alignItems: "center", gap: 12,
                  padding: "10px 0",
                  borderBottom: i < topAssets.length - 1 ? "1px solid rgba(255,255,255,0.05)" : "none",
                }}>
                  <span style={{ fontFamily: F.mono, fontSize: 10, color: "#3E6680" }}>{i + 1}</span>
                  <div>
                    <div style={{ fontFamily: F.display, fontWeight: 700, fontSize: 14, color: "#F1F5F9" }}>{a.symbol}</div>
                    <div style={{ fontFamily: F.body, fontSize: 10, color: "#3E6680", marginTop: 1 }}>{a.asset_class}</div>
                  </div>
                  <div style={{ fontFamily: F.mono, fontSize: 14, color: (a.cis_score || 0) >= 65 ? "#00D98A" : "#C8A84B" }}>
                    {(a.cis_score || 0).toFixed(1)}
                  </div>
                  <div style={{
                    width: 28, height: 28, borderRadius: 6, display: "flex", alignItems: "center", justifyContent: "center",
                    background: `${gc}18`, border: `1px solid ${gc}35`,
                    fontFamily: F.mono, fontWeight: 700, fontSize: 11, color: gc,
                  }}>
                    {a.grade}
                  </div>
                  <div style={{ fontFamily: F.mono, fontSize: 10, fontWeight: 700, color: sc, minWidth: 42, textAlign: "right" }}>
                    {SIG_SHORT[a.signal] || "—"}
                  </div>
                </div>
              );
            })}
          </div>

          {/* Key proposition */}
          <div style={{
            padding: "16px 18px", borderRadius: 10,
            background: "rgba(200,168,75,0.06)", border: "1px solid rgba(200,168,75,0.15)",
            marginBottom: 24,
          }}>
            <div style={{ fontFamily: F.display, fontSize: 12, fontWeight: 700, color: "#C8A84B", letterSpacing: "0.04em", marginBottom: 8 }}>
              Why CometCloud
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              {[
                "AI-curated Fund-of-Funds on Solana",
                "0% management fee · Performance-only",
                "Institutional DeFi · $30M AUM target",
              ].map((txt, i) => (
                <div key={i} style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <div style={{ width: 4, height: 4, borderRadius: "50%", background: "#C8A84B", flexShrink: 0 }} />
                  <span style={{ fontFamily: F.body, fontSize: 11, color: "#94A3B8" }}>{txt}</span>
                </div>
              ))}
            </div>
          </div>

          {/* Footer */}
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <div style={{ fontFamily: F.mono, fontSize: 9, color: "#3E6680", letterSpacing: "0.08em" }}>
              looloomi.ai/strategy
            </div>
            <div style={{ fontFamily: F.mono, fontSize: 9, color: "#1E3A5F", letterSpacing: "0.06em" }}>
              For qualified investors only
            </div>
          </div>
        </div>
      </div>

      {/* ── Controls below card ── */}
      <div style={{ width: "100%", maxWidth: 540, marginTop: 28, display: "flex", flexDirection: "column", gap: 16 }}>

        {/* Referral code */}
        <div>
          <div style={{ fontFamily: F.mono, fontSize: 9, color: "#3E6680", letterSpacing: "0.12em", textTransform: "uppercase", marginBottom: 8 }}>
            Your Referral Code
          </div>
          <input
            value={refCode}
            onChange={e => setRefCode(e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, ""))}
            placeholder="e.g. nic · bumblebee · yourname"
            style={{
              width: "100%", boxSizing: "border-box",
              padding: "10px 14px", borderRadius: 8,
              background: "rgba(255,255,255,0.04)",
              border: "1px solid rgba(255,255,255,0.09)",
              color: "#F1F5F9", fontFamily: F.mono, fontSize: 13,
              outline: "none",
            }}
          />
          <div style={{ fontFamily: F.body, fontSize: 11, color: "#3E6680", marginTop: 6 }}>
            Leads from your link will be attributed to this code.
          </div>
        </div>

        {/* Referral link display */}
        <div style={{
          padding: "12px 16px", borderRadius: 8,
          background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.07)",
          display: "flex", alignItems: "center", gap: 12,
        }}>
          <div style={{ flex: 1, fontFamily: F.mono, fontSize: 11, color: "#7AAEC8", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {referralUrl}
          </div>
          <button onClick={copyLink} style={{
            padding: "6px 16px", borderRadius: 6, cursor: "pointer",
            fontFamily: F.display, fontWeight: 700, fontSize: 11, letterSpacing: "0.06em",
            border: copied ? "1px solid rgba(0,217,138,0.4)" : "1px solid rgba(200,168,75,0.4)",
            background: copied ? "rgba(0,217,138,0.08)" : "rgba(200,168,75,0.08)",
            color: copied ? "#00D98A" : "#C8A84B",
            transition: "all 0.2s", flexShrink: 0,
          }}>
            {copied ? "Copied ✓" : "Copy Link"}
          </button>
        </div>

        {/* Quick share buttons */}
        <div style={{ display: "flex", gap: 10 }}>
          {[
            { label: "Share Strategy Page", href: referralUrl, color: "#4472FF" },
            { label: "Open Platform", href: "app.html", color: "#6B0FCC" },
          ].map((btn, i) => (
            <a key={i} href={btn.href} target={i === 0 ? "_blank" : "_self"} rel="noopener noreferrer"
              style={{
                flex: 1, padding: "11px 0", borderRadius: 8, textAlign: "center",
                fontFamily: F.display, fontWeight: 700, fontSize: 12, letterSpacing: "0.04em",
                color: "#fff", textDecoration: "none",
                background: `${btn.color}22`,
                border: `1px solid ${btn.color}40`,
                transition: "all 0.15s",
              }}
            >
              {btn.label}
            </a>
          ))}
        </div>

        <div style={{ fontFamily: F.mono, fontSize: 9, color: "#1E3A5F", lineHeight: 1.6, textAlign: "center" }}>
          Screenshot the card above to share on WeChat / Telegram / social media.
          CIS data is live and updates every ~30 minutes.
          For qualified investors only.
        </div>
      </div>
    </div>
  );
}
