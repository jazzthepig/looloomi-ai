/**
 * ApiKeysPage — Self-serve API key issuance
 * Free tier delivered instantly. Pro/Enterprise via email follow-up.
 */
import { useState } from "react";
import { track } from "../main.jsx";

const API_BASE = import.meta.env.VITE_API_URL || "";

const TIERS = [
  {
    id: "free",
    label: "Free",
    rpm: 60,
    rpd: "1,000",
    features: ["CIS Universe (84 assets)", "Macro Pulse", "Signal Feed", "Standard latency"],
    cta: "Get Free Key",
    price: "$0",
    highlight: false,
  },
  {
    id: "pro",
    label: "Pro",
    rpm: 300,
    rpd: "50,000",
    features: ["Everything in Free", "Grade-change webhooks", "LAS + confidence scores", "Historical time series", "Priority support"],
    cta: "Request Pro Access",
    price: "Contact us",
    highlight: true,
  },
  {
    id: "enterprise",
    label: "Enterprise",
    rpm: "Custom",
    rpd: "Unlimited",
    features: ["Everything in Pro", "Dedicated endpoints", "SLA guarantee", "Custom regime signals", "White-label option"],
    cta: "Talk to Jazz",
    price: "Custom",
    highlight: false,
  },
];

export default function ApiKeysPage() {
  const [form, setForm] = useState({ name: "", email: "", intended_use: "", tier: "free" });
  const [state, setState] = useState("idle"); // idle | loading | success | error
  const [result, setResult] = useState(null);
  const [copied, setCopied] = useState(false);
  const [errorMsg, setErrorMsg] = useState("");

  const handleTierSelect = (tier) => {
    if (tier === "pro" || tier === "enterprise") {
      window.location.href = `mailto:jazz@cometcloud.ai?subject=CometCloud ${tier.charAt(0).toUpperCase() + tier.slice(1)} API Access&body=Name: %0ACompany: %0AUse case: `;
      return;
    }
    setForm((f) => ({ ...f, tier }));
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!form.name.trim() || !form.email.trim()) return;
    setState("loading");
    setErrorMsg("");

    try {
      const res = await fetch(`${API_BASE}/api/v1/keys/create`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: form.name.trim(),
          email: form.email.trim(),
          intended_use: form.intended_use.trim() || "general",
          tier: "free",
        }),
      });

      const data = await res.json();

      if (!res.ok) {
        throw new Error(data.detail || data.message || `Error ${res.status}`);
      }

      setResult(data);
      setState("success");
      track("api_key_created", { tier: "free", intended_use: form.intended_use || "general" });
    } catch (err) {
      setErrorMsg(err.message || "Request failed. Try again or email jazz@cometcloud.ai");
      setState("error");
    }
  };

  const copyKey = () => {
    if (result?.api_key) {
      navigator.clipboard.writeText(result.api_key).then(() => {
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      });
    }
  };

  return (
    <div style={{ minHeight: "100vh", background: "#020208", color: "#e8e6dc", fontFamily: "'Exo 2', sans-serif", padding: "0 0 80px" }}>

      {/* Header */}
      <div style={{ borderBottom: "1px solid rgba(0,240,255,0.08)", padding: "40px 24px 32px", maxWidth: 960, margin: "0 auto" }}>
        <div style={{ fontSize: 11, letterSpacing: "0.2em", color: "#00f0ff", opacity: 0.7, marginBottom: 12, textTransform: "uppercase" }}>
          Research as a Service · API Access
        </div>
        <h1 style={{ fontFamily: "'Space Grotesk', sans-serif", fontSize: 32, fontWeight: 700, margin: "0 0 12px", color: "#faf9f5" }}>
          CometCloud Intelligence API
        </h1>
        <p style={{ fontSize: 15, color: "#b0aea5", maxWidth: 560, margin: 0, lineHeight: 1.6 }}>
          Institutional-grade crypto scoring for agents, quants, and developers.
          Free tier delivers instantly. Pro and Enterprise via direct onboarding.
        </p>
      </div>

      <div style={{ maxWidth: 960, margin: "0 auto", padding: "0 24px" }}>

        {/* Tier Cards */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: 16, marginTop: 40, marginBottom: 48 }}>
          {TIERS.map((tier) => (
            <div
              key={tier.id}
              style={{
                background: tier.highlight ? "rgba(0,240,255,0.04)" : "rgba(5,7,22,0.88)",
                border: `1px solid ${tier.highlight ? "rgba(0,240,255,0.25)" : "rgba(0,240,255,0.08)"}`,
                borderRadius: 8,
                padding: "24px 20px",
                position: "relative",
              }}
            >
              {tier.highlight && (
                <div style={{ position: "absolute", top: -1, left: 20, background: "#00f0ff", color: "#020208", fontSize: 10, fontWeight: 700, letterSpacing: "0.15em", padding: "2px 10px", borderRadius: "0 0 4px 4px", textTransform: "uppercase" }}>
                  Most Popular
                </div>
              )}
              <div style={{ fontSize: 13, color: "#b0aea5", marginBottom: 4, textTransform: "uppercase", letterSpacing: "0.1em" }}>{tier.label}</div>
              <div style={{ fontFamily: "'Space Grotesk', sans-serif", fontSize: 26, fontWeight: 700, color: "#faf9f5", marginBottom: 4 }}>{tier.price}</div>
              <div style={{ fontSize: 12, color: "#b0aea5", marginBottom: 20 }}>
                {typeof tier.rpm === "number" ? `${tier.rpm} rpm · ${tier.rpd} req/day` : "Custom limits"}
              </div>
              <ul style={{ listStyle: "none", padding: 0, margin: "0 0 24px", fontSize: 13, color: "#b0aea5" }}>
                {tier.features.map((f) => (
                  <li key={f} style={{ padding: "4px 0", display: "flex", gap: 8, alignItems: "flex-start" }}>
                    <span style={{ color: "#00f0ff", opacity: 0.8, flexShrink: 0, marginTop: 1 }}>◈</span>
                    {f}
                  </li>
                ))}
              </ul>
              <button
                onClick={() => handleTierSelect(tier.id)}
                style={{
                  width: "100%",
                  padding: "10px 0",
                  background: tier.highlight ? "#00f0ff" : "transparent",
                  color: tier.highlight ? "#020208" : "#00f0ff",
                  border: `1px solid ${tier.highlight ? "#00f0ff" : "rgba(0,240,255,0.3)"}`,
                  borderRadius: 4,
                  fontSize: 13,
                  fontWeight: 600,
                  cursor: "pointer",
                  letterSpacing: "0.05em",
                }}
              >
                {tier.cta}
              </button>
            </div>
          ))}
        </div>

        {/* Key Request Form */}
        {state !== "success" && (
          <div style={{ background: "rgba(5,7,22,0.88)", border: "1px solid rgba(0,240,255,0.08)", borderRadius: 8, padding: "32px 28px", maxWidth: 520 }}>
            <h2 style={{ fontFamily: "'Space Grotesk', sans-serif", fontSize: 18, fontWeight: 600, margin: "0 0 6px", color: "#faf9f5" }}>
              Request Free API Key
            </h2>
            <p style={{ fontSize: 13, color: "#b0aea5", margin: "0 0 24px" }}>
              60 req/min · 1,000 req/day · No credit card required
            </p>

            <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: 16 }}>
              <div>
                <label style={{ fontSize: 12, color: "#b0aea5", display: "block", marginBottom: 6, letterSpacing: "0.08em", textTransform: "uppercase" }}>Name *</label>
                <input
                  type="text"
                  value={form.name}
                  onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                  placeholder="Your name or org"
                  required
                  style={inputStyle}
                />
              </div>
              <div>
                <label style={{ fontSize: 12, color: "#b0aea5", display: "block", marginBottom: 6, letterSpacing: "0.08em", textTransform: "uppercase" }}>Email *</label>
                <input
                  type="email"
                  value={form.email}
                  onChange={(e) => setForm((f) => ({ ...f, email: e.target.value }))}
                  placeholder="you@example.com"
                  required
                  style={inputStyle}
                />
              </div>
              <div>
                <label style={{ fontSize: 12, color: "#b0aea5", display: "block", marginBottom: 6, letterSpacing: "0.08em", textTransform: "uppercase" }}>Intended Use</label>
                <input
                  type="text"
                  value={form.intended_use}
                  onChange={(e) => setForm((f) => ({ ...f, intended_use: e.target.value }))}
                  placeholder="e.g. quant research, agent integration, dashboarding"
                  style={inputStyle}
                />
              </div>

              {state === "error" && (
                <div style={{ fontSize: 13, color: "#ff6b6b", background: "rgba(255,107,107,0.08)", border: "1px solid rgba(255,107,107,0.2)", borderRadius: 4, padding: "10px 14px" }}>
                  {errorMsg}
                </div>
              )}

              <button
                type="submit"
                disabled={state === "loading"}
                style={{
                  padding: "12px 0",
                  background: state === "loading" ? "rgba(0,240,255,0.15)" : "#00f0ff",
                  color: "#020208",
                  border: "none",
                  borderRadius: 4,
                  fontSize: 14,
                  fontWeight: 700,
                  cursor: state === "loading" ? "not-allowed" : "pointer",
                  letterSpacing: "0.05em",
                }}
              >
                {state === "loading" ? "Generating…" : "Generate Free Key"}
              </button>
            </form>
          </div>
        )}

        {/* Success State — show key once */}
        {state === "success" && result && (
          <div style={{ background: "rgba(5,7,22,0.88)", border: "1px solid rgba(0,240,255,0.2)", borderRadius: 8, padding: "32px 28px", maxWidth: 520 }}>
            <div style={{ fontSize: 11, letterSpacing: "0.2em", color: "#00f0ff", opacity: 0.7, marginBottom: 12, textTransform: "uppercase" }}>
              ◈ Key Generated
            </div>
            <h2 style={{ fontFamily: "'Space Grotesk', sans-serif", fontSize: 20, fontWeight: 600, margin: "0 0 8px", color: "#faf9f5" }}>
              Your API key is ready
            </h2>
            <p style={{ fontSize: 13, color: "#ff9d4a", margin: "0 0 20px" }}>
              Copy this now — it won't be shown again.
            </p>

            <div style={{ display: "flex", gap: 8, alignItems: "center", marginBottom: 24 }}>
              <code style={{
                flex: 1,
                background: "rgba(0,0,0,0.4)",
                border: "1px solid rgba(0,240,255,0.15)",
                borderRadius: 4,
                padding: "10px 14px",
                fontSize: 13,
                fontFamily: "'JetBrains Mono', monospace",
                color: "#00f0ff",
                wordBreak: "break-all",
              }}>
                {result.api_key}
              </code>
              <button
                onClick={copyKey}
                style={{
                  padding: "10px 16px",
                  background: copied ? "rgba(0,240,255,0.15)" : "transparent",
                  border: "1px solid rgba(0,240,255,0.3)",
                  borderRadius: 4,
                  color: "#00f0ff",
                  cursor: "pointer",
                  fontSize: 12,
                  whiteSpace: "nowrap",
                }}
              >
                {copied ? "Copied ✓" : "Copy"}
              </button>
            </div>

            <div style={{ fontSize: 13, color: "#b0aea5", marginBottom: 20, lineHeight: 1.6 }}>
              <strong style={{ color: "#e8e6dc" }}>Rate limits:</strong> 60 req/min · 1,000 req/day<br />
              <strong style={{ color: "#e8e6dc" }}>Header:</strong> <code style={{ fontFamily: "monospace", color: "#00f0ff" }}>X-API-Key: {result.api_key?.slice(0, 20)}…</code>
            </div>

            <div style={{ background: "rgba(0,0,0,0.3)", border: "1px solid rgba(0,240,255,0.08)", borderRadius: 4, padding: "14px 16px" }}>
              <div style={{ fontSize: 11, color: "#b0aea5", marginBottom: 8, letterSpacing: "0.1em", textTransform: "uppercase" }}>Quick start</div>
              <pre style={{ margin: 0, fontSize: 12, color: "#e8e6dc", fontFamily: "'JetBrains Mono', monospace", whiteSpace: "pre-wrap", lineHeight: 1.6 }}>
{`curl https://looloomi.ai/api/v1/cis/universe \\
  -H "X-API-Key: ${result.api_key}"`}
              </pre>
            </div>

            <div style={{ marginTop: 20, fontSize: 13, color: "#b0aea5" }}>
              Need higher limits?{" "}
              <a href="mailto:jazz@cometcloud.ai?subject=Pro API Access" style={{ color: "#00f0ff", textDecoration: "none" }}>
                jazz@cometcloud.ai
              </a>
            </div>
          </div>
        )}

        {/* Quick reference */}
        <div style={{ marginTop: 48, display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: 12 }}>
          {[
            { label: "CIS Universe", path: "/api/v1/cis/universe", desc: "84 assets, grades, signals, pillars" },
            { label: "Macro Pulse", path: "/api/v1/market/macro-pulse", desc: "Regime, BTC dominance, FNG" },
            { label: "Signal Feed", path: "/api/v1/signals/feed", desc: "7 concurrent intelligence sources" },
            { label: "Asset History", path: "/api/v1/cis/history/BTC?days=7", desc: "Score time series + delta + z-score" },
          ].map((ep) => (
            <div key={ep.path} style={{ background: "rgba(5,7,22,0.6)", border: "1px solid rgba(0,240,255,0.06)", borderRadius: 6, padding: "14px 16px" }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: "#e8e6dc", marginBottom: 4 }}>{ep.label}</div>
              <div style={{ fontSize: 11, color: "#00f0ff", fontFamily: "monospace", marginBottom: 6, wordBreak: "break-all" }}>{ep.path}</div>
              <div style={{ fontSize: 11, color: "#b0aea5" }}>{ep.desc}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

const inputStyle = {
  width: "100%",
  background: "rgba(0,0,0,0.3)",
  border: "1px solid rgba(0,240,255,0.12)",
  borderRadius: 4,
  padding: "10px 14px",
  fontSize: 14,
  color: "#e8e6dc",
  outline: "none",
  boxSizing: "border-box",
  fontFamily: "'Exo 2', sans-serif",
};
