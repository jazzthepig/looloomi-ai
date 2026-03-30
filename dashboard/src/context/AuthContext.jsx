/**
 * AuthContext — shared wallet auth state for CometCloud AI
 *
 * Provides:
 *   useAuth()  → { address, token, status, isConnected, connect, disconnect }
 *
 * Architecture:
 *   - Uses window.solana (Phantom injected provider) directly — no adapter lib needed
 *   - Session persisted in localStorage (cc_session / cc_wallet)
 *   - Session validated against backend on mount; stale tokens are cleared
 *   - Redis-backed session tokens (24h TTL) on Railway backend
 *
 * Usage:
 *   Wrap App with <AuthProvider> once.
 *   Any component calls useAuth() to read/drive auth state.
 */

import { createContext, useContext, useState, useEffect, useCallback } from "react";

const API = import.meta.env.VITE_API_URL || "";

// ── LocalStorage keys ─────────────────────────────────────────────────────────
const LS_SESSION = "cc_session";
const LS_ADDRESS = "cc_wallet";

function loadSession() {
  try {
    const token   = localStorage.getItem(LS_SESSION);
    const address = localStorage.getItem(LS_ADDRESS);
    return token && address ? { token, address } : null;
  } catch { return null; }
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

export function shortAddr(address) {
  if (!address) return "";
  return `${address.slice(0, 4)}…${address.slice(-4)}`;
}

function toHex(bytes) {
  return Array.from(bytes).map(b => b.toString(16).padStart(2, "0")).join("");
}

function signMessage(address, nonce) {
  return `CometCloud AI\nSign in with wallet: ${address}\nNonce: ${nonce}`;
}

// ── Context ───────────────────────────────────────────────────────────────────
const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [state, setState] = useState({
    address: null,
    token:   null,
    status:  "idle",     // idle | connecting | signing | error | connected
    error:   null,
    profile: null,       // Supabase wallet_profiles row (optional)
  });

  // ── Restore session on mount ────────────────────────────────────────────────
  useEffect(() => {
    const session = loadSession();
    if (!session) return;

    // Optimistically restore — then validate in background
    setState(s => ({
      ...s,
      address: session.address,
      token:   session.token,
      status:  "connected",
    }));

    // Background validation: ping /auth/profile with session token to confirm still valid
    fetch(`${API}/api/v1/auth/profile/${session.address}`, {
      headers: { "Authorization": `Bearer ${session.token}` },
    })
      .then(r => {
        if (!r.ok) throw new Error("session invalid");
        return r.json();
      })
      .then(profile => {
        setState(s => ({ ...s, profile }));
      })
      .catch(() => {
        // Session expired server-side — clear local state
        clearSession();
        setState({ address: null, token: null, status: "idle", error: null, profile: null });
      });
  }, []);

  // ── Connect (Phantom → sign → verify) ──────────────────────────────────────
  const connect = useCallback(async () => {
    const phantom = window.solana;
    if (!phantom?.isPhantom) {
      setState(s => ({ ...s, status: "error", error: "Phantom not found — install at phantom.app" }));
      setTimeout(() => setState(s => s.status === "error" ? { ...s, status: "idle", error: null } : s), 4000);
      return;
    }

    setState(s => ({ ...s, status: "connecting", error: null }));

    try {
      // 1. Connect wallet
      const { publicKey } = await phantom.connect();
      const address = publicKey.toString();
      setState(s => ({ ...s, status: "signing", address }));

      // 2. Get nonce
      const nonceRes = await fetch(`${API}/api/v1/auth/nonce/${address}`);
      if (!nonceRes.ok) throw new Error("Backend unavailable — try again");
      const { message, nonce } = await nonceRes.json();

      // 3. Sign (user may cancel → code 4001)
      const encodedMsg = new TextEncoder().encode(message || signMessage(address, nonce));
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
      const { session_token: token, profile } = await signinRes.json();

      saveSession(address, token);
      setState({ address, token, status: "connected", error: null, profile: profile || null });

    } catch (err) {
      const isCancel =
        err?.code === 4001 ||
        err?.message?.toLowerCase().includes("rejected") ||
        err?.message?.toLowerCase().includes("cancelled") ||
        err?.message?.toLowerCase().includes("user denied");

      if (isCancel) {
        setState({ address: null, token: null, status: "idle", error: null, profile: null });
      } else {
        const msg = err?.message || "Connection failed";
        setState(s => ({ ...s, status: "error", error: msg, address: null, token: null }));
        setTimeout(() => setState(s => s.status === "error" ? { ...s, status: "idle", error: null } : s), 5000);
      }
    }
  }, []);

  // ── Disconnect ───────────────────────────────────────────────────────────────
  const disconnect = useCallback(() => {
    try { window.solana?.disconnect(); } catch {}
    clearSession();
    setState({ address: null, token: null, status: "idle", error: null, profile: null });
  }, []);

  const value = {
    ...state,
    isConnected: state.status === "connected",
    connect,
    disconnect,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

// ── Hook ───────────────────────────────────────────────────────────────────────
export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}

// ── AuthGate — render children only when connected ────────────────────────────
export function AuthGate({ children, fallback }) {
  const { isConnected } = useAuth();
  if (isConnected) return children;
  return fallback ?? null;
}
