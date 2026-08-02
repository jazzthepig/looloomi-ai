"""
Influence propagation — the diffusion-wavefront layer over the embedding field (Seth, 2026-07-23).
====================================================================================================

The frontier the kernel keeps pointing at (`ARCHITECTURE.md` §Kernel, §Vectors & movement): markets and
CIS are DOWNSTREAM REFLECTIONS; the cause is the marginal decision of an influential entity, PROPAGATING
through a field into asset quality and price. Stated as mechanics, not nouns:

    "Influence is a vector, not a label. Propagation is a wavefront with velocity and lag. beta+ is a
     TEMPORAL vector — standing upstream in time, closer to the source before the wavefront arrives at
     price. CIS/momentum are the wave AFTER it has passed — reflections with a lag. THE EDGE IS THE LAG."
    "Price is the integral of marginal flows over the diffusion field."

This module makes that field concrete. The embedding similarity graph (the same space now on pgvector) IS
the diffusion field — similar assets are *near* in propagation-space, so a decision/signal at one node
radiates to its neighbours along the edges. We formalize the wavefront as **graph label-diffusion**
(personalized-PageRank), and read the edge as the LAG:

    p = (1 − α)·s + α·W·p     — diffuse source signal s over row-normalized similarity operator W
    entanglement_delta = p − s  — how much the FIELD (neighbours) implies about a node beyond its own
                                  reflection. Positive ⇒ the wavefront has reached the neighbourhood but
                                  the node's own CIS/price has NOT yet caught up ⇒ the node is UPSTREAM in
                                  time ⇒ beta+ candidate.

"Be water" = the field is in motion and formless (大象无形); the operator W reshapes every cycle as
embeddings update — no frozen factor. "Be quantum" = a node's state is not its local scalar but a
superposition over the whole field (non-local); propagation is entanglement, not a point estimate.

Rigour, not mysticism: label-diffusion / PPR is a standard convergent linear operator, and the claim was
put through the loop immediately (S-81). Two hard findings, both sharpening the thesis:

  1. **Diffusing the LEVEL is refuted.** `entanglement_delta` of the CIS level has cross-sectional
     fwd-return IC **−0.16** (24% of days positive) vs the raw score's +0.13 — because propagating a
     *reflection* (level) just re-derives inverse-level: a low-score node beside high-score neighbours has
     a big positive delta, and low score underperforms. Level-diffusion cannot see the lag. ⇒ the source
     signal MUST be the **change / flow / decision** (the cause moving), NOT the level.
  2. **Diffusing the CHANGE is untestable on the proxy history.** In `cis_historical_11yr.csv` the score's
     daily change is *reconstructed from* the return (momentum proxy), so Δscore ≡ fwd_ret by construction
     (own-Δscore→fwd IC = 0.9999, a leak). The frontier's correct form — does a neighbour's Δ (the cause)
     LEAD a node's forward change before its own reflection updates — needs REAL CIS history where Δscore
     is not mechanically the return (§DATA-ALIGN). Third independent confirmation that proxy/bear data
     cannot validate the deep signals.

So: the PRIMITIVE is built + design-correct; the naive level form is refuted; the correct change/flow form
is the open frontier, gated on real multi-cycle CIS. NOT claimed as alpha (anti-imposter). Source signals to
try when the data lands: Δpillar, marginal-flow (D1), attention-diffusion (D4), holder-concentration Δ.

Pure numpy; operates on an embeddings dict via the NaN-aware cosine. Compliance: internal research.
"""
from __future__ import annotations

import numpy as np

from .embedder import cosine_similarity


def build_similarity_graph(embeddings: dict[str, list], k: int = 5,
                           min_sim: float = 0.10) -> dict[str, list[tuple[str, float]]]:
    """k-NN similarity graph — the diffusion field. {node: [(neighbour, weight), …]} top-k by NaN-aware
    cosine, keeping only edges ≥ min_sim (a weak tie is not a channel). Directed per-node top-k; weights
    are the raw cosine (the coupling strength of the propagation edge)."""
    syms = list(embeddings.keys())
    graph: dict[str, list[tuple[str, float]]] = {}
    for i in syms:
        vi = embeddings[i]
        sims = []
        for j in syms:
            if j == i:
                continue
            s = cosine_similarity(vi, embeddings[j])
            if s >= min_sim:
                sims.append((j, float(s)))
        sims.sort(key=lambda t: -t[1])
        graph[i] = sims[:k]
    return graph


def propagate(graph: dict[str, list[tuple[str, float]]], source: dict[str, float],
              alpha: float = 0.5, steps: int = 30, tol: float = 1e-6) -> dict[str, float]:
    """Diffuse `source` over the graph: p = (1−α)·s + α·W·p, W = row-normalized edge weights.

    α = 0 → p == s (pure local reflection, no propagation). α → 1 → full neighbour consensus (the field
    dominates). Iterates to convergence (‖Δp‖∞ < tol) or `steps`. Nodes absent from `source` seed 0.
    This is personalized-PageRank / label-propagation — a convergent linear operator, not a heuristic.
    """
    nodes = list(graph.keys())
    idx = {n: t for t, n in enumerate(nodes)}
    n = len(nodes)
    s = np.array([float(source.get(nd, 0.0) or 0.0) for nd in nodes], dtype=np.float64)
    # row-normalized transition matrix over the (sparse) k-NN edges
    W = np.zeros((n, n), dtype=np.float64)
    for i, nd in enumerate(nodes):
        nbrs = graph.get(nd, [])
        tot = sum(w for _, w in nbrs)
        if tot <= 0:
            continue
        for j_name, w in nbrs:
            if j_name in idx:
                W[i, idx[j_name]] = w / tot
    p = s.copy()
    a = max(0.0, min(1.0, alpha))
    for _ in range(max(1, steps)):
        p_new = (1.0 - a) * s + a * (W @ p)
        if np.max(np.abs(p_new - p)) < tol:
            p = p_new
            break
        p = p_new
    return {nd: float(p[i]) for i, nd in enumerate(nodes)}


def entanglement_delta(propagated: dict[str, float], source: dict[str, float]) -> dict[str, float]:
    """`p − s` per node — the LAG signal. Positive ⇒ the field/neighbourhood has moved beyond the node's
    own reflection (wavefront arriving, node upstream in time ⇒ beta+); negative ⇒ the node leads its field."""
    out = {}
    for nd, p in propagated.items():
        s = source.get(nd)
        if s is None or (isinstance(s, float) and s != s):
            continue
        out[nd] = float(p) - float(s)
    return out


def wavefront_rank(embeddings: dict[str, list], source: dict[str, float], *, k: int = 5,
                   alpha: float = 0.5, min_sim: float = 0.10) -> list[dict]:
    """One-call: build the field, diffuse the source, rank nodes by entanglement_delta (the beta+ read).
    Returns [{symbol, source, propagated, delta}] sorted by delta desc — the assets the field implies are
    about to catch up (top) vs those already ahead of their field (bottom)."""
    g = build_similarity_graph(embeddings, k=k, min_sim=min_sim)
    p = propagate(g, source, alpha=alpha)
    d = entanglement_delta(p, source)
    rows = [{"symbol": nd, "source": round(float(source.get(nd, float("nan"))), 3),
             "propagated": round(p.get(nd, float("nan")), 3), "delta": round(dv, 3)}
            for nd, dv in d.items()]
    return sorted(rows, key=lambda r: -r["delta"])
