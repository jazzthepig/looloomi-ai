"""
Factor Performance Tracker — CometCloud AI
============================================
Persists and aggregates factor-level Pearson correlations vs realized returns
from paper trade mining. Updates after each mine run.

Redis key: cis:factor_performance
Schema: {
  factor_id: {
    pillar: str,
    pearson_r: float,
    sample_size: int,
    last_updated: float (unix ts),
    rolling_7d: [float, ...],      # last 7 daily readings (newest last)
    status: "active" | "probationary" | "candidate_removal",
  },
  _meta: {
    last_run: float,
    periods_computed: int,
    total_trades_analysed: int,
  }
}

Selection thresholds (§F-SEL rule 2):
  |r| > 0.10               → factor retained (active)
  0.05 < |r| ≤ 0.10        → probationary (3 consecutive periods → candidate_removal)
  |r| ≤ 0.05               → candidate for removal (flag in next weekly review)
"""

import json
import math
import time
import logging
from typing import Optional

_logger = logging.getLogger(__name__)

_KEY     = "cis:factor_performance"
_TTL     = 7 * 86_400  # 7 days — roll-up persists across restarts

# Thresholds from §F-SEL rule 2
_THRESHOLD_ACTIVE   = 0.10
_THRESHOLD_PROB     = 0.05

# Pillar factor ID → component key mapping (matches cis_provider breakdown dict)
_PILLAR_COMPONENT_MAP: dict[str, str] = {
    "market_cap":           "f",
    "tvl":                  "f",
    "volume_24h":           "f",
    "supply_inflation":     "f",
    "fdv_ratio":            "f",
    "dev_activity":         "f",
    "eodhd_pe":             "f",
    "eodhd_revenue_growth": "f",
    "momentum_30d":         "m",
    "momentum_7d_sparkline":"m",
    "ath_distance":         "m",
    "volatility_annualised":"o",
    "ath_drawdown":         "o",
    "tvl_risk_score":       "o",
    "exchange_hhi":         "o",
    "funding_rate":         "o",
    "oi_mcap_ratio":        "o",
    "fear_greed_index":     "s",
    "vix_inverse":          "s",
    "category_divergence":  "s",
    "vol_regime":           "s",
    "momentum_structure":   "s",
    "beta_dxy_vix":         "s",
    "trending_rank":        "s",
    "recovery_bonus":       "s",
    "btc_divergence":       "a",
    "spy_divergence":       "a",
    "class_independence":   "a",
    "size_efficiency":      "a",
    "correlation_discount": "a",
}


def _redis_get(key: str) -> Optional[str]:
    import os, urllib.request
    url   = os.environ.get("UPSTASH_REDIS_REST_URL", "")
    token = os.environ.get("UPSTASH_REDIS_REST_TOKEN", "")
    if not url or not token:
        return None
    try:
        req = urllib.request.Request(
            f"{url}/get/{key}",
            headers={"Authorization": f"Bearer {token}"},
        )
        with urllib.request.urlopen(req, timeout=3) as r:
            return json.loads(r.read()).get("result")
    except Exception as e:
        _logger.debug(f"[FactorPerf] GET failed: {e}")
        return None


def _redis_set(key: str, value: str, ttl: int = _TTL) -> bool:
    import os, urllib.request
    url   = os.environ.get("UPSTASH_REDIS_REST_URL", "").rstrip("/")
    token = os.environ.get("UPSTASH_REDIS_REST_TOKEN", "")
    if not url or not token:
        return False
    try:
        # Upstash REST: POST /set/{key}?EX={ttl} with value as body
        # (pipeline format requires [["SET",...]] outer array — use simple REST to avoid that)
        req = urllib.request.Request(
            f"{url}/set/{key}?EX={ttl}",
            data=value.encode("utf-8"),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "text/plain"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            r.read()
        return True
    except Exception as e:
        _logger.warning(f"[FactorPerf] SET failed: {e}")
        return False


def load() -> dict:
    """Load current factor performance store from Redis."""
    raw = _redis_get(_KEY)
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return {}


def update_from_pillar_fitness(
    pillar_fitness: dict,
    trade_count: int,
) -> dict:
    """
    Update factor performance store from a pillar_fitness mine result.

    pillar_fitness structure (from trading.py /mine):
    {
      "F": {"correlation": 0.23, "sample_size": 42, ...},
      "M": {"correlation": 0.31, ...},
      ...
    }

    Since pillar_fitness returns pillar-level (not sub-factor-level) correlations,
    the performance is attributed equally to all factors within that pillar.
    Sub-factor correlations require T1 data (Mac Mini breakdown available).
    """
    store = load()
    now   = time.time()

    for pillar_key, result in pillar_fitness.items():
        if not isinstance(result, dict):
            continue
        r = float(result.get("correlation") or 0)
        n = int(result.get("sample_size") or 0)
        if n < 5:
            continue  # insufficient data

        # Determine status
        abs_r = abs(r)
        if abs_r > _THRESHOLD_ACTIVE:
            status = "active"
        elif abs_r > _THRESHOLD_PROB:
            status = "probationary"
        else:
            status = "candidate_removal"

        # Update all factors in this pillar
        for factor_id, fac_pillar in _PILLAR_COMPONENT_MAP.items():
            if fac_pillar != pillar_key.lower():
                continue
            entry = store.get(factor_id, {
                "pillar":        pillar_key,
                "pearson_r":     r,
                "sample_size":   n,
                "last_updated":  now,
                "rolling_7d":    [],
                "status":        status,
                "probationary_count": 0,
            })
            entry["pearson_r"]    = r
            entry["sample_size"]  = n
            entry["last_updated"] = now
            entry["status"]       = status

            # Rolling window: keep last 7 readings
            rolling = entry.get("rolling_7d", [])
            rolling.append(round(r, 4))
            entry["rolling_7d"] = rolling[-7:]

            # Probationary counter — 3 consecutive periods below threshold → candidate_removal
            if status == "probationary":
                entry["probationary_count"] = entry.get("probationary_count", 0) + 1
                if entry["probationary_count"] >= 3:
                    entry["status"] = "candidate_removal"
            else:
                entry["probationary_count"] = 0

            store[factor_id] = entry

    # Update meta
    store["_meta"] = {
        "last_run":               now,
        "periods_computed":       store.get("_meta", {}).get("periods_computed", 0) + 1,
        "total_trades_analysed":  trade_count,
    }

    _redis_set(_KEY, json.dumps(store))
    return store


def get_factor_health_report() -> dict:
    """
    Summary report for weekly strategy review.
    Returns factors by status with trend direction.
    """
    store = load()
    from src.data.factors.registry import FACTORS

    report = {
        "active":            [],
        "probationary":      [],
        "candidate_removal": [],
        "no_data":           [],
        "meta":              store.get("_meta", {}),
    }

    for fac in FACTORS:
        fid  = fac["id"]
        perf = store.get(fid)
        if not perf:
            report["no_data"].append({
                "id":    fid,
                "pillar": fac["pillar"],
                "reason": "No trade data yet",
            })
            continue

        rolling = perf.get("rolling_7d", [])
        trend   = (
            "improving" if len(rolling) >= 2 and rolling[-1] > rolling[-2] else
            "declining" if len(rolling) >= 2 and rolling[-1] < rolling[-2] else
            "stable"
        )
        entry = {
            "id":           fid,
            "pillar":       perf.get("pillar"),
            "pearson_r":    perf.get("pearson_r"),
            "sample_size":  perf.get("sample_size"),
            "trend":        trend,
            "rolling_7d":   rolling,
            "probationary_count": perf.get("probationary_count", 0),
        }
        report[perf.get("status", "no_data")].append(entry)

    return report
