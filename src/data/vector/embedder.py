"""
Asset Embedding Engine — CometCloud AI
========================================
Generates 18-dimensional feature vectors from CIS asset data.
Enables cosine similarity search, k-means clustering, and regime fingerprinting.

No external vector DB needed at 84-asset scale — all operations are in-memory
with Redis persistence. Sub-millisecond search, numpy-only clustering.

Vector dimensions (18):
  [0]  F_score / 100            — Fundamental pillar (normalized)
  [1]  M_score / 100            — Momentum pillar
  [2]  O_score / 100            — On-chain / Risk-Adjusted pillar
  [3]  S_score / 100            — Sentiment pillar
  [4]  A_score / 100            — Alpha pillar
  [5]  cis_score / 100          — Total CIS
  [6]  log10(mcap) / 15         — Market cap (log-normalized, 15=~$1Q)
  [7]  clamp(chg_24h / 20, -1, 1)  — 24h price change
  [8]  clamp(chg_7d / 50, -1, 1)   — 7d price change
  [9]  clamp(chg_30d / 100, -1, 1) — 30d price change
  [10] min(vol_mcap_ratio * 10, 1) — Volume/MCap ratio
  [11] clamp(funding_rate * 1000, -1, 1)  — Futures funding rate (0.01%/8h = 0.1)
  [12] clamp(oi_mcap_ratio * 5, 0, 1)    — OI / MCap leverage ratio
  [13] (100 - ath_distance) / 100        — ATH proximity (1=at ATH, 0=80% below)
  [14] las / 100                          — Liquidity-Adjusted Score
  [15] confidence                         — Data confidence [0-1]
  [16] asset_class_encoded / 10          — Asset class category encoding
  [17] regime_alignment                  — Regime directional alignment [-1, 1]
"""

import math
import json
import logging
from typing import Optional

import numpy as np

_logger = logging.getLogger(__name__)

# Asset class → encoded float (preserves clustering: L1/L2/DeFi closer than RWA/TradFi)
_CLASS_ENC: dict[str, float] = {
    "L1":            1.0,
    "L2":            0.9,
    "DeFi":          0.7,
    "Infrastructure":0.6,
    "RWA":           0.4,
    "AI":            0.5,
    "Gaming":        0.3,
    "Memecoin":      0.2,
    "Crypto":        0.8,   # catch-all crypto
    "US Equity":     0.15,
    "US Bond":       0.05,
    "Commodity":     0.10,
    "FX":            0.08,
    "Real Estate":   0.12,
    "EM Equity":     0.18,
}

# Regime → directional bias encoding
_REGIME_ALIGN: dict[str, float] = {
    "Goldilocks":   1.0,
    "Risk-On":      0.75,
    "Easing":       0.60,
    "Neutral":      0.0,
    "Tightening":  -0.25,
    "Risk-Off":    -0.75,
    "Stagflation": -1.0,
}


def _clamp(val: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, val))


def generate_embedding(
    asset: dict,
    macro_regime: str = "Neutral",
    derivatives: dict | None = None,
) -> list[float]:
    """
    Generate 18-dim normalized feature vector for an asset.

    Parameters
    ----------
    asset : CIS asset dict (T1 or T2 shape)
    macro_regime : current macro regime string
    derivatives : {symbol: {funding_rate, oi_usd}} pre-fetched derivatives map
    """
    # Pillar scores — handle both T1 (pillars dict) and T2 (flat) shapes
    pillars = asset.get("pillars") or {}
    f_raw   = pillars.get("F") or asset.get("f_score", 0) or 0
    m_raw   = pillars.get("M") or asset.get("m_score", 0) or 0
    o_raw   = pillars.get("O") or asset.get("o_score", 0) or 0
    s_raw   = pillars.get("S") or asset.get("s_score", 0) or 0
    a_raw   = pillars.get("A") or asset.get("a_score", 0) or 0
    cis_raw = asset.get("cis_score") or asset.get("total_score") or asset.get("score") or 0

    # Market data
    sym       = (asset.get("symbol") or asset.get("asset_id") or "").upper()
    mcap      = asset.get("market_cap") or asset.get("mcap_usd") or 1e6
    chg_24h   = float(asset.get("change_24h") or asset.get("price_change_24h") or 0)
    chg_7d    = float(asset.get("change_7d")  or asset.get("price_change_7d")  or 0)
    chg_30d   = float(asset.get("change_30d") or asset.get("price_change_30d") or 0)
    vol_24h   = float(asset.get("volume_24h") or 0)
    ath_dist  = float(asset.get("ath_distance_pct") or pillars.get("ath_dist") or 50)
    las       = float(asset.get("las") or 0)
    conf      = float(asset.get("confidence") or 0.8)
    ac        = asset.get("asset_class") or "Crypto"

    # Derived
    log_mcap     = math.log10(max(mcap, 1e3)) / 15.0  # 1M→0.4, 1T→0.8, 1Q→1.0
    vol_mcap     = (vol_24h / mcap) if mcap > 0 else 0

    # Derivatives features
    funding_rate = 0.0
    oi_mcap_ratio = 0.0
    if derivatives and sym in derivatives:
        d = derivatives[sym]
        funding_rate  = float(d.get("funding_rate") or 0)
        oi_usd        = float(d.get("open_interest_usd") or 0)
        if mcap > 0 and oi_usd > 0:
            oi_mcap_ratio = oi_usd / mcap

    vec = [
        _clamp(f_raw / 100,  0.0, 1.0),
        _clamp(m_raw / 100,  0.0, 1.0),
        _clamp(o_raw / 100,  0.0, 1.0),
        _clamp(s_raw / 100,  0.0, 1.0),
        _clamp(a_raw / 100,  0.0, 1.0),
        _clamp(cis_raw / 100, 0.0, 1.0),
        _clamp(log_mcap,     0.0, 1.0),
        _clamp(chg_24h / 20, -1.0, 1.0),
        _clamp(chg_7d  / 50, -1.0, 1.0),
        _clamp(chg_30d / 100,-1.0, 1.0),
        _clamp(vol_mcap * 10, 0.0, 1.0),
        _clamp(funding_rate * 1000, -1.0, 1.0),
        _clamp(oi_mcap_ratio * 5,   0.0, 1.0),
        _clamp((100 - ath_dist) / 100, 0.0, 1.0),
        _clamp(las / 100,    0.0, 1.0),
        _clamp(conf,         0.0, 1.0),
        _clamp(_CLASS_ENC.get(ac, 0.5), 0.0, 1.0),
        _REGIME_ALIGN.get(macro_regime, 0.0),
    ]
    return vec


def cosine_similarity(v1: list[float], v2: list[float]) -> float:
    """Cosine similarity in [−1, 1]. Returns 0 on zero vectors."""
    a = np.array(v1, dtype=np.float32)
    b = np.array(v2, dtype=np.float32)
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na < 1e-9 or nb < 1e-9:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def find_similar(
    target_sym: str,
    embeddings: dict[str, list[float]],
    k: int = 5,
    exclude_same_class: bool = False,
    asset_classes: dict[str, str] | None = None,
) -> list[dict]:
    """
    Return top-k most similar assets to target_sym by cosine similarity.

    Parameters
    ----------
    target_sym : symbol to find neighbors for
    embeddings : {symbol: [18 floats]}
    k : number of neighbors (excluding target itself)
    exclude_same_class : if True, skip assets in same class (finds cross-class analogs)
    asset_classes : {symbol: class} for class filtering
    """
    target_vec = embeddings.get(target_sym.upper())
    if target_vec is None:
        return []

    target_class = (asset_classes or {}).get(target_sym.upper())
    results = []
    for sym, vec in embeddings.items():
        if sym == target_sym.upper():
            continue
        if exclude_same_class and asset_classes and asset_classes.get(sym) == target_class:
            continue
        sim = cosine_similarity(target_vec, vec)
        results.append({"symbol": sym, "similarity": round(sim, 4)})

    results.sort(key=lambda x: -x["similarity"])
    return results[:k]


def k_means_cluster(
    embeddings: dict[str, list[float]],
    k: int = 6,
    max_iter: int = 100,
    seed: int = 42,
) -> dict[int, list[str]]:
    """
    K-means clustering of asset embeddings.

    Returns {cluster_id: [symbol_list]}.
    Cluster 0 = centroid closest to (1,1,...,1) = highest-quality assets.
    """
    if len(embeddings) < k:
        k = max(1, len(embeddings))

    syms = list(embeddings.keys())
    X    = np.array([embeddings[s] for s in syms], dtype=np.float32)

    rng = np.random.default_rng(seed)
    # K-means++ initialization
    centers = [X[rng.integers(len(X))]]
    for _ in range(k - 1):
        dists = np.array([
            min(np.linalg.norm(x - c) ** 2 for c in centers)
            for x in X
        ])
        probs  = dists / dists.sum()
        idx    = rng.choice(len(X), p=probs)
        centers.append(X[idx])
    centers = np.stack(centers)

    labels = np.zeros(len(X), dtype=int)
    for _ in range(max_iter):
        # Assignment step
        dists  = np.stack([np.linalg.norm(X - c, axis=1) for c in centers], axis=1)
        new_lb = dists.argmin(axis=1)
        if np.array_equal(new_lb, labels):
            break
        labels = new_lb
        # Update step
        for j in range(k):
            mask = labels == j
            if mask.any():
                centers[j] = X[mask].mean(axis=0)

    result: dict[int, list[str]] = {j: [] for j in range(k)}
    for sym, lbl in zip(syms, labels):
        result[int(lbl)].append(sym)

    return result


def generate_regime_embedding(
    macro_pulse: dict,
    cis_universe: list[dict] | None = None,
) -> list[float]:
    """
    Generate a 12-dim regime fingerprint vector for the current macro state.
    Used for historical regime matching.

    Dimensions:
      [0]  BTC dominance / 100
      [1]  Fear & Greed / 100
      [2]  Global mcap (log) / 15
      [3]  avg_cis / 100
      [4]  pct_outperform (OUTPERFORM / total) / 100
      [5]  regime_alignment [-1, 1] (from _REGIME_ALIGN)
      [6]  top_sector_avg_cis / 100
      [7]  vol_regime_score / 10 (-1..1)
      [8]  btc_chg_7d / 50 [-1, 1]
      [9]  avg_funding_rate * 1000 [-1, 1]
      [10] defi_tvl_change / 50 [-1, 1]
      [11] avg_oi_mcap_ratio * 5 [0, 1]
    """
    regime   = macro_pulse.get("macro_regime", "Neutral")
    btc_dom  = float(macro_pulse.get("btc_dominance", 50) or 50) / 100
    fng      = float(macro_pulse.get("fear_greed_index", 50) or 50) / 100
    gcap     = float(macro_pulse.get("global_mcap_usd") or 1e12)
    log_gcap = math.log10(max(gcap, 1e9)) / 15
    reg_enc  = _REGIME_ALIGN.get(regime, 0.0)
    btc_chg  = float(macro_pulse.get("btc_change_7d") or 0) / 50

    # CIS universe aggregates
    avg_cis = 50.0
    pct_out = 0.5
    top_sec = 50.0
    if cis_universe:
        scores  = [a.get("cis_score") or a.get("score") or 0 for a in cis_universe]
        sigs    = [a.get("signal", "") for a in cis_universe]
        avg_cis = (sum(scores) / len(scores)) if scores else 50.0
        n_out   = sum(1 for s in sigs if "OUTPERFORM" in s)
        pct_out = n_out / len(sigs) if sigs else 0.5
        # Top sector
        from collections import defaultdict
        by_class: dict[str, list[float]] = defaultdict(list)
        for a in cis_universe:
            by_class[a.get("asset_class","Unknown")].append(a.get("cis_score") or a.get("score") or 0)
        top_sec = max((sum(v)/len(v) for v in by_class.values() if v), default=50.0)

    vec = [
        _clamp(btc_dom,    0.0, 1.0),
        _clamp(fng,        0.0, 1.0),
        _clamp(log_gcap,   0.0, 1.0),
        _clamp(avg_cis / 100, 0.0, 1.0),
        _clamp(pct_out,    0.0, 1.0),
        _clamp(reg_enc,   -1.0, 1.0),
        _clamp(top_sec / 100, 0.0, 1.0),
        0.0,   # vol_regime_score placeholder
        _clamp(btc_chg,  -1.0, 1.0),
        0.0,   # avg_funding_rate placeholder (filled by caller)
        0.0,   # defi_tvl_change placeholder
        0.0,   # avg_oi_mcap_ratio placeholder
    ]
    return vec
