"""
CIS Cache Writer — writes local CIS engine scores to a JSON file
for Freqtrade's CometCloudStrategy to read.

Reads from cis_scheduler's output and writes to the expected cache path.

Usage:
    python scripts/write_cis_cache.py
"""
import json, os, sys, time
from pathlib import Path

# Paths — adjust to Mac Mini layout
SCRIPT_DIR = Path(__file__).resolve().parent
FT_DIR = SCRIPT_DIR.parent
CIS_CACHE_DIR = FT_DIR / "cis_cache"
CIS_CACHE_FILE = CIS_CACHE_DIR / "cis_scores.json"

# Local engine data dir
LOCAL_ENGINE_DIR = Path("/Volumes/CometCloudAI/cometcloud-local")


def get_latest_scores():
    """Read latest CIS scores from local scheduler's output."""
    scheduler_output = LOCAL_ENGINE_DIR / "_data" / "cis_scores_latest.json"
    if scheduler_output.exists():
        try:
            data = json.loads(scheduler_output.read_text())
            # Scheduler writes "scores" as the key
            if data.get("scores"):
                return data
        except Exception as e:
            print(f"[CIS-CACHE] Scheduler output read failed: {e}")

    return None


def write_cache(data: dict):
    """Write CIS scores to cache file for Freqtrade."""
    CIS_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # Scheduler writes "scores" — normalize to "universe" list for CometCloudStrategy compat
    scores_list = data.get("scores", [])

    # Transform to the format CometCloudStrategy expects (list of assets)
    universe = []
    for asset in scores_list:
        sym = asset.get("asset", asset.get("symbol", "")).upper()
        if not sym:
            continue
        raw_score = asset.get("cis_score") or asset.get("score", 0)
        universe.append({
            "symbol": sym,
            "name": asset.get("asset_name", asset.get("name", sym)),
            "cis_score": raw_score,
            "grade": asset.get("grade", "N/A"),
            "signal": asset.get("signal", "NEUTRAL"),
            "percentile_rank": asset.get("percentile", asset.get("percentile_rank")),
            "asset_class": asset.get("asset_class", ""),
            "pillars": asset.get("pillars", {}),
            "updated": data.get("timestamp", ""),
        })

    payload = {
        "universe": universe,
        "count": len(universe),
        "timestamp": data.get("timestamp", ""),
        "source": data.get("source", "local_engine"),
    }

    # Write to Freqtrade CIS cache (CometCloudStrategy reads from here)
    CIS_CACHE_FILE.write_text(json.dumps(payload, indent=2))
    print(f"[CIS-CACHE] Wrote {len(universe)} scores to {CIS_CACHE_FILE}")

    # Also write to backend path (legacy CometCloudStrategy expected path)
    backend_cache_dir = Path("/Volumes/CometCloudAI/backend/data/cis_cache")
    backend_cache_dir.mkdir(parents=True, exist_ok=True)
    backend_cache_file = backend_cache_dir / "cis_scores.json"
    backend_cache_file.write_text(json.dumps(payload, indent=2))
    print(f"[CIS-CACHE] Wrote {len(universe)} scores to {backend_cache_file}")
    return True


def main():
    data = get_latest_scores()
    if data:
        write_cache(data)
    else:
        print("[CIS-CACHE] No scores available to cache")


if __name__ == "__main__":
    main()
