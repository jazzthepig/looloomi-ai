import { useState } from "react";
import MarketDashboard from "./components/MarketDashboard";
import IntelligencePage from "./components/IntelligencePage";
import CISLeaderboard from "./components/CISLeaderboard";

export default function App() {
  const [activeTab, setActiveTab] = useState("Market");

  return (
    <>
      {activeTab === "Market" && (
        <MarketDashboard activeTab={activeTab} setActiveTab={setActiveTab} />
      )}
      {(activeTab === "Intelligence" || activeTab === "Quant GP") && (
        <IntelligencePage activeTab={activeTab} setActiveTab={setActiveTab} />
      )}
      {activeTab === "CIS" && (
        <CISPage activeTab={activeTab} setActiveTab={setActiveTab} />
      )}
    </>
  );
}

// CIS Page wrapper with navigation
function CISPage({ activeTab, setActiveTab }) {
  return (
    <div style={{ position: "relative", minHeight: "100vh", background: "#020208" }}>
      <div className="turrell-wrap">
        <div className="t-orb t-orb-1" /><div className="t-orb t-orb-2" />
        <div className="t-orb t-orb-3" /><div className="t-orb t-orb-4" />
      </div>
      <div style={{ position: "relative", zIndex: 1, maxWidth: 1400, margin: "0 auto", padding: "0 28px 56px" }}>
        {/* Navigation */}
        <div style={{
          display: "flex", alignItems: "center", justifyContent: "space-between",
          padding: "18px 0 20px", borderBottom: `1px solid #1A173A`,
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
            <span style={{
              fontFamily: "'Space Grotesk', sans-serif", fontWeight: 800, fontSize: 20,
              letterSpacing: "-0.03em",
              background: "linear-gradient(120deg,#FF1060 0%,#6B0FCC 45%,#4472FF 100%)",
              WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent",
            }}>
              LOOLOOMI
            </span>
            <div style={{ display: "flex", gap: 4 }}>
              {["Market", "Intelligence", "CIS", "Quant GP"].map(tab => (
                <button key={tab} className={`lm-tab${activeTab === tab ? " active" : ""}`}
                  onClick={() => setActiveTab(tab)}>
                  {tab}
                </button>
              ))}
            </div>
          </div>
        </div>

        {/* Header */}
        <div style={{ marginTop: 24, marginBottom: 20 }}>
          <h1 style={{
            fontFamily: "'Space Grotesk', sans-serif", fontSize: 28, fontWeight: 700,
            color: "#F0EEFF", marginBottom: 8, letterSpacing: "-0.02em"
          }}>
            CIS Leaderboard
          </h1>
          <p style={{
            fontFamily: "'Exo 2', sans-serif", fontSize: 14, color: "#8880BE",
            maxWidth: 600, lineHeight: 1.6
          }}>
            CometCloud Intelligence Score — Multi-dimensional asset evaluation
            across Fundamental, Market Structure, On-Chain Health, Sentiment, and Alpha Independence.
          </p>
        </div>

        {/* Stats Summary */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 10, marginBottom: 24 }}>
          {[
            { label: "Total Assets", value: "20", color: "#4472FF" },
            { label: "Grade A", value: "4", color: "#00D98A" },
            { label: "Grade B", value: "12", color: "#4472FF" },
            { label: "Grade C", value: "4", color: "#E8A000" },
          ].map((s, i) => (
            <div key={i} className="lm-card" style={{ padding: "16px 20px" }}>
              <div style={{ fontSize: 10, color: "#3E3A6E", letterSpacing: "0.1em", textTransform: "uppercase", marginBottom: 8 }}>
                {s.label}
              </div>
              <div style={{ fontSize: 24, fontWeight: 600, color: s.color, fontFamily: "'JetBrains Mono', monospace" }}>
                {s.value}
              </div>
            </div>
          ))}
        </div>

        {/* Leaderboard */}
        <div className="lm-card" style={{ overflow: "hidden" }}>
          <CISLeaderboard />
        </div>
      </div>

      <style>{`
        .turrell-wrap { position:fixed;inset:0;pointer-events:none;z-index:0;overflow:hidden; }
        .t-orb { position:absolute;border-radius:50%;filter:blur(100px);mix-blend-mode:screen; }
        .t-orb-1 { width:720px;height:720px;background:radial-gradient(circle,rgba(107,15,204,.20) 0%,transparent 65%);top:-300px;left:-200px;animation:breathe 52s ease-in-out infinite; }
        .t-orb-2 { width:560px;height:560px;background:radial-gradient(circle,rgba(45,53,212,.15) 0%,transparent 65%);top:5%;right:-200px;animation:breathe2 64s ease-in-out infinite 9s; }
        .t-orb-3 { width:380px;height:380px;background:radial-gradient(circle,rgba(0,200,224,.09) 0%,transparent 65%);bottom:0;left:22%;animation:breathe 76s ease-in-out infinite 24s; }
        .t-orb-4 { width:280px;height:280px;background:radial-gradient(circle,rgba(255,16,96,.07) 0%,transparent 65%);bottom:12%;right:8%;animation:breathe2 60s ease-in-out infinite 38s; }
        @keyframes breathe { 0%,100%{opacity:.28;transform:scale(1) translateY(0)} 50%{opacity:.44;transform:scale(1.06) translateY(-12px)} }
        @keyframes breathe2 { 0%,100%{opacity:.16;transform:scale(1)} 50%{opacity:.30;transform:scale(1.08) translateX(10px)} }
        .lm-card { background:rgba(10,9,24,.82);border:1px solid #1A173A;border-radius:10px;backdrop-filter:blur(20px); }
        .lm-tab { padding:5px 14px;border-radius:5px;font-size:12px;font-weight:500;font-family:'Exo 2',sans-serif;cursor:pointer;outline:none;border:1px solid #1A173A;background:transparent;color:#8880BE;transition:all .18s ease;letter-spacing:.01em; }
        .lm-tab:hover { border-color:#28244C;color:#F0EEFF; }
        .lm-tab.active { border-color:rgba(68,114,255,.5);background:rgba(68,114,255,.10);color:#4472FF; }
      `}</style>
    </div>
  );
}
