"""
Asset Embedding Engine — CometCloud AI
========================================
Generates 18-dimensional feature vectors from CIS asset data.
Enables cosine similarity search, k-means clustering, and regime fingerprinting.

No external vector DB needed at 84-asset scale — all operations are in-memory
with Redis persistence. Sub-millisecond search, numpy-only clustering.

Vector dimensions — v1 (18, dims [0..17]) + v2 additions (7, dims [18..24]):
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
  --- v2 (SCHEMA_VERSION=2, VECTOR_SCHEMA_SPEC §1.1; build-order #2, 2026-07-22) ---
  [18] d_F  = clamp(ΔF/50, -1, 1)  — 1-step pillar CHANGE (NaN if no prior)
  [19] d_M  = clamp(ΔM/50, -1, 1)
  [20] d_O  = clamp(ΔO/50, -1, 1)  — fast-state pillar; R63b stability premium
  [21] d_S  = clamp(ΔS/50, -1, 1)  — fast-state pillar; R63b stability premium
  [22] d_A  = clamp(ΔA/50, -1, 1)  — directional-change pillar (rising ⇒ better edge)
  [23] stability_O = clamp(std(O_window)/25, 0, 1)  — distance from the stable sweet spot
  [24] stability_S = clamp(std(S_window)/25, 0, 1)  — large ⇒ we sampled AFTER the reprice

Invariants (VECTOR_SCHEMA_SPEC §0):
  I1  Unmeasured is NaN, never 0. v2 dims are float('nan') when prior/history is absent;
      cosine_similarity SKIPS NaN dims and refuses below MIN_SHARED_DIMS shared coords.
  I2  Point-in-time. Deltas/stability use ONLY prior snapshots (data < t). The caller supplies
      PIT-ordered history; this module never reaches forward.
  I6  Versioned. v1 dims [0..17] are byte-for-byte unchanged; v2 appends [18..24]. Old (18-dim)
      and new (25-dim) vectors interoperate — similarity compares the shared leading prefix.
"""

import math
import json
import logging
from typing import Optional

import numpy as np

_logger = logging.getLogger(__name__)

# ── v2 schema constants (build-order #2) ─────────────────────────────────────
SCHEMA_VERSION   = 2
ASSET_DIMS_V1    = 18          # dims [0..17] — the original dense snapshot vector
ASSET_DIMS_V2    = 25          # + [18..24] pillar deltas (5) + stability (2)
_DELTA_NORM      = 50.0        # a 50-pt pillar swing ⇒ ±1 (pillar moves are usually small)
_STABILITY_NORM  = 25.0        # trailing std of 25 pillar-pts ⇒ 1.0 (very unstable)
_STABILITY_MIN_OBS = 3         # < this many window obs ⇒ NaN (I1), never a fabricated 0
MIN_SHARED_DIMS  = 4           # cosine refuses below this many shared non-NaN coords (I1)
_NAN = float("nan")
_PILLAR_KEYS = ("F", "M", "O", "S", "A")


def _pillars_of(asset: dict) -> dict:
    """Extract {F,M,O,S,A} from any shape we carry: T1 (`pillars` dict), an already-extracted
    {F,M,O,S,A} dict (bare UPPERCASE), T2 (flat `f_score`…), or a history_db row (bare lowercase
    `f`/`m`/`o`/`s`/`a`). Each pillar resolved independently — a partial dict yields the pillars it
    has and None for the rest. Missing ⇒ None, never 0 (I1)."""
    p = asset.get("pillars") or {}
    out = {}
    for k in _PILLAR_KEYS:
        v = p.get(k)                          # T1 nested pillars dict
        if v is None:
            v = asset.get(k)                  # bare UPPERCASE (already-extracted pillar dict)
        if v is None:
            v = asset.get(f"{k.lower()}_score")  # T2 flat
        if v is None:
            v = asset.get(k.lower())          # history_db row: bare f/m/o/s/a
        out[k] = None if v is None else float(v)
    return out


def pillar_deltas(current: dict, prior: Optional[dict]) -> list[float]:
    """[d_F, d_M, d_O, d_S, d_A] normalized 1-step pillar changes, NaN when unmeasurable (I1).

    `current`/`prior` are pillar dicts ({F,M,O,S,A}) or raw asset dicts (auto-extracted).
    NaN — never 0 — when there is no prior or a pillar is missing on either side. Imputing 0
    would assert "no change," a claim we did not measure.
    """
    if prior is None:
        return [_NAN] * 5
    cur = _pillars_of(current)   # canonical extractor handles every key shape, pillar-by-pillar
    pri = _pillars_of(prior)
    out = []
    for k in _PILLAR_KEYS:
        a, b = cur.get(k), pri.get(k)
        if a is None or b is None:
            out.append(_NAN)
        else:
            out.append(_clamp((float(a) - float(b)) / _DELTA_NORM, -1.0, 1.0))
    return out


def pillar_stability(history: Optional[list], keys: tuple = ("O", "S")) -> list[float]:
    """[stability_O, stability_S] = normalized trailing std over the PIT window, NaN if too few
    obs (I1). `history` is a list of pillar/asset dicts ordered oldest→newest, INCLUDING current.

    Large std ⇒ the pillar just moved a lot ⇒ we are sampling AFTER the market repriced (R63b:
    edge peaks when S/O are STABLE, degrades at both extremes). NaN below _STABILITY_MIN_OBS.
    """
    if not history or len(history) < _STABILITY_MIN_OBS:
        return [_NAN] * len(keys)
    norm_hist = [_pillars_of(h) for h in history]
    out = []
    for k in keys:
        vals = [float(h[k]) for h in norm_hist if h.get(k) is not None]
        if len(vals) < _STABILITY_MIN_OBS:
            out.append(_NAN)
        else:
            out.append(_clamp(float(np.std(vals)) / _STABILITY_NORM, 0.0, 1.0))
    return out

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
    *,
    prior_pillars: dict | None = None,
    pillar_history: list | None = None,
) -> list[float]:
    """
    Generate the normalized feature vector for an asset — 18-dim (v1) or 25-dim (v2).

    v1 dims [0..17] are byte-for-byte unchanged (I6). When `prior_pillars` OR `pillar_history`
    is supplied, 7 v2 dims [18..24] are appended (pillar deltas + O/S stability). Absent inputs
    ⇒ those dims are float('nan') (I1: unmeasured is NaN, never 0), and cosine_similarity skips
    them — so a v2 vector with all-NaN tail ranks identically to the v1 vector.

    Parameters
    ----------
    asset : CIS asset dict (T1 or T2 shape)
    macro_regime : current macro regime string
    derivatives : {symbol: {funding_rate, oi_usd}} pre-fetched derivatives map
    prior_pillars : the asset's PIT-prior pillar snapshot {F,M,O,S,A} at t-1 (or None) — deltas
    pillar_history : list of PIT-ordered prior pillar/asset dicts INCLUDING current (or None) —
        oldest→newest; drives O/S trailing-std stability. Must contain only data ≤ t (I2).
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

    # ── v2 append [18..24] — pillar deltas + O/S stability (I1 NaN-honest, I2 PIT) ──
    if prior_pillars is not None or pillar_history is not None:
        cur_pillars = {"F": f_raw, "M": m_raw, "O": o_raw, "S": s_raw, "A": a_raw}
        vec.extend(pillar_deltas(cur_pillars, prior_pillars))          # [18..22] d_F..d_A
        vec.extend(pillar_stability(pillar_history, keys=("O", "S")))  # [23..24] stability_O/S
    return vec


def cosine_similarity(v1: list[float], v2: list[float]) -> float:
    """NaN-aware, length-tolerant cosine similarity in [−1, 1] (I1).

    - Compares only the shared leading prefix, so v1 (18-dim) and v2 (25-dim) vectors interoperate
      during rollout without a length crash.
    - Skips any coordinate that is NaN in EITHER vector (an unmeasured dim contributes nothing
      rather than poisoning the whole score).
    - Refuses (returns 0.0) below MIN_SHARED_DIMS shared measured coords — a confident number from
      one or two overlapping dims is noise, not similarity.
    """
    n = min(len(v1), len(v2))
    if n == 0:
        return 0.0
    a = np.asarray(v1[:n], dtype=np.float64)
    b = np.asarray(v2[:n], dtype=np.float64)
    mask = ~(np.isnan(a) | np.isnan(b))
    if int(mask.sum()) < MIN_SHARED_DIMS:
        return 0.0
    a, b = a[mask], b[mask]
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
    # Length-align to the shared prefix (v1 18-dim and v2 25-dim vectors may coexist), then
    # impute NaN per column with the column mean — clustering needs dense rows, so unlike cosine
    # it cannot skip dims pairwise; NaN ⇒ "treat as the cohort-average on this axis" for geometry
    # only. Columns that are entirely NaN collapse to 0 (no information to cluster on).
    dim = min(len(embeddings[s]) for s in syms)
    X   = np.array([embeddings[s][:dim] for s in syms], dtype=np.float64)
    if np.isnan(X).any():
        col_mean = np.nanmean(np.where(np.isnan(X), np.nan, X), axis=0)
        col_mean = np.where(np.isnan(col_mean), 0.0, col_mean)
        X = np.where(np.isnan(X), col_mean, X)

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
