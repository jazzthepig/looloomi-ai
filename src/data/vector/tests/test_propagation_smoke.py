"""
Smoke tests — influence-propagation / diffusion-wavefront primitive. Sandbox-safe, pure.
Run: python3 -m src.data.vector.tests.test_propagation_smoke

Verifies the mechanic the ARCHITECTURE frontier rests on: a signal at a hub radiates to its neighbours
(the wavefront), and `entanglement_delta = propagated − source` reads the LAG — positive where the field
has moved ahead of a node's own reflection (beta+ upstream), negative where the node leads its field.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")))

from src.data.vector.propagation import (  # noqa: E402
    build_similarity_graph, propagate, entanglement_delta, wavefront_rank,
)

# Hub A carries the signal; B/C/D are its low-signal neighbours (a star graph).
STAR = {"A": [("B", 1.0), ("C", 1.0), ("D", 1.0)], "B": [("A", 1.0)], "C": [("A", 1.0)], "D": [("A", 1.0)]}
SRC = {"A": 1.0, "B": 0.0, "C": 0.0, "D": 0.0}


def test_alpha_zero_is_pure_local():
    """α=0 ⇒ no propagation, p == s (the classical local reflection)."""
    p = propagate(STAR, SRC, alpha=0.0)
    assert all(abs(p[n] - SRC[n]) < 1e-9 for n in SRC)


def test_wavefront_lifts_neighbours_drags_hub():
    """The signal diffuses: neighbours rise toward the hub, the hub is dragged toward its (0) field."""
    p = propagate(STAR, SRC, alpha=0.5)
    assert p["A"] < 1.0, "hub dragged down by 0-signal neighbours"
    assert p["B"] > 0.0 and abs(p["B"] - p["C"]) < 1e-9, "neighbours lifted symmetrically"
    # closed-form check: p_A = 0.667, p_B = 0.333
    assert abs(p["A"] - 0.6667) < 1e-3 and abs(p["B"] - 0.3333) < 1e-3


def test_entanglement_delta_reads_the_lag():
    """delta>0 = field ahead of the node (wavefront arriving, beta+); delta<0 = node leads its field."""
    p = propagate(STAR, SRC, alpha=0.5)
    d = entanglement_delta(p, SRC)
    assert d["B"] > 0 and d["C"] > 0 and d["D"] > 0, "neighbours are upstream of arriving wavefront"
    assert d["A"] < 0, "hub already ahead of its field"


def test_entanglement_delta_skips_nan_source():
    p = {"A": 0.5, "B": 0.3}
    d = entanglement_delta(p, {"A": 0.2, "B": float("nan")})
    assert "A" in d and "B" not in d, "NaN source ⇒ no delta (I1)"


def test_build_graph_topk_and_threshold():
    # A ~ B (identical), A ~ C (identical), A far from D (orthogonal-ish)
    emb = {"A": [1.0, 0.0, 0.0, 0.0, 0.0, 0.0],
           "B": [0.99, 0.01, 0.0, 0.0, 0.0, 0.0],
           "C": [0.98, 0.0, 0.02, 0.0, 0.0, 0.0],
           "D": [0.0, 0.0, 0.0, 1.0, 0.0, 0.0]}
    g = build_similarity_graph(emb, k=2, min_sim=0.5)
    a_nbrs = [n for n, _ in g["A"]]
    assert "B" in a_nbrs and "C" in a_nbrs and "D" not in a_nbrs, "top-k by sim, weak ties dropped"


def test_wavefront_rank_end_to_end():
    emb = {"A": [1.0, 0, 0, 0], "B": [0.99, 0.01, 0, 0], "C": [0.98, 0, 0.02, 0], "D": [0.97, 0, 0, 0.03]}
    rank = wavefront_rank(emb, {"A": 1.0, "B": 0.0, "C": 0.0, "D": 0.0}, k=3, alpha=0.5)
    top = rank[0]
    assert top["symbol"] in ("B", "C", "D") and top["delta"] > 0, "field lifts the low-signal neighbours"


TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_")]

if __name__ == "__main__":
    p = 0
    for t in TESTS:
        t(); print(f"  ✓ {t.__name__}"); p += 1
    print(f"\n✅ {p}/{len(TESTS)} propagation smoke tests passed")
