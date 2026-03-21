#!/usr/bin/env python3
"""
CIS Push Script
===============
Pushes local CIS scores to Railway backend.
Called after local cis_scheduler completes scoring.

Usage:
    python cis_push.py                    # Push latest scores
    python cis_push.py --url RAILWAY_URL  # Push to specific URL
    python cis_push.py --dry-run          # Show data without pushing

Output:
    cis_scores_latest.json → POST to Railway /internal/cis-scores
"""

import json
import sys
import os
import argparse
from pathlib import Path
from datetime import datetime

# Try to import requests, install if missing
try:
    import requests
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "requests", "-q"])
    import requests


# Paths
LOCAL_DATA_DIR = Path("/Volumes/CometCloudAI/cometcloud-local/_data")
LATEST_SCORES_FILE = LOCAL_DATA_DIR / "cis_scores_latest.json"

# Railway URL from env or use default
RAILWAY_URL = os.environ.get("RAILWAY_URL", "https://web-production-0cdf76.up.railway.app")

# Internal token from env
INTERNAL_TOKEN = os.environ.get("INTERNAL_TOKEN", "")


def load_scores() -> dict:
    """Load latest CIS scores from local file."""
    if not LATEST_SCORES_FILE.exists():
        print(f"Error: Score file not found: {LATEST_SCORES_FILE}")
        return None

    with open(LATEST_SCORES_FILE, 'r') as f:
        data = json.load(f)

    return data


def push_to_railway(url: str, data: dict) -> bool:
    """POST scores to Railway backend."""
    endpoint = f"{url}/internal/cis-scores"

    # Extract and map scores to Railway format
    scores = data.get("scores", [])
    mapped_scores = []
    for s in scores:
        mapped = dict(s)
        # Map "asset" -> "symbol" for Railway compatibility
        if "asset" in mapped and "symbol" not in mapped:
            mapped["symbol"] = mapped.pop("asset")
        mapped_scores.append(mapped)

    # Convert timestamp to Unix epoch (Railway expects this for age calculation)
    ts = data.get("timestamp", "")
    if ts:
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            epoch = int(dt.timestamp())
        except:
            epoch = int(datetime.now().timestamp())
    else:
        epoch = int(datetime.now().timestamp())

    payload = {
        "universe": mapped_scores,
        "timestamp": epoch,
    }

    # Build headers with internal token
    headers = {"Content-Type": "application/json"}
    if INTERNAL_TOKEN:
        headers["X-Internal-Token"] = INTERNAL_TOKEN

    print(f"Pushing {len(payload['universe'])} scores to {endpoint}")

    try:
        response = requests.post(
            endpoint,
            json=payload,
            timeout=30,
            headers=headers
        )

        if response.status_code == 200:
            result = response.json()
            print(f"Success: {result}")
            return True
        else:
            print(f"Error: HTTP {response.status_code}")
            print(f"Response: {response.text}")
            return False

    except requests.exceptions.ConnectionError:
        print(f"Error: Could not connect to {url}")
        print("Make sure Railway backend is running or the URL is correct")
        return False
    except Exception as e:
        print(f"Error: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Push CIS scores to Railway")
    parser.add_argument(
        "--url",
        default=RAILWAY_URL,
        help=f"Railway backend URL (default: {RAILWAY_URL})"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Load and show data without pushing"
    )
    args = parser.parse_args()

    print("=" * 60)
    print("CIS Push Script")
    print("=" * 60)

    # Load scores
    data = load_scores()
    if not data:
        sys.exit(1)

    scores = data.get("scores", [])
    print(f"Loaded {len(scores)} scores from {LATEST_SCORES_FILE}")

    if args.dry_run:
        print("\n[Dry run - showing first 3 assets]")
        for asset in scores[:3]:
            print(f"  {asset.get('symbol', asset.get('asset', '?'))}: {asset.get('cis_score', 'N/A')}")
        sys.exit(0)

    # Push to Railway
    success = push_to_railway(args.url, data)

    if success:
        print("\n✓ Push completed successfully")
    else:
        print("\n✗ Push failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
