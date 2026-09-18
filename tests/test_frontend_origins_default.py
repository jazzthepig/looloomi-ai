"""Regression guard: every host we ship the dashboard on must be in the
FRONTEND_ORIGINS default, or dashboard users hit the anon rate-limit bucket.

2026-09-18 incident: web-production-0cdf76.up.railway.app was missing from
the default. Users opening the dashboard directly on the Railway auto-URL
sent a Referer that did not match FRONTEND_ORIGINS, fell through to anon
(120 rpm / 2000 rpd), and the first burst on the CIS page (six components
each fetching /api/v1/cis/universe) tripped 429. Asset Radar then showed
"Data unavailable" because the same endpoint was already rate-limited.

If you add a new production host (or rename the Railway project), add the
origin here too — and update this test. The test rides on the literal
default value in the source, so any edit will trip it.

Run: python3 -m pytest tests/test_frontend_origins_default.py
"""
from __future__ import annotations

import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
RL_PATH = ROOT / "src" / "api" / "middleware" / "rate_limit.py"


def _read_rate_limit() -> str:
    assert RL_PATH.exists(), f"rate_limit.py missing at {RL_PATH}"
    return RL_PATH.read_text(encoding="utf-8")


def _extract_default_origins() -> str:
    """Pull the literal default string out of the FRONTEND_ORIGINS os.getenv call.

    We DO NOT exec the module (it pulls httpx + Starlette at import time, which
    this test environment may not have configured). Regex against the source is
    what we want — the test pins the literal that ships.

    The default may be one literal or split across adjacent string concatenations
    ("foo," "bar") — Python's automatic literal concat. Handle both.
    """
    text = _read_rate_limit()
    # Find the os.getenv("FRONTEND_ORIGINS", ...) call and capture everything
    # from the opening `"` of the default literal up to the matching closing
    # `)` of os.getenv.
    m = re.search(
        r'os\.getenv\(\s*"FRONTEND_ORIGINS"\s*,\s*(.+?)\s*\)\.split',
        text,
        re.DOTALL,
    )
    assert m, (
        "could not find os.getenv(\"FRONTEND_ORIGINS\", ...) call in "
        f"{RL_PATH} — the source shape changed; update this test"
    )
    # Pull every "..." literal out of the captured region and concat them.
    literals = re.findall(r'"([^"]*)"', m.group(1))
    assert literals, (
        f"no string literals found inside FRONTEND_ORIGINS default block: "
        f"{m.group(1)!r}"
    )
    return "".join(literals)


def test_railway_auto_url_is_in_default():
    """The 2026-09-18 regression. If this trips, the dashboard on the Railway
    auto-URL will hit the anon bucket (120 rpm / 2000 rpd) instead of the
    dashboard bucket (600 rpm / ∞)."""
    default = _extract_default_origins()
    assert "web-production-0cdf76.up.railway.app" in default, (
        "Railway auto-URL missing from FRONTEND_ORIGINS default — the "
        "dashboard at that host will fall through to the anon bucket and "
        "trip 429 on the CIS page (six-component fetch burst). See "
        "2026-09-18 commit for the fix."
    )


def test_production_domains_are_in_default():
    """The two production domains must be present, otherwise the dashboard
    on those hosts also falls through."""
    default = _extract_default_origins()
    for host in ("https://looloomi.ai", "https://looloomi.com"):
        assert host in default, (
            f"{host} missing from FRONTEND_ORIGINS default — production "
            f"dashboard users would hit anon bucket limits."
        )


def test_local_dev_origins_are_in_default():
    """Local Vite (5173) + local FastAPI (8000) for dev work — both must be
    present so local dev never trips the anon bucket."""
    default = _extract_default_origins()
    for host in ("http://localhost:5173", "http://localhost:8000"):
        assert host in default, (
            f"{host} missing from FRONTEND_ORIGINS default — local dev "
            f"would hit anon bucket limits."
        )
