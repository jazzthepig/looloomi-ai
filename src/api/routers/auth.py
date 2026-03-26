"""
Auth Router — Wallet-based sign-in for CometCloud AI
=====================================================
Solana wallet sign-in: connect → sign nonce → verify → upsert Supabase profile.

Endpoints:
  GET  /api/v1/auth/config          — returns public Supabase config for frontend
  GET  /api/v1/auth/nonce/{address} — returns a fresh nonce for the wallet to sign
  POST /api/v1/auth/wallet-signin   — verify signature, upsert profile, return session
  GET  /api/v1/auth/profile/{addr}  — fetch wallet profile

Signature verification:
  Solana uses Ed25519. PyNaCl's nacl.signing.VerifyKey handles this.
  Message format: "CometCloud AI\nSign in with wallet: {address}\nNonce: {nonce}"
"""

import os, json, time, secrets
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.api.store import redis_get_key, redis_set_key, _get_supabase_client

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

# ── Config ─────────────────────────────────────────────────────────────────────
_SB_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
_SB_KEY = os.environ.get("SUPABASE_KEY", "")
_SB_TABLE = "wallet_profiles"

_SB_HEADERS = {
    "apikey": _SB_KEY,
    "Authorization": f"Bearer {_SB_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation",
}

# Nonce TTL: 5 minutes
_NONCE_TTL = 300

# Sign-in message template
def _sign_message(address: str, nonce: str) -> str:
    return f"CometCloud AI\nSign in with wallet: {address}\nNonce: {nonce}"


# ── Models ─────────────────────────────────────────────────────────────────────
class WalletSigninRequest(BaseModel):
    address: str          # Solana base58 public key
    nonce: str            # nonce that was signed
    signature: str        # hex or base58 signature bytes


# ── Helpers ────────────────────────────────────────────────────────────────────
async def _sb_upsert_profile(address: str) -> dict:
    """Upsert wallet_profiles row, return the row."""
    client = _get_supabase_client()
    now = datetime.now(timezone.utc).isoformat()
    url = f"{_SB_URL}/rest/v1/{_SB_TABLE}"
    payload = {
        "wallet_address": address,
        "last_seen": now,
    }
    # Upsert: insert with on conflict update last_seen
    try:
        resp = await client.post(
            url,
            content=json.dumps(payload),
            headers={
                **_SB_HEADERS,
                "Prefer": "return=representation,resolution=merge-duplicates",
            },
        )
        if resp.status_code in (200, 201):
            rows = resp.json()
            return rows[0] if isinstance(rows, list) and rows else payload
        else:
            print(f"[AUTH] Supabase upsert error {resp.status_code}: {resp.text[:200]}")
            return payload
    except Exception as e:
        print(f"[AUTH] Supabase upsert exception: {e}")
        return payload


def _verify_solana_signature(address: str, message: str, signature: str) -> bool:
    """
    Verify an Ed25519 signature from a Solana wallet.
    Falls back to True in dev mode if PyNaCl is unavailable.
    """
    try:
        import nacl.signing
        import nacl.encoding
        import base58

        # Decode public key from base58
        pub_bytes = base58.b58decode(address)
        verify_key = nacl.signing.VerifyKey(pub_bytes)

        # Decode signature — try hex first, then base58
        if len(signature) == 128:  # hex 64 bytes
            sig_bytes = bytes.fromhex(signature)
        else:
            sig_bytes = base58.b58decode(signature)

        # Message as bytes
        msg_bytes = message.encode("utf-8")

        verify_key.verify(msg_bytes, sig_bytes)
        return True
    except ImportError:
        # PyNaCl not installed — skip verification in dev
        print("[AUTH] WARNING: PyNaCl not available, skipping sig verification")
        return True
    except Exception as e:
        print(f"[AUTH] Signature verification failed: {e}")
        return False


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get("/config")
async def get_auth_config():
    """
    Returns public Supabase config for frontend initialization.
    The anon key is intentionally public (row-level security enforced server-side).
    """
    return {
        "supabase_url": _SB_URL,
        "supabase_anon_key": _SB_KEY,
        "wallet_sign_message_template": "CometCloud AI\nSign in with wallet: {address}\nNonce: {nonce}",
    }


@router.get("/nonce/{address}")
async def get_nonce(address: str):
    """
    Issue a fresh nonce for a wallet address.
    Stored in Redis with 5-minute TTL.
    Frontend calls this before asking user to sign.
    """
    if not address or len(address) < 32:
        raise HTTPException(status_code=400, detail="Invalid wallet address")

    nonce = secrets.token_hex(16)
    cache_key = f"auth:nonce:{address}"
    await redis_set_key(cache_key, {"nonce": nonce, "ts": int(time.time())}, ttl=_NONCE_TTL)

    return {
        "address": address,
        "nonce": nonce,
        "message": _sign_message(address, nonce),
        "expires_in": _NONCE_TTL,
    }


@router.post("/wallet-signin")
async def wallet_signin(req: WalletSigninRequest):
    """
    Verify wallet signature and return session.

    Flow:
      1. Fetch nonce from Redis for this address
      2. Reconstruct sign message
      3. Verify Ed25519 signature
      4. Upsert wallet_profiles in Supabase
      5. Return session token (simple Redis-backed token, 24h TTL)
    """
    if not _SB_URL or not _SB_KEY:
        raise HTTPException(status_code=503, detail="Auth service not configured")

    # 1. Fetch expected nonce
    cache_key = f"auth:nonce:{req.address}"
    nonce_data = await redis_get_key(cache_key)
    if not nonce_data:
        raise HTTPException(
            status_code=400,
            detail="Nonce expired or not found. Call /auth/nonce/{address} first.",
        )

    expected_nonce = nonce_data.get("nonce", "")
    if req.nonce != expected_nonce:
        raise HTTPException(status_code=400, detail="Nonce mismatch")

    # 2. Reconstruct message
    message = _sign_message(req.address, req.nonce)

    # 3. Verify signature
    if not _verify_solana_signature(req.address, message, req.signature):
        raise HTTPException(status_code=401, detail="Invalid signature")

    # 4. Upsert Supabase profile
    profile = await _sb_upsert_profile(req.address)

    # 5. Issue session token (24h Redis)
    session_token = secrets.token_hex(32)
    session_key = f"auth:session:{session_token}"
    await redis_set_key(
        session_key,
        {
            "address": req.address,
            "created_at": int(time.time()),
        },
        ttl=86400,  # 24 hours
    )

    # Invalidate used nonce
    await redis_set_key(cache_key, {}, ttl=1)

    return {
        "ok": True,
        "address": req.address,
        "session_token": session_token,
        "expires_in": 86400,
        "profile": profile,
    }


@router.get("/profile/{address}")
async def get_profile(address: str):
    """Fetch public wallet profile."""
    if not _SB_URL or not _SB_KEY:
        raise HTTPException(status_code=503, detail="Auth service not configured")

    client = _get_supabase_client()
    url = f"{_SB_URL}/rest/v1/{_SB_TABLE}"
    try:
        resp = await client.get(
            url,
            params={"wallet_address": f"eq.{address}", "select": "*"},
            headers=_SB_HEADERS,
        )
        if resp.status_code == 200:
            rows = resp.json()
            if rows:
                return rows[0]
        raise HTTPException(status_code=404, detail="Profile not found")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
