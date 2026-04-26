#!/usr/bin/env python3
"""
CometCloud Auth E2E Test — run from Mac Mini
Tests the full wallet sign-in flow against the live Railway backend.

Usage:
    cd ~/projects/looloomi-ai
    python scripts/test_auth_e2e.py [--base https://looloomi.ai]

Requirements:
    pip install PyNaCl base58 requests
"""

import sys
import json
import time
import argparse
import traceback

try:
    import nacl.signing
    import base58
    import requests
except ImportError as e:
    print(f"[ERROR] Missing deps: {e}")
    print("       Run: pip install PyNaCl base58 requests")
    sys.exit(1)


def _fmt(status, expected=None):
    ok = expected is None or status == expected
    tag = "✅" if ok else "⚠️ "
    exp = f" (expected {expected})" if expected and not ok else ""
    return f"{tag} {status}{exp}"


def run_tests(base: str):
    session = requests.Session()
    session.timeout = 15

    print(f"\n{'='*60}")
    print(f"  CometCloud Auth E2E — {base}")
    print(f"{'='*60}\n")

    passed = 0
    failed = 0

    # ── Generate test keypair ───────────────────────────────────────────────────
    signing_key = nacl.signing.SigningKey.generate()
    verify_key  = signing_key.verify_key
    pub_bytes   = bytes(verify_key)
    address     = base58.b58encode(pub_bytes).decode()
    print(f"[SETUP] Test wallet: {address[:8]}…{address[-4:]}")
    print(f"        (Ed25519, {len(pub_bytes)} bytes)\n")

    # ── 1. Short address sanity ──────────────────────────────────────────────────
    print("[1] Short address format…")
    assert len(address) >= 32, f"Address too short: {len(address)}"
    print(f"    Address length: {len(address)} chars ✅")
    passed += 1

    # ── 2. /api/v1/auth/config ──────────────────────────────────────────────────
    print("\n[2] GET /api/v1/auth/config…")
    try:
        r = session.get(f"{base}/api/v1/auth/config")
        print(f"    Status: {_fmt(r.status_code, 200)}")
        data = r.json()
        assert "wallet_sign_message_template" in data, "Missing wallet_sign_message_template"
        print(f"    Supabase URL present: {'supabase_url' in data and bool(data['supabase_url'])}")
        print(f"    Message template: {repr(data['wallet_sign_message_template'][:50])}")
        passed += 1
    except Exception as e:
        print(f"    ❌ FAIL: {e}")
        failed += 1

    # ── 3. /api/v1/auth/nonce/{address} ─────────────────────────────────────────
    print("\n[3] GET /api/v1/auth/nonce/{address}…")
    nonce = message = None
    try:
        r = session.get(f"{base}/api/v1/auth/nonce/{address}")
        print(f"    Status: {_fmt(r.status_code, 200)}")
        data = r.json()
        nonce   = data.get("nonce")
        message = data.get("message")
        assert nonce,   "Missing nonce in response"
        assert message, "Missing message in response"
        assert len(nonce) == 32,  f"Nonce length unexpected: {len(nonce)} (want 32 hex chars)"
        assert req_addr := data.get("address"), "Missing address in response"
        assert req_addr == address, f"Address mismatch: {req_addr} != {address}"
        assert "CometCloud AI" in message, "Message missing CometCloud AI header"
        assert nonce in message, "Nonce not in message"
        print(f"    Nonce: {nonce[:8]}… ✅")
        print(f"    Message: {repr(message)}")
        passed += 1
    except Exception as e:
        print(f"    ❌ FAIL: {e}")
        failed += 1
        print("    Cannot continue without nonce — aborting")
        _print_summary(passed, failed)
        sys.exit(1)

    # ── 4. Invalid address for nonce ─────────────────────────────────────────────
    print("\n[4] GET /api/v1/auth/nonce/short (bad address, expect 400)…")
    try:
        r = session.get(f"{base}/api/v1/auth/nonce/abc")
        print(f"    Status: {_fmt(r.status_code, 400)}")
        if r.status_code == 400:
            passed += 1
        else:
            print(f"    ⚠️  Body: {r.text[:100]}")
            failed += 1
    except Exception as e:
        print(f"    ❌ FAIL: {e}")
        failed += 1

    # ── 5. Sign the message (local Ed25519) ─────────────────────────────────────
    print("\n[5] Sign message locally…")
    try:
        msg_bytes = message.encode("utf-8")
        signed    = signing_key.sign(msg_bytes)
        sig_bytes = signed.signature
        sig_hex   = sig_bytes.hex()
        assert len(sig_hex) == 128, f"Unexpected sig length: {len(sig_hex)}"

        # Verify locally — if this fails, backend will also fail
        verify_key.verify(msg_bytes, sig_bytes)
        print(f"    Signature: {sig_hex[:16]}… ({len(sig_hex)} chars)")
        print(f"    Local Ed25519 verify: ✅ PASS")
        passed += 1
    except Exception as e:
        print(f"    ❌ FAIL: {e}")
        failed += 1
        print("    Cannot continue without signature — aborting")
        _print_summary(passed, failed)
        sys.exit(1)

    # ── 6. POST /api/v1/auth/wallet-signin ──────────────────────────────────────
    print("\n[6] POST /api/v1/auth/wallet-signin…")
    token = None
    try:
        payload = {"address": address, "nonce": nonce, "signature": sig_hex}
        r = session.post(f"{base}/api/v1/auth/wallet-signin", json=payload)
        print(f"    Status: {_fmt(r.status_code, 200)}")
        data = r.json()
        if r.status_code != 200:
            print(f"    Error detail: {data.get('detail')}")
            failed += 1
        else:
            token   = data.get("session_token")
            profile = data.get("profile")
            assert data.get("ok"), "ok=false in response"
            assert token,          "Missing session_token"
            assert len(token) == 64, f"Token length unexpected: {len(token)} (want 64 hex chars)"
            assert data.get("expires_in") == 86400, "Wrong expires_in"
            print(f"    ok: {data.get('ok')} ✅")
            print(f"    session_token: {token[:12]}…{token[-4:]}")
            print(f"    expires_in: {data.get('expires_in')}s")
            print(f"    profile: {profile}")
            passed += 1
    except Exception as e:
        print(f"    ❌ FAIL: {e}")
        traceback.print_exc()
        failed += 1

    # ── 7. GET /api/v1/auth/profile/{address} (valid token) ─────────────────────
    if token:
        print(f"\n[7] GET /api/v1/auth/profile/{{address}} (valid token)…")
        try:
            r = session.get(
                f"{base}/api/v1/auth/profile/{address}",
                headers={"Authorization": f"Bearer {token}"},
            )
            print(f"    Status: {_fmt(r.status_code, 200)}")
            data = r.json()
            if r.status_code == 200:
                wa = data.get("wallet_address", "")
                assert wa == address, f"Address mismatch: {wa}"
                print(f"    wallet_address: {wa[:8]}…{wa[-4:]} ✅")
                print(f"    last_seen: {data.get('last_seen')}")
                passed += 1
            else:
                print(f"    Error: {data}")
                failed += 1
        except Exception as e:
            print(f"    ❌ FAIL: {e}")
            failed += 1

    # ── 8. GET /api/v1/auth/profile without token (expect 401) ──────────────────
    print(f"\n[8] GET /api/v1/auth/profile (no token, expect 401)…")
    try:
        r = session.get(f"{base}/api/v1/auth/profile/{address}")
        print(f"    Status: {_fmt(r.status_code, 401)}")
        if r.status_code == 401:
            passed += 1
        else:
            print(f"    ⚠️  Body: {r.text[:100]}")
            failed += 1
    except Exception as e:
        print(f"    ❌ FAIL: {e}")
        failed += 1

    # ── 9. Replay nonce (expect 400) ────────────────────────────────────────────
    print(f"\n[9] Replay nonce (expect 400)…")
    try:
        payload = {"address": address, "nonce": nonce, "signature": sig_hex}
        r = session.post(f"{base}/api/v1/auth/wallet-signin", json=payload)
        print(f"    Status: {_fmt(r.status_code, 400)}")
        if r.status_code == 400:
            detail = r.json().get("detail", "")
            print(f"    Detail: {detail} ✅")
            passed += 1
        else:
            print(f"    ⚠️  Expected 400, got {r.status_code}")
            failed += 1
    except Exception as e:
        print(f"    ❌ FAIL: {e}")
        failed += 1

    # ── 10. Bad signature (expect 401) ───────────────────────────────────────────
    print(f"\n[10] Bad signature (expect 401 or 400)…")
    try:
        # Get fresh nonce (old one was invalidated)
        r2 = session.get(f"{base}/api/v1/auth/nonce/{address}")
        assert r2.status_code == 200, f"Nonce request failed: {r2.status_code}"
        data2 = r2.json()
        bad_payload = {
            "address": address,
            "nonce": data2["nonce"],
            "signature": "a" * 128,   # 64 bytes of fake signature in hex
        }
        r = session.post(f"{base}/api/v1/auth/wallet-signin", json=bad_payload)
        print(f"    Status: {_fmt(r.status_code)} (want 400 or 401)")
        if r.status_code in (400, 401):
            print(f"    ✅ Bad signature rejected: {r.json().get('detail')}")
            passed += 1
        else:
            print(f"    ⚠️  Unexpected {r.status_code}: {r.text[:100]}")
            failed += 1
    except Exception as e:
        print(f"    ❌ FAIL: {e}")
        failed += 1

    # ── 11. Stale token (expect 401) ─────────────────────────────────────────────
    print(f"\n[11] Stale/invalid token (expect 401)…")
    try:
        fake_token = "0" * 64
        r = session.get(
            f"{base}/api/v1/auth/profile/{address}",
            headers={"Authorization": f"Bearer {fake_token}"},
        )
        print(f"    Status: {_fmt(r.status_code, 401)}")
        if r.status_code == 401:
            passed += 1
        else:
            print(f"    ⚠️  Expected 401: {r.text[:100]}")
            failed += 1
    except Exception as e:
        print(f"    ❌ FAIL: {e}")
        failed += 1

    _print_summary(passed, failed)


def _print_summary(passed, failed):
    total = passed + failed
    print(f"\n{'='*60}")
    if failed == 0:
        print(f"✅  ALL {total} TESTS PASSED")
    else:
        print(f"❌  {failed}/{total} TESTS FAILED  ({passed} passed)")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CometCloud auth E2E test")
    parser.add_argument("--base", default="https://looloomi.ai", help="API base URL")
    args = parser.parse_args()
    run_tests(args.base)
