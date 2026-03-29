/**
 * WalletConnect — Phantom wallet sign-in for CometCloud AI
 *
 * Now driven by AuthContext — state is shared across the entire app.
 * useWalletAuth() is kept as an alias for backward compatibility.
 *
 * Flow:
 *   1. connect()     → window.solana.connect() → get publicKey
 *   2. nonce()       → GET /api/v1/auth/nonce/:address
 *   3. signMessage() → window.solana.signMessage(encoded message)
 *   4. signin()      → POST /api/v1/auth/wallet-signin → session token
 *   5. AuthContext persists token + address in localStorage + shared state
 */

import { useState } from "react";
import { useAuth, shortAddr } from "../context/AuthContext.jsx";

// ── Backward-compat alias ────────────────────────────────────────────────────
export function useWalletAuth() {
  return useAuth();
}

// ── Component ────────────────────────────────────────────────────────────────

const GOLD = "#C8A84B";

export default function WalletConnect({ compact = false }) {
  const { address, status, error, connect, disconnect } = useAuth();
  const [showMenu, setShowMenu] = useState(false);

  const isConnected = status === "connected";
  const isLoading   = status === "connecting" || status === "signing";

  const labelMap = {
    idle:       compact ? "Connect" : "Connect Wallet",
    connecting: "Connecting…",
    signing:    "Sign in Phantom…",
    connected:  shortAddr(address),
    error:      "Retry",
  };
  const label = labelMap[status] || "Connect";

  const dotColor = isConnected ? "#00D98A" : status === "error" ? "#FF2D55" : "transparent";

  return (
    <div style={{ position: "relative", display: "inline-block" }}>
      <button
        onClick={isConnected ? () => setShowMenu(m => !m) : connect}
        disabled={isLoading}
        style={{
          display: "flex", alignItems: "center", gap: 6,
          padding: compact ? "5px 12px" : "7px 16px",
          borderRadius: 8,
          border: `1px solid ${isConnected ? "rgba(200,168,75,0.35)" : "rgba(56,148,210,0.20)"}`,
          background: isConnected ? "rgba(200,168,75,0.08)" : "rgba(255,255,255,0.04)",
          color: isConnected ? GOLD : "#7AAEC8",
          fontFamily: "'Space Grotesk', sans-serif",
          fontWeight: 700, fontSize: compact ? 11 : 12,
          letterSpacing: "0.06em", cursor: isLoading ? "not-allowed" : "pointer",
          opacity: isLoading ? 0.6 : 1, transition: "all 0.2s ease", whiteSpace: "nowrap",
        }}
        onMouseEnter={e => {
          if (!isLoading) e.currentTarget.style.borderColor = isConnected ? "rgba(200,168,75,0.55)" : "rgba(56,148,210,0.40)";
        }}
        onMouseLeave={e => {
          e.currentTarget.style.borderColor = isConnected ? "rgba(200,168,75,0.35)" : "rgba(56,148,210,0.20)";
        }}
      >
        {/* Status dot */}
        {(isConnected || status === "error") && (
          <span style={{
            width: 6, height: 6, borderRadius: "50%",
            background: dotColor,
            boxShadow: isConnected ? `0 0 8px ${dotColor}` : "none",
            flexShrink: 0,
          }} />
        )}

        {/* Phantom ghost icon (idle) */}
        {!isConnected && !isLoading && (
          <svg width="14" height="14" viewBox="0 0 128 128" fill="none" style={{ flexShrink: 0 }}>
            <rect width="128" height="128" rx="26" fill="rgba(200,168,75,0.12)" />
            <path d="M110 64c0 25.4-20.6 46-46 46S18 89.4 18 64 38.6 18 64 18s46 20.6 46 46z" fill="rgba(200,168,75,0.5)" />
            <circle cx="52" cy="58" r="8" fill="#EFF8FF" />
            <circle cx="76" cy="58" r="8" fill="#EFF8FF" />
          </svg>
        )}

        {label}
      </button>

      {/* Error tooltip */}
      {status === "error" && error && (
        <div style={{
          position: "absolute", top: "calc(100% + 8px)", right: 0,
          background: "rgba(14,30,56,0.95)", border: "1px solid rgba(255,61,90,0.3)",
          borderRadius: 8, padding: "8px 12px",
          color: "#FF3D5A", fontSize: 11, fontFamily: "'Exo 2', sans-serif",
          boxShadow: "0 4px 12px rgba(0,0,0,0.4)",
          whiteSpace: "nowrap", maxWidth: 240, zIndex: 2000,
        }}>
          {error}
        </div>
      )}

      {/* Wallet menu (connected) */}
      {isConnected && showMenu && (
        <div
          style={{
            position: "absolute", top: "calc(100% + 8px)", right: 0,
            background: "rgba(9,23,40,0.97)", border: "1px solid rgba(56,148,210,0.18)",
            borderRadius: 10, padding: "4px",
            minWidth: 200, zIndex: 2000,
            boxShadow: "0 8px 32px rgba(0,0,0,0.5), 0 2px 8px rgba(6,182,212,0.06)",
          }}
          onMouseLeave={() => setShowMenu(false)}
        >
          {/* Address row */}
          <div style={{
            padding: "8px 12px", fontSize: 11,
            fontFamily: "'JetBrains Mono', monospace", color: GOLD,
            borderBottom: "1px solid rgba(255,255,255,0.06)",
            marginBottom: 4, letterSpacing: "0.02em",
            overflow: "hidden", textOverflow: "ellipsis",
          }}>
            {address}
          </div>

          <button onClick={() => { navigator.clipboard?.writeText(address); }} style={menuItemStyle}>
            Copy address
          </button>

          <button
            onClick={() => { disconnect(); setShowMenu(false); }}
            style={{ ...menuItemStyle, color: "#FF2D55" }}
          >
            Disconnect
          </button>
        </div>
      )}
    </div>
  );
}

const menuItemStyle = {
  display: "block", width: "100%", textAlign: "left",
  padding: "8px 12px", borderRadius: 6,
  border: "none", background: "transparent",
  color: "#7AAEC8",
  fontFamily: "'Space Grotesk', sans-serif", fontSize: 12, fontWeight: 600,
  cursor: "pointer", transition: "background 0.15s",
};
