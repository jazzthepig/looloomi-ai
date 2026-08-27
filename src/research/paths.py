"""
Centralised path resolution for Seth-lane research code.

Mac-side paths (CLAUDE.md rule #3 — Minimax lane owns
``/Volumes/CometCloudAI/cometcloud-local/``, Seth-lane reads it).
Defaults preserve current behaviour so existing scripts keep working;
overriding via env is the intended migration path.

Environment variables (all optional):

  COMETCLOUD_OHLCV_DIR          default: ``/Volumes/CometCloudAI/data/ohlcv``
  COMETCLOUD_MAC_ROOT           default: ``/Volumes/CometCloudAI/cometcloud-local``
  COMETCLOUD_MAC_REPORTS        default: ``<MAC_ROOT>/_reports``
  COMETCLOUD_MAC_DATA           default: ``<MAC_ROOT>/_data``
  COMETCLOUD_MAC_ENV            default: ``<MAC_ROOT>/.env``
  COMETCLOUD_BACKTEST_DIR       default: ``<MAC_REPORTS>/backtest``
  COMETCLOUD_SLEEVE_A_OUT_DIR   default: ``<MAC_REPORTS>/nautilus/sleeve_a``
  COMETCLOUD_SLEEVE_A_DATA_DIR  default: ``<MAC_ROOT>/user_data/data/binance/futures``

Why this exists (P0-5, 2026-08-27):
  Audit found 8 hardcoded ``/Volumes/CometCloudAI/...`` literals spread across
  7 Seth-lane files. Two were duplicated (``OHLCV_DIR`` in 2 files, ``_MAC_ENV``
  in 2 files). Drift risk + mount-point fragility if Minimax relocates the
  volume. One-shot refactor consolidates to one source of truth.

Lane discipline:
  These are READ paths into Minimax's lane. Never write here from Seth code.
  For writes that belong to the research book (paper ledger, reports), the
  contract lives in ``MINIMAX_SYNC.md`` §IN-FLIGHT and writes go through the
  agreed handoff (e.g. ``_reports/absorb_input/``).
"""
from __future__ import annotations

import os
from pathlib import Path

_MAC_DEFAULT_ROOT = "/Volumes/CometCloudAI"


def _from_env(var: str, default: Path) -> Path:
    """Resolve a Path from env, falling back to ``default``.

    Empty string is treated as "not set" (mirrors common docker-compose
    patterns where an empty ``VAR=`` is used to disable a config).
    """
    raw = os.getenv(var)
    return Path(raw) if raw else default


# ── OHLCV parquet (Seth-lane reads; Mac-side ohlcv_collector writes) ─────────
OHLCV_DIR: Path = _from_env(
    "COMETCLOUD_OHLCV_DIR",
    Path(_MAC_DEFAULT_ROOT) / "data" / "ohlcv",
)

# ── Mac-side cometcloud-local/ (Minimax lane; Seth reads via env) ─────────────
MAC_ROOT: Path = _from_env(
    "COMETCLOUD_MAC_ROOT",
    Path(_MAC_DEFAULT_ROOT) / "cometcloud-local",
)

MAC_REPORTS: Path = _from_env(
    "COMETCLOUD_MAC_REPORTS",
    MAC_ROOT / "_reports",
)

MAC_DATA: Path = _from_env(
    "COMETCLOUD_MAC_DATA",
    MAC_ROOT / "_data",
)

MAC_ENV: Path = _from_env(
    "COMETCLOUD_MAC_ENV",
    MAC_ROOT / ".env",
)

BACKTEST_DIR: Path = _from_env(
    "COMETCLOUD_BACKTEST_DIR",
    MAC_REPORTS / "backtest",
)

# ── Sleeve A (nautilus) write/output surface ─────────────────────────────────
SLEEVE_A_OUT_DIR: Path = _from_env(
    "COMETCLOUD_SLEEVE_A_OUT_DIR",
    MAC_REPORTS / "nautilus" / "sleeve_a",
)

SLEEVE_A_DATA_DIR: Path = _from_env(
    "COMETCLOUD_SLEEVE_A_DATA_DIR",
    MAC_ROOT / "user_data" / "data" / "binance" / "futures",
)


__all__ = [
    "OHLCV_DIR",
    "MAC_ROOT",
    "MAC_REPORTS",
    "MAC_DATA",
    "MAC_ENV",
    "BACKTEST_DIR",
    "SLEEVE_A_OUT_DIR",
    "SLEEVE_A_DATA_DIR",
]
