/**
 * WalletConnect — Phantom wallet sign-in for CometCloud AI
 *
 * Uses window.solana (Phantom injected provider) directly.
 * No wallet-adapter library needed — lighter bundle, same result.
 *
 * Flow:
 *   1. connect()     → window.solana.connect() → get publicKey
 *   2. nonce()       → GET /api/v1/auth/nonce/:address
 *   3. signMessage() → window.solana.signMessage(encoded message)
 *   4. signin()      → POST /api/v1/auth/wallet-signin → session token
 *   5. Store token + address in localStorage → auth state in context
 */

import { useState, useEffect, useCallback } from "react";

const API = import.meta.env.VITE_API_URL || "";

// ── Utilities ────────────────────────────────────────────────────────────────

const LS_SESSION = "cc_session";
const LS_ADDRESS = "cc_wallet";

function loadSession() {
  try {
    const token = localStorage.getItem(LS_SESSION);
    const address = localStorage.getItem(LS_ADDRESS);
    return token && address ? { token, address } : null;
  } catch {
    return null;
  }
}

function saveSession(address, token) {
  try {
    localStorage.setItem(LS_SESSION, token);
    localStorage.setItem(LS_ADDRESS, address);
  } catch {}
}

function clearSession() {
  try {
    localStorage.removeItem(LS_SESSION);
    localStorage.removeItem(LS_ADDRESS);
  } catch {}
}

function shortAddr(address) {
  if (!address) return "";
  return `${address.slice(0, 4)}…${address.slice(-4)}`;
}

// Convert Uint8Array signature to hex string
function toHex(bytes) {
  return Array.from(bytes).map(b => b.toString(16).padStart(2, "0")).join("");
}

// ── Hook ────────────────────────────────────────────────────────────────────

export function useWalletAuth() {
  const [state, setState] = useState({
    address: null,
    token: null,
    status: "idle",   // idle | connecting | signing | error | connected
    error: null,
  });

  // Restore session on mount
  useEffect(() => {
    const session = loadSession();
    if (session) {
      setState(s => ({ ...s, address: session.address, token: session.token, status: "connected" }));
    }
  }, []);

  const connect = useCallback(async () => {
    const phantom = window.solana;
    if (!phantom?.isPhantom) {
      setState(s => ({ ...s, status: "error", error: "Phantom not found — install at phantom.app" }));
      // Auto-clear error after 4s
      setTimeout(() => setState(s => s.status === "error" ? { ...s, status: "idle", error: null } : s), 4000);
      return;
    }

    setState(s => ({ ...s, status: "connecting", error: null }));

    try {
      // 1. Connect wallet (user may cancel → code 4001)
      const { publicKey } = await phantom.connect();
      const address = publicKey.toString();

      setState(s => ({ ...s, status: "signing", address }));

      // 2. Get nonce from backend
      const nonceRes = await fetch(`${API}/api/v1/auth/nonce/${address}`);
      if (!nonceRes.ok) throw new Error("Backend unavailable — try again");
      const { message, nonce } = await nonceRes.json();

      // 3. Sign the message (user may cancel → code 4001)
      const encodedMsg = new TextEncoder().encode(message);
      const { signature } = await phantom.signMessage(encodedMsg, "utf8");
      const sigHex = toHex(signature);

      // 4. Verify + get session
      const signinRes = await fetch(`${API}/api/v1/auth/wallet-signin`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ address, nonce, signature: sigHex }),
      });
      if (!signinRes.ok) {
        const err = await signinRes.json().catch(() => ({}));
        throw new Error(err.detail || "Sign-in failed");
      }
      const { session_token: token } = await signinRes.json();

      saveSession(address, token);
      setState({ address, token, status: "connected", error: null });

    } catch (err) {
      // User dismissed Phantom popup → code 4001 or message includes "rejected"
      const isCancel =
        err?.code === 4001 ||
        err?.message?.toLowerCase().includes("rejected") ||
        err?.message?.toLowerCase().includes("cancelled") ||
        err?.message?.toLowerCase().includes("user denied");

      if (isCancel) {
        // Silently reset — not an error
        setState({ address: null, token: null, status: "idle", error: null });
      } else {
        const msg = err?.message || "Connection failed";
        setState(s => ({ ...s, status: "error", error: msg, address: null, token: null }));
        // Auto-clear error after 5s
        setTimeout(() => setState(s => s.status === "error" ? { ...s, status: "idle", error: null } : s), 5000);
      }
    }
  }, []);

  const disconnect = useCallback(() => {
    try { window.solana?.disconnect(); } catch {}
    clearSession();
    setState({ address: null, token: null, status: "idle", error: null });
  }, []);

  return { ...state, connect, disconnect };
}


// ── Component ────────────────────────────────────────────────────────────────

const GOLD = "#92722A";
const VOID = "#FFFFFF";

export default function WalletConnect({ compact = false }) {
  const { address, status, error, connect, disconnect } = useWalletAuth();

  const [showMenu, setShowMenu] = useState(false);

  const isConnected = status === "connected";
  const isLoading = status === "connecting" || status === "signing";

  const labelMap = {
    idle:       compact ? "Connect" : "Connect Wallet",
    connecting: "Connecting…",
    signing:    "Sign in Phantom…",
    connected:  shortAddr(address),
    error:      compact ? "Retry" : "Retry",
  };

  const label = labelMap[status] || "Connect";

  // Status dot color
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
          border: `1px solid ${isConnected ? "rgba(146,114,42,0.3)" : "rgba(0,0,0,0.1)"}`,
          background: isConnected
            ? "rgba(146,114,42,0.06)"
            : "transparent",
          color: isConnected ? GOLD : "#6B7280",
          fontFamily: "'Space Grotesk', sans-serif",
          fontWeight: 700,
          fontSize: compact ? 11 : 12,
          letterSpacing: "0.06em",
          cursor: isLoading ? "not-allowed" : "pointer",
          opacity: isLoading ? 0.6 : 1,
          transition: "all 0.2s ease",
          whiteSpace: "nowrap",
        }}
        onMouseEnter={e => {
          if (!isLoading) e.currentTarget.style.borderColor = "rgba(146,114,42,0.5)";
        }}
        onMouseLeave={e => {
          e.currentTarget.style.borderColor = isConnected
            ? "rgba(146,114,42,0.3)"
            : "rgba(0,0,0,0.1)";
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

        {/* Phantom logo (SVG) */}
        {!isConnected && !isLoading && (
          <svg width="14" height="14" viewBox="0 0 128 128" fill="none" style={{ flexShrink: 0 }}>
            <rect width="128" height="128" rx="26" fill="rgba(146,114,42,0.15)" />
            <path d="M110 64c0 25.4-20.6 46-46 46S18 89.4 18 64 38.6 18 64 18s46 20.6 46 46z" fill="rgba(146,114,42,0.6)" />
            <circle cx="52" cy="58" r="8" fill="#FFFFFF" />
            <circle cx="76" cy="58" r="8" fill="#FFFFFF" />
          </svg>
        )}

        {label}
      </button>

      {/* Error tooltip */}
      {status === "error" && error && (
        <div style={{
          position: "absolute", top: "calc(100% + 8px)", right: 0,
          background: "#FFFFFF", border: "1px solid rgba(239,68,68,0.2)",
          borderRadius: 8, padding: "8px 12px",
          color: "#EF4444", fontSize: 11, fontFamily: "'Inter', sans-serif",
          boxShadow: "0 4px 12px rgba(0,0,0,0.08)",
          whiteSpace: "nowrap", maxWidth: 240, zIndex: 2000,
        }}>
          {error}
        </div>
      )}

      {/* Wallet menu (when connected) */}
      {isConnected && showMenu && (
        <div
          style={{
            position: "absolute", top: "calc(100% + 8px)", right: 0,
            background: "#FFFFFF", border: "1px solid rgba(0,0,0,0.08)",
            borderRadius: 10, padding: "4px",
            minWidth: 180, zIndex: 2000,
            boxShadow: "0 8px 24px rgba(0,0,0,0.1), 0 2px 8px rgba(0,0,0,0.04)",
          }}
          onMouseLeave={() => setShowMenu(false)}
        >
          {/* Address row */}
          <div style={{
            padding: "8px 12px", fontSize: 11,
            fontFamily: "'JetBrains Mono', monospace", color: GOLD,
            borderBottom: "1px solid rgba(0,0,0,0.06)",
            marginBottom: 4,
          }}>
            {address}
          </div>

          <button
            onClick={() => { navigator.clipboard?.writeText(address); }}
            style={menuItemStyle}
          >
            Copy address
          </button>

          <button
            onClick={() => {
              disconnect();
              setShowMenu(false);
            }}
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
  color: "#4B5563",
  fontFamily: "'Space Grotesk', sans-serif", fontSize: 12, fontWeight: 600,
  cursor: "pointer",
  transition: "background 0.15s",
};
