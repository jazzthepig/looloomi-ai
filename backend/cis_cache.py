"""
CIS Score Local Cache
=====================
Syncs CIS scores from CometCloud Railway API to local cache.
Freqtrade strategy reads from local cache instead of calling remote API.

Usage:
    python cis_cache.py          # Manual sync
    # Add to crontab for hourly sync:
    # 0 * * * * cd /path/to/backend && python cis_cache.py
"""

import json
import time
import os
import requests
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional, List

# === Configuration ===
# CometCloud Railway API
CIS_API = "https://web-production-0cdf76.up.railway.app/api/v1/cis/universe"

# Local cache path - store in project data directory
CACHE_DIR = Path(__file__).parent / "data" / "cis_cache"
CACHE_FILE = CACHE_DIR / "cis_scores.json"
CACHE_TTL = 3600  # 1 hour TTL

# Fallback: also support local development API
LOCAL_API = "http://localhost:8000/api/v1/cis/universe"


def sync_cis_scores(force: bool = False) -> Optional[dict]:
    """
    Sync CIS scores from CometCloud API to local cache.

    Args:
        force: If True, ignore cache and force fresh fetch

    Returns:
        dict: The cached data, or None if sync failed
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # Check if cache exists and is fresh
    if not force and CACHE_FILE.exists():
        try:
            data = json.loads(CACHE_FILE.read_text())
            cached_at = datetime.fromisoformat(data.get("_cached_at", "2000-01-01"))
            if datetime.utcnow() - cached_at < timedelta(seconds=CACHE_TTL):
                print(f"[CIS Cache] Using cached data (age: {(datetime.utcnow() - cached_at).seconds}s)")
                return data
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            print(f"[CIS Cache] Cache corrupted, re-syncing: {e}")

    # Try Railway API first, then local
    apis = [CIS_API, LOCAL_API]
    last_error = None

    for api_url in apis:
        try:
            print(f"[CIS Cache] Fetching from {api_url}...")
            resp = requests.get(api_url, timeout=30)

            if resp.ok:
                data = resp.json()
                data["_cached_at"] = datetime.utcnow().isoformat()
                data["_source"] = api_url

                # Save to cache
                CACHE_FILE.write_text(json.dumps(data, indent=2))
                universe = data.get("universe", [])
                print(f"[CIS Cache] Synced {len(universe)} assets from {api_url}")
                return data
            else:
                last_error = f"HTTP {resp.status_code}"
                print(f"[CIS Cache] {api_url} returned {resp.status_code}")

        except requests.exceptions.ConnectionError as e:
            last_error = "Connection failed"
            print(f"[CIS Cache] Cannot connect to {api_url}: {e}")
        except requests.exceptions.Timeout as e:
            last_error = "Timeout"
            print(f"[CIS Cache] Timeout fetching from {api_url}: {e}")
        except Exception as e:
            last_error = str(e)
            print(f"[CIS Cache] Error fetching from {api_url}: {e}")

    print(f"[CIS Cache] ALL APIs FAILED. Last error: {last_error}")
    return None


def get_cis_score(symbol: str) -> dict:
    """
    Get CIS score for a single asset (from local cache).

    Args:
        symbol: Asset symbol (e.g., "BTC", "ETH")

    Returns:
        dict: CIS data for the asset, or default values if not found
    """
    # Ensure cache exists
    if not CACHE_FILE.exists():
        sync_cis_scores()

    try:
        data = json.loads(CACHE_FILE.read_text())

        # Check if cache needs refresh
        cached_at = datetime.fromisoformat(data.get("_cached_at", "2000-01-01"))
        if datetime.utcnow() - cached_at > timedelta(seconds=CACHE_TTL):
            sync_cis_scores()
            data = json.loads(CACHE_FILE.read_text())

        # Find the asset
        clean_symbol = symbol.upper().replace("/USDT", "").replace("USDT", "")
        for asset in data.get("universe", []):
            if asset.get("symbol", "").upper() == clean_symbol:
                return asset

    except Exception as e:
        print(f"[CIS Cache] Read error: {e}")

    # Default return if not found
    return {
        "symbol": symbol.upper(),
        "cis_score": 0,
        "grade": "N/A",
        "signal": "NEUTRAL",
        "confidence": 0,
        "data_completeness": 0,
    }


def get_all_scores() -> List[dict]:
    """
    Get all CIS scores from local cache.

    Returns:
        list: List of all CIS assets
    """
    if not CACHE_FILE.exists():
        sync_cis_scores()

    try:
        data = json.loads(CACHE_FILE.read_text())
        return data.get("universe", [])
    except Exception as e:
        print(f"[CIS Cache] Read error: {e}")
        return []


def get_cache_status() -> dict:
    """
    Get cache status information.

    Returns:
        dict: Cache metadata (age, count, source)
    """
    if not CACHE_FILE.exists():
        return {
            "cached": False,
            "age_seconds": None,
            "asset_count": 0,
            "source": None,
        }

    try:
        data = json.loads(CACHE_FILE.read_text())
        cached_at = datetime.fromisoformat(data.get("_cached_at", "2000-01-01"))
        age = (datetime.utcnow() - cached_at).seconds

        return {
            "cached": True,
            "age_seconds": age,
            "age_human": f"{age // 3600}h {(age % 3600) // 60}m",
            "asset_count": len(data.get("universe", [])),
            "source": data.get("_source", "unknown"),
        }
    except Exception as e:
        return {
            "cached": False,
            "error": str(e),
        }


# === CLI ===
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="CIS Score Cache Manager")
    parser.add_argument("--force", "-f", action="store_true", help="Force fresh sync")
    parser.add_argument("--status", "-s", action="store_true", help="Show cache status")
    parser.add_argument("--watch", "-w", action="store_true", help="Watch mode (continuous sync)")
    args = parser.parse_args()

    if args.status:
        status = get_cache_status()
        print("\n=== CIS Cache Status ===")
        if status.get("cached"):
            print(f"  Cached: Yes")
            print(f"  Age: {status.get('age_human', 'unknown')}")
            print(f"  Assets: {status.get('asset_count', 0)}")
            print(f"  Source: {status.get('source', 'unknown')}")
        else:
            print(f"  Cached: No ({status.get('error', 'unknown error')})")
        print()

    elif args.watch:
        print("=== CIS Cache Watch Mode (Ctrl+C to exit) ===")
        try:
            while True:
                status = sync_cis_scores(force=True)
                if status:
                    universe = status.get("universe", [])
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] Synced {len(universe)} assets")
                time.sleep(300)  # Sync every 5 minutes in watch mode
        except KeyboardInterrupt:
            print("\nExiting...")

    else:
        # Default: sync once
        print("=== CIS Cache Sync ===")
        data = sync_cis_scores(force=args.force)

        if data:
            universe = data.get("universe", [])
            print(f"\nSynced {len(universe)} assets")

            # Show sample data
            print("\nSample assets:")
            for asset in universe[:5]:
                print(f"  {asset.get('symbol'):<8} CIS: {asset.get('cis_score'):>3}  "
                      f"Grade: {asset.get('grade'):<3}  Signal: {asset.get('signal')}")

            # Test get_cis_score
            print("\nTest get_cis_score('BTC'):")
            btc = get_cis_score("BTC")
            print(f"  {btc}")
        else:
            print("Sync failed!")
