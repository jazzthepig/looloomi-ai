"""No Supabase service-role / secret key in the tree, in a pushed commit, or in a public response (2026-10-20).

Two leaks the same day: a lane pushed the service_role JWT (split across three string literals) to a branch
of this public repo, and GET /api/v1/auth/config had been returning SUPABASE_KEY — service_role on Railway —
as "supabase_anon_key" since 2026-03-26. The scanner is scripts/secret_scan.py; the pre-push hook runs it.
"""
from __future__ import annotations

import asyncio
import base64
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

import secret_scan as ss  # noqa: E402


def _jwt(body: dict) -> str:
    enc = lambda b: base64.urlsafe_b64encode(b).decode().rstrip("=")  # noqa: E731
    return enc(b'{"alg":"HS256","typ":"JWT"}') + "." + enc(json.dumps(body, separators=(",", ":")).encode()) + "." + "Q" * 43


def test_tracked_tree_has_no_keys():
    hits = ss.scan_tree()
    assert hits == [], "key material in tracked files:\n" + "\n".join(hits)


def test_catches_service_role_jwt_whole_and_split_across_literals():
    tok = _jwt({"iss": "supabase", "ref": "abcdefghijklmnopqrst", "role": "service_role", "iat": 1773733365})
    assert ss.scan_text(f'KEY = "{tok}"')
    for a, b in ((20, 60), (37, 101), (55, 140)):
        split = f'KEY = (\n    "{tok[:a]}"\n    "{tok[a:b]}"\n    "{tok[b:]}"\n)'
        assert ss.scan_text(split), (a, b)
    assert ss.scan_text(f'k = "{tok[:50]}" + "{tok[50:]}"')


def test_catches_new_style_secret_and_personal_tokens():
    assert ss.scan_text("SUPABASE_KEY=" + "sb_" + "secret_" + "a1B2c3D4e5F6g7H8")
    assert ss.scan_text("token " + "sb" + "p_" + "0123456789abcdef" * 2 + "01234567")


def test_anon_jwt_and_ordinary_text_pass():
    assert ss.scan_text(f'ANON="{_jwt({"iss": "supabase", "ref": "abc", "role": "anon"})}"') == []
    assert ss.scan_text("service_role bypasses RLS; read SUPABASE_KEY from the environment") == []


def test_auth_config_returns_no_supabase_key(monkeypatch):
    from src.api.routers import auth
    sentinel = _jwt({"role": "service_role", "ref": "sentinel"})
    monkeypatch.setattr(auth, "_SB_KEY", sentinel)
    body = json.dumps(asyncio.run(auth.get_auth_config()))
    assert sentinel not in body
    assert "key" not in json.loads(body) and "supabase_anon_key" not in body


def test_pre_push_hook_runs_the_scan_on_every_pushed_commit():
    hook = (ROOT / "scripts" / "githooks" / "pre-push").read_text(encoding="utf-8")
    assert "secret_scan.py\" --rev \"$local_sha\"" in hook
