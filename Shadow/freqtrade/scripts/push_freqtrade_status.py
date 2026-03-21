#!/usr/bin/env python3
"""
Freqtrade Status Pusher — Mac Mini → Railway
=============================================
Polls Freqtrade REST API (port 18432) every 30 seconds and pushes
status to Railway for the QuantMonitor dashboard.

Usage:
    python push_freqtrade_status.py              # Run once
    python push_freqtrade_status.py --continuous  # Daemon mode

Cron (recommended):
    */5 * * * * /Volumes/CometCloudAI/freqtrade/.venv/bin/python /Volumes/CometCloudAI/freqtrade/scripts/push_freqtrade_status.py
"""

import json
import os
import sys
import argparse
import time
from datetime import datetime

# Try to import requests, install if missing
try:
    import requests
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "requests", "-q"])
    import requests

# ── Config ────────────────────────────────────────────────────────────────────

FREQUTRADE_API = "http://127.0.0.1:18432"
API_USER = "jazz"
API_PASS = "cu5nK5nLRsoN99B0oZ0lfg"

RAILWAY_URL = os.environ.get("RAILWAY_URL", "https://web-production-0cdf76.up.railway.app")
INTERNAL_TOKEN = os.environ.get("INTERNAL_TOKEN", "")
POLL_INTERVAL = 30  # seconds


def get_access_token() -> str | None:
    """Authenticate with Freqtrade API and get access token."""
    try:
        resp = requests.post(
            f"{FREQUTRADE_API}/api/v1/token/login",
            auth=(API_USER, API_PASS),
            timeout=10,
        )
        if resp.ok:
            return resp.json().get("access_token")
    except Exception as e:
        print(f"[QUANT-PUSH] Auth failed: {e}")
    return None


def fetch_status(token: str) -> dict:
    """Fetch current open trades, balance, and daily P&L."""
    headers = {"Authorization": f"Bearer {token}"}

    # Fetch status (open trades)
    try:
        status_resp = requests.get(
            f"{FREQUTRADE_API}/api/v1/status",
            headers=headers,
            timeout=10,
        )
        open_trades = status_resp.json() if status_resp.ok else []
    except Exception:
        open_trades = []

    # Fetch balance
    try:
        balance_resp = requests.get(
            f"{FREQUTRADE_API}/api/v1/balance",
            headers=headers,
            timeout=10,
        )
        balance_data = balance_resp.json() if balance_resp.ok else {}
    except Exception:
        balance_data = {}

    # Fetch profit (daily P&L)
    try:
        profit_resp = requests.get(
            f"{FREQUTRADE_API}/api/v1/profit",
            headers=headers,
            timeout=10,
        )
        profit_data = profit_resp.json() if profit_resp.ok else {}
    except Exception:
        profit_data = {}

    # Extract key fields
    total_balance = balance_data.get("total", 0)
    starting_balance = balance_data.get("starting_balance", 10000)
    daily_pnl = profit_data.get("profit_all_percent", 0)

    # Format open trades for dashboard
    trades = []
    for t in open_trades:
        trades.append({
            "trade_id": t.get("trade_id"),
            "pair": t.get("pair"),
            "amount": t.get("amount"),
            "is_open": t.get("is_open", True),
            "entry_price": t.get("open_rate"),
            "current_price": t.get("current_rate"),
            "pnl_abs": t.get("profit_abs"),
            "pnl_pct": t.get("profit_ratio"),
            "open_timestamp": t.get("open_date"),
        })

    return {
        "open_trades": trades,
        "balance": {
            "total": total_balance,
            "starting": starting_balance,
            "equity": total_balance,
        },
        "daily_pnl": round(daily_pnl, 4) if isinstance(daily_pnl, float) else daily_pnl,
    }


def fetch_trades(token: str, limit: int = 20) -> list:
    """Fetch recent closed trades."""
    headers = {"Authorization": f"Bearer {token}"}
    try:
        resp = requests.get(
            f"{FREQUTRADE_API}/api/v1/trades",
            headers=headers,
            params={"limit": limit},
            timeout=10,
        )
        if resp.ok:
            return resp.json()[:limit]
    except Exception:
        pass
    return []


def push_to_railway(data: dict, trades: list, equity: dict) -> bool:
    """Push status to Railway."""
    endpoint = f"{RAILWAY_URL}/internal/quant-push"
    headers = {"Content-Type": "application/json", "X-Internal-Token": INTERNAL_TOKEN}

    payload = {
        "status": data,
        "trades": trades,
        "equity": equity,
    }

    try:
        resp = requests.post(endpoint, json=payload, headers=headers, timeout=15)
        if resp.ok:
            print(f"[QUANT-PUSH] Pushed OK — trades={len(trades)}")
            return True
        else:
            print(f"[QUANT-PUSH] Push failed: HTTP {resp.status_code}")
    except Exception as e:
        print(f"[QUANT-PUSH] Push error: {e}")
    return False


def run_once():
    """Single push, then exit. For cron."""
    token = get_access_token()
    if not token:
        print("[QUANT-PUSH] No token — Freqtrade may not be running")
        sys.exit(1)

    status = fetch_status(token)
    trades = fetch_trades(token)
    equity = status.get("balance", {})

    push_to_railway(status, trades, equity)


def run_continuous():
    """Daemon mode — poll every POLL_INTERVAL seconds."""
    print(f"[QUANT-PUSH] Continuous mode — polling every {POLL_INTERVAL}s")
    print(f"[QUANT-PUSH] Railway: {RAILWAY_URL}")
    print(f"[QUANT-PUSH] Token set: {'yes' if INTERNAL_TOKEN else 'NO — check INTERNAL_TOKEN env'}")

    while True:
        try:
            run_once()
        except Exception as e:
            print(f"[QUANT-PUSH] Loop error: {e}")
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Push Freqtrade status to Railway")
    parser.add_argument("--continuous", action="store_true", help="Run continuously")
    parser.add_argument("--interval", type=int, default=POLL_INTERVAL, help=f"Poll interval (default {POLL_INTERVAL}s)")
    args = parser.parse_args()

    if args.interval != POLL_INTERVAL:
        global POLL_INTERVAL
        POLL_INTERVAL = args.interval

    if args.continuous:
        run_continuous()
    else:
        run_once()
